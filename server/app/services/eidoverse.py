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

MAX_BYTES = 80_000_000


class EidoverseError(RuntimeError):
    pass


def _check_glb(path: Path) -> None:
    if path.stat().st_size > MAX_BYTES:
        raise EidoverseError(f"{path.name} is {path.stat().st_size // 1_000_000}MB — eidoverse caps uploads at 80MB "
                             "(retopo or convert with smaller texture_size first)")
    with open(path, "rb") as f:
        if f.read(4) != b"glTF":
            raise EidoverseError(f"{path.name} is not a GLB container — eidoverse accepts .glb/.vrm only")


async def send_object(glb_path: Path) -> dict:
    """Upload a GLB as a world object; returns {"path": "store/<hash>.glb"}."""
    _check_glb(glb_path)
    s = get_settings()
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(f"{s.eidoverse_url}/upload", content=glb_path.read_bytes())
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
    """Run tools/slim-vrm.ts when the VRM is over the 80MB cap (texture downsize)."""
    if vrm_path.stat().st_size <= MAX_BYTES:
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


async def send_avatar(glb_path: Path, name: str, height: float | None = None) -> dict:
    """Convert rigged GLB -> VRM and upload as a named avatar."""
    vrm = await glb_to_vrm(glb_path, name, height)
    vrm = await slim_vrm_if_needed(vrm)
    _check_glb(vrm)
    s = get_settings()
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(
            f"{s.eidoverse_url}/upload",
            params={"as": "avatar", "name": name},
            content=vrm.read_bytes(),
        )
    if r.status_code >= 400:
        raise EidoverseError(f"eidoverse avatar upload failed: {r.status_code} {r.text[:200]}")
    return r.json()
