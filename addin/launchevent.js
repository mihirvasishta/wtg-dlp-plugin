/*
 * WTG DLP Plugin — Smart Alerts event handler
 *
 * Triggered by OnMessageSend (compose mode, OWA).
 * Collects email data, calls the DLP backend, and either:
 *   - Allows send (no violations or backend unreachable)
 *   - Prompts user with violation summary (warn-level violations)
 *   - Blocks send (block-level violations)
 *
 * Plain JS — no TypeScript or webpack needed for prototype.
 * Requirement sets: Mailbox 1.8 (getAttachmentContentAsync), 1.12 (Smart Alerts)
 */

/* =========================================================================
   Configuration
   =========================================================================
   Replace the URLs below with your actual backend URL before deployment.

   Railway:  https://your-project.up.railway.app
   Bastion:  https://dlp.wisetechglobal.internal:8443

   Do a global find-and-replace on "https://BACKEND_URL" across both
   launchevent.js and taskpane.js, and on "BASTION_HOSTNAME:BASTION_PORT"
   in manifest.xml.
   ========================================================================= */

var DLP_BACKEND_URL  = "https://wtg-dlp-plugin-production.up.railway.app/api/dlp/check";
var AUDIT_BACKEND_URL = "https://wtg-dlp-plugin-production.up.railway.app/api/audit/log";
var FETCH_TIMEOUT_MS = 8000;  // fail-open after 8 s


/* =========================================================================
   Office.js initialisation
   ========================================================================= */

Office.onReady(function () {
  // Associate the handler with the action name declared in manifest.xml
  Office.actions.associate("onMessageSendHandler", onMessageSendHandler);
});


/* =========================================================================
   Main event handler
   ========================================================================= */

function onMessageSendHandler(event) {
  collectEmailData()
    .then(function (payload) {
      return callDlpBackend(payload);
    })
    .then(function (result) {
      handleDlpResult(event, result);
    })
    .catch(function (err) {
      // Any uncaught error → fail open so send is never blocked by a bug
      console.error("[WTG DLP] Unexpected error — failing open:", err);
      event.completed({ allowEvent: true });
    });
}


/* =========================================================================
   Data collection helpers
   ========================================================================= */

/**
 * Collect all email data from the compose item.
 * Returns a Promise<payload object> suitable for JSON.stringify.
 */
function collectEmailData() {
  var item = Office.context.mailbox.item;

  return Promise.all([
    getRecipientsAsync(item.to, "to"),
    getRecipientsAsync(item.cc, "cc"),
    getRecipientsAsync(item.bcc, "bcc"),
    getSubjectAsync(item),
    getBodyTextAsync(item),
    getAttachmentsWithContent(item),
  ]).then(function (results) {
    var to          = results[0];
    var cc          = results[1];
    var bcc         = results[2];
    var subject     = results[3];
    var bodyText    = results[4];
    var attachments = results[5];

    var mailboxAddress = Office.context.mailbox.userProfile
      ? Office.context.mailbox.userProfile.emailAddress
      : "";

    return {
      mailbox_address: mailboxAddress,
      sender_upn: mailboxAddress,
      recipients: { to: to, cc: cc, bcc: bcc },
      subject: subject,
      body_text: bodyText,
      attachments: attachments,
    };
  });
}

/** Resolve recipient field to an array of email address strings. */
function getRecipientsAsync(recipientField, fieldName) {
  return new Promise(function (resolve) {
    if (!recipientField) {
      resolve([]);
      return;
    }
    recipientField.getAsync(function (asyncResult) {
      if (asyncResult.status === Office.AsyncResultStatus.Succeeded) {
        var addresses = (asyncResult.value || []).map(function (r) {
          return r.emailAddress || "";
        }).filter(Boolean);
        resolve(addresses);
      } else {
        console.warn("[WTG DLP] Could not read " + fieldName + ":", asyncResult.error);
        resolve([]);
      }
    });
  });
}

/** Resolve subject to a string. */
function getSubjectAsync(item) {
  return new Promise(function (resolve) {
    item.subject.getAsync(function (asyncResult) {
      if (asyncResult.status === Office.AsyncResultStatus.Succeeded) {
        resolve(asyncResult.value || "");
      } else {
        resolve("");
      }
    });
  });
}

/** Extract body as plain text (strips HTML). */
function getBodyTextAsync(item) {
  return new Promise(function (resolve) {
    item.body.getAsync(Office.CoercionType.Text, function (asyncResult) {
      if (asyncResult.status === Office.AsyncResultStatus.Succeeded) {
        resolve(asyncResult.value || "");
      } else {
        resolve("");
      }
    });
  });
}

/**
 * Collect attachment metadata + Base64 content for each directly uploaded file.
 * OneDrive/SharePoint link attachments return no content (handled gracefully).
 */
function getAttachmentsWithContent(item) {
  var attachments = item.attachments || [];

  if (!attachments || attachments.length === 0) {
    return Promise.resolve([]);
  }

  var contentPromises = attachments.map(function (att) {
    return getAttachmentContentAsync(item, att.id).then(function (b64) {
      return {
        name: att.name || "",
        content_type: att.contentType || "",
        size_bytes: att.size || 0,
        content_b64: b64,  // null if not available (OneDrive links etc.)
      };
    });
  });

  return Promise.all(contentPromises);
}

