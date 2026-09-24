import asyncio
import os
import wave

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse

from google import genai
from google.genai import types

import db
import export

load_dotenv()

MODEL = "gemini-3.5-live-translate-preview"
API_KEY = os.environ.get("GEMINI_API_KEY")
CHUNK_BYTES = 3200
SILENCE_FLUSH_SECONDS = 1.2
MAX_LINE_CHARS = 160

SAMPLE_AUDIO = {
    "demo-en": "sample_audio/en_test_clip.wav",
    "demo-es": "sample_audio/midudev_clip.wav",
}

app = FastAPI()


class Session:
    """Una sesion aislada: su propia conexion a la Live API, sus propios
    clientes WS conectados. No comparte estado con otras sesiones, que es
    lo que permite escalar a mas sesiones simplemente creando mas instancias.
    """

    def __init__(self, session_id: str, audio_path: str, target_lang: str = "es"):
        self.session_id = session_id
        self.audio_path = audio_path
        self.target_lang = target_lang
        self.clients: set[WebSocket] = set()
        self.task: asyncio.Task | None = None
        self.buffers = {"original": "", "translated": ""}
        self.last_update = {"original": None, "translated": None}
        self.buffer_start = {"original": None, "translated": None}
        self.session_start = None

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def add_fragment(self, kind: str, fragment: str):
        now = asyncio.get_event_loop().time()
        last = self.last_update[kind]
        if last is not None and (now - last) > SILENCE_FLUSH_SECONDS:
            await self.flush(kind)
        if not self.buffers[kind]:
            self.buffer_start[kind] = now
        self.buffers[kind] += fragment
        self.last_update[kind] = now
        await self.broadcast(
            {"session": self.session_id, "kind": kind, "text": self.buffers[kind], "final": False}
        )
        if len(self.buffers[kind]) >= MAX_LINE_CHARS:
            await self.flush(kind)

    async def flush(self, kind: str):
        text = self.buffers[kind].strip()
        if text:
            await self.broadcast(
                {"session": self.session_id, "kind": kind, "text": text, "final": True}
            )
            start_ts = (self.buffer_start[kind] or self.last_update[kind]) - self.session_start
            end_ts = self.last_update[kind] - self.session_start
            db_kind = kind if kind == "original" else f"translated_{self.target_lang}"
            await asyncio.to_thread(
                db.insert_segment, self.session_id, db_kind, text, start_ts, end_ts
            )
        self.buffers[kind] = ""
        self.last_update[kind] = None
        self.buffer_start[kind] = None

    async def run(self):
        self.session_start = asyncio.get_event_loop().time()
        client = genai.Client(api_key=API_KEY)
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            translation_config=types.TranslationConfig(
                target_language_code=self.target_lang, echo_target_language=False
            ),
        )

        with wave.open(self.audio_path, "rb") as wf:
            data = wf.readframes(wf.getnframes())

        async with client.aio.live.connect(model=MODEL, config=config) as live_session:

            async def send():
                for i in range(0, len(data), CHUNK_BYTES):
                    await live_session.send_realtime_input(
                        audio={"data": data[i : i + CHUNK_BYTES], "mime_type": "audio/pcm;rate=16000"}
                    )
                    await asyncio.sleep(CHUNK_BYTES / 2 / 16000)

            async def receive():
                async for response in live_session.receive():
                    sc = response.server_content
                    if sc is None:
                        continue
                    if sc.input_transcription and sc.input_transcription.text:
                        await self.add_fragment("original", sc.input_transcription.text)
                    if sc.output_transcription and sc.output_transcription.text:
                        await self.add_fragment("translated", sc.output_transcription.text)

            recv_task = asyncio.create_task(receive())
            await send()
            await asyncio.sleep(4)
            recv_task.cancel()
            await self.flush("original")
            await self.flush("translated")


sessions: dict[str, Session] = {}


@app.on_event("startup")
async def startup():
    db.init_db()


@app.get("/sessions/{session_id}/segments")
async def get_segments(session_id: str, kind: str | None = None):
    return db.get_segments(session_id, kind)


EXPORTERS = {"srt": export.to_srt, "vtt": export.to_vtt, "txt": export.to_txt}


@app.get("/sessions/{session_id}/export")
async def export_session(session_id: str, format: str = "srt", kind: str = "translated_es"):
    if format not in EXPORTERS:
        return PlainTextResponse(f"Formato invalido: {format}. Usar srt, vtt o txt.", status_code=400)
    segments = db.get_segments(session_id, kind)
    content = EXPORTERS[format](segments)
    return PlainTextResponse(content, media_type="text/plain")


@app.get("/status")
async def status():
    result = []
    for session_id, session in sessions.items():
        result.append(
            {
                "session_id": session_id,
                "clients": len(session.clients),
                "running": bool(session.task and not session.task.done()),
                "last_update": {
                    k: v for k, v in session.last_update.items() if v is not None
                },
            }
        )
    return {"sessions": result}


@app.websocket("/ws/{session_id}/{target_lang}")
async def ws_endpoint(websocket: WebSocket, session_id: str, target_lang: str):
    await websocket.accept()
    key = f"{session_id}:{target_lang}"
    session = sessions.get(key)
    if session is None:
        audio_path = SAMPLE_AUDIO.get(session_id, "sample_audio/en_test_clip.wav")
        session = Session(session_id, audio_path, target_lang=target_lang)
        sessions[key] = session
    session.clients.add(websocket)

    if session.task is None or session.task.done():
        session.task = asyncio.create_task(session.run())

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        session.clients.discard(websocket)


@app.get("/")
async def root():
    return FileResponse("static/audience.html")


@app.get("/admin")
async def admin():
    return FileResponse("static/admin.html")


@app.get("/health")
async def health():
    return {"status": "ok", "active_sessions": list(sessions.keys())}
