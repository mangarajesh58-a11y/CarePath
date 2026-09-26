// =====================================================
// HOSPITALCARE ADMIN JAVASCRIPT
// =====================================================

const API = "http://127.0.0.1:8000";


// =====================================================
// PAGE LOAD
// =====================================================

document.addEventListener("DOMContentLoaded", function () {

    console.log("HospitalCare Admin started");

    const path = window.location.pathname.toLowerCase();

    if (path.includes("hospital.html")) {

        loadHospitals();

    }

    if (path.includes("dashboard.html")) {

        loadDashboard();

    }

});


// =====================================================
// ADMIN LOGOUT
// =====================================================

function adminLogout() {

    localStorage.removeItem("adminLoggedIn");

    localStorage.removeItem("adminEmail");

    window.location.href = "login.html";

}


// =====================================================
// OPEN HOSPITALS
// =====================================================

function openHospitals() {

    window.location.href = "hospital.html";

}


// =====================================================
// OPEN PAYMENTS
// =====================================================

function openPayments() {

    window.location.href = "payments.html";

}


// =====================================================
// OPEN TOKENS
// =====================================================

function openTokens() {

    window.location.href = "tokens.html";

}


// =====================================================
// BACK TO DASHBOARD
// =====================================================

function goDashboard() {

    window.location.href = "dashboard.html";

}


// =====================================================
// LOAD ADMIN DASHBOARD
// =====================================================

async function loadDashboard() {

    try {

        await loadDashboardHospitals();

        await loadRevenue();

    } catch (error) {

        console.error(
            "Dashboard loading error:",
            error
        );

    }

}


// =====================================================
// LOAD HOSPITAL COUNT
// =====================================================

async function loadDashboardHospitals() {

    try {

        const response = await fetch(
            `${API}/admin/hospitals`
        );

        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }

        const hospitals =
            await response.json();

        const hospitalCount =
            document.getElementById(
                "hospitalCount"
            );

        if (hospitalCount) {

            hospitalCount.textContent =
                hospitals.length;

        }

    } catch (error) {

        console.error(
            "Hospital count error:",
            error
        );

    }

}


// =====================================================
// LOAD REVENUE
// =====================================================

