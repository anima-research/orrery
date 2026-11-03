"""The upload key rides Authorization: Bearer; ?token= only while EIDOVERSE_TOKEN_IN_URL is on."""
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MOCK_APIS", "1")


def _push(tmp_path, monkeypatch, in_url: str | None):
    monkeypatch.setenv("EIDOVERSE_URL", "http://world.test")
    monkeypatch.setenv("EIDOVERSE_TOKEN", "door-key")
    if in_url is None:
        monkeypatch.delenv("EIDOVERSE_TOKEN_IN_URL", raising=False)
    else:
        monkeypatch.setenv("EIDOVERSE_TOKEN_IN_URL", in_url)
    from tests.conftest import reset_app_modules
    reset_app_modules()
    from app.services import eidoverse

    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"path": "store/x.glb"})

    real = httpx.AsyncClient
    monkeypatch.setattr(eidoverse.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    glb = tmp_path / "a.glb"
    glb.write_bytes(b"glTF" + b"\0" * 16)
    asyncio.run(eidoverse.send_object(glb, name="lamp"))
    return seen[0]


def test_bearer_header_and_legacy_query_by_default(tmp_path, monkeypatch):
    req = _push(tmp_path, monkeypatch, None)
    assert req.headers["authorization"] == "Bearer door-key"
    assert req.url.params.get("token") == "door-key"   # servers before eidoverse #260 read only this


def test_token_off_the_url_when_switched_off(tmp_path, monkeypatch):
    req = _push(tmp_path, monkeypatch, "false")
    assert req.headers["authorization"] == "Bearer door-key"
    assert "token" not in req.url.params
    assert "door-key" not in str(req.url)
