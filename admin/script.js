// =====================================================
// CAREPATH ADMIN JAVASCRIPT
// =====================================================

const REMOTE_API = "https://carepath-3q9q.onrender.com";
const LOCAL_API = "http://127.0.0.1:8000";

function resolveApiBase() {
    const saved = localStorage.getItem("carepath_api");
    if (saved) return saved.replace(/\/+$/, "");
    return REMOTE_API;
}

let API = resolveApiBase();
const FRONTEND = "https://carepath-admin.vercel.app";

// Pre-warm backend immediately on load to reduce Render cold-start lag
try {
    fetch(`${API}/health`).catch(() => {});
} catch (_) {}

function switchApi(newUrl) {
    API = newUrl.replace(/\/+$/, "");
    localStorage.setItem("carepath_api", API);
    alert(`Backend API set to: ${API}\nReloading page...`);
    window.location.reload();
}
window.switchApi = switchApi;

// =====================================================
// ROBUST FETCH WITH RETRY & AUTO-SWITCH
// =====================================================

async function fetchWithRetry(url, options = {}, retries = 1, delayMs = 2500) {
    try {
        return await fetch(url, options);
    } catch (err) {
        if (retries <= 0) throw err;
        console.warn(`Fetch failed (${url}), retrying after ${delayMs}ms (server may be waking up):`, err);

        const isLocal = window.location.hostname === "localhost" ||
                        window.location.hostname === "127.0.0.1" ||
                        window.location.protocol === "file:";

        if (isLocal && API !== LOCAL_API) {
            try {
                const localTest = await fetch(`${LOCAL_API}/health`, { signal: AbortSignal.timeout(1500) });
                if (localTest.ok) {
                    API = LOCAL_API;
                    localStorage.setItem("carepath_api", LOCAL_API);
                    console.log("Auto-switched to active local FastAPI backend:", LOCAL_API);
                    if (typeof url === "string" && url.startsWith(REMOTE_API)) {
                        url = url.replace(REMOTE_API, LOCAL_API);
                    }
                }
            } catch (_) {}
        }

        await new Promise(r => setTimeout(r, delayMs));
        return await fetch(url, options);
    }
}

// =====================================================
// SAFE RESPONSE READER
// =====================================================

async function readResponse(response) {
    const text = await response.text();

    if (!text) {
        return {};
    }

    try {
        return JSON.parse(text);
    } catch (error) {
        return {
            detail: text
        };
    }
}

// =====================================================
// ADMIN AUTHENTICATION HEADERS
// =====================================================

function getAdminAuthHeaders(extraHeaders = {}) {
    const token = localStorage.getItem("adminToken");

    return {
        ...extraHeaders,
        ...(token
            ? {
                  Authorization: `Bearer ${token}`
              }
            : {})
    };
}

// =====================================================
// REQUIRE ADMIN LOGIN
// =====================================================

function requireAdminLogin() {
    const token = localStorage.getItem("adminToken");
    const role = localStorage.getItem("adminRole");

    if (!token || role !== "admin") {
        alert(
            "Your admin session is missing or expired. Please login again."
        );

        localStorage.removeItem("adminLoggedIn");
        localStorage.removeItem("adminEmail");
        localStorage.removeItem("adminRole");
        localStorage.removeItem("adminToken");

        window.location.replace("index.html");
        return false;
    }

    return true;
}

// =====================================================
// PAGE LOAD
// =====================================================

document.addEventListener("DOMContentLoaded", function () {
    console.log("CarePath Admin started.");

    const path = window.location.pathname.toLowerCase();

    console.log("Current page:", path);

    const isLoginPage =
        path.endsWith("/admin/") ||
        path.endsWith("/admin/index.html") ||
        path.endsWith("index.html");

    if (!isLoginPage) {
        if (!requireAdminLogin()) {
            return;
        }
    }

    if (path.includes("dashboard.html")) {
        loadDashboard();
    }

    if (path.includes("hospitals.html")) {
        loadHospitals();
    const commParam = new URLSearchParams(window.location.search);
    if (commParam.get("open_comm") === "true") {
        setTimeout(() => {
            if (typeof openGeneralDirectCommunicationModal === "function") {
                openGeneralDirectCommunicationModal();
            }
        }, 800);
    }

    }

    if (path.includes("payments.html")) {
        loadPayments();
    }

    if (path.includes("tokens.html")) {
        loadTokens();
    }

    if (isLoginPage) {
        console.log("Admin login page loaded.");
    }
});

// =====================================================
// ADMIN LOGIN
// =====================================================

async function adminLogin() {
    const emailInput = document.getElementById("adminEmail");
    const passwordInput = document.getElementById("adminPassword");

    const email =
        emailInput?.value.trim().toLowerCase() || "";

    const password =
        passwordInput?.value || "";

    if (!email || !password) {
        showLoginMessage(
            "Please enter your email and password.",
            "error"
        );
        return;
    }

    try {
        showLoginMessage(
            "Logging in...",
            "success"
        );

        const response = await fetch(
            `${API}/admin/login`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    email: email,
                    password: password
                })
            }
        );

        const data = await readResponse(response);

        console.log(
            "Admin login status:",
            response.status
        );

        console.log(
            "Admin login response:",
            data
        );

        if (!response.ok) {
            showLoginMessage(
                getErrorMessage(
                    data,
                    `Login failed (HTTP ${response.status}).`
                ),
                "error"
            );
            return;
        }

        if (!data.access_token) {
            throw new Error(
                "Login succeeded, but authentication token was not returned."
            );
        }

        localStorage.setItem(
            "adminLoggedIn",
            "true"
        );

        localStorage.setItem(
            "adminEmail",
            email
        );

        localStorage.setItem(
            "adminRole",
            "admin"
        );

        localStorage.setItem(
            "adminToken",
            data.access_token
        );

        showLoginMessage(
            "Login successful",
            "success"
        );

        setTimeout(() => {
            window.location.href =
                `${FRONTEND}/dashboard.html`;
        }, 500);

    } catch (error) {
        console.error(
            "Admin login connection error:",
            error
        );

        showLoginMessage(
            error.message ||
            "Cannot connect to CarePath FastAPI.",
            "error"
        );
    }
}

// =====================================================
// GOOGLE ADMIN LOGIN
// =====================================================

async function handleGoogleLogin(response) {
    if (
        !response ||
        !response.credential
    ) {
        showLoginMessage(
            "Google login failed. Please try again.",
            "error"
        );
        return;
    }

    try {
        showLoginMessage(
            "Verifying Google account...",
            "success"
        );

        const result = await fetch(
            `${API}/auth/google`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    credential: response.credential,
                    role: "admin"
                })
            }
        );

        const data =
            await readResponse(result);

        console.log(
            "Google login status:",
            result.status
        );

        console.log(
            "Google login response:",
            data
        );

        if (!result.ok) {
            showLoginMessage(
                getErrorMessage(
                    data,
                    `Google login failed (HTTP ${result.status}).`
                ),
                "error"
            );
            return;
        }

        if (!data.access_token) {
            throw new Error(
                "Google login succeeded, but authentication token was not returned."
            );
        }

        localStorage.setItem(
            "adminLoggedIn",
            "true"
        );

        localStorage.setItem(
            "adminEmail",
            data.user?.email ||
            data.email ||
            "Google Admin"
        );

        localStorage.setItem(
            "adminRole",
            "admin"
        );

        localStorage.setItem(
            "adminToken",
            data.access_token
        );

        showLoginMessage(
            "Google login successful. Opening dashboard...",
            "success"
        );

        setTimeout(() => {
            window.location.href =
                `${FRONTEND}/dashboard.html`;
        }, 500);

    } catch (error) {
        console.error(
            "Google login connection error:",
            error
        );

        showLoginMessage(
            error.message ||
            "Cannot connect to CarePath FastAPI.",
            "error"
        );
    }
}

// =====================================================
// LOGIN MESSAGE
// =====================================================

function showLoginMessage(
    message,
    type = "success"
) {
    const element =
        document.getElementById(
            "loginMessage"
        );

    if (!element) {
        alert(message);
        return;
    }

    element.textContent = message;

    element.className =
        `message ${type}`;
}

// =====================================================
// ADMIN LOGOUT
// =====================================================

function adminLogout() {
    localStorage.removeItem(
        "adminLoggedIn"
    );

    localStorage.removeItem(
        "adminEmail"
    );

    localStorage.removeItem(
        "adminRole"
    );

    localStorage.removeItem(
        "adminToken"
    );

    window.location.replace(
        "index.html"
    );
}

// =====================================================
// OPEN HOSPITALS
// =====================================================

function openHospitals() {
    window.location.href =
        "hospitals.html";
}

