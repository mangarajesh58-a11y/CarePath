const API = "https://queueless-api-production.com";


// ===============================
// HOSPITAL REGISTRATION
// ===============================

function registerHospital() {

    const hospitalName =
        document.getElementById("hospitalName").value.trim();

    const email =
        document.getElementById("hospitalEmail").value.trim();

    const phone =
        document.getElementById("hospitalPhone").value.trim();

    const address =
        document.getElementById("hospitalAddress").value.trim();

    const license =
        document.getElementById("licenseNumber").value.trim();

    const password =
        document.getElementById("hospitalPassword").value;

    const confirmPassword =
        document.getElementById("confirmPassword").value;


    if (
        hospitalName === "" ||
        email === "" ||
        phone === "" ||
        address === "" ||
        license === "" ||
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
        "hospitalAddress",
        address
    );

    localStorage.setItem(
        "hospitalLicense",
        license
    );

    localStorage.setItem(
        "hospitalPassword",
        password
    );


    alert("Hospital registration successful!");

    window.location.href = "index.html";
}



// ===============================
// HOSPITAL LOGIN
// ===============================

function hospitalLogin() {

    const email =
        document.getElementById("loginEmail").value.trim();

    const password =
        document.getElementById("loginPassword").value;


    const savedEmail =
        localStorage.getItem("hospitalEmail");

    const savedPassword =
        localStorage.getItem("hospitalPassword");


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

    } else {

        alert(
            "Invalid hospital email or password."
        );
    }
}



// ===============================
// LOGOUT
// ===============================

function hospitalLogout() {

    localStorage.removeItem(
        "hospitalLoggedIn"
    );

    window.location.href =
        "index.html";
}



// ===============================
// DASHBOARD
// ===============================

function loadHospitalDashboard() {

    const loggedIn =
        localStorage.getItem(
            "hospitalLoggedIn"
        );


    if (loggedIn !== "true") {

        window.location.href =
            "index.html";

        return;
    }


    const hospitalName =
        localStorage.getItem(
            "hospitalName"
        );


    const element =
        document.getElementById(
            "hospitalNameDisplay"
        );


    if (element && hospitalName) {

        element.innerText =
            hospitalName;
    }


    loadQueue();
}



// ===============================
// DASHBOARD BUTTONS
// ===============================

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


function goDashboard() {

    window.location.href =
        "dashboard.html";
}



// ===============================
// DOCTORS
// ===============================

function addDoctor() {

    const name =
        document.getElementById(
            "doctorName"
        ).value.trim();


    const department =
        document.getElementById(
            "doctorDepartment"
        ).value;


    const experience =
        document.getElementById(
            "doctorExperience"
        ).value.trim();


    if (
        name === "" ||
        department === "" ||
        experience === ""
    ) {

        alert(
            "Please fill all doctor details."
        );

        return;
    }


    let doctors =
        JSON.parse(
            localStorage.getItem(
                "hospitalDoctors"
            )
        ) || [];


    doctors.push({

        name: name,

        department: department,

        experience: experience

    });


    localStorage.setItem(
        "hospitalDoctors",
        JSON.stringify(doctors)
    );


    alert(
        "Doctor added successfully!"
    );


    document.getElementById(
        "doctorName"
    ).value = "";


    document.getElementById(
        "doctorDepartment"
    ).value = "";


    document.getElementById(
        "doctorExperience"
    ).value = "";


    loadDoctors();
}



function loadDoctors() {

    const doctorList =
        document.getElementById(
            "doctorList"
        );


    if (!doctorList) {
        return;
    }


    let doctors =
        JSON.parse(
            localStorage.getItem(
                "hospitalDoctors"
            )
        ) || [];


    if (doctors.length === 0) {

        doctorList.innerHTML =
            "<p>No doctors added yet.</p>";

        return;
    }


    doctorList.innerHTML = "";


    doctors.forEach(
        function(doctor, index) {

            const div =
                document.createElement(
                    "div"
                );


            div.className =
                "doctor-item";


            div.innerHTML = `

                <strong>
                    ${doctor.name}
                </strong>

                <span>
                    ${doctor.department}
                </span>

                <span>
                    ${doctor.experience}
                </span>

                <button
                    onclick="deleteDoctor(${index})"
                >
                    Delete
                </button>

            `;


            doctorList.appendChild(
                div
            );
        }
    );
}



