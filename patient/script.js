/* =========================================================
   CarePath - Patient Dashboard
   ========================================================= */

const API = "https://carepath-3q9q.onrender.com";
const FRONTEND = "https://carepath-patient-mx5v.vercel.app";

const PLATFORM_FEE = 10;


// =========================================================
// GLOBAL DATA
// =========================================================

let hospitals = [];

let selectedHospital = null;

let selectedDoctor = null;

let paymentInProgress = false;


// =========================================================
// SAFE RESPONSE READER
// =========================================================

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
// =========================================================
// GET READABLE ERROR MESSAGE
// =========================================================

function getErrorMessage(data, fallback) {

    if (!data) {
        return fallback;
    }

    if (typeof data.detail === "string") {
        return data.detail;
    }

    if (data.detail && typeof data.detail === "object") {

        if (data.detail.message) {
            return data.detail.message;
        }

        if (data.detail.error) {
            return data.detail.error;
        }

        return JSON.stringify(data.detail);
    }

    if (typeof data.message === "string") {
        return data.message;
    }

    return fallback;
}


// =========================================================
// PAGE LOAD
// =========================================================



document.addEventListener("DOMContentLoaded", async function () {
    console.log("CarePath patient dashboard loaded.");

    loadPatientName();
    setupEvents();
    loadHospitals();

    const params = new URLSearchParams(window.location.search);
    const cashfreeOrderId = params.get("cashfree_order_id");

    if (!cashfreeOrderId) return;

    // Prevent duplicate verification if the page is refreshed.
    if (localStorage.getItem("verifiedCashfreeOrderId") === cashfreeOrderId) {
        return;
    }

    const hospitalName = localStorage.getItem("selectedHospitalName");
    const department = localStorage.getItem("selectedDepartment");
    const doctorName = localStorage.getItem("selectedDoctorName");
    const patientName = localStorage.getItem("patientName");

    if (!hospitalName || !department || !doctorName || !patientName) {
        console.error("Saved booking details are missing.");
        showMessage(
            "Booking details are missing. Please contact CarePath support before retrying.",
            "error"
        );
        return;
    }

    localStorage.setItem("cashfreeOrderId", cashfreeOrderId);

        try {
        localStorage.removeItem("tokenNumber");

        await createTokenAfterPayment(
            cashfreeOrderId,
            hospitalName,
            department,
            doctorName,
            patientName
        );

        if (localStorage.getItem("tokenNumber")) {
            localStorage.setItem("verifiedCashfreeOrderId", cashfreeOrderId);

            window.history.replaceState(
                {},
                document.title,
                window.location.pathname
            );
        } else {
            throw new Error("Token was not created after payment verification.");
        }
    } catch (error) {
        console.error("Cashfree return handling failed:", error);
        showMessage(
            error.message || "Payment verification failed. Please contact CarePath support.",
            "error"
        );
    }
});

// =========================================================
// LOAD PATIENT NAME
// =========================================================

function loadPatientName() {

    const patientName =
        localStorage.getItem("patientName");

    const element =
        document.getElementById("patientName");


    if (element) {

        element.textContent =
            patientName || "Patient";

    }

}


// =========================================================
// LOAD HOSPITALS
// =========================================================

