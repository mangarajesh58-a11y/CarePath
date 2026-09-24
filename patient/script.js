
const API = "https://queueless-api-production.com";


/* =========================
   PATIENT REGISTRATION
========================= */

function registerPatient() {

    const fullName =
        document.getElementById("fullName").value.trim();

    const email =
        document.getElementById("email").value.trim();

    const phone =
        document.getElementById("phone").value.trim();

    const password =
        document.getElementById("password").value;

    const confirmPassword =
        document.getElementById("confirmPassword").value;


    if (
        fullName === "" ||
        email === "" ||
        phone === "" ||
        password === "" ||
        confirmPassword === ""
    ) {

        alert("Please fill all fields.");

        return;
    }


    if (password !== confirmPassword) {

        alert("Passwords do not match.");

        return;
    }


    /*
       TEMPORARY PATIENT LOGIN

       Registration will be moved to
       FastAPI + MySQL next.
    */

    localStorage.setItem(
        "patientName",
        fullName
    );

    localStorage.setItem(
        "patientEmail",
        email
    );

    localStorage.setItem(
        "patientPhone",
        phone
    );

    localStorage.setItem(
        "patientPassword",
        password
    );


    alert(
        "Registration successful!"
    );


    window.location.href =
        "index.html";
}


/* =========================
   PATIENT LOGIN
========================= */

function loginPatient() {

    const username =
        document.getElementById(
            "loginUser"
        ).value.trim();

    const password =
        document.getElementById(
            "loginPassword"
        ).value;


    const savedEmail =
        localStorage.getItem(
            "patientEmail"
        );

    const savedPhone =
        localStorage.getItem(
            "patientPhone"
        );

    const savedPassword =
        localStorage.getItem(
            "patientPassword"
        );


    if (

        (
            username === savedEmail ||
            username === savedPhone
        )

        &&

        password === savedPassword

    ) {

        localStorage.setItem(
            "patientLoggedIn",
            "true"
        );


        window.location.href =
            "dashboard.html";


    } else {

        alert(
            "Invalid email/phone or password."
        );

    }
}


/* =========================
   BOOK TOKEN
========================= */

async function bookToken() {

    const patientName =
        localStorage.getItem(
            "patientName"
        );


    const hospital =
        document.getElementById(
            "hospital"
        ).value;


    const department =
        document.getElementById(
            "department"
        ).value;


    const doctor =
        document.getElementById(
            "doctor"
        ).value;


    /* =========================
       LOGIN CHECK
    ========================= */

    if (!patientName) {

        alert(
            "Please login first."
        );

        window.location.href =
            "index.html";

        return;
    }


    /* =========================
       FORM VALIDATION
    ========================= */

    if (
        hospital === "" ||
        department === "" ||
        doctor === ""
    ) {

        alert(
            "Please select hospital, department and doctor."
        );

        return;
    }


    /* =========================
       SEND DATA TO FASTAPI
    ========================= */

    try {

        console.log(
            "Sending token data..."
        );


        const response =
            await fetch(

                API + "/tokens",

                {

                    method: "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    body: JSON.stringify({

                        patient_name:
                            patientName,

                        hospital:
                            hospital,

                        department:
                            department,

                        doctor:
                            doctor

                    })

                }

            );


        /* =========================
           READ FASTAPI RESPONSE
        ========================= */

        const data =
            await response.json();


        console.log(
            "FastAPI response:",
            data
        );


        /* =========================
           ERROR CHECK
        ========================= */

        if (!response.ok) {

            alert(

                "Token creation failed.\n\n" +

                (
                    data.detail ||
                    data.message ||
                    "Unknown error"
                )

            );

            return;
        }


        if (
            data.success === false
        ) {

            alert(

                "Database error:\n\n" +

                data.error

            );

            return;
        }


        /* =========================
           SAVE TOKEN INFORMATION
        ========================= */

        localStorage.setItem(
            "token",
            data.token
        );


        localStorage.setItem(
            "currentToken",
            data.current_token
        );


        localStorage.setItem(
            "peopleAhead",
            data.people_ahead
        );


        localStorage.setItem(
            "hospital",
            hospital
        );


        localStorage.setItem(
            "department",
            department
        );


        localStorage.setItem(
            "doctor",
            doctor
        );


        localStorage.setItem(
            "paymentStatus",
            data.payment_status
        );


        localStorage.setItem(
            "tokenStatus",
            data.status
        );


        localStorage.setItem(
            "tokenId",
            data.id
        );


        /* =========================
           SUCCESS
        ========================= */

        alert(

            "Token generated successfully!\n\n" +

            "Your Token: " +
            data.token

        );


        window.location.href =
            "token.html";


    } catch (error) {

        console.error(
            "Token error:",
            error
        );


        alert(

            "Cannot connect to FastAPI.\n\n" +

            "Make sure the backend is running:\n" +

            "uvicorn main:app --reload"

        );

    }
}


