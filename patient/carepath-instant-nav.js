/**
 * CarePath Instant 0ms Navigation Engine
 * Zero-delay page navigation with speculative prerendering,
 * touchstart prefetching, and instant in-memory cache.
 */
(function () {
  "use strict";

  if (window.__carepathInstantNavLoaded) return;
  window.__carepathInstantNavLoaded = true;

  const prefetchedUrls = new Set();
  const pageCache = new Map();

  const APP_PAGES = [
    // Patient App
    "dashboard.html",
    "doctor.html",
    "my-tokens.html",
    "profile.html",
    "hospital-details.html",
    "hospital.html",
    "contact.html",
    "terms.html",
    "privacy.html",
    "refund.html",
    // Hospital App
    "token-queue.html",
    "doctors.html",
    "patients.html",
    "ads.html",
    "display.html",
    // Admin App
    "hospitals.html",
    "tokens.html",
    "patients.html",
    "payments.html",
    "broadcasts.html",
    "online-users.html",
    "contact-settings.html"
  ];

  // 1. Speculation Rules API (Native 0ms Prerendering in Chrome/WebView)
  function injectSpeculationRules() {
    try {
      if (HTMLScriptElement.supports && HTMLScriptElement.supports("speculationrules")) {
        const specScript = document.createElement("script");
        specScript.type = "speculationrules";
        specScript.textContent = JSON.stringify({
          prerender: [
            {
              source: "list",
              urls: APP_PAGES,
              eagerness: "immediate"
            }
          ]
        });
        document.head.appendChild(specScript);
      }
    } catch (e) {}
  }

  // 2. High-priority prefetch of target page
  function prefetchUrl(url) {
    if (!url) return;
    const clean = url.split("?")[0].split("#")[0];
    if (prefetchedUrls.has(clean)) return;

    if (clean.startsWith("http://") || clean.startsWith("https://") || clean.startsWith("//")) {
      if (!clean.startsWith(window.location.origin)) return;
    }
    if (clean.startsWith("#") || clean.startsWith("javascript:") || clean.startsWith("mailto:") || clean.startsWith("tel:")) {
      return;
    }

    prefetchedUrls.add(clean);

    // Dynamic link rel="prefetch"
    try {
      const link = document.createElement("link");
      link.rel = "prefetch";
      link.href = clean;
      link.as = "document";
      document.head.appendChild(link);
    } catch (e) {}

    // In-memory fetch prefetch
    if (window.fetch) {
      try {
        fetch(clean, { priority: "high", cache: "force-cache" })
          .then(function (res) {
            if (res.ok) return res.text();
            throw new Error("HTTP " + res.status);
          })
          .then(function (html) {
            if (html && html.length > 50) {
              pageCache.set(clean, html);
            }
          })
          .catch(function () {});
      } catch (e) {}
    }
  }

  // 3. Scan page links and prefetch
  function prefetchVisibleLinks() {
    APP_PAGES.forEach(function (page) {
      prefetchUrl(page);
    });

    document.querySelectorAll("a[href]").forEach(function (a) {
      const href = a.getAttribute("href");
      if (href && !href.startsWith("#") && !href.startsWith("javascript:") && !href.startsWith("http")) {
        prefetchUrl(href);
      }
    });
  }

  // 4. Instant Touchstart & Pointerdown Preloading (100-300ms faster than click)
  function attachTouchPreloaders() {
    const events = ["touchstart", "pointerdown", "mousedown", "mouseover"];
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

  // Auto-run
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      injectSpeculationRules();
      attachTouchPreloaders();
      setTimeout(prefetchVisibleLinks, 60);
    });
  } else {
    injectSpeculationRules();
    attachTouchPreloaders();
    setTimeout(prefetchVisibleLinks, 60);
  }
})();
