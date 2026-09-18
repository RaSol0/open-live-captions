# [Nombre del proyecto]

> [Una línea: transcripción y traducción simultánea en vivo, open source, para conferencias multi-sesión.]

Construido para la [Nerdearla Vibeathon 2026](https://nerdearla26.devpost.com/) — transcripción y traducción en tiempo real de charlas en inglés, pensada para correr múltiples sesiones en simultáneo sin depender de operación manual ni herramientas comerciales.

## Demo

- Video demo: [link a YouTube]
- [Screenshot o GIF de la vista de audiencia]

## Qué hace

- Transcribe audio en vivo (inglés) y lo traduce a español en tiempo real.
- Corre múltiples sesiones ("escenarios") en simultáneo, cada una aislada.
- Vista de audiencia web: elegís sesión + idioma y ves los subtítulos en vivo.
- Exporta la transcripción completa al cerrar cada sesión (SRT / VTT / texto).
- Panel de monitoreo: estado, latencia y errores por sesión.

## Arquitectura

[Pegar acá el diagrama/resumen del brief técnico: ingest → worker por sesión → backend WS/API → frontend]

## Requisitos

- Python 3.x
- Una API key de Gemini ([cómo conseguirla](https://aistudio.google.com/))

## Instalación

```bash
git clone [url del repo]
cd [nombre]
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # completar GEMINI_API_KEY
```

## Uso

```bash
python run.py
```

Abrir `http://localhost:8000` para la vista de audiencia, `http://localhost:8000/admin` para el panel de monitoreo.

### Probar con audio de ejemplo

El repo incluye audios de prueba en `sample_audio/` (extraídos de charlas anteriores de Nerdearla). Para simular una sesión:

```bash
python run.py --session demo1 --source sample_audio/charla1.mp3
```

### Correr varias sesiones en simultáneo

[Explicar cómo levantar 2+ sesiones — ejemplo de comando o instrucciones]

## Cómo escalar a más sesiones

Cada sesión es un worker aislado sin estado compartido — escalar es levantar más workers/procesos. [Pegar acá el resultado del load test sintético: cuántas sesiones simuladas, latencia observada, cómo desplegarían esto en producción para 10-30 sesiones.]

## Exportar transcripciones

```bash
curl http://localhost:8000/export/demo1?format=srt > demo1.srt
```

Formatos soportados: `srt`, `vtt`, `txt`.

## Licencia

Apache License 2.0 — ver [LICENSE](LICENSE).

## Roadmap / no incluido en esta versión

- Integración con OBS/vMix para quemar subtítulos en el stream.
- Modo 100% local con Gemma (sin dependencia de API externa).
- Glosario mantenible de términos técnicos y nombres propios.
- Idiomas adicionales de entrada/salida (ej. portugués) — la arquitectura ya trata el idioma como parámetro de configuración, así que agregar uno nuevo no debería requerir cambios de código.

---

Construido en la Nerdearla Vibeathon 2026 por [tu nombre].