async function loadHospitals() {

    const hospitalSelect =
        document.getElementById("hospital");


    if (!hospitalSelect) {

        console.error(
            "Hospital select not found."
        );

        return;

    }


    hospitalSelect.disabled = true;


    hospitalSelect.innerHTML = `
        <option value="">
            Loading hospitals...
        </option>
    `;


    try {

        const response =
            await fetch(
                `${API}/hospitals`
            );


        const data =
            await readResponse(
                response
            );


        console.log(
            "Hospitals response:",
            data
        );


       if (!response.ok) {

    throw new Error(
        getErrorMessage(
            data,
            "Unable to load hospitals."
        )
    );

}


        hospitals =
            Array.isArray(data)
                ? data
                : data.hospitals || [];


        hospitalSelect.innerHTML = `
            <option value="">
                Select Hospital
            </option>
        `;


        if (hospitals.length === 0) {

            hospitalSelect.innerHTML = `
                <option value="">
                    No hospitals available
                </option>
            `;

            updateFeeDisplay();

            updatePaymentButton();

            return;

        }


        hospitals.forEach(
            function (hospital) {

                const option =
                    document.createElement(
                        "option"
                    );


                option.value =
                    hospital.id;


                option.textContent =
                    hospital.city
                        ? `${hospital.name} - ${hospital.city}`
                        : hospital.name;


                hospitalSelect.appendChild(
                    option
                );

            }
        );


        hospitalSelect.disabled = false;


    } catch (error) {

        console.error(
            "Hospital loading error:",
            error
        );


        hospitalSelect.innerHTML = `
            <option value="">
                Failed to load hospitals
            </option>
        `;


        showMessage(
            error.message ||
            "Unable to load hospitals.",
            "error"
        );

    }

}


// =========================================================
// HOSPITAL SELECTED
// =========================================================

async function hospitalSelected() {

    const hospitalSelect =
        document.getElementById("hospital");


    if (!hospitalSelect) {
        return;
    }


    const hospitalId =
        hospitalSelect.value;


    selectedHospital = null;

    selectedDoctor = null;


    resetDepartment();

    resetDoctor();


    if (!hospitalId) {

        localStorage.removeItem(
            "selectedHospitalTokenFee"
        );

        updateFeeDisplay();

        updatePaymentButton();

        return;

    }


    const hospital =
        hospitals.find(
            function (item) {

                return String(item.id) ===
                    String(hospitalId);

            }
        );


    if (!hospital) {

        showMessage(
            "Hospital information not found.",
            "error"
        );

        return;

    }


    selectedHospital =
        hospital;


    console.log(
        "Selected hospital:",
        selectedHospital
    );


    /*
        Store only for display/reference.
        Backend remains the source of truth
        for payment amount.
    */

    localStorage.setItem(
        "selectedHospitalId",
        String(hospital.id)
    );


    localStorage.setItem(
        "selectedHospitalName",
        hospital.name || ""
    );


    localStorage.setItem(
        "selectedHospitalTokenFee",
        String(
            Number(hospital.token_fee || 0)
        )
    );


    updateFeeDisplay();

    updatePaymentButton();


    await loadDepartments(
        hospitalId
    );

}


// =========================================================
// RESET DEPARTMENT
// =========================================================

function resetDepartment() {

    const departmentSelect =
        document.getElementById(
            "department"
        );


    if (!departmentSelect) {
        return;
    }


    departmentSelect.innerHTML = `
        <option value="">
            Select Department
        </option>
    `;


    departmentSelect.disabled = true;

}


// =========================================================
// LOAD DEPARTMENTS
// =========================================================

