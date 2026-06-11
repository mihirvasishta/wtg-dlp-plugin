"""
Rule 1 — Recipient Domain Validation

Checks every To/CC/BCC address against the allowed domains declared in the
DLP partner list.  Any recipient whose domain is NOT listed for any partner
triggers a WARN violation.

This is the primary SafeSend parity check.
"""
from __future__ import annotations
from typing import List

from models import DLPCheckRequest, Violation
from dlp.data_source import PartnerEntry, extract_domain


def check(request: DLPCheckRequest, partners: List[PartnerEntry]) -> List[Violation]:
    """Return violations for recipient addresses on unknown domains."""
    if not partners:
        return []

    # Build a flat set of all allowed domains across every partner
    all_allowed: set[str] = set()
    for p in partners:
        all_allowed.update(p.allowed_domains)

    unknown: List[str] = []
    for addr in request.recipients.all_addresses():
        domain = extract_domain(addr)
        if domain and domain not in all_allowed:
            unknown.append(addr)

    if not unknown:
        return []

    domains_display = ", ".join(sorted({extract_domain(a) for a in unknown}))
    return [
        Violation(
            rule_id="UNKNOWN_DOMAIN",
            severity="warn",
            title="Unregistered recipient domain",
            detail=(
                f"The following recipient domain(s) are not registered for any partner "
                f"on this mailbox: {domains_display}. "
                f"Verify the recipients are correct before sending."
            ),
            affected=unknown,
        )
    ]
