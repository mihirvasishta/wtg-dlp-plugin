"""
audit/logger.py — Append-only NDJSON audit log.

Each DLP check that results in a send, override, or cancel is logged as
one JSON object per line in audit/audit.ndjson.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List


def _ensure_log_dir(path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def log_check(
    *,
    audit_log_path: str,
    mailbox_address: str,
    sender_upn: str,
    analyst_name: str = "",
    recipients: Dict[str, List[str]],
    subject: str,
    attachment_names: List[str],
    violations: List[Dict[str, Any]],
    decision: str,          # "sent_clean" | "sent_with_override" | "cancelled" | "blocked"
) -> None:
    """
    Append one audit record to the NDJSON log file.

    decision values:
      "sent_clean"         — no violations, add-in allowed send
      "sent_with_override" — warn-level violations, user chose Send Anyway
      "cancelled"          — user chose Don't Send after seeing violations
      "blocked"            — block-level violation prevented send
    """
    _ensure_log_dir(audit_log_path)

    record: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mailbox": mailbox_address,
        "sender_upn": sender_upn,
        "analyst_name": analyst_name,
        "recipients": recipients,
        "subject": subject,
        "attachments": attachment_names,
        "violations": violations,
        "decision": decision,
    }

    with open(audit_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
