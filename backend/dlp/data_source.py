"""
data_source.py — Abstract DLP data source + CSV implementation for the prototype.

The DLPDataSource interface is designed so that replacing CSVDLPSource with
RDMDLPSource (Phase 2) requires no changes to the DLP engine or rules.
"""
from __future__ import annotations
import csv
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List


# ---------------------------------------------------------------------------
# Shared data model
# ---------------------------------------------------------------------------

@dataclass
class PartnerEntry:
    """One row in the DLP list: a partner name and its allowed contact domains."""
    partner_name: str
    allowed_domains: List[str] = field(default_factory=list)   # normalised bare domains


# ---------------------------------------------------------------------------
# Domain normalisation utility (shared across all rule modules)
# ---------------------------------------------------------------------------

def extract_domain(value: str) -> str:
    """
    Normalise a contact value to a bare lowercase domain.

    RDM (and CSV) may store either:
      - Full email addresses: 'contact@acme.com'  → returns 'acme.com'
      - Bare domains:         'acme.com'           → returns 'acme.com'
    """
    value = value.strip().lower()
    if "@" in value:
        return value.split("@")[-1]
    return value


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class DLPDataSource(ABC):
    @abstractmethod
    async def get_partner_list(self, mailbox_address: str) -> List[PartnerEntry]:
        """Return the partner DLP list for the given shared mailbox address."""
        ...


# ---------------------------------------------------------------------------
# CSV implementation (prototype)
# ---------------------------------------------------------------------------

class CSVDLPSource(DLPDataSource):
    """
    Reads the DLP list from a CSV file at:
        <dlp_list_dir>/<mailbox_address>.csv

    CSV format (header row required):
        partner_name,allowed_contacts
        Acme Corp,"contact@acme.com,acme.co.uk"
        Globex Industries,globex.net

    - The 'allowed_contacts' cell may contain a comma-separated list of
      full email addresses or bare domains.
    - Values are split on commas; each is normalised to a bare domain.
    - In-process cache: file is re-read only if the mtime has changed.
    """

    def __init__(self, dlp_list_dir: str) -> None:
        self._dir = dlp_list_dir
        self._cache: Dict[str, tuple[float, List[PartnerEntry]]] = {}

    def _csv_path(self, mailbox_address: str) -> str:
        safe = mailbox_address.lower().replace("/", "_")
        return os.path.join(self._dir, f"{safe}.csv")

    def _load_csv(self, path: str) -> List[PartnerEntry]:
        entries: List[PartnerEntry] = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("partner_name") or "").strip()
                contacts_raw = (row.get("allowed_contacts") or "").strip()
                if not name:
                    continue
                domains = [
                    extract_domain(c)
                    for c in re.split(r"[,;]+", contacts_raw)
                    if c.strip()
                ]
                entries.append(PartnerEntry(
                    partner_name=name,
                    allowed_domains=domains,
                ))
        return entries

    async def get_partner_list(self, mailbox_address: str) -> List[PartnerEntry]:
        path = self._csv_path(mailbox_address)
        print(f"[dlp] mailbox_address='{mailbox_address}' → csv_path='{path}' exists={os.path.isfile(path)}")
        if not os.path.isfile(path):
            print(f"[dlp] WARNING: no DLP list found for '{mailbox_address}' — returning empty partner list (all checks will pass)")
            return []

        mtime = os.path.getmtime(path)
        cached = self._cache.get(mailbox_address)
        if cached and cached[0] == mtime:
            print(f"[dlp] cache hit for '{mailbox_address}' ({len(cached[1])} partners)")
            return cached[1]

        entries = self._load_csv(path)
        self._cache[mailbox_address] = (mtime, entries)
        print(f"[dlp] loaded {len(entries)} partners from '{path}'")
        return entries
