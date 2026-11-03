"""The upload key rides Authorization: Bearer; ?token= only while that target's EIDOVERSE[2]_TOKEN_IN_URL is on."""
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MOCK_APIS", "1")
_RealClient = httpx.AsyncClient


def _push(tmp_path, monkeypatch, in_url: str | None, kind: str = "object", target: str = "eidoverse",
          env: dict | None = None):
    monkeypatch.setenv("EIDOVERSE_URL", "http://world.test")
    monkeypatch.setenv("EIDOVERSE_TOKEN", "door-key")
    if in_url is None:
        monkeypatch.delenv("EIDOVERSE_TOKEN_IN_URL", raising=False)
    else:
        monkeypatch.setenv("EIDOVERSE_TOKEN_IN_URL", in_url)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    from tests.conftest import reset_app_modules
    reset_app_modules()
    from app import config
    from app.services import eidoverse

    settings = config.Settings(_env_file=None)   # the declared defaults, not a local .env
    monkeypatch.setattr(eidoverse, "get_settings", lambda: settings)
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"path": "store/x.glb"})

    monkeypatch.setattr(eidoverse.httpx, "AsyncClient",
                        lambda **kw: _RealClient(transport=httpx.MockTransport(handler), **kw))
    glb = tmp_path / "a.glb"
    glb.write_bytes(b"glTF" + b"\0" * 16)
    if kind == "avatar":
        async def as_is(path, *a, **kw):
            return glb
        monkeypatch.setattr(eidoverse, "glb_to_vrm", as_is)
        monkeypatch.setattr(eidoverse, "slim_vrm_if_needed", as_is)
        asyncio.run(eidoverse.send_avatar(glb, name="tess", target=target))
    else:
        asyncio.run(eidoverse.send_object(glb, name="lamp", target=target))
    return seen[0]


@pytest.mark.parametrize("kind", ["object", "avatar"])
def test_bearer_header_and_legacy_query_by_default(tmp_path, monkeypatch, kind):
    req = _push(tmp_path, monkeypatch, None, kind)
    assert req.headers["authorization"] == "Bearer door-key"
    assert req.url.params.get("token") == "door-key"   # servers before eidoverse #260 read only this


@pytest.mark.parametrize("kind", ["object", "avatar"])
def test_token_off_the_url_when_switched_off(tmp_path, monkeypatch, kind):
    req = _push(tmp_path, monkeypatch, "false", kind)
    assert req.headers["authorization"] == "Bearer door-key"
    assert "token" not in req.url.params
    assert "door-key" not in str(req.url)


STAGING = {"EIDOVERSE2_URL": "http://staging.test", "EIDOVERSE2_TOKEN": "staging-key"}


@pytest.mark.parametrize("staging_in_url,prod_in_url", [("false", "true"), ("true", "false")])
def test_each_target_moves_to_the_header_on_its_own(tmp_path, monkeypatch, staging_in_url, prod_in_url):
    env = {**STAGING, "EIDOVERSE2_TOKEN_IN_URL": staging_in_url}
    stg = _push(tmp_path, monkeypatch, prod_in_url, target="eidoverse2", env=env)
    prod = _push(tmp_path, monkeypatch, prod_in_url, target="eidoverse", env=env)
    assert stg.url.host == "staging.test" and stg.headers["authorization"] == "Bearer staging-key"
    assert prod.url.host == "world.test" and prod.headers["authorization"] == "Bearer door-key"
    assert ("token" in stg.url.params) == (staging_in_url == "true")
    assert ("token" in prod.url.params) == (prod_in_url == "true")
