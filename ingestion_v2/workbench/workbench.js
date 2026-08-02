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
    const blocking = cases.filter((entry) => entry.severity === "blocking" && !["approved", "excluded_record"].includes(entry.status)).length;
    document.getElementById("case-count").textContent = cases.length;
    document.getElementById("blocking-count").textContent = blocking;
    document.getElementById("verified-count").textContent = cases.filter((entry) => entry.source_verification_recorded).length;
    document.getElementById("queue-position").textContent = `${selectedIndex + 1} / ${cases.length}`;
    renderRun();
    renderCandidate();
    if (!item) {
      document.getElementById("queue-position").textContent = "0 / 0";
      document.getElementById("question-meta").textContent = "START A SYNTHETIC RUN";
      document.getElementById("damage-title").textContent = "No review cases loaded";
      document.getElementById("status-pill").textContent = "Waiting";
      document.getElementById("finding-explanation").textContent = "Start the private synthetic run to process its disposable document copy.";
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

  function renderRun() {
    const run = payload.run || { state: "unmanaged_demo" };
    const state = document.getElementById("run-state");
    const artifacts = document.getElementById("run-artifacts");
    const start = document.getElementById("start-run-button");
    const complete = document.getElementById("complete-run-button");
    state.textContent = run.state.replaceAll("_", " ");
    if (run.state === "not_started") {
      artifacts.textContent = "No disposable source or text artifacts.";
      start.disabled = false;
    } else if (run.state === "unmanaged_demo") {
      artifacts.textContent = "Standalone display only; open through the local engine to run stages.";
      start.disabled = true;
    } else {
      artifacts.textContent = `staged copy: ${run.staged_copy_present ? "present" : "removed"} · raw text: ${run.raw_text_present ? "present" : "removed"} · cleaned text: ${run.cleaned_text_present ? "present" : "removed"}`;
      start.disabled = true;
    }
    complete.disabled = run.state !== "compared";
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
