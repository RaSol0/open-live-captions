# Open Live Captions

> Transcripción y traducción simultánea en vivo, open source, para conferencias multi-sesión.

Construido en la [Nerdearla Vibeathon 2026](https://nerdearla26.devpost.com/) — transcripción y traducción en tiempo real de charlas, pensada para correr múltiples sesiones en simultáneo sin depender de operación manual ni herramientas comerciales.

## Qué hace

- Transcribe audio en vivo y lo traduce en tiempo real (probado en inglés, español y portugués).
- Recibe audio de un archivo de prueba **o de un micrófono real** capturado desde el navegador (`/broadcast`) — audio genuinamente en vivo, sin archivos pregrabados.
- Corre múltiples sesiones ("escenarios") en simultáneo, cada una aislada — probado con 10 sesiones concurrentes sin degradación.
- Vista de audiencia web: elegís escenario e idioma y ves los subtítulos en vivo, estilo closed captions, con animación tipo máquina de escribir.
- Corrige automáticamente términos técnicos y nombres propios mal transcriptos (glosario en `glossary.py`), sin agregar latencia.
- Panel de monitoreo en `/admin`: estado, clientes conectados y última actualización por sesión.
- Exporta la transcripción completa (SRT / VTT / texto).
- Sincroniza pausa/reanudar/rebobinar del video con el pipeline de traducción en tiempo real.

## Arquitectura

```
[Audio (archivo o stream)] -> [Session: conexion aislada a Gemini Live API]
                                    |
                                    v
                          [CaptionBuffer: acumula fragmentos,
                           corta por silencio o largo maximo]
                                    |
                        +-----------+-----------+
                        v                       v
                [WebSocket -> Frontend]   [SQLite -> Export]
```

Cada sesión (`Session` en `server.py`) es una conexión WebSocket independiente a la Gemini Live API, sin estado compartido con otras sesiones — por eso escalar a más escenarios es simplemente abrir más conexiones, no cambiar la arquitectura. El idioma destino también es un parámetro de la sesión (no está hardcodeado), así que agregar un idioma nuevo es una línea de configuración, no código nuevo.

## Requisitos

- Python 3.11+
- Una API key de Gemini ([conseguirla en Google AI Studio](https://aistudio.google.com/))
- Acceso al modelo `gemini-3.5-live-translate-preview` (Live API, en preview a la fecha de este proyecto)

## Instalación

```bash
git clone https://github.com/RaSol0/open-live-captions.git
cd open-live-captions
python -m venv venv
source venv/Scripts/activate  # Windows (Git Bash). En cmd/PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env  # completar GEMINI_API_KEY
```

## Uso

```bash
python -m uvicorn server:app --port 8000
```

- Vista de audiencia: `http://localhost:8000/`
- Panel de monitoreo: `http://localhost:8000/admin`

### Probar con audio de ejemplo

Este repo **no incluye archivos de audio** de terceros (evitamos publicar clips bajados de YouTube u otras fuentes con derechos de autor de otra gente). Para probarlo:

1. Conseguí un clip corto (15-30s) en formato `.wav`, mono, 16kHz — tuyo, grabado por vos, o de una fuente con licencia libre (ej. audio propio, Creative Commons).
2. Convertilo si hace falta con ffmpeg: `ffmpeg -i tu_audio.mp4 -t 25 -ar 16000 -ac 1 -c:a pcm_s16le sample_audio/mi_clip.wav`
3. Agregá la entrada correspondiente en `SAMPLE_AUDIO` dentro de `server.py`, o pasale la ruta directo a `live_pipeline.py <ruta>` para un test rápido por consola.

La carpeta `sample_audio/` está en `.gitignore` a propósito — cada quien pone sus propios clips de prueba localmente.

### Correr varias sesiones en simultáneo

Cada combinación de escenario + idioma es una sesión aislada. Para probarlo, abrí dos pestañas del navegador en `http://localhost:8000/` y elegí escenarios distintos en cada una — cada pestaña dispara su propia conexión a la Live API, sin interferencia entre ellas. Confirmado con `load_test.py` corriendo 10 sesiones simultáneas sin errores:

```bash
python load_test.py 10
```

## Cómo escalar a más sesiones

Cada sesión es un worker aislado sin estado compartido — escalar es levantar más conexiones, no cambiar arquitectura. Resultado real del load test con 10 sesiones simultáneas (audio de prueba en loop, ventana de medición de 30s):

- 10/10 sesiones exitosas, sin errores de cuota ni caídas.
- Latencia al primer mensaje: ~2.2s promedio (min 2.08s, max 2.50s).
- ~62 mensajes de subtítulos por sesión en 30 segundos de audio, de forma sostenida.

Con menos concurrencia (3 sesiones) la latencia inicial fue similar en órdenes de magnitud (~9-15s en corridas con menor "warm-up" de la conexión), lo que sugiere que la mayor parte del costo es el arranque de cada conexión individual a la Live API, no la cantidad de sesiones en sí — consistente con que cada sesión es un worker totalmente aislado.

Para producción a 10-30 escenarios: cada sesión ya es independiente, así que el límite real es la cuota de la API de Gemini (revisar en Google Cloud Console → APIs & Services → Quotas) y el ancho de banda del servidor, no la arquitectura del código.

## Exportar transcripciones

```bash
curl "http://localhost:8000/sessions/demo-en/export?format=srt&kind=translated_es" > demo-en.srt
```

Formatos soportados: `srt`, `vtt`, `txt`. `kind` puede ser `original` o `translated_<codigo_idioma>` (ej. `translated_es`, `translated_en`).

## Licencia

Apache License 2.0 — ver [LICENSE](LICENSE).

## Roadmap / no incluido en esta versión

- Integración con OBS/vMix para quemar subtítulos en el stream.
- Modo 100% local con Gemma (sin dependencia de API externa).
- Video en vivo de la cámara visible en la vista de audiencia (requeriria WebRTC para hacerlo bien).
- Modo de escucha con audio traducido (el modelo ya genera audio internamente; hoy solo extraemos el texto transcripto).
- Más idiomas probados end-to-end (probamos inglés, español y portugués; la arquitectura soporta cualquier idioma que soporte la Live API sin cambios de código).

---

Construido en la Nerdearla Vibeathon 2026.
