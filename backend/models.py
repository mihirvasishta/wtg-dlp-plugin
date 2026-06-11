"""
models.py — Pydantic request/response models for the DLP check API.
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inbound request
# ---------------------------------------------------------------------------

class AttachmentPayload(BaseModel):
    name: str
    content_type: str = ""
    size_bytes: int = 0
    content_b64: Optional[str] = None   # Base64-encoded file bytes; None if unavailable


class Recipients(BaseModel):
    to: List[str] = Field(default_factory=list)
    cc: List[str] = Field(default_factory=list)
    bcc: List[str] = Field(default_factory=list)

    def all_addresses(self) -> List[str]:
        return self.to + self.cc + self.bcc


class DLPCheckRequest(BaseModel):
    mailbox_address: str                          # The shared mailbox being sent from
    sender_upn: str = ""                          # The OWA user's UPN (for audit)
    recipients: Recipients
    subject: str = ""
    body_text: str = ""                           # Plain text body (HTML stripped by add-in)
    attachments: List[AttachmentPayload] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Outbound response
# ---------------------------------------------------------------------------

class Violation(BaseModel):
    rule_id: str
    severity: str                   # "warn" | "block"
    title: str
    detail: str
    affected: List[str] = Field(default_factory=list)


class DLPCheckResponse(BaseModel):
    allow: bool                     # True = no block-level violations; False = at least one block
    violations: List[Violation] = Field(default_factory=list)
