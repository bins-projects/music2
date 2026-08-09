(() => {
  "use strict";

  let payload = window.PREPFLOW_REVIEW_DEMO;
  let cases = payload.cases.map((item) => ({ ...item }));
  let selectedIndex = 0;
  let resumableRun = null;
  let selectedNewRunPack = null;

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

  function renderActions(item) {
    const actions = document.getElementById("actions");
    actions.replaceChildren();
    if (["needs_proposal", "awaiting_decision", "deferred", "rejected"].includes(item.status)) {
      const source = document.createElement("button");
      source.type = "button";
      source.className = "secondary";
      source.textContent = "Open temporary source page";
      source.addEventListener("click", () => openFindingSource(item));
      actions.append(source);
    }
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
    }
  }

  function openProposalEditor(item) {
    const dialog = document.getElementById("proposal-dialog");
    dialog.dataset.findingId = item.finding_id;
    const value = item.proposal?.proposed_value ?? item.preserved_value;
    dialog.dataset.valueType = typeof value === "string" ? "text" : "json";
    document.getElementById("proposal-value").value = typeof value === "string"
      ? value
      : JSON.stringify(value, null, 2);
    document.getElementById("proposal-reason").value = item.proposal?.explanation || "";
    document.getElementById("proposal-verification").checked = Boolean(item.proposal?.requires_source_verification);
    document.getElementById("proposal-error").textContent = "";
    dialog.showModal();
  }

  document.getElementById("proposal-cancel").addEventListener("click", () => {
    document.getElementById("proposal-dialog").close();
  });

  document.getElementById("proposal-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const dialog = document.getElementById("proposal-dialog");
    const errorNode = document.getElementById("proposal-error");
    try {
      const rawValue = document.getElementById("proposal-value").value;
      const proposedAfter = dialog.dataset.valueType === "text"
        ? rawValue
        : JSON.parse(rawValue);
      const response = await fetch("/api/proposals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          finding_id: dialog.dataset.findingId,
          proposed_after: proposedAfter,
          explanation: document.getElementById("proposal-reason").value,
          requires_source_verification: document.getElementById("proposal-verification").checked
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Proposal was rejected.");
      dialog.close();
      acceptEnginePayload(result);
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
      document.getElementById("source-page-title").textContent = `Extracted PDF page ${result.page_number} of ${result.page_count}`;
      document.getElementById("source-page-text").textContent = result.text;
      document.getElementById("source-dialog").showModal();
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    }
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
      set("case-count", "case-count-label", identity.parsed_count, "parsed records");
      set("blocking-count", "blocking-count-label", identity.matched_count, "exact ID matches");
      set("verified-count", "verified-count-label", identity.finding_count, "source records to classify");
      set("summary-tail-count", "summary-tail-label", identity.target_only_count, "Pack-only records");
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
    const item = cases[selectedIndex];
    const identityCases = payload.pipeline?.identity?.review_cases || [];
    // Advance past deliberately unresolved cases while any untouched cases
    // remain. Once all cases have a decision, keep one visible for review.
    const identityCase = identityCases.find((entry) => entry.status === "pending") || identityCases[0];
    const blocking = cases.filter((entry) => entry.severity === "blocking" && !["approved", "excluded_record"].includes(entry.status)).length;
    renderSummaryCounts(identityCases, blocking);
    document.getElementById("queue-position").textContent = `${selectedIndex + 1} / ${cases.length}`;
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
    document.getElementById("question-meta").textContent = `${item.question_id} · ${chapterLabel(item)}${sourceRecordLabel(item)} · ${item.field}`;
    document.getElementById("damage-title").textContent = item.damage_type.replaceAll("_", " ");
    const pill = document.getElementById("status-pill");
    pill.textContent = statusLabels[item.status];
    pill.dataset.status = item.status;
    document.getElementById("finding-explanation").textContent = item.explanation;
    document.getElementById("preserved-card-label").innerHTML = '<span class="dot amber"></span>Preserved complete question';
    document.getElementById("proposed-card-label").innerHTML = '<span class="dot blue"></span>Proposed complete question';
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
    document.getElementById("preserved-card-label").innerHTML = '<span class="dot amber"></span>Preserved parsed structure';
    document.getElementById("proposed-card-label").innerHTML = '<span class="dot blue"></span>Identity evidence';
    document.getElementById("queue-position").textContent = `${item.record_id} · ${item.status}`;
    document.getElementById("question-meta").textContent = `${item.record_id} · ${chapterLabel(item)}`;
    document.getElementById("damage-title").textContent = "Identity review required";
    const pill = document.getElementById("status-pill");
    pill.textContent = item.status === "pending" ? "Review required" : item.status;
    pill.dataset.status = item.status;
    document.getElementById("finding-explanation").textContent = "Parsing succeeded, but PrepFlow cannot safely decide whether this is a question, parser debris, or a duplicate. The protected Pack supplies identity evidence only—not corrected content.";
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
    document.getElementById("proposal-explanation").textContent = "Ranked suggestion only; this is identity evidence. Matching does not copy the Pack's wording or answer into this record.";
    document.getElementById("verification-card").hidden = true;
    const actions = document.getElementById("actions");
    actions.replaceChildren();
    const source = document.createElement("button");
    source.type = "button";
    source.textContent = "View source context";
    source.className = "secondary";
    source.addEventListener("click", () => openIdentitySourceContext(item));
    actions.append(source);
    [
      ["approve", "Match selected ID", "primary"],
      ["retain_new_question", "Keep as new question", "primary"],
      ["exclude_parser_debris", "Exclude parser debris", "danger"],
      ["exclude_duplicate", "Exclude duplicate record", "danger"],
      ["defer", "Leave unresolved", "secondary"]
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
    if (!candidate || candidate.state === "not_built") {
      state.textContent = "Not built";
      detail.textContent = "Builds in memory only. Unresolved findings remain visible.";
      button.disabled = payload.session?.mode !== "synthetic_in_memory" || !["review_ready", "candidate_built", "compared", "unmanaged_demo"].includes(payload.run?.state);
      comparisonButton.disabled = true;
      comparisonDetail.textContent = "Comparison has not run.";
      comparisonChanges.replaceChildren();
      return;
    }
    state.textContent = `${candidate.question_count} questions · ${candidate.applied_proposal_ids.length} approved proposal(s) applied`;
    detail.textContent = `${candidate.unresolved_finding_ids.length} unresolved finding(s) · ${candidate.excluded_question_ids.length} documented exclusion(s) · promotion remains ${candidate.promotion_ready ? "ready" : "blocked"}.`;
    button.textContent = "Rebuild isolated candidate";
    button.disabled = payload.run?.state === "completed";
    comparisonButton.disabled = payload.session?.mode !== "synthetic_in_memory" || payload.run?.state === "completed";
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

  document.getElementById("candidate-button").addEventListener("click", () => {
    if (payload.session?.mode !== "synthetic_in_memory") return;
    fetch("/api/candidate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Candidate build failed.");
        acceptEnginePayload(result);
      })
      .catch((error) => {
        document.getElementById("decision-help").textContent = error.message;
      });
  });

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