// =====================================================
// OPEN PAYMENTS
// =====================================================

function openPayments() {
    window.location.href =
        "payments.html";
}

// =====================================================
// OPEN TOKENS
// =====================================================

function openTokens() {
    window.location.href =
        "tokens.html";
}

// =====================================================
// BACK TO DASHBOARD
// =====================================================

function goDashboard() {
    window.location.href =
        "dashboard.html";
}

// =====================================================
// LOAD ADMIN DASHBOARD
// =====================================================

async function loadDashboard() {
    console.log(
        "Loading admin dashboard..."
    );

    try {
        await loadDashboardHospitals();
        await loadRevenue();

    } catch (error) {
        console.error(
            "Dashboard loading error:",
            error
        );

        showMessage(
            error.message ||
            "Unable to load dashboard.",
            "error"
        );
    }
}

// =====================================================
// LOAD HOSPITAL COUNT
// =====================================================

async function loadDashboardHospitals() {
    const hospitalCount =
        document.getElementById(
            "hospitalCount"
        );

    try {
        const response = await fetchWithRetry(
            `${API}/admin/hospitals`,
            {
                headers:
                    getAdminAuthHeaders()
            }
        );

        const data =
            await readResponse(response);

        if (!response.ok) {
            throw new Error(
                getErrorMessage(
                    data,
                    `HTTP ${response.status}`
                )
            );
        }

        const hospitals =
            Array.isArray(data)
                ? data
                : data.hospitals || [];

        allLoadedHospitals = hospitals;

        if (hospitalCount) {
            hospitalCount.textContent =
                hospitals.length;
        }

    } catch (error) {
        console.error(
            "Hospital count error:",
            error
        );

        if (hospitalCount) {
            hospitalCount.textContent =
                "0";
        }

        throw error;
    }
}

// =====================================================
// LOAD REVENUE
// =====================================================

async function loadRevenue() {
    try {
        const response = await fetch(
            `${API}/admin/revenue`,
            {
                headers:
                    getAdminAuthHeaders()
            }
        );

        const data =
            await readResponse(response);

        if (!response.ok) {
            throw new Error(
                getErrorMessage(
                    data,
                    `HTTP ${response.status}`
                )
            );
        }

        console.log(
            "Revenue response:",
            data
        );

        const tokenRevenueValue =
            Number(
                data.token_revenue || 0
            );

        const platformRevenueValue =
            Number(
                data.platform_revenue ??
                data.total_revenue ??
                0
            );

        const totalCollectedValue =
            Number(
                data.total_collected ??
                (
                    tokenRevenueValue +
                    platformRevenueValue
                )
            );

        const totalTokens =
            Number(
                data.total_tokens || 0
            );

        const platformRevenue =
            document.getElementById(
                "platformRevenue"
            );

        if (platformRevenue) {
            platformRevenue.textContent =
                `₹${platformRevenueValue}`;
        }

        const platformRevenue2 =
            document.getElementById(
                "platformRevenue2"
            );

        if (platformRevenue2) {
            platformRevenue2.textContent =
                `₹${platformRevenueValue}`;
        }

        const tokenRevenue =
            document.getElementById(
                "tokenRevenue"
            );

        if (tokenRevenue) {
            tokenRevenue.textContent =
                `₹${tokenRevenueValue}`;
        }

        const totalCollected =
            document.getElementById(
                "totalCollected"
            );

        if (totalCollected) {
            totalCollected.textContent =
                `₹${totalCollectedValue}`;
        }

        const tokenCount =
            document.getElementById(
                "tokenCount"
            );

        if (tokenCount) {
            tokenCount.textContent =
                totalTokens;
        }

        const paymentCount =
            document.getElementById(
                "paymentCount"
            );

        if (paymentCount) {
            paymentCount.textContent =
                totalTokens;
        }

    } catch (error) {
        console.error(
            "Revenue loading error:",
            error
        );

        throw error;
    }
}

// =====================================================
// LOAD HOSPITALS
// =====================================================

async function loadHospitals() {
    const tableBody =
        document.getElementById(
            "hospitalTableBody"
        );

    if (!tableBody) {
        return;
    }

    tableBody.innerHTML = `
        <tr>
            <td
                colspan="9"
                class="loading"
            >
                Loading hospitals (connecting to backend)...
            </td>
        </tr>
    `;

    try {
        const response = await fetchWithRetry(
            `${API}/admin/hospitals`,
            {
                headers:
                    getAdminAuthHeaders()
            }
        );

        const data =
            await readResponse(response);

        if (!response.ok) {
            throw new Error(
                getErrorMessage(
                    data,
                    `HTTP ${response.status}`
                )
            );
        }

        const hospitals =
            Array.isArray(data)
                ? data
                : data.hospitals || [];

        if (hospitals.length === 0) {
            tableBody.innerHTML = `
                <tr>
                    <td
                        colspan="9"
                        class="loading"
                    >
                        No hospitals registered yet.
                    </td>
                </tr>
            `;

            return;
        }

        tableBody.innerHTML = "";

        hospitals.forEach(
            function (hospital) {
                const row =
                    document.createElement(
                        "tr"
                    );

                const status =
                    String(
                        hospital.approval_status ||
                        "PENDING"
                    ).toUpperCase();

                const published =
                    hospital.is_published === true;

                let statusClass =
                    "pending";

                if (status === "APPROVED") {
                    statusClass =
                        "approved";
                }

                if (status === "REJECTED") {
                    statusClass =
                        "rejected";
                }

                const hospitalId =
                    Number(hospital.id);

                const approveButton =
                    status !== "APPROVED"
                        ? `
                            <button
                                class="approve-btn"
                                onclick="approveHospital(${hospitalId})"
                            >
                                ✅ Approve
                            </button>
                        `
                        : "";

                const rejectButton =
                    status !== "REJECTED"
                        ? `
                            <button
                                class="reject-btn"
                                onclick="rejectHospital(${hospitalId})"
                            >
                                ❌ Reject
                            </button>
                        `
                        : "";

                const publishButton =
                    status === "APPROVED" &&
                    !published
                        ? `
                            <button
                                class="publish-btn"
                                onclick="publishHospital(${hospitalId})"
                            >
                                📢 Publish
                            </button>
                        `
                        : "";

                const unpublishButton =
                    published
                        ? `
                            <button
                                class="unpublish-btn"
                                onclick="unpublishHospital(${hospitalId})"
                            >
                                🚫 Unpublish
                            </button>
                        `
                        : "";

                const rawImg = hospital.image_url || hospital.photo_url || "";
                const thumbUrl = rawImg
                    ? (/^https?:\/\//i.test(rawImg) || rawImg.startsWith("data:")
                        ? rawImg
                        : `${API}${rawImg.startsWith("/") ? "" : "/"}${rawImg}`)
                    : `${API}/hospital-photos/hospital_${hospitalId}.jpg`;

                row.innerHTML = `
                    <td>
                        ${escapeHtml(
                            hospital.id ?? "-"
                        )}
                    </td>

                    <td>
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <img
                                src="${thumbUrl}"
                                alt="${escapeHtml(hospital.name || 'Hospital')}"
                                style="width: 44px; height: 44px; border-radius: 8px; object-fit: cover; border: 1px solid #e2e8f0; background: #f8fafc; flex-shrink: 0;"
                                onerror="this.onerror=null; this.src='https://images.unsplash.com/photo-1586773860418-d37222d8fce3?auto=format&fit=crop&w=120&q=80';"
                            >
                            <div>
                                <strong>
                                    ${escapeHtml(
                                        hospital.name || "-"
                                    )}
                                </strong>
                            </div>
                        </div>
                    </td>

                    <td>
                        ${escapeHtml(
                            hospital.city || "-"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            hospital.license_id ||
                            "Not provided"
                        )}
                    </td>

                    <td>
                        ₹${Number(
                            hospital.token_fee || 0
                        )}
                    </td>

                    <td>
                        <span
                            class="status ${statusClass}"
                        >
                            ${escapeHtml(status)}
                        </span>
                    </td>

                    <td>
                        <span
                            class="${
                                published
                                    ? "published"
                                    : "not-published"
                            }"
                        >
                            ${
                                published
                                    ? "YES"
                                    : "NO"
                            }
                        </span>
                    </td>

                    <td>
                        ${Number(
                            hospital.doctor_count || 0
                        )}
                    </td>

                    <td>
                        <div class="action-buttons">

                            <button
                                class="view-btn"
                                onclick="viewHospital(${hospitalId})"
                            >
                                👁 View
                            </button>

                            <button
                                class="view-btn"
                                style="background: #2563eb; color: #ffffff; font-weight: 700; border: none;"
                                onclick="openDirectCommModal(${hospitalId}, '${escapeHtml(hospital.name || 'Hospital')}', '${escapeHtml(hospital.phone || '')}', '${escapeHtml(hospital.city || '')}')"
                                title="Send direct notice, WhatsApp or call"
                            >
                                💬 Message
                            </button>

                            ${approveButton}

                            ${rejectButton}

                            ${publishButton}

                            ${unpublishButton}

                            <button
                                class="delete-btn"
                                onclick="deleteHospital(${hospitalId})"
                            >
                                🗑 Delete
                            </button>

                        </div>
                    </td>
                `;

                tableBody.appendChild(row);
            }
        );

    } catch (error) {
        console.error(
            "Hospital loading error:",
            error
        );

        const otherApi = API === REMOTE_API ? LOCAL_API : REMOTE_API;
        const otherLabel = API === REMOTE_API ? "Localhost (127.0.0.1:8000)" : "Render Cloud Server";

        tableBody.innerHTML = `
            <tr>
                <td
                    colspan="9"
                    class="loading"
                    style="padding: 24px 16px; text-align: center;"
                >
                    <div style="max-width: 520px; margin: 0 auto; text-align: center;">
                        <div style="font-size: 22px; font-weight: bold; margin-bottom: 8px;">❌ Cannot Connect to Server</div>
                        <div style="color: #64748b; font-size: 14px; margin-bottom: 14px;">
                            ${escapeHtml(error.message || "Failed to fetch from backend.")}
                        </div>
                        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-bottom: 16px; font-size: 13px; text-align: left; line-height: 1.5;">
                            <strong>Active API:</strong> <code>${escapeHtml(API)}</code><br>
                            ${API.includes("onrender.com") ? "💡 <em>Note: Render free tier services sleep after 15 minutes of inactivity and take ~30–45s to wake up on the first request.</em>" : "💡 <em>Make sure your local FastAPI backend is running via <code>uvicorn main:app --reload</code>.</em>"}
                        </div>
                        <div style="display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
                            <button type="button" onclick="loadHospitals()" style="background: #1976d2; color: white; border: none; padding: 8px 18px; border-radius: 6px; cursor: pointer; font-weight: 600;">
                                🔄 Retry
                            </button>
                            <button type="button" onclick="switchApi('${otherApi}')" style="background: #475569; color: white; border: none; padding: 8px 18px; border-radius: 6px; cursor: pointer; font-weight: 600;">
                                ⚡ Switch to ${otherLabel}
                            </button>
                        </div>
                    </div>
                </td>
            </tr>
        `;
    }
}

