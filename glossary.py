import re

# Glosario de terminos tecnicos y nombres propios comunes en charlas de
# conferencias de tecnologia. La clave es como suele aparecer mal
# transcripto/capitalizado, el valor es la forma correcta. Se aplica sin
# distinguir mayusculas/minusculas, respetando limites de palabra.
GLOSSARY: dict[str, str] = {
    "ia": "IA",
    "inteligencia artificial": "inteligencia artificial",
    "nerdearla": "Nerdearla",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "python": "Python",
    "github": "GitHub",
    "gitlab": "GitLab",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "websocket": "WebSocket",
    "websockets": "WebSockets",
    "api": "API",
    "json": "JSON",
    "sql": "SQL",
    "html": "HTML",
    "css": "CSS",
    "fastapi": "FastAPI",
    "sqlite": "SQLite",
    "gemini": "Gemini",
    "google": "Google",
    "openai": "OpenAI",
    "chatgpt": "ChatGPT",
    "linux": "Linux",
    "windows": "Windows",
    "macos": "macOS",
    "ios": "iOS",
    "android": "Android",
    "wifi": "WiFi",
    "backend": "backend",
    "frontend": "frontend",
    "opensource": "open source",
    "devops": "DevOps",
}

_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in GLOSSARY) + r")\b",
    re.IGNORECASE,
)


def apply_glossary(text: str) -> str:
    if not text:
        return text

    def _replace(match: re.Match) -> str:
        return GLOSSARY[match.group(0).lower()]

    return _PATTERN.sub(_replace, text)
