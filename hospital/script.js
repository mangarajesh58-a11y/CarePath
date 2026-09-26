// ============================================================
// HOSPITALCARE - HOSPITAL SCRIPT
// ============================================================

const API = "http://127.0.0.1:8000";


// ============================================================
// HELPER FUNCTIONS
// ============================================================

function escapeHTML(value) {

    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


// ============================================================
// HOSPITAL REGISTRATION
// ============================================================

async function registerHospital() {

    // --------------------------------------------------------
    // Get values from register.html
    // --------------------------------------------------------

    const hospitalName =
        document.getElementById("hospitalName")?.value.trim();

    const email =
        document.getElementById("hospitalEmail")?.value.trim();

    const phone =
        document.getElementById("hospitalPhone")?.value.trim();

    const city =
        document.getElementById("hospitalCity")?.value.trim();

    const address =
        document.getElementById("hospitalAddress")?.value.trim();

    const description =
        document.getElementById("hospitalDescription")?.value.trim();

    // IMPORTANT:
    // register.html uses id="licenseId"
    const licenseId =
        document.getElementById("licenseId")?.value.trim();

    const password =
        document.getElementById("hospitalPassword")?.value;

    // IMPORTANT:
    // register.html uses id="confirmPassword"
    const confirmPassword =
        document.getElementById("confirmPassword")?.value;


    // --------------------------------------------------------
    // Validate fields
    // --------------------------------------------------------

    if (
        !hospitalName ||
        !email ||
        !phone ||
        !city ||
        !address ||
        !licenseId ||
        !password ||
        !confirmPassword
    ) {

        alert("Please fill all required fields.");

        return;
    }


    // --------------------------------------------------------
    // Password validation
    // --------------------------------------------------------

    if (password !== confirmPassword) {

        alert("Passwords do not match.");

        return;
    }


    // --------------------------------------------------------
    // Send registration to FastAPI
    // --------------------------------------------------------

    try {

        console.log("Registering hospital...");


        const response = await fetch(
            `${API}/hospitals`,
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({

                    name: hospitalName,

                    email: email,

                    phone: phone,

                    city: city,

                    address: address,

                    description: description,

                    license_id: licenseId,

                    password: password

                })
            }
        );


        // ----------------------------------------------------
        // Read backend response
        // ----------------------------------------------------

        const data = await response.json();


        console.log(
            "Registration response:",
            data
        );


        // ----------------------------------------------------
        // Handle backend error
        // ----------------------------------------------------

        if (!response.ok) {

            alert(
                data.detail ||
                "Hospital registration failed."
            );

            return;
        }


        // ----------------------------------------------------
        // Save hospital ID
        // ----------------------------------------------------

        if (
            data.hospital &&
            data.hospital.id
        ) {

            localStorage.setItem(
                "hospitalId",
                data.hospital.id
            );

            console.log(
                "Hospital ID saved:",
                data.hospital.id
            );
        }


        // ----------------------------------------------------
        // Save hospital information
        // ----------------------------------------------------

        localStorage.setItem(
            "hospitalName",
            hospitalName
        );

        localStorage.setItem(
            "hospitalEmail",
            email
        );

        localStorage.setItem(
            "hospitalPhone",
            phone
        );

        localStorage.setItem(
            "hospitalCity",
            city
        );

        localStorage.setItem(
            "hospitalAddress",
            address
        );

        localStorage.setItem(
            "hospitalDescription",
            description
        );

        localStorage.setItem(
            "hospitalLicense",
            licenseId
        );


        // ----------------------------------------------------
        // Temporary local login support
        // ----------------------------------------------------

        localStorage.setItem(
            "hospitalPassword",
            password
        );

        localStorage.setItem(
            "hospitalLoggedIn",
            "true"
        );


        // ----------------------------------------------------
        // Registration success
        // ----------------------------------------------------

        alert(
            "Hospital registered successfully!\n\n" +
            "Your hospital is waiting for admin approval."
        );


        window.location.href =
            "index.html";

    }

    catch (error) {

        console.error(
            "Hospital registration error:",
            error
        );

        alert(
            "Cannot connect to FastAPI.\n\n" +
            "Make sure the backend is running."
        );
    }
}


