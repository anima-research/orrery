"""aid1 verification + per-user library access tests.

We mint our own issuer keypair and tokens — the verifier can't tell the
difference, which is the point of offline verification.
"""
import base64
import json
import os
import sys
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MOCK_APIS", "1")

ISS = "id.test"
AUD = "orrery"


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


@pytest.fixture(scope="module")
def issuer():
    priv = Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv, f"ed25519:{_b64u(raw)}"


def mint(priv, *, sub="human:discord:1", name="tess", scopes=("orrery:use",),
         aud=AUD, iss=ISS, exp_in=3600, iat_skew=0, jti=None, v=1):
    payload = {"v": v, "iss": iss, "sub": sub, "kind": "human", "name": name,
               "aud": aud, "scopes": list(scopes), "claims": {},
               "iat": int(time.time()) + iat_skew,
               "exp": int(time.time()) + exp_in}
    if jti:
        payload["jti"] = jti
    seg = _b64u(json.dumps(payload).encode())
    sig = priv.sign(f"aid1.{seg}".encode())
    return f"aid1.{seg}.{_b64u(sig)}"


# ---------- token verification ----------

def test_verify_good_token(issuer):
    from app.services.aid1 import verify_token
    priv, pub = issuer
    v = verify_token(mint(priv), issuer_key=pub, iss=ISS, aud=AUD,
                     require_scopes=["orrery:use"])
    assert v.ok and v.payload["name"] == "tess"


def test_verify_rejections(issuer):
    from app.services.aid1 import verify_token
    priv, pub = issuer
    other_pub = "ed25519:" + _b64u(
        Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    cases = [
        (mint(priv), dict(issuer_key=other_pub), "signature"),        # wrong key
        (mint(priv, aud="eidoverse"), {}, "audience"),                # wrong aud
        (mint(priv, iss="id.evil"), {}, "issuer"),                    # wrong iss
        (mint(priv, exp_in=-10), {}, "expired"),                      # expired
        (mint(priv, iat_skew=9999), {}, "future"),                    # future iat
        (mint(priv, scopes=()), dict(require_scopes=["orrery:use"]), "scope"),
        (mint(priv, v=2), {}, "version"),
        ("aid1.garbage", {}, "malformed"),
        ("nope", {}, "aid1"),
    ]
    for token, extra, expect in cases:
        kw = dict(issuer_key=pub, iss=ISS, aud=AUD)
        kw.update(extra)
        v = verify_token(token, **kw)
        assert not v.ok and expect in v.error.lower(), (expect, v.error)


def test_tampered_payload_fails(issuer):
    from app.services.aid1 import verify_token
    priv, pub = issuer
    token = mint(priv)
    _, seg, sig = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(seg + "=="))
    payload["scopes"] = ["orrery:use", "orrery:admin"]   # privilege escalation attempt
    forged = f"aid1.{_b64u(json.dumps(payload).encode())}.{sig}"
    assert not verify_token(forged, issuer_key=pub, iss=ISS, aud=AUD).ok


def test_jti_single_use():
    from app.services.aid1 import JtiCache
    c = JtiCache()
    assert c.claim("abc", time.time() + 60)
    assert not c.claim("abc", time.time() + 60)
    assert c.claim("def", time.time() + 60)


# ---------- per-user libraries over the API ----------

@pytest.mark.asyncio
async def test_ownership_scoping(tmp_path, monkeypatch, issuer):
    priv, pub = issuer
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MOCK_APIS", "1")
    monkeypatch.setenv("HN_ISSUER_KEY", pub)
    monkeypatch.setenv("HN_ISS", ISS)
    monkeypatch.setenv("HN_AUD", AUD)
    from tests.conftest import reset_app_modules
    reset_app_modules()
    from app.config import get_settings
    get_settings.cache_clear()
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.db import init_db
    await init_db()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # anonymous → 401
        r = await c.get("/api/projects")
        assert r.status_code == 401

        alice = {"Authorization": "Bearer " + mint(priv, sub="human:discord:1", name="alice")}
        bob = {"Authorization": "Bearer " + mint(priv, sub="human:discord:2", name="bob")}
        boss = {"Authorization": "Bearer " + mint(
            priv, sub="human:discord:9", name="boss",
            scopes=("orrery:use", "orrery:admin"))}
        noscope = {"Authorization": "Bearer " + mint(priv, sub="human:discord:3",
                                                     name="carol", scopes=())}

        # scope gate
        assert (await c.get("/api/projects", headers=noscope)).status_code == 401

        # alice creates a project; bob can't see or touch it
        p = (await c.post("/api/projects", json={"name": "a1", "prompt": "x"},
                          headers=alice)).json()
        assert p["owner_name"] == "alice"
        assert [q["id"] for q in (await c.get("/api/projects", headers=bob)).json()] == []
        assert (await c.get(f"/api/projects/{p['id']}/tree", headers=bob)).status_code == 404
        assert (await c.post(f"/api/projects/{p['id']}/nodes", headers=bob,
                             json={"op": "ref_set"})).status_code in (403, 404)

        # sharing makes it readable, not writable
        await c.patch(f"/api/projects/{p['id']}", json={"shared": True}, headers=alice)
        assert (await c.get(f"/api/projects/{p['id']}/tree", headers=bob)).status_code == 200
        assert (await c.post(f"/api/projects/{p['id']}/nodes", headers=bob,
                             json={"op": "ref_set"})).status_code == 403
        # ...and assets of a shared project are readable
        assert len((await c.get("/api/projects", headers=bob)).json()) == 1

        # admin sees and writes everything
        assert len((await c.get("/api/projects", headers=boss)).json()) == 1
        assert (await c.post(f"/api/projects/{p['id']}/nodes", headers=boss,
                             json={"op": "ref_set"})).status_code == 200

        # login flow: fragment token -> cookie session; jti single use
        tok = mint(priv, sub="human:discord:1", name="alice", jti="one-shot")
        r = await c.post("/api/auth/login", json={"token": tok})
        assert r.status_code == 200 and "orr_sess" in r.headers.get("set-cookie", "")
        r2 = await c.post("/api/auth/login", json={"token": tok})
        assert r2.status_code == 403  # replay refused
