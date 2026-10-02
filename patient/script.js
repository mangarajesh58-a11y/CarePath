/* =========================================================
   CarePath - Patient Dashboard
   ========================================================= */

const API = "https://carepath-backend-fgb9.onrender.com";
const FRONTEND = "http://127.0.0.1:5500/patient";

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

document.addEventListener(
    "DOMContentLoaded",
    function () {

        console.log(
            "CarePath patient dashboard loaded."
        );

        loadPatientName();

        setupEvents();

        loadHospitals();

    }
);


// =========================================================
// SETUP EVENTS
// =========================================================

function setupEvents() {

    const hospitalSelect =
        document.getElementById("hospital");

    const departmentSelect =
        document.getElementById("department");

    const doctorSelect =
        document.getElementById("doctor");

    const continueBtn =
        document.getElementById("continueBtn");

    const logoutButton =
        document.getElementById("logoutButton");


    if (hospitalSelect) {

        hospitalSelect.addEventListener(
            "change",
            hospitalSelected
        );

    }


    if (departmentSelect) {

        departmentSelect.addEventListener(
            "change",
            departmentSelected
        );

    }


    if (doctorSelect) {

        doctorSelect.addEventListener(
            "change",
            doctorSelected
        );

    }


    if (continueBtn) {

        continueBtn.addEventListener(
            "click",
            continueAndGetToken
        );

    }


    if (logoutButton) {

        logoutButton.addEventListener(
            "click",
            logout
        );

    }


    updateFeeDisplay();

    updatePaymentButton();

}


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

    if (paymentInProgress) {
        return;
    }


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


    if (
        !hospitalSelect ||
        !departmentSelect ||
        !doctorSelect
    ) {

        showMessage(
            "Booking form is not available.",
            "error"
        );

        return;

    }


    const hospitalId =
        hospitalSelect.value;


    const department =
        departmentSelect.value;


    const doctorId =
        doctorSelect.value;


    const patientName =
        localStorage.getItem(
            "patientName"
        );


    // ---------------------------------------------------------
    // VALIDATION
    // ---------------------------------------------------------

    if (!patientName) {

        showMessage(
            "Please login first.",
            "error"
        );

        return;

    }


    if (!hospitalId) {

        showMessage(
            "Please select a hospital.",
            "error"
        );

        return;

    }


    if (!department) {

        showMessage(
            "Please select a department.",
            "error"
        );

        return;

    }


    if (!doctorId) {

        showMessage(
            "Please select a doctor.",
            "error"
        );

        return;

    }


    if (!selectedHospital) {

        showMessage(
            "Hospital information is unavailable.",
            "error"
        );

        return;

    }


    if (!selectedDoctor) {

        showMessage(
            "Doctor information is unavailable.",
            "error"
        );

        return;

    }


    const hospitalName =
        selectedHospital.name;


    const doctorName =
        selectedDoctor.name;


    if (!hospitalName) {

        showMessage(
            "Hospital name is missing.",
            "error"
        );

        return;

    }


    if (!doctorName) {

        showMessage(
            "Doctor name is missing.",
            "error"
        );

        return;

    }


    // ---------------------------------------------------------
    // CLEAR OLD TOKEN
    // ---------------------------------------------------------

    clearOldBookingData();


    // ---------------------------------------------------------
    // LOCK BUTTON
    // ---------------------------------------------------------

    paymentInProgress = true;

    updatePaymentButton();


    try {

        /*
            IMPORTANT:

            Do NOT send token_fee from frontend.

            FastAPI must get the hospital's
            token_fee directly from MySQL.
        */

        const response =
            await fetch(
                `${API}/api/create-order`,
                {

                    method: "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                   body :
                        JSON.stringify({

                            patient_name:
                                patientName,

                            hospital:
                                hospitalName,

                            department:
                                department,

                            doctor:
                                doctorName

                        })

                }
            );


        const order =
            await readResponse(
                response
            );


        console.log(
            "Create order response:",
            order
        );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                order,
                "Unable to create payment order."
                )
            );

        }


        if (
            !order.order_id ||
            !order.key_id ||
            !order.amount
        ) {

            throw new Error(
                "Invalid payment order received from FastAPI."
            );

        }


        // -----------------------------------------------------
        // SAVE BOOKING INFORMATION
        // -----------------------------------------------------

        localStorage.setItem(
            "selectedHospitalId",
            String(hospitalId)
        );


        localStorage.setItem(
            "selectedHospitalName",
            hospitalName
        );


        localStorage.setItem(
            "selectedDoctorId",
            String(doctorId)
        );


        localStorage.setItem(
            "selectedDoctorName",
            doctorName
        );


        localStorage.setItem(
            "selectedDepartment",
            department
        );


        localStorage.setItem(
            "selectedTokenFee",
            String(
                order.token_fee ??
                getTokenFee()
            )
        );


        localStorage.setItem(
            "selectedPlatformFee",
            String(
                order.platform_fee ??
                getPlatformFee()
            )
        );


        localStorage.setItem(
            "selectedTotalAmount",
            String(
                order.total_amount ??
                Number(order.amount) / 100
            )
        );


        openRazorpay(
            order,
            hospitalName,
            department,
            doctorName,
            patientName
        );


    } catch (error) {

        console.error(
            "Payment creation error:",
            error
        );


        showMessage(
            error.message ||
            "Payment could not be started.",
            "error"
        );


        resetPaymentButton();

    }

}


