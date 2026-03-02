from __future__ import annotations

import asyncio

from botmusica.music.services.dns_cache import DnsCache


def test_dns_cache_resolves_and_reuses() -> None:
    async def _run() -> None:
        cache = DnsCache(ttl_seconds=60, max_entries=32)
        ip1 = await cache.resolve_ipv4("localhost", 80)
        ip2 = await cache.resolve_ipv4("localhost", 80)
        assert ip1 == ip2

    asyncio.run(_run())
