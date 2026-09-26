/* =========================================================
   HospitalCare - Patient Dashboard
   ========================================================= */

const API = "http://127.0.0.1:8000";


// =========================================================
// PAGE LOAD
// =========================================================

document.addEventListener("DOMContentLoaded", function () {

    loadPatientName();

    loadHospitals();

    setupEvents();

});


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


    // Hospital selection

    if (hospitalSelect) {

        hospitalSelect.addEventListener(
            "change",
            hospitalSelected
        );

    }


    // Department selection

    if (departmentSelect) {

        departmentSelect.addEventListener(
            "change",
            departmentSelected
        );

    }


    // Doctor selection

    if (doctorSelect) {

        doctorSelect.addEventListener(
            "change",
            doctorSelected
        );

    }


    // Payment button

    if (continueBtn) {

        continueBtn.addEventListener(
            "click",
            continueAndGetToken
        );

    }


    // Logout

    if (logoutButton) {

        logoutButton.addEventListener(
            "click",
            logout
        );

    }

}


// =========================================================
// LOAD PATIENT NAME
// =========================================================

function loadPatientName() {

    const patientName =
        localStorage.getItem("patientName");

    const nameElement =
        document.getElementById("patientName");


    if (nameElement) {

        nameElement.textContent =
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


    hospitalSelect.innerHTML =
        `
        <option value="">
            Loading hospitals...
        </option>
        `;


    try {

        const response =
            await fetch(
                `${API}/hospitals`
            );


        const hospitals =
            await response.json();


        if (!response.ok) {

            throw new Error(
                hospitals.detail ||
                "Unable to load hospitals."
            );

        }


        hospitalSelect.innerHTML =
            `
            <option value="">
                Select Hospital
            </option>
            `;


        if (
            !Array.isArray(hospitals) ||
            hospitals.length === 0
        ) {

            hospitalSelect.innerHTML =
                `
                <option value="">
                    No hospitals available
                </option>
                `;

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


        hospitalSelect.disabled =
            false;

    }

    catch (error) {

        console.error(
            "Hospital loading error:",
            error
        );


        hospitalSelect.innerHTML =
            `
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
        document.getElementById(
            "hospital"
        );


    const hospitalId =
        hospitalSelect.value;


    // Reset department

    resetDepartment();


    // Reset doctor

    resetDoctor();


    // Disable payment

    disablePaymentButton();


    if (!hospitalId) {

        return;

    }


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


    departmentSelect.innerHTML =
        `
        <option value="">
            Select Department
        </option>
        `;


    departmentSelect.disabled =
        true;

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

        console.error(
            "Department select not found."
        );

        return;

    }


    departmentSelect.disabled =
        true;


    departmentSelect.innerHTML =
        `
        <option value="">
            Loading departments...
        </option>
        `;


    try {

        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}/departments`
            );


        const departments =
            await response.json();


        console.log(
            "Departments received:",
            departments
        );


        if (!response.ok) {

            throw new Error(
                departments.detail ||
                "Unable to load departments."
            );

        }


        departmentSelect.innerHTML =
            `
            <option value="">
                Select Department
            </option>
            `;


        if (
            !Array.isArray(departments) ||
            departments.length === 0
        ) {

            departmentSelect.innerHTML =
                `
                <option value="">
                    No departments available
                </option>
                `;

            return;

        }


        departments.forEach(
            function (department) {

                const option =
                    document.createElement(
                        "option"
                    );


                /*
                 * Backend returns:
                 *
                 * [
                 *   "Cardiology",
                 *   "Neurology",
                 *   "Dermatology"
                 * ]
                 *
                 */


                option.value =
                    department;


                option.textContent =
                    department;


                departmentSelect.appendChild(
                    option
                );

            }
        );


        departmentSelect.disabled =
            false;

    }

    catch (error) {

        console.error(
            "Department loading error:",
            error
        );


        departmentSelect.innerHTML =
            `
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


    const hospitalId =
        hospitalSelect.value;


    const department =
        departmentSelect.value;


    // Reset doctor

    resetDoctor();


    // Disable payment

    disablePaymentButton();


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


    doctorSelect.innerHTML =
        `
        <option value="">
            Select Doctor
        </option>
        `;


    doctorSelect.disabled =
        true;

}


// =========================================================
// LOAD DOCTORS BY DEPARTMENT
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

        console.error(
            "Doctor select not found."
        );

        return;

    }


    doctorSelect.disabled =
        true;


    doctorSelect.innerHTML =
        `
        <option value="">
            Loading doctors...
        </option>
        `;


    try {

        const url =
            `${API}/hospitals/${hospitalId}/doctors?department=${encodeURIComponent(department)}`;


        console.log(
            "Loading doctors:",
            url
        );


        const response =
            await fetch(url);


        const doctors =
            await response.json();


        console.log(
            "Doctors received:",
            doctors
        );


        if (!response.ok) {

            throw new Error(
                doctors.detail ||
                "Unable to load doctors."
            );

        }


        doctorSelect.innerHTML =
            `
            <option value="">
                Select Doctor
            </option>
            `;


        if (
            !Array.isArray(doctors) ||
            doctors.length === 0
        ) {

            doctorSelect.innerHTML =
                `
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


                let doctorText =
                    doctor.name;


                if (
                    doctor.specialization
                ) {

                    doctorText +=
                        ` - ${doctor.specialization}`;

                }


                option.textContent =
                    doctorText;


                doctorSelect.appendChild(
                    option
                );

            }
        );


        doctorSelect.disabled =
            false;

    }

    catch (error) {

        console.error(
            "Doctor loading error:",
            error
        );


        doctorSelect.innerHTML =
            `
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


    const continueBtn =
        document.getElementById(
            "continueBtn"
        );


    if (
        doctorSelect &&
        continueBtn &&
        doctorSelect.value
    ) {

        continueBtn.disabled =
            false;

    }

    else if (continueBtn) {

        continueBtn.disabled =
            true;

    }

}


// =========================================================
// DISABLE PAYMENT BUTTON
// =========================================================

function disablePaymentButton() {

    const continueBtn =
        document.getElementById(
            "continueBtn"
        );


    if (!continueBtn) {

        return;

    }


    continueBtn.disabled =
        true;


    continueBtn.textContent =
        "💳 Continue & Pay ₹10";

}


// =========================================================
// CONTINUE & PAY
// =========================================================

async function continueAndGetToken() {

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


    // Check patient

    if (!patientName) {

        showMessage(
            "Please login first.",
            "error"
        );

        return;

    }


    // Check hospital

    if (!hospitalId) {

        showMessage(
            "Please select a hospital.",
            "error"
        );

        return;

    }


    // Check department

    if (!department) {

        showMessage(
            "Please select a department.",
            "error"
        );

        return;

    }


    // Check doctor

    if (!doctorId) {

        showMessage(
            "Please select a doctor.",
            "error"
        );

        return;

    }


    const button =
        document.getElementById(
            "continueBtn"
        );


    button.disabled =
        true;


    button.textContent =
        "Creating Payment...";


    try {

        const response =
            await fetch(
                `${API}/api/create-order`,
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

                            hospital_id:
                                Number(
                                    hospitalId
                                ),

                            doctor_id:
                                Number(
                                    doctorId
                                )

                        })

                }
            );


        const order =
            await response.json();


        console.log(
            "Order:",
            order
        );


        if (!response.ok) {

            throw new Error(
                order.detail ||
                "Unable to create payment order."
            );

        }


        openRazorpay(
            order,
            hospitalId,
            doctorId,
            patientName
        );

    }

    catch (error) {

        console.error(
            "Payment error:",
            error
        );


        showMessage(
            error.message ||
            "Payment could not be started.",
            "error"
        );


        button.disabled =
            false;


        button.textContent =
            "💳 Continue & Pay ₹10";

    }

}


// =========================================================
// OPEN RAZORPAY
// =========================================================

function openRazorpay(
    order,
    hospitalId,
    doctorId,
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

        const button =
            document.getElementById(
                "continueBtn"
            );


        button.disabled =
            false;


        button.textContent =
            "💳 Continue & Pay ₹10";


        return;

    }


    const options = {

        key:
            order.key_id,

        amount:
            order.amount,

        currency:
            order.currency,

        name:
            "HospitalCare",

        description:
            "Hospital Token Fee",

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
                    "Payment successful:",
                    paymentResponse
                );


                await verifyPaymentAndCreateToken(

                    paymentResponse,

                    hospitalId,

                    doctorId,

                    patientName

                );

            },


        modal: {

            ondismiss:
                function () {

                    const button =
                        document.getElementById(
                            "continueBtn"
                        );


                    button.disabled =
                        false;


                    button.textContent =
                        "💳 Continue & Pay ₹10";


                    showMessage(
                        "Payment window closed.",
                        "error"
                    );

                }

        }

    };


    const razorpay =
        new Razorpay(
            options
        );


    razorpay.on(
        "payment.failed",
        function (response) {

            console.error(
                "Payment failed:",
                response.error
            );


            showMessage(

                response.error.description ||
                "Payment failed.",

                "error"

            );


            const button =
                document.getElementById(
                    "continueBtn"
                );


            button.disabled =
                false;


            button.textContent =
                "💳 Continue & Pay ₹10";

        }
    );


    razorpay.open();

}


// =========================================================
// VERIFY PAYMENT + CREATE TOKEN
// =========================================================

async function verifyPaymentAndCreateToken(

    paymentResponse,

    hospitalId,

    doctorId,

    patientName

) {

    const button =
        document.getElementById(
            "continueBtn"
        );


    button.disabled =
        true;


    button.textContent =
        "Verifying Payment...";


    try {

        // =========================================
        // VERIFY PAYMENT
        // =========================================

        const verifyResponse =
            await fetch(
                `${API}/api/verify-payment`,
                {

                    method: "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    body:
                        JSON.stringify({

                            razorpay_order_id:
                                paymentResponse.razorpay_order_id,

                            razorpay_payment_id:
                                paymentResponse.razorpay_payment_id,

                            razorpay_signature:
                                paymentResponse.razorpay_signature

                        })

                }
            );


        const verifyData =
            await verifyResponse.json();


        if (!verifyResponse.ok) {

            throw new Error(

                verifyData.detail ||
                "Payment verification failed."

            );

        }


        // =========================================
        // CREATE TOKEN
        // =========================================

        button.textContent =
            "Creating Token...";


        const tokenResponse =
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

                            hospital_id:
                                Number(
                                    hospitalId
                                ),

                            doctor_id:
                                Number(
                                    doctorId
                                ),

                            razorpay_order_id:
                                paymentResponse
                                    .razorpay_order_id,

                            razorpay_payment_id:
                                paymentResponse
                                    .razorpay_payment_id

                        })

                }
            );


        const tokenData =
            await tokenResponse.json();


        if (!tokenResponse.ok) {

            throw new Error(

                tokenData.detail ||
                "Token creation failed."

            );

        }


        console.log(
            "Token created:",
            tokenData
        );


        // =========================================
        // SAVE TOKEN
        // =========================================

        localStorage.setItem(
            "tokenId",
            tokenData.token.id
        );


        localStorage.setItem(
            "tokenNumber",
            tokenData.token.token_number
        );


        // =========================================
        // SUCCESS
        // =========================================

        showMessage(

            `Payment successful! Your token number is ${tokenData.token.token_number}.`,

            "success"

        );


        button.textContent =
            "Token Created ✓";


        // =========================================
        // TOKEN PAGE
        // =========================================

        setTimeout(
            function () {

                window.location.href =
                    "token.html";

            },
            1200
        );

    }

    catch (error) {

        console.error(
            "Token creation error:",
            error
        );


        showMessage(

            error.message ||
            "Unable to create token.",

            "error"

        );


        button.disabled =
            false;


        button.textContent =
            "💳 Continue & Pay ₹10";

    }

}


// =========================================================
// MESSAGE
// =========================================================

function showMessage(
    message,
    type = "success"
) {

    const messageElement =
        document.getElementById(
            "message"
        );


    if (!messageElement) {

        console.log(
            message
        );

        return;

    }


    messageElement.textContent =
        message;


    messageElement.className =
        `message ${type}`;

}


// =========================================================
// LOGOUT
// =========================================================

function logout() {

    localStorage.removeItem(
        "patientId"
    );

    localStorage.removeItem(
        "patientName"
    );

    localStorage.removeItem(
        "patientEmail"
    );

    localStorage.removeItem(
        "patientPhone"
    );

    localStorage.removeItem(
        "patientPicture"
    );

    localStorage.removeItem(
        "googleId"
    );

    localStorage.removeItem(
        "tokenId"
    );

    localStorage.removeItem(
        "tokenNumber"
    );


    window.location.href =
        "index.html";

}