// =========================================================
// OPEN RAZORPAY
// =========================================================

function openRazorpay(
    order,
    hospitalName,
    department,
    doctorName,
    patientName
) {

    if (
        typeof Razorpay ===
        "undefined"
    ) {

        showMessage(
            "Razorpay SDK is not loaded.",
            "error"
        );


        resetPaymentButton();

        return;

    }


    const tokenFee =
        Number(
            order.token_fee ??
            getTokenFee()
        );


    const platformFee =
        Number(
            order.platform_fee ??
            getPlatformFee()
        );


    const totalAmount =
        Number(
            order.total_amount ??
            Number(order.amount) / 100
        );


    /*
        Optional frontend consistency check.

        Backend remains the final authority.
    */

    if (
        tokenFee +
        platformFee !==
        totalAmount
    ) {

        console.warn(
            "Payment amount information is inconsistent.",
            {
                tokenFee,
                platformFee,
                totalAmount
            }
        );

    }


    const options = {

        key:
            order.key_id,

        amount:
            order.amount,

        currency:
            order.currency ||
            "INR",

        name:
            "CarePath",

        description:
            `Hospital Token ₹${tokenFee} + Platform Fee ₹${platformFee}`,

        order_id:
            order.order_id,


        prefill: {

            name:
                patientName,

            email:
                localStorage.getItem(
                    "patientEmail"
                ) || "",

            contact:
                localStorage.getItem(
                    "patientPhone"
                ) || ""

        },


        theme: {

            color:
                "#1769aa"

        },


        handler:
            async function (
                paymentResponse
            ) {

                console.log(
                    "Razorpay payment response:",
                    paymentResponse
                );


                if (
                    !paymentResponse ||
                    !paymentResponse.razorpay_order_id ||
                    !paymentResponse.razorpay_payment_id ||
                    !paymentResponse.razorpay_signature
                ) {

                    showMessage(
                        "Invalid payment response received.",
                        "error"
                    );


                    resetPaymentButton();

                    return;

                }


                await createTokenAfterPayment(

                    paymentResponse,

                    hospitalName,

                    department,

                    doctorName,

                    patientName

                );

            },


        modal: {

            ondismiss:
                function () {

                    console.log(
                        "Razorpay window closed."
                    );


                    resetPaymentButton();


                    showMessage(
                        "Payment window closed.",
                        "error"
                    );

                }

        }

    };


    try {

        const razorpay =
            new Razorpay(
                options
            );


        razorpay.on(
            "payment.failed",
            function (response) {

                console.error(
                    "Payment failed:",
                    response
                );


                const message =
                    response &&
                    response.error &&
                    response.error.description
                        ? response.error.description
                        : "Payment failed.";


                showMessage(
                    message,
                    "error"
                );


                resetPaymentButton();

            }
        );


        razorpay.open();


    } catch (error) {

        console.error(
            "Razorpay error:",
            error
        );


        showMessage(
            "Unable to open Razorpay.",
            "error"
        );


        resetPaymentButton();

    }

}


