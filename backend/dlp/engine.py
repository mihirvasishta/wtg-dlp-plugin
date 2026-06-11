"""
DLP Engine — orchestrates all three rule modules and returns a DLPCheckResponse.

Pipeline order:
  1. attachments.check()  → (attachment_violations, extracted_texts)
  2. recipient_domains.check() → domain violations
  3. partner_reference.check() → mismatch violations (uses extracted_texts from step 1)

allow = True  iff no violation has severity == "block"
"""
from __future__ import annotations

from typing import List

from models import DLPCheckRequest, DLPCheckResponse, Violation
from dlp.data_source import DLPDataSource
from dlp.rules import attachments, recipient_domains, partner_reference


async def run_checks(
    request: DLPCheckRequest,
    data_source: DLPDataSource,
) -> DLPCheckResponse:
    """
    Run all DLP rules and return a combined response.

    Parameters
    ----------
    request     : validated DLPCheckRequest from the API layer
    data_source : DLPDataSource implementation (CSVDLPSource for prototype,
                  RDMDLPSource for production)
    """
    all_violations: List[Violation] = []

    # --- Step 1: Attachment inspection (tiers 1-6) -----------------------
    # Also extracts plain text from each attachment for use in Rule 2.
    attachment_violations, extracted_texts = attachments.check(request.attachments)
    all_violations.extend(attachment_violations)

    # --- Load partner list for this mailbox ------------------------------
    partners = await data_source.get_partner_list(request.mailbox_address)

    # --- Step 2: Recipient domain validation (Rule 1) --------------------
    domain_violations = recipient_domains.check(request, partners)
    all_violations.extend(domain_violations)

    # --- Step 3: Partner-reference vs. recipient mismatch (Rule 2) -------
    mismatch_violations = partner_reference.check(
        request, partners, attachment_texts=extracted_texts
    )
    all_violations.extend(mismatch_violations)

    # --- Determine allow flag --------------------------------------------
    # Block if ANY violation is severity "block"; warn-only → allow=True
    blocked = any(v.severity == "block" for v in all_violations)

    return DLPCheckResponse(
        allow=not blocked,
        violations=all_violations,
    )