// =====================================================
// CURRENT HOSPITAL DETAILS
// =====================================================

let currentHospitalDetailsId = null;
let allLoadedHospitals = [];
let currentDirectCommHospitalId = null;


// =====================================================
// VIEW HOSPITAL
// =====================================================

async function viewHospital(id) {
    const hospitalId =
        Number(id);

    if (
        !Number.isInteger(hospitalId) ||
        hospitalId <= 0
    ) {
        showMessage(
            "Invalid hospital ID.",
            "error"
        );
        return;
    }

    const modal =
        document.getElementById(
            "hospitalDetailsModal"
        );

    const nameElement =
        document.getElementById(
            "modalHospitalName"
        );

    const detailsElement =
        document.getElementById(
            "hospitalDetailsContent"
        );

    const certificateName =
        document.getElementById(
            "certificateFileName"
        );

    const certificateViewer =
        document.getElementById(
            "certificateViewer"
        );

    const hospitalPhotoPreview =
        document.getElementById(
            "hospitalPhotoPreview"
        );

    const hospitalPhotoMessage =
        document.getElementById(
            "hospitalPhotoMessage"
        );

    const messageElement =
        document.getElementById(
            "certificateModalMessage"
        );

    const verifyButton =
        document.getElementById(
            "verifyCertificateButton"
        );

    const rejectButton =
        document.getElementById(
            "rejectCertificateButton"
        );

    if (
        !modal ||
        !nameElement ||
        !detailsElement ||
        !certificateName ||
        !certificateViewer
    ) {
        showMessage(
            "Hospital details modal is missing from hospitals.html.",
            "error"
        );
        return;
    }

    currentHospitalDetailsId =
        hospitalId;

    modal.style.display =
        "block";

    nameElement.textContent =
        "Loading hospital...";

    detailsElement.textContent =
        "Loading hospital details...";

    certificateName.textContent =
        "Checking certificate...";

    certificateViewer.src =
        "about:blank";

    if (hospitalPhotoPreview) {
        hospitalPhotoPreview.style.display =
            "none";

        hospitalPhotoPreview.removeAttribute(
            "src"
        );
    }

    if (hospitalPhotoMessage) {
        hospitalPhotoMessage.textContent =
            "Loading hospital photo...";
    }

    if (messageElement) {
        messageElement.textContent =
            "";
    }

    if (verifyButton) {
        verifyButton.disabled =
            true;
    }

    if (rejectButton) {
        rejectButton.disabled =
            true;
    }

    try {
        // =====================================================
        // LOAD HOSPITAL DETAILS
        // =====================================================

        const response =
            await fetch(
                `${API}/admin/hospitals/${hospitalId}`,
                {
                    headers:
                        getAdminAuthHeaders()
                }
            );

        const hospital =
            await readResponse(
                response
            );

        if (!response.ok) {
            throw new Error(
                getErrorMessage(
                    hospital,
                    "Could not load hospital details."
                )
            );
        }

        nameElement.textContent =
            hospital.name ||
            hospital.hospital_name ||
            "Hospital Details";

        // =====================================================
        // HOSPITAL PHOTO
        // =====================================================

        let imagePath =
            hospital.image_url ||
            hospital.photo_url ||
            hospital.hospital_photo_url ||
            "";

        // Direct database base64 fallback if image_url is missing
        if (!imagePath && hospital.photo_base64 && typeof hospital.photo_base64 === "string") {
            imagePath = hospital.photo_base64.startsWith("data:")
                ? hospital.photo_base64
                : `data:image/jpeg;base64,${hospital.photo_base64}`;
        }

        // Guaranteed fallback so cover photo is NEVER missing
        if (!imagePath) {
            imagePath = `${API}/hospital-photos/hospital_${hospital.id || id}.jpg`;
        }

        if (
            hospitalPhotoPreview &&
            hospitalPhotoMessage
        ) {
            const photoUrl =
                /^https?:\/\//i.test(imagePath) || imagePath.startsWith("data:")
                    ? imagePath
                    : `${API}${
                          imagePath.startsWith("/")
                              ? ""
                              : "/"
                      }${imagePath}`;

            hospitalPhotoPreview.onload =
                () => {
                    hospitalPhotoPreview.style.display =
                        "block";

                    hospitalPhotoMessage.textContent =
                        "Hospital cover photo loaded.";
                };

            hospitalPhotoPreview.onerror =
                () => {
                    // 1. If file URL failed, try database base64 if available
                    if (hospital.photo_base64 && typeof hospital.photo_base64 === "string" && !hospitalPhotoPreview.src.startsWith("data:")) {
                        const b64Src = hospital.photo_base64.startsWith("data:")
                            ? hospital.photo_base64
                            : `data:image/jpeg;base64,${hospital.photo_base64}`;
                        hospitalPhotoPreview.onerror = () => {
                            hospitalPhotoPreview.onerror = null;
                            hospitalPhotoPreview.src = "https://images.unsplash.com/photo-1586773860418-d37222d8fce3?auto=format&fit=crop&w=900&q=80";
                            hospitalPhotoMessage.textContent = "Default medical cover photo loaded.";
                        };
                        hospitalPhotoPreview.src = b64Src;
                        return;
                    }

                    // 2. High quality curated fallback photo so cover is never missing
                    hospitalPhotoPreview.onerror = null;
                    hospitalPhotoPreview.src = "https://images.unsplash.com/photo-1586773860418-d37222d8fce3?auto=format&fit=crop&w=900&q=80";
                    hospitalPhotoMessage.textContent = "Default medical cover photo loaded.";
                };

            hospitalPhotoPreview.src =
                photoUrl;
        }

        // =====================================================
        // HOSPITAL DETAILS
        // =====================================================

        const fields = [
            [
                "Hospital Name",
                hospital.name ||
                hospital.hospital_name
            ],

            [
                "City",
                hospital.city
            ],

            [
                "Address",
                hospital.address
            ],

            [
                "License ID",
                hospital.license_id ||
                hospital.registration_number
            ],

            [
                "Token Fee",
                hospital.token_fee == null
                    ? ""
                    : `₹${hospital.token_fee}`
            ],

            [
                "Approval Status",
                hospital.approval_status
            ],

            [
                "Published",
                hospital.is_published
                    ? "Yes"
                    : "No"
            ],

            [
                "Certificate Status",
                hospital.certificate_verification_status ||
                "PENDING"
            ],

            [
                "Issuing Authority",
                hospital.issuing_authority
            ],

            [
                "License Expiry Date",
                hospital.license_expiry_date
            ]
        ];

        detailsElement.replaceChildren();

        fields.forEach(
            ([label, value]) => {
                const paragraph =
                    document.createElement(
                        "p"
                    );

                const strong =
                    document.createElement(
                        "strong"
                    );

                strong.textContent =
                    `${label}: `;

                paragraph.appendChild(
                    strong
                );

                paragraph.appendChild(
                    document.createTextNode(
                        value === undefined ||
                        value === null ||
                        value === ""
                            ? "Not provided"
                            : String(value)
                    )
                );

                detailsElement.appendChild(
                    paragraph
                );
            }
        );

        // =====================================================
        // CERTIFICATE
        // IMPORTANT:
        // Do NOT depend on certificate metadata from
        // /admin/hospitals/{id}.
        //
        // The protected certificate endpoint is the
        // source of truth for whether the file exists.
        // =====================================================

        const certificateStatus =
            String(
                hospital.certificate_verification_status ||
                "PENDING"
            ).toUpperCase();

        let hasCertificate = false;

        try {
            await loadProtectedCertificate(
                hospitalId,
                certificateViewer
            );

            // The protected endpoint returned the
            // certificate successfully.
            hasCertificate = true;

            certificateName.textContent =
                hospital.certificate_original_name
                    ? `File: ${hospital.certificate_original_name}`
                    : "Hospital registration certificate uploaded.";

        } catch (certificateError) {
            console.error(
                "Certificate loading error:",
                certificateError
            );

            certificateName.textContent =
                "No certificate uploaded for this hospital.";

            certificateViewer.src =
                "about:blank";

            if (messageElement) {
                messageElement.textContent =
                    certificateError.message ||
                    "Unable to load hospital certificate.";
            }
        }

        // =====================================================
        // CERTIFICATE ACTION BUTTONS
        // =====================================================

        if (verifyButton) {
            verifyButton.disabled = certificateStatus === "VERIFIED";
        }

        if (rejectButton) {
            rejectButton.disabled =
                !hasCertificate ||
                certificateStatus === "REJECTED";
        }
        { setupHospitalDirectCommunication(hospital, hospitalId);
        }

    } catch (error) {
        console.error(
            "View hospital error:",
            error
        );

        detailsElement.textContent =
            error.message ||
            "Unable to load hospital details.";

        certificateName.textContent =
            "Certificate could not be loaded.";

        certificateViewer.src =
            "about:blank";

        if (hospitalPhotoPreview) {
            hospitalPhotoPreview.style.display =
                "none";
        }

        if (hospitalPhotoMessage) {
            hospitalPhotoMessage.textContent =
                "Unable to load hospital photo.";
        }

        if (messageElement) {
            messageElement.textContent =
                error.message ||
                "Unable to load hospital details.";
        }
    }
}

