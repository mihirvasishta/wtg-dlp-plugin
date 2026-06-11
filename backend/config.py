"""
config.py — Load environment variables from the existing WTG env file.
Reuses the same parsing approach as the existing Graph API scripts.

Deployment contexts
-------------------
Bastion server : reads from /e2open/home/chub/.WTG_Graph_API_Key.env
Railway        : reads from Railway environment variables directly
                 (set them in the Railway dashboard — no env file needed)
Local dev      : reads from a .env file placed in the repo root or backend/
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate the repo root (one level up from this file, which lives in backend/)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent

ENV_FILE_PATH = os.environ.get(
    "WTG_ENV_FILE",
    "/e2open/home/chub/.WTG_Graph_API_Key.env"
)

# ---------------------------------------------------------------------------
# Env file parser (matches existing WTG pattern)
# ---------------------------------------------------------------------------

def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith("'") and s.endswith("'")) or \
       (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    return s


def _load_env_file(path: str) -> None:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Env file not found: {path}")
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[_strip_quotes(key).strip()] = _strip_quotes(value).strip()


# Load on import
try:
    _load_env_file(ENV_FILE_PATH)
except FileNotFoundError:
    # Allow running locally without the env file (values must be set manually)
    pass

# ---------------------------------------------------------------------------
# Exported settings
# ---------------------------------------------------------------------------

CLIENT_ID: str = os.environ.get("CLIENT_ID", "")
TENANT_ID: str = os.environ.get("TENANT_ID", "")
CLIENT_SECRET: str = os.environ.get("CLIENT_SECRET", "")
GRAPH_BASE: str = "https://graph.microsoft.com/v1.0"

# Backend server settings
HOST: str = os.environ.get("DLP_HOST", "0.0.0.0")

# Railway injects PORT; DLP_PORT is used on the bastion.
# Falls back to 8443 for local dev (where TLS is self-managed).
PORT: int = int(os.environ.get("PORT") or os.environ.get("DLP_PORT") or "8443")

# TLS — only needed on the bastion. Railway terminates TLS at its proxy,
# so leave these empty when deploying to Railway.
CERT_PATH: str = os.environ.get("CERT_PATH", "")
KEY_PATH: str = os.environ.get("KEY_PATH", "")

# DLP list directory — default resolves to <repo-root>/config/dlp_lists
# regardless of which directory uvicorn is launched from.
DLP_LIST_DIR: str = os.environ.get(
    "DLP_LIST_DIR",
    str(_REPO_ROOT / "config" / "dlp_lists"),
)

# Audit log — default resolves to <repo-root>/audit/audit.ndjson
# On Railway this resets on redeploy (ephemeral FS). For production,
# override with a mounted volume path or switch to a database writer.
AUDIT_LOG_PATH: str = os.environ.get(
    "AUDIT_LOG_PATH",
    str(_REPO_ROOT / "audit" / "audit.ndjson"),
)

# CORS — allow the OWA origin so the add-in's fetch() calls are accepted
# In production, lock this down to the specific OWA origin
CORS_ORIGINS: list[str] = [
    "https://outlook.office.com",
    "https://outlook.office365.com",
    "https://outlook.live.com",
    # Add internal OWA URL if using on-premises Exchange Online
]
