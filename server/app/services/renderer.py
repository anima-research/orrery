"""Headless model screenshots via Playwright + an embedded three.js page.

Drives headless Chromium to render a GLB/GLTF with three.js (vendored in
``viewer_assets/`` — no network requests at render time; everything is served
through Playwright route interception on a fake ``https://viewer.local``
origin) and captures ``count`` turntable screenshots around the yaw axis.

    await turntable(model_path, out_dir, count=8, size=1024, elevation=20)

returns a list of PNG paths (``yaw_000.png`` ...), cached by a signature of
(model mtime+size, count, size, elevation) stored in ``out_dir/signature.txt``.
"""
from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

_ASSET_DIR = Path(__file__).resolve().parent / "viewer_assets"
_ORIGIN = "https://viewer.local"

_INSTALL_HINT = (
    "install it with:\n"
    "  server/.venv/bin/pip install playwright\n"
    "  server/.venv/bin/python -m playwright install chromium"
)

# Software WebGL (SwiftShader) needs an explicit opt-in on recent Chromium;
# without it headless rendering has no GL context on machines w/o GPU access.
_LAUNCH_ARGS = [
    "--enable-unsafe-swiftshader",
    "--hide-scrollbars",
    "--force-color-profile=srgb",
]

# Lazy module-level browser singleton, shared across calls.
_playwright: Any = None
_browser: Any = None
_browser_lock = asyncio.Lock()
# At most 2 renders drive Chromium concurrently.
_render_sem = asyncio.Semaphore(2)

_VIEWER_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>html, body { margin: 0; background: #e5e5e8; }</style>
<script>window.__ready = false; window.__error = null;</script>
<script type="importmap">{"imports": {"three": "/three.module.js"}}</script>
</head>
<body>
<canvas id="c"></canvas>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader } from '/jsm/loaders/GLTFLoader.js';

const params = new URLSearchParams(location.search);
const size = parseInt(params.get('size') || '1024', 10);
const elevation = parseFloat(params.get('elevation') || '20');
const modelUrl = params.get('model') || '/model/model.glb';

let renderer, scene, camera, center, dist;

async function init() {
  renderer = new THREE.WebGLRenderer({
    canvas: document.getElementById('c'),
    antialias: true,
    preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(1);
  renderer.setSize(size, size, false);

  // Neutral studio: light gray bg, hemisphere + key/fill/rim directionals so
  // both untextured and PBR models read well.
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe5e5e8);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8890a0, 1.2));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(3, 5, 4);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.9);
  fill.position.set(-4, 2, -2);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0xffffff, 0.7);
  rim.position.set(0, 4, -5);
  scene.add(rim);

  // Animations (if any) are ignored: no mixer -> default pose, first frame.
  const gltf = await new GLTFLoader().loadAsync(modelUrl);
  scene.add(gltf.scene);
  gltf.scene.updateMatrixWorld(true);

  // Auto-frame via bounding sphere with ~15% margin.
  const box = new THREE.Box3().setFromObject(gltf.scene);
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  center = sphere.center.clone();
  const radius = (isFinite(sphere.radius) && sphere.radius > 0) ? sphere.radius : 1;
  const fov = 35;
  dist = (radius * 1.15) / Math.sin(THREE.MathUtils.degToRad(fov / 2));
  camera = new THREE.PerspectiveCamera(fov, 1, dist / 100, dist * 10);
  window.__ready = true;
}
init().catch((e) => { window.__error = String((e && e.message) || e); });

