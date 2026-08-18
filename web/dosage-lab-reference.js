(() => {
  const board = document.querySelector("#dosage-board");
  if (!board) return;

  const pages = [
    {
      title: "Formula Review · 1 of 2",
      sections: [
        ["Basic medication dose", "Desired ÷ Have × Quantity = amount to give", "Use for tablets, capsules, liquids, and injectable volumes."],
        ["Weight-based dose", "mg/kg/dose × kg = mg per dose", "If the order is mg/kg/day, find the daily dose first, then divide by doses per day."],
        ["Pump rate — hours", "mL ÷ hours = mL/hr", "Example: 1,000 mL ÷ 8 hr = 125 mL/hr."],
        ["Pump rate — minutes", "mL ÷ (minutes ÷ 60) = mL/hr", "Example: 100 mL over 30 min → 100 ÷ 0.5 = 200 mL/hr."],
        ["Infusion duration", "mL ÷ mL/hr = hours", "Convert the decimal part of an hour to minutes when needed."],
        ["Completion time", "start time + infusion duration = finish time", "Carry across midnight when necessary."],
        ["Gravity flow", "(mL × gtt/mL) ÷ minutes = gtt/min", "Convert hours to minutes first. Round to a whole drop."],
        ["Known mL/hr → gtt/min", "(mL/hr × gtt/mL) ÷ 60 = gtt/min", "Round the final answer to a whole drop."]
      ]
    },
    {
      title: "Formula Review · 2 of 2",
      sections: [
        ["Known gtt/min → mL/hr", "(gtt/min × 60) ÷ gtt/mL = mL/hr", "Convert the gravity rate back to an hourly pump rate."],
        ["Reconstitution", "ordered dose ÷ resulting concentration = mL to draw", "Use the label's resulting concentration—not simply the amount of diluent added."],
        ["Units/hr infusion", "ordered units/hr ÷ units/mL = mL/hr", "Common format for heparin- or insulin-style workbook problems."],
        ["mcg/min infusion", "(mcg/min × 60) ÷ mcg/mL = mL/hr", "Convert the ordered minute dose to an hourly amount before dividing by concentration."],
        ["mcg/kg/min infusion", "(mcg/kg/min × kg × 60) ÷ mcg/mL = mL/hr", "Weight first, then convert minutes to hours."],
        ["mg/hr or g/hr infusion", "ordered amount/hr ÷ amount/mL = mL/hr", "Keep the numerator and concentration in matching units."],
        ["mEq to mL", "ordered mEq ÷ mEq/mL = mL", "Used for source-locked electrolyte and bicarbonate problems."],
        ["Daily divided dose", "mg/kg/day × kg ÷ doses/day = mg per dose", "q6h = 4/day · q8h = 3/day · q12h = 2/day · q24h = 1/day."]
      ]
    }
  ];

  let pageIndex = 0;

  function renderPage(index) {
    pageIndex = Math.max(0, Math.min(index, pages.length - 1));
    const page = pages[pageIndex];
    const cards = page.sections.map(([name, formula, note]) => `
      <section class="formula-line-item">
        <h3>${name}</h3>
        <div class="formula-equation">${formula}</div>
        <p>${note}</p>
      </section>
    `).join("");

    board.innerHTML = `
      <h1 class="board-title board-hand">${page.title}</h1>
      <div class="formula-sheet-grid">${cards}</div>
      <nav class="formula-sheet-nav" aria-label="Formula review navigation">
        ${pageIndex > 0 ? '<button type="button" class="formula-text-action" data-ref-action="prev">← Previous</button>' : '<span></span>'}
        <button type="button" class="formula-text-action" data-ref-action="home">Back</button>
        ${pageIndex < pages.length - 1 ? '<button type="button" class="formula-text-action" data-ref-action="next">Next →</button>' : '<span></span>'}
      </nav>
    `;
  }

  document.addEventListener("click", (event) => {
    const reviewTrigger = event.target.closest('[data-action="review"]');
    if (reviewTrigger) {
      event.preventDefault();
      event.stopImmediatePropagation();
      renderPage(0);
      return;
    }

    const refAction = event.target.closest("[data-ref-action]");
    if (!refAction) return;
    event.preventDefault();
    event.stopImmediatePropagation();

    const action = refAction.dataset.refAction;
    if (action === "prev") renderPage(pageIndex - 1);
    if (action === "next") renderPage(pageIndex + 1);
    if (action === "home") {
      const setupTrigger = document.createElement("button");
      setupTrigger.dataset.action = "welcome";
      setupTrigger.hidden = true;
      board.appendChild(setupTrigger);
      setupTrigger.click();
    }
  }, true);
})();
