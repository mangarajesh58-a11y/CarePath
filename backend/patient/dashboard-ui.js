
/* ============================================================
   CarePath Patient Dashboard
   Hospital listing, search, filters, recent hospitals
   ============================================================ */

(function () {
  "use strict";

  const API_BASE = "https://carepath-3q9q.onrender.com";
  const RECENT_KEY = "CarePathRecentlyViewed";

  const FALLBACK_HOSPITAL_PHOTOS = [
    "https://images.unsplash.com/photo-1586773860418-d37222d8fce3?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1519494026892-80bbd2d6fd0d?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1538108149393-fbbd81895907?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1516549655169-df83a0774514?auto=format&fit=crop&w=900&q=80"
  ];

  let hospitalRecords = [];
  let activeSponsoredAds = [];
  let activeFilter = "all";
  let activeQuery = "";
  let requestController = null;

  const byId = (id) => document.getElementById(id);

  document.addEventListener("DOMContentLoaded", initializeDashboard);

  function initializeDashboard() {
    const search = byId("hospitalSearch");
    const clearButton = byId("clearSearch");
    const logoutButton = byId("logoutButton");
    const patientName = byId("patientName");

    if (patientName) {
      const savedName =
        localStorage.getItem("patientName") ||
        localStorage.getItem("patient_name") ||
        localStorage.getItem("full_name");

      if (savedName) {
        patientName.textContent = savedName;
      }
    }

    if (search) {
      search.addEventListener("input", function () {
        activeQuery = search.value.trim().toLowerCase();
        renderHospitalCards();
      });
    }

    if (clearButton) {
      clearButton.addEventListener("click", function () {
        if (search) {
          search.value = "";
          search.focus();
        }

        activeQuery = "";
        renderHospitalCards();
      });
    }

    document.querySelectorAll("[data-filter]").forEach(function (button) {
      button.addEventListener("click", function () {
        activeFilter = button.dataset.filter || "all";

        document.querySelectorAll("[data-filter]").forEach(function (item) {
          item.classList.toggle("active", item === button);
        });

        renderHospitalCards();
      });
    });

    document.querySelectorAll("[data-query]").forEach(function (button) {
      button.addEventListener("click", function () {
        const query = button.dataset.query || "";

        if (search) {
          search.value = query;
        }

        activeQuery = query.trim().toLowerCase();
        renderHospitalCards();

        const container = byId("hospitalCards");

        if (container) {
          container.scrollIntoView({
            behavior: "smooth",
            block: "start"
          });
        }
      });
    });

    if (logoutButton) {
      logoutButton.addEventListener("click", function () {
        [
          "patientName",
          "patient_name",
          "full_name",
          "patientToken",
          "patient_token",
          "patient"
        ].forEach(function (key) {
          localStorage.removeItem(key);
        });

        window.location.href = "./index.html";
      });
    }

    // Show previously viewed hospitals immediately.
    renderRecentHospitals();

    // Check if patient navigated with direct hospital link (?id=... or ?hospital_id=...)
    const urlParams = new URLSearchParams(window.location.search);
    const targetHospId = urlParams.get("id") || urlParams.get("hospital_id") || urlParams.get("hospitalId");
    if (targetHospId) {
        localStorage.setItem("selectedHospitalId", String(targetHospId));
        localStorage.setItem("hospital_id", String(targetHospId));
        localStorage.setItem("hospitalId", String(targetHospId));
        window.location.replace("./hospital-details.html?id=" + encodeURIComponent(targetHospId));
        return;
    }

    // Load current hospital records from the backend.
    loadHospitalsForCards();
  }

  async function loadHospitalsForCards() {
    const container = byId("hospitalCards");
    const empty = byId("emptyHospitals");
    const count = byId("hospitalCount");

    if (!container) {
      console.error('CarePath: Missing element id="hospitalCards".');
      return;
    }

    container.innerHTML =
      '<div class="loading-card">' +
      '<span class="spinner"></span>' +
      '<span>Loading hospitals from CarePath...</span>' +
      "</div>";

    if (empty) empty.hidden = true;
    if (count) count.textContent = "Loading hospitals...";

    if (requestController) {
      requestController.abort();
    }

    const controller = new AbortController();
    requestController = controller;

    const timeoutId = setTimeout(function () {
      controller.abort();
    }, 12000);

    try {
      const response = await fetch(API_BASE + "/hospitals", {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error("Hospital API returned HTTP " + response.status);
      }

      const payload = await response.json();

      if (Array.isArray(payload)) {
        hospitalRecords = payload;
      } else if (payload && Array.isArray(payload.hospitals)) {
        hospitalRecords = payload.hospitals;
      } else if (payload && Array.isArray(payload.data)) {
        hospitalRecords = payload.data;
      } else {
        throw new Error("Unexpected hospital API response format.");
      }

      console.log(
        "CarePath: Hospital records received:",
        hospitalRecords.length
      );

      renderHospitalCards();
      renderRecentHospitals();
      fetchActiveAds();
    } catch (error) {
      if (error.name === "AbortError") {
        console.error("CarePath: Hospital request timed out or was cancelled.");
      } else {
        console.error("CarePath hospital loading error:", error);
      }

      container.replaceChildren();

      const message = makeElement(
        "div",
        "empty-state",
        error.name === "AbortError"
          ? "The hospital request timed out. Please refresh and try again."
          : "Unable to load hospitals. Please check your connection and try again."
      );

      if (empty) {
        empty.hidden = false;
        empty.textContent = message.textContent;
      } else {
        container.appendChild(message);
      }

      if (count) count.textContent = "Could not load hospitals";
    } finally {
      clearTimeout(timeoutId);

      if (requestController === controller) {
        requestController = null;
      }
    }
  }

  function hospitalName(hospital) {
    return String(
      hospital.name ||
      hospital.hospital_name ||
      hospital.hospital ||
      "Hospital"
    );
  }

  function hospitalCity(hospital) {
    return String(
      hospital.city ||
      hospital.location ||
      hospital.address ||
      "Location not provided"
    );
  }

  function hospitalId(hospital) {
    return hospital.id ?? hospital.hospital_id ?? hospital.hospitalId;
  }

  function isVerified(hospital) {
    const status = String(
      hospital.verification_status ||
      hospital.approval_status ||
      hospital.status ||
      ""
    ).toLowerCase();

    return (
      hospital.is_verified === true ||
      hospital.verified === true ||
      status === "verified" ||
      status === "approved"
    );
  }

  function tokenFee(hospital) {
    const fee = Number(hospital.token_fee ?? hospital.tokenFee ?? 0);

    return Number.isFinite(fee) && fee >= 0 ? fee : 0;
  }

  function hospitalPhoto(hospital, index) {
    const images = Array.isArray(hospital.images)
      ? hospital.images
      : [];

    const candidate =
      hospital.cover_image_url ||
      hospital.hospital_image_url ||
      hospital.image_url ||
      hospital.photo_url ||
      hospital.hospital_photo ||
      hospital.photo ||
      hospital.image ||
      images[0] ||
      "";

    if (typeof candidate === "string" && candidate.trim()) {
      const value = candidate.trim();

      if (/^https?:\/\//i.test(value)) {
        return value;
      }

      if (value.startsWith("/")) {
        return API_BASE + value;
      }

      return API_BASE + "/" + value;
    }

    return FALLBACK_HOSPITAL_PHOTOS[
      index % FALLBACK_HOSPITAL_PHOTOS.length
    ];
  }

  
  async function fetchActiveAds() {
    try {
      const response = await fetch(API_BASE + "/ads/active", {
        headers: { Accept: "application/json" }
      });
      if (!response.ok) return;
      const data = await response.json();
      if (Array.isArray(data)) {
        activeSponsoredAds = data;
        console.log("CarePath: Active rotating sponsored ads:", activeSponsoredAds.length);
        if (hospitalRecords && hospitalRecords.length > 0) {
          renderHospitalCards();
        }
      }
    } catch (err) {
      console.warn("CarePath: Sponsored ads fetch skipped:", err);
    }
  }

  function filteredHospitals() {
    let result = hospitalRecords.filter(function (hospital) {
      const departments = Array.isArray(hospital.departments)
        ? hospital.departments.join(" ")
        : hospital.departments || "";

      const haystack = [
        hospitalName(hospital),
        hospitalCity(hospital),
        hospital.description || "",
        departments
      ].join(" ").toLowerCase();

      if (activeQuery && !haystack.includes(activeQuery)) {
        return false;
      }

      if (activeFilter === "verified" && !isVerified(hospital)) {
        return false;
      }

      return true;
    });

    if (activeFilter === "lowfee") {
      result = result.slice().sort(function (a, b) {
        return tokenFee(a) - tokenFee(b);
      });
    }

    return result;
  }

  function makeElement(tag, className, text) {
    const element = document.createElement(tag);

    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;

    return element;
  }

  function renderHospitalCards() {
    const container = byId("hospitalCards");
    const empty = byId("emptyHospitals");
    const count = byId("hospitalCount");

    if (!container) return;

    const items = filteredHospitals();
    container.replaceChildren();

    if (count) {
      count.textContent =
        items.length + " hospital" + (items.length === 1 ? "" : "s");
    }

    if (empty) {
      empty.hidden = items.length > 0;
      empty.textContent = hospitalRecords.length === 0
        ? "No hospitals are currently available."
        : "No hospitals match your search. Try another name or city.";
    }

        // Instagram-style randomized ad injection:
    // Ads appear naturally with random spacing (every 3-5 items) and shuffled non-fixed rotation
    const adInsertIndices = new Set();
    if (activeSponsoredAds && activeSponsoredAds.length > 0 && items.length > 0) {
      if (items.length === 1) {
        adInsertIndices.add(0);
      } else {
        let nextAdPos = Math.floor(Math.random() * 3) + 2; // First ad randomly after 2nd, 3rd, or 4th item
        while (nextAdPos <= items.length) {
          adInsertIndices.add(nextAdPos - 1);
          const randomGap = Math.floor(Math.random() * 3) + 3; // Random gap of 3 to 5 organic hospitals
          nextAdPos += randomGap;
        }
      }
    }

    // Shuffled copy of active sponsored ads (Fisher-Yates) for fresh, non-repetitive order
    const shuffledAds = (activeSponsoredAds || []).slice();
    for (let si = shuffledAds.length - 1; si > 0; si--) {
      const sj = Math.floor(Math.random() * (si + 1));
      const st = shuffledAds[si];
      shuffledAds[si] = shuffledAds[sj];
      shuffledAds[sj] = st;
    }
    let adCounter = 0;

    items.forEach(function (hospital, index) {
      const card = makeElement("article", "hospital-card");
      const cover = makeElement("div", "hospital-cover");
      const photo = makeElement("img", "hospital-photo");

      photo.src = hospitalPhoto(hospital, index);
      photo.alt = hospitalName(hospital) + " hospital building";
      photo.loading = "lazy";

      photo.onerror = function () {
        photo.onerror = null;
        photo.src = FALLBACK_HOSPITAL_PHOTOS[
          (index + 1) % FALLBACK_HOSPITAL_PHOTOS.length
        ];
      };

      cover.appendChild(photo);
      cover.appendChild(makeElement("span", "hospital-photo-shade"));

      if (isVerified(hospital)) {
        cover.appendChild(
          makeElement("span", "hospital-badge", "✓ VERIFIED")
        );
      }

      cover.appendChild(
        makeElement("span", "hospital-fee", "Token fee ₹" + tokenFee(hospital))
      );

      card.appendChild(cover);

      const info = makeElement("div", "hospital-info");
      const details = makeElement("div", "hospital-details");

      details.appendChild(makeElement("h3", "", hospitalName(hospital)));

      details.appendChild(
        makeElement("p", "hospital-location", "⌖ " + hospitalCity(hospital))
      );

      details.appendChild(
        makeElement(
          "p",
          "hospital-description",
          String(hospital.description || "View departments and available doctors")
        )
      );

      info.appendChild(details);
      card.appendChild(info);

      const actionRow = makeElement("div", "card-action");
      const selectButton = makeElement(
        "button",
        "select-hospital-button",
        "View & Book →"
      );

      selectButton.type = "button";
      selectButton.addEventListener("click", function () {
        selectHospital(hospital);
      });
      actionRow.appendChild(selectButton);

      const rawPhone = hospital.phone || "";
      const cleanPhone = String(rawPhone).replace(/[^0-9]/g, "");
      if (cleanPhone) {
        const waNum = cleanPhone.length === 10 ? ("91" + cleanPhone) : cleanPhone;
        const waLink = makeElement("a", "card-wa-btn", "🟢");
        waLink.href = "https://wa.me/" + waNum + "?text=" + encodeURIComponent("Hello " + (hospitalName(hospital) || "Hospital") + ", I have an inquiry about appointments on CarePath.");
        waLink.target = "_blank";
        waLink.rel = "noopener noreferrer";
        waLink.title = "Chat with " + hospitalName(hospital) + " on WhatsApp";
        waLink.setAttribute("style", "padding: 10px 14px; background: #25D366; color: white; border-radius: 8px; text-decoration: none; font-size: 13px; font-weight: bold; display: inline-flex; align-items: center; justify-content: center;");
        actionRow.appendChild(waLink);

        const callLink = makeElement("a", "card-call-btn", "📞");
        callLink.href = "tel:" + cleanPhone;
        callLink.title = "Call " + hospitalName(hospital);
        callLink.setAttribute("style", "padding: 10px 14px; background: #0284c7; color: white; border-radius: 8px; text-decoration: none; font-size: 13px; font-weight: bold; display: inline-flex; align-items: center; justify-content: center;");
        actionRow.appendChild(callLink);
      }

      card.appendChild(actionRow);
      container.appendChild(card);

      // Inject Instagram-style randomized sponsored ad
      if (adInsertIndices.has(index) && shuffledAds.length > 0) {
        const adToRender = shuffledAds[adCounter % shuffledAds.length];
        adCounter++;
        const sponsoredCard = makeSponsoredAdCard(adToRender);
        if (sponsoredCard) {
          container.appendChild(sponsoredCard);
        }
      }
    });
  }


  function makeSponsoredAdCard(ad) {
    if (!ad) return null;
    const card = makeElement("article", "hospital-card sponsored-ad-card");

    const cover = makeElement("div", "hospital-cover sponsored-cover");
    const photo = makeElement("img", "hospital-photo sponsored-photo");

    const rawUrl = ad.image_url || ad.hospital_image || "";
    let finalSrc = rawUrl;
    if (rawUrl && !rawUrl.startsWith("http") && !rawUrl.startsWith("data:")) {
      finalSrc = API_BASE + (rawUrl.startsWith("/") ? "" : "/") + rawUrl;
    }
    if (!finalSrc) {
      finalSrc = FALLBACK_HOSPITAL_PHOTOS[0];
    }

    photo.src = finalSrc;
    photo.alt = (ad.title || ad.hospital_name || "CarePath") + " sponsored banner";
    photo.loading = "lazy";
    photo.onerror = function () {
      photo.onerror = null;
      photo.src = FALLBACK_HOSPITAL_PHOTOS[0];
    };

    cover.appendChild(photo);
    cover.appendChild(makeElement("span", "hospital-photo-shade"));

    // Sponsored badge
    cover.appendChild(makeElement("span", "sponsored-badge", "📢 SPONSORED"));

    // Hospital attribution chip
    if (ad.hospital_name) {
      cover.appendChild(makeElement("span", "hospital-fee", ad.hospital_name));
    }

    card.appendChild(cover);

    const info = makeElement("div", "hospital-info");
    const details = makeElement("div", "hospital-details");

    details.appendChild(makeElement("h3", "sponsored-title", ad.title || "Featured Healthcare Offer"));

    const locText = (ad.hospital_name || "") + (ad.hospital_city ? (" • " + ad.hospital_city) : "");
    if (locText.trim()) {
      details.appendChild(makeElement("p", "hospital-location", "📍 " + locText));
    }

    if (ad.description) {
      details.appendChild(makeElement("p", "hospital-description sponsored-desc", ad.description));
    }

    info.appendChild(details);
    card.appendChild(info);

    const actionRow = makeElement("div", "card-action sponsored-action-row");

    const bookBtn = makeElement("button", "select-hospital-button sponsored-btn", "Book Appointment →");
    bookBtn.type = "button";
    bookBtn.addEventListener("click", function () {
      const match = (hospitalRecords || []).find(function (h) {
        return String(hospitalId(h)) === String(ad.hospital_id);
      });
      selectHospital(match || { id: ad.hospital_id, name: ad.hospital_name, city: ad.hospital_city });
    });
    actionRow.appendChild(bookBtn);

    if (ad.target_phone) {
      const callBtn = makeElement("a", "sponsored-call-btn", "📞 Call");
      callBtn.href = "tel:" + ad.target_phone;
      actionRow.appendChild(callBtn);
    }

    if (ad.target_link) {
      const linkBtn = makeElement("a", "sponsored-link-btn", "🌐 Details ↗");
      linkBtn.href = ad.target_link;
      linkBtn.target = "_blank";
      linkBtn.rel = "noopener noreferrer";
      actionRow.appendChild(linkBtn);
    }

    card.appendChild(actionRow);
    return card;
  }

  function readRecentHospitals() {
    try {
      const saved = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      return Array.isArray(saved) ? saved : [];
    } catch (error) {
      console.warn("Could not read recent hospitals:", error);
      return [];
    }
  }

    function renderRecentHospitals() {
    const section = byId("recentSection");
    const container = byId("recentHospitals");

    if (!section || !container) {
      console.warn(
        'CarePath: Check that your HTML contains "recentSection" and "recentHospitals".'
      );
      return;
    }

    const rawRecent = readRecentHospitals();
    const activeList = hospitalRecords || [];
    let validRecent = [];

    // Filter to ONLY hospitals that currently exist and are published in the app
    if (activeList.length > 0) {
      validRecent = rawRecent.map(function (item) {
        if (!item || typeof item !== "object") return null;
        const id = hospitalId(item);
        if (!id) return null;
        // Match with latest hospital record in the app
        const found = activeList.find(function (h) {
          return String(hospitalId(h)) === String(id);
        });
        return found || null;
      }).filter(Boolean);

      // Keep localStorage in sync with currently active hospitals only (max 5)
      localStorage.setItem(RECENT_KEY, JSON.stringify(validRecent.slice(0, 5)));
    } else {
      validRecent = rawRecent.filter(function (item) {
        return item && typeof item === "object" && hospitalId(item) != null;
      });
    }

    const displayRecent = validRecent.slice(0, 5);
    container.replaceChildren();

    // Hide the entire section when there are no valid recent hospitals
    section.hidden = displayRecent.length === 0;

    displayRecent.forEach(function (hospital, index) {
      const card = makeElement("button", "recent-hospital-card");
      card.type = "button";
      card.setAttribute("aria-label", "View " + hospitalName(hospital));

      const image = makeElement("img", "recent-hospital-image");
      image.src = hospitalPhoto(hospital, index);
      image.alt = "";
      image.loading = "lazy";

      image.onerror = function () {
        image.onerror = null;
        image.src = FALLBACK_HOSPITAL_PHOTOS[
          index % FALLBACK_HOSPITAL_PHOTOS.length
        ];
      };

      const content = makeElement("div", "recent-hospital-content");
      content.appendChild(
        makeElement("strong", "recent-hospital-name", hospitalName(hospital))
      );
      content.appendChild(
        makeElement("span", "recent-hospital-city", "⌖ " + hospitalCity(hospital))
      );
      content.appendChild(
        makeElement("span", "recent-hospital-action", "View hospital →")
      );

      card.appendChild(image);
      card.appendChild(content);

      card.addEventListener("click", function () {
        selectHospital(hospital);
      });

      container.appendChild(card);
    });
  }

  function selectHospital(hospital) {
    if (!hospital || typeof hospital !== "object") {
      return;
    }

    const id = hospitalId(hospital);
    if (!id) {
      return;
    }

    const activeList = hospitalRecords || [];
    // Only accept hospitals that currently exist in the app
    const fresh = activeList.find(function (h) {
      return String(hospitalId(h)) === String(id);
    }) || hospital;

    localStorage.setItem("selectedHospitalId", String(id));
    localStorage.setItem("hospital_id", String(id));
    localStorage.setItem("hospitalId", String(id));
    localStorage.setItem("selectedHospital", JSON.stringify(fresh));

    // Save the selected hospital at the top without duplicates, filtering out nonexistent hospitals
    const existing = readRecentHospitals().filter(function (item) {
      const itemId = hospitalId(item);
      const isCurrent = String(itemId) === String(id);
      const existsInApp = activeList.length === 0 || activeList.some(function (h) {
        return String(hospitalId(h)) === String(itemId);
      });
      return !isCurrent && existsInApp;
    });

    existing.unshift(fresh);

    // Save at most 5 items in recent list
    localStorage.setItem(
      RECENT_KEY,
      JSON.stringify(existing.slice(0, 5))
    );

    window.location.href = "./hospital-details.html";
  }
})();