function deleteDoctor(index) {

    let doctors =
        JSON.parse(
            localStorage.getItem(
                "hospitalDoctors"
            )
        ) || [];


    doctors.splice(
        index,
        1
    );


    localStorage.setItem(
        "hospitalDoctors",
        JSON.stringify(doctors)
    );


    loadDoctors();
}



// ===============================
// HOSPITAL PROFILE
// ===============================

function loadProfile() {

    const name =
        document.getElementById(
            "profileName"
        );


    if (!name) {
        return;
    }


    name.value =
        localStorage.getItem(
            "hospitalName"
        ) || "";


    document.getElementById(
        "profileEmail"
    ).value =
        localStorage.getItem(
            "hospitalEmail"
        ) || "";


    document.getElementById(
        "profilePhone"
    ).value =
        localStorage.getItem(
            "hospitalPhone"
        ) || "";


    document.getElementById(
        "profileAddress"
    ).value =
        localStorage.getItem(
            "hospitalAddress"
        ) || "";


    document.getElementById(
        "profileLicense"
    ).value =
        localStorage.getItem(
            "hospitalLicense"
        ) || "";
}



function saveProfile() {

    const name =
        document.getElementById(
            "profileName"
        ).value.trim();


    const email =
        document.getElementById(
            "profileEmail"
        ).value.trim();


    const phone =
        document.getElementById(
            "profilePhone"
        ).value.trim();


    const address =
        document.getElementById(
            "profileAddress"
        ).value.trim();


    const license =
        document.getElementById(
            "profileLicense"
        ).value.trim();


    localStorage.setItem(
        "hospitalName",
        name
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
        "hospitalAddress",
        address
    );


    localStorage.setItem(
        "hospitalLicense",
        license
    );


    alert(
        "Hospital profile updated successfully!"
    );
}



// ===============================
// LOAD PATIENTS
// ===============================

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

        const response =
            await fetch(
                API + "/tokens"
            );


        const tokens =
            await response.json();


        const hospitalName =
            localStorage.getItem(
                "hospitalName"
            );


        const hospitalTokens =
            tokens.filter(
                function(token) {

                    return (
                        token.hospital ===
                        hospitalName
                    );

                }
            );


        if (
            hospitalTokens.length === 0
        ) {

            patientList.innerHTML =
                "<p>No patients found.</p>";

            return;
        }


        patientList.innerHTML = "";


        hospitalTokens.forEach(
            function(token) {

                const div =
                    document.createElement(
                        "div"
                    );


                div.className =
                    "doctor-item";


                div.innerHTML = `

                    <strong>
                        Token ${token.token_number}
                    </strong>

                    <span>
                        ${token.patient_name}
                    </span>

                    <span>
                        ${token.department}
                    </span>

                    <span>
                        ${token.doctor}
                    </span>

                    <span>
                        ${token.status}
                    </span>

                `;


                patientList.appendChild(
                    div
                );
            }
        );


    } catch (error) {

        console.error(error);


        patientList.innerHTML = `

            <p>
                Cannot connect to FastAPI.
                <br>
                Make sure backend is running.
            </p>

        `;
    }
}



// ===============================
// DASHBOARD QUEUE
// ===============================

