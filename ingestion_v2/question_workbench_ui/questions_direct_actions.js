(() => {
  "use strict";

  const FLASH_KEY = "prepflow.questionWorkbench.flash.v1";
  const ACTIONABLE_STATES = new Set(["pending", "publishing"]);
  const $ = (id) => document.getElementById(id);

  async function json(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Workbench request failed");
    return payload;
  }

  function setFeedback(message, ok = true) {
    const node = $("operation-feedback");
    if (!node) return;
    node.textContent = message;
    node.className = ok ? "message ok" : "message";
  }

  function showFlash() {
    const message = sessionStorage.getItem(FLASH_KEY);
    if (!message) return;
    sessionStorage.removeItem(FLASH_KEY);
    setFeedback(message, true);
  }

  function installStableRecoveryVisibility() {
    const pending = $("pending");
    const panel = pending?.closest("section.panel");
    if (!panel) return;
    panel.classList.add("direct-recovery-panel");
    if (!document.getElementById("direct-recovery-visibility-style")) {
      const style = document.createElement("style");
      style.id = "direct-recovery-visibility-style";
      style.textContent = `
        .direct-recovery-panel { display: none !important; }
        body.direct-has-recovery .direct-recovery-panel { display: block !important; }
      `;
      document.head.append(style);
    }
  }

  function installHistory(state) {
    const pending = $("pending");
    const panel = pending?.closest("section.panel");
    if (!panel || document.getElementById("question-change-history")) return;

    const history = document.createElement("details");
    history.id = "question-change-history";
    history.className = "panel canonical-record";
    const summary = document.createElement("summary");
    summary.textContent = "Change history";
    const body = document.createElement("div");
    body.className = "pending";
    history.append(summary, body);
    panel.insertAdjacentElement("afterend", history);

    const completed = [...(state.operations || [])]
      .filter((op) => op.state === "published")
      .reverse()
      .slice(0, 20);
    if (!completed.length) {
      body.textContent = "No completed Workbench changes in the current ledger. The permanent audit log remains in the repository.";
      return;
    }
    completed.forEach((op) => {
      const row = document.createElement("div");
      const verb = op.operation_type === "addition" ? "Added" : op.operation_type === "deletion" ? "Deleted" : "Replaced";
      const when = op.publication?.published_at || op.updated_at || "";
      row.className = "pending-card";
      row.innerHTML = `<div><strong>${verb} · ${String(op.question_id || "")}</strong><small>${String(op.pack_id || "")}${when ? ` · ${String(when)}` : ""}</small></div>`;
      body.append(row);
    });
  }

  function cleanRecoveryPanel(state) {
    const target = $("pending");
    const panel = target?.closest("section.panel");
    if (!target || !panel) return;

    const renderedOperations = [...(state.operations || [])]
      .filter((op) => op.state !== "published")
      .reverse();
    const cards = [...target.querySelectorAll(".pending-card")];
    let actionableCount = 0;

    cards.forEach((card, index) => {
      const operation = renderedOperations[index];
      const actionable = operation && ACTIONABLE_STATES.has(operation.state);
      card.hidden = !actionable;
      if (!actionable) {
        card.querySelectorAll("button").forEach((button) => { button.disabled = true; });
      } else {
        actionableCount += 1;
      }
    });

    document.body.classList.toggle("direct-has-recovery", actionableCount > 0);
    panel.hidden = actionableCount === 0;
    const heading = panel.querySelector("h2");
    if (heading) heading.textContent = "Recovery needed";
    const eyebrow = panel.querySelector(".eyebrow");
    if (eyebrow) eyebrow.textContent = "UNFINISHED PUBLICATION";
  }

  async function refreshDirectPresentation() {
    let state;
    try {
      state = await json("/api/question-workbench");
    } catch {
      return;
    }
    cleanRecoveryPanel(state);
    installHistory(state);
  }

  function installDeleteFlow() {
    const button = $("delete-question");
    if (!button || button.dataset.directDeleteInstalled === "1") return;
    button.dataset.directDeleteInstalled = "1";
    let resetTimer = null;

    function resetConfirmation() {
      clearTimeout(resetTimer);
      button.dataset.confirmDelete = "0";
      button.disabled = false;
      button.textContent = "Delete question";
    }

    button.onclick = async () => {
      let question;
      try {
        question = JSON.parse($("browse-record-json")?.textContent || "null");
      } catch {
        question = null;
      }
      if (!question?.id) {
        setFeedback("Delete failed — the current question record could not be read.", false);
        return;
      }

      if (button.dataset.confirmDelete !== "1") {
        button.dataset.confirmDelete = "1";
        button.textContent = "Confirm delete";
        setFeedback(`Delete ${question.id}? Click Confirm delete once more to remove it from the canonical Pack and publish the change.`, false);
        resetTimer = setTimeout(resetConfirmation, 10000);
        return;
      }

      clearTimeout(resetTimer);
      button.disabled = true;
      button.textContent = "Deleting…";
      setFeedback(`Deleting ${question.id}…`, false);

      try {
        const response = await json("/api/question-workbench/action", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            operation_type: "deletion",
            pack_id: $("pack")?.value || "",
            question,
          }),
        });
        if (response.operation?.state === "published") {
          sessionStorage.setItem(FLASH_KEY, `Question deleted successfully — ${question.id}`);
          window.location.reload();
          return;
        }
        setFeedback(`Deletion saved for ${question.id}. Publication is incomplete, so it remains under Recovery needed.`, false);
        resetConfirmation();
        $("refresh")?.click();
        setTimeout(() => { void refreshDirectPresentation(); }, 100);
      } catch (error) {
        setFeedback(`Delete failed — ${error.message}`, false);
        resetConfirmation();
      }
    };
  }

  function installPublishedSuccessReset() {
    const saveState = $("save-state");
    if (!saveState || saveState.dataset.directSuccessInstalled === "1") return;
    saveState.dataset.directSuccessInstalled = "1";
    let reloading = false;
    const observer = new MutationObserver(() => {
      if (reloading || !saveState.textContent.startsWith("Published")) return;
      reloading = true;
      const addition = $("editor-mode")?.textContent.includes("ADD NEW");
      const id = $("question-id")?.textContent || "question";
      sessionStorage.setItem(
        FLASH_KEY,
        addition ? `Question added successfully — ${id}` : `Question replaced successfully — ${id}`,
      );
      setTimeout(() => window.location.reload(), 150);
    });
    observer.observe(saveState, {childList: true, subtree: true, characterData: true});
  }

  function install() {
    installStableRecoveryVisibility();
    showFlash();
    installDeleteFlow();
    installPublishedSuccessReset();
    void refreshDirectPresentation();
  }

  const observer = new MutationObserver(() => {
    installStableRecoveryVisibility();
    installDeleteFlow();
    installPublishedSuccessReset();
    setTimeout(() => { void refreshDirectPresentation(); }, 30);
  });
  observer.observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ["hidden"]});
  install();
})();
