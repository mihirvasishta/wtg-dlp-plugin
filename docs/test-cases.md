# WTG DLP Plugin — Manual Test Cases

**Pre-requisites**
- Manifest deployed to the test shared mailbox via M365 Admin Center
- OWA mailbox policy has `OnSendAddinsEnabled = $true` for the test mailbox
- Railway backend is running — confirm at `https://wtg-dlp-plugin-production.up.railway.app/health`
- DLP list file on Railway matches the mailbox address (filename = `<mailbox>.csv`)
- Open OWA as a user who has delegate/member access to the test shared mailbox
- Compose all test emails **From** the shared mailbox (not your personal mailbox)

**DLP list partners for these tests**

| Partner | Allowed domains |
|---|---|
| Acme Corporation | acmecorp.com |
| Globex Industries | globex.net |
| Brother US | brother.com |
| Contoso Ltd | contoso.com |
| Initech | initech.com |

---

## TC-001 — Clean send, no violations

**What it tests:** Happy path — email passes all checks without interruption.

| Field | Value |
|---|---|
| To | contact@acmecorp.com |
| Subject | Q2 Data Report |
| Body | Please find the Q2 report attached. |
| Attachments | None |

**Expected result:** Email sends immediately with no dialog. No violation dialog appears.

---

## TC-002 — Rule 1: Unknown recipient domain

**What it tests:** Recipient domain is not registered for any partner in the DLP list.

| Field | Value |
|---|---|
| To | someone@unknowncorp.com |
| Subject | Hello |
| Body | Test message. |
| Attachments | None |

**Expected result:**
- Smart Alerts dialog appears before send
- Violation shown: **WARN — Unregistered recipient domain**
- Detail mentions `unknowncorp.com`
- "Send Anyway" button is available (warn, not block)
- "Don't Send" button is available

---

## TC-003 — Rule 1: Multiple unknown domains

**What it tests:** More than one unregistered domain in the recipient list.

| Field | Value |
|---|---|
| To | alice@unknowncorp.com |
| CC | bob@anotherbadcorp.org |
| Subject | Report |
| Body | See attached. |

**Expected result:**
- One UNKNOWN_DOMAIN violation listing both `unknowncorp.com` and `anotherbadcorp.org`

---

## TC-004 — Rule 2: Partner name in subject, wrong recipient domain

**What it tests:** Email references Globex Industries in the subject but is addressed to an Acme contact.

| Field | Value |
|---|---|
| To | contact@acmecorp.com |
| Subject | Globex Industries Q2 Report |
| Body | Please review the attached data. |
| Attachments | None |

**Expected result:**
- WARN — **Partner reference — recipient mismatch**
- Detail: "'Globex Industries' is referenced in subject, but no recipient is on an allowed domain for this partner (globex.net)"

---

## TC-005 — Rule 2: Partner name in body, wrong recipient domain

**What it tests:** Partner name appears in the email body but the recipient is from a different partner.

| Field | Value |
|---|---|
| To | contact@acmecorp.com |
| Subject | Monthly Update |
| Body | Hi team, please find the Globex Industries monthly update for your review. |
| Attachments | None |

**Expected result:**
- WARN — Partner reference mismatch for Globex Industries

---

## TC-006 — Rule 2: Correct partner-recipient pairing (no violation)

**What it tests:** Partner name referenced AND recipient is on that partner's allowed domain — no violation expected.

| Field | Value |
|---|---|
| To | orders@globex.net |
| Subject | Globex Industries Q2 Report |
| Body | Please find the Globex Industries quarterly data attached. |
| Attachments | None |

**Expected result:** Email sends with no dialog.

---

## TC-007 — Rule 2: Two partners mentioned, only one recipient matches

**What it tests:** Body mentions two partner names; recipient matches only one.

| Field | Value |
|---|---|
| To | contact@acmecorp.com |
| Subject | Partner Update |
| Body | This update covers Acme Corporation and Globex Industries accounts. |
| Attachments | None |

**Expected result:**
- No violation for Acme Corporation (recipient is on acmecorp.com ✓)
- WARN for Globex Industries (no globex.net recipient)

---

## TC-008 — Rule 2: Partner name in attachment filename

**What it tests:** Filename alone triggers the partner reference check.

**Attachment to create:** Create any file (e.g. a blank `.txt`) and name it `Globex_Industries_Report.txt`

| Field | Value |
|---|---|
| To | contact@acmecorp.com |
| Subject | Monthly Report |
| Body | Please review. |
| Attachments | `Globex_Industries_Report.txt` |

**Expected result:**
- WARN — Partner reference mismatch for Globex Industries
- Detail mentions `filename 'Globex_Industries_Report.txt'`

---

## TC-009 — Rule 2: Partner name inside attachment content (text file)

**What it tests:** Content scanning finds a partner name inside an uploaded file.

**Attachment to create:** Create a `.txt` file with this exact content:
```
Q2 financial summary for Globex Industries.
Revenue: $4.2M
```
Name it `q2-summary.txt`.

