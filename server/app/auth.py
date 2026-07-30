"""Identity resolution + sessions for orrery.

Modes:
- Auth OFF (no HN_ISSUER_KEY configured): every request is a synthetic local
  admin — preserves the original open localhost/tailnet behavior.
- Auth ON: humans present a session cookie (minted at POST /api/auth/login from
  a fragment-delivered aid1 token, jti single-use); agents present
  `Authorization: Bearer aid1....` per request (verified with a small cache).
  Every accepted identity must carry the `orrery:use` scope.

All ownership is keyed by the durable `sub`.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

from fastapi import HTTPException, Request

from .config import get_settings
from .services.aid1 import JtiCache, verify_token

SESSION_COOKIE = "orr_sess"


@dataclass
class Identity:
    sub: str
    name: str
    kind: str = "human"
    scopes: list[str] = field(default_factory=list)
    admin: bool = False

    @property
    def is_local(self) -> bool:
        return self.sub == "local"


LOCAL_ADMIN = Identity(sub="local", name="local", kind="service",
                       scopes=["orrery:use", "orrery:admin"], admin=True)


class Sessions:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Identity, float]] = {}

    def mint(self, ident: Identity) -> str:
        sid = secrets.token_hex(32)
        ttl = get_settings().session_ttl_hours * 3600
        self._store[sid] = (ident, time.time() + ttl)
        return sid

    def get(self, sid: str) -> Identity | None:
        row = self._store.get(sid)
        if not row:
            return None
        ident, exp = row
        if exp <= time.time():
            del self._store[sid]
            return None
        return ident

    def drop(self, sid: str) -> None:
        self._store.pop(sid, None)


sessions = Sessions()
jti_cache = JtiCache()
_bearer_cache: dict[str, tuple[Identity, float]] = {}   # token -> (ident, exp)


def auth_enabled() -> bool:
    return bool(get_settings().hn_issuer_key)


def _to_identity(payload: dict) -> Identity:
    s = get_settings()
    scopes = payload.get("scopes") or []
    admin_subs = {x.strip() for x in s.admin_subs.split(",") if x.strip()}
    return Identity(
        sub=payload["sub"],
        name=payload.get("name") or payload["sub"],
        kind=payload.get("kind") or "human",
        scopes=scopes,
        admin=(s.hn_admin_scope in scopes) or (payload["sub"] in admin_subs),
    )


def identity_from_login_token(token: str) -> Identity:
    """Verify a fragment-delivered login token (single-use jti) -> Identity."""
    s = get_settings()
    v = verify_token(token, issuer_key=s.hn_issuer_key, iss=s.hn_iss,
                     aud=s.hn_aud, require_scopes=[s.hn_use_scope])
    if not v.ok:
        raise HTTPException(403, f"token rejected: {v.error}")
    jti = v.payload.get("jti")
    if jti and not jti_cache.claim(jti, v.payload.get("exp", time.time() + 600)):
        raise HTTPException(403, "token already used")
    return _to_identity(v.payload)


def _identity_from_bearer(token: str) -> Identity | None:
    now = time.time()
    hit = _bearer_cache.get(token)
    if hit and hit[1] > now:
        return hit[0]
    s = get_settings()
    v = verify_token(token, issuer_key=s.hn_issuer_key, iss=s.hn_iss,
                     aud=s.hn_aud, require_scopes=[s.hn_use_scope])
    if not v.ok:
        return None
    ident = _to_identity(v.payload)
    if len(_bearer_cache) > 500:
        for k in [k for k, (_, e) in _bearer_cache.items() if e <= now]:
            del _bearer_cache[k]
    _bearer_cache[token] = (ident, min(v.payload["exp"], now + 3600))
    return ident


def current_identity(request: Request) -> Identity:
    """FastAPI dependency: resolve the caller or 401."""
    if not auth_enabled():
        return LOCAL_ADMIN
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        ident = sessions.get(sid)
        if ident:
            return ident
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        ident = _identity_from_bearer(authz[7:].strip())
        if ident:
            return ident
    raise HTTPException(401, "login required")