// =====================================================
// LOAD PROTECTED CERTIFICATE
// =====================================================

async function loadProtectedCertificate(
    hospitalId,
    viewer
) {
    if (!viewer) {
        throw new Error(
            "Certificate viewer is missing."
        );
    }

    const token =
        localStorage.getItem(
            "adminToken"
        );

    if (!token) {
        throw new Error(
            "Admin authentication token is missing."
        );
    }

    const response =
        await fetch(
            `${API}/admin/hospitals/${hospitalId}/certificate`,
            {
                method: "GET",
                headers: {
                    Authorization:
                        `Bearer ${token}`
                }
            }
        );

    if (!response.ok) {
        const data =
            await readResponse(
                response
            );

        throw new Error(
            getErrorMessage(
                data,
                `Unable to load certificate (HTTP ${response.status}).`
            )
        );
    }

    const blob =
        await response.blob();

    if (!blob || blob.size === 0) {
        throw new Error(
            "Certificate file is empty."
        );
    }

    const blobUrl =
        URL.createObjectURL(blob);

    // Release previous certificate URL.
    if (viewer.dataset.blobUrl) {
        URL.revokeObjectURL(
            viewer.dataset.blobUrl
        );
    }

    viewer.dataset.blobUrl =
        blobUrl;

    viewer.src =
        blobUrl;
}

// =====================================================
// CLOSE HOSPITAL DETAILS
// =====================================================

function closeHospitalDetails() { resetHospitalDirectCommunication();
    const modal =
        document.getElementById(
            "hospitalDetailsModal"
        );

    const viewer =
        document.getElementById(
            "certificateViewer"
        );

    if (modal) {
        modal.style.display =
            "none";
    }

    if (viewer) {
        if (viewer.dataset.blobUrl) {
            URL.revokeObjectURL(
                viewer.dataset.blobUrl
            );

            delete viewer.dataset.blobUrl;
        }

        viewer.src =
            "about:blank";
    }

    currentHospitalDetailsId =
        null;
}

// =====================================================
// VERIFY HOSPITAL CERTIFICATE
// =====================================================

async function verifyHospitalCertificate(id) {
    const hospitalId =
        Number(id);

    if (
        !Number.isInteger(hospitalId) ||
        hospitalId <= 0
    ) {
        showMessage(
            "Invalid hospital ID.",
            "error"
        );
        return false;
    }

    if (
        !confirm(
            "Are you sure you want to verify this hospital certificate?"
        )
    ) {
        return false;
    }

    try {
        const response =
            await fetch(
                `${API}/admin/hospitals/${hospitalId}/certificate/verify`,
                {
                    method: "PUT",
                    headers:
                        getAdminAuthHeaders({
                            "Content-Type":
                                "application/json"
                        })
                }
            );

        const data =
            await readResponse(
                response
            );

        if (!response.ok) {
            throw new Error(
                getErrorMessage(
                    data,
                    "Certificate verification failed."
                )
            );
        }

        showMessage(
            data.message ||
            "Hospital certificate verified successfully.",
            "success"
        );

        await loadHospitals();

        return true;

    } catch (error) {
        console.error(
            "Certificate verification error:",
            error
        );

        showMessage(
            error.message ||
            "Unable to verify certificate.",
            "error"
        );

        return false;
    }
}

// =====================================================
// REJECT HOSPITAL CERTIFICATE
// =====================================================

async function rejectHospitalCertificate(id) {
    const hospitalId =
        Number(id);

    if (
        !Number.isInteger(hospitalId) ||
        hospitalId <= 0
    ) {
        showMessage(
            "Invalid hospital ID.",
            "error"
        );
        return false;
    }

    const reason =
        prompt(
            "Enter the reason for rejecting this certificate:"
        );

    if (reason === null) {
        return false;
    }

    if (!reason.trim()) {
        showMessage(
            "Please enter a rejection reason.",
            "error"
        );
        return false;
    }

    if (
        !confirm(
            "Are you sure you want to reject this certificate?"
        )
    ) {
        return false;
    }

    try {
        const response =
            await fetch(
                `${API}/admin/hospitals/${hospitalId}/certificate/reject`,
                {
                    method: "PUT",
                    headers:
                        getAdminAuthHeaders({
                            "Content-Type":
                                "application/json"
                        }),
                    body:
                        JSON.stringify({
                            reason:
                                reason.trim()
                        })
                }
            );

        const data =
            await readResponse(
                response
            );

        if (!response.ok) {
            throw new Error(
                getErrorMessage(
                    data,
                    "Certificate rejection failed."
                )
            );
        }

        showMessage(
            data.message ||
            "Hospital certificate rejected successfully.",
            "success"
        );

        await loadHospitals();

        return true;

    } catch (error) {
        console.error(
            "Certificate rejection error:",
            error
        );

        showMessage(
            error.message ||
            "Unable to reject certificate.",
            "error"
        );

        return false;
    }
}

// =====================================================
// VERIFY FROM MODAL
// =====================================================

async function verifyHospitalCertificateFromModal() {
    const id =
        currentHospitalDetailsId;

    if (!id) {
        showMessage(
            "Please open a hospital first.",
            "error"
        );
        return;
    }

    const success =
        await verifyHospitalCertificate(
            id
        );

    if (
        success &&
        currentHospitalDetailsId === id
    ) {
        await viewHospital(id);
    }
}

// =====================================================
// REJECT FROM MODAL
// =====================================================

async function rejectHospitalCertificateFromModal() {
    const id =
        currentHospitalDetailsId;

    if (!id) {
        showMessage(
            "Please open a hospital first.",
            "error"
        );
        return;
    }

    const success =
        await rejectHospitalCertificate(
            id
        );

    if (
        success &&
        currentHospitalDetailsId === id
    ) {
        await viewHospital(id);
    }
}

