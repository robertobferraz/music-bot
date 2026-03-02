from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

from aiohttp import web


def validate_admin_token(request: web.Request, expected_token: str) -> bool:
    if not expected_token:
        return False
    header_token = request.headers.get("X-Admin-Token", "").strip()
    if header_token and header_token == expected_token:
        return True
    query_token = request.query.get("token", "").strip()
    if query_token and query_token == expected_token:
        return True
    return False


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + pad).encode("ascii"))


def _sign_blob(secret: str, blob: bytes) -> str:
    return _b64url_encode(hmac.new(secret.encode("utf-8"), blob, hashlib.sha256).digest())


def create_oauth_state(secret: str, *, ttl_seconds: int = 300) -> str:
    payload = {
        "nonce": secrets.token_urlsafe(12),
        "iat": int(time.time()),
        "exp": int(time.time()) + max(int(ttl_seconds), 30),
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _b64url_encode(payload_raw)
    sig = _sign_blob(secret, payload_raw)
    return f"{encoded}.{sig}"


def verify_oauth_state(secret: str, state: str) -> bool:
    if not secret or not state or "." not in state:
        return False
    encoded, sig = state.split(".", 1)
    try:
        payload_raw = _b64url_decode(encoded)
    except Exception:
        return False
    expected = _sign_blob(secret, payload_raw)
    if not hmac.compare_digest(expected, sig):
        return False
    try:
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        return False
    now = int(time.time())
    exp = int(payload.get("exp", 0) or 0)
    iat = int(payload.get("iat", 0) or 0)
    if exp <= 0 or iat <= 0:
        return False
    if now > exp:
        return False
    if iat > now + 30:
        return False
    return True


def build_discord_oauth_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scope: str = "identify",
) -> str:
    params = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "prompt": "none",
        }
    )
    return f"https://discord.com/api/oauth2/authorize?{params}"


def create_signed_session_cookie(
    *,
    secret: str,
    payload: dict[str, object],
    ttl_seconds: int = 43200,
) -> str:
    now = int(time.time())
    body = {
        **payload,
        "iat": now,
        "exp": now + max(int(ttl_seconds), 300),
    }
    body_raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _b64url_encode(body_raw)
    sig = _sign_blob(secret, body_raw)
    return f"{encoded}.{sig}"


def parse_signed_session_cookie(secret: str, cookie_value: str) -> dict[str, object] | None:
    if not secret or not cookie_value or "." not in cookie_value:
        return None
    encoded, sig = cookie_value.split(".", 1)
    try:
        body_raw = _b64url_decode(encoded)
    except Exception:
        return None
    expected = _sign_blob(secret, body_raw)
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        body = json.loads(body_raw.decode("utf-8"))
    except Exception:
        return None
    now = int(time.time())
    exp = int(body.get("exp", 0) or 0)
    if exp <= 0 or now > exp:
        return None
    return body
