import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "captions.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            start_ts REAL NOT NULL,
            end_ts REAL NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def insert_segment(session_id: str, kind: str, text: str, start_ts: float, end_ts: float):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO segments (session_id, kind, text, start_ts, end_ts) VALUES (?, ?, ?, ?, ?)",
        (session_id, kind, text, start_ts, end_ts),
    )
    conn.commit()
    conn.close()


def get_segments(session_id: str, kind: str | None = None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if kind:
        rows = conn.execute(
            "SELECT * FROM segments WHERE session_id = ? AND kind = ? ORDER BY start_ts",
            (session_id, kind),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM segments WHERE session_id = ? ORDER BY start_ts",
            (session_id,),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