| Field | Value |
|---|---|
| To | contact@acmecorp.com |
| Subject | Q2 Summary |
| Body | See attached. |
| Attachments | `q2-summary.txt` |

**Expected result:**
- WARN — Partner reference mismatch for Globex Industries
- Detail mentions `content of 'q2-summary.txt'`

---

## TC-010 — Rule 3: Blocked file extension

**What it tests:** Attachment with a hard-blocked extension (`.exe`, `.ps1`, etc.) cannot be sent.

**Attachment to create:** Create a blank text file and rename it to `setup.exe` (or `script.ps1`).

| Field | Value |
|---|---|
| To | contact@acmecorp.com |
| Subject | Software |
| Body | Please install. |
| Attachments | `setup.exe` |

**Expected result:**
- **BLOCK** — Blocked attachment type
- Dialog shows ⛔ severity
- **"Send Anyway" button is disabled / absent** — block violations cannot be overridden
- Only "Don't Send" is available

---

## TC-011 — Rule 3: ZIP containing blocked file

**What it tests:** ZIP archive whose member has a blocked extension.

**Attachment to create:** Create a ZIP file containing a file named `malware.exe` (the inner file can be empty — only the name is checked).

| Field | Value |
|---|---|
| To | contact@acmecorp.com |
| Subject | Archive |
| Body | See zip. |
| Attachments | `archive.zip` |

**Expected result:**
- BLOCK — Archive contains blocked file type
- Detail mentions `malware.exe`

---

## TC-012 — Rule 3: Warn on compressed archive

**What it tests:** ZIP attachment without blocked members generates a warning, not a block.

**Attachment to create:** A ZIP file containing only a harmless `.txt` file.

| Field | Value |
|---|---|
| To | contact@acmecorp.com |
| Subject | Data package |
| Body | Compressed files attached. |
| Attachments | `data.zip` |

**Expected result:**
- WARN — Compressed archive attachment
- "Send Anyway" available (warn-only)

---

## TC-013 — Override a warn violation (audit log)

**What it tests:** User consciously overrides a warn violation; audit log records the decision.

Use the TC-002 setup (unknown recipient domain).

**Steps:**
1. Compose email as per TC-002
2. Click Send → violation dialog appears
3. Open the DLP Violations task pane (button in compose ribbon)
4. Enter your name in the "Your name" field
5. Click **Log: Send Anyway**
6. Close the task pane; click **Send Anyway** in the native OWA dialog

**Expected result:**
- Email is sent
- Audit log on Railway (`audit/audit.ndjson`) contains an entry with `"decision": "sent_with_override"` and your name

---

## TC-014 — Cancel on warn violation (audit log)

**What it tests:** User chooses not to send after seeing violations.

Use the TC-004 setup (partner name in subject, wrong recipient).

**Steps:**
1. Compose and click Send → violation dialog appears
2. Click **Don't Send**

**Expected result:**
- Email is NOT sent; compose window stays open
- Audit log records `"decision": "cancelled"` (if task pane log button was also clicked)

---

## TC-015 — Fail-open: backend unreachable

**What it tests:** If the DLP backend is down, email is never blocked.

**Setup:** Temporarily pause the Railway service (Railway dashboard → service → Pause), or change `DLP_BACKEND_URL` in `launchevent.js` to a bad URL, redeploy, and reload OWA.

| Field | Value |
|---|---|
| To | anyone@anywhere.com |
| Subject | Test |
| Body | Test |

**Expected result:**
- Email sends without any dialog (fail-open behaviour)
- No error shown to the analyst

**Restore:** Unpause the Railway service and reload OWA.

---

## TC-016 — Multiple violations in one email

**What it tests:** All three rule categories fire simultaneously.

**Attachment to create:** A `.txt` file named `Globex_Q2.txt` containing the text `Globex Industries quarterly data`.

| Field | Value |
|---|---|
| To | someone@unknowncorp.com |
| Subject | Globex Industries Report |
| Body | See Globex Industries data attached. |
| Attachments | `Globex_Q2.txt` |

**Expected result:**
- WARN — Unregistered recipient domain (`unknowncorp.com`)
- WARN — Partner reference mismatch for Globex Industries (found in subject, body, filename, and file content)
- All violations displayed in the dialog

---

## Test Result Log

| TC | Description | Pass / Fail | Notes |
|---|---|---|---|
| TC-001 | Clean send | | |
| TC-002 | Unknown domain | | |
| TC-003 | Multiple unknown domains | | |
| TC-004 | Partner in subject, wrong recipient | | |
| TC-005 | Partner in body, wrong recipient | | |
| TC-006 | Correct pairing — no violation | | |
| TC-007 | Two partners, one unmatched | | |
| TC-008 | Partner in filename | | |
| TC-009 | Partner in text file content | | |
| TC-010 | Blocked extension | | |
| TC-011 | ZIP with blocked member | | |
| TC-012 | Warn on archive | | |
| TC-013 | Override warn + audit log | | |
| TC-014 | Cancel on warn | | |
| TC-015 | Fail-open | | |
| TC-016 | Multiple violations | | |