async function loadDepartments(
    hospitalId
) {

    const departmentSelect =
        document.getElementById(
            "department"
        );


    if (!departmentSelect) {
        return;
    }


    departmentSelect.disabled = true;


    departmentSelect.innerHTML = `
        <option value="">
            Loading departments...
        </option>
    `;


    try {

        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}/departments`
            );


        const data =
            await readResponse(
                response
            );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                data,
                "Unable to load departments."
                )
            );

        }


        const departments =
            Array.isArray(data)
                ? data
                : data.departments || [];


        departmentSelect.innerHTML = `
            <option value="">
                Select Department
            </option>
        `;


        if (departments.length === 0) {

            departmentSelect.innerHTML = `
                <option value="">
                    No departments available
                </option>
            `;

            return;

        }


        departments.forEach(
            function (department) {

                let departmentName = "";


                if (
                    typeof department ===
                    "string"
                ) {

                    departmentName =
                        department;

                } else {

                    departmentName =
                        department.name ||
                        department.department ||
                        "";

                }


                if (!departmentName) {
                    return;
                }


                const option =
                    document.createElement(
                        "option"
                    );


                option.value =
                    departmentName;


                option.textContent =
                    departmentName;


                departmentSelect.appendChild(
                    option
                );

            }
        );


        if (
            departmentSelect.options.length > 1
        ) {

            departmentSelect.disabled =
                false;

        }


    } catch (error) {

        console.error(
            "Department loading error:",
            error
        );


        departmentSelect.innerHTML = `
            <option value="">
                Failed to load departments
            </option>
        `;


        showMessage(
            error.message ||
            "Unable to load departments.",
            "error"
        );

    }

}


// =========================================================
// DEPARTMENT SELECTED
// =========================================================

async function departmentSelected() {

    const hospitalSelect =
        document.getElementById(
            "hospital"
        );

    const departmentSelect =
        document.getElementById(
            "department"
        );


    if (
        !hospitalSelect ||
        !departmentSelect
    ) {
        return;
    }


    const hospitalId =
        hospitalSelect.value;


    const department =
        departmentSelect.value;


    resetDoctor();


    updateFeeDisplay();

    updatePaymentButton();


    if (
        !hospitalId ||
        !department
    ) {

        return;

    }


    await loadDoctors(
        hospitalId,
        department
    );

}


// =========================================================
// RESET DOCTOR
// =========================================================

function resetDoctor() {

    const doctorSelect =
        document.getElementById(
            "doctor"
        );


    if (!doctorSelect) {
        return;
    }


    doctorSelect.innerHTML = `
        <option value="">
            Select Doctor
        </option>
    `;


    doctorSelect.disabled = true;


    selectedDoctor = null;

}


// =========================================================
// LOAD DOCTORS
// =========================================================

async function loadDoctors(
    hospitalId,
    department
) {

    const doctorSelect =
        document.getElementById(
            "doctor"
        );


    if (!doctorSelect) {
        return;
    }


    doctorSelect.disabled = true;


    doctorSelect.innerHTML = `
        <option value="">
            Loading doctors...
        </option>
    `;


    try {

        /*
            We load doctors from the hospital.

            The backend may return:
            - only selected department doctors
            - all hospital doctors

            Therefore we filter again here.
        */

        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}/doctors`
            );


        const data =
            await readResponse(
                response
            );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                data,
                "Unable to load doctors."
                )
            );

        }


        let doctors =
            Array.isArray(data)
                ? data
                : data.doctors || [];


        doctors =
            doctors.filter(
                function (doctor) {

                    return String(
                        doctor.department || ""
                    ).trim().toLowerCase() ===
                    String(
                        department
                    ).trim().toLowerCase();

                }
            );


        doctorSelect.innerHTML = `
            <option value="">
                Select Doctor
            </option>
        `;


        if (doctors.length === 0) {

            doctorSelect.innerHTML = `
                <option value="">
                    No doctors available
                </option>
            `;

            return;

        }


        doctors.forEach(
            function (doctor) {

                const option =
                    document.createElement(
                        "option"
                    );


                option.value =
                    doctor.id;


                option.dataset.name =
                    doctor.name || "Doctor";


                option.textContent =
                    doctor.specialization
                        ? `${doctor.name} - ${doctor.specialization}`
                        : doctor.name;


                doctorSelect.appendChild(
                    option
                );

            }
        );


        doctorSelect.disabled =
            false;


    } catch (error) {

        console.error(
            "Doctor loading error:",
            error
        );


        doctorSelect.innerHTML = `
            <option value="">
                Failed to load doctors
            </option>
        `;


        showMessage(
            error.message ||
            "Unable to load doctors.",
            "error"
        );

    }

}


// =========================================================
// DOCTOR SELECTED
// =========================================================

function doctorSelected() {

    const doctorSelect =
        document.getElementById(
            "doctor"
        );


    if (!doctorSelect) {
        return;
    }


    const doctorId =
        doctorSelect.value;


    selectedDoctor = null;


    if (doctorId) {

        const option =
            doctorSelect.options[
                doctorSelect.selectedIndex
            ];


        if (option) {

            selectedDoctor = {

                id:
                    doctorId,

                name:
                    option.dataset.name ||
                    option.textContent.trim()

            };

        }

    }


    updateFeeDisplay();

    updatePaymentButton();

}