// =====================================================
// APPROVE HOSPITAL
// =====================================================

async function approveHospital(id) {
    const confirmed =
        confirm(
            "Are you sure you want to approve this hospital?"
        );

    if (!confirmed) {
        return;
    }

    await hospitalAction(
        id,
        "approve"
    );
}

// =====================================================
// REJECT HOSPITAL
// =====================================================

async function rejectHospital(id) {
    const reason =
        prompt(
            "Enter rejection reason:"
        );

    if (reason === null) {
        return;
    }

    if (!reason.trim()) {
        alert(
            "Please enter a rejection reason."
        );
        return;
    }

    await hospitalAction(
        id,
        "reject",
        reason.trim()
    );
}

// =====================================================
// PUBLISH HOSPITAL
// =====================================================

async function publishHospital(id) {
    const confirmed =
        confirm(
            "Publish this hospital to the Patient App?"
        );

    if (!confirmed) {
        return;
    }

    await hospitalAction(
        id,
        "publish"
    );
}

// =====================================================
// UNPUBLISH HOSPITAL
// =====================================================

async function unpublishHospital(id) {
    const confirmed =
        confirm(
            "Unpublish this hospital from the Patient App?"
        );

    if (!confirmed) {
        return;
    }

    await hospitalAction(
        id,
        "unpublish"
    );
}

// =====================================================
// DELETE HOSPITAL
// =====================================================

async function deleteHospital(id) {
    const confirmed =
        confirm(
            "WARNING!\n\n" +
            "Deleting this hospital may remove " +
            "its doctors and tokens.\n\n" +
            "Are you sure?"
        );

    if (!confirmed) {
        return;
    }

    await hospitalAction(
        id,
        "delete"
    );
}

// =====================================================
// HOSPITAL ACTION
// APPROVE / REJECT / PUBLISH / UNPUBLISH / DELETE
// =====================================================

async function hospitalAction(
    id,
    action,
    reason = ""
) {
    try {
        let method = "PUT";

        let url =
            `${API}/admin/hospitals/${id}`;

        if (action === "delete") {
            method = "DELETE";

        } else if (action === "approve") {
            url =
                `${API}/admin/hospitals/${id}/approve`;

        } else if (action === "reject") {
            url =
                `${API}/admin/hospitals/${id}/reject`;

        } else if (action === "publish") {
            url =
                `${API}/admin/hospitals/${id}/publish`;

        } else if (action === "unpublish") {
            url =
                `${API}/admin/hospitals/${id}/unpublish`;

        } else {
            throw new Error(
                "Unknown hospital action."
            );
        }

        const options = {
            method: method,
            headers:
                getAdminAuthHeaders({
                    "Content-Type":
                        "application/json"
                })
        };

        if (action === "reject") {
            options.body =
                JSON.stringify({
                    reason:
                        reason
                });

        } else if (action === "approve") {
            options.body =
                JSON.stringify({});
        }

        console.log(
            "Hospital action:",
            action
        );

        console.log(
            "Request URL:",
            url
        );

        const response =
            await fetch(
                url,
                options
            );

        const data =
            await readResponse(
                response
            );

        console.log(
            "Hospital action response:",
            data
        );

        if (!response.ok) {
            throw new Error(
                getErrorMessage(
                    data,
                    `HTTP ${response.status}`
                )
            );
        }

        showMessage(
            data.message ||
            `Hospital ${action} completed successfully.`,
            "success"
        );

        await loadHospitals();

    } catch (error) {
        console.error(
            "Hospital action error:",
            error
        );

        showMessage(
            error.message ||
            "Unable to complete hospital action.",
            "error"
        );
    }
}

// =====================================================
// LOAD TOKENS
// ADMIN USES /admin/tokens
// =====================================================

async function loadTokens() {
    console.log(
        "Loading admin tokens..."
    );

    const tokenTableBody =
        document.getElementById(
            "tokenTableBody"
        );

    if (!tokenTableBody) {
        return;
    }

    tokenTableBody.innerHTML = `
        <tr>
            <td
                colspan="11"
                class="loading"
            >
                Loading tokens...
            </td>
        </tr>
    `;

    try {
        const response =
            await fetch(
                `${API}/admin/tokens`,
                {
                    headers:
                        getAdminAuthHeaders()
                }
            );

        const data =
            await readResponse(
                response
            );

        if (!response.ok) {
            throw new Error(
                getErrorMessage(
                    data,
                    `HTTP ${response.status}`
                )
            );
        }

        const tokens =
            Array.isArray(data)
                ? data
                : data.tokens || [];

        if (tokens.length === 0) {
            tokenTableBody.innerHTML = `
                <tr>
                    <td
                        colspan="11"
                        class="loading"
                    >
                        No tokens found.
                    </td>
                </tr>
            `;

            return;
        }

        tokenTableBody.innerHTML = "";

        tokens.forEach(
            function (token) {
                const row =
                    document.createElement(
                        "tr"
                    );

                const paymentStatus =
                    String(
                        token.payment_status ||
                        "-"
                    ).toUpperCase();

                const tokenStatus =
                    String(
                        token.status ||
                        "-"
                    ).toUpperCase();

                row.innerHTML = `
                    <td>
                        ${escapeHtml(
                            token.id ?? "-"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            token.patient_name || "-"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            token.hospital || "-"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            token.department || "-"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            token.doctor || "-"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            token.token_number ?? "-"
                        )}
                    </td>

                    <td>
                        ₹${Number(
                            token.token_fee || 0
                        )}
                    </td>

                    <td>
                        ₹${Number(
                            token.platform_fee || 0
                        )}
                    </td>

                    <td>
                        ₹${Number(
                            token.total_amount ||
                            (
                                Number(
                                    token.token_fee || 0
                                ) +
                                Number(
                                    token.platform_fee || 0
                                )
                            )
                        )}
                    </td>

                    <td>
                        <span
                            class="status ${
                                paymentStatus === "PAID"
                                    ? "status-paid"
                                    : "status-waiting"
                            }"
                        >
                            ${escapeHtml(
                                paymentStatus
                            )}
                        </span>
                    </td>

                    <td>
                        <span
                            class="status ${
                                tokenStatus === "SERVING"
                                    ? "status-serving"
                                    : tokenStatus === "COMPLETED"
                                        ? "status-completed"
                                        : "status-waiting"
                            }"
                        >
                            ${escapeHtml(
                                tokenStatus
                            )}
                        </span>
                    </td>
                `;

                tokenTableBody.appendChild(
                    row
                );
            }
        );

    } catch (error) {
        console.error(
            "Token loading error:",
            error
        );

        tokenTableBody.innerHTML = `
            <tr>
                <td
                    colspan="11"
                    class="loading"
                >
                    ❌ Unable to load tokens.
                    <br><br>
                    ${escapeHtml(
                        error.message ||
                        "Make sure FastAPI is running."
                    )}
                </td>
            </tr>
        `;
    }
}

// =====================================================
// LOAD PAYMENTS
// ADMIN USES /admin/tokens
// =====================================================

async function loadPayments() {
    console.log(
        "Loading payments..."
    );

    const paymentTableBody =
        document.getElementById(
            "paymentTableBody"
        );

    if (!paymentTableBody) {
        return;
    }

    paymentTableBody.innerHTML = `
        <tr>
            <td
                colspan="10"
                class="loading"
            >
                Loading payments...
            </td>
        </tr>
    `;

    try {
        const response =
            await fetch(
                `${API}/admin/tokens`,
                {
                    headers:
                        getAdminAuthHeaders()
                }
            );

        const data =
            await readResponse(
                response
            );

        if (!response.ok) {
            throw new Error(
                getErrorMessage(
                    data,
                    `HTTP ${response.status}`
                )
            );
        }

        const tokens =
            Array.isArray(data)
                ? data
                : data.tokens || [];

        if (tokens.length === 0) {
            paymentTableBody.innerHTML = `
                <tr>
                    <td
                        colspan="10"
                        class="loading"
                    >
                        No payment records found.
                    </td>
                </tr>
            `;

            return;
        }

        paymentTableBody.innerHTML = "";

        tokens.forEach(
            function (token) {
                const row =
                    document.createElement(
                        "tr"
                    );

                const paymentStatus =
                    String(
                        token.payment_status ||
                        "PENDING"
                    ).toUpperCase();

                row.innerHTML = `
                    <td>
                        ${escapeHtml(
                            token.id ?? "-"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            token.patient_name || "-"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            token.hospital || "-"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            token.department || "-"
                        )}
                    </td>

                    <td>
                        ${escapeHtml(
                            token.doctor || "-"
                        )}
                    </td>

                    <td>
                        ₹${Number(
                            token.token_fee || 0
                        )}
                    </td>

                    <td>
                        ₹${Number(
                            token.platform_fee || 0
                        )}
                    </td>

                    <td>
                        ₹${Number(
                            token.total_amount || 0
                        )}
                    </td>

                    <td>
                        <span
                            class="status ${
                                paymentStatus === "PAID"
                                    ? "status-paid"
                                    : "status-waiting"
                            }"
                        >
                            ${escapeHtml(
                                paymentStatus
                            )}
                        </span>
                    </td>

                    <td>
                        ${escapeHtml(
                            token.razorpay_payment_id ||
                            "-"
                        )}
                    </td>
                `;

                paymentTableBody.appendChild(
                    row
                );
            }
        );

    } catch (error) {
        console.error(
            "Payment loading error:",
            error
        );

        paymentTableBody.innerHTML = `
            <tr>
                <td
                    colspan="10"
                    class="loading"
                >
                    ❌ Unable to load payments.
                    <br><br>
                    ${escapeHtml(
                        error.message ||
                        "Make sure FastAPI is running."
                    )}
                </td>
            </tr>
        `;
    }
}