// ============================================================
// HOSPITAL LOGIN
// ============================================================

function hospitalLogin() {

    const email =
        document.getElementById(
            "hospitalLoginEmail"
        )?.value.trim();

    const password =
        document.getElementById(
            "hospitalLoginPassword"
        )?.value;


    if (!email || !password) {

        alert(
            "Please enter email and password."
        );

        return;
    }


    const savedEmail =
        localStorage.getItem(
            "hospitalEmail"
        );

    const savedPassword =
        localStorage.getItem(
            "hospitalPassword"
        );


    // --------------------------------------------------------
    // Check saved login information
    // --------------------------------------------------------

    if (
        email === savedEmail &&
        password === savedPassword
    ) {

        localStorage.setItem(
            "hospitalLoggedIn",
            "true"
        );

        window.location.href =
            "dashboard.html";

        return;
    }


    alert(
        "Invalid email or password."
    );
}


// ============================================================
// GOOGLE LOGIN
// ============================================================

async function handleHospitalGoogleLogin(response) {

    if (
        !response ||
        !response.credential
    ) {

        alert(
            "Google login failed."
        );

        return;
    }


    try {

        const result = await fetch(
            `${API}/auth/google`,
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({

                    credential:
                        response.credential,

                    role:
                        "hospital"

                })
            }
        );


        const data =
            await result.json();


        if (!result.ok) {

            alert(
                data.detail ||
                "Google login failed."
            );

            return;
        }


        // ----------------------------------------------------
        // Save Google access token
        // ----------------------------------------------------

        if (data.access_token) {

            localStorage.setItem(
                "hospitalAccessToken",
                data.access_token
            );
        }


        localStorage.setItem(
            "hospitalLoggedIn",
            "true"
        );

        localStorage.setItem(
            "hospitalRole",
            "hospital"
        );


        // ----------------------------------------------------
        // Save returned hospital information
        // ----------------------------------------------------

        if (data.user) {

            if (data.user.id) {

                localStorage.setItem(
                    "hospitalId",
                    data.user.id
                );
            }


            if (data.user.name) {

                localStorage.setItem(
                    "hospitalName",
                    data.user.name
                );
            }


            if (data.user.email) {

                localStorage.setItem(
                    "hospitalEmail",
                    data.user.email
                );
            }


            if (data.user.phone) {

                localStorage.setItem(
                    "hospitalPhone",
                    data.user.phone
                );
            }
        }


        window.location.href =
            "dashboard.html";

    }

    catch (error) {

        console.error(
            "Google login error:",
            error
        );

        alert(
            "Cannot connect to FastAPI."
        );
    }
}


// ============================================================
// HOSPITAL LOGOUT
// ============================================================

function hospitalLogout() {

    const keys = [

        "hospitalLoggedIn",

        "hospitalAccessToken",

        "hospitalRole",

        "hospitalId",

        "hospitalName",

        "hospitalEmail",

        "hospitalPhone",

        "hospitalCity",

        "hospitalAddress",

        "hospitalDescription",

        "hospitalLicense",

        "hospitalPassword",

        "hospitalLatitude",

        "hospitalLongitude"

    ];


    keys.forEach(function (key) {

        localStorage.removeItem(key);

    });


    window.location.href =
        "index.html";
}


// ============================================================
// GET CURRENT HOSPITAL ID
// ============================================================

