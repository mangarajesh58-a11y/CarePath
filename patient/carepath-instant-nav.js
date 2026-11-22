/**
 * Q-Arovia Instant Navigation Engine
 * Intent-driven, lightweight preloading with Speculation Rules and touch/hover prefetching.
 */
(function () {
  "use strict";

  if (window.__carepathInstantNavLoaded) return;
  window.__carepathInstantNavLoaded = true;

  const prefetchedUrls = new Set();

  // 1. Speculation Rules API (Prerender on hover/pointerdown with moderate eagerness)
  function injectSpeculationRules() {
    try {
      if (HTMLScriptElement.supports && HTMLScriptElement.supports("speculationrules")) {
        const specScript = document.createElement("script");
        specScript.type = "speculationrules";
        specScript.textContent = JSON.stringify({
          prerender: [
            {
              source: "document",
              where: {
                and: [
                  { href_matches: "/*" },
                  { not: { href_matches: ["*logout*", "*#*", "javascript:*", "mailto:*", "tel:*"] } }
                ]
              },
              eagerness: "moderate"
            }
          ]
        });
        document.head.appendChild(specScript);
      }
    } catch (e) {}
  }

  // 2. Intent-based link prefetch (only for user-targeted links)
  function prefetchUrl(url) {
    if (!url) return;
    const clean = url.split("?")[0].split("#")[0];
    if (prefetchedUrls.has(clean)) return;

    if (clean.startsWith("http://") || clean.startsWith("https://") || clean.startsWith("//")) {
      if (!clean.startsWith(window.location.origin)) return;
    }
    if (clean.startsWith("#") || clean.startsWith("javascript:") || clean.startsWith("mailto:") || clean.startsWith("tel:") || clean.includes("logout")) {
      return;
    }

    prefetchedUrls.add(clean);

    try {
      const link = document.createElement("link");
      link.rel = "prefetch";
      link.href = clean;
      link.as = "document";
      document.head.appendChild(link);
    } catch (e) {}
  }

  // 3. User interaction listener: prefetch on hover or touch/pointer intent
  function attachIntentPreloaders() {
    const events = ["touchstart", "pointerdown", "mouseover", "focusin"];
    events.forEach(function (evt) {
      document.addEventListener(
        evt,
        function (e) {
          const target = e.target.closest("a[href], .dock-item, .module-card, [data-href]");
          if (!target) return;
          const href = target.getAttribute("href") || target.getAttribute("data-href");
          if (href) {
            prefetchUrl(href);
          }
        },
        { passive: true }
      );
    });
  }

  // Initialize once DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      injectSpeculationRules();
      attachIntentPreloaders();
    });
  } else {
    injectSpeculationRules();
    attachIntentPreloaders();
  }
})();