// =====================================================
// SHOW MESSAGE
// =====================================================

function showMessage(
    message,
    type = "success"
) {
    const element =
        document.getElementById(
            "message"
        );

    if (!element) {
        alert(message);
        return;
    }

    element.textContent =
        message;

    element.className =
        `message ${type}`;

    setTimeout(
        function () {
            element.textContent =
                "";

            element.className =
                "message";
        },
        4000
    );
}

// =====================================================
// ERROR MESSAGE FORMATTER
// =====================================================

function getErrorMessage(
    data,
    fallback = "Request failed."
) {
    if (!data) {
        return fallback;
    }

    if (
        typeof data.detail ===
        "string"
    ) {
        return data.detail;
    }

    if (
        Array.isArray(data.detail)
    ) {
        return data.detail
            .map(
                function (item) {
                    if (
                        typeof item ===
                        "string"
                    ) {
                        return item;
                    }

                    if (
                        item &&
                        typeof item ===
                        "object"
                    ) {
                        const location =
                            Array.isArray(
                                item.loc
                            )
                                ? item.loc.join(
                                      " → "
                                  )
                                : "";

                        const message =
                            item.msg ||
                            "Invalid value";

                        return location
                            ? `${location}: ${message}`
                            : message;
                    }

                    return String(item);
                }
            )
            .join("\n");
    }

    if (
        data.message &&
        typeof data.message ===
        "string"
    ) {
        return data.message;
    }

    return fallback;
}

// =====================================================
// HTML ESCAPE
// =====================================================

function escapeHtml(value) {
    const div =
        document.createElement(
            "div"
        );

    div.textContent =
        String(value ?? "");

    return div.innerHTML;
}

// =====================================================
// EXPORT FUNCTIONS
// =====================================================

window.adminLogin =
    adminLogin;

window.handleGoogleLogin =
    handleGoogleLogin;

window.adminLogout =
    adminLogout;

window.openHospitals =
    openHospitals;

window.openPayments =
    openPayments;

window.openTokens =
    openTokens;

window.goDashboard =
    goDashboard;

window.loadDashboard =
    loadDashboard;

window.loadHospitals =
    loadHospitals;

window.loadTokens =
    loadTokens;

window.loadPayments =
    loadPayments;

window.viewHospital =
    viewHospital;

window.closeHospitalDetails =
    closeHospitalDetails;

window.verifyHospitalCertificate =
    verifyHospitalCertificate;

window.rejectHospitalCertificate =
    rejectHospitalCertificate;

window.adminUploadHospitalPhoto = adminUploadHospitalPhoto;
window.adminUploadHospitalCertificate = adminUploadHospitalCertificate;
window.verifyHospitalCertificateFromModal =
    verifyHospitalCertificateFromModal;

window.rejectHospitalCertificateFromModal =
    rejectHospitalCertificateFromModal;

window.approveHospital =
    approveHospital;

window.rejectHospital =
    rejectHospital;

window.publishHospital =
    publishHospital;

window.unpublishHospital =
    unpublishHospital;

window.deleteHospital =
    deleteHospital;

window.hospitalAction =
    hospitalAction;

window.showMessage =
    showMessage;

// =====================================================
// ADMIN UPLOAD HOSPITAL PHOTO
// =====================================================
async function adminUploadHospitalPhoto() {
    const id = currentHospitalDetailsId;
    if (!id) {
        alert("Please open a hospital first.");
        return;
    }
    const fileInput = document.getElementById("adminPhotoFileInput");
    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
        alert("Please select an image file (JPG, PNG, or WEBP) first.");
        return;
    }

    const formData = new FormData();
    formData.append("photo", fileInput.files[0]);

    const token = localStorage.getItem("adminToken");
    try {
        const res = await fetch(`${API}/admin/hospitals/${id}/photo`, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${token}`
            },
            body: formData
        });
        const data = await readResponse(res);
        if (!res.ok) {
            throw new Error(getErrorMessage(data, "Failed to upload photo"));
        }
        showMessage("Hospital cover photo updated successfully!", "success");
        await viewHospital(id);
    } catch (err) {
        alert(err.message || "Failed to upload photo");
    }
}

// =====================================================
// ADMIN UPLOAD HOSPITAL CERTIFICATE
// =====================================================
async function adminUploadHospitalCertificate() {
    const id = currentHospitalDetailsId;
    if (!id) {
        alert("Please open a hospital first.");
        return;
    }
    const fileInput = document.getElementById("adminCertificateFileInput");
    if (!fileInput || !fileInput.files || !fileInput.files[0]) {
        alert("Please select a certificate file (PDF, JPG, or PNG) first.");
        return;
    }

    const formData = new FormData();
    formData.append("certificate", fileInput.files[0]);

    const token = localStorage.getItem("adminToken");
    try {
        const res = await fetch(`${API}/admin/hospitals/${id}/certificate`, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${token}`
            },
            body: formData
        });
        const data = await readResponse(res);
        if (!res.ok) {
            throw new Error(getErrorMessage(data, "Failed to upload certificate"));
        }
        showMessage("Hospital certificate updated successfully!", "success");
        await viewHospital(id);
    } catch (err) {
        alert(err.message || "Failed to upload certificate");
    }
}


// =====================================================
// DIRECT COMMUNICATION (ADMIN <-> HOSPITAL)
// =====================================================

function setupHospitalDirectCommunication(hospital, hospitalId) {
    resetHospitalDirectCommunication();

    const rawPhone = hospital.phone || "";
    const cleanPhone = String(rawPhone).replace(/[^0-9]/g, "");

    const btnWhatsApp = document.getElementById("btnHospitalWhatsApp");
    if (btnWhatsApp) {
        if (cleanPhone) {
            const waNumber = cleanPhone.length === 10 ? `91${cleanPhone}` : cleanPhone;
            btnWhatsApp.href = `https://wa.me/${waNumber}?text=${encodeURIComponent(`Hello ${hospital.name || "Hospital"}, this is CarePath Platform Admin.`)}`;
            btnWhatsApp.style.display = "inline-flex";
        } else {
            btnWhatsApp.style.display = "none";
        }
    }

    const btnCall = document.getElementById("btnHospitalCall");
    if (btnCall) {
        if (cleanPhone) {
            btnCall.href = `tel:${cleanPhone}`;
            btnCall.style.display = "inline-flex";
        } else {
            btnCall.style.display = "none";
        }
    }

    loadHospitalMessages(hospitalId);
}

function resetHospitalDirectCommunication() {
    const container = document.getElementById("hospitalMessagesContainer");
    if (container) {
        container.innerHTML = `<div style="text-align: center; color: #64748b; font-size: 13px; padding: 10px 0;">Loading conversation...</div>`;
    }
    const subjInput = document.getElementById("adminMsgSubject");
    if (subjInput) subjInput.value = "";
    const textInput = document.getElementById("adminMsgText");
    if (textInput) textInput.value = "";
}

