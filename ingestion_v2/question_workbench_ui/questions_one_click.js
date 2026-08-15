(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const json = async (url, options) => {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Workbench request failed");
    return payload;
  };

  function isEmbedded() { return window.self !== window.top; }

  function compactShell() {
    if (document.body.dataset.compactQuestionShell === "1") return;
    document.body.dataset.compactQuestionShell = "1";

    if (isEmbedded()) {
      const header = document.querySelector("body > header");
      if (header) header.hidden = true;
      document.body.classList.add("embedded-question-workbench");
    }

    const setup = document.querySelector("section.panel.setup");
    if (setup && !setup.closest("details.question-finder")) {
      const drawer = document.createElement("details");
      drawer.className = "question-finder";
      const summary = document.createElement("summary");
      summary.innerHTML = "<strong>Find / browse a question</strong><span>Book · chapter · stem · Ref · PFQ ID</span>";
      setup.parentNode.insertBefore(drawer, setup);
      drawer.append(summary, setup);
      setup.classList.remove("panel");
      setup.classList.add("question-finder-body");

      const closeWhenFocused = () => {
        if (!$("record-view")?.hidden || !$("editor")?.hidden) drawer.open = false;
      };
      const focusObserver = new MutationObserver(closeWhenFocused);
      if ($("record-view")) focusObserver.observe($("record-view"), {attributes: true, attributeFilter: ["hidden"]});
      if ($("editor")) focusObserver.observe($("editor"), {attributes: true, attributeFilter: ["hidden"]});
    }
  }

  function finalLabel() {
    const button = $("final-action");
    if (!button || $("editor")?.hidden) return;
    const addition = $("editor-mode")?.textContent.includes("ADD NEW");
    const desired = addition ? "Add & publish" : "Replace & publish";
    if (button.textContent !== desired) button.textContent = desired;
  }

  function normalizeMessages(state) {
    const actionable = (state?.operations || []).filter((op) => op.state !== "published");
    const readiness = $("readiness");
    if (readiness) readiness.hidden = actionable.length === 0;

    const saveState = $("save-state");
    if (saveState?.textContent === "Saved for publication") {
      saveState.textContent = "Saved to canonical Pack — publication pending";
    }
    const validation = $("validation");
    if (validation?.textContent.includes("Saved durably")) {
      validation.textContent = "Saved to the canonical Pack. Publication can be retried without reapplying the question.";
    }
    const final = $("final-action");
    if (saveState?.textContent.includes("Saved to canonical Pack") && final && !final.disabled) {
      final.disabled = true;
    }
    finalLabel();
  }

  function updatePendingVisibility(state) {
    const target = $("pending");
    const panel = target?.closest("section.panel");
    if (!panel) return;
    const actionable = (state.operations || []).filter((op) => op.state !== "published");
    panel.hidden = actionable.length === 0;
  }

  async function enhancePending(state) {
    const target = $("pending");
    if (!target) return;
    const operations = [...(state.operations || [])].filter((op) => op.state !== "published").reverse();
    const cards = [...target.querySelectorAll(".pending-card")];
    cards.forEach((card, index) => {
      const operation = operations[index];
      if (!operation || card.dataset.oneClickEnhanced === operation.operation_id) return;
      card.dataset.oneClickEnhanced = operation.operation_id;
      const actions = card.querySelector(".pending-actions");
      if (!actions) return;

      if (operation.state === "pending") {
        const discard = document.createElement("button");
        discard.type = "button";
        discard.className = "secondary";
        discard.textContent = operation.operation_type === "repair" ? "Cancel repair" : "Discard draft";
        discard.onclick = async () => {
          if (!confirm(`${discard.textContent}? This removes only saved Workbench state and does not change a Pack.`)) return;
          discard.disabled = true;
          try {
            await json("/api/question-workbench/discard", {
              method: "POST",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify({operation_id: operation.operation_id}),
            });
            $("refresh")?.click();
          } catch (error) {
            discard.disabled = false;
            alert(error.message);
          }
        };
        actions.append(discard);
      }

      if (operation.state === "applied") {
        const retry = document.createElement("button");
        retry.type = "button";
        retry.textContent = "Retry publish";
        retry.onclick = async () => {
          retry.disabled = true;
          retry.textContent = "Publishing…";
          try {
            const response = await json("/api/question-workbench/publish", {
              method: "POST",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify({operation_id: operation.operation_id}),
            });
            if (response.publication_error) {
              alert(`Canonical Pack is safe. Publication still needs attention: ${response.publication_error}`);
            }
            $("refresh")?.click();
          } catch (error) {
            retry.disabled = false;
            retry.textContent = "Retry publish";
            alert(error.message);
          }
        };
        actions.append(retry);
      }
    });
  }

  async function refreshEnhancements() {
    compactShell();
    let state;
    try { state = await json("/api/question-workbench"); } catch { finalLabel(); return; }
    normalizeMessages(state);
    updatePendingVisibility(state);
    await enhancePending(state);
  }

  let timer = null;
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(() => { void refreshEnhancements(); }, 60);
  };

  const observer = new MutationObserver(schedule);
  observer.observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["hidden", "disabled"],
  });
  document.addEventListener("click", () => setTimeout(schedule, 0));
  schedule();
})();
