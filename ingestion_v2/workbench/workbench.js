(() => {
  "use strict";

  let payload = window.PREPFLOW_REVIEW_DEMO;
  let cases = payload.cases.map((item) => ({ ...item }));
  let selectedIndex = 0;
  let resumableRun = null;
  let selectedNewRunPack = null;
  let selectedIdentityRecordId = null;
  let candidateBuildInFlight = false;
  let candidateBuildError = "";
  let actionInFlight = false;
  let inspection = null;
  let inspectionIndex = 0;

  const labels = {
    approve: "Approve proposal",
    reject: "Reject",
    defer: "Decide later",
    edit_as_new_proposal: "Edit proposal",
    leave_blocked: "Leave blocked",
    exclude_record: "Exclude record",
    create_proposal: "Draft proposal",
    create_new_proposal: "Draft new proposal"
  };

  const statusLabels = {
    needs_proposal: "Needs proposal",
    awaiting_decision: "Awaiting decision",
    deferred: "Deferred",
    rejected: "Rejected",
    awaiting_source_verification: "Verification required",
    approved: "Approved for candidate",
    retained_blocker: "Confirmed blocker",
    excluded_record: "Excluded by decision"
  };

  function formatValue(value) {
    if (Array.isArray(value)) {
      if (value.every((item) => typeof item === "string")) return value.join(", ");
      return value.map((item) => `<div class="choice-row"><b>${escapeHtml(item[0])}</b><span>${escapeHtml(item[1])}</span></div>`).join("");
    }
    return escapeHtml(String(value ?? "Not available"));
  }

  function formatReviewValue(value, item, corrected = false) {
    if (item.field !== "correct_answers" || !Array.isArray(value)) return formatValue(value);
    const choiceByLabel = new Map((item.answer_choice_context || []).map(([label, text]) => [label, text]));
    const uniqueLabels = [...new Set(value)];
    const rows = uniqueLabels.map((label) => {
      const text = choiceByLabel.get(label);
      return `<div class="answer-context-row"><b>${escapeHtml(label)}</b><span>${text ? escapeHtml(text) : "No matching choice was parsed"}</span></div>`;
    }).join("");
    return `<div class="answer-labels"><small>${corrected ? "Corrected answer" : "Broken parsed answer"}</small><strong>${escapeHtml(value.join(", "))}</strong></div>${rows}`;
  }

  function formatQuestionPacket(packet) {
    if (!packet) return "No complete correction proposed";
    const field = (label, value, key) => {
      const changed = packet.changed_fields?.includes(key) ? " packet-field-changed" : "";
      return `<section class="packet-field${changed}"><small>${label}</small><div>${value}</div></section>`;
    };
    const choices = packet.choices?.length
      ? packet.choices.map(([label, text]) => `<div class="choice-row"><b>${escapeHtml(label)}</b><span>${escapeHtml(text)}</span></div>`).join("")
      : "<em>No choices parsed</em>";
    const answers = packet.correct_answers?.length
      ? escapeHtml(packet.correct_answers.join(", "))
      : "<em>No answer key parsed</em>";
    return `<div class="question-packet">${field("Stem", escapeHtml(packet.stem || "No stem parsed"), "stem")}${field("Choices", choices, "choices")}${field("Correct answer(s)", answers, "correct_answers")}${field("Rationale", escapeHtml(packet.rationale || "No rationale parsed"), "rationale")}</div>`;
  }

  function formatCorrectAnswerContext(context) {
    if (!context?.correct_answer_text?.length) return "No answer context available";
    return context.correct_answer_text.map((item) => (
      `${escapeHtml(item.label)} — ${escapeHtml(item.text || "No matching choice was parsed")}`
    )).join("<br>");
  }

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = value;
    return node.innerHTML;
  }

  async function lookupRepairDesk(query) {
    const result = document.getElementById("repair-desk-results");
    const normalized = query.trim();
    if (!normalized) {
      result.textContent = "Enter a full stable ID or numeric suffix.";
      return;
    }
    try {
      const response = await fetch(`/api/repair-desk?q=${encodeURIComponent(normalized)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Repair Desk lookup failed.");
      const rows = payload.matches.map((item) => `<li><b>${escapeHtml(item.question_id)}</b> · ${escapeHtml(item.location)}${item.repair_id ? ` · ${escapeHtml(item.repair_id)}` : ""}${item.finding_id ? ` · ${escapeHtml(item.finding_id)}` : ""}</li>`).join("");
      result.innerHTML = rows ? `<ul>${rows}</ul>` : "No matching stable ID was found in the protected lookup locations.";
      const url = new URL(window.location.href);
      url.searchParams.set("question", normalized);
      window.history.replaceState({}, "", url);
    } catch (error) {
      result.textContent = error.message;
    }
  }

  function chapterLabel(item) {
    const number = item.chapter == null ? "Chapter unknown" : `Chapter ${item.chapter}`;
    return item.chapter_title ? `${number}: ${item.chapter_title}` : number;
  }

  function sourceRecordLabel(item) {
    return item.source_record_id ? ` · source ${item.source_record_id}` : "";
  }

  function renderQueue() {
    const queue = document.getElementById("queue");
    queue.replaceChildren();
    cases.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `queue-item${index === selectedIndex ? " selected" : ""}`;
      button.innerHTML = `<span class="queue-severity"></span><span><b>${escapeHtml(item.question_id.replace("PFQ-synthetic-", "Question "))}</b><small>${escapeHtml(item.damage_type.replaceAll("_", " "))}</small></span><em>${escapeHtml(statusLabels[item.status])}</em>`;
      button.addEventListener("click", () => {
        selectedIndex = index;
        render();
      });
      queue.append(button);
    });
  }

  function renderLocalStatus() {
    const run = payload.run || {};
    const source = payload.pipeline?.source_metadata;
    const sourceLabel = source ? `${source.display_name} · ${run.run_id || "run pending"}` : (run.run_id ? `Current run · ${run.run_id}` : "No active source");
    const candidate = payload.candidate || {};
    const candidateLabel = candidate.state === "built_in_memory"
      ? `New Pack candidate · ${candidate.question_count} questions`
      : run.private_checkpoint ? "Private checkpoint available" : "No new Pack candidate";
    document.getElementById("local-status-source").textContent = sourceLabel;
    document.getElementById("local-status-candidate").textContent = candidateLabel;
  }

  function renderActions(item) {
    const actions = document.getElementById("actions");
    actions.replaceChildren();
    if (["approved", "excluded_record"].includes(item.status)) return;
    const add = (label, style, callback) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.className = style;
      button.disabled = actionInFlight;
      button.addEventListener("click", callback);
      actions.append(button);
    };
    add("Accept and next", "primary", () => {
      if (item.proposal) takeAction(item, "approve");
      else takeDuplicateDisposition(item, "accept_as_is");
    });
    add("Fix question", "secondary", () => openProposalEditor(item));
    add("Exclude", "danger", () => openExcludeMenu(item));
    add("Decide later", "secondary", () => item.proposal ? takeAction(item, "defer") : takeDuplicateDisposition(item, "leave_blocked"));
    if (["needs_proposal", "awaiting_decision", "deferred", "rejected"].includes(item.status)) {
      const source = document.createElement("button");
      source.type = "button";
      source.className = "secondary";
      source.textContent = "Open temporary source page";
      source.addEventListener("click", () => openFindingSource(item));
      source.textContent = "Open source context";
      actions.append(source);
    }
    return;
    if (item.damage_type === "complete_duplicate_record" && item.related_question) {
      if (item.status === "excluded_record") {
        const restore = document.createElement("button");
        restore.type = "button";
        restore.className = "secondary";
        restore.textContent = `Undo exclusion of ${item.disposition.question_id}`;
        restore.addEventListener("click", () => takeDuplicateDisposition(item, "restore_record"));
        actions.append(restore);
        return;
      }
      [item, item.related_question].forEach((record) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "danger";
        button.textContent = `Exclude ${record.question_id}`;
        button.addEventListener("click", () => takeDuplicateDisposition(item, "exclude_record", record.question_id));
        actions.append(button);
      });
      return;
    }
    item.allowed_actions.filter((action) => labels[action]).forEach((action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = labels[action] || action;
      button.className = action === "approve" ? "primary" : action === "reject" ? "danger" : "secondary";
      button.addEventListener("click", () => {
        if (["create_proposal", "create_new_proposal", "edit_as_new_proposal"].includes(action)) {
          openProposalEditor(item);
        } else {
          takeAction(item, action);
        }
      });
      actions.append(button);
    });
  }

  async function takeDuplicateDisposition(item, action, targetQuestionId = null) {
    try {
      actionInFlight = true;
      document.getElementById("decision-help").textContent = "Saving…";
      renderActions(item);
      const response = await fetch("/api/dispositions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          finding_id: item.finding_id,
          action,
          target_question_id: targetQuestionId
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Duplicate decision was rejected.");
      acceptEnginePayload(result);
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    } finally {
      actionInFlight = false;
    }
  }

  function openProposalEditor(item) {
    const dialog = document.getElementById("proposal-dialog");
    delete dialog.dataset.identityRepair;
    delete dialog.dataset.identityRecordId;
    dialog.dataset.findingId = item.finding_id;
    dialog.dataset.findingField = item.field;
    dialog.dataset.questionId = item.question_id;
    const value = item.proposal?.proposed_value ?? item.preserved_value;
    dialog.dataset.valueType = typeof value === "string" ? "text" : "json";
    document.getElementById("proposal-value").value = typeof value === "string"
      ? value
      : JSON.stringify(value, null, 2);
    document.getElementById("proposal-reason").value = "Operator field correction.";
    document.getElementById("proposal-verification").checked = false;
    const picker = document.getElementById("answer-choice-picker");
    const select = document.getElementById("answer-choice-select");
    picker.hidden = item.field !== "correct_answers";
    select.replaceChildren();
    if (item.field === "correct_answers") {
      (item.answer_choice_context || []).forEach(([label, text]) => {
        const option = document.createElement("option");
        option.value = label;
        option.textContent = `${label} — ${text}`;
        option.selected = (item.preserved_value || []).includes(label);
        select.append(option);
      });
      select.addEventListener("change", () => { document.getElementById("proposal-value").value = select.value; }, { once: true });
    }
    document.getElementById("proposal-error").textContent = "";
    dialog.showModal();
  }

  function openIdentityRepairEditor(item) {
    const dialog = document.getElementById("proposal-dialog");
    dialog.dataset.identityRecordId = item.record_id;
    dialog.dataset.valueType = "text";
    dialog.dataset.identityRepair = "true";
    document.getElementById("proposal-value").value = item.parsed_stem || "";
    document.getElementById("proposal-reason").value = "Verified against temporary source page.";
    document.getElementById("proposal-verification").checked = true;
    document.getElementById("proposal-verification").disabled = true;
    document.getElementById("proposal-error").textContent = "This repair requires source verification and explicit approval after identity review.";
    dialog.showModal();
  }

  document.getElementById("proposal-cancel").addEventListener("click", () => {
    const dialog = document.getElementById("proposal-dialog");
    delete dialog.dataset.identityRepair;
    delete dialog.dataset.identityRecordId;
    document.getElementById("proposal-verification").disabled = false;
    dialog.close();
  });

  document.getElementById("proposal-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const dialog = document.getElementById("proposal-dialog");
    const errorNode = document.getElementById("proposal-error");
    try {
      const rawValue = document.getElementById("proposal-value").value;
      const proposedAfter = dialog.dataset.valueType === "text"
        ? rawValue
        : dialog.dataset.findingField === "correct_answers" ? [document.getElementById("answer-choice-select").value] : JSON.parse(rawValue);
      const identityRepair = dialog.dataset.identityRepair === "true";
      const response = await fetch(identityRepair ? "/api/identity/repairs" : "/api/proposals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          finding_id: dialog.dataset.findingId,
          record_id: dialog.dataset.identityRecordId,
          field: "stem",
          proposed_after: proposedAfter,
          explanation: document.getElementById("proposal-reason").value,
          requires_source_verification: document.getElementById("proposal-verification").checked
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Proposal was rejected.");
      if (!identityRepair) {
        const approve = await fetch("/api/actions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ finding_id: dialog.dataset.findingId, action: "approve" }) });
        const approved = await approve.json();
        if (!approve.ok) throw new Error(approved.error || "Fix was saved but could not be accepted.");
        acceptEnginePayload(approved, dialog.dataset.questionId);
      }
      dialog.close();
      delete dialog.dataset.identityRepair;
      delete dialog.dataset.identityRecordId;
      document.getElementById("proposal-verification").disabled = false;
      if (identityRepair) acceptEnginePayload(result);
    } catch (error) {
      errorNode.textContent = error instanceof SyntaxError
        ? "Proposed value must be valid JSON. Text values need quotation marks."
        : error.message;
    }
  });

  async function openFindingSource(item) {
    try {
      const response = await fetch("/api/source-page", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ finding_id: item.finding_id })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Temporary source page is unavailable.");
      const first = result.page_range?.[0] || result.page_number;
      const last = result.page_range?.[1] || result.page_number;
      document.getElementById("source-page-title").textContent = first === last
        ? `Extracted PDF page ${first} of ${result.page_count}`
        : `Extracted PDF context · pages ${first}–${last} of ${result.page_count}`;
      document.getElementById("source-page-text").textContent = result.pages
        ? result.pages.map((page) => `PAGE ${page.page_number}\n\n${page.text}`).join("\n\n════════════════════════════════════════\n\n")
        : result.text;
      document.getElementById("source-dialog").showModal();
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    }
  }

  function openExcludeMenu(item) {
    const actions = document.getElementById("actions");
    actions.replaceChildren();
    [
      ["Duplicate question", "exclude_record"],
      ["Source/parser artifact", "exclude_record"],
    ].forEach(([label, action]) => {
      const button = document.createElement("button");
      button.type = "button"; button.className = "danger"; button.textContent = label;
      button.addEventListener("click", () => takeDuplicateDisposition(item, action));
      actions.append(button);
    });
  }

  async function openIdentitySourceContext(item) {
    try {
      const response = await fetch("/api/identity/source-context", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_id: item.record_id })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Temporary source context is unavailable.");
      const first = result.pages[0]?.page_number;
      const last = result.pages.at(-1)?.page_number;
      document.getElementById("source-page-title").textContent =
        "Extracted PDF context · pages " + first + "–" + last + " of " + result.page_count;
      document.getElementById("source-page-text").textContent = result.pages
        .map((page) => {
          const marker = page.role === "current" ? " ← selected record" : "";
          return "PAGE " + page.page_number + marker + "\n\n" + page.text;
        })
        .join("\n\n════════════════════════════════════════\n\n");
      document.getElementById("source-dialog").showModal();
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    }
  }

  async function takeAction(item, action) {
    if (payload.session?.mode === "synthetic_in_memory") {
      try {
        actionInFlight = true;
        document.getElementById("decision-help").textContent = "Saving…";
        renderActions(item);
        const dispositionAction = action === "leave_blocked" || action === "exclude_record";
        const response = await fetch(dispositionAction ? "/api/dispositions" : "/api/actions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ finding_id: item.finding_id, action })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Engine rejected the action.");
        acceptEnginePayload(result, action === "reject" ? item.question_id : null);
      } catch (error) {
        document.getElementById("decision-help").textContent = error.message;
      } finally {
        actionInFlight = false;
      }
      return;
    }
    if (action === "approve") {
      item.status = item.proposal?.requires_source_verification && !item.source_verification_recorded
        ? "awaiting_source_verification"
        : "approved";
      item.allowed_actions = item.status === "approved"
        ? []
        : ["reject", "leave_blocked"];
    } else if (action === "reject") {
      item.status = "rejected";
      item.allowed_actions = ["leave_blocked", "create_proposal"];
    } else if (action === "defer" || action === "leave_blocked") {
      item.status = "deferred";
      item.allowed_actions = item.proposal ? ["approve", "reject", "edit_as_new_proposal"] : ["create_proposal"];
    } else {
      document.getElementById("decision-help").textContent = "Proposal editing will be wired to the engine in a later slice.";
      return;
    }
    render();
  }

  function renderSummaryCounts(identityCases, blocking) {
    const identity = payload.pipeline?.identity;
    const identityReview = ["identity_review", "identity_matched"].includes(payload.run?.state);
    const set = (countId, labelId, value, label) => {
      document.getElementById(countId).textContent = value;
      document.getElementById(labelId).textContent = label;
    };
    if (identityReview && identity?.state !== "not_run") {
      set("case-count", "case-count-label", identity.unresolved_count, "questions need review");
      set("blocking-count", "blocking-count-label", identity.matched_count, "stable IDs retained");
      set("verified-count", "verified-count-label", identity.review_approved_count, "review decisions saved");
      set("summary-tail-count", "summary-tail-label", "New v2", "replacement Pack");
      return;
    }
    set("case-count", "case-count-label", cases.length, "review cases");
    set("blocking-count", "blocking-count-label", blocking, "blocking");
    set(
      "verified-count",
      "verified-count-label",
      cases.filter((entry) => entry.source_verification_recorded).length,
      "source verified"
    );
    set("summary-tail-count", "summary-tail-label", "Locked", "canonical promotion");
  }

  function render() {
    renderLocalStatus();
    const item = cases[selectedIndex];
    const identityCases = payload.pipeline?.identity?.review_cases || [];
    // Advance past deliberately unresolved cases while any untouched cases
    // remain. Once all cases have a decision, keep one visible for review.
    const unresolvedIdentity = identityCases.filter((entry) => ["pending", "defer"].includes(entry.status));
    const legacyDetails = document.getElementById("legacy-details");
    legacyDetails.hidden = unresolvedIdentity.length === 0;
    document.getElementById("legacy-details-text").textContent = unresolvedIdentity.length
      ? `${unresolvedIdentity.length} record(s) need a stable-ID migration decision. Legacy content is not used to change this new v2 question.`
      : "";
    const identityCase = unresolvedIdentity.find((entry) => entry.record_id === selectedIdentityRecordId)
      || unresolvedIdentity[0]
      || identityCases.find((entry) => entry.record_id === selectedIdentityRecordId)
      || identityCases[0];
    const blocking = cases.filter((entry) => entry.severity === "blocking" && !["approved", "excluded_record"].includes(entry.status)).length;
    renderSummaryCounts(identityCases, blocking);
    document.getElementById("queue-position").textContent = payload.run?.state === "identity_review"
      ? `Question ${Math.max(1, unresolvedIdentity.findIndex((entry) => entry.record_id === identityCase?.record_id) + 1)} of ${unresolvedIdentity.length}`
      : `Question ${selectedIndex + 1} of ${cases.length}`;
    renderRun();
    renderCandidate();
    if (!item) {
      const identityPending = payload.run?.state === "identity_pending";
      const identityReview = ["identity_review", "identity_matched"].includes(payload.run?.state);
      const failed = payload.run?.state === "failed";
      if (payload.run?.state === "identity_review" && identityCase) {
        renderIdentityCase(identityCase);
        return;
      }
      document.getElementById("queue-position").textContent = "0 / 0";
      document.getElementById("question-meta").textContent = failed ? "PDF INTAKE FAILED" : identityReview ? "IDENTITY ASSESSMENT COMPLETE" : identityPending ? "PDF FRONT-HALF COMPLETE" : "START A RUN";
      document.getElementById("damage-title").textContent = failed ? "Controlled cleanup required" : identityReview ? "Stable IDs remain guarded" : identityPending ? "Stable identity decision required" : "No review cases loaded";
      document.getElementById("status-pill").textContent = "Waiting";
      document.getElementById("finding-explanation").textContent = failed
        ? `The run stopped safely with code ${payload.run.failure_code}. Use Cancel and clean run before retrying.`
        : identityReview
        ? `${payload.pipeline.identity.matched_count} unique exact match(es); ${payload.pipeline.identity.finding_count} parsed record(s) and ${payload.pipeline.identity.target_only_count} Pack record(s) still require identity review. No uncertain IDs were assigned.`
        : identityPending
        ? `${payload.run.parsed_records} record(s) parsed with ${payload.run.parser_findings} parser finding(s). Choose new Pack or existing-Pack re-import before assigning stable IDs.`
        : "Start the private synthetic run to process its disposable document copy.";
      document.getElementById("preserved-value").textContent = "No record";
      document.getElementById("proposed-value").textContent = "No proposal";
      document.getElementById("proposal-explanation").textContent = "The parser and review queue have not run.";
      document.getElementById("verification-card").hidden = true;
      document.getElementById("actions").replaceChildren();
      renderQueue();
      return;
    }
    document.getElementById("question-meta").textContent = `NEW V2 QUESTION · ${item.question_id} · ${chapterLabel(item)}${sourceRecordLabel(item)} · ${item.field}`;
    document.getElementById("damage-title").textContent = item.damage_type.replaceAll("_", " ");
    const pill = document.getElementById("status-pill");
    pill.textContent = statusLabels[item.status];
    pill.dataset.status = item.status;
    document.getElementById("finding-explanation").textContent = item.explanation;
    document.getElementById("preserved-card-label").innerHTML = '<span class="dot amber"></span>New v2 question';
    document.getElementById("proposed-card-label").innerHTML = '<span class="dot blue"></span>Correction to new question';
    document.getElementById("preserved-value").innerHTML = item.preserved_question
      ? formatQuestionPacket(item.preserved_question)
      : formatReviewValue(item.preserved_value, item);
    if (item.damage_type === "complete_duplicate_record" && item.related_question) {
      document.getElementById("proposed-value").innerHTML = `<b>${escapeHtml(item.related_question.question_id)}</b><br>${escapeHtml(chapterLabel(item.related_question))}${escapeHtml(sourceRecordLabel(item.related_question))}<br><br>${escapeHtml(item.related_question.stem)}`;
      document.getElementById("proposal-explanation").textContent = "These are two preserved records. Explicitly choose the stable ID to exclude; the other remains unchanged.";
    } else {
      document.getElementById("proposed-value").innerHTML = item.proposed_question
        ? formatQuestionPacket(item.proposed_question)
        : "No complete correction proposed";
      document.getElementById("proposal-explanation").textContent = item.proposal?.explanation || "The record remains blocked until a justified proposal exists.";
    }
    const verificationCard = document.getElementById("verification-card");
    verificationCard.hidden = item.status !== "awaiting_source_verification";
    renderActions(item);
    renderQueue();
  }

  function renderIdentityCase(item) {
    document.getElementById("preserved-card-label").innerHTML = '<span class="dot amber"></span>New v2 question';
    document.getElementById("proposed-card-label").innerHTML = '<span class="dot blue"></span>Old Pack reference';
    document.getElementById("question-meta").textContent = `NEW V2 QUESTION · ${item.record_id} · ${chapterLabel(item)}`;
    document.getElementById("damage-title").textContent = "Review this new v2 question";
    const pill = document.getElementById("status-pill");
    pill.textContent = item.status === "pending" ? "Review required" : item.status;
    pill.dataset.status = item.status;
    document.getElementById("finding-explanation").textContent = "This new v2 question needs a human decision because its old-Pack reference was not unambiguous. The source PDF remains authoritative.";
    const preserved = document.getElementById("preserved-value");
    preserved.replaceChildren();
    const stem = document.createElement("div");
    stem.textContent = item.parsed_stem || "No question stem was parsed.";
    preserved.append(stem);
    if (item.parsed_choices?.length) {
      const choiceLabel = document.createElement("small");
      choiceLabel.textContent = "Parsed choices";
      preserved.append(choiceLabel);
      item.parsed_choices.forEach(([label, text]) => {
        const row = document.createElement("div");
        row.className = "choice-row";
        const labelNode = document.createElement("b");
        labelNode.textContent = label;
        const textNode = document.createElement("span");
        textNode.textContent = text;
        row.append(labelNode, textNode);
        preserved.append(row);
      });
    }
    if (item.parsed_correct_answers?.length) {
      const answerLabel = document.createElement("small");
      answerLabel.textContent = `Parsed answer: ${item.parsed_correct_answers.join(", ")}`;
      preserved.append(answerLabel);
    } else {
      const missingAnswer = document.createElement("small");
      missingAnswer.textContent = "No answer key was parsed.";
      preserved.append(missingAnswer);
    }
    const proposed = document.getElementById("proposed-value");
    proposed.replaceChildren();
    const select = document.createElement("select");
    select.id = "identity-suggestion-select";
    const preview = document.createElement("div");
    preview.id = "identity-target-preview";
    preview.className = "identity-target-preview";
    item.suggestions.forEach((suggestion) => {
      const option = document.createElement("option");
      option.value = suggestion.target_question_id;
      option.textContent = `${suggestion.target_question_id} · ${Math.round(suggestion.similarity * 100)}% match`;
      option.selected = suggestion.target_question_id === item.selected_target_question_id;
      select.append(option);
    });
    const showSelectedSuggestion = () => {
      const selected = item.suggestions.find((suggestion) => suggestion.target_question_id === select.value);
      preview.textContent = selected?.target_stem || "No suggested existing-Pack question is available.";
    };
    select.addEventListener("change", showSelectedSuggestion);
    proposed.append(select, preview);
    showSelectedSuggestion();
    document.getElementById("proposal-explanation").textContent = "Old Pack reference only. It never replaces this new v2 question’s wording or answer.";
    document.getElementById("verification-card").hidden = true;
    const actions = document.getElementById("actions");
    actions.replaceChildren();
    const source = document.createElement("button");
    source.type = "button";
    source.textContent = "View source context";
    source.className = "secondary";
    source.addEventListener("click", () => openIdentitySourceContext(item));
    actions.append(source);
    if (item.status === "approve") {
      const matched = document.createElement("strong");
      matched.textContent = "Identity matched — field repair remains available.";
      actions.append(matched);
      const repair = document.createElement("button");
      repair.type = "button";
      repair.className = "primary";
      repair.textContent = item.field_repair_staged ? "Edit field repair" : "Create field repair";
      repair.addEventListener("click", () => openIdentityRepairEditor(item));
      actions.append(repair);
      const next = document.createElement("button");
      next.type = "button";
      next.textContent = "Next record";
      next.addEventListener("click", () => { selectedIdentityRecordId = null; render(); });
      actions.append(next);
    }
    [
      ["approve", "Same question", "primary"],
      ["retain_new_question", "Accept new question", "primary"],
      ["exclude_parser_debris", "Exclude source artifact", "danger"],
      ["exclude_duplicate", "Exclude duplicate", "danger"],
      ["defer", "Decide later", "secondary"]
    ].forEach(([action, label, style]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.className = style;
      button.disabled = action === "approve" && !item.suggestions.length;
      button.addEventListener("click", () => takeIdentityAction(item, action, select.value));
      actions.append(button);
    });
    renderQueue();
  }

  async function takeIdentityAction(item, action, targetQuestionId) {
    try {
      const response = await fetch("/api/identity/actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          record_id: item.record_id,
          action,
          target_question_id: action === "approve" ? targetQuestionId : null
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Identity decision was rejected.");
      selectedIdentityRecordId = item.record_id;
      acceptEnginePayload(result);
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    }
  }

  function renderRun() {
    const run = payload.run || { state: "unmanaged_demo" };
    const state = document.getElementById("run-state");
    const artifacts = document.getElementById("run-artifacts");
    const extraction = document.getElementById("run-extraction");
    const cleaning = document.getElementById("run-cleaning");
    const identity = document.getElementById("run-identity");
    const qa = document.getElementById("run-qa");
    const proposals = document.getElementById("run-proposals");
    const start = document.getElementById("start-run-button");
    const complete = document.getElementById("complete-run-button");
    const cleanup = document.getElementById("cleanup-run-button");
    const pdfInput = document.getElementById("pdf-input");
    const pdfButton = document.querySelector("label[for='pdf-input']");
    const identityButtons = document.querySelectorAll(".identity-button");
    const materializeIdentity = document.getElementById("materialize-identity-button");
    document.getElementById("factory-home").hidden = !["not_started", "completed"].includes(run.state);
    state.textContent = run.state.replaceAll("_", " ");
    if (["not_started", "completed"].includes(run.state)) {
      artifacts.textContent = "No disposable source or text artifacts.";
      extraction.textContent = "Extractor has not run.";
      cleaning.textContent = "Cleaner has not run.";
      identity.textContent = "Identity matcher has not run.";
      qa.textContent = "QA detectors have not run.";
      proposals.textContent = "Proposal generator has not run.";
      start.disabled = false;
      pdfInput.disabled = false;
      pdfButton.classList.remove("disabled");
    } else if (run.state === "unmanaged_demo") {
      artifacts.textContent = "Standalone display only; open through the local engine to run stages.";
      extraction.textContent = "Connected extraction metrics unavailable.";
      cleaning.textContent = "Connected cleaning metrics unavailable.";
      identity.textContent = "Identity matcher unavailable.";
      qa.textContent = "QA detectors unavailable.";
      proposals.textContent = "Proposal generator unavailable.";
      start.disabled = true;
      pdfInput.disabled = true;
      pdfButton.classList.add("disabled");
    } else {
      artifacts.textContent = `staged copy: ${run.staged_copy_present ? "present" : "removed"} · raw text: ${run.raw_text_present ? "present" : "removed"} · cleaned text: ${run.cleaned_text_present ? "present" : "removed"}`;
      const extractionMetrics = payload.pipeline?.extraction;
      extraction.textContent = extractionMetrics
        ? `${extractionMetrics.adapter} · ${extractionMetrics.page_count} page(s) · ${extractionMetrics.extracted_characters} characters`
        : "Extractor has not run.";
      const metrics = payload.pipeline?.cleaning;
      cleaning.textContent = metrics
        ? `${metrics.cleaner} · ${metrics.removed_repeated_lines} repeated lines removed · ${metrics.stripped_repeated_suffixes} suffixes removed · ${metrics.protected_repeated_structures} structures protected`
        : "Cleaner has not run.";
      const identityReport = payload.pipeline?.identity;
      identity.textContent = identityReport && identityReport.state !== "not_run"
        ? `${identityReport.matched_count} exact ID match(es) · ${identityReport.finding_count} review finding(s) · ${identityReport.target_only_count} Pack-only record(s)`
        : "Identity matcher has not run.";
      const qaReport = payload.pipeline?.qa;
      qa.textContent = qaReport && qaReport.state !== "not_run"
        ? `${qaReport.finding_count} QA finding(s) · ${qaReport.automatic_repairs} automatic repair(s) · ${qaReport.proposals_created} proposal(s)`
        : "QA detectors have not run.";
      const proposalReport = payload.pipeline?.proposal_generation;
      proposals.textContent = proposalReport?.state === "complete"
        ? `${proposalReport.proposal_count} review proposal(s) · ${proposalReport.automatic_applications} automatic application(s)`
        : "Proposal generator has not run.";
      start.disabled = true;
      pdfInput.disabled = true;
      pdfButton.classList.add("disabled");
    }
    complete.disabled = run.state !== "compared";
    cleanup.disabled = ["not_started", "unmanaged_demo", "completed"].includes(run.state);
    identityButtons.forEach((button) => { button.disabled = run.state !== "identity_pending"; });
    materializeIdentity.disabled = run.state !== "identity_matched";
  }

  function renderCandidate() {
    const candidate = payload.candidate;
    const state = document.getElementById("candidate-state");
    const detail = document.getElementById("candidate-detail");
    const comparisonDetail = document.getElementById("comparison-detail");
    const comparisonChanges = document.getElementById("comparison-changes");
    const button = document.getElementById("candidate-button");
    const comparisonButton = document.getElementById("comparison-button");
    const inspectButton = document.getElementById("inspect-candidate-button");
    if (!candidate || candidate.state === "not_built") {
      state.textContent = "Not built";
      detail.textContent = candidateBuildInFlight
        ? "Building new v2 Pack…"
        : candidateBuildError || "Finish review to build a private new Pack candidate.";
      button.textContent = candidateBuildInFlight ? "Building new v2 Pack…" : "Build new Pack candidate";
      button.disabled = candidateBuildInFlight || payload.session?.mode !== "synthetic_in_memory" || !["review_ready", "candidate_built", "compared", "unmanaged_demo"].includes(payload.run?.state);
      comparisonButton.disabled = true;
      inspectButton.disabled = true;
      comparisonDetail.textContent = "Comparison has not run.";
      comparisonChanges.replaceChildren();
      return;
    }
    state.textContent = `${candidate.question_count} retained questions · ${candidate.applied_proposal_ids.length} fixes applied`;
    detail.textContent = `${candidate.unresolved_finding_ids.length} remaining issue(s) · ${candidate.documented_exclusion_count ?? candidate.excluded_question_ids.length} excluded record(s). Review complete.`;
    button.textContent = candidateBuildInFlight ? "Building new v2 Pack…" : "Rebuild new Pack candidate";
    button.disabled = candidateBuildInFlight || payload.run?.state === "completed";
    comparisonButton.disabled = payload.session?.mode !== "synthetic_in_memory" || payload.run?.state === "completed";
    inspectButton.disabled = false;
    if (payload.comparison?.state === "complete") {
      const identityStatus = payload.comparison.stable_ids_exact ? "stable IDs exact" : "all ID differences documented";
      comparisonDetail.textContent = `Comparison complete · ${identityStatus} · ${payload.comparison.field_change_count} changed field(s).`;
      const contextById = new Map((payload.comparison.question_context || []).map((item) => [item.question_id, item]));
      const groupCards = (payload.comparison.exact_contaminant_groups || []).map((group) => (
        `<section class="contaminant-group-card">
          <b>Exact contaminant group · ${group.match_count} matches</b>
          <code>${escapeHtml(group.contaminant)}</code>
          <small>${group.occurrences.map((item) => `${escapeHtml(item.question_id)} · ${escapeHtml(item.field)}`).join("<br>")}</small>
          <button type="button" data-group-id="${escapeHtml(group.group_id)}">Approve exact group correction</button>
        </section>`
      )).join("");
      const categoryCards = (payload.comparison.review_categories || []).map((category) => (
        `<section class="comparison-category-card" data-category="${escapeHtml(category.classification)}">
          <b>${escapeHtml(category.classification.replaceAll("_", " "))} · ${category.change_count}</b>
          <small>${escapeHtml(category.explanation)}</small>
          <span>${category.changes.slice(0, 6).map((item) => `${escapeHtml(item.question_id)} · ${escapeHtml(item.field)}`).join("<br>")}${category.change_count > 6 ? `<br>…and ${category.change_count - 6} more` : ""}</span>
          <div class="category-actions">
            ${category.allowed_action === "use_reference" ? `<button type="button" data-category-source="${escapeHtml(category.category_id)}">Open source page</button>` : ""}
            <button type="button" data-category-approve="${escapeHtml(category.category_id)}" data-category-action="${escapeHtml(category.allowed_action)}" ${category.decision ? "disabled" : ""}>${category.decision ? "Decision recorded" : category.allowed_action === "accept_candidate" ? "Accept full source title" : "Use clean reference value"}</button>
          </div>
        </section>`
      )).join("");
      const changeCards = payload.comparison.field_changes.map((change) => {
        const context = contextById.get(change.question_id) || {};
        const chapter = context.candidate || context.benchmark || {};
        return `<section class="comparison-change-card">
          <b>${escapeHtml(change.question_id)} · ${escapeHtml(change.field)}</b>
          <small>${escapeHtml(chapterLabel(chapter))}</small>
          <div><em>Broken candidate value</em>${formatValue(change.candidate_value)}</div>
          <div><em>Existing Pack reference</em>${formatValue(change.benchmark_value)}</div>
          <div><em>Candidate correct answer</em>${formatCorrectAnswerContext(context.candidate)}</div>
          <div><em>Reference correct answer</em>${formatCorrectAnswerContext(context.benchmark)}</div>
        </section>`;
      }).join("");
      comparisonChanges.innerHTML = groupCards + categoryCards + changeCards;
      comparisonChanges.querySelectorAll("[data-group-id]").forEach((groupButton) => {
        groupButton.addEventListener("click", () => approveExactGroup(groupButton.dataset.groupId));
      });
      comparisonChanges.querySelectorAll("[data-category-source]").forEach((sourceButton) => {
        sourceButton.addEventListener("click", () => openComparisonSource(sourceButton.dataset.categorySource));
      });
      comparisonChanges.querySelectorAll("[data-category-approve]").forEach((categoryButton) => {
        categoryButton.addEventListener("click", () => approveComparisonCategory(
          categoryButton.dataset.categoryApprove,
          categoryButton.dataset.categoryAction
        ));
      });
      comparisonButton.textContent = "Run comparison again";
    } else {
      comparisonDetail.textContent = "Comparison has not run for this candidate.";
      comparisonChanges.replaceChildren();
      comparisonButton.textContent = "Compare with benchmark";
    }
  }

  function renderInspection() {
    const panel = document.getElementById("candidate-inspection");
    if (!inspection?.questions?.length) { panel.hidden = true; return; }
    panel.hidden = false;
    const question = inspection.questions[inspectionIndex];
    const overview = inspection.overview;
    document.getElementById("candidate-overview").innerHTML = [
      ["Pack", overview.title], ["Chapters", overview.chapter_count], ["Retained", overview.retained_questions],
      ["Excluded", overview.excluded_questions], ["Fixes", overview.applied_fixes], ["Issues", overview.unresolved_blockers],
      ["QA", overview.qa_finding_count], ["Hash", overview.candidate_sha256],
    ].map(([label, value]) => `<span><small>${label}</small><b>${escapeHtml(String(value))}</b></span>`).join("");
    document.getElementById("inspection-position").textContent = `Question ${inspectionIndex + 1} of ${inspection.questions.length}`;
    document.getElementById("candidate-chapters").innerHTML = inspection.chapters.map((chapter) => `<span>Chapter ${chapter.chapter ?? "?"}: ${escapeHtml(chapter.title || "Unnamed")} · ${chapter.question_count}</span>`).join("<br>") + (inspection.warnings.length ? `<p>Warnings: ${escapeHtml(inspection.warnings.join(", "))}</p>` : "");
    document.getElementById("candidate-preview").innerHTML = `<p><b>${escapeHtml(question.question_id)}</b> · ${escapeHtml(chapterLabel(question))} · ${question.position_in_chapter} in chapter</p>${formatQuestionPacket(question)}`;
    const select = document.getElementById("inspection-chapter");
    if (!select.options.length) {
      inspection.chapters.forEach((chapter) => { const option = document.createElement("option"); option.value = String(chapter.chapter); option.textContent = `Chapter ${chapter.chapter ?? "?"}: ${chapter.title || "Unnamed"}`; select.append(option); });
    }
  }

  async function loadInspection() {
    const response = await fetch("/api/candidate/inspection");
    const result = await response.json();
    if (!response.ok || result.state !== "ready") throw new Error(result.error || "Build a candidate before inspection.");
    inspection = result; inspectionIndex = 0; renderInspection();
  }

  async function approveExactGroup(groupId) {
    try {
      const response = await fetch("/api/comparison/groups/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group_id: groupId })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Exact group correction was rejected.");
      acceptEnginePayload(result);
      document.getElementById("decision-help").textContent = "Exact group correction applied to the isolated candidate; full QA and comparison reran.";
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    }
  }

  async function openComparisonSource(categoryId) {
    try {
      const response = await fetch("/api/comparison/categories/source-page", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: categoryId })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Comparison source page is unavailable.");
      document.getElementById("source-page-title").textContent = `Extracted PDF page ${result.page_number} of ${result.page_count}`;
      document.getElementById("source-page-text").textContent = result.text;
      document.getElementById("source-dialog").showModal();
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    }
  }

  async function approveComparisonCategory(categoryId, action) {
    try {
      const response = await fetch("/api/comparison/categories/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: categoryId, action })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Comparison decision was rejected.");
      acceptEnginePayload(result);
      document.getElementById("decision-help").textContent = "Comparison decision recorded; full QA and comparison reran.";
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    }
  }

  document.getElementById("verify-button").addEventListener("click", () => {
    const item = cases[selectedIndex];
    if (payload.session?.mode === "synthetic_in_memory") {
      fetch("/api/verifications", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ finding_id: item.finding_id })
      })
        .then(async (response) => {
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || "Engine rejected verification.");
          acceptEnginePayload(result);
        })
        .catch((error) => {
          document.getElementById("decision-help").textContent = error.message;
        });
      return;
    }
    item.source_verification_recorded = true;
    item.status = "approved";
    item.allowed_actions = [];
    document.getElementById("decision-help").textContent = "Synthetic verification recorded. No candidate or canonical data changed.";
    render();
  });

  document.getElementById("view-source-button").addEventListener("click", async () => {
    const item = cases[selectedIndex];
    await openFindingSource(item);
  });

  document.getElementById("source-close").addEventListener("click", () => {
    document.getElementById("source-page-text").textContent = "";
    document.getElementById("source-dialog").close();
  });

  document.getElementById("candidate-button").addEventListener("click", async () => {
    if (payload.session?.mode !== "synthetic_in_memory" || candidateBuildInFlight) return;
    candidateBuildInFlight = true;
    candidateBuildError = "";
    renderCandidate();
    try {
      const response = await fetch("/api/candidate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Candidate build failed.");
      candidateBuildInFlight = false;
      acceptEnginePayload(result);
    } catch (error) {
      candidateBuildInFlight = false;
      candidateBuildError = error.message;
      document.getElementById("decision-help").textContent = error.message;
      renderCandidate();
    }
  });

  document.getElementById("inspect-candidate-button").addEventListener("click", () => {
    loadInspection().catch((error) => { document.getElementById("decision-help").textContent = error.message; });
  });
  document.getElementById("inspection-previous").addEventListener("click", () => { if (inspection) { inspectionIndex = Math.max(0, inspectionIndex - 1); renderInspection(); } });
  document.getElementById("inspection-next").addEventListener("click", () => { if (inspection) { inspectionIndex = Math.min(inspection.questions.length - 1, inspectionIndex + 1); renderInspection(); } });
  document.getElementById("inspection-chapter").addEventListener("change", (event) => { if (inspection) { const index = inspection.questions.findIndex((item) => String(item.chapter) === event.target.value); if (index >= 0) { inspectionIndex = index; renderInspection(); } } });
  document.getElementById("inspection-jump").addEventListener("change", (event) => { if (inspection) { const index = Number(event.target.value) - 1; if (index >= 0 && index < inspection.questions.length) { inspectionIndex = index; renderInspection(); } } });
  document.getElementById("inspection-search").addEventListener("search", (event) => { if (inspection) { const value = event.target.value.trim().toLowerCase(); const index = inspection.questions.findIndex((item) => item.question_id.toLowerCase().includes(value) || item.stem.toLowerCase().includes(value)); if (index >= 0) { inspectionIndex = index; renderInspection(); } } });
  document.addEventListener("keydown", (event) => { if (inspection && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) { if (event.key === "ArrowLeft") document.getElementById("inspection-previous").click(); if (event.key === "ArrowRight") document.getElementById("inspection-next").click(); } });

  document.getElementById("comparison-button").addEventListener("click", () => {
    if (payload.session?.mode !== "synthetic_in_memory") return;
    fetch("/api/comparison", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Comparison failed.");
        acceptEnginePayload(result);
      })
      .catch((error) => {
        document.getElementById("decision-help").textContent = error.message;
      });
  });

  function runCommand(path) {
    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Run command failed.");
        acceptEnginePayload(result);
      })
      .catch((error) => {
        document.getElementById("decision-help").textContent = error.message;
      });
  }

  document.getElementById("start-run-button").addEventListener("click", () => runCommand("/api/run/start"));
  function sourceOnlyMetadata() {
    if (selectedNewRunPack === "peds") {
      return { display_name: "Pediatrics", slug: "pediatrics", prefix: "Peds" };
    }
    return {
      display_name: document.getElementById("new-source-name").value,
      slug: document.getElementById("new-source-slug").value,
      prefix: document.getElementById("new-source-prefix").value
    };
  }
  function updateNewSourcePreview() {
    const select = document.getElementById("new-run-pack");
    const metadata = document.getElementById("new-source-metadata");
    const isNew = select.value === "new_source";
    metadata.hidden = !isNew;
    const source = sourceOnlyMetadata();
    const slug = String(source.slug || "slug").trim().toLowerCase().replace(/[^a-z0-9_]/g, "");
    const prefix = String(source.prefix || "Prefix").trim();
    document.getElementById("new-source-preview").textContent = `Preview: PFQ-${slug || "slug"}-000000001 · ${prefix || "Prefix"} 1`;
  }
  document.getElementById("new-run-pack").addEventListener("change", updateNewSourcePreview);
  ["new-source-name", "new-source-slug", "new-source-prefix"].forEach((id) => {
    document.getElementById(id).addEventListener("input", updateNewSourcePreview);
  });
  updateNewSourcePreview();
  document.getElementById("new-run-button").addEventListener("click", () => {
    selectedNewRunPack = document.getElementById("new-run-pack").value;
    document.getElementById("pdf-input").click();
  });
  document.getElementById("resume-run-button").addEventListener("click", async () => {
    if (!resumableRun) return;
    try {
      const response = await fetch("/api/run/resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: resumableRun.run_id, pack_id: resumableRun.pack_id })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Previous review could not be restored.");
      resumableRun = null;
      document.getElementById("resume-run-button").disabled = true;
      acceptEnginePayload(result);
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    }
  });
  document.getElementById("complete-run-button").addEventListener("click", () => runCommand("/api/run/complete"));
  document.getElementById("cleanup-run-button").addEventListener("click", () => runCommand("/api/run/cleanup"));
  document.getElementById("materialize-identity-button").addEventListener("click", () => runCommand("/api/identity/materialize"));
  document.querySelectorAll(".identity-button").forEach((button) => {
    button.addEventListener("click", () => {
      fetch("/api/identity/existing-pack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pack_id: button.dataset.packId })
      })
        .then(async (response) => {
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || "Identity matching stopped.");
          acceptEnginePayload(result);
        })
        .catch((error) => {
          document.getElementById("decision-help").textContent = error.message;
        });
    });
  });

  document.getElementById("pdf-input").addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const response = await fetch("/api/run/start-pdf", {
        method: "POST",
        headers: { "Content-Type": "application/pdf" },
        body: file
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "PDF intake failed.");
      acceptEnginePayload(result);
      if (selectedNewRunPack) {
        if (["peds", "new_source"].includes(selectedNewRunPack)) {
          const sourceResponse = await fetch("/api/identity/source-only", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ metadata: sourceOnlyMetadata(), preset: selectedNewRunPack === "peds" ? "peds" : null }) });
          const sourceResult = await sourceResponse.json();
          if (!sourceResponse.ok) throw new Error(sourceResult.error || "Source-only review could not begin.");
          acceptEnginePayload(sourceResult);
          return;
        }
        const packResponse = await fetch("/api/identity/existing-pack", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pack_id: selectedNewRunPack })
        });
        const packResult = await packResponse.json();
        if (!packResponse.ok) throw new Error(packResult.error || "Pack comparison could not begin.");
        acceptEnginePayload(packResult);
      }
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    } finally {
      selectedNewRunPack = null;
      event.target.value = "";
    }
  });

  function acceptEnginePayload(result, advanceQuestionId = null) {
    const selectedFinding = cases[selectedIndex]?.finding_id;
    payload = result;
    cases = result.cases.map((item) => ({ ...item }));
    const nextInPacket = advanceQuestionId
      ? cases.findIndex((item) => item.question_id === advanceQuestionId && !["approved", "excluded_record", "rejected"].includes(item.status))
      : -1;
    selectedIndex = nextInPacket >= 0
      ? nextInPacket
      : Math.max(0, cases.findIndex((item) => item.finding_id === selectedFinding));
    document.getElementById("connection-badge").innerHTML = result.session.private_checkpoint
      ? "<span></span> Engine connected · private checkpoint"
      : "<span></span> Engine connected · in memory";
    document.getElementById("decision-help").textContent = result.session.private_checkpoint
      ? `Validated by Python engine · ${result.session.event_count} session event(s) · private checkpoint saved; canonical Pack unchanged.`
      : `Validated by Python engine · ${result.session.event_count} session event(s) · no canonical write.`;
    render();
  }

  function discoverPrivateRuns() {
    fetch("/api/runs", { headers: { "Accept": "application/json" } })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Resume discovery failed.");
        resumableRun = result.resumable.at(-1) || null;
        const button = document.getElementById("resume-run-button");
        button.disabled = !resumableRun;
        document.getElementById("resume-summary").textContent = resumableRun
          ? `${resumableRun.pack_id.replaceAll("_", "-")} · ${resumableRun.stage.replaceAll("_", " ")} · ${resumableRun.parsed_records} parsed records`
          : "No validated unfinished review was found.";
        if (resumableRun) {
          button.textContent = `Continue previous ${resumableRun.pack_id.replaceAll("_", "-")} review`;
        } else {
          button.textContent = "Nothing to continue";
        }
        const completed = document.getElementById("completed-runs");
        completed.replaceChildren();
        if (!result.completed.length) completed.textContent = "No completed private runs yet.";
        result.completed.forEach((run) => {
          const summary = document.createElement("div");
          summary.className = "completed-run";
          summary.textContent = `${run.pack_id.replaceAll("_", "-")} · ${run.candidate_questions} candidate questions · ${run.field_changes} compared field changes`;
          completed.append(summary);
        });
      })
      .catch(() => {
        resumableRun = null;
        document.getElementById("resume-run-button").disabled = true;
      });
  }

  document.getElementById("repair-desk-form").addEventListener("submit", (event) => {
    event.preventDefault();
    lookupRepairDesk(document.getElementById("repair-desk-query").value);
  });
  const deepLinkQuestion = new URL(window.location.href).searchParams.get("question");
  if (deepLinkQuestion) {
    document.getElementById("repair-desk-query").value = deepLinkQuestion;
    lookupRepairDesk(deepLinkQuestion);
  }

  fetch("/api/review", { headers: { "Accept": "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error("Engine unavailable");
      return response.json();
    })
    .then((result) => {
      acceptEnginePayload(result);
      if (["not_started", "completed"].includes(result.run?.state)) discoverPrivateRuns();
    })
    .catch(() => {
      document.getElementById("connection-badge").innerHTML = "<span></span> Standalone mock · no writes";
      render();
    });
})();
