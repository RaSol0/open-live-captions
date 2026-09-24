import asyncio
import os
import sys
import wave

from dotenv import load_dotenv
from google import genai
from google.genai import types

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

MODEL = "gemini-3.5-live-translate-preview"
API_KEY = os.environ.get("GEMINI_API_KEY")
CHUNK_BYTES = 3200  # ~0.1s of 16kHz 16-bit mono audio

CONFIG = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
    translation_config=types.TranslationConfig(
        target_language_code="es",
        echo_target_language=False,
    ),
)


async def stream_file(session, path):
    with wave.open(path, "rb") as wf:
        if wf.getframerate() != 16000 or wf.getnchannels() != 1:
            raise ValueError("El audio debe ser mono a 16kHz")
        data = wf.readframes(wf.getnframes())

    for i in range(0, len(data), CHUNK_BYTES):
        chunk = data[i : i + CHUNK_BYTES]
        await session.send_realtime_input(
            audio={"data": chunk, "mime_type": "audio/pcm;rate=16000"}
        )
        await asyncio.sleep(CHUNK_BYTES / 2 / 16000)


SILENCE_FLUSH_SECONDS = 1.2
MAX_LINE_CHARS = 160


class CaptionBuffer:
    """Acumula fragmentos de streaming en lineas de subtitulo legibles.

    La Live API no manda una senal explicita de "fin de frase", asi que
    cortamos la linea por silencio (sin fragmentos nuevos por un rato) o
    por largo maximo, que es el enfoque estandar en sistemas de captions.
    """

    def __init__(self, label):
        self.label = label
        self.text = ""
        self.last_update = None

    def add(self, fragment):
        now = asyncio.get_event_loop().time()
        if self.last_update is not None and (now - self.last_update) > SILENCE_FLUSH_SECONDS:
            self.flush()
        self.text += fragment
        self.last_update = now
        print(f"\r[{self.label}] {self.text}" + " " * 10, end="", flush=True)
        if len(self.text) >= MAX_LINE_CHARS:
            self.flush()

    def flush(self):
        if self.text.strip():
            print(f"\r[{self.label}] {self.text}")
        self.text = ""
        self.last_update = None


async def receive(session):
    original_buf = CaptionBuffer("ORIGINAL ")
    translated_buf = CaptionBuffer("TRADUCIDO")
    async for response in session.receive():
        server_content = response.server_content
        if server_content is None:
            continue
        if server_content.input_transcription and server_content.input_transcription.text:
            original_buf.add(server_content.input_transcription.text)
        if server_content.output_transcription and server_content.output_transcription.text:
            translated_buf.add(server_content.output_transcription.text)


async def main():
    if not API_KEY:
        print("Falta GEMINI_API_KEY en .env (copia .env.example a .env y completa la key)")
        sys.exit(1)

    path = sys.argv[1] if len(sys.argv) > 1 else "sample_audio/midudev_clip.wav"
    client = genai.Client(api_key=API_KEY)

    async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:
        recv_task = asyncio.create_task(receive(session))
        await stream_file(session, path)
        await asyncio.sleep(4)
        recv_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
