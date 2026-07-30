"""Auth routes: login (fragment token -> session cookie), me, logout, config."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..auth import (
    SESSION_COOKIE, Identity, auth_enabled, current_identity,
    identity_from_login_token, sessions,
)
from ..config import get_settings

router = APIRouter(tags=["auth"])

# The front door for the home-node redirect: token arrives in the URL FRAGMENT
# (never sent to the server or logged); this page hands it to /api/auth/login.
_AUTH_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>orrery — signing in</title>
<style>body{background:#17181c;color:#e4e5e9;font:15px system-ui;display:grid;place-items:center;height:100vh;margin:0}</style>
</head><body><div id="s">signing in…</div><script>
(async () => {
  const el = document.getElementById('s');
  const m = location.hash.match(/token=([^&]+)/);
  if (!m) { el.textContent = 'no token in URL — start from the login link'; return; }
  history.replaceState(null, '', '/auth');  // scrub the fragment
  try {
    const r = await fetch('/api/auth/login', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: decodeURIComponent(m[1]) }) });
    if (!r.ok) { el.textContent = 'rejected: ' + (await r.text()).slice(0, 200); return; }
    location.replace('/');
  } catch (e) { el.textContent = 'error: ' + e.message; }
})();
</script></body></html>"""


@router.get("/auth", include_in_schema=False)
async def auth_page() -> HTMLResponse:
    return HTMLResponse(_AUTH_PAGE)


class LoginIn(BaseModel):
    token: str


@router.post("/api/auth/login")
async def login(body: LoginIn, response: Response) -> dict:
    if not auth_enabled():
        return {"ok": True, "sub": "local", "name": "local", "note": "auth disabled"}
    ident = identity_from_login_token(body.token)   # raises 403 on bad token
    sid = sessions.mint(ident)
    response.set_cookie(
        SESSION_COOKIE, sid,
        max_age=get_settings().session_ttl_hours * 3600,
        httponly=True, samesite="lax", secure=auth_enabled(), path="/",
    )
    return {"ok": True, "sub": ident.sub, "name": ident.name, "admin": ident.admin}


@router.get("/api/auth/me")
async def me(ident: Identity = Depends(current_identity)) -> dict:
    return {"sub": ident.sub, "name": ident.name, "kind": ident.kind,
            "admin": ident.admin, "auth_enabled": auth_enabled()}


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response) -> dict:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        sessions.drop(sid)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/api/auth/config")
async def auth_config() -> dict:
    """Public: how to log in (the UI redirects here on 401)."""
    s = get_settings()
    return {"enabled": auth_enabled(), "login_url": s.hn_login_url}