/* =========================
   LOAD TOKEN PAGE
========================= */

function loadToken() {

    const token =
        localStorage.getItem(
            "token"
        );


    if (!token) {

        window.location.href =
            "dashboard.html";

        return;
    }


    const tokenElement =
        document.getElementById(
            "myToken"
        );


    if (tokenElement) {

        tokenElement.innerText =
            token;

    }


    const hospitalElement =
        document.getElementById(
            "myHospital"
        );


    if (hospitalElement) {

        hospitalElement.innerText =
            localStorage.getItem(
                "hospital"
            );

    }


    const departmentElement =
        document.getElementById(
            "myDepartment"
        );


    if (departmentElement) {

        departmentElement.innerText =
            localStorage.getItem(
                "department"
            );

    }


    const doctorElement =
        document.getElementById(
            "myDoctor"
        );


    if (doctorElement) {

        doctorElement.innerText =
            localStorage.getItem(
                "doctor"
            );

    }


    const currentTokenElement =
        document.getElementById(
            "currentToken"
        );


    if (currentTokenElement) {

        currentTokenElement.innerText =
            localStorage.getItem(
                "currentToken"
            );

    }


    const peopleAheadElement =
        document.getElementById(
            "peopleAhead"
        );


    if (peopleAheadElement) {

        peopleAheadElement.innerText =
            localStorage.getItem(
                "peopleAhead"
            );

    }


    const statusElement =
        document.getElementById(
            "status"
        );


    if (statusElement) {

        const status =
            localStorage.getItem(
                "tokenStatus"
            );


        if (status === "waiting") {

            statusElement.innerText =
                "Waiting";

        }

        else if (
            status === "serving"
        ) {

            statusElement.innerText =
                "Your Turn";

        }

        else if (
            status === "completed"
        ) {

            statusElement.innerText =
                "Completed";

        }

        else {

            statusElement.innerText =
                "Token Confirmed";

        }

    }

}


/* =========================
   DASHBOARD NAME
========================= */

function loadPatientName() {

    const name =
        localStorage.getItem(
            "patientName"
        );


    const element =
        document.getElementById(
            "patientName"
        );


    if (
        element &&
        name
    ) {

        element.innerText =
            name;

    }

}


/* =========================
   LOGOUT
========================= */

function logout() {

    localStorage.removeItem(
        "patientLoggedIn"
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
        "patientPassword"
    );


    window.location.href =
        "index.html";

}


/* =========================
   BACK TO DASHBOARD
========================= */

function backDashboard() {

    window.location.href =
        "dashboard.html";

}


/* =========================
   PAGE DETECTION
========================= */

if (

    window.location.pathname.includes(
        "dashboard.html"
    )

) {

    loadPatientName();

}


if (

    window.location.pathname.includes(
        "token.html"
    )

) {

    loadToken();

}
```
// =====================================
// CHECK WHETHER PATIENT IS CALLED
// =====================================

async function checkPatientToken() {

    const tokenId =
        localStorage.getItem("tokenId");

    if (!tokenId) {
        return;
    }

    try {

        const response =
            await fetch(
                API +
                "/patient-token/" +
                tokenId
            );

        const data =
            await response.json();


        if (!data.success) {
            return;
        }


        const status =
            data.status;


        const message =
            document.getElementById(
                "callMessage"
            );


        const statusElement =
            document.getElementById(
                "status"
            );


        if (statusElement) {

            statusElement.innerText =
                status;
        }


        if (
            status === "serving"
        ) {

            if (message) {

                message.innerText =
                    "🔔 Your token is called! Please go to the consultation room.";
            }

            message.style.color =
                "#16a34a";


            // Optional browser notification
            if (
                "Notification" in window
            ) {

                if (
                    Notification.permission ===
                    "granted"
                ) {

                    new Notification(
                        "HospitalCare",
                        {
                            body:
                                "Your token " +
                                data.token +
                                " has been called."
                        }
                    );
                }
            }


        } else if (
            status === "completed"
        ) {

            if (message) {

                message.innerText =
                    "Consultation completed.";
            }


        } else {

            if (message) {

                message.innerText =
                    "Please wait for your turn.";
            }

            message.style.color =
                "#1976d2";
        }


    } catch (error) {

        console.error(
            "Patient token check error:",
            error
        );
    }
}