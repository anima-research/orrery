"""Application settings, loaded from environment / .env at repo root."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    wavespeed_api_key: str = ""
    tripo_api_key: str = ""
    openrouter_api_key: str = ""
    blackforest_api_key: str = ""
    gemini_api_key: str = ""
    luma_api_key: str = ""
    anthropic_api_key: str = ""      # Haiku vision pass for auto-labeling grid views

    data_dir: Path = REPO_ROOT / "data"

    # WaveSpeed account tier caps concurrency (Bronze=2, Silver=300).
    wavespeed_max_concurrency: int = 2
    # Tripo defaults: 3D gen 10, model processing 5, mesh ops 10, animation 10.
    tripo_max_concurrency: int = 8

    # Return canned fixtures instead of calling providers.
    mock_apis: bool = False

    # Archipelago auth (home node aid1 tokens). Auth is ON iff hn_issuer_key is
    # set; unset = open local/tailnet mode (single synthetic admin identity).
    hn_issuer_key: str = ""          # "ed25519:<b64url raw 32B>" — issuer PUBLIC key pin
    hn_iss: str = "id.animalabs.ai"
    hn_aud: str = "orrery"
    hn_login_url: str = "https://id.animalabs.ai/login?audience=orrery"
    hn_use_scope: str = "orrery:use"     # required on every token
    hn_admin_scope: str = "orrery:admin"
    admin_subs: str = ""                 # csv of subs that are admins regardless of scope
    session_ttl_hours: int = 12

    # Eidoverse-worlds integration (raw-GLB POST /upload; glb2vrm for avatars)
    eidoverse_url: str = "http://127.0.0.1:8940"
    eidoverse_token: str = ""        # door key or agent bearer (?token=) if the server requires one
    eidoverse_max_mb: int = 20       # must match the world's UPLOAD_CAP_MB (default 20)
    eidoverse_repo: Path = Path.home() / "connectome-local" / "eidoverse-worlds"
    bun_bin: str = str(Path.home() / ".bun" / "bin" / "bun")

    # Polling
    poll_initial_seconds: float = 2.0
    poll_max_seconds: float = 8.0

    host: str = "127.0.0.1"
    port: int = 8420

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pipeline.db"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.projects_dir.mkdir(parents=True, exist_ok=True)
    return s
