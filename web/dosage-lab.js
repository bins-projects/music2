(() => {
  const board = document.querySelector("#dosage-board");
  const homeButton = document.querySelector("#dosage-home");

  if (!board) return;

  const SESSION_LENGTH = 5;
  let questions = [];
  let questionIndex = 0;
  let correctCount = 0;
  let currentAnswered = false;

  function choice(values) {
    return values[Math.floor(Math.random() * values.length)];
  }

  function round(value, places = 1) {
    const factor = 10 ** places;
    return Math.round((value + Number.EPSILON) * factor) / factor;
  }

  function generateMlHr() {
    const options = [
      [1000, 8], [1000, 10], [500, 4], [500, 5], [250, 2],
      [150, 1.5], [100, 0.5], [250, 2.5], [1000, 12], [500, 8]
    ];
    const [volumeMl, hours] = choice(options);
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

  function generateGttMin() {
    const options = [
      [1000, 8, 15], [500, 4, 20], [1000, 10, 10], [250, 2, 15],
      [500, 6, 20], [1000, 12, 15], [250, 4, 10], [120, 2, 60]
    ];
    const [volumeMl, hours, dropFactor] = choice(options);
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

  function generateInfusionTime() {
    const options = [
      [1000, 125], [500, 100], [250, 125], [1000, 100],
      [500, 125], [250, 100], [100, 200], [500, 80]
    ];
    const [volumeMl, rateMlHr] = choice(options);
    const hours = volumeMl / rateMlHr;
    const answer = round(hours, 2);

    let displayTime;
    if (Number.isInteger(hours)) {
      displayTime = `${hours} ${hours === 1 ? "hour" : "hours"}`;
    } else {
      const wholeHours = Math.floor(hours);
      const minutes = Math.round((hours - wholeHours) * 60);
      displayTime = `${wholeHours ? `${wholeHours} hr ` : ""}${minutes} min`;
    }

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

  const generators = [generateMlHr, generateGttMin, generateInfusionTime];

  function buildSession() {
    const session = [];
    while (session.length < SESSION_LENGTH) {
      session.push(choice(generators)());
    }
    return session;
  }

  function renderWelcome() {
    board.innerHTML = `
      <h1 class="board-title board-hand">Dosage Calculations</h1>
      <p class="board-subtitle board-hand">Need to study the formulas first?</p>
      <p class="board-copy">Review two worked examples, or jump straight into a five-question practice set.</p>
      <div class="board-actions">
        <button class="board-button" type="button" data-action="review">Review formulas</button>
        <button class="board-button primary" type="button" data-action="start">Start practice</button>
      </div>
    `;
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
        <button class="board-button primary" type="button" data-action="start">Start practice</button>
      </div>
    `;
  }

  function startSession() {
    questions = buildSession();
    questionIndex = 0;
    correctCount = 0;
    currentAnswered = false;
    renderQuestion();
  }

  function renderQuestion() {
    currentAnswered = false;
    const problem = questions[questionIndex];
    board.innerHTML = `
      <div class="problem-meta">
        <span>Question ${questionIndex + 1} of ${SESSION_LENGTH}</span>
        <span>${problem.type}</span>
      </div>
      <h1 class="board-title board-hand">Calculate the dose</h1>
      <p class="problem-text board-hand">${problem.prompt}</p>
      <div class="answer-row">
        <label class="sr-only" for="dosage-answer">Your answer</label>
        <input id="dosage-answer" class="answer-input" type="number" step="any" inputmode="decimal" autocomplete="off">
        <span class="answer-unit">${problem.unit}</span>
      </div>
      <div class="board-actions">
        <button class="board-button primary" type="button" data-action="submit">Submit answer</button>
      </div>
      <div id="dosage-feedback" class="feedback" hidden aria-live="polite"></div>
    `;

    const input = board.querySelector("#dosage-answer");
    input?.focus();
    input?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") submitAnswer();
    });
  }

  function submitAnswer() {
    if (currentAnswered) return;
    const input = board.querySelector("#dosage-answer");
    const feedback = board.querySelector("#dosage-feedback");
    const submitButton = board.querySelector('[data-action="submit"]');
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

    feedback.hidden = false;
    feedback.innerHTML = `
      <h2 class="feedback-result">${isCorrect ? "Correct" : `Not quite — ${problem.answer} ${problem.unit}`}</h2>
      <p class="solution-work">${problem.solution}</p>
      ${isCorrect ? "" : `
        <div class="board-actions">
          <button class="board-button" type="button" data-action="toggle-formula" aria-expanded="false">Formula</button>
        </div>
        <section id="missed-formula" class="formula-card" hidden>
          <h3 class="board-hand">Formula</h3>
          <div class="formula-equation">${problem.formula}</div>
          <p>${problem.formulaNote}</p>
        </section>
      `}
      <div class="board-actions">
        <button class="board-button primary" type="button" data-action="next">${questionIndex + 1 === SESSION_LENGTH ? "See results" : "Next problem"}</button>
      </div>
    `;
  }

  function toggleMissedFormula(button) {
    const formula = board.querySelector("#missed-formula");
    if (!formula) return;

    const willShow = formula.hidden;
    formula.hidden = !willShow;
    button.setAttribute("aria-expanded", String(willShow));
    button.textContent = willShow ? "Hide formula" : "Formula";
  }

  function nextQuestion() {
    questionIndex += 1;
    if (questionIndex >= SESSION_LENGTH) {
      renderSummary();
      return;
    }
    renderQuestion();
  }

  function renderSummary() {
    const percent = Math.round((correctCount / SESSION_LENGTH) * 100);
    board.innerHTML = `
      <h1 class="board-title board-hand">Practice Complete</h1>
      <div class="summary-score">${correctCount} / ${SESSION_LENGTH}</div>
      <p class="board-subtitle board-hand">${percent}% correct</p>
      <div class="board-actions">
        <button class="board-button primary" type="button" data-action="start">Try another set</button>
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
    if (action === "start") startSession();
    if (action === "submit") submitAnswer();
    if (action === "next") nextQuestion();
    if (action === "toggle-formula") toggleMissedFormula(button);
  });

  homeButton?.addEventListener("click", () => {
    window.location.href = "./";
  });

  renderWelcome();
})();