async function loadHospitalMessages(hospitalId) {
    const container = document.getElementById("hospitalMessagesContainer");
    if (!container) return;

    container.innerHTML = `
        <div style="text-align: center; color: #64748b; font-size: 13px; padding: 12px 0;">
            💬 Loading conversation messages...
        </div>
    `;

    try {
        const response = await fetch(`${API}/admin/hospitals/${hospitalId}/messages`, {
            headers: getAdminAuthHeaders()
        });

        const data = await readResponse(response);

        if (!response.ok) {
            throw new Error(getErrorMessage(data, "Unable to load conversation"));
        }

        const messages = Array.isArray(data.messages) ? data.messages : [];

        if (messages.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; color: #94a3b8; font-size: 13px; padding: 25px 10px; background: white; border-radius: 8px; border: 1px dashed #cbd5e1;">
                    <div style="font-size: 24px; margin-bottom: 6px;">💬</div>
                    <strong style="color: #475569;">No messages exchanged yet</strong>
                    <div style="font-size: 12px; margin-top: 4px; color: #64748b;">
                        Send your first direct message, inquiry, or compliance notice below.
                    </div>
                </div>
            `;
            return;
        }

        container.innerHTML = messages.map(msg => {
            const isAdmin = (msg.sender_role || "").toLowerCase() === "admin";
            const align = isAdmin ? "flex-end" : "flex-start";
            const bubbleBg = isAdmin ? "#2563eb" : "#ffffff";
            const textColor = isAdmin ? "#ffffff" : "#0f172a";
            const border = isAdmin ? "none" : "1px solid #e2e8f0";
            const senderTag = isAdmin ? "Platform Admin (You)" : (msg.sender_name || "Hospital Staff");
            const timeStr = msg.created_at ? new Date(msg.created_at).toLocaleString() : "";
            const isUrgent = msg.priority === "urgent";
            const isCompliance = msg.priority === "compliance";

            let priorityBadge = "";
            if (isUrgent) {
                priorityBadge = `<span style="background: ${isAdmin ? '#ef4444' : '#fee2e2'}; color: ${isAdmin ? '#fff' : '#b91c1c'}; font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 4px; text-transform: uppercase;">🚨 URGENT</span>`;
            } else if (isCompliance) {
                priorityBadge = `<span style="background: ${isAdmin ? '#f59e0b' : '#fef3c7'}; color: ${isAdmin ? '#fff' : '#b45309'}; font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 4px; text-transform: uppercase;">⚠️ COMPLIANCE</span>`;
            }

            const emailTag = msg.sent_via_email 
                ? `<span style="font-size: 11px; opacity: 0.85; margin-left: 6px;">📧 Dispatched to email</span>` 
                : "";

            return `
                <div style="display: flex; flex-direction: column; align-self: ${align}; max-width: 85%;">
                    <div style="font-size: 11px; color: #64748b; margin-bottom: 3px; display: flex; gap: 6px; align-items: center; justify-content: ${isAdmin ? 'flex-end' : 'flex-start'};">
                        <strong>${escapeHtml(senderTag)}</strong>
                        <span>•</span>
                        <span>${timeStr}</span>
                        ${emailTag}
                    </div>
                    <div style="background: ${bubbleBg}; color: ${textColor}; border: ${border}; border-radius: 12px; padding: 11px 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); font-size: 13px; line-height: 1.45;">
                        ${priorityBadge ? `<div style="margin-bottom: 6px;">${priorityBadge}</div>` : ''}
                        ${msg.subject ? `<div style="font-weight: 700; margin-bottom: 4px; font-size: 13.5px;">${escapeHtml(msg.subject)}</div>` : ''}
                        <div style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(msg.message || '')}</div>
                    </div>
                </div>
            `;
        }).join("");

        container.scrollTop = container.scrollHeight;
    } catch (err) {
        console.error("Load messages error:", err);
        container.innerHTML = `
            <div style="color: #ef4444; font-size: 13px; text-align: center; padding: 14px;">
                Failed to load conversation: ${escapeHtml(err.message)}
            </div>
        `;
    }
}

async function sendDirectMessageToHospital() {
    if (!currentHospitalDetailsId) {
        alert("Please open a hospital first.");
        return;
    }

    const textInput = document.getElementById("adminMsgText");
    const subjInput = document.getElementById("adminMsgSubject");
    const prioSelect = document.getElementById("adminMsgPriority");
    const emailCheck = document.getElementById("adminMsgSendEmail");
    const btn = document.getElementById("btnAdminSendMsg");

    const message = textInput ? textInput.value.trim() : "";
    if (!message) {
        alert("Please enter a message for the hospital.");
        if (textInput) textInput.focus();
        return;
    }

    const subject = subjInput ? subjInput.value.trim() : "";
    const priority = prioSelect ? prioSelect.value : "normal";
    const sendEmail = emailCheck ? emailCheck.checked : true;

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = "⏳ Sending...";
    }

    try {
        const response = await fetch(`${API}/admin/hospitals/${currentHospitalDetailsId}/messages`, {
            method: "POST",
            headers: {
                ...getAdminAuthHeaders(),
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                subject: subject || null,
                message: message,
                priority: priority,
                send_email: sendEmail
            })
        });

        const data = await readResponse(response);

        if (!response.ok) {
            throw new Error(getErrorMessage(data, "Could not send direct message"));
        }

        if (textInput) textInput.value = "";
        if (subjInput) subjInput.value = "";

        showMessage(
            data.email_dispatched 
                ? "Message sent to hospital and email copy dispatched!" 
                : "Message delivered to hospital dashboard!",
            "success"
        );

        await loadHospitalMessages(currentHospitalDetailsId);
    } catch (err) {
        console.error("Send message error:", err);
        alert(err.message || "Failed to send message to hospital");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = "🚀 Send Message";
        }
    }
}


// =====================================================
// DEDICATED DIRECT COMMUNICATION MODAL FUNCTIONS
// =====================================================

function switchHospitalModalTab(tabName) {
    const detailsTab = document.getElementById("hospitalModalDetailsTab");
    const commTab = document.getElementById("hospitalModalCommTab");
    const btnDetails = document.getElementById("tabBtnDetails");
    const btnComm = document.getElementById("tabBtnComm");

    if (tabName === "comm") {
        if (detailsTab) detailsTab.style.display = "none";
        if (commTab) commTab.style.display = "block";
        if (btnDetails) {
            btnDetails.style.background = "#f1f5f9";
            btnDetails.style.color = "#475569";
        }
        if (btnComm) {
            btnComm.style.background = "#2563eb";
            btnComm.style.color = "#ffffff";
        }
    } else {
        if (detailsTab) detailsTab.style.display = "block";
        if (commTab) commTab.style.display = "none";
        if (btnDetails) {
            btnDetails.style.background = "#2563eb";
            btnDetails.style.color = "#ffffff";
        }
        if (btnComm) {
            btnComm.style.background = "#f1f5f9";
            btnComm.style.color = "#475569";
        }
    }
}

async function openDirectCommModal(hospitalId, hospitalName = "", hospitalPhone = "", hospitalCity = "") {
    const modal = document.getElementById("directCommModal");
    if (!modal) {
        // Fallback: If dedicated modal is missing, open via viewHospital
        await viewHospital(hospitalId);
        switchHospitalModalTab("comm");
        return;
    }

    currentDirectCommHospitalId = Number(hospitalId);
    currentHospitalDetailsId = Number(hospitalId);

    // If name wasn't passed, find in allLoadedHospitals
    if (!hospitalName && Array.isArray(allLoadedHospitals)) {
        const found = allLoadedHospitals.find(h => Number(h.id) === currentDirectCommHospitalId);
        if (found) {
            hospitalName = found.name || found.hospital_name || "";
            hospitalPhone = found.phone || "";
            hospitalCity = found.city || "";
        }
    }

    const titleEl = document.getElementById("commModalHospitalBadge");
    if (titleEl) {
        titleEl.textContent = hospitalName ? `${hospitalName} (ID: ${hospitalId})` : `Hospital #${hospitalId}`;
    }

    const cityEl = document.getElementById("commModalCityBadge");
    if (cityEl) {
        cityEl.textContent = hospitalCity ? `📍 ${hospitalCity}` : "";
    }

    const pickerEl = document.getElementById("commModalHospitalPicker");
    if (pickerEl) pickerEl.style.display = "none";

    // Clean Phone for WhatsApp and Call
    const cleanPhone = String(hospitalPhone || "").replace(/[^0-9]/g, "");
    const btnWhatsApp = document.getElementById("commModalWhatsAppBtn");
    if (btnWhatsApp) {
        if (cleanPhone) {
            const waNumber = cleanPhone.length === 10 ? `91${cleanPhone}` : cleanPhone;
            btnWhatsApp.href = `https://wa.me/${waNumber}?text=${encodeURIComponent(`Hello ${hospitalName || "Hospital"}, this is CarePath Platform Admin.`)}`;
            btnWhatsApp.style.display = "inline-flex";
        } else {
            btnWhatsApp.style.display = "none";
        }
    }

    const btnCall = document.getElementById("commModalCallBtn");
    if (btnCall) {
        if (cleanPhone) {
            btnCall.href = `tel:${cleanPhone}`;
            btnCall.style.display = "inline-flex";
        } else {
            btnCall.style.display = "none";
        }
    }

    // Reset inputs
    const subjInput = document.getElementById("commModalMsgSubject");
    if (subjInput) subjInput.value = "";
    const textInput = document.getElementById("commModalMsgText");
    if (textInput) textInput.value = "";

    modal.style.display = "block";
    await loadDirectCommMessages(currentDirectCommHospitalId);
}

