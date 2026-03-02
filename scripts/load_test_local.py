#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

from botmusica.music.player import MusicService


SEARCH_QUERIES = [
    "linkin park numb",
    "daft punk one more time",
    "alan walker faded",
    "coldplay viva la vida",
    "imagine dragons believer",
]


async def run_load(concurrency: int, iterations: int) -> int:
    service = MusicService()
    latencies_ms: list[float] = []
    errors = 0
    idx = 0
    lock = asyncio.Lock()

    async def worker(worker_id: int) -> None:
        nonlocal idx, errors
        while True:
            async with lock:
                if idx >= iterations:
                    return
                current = idx
                idx += 1
            query = SEARCH_QUERIES[current % len(SEARCH_QUERIES)]
            start = time.perf_counter()
            try:
                await service.search_tracks(query, requester=f"load-worker-{worker_id}", limit=3)
            except Exception:
                errors += 1
            finally:
                latencies_ms.append((time.perf_counter() - start) * 1000.0)

    workers = [asyncio.create_task(worker(i)) for i in range(max(concurrency, 1))]
    await asyncio.gather(*workers)

    if latencies_ms:
        sorted_lat = sorted(latencies_ms)
        p50 = statistics.median(sorted_lat)
        p95_idx = min(int(len(sorted_lat) * 0.95), len(sorted_lat) - 1)
        p95 = sorted_lat[p95_idx]
        avg = statistics.mean(sorted_lat)
    else:
        p50 = p95 = avg = 0.0

    print("=== Load Test Result ===")
    print(f"requests: {iterations}")
    print(f"concurrency: {concurrency}")
    print(f"errors: {errors}")
    print(f"avg_ms: {avg:.1f}")
    print(f"p50_ms: {p50:.1f}")
    print(f"p95_ms: {p95:.1f}")
    return 0 if errors == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load test local para buscas do bot de musica.")
    parser.add_argument("--concurrency", type=int, default=8, help="Numero de workers simultaneos.")
    parser.add_argument("--iterations", type=int, default=120, help="Total de requisicoes.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(run_load(concurrency=args.concurrency, iterations=args.iterations))


if __name__ == "__main__":
    raise SystemExit(main())