/** Fetch Base64 content for one attachment. Returns null on failure. */
function getAttachmentContentAsync(item, attachmentId) {
  return new Promise(function (resolve) {
    // getAttachmentContentAsync requires requirement set 1.8
    if (!item.getAttachmentContentAsync) {
      resolve(null);
      return;
    }
    item.getAttachmentContentAsync(attachmentId, function (asyncResult) {
      if (
        asyncResult.status === Office.AsyncResultStatus.Succeeded &&
        asyncResult.value &&
        asyncResult.value.format === Office.MailboxEnums.AttachmentContentFormat.Base64
      ) {
        resolve(asyncResult.value.content);
      } else {
        // Cloud attachment or error — no content available
        resolve(null);
      }
    });
  });
}


/* =========================================================================
   Backend call
   ========================================================================= */

/**
 * POST the email payload to the DLP backend.
 * Returns the parsed JSON response, or a synthetic allow=true response on
 * network error / timeout (fail-open).
 */
function callDlpBackend(payload) {
  var controller = new AbortController();
  var timeoutId = setTimeout(function () { controller.abort(); }, FETCH_TIMEOUT_MS);

  return fetch(DLP_BACKEND_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: controller.signal,
  })
    .then(function (response) {
      clearTimeout(timeoutId);
      if (!response.ok) {
        throw new Error("DLP backend returned HTTP " + response.status);
      }
      return response.json();
    })
    .catch(function (err) {
      clearTimeout(timeoutId);
      console.warn("[WTG DLP] Backend unreachable — failing open:", err);
      return { allow: true, violations: [] };
    });
}


/* =========================================================================
   Result handling
   ========================================================================= */

/**
 * Inspect the DLP result and call event.completed() appropriately.
 *
 * - No violations            → allow send
 * - Warn violations only     → show native Smart Alerts dialog (PromptUser)
 * - Any block violation      → show dialog, send is hard-blocked
 */
function handleDlpResult(event, result) {
  var violations = result.violations || [];

  if (violations.length === 0) {
    // Clean send — no DLP issues
    logDecision(event._item, violations, "sent_clean");
    event.completed({ allowEvent: true });
    return;
  }

  var hasBlock = violations.some(function (v) { return v.severity === "block"; });

  // Store violations in roaming settings so the task pane can read them
  try {
    Office.context.roamingSettings.set(
      "wtg_dlp_violations",
      JSON.stringify(violations)
    );
    Office.context.roamingSettings.saveAsync(function () {});
  } catch (e) {
    // Non-fatal — task pane won't show detail cards but native dialog still shows
    console.warn("[WTG DLP] Could not save roaming settings:", e);
  }

  var errorMessage = buildDialogMessage(violations, hasBlock);

  if (hasBlock) {
    // Hard block — user cannot override
    event.completed({
      allowEvent: false,
      errorMessage: errorMessage,
      // No sendModeOverride → OWA only shows "Don't Send", no "Send Anyway"
    });
  } else {
    // Warn only — user can choose to send anyway
    event.completed({
      allowEvent: false,
      errorMessage: errorMessage,
      sendModeOverride: Office.MailboxEnums.SendModeOverride.PromptUser,
    });
  }
}

/**
 * Build the markdown string shown in the native Smart Alerts dialog.
 * OWA renders this as formatted text inside the dialog body.
 */
function buildDialogMessage(violations, hasBlock) {
  var header = hasBlock
    ? "**⛔ DLP Policy — Send Blocked**"
    : "**⚠️ DLP Policy Warning**";

  var lines = [header, ""];

  violations.forEach(function (v) {
    var icon = v.severity === "block" ? "⛔" : "⚠️";
    lines.push(icon + " **" + v.title + "**");
    lines.push(v.detail);
    lines.push("");
  });

  if (!hasBlock) {
    lines.push(
      "_Select **Send Anyway** to override these warnings, or **Don't Send** to revise the email._"
    );
    lines.push("_Select **Review Details** in the add-in task pane for more information._");
  } else {
    lines.push(
      "_This email cannot be sent. Remove the blocked content and try again._"
    );
  }

  return lines.join("\n");
}


/* =========================================================================
   Audit logging (fire-and-forget)
   ========================================================================= */

/**
 * Send an audit record to the backend.
 * Called after a clean send; for overrides / cancellations the task pane
 * calls the audit endpoint directly when the analyst clicks "Send Anyway"
 * or "Don't Send" in the native dialog.
 *
 * Note: for clean sends, Office fires onMessageSend before the message is
 * actually dispatched, so we log the intent here.
 */
function logDecision(item, violations, decision) {
  if (!AUDIT_BACKEND_URL || AUDIT_BACKEND_URL.indexOf("BASTION_HOSTNAME") !== -1) {
    // Audit endpoint not yet configured — skip silently
    return;
  }

  // For a clean send we don't have full payload here (already sent to DLP
  // backend). Send a minimal record.
  var record = {
    mailbox_address: Office.context.mailbox.userProfile
      ? Office.context.mailbox.userProfile.emailAddress
      : "",
    sender_upn: Office.context.mailbox.userProfile
      ? Office.context.mailbox.userProfile.emailAddress
      : "",
    analyst_name: "",  // not available in event handler; task pane sets this
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
  }).catch(function () {
    // Fire-and-forget — audit failure must never affect send flow
  });
}
