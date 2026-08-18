(() => {
  const board = document.querySelector("#dosage-board");
  if (!board) return;

  function normalizeUnit(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "")
      .replace(/milliliters?|millilitres?/g, "ml")
      .replace(/hours?|hrs?/g, "hr")
      .replace(/drops?/g, "gtt");
  }

  function unitMatches(typed, expected) {
    const t = normalizeUnit(typed);
    const e = normalizeUnit(expected);
    if (!t || !e) return false;
    if (e === "hr") return ["hr", "hour", "hours"].includes(t);
    return t === e;
  }

  function decorateQuestion() {
    const input = board.querySelector("#dosage-answer");
    if (!input || input.dataset.unitReady === "true") return;

    const unitNode = board.querySelector(".answer-unit");
    const expectedUnit = unitNode?.textContent?.trim() || "";
    input.dataset.expectedUnit = expectedUnit;
    input.dataset.unitReady = "true";
    input.type = "text";
    input.inputMode = "text";
    input.removeAttribute("step");
    input.setAttribute("autocomplete", "off");
    input.setAttribute("spellcheck", "false");
    input.setAttribute("aria-label", `Answer including unit${expectedUnit ? `, such as ${expectedUnit}` : ""}`);

    const row = input.closest(".answer-row");
    if (row && !board.querySelector("#unit-entry-message")) {
      const msg = document.createElement("p");
      msg.id = "unit-entry-message";
      msg.className = "unit-entry-message";
      msg.setAttribute("aria-live", "polite");
      row.insertAdjacentElement("afterend", msg);
    }
  }

  const observer = new MutationObserver(decorateQuestion);
  observer.observe(board, { childList: true, subtree: true });
  decorateQuestion();

  board.addEventListener("click", (event) => {
    const submit = event.target.closest('[data-action="submit"]');
    if (!submit) return;

    const input = board.querySelector("#dosage-answer");
    const message = board.querySelector("#unit-entry-message");
    if (!input || input.disabled) return;

    const raw = input.value.trim();
    const match = raw.match(/^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(.*?)\s*$/);
    const expectedUnit = input.dataset.expectedUnit || "";

    if (!match) {
      event.preventDefault();
      event.stopPropagation();
      if (message) message.textContent = "Write the number and the unit.";
      input.focus();
      return;
    }

    const [, numeric, typedUnit] = match;
    if (!unitMatches(typedUnit, expectedUnit)) {
      event.preventDefault();
      event.stopPropagation();
      if (message) message.textContent = "Include the correct unit with your answer.";
      input.focus();
      return;
    }

    input.dataset.fullAnswer = raw;
    input.value = numeric;
    if (message) message.textContent = "";

    queueMicrotask(() => {
      const current = board.querySelector("#dosage-answer");
      if (current && current.disabled && current.dataset.fullAnswer) {
        current.value = current.dataset.fullAnswer;
      }
    });
  }, true);
})();