// =========================================================
// TOKEN FEE
// =========================================================

function getTokenFee() {

    if (
        selectedHospital &&
        selectedHospital.token_fee !==
        undefined &&
        selectedHospital.token_fee !==
        null
    ) {

        const fee =
            Number(
                selectedHospital.token_fee
            );


        if (
            Number.isFinite(fee) &&
            fee >= 0
        ) {

            return fee;

        }

    }


    return 0;

}


// =========================================================
// PLATFORM FEE
// =========================================================

function getPlatformFee() {

    return PLATFORM_FEE;

}


// =========================================================
// TOTAL
// =========================================================

function getTotalAmount() {

    return (
        getTokenFee() +
        getPlatformFee()
    );

}


// =========================================================
// UPDATE FEE DISPLAY
// =========================================================

function updateFeeDisplay() {

    const tokenFeeElement =
        document.getElementById(
            "tokenFee"
        );

    const platformFeeElement =
        document.getElementById(
            "platformFee"
        );

    const totalAmountElement =
        document.getElementById(
            "totalAmount"
        );


    const tokenFee =
        getTokenFee();


    const platformFee =
        getPlatformFee();


    const total =
        tokenFee +
        platformFee;


    if (tokenFeeElement) {

        tokenFeeElement.textContent =
            `₹${tokenFee}`;

    }


    if (platformFeeElement) {

        platformFeeElement.textContent =
            `₹${platformFee}`;

    }


    if (totalAmountElement) {

        totalAmountElement.textContent =
            `₹${total}`;

    }

}


// =========================================================
// PAYMENT BUTTON
// =========================================================

function updatePaymentButton() {

    const button =
        document.getElementById(
            "continueBtn"
        );


    if (!button) {
        return;
    }


    updateFeeDisplay();


    const hospitalSelect =
        document.getElementById(
            "hospital"
        );

    const departmentSelect =
        document.getElementById(
            "department"
        );

    const doctorSelect =
        document.getElementById(
            "doctor"
        );


    const hospitalValue =
        hospitalSelect
            ? hospitalSelect.value
            : "";


    const departmentValue =
        departmentSelect
            ? departmentSelect.value
            : "";


    const doctorValue =
        doctorSelect
            ? doctorSelect.value
            : "";


    if (
        hospitalValue &&
        departmentValue &&
        doctorValue &&
        !paymentInProgress
    ) {

        button.disabled = false;


        button.textContent =
            `💳 Continue & Pay ₹${getTotalAmount()}`;

        return;

    }


    button.disabled = true;


    if (paymentInProgress) {

        button.textContent =
            "Processing...";

    }

    else if (!hospitalValue) {

        button.textContent =
            "💳 Select Hospital";

    }

    else if (!departmentValue) {

        button.textContent =
            "💳 Select Department";

    }

    else if (!doctorValue) {

        button.textContent =
            "💳 Select Doctor";

    }

    else {

        button.textContent =
            "💳 Continue";

    }

}


// =========================================================
// CONTINUE & PAY
// =========================================================


