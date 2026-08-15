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

  let embeddedMode = "repair";
  let parentShellInstalled = false;
  let embeddedModeApplied = false;
  let heightTimer = null;

  function reportEmbeddedHeight() {
    if (!isEmbedded()) return;
    clearTimeout(heightTimer);
    heightTimer = setTimeout(() => {
      try {
        const frame = window.frameElement;
        const main = document.querySelector("main");
        if (!frame || !main) return;
        frame.setAttribute("scrolling", "no");

        const styles = getComputedStyle(main);
        const marginBottom = parseFloat(styles.marginBottom) || 0;
        const target = Math.max(
          320,
          Math.ceil(main.offsetTop + main.scrollHeight + marginBottom + 24)
        );
        const current = parseFloat(frame.style.height) || 0;
        if (Math.abs(current - target) > 2) frame.style.height = `${target}px`;
      } catch (_) {}
    }, 30);
  }

  function updateModePresentation() {
    const addition = embeddedMode === "addition";
    const needsReviewPanel = $("needs-review")?.closest("section.panel");
    const finder = document.querySelector("details.question-finder");
    const results = $("search-results");
    if (needsReviewPanel) needsReviewPanel.hidden = addition;
    if (finder) {
      finder.hidden = false;
      const summary = finder.querySelector("summary");
      if (summary) {
        summary.innerHTML = addition
          ? "<strong>Choose where this question goes</strong><span>Pack · chapter · question type</span>"
          : "<strong>Find / browse a question</strong><span>Book · chapter · stem · Ref · PFQ ID</span>";
      }
      if (addition) finder.open = true;
    }
    if (results) results.hidden = addition;
    reportEmbeddedHeight();
  }

  function setEmbeddedWorkspaceMode(mode) {
    embeddedMode = mode === "addition" ? "addition" : "repair";
    const button = document.querySelector(`[data-mode="${embeddedMode}"]`);
    if (button && $("pack")?.options.length) {
      button.click();
      embeddedModeApplied = true;
    }
    updateModePresentation();
  }

  function installParentShell() {
    if (!isEmbedded() || parentShellInstalled) return;
    let parentDocument;
    try { parentDocument = window.parent.document; } catch (_) { return; }

    const nav = parentDocument.querySelector(".workbench-modes");
    const factoryButton = parentDocument.getElementById("factory-mode-button");
    const oldQuestionButton = parentDocument.getElementById("question-mode-button");
    const factory = parentDocument.getElementById("factory-workspace");
    const workspace = parentDocument.getElementById("question-workspace");
    const frame = parentDocument.getElementById("question-workbench-frame");
    if (!nav || !factoryButton || !oldQuestionButton || !factory || !workspace || !frame) return;

    parentShellInstalled = true;
    factoryButton.textContent = "Build / review a Pack";
    oldQuestionButton.textContent = "Repair existing question";
    frame.setAttribute("scrolling", "no");

    let addButton = parentDocument.getElementById("add-mode-button");
    if (!addButton) {
      addButton = parentDocument.createElement("button");
      addButton.id = "add-mode-button";
      addButton.type = "button";
      addButton.textContent = "Add new question";
      nav.append(addButton);
    }

    const style = parentDocument.createElement("style");
    style.id = "prepflow-unified-shell-style";
    style.textContent = `
      .workbench-modes { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .workbench-modes button { border-width: 2px !important; border-color: #60757a !important; }
      .workbench-modes button:hover { border-color: var(--cyan) !important; }
      .workbench-modes button.active { border-color: #9ff5e8 !important; }
      .question-workspace { overflow: visible !important; }
      .question-workspace iframe { min-height: 0 !important; overflow: hidden !important; }
      body.prepflow-factory-idle #factory-workspace > .summary,
      body.prepflow-factory-idle #factory-workspace > .runbar,
      body.prepflow-factory-idle #factory-workspace > .workspace { display: none !important; }
      body.prepflow-factory-idle #factory-home { margin-bottom: 0; }
      @media (max-width: 760px) { .workbench-modes { grid-template-columns: 1fr; } }
    `;
    parentDocument.getElementById(style.id)?.remove();
    parentDocument.head.append(style);

    const runState = parentDocument.getElementById("run-state");
    const updateFactoryIdle = () => {
      const state = (runState?.textContent || "").trim().toLowerCase();
      parentDocument.body.classList.toggle(
        "prepflow-factory-idle",
        state === "not started" || state === "completed" || state === "not_started" || !state
      );
    };
    updateFactoryIdle();
    if (runState) {
      new MutationObserver(updateFactoryIdle).observe(runState, {
        subtree: true,
        childList: true,
        characterData: true,
      });
    }

    function activate(mode) {
      const questionMode = mode !== "factory";
      factory.hidden = questionMode;
      workspace.hidden = !questionMode;
      factoryButton.classList.toggle("active", mode === "factory");
      oldQuestionButton.classList.toggle("active", mode === "repair");
      addButton.classList.toggle("active", mode === "addition");
      parentDocument.defaultView.sessionStorage.setItem("prepflow.workbench.mode", mode);
      if (questionMode) setEmbeddedWorkspaceMode(mode);
      reportEmbeddedHeight();
    }

    factoryButton.addEventListener("click", () => activate("factory"));
    oldQuestionButton.addEventListener("click", () => activate("repair"));
    addButton.addEventListener("click", () => activate("addition"));

    const saved = parentDocument.defaultView.sessionStorage.getItem("prepflow.workbench.mode");
    const initial = saved === "addition" ? "addition" : saved === "repair" || saved === "questions" ? "repair" : "factory";
    activate(initial);
    setTimeout(() => activate(initial), 150);
  }

  function compactShell() {
    if (document.body.dataset.compactQuestionShell === "1") return;
    document.body.dataset.compactQuestionShell = "1";

    if (isEmbedded()) {
      const header = document.querySelector("body > header");
      if (header) header.hidden = true;
      document.body.classList.add("embedded-question-workbench");
      const operations = document.querySelector(".operations");
      if (operations) operations.hidden = true;
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
        if (embeddedMode === "repair" && (!$("record-view")?.hidden || !$("editor")?.hidden)) drawer.open = false;
        reportEmbeddedHeight();
      };
      const focusObserver = new MutationObserver(closeWhenFocused);
      if ($("record-view")) focusObserver.observe($("record-view"), {attributes: true, attributeFilter: ["hidden"]});
      if ($("editor")) focusObserver.observe($("editor"), {attributes: true, attributeFilter: ["hidden"]});
      drawer.addEventListener("toggle", reportEmbeddedHeight);
    }

    installParentShell();
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

    if (isEmbedded() && !embeddedModeApplied) {
      let parentMode = "repair";
      try {
        const saved = window.parent.sessionStorage.getItem("prepflow.workbench.mode");
        parentMode = saved === "addition" ? "addition" : "repair";
      } catch (_) {}
      setEmbeddedWorkspaceMode(parentMode);
    } else if (isEmbedded()) {
      updateModePresentation();
    }
    reportEmbeddedHeight();
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
  window.addEventListener("resize", reportEmbeddedHeight);
  schedule();
})();