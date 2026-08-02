(() => {
  "use strict";

  let payload = window.PREPFLOW_REVIEW_DEMO;
  let cases = payload.cases.map((item) => ({ ...item }));
  let selectedIndex = 0;

  const labels = {
    approve: "Approve proposal",
    reject: "Reject",
    defer: "Decide later",
    edit_as_new_proposal: "Edit proposal",
    leave_blocked: "Leave blocked",
    exclude_record: "Exclude record",
    create_proposal: "Draft proposal"
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

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = value;
    return node.innerHTML;
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
    item.allowed_actions.filter((action) => labels[action]).forEach((action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = labels[action] || action;
      button.className = action === "approve" ? "primary" : action === "reject" ? "danger" : "secondary";
      button.addEventListener("click", () => takeAction(item, action));
      actions.append(button);
    });
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
        acceptEnginePayload(result);
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

  function render() {
    const item = cases[selectedIndex];
    const identityCases = payload.pipeline?.identity?.review_cases || [];
    const identityCase = identityCases.find((entry) => entry.status === "pending" || entry.status === "defer") || identityCases[0];
    const blocking = cases.filter((entry) => entry.severity === "blocking" && !["approved", "excluded_record"].includes(entry.status)).length;
    document.getElementById("case-count").textContent = cases.length;
    document.getElementById("blocking-count").textContent = blocking;
    document.getElementById("verified-count").textContent = cases.filter((entry) => entry.source_verification_recorded).length;
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
    document.getElementById("question-meta").textContent = `${item.question_id} · Chapter ${item.chapter} · ${item.field}`;
    document.getElementById("damage-title").textContent = item.damage_type.replaceAll("_", " ");
    const pill = document.getElementById("status-pill");
    pill.textContent = statusLabels[item.status];
    pill.dataset.status = item.status;
    document.getElementById("finding-explanation").textContent = item.explanation;
    document.getElementById("preserved-value").innerHTML = formatValue(item.preserved_value);
    document.getElementById("proposed-value").innerHTML = item.proposal ? formatValue(item.proposal.proposed_value) : "No correction proposed";
    document.getElementById("proposal-explanation").textContent = item.proposal?.explanation || "The record remains blocked until a justified proposal exists.";
    const verificationCard = document.getElementById("verification-card");
    verificationCard.hidden = item.status !== "awaiting_source_verification";
    renderActions(item);
    renderQueue();
  }

  function renderIdentityCase(item) {
    document.getElementById("queue-position").textContent = `${item.record_id} · ${item.status}`;
    document.getElementById("question-meta").textContent = `${item.record_id} · Chapter ${item.chapter ?? "unknown"}`;
    document.getElementById("damage-title").textContent = "Confirm stable question identity";
    const pill = document.getElementById("status-pill");
    pill.textContent = item.status === "pending" ? "Review required" : item.status;
    pill.dataset.status = item.status;
    document.getElementById("finding-explanation").textContent = "PrepFlow found possible existing-Pack matches, but similarity is evidence only. You must authorize the identity explicitly.";
    document.getElementById("preserved-value").textContent = item.parsed_stem;
    const proposed = document.getElementById("proposed-value");
    proposed.replaceChildren();
    const select = document.createElement("select");
    select.id = "identity-suggestion-select";
    item.suggestions.forEach((suggestion) => {
      const option = document.createElement("option");
      option.value = suggestion.target_question_id;
      option.textContent = `${suggestion.target_question_id} · ${Math.round(suggestion.similarity * 100)}% · ${suggestion.target_stem}`;
      option.selected = suggestion.target_question_id === item.selected_target_question_id;
      select.append(option);
    });
    proposed.append(select);
    document.getElementById("proposal-explanation").textContent = "Ranked suggestion only. No stable ID is attached until you approve it.";
    document.getElementById("verification-card").hidden = true;
    const actions = document.getElementById("actions");
    actions.replaceChildren();
    [["approve", "Approve selected match", "primary"], ["defer", "Decide later", "secondary"], ["reject", "Reject suggestions", "danger"]].forEach(([action, label, style]) => {
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
    const start = document.getElementById("start-run-button");
    const complete = document.getElementById("complete-run-button");
    const cleanup = document.getElementById("cleanup-run-button");
    const pdfInput = document.getElementById("pdf-input");
    const pdfButton = document.querySelector("label[for='pdf-input']");
    const identityButtons = document.querySelectorAll(".identity-button");
    state.textContent = run.state.replaceAll("_", " ");
    if (["not_started", "completed"].includes(run.state)) {
      artifacts.textContent = "No disposable source or text artifacts.";
      extraction.textContent = "Extractor has not run.";
      cleaning.textContent = "Cleaner has not run.";
      identity.textContent = "Identity matcher has not run.";
      start.disabled = false;
      pdfInput.disabled = false;
      pdfButton.classList.remove("disabled");
    } else if (run.state === "unmanaged_demo") {
      artifacts.textContent = "Standalone display only; open through the local engine to run stages.";
      extraction.textContent = "Connected extraction metrics unavailable.";
      cleaning.textContent = "Connected cleaning metrics unavailable.";
      identity.textContent = "Identity matcher unavailable.";
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
      start.disabled = true;
      pdfInput.disabled = true;
      pdfButton.classList.add("disabled");
    }
    complete.disabled = run.state !== "compared";
    cleanup.disabled = ["not_started", "unmanaged_demo", "completed"].includes(run.state);
    identityButtons.forEach((button) => { button.disabled = run.state !== "identity_pending"; });
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
      button.disabled = payload.session?.mode !== "synthetic_in_memory" || ["not_started", "completed"].includes(payload.run?.state);
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
      comparisonChanges.innerHTML = payload.comparison.field_changes.map((change) => (
        `<span><b>${escapeHtml(change.question_id.replace("PFQ-synthetic-", "Question "))} · ${escapeHtml(change.field)}</b> ${formatValue(change.benchmark_value)} → ${formatValue(change.candidate_value)}</span>`
      )).join("");
      comparisonButton.textContent = "Run comparison again";
    } else {
      comparisonDetail.textContent = "Comparison has not run for this candidate.";
      comparisonChanges.replaceChildren();
      comparisonButton.textContent = "Compare with benchmark";
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
  document.getElementById("complete-run-button").addEventListener("click", () => runCommand("/api/run/complete"));
  document.getElementById("cleanup-run-button").addEventListener("click", () => runCommand("/api/run/cleanup"));
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
    } catch (error) {
      document.getElementById("decision-help").textContent = error.message;
    } finally {
      event.target.value = "";
    }
  });

  function acceptEnginePayload(result) {
    const selectedFinding = cases[selectedIndex]?.finding_id;
    payload = result;
    cases = result.cases.map((item) => ({ ...item }));
    selectedIndex = Math.max(0, cases.findIndex((item) => item.finding_id === selectedFinding));
    document.getElementById("connection-badge").innerHTML = "<span></span> Engine connected · in memory";
    document.getElementById("decision-help").textContent = `Validated by Python engine · ${result.session.event_count} session event(s) · nothing saved to disk.`;
    render();
  }

  fetch("/api/review", { headers: { "Accept": "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error("Engine unavailable");
      return response.json();
    })
    .then(acceptEnginePayload)
    .catch(() => {
      document.getElementById("connection-badge").innerHTML = "<span></span> Standalone mock · no writes";
      render();
    });
})();
