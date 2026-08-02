"""Push models into eidoverse-worlds (verified contract, 2026-07):

- objects:  POST {url}/upload            raw GLB bytes -> {"path": "store/<hash>.glb"}
- avatars:  POST {url}/upload?as=avatar&name=<n>  raw VRM bytes -> {"name", "path"}
  Rigged humanoid GLB -> VRM 1.0 via eidoverse's own tools/glb2vrm.ts (bun),
  built for Tripo-style skeletons. No auth (tailnet trust), 80 MB cap,
  GLB magic-number check server-side.
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import httpx

from ..config import get_settings

class EidoverseError(RuntimeError):
    pass


class EidoverseTooLarge(EidoverseError):
    """Pre-flight size failure — a local client error (413), not a bad gateway."""


def _max_bytes() -> int:
    return get_settings().eidoverse_max_mb * 1_000_000


def _upload_params(extra: dict | None = None, by: str | None = None) -> dict:
    s = get_settings()
    params = dict(extra or {})
    if s.eidoverse_token:
        params["token"] = s.eidoverse_token
    if by:
        params["by"] = by[:64]
    return params


def _check_glb(path: Path) -> None:
    cap = _max_bytes()
    size = path.stat().st_size
    if size > cap:
        # For Tripo meshes the weight is geometry (v3.1 runs to ~1.5M triangles),
        # not textures — so retopo/face_limit is the lever, NOT texture_size.
        raise EidoverseTooLarge(
            f"{path.name} is {size / 1_000_000:.1f}MB — the world caps uploads at "
            f"{cap // 1_000_000}MB. This is triangle count, not textures: branch a retopo "
            f"(mesh/decimate) and send that, or regenerate mesh_gen with a face_limit.")
    with open(path, "rb") as f:
        if f.read(4) != b"glTF":
            raise EidoverseError(f"{path.name} is not a GLB container — eidoverse accepts .glb/.vrm only")


async def send_object(glb_path: Path, name: str | None = None,
                      by: str | None = None) -> dict:
    """Upload a GLB as a world object; returns {"path": "store/<hash>.glb"}.
    `name` lands in the store manifest — without it the content-addressed
    catalog can only ever call this object a hash."""
    _check_glb(glb_path)
    s = get_settings()
    extra = {"name": name[:64]} if name else None
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{s.eidoverse_url}/upload",
                                  params=_upload_params(extra, by=by),
                                  content=glb_path.read_bytes())
    except httpx.HTTPError as e:
        raise EidoverseError(f"cannot reach eidoverse at {s.eidoverse_url}: {e.__class__.__name__}: {e}")
    if r.status_code == 401:
        raise EidoverseError("eidoverse requires an upload token — set EIDOVERSE_TOKEN")
    if r.status_code >= 400:
        raise EidoverseError(f"eidoverse upload failed: {r.status_code} {r.text[:200]}")
    return r.json()


async def glb_to_vrm(glb_path: Path, name: str, height: float | None = None) -> Path:
    """Convert a rigged humanoid GLB to VRM 1.0 using eidoverse's glb2vrm tool."""
    s = get_settings()
    tool = s.eidoverse_repo / "tools" / "glb2vrm.ts"
    if not tool.exists():
        raise EidoverseError(f"glb2vrm tool not found at {tool} — set EIDOVERSE_REPO")
    out = Path(tempfile.mkdtemp(prefix="vrm_")) / f"{name}.vrm"
    cmd = [s.bun_bin, str(tool), str(glb_path), "--name", name, "--out", str(out)]
    if height:
        cmd += ["--height", str(height)]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(s.eidoverse_repo),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0 or not out.exists():
        raise EidoverseError(f"glb2vrm failed (exit {proc.returncode}): {stdout.decode()[-400:]}")
    return out


async def slim_vrm_if_needed(vrm_path: Path) -> Path:
    """Run tools/slim-vrm.ts when the VRM is over the upload cap (texture downsize)."""
    if vrm_path.stat().st_size <= _max_bytes():
        return vrm_path
    s = get_settings()
    tool = s.eidoverse_repo / "tools" / "slim-vrm.ts"
    slim = vrm_path.with_name(vrm_path.stem + "_slim.vrm")
    proc = await asyncio.create_subprocess_exec(
        s.bun_bin, str(tool), str(vrm_path), "--out", str(slim),
        cwd=str(s.eidoverse_repo),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0 or not slim.exists():
        raise EidoverseError(f"slim-vrm failed: {stdout.decode()[-300:]}")
    return slim


async def send_avatar(glb_path: Path, name: str, height: float | None = None,
                      by: str | None = None) -> dict:
    """Convert rigged GLB -> VRM and upload as a named avatar."""
    vrm = await glb_to_vrm(glb_path, name, height)
    vrm = await slim_vrm_if_needed(vrm)
    _check_glb(vrm)
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(
                f"{s.eidoverse_url}/upload",
                params=_upload_params({"as": "avatar", "name": name}, by=by),
                content=vrm.read_bytes(),
            )
    except httpx.HTTPError as e:
        raise EidoverseError(f"cannot reach eidoverse at {s.eidoverse_url}: {e.__class__.__name__}: {e}")
    if r.status_code == 401:
        raise EidoverseError("eidoverse requires an upload token — set EIDOVERSE_TOKEN")
    if r.status_code >= 400:
        raise EidoverseError(f"eidoverse avatar upload failed: {r.status_code} {r.text[:200]}")
    return r.json()
