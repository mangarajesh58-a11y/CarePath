/* HospitalCare patient dashboard presentation layer.
   Keeps booking and Razorpay logic in the existing script.js. */
(function () {
  "use strict";

  const API_BASE = "http://127.0.0.1:8000";
  const RECENT_KEY = "hospitalCareRecentlyViewed";
  let hospitalRecords = [];
  let activeFilter = "all";
  let activeQuery = "";
  const FALLBACK_HOSPITAL_PHOTOS = [
    "https://images.unsplash.com/photo-1586773860418-d37222d8fce3?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1519494026892-80bbd2d6fd0d?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1538108149393-fbbd81895907?auto=format&fit=crop&w=900&q=80",
    "https://images.unsplash.com/photo-1516549655169-df83a0774514?auto=format&fit=crop&w=900&q=80"
  ];

  const byId = (id) => document.getElementById(id);

  document.addEventListener("DOMContentLoaded", () => {
    const search = byId("hospitalSearch");
    const clear = byId("clearSearch");
    if (search) search.addEventListener("input", () => {
      activeQuery = search.value.trim().toLowerCase();
      renderHospitalCards();
    });
    if (clear) clear.addEventListener("click", () => {
      if (search) {
        search.value = "";
        activeQuery = "";
        search.focus();
      }
      renderHospitalCards();
    });

    document.querySelectorAll("[data-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        activeFilter = button.dataset.filter || "all";
        document.querySelectorAll("[data-filter]").forEach((item) => item.classList.toggle("active", item === button));
        renderHospitalCards();
      });
    });

    document.querySelectorAll("[data-query]").forEach((button) => {
      button.addEventListener("click", () => {
        const query = button.dataset.query || "";
        if (search) search.value = query;
        activeQuery = query.toLowerCase();
        renderHospitalCards();
        const section = byId("hospitalCards");
        if (section) section.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    loadHospitalsForCards();
  });

  async function loadHospitalsForCards() {
    const cards = byId("hospitalCards");
    try {
      const response = await fetch(`${API_BASE}/hospitals`);
      if (!response.ok) throw new Error(`Hospital request failed (${response.status})`);
      const payload = await response.json();
      hospitalRecords = Array.isArray(payload) ? payload : (payload.hospitals || []);
      renderHospitalCards();
      renderRecentHospitals();
    } catch (error) {
      console.error("Unable to load hospital cards:", error);
      if (cards) cards.innerHTML = "";
      const empty = byId("emptyHospitals");
      if (empty) {
        empty.hidden = false;
        empty.textContent = "Could not connect to the hospital list. Check that FastAPI is running at http://127.0.0.1:8000.";
      }
      const count = byId("hospitalCount");
      if (count) count.textContent = "Connection issue";
    }
  }

  function hospitalName(hospital) {
    return String(hospital.name || hospital.hospital_name || "Hospital");
  }

  function hospitalCity(hospital) {
    return String(hospital.city || hospital.address || hospital.location || "Location not provided");
  }

  function isVerified(hospital) {
    const status = String(hospital.verification_status || hospital.status || "").toLowerCase();
    return hospital.is_verified === true || hospital.verified === true || status === "verified" || status === "approved";
  }

  function tokenFee(hospital) {
    const fee = Number(hospital.token_fee ?? hospital.tokenFee ?? 0);
    return Number.isFinite(fee) && fee >= 0 ? fee : 0;
  }

  function hospitalPhoto(hospital, index = 0) {
    const images = Array.isArray(hospital.images) ? hospital.images : [];
    const candidate = hospital.cover_image_url || hospital.hospital_image_url ||
      hospital.image_url || hospital.photo_url || hospital.hospital_photo ||
      hospital.photo || hospital.image || images[0] || "";
    if (typeof candidate === "string" && candidate.trim()) {
      const value = candidate.trim();
      if (/^https?:\/\//i.test(value)) return value;
      if (value.startsWith("/")) return `${API_BASE}${value}`;
      return `${API_BASE}/${value}`;
    }
    return FALLBACK_HOSPITAL_PHOTOS[index % FALLBACK_HOSPITAL_PHOTOS.length];
  }

  function filteredHospitals() {
    let result = hospitalRecords.filter((hospital) => {
      const haystack = [hospitalName(hospital), hospitalCity(hospital), hospital.description || "", hospital.departments || ""]
        .join(" ").toLowerCase();
      if (activeQuery && !haystack.includes(activeQuery)) return false;
      if (activeFilter === "verified" && !isVerified(hospital)) return false;
      return true;
    });
    if (activeFilter === "lowfee") result = result.slice().sort((a, b) => tokenFee(a) - tokenFee(b));
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
    if (count) count.textContent = `${items.length} hospital${items.length === 1 ? "" : "s"}`;
    if (empty) empty.hidden = items.length > 0;

    items.forEach((hospital, index) => {
      const card = makeElement("article", "hospital-card");
      const cover = makeElement("div", "hospital-cover");
      const photo = makeElement("img", "hospital-photo");
      photo.src = hospitalPhoto(hospital, index);
      photo.alt = `${hospitalName(hospital)} hospital building`;
      photo.loading = "lazy";
      photo.onerror = () => {
        photo.onerror = null;
        photo.src = FALLBACK_HOSPITAL_PHOTOS[(index + 1) % FALLBACK_HOSPITAL_PHOTOS.length];
      };
      cover.appendChild(photo);
      cover.appendChild(makeElement("span", "hospital-photo-shade"));
      if (isVerified(hospital)) cover.appendChild(makeElement("span", "hospital-badge", "✓ VERIFIED"));
      const fee = makeElement("span", "hospital-fee", `Token fee ₹${tokenFee(hospital)}`);
      cover.appendChild(fee);
      card.appendChild(cover);

      const info = makeElement("div", "hospital-info");
      const details = makeElement("div", "hospital-details");
      details.appendChild(makeElement("h3", "", hospitalName(hospital)));
      details.appendChild(makeElement("p", "hospital-location", `⌖ ${hospitalCity(hospital)}`));
      details.appendChild(makeElement("p", "hospital-description", String(hospital.description || "View departments and available doctors")));
      info.appendChild(details);
      card.appendChild(info);

      const actionRow = makeElement("div", "card-action");
      const selectButton = makeElement("button", "select-hospital-button", "View & Book →");
      selectButton.type = "button";
      selectButton.addEventListener("click", () => selectHospital(hospital));
      actionRow.appendChild(selectButton);
      card.appendChild(actionRow);
      container.appendChild(card);
    });
  }

  function selectHospital(hospital) {
    const select = byId("hospital");
    if (!select) return;
    const id = hospital.id ?? hospital.hospital_id;
    if (id === undefined || id === null) {
      const message = byId("message");
      if (message) {
        message.textContent = "This hospital record has no ID. Please contact support.";
        message.className = "message error";
      }
      return;
    }
    const optionExists = Array.from(select.options).some((option) => String(option.value) === String(id));
    if (!optionExists) {
      const option = document.createElement("option");
      option.value = String(id);
      option.textContent = `${hospitalName(hospital)}${hospital.city ? ` - ${hospital.city}` : ""}`;
      select.appendChild(option);
    }
    select.value = String(id);
    select.dispatchEvent(new Event("change", { bubbles: true }));
    saveRecent(hospital);
    renderRecentHospitals();
    const booking = byId("bookingSection");
    if (booking) booking.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function readRecent() {
    try {
      const data = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      return Array.isArray(data) ? data : [];
    } catch (_) { return []; }
  }

  function saveRecent(hospital) {
    const id = String(hospital.id ?? hospital.hospital_id ?? "");
    if (!id) return;
    const next = [{ id, name: hospitalName(hospital), city: hospitalCity(hospital) }, ...readRecent().filter((item) => String(item.id) !== id)].slice(0, 6);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch (_) { /* storage may be unavailable */ }
  }

  function renderRecentHospitals() {
    const section = byId("recentSection");
    const container = byId("recentHospitals");
    if (!section || !container) return;
    const recent = readRecent().filter((item) => hospitalRecords.some((hospital) => String(hospital.id ?? hospital.hospital_id) === String(item.id)));
    container.replaceChildren();
    section.hidden = recent.length === 0;
    recent.forEach((item) => {
      const card = makeElement("button", "recent-card");
      card.type = "button";
      const hospital = hospitalRecords.find((record) => String(record.id ?? record.hospital_id) === String(item.id));
      const image = makeElement("img", "recent-photo");
      image.src = hospital ? hospitalPhoto(hospital, 0) : FALLBACK_HOSPITAL_PHOTOS[0];
      image.alt = `${item.name} hospital`;
      image.loading = "lazy";
      image.onerror = () => { image.onerror = null; image.src = FALLBACK_HOSPITAL_PHOTOS[1]; };
      card.appendChild(image);
      card.appendChild(makeElement("span", "recent-name", item.name));
      card.appendChild(makeElement("span", "recent-city", item.city));
      card.addEventListener("click", () => {
        const hospital = hospitalRecords.find((record) => String(record.id ?? record.hospital_id) === String(item.id));
        if (hospital) selectHospital(hospital);
      });
      container.appendChild(card);
    });
  }
})();