async function loadRevenue() {

    try {

        const response = await fetch(
            `${API}/admin/revenue`
        );

        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }

        const data =
            await response.json();

        const platformRevenue =
            document.getElementById(
                "platformRevenue"
            );

        const platformRevenue2 =
            document.getElementById(
                "platformRevenue2"
            );

        const totalCollected =
            document.getElementById(
                "totalCollected"
            );

        const tokenRevenue =
            document.getElementById(
                "tokenRevenue"
            );

        const tokenCount =
            document.getElementById(
                "tokenCount"
            );

        if (platformRevenue) {

            platformRevenue.textContent =
                `₹${data.total_revenue || 0}`;

        }

        if (platformRevenue2) {

            platformRevenue2.textContent =
                `₹${data.total_revenue || 0}`;

        }

        if (tokenRevenue) {

            tokenRevenue.textContent =
                `₹${data.total_revenue || 0}`;

        }

        if (totalCollected) {

            totalCollected.textContent =
                `₹${data.total_revenue || 0}`;

        }

        if (tokenCount) {

            tokenCount.textContent =
                data.total_tokens || 0;

        }

    } catch (error) {

        console.error(
            "Revenue loading error:",
            error
        );

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
                colspan="8"
                class="loading"
            >
                Loading hospitals...
            </td>

        </tr>

    `;


    try {

        const response = await fetch(
            `${API}/admin/hospitals`
        );


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const hospitals =
            await response.json();


        if (
            !hospitals ||
            hospitals.length === 0
        ) {

            tableBody.innerHTML = `

                <tr>

                    <td
                        colspan="8"
                        class="loading"
                    >
                        No hospitals registered yet.
                    </td>

                </tr>

            `;

            return;

        }


        tableBody.innerHTML = "";


        hospitals.forEach(function (hospital) {

            const row =
                document.createElement("tr");


            const status =
                hospital.approval_status ||
                "PENDING";


            const published =
                hospital.is_published === true;


            let statusClass =
                "pending";


            if (status === "APPROVED") {

                statusClass = "approved";

            }


            if (status === "REJECTED") {

                statusClass = "rejected";

            }


            row.innerHTML = `

                <td>
                    ${hospital.id}
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
                        hospital.license_id || "Not provided"
                    )}
                </td>

                <td>

                    <span
                        class="status ${statusClass}"
                    >
                        ${status}
                    </span>

                </td>

                <td>

                    <span
                        class="status ${
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
                    ${hospital.doctor_count || 0}
                </td>

                <td>

                    <div class="action-buttons">

                        <button
                            class="view-btn"
                            onclick="viewHospital(
                                ${hospital.id}
                            )"
                        >
                            👁 View
                        </button>


                        ${
                            status !== "APPROVED"
                                ? `
                                <button
                                    class="approve-btn"
                                    onclick="approveHospital(
                                        ${hospital.id}
                                    )"
                                >
                                    ✅ Approve
                                </button>
                                `
                                : ""
                        }


                        ${
                            status !== "REJECTED"
                                ? `
                                <button
                                    class="reject-btn"
                                    onclick="rejectHospital(
                                        ${hospital.id}
                                    )"
                                >
                                    ❌ Reject
                                </button>
                                `
                                : ""
                        }


                        ${
                            status === "APPROVED" &&
                            !published
                                ? `
                                <button
                                    class="publish-btn"
                                    onclick="publishHospital(
                                        ${hospital.id}
                                    )"
                                >
                                    📢 Publish
                                </button>
                                `
                                : ""
                        }


                        ${
                            published
                                ? `
                                <button
                                    class="unpublish-btn"
                                    onclick="unpublishHospital(
                                        ${hospital.id}
                                    )"
                                >
                                    🚫 Unpublish
                                </button>
                                `
                                : ""
                        }


                        <button
                            class="delete-btn"
                            onclick="deleteHospital(
                                ${hospital.id}
                            )"
                        >
                            🗑 Delete
                        </button>

                    </div>

                </td>

            `;


            tableBody.appendChild(row);

        });


    } catch (error) {

        console.error(
            "Hospital loading error:",
            error
        );


        tableBody.innerHTML = `

            <tr>

                <td
                    colspan="8"
                    class="loading"
                >

                    ❌ Cannot connect to FastAPI.

                    <br><br>

                    Make sure the backend is running.

                </td>

            </tr>

        `;

    }

}


// =====================================================
// VIEW HOSPITAL
// =====================================================

async function viewHospital(id) {

    try {

        const response = await fetch(
            `${API}/admin/hospitals/${id}`
        );


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const hospital =
            await response.json();


        alert(

            "Hospital Details\n\n" +

            "Hospital: " +
            (hospital.name || "-") +

            "\n\nLicense ID: " +
            (hospital.license_id || "-") +

            "\n\nCity: " +
            (hospital.city || "-") +

            "\n\nAddress: " +
            (hospital.address || "-") +

            "\n\nDescription: " +
            (hospital.description || "-") +

            "\n\nApproval Status: " +
            (hospital.approval_status || "-") +

            "\n\nPublished: " +
            (
                hospital.is_published
                    ? "Yes"
                    : "No"
            )

        );


    } catch (error) {

        console.error(
            "View hospital error:",
            error
        );

        showMessage(
            "Unable to load hospital details.",
            "error"
        );

    }

}


// =====================================================
// APPROVE HOSPITAL
// =====================================================

async function approveHospital(id) {

    const confirmed = confirm(
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

    const reason = prompt(
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
        reason
    );

}


// =====================================================
// PUBLISH HOSPITAL
// =====================================================

async function publishHospital(id) {

    const confirmed = confirm(
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

    const confirmed = confirm(
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

    const confirmed = confirm(

        "WARNING!\n\n" +

        "Deleting this hospital will remove it " +
        "from HospitalCare.\n\n" +

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
// =====================================================

async function hospitalAction(
    id,
    action,
    reason = ""
) {

    try {

        const response = await fetch(

            `${API}/admin/hospitals/${id}/${action}`,

            {

                method: "POST",

                headers: {

                    "Content-Type":
                        "application/json"

                },

                body: JSON.stringify({

                    reason: reason

                })

            }

        );


        const data =
            await response.json();


        if (!response.ok) {

            throw new Error(
                data.detail ||
                data.message ||
                "Action failed"
            );

        }


        showMessage(
            data.message ||
            "Action completed successfully.",
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
            "Unable to complete action.",
            "error"
        );

    }

}


// =====================================================
// SHOW MESSAGE
// =====================================================

function showMessage(
    message,
    type
) {

    const element =
        document.getElementById(
            "message"
        );


    if (!element) {

        return;

    }


    element.textContent =
        message;


    element.className =
        `message ${type}`;


    setTimeout(function () {

        element.textContent = "";

        element.className =
            "message";

    }, 4000);

}


// =====================================================
// HTML ESCAPE
// =====================================================

function escapeHtml(value) {

    const div =
        document.createElement("div");

    div.textContent =
        value;

    return div.innerHTML;

}