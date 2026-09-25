import asyncio
import json
import logging
import os
import wave

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("open-live-captions")

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from google import genai
from google.genai import types

import db
import export
from glossary import apply_glossary

load_dotenv()

MODEL = "gemini-3.5-live-translate-preview"
API_KEY = os.environ.get("GEMINI_API_KEY")
CHUNK_BYTES = 3200
SILENCE_FLUSH_SECONDS = 1.2
MAX_LINE_CHARS = 160
FIRST_RESPONSE_TIMEOUT = 15
MAX_CONNECT_ATTEMPTS = 3

SAMPLE_AUDIO = {
    "demo-en": "sample_audio/demo_en_clip.wav",
    "demo-es": "sample_audio/demo_es_clip.wav",
}

app = FastAPI()

if os.path.isdir("local_media"):
    app.mount("/media", StaticFiles(directory="local_media"), name="media")


class Session:
    """Una sesion aislada: su propia conexion a la Live API, sus propios
    clientes WS conectados. No comparte estado con otras sesiones, que es
    lo que permite escalar a mas sesiones simplemente creando mas instancias.
    """

    def __init__(self, session_id: str, audio_path: str | None, target_lang: str = "es", live: bool = False):
        self.session_id = session_id
        self.audio_path = audio_path
        self.target_lang = target_lang
        self.live = live
        self.live_queue: asyncio.Queue = asyncio.Queue()
        self.clients: set[WebSocket] = set()
        self.task: asyncio.Task | None = None
        self.buffers = {"original": "", "translated": ""}
        self.last_update = {"original": None, "translated": None}
        self.buffer_start = {"original": None, "translated": None}
        self.session_start = None
        self.paused = False
        self.gen = 0
        self.lock = asyncio.Lock()

    async def push_live_audio(self, chunk: bytes):
        await self.live_queue.put(chunk)

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
        text = apply_glossary(self.buffers[kind].strip())
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

    async def run(self, start_offset_seconds: float = 0.0):
        """Corre el pipeline sobre el audio de prueba y, al llegar al final,
        vuelve a arrancar desde el principio (loop) en vez de terminar.

        Esto simula una fuente en vivo genuina: un stream real nunca "se
        acaba", asi que un cliente que se conecta en cualquier momento
        siempre encuentra una sesion activa. Sin este loop, la sesion
        moria despues de una sola pasada y un cliente que llegaba tarde
        se quedaba escuchando un pipeline ya terminado, sin recibir nada.
        """
        my_gen = self.gen
        offset = start_offset_seconds
        while my_gen == self.gen:
            succeeded = False
            for attempt in range(1, MAX_CONNECT_ATTEMPTS + 1):
                if my_gen != self.gen:
                    return
                ok = await self._run_once(offset, my_gen, attempt)
                if ok:
                    succeeded = True
                    break
                if my_gen != self.gen:
                    return
                logger.warning(
                    "Session %s: intento %d/%d sin respuesta, reintentando",
                    self.session_id, attempt, MAX_CONNECT_ATTEMPTS,
                )
            if not succeeded:
                return
            offset = 0.0

    async def _run_once(self, start_offset_seconds: float, my_gen: int, attempt: int) -> bool:
        self.paused = False
        self.session_start = asyncio.get_event_loop().time() - start_offset_seconds
        client = genai.Client(api_key=API_KEY)
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            translation_config=types.TranslationConfig(
                target_language_code=self.target_lang, echo_target_language=True
            ),
        )

        if not self.live:
            with wave.open(self.audio_path, "rb") as wf:
                sample_rate = wf.getframerate()
                channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                data = wf.readframes(wf.getnframes())

            bytes_per_second = sample_rate * channels * sampwidth
            start_byte = int(start_offset_seconds * bytes_per_second)
            start_byte -= start_byte % (channels * sampwidth)
            data = data[start_byte:]

        first_response = asyncio.get_event_loop().create_future()

        try:
            async with client.aio.live.connect(model=MODEL, config=config) as live_session:

                async def send_from_file():
                    for i in range(0, len(data), CHUNK_BYTES):
                        if my_gen != self.gen:
                            return
                        while self.paused:
                            if my_gen != self.gen:
                                return
                            await asyncio.sleep(0.2)
                        await live_session.send_realtime_input(
                            audio={"data": data[i : i + CHUNK_BYTES], "mime_type": "audio/pcm;rate=16000"}
                        )
                        await asyncio.sleep(CHUNK_BYTES / 2 / 16000)

                async def send_from_live_queue():
                    while my_gen == self.gen:
                        try:
                            chunk = await asyncio.wait_for(self.live_queue.get(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        while self.paused:
                            if my_gen != self.gen:
                                return
                            await asyncio.sleep(0.2)
                        await live_session.send_realtime_input(
                            audio={"data": chunk, "mime_type": "audio/pcm;rate=16000"}
                        )

                send = send_from_live_queue if self.live else send_from_file

                async def receive():
                    async for response in live_session.receive():
                        if my_gen != self.gen:
                            return
                        if not first_response.done():
                            first_response.set_result(True)
                        sc = response.server_content
                        if sc is None:
                            continue
                        if sc.input_transcription and sc.input_transcription.text:
                            await self.add_fragment("original", sc.input_transcription.text)
                        if sc.output_transcription and sc.output_transcription.text:
                            await self.add_fragment("translated", sc.output_transcription.text)

                recv_task = asyncio.create_task(receive())
                send_task = asyncio.create_task(send())

                try:
                    await asyncio.wait_for(asyncio.shield(first_response), timeout=FIRST_RESPONSE_TIMEOUT)
                except asyncio.TimeoutError:
                    send_task.cancel()
                    recv_task.cancel()
                    return False

                await send_task
                await asyncio.sleep(4)
                recv_task.cancel()
                if my_gen == self.gen:
                    await self.flush("original")
                    await self.flush("translated")
                return True
        except Exception:
            logger.exception(
                "Session %s: error de conexion en intento %d", self.session_id, attempt
            )
            return False

    def set_paused(self, paused: bool):
        self.paused = paused

    async def restart(self, offset_seconds: float):
        async with self.lock:
            self.gen += 1
            if self.task and not self.task.done():
                self.task.cancel()
            for kind in ("original", "translated"):
                self.buffers[kind] = ""
                self.last_update[kind] = None
                self.buffer_start[kind] = None
            self.task = spawn_run(self, start_offset_seconds=offset_seconds)


sessions: dict[str, Session] = {}


def _log_task_result(task: asyncio.Task):
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("Session task failed", exc_info=exc)


def spawn_run(session: "Session", start_offset_seconds: float = 0.0) -> asyncio.Task:
    task = asyncio.create_task(session.run(start_offset_seconds=start_offset_seconds))
    task.add_done_callback(_log_task_result)
    return task


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
        if session_id in SAMPLE_AUDIO:
            session = Session(session_id, SAMPLE_AUDIO[session_id], target_lang=target_lang)
        elif session_id.startswith("live"):
            # Sesiones "live*" esperan audio real por /ws-ingest, no caen
            # a un video de prueba por defecto (eso confundia "live-mic"
            # con una demo la primera vez que lo armamos).
            session = Session(session_id, audio_path=None, target_lang=target_lang, live=True)
        else:
            # Cualquier otro id desconocido (ej. los del load test) se
            # trata como demo generica, asi cada uno dispara su propio
            # pipeline aislado contra el mismo audio de prueba.
            session = Session(session_id, "sample_audio/demo_en_clip.wav", target_lang=target_lang)
        sessions[key] = session
    session.clients.add(websocket)

    if not session.live and len(session.clients) == 1:
        # Primer/unico viewer conectandose a esta sesion: el video del
        # cliente siempre arranca en el segundo 0, asi que resincronizamos
        # el pipeline al mismo punto en vez de dejarlo donde iba su loop
        # interno (que puede llevar varios ciclos de ventaja si la sesion
        # ya venia corriendo de antes).
        await session.restart(0.0)
    else:
        async with session.lock:
            if session.task is None or session.task.done():
                session.task = spawn_run(session)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            action = msg.get("action")
            if action == "pause":
                session.set_paused(True)
            elif action == "resume":
                session.set_paused(False)
            elif action == "seek":
                await session.restart(float(msg.get("position", 0)))
    except WebSocketDisconnect:
        session.clients.discard(websocket)


@app.websocket("/ws-ingest/{session_id}/{target_lang}")
async def ws_ingest(websocket: WebSocket, session_id: str, target_lang: str):
    """Endpoint para transmitir audio en vivo desde el navegador (microfono
    capturado con getUserMedia) hacia el pipeline. El cliente manda frames
    binarios PCM16 mono 16kHz; este endpoint no devuelve captions, para eso
    el mismo cliente (u otros) se conectan a /ws/{session_id}/{target_lang}.
    """
    await websocket.accept()
    key = f"{session_id}:{target_lang}"
    session = sessions.get(key)
    if session is None:
        session = Session(session_id, audio_path=None, target_lang=target_lang, live=True)
        sessions[key] = session

    async with session.lock:
        if session.task is None or session.task.done():
            session.task = spawn_run(session)

    try:
        while True:
            data = await websocket.receive_bytes()
            await session.push_live_audio(data)
    except WebSocketDisconnect:
        pass


@app.get("/")
async def root():
    return FileResponse("static/audience.html")


@app.get("/admin")
async def admin():
    return FileResponse("static/admin.html")


@app.get("/broadcast")
async def broadcast():
    return FileResponse("static/broadcast.html")


@app.get("/health")
async def health():
    return {"status": "ok", "active_sessions": list(sessions.keys())}
