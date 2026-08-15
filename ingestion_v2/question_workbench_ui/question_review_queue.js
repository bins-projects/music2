(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let lastSignature = null;
  let refreshTimer = null;

  async function request(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Review queue request failed");
    return payload;
  }

  function ensurePanel() {
    let panel = $("submitted-review-panel");
    if (panel) return panel;
    const needsReview = $("needs-review")?.closest("section.panel");
    if (!needsReview) return null;

    panel = document.createElement("section");
    panel.id = "submitted-review-panel";
    panel.className = "panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="row">
        <div>
          <p class="eyebrow">LEARNER SUBMISSIONS</p>
          <h2>Submitted for review <span id="submitted-review-count"></span></h2>
        </div>
        <button id="submitted-review-refresh" type="button" class="secondary">Refresh</button>
      </div>
      <p>Questions learners sent for review from the public study site.</p>
      <div id="submitted-review-list" class="pending" aria-live="polite"></div>
    `;
    needsReview.parentNode.insertBefore(panel, needsReview);
    $("submitted-review-refresh")?.addEventListener("click", refresh);
    return panel;
  }

  function openReport(report) {
    if (!report.available) return;
    const pack = $("pack");
    const search = $("search");
    const form = $("search-form");
    const results = $("search-results");
    if (!pack || !search || !form || !results) return;

    const clickResult = new MutationObserver(() => {
      const row = results.querySelector("button.result");
      if (!row) return;
      clickResult.disconnect();
      row.click();
    });
    clickResult.observe(results, { childList: true, subtree: true });

    pack.value = report.pack_id;
    pack.dispatchEvent(new Event("change", { bubbles: true }));
    window.setTimeout(() => {
      const chapter = $("chapter");
      if (chapter) chapter.value = "";
      search.value = report.question_id;
      form.requestSubmit();
    }, 0);
  }

  async function clearReport(report, button) {
    button.disabled = true;
    try {
      await request("/api/question-review-reports/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_id: report.question_id }),
      });
      lastSignature = null;
      await refresh();
    } catch (error) {
      button.disabled = false;
      alert(error.message);
    }
  }

  function render(payload) {
    const panel = ensurePanel();
    if (!panel) return;
    const reports = Array.isArray(payload.reports) ? payload.reports : [];
    const signature = JSON.stringify({ configured: payload.configured, reports });
    if (signature === lastSignature) return;
    lastSignature = signature;

    const additionMode = document.querySelector('[data-mode="addition"]')?.classList.contains("active");
    panel.hidden = !payload.configured || additionMode;
    if (!payload.configured) return;

    $("submitted-review-count").textContent = `(${reports.length.toLocaleString()})`;
    const target = $("submitted-review-list");
    target.replaceChildren();

    if (!reports.length) {
      const empty = document.createElement("p");
      empty.textContent = "No learner-submitted questions are waiting for review.";
      target.append(empty);
      return;
    }

    reports.forEach((report) => {
      const card = document.createElement("div");
      card.className = "pending-card";

      const content = document.createElement("div");
      const heading = document.createElement("strong");
      heading.textContent = report.available
        ? `${report.pack_title} · Chapter ${report.chapter} · ${report.question_id}`
        : report.question_id;
      const detail = document.createElement("small");
      detail.textContent = report.available
        ? `${report.stem}${Number(report.report_count || 1) > 1 ? ` · sent ${report.report_count} times` : ""}`
        : "This PFQ ID is not present in the installed canonical Packs.";
      content.append(heading, detail);

      const actions = document.createElement("div");
      actions.className = "pending-actions";
      const open = document.createElement("button");
      open.type = "button";
      open.textContent = "Open question";
      open.disabled = !report.available;
      open.addEventListener("click", () => openReport(report));
      const clear = document.createElement("button");
      clear.type = "button";
      clear.className = "secondary";
      clear.textContent = "Clear report";
      clear.addEventListener("click", () => { void clearReport(report, clear); });
      actions.append(open, clear);
      card.append(content, actions);
      target.append(card);
    });
  }

  async function refresh() {
    clearTimeout(refreshTimer);
    try {
      render(await request("/api/question-review-reports"));
    } catch (error) {
      const panel = ensurePanel();
      if (!panel) return;
      panel.hidden = false;
      $("submitted-review-count").textContent = "";
      $("submitted-review-list").textContent = error.message;
    }
  }

  document.addEventListener("click", (event) => {
    if (event.target?.matches('[data-mode="repair"]')) {
      window.setTimeout(() => { lastSignature = null; void refresh(); }, 0);
    }
    if (event.target?.matches('[data-mode="addition"]')) {
      const panel = ensurePanel();
      if (panel) panel.hidden = true;
    }
    if (event.target?.id === "final-action") {
      refreshTimer = window.setTimeout(() => { lastSignature = null; void refresh(); }, 1200);
    }
  });

  $("refresh")?.addEventListener("click", () => { lastSignature = null; void refresh(); });
  void refresh();
})();
