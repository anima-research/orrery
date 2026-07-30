"""aid1 token verification — Python port of the archipelago-home verifier.

Token format:  aid1.<base64url(payload json)>.<base64url(ed25519 signature)>
The signature covers the LITERAL BYTES of "aid1.<payload-segment>" (prefix
included) — verify the received bytes first, parse JSON second. Verification
is fully offline against the issuer's pinned ed25519 public key
("ed25519:<base64url raw 32 bytes>"); the issuer being down never blocks us.

Reference implementations: archipelago-home/src/token.ts (source of truth),
eidoverse-worlds/server/aid1.ts (worked audience example).
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

TOKEN_PREFIX = "aid1"


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass
class VerifyResult:
    ok: bool
    payload: dict[str, Any] | None = None
    error: str = ""


def verify_token(
    token: str,
    *,
    issuer_key: str,          # "ed25519:<b64url raw 32B>"
    iss: str,                 # e.g. "id.animalabs.ai"
    aud: str,                 # our audience name, e.g. "orrery"
    require_scopes: list[str] | None = None,
    now: float | None = None,
) -> VerifyResult:
    def fail(msg: str) -> VerifyResult:
        return VerifyResult(ok=False, error=msg)

    if not isinstance(token, str) or not token.startswith(f"{TOKEN_PREFIX}."):
        return fail("not an aid1 token")
    parts = token.split(".")
    if len(parts) != 3:
        return fail("malformed token")
    _, seg, sig_seg = parts

    if not issuer_key.startswith("ed25519:"):
        return fail("issuer key must be ed25519:<b64url>")
    try:
        raw_key = _b64url_decode(issuer_key[len("ed25519:"):])
        pub = Ed25519PublicKey.from_public_bytes(raw_key)
    except Exception:
        return fail("bad issuer key")

    try:
        sig = _b64url_decode(sig_seg)
        pub.verify(sig, f"{TOKEN_PREFIX}.{seg}".encode("utf-8"))
    except (InvalidSignature, Exception):
        return fail("signature verify failed")

    try:
        payload = json.loads(_b64url_decode(seg))
    except Exception:
        return fail("payload is not valid JSON")

    t = now if now is not None else time.time()
    if payload.get("v") != 1:
        return fail(f"unsupported token version {payload.get('v')!r}")
    if payload.get("iss") != iss:
        return fail(f"wrong issuer {payload.get('iss')!r}")
    if payload.get("aud") != aud:
        return fail(f"wrong audience {payload.get('aud')!r} (want {aud!r})")
    if not payload.get("sub"):
        return fail("missing sub")
    if not payload.get("name"):
        return fail("missing name")
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or exp <= t:
        return fail("token expired")
    iat = payload.get("iat")
    if isinstance(iat, (int, float)) and iat > t + 300:
        return fail("token issued in the future")
    scopes = payload.get("scopes") or []
    for s in require_scopes or []:
        if s not in scopes:
            return fail(f"missing scope {s!r}")
    return VerifyResult(ok=True, payload=payload)


@dataclass
class JtiCache:
    """Single-use guard for login-redirect tokens (jti replay protection).
    In-memory, pruned on insert — matches the reference implementation."""
    seen: dict[str, float] = field(default_factory=dict)

    def claim(self, jti: str, exp: float) -> bool:
        now = time.time()
        # prune expired entries
        for k in [k for k, e in self.seen.items() if e <= now]:
            del self.seen[k]
        if jti in self.seen:
            return False
        self.seen[jti] = exp
        return True