async function getCurrentHospital() {

    // --------------------------------------------------------
    // First use saved hospital ID
    // --------------------------------------------------------

    const savedHospitalId =
        localStorage.getItem(
            "hospitalId"
        );


    if (savedHospitalId) {

        console.log(
            "Current Hospital ID:",
            savedHospitalId
        );


        return parseInt(
            savedHospitalId,
            10
        );
    }


    // --------------------------------------------------------
    // If ID doesn't exist, find hospital by name
    // --------------------------------------------------------

    const hospitalName =
        localStorage.getItem(
            "hospitalName"
        );


    if (!hospitalName) {

        throw new Error(
            "Hospital information not found."
        );
    }


    try {

        const response =
            await fetch(
                `${API}/hospitals`
            );


        if (!response.ok) {

            throw new Error(
                "Unable to load hospitals."
            );
        }


        const hospitals =
            await response.json();


        const hospital =
            hospitals.find(
                function (item) {

                    return (
                        item.name ===
                        hospitalName
                    );

                }
            );


        if (!hospital) {

            throw new Error(
                "Hospital not found in database."
            );
        }


        localStorage.setItem(
            "hospitalId",
            hospital.id
        );


        console.log(
            "Hospital ID found:",
            hospital.id
        );


        return hospital.id;

    }

    catch (error) {

        console.error(
            "Get current hospital error:",
            error
        );

        throw error;
    }
}


// ============================================================
// DASHBOARD
// ============================================================

function goDashboard() {

    window.location.href =
        "dashboard.html";
}


function openDoctors() {

    window.location.href =
        "doctors.html";
}


function openPatients() {

    window.location.href =
        "patients.html";
}


function openProfile() {

    window.location.href =
        "profile.html";
}


// ============================================================
// ADD DOCTOR
// ============================================================

async function addDoctor() {

    const name =
        document.getElementById(
            "doctorName"
        )?.value.trim();


    const department =
        document.getElementById(
            "doctorDepartment"
        )?.value.trim();


    const experience =
        document.getElementById(
            "doctorExperience"
        )?.value.trim();


    if (!name || !department) {

        alert(
            "Please enter doctor name and department."
        );

        return;
    }


    try {

        const hospitalId =
            await getCurrentHospital();


        console.log(
            "Adding doctor to hospital:",
            hospitalId
        );


        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}/doctors`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({

                        name:
                            name,

                        department:
                            department,

                        experience:
                            experience || ""

                    })
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            alert(
                data.detail ||
                "Doctor could not be added."
            );

            return;
        }


        alert(
            "Doctor added successfully!"
        );


        // ----------------------------------------------------
        // Clear form
        // ----------------------------------------------------

        const doctorNameInput =
            document.getElementById(
                "doctorName"
            );

        const doctorDepartmentInput =
            document.getElementById(
                "doctorDepartment"
            );

        const doctorExperienceInput =
            document.getElementById(
                "doctorExperience"
            );


        if (doctorNameInput) {

            doctorNameInput.value = "";
        }


        if (doctorDepartmentInput) {

            doctorDepartmentInput.value = "";
        }


        if (doctorExperienceInput) {

            doctorExperienceInput.value = "";
        }


        await loadDoctors();

    }

    catch (error) {

        console.error(
            "Add doctor error:",
            error
        );

        alert(
            "Cannot connect to FastAPI."
        );
    }
}


// ============================================================
// LOAD DOCTORS
// ============================================================

async function loadDoctors() {

    const doctorList =
        document.getElementById(
            "doctorList"
        );


    if (!doctorList) {

        return;
    }


    doctorList.innerHTML =
        "<p>Loading doctors...</p>";


    try {

        const hospitalId =
            await getCurrentHospital();


        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}/doctors`
            );


        if (!response.ok) {

            throw new Error(
                "Unable to load doctors."
            );
        }


        const doctors =
            await response.json();


        console.log(
            "Doctors received:",
            doctors
        );


        if (
            !doctors ||
            doctors.length === 0
        ) {

            doctorList.innerHTML = `
                <p>
                    No doctors added yet.
                </p>
            `;

            return;
        }


        doctorList.innerHTML = "";


        doctors.forEach(
            function (doctor) {

                const div =
                    document.createElement(
                        "div"
                    );


                div.className =
                    "doctor-item";


                div.innerHTML = `

                    <div class="doctor-info">

                        <strong>
                            👨‍⚕️
                            ${escapeHTML(
                                doctor.name
                            )}
                        </strong>

                        <span>
                            Department:
                            ${escapeHTML(
                                doctor.department
                            )}
                        </span>

                        <span>
                            Experience:
                            ${escapeHTML(
                                doctor.experience ||
                                "Not specified"
                            )}
                        </span>

                    </div>

                    <button
                        class="remove-doctor"
                        onclick="removeDoctor(${doctor.id})"
                    >
                        🗑 Remove
                    </button>

                `;


                doctorList.appendChild(
                    div
                );
            }
        );

    }

    catch (error) {

        console.error(
            "Load doctors error:",
            error
        );


        doctorList.innerHTML = `

            <p>
                Cannot load doctors.
                <br><br>
                Make sure FastAPI is running.
            </p>

        `;
    }
}