function closeDirectCommModal() {
    const modal = document.getElementById("directCommModal");
    if (modal) modal.style.display = "none";
    currentDirectCommHospitalId = null;
}

function openGeneralDirectCommunicationModal() {
    const modal = document.getElementById("directCommModal");
    if (!modal) return;

    const pickerEl = document.getElementById("commModalHospitalPicker");
    const selectEl = document.getElementById("commModalHospitalSelect");

    if (pickerEl && selectEl && Array.isArray(allLoadedHospitals) && allLoadedHospitals.length > 0) {
        pickerEl.style.display = "block";
        selectEl.innerHTML = allLoadedHospitals.map(h => 
            `<option value="${h.id}">${escapeHtml(h.name || 'Hospital')} (ID: ${h.id}${h.city ? ', ' + h.city : ''})</option>`
        ).join("");

        const first = allLoadedHospitals[0];
        openDirectCommModal(first.id, first.name, first.phone, first.city);
        pickerEl.style.display = "block";
        selectEl.value = String(first.id);
    } else {
        alert("Loading hospitals... please wait 2 seconds and try again.");
    }
}

function onCommHospitalSelectChange(hospId) {
    const hid = Number(hospId);
    if (!Array.isArray(allLoadedHospitals)) return;
    const target = allLoadedHospitals.find(h => Number(h.id) === hid);
    if (target) {
        openDirectCommModal(target.id, target.name, target.phone, target.city);
        const pickerEl = document.getElementById("commModalHospitalPicker");
        if (pickerEl) pickerEl.style.display = "block";
        const selectEl = document.getElementById("commModalHospitalSelect");
        if (selectEl) selectEl.value = String(target.id);
    }
}

async function refreshCurrentCommMessages() {
    if (currentDirectCommHospitalId) {
        await loadDirectCommMessages(currentDirectCommHospitalId);
    }
}

async function loadDirectCommMessages(hospitalId) {
    const container = document.getElementById("commModalMessagesContainer");
    if (!container) return;

    container.innerHTML = `
        <div style="text-align: center; color: #64748b; font-size: 13px; padding: 20px 0;">
            💬 Loading conversation messages...
        </div>
    `;

    try {
        const response = await fetch(`${API}/admin/hospitals/${hospitalId}/messages`, {
            headers: getAdminAuthHeaders()
        });

        const data = await readResponse(response);

        if (!response.ok) {
            throw new Error(getErrorMessage(data, "Unable to load conversation"));
        }

        const messages = Array.isArray(data.messages) ? data.messages : [];

        if (messages.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; color: #94a3b8; font-size: 13px; padding: 30px 10px; background: white; border-radius: 8px; border: 1px dashed #cbd5e1;">
                    <div style="font-size: 28px; margin-bottom: 6px;">💬</div>
                    <strong style="color: #475569; font-size: 14px;">No messages exchanged yet</strong>
                    <div style="font-size: 12px; margin-top: 4px; color: #64748b;">
                        Send your first direct message, inquiry, or compliance notice below.
                    </div>
                </div>
            `;
            return;
        }

        container.innerHTML = messages.map(msg => {
            const isAdmin = (msg.sender_role || "").toLowerCase() === "admin";
            const align = isAdmin ? "flex-end" : "flex-start";
            const bubbleBg = isAdmin ? "#2563eb" : "#ffffff";
            const textColor = isAdmin ? "#ffffff" : "#0f172a";
            const border = isAdmin ? "none" : "1px solid #e2e8f0";
            const senderTag = isAdmin ? "Platform Admin (You)" : (msg.sender_name || "Hospital Staff");
            const timeStr = msg.created_at ? new Date(msg.created_at).toLocaleString() : "";
            const isUrgent = msg.priority === "urgent";
            const isCompliance = msg.priority === "compliance";

            let priorityBadge = "";
            if (isUrgent) {
                priorityBadge = `<span style="background: ${isAdmin ? '#ef4444' : '#fee2e2'}; color: ${isAdmin ? '#fff' : '#b91c1c'}; font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 4px; text-transform: uppercase;">🚨 URGENT</span>`;
            } else if (isCompliance) {
                priorityBadge = `<span style="background: ${isAdmin ? '#f59e0b' : '#fef3c7'}; color: ${isAdmin ? '#fff' : '#b45309'}; font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 4px; text-transform: uppercase;">⚠️ COMPLIANCE</span>`;
            }

            const emailTag = msg.sent_via_email 
                ? `<span style="font-size: 11px; opacity: 0.85; margin-left: 6px;">📧 Dispatched to email</span>` 
                : "";

            return `
                <div style="display: flex; flex-direction: column; align-self: ${align}; max-width: 85%;">
                    <div style="font-size: 11px; color: #64748b; margin-bottom: 3px; display: flex; gap: 6px; align-items: center; justify-content: ${isAdmin ? 'flex-end' : 'flex-start'};">
                        <strong>${escapeHtml(senderTag)}</strong>
                        <span>•</span>
                        <span>${timeStr}</span>
                        ${emailTag}
                    </div>
                    <div style="background: ${bubbleBg}; color: ${textColor}; border: ${border}; border-radius: 12px; padding: 11px 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); font-size: 13px; line-height: 1.45;">
                        ${priorityBadge ? `<div style="margin-bottom: 6px;">${priorityBadge}</div>` : ''}
                        ${msg.subject ? `<div style="font-weight: 700; margin-bottom: 4px; font-size: 13.5px;">${escapeHtml(msg.subject)}</div>` : ''}
                        <div style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(msg.message || '')}</div>
                    </div>
                </div>
            `;
        }).join("");

        container.scrollTop = container.scrollHeight;
    } catch (err) {
        console.error("Load direct comm messages error:", err);
        container.innerHTML = `
            <div style="color: #ef4444; font-size: 13px; text-align: center; padding: 14px;">
                Failed to load conversation: ${escapeHtml(err.message)}
            </div>
        `;
    }
}

async function sendCommModalMessage() {
    if (!currentDirectCommHospitalId) {
        alert("Please select a hospital first.");
        return;
    }

    const textInput = document.getElementById("commModalMsgText");
    const subjInput = document.getElementById("commModalMsgSubject");
    const prioSelect = document.getElementById("commModalMsgPriority");
    const emailCheck = document.getElementById("commModalSendEmail");
    const btn = document.getElementById("btnCommModalSend");

    const message = textInput ? textInput.value.trim() : "";
    if (!message) {
        alert("Please enter a message for the hospital.");
        if (textInput) textInput.focus();
        return;
    }

    const subject = subjInput ? subjInput.value.trim() : "";
    const priority = prioSelect ? prioSelect.value : "normal";
    const sendEmail = emailCheck ? emailCheck.checked : true;

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = "⏳ Sending...";
    }

    try {
        const response = await fetch(`${API}/admin/hospitals/${currentDirectCommHospitalId}/messages`, {
            method: "POST",
            headers: {
                ...getAdminAuthHeaders(),
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                subject: subject || null,
                message: message,
                priority: priority,
                send_email: sendEmail
            })
        });

        const data = await readResponse(response);

        if (!response.ok) {
            throw new Error(getErrorMessage(data, "Could not send direct message"));
        }

        if (textInput) textInput.value = "";
        if (subjInput) subjInput.value = "";

        showMessage(
            data.email_dispatched 
                ? "Message sent to hospital and email copy dispatched!" 
                : "Message delivered to hospital dashboard!",
            "success"
        );

        await loadDirectCommMessages(currentDirectCommHospitalId);
    } catch (err) {
        console.error("Send message error:", err);
        alert(err.message || "Failed to send message to hospital");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = "🚀 Send Message";
        }
    }
}

window.openDirectCommModal = openDirectCommModal;
window.closeDirectCommModal = closeDirectCommModal;
window.openGeneralDirectCommunicationModal = openGeneralDirectCommunicationModal;
window.onCommHospitalSelectChange = onCommHospitalSelectChange;
window.switchHospitalModalTab = switchHospitalModalTab;
window.refreshCurrentCommMessages = refreshCurrentCommMessages;
window.sendCommModalMessage = sendCommModalMessage;

window.addEventListener("DOMContentLoaded", function() {
    const directCommModalEl = document.getElementById("directCommModal");
    if (directCommModalEl) {
        directCommModalEl.addEventListener("click", function(e) {
            if (e.target === directCommModalEl) {
                closeDirectCommModal();
            }
        });
    }
});