async function loadQueue() {

    const waitingCount =
        document.getElementById(
            "waitingCount"
        );


    const currentToken =
        document.getElementById(
            "currentToken"
        );


    const completedCount =
        document.getElementById(
            "completedCount"
        );


    if (
        !waitingCount ||
        !currentToken ||
        !completedCount
    ) {
        return;
    }


    try {

        const response =
            await fetch(
                API + "/tokens"
            );


        const tokens =
            await response.json();


        const hospitalName =
            localStorage.getItem(
                "hospitalName"
            );


        const hospitalTokens =
            tokens.filter(
                function(token) {

                    return (
                        token.hospital ===
                        hospitalName
                    );

                }
            );


        let waiting = 0;

        let completed = 0;

        let serving = 0;


        hospitalTokens.forEach(
            function(token) {

                if (
                    token.status ===
                    "waiting"
                ) {

                    waiting++;
                }


                if (
                    token.status ===
                    "completed"
                ) {

                    completed++;
                }


                if (
                    token.status ===
                    "serving"
                ) {

                    serving =
                        token.token_number;
                }

            }
        );


        waitingCount.innerText =
            waiting;


        completedCount.innerText =
            completed;


        currentToken.innerText =
            serving;


    } catch (error) {

        console.error(
            "Queue error:",
            error
        );
    }
}



// ===============================
// CALL NEXT PATIENT
// ===============================

async function callNextPatient() {

    const hospital =
        localStorage.getItem(
            "hospitalName"
        );


    if (!hospital) {

        alert(
            "Hospital information not found."
        );

        return;
    }


    /*
       For now these values match
       the patient dashboard.
       Later we will make them
       selectable from the dashboard.
    */

    const department =
        "General Medicine";


    const doctor =
        "Dr. Kumar";


    try {

        const url =
            API +
            "/next-patient" +
            "?hospital=" +
            encodeURIComponent(hospital) +
            "&department=" +
            encodeURIComponent(department) +
            "&doctor=" +
            encodeURIComponent(doctor);


        const response =
            await fetch(
                url,
                {
                    method: "POST"
                }
            );


        const data =
            await response.json();


        if (
            data.token
        ) {

            alert(
                "Calling Token " +
                data.token +
                "\nPatient: " +
                data.patient
            );

        } else {

            alert(
                data.message ||
                "No waiting patients."
            );
        }


        loadQueue();


    } catch (error) {

        console.error(error);


        alert(
            "Cannot connect to FastAPI.\n\n" +
            "Make sure the backend is running."
        );
    }
}



// ===============================
// GOOGLE MAPS
// ===============================

let hospitalMap;

let hospitalMarker;



function initMap() {

    const defaultLocation = {
        lat: 17.3850,
        lng: 78.4867
    };


    hospitalMap =
        new google.maps.Map(
            document.getElementById("map"),
            {
                center: defaultLocation,
                zoom: 13
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
        function(event) {

            updateHospitalLocation(
                event.latLng.lat(),
                event.latLng.lng()
            );

        }
    );


    hospitalMap.addListener(
        "click",
        function(event) {

            hospitalMarker.setPosition(
                event.latLng
            );


            updateHospitalLocation(
                event.latLng.lat(),
                event.latLng.lng()
            );

        }
    );
}



function updateHospitalLocation(
    latitude,
    longitude
) {

    const latElement =
        document.getElementById(
            "latitude"
        );


    const lngElement =
        document.getElementById(
            "longitude"
        );


    if (latElement) {

        latElement.innerText =
            latitude.toFixed(6);
    }


    if (lngElement) {

        lngElement.innerText =
            longitude.toFixed(6);
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



// ===============================
// PAGE LOADING
// ===============================

if (
    window.location.pathname.includes(
        "dashboard.html"
    )
) {

    loadHospitalDashboard();
}


if (
    window.location.pathname.includes(
        "doctors.html"
    )
) {

    loadDoctors();
}


if (
    window.location.pathname.includes(
        "patients.html"
    )
) {

    loadPatients();
}


if (
    window.location.pathname.includes(
        "profile.html"
    )
) {

    loadProfile();
}