from __future__ import annotations

import asyncio
import socket
import time
from collections import OrderedDict


class DnsCache:
    def __init__(self, *, ttl_seconds: float = 300.0, max_entries: int = 128) -> None:
        self.ttl_seconds = max(ttl_seconds, 1.0)
        self.max_entries = max(max_entries, 16)
        self._cache: OrderedDict[tuple[str, int], tuple[float, str]] = OrderedDict()

    async def resolve_ipv4(self, host: str, port: int) -> str:
        key = (host.strip().casefold(), int(port))
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None:
            exp, ip = cached
            if exp >= now:
                self._cache.move_to_end(key)
                return ip
            self._cache.pop(key, None)

        infos = await asyncio.to_thread(socket.getaddrinfo, host, port, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            raise RuntimeError(f"DNS resolve falhou para {host}:{port}")
        ip = str(infos[0][4][0])
        self._cache[key] = (now + self.ttl_seconds, ip)
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)
        return ip