async function continueAndGetToken() {
    if (paymentInProgress) return;

    const hospitalSelect = document.getElementById("hospital");
    const departmentSelect = document.getElementById("department");
    const doctorSelect = document.getElementById("doctor");

    if (!hospitalSelect || !departmentSelect || !doctorSelect) {
        showMessage("Booking form is not available.", "error");
        return;
    }

    const hospitalId = hospitalSelect.value;
    const department = departmentSelect.value;
    const doctorId = doctorSelect.value;
    const patientName = localStorage.getItem("patientName");

    if (!patientName) {
        showMessage("Please login first.", "error");
        return;
    }

    if (!hospitalId || !department || !doctorId) {
        showMessage("Please select a hospital, department, and doctor.", "error");
        return;
    }

    if (!selectedHospital || !selectedDoctor) {
        showMessage("Hospital or doctor information is unavailable.", "error");
        return;
    }

    const hospitalName = selectedHospital.name;
    const doctorName = selectedDoctor.name;

    if (!hospitalName || !doctorName) {
        showMessage("Hospital or doctor name is missing.", "error");
        return;
    }

    if (typeof Cashfree === "undefined") {
        showMessage("Cashfree SDK is not loaded. Please refresh the page.", "error");
        return;
    }

    clearOldBookingData();

    paymentInProgress = true;
    updatePaymentButton();

    try {
        const response = await fetch(`${API}/api/create-order`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${localStorage.getItem("patientToken") || ""}`
            },
            body: JSON.stringify({
    patient_name: patientName,
    hospital: hospitalName,
    department: department,
    doctor: doctorName,
    appointment_date:
        document.getElementById("appointmentDate")?.value || null
})
        });

        const order = await readResponse(response);

        if (!response.ok) {
            throw new Error(
                getErrorMessage(order, "Unable to create Cashfree order.")
            );
        }

        if (!order.order_id || !order.payment_session_id) {
            throw new Error("Cashfree did not return a valid payment session.");
        }

        localStorage.setItem("selectedHospitalId", String(hospitalId));
        localStorage.setItem("selectedHospitalName", hospitalName);
        localStorage.setItem("selectedDoctorId", String(doctorId));
        localStorage.setItem("selectedDoctorName", doctorName);
        localStorage.setItem("selectedDepartment", department);
        localStorage.setItem("selectedTokenFee", String(order.token_fee));
        localStorage.setItem("selectedPlatformFee", String(order.platform_fee));
        localStorage.setItem("selectedTotalAmount", String(order.total_amount));

        // Keep the order ID for the verification step after checkout.
        localStorage.setItem("cashfreeOrderId", order.order_id);

        const cashfree = Cashfree({
            mode: "sandbox"
        });

        const result = await cashfree.checkout({
            paymentSessionId: order.payment_session_id,
            redirectTarget: "_self"
        });

        // If checkout reports an immediate error, allow another attempt.
        if (result && result.error) {
            throw new Error(
                result.error.message || "Unable to open Cashfree checkout."
            );
        }

        } catch (error) {
        console.error("Cashfree verification error:", error);

        showMessage(
            error.message || "Unable to verify payment or create token.",
            "error"
        );

        resetPaymentButton();

         }
}


// Compatibility name retained temporarily; this function now opens Cashfree.
function openRazorpay(
    order,
    hospitalName,
    department,
    doctorName,
    patientName
) {
    if (typeof Cashfree === "undefined") {
        showMessage("Cashfree SDK is not loaded.", "error");
        resetPaymentButton();
        return;
    }

    if (!order || !order.payment_session_id) {
        showMessage("Cashfree payment session is missing.", "error");
        resetPaymentButton();
        return;
    }

    try {
        const cashfree = Cashfree({
            mode: "sandbox"
        });

        cashfree.checkout({
            paymentSessionId: order.payment_session_id,
            redirectTarget: "_self"
        }).catch(function (error) {
            console.error("Cashfree checkout error:", error);
            showMessage("Unable to open Cashfree checkout.", "error");
            resetPaymentButton();
        });
    } catch (error) {
        console.error("Cashfree initialization error:", error);
        showMessage("Unable to initialize Cashfree checkout.", "error");
        resetPaymentButton();
    }
}
// =========================================================
// CREATE TOKEN AFTER PAYMENT
// =========================================================


async function createTokenAfterPayment(
    cashfreeOrderId,
    hospitalName,
    department,
    doctorName,
    patientName
) {
    const button = document.getElementById("continueBtn");

    if (!button) return;

    button.disabled = true;
    button.textContent = "Verifying Cashfree Payment...";

    try {
        const response = await fetch(`${API}/payments/verify`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${localStorage.getItem("patientToken") || ""}`
            },
            body: JSON.stringify({
                patient_name: patientName,
                hospital: hospitalName,
                department: department,
                doctor: doctorName,
                cashfree_order_id: cashfreeOrderId
            })
        });

        const data = await readResponse(response);

        if (!response.ok) {
            throw new Error(
                getErrorMessage(data, "Cashfree payment verification failed.")
            );
        }

        const token = data.token || data;

        if (!token || token.token_number === undefined) {
            throw new Error("The server did not return token information.");
        }

        const paymentId =
            token.cashfree_payment_id ||
            data.cashfree_payment_id ||
            "";

        if (token.id) {
            localStorage.setItem("tokenId", String(token.id));
        }

        localStorage.setItem("tokenNumber", String(token.token_number));
        localStorage.setItem("token", String(token.token_number));
        localStorage.setItem("tokenHospital", token.hospital || hospitalName);
        localStorage.setItem("hospital", token.hospital || hospitalName);
        localStorage.setItem("tokenDepartment", token.department || department);
        localStorage.setItem("department", token.department || department);
        localStorage.setItem("tokenDoctor", token.doctor || doctorName);
        localStorage.setItem("doctor", token.doctor || doctorName);
        localStorage.setItem("tokenStatus", token.status || "waiting");
        localStorage.setItem("tokenFee", String(token.token_fee ?? 0));
        localStorage.setItem("platformFee", String(token.platform_fee ?? 10));
        llocalStorage.setItem(
    "totalAmount",
    String(token.total_amount ?? data.total_amount ?? 0)
);
        localStorage.setItem("paymentStatus", "Paid");
        localStorage.setItem("cashfreeOrderId", cashfreeOrderId);

        if (paymentId) {
            localStorage.setItem("paymentId", String(paymentId));
        }

        showMessage(
            `Payment verified! Your token number is ${token.token_number}.`,
            "success"
        );

        button.textContent = "Token Created ✓";

        setTimeout(() => {
            window.location.href = "token.html";
        }, 1000);

    } catch (error) {
        console.error("Cashfree verification error:", error);
        showMessage(
            error.message || "Unable to verify payment or create token.",
            "error"
        );
        resetPaymentButton();
    }
}
// =========================================================
// CLEAR OLD BOOKING DATA
// =========================================================