window.__shoot = (yawDeg) => {
  const phi = THREE.MathUtils.degToRad(90 - elevation);
  const theta = THREE.MathUtils.degToRad(yawDeg);
  camera.position.setFromSphericalCoords(dist, phi, theta).add(center);
  camera.lookAt(center);
  renderer.render(scene, camera);
  // Read the framebuffer directly (same-task, forces MSAA resolve) instead
  // of WebGL-canvas toDataURL, which can flake to black on software GL.
  const gl = renderer.getContext();
  const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
  const px = new Uint8Array(w * h * 4);
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
  const c2 = document.createElement('canvas');
  c2.width = w; c2.height = h;
  const ctx = c2.getContext('2d');
  const img = ctx.createImageData(w, h);
  const row = w * 4;
  for (let y = 0; y < h; y++) {  // flip: GL rows are bottom-up
    img.data.set(px.subarray((h - 1 - y) * row, (h - y) * row), y * row);
  }
  ctx.putImageData(img, 0, 0);
  return c2.toDataURL('image/png');
};
</script>
</body>
</html>
"""


class RendererUnavailable(RuntimeError):
    pass


def _signature(model_path: Path, count: int, size: int, elevation: float) -> str:
    st = model_path.stat()
    return f"{st.st_mtime_ns}:{st.st_size}:{count}:{size}:{elevation}"


def _shot_paths(out_dir: Path, count: int) -> list[Path]:
    return [out_dir / f"yaw_{round(i * 360 / count):03d}.png" for i in range(count)]


def _cache_valid(sig_file: Path, sig: str, paths: list[Path]) -> bool:
    try:
        cached = sig_file.read_text().strip()
    except OSError:
        return False
    return cached == sig and all(p.exists() for p in paths)


async def _get_browser() -> Any:
    """Launch (once) and return the shared headless Chromium instance."""
    global _playwright, _browser
    async with _browser_lock:
        if _browser is not None and _browser.is_connected():
            return _browser
        try:
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RendererUnavailable(f"playwright is not installed; {_INSTALL_HINT}") from e
        try:
            if _playwright is None:
                _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        except PlaywrightError as e:
            raise RendererUnavailable(f"could not launch headless Chromium ({e}); {_INSTALL_HINT}") from e
        return _browser


def _make_route_handler(model_path: Path):
    """Serve viewer HTML, vendored three.js and model files — all from disk."""
    model_dir = model_path.parent

    async def handle(route: Any) -> None:
        path = unquote(urlsplit(route.request.url).path)
        if path in ("/", "/index.html"):
            await route.fulfill(status=200, content_type="text/html", body=_VIEWER_HTML)
            return
        if path.endswith(".js"):
            asset = _ASSET_DIR / Path(path).name
            if asset.is_file():
                body = await asyncio.to_thread(asset.read_bytes)
                await route.fulfill(status=200, content_type="text/javascript", body=body)
                return
        if path.startswith("/model/"):
            # Resolve within the model's directory so .gltf sidecars
            # (.bin, textures) referenced by relative URI load too.
            target = (model_dir / path[len("/model/"):]).resolve()
            if target.is_relative_to(model_dir.resolve()) and target.is_file():
                body = await asyncio.to_thread(target.read_bytes)
                ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                await route.fulfill(status=200, content_type=ctype, body=body)
                return
        await route.fulfill(status=404, body="not found")

    return handle


async def _render(model_path: Path, paths: list[Path], *, count: int,
                  size: int, elevation: float) -> None:
    """Drive one Chromium page through all yaw angles, writing PNGs."""
    browser = await _get_browser()
    context = await browser.new_context(viewport={"width": size, "height": size})
    page = await context.new_page()
    try:
        await page.route(f"{_ORIGIN}/**", _make_route_handler(model_path))
        url = (f"{_ORIGIN}/index.html?size={size}&elevation={elevation}"
               f"&model=/model/{quote(model_path.name)}")
        await page.goto(url)
        await page.wait_for_function(
            "window.__ready === true || typeof window.__error === 'string'",
            timeout=60_000)
        err = await page.evaluate("window.__error")
        if err:
            raise RuntimeError(f"viewer failed to render {model_path.name}: {err}")
        for i, dest in enumerate(paths):
            data_url = await page.evaluate("yaw => window.__shoot(yaw)", i * 360.0 / count)
            png = base64.b64decode(data_url.split(",", 1)[1])
            await asyncio.to_thread(dest.write_bytes, png)
    finally:
        await context.close()


async def turntable(model_path: Path, out_dir: Path, *, count: int = 8,
                    size: int = 1024, elevation: float = 20.0,
                    refresh: bool = False) -> list[Path]:
    """Render `count` turntable screenshots of a GLB/GLTF around the yaw axis.

    Camera sits `elevation` degrees above the horizon, model auto-framed with
    ~15% margin; each shot is a `size`x`size` PNG named ``yaw_<deg:03d>.png``.
    Cached: if the parameter signature matches out_dir/signature.txt and all
    PNGs exist (and refresh is False), returns without launching the browser.
    """
    model_path = model_path.resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"model not found: {model_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    sig = _signature(model_path, count, size, elevation)
    sig_file = out_dir / "signature.txt"
    paths = _shot_paths(out_dir, count)
    if not refresh and _cache_valid(sig_file, sig, paths):
        return paths
    async with _render_sem:
        # A concurrent call may have produced the same shots while we waited.
        if not refresh and _cache_valid(sig_file, sig, paths):
            return paths
        await _render(model_path, paths, count=count, size=size, elevation=elevation)
        sig_file.write_text(sig + "\n")
    return paths
