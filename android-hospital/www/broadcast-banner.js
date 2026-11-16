/**
 * CarePath System Emergency Broadcast Banner Client
 * Automatically fetches and renders active emergency alerts and announcements
 */
(function () {
    const API_URL = (typeof API !== "undefined" ? API : (typeof API_BASE !== "undefined" ? API_BASE : "https://carepath-3q9q.onrender.com")).replace(/\/+$/, "");

    // Determine target audience based on location
    const isHospital = window.location.pathname.includes("/hospital/") || document.title.toLowerCase().includes("hospital");
    const targetAudience = isHospital ? "hospital" : "patient";

    const ICONS = {
        critical: "🚨",
        warning: "⚠️",
        info: "ℹ️",
        success: "✅"
    };

    const STYLES = `
    .carepath-broadcast-container {
        width: 100%;
        max-width: 1200px;
        margin: 12px auto 20px auto;
        padding: 0 15px;
        box-sizing: border-box;
        z-index: 9999;
    }
    .carepath-broadcast-banner {
        padding: 14px 20px;
        border-radius: 12px;
        color: white;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
        animation: cpSlideDown 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        position: relative;
    }
    @keyframes cpSlideDown {
        from { transform: translateY(-12px); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
    }
    .carepath-broadcast-banner.critical {
        background: linear-gradient(135deg, #991b1b 0%, #dc2626 100%);
        border: 1px solid #b91c1c;
    }
    .carepath-broadcast-banner.warning {
        background: linear-gradient(135deg, #c2410c 0%, #ea580c 100%);
        border: 1px solid #f97316;
    }
    .carepath-broadcast-banner.info {
        background: linear-gradient(135deg, #0369a1 0%, #0284c7 100%);
        border: 1px solid #38bdf8;
    }
    .carepath-broadcast-banner.success {
        background: linear-gradient(135deg, #15803d 0%, #16a34a 100%);
        border: 1px solid #22c55e;
    }
    .cp-banner-content {
        display: flex;
        align-items: center;
        gap: 14px;
        flex: 1;
    }
    .cp-banner-icon {
        font-size: 24px;
        flex-shrink: 0;
    }
    .cp-banner-text-title {
        font-weight: 800;
        font-size: 15px;
        letter-spacing: -0.2px;
        margin-bottom: 3px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .cp-banner-text-msg {
        font-size: 13.5px;
        opacity: 0.95;
        line-height: 1.42;
    }
    .cp-banner-actions {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-shrink: 0;
    }
    .cp-action-btn {
        background: rgba(255, 255, 255, 0.22);
        color: white;
        padding: 7px 15px;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 700;
        text-decoration: none;
        border: 1px solid rgba(255, 255, 255, 0.45);
        white-space: nowrap;
        transition: background 0.2s;
    }
    .cp-action-btn:hover {
        background: rgba(255, 255, 255, 0.36);
    }
    .cp-close-btn {
        background: none;
        border: none;
        color: white;
        font-size: 20px;
        cursor: pointer;
        opacity: 0.8;
        padding: 4px;
        line-height: 1;
        transition: opacity 0.2s, transform 0.2s;
    }
    .cp-close-btn:hover {
        opacity: 1;
        transform: scale(1.15);
    }
    @media (max-width: 640px) {
        .carepath-broadcast-banner {
            flex-direction: column;
            align-items: flex-start;
        }
        .cp-banner-actions {
            width: 100%;
            justify-content: space-between;
            margin-top: 10px;
        }
    }
    `;

    function injectStyles() {
        if (document.getElementById("carepath-broadcast-styles")) return;
        const style = document.createElement("style");
        style.id = "carepath-broadcast-styles";
        style.textContent = STYLES;
        document.head.appendChild(style);
    }

    async function loadActiveBroadcasts() {
        try {
            const res = await fetch(`${API_URL}/broadcasts/active?audience=${targetAudience}`);
            if (!res.ok) return;
            const data = await res.json();
            const list = data.broadcasts || [];
            if (list.length === 0) return;

            injectStyles();

            // Find or create container
            let container = document.getElementById("emergencyBroadcastContainer");
            if (!container) {
                container = document.createElement("div");
                container.id = "emergencyBroadcastContainer";
                container.className = "carepath-broadcast-container";

                // Insert at the top of the main content or body
                const header = document.querySelector("header") || document.querySelector(".topbar");
                if (header && header.nextSibling) {
                    header.parentNode.insertBefore(container, header.nextSibling);
                } else {
                    document.body.insertBefore(container, document.body.firstChild);
                }
            }

            container.innerHTML = "";

            list.forEach(b => {
                // If user dismissed this broadcast in this session, skip unless critical
                if (b.is_dismissible && sessionStorage.getItem(`cp_dismissed_broadcast_${b.id}`)) {
                    return;
                }

                const icon = ICONS[b.banner_type] || "📢";
                const bannerEl = document.createElement("div");
                bannerEl.id = `cp-broadcast-${b.id}`;
                bannerEl.className = `carepath-broadcast-banner ${b.banner_type || "warning"}`;

                let actionHtml = "";
                if (b.action_link && b.action_label) {
                    actionHtml = `<a href="${encodeURI(b.action_link)}" class="cp-action-btn">${escapeHtml(b.action_label)}</a>`;
                }

                const closeHtml = b.is_dismissible
                    ? `<button type="button" class="cp-close-btn" onclick="dismissCarepathBroadcast(${b.id})" title="Dismiss Alert" aria-label="Dismiss">✕</button>`
                    : "";

                bannerEl.innerHTML = `
                    <div class="cp-banner-content">
                        <span class="cp-banner-icon">${icon}</span>
                        <div>
                            <div class="cp-banner-text-title">${escapeHtml(b.title)}</div>
                            <div class="cp-banner-text-msg">${escapeHtml(b.message)}</div>
                        </div>
                    </div>
                    <div class="cp-banner-actions">
                        ${actionHtml}
                        ${closeHtml}
                    </div>
                `;

                container.appendChild(bannerEl);
            });

        } catch (err) {
            console.warn("Could not check emergency broadcasts:", err);
        }
    }

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text ?? "";
        return div.innerHTML;
    }

    window.dismissCarepathBroadcast = function (id) {
        sessionStorage.setItem(`cp_dismissed_broadcast_${id}`, "1");
        const el = document.getElementById(`cp-broadcast-${id}`);
        if (el) {
            el.style.transition = "all 0.25s ease";
            el.style.opacity = "0";
            el.style.transform = "translateY(-10px)";
            setTimeout(() => el.remove(), 250);
        }
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", loadActiveBroadcasts);
    } else {
        loadActiveBroadcasts();
    }
})();