// ============================================================
// REMOVE DOCTOR
// ============================================================

async function removeDoctor(doctorId) {

    const confirmDelete =
        confirm(
            "Are you sure you want to remove this doctor?"
        );


    if (!confirmDelete) {

        return;
    }


    try {

        const response =
            await fetch(
                `${API}/doctors/${doctorId}`,
                {
                    method: "DELETE"
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            alert(
                data.detail ||
                "Doctor could not be removed."
            );

            return;
        }


        alert(
            "Doctor removed successfully!"
        );


        await loadDoctors();

    }

    catch (error) {

        console.error(
            "Remove doctor error:",
            error
        );


        alert(
            "Cannot connect to FastAPI."
        );
    }
}


// ============================================================
// LOAD PATIENTS / TOKENS
// ============================================================

async function loadPatients() {

    const patientList =
        document.getElementById(
            "patientList"
        );


    if (!patientList) {

        return;
    }


    patientList.innerHTML =
        "<p>Loading patients...</p>";


    try {

        const hospitalName =
            localStorage.getItem(
                "hospitalName"
            );


        if (!hospitalName) {

            patientList.innerHTML =
                "<p>Hospital information not found.</p>";

            return;
        }


        const response =
            await fetch(
                `${API}/tokens`
            );


        if (!response.ok) {

            throw new Error(
                "Unable to load tokens."
            );
        }


        const allTokens =
            await response.json();


        const hospitalTokens =
            allTokens.filter(
                function (token) {

                    return (
                        token.hospital ===
                        hospitalName
                    );

                }
            );


        if (
            hospitalTokens.length === 0
        ) {

            patientList.innerHTML = `

                <p>
                    No patients have booked tokens yet.
                </p>

            `;

            return;
        }


        patientList.innerHTML = "";


        hospitalTokens.forEach(
            function (token) {

                const div =
                    document.createElement(
                        "div"
                    );


                div.className =
                    "patient-item";


                div.innerHTML = `

                    <strong>
                        🎫 Token
                        ${escapeHTML(
                            token.token_number
                        )}
                    </strong>

                    <span>
                        Patient:
                        ${escapeHTML(
                            token.patient_name
                        )}
                    </span>

                    <span>
                        Department:
                        ${escapeHTML(
                            token.department
                        )}
                    </span>

                    <span>
                        Doctor:
                        ${escapeHTML(
                            token.doctor
                        )}
                    </span>

                    <span>
                        Status:
                        ${escapeHTML(
                            token.status
                        )}
                    </span>

                `;


                patientList.appendChild(
                    div
                );
            }
        );

    }

    catch (error) {

        console.error(
            "Load patients error:",
            error
        );


        patientList.innerHTML = `

            <p>
                Cannot load patients.
                <br><br>
                Make sure FastAPI is running.
            </p>

        `;
    }
}


// ============================================================
// LOAD HOSPITAL PROFILE
// ============================================================

async function loadProfile() {

    const nameInput =
        document.getElementById(
            "profileHospitalName"
        );


    const emailInput =
        document.getElementById(
            "profileHospitalEmail"
        );


    const phoneInput =
        document.getElementById(
            "profileHospitalPhone"
        );


    const cityInput =
        document.getElementById(
            "profileHospitalCity"
        );


    const addressInput =
        document.getElementById(
            "profileHospitalAddress"
        );


    const descriptionInput =
        document.getElementById(
            "profileHospitalDescription"
        );


    if (nameInput) {

        nameInput.value =
            localStorage.getItem(
                "hospitalName"
            ) || "";
    }


    if (emailInput) {

        emailInput.value =
            localStorage.getItem(
                "hospitalEmail"
            ) || "";
    }


    if (phoneInput) {

        phoneInput.value =
            localStorage.getItem(
                "hospitalPhone"
            ) || "";
    }


    if (cityInput) {

        cityInput.value =
            localStorage.getItem(
                "hospitalCity"
            ) || "";
    }


    if (addressInput) {

        addressInput.value =
            localStorage.getItem(
                "hospitalAddress"
            ) || "";
    }


    if (descriptionInput) {

        descriptionInput.value =
            localStorage.getItem(
                "hospitalDescription"
            ) || "";
    }
}


// ============================================================
// SAVE HOSPITAL PROFILE
// ============================================================

function saveProfile() {

    const nameInput =
        document.getElementById(
            "profileHospitalName"
        );


    const emailInput =
        document.getElementById(
            "profileHospitalEmail"
        );


    const phoneInput =
        document.getElementById(
            "profileHospitalPhone"
        );


    const cityInput =
        document.getElementById(
            "profileHospitalCity"
        );


    const addressInput =
        document.getElementById(
            "profileHospitalAddress"
        );


    const descriptionInput =
        document.getElementById(
            "profileHospitalDescription"
        );


    if (nameInput) {

        localStorage.setItem(
            "hospitalName",
            nameInput.value.trim()
        );
    }


    if (emailInput) {

        localStorage.setItem(
            "hospitalEmail",
            emailInput.value.trim()
        );
    }


    if (phoneInput) {

        localStorage.setItem(
            "hospitalPhone",
            phoneInput.value.trim()
        );
    }


    if (cityInput) {

        localStorage.setItem(
            "hospitalCity",
            cityInput.value.trim()
        );
    }


    if (addressInput) {

        localStorage.setItem(
            "hospitalAddress",
            addressInput.value.trim()
        );
    }


    if (descriptionInput) {

        localStorage.setItem(
            "hospitalDescription",
            descriptionInput.value.trim()
        );
    }


    alert(
        "Profile saved successfully!"
    );
}


// ============================================================
// LOAD QUEUE
// ============================================================

async function loadQueue() {

    const queueList =
        document.getElementById(
            "queueList"
        );


    if (!queueList) {

        return;
    }


    queueList.innerHTML =
        "<p>Loading queue...</p>";


    try {

        const hospitalName =
            localStorage.getItem(
                "hospitalName"
            );


        const response =
            await fetch(
                `${API}/tokens`
            );


        if (!response.ok) {

            throw new Error(
                "Unable to load queue."
            );
        }


        const tokens =
            await response.json();


        const hospitalTokens =
            tokens.filter(
                function (token) {

                    return (
                        token.hospital ===
                        hospitalName
                    );

                }
            );


        if (
            hospitalTokens.length === 0
        ) {

            queueList.innerHTML = `
                <p>No patients waiting.</p>
            `;

            return;
        }


        queueList.innerHTML = "";


        hospitalTokens.forEach(
            function (token) {

                const div =
                    document.createElement(
                        "div"
                    );


                div.className =
                    "queue-item";


                div.innerHTML = `

                    <strong>
                        Token
                        ${escapeHTML(
                            token.token_number
                        )}
                    </strong>

                    <span>
                        ${escapeHTML(
                            token.patient_name
                        )}
                    </span>

                    <span>
                        ${escapeHTML(
                            token.doctor
                        )}
                    </span>

                    <span>
                        ${escapeHTML(
                            token.status
                        )}
                    </span>

                `;


                queueList.appendChild(
                    div
                );
            }
        );

    }

    catch (error) {

        console.error(
            "Queue error:",
            error
        );


        queueList.innerHTML = `
            <p>
                Unable to load queue.
            </p>
        `;
    }
}


// ============================================================
// CALL NEXT PATIENT
// ============================================================

async function callNextPatient(
    department,
    doctor
) {

    try {

        const hospitalName =
            localStorage.getItem(
                "hospitalName"
            );


        if (!hospitalName) {

            alert(
                "Hospital information not found."
            );

            return;
        }


        const url =
            `${API}/next-patient` +
            `?hospital=${encodeURIComponent(
                hospitalName
            )}` +
            `&department=${encodeURIComponent(
                department
            )}` +
            `&doctor=${encodeURIComponent(
                doctor
            )}`;


        const response =
            await fetch(
                url,
                {
                    method: "POST"
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            alert(
                data.detail ||
                "Unable to call next patient."
            );

            return;
        }


        alert(
            data.message ||
            "Next patient called."
        );


        await loadQueue();

    }

    catch (error) {

        console.error(
            "Call next patient error:",
            error
        );


        alert(
            "Cannot connect to FastAPI."
        );
    }
}


// ============================================================
// GOOGLE MAP
// ============================================================

let hospitalMap = null;
let hospitalMarker = null;


// ============================================================
// INITIALIZE MAP
// ============================================================

function initMap() {

    const mapElement =
        document.getElementById(
            "map"
        );


    if (!mapElement) {

        return;
    }


    const defaultLocation = {

        lat: 17.3850,

        lng: 78.4867

    };


    hospitalMap =
        new google.maps.Map(
            mapElement,
            {

                center:
                    defaultLocation,

                zoom:
                    12

            }
        );


    hospitalMarker =
        new google.maps.Marker({

            position:
                defaultLocation,

            map:
                hospitalMap,

            draggable:
                true

        });


    hospitalMarker.addListener(
        "dragend",
        function () {

            const position =
                hospitalMarker.getPosition();


            updateHospitalLocation(
                position.lat(),
                position.lng()
            );
        }
    );
}


// ============================================================
// UPDATE HOSPITAL LOCATION
// ============================================================

function updateHospitalLocation(
    latitude,
    longitude
) {

    const latInput =
        document.getElementById(
            "hospitalLatitude"
        );


    const lngInput =
        document.getElementById(
            "hospitalLongitude"
        );


    if (latInput) {

        latInput.value =
            latitude;
    }


    if (lngInput) {

        lngInput.value =
            longitude;
    }


    localStorage.setItem(
        "hospitalLatitude",
        latitude
    );


    localStorage.setItem(
        "hospitalLongitude",
        longitude
    );
}


// ============================================================
// PAGE INITIALIZATION
// ============================================================

document.addEventListener(
    "DOMContentLoaded",
    function () {

        console.log(
            "HospitalCare hospital script loaded."
        );


        // ----------------------------------------------------
        // Doctors page
        // ----------------------------------------------------

        if (
            document.getElementById(
                "doctorList"
            )
        ) {

            loadDoctors();
        }


        // ----------------------------------------------------
        // Patients page
        // ----------------------------------------------------

        if (
            document.getElementById(
                "patientList"
            )
        ) {

            loadPatients();
        }


        // ----------------------------------------------------
        // Queue page
        // ----------------------------------------------------

        if (
            document.getElementById(
                "queueList"
            )
        ) {

            loadQueue();
        }


        // ----------------------------------------------------
        // Profile page
        // ----------------------------------------------------

        if (
            document.getElementById(
                "profileHospitalName"
            )
        ) {

            loadProfile();
        }

    }
);


// ============================================================
// EXPORT FUNCTIONS
// ============================================================

window.registerHospital =
    registerHospital;

window.hospitalLogin =
    hospitalLogin;

window.handleHospitalGoogleLogin =
    handleHospitalGoogleLogin;

window.hospitalLogout =
    hospitalLogout;

window.openDoctors =
    openDoctors;

window.openPatients =
    openPatients;

window.openProfile =
    openProfile;

window.goDashboard =
    goDashboard;

window.addDoctor =
    addDoctor;

window.loadDoctors =
    loadDoctors;

window.removeDoctor =
    removeDoctor;

window.loadPatients =
    loadPatients;

window.loadProfile =
    loadProfile;

window.saveProfile =
    saveProfile;

window.loadQueue =
    loadQueue;

window.callNextPatient =
    callNextPatient;

window.initMap =
    initMap;

window.updateHospitalLocation =
    updateHospitalLocation;