function clearOldBookingData() {

    const keys = [

        "tokenId",

        "tokenNumber",

        "token",

        "tokenHospital",

        "tokenDepartment",

        "tokenDoctor",

        "tokenStatus",

        "tokenFee",

        "platformFee",

        "totalAmount",

        "hospital",

        "department",

        "doctor",

        "paymentStatus",

        "currentToken",

        "peopleAhead"

    ];


    keys.forEach(
        function (key) {

            localStorage.removeItem(
                key
            );

        }
    );

}


// =========================================================
// RESET PAYMENT BUTTON
// =========================================================

function resetPaymentButton() {

    paymentInProgress =
        false;


    updatePaymentButton();

}


// =========================================================
// MESSAGE
// =========================================================

function showMessage(
    message,
    type = "success"
) {

    const element =
        document.getElementById(
            "message"
        );


    if (!element) {

        console.log(
            message
        );

        return;

    }


    element.textContent =
        message;


    element.className =
        `message ${type}`;

}


// =========================================================
// LOGOUT
// =========================================================

function logout() {

    const keys = [

        "patientId",

        "patientName",

        "patientEmail",

        "patientPhone",

        "patientPicture",

        "googleId",

        "patientAccessToken",

        "selectedHospitalId",

        "selectedHospitalName",

        "selectedDoctorId",

        "selectedDoctorName",

        "selectedDepartment",

        "selectedTokenFee",

        "selectedPlatformFee",

        "selectedTotalAmount",

        "selectedHospitalTokenFee",

        "tokenId",

        "tokenNumber",

        "token",

        "tokenHospital",

        "tokenDepartment",

        "tokenDoctor",

        "tokenStatus",

        "tokenFee",

        "platformFee",

        "totalAmount",

        "hospital",

        "department",

        "doctor",

        "paymentStatus",

        "currentToken",

        "peopleAhead"

    ];


    keys.forEach(
        function (key) {

            localStorage.removeItem(
                key
            );

        }
    );


    window.location.href =
        "index.html";

}