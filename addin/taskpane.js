/*
 * WTG DLP Plugin — Task Pane JavaScript
 *
 * Reads DLP violations from Office roaming settings (stored by launchevent.js)
 * and renders violation cards. Also lets the analyst log their decision
 * (send_with_override / cancelled) to the audit backend.
 *
 * Plain JS — no TypeScript or webpack needed for prototype.
 */

var AUDIT_BACKEND_URL = "https://wtg-dlp-plugin.lemonhill-d4c8d24d.centralindia.azurecontainerapps.io/api/audit/log";

/* =========================================================================
   Office.js initialisation
   ========================================================================= */

Office.onReady(function (info) {
  if (info.host === Office.HostType.Outlook) {
    renderViolations();
    wireButtons();
  }
});


/* =========================================================================
   Render violations
   ========================================================================= */

function renderViolations() {
  var rawJson = Office.context.roamingSettings.get("wtg_dlp_violations");
  var violations = [];

  if (rawJson) {
    try {
      violations = JSON.parse(rawJson);
    } catch (e) {
      violations = [];
    }
  }

  var banner    = document.getElementById("status-banner");
  var list      = document.getElementById("violations-list");
  var emptyEl   = document.getElementById("empty-state");
  var analystEl = document.getElementById("analyst-section");
  var actionEl  = document.getElementById("action-section");

  if (!violations || violations.length === 0) {
    banner.className = "ok";
    banner.textContent = "✔ No DLP violations detected for this email.";
    banner.style.display = "block";
    emptyEl.style.display = "block";
    return;
  }

  var hasBlock = violations.some(function (v) { return v.severity === "block"; });

  // Status banner
  if (hasBlock) {
    banner.className = "block";
    banner.textContent = "⛔ Send blocked — resolve the issues below before sending.";
  } else {
    banner.className = "warn";
    banner.textContent = "⚠️ " + violations.length + " warning(s) — review before sending.";
  }
  banner.style.display = "block";

  // Violation cards
  violations.forEach(function (v) {
    var card = document.createElement("div");
    card.className = "violation-card " + (v.severity === "block" ? "block" : "warn");

    var header = document.createElement("div");
    header.className = "card-header";

    var badge = document.createElement("span");
    badge.className = "badge " + (v.severity === "block" ? "block" : "warn");
    badge.textContent = v.severity === "block" ? "BLOCK" : "WARN";

    var title = document.createElement("span");
    title.textContent = v.title || v.rule_id;

    header.appendChild(badge);
    header.appendChild(title);
    card.appendChild(header);

    var detail = document.createElement("div");
    detail.className = "card-detail";
    detail.textContent = v.detail || "";
    card.appendChild(detail);

    if (v.affected && v.affected.length > 0) {
      var affectedDiv = document.createElement("div");
      affectedDiv.className = "affected-list";
      v.affected.forEach(function (item) {
        var tag = document.createElement("span");
        tag.textContent = item;
        affectedDiv.appendChild(tag);
      });
      card.appendChild(affectedDiv);
    }

    list.appendChild(card);
  });

  // Show analyst + action controls (buttons disabled for block; enabled for warn)
  analystEl.style.display = "block";
  actionEl.style.display = "block";

  var overrideBtn = document.getElementById("btn-log-override");
  if (hasBlock) {
    overrideBtn.disabled = true;
    overrideBtn.title = "Send is blocked — remove blocked content to send.";
  }
  // Cancel button always enabled
}


/* =========================================================================
   Wire action buttons
   ========================================================================= */

function wireButtons() {
  var overrideBtn     = document.getElementById("btn-log-override");
  var cancelBtn       = document.getElementById("btn-log-cancel");
  var analystInput    = document.getElementById("analyst-name");
  var confirmationMsg = document.getElementById("confirmation-msg");

  // Enable "Send Anyway" only when analyst name is filled in
  analystInput.addEventListener("input", function () {
    var hasName = analystInput.value.trim().length > 0;
    var rawJson = Office.context.roamingSettings.get("wtg_dlp_violations");
    var violations = rawJson ? JSON.parse(rawJson) : [];
    var hasBlock = violations.some(function (v) { return v.severity === "block"; });
    overrideBtn.disabled = hasBlock || !hasName;
  });

  overrideBtn.addEventListener("click", function () {
    logDecision("sent_with_override", analystInput.value.trim(), function () {
      // Clear the override button and show confirmation
      overrideBtn.disabled = true;
      cancelBtn.disabled = true;
      confirmationMsg.style.display = "block";
      // Clear stored violations so next compose starts clean
      Office.context.roamingSettings.remove("wtg_dlp_violations");
      Office.context.roamingSettings.saveAsync(function () {});
    });
  });

  cancelBtn.addEventListener("click", function () {
    logDecision("cancelled", analystInput.value.trim(), function () {
      overrideBtn.disabled = true;
      cancelBtn.disabled = true;
      confirmationMsg.style.display = "block";
      Office.context.roamingSettings.remove("wtg_dlp_violations");
      Office.context.roamingSettings.saveAsync(function () {});
    });
  });
}


/* =========================================================================
   Audit logging
   ========================================================================= */

function logDecision(decision, analystName, callback) {
  if (!AUDIT_BACKEND_URL || AUDIT_BACKEND_URL.indexOf("BASTION_HOSTNAME") !== -1) {
    // Audit not configured — just call the callback
    if (callback) callback();
    return;
  }

  var rawJson = Office.context.roamingSettings.get("wtg_dlp_violations");
  var violations = [];
  try { violations = rawJson ? JSON.parse(rawJson) : []; } catch (e) {}

  var mailboxAddress = Office.context.mailbox.userProfile
    ? Office.context.mailbox.userProfile.emailAddress
    : "";

  var record = {
    mailbox_address: mailboxAddress,
    sender_upn: mailboxAddress,
    analyst_name: analystName,
    recipients: { to: [], cc: [], bcc: [] },
    subject: "",
    body_text: "",
    attachments: [],
    violations: violations,
    decision: decision,
  };

  fetch(AUDIT_BACKEND_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(record),
  })
    .then(function () {
      if (callback) callback();
    })
    .catch(function (err) {
      console.warn("[WTG DLP taskpane] Audit log failed:", err);
      // Still call callback so UI responds even if audit fails
      if (callback) callback();
    });
}
