(function () {
  const initialPhoneQuery = window.matchMedia(
    "(max-width: 820px) and (pointer: coarse)"
  );

  if (initialPhoneQuery.matches) {
    const viewport = document.querySelector('meta[name="viewport"]');
    if (viewport) {
      viewport.setAttribute(
        "content",
        "width=1200, initial-scale=1, viewport-fit=cover"
      );
    }

    document.documentElement.dataset.unifiedPhoneUi = "true";

    const unifiedPhoneStyle = document.createElement("style");
    unifiedPhoneStyle.id = "unified-phone-ui-styles";
    unifiedPhoneStyle.textContent = `
      html[data-unified-phone-ui="true"] #quiz-screen.quiz-screen:not([hidden]) {
        box-sizing: border-box !important;
        padding:
          max(env(safe-area-inset-top), 12px)
          max(env(safe-area-inset-right), 12px)
          max(env(safe-area-inset-bottom), 12px)
          max(env(safe-area-inset-left), 12px) !important;
      }

      html[data-unified-phone-ui="true"] #quiz-screen .quiz-book {
        transform-origin: center center !important;
      }

      html[data-unified-phone-ui="true"] #phone-orientation-hint {
        display: none;
        position: fixed;
        z-index: 9999;
        left: 50%;
        top: max(env(safe-area-inset-top), 12px);
        transform: translateX(-50%);
        padding: 7px 12px;
        border: 1px solid rgba(220, 174, 73, .72);
        border-radius: 999px;
        color: #fff1bd;
        background: rgba(9, 10, 42, .86);
        font: 800 12px/1.15 Arial, Helvetica, sans-serif;
        letter-spacing: .02em;
        box-shadow: 0 3px 10px rgba(0, 0, 0, .28);
        pointer-events: none;
      }

      @media (orientation: portrait) {
        html[data-unified-phone-ui="true"] body:has(#quiz-screen:not([hidden])) #phone-orientation-hint {
          display: block;
        }
      }
    `;
    document.head.appendChild(unifiedPhoneStyle);

    function ensureOrientationHint() {
      if (document.getElementById("phone-orientation-hint")) return;
      const hint = document.createElement("div");
      hint.id = "phone-orientation-hint";
      hint.setAttribute("aria-hidden", "true");
      hint.textContent = "Rotate to landscape for the full book view";
      document.body.appendChild(hint);
    }

    function fitQuizBookToPhoneViewport() {
      const book = document.querySelector("#quiz-screen .quiz-book");
      if (!book) return;

      const viewportWidth = window.visualViewport?.width || window.innerWidth;
      const viewportHeight = window.visualViewport?.height || window.innerHeight;
      const horizontalRoom = Math.max(320, viewportWidth - 40);
      const verticalRoom = Math.max(260, viewportHeight - 44);
      const bookRatio = 1.72;
      const fittedWidth = Math.min(horizontalRoom, verticalRoom * bookRatio, 1420);
      const fittedHeight = fittedWidth / bookRatio;

      book.style.setProperty("width", `${fittedWidth}px`, "important");
      book.style.setProperty("height", `${fittedHeight}px`, "important");
    }

    function syncPhoneQuizLayout() {
      ensureOrientationHint();
      fitQuizBookToPhoneViewport();
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", syncPhoneQuizLayout, { once: true });
    } else {
      syncPhoneQuizLayout();
    }

    window.addEventListener("resize", syncPhoneQuizLayout);
    window.addEventListener("orientationchange", syncPhoneQuizLayout);
    window.visualViewport?.addEventListener("resize", syncPhoneQuizLayout);
  }

  const portraitQuery = window.matchMedia(
    "(max-width: 760px) and (orientation: portrait)"
  );

  function syncMobilePortraitMode() {
    document.documentElement.classList.toggle(
      "mobile-portrait",
      portraitQuery.matches
    );
  }

  syncMobilePortraitMode();

  if (typeof portraitQuery.addEventListener === "function") {
    portraitQuery.addEventListener("change", syncMobilePortraitMode);
  } else {
    portraitQuery.addListener(syncMobilePortraitMode);
  }
}());
