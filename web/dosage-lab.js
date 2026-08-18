(() => {
  const board = document.querySelector("#dosage-board");
  const homeButton = document.querySelector("#dosage-home");

  if (!board) return;

  let questions = [];
  let questionIndex = 0;
  let correctCount = 0;
  let currentAnswered = false;
  let sessionMode = "practice";
  let sessionLength = 10;
  let selectedTypeIds = [];

  function choice(values) {
    return values[Math.floor(Math.random() * values.length)];
  }

  function shuffle(values) {
    const result = [...values];
    for (let index = result.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(Math.random() * (index + 1));
      [result[index], result[swapIndex]] = [result[swapIndex], result[index]];
    }
    return result;
  }

  function round(value, places = 1) {
    const factor = 10 ** places;
    return Math.round((value + Number.EPSILON) * factor) / factor;
  }

  function generateMlHr() {
    const [volumeMl, hours] = choice([
      [1000, 8], [1000, 10], [500, 4], [500, 5], [250, 2],
      [150, 1.5], [100, 0.5], [250, 2.5], [1000, 12], [500, 8]
    ]);
    const answer = round(volumeMl / hours, 1);
    return {
      type: "mL/hr",
      prompt: `Infuse ${volumeMl.toLocaleString()} mL of IV fluid over ${hours} ${hours === 1 ? "hour" : "hours"}. What rate should the IV pump be programmed to?`,
      answer,
      unit: "mL/hr",
      tolerance: 0.05,
      formula: "mL ÷ hours = mL/hr",
      formulaNote: "Use the total IV volume as mL and the infusion duration as hours.",
      solution: `${volumeMl.toLocaleString()} mL ÷ ${hours} hr = ${answer} mL/hr`
    };
  }

  function generateMlHrFromMinutes() {
    const [volumeMl, minutes] = choice([
      [100, 30], [250, 90], [500, 150], [150, 45],
      [50, 30], [100, 45], [250, 120], [75, 30]
    ]);
    const hours = minutes / 60;
    const answer = round(volumeMl / hours, 1);
    return {
      type: "Minutes → mL/hr",
      prompt: `Infuse ${volumeMl.toLocaleString()} mL over ${minutes} minutes. What rate should the IV pump be programmed to?`,
      answer,
      unit: "mL/hr",
      tolerance: 0.05,
      formula: "mL ÷ (minutes ÷ 60) = mL/hr",
      formulaNote: "A pump rate is per hour, so convert ordered minutes to hours before dividing.",
      solution: `${minutes} min ÷ 60 = ${round(hours, 2)} hr\n${volumeMl.toLocaleString()} mL ÷ ${round(hours, 2)} hr = ${answer} mL/hr`
    };
  }

  function generateGttMin() {
    const [volumeMl, hours, dropFactor] = choice([
      [1000, 8, 15], [500, 4, 20], [1000, 10, 10], [250, 2, 15],
      [500, 6, 20], [1000, 12, 15], [250, 4, 10], [120, 2, 60]
    ]);
    const minutes = hours * 60;
    const raw = (volumeMl * dropFactor) / minutes;
    const answer = Math.round(raw);
    return {
      type: "gtt/min",
      prompt: `Infuse ${volumeMl.toLocaleString()} mL over ${hours} ${hours === 1 ? "hour" : "hours"}. The tubing drop factor is ${dropFactor} gtt/mL. Calculate the flow rate.`,
      answer,
      unit: "gtt/min",
      tolerance: 0.05,
      formula: "mL × gtt/mL ÷ minutes = gtt/min",
      formulaNote: "Convert hours to minutes first, then round the final answer to a whole drop.",
      solution: `${hours} hr × 60 = ${minutes} min\n(${volumeMl.toLocaleString()} mL × ${dropFactor} gtt/mL) ÷ ${minutes} min = ${round(raw, 2)}\nRound to a whole drop = ${answer} gtt/min`
    };
  }

  function generateGttFromMlHr() {
    const [rateMlHr, dropFactor] = choice([
      [100, 15], [125, 20], [150, 10], [75, 20],
      [80, 15], [120, 10], [60, 60], [125, 15]
    ]);
    const raw = (rateMlHr * dropFactor) / 60;
    const answer = Math.round(raw);
    return {
      type: "mL/hr → gtt/min",
      prompt: `An IV is infusing at ${rateMlHr} mL/hr. The tubing drop factor is ${dropFactor} gtt/mL. What gravity flow rate should be set?`,
      answer,
      unit: "gtt/min",
      tolerance: 0.05,
      formula: "mL/hr × gtt/mL ÷ 60 = gtt/min",
      formulaNote: "Multiply the hourly pump rate by the drop factor and divide by 60 minutes.",
      solution: `(${rateMlHr} mL/hr × ${dropFactor} gtt/mL) ÷ 60 = ${round(raw, 2)}\nRound to a whole drop = ${answer} gtt/min`
    };
  }

  function generateMlHrFromGtt() {
    const [gttMin, dropFactor] = choice([
      [25, 15], [42, 20], [20, 10], [60, 60],
      [30, 15], [40, 20], [15, 10], [50, 20]
    ]);
    const raw = (gttMin * 60) / dropFactor;
    const answer = round(raw, 1);
    return {
      type: "gtt/min → mL/hr",
      prompt: `An IV is running at ${gttMin} gtt/min using tubing with a drop factor of ${dropFactor} gtt/mL. What is the equivalent infusion rate?`,
      answer,
      unit: "mL/hr",
      tolerance: 0.05,
      formula: "gtt/min × 60 ÷ gtt/mL = mL/hr",
      formulaNote: "Convert drops per minute into drops per hour, then divide by the tubing drop factor.",
      solution: `(${gttMin} gtt/min × 60 min/hr) ÷ ${dropFactor} gtt/mL = ${answer} mL/hr`
    };
  }

  function generateInfusionTime() {
    const [volumeMl, rateMlHr] = choice([
      [1000, 125], [500, 100], [250, 125], [1000, 100],
      [500, 125], [250, 100], [100, 200], [500, 80]
    ]);
    const hours = volumeMl / rateMlHr;
    const answer = round(hours, 2);
    const wholeHours = Math.floor(hours);
    const minutes = Math.round((hours - wholeHours) * 60);
    const displayTime = Number.isInteger(hours)
      ? `${hours} ${hours === 1 ? "hour" : "hours"}`
      : `${wholeHours ? `${wholeHours} hr ` : ""}${minutes} min`;
    return {
      type: "Infusion time",
      prompt: `${volumeMl.toLocaleString()} mL of IV fluid is infusing at ${rateMlHr} mL/hr. How many hours will the infusion take? Enter your answer in hours.`,
      answer,
      unit: "hours",
      tolerance: 0.02,
      formula: "mL ÷ mL/hr = hours",
      formulaNote: "Divide the total volume by the hourly pump rate.",
      solution: `${volumeMl.toLocaleString()} mL ÷ ${rateMlHr} mL/hr = ${answer} hr\nInfusion time = ${displayTime}`
    };
  }

  const typeRegistry = [
    { id: "mlhr-hours", label: "mL/hr — hours", group: "IV Rates", generate: generateMlHr },
    { id: "mlhr-minutes", label: "mL/hr — minutes", group: "IV Rates", generate: generateMlHrFromMinutes },
    { id: "gtt-volume-time", label: "gtt/min — volume + time", group: "Gravity", generate: generateGttMin },
    { id: "gtt-from-mlhr", label: "mL/hr → gtt/min", group: "Gravity", generate: generateGttFromMlHr },
    { id: "mlhr-from-gtt", label: "gtt/min → mL/hr", group: "Gravity", generate: generateMlHrFromGtt },
    { id: "infusion-time", label: "Infusion duration", group: "IV Time", generate: generateInfusionTime }
  ];

  function renderWelcome() {
    board.innerHTML = `
      <h1 class="board-title board-hand">Dosage Calculations</h1>
      <p class="board-subtitle board-hand">How do you want to study?</p>
      <p class="board-copy">Choose exactly what you want to practice, combine several types, or let Dosage Lab mix them for you.</p>
      <div class="board-actions">
        <button class="board-button" type="button" data-action="review">Review formulas</button>
        <button class="board-button primary" type="button" data-action="setup">Build a session</button>
      </div>
    `;
  }

  function renderSetup() {
    const typeRows = typeRegistry.map((entry) => `
      <label class="setup-check">
        <input type="checkbox" name="question-type" value="${entry.id}">
        <span>${entry.label}</span>
      </label>
    `).join("");

    board.innerHTML = `
      <h1 class="board-title board-hand">Build a Session</h1>
      <div class="setup-layout">
        <section class="setup-section">
          <h3>Mode</h3>
          <div class="setup-choice-row">
            <label class="setup-radio"><input type="radio" name="session-mode" value="practice" checked><span>Practice</span></label>
            <label class="setup-radio"><input type="radio" name="session-mode" value="quiz"><span>Quiz</span></label>
          </div>
          <p class="setup-note"><strong>Practice:</strong> formula available while working. <strong>Quiz:</strong> no formula help.</p>
        </section>

        <section class="setup-section">
          <div class="setup-heading-row">
            <h3>Question types</h3>
            <button class="setup-text-button" type="button" data-action="random-mix">Random mix</button>
          </div>
          <div class="setup-type-grid">${typeRows}</div>
          <p class="setup-note">Pick one type to drill one formula, or select several.</p>
        </section>

        <section class="setup-section setup-length-section">
          <h3>Questions</h3>
          <div class="setup-choice-row">
            ${[5,10,15,25].map((count) => `<label class="setup-radio"><input type="radio" name="session-length" value="${count}" ${count === 10 ? "checked" : ""}><span>${count}</span></label>`).join("")}
          </div>
        </section>
      </div>
      <p id="setup-message" class="setup-message" aria-live="polite"></p>
      <div class="board-actions setup-actions">
        <button class="board-button" type="button" data-action="welcome">Back</button>
        <button class="board-button primary" type="button" data-action="start-configured">Start session</button>
      </div>
    `;
  }

  function chooseRandomMix() {
    board.querySelectorAll('input[name="question-type"]').forEach((input) => {
      input.checked = true;
    });
    const message = board.querySelector("#setup-message");
    if (message) message.textContent = "Random mix selected — all available types are included.";
  }

  function buildSession(generators, count) {
    const session = [];
    const order = shuffle(generators);
    let cursor = 0;
    while (session.length < count) {
      if (cursor >= order.length) {
        cursor = 0;
        order.splice(0, order.length, ...shuffle(generators));
      }
      session.push(order[cursor].generate());
      cursor += 1;
    }
    return session;
  }

  function startConfiguredSession() {
    const selectedMode = board.querySelector('input[name="session-mode"]:checked');
    const selectedLength = board.querySelector('input[name="session-length"]:checked');
    const selectedInputs = [...board.querySelectorAll('input[name="question-type"]:checked')];
    const message = board.querySelector("#setup-message");

    if (!selectedInputs.length) {
      if (message) message.textContent = "Choose at least one question type, or tap Random mix.";
      return;
    }

    sessionMode = selectedMode?.value || "practice";
    sessionLength = Number(selectedLength?.value || 10);
    selectedTypeIds = selectedInputs.map((input) => input.value);

    const selectedGenerators = typeRegistry.filter((entry) => selectedTypeIds.includes(entry.id));
    questions = buildSession(selectedGenerators, sessionLength);
    questionIndex = 0;
    correctCount = 0;
    currentAnswered = false;
    renderQuestion();
  }

  function renderReference() {
    board.innerHTML = `
      <h1 class="board-title board-hand">Formula Review</h1>
      <div class="formula-grid">
        <section class="formula-card">
          <h3 class="board-hand">Pump rate — mL/hr</h3>
          <div class="formula-equation">mL ÷ hours = mL/hr</div>
          <p><strong>Example:</strong> Infuse 1,000 mL over 8 hr.</p>
          <p class="board-hand">1,000 ÷ 8 = 125</p>
          <p><strong>Answer: 125 mL/hr</strong></p>
        </section>
        <section class="formula-card">
          <h3 class="board-hand">Gravity flow — gtt/min</h3>
          <div class="formula-equation">mL × drop factor ÷ minutes</div>
          <p><strong>Example:</strong> 500 mL over 4 hr; tubing 20 gtt/mL.</p>
          <p class="board-hand">4 × 60 = 240 min</p>
          <p class="board-hand">500 × 20 ÷ 240 = 41.67</p>
          <p><strong>Answer: 42 gtt/min</strong></p>
        </section>
      </div>
      <div class="board-actions">
        <button class="board-button" type="button" data-action="welcome">Back</button>
        <button class="board-button primary" type="button" data-action="setup">Build a session</button>
      </div>
    `;
  }

  function renderQuestion() {
    currentAnswered = false;
    const problem = questions[questionIndex];
    const practiceFormula = sessionMode === "practice" ? `
      <button class="board-button" type="button" data-action="toggle-working-formula" aria-expanded="false">Formula</button>
    ` : "";

    board.innerHTML = `
      <div class="problem-meta">
        <span>${sessionMode === "practice" ? "Practice" : "Quiz"} · Question ${questionIndex + 1} of ${sessionLength}</span>
        <span>${problem.type}</span>
      </div>
      <h1 class="board-title board-hand">Calculate the dose</h1>
      <p class="problem-text board-hand">${problem.prompt}</p>
      <section id="working-formula" class="working-formula" hidden>
        <div class="formula-equation">${problem.formula}</div>
        <p>${problem.formulaNote}</p>
      </section>
      <div class="answer-row">
        <label class="sr-only" for="dosage-answer">Your answer</label>
        <input id="dosage-answer" class="answer-input" type="number" step="any" inputmode="decimal" autocomplete="off">
        <span class="answer-unit">${problem.unit}</span>
      </div>
      <div class="board-actions">
        <button class="board-button primary" type="button" data-action="submit">Submit answer</button>
        ${practiceFormula}
      </div>
      <div id="dosage-feedback" class="feedback" hidden aria-live="polite"></div>
    `;

    const input = board.querySelector("#dosage-answer");
    input?.focus();
    input?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") submitAnswer();
    });
  }

  function toggleWorkingFormula(button) {
    const formula = board.querySelector("#working-formula");
    if (!formula) return;
    const willShow = formula.hidden;
    formula.hidden = !willShow;
    button.setAttribute("aria-expanded", String(willShow));
    button.textContent = willShow ? "Hide formula" : "Formula";
  }

  function submitAnswer() {
    if (currentAnswered) return;
    const input = board.querySelector("#dosage-answer");
    const feedback = board.querySelector("#dosage-feedback");
    const submitButton = board.querySelector('[data-action="submit"]');
    const formulaButton = board.querySelector('[data-action="toggle-working-formula"]');
    const problem = questions[questionIndex];

    if (!input || input.value.trim() === "") {
      input?.focus();
      return;
    }

    const student = Number(input.value);
    if (!Number.isFinite(student)) return;

    const isCorrect = Math.abs(student - problem.answer) <= problem.tolerance;
    currentAnswered = true;
    if (isCorrect) correctCount += 1;

    input.disabled = true;
    if (submitButton) submitButton.hidden = true;
    if (formulaButton) formulaButton.hidden = true;

    const showWorkedSolution = sessionMode === "practice";
    feedback.hidden = false;
    feedback.innerHTML = `
      <h2 class="feedback-result">${isCorrect ? "Correct" : `Not quite — ${problem.answer} ${problem.unit}`}</h2>
      ${showWorkedSolution ? `<p class="solution-work">${problem.solution}</p>` : ""}
      <div class="board-actions">
        <button class="board-button primary" type="button" data-action="next">${questionIndex + 1 === sessionLength ? "See results" : "Next problem"}</button>
      </div>
    `;
  }

  function nextQuestion() {
    questionIndex += 1;
    if (questionIndex >= sessionLength) {
      renderSummary();
      return;
    }
    renderQuestion();
  }

  function renderSummary() {
    const percent = Math.round((correctCount / sessionLength) * 100);
    board.innerHTML = `
      <h1 class="board-title board-hand">${sessionMode === "practice" ? "Practice" : "Quiz"} Complete</h1>
      <div class="summary-score">${correctCount} / ${sessionLength}</div>
      <p class="board-subtitle board-hand">${percent}% correct</p>
      <div class="board-actions">
        <button class="board-button primary" type="button" data-action="setup">Build another session</button>
        <button class="board-button" type="button" data-action="review">Review formulas</button>
      </div>
    `;
  }

  board.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;

    const action = button.dataset.action;
    if (action === "review") renderReference();
    if (action === "welcome") renderWelcome();
    if (action === "setup") renderSetup();
    if (action === "random-mix") chooseRandomMix();
    if (action === "start-configured") startConfiguredSession();
    if (action === "submit") submitAnswer();
    if (action === "next") nextQuestion();
    if (action === "toggle-working-formula") toggleWorkingFormula(button);
  });

  homeButton?.addEventListener("click", () => {
    window.location.href = "./";
  });

  renderWelcome();
})();
