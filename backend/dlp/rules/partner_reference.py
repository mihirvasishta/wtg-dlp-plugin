"""
Rule 2 — Partner Reference vs. Recipient Domain Mismatch

For each partner in the DLP list, checks whether the partner name appears
anywhere in the email (subject, body, attachment filenames, or extracted
attachment text).  If a reference is found but NO recipient address belongs
to that partner's allowed domains, a WARN violation is raised.

This catches the scenario where an analyst writes "Acme Corp report" in the
subject/body but accidentally addresses the email to a Globex contact.
"""
from __future__ import annotations
import re
from typing import List, Optional

from models import DLPCheckRequest, Violation
from dlp.data_source import PartnerEntry, extract_domain


def _contains_partner_name(text: str, partner_name: str) -> bool:
    """
    Case-insensitive search for partner_name in text.

    Spaces in the partner name are matched flexibly against common
    filename and text separators (space, underscore, hyphen, dot) so
    that "Globex Industries" matches all of:
      - "Globex Industries"   (subject / body text)
      - "Globex_Industries"   (filename with underscores)
      - "Globex-Industries"   (filename with hyphens)
      - "Globex.Industries"   (filename with dots)
    """
    if not text or not partner_name:
        return False
    # Escape each word individually, then join with a flexible separator
    parts = [re.escape(word) for word in partner_name.split()]
    pattern = r"[\s_\-\.]+".join(parts)
    return bool(re.search(pattern, text, re.IGNORECASE))


def _recipient_on_partner_domain(
    all_addresses: List[str],
    partner: PartnerEntry,
) -> bool:
    """Return True if at least one recipient is on one of the partner's allowed domains."""
    partner_domains = set(partner.allowed_domains)
    return any(extract_domain(addr) in partner_domains for addr in all_addresses)


def check(
    request: DLPCheckRequest,
    partners: List[PartnerEntry],
    attachment_texts: Optional[List[str]] = None,
) -> List[Violation]:
    """
    Return violations for partner-name references that don't match the recipients.

    attachment_texts: list of plain-text strings extracted from each attachment,
                      in the same order as request.attachments. Pass None if
                      attachment extraction has not been performed.
    """
    if not partners:
        return []

    attachment_texts = attachment_texts or []
    all_addresses = request.recipients.all_addresses()
    violations: List[Violation] = []

    for partner in partners:
        # --- Search for partner name in subject --------------------------
        found_in = []
        if _contains_partner_name(request.subject, partner.partner_name):
            found_in.append("subject")

        # --- Search in body text -----------------------------------------
        if _contains_partner_name(request.body_text, partner.partner_name):
            found_in.append("email body")

        # --- Search in attachment filenames ------------------------------
        for att in request.attachments:
            if _contains_partner_name(att.name, partner.partner_name):
                found_in.append(f"filename '{att.name}'")
                break

        # --- Search in extracted attachment text -------------------------
        for idx, text in enumerate(attachment_texts):
            if _contains_partner_name(text, partner.partner_name):
                att_name = (
                    request.attachments[idx].name
                    if idx < len(request.attachments)
                    else f"attachment {idx + 1}"
                )
                found_in.append(f"content of '{att_name}'")

        if not found_in:
            continue  # Partner not mentioned anywhere — skip

        # Partner name IS referenced — now check if any recipient matches
        if _recipient_on_partner_domain(all_addresses, partner):
            continue  # At least one recipient is on an allowed domain — OK

        allowed_display = ", ".join(partner.allowed_domains) or "none configured"
        found_display = ", ".join(found_in)

        violations.append(
            Violation(
                rule_id="PARTNER_MISMATCH",
                severity="warn",
                title="Partner reference — recipient mismatch",
                detail=(
                    f"'{partner.partner_name}' is referenced in {found_display}, "
                    f"but no recipient is on an allowed domain for this partner "
                    f"({allowed_display}). "
                    f"Check that you are sending to the correct recipients."
                ),
                affected=[partner.partner_name],
            )
        )

    return violations
