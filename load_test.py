"""Load test de escalabilidad: abre N sesiones en paralelo contra el
backend y mide latencia al primer mensaje y throughput por sesion.

Uso:
    python load_test.py 5
"""

import asyncio
import json
import sys
import time

import websockets

SERVER = "ws://localhost:8000/ws"
DURATION_SECONDS = 15


async def run_one(session_id: str, results: dict):
    start = time.monotonic()
    first_msg_at = None
    count = 0
    errors = None
    try:
        async with websockets.connect(f"{SERVER}/{session_id}") as ws:
            end_at = start + DURATION_SECONDS
            while time.monotonic() < end_at:
                remaining = end_at - time.monotonic()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                json.loads(raw)
                count += 1
                if first_msg_at is None:
                    first_msg_at = time.monotonic() - start
    except Exception as exc:  # noqa: BLE001
        errors = str(exc)

    results[session_id] = {
        "messages": count,
        "latency_to_first_msg": first_msg_at,
        "error": errors,
    }


async def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    session_ids = [f"load-test-{i}" for i in range(n)]
    results: dict = {}

    print(f"Lanzando {n} sesiones en paralelo por {DURATION_SECONDS}s...")
    t0 = time.monotonic()
    await asyncio.gather(*(run_one(sid, results) for sid in session_ids))
    elapsed = time.monotonic() - t0

    ok = [r for r in results.values() if r["error"] is None and r["messages"] > 0]
    failed = [sid for sid, r in results.items() if r["error"] or r["messages"] == 0]

    print(f"\n--- Resumen ({elapsed:.1f}s totales) ---")
    print(f"Sesiones exitosas: {len(ok)}/{n}")
    if ok:
        latencies = [r["latency_to_first_msg"] for r in ok]
        print(f"Latencia al primer mensaje: min={min(latencies):.2f}s avg={sum(latencies)/len(latencies):.2f}s max={max(latencies):.2f}s")
        msg_counts = [r["messages"] for r in ok]
        print(f"Mensajes por sesion: min={min(msg_counts)} avg={sum(msg_counts)/len(msg_counts):.1f} max={max(msg_counts)}")
    if failed:
        print(f"Sesiones con error: {failed}")
        for sid in failed:
            print(f"  {sid}: {results[sid]['error']}")


if __name__ == "__main__":
    asyncio.run(main())
