"""
WTG DLP Plugin — FastAPI backend

Endpoints:
  POST /api/dlp/check   — run DLP rules, return violations
  POST /api/audit/log   — record analyst decision after check

Static files (add-in HTML/JS) are served from ../addin/ so a single process
hosts both the API and the Office add-in assets.

TLS is terminated here via uvicorn ssl_keyfile / ssl_certfile so OWA can
load the add-in over HTTPS from the bastion server.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import config
from models import DLPCheckRequest, DLPCheckResponse, Violation
from dlp.data_source import CSVDLPSource
from dlp.engine import run_checks
from audit.logger import log_check


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate critical paths exist on startup."""
    dlp_dir = Path(config.DLP_LIST_DIR)
    audit_dir = Path(config.AUDIT_LOG_PATH).parent

    if not dlp_dir.exists():
        dlp_dir.mkdir(parents=True, exist_ok=True)

    audit_dir.mkdir(parents=True, exist_ok=True)

    print(f"[startup] DLP list directory : {dlp_dir.resolve()}")
    print(f"[startup] Audit log          : {Path(config.AUDIT_LOG_PATH).resolve()}")
    print(f"[startup] CORS origins       : {config.CORS_ORIGINS}")
    yield


# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------

app = FastAPI(
    title="WTG DLP Plugin Backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ---------------------------------------------------------------------------
# Shared data source instance (one CSV-backed source; swap for RDMDLPSource later)
# ---------------------------------------------------------------------------

_data_source = CSVDLPSource(dlp_list_dir=config.DLP_LIST_DIR)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/api/dlp/check", response_model=DLPCheckResponse)
async def dlp_check(request: DLPCheckRequest):
    """
    Run DLP checks for a composed email.

    Called by the Office add-in launchevent.js immediately before send.
    Returns violations and an allow flag.
    """
    try:
        att_names = [a.name for a in request.attachments]
        print(f"[api] /dlp/check mailbox='{request.mailbox_address}' to={request.recipients.to} subject='{request.subject[:60]}' attachments={att_names}")
        response = await run_checks(request, _data_source)
        print(f"[api] result: allow={response.allow} violations={[v.rule_id for v in response.violations]}")
        return response
    except FileNotFoundError:
        # No CSV found for this mailbox — fail open with a single warn
        return DLPCheckResponse(
            allow=True,
            violations=[
                Violation(
                    rule_id="DLP_LIST_NOT_FOUND",
                    severity="warn",
                    title="DLP list not configured",
                    detail=(
                        f"No DLP partner list is configured for mailbox "
                        f"'{request.mailbox_address}'. Contact your administrator."
                    ),
                    affected=[request.mailbox_address],
                )
            ],
        )
    except Exception as exc:
        # Unexpected error — fail open so backend issues never block mail
        print(f"[error] DLP check failed: {exc}")
        return DLPCheckResponse(allow=True, violations=[])


class AuditRequest(DLPCheckRequest):
    """DLPCheckRequest extended with the analyst's final decision."""
    decision: str               # "sent_clean" | "sent_with_override" | "cancelled" | "blocked"
    analyst_name: str = ""      # free-text from the task pane UI
    violations: List[Violation] = []  # echoed back from the /check response


@app.post("/api/audit/log", status_code=204)
async def audit_log(body: AuditRequest):
    """
    Record the analyst's decision after a DLP check.

    Called by the task pane when the analyst clicks Send Anyway / Don't Send.
    Returns 204 No Content.
    """
    print(f"[audit] decision='{body.decision}' analyst='{body.analyst_name}' mailbox='{body.mailbox_address}' violations={[v.rule_id if hasattr(v, 'rule_id') else v.get('rule_id') for v in body.violations]}")
    try:
        log_check(
            audit_log_path=config.AUDIT_LOG_PATH,
            mailbox_address=body.mailbox_address,
            sender_upn=body.sender_upn,
            analyst_name=body.analyst_name,
            recipients={
                "to": body.recipients.to,
                "cc": body.recipients.cc,
                "bcc": body.recipients.bcc,
            },
            subject=body.subject,
            attachment_names=[a.name for a in body.attachments],
            violations=[v if isinstance(v, dict) else v.model_dump() for v in body.violations],
            decision=body.decision,
        )
        print(f"[audit] written to {config.AUDIT_LOG_PATH}")
    except Exception as exc:
        print(f"[audit] ERROR: {exc}")


# ---------------------------------------------------------------------------
# Serve add-in static files
# ---------------------------------------------------------------------------

_addin_dir = Path(__file__).parent.parent / "addin"
if _addin_dir.exists():
    app.mount("/addin", StaticFiles(directory=str(_addin_dir), html=True), name="addin")


# ---------------------------------------------------------------------------
# Health check (useful for bastion monitoring)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug/audit")
async def debug_audit(last: int = 20):
    """
    Return the last N lines of the audit log as JSON.
    Useful on Railway where the filesystem is not directly browsable.
    GET https://<railway-url>/debug/audit?last=20
    """
    audit_path = Path(config.AUDIT_LOG_PATH)
    if not audit_path.exists():
        return {"audit_log_path": str(audit_path.resolve()), "entries": [], "note": "File does not exist yet — no audit records written"}
    import json as _json
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    tail = lines[-last:] if len(lines) > last else lines
    entries = []
    for line in tail:
        try:
            entries.append(_json.loads(line))
        except Exception:
            entries.append({"raw": line})
    return {"audit_log_path": str(audit_path.resolve()), "total_entries": len(lines), "returned": len(entries), "entries": entries}


@app.get("/debug/info")
async def debug_info():
    """
    Returns runtime path info and the list of CSV files found.
    Use this to verify the backend can see the DLP list files.
    GET https://<railway-url>/debug/info
    """
    import glob as _glob
    dlp_dir = Path(config.DLP_LIST_DIR)
    csv_files = [Path(f).name for f in _glob.glob(str(dlp_dir / "*.csv"))]
    return {
        "dlp_list_dir": str(dlp_dir.resolve()),
        "dlp_dir_exists": dlp_dir.exists(),
        "csv_files_found": csv_files,
        "audit_log_path": str(Path(config.AUDIT_LOG_PATH).resolve()),
    }


# ---------------------------------------------------------------------------
# Entry point (uvicorn)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    ssl_kwargs = {}
    if config.CERT_PATH and config.KEY_PATH:
        # Bastion deployment: uvicorn terminates TLS directly
        ssl_kwargs = {
            "ssl_certfile": config.CERT_PATH,
            "ssl_keyfile": config.KEY_PATH,
        }
        print(f"[startup] TLS enabled — cert: {config.CERT_PATH}")
    else:
        # Railway / reverse-proxy deployment: TLS terminated upstream; app runs plain HTTP
        print("[startup] No TLS cert configured — running plain HTTP (expected on Railway)")

    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        **ssl_kwargs,
    )
