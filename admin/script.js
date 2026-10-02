// =====================================================
// CAREPATH ADMIN JAVASCRIPT
// =====================================================

const API = "https://carepath-3q9q.onrender.com";
const FRONTEND = "https://carepath-admin.vercel.app";

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
// PAGE LOAD
// =====================================================

document.addEventListener("DOMContentLoaded", function () {

    console.log("CarePath Admin started.");

    const path =
        window.location.pathname.toLowerCase();

    console.log("Current page:", path);


    // Admin dashboard

    if (path.includes("dashboard.html")) {

        loadDashboard();

    }


    // Hospitals

    if (path.includes("hospitals.html")) {

        loadHospitals();

    }


    // Payments

    if (path.includes("payments.html")) {

        loadPayments();

    }


    // Tokens

    if (path.includes("tokens.html")) {

        loadTokens();

    }


    // Admin login

    if (
        path.endsWith("/admin/") ||
        path.endsWith("/admin/index.html") ||
        path.endsWith("index.html")
    ) {

        console.log(
            "Admin login page loaded."
        );

    }

});
// =====================================================
// ADMIN LOGIN
// =====================================================

async function adminLogin() {
    const emailInput = document.getElementById("adminEmail");
    const passwordInput = document.getElementById("adminPassword");

    const email = emailInput?.value.trim().toLowerCase() || "";
    const password = passwordInput?.value || "";

    if (!email || !password) {
        showLoginMessage(
            "Please enter your email and password.",
            "error"
        );
        return;
    }

    try {
        showLoginMessage("Logging in...", "success");

        const response = await fetch(`${API}/admin/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                email: email,
                password: password
            })
        });

        const data = await readResponse(response);

        console.log("Admin login status:", response.status);
        console.log("Admin login response:", data);

        if (!response.ok) {
            console.error("Admin login failed:", {
                status: response.status,
                response: data
            });

            showLoginMessage(
                getErrorMessage(
                    data,
                    `Login failed (HTTP ${response.status}).`
                ),
                "error"
            );
            return;
        }

        localStorage.setItem("adminLoggedIn", "true");
        localStorage.setItem("adminEmail", email);
        localStorage.setItem("adminRole", "admin");

        showLoginMessage(
            "Login successful. Opening dashboard...",
            "success"
        );

        setTimeout(() => {
            window.location.href = `${FRONTEND}/dashboard.html`;
        }, 500);

    } catch (error) {
        console.error("Admin login connection error:", error);

        showLoginMessage(
            "Cannot connect to FastAPI. Make sure your backend is running at https://carepath-3q9q.onrender.com",
            "error"
        );
    }
}


// =====================================================
// GOOGLE ADMIN LOGIN
// =====================================================

async function handleGoogleLogin(response) {
    if (!response || !response.credential) {
        showLoginMessage("Google login failed. Please try again.", "error");
        return;
    }

    try {
        showLoginMessage("Verifying Google account...", "success");

        const result = await fetch(`${API}/auth/google`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                credential: response.credential,
                role: "admin"
            })
        });

        const data = await readResponse(result);

        console.log("Google login status:", result.status);
        console.log("Google login response:", data);

        if (!result.ok) {
            console.error("Google login failed:", {
                status: result.status,
                response: data
            });

            showLoginMessage(
                getErrorMessage(
                    data,
                    `Google login failed (HTTP ${result.status}).`
                ),
                "error"
            );
            return;
        }

        localStorage.setItem("adminLoggedIn", "true");
        localStorage.setItem(
            "adminEmail",
            data.user?.email || data.email || "Google Admin"
        );
        localStorage.setItem("adminRole", "admin");

        showLoginMessage(
            "Google login successful. Opening dashboard...",
            "success"
        );

        setTimeout(() => {
            window.location.href = `${FRONTEND}/dashboard.html`;
        }, 500);

    } catch (error) {
        console.error("Google login connection error:", error);

        showLoginMessage(
            "Cannot connect to CarePath FastAPI.",
            "error"
        );
    }
}


// =====================================================
// LOGIN MESSAGE
// =====================================================

function showLoginMessage(message, type = "success") {
    const element = document.getElementById("loginMessage");

    if (!element) {
        alert(message);
        return;
    }

    element.textContent = message;
    element.className = `message ${type}`;
}
// =====================================================
// ADMIN LOGOUT
// =====================================================


function adminLogout() {
    localStorage.removeItem("adminLoggedIn");
    localStorage.removeItem("adminEmail");
    localStorage.removeItem("adminRole");

    window.location.replace("index.html");
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

        const response =
            await fetch(
                `${API}/admin/hospitals`
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

        const response =
            await fetch(
                `${API}/admin/revenue`
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


        /*
         * Backend values
         *
         * token_revenue
         * platform_revenue
         * total_revenue
         * total_collected
         * total_tokens
         */


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


        // Platform revenue

        const platformRevenue =
            document.getElementById(
                "platformRevenue"
            );


        if (platformRevenue) {

            platformRevenue.textContent =
                `₹${platformRevenueValue}`;
        }


        // Platform revenue second box

        const platformRevenue2 =
            document.getElementById(
                "platformRevenue2"
            );


        if (platformRevenue2) {

            platformRevenue2.textContent =
                `₹${platformRevenueValue}`;
        }


        // Hospital token fee revenue

        const tokenRevenue =
            document.getElementById(
                "tokenRevenue"
            );


        if (tokenRevenue) {

            tokenRevenue.textContent =
                `₹${tokenRevenueValue}`;
        }


        // Total collected

        const totalCollected =
            document.getElementById(
                "totalCollected"
            );


        if (totalCollected) {

            totalCollected.textContent =
                `₹${totalCollectedValue}`;
        }


        // Token count

        const tokenCount =
            document.getElementById(
                "tokenCount"
            );


        if (tokenCount) {

            tokenCount.textContent =
                totalTokens;
        }


        // Payment count

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
                Loading hospitals...
            </td>

        </tr>

    `;


    try {

        const response =
            await fetch(
                `${API}/admin/hospitals`
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


                if (
                    status === "APPROVED"
                ) {

                    statusClass =
                        "approved";
                }


                if (
                    status === "REJECTED"
                ) {

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


                row.innerHTML = `

                    <td>
                        ${escapeHtml(
                            hospital.id ?? "-"
                        )}
                    </td>


                    <td>

                        <strong>
                            ${escapeHtml(
                                hospital.name || "-"
                            )}
                        </strong>

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


        tableBody.innerHTML = `

            <tr>

                <td
                    colspan="9"
                    class="loading"
                >

                    ❌ Cannot connect to FastAPI.

                    <br><br>

                    ${escapeHtml(
                        error.message ||
                        "Make sure the backend is running."
                    )}

                </td>

            </tr>

        `;
    }
}


// =====================================================
// VIEW HOSPITAL
// =====================================================




 // =====================================================
 // VIEW HOSPITAL AND CERTIFICATE
 // =====================================================

let currentHospitalDetailsId = null;


// Open selected hospital details
async function viewHospital(id) {
    const hospitalId = Number(id);

    if (!Number.isInteger(hospitalId) || hospitalId <= 0) {
        showMessage("Invalid hospital ID.", "error");
        return;
    }

    const modal = document.getElementById("hospitalDetailsModal");
    const nameElement = document.getElementById("modalHospitalName");
    const detailsElement = document.getElementById("hospitalDetailsContent");
    const certificateName = document.getElementById("certificateFileName");
    const certificateViewer = document.getElementById("certificateViewer");
    const hospitalPhotoPreview = document.getElementById("hospitalPhotoPreview");
    const hospitalPhotoMessage = document.getElementById("hospitalPhotoMessage");
    const messageElement = document.getElementById("certificateModalMessage");
    const verifyButton = document.getElementById("verifyCertificateButton");
    const rejectButton = document.getElementById("rejectCertificateButton");

    if (!modal || !nameElement || !detailsElement ||
        !certificateName || !certificateViewer) {
        showMessage(
            "Hospital details modal is missing from hospitals.html.",
            "error"
        );
        return;
    }

    currentHospitalDetailsId = hospitalId;

    modal.style.display = "block";
    nameElement.textContent = "Loading hospital...";
    detailsElement.textContent = "Loading hospital details...";
    certificateName.textContent = "Checking certificate...";
    certificateViewer.src = "about:blank";

    if (hospitalPhotoPreview) {
        hospitalPhotoPreview.style.display = "none";
        hospitalPhotoPreview.removeAttribute("src");
    }
    if (hospitalPhotoMessage) {
        hospitalPhotoMessage.textContent = "Loading hospital photo...";
    }

    if (messageElement) {
        messageElement.textContent = "";
    }

    if (verifyButton) verifyButton.disabled = true;
    if (rejectButton) rejectButton.disabled = true;

    try {
        const response = await fetch(
            `${API}/admin/hospitals/${hospitalId}`
        );

        const hospital = await readResponse(response);

        if (!response.ok) {
            throw new Error(
                getErrorMessage(hospital, "Could not load hospital details.")
            );
        }

        nameElement.textContent =
            hospital.name ||
            hospital.hospital_name ||
            "Hospital Details";

        // Show the same uploaded cover photo used by the Patient App.
        const imagePath = hospital.image_url || hospital.photo_url || hospital.hospital_photo_url || "";
        if (hospitalPhotoPreview && hospitalPhotoMessage) {
            if (imagePath) {
                const photoUrl = /^https?:\/\//i.test(imagePath)
                    ? imagePath
                    : `${API}${imagePath.startsWith("/") ? "" : "/"}${imagePath}`;
                hospitalPhotoPreview.onload = () => {
                    hospitalPhotoPreview.style.display = "block";
                    hospitalPhotoMessage.textContent = "Hospital cover photo loaded.";
                };
                hospitalPhotoPreview.onerror = () => {
                    hospitalPhotoPreview.style.display = "none";
                    hospitalPhotoMessage.textContent = "Photo URL exists, but the image could not be loaded.";
                };
                hospitalPhotoPreview.src = photoUrl;
            } else {
                hospitalPhotoPreview.style.display = "none";
                hospitalPhotoMessage.textContent = "No cover photo uploaded for this hospital.";
            }
        }

        const fields = [
            ["Hospital Name", hospital.name || hospital.hospital_name],
            ["City", hospital.city],
            ["Address", hospital.address],
            ["License ID", hospital.license_id || hospital.registration_number],
            ["Token Fee", hospital.token_fee == null ? "" : `₹${hospital.token_fee}`],
            ["Approval Status", hospital.approval_status],
            ["Published", hospital.is_published ? "Yes" : "No"],
            [
                "Certificate Status",
                hospital.certificate_verification_status || "PENDING"
            ],
            ["Issuing Authority", hospital.issuing_authority],
            ["License Expiry Date", hospital.license_expiry_date]
        ];

        detailsElement.replaceChildren();

        fields.forEach(([label, value]) => {
            const paragraph = document.createElement("p");
            const strong = document.createElement("strong");

            strong.textContent = `${label}: `;
            paragraph.appendChild(strong);
            paragraph.appendChild(
                document.createTextNode(
                    value === undefined || value === null || value === ""
                        ? "Not provided"
                        : String(value)
                )
            );

            detailsElement.appendChild(paragraph);
        });

        const certificateStatus = String(
            hospital.certificate_verification_status || "PENDING"
        ).toUpperCase();

        const hasCertificate = Boolean(
            hospital.certificate_original_name ||
            hospital.license_certificate
        );

        if (hasCertificate) {
            certificateName.textContent =
                `File: ${hospital.certificate_original_name || "Uploaded certificate"}`;

            certificateViewer.src =
                `${API}/admin/hospitals/${hospitalId}/certificate`;
        } else {
            certificateName.textContent =
                "No certificate uploaded for this hospital.";

            certificateViewer.src = "about:blank";
        }

        if (verifyButton) {
            verifyButton.disabled =
                !hasCertificate || certificateStatus === "VERIFIED";
        }

        if (rejectButton) {
            rejectButton.disabled =
                !hasCertificate || certificateStatus === "REJECTED";
        }

    } catch (error) {
        console.error("View hospital error:", error);

        detailsElement.textContent =
            error.message || "Unable to load hospital details.";

        certificateName.textContent =
            "Certificate could not be loaded.";

        certificateViewer.src = "about:blank";
        if (hospitalPhotoPreview) hospitalPhotoPreview.style.display = "none";
        if (hospitalPhotoMessage) hospitalPhotoMessage.textContent = "Unable to load hospital photo.";

        if (messageElement) {
            messageElement.textContent =
                error.message || "Unable to load hospital details.";
        }
    }
}


// Close hospital details modal
function closeHospitalDetails() {
    const modal = document.getElementById("hospitalDetailsModal");
    const viewer = document.getElementById("certificateViewer");

    if (modal) {
        modal.style.display = "none";
    }

    if (viewer) {
        viewer.src = "about:blank";
    }

    currentHospitalDetailsId = null;
}


// Verify a hospital certificate
async function verifyHospitalCertificate(id) {
    const hospitalId = Number(id);

    if (!Number.isInteger(hospitalId) || hospitalId <= 0) {
        showMessage("Invalid hospital ID.", "error");
        return false;
    }

    if (!confirm("Are you sure you want to verify this hospital certificate?")) {
        return false;
    }

    try {
        const response = await fetch(
            `${API}/admin/hospitals/${hospitalId}/certificate/verify`,
            {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json"
                }
            }
        );

        const data = await readResponse(response);

        if (!response.ok) {
            throw new Error(
                getErrorMessage(data, "Certificate verification failed.")
            );
        }

        showMessage(
            data.message || "Hospital certificate verified successfully.",
            "success"
        );

        await loadHospitals();
        return true;

    } catch (error) {
        console.error("Certificate verification error:", error);

        showMessage(
            error.message || "Unable to verify certificate.",
            "error"
        );

        return false;
    }
}


// Reject a hospital certificate
async function rejectHospitalCertificate(id) {
    const hospitalId = Number(id);

    if (!Number.isInteger(hospitalId) || hospitalId <= 0) {
        showMessage("Invalid hospital ID.", "error");
        return false;
    }

    const reason = prompt("Enter the reason for rejecting this certificate:");

    if (reason === null) {
        return false;
    }

    if (!reason.trim()) {
        showMessage("Please enter a rejection reason.", "error");
        return false;
    }

    if (!confirm("Are you sure you want to reject this certificate?")) {
        return false;
    }

    try {
        const response = await fetch(
            `${API}/admin/hospitals/${hospitalId}/certificate/reject`,
            {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    reason: reason.trim()
                })
            }
        );

        const data = await readResponse(response);

        if (!response.ok) {
            throw new Error(
                getErrorMessage(data, "Certificate rejection failed.")
            );
        }

        showMessage(
            data.message || "Hospital certificate rejected successfully.",
            "success"
        );

        await loadHospitals();
        return true;

    } catch (error) {
        console.error("Certificate rejection error:", error);

        showMessage(
            error.message || "Unable to reject certificate.",
            "error"
        );

        return false;
    }
}


// Verify button inside the details modal
async function verifyHospitalCertificateFromModal() {
    const id = currentHospitalDetailsId;

    if (!id) {
        showMessage("Please open a hospital first.", "error");
        return;
    }

    const success = await verifyHospitalCertificate(id);

    if (success && currentHospitalDetailsId === id) {
        await viewHospital(id);
    }
}


// Reject button inside the details modal
async function rejectHospitalCertificateFromModal() {
    const id = currentHospitalDetailsId;

    if (!id) {
        showMessage("Please open a hospital first.", "error");
        return;
    }

    const success = await rejectHospitalCertificate(id);

    if (success && currentHospitalDetailsId === id) {
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
// HOSPITAL ACTION - APPROVE / REJECT / PUBLISH / DELETE
// =====================================================

async function hospitalAction(id, action, reason = "") {
    try {
        let method = "PUT";
        let url = `${API}/admin/hospitals/${id}`;

        if (action === "delete") {
            method = "DELETE";
        } else if (action === "approve") {
            url = `${API}/admin/hospitals/${id}/approve`;
        } else if (action === "reject") {
            url = `${API}/admin/hospitals/${id}/reject`;
        } else if (action === "publish") {
            url = `${API}/admin/hospitals/${id}/publish`;
        } else if (action === "unpublish") {
            url = `${API}/admin/hospitals/${id}/unpublish`;
        } else {
            throw new Error("Unknown hospital action.");
        }

        const options = {
            method: method,
            headers: {
                "Content-Type": "application/json"
            }
        };

        // Send a JSON body for approval and other actions.
        // Rejection includes the reason.
        if (action === "reject") {
            options.body = JSON.stringify({
                reason: reason
            });
        } else if (action === "approve") {
            options.body = JSON.stringify({});
        }

        console.log("Hospital action:", action);
        console.log("Request URL:", url);

        const response = await fetch(url, options);
        const data = await readResponse(response);

        console.log("Hospital action response:", data);

        if (!response.ok) {
            throw new Error(
                getErrorMessage(data, `HTTP ${response.status}`)
            );
        }

        showMessage(
            data.message || `Hospital ${action} completed successfully.`,
            "success"
        );

        await loadHospitals();

    } catch (error) {
        console.error("Hospital action error:", error);

        showMessage(
            error.message || "Unable to complete hospital action.",
            "error"
        );
    }
}



// =====================================================
// LOAD TOKENS
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
                `${API}/tokens`
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

        /*
         * Your current backend stores payment
         * information inside the Token records.
         *
         * Therefore we load /tokens and display
         * records that contain payment information.
         */

        const response =
            await fetch(
                `${API}/tokens`
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
            .map(function (item) {

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

            })
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


 // =====================================================
 // EXPORT FUNCTIONS
 // =====================================================

window.adminLogin = adminLogin;
window.handleGoogleLogin = handleGoogleLogin;
window.adminLogout = adminLogout;

window.openHospitals = openHospitals;
window.openPayments = openPayments;
window.openTokens = openTokens;
window.goDashboard = goDashboard;

window.loadDashboard = loadDashboard;
window.loadHospitals = loadHospitals;
window.loadTokens = loadTokens;
window.loadPayments = loadPayments;

window.viewHospital = viewHospital;
window.closeHospitalDetails = closeHospitalDetails;

window.verifyHospitalCertificate = verifyHospitalCertificate;
window.rejectHospitalCertificate = rejectHospitalCertificate;

window.verifyHospitalCertificateFromModal =
    verifyHospitalCertificateFromModal;

window.rejectHospitalCertificateFromModal =
    rejectHospitalCertificateFromModal;

window.approveHospital = approveHospital;
window.rejectHospital = rejectHospital;
window.publishHospital = publishHospital;
window.unpublishHospital = unpublishHospital;
window.deleteHospital = deleteHospital;
window.hospitalAction = hospitalAction;

window.showMessage = showMessage;