// =========================================================
// CREATE TOKEN AFTER PAYMENT
// =========================================================

async function createTokenAfterPayment(

    paymentResponse,

    hospitalName,

    department,

    doctorName,

    patientName

) {

    const button =
        document.getElementById(
            "continueBtn"
        );


    if (!button) {
        return;
    }


    button.disabled = true;

    button.textContent =
        "Creating Token...";


    try {

        const response =
            await fetch(
                `${API}/tokens`,
                {

                    method: "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    body:
                        JSON.stringify({

                            patient_name:
                                patientName,

                            hospital:
                                hospitalName,

                            department:
                                department,

                            doctor:
                                doctorName,

                            razorpay_order_id:
                                paymentResponse
                                    .razorpay_order_id,

                            razorpay_payment_id:
                                paymentResponse
                                    .razorpay_payment_id,

                            razorpay_signature:
                                paymentResponse
                                    .razorpay_signature

                        })

                }
            );


        const data =
            await readResponse(
                response
            );


        console.log(
            "Token response:",
            data
        );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                data,
                "Token creation failed."
                )
            );

        }


        const token =
            data.token ||
            data;


        if (
            !token ||
            token.token_number ===
            undefined
        ) {

            throw new Error(
                "FastAPI did not return token information."
            );

        }


        // =====================================================
        // SAVE TOKEN INFORMATION
        // =====================================================

        if (token.id) {

            localStorage.setItem(
                "tokenId",
                String(token.id)
            );

        }


        localStorage.setItem(
            "tokenNumber",
            String(
                token.token_number
            )
        );


        localStorage.setItem(
            "tokenHospital",
            token.hospital ||
            hospitalName
        );


        localStorage.setItem(
            "tokenDepartment",
            token.department ||
            department
        );


        localStorage.setItem(
            "tokenDoctor",
            token.doctor ||
            doctorName
        );


        localStorage.setItem(
            "tokenStatus",
            token.status ||
            "waiting"
        );


        localStorage.setItem(
            "tokenFee",
            String(
                token.token_fee ??
                getTokenFee()
            )
        );


        localStorage.setItem(
            "platformFee",
            String(
                token.platform_fee ??
                getPlatformFee()
            )
        );


        localStorage.setItem(
            "totalAmount",
            String(
                token.total_amount ??
                (
                    Number(
                        token.token_fee ??
                        getTokenFee()
                    ) +
                    Number(
                        token.platform_fee ??
                        getPlatformFee()
                    )
                )
            )
        );


        // Compatibility with older token.html

        localStorage.setItem(
            "token",
            String(
                token.token_number
            )
        );


        localStorage.setItem(
            "hospital",
            token.hospital ||
            hospitalName
        );


        localStorage.setItem(
            "department",
            token.department ||
            department
        );


        localStorage.setItem(
            "doctor",
            token.doctor ||
            doctorName
        );


        localStorage.setItem(
            "paymentStatus",
            "Paid"
        );


        localStorage.setItem(
            "tokenStatus",
            token.status ||
            "waiting"
        );


        // =====================================================
        // SUCCESS
        // =====================================================

        showMessage(
            `Payment successful! Your token number is ${token.token_number}.`,
            "success"
        );


        button.textContent =
            "Token Created ✓";


        setTimeout(
            function () {

                window.location.href =
                    "token.html";

            },
            1000
        );


    } catch (error) {

        console.error(
            "Token creation error:",
            error
        );


        showMessage(
            error.message ||
            "Unable to create token.",
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