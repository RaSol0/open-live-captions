def _format_ts(seconds: float, srt: bool) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    sep = "," if srt else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(segments: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = _format_ts(seg["start_ts"], srt=True)
        end = _format_ts(seg["end_ts"], srt=True)
        lines.append(f"{i}\n{start} --> {end}\n{seg['text']}\n")
    return "\n".join(lines)


def to_vtt(segments: list[dict]) -> str:
    lines = ["WEBVTT\n"]
    for seg in segments:
        start = _format_ts(seg["start_ts"], srt=False)
        end = _format_ts(seg["end_ts"], srt=False)
        lines.append(f"{start} --> {end}\n{seg['text']}\n")
    return "\n".join(lines)


def to_txt(segments: list[dict]) -> str:
    return "\n".join(seg["text"] for seg in segments)
