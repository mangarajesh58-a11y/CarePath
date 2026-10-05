// =========================================================
// CarePath - HOSPITAL APP SCRIPT
// =========================================================

const API =
    "https://carepath-3q9q.onrender.com";

const FRONTEND =
    "https://carepath-hospital-ten.vercel.app";


// =========================================================
// LOCAL STORAGE
// =========================================================

function getHospitalId() {

    return (
        localStorage.getItem("hospital_id") ||
        localStorage.getItem("hospitalId") ||
        null
    );
}


function getHospitalToken() {

    return localStorage.getItem(
        "hospitalToken"
    );
}


function getHospitalAuthHeaders(
    includeJson = false
) {

    const token =
        getHospitalToken();

    const headers = {};

    if (token) {

        headers.Authorization =
            `Bearer ${token}`;

    }

    if (includeJson) {

        headers["Content-Type"] =
            "application/json";

    }

    return headers;
}


function getHospitalData() {

    try {

        const data =
            localStorage.getItem(
                "hospital"
            );

        if (!data) {

            return null;

        }

        return JSON.parse(data);

    } catch (error) {

        console.error(
            "Hospital data error:",
            error
        );

        return null;

    }

}


function saveHospitalData(
    hospital
) {

    if (
        !hospital ||
        !hospital.id
    ) {

        console.error(
            "Invalid hospital data:",
            hospital
        );

        return;

    }


    const id =
        String(hospital.id);


    localStorage.setItem(
        "hospital",
        JSON.stringify(hospital)
    );


    localStorage.setItem(
        "hospital_id",
        id
    );


    localStorage.setItem(
        "hospitalId",
        id
    );


    localStorage.setItem(
        "hospital_name",
        hospital.name || ""
    );


    localStorage.setItem(
        "hospital_email",
        hospital.email || ""
    );


    localStorage.setItem(
        "hospital_phone",
        hospital.phone || ""
    );


    localStorage.setItem(
        "hospital_city",
        hospital.city || ""
    );


    localStorage.setItem(
        "hospital_token_fee",
        String(
            hospital.token_fee ?? 0
        )
    );


    localStorage.setItem(
        "hospital_approval_status",
        hospital.approval_status || ""
    );


    localStorage.setItem(
        "hospital_is_published",
        String(
            hospital.is_published ?? false
        )
    );

}


function clearHospitalData() {

    const keys = [

        "hospital",

        "hospital_id",

        "hospitalId",

        "hospital_name",

        "hospital_email",

        "hospital_phone",

        "hospital_city",

        "hospital_token_fee",

        "hospital_approval_status",

        "hospital_is_published",

        "hospital_latitude",

        "hospital_longitude",

        "hospitalLocation"

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
// RESPONSE HELPERS
// =========================================================

function getErrorMessage(
    data,
    defaultMessage = "Something went wrong."
) {

    if (!data) {

        return defaultMessage;

    }


    if (
        typeof data.detail ===
        "string"
    ) {

        return data.detail;

    }


    if (
        Array.isArray(
            data.detail
        )
    ) {

        return data.detail
            .map(
                function (error) {

                    if (
                        typeof error ===
                        "string"
                    ) {

                        return error;

                    }


                    if (
                        error &&
                        typeof error ===
                        "object"
                    ) {

                        const location =
                            Array.isArray(
                                error.loc
                            )
                                ? error.loc.join(
                                    " → "
                                )
                                : "";


                        const message =
                            error.msg ||
                            error.message ||
                            "Invalid value";


                        return location
                            ? `${location}: ${message}`
                            : message;

                    }


                    return String(
                        error
                    );

                }
            )
            .join("\n");

    }


    if (
        data.detail &&
        typeof data.detail ===
        "object"
    ) {

        return (
            data.detail.msg ||
            data.detail.message ||
            JSON.stringify(
                data.detail
            )
        );

    }


    if (
        typeof data.message ===
        "string"
    ) {

        return data.message;

    }


    return defaultMessage;

}


async function readJsonResponse(
    response
) {

    const text =
        await response.text();


    if (!text) {

        return {};

    }


    try {

        return JSON.parse(
            text
        );

    } catch (error) {

        return {
            detail: text
        };

    }

}


function getHospitalFromResponse(
    data
) {

    if (
        data &&
        data.hospital &&
        typeof data.hospital ===
        "object"
    ) {

        return data.hospital;

    }


    return data;

}


// =========================================================
// AUTH ERROR HANDLING
// =========================================================

function handleHospitalAuthFailure(
    response
) {

    if (
        response.status === 401 ||
        response.status === 403
    ) {

        alert(
            "Your hospital session has expired or is not authorized. Please login again."
        );

        hospitalLogout();

        return true;

    }

    return false;

}


// =========================================================
// BACKEND CONNECTION
// =========================================================

async function checkBackend() {

    /*
     * Do not call a public API endpoint
     * unnecessarily on every hospital page.
     *
     * /health is enough to check whether
     * the backend is alive.
     */

    try {

        const response =
            await fetch(
                `${API}/health`
            );


        if (!response.ok) {

            throw new Error(
                "Backend health check failed."
            );

        }


        const data =
            await readJsonResponse(
                response
            );


        console.log(
            "CarePath backend is healthy:",
            data
        );


        return true;

    } catch (error) {

        console.error(
            "BACKEND CONNECTION ERROR:",
            error
        );

        return false;

    }

}


// =========================================================
// HOSPITAL LOGIN CHECK
// =========================================================

function requireHospitalLogin() {

    const hospitalId =
        getHospitalId();

    const hospitalToken =
        getHospitalToken();


    if (
        !hospitalId ||
        !hospitalToken
    ) {

        alert(
            "Your session is missing or expired. Please login again."
        );


        localStorage.removeItem(
            "hospitalToken"
        );


        clearHospitalData();


        window.location.replace(
            "index.html"
        );


        return null;

    }


    return hospitalId;

}


// =========================================================
// GOOGLE LOGIN
// =========================================================

async function handleHospitalGoogleLogin(
    response
) {

    console.log(
        "Hospital Google Login Response:",
        response
    );


    if (
        !response ||
        !response.credential
    ) {

        alert(
            "Google login failed. No credential received."
        );

        return;

    }


    try {

        const result =
            await fetch(
                `${API}/hospitals/google-login`,
                {

                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({

                            credential:
                                response.credential

                        })

                }
            );


        const data =
            await readJsonResponse(
                result
            );


        if (!result.ok) {

            throw new Error(
                getErrorMessage(
                    data,
                    "Google hospital login failed."
                )
            );

        }


        const hospital =
            getHospitalFromResponse(
                data
            );


        if (
            !hospital ||
            !hospital.id
        ) {

            throw new Error(
                "Hospital information was not returned by the server."
            );

        }


        if (
            !data.access_token
        ) {

            throw new Error(
                "Login succeeded, but the authentication token was not returned."
            );

        }


        localStorage.setItem(
            "hospitalToken",
            data.access_token
        );


        saveHospitalData(
            hospital
        );


        alert(
            "Google login successful."
        );


        window.location.replace(
            "dashboard.html"
        );


    } catch (error) {

        console.error(
            "GOOGLE HOSPITAL LOGIN ERROR:",
            error
        );


        alert(
            error.message ||
            "Google login failed."
        );

    }

}


// =========================================================
// NORMAL HOSPITAL LOGIN
// =========================================================

async function hospitalLogin(
    event
) {

    if (event) {

        event.preventDefault();

    }


    const emailInput =
        document.getElementById("email") ||
        document.getElementById(
            "hospitalEmail"
        );


    const passwordInput =
        document.getElementById("password") ||
        document.getElementById(
            "hospitalPassword"
        );


    if (!emailInput) {

        alert(
            "Hospital email input not found."
        );

        return;

    }


    if (!passwordInput) {

        alert(
            "Hospital password input not found."
        );

        return;

    }


    const email =
        emailInput.value
            .trim()
            .toLowerCase();


    const password =
        passwordInput.value;


    if (!email) {

        alert(
            "Please enter hospital email."
        );

        return;

    }


    if (!password) {

        alert(
            "Please enter password."
        );

        return;

    }


    try {

        const response =
            await fetch(
                `${API}/hospitals/login`,
                {

                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({

                            email,
                            password

                        })

                }
            );


        const data =
            await readJsonResponse(
                response
            );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                    data,
                    "Hospital login failed."
                )
            );

        }


        const hospital =
            getHospitalFromResponse(
                data
            );


        if (
            !hospital ||
            !hospital.id
        ) {

            throw new Error(
                "Hospital information was not returned by the server."
            );

        }


        if (
            !data.access_token
        ) {

            throw new Error(
                "Login succeeded, but the authentication token was not returned."
            );

        }


        localStorage.setItem(
            "hospitalToken",
            data.access_token
        );


        saveHospitalData(
            hospital
        );


        alert(
            "Hospital login successful."
        );


        window.location.replace(
            "dashboard.html"
        );


    } catch (error) {

        console.error(
            "HOSPITAL LOGIN ERROR:",
            error
        );


        alert(
            error.message ||
            "Hospital login failed."
        );

    }

}


// =========================================================
// LOGOUT
// =========================================================

function hospitalLogout() {

    const keys = [

        "hospital",

        "hospital_id",

        "hospitalId",

        "hospital_name",

        "hospital_email",

        "hospital_phone",

        "hospital_city",

        "hospital_token_fee",

        "hospital_approval_status",

        "hospital_is_published",

        "hospital_latitude",

        "hospital_longitude",

        "hospitalLocation",

        "hospital_logged_in",

        "hospitalToken"

    ];


    keys.forEach(
        function (key) {

            localStorage.removeItem(
                key
            );

        }
    );


    window.location.replace(
        "index.html"
    );

}


// =========================================================
// NAVIGATION
// =========================================================

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


// =========================================================
// LOAD HOSPITAL PROFILE
// =========================================================

async function loadProfile() {

    const hospitalId =
        requireHospitalLogin();


    if (!hospitalId) {

        return;

    }


    try {

        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}`,
                {
                    headers:
                        getHospitalAuthHeaders()
                }
            );


        if (
            handleHospitalAuthFailure(
                response
            )
        ) {

            return;

        }


        const data =
            await readJsonResponse(
                response
            );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                    data,
                    "Unable to load hospital profile."
                )
            );

        }


        const hospital =
            getHospitalFromResponse(
                data
            );


        if (
            !hospital ||
            !hospital.id
        ) {

            throw new Error(
                "Hospital profile data was not returned."
            );

        }


        saveHospitalData(
            hospital
        );


        const fields = {

            profileName:
                hospital.name,

            profileEmail:
                hospital.email,

            profilePhone:
                hospital.phone,

            profileCity:
                hospital.city,

            profileAddress:
                hospital.address,

            profileDescription:
                hospital.description,

            profileLicense:
                hospital.license_id,

            profileTokenFee:
                hospital.token_fee

        };


        Object.keys(fields).forEach(
            function (id) {

                const element =
                    document.getElementById(
                        id
                    );


                if (element) {

                    element.value =
                        fields[id] ?? "";

                }

            }
        );


        updatePaymentStatus(
            hospital.payment_account_status
        );


        const latitude =
            document.getElementById(
                "hospitalLatitude"
            );


        const longitude =
            document.getElementById(
                "hospitalLongitude"
            );


        if (latitude) {

            latitude.value =
                hospital.latitude ?? "";

        }


        if (longitude) {

            longitude.value =
                hospital.longitude ?? "";

        }


    } catch (error) {

        console.error(
            "LOAD PROFILE ERROR:",
            error
        );


        alert(
            error.message ||
            "Unable to load hospital profile."
        );

    }

}


// =========================================================
// PAYMENT STATUS
// =========================================================

function formatPaymentStatus(
    status
) {

    if (!status) {

        return "Not Added";

    }


    switch (
        String(status).toUpperCase()
    ) {

        case "NOT_ADDED":
            return "Not Added";

        case "PENDING":
        case "PENDING_VERIFICATION":
            return "Pending Verification";

        case "APPROVED":
            return "Approved";

        case "VERIFIED":
            return "Verified";

        case "REJECTED":
            return "Rejected";

        default:
            return status;

    }

}


function updatePaymentStatus(
    status
) {

    const element =
        document.getElementById(
            "paymentAccountStatus"
        );


    if (!element) {

        return;

    }


    const finalStatus =
        status || "NOT_ADDED";


    element.textContent =
        "Payment account status: " +
        formatPaymentStatus(
            finalStatus
        );


    element.className =
        "payment-status " +
        String(finalStatus)
            .toLowerCase();

}


// =========================================================
// SAVE PROFILE
// =========================================================

async function saveProfile(
    event
) {

    if (event) {

        event.preventDefault();

    }


    const hospitalId =
        requireHospitalLogin();


    if (!hospitalId) {

        return;

    }


    const name =
        document.getElementById(
            "profileName"
        )?.value.trim();


    const email =
        document.getElementById(
            "profileEmail"
        )?.value.trim().toLowerCase();


    const phone =
        document.getElementById(
            "profilePhone"
        )?.value.trim();


    const city =
        document.getElementById(
            "profileCity"
        )?.value.trim();


    const address =
        document.getElementById(
            "profileAddress"
        )?.value.trim();


    const description =
        document.getElementById(
            "profileDescription"
        )?.value.trim();


    const tokenFeeInput =
        document.getElementById(
            "profileTokenFee"
        )?.value;


    const tokenFee =
        Number(
            tokenFeeInput || 0
        );


    if (!name) {

        alert(
            "Please enter hospital name."
        );

        return;

    }


    if (!email) {

        alert(
            "Please enter hospital email."
        );

        return;

    }


    if (!phone) {

        alert(
            "Please enter hospital phone number."
        );

        return;

    }


    if (!city) {

        alert(
            "Please enter city."
        );

        return;

    }


    if (!address) {

        alert(
            "Please enter hospital address."
        );

        return;

    }


    if (
        !Number.isFinite(tokenFee) ||
        tokenFee < 0
    ) {

        alert(
            "Token fee must be 0 or greater."
        );

        return;

    }


    try {

        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}`,
                {

                    method: "PUT",

                    headers:
                        getHospitalAuthHeaders(
                            true
                        ),

                    body:
                        JSON.stringify({

                            name,

                            email,

                            phone,

                            city,

                            address,

                            description:
                                description || "",

                            token_fee:
                                tokenFee

                        })

                }
            );


        if (
            handleHospitalAuthFailure(
                response
            )
        ) {

            return;

        }


        const data =
            await readJsonResponse(
                response
            );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                    data,
                    "Unable to update hospital profile."
                )
            );

        }


        const hospital =
            getHospitalFromResponse(
                data
            );


        const oldHospital =
            getHospitalData() || {};


        const updatedHospital = {

            ...oldHospital,

            ...(hospital || {}),

            id:
                hospital?.id ||
                hospitalId,

            name:
                hospital?.name ??
                name,

            email:
                hospital?.email ??
                email,

            phone:
                hospital?.phone ??
                phone,

            city:
                hospital?.city ??
                city,

            address:
                hospital?.address ??
                address,

            description:
                hospital?.description ??
                description,

            token_fee:
                hospital?.token_fee ??
                tokenFee

        };


        saveHospitalData(
            updatedHospital
        );


        alert(
            "Hospital profile updated successfully."
        );


    } catch (error) {

        console.error(
            "SAVE PROFILE ERROR:",
            error
        );


        alert(
            error.message ||
            "Unable to update hospital profile."
        );

    }

}


// =========================================================
// SAVE PAYMENT ACCOUNT
// =========================================================

async function savePaymentAccount() {

    const hospitalId =
        requireHospitalLogin();


    if (!hospitalId) {

        return;

    }


    const accountName =
        document.getElementById(
            "paymentAccountName"
        )?.value.trim();


    const accountNumber =
        document.getElementById(
            "paymentAccountNumber"
        )?.value.trim();


    const confirmAccountNumber =
        document.getElementById(
            "paymentConfirmAccountNumber"
        )?.value.trim();


    const ifsc =
        document.getElementById(
            "paymentIfsc"
        )?.value.trim().toUpperCase();


    const upi =
        document.getElementById(
            "paymentUpi"
        )?.value.trim().toLowerCase();


    if (
        !accountNumber &&
        !upi
    ) {

        alert(
            "Please enter a bank account number or UPI ID."
        );

        return;

    }


    if (accountNumber) {

        if (!accountName) {

            alert(
                "Please enter account holder name."
            );

            return;

        }


        if (!confirmAccountNumber) {

            alert(
                "Please confirm your bank account number."
            );

            return;

        }


        if (
            accountNumber !==
            confirmAccountNumber
        ) {

            alert(
                "Bank account numbers do not match."
            );

            return;

        }


        if (
            !/^[0-9]+$/.test(
                accountNumber
            )
        ) {

            alert(
                "Bank account number must contain only numbers."
            );

            return;

        }


        if (
            accountNumber.length < 9 ||
            accountNumber.length > 18
        ) {

            alert(
                "Please enter a valid bank account number."
            );

            return;

        }


        if (!ifsc) {

            alert(
                "Please enter IFSC code."
            );

            return;

        }


        if (
            !/^[A-Z]{4}0[A-Z0-9]{6}$/.test(
                ifsc
            )
        ) {

            alert(
                "Please enter a valid IFSC code."
            );

            return;

        }

    }


    if (upi) {

        if (
            !/^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+$/.test(
                upi
            )
        ) {

            alert(
                "Please enter a valid UPI ID."
            );

            return;

        }

    }


    try {

        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}/payment-account`,
                {

                    method: "PUT",

                    headers:
                        getHospitalAuthHeaders(
                            true
                        ),

                    body:
                        JSON.stringify({

                            account_name:
                                accountName || "",

                            account_number:
                                accountNumber || "",

                            ifsc:
                                ifsc || "",

                            upi:
                                upi || ""

                        })

                }
            );


        if (
            handleHospitalAuthFailure(
                response
            )
        ) {

            return;

        }


        const data =
            await readJsonResponse(
                response
            );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                    data,
                    "Unable to save payment account."
                )
            );

        }


        const paymentAccount =
            data.payment_account ||
            data.paymentAccount ||
            {};


        const status =
            paymentAccount.status ||
            paymentAccount.payment_account_status ||
            data.payment_account_status ||
            data.status ||
            "PENDING_VERIFICATION";


        updatePaymentStatus(
            status
        );


        alert(
            "Payment account saved successfully. It is now pending verification."
        );


    } catch (error) {

        console.error(
            "SAVE PAYMENT ACCOUNT ERROR:",
            error
        );


        alert(
            error.message ||
            "Unable to save payment account."
        );

    }

}


// =========================================================
// GOOGLE MAP
// =========================================================

let hospitalMap = null;

let hospitalMarker = null;


// =========================================================
// INITIALIZE MAP
// =========================================================

function initMap() {

    const mapElement =
        document.getElementById(
            "map"
        );


    if (!mapElement) {

        return;

    }


    if (
        typeof google === "undefined" ||
        !google.maps
    ) {

        console.error(
            "Google Maps API is not loaded."
        );

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


    hospitalMap.addListener(
        "click",
        function (event) {

            if (
                event &&
                event.latLng
            ) {

                setHospitalLocation(

                    event.latLng.lat(),

                    event.latLng.lng()

                );

            }

        }
    );


    loadSavedHospitalLocation();

}


// =========================================================
// LOAD SAVED LOCATION
// =========================================================

function loadSavedHospitalLocation() {

    const hospital =
        getHospitalData();


    if (
        hospital &&
        hospital.latitude !== null &&
        hospital.latitude !== undefined &&
        hospital.longitude !== null &&
        hospital.longitude !== undefined
    ) {

        const lat =
            Number(
                hospital.latitude
            );


        const lng =
            Number(
                hospital.longitude
            );


        if (
            Number.isFinite(lat) &&
            Number.isFinite(lng)
        ) {

            setHospitalLocation(
                lat,
                lng
            );

            return;

        }

    }


    try {

        const saved =
            JSON.parse(
                localStorage.getItem(
                    "hospitalLocation"
                )
            );


        if (
            saved &&
            saved.latitude !== undefined &&
            saved.longitude !== undefined
        ) {

            const lat =
                Number(
                    saved.latitude
                );


            const lng =
                Number(
                    saved.longitude
                );


            if (
                Number.isFinite(lat) &&
                Number.isFinite(lng)
            ) {

                setHospitalLocation(
                    lat,
                    lng
                );

            }

        }


    } catch (error) {

        console.error(
            "LOCATION LOAD ERROR:",
            error
        );

    }

}


// =========================================================
// SET HOSPITAL LOCATION
// =========================================================

function setHospitalLocation(
    latitude,
    longitude
) {

    if (!hospitalMap) {

        console.log(
            "Google Map is not ready."
        );

        return;

    }


    const lat =
        Number(latitude);


    const lng =
        Number(longitude);


    if (
        !Number.isFinite(lat) ||
        !Number.isFinite(lng)
    ) {

        alert(
            "Invalid hospital location."
        );

        return;

    }


    const position = {

        lat,
        lng

    };


    hospitalMap.setCenter(
        position
    );


    hospitalMap.setZoom(
        16
    );


    if (hospitalMarker) {

        hospitalMarker.setPosition(
            position
        );

    } else {

        hospitalMarker =
            new google.maps.Marker({

                position,

                map:
                    hospitalMap,

                title:
                    "Hospital Location"

            });

    }


    const latitudeInput =
        document.getElementById(
            "hospitalLatitude"
        );


    const longitudeInput =
        document.getElementById(
            "hospitalLongitude"
        );


    if (latitudeInput) {

        latitudeInput.value =
            lat;

    }


    if (longitudeInput) {

        longitudeInput.value =
            lng;

    }

}


// =========================================================
// SEARCH HOSPITAL LOCATION
// =========================================================

function searchHospitalLocation() {

    const locationInput =
        document.getElementById(
            "hospitalLocation"
        );


    if (!locationInput) {

        return;

    }


    const address =
        locationInput.value.trim();


    if (!address) {

        alert(
            "Please enter a hospital location."
        );

        return;

    }


    if (
        typeof google === "undefined" ||
        !google.maps
    ) {

        alert(
            "Google Maps is not loaded yet."
        );

        return;

    }


    const geocoder =
        new google.maps.Geocoder();


    geocoder.geocode(

        {
            address
        },

        function (
            results,
            status
        ) {

            if (
                status !== "OK" ||
                !results ||
                !results.length
            ) {

                alert(
                    "Location not found. Please try another address."
                );

                return;

            }


            const location =
                results[0]
                    .geometry
                    .location;


            setHospitalLocation(

                location.lat(),

                location.lng()

            );

        }

    );

}


// =========================================================
// SAVE HOSPITAL LOCATION
// =========================================================

async function saveHospitalLocation() {

    const hospitalId =
        requireHospitalLogin();


    if (!hospitalId) {

        return;

    }


    const latitude =
        document.getElementById(
            "hospitalLatitude"
        )?.value;


    const longitude =
        document.getElementById(
            "hospitalLongitude"
        )?.value;


    if (
        latitude === undefined ||
        longitude === undefined ||
        latitude === "" ||
        longitude === ""
    ) {

        alert(
            "Please select a hospital location on the map first."
        );

        return;

    }


    const locationData = {

        latitude:
            Number(latitude),

        longitude:
            Number(longitude)

    };


    if (
        !Number.isFinite(
            locationData.latitude
        ) ||
        !Number.isFinite(
            locationData.longitude
        )
    ) {

        alert(
            "Invalid hospital location."
        );

        return;

    }


    try {

        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}/location`,
                {

                    method: "PUT",

                    headers:
                        getHospitalAuthHeaders(
                            true
                        ),

                    body:
                        JSON.stringify(
                            locationData
                        )

                }
            );


        if (
            handleHospitalAuthFailure(
                response
            )
        ) {

            return;

        }


        const data =
            await readJsonResponse(
                response
            );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                    data,
                    "Hospital location could not be saved."
                )
            );

        }


        localStorage.setItem(
            "hospitalLocation",
            JSON.stringify(
                locationData
            )
        );


        const hospital =
            getHospitalFromResponse(
                data
            );


        if (
            hospital &&
            hospital.id
        ) {

            saveHospitalData(
                hospital
            );

        }


        alert(
            "Hospital location saved successfully."
        );


    } catch (error) {

        console.error(
            "SAVE LOCATION ERROR:",
            error
        );


        alert(
            error.message ||
            "Unable to save hospital location."
        );

    }

}


// =========================================================
// LOAD DOCTORS
// =========================================================

async function loadDoctors() {

    const hospitalId =
        requireHospitalLogin();


    if (!hospitalId) {

        return;

    }


    const container =
        document.getElementById(
            "doctorsList"
        );


    if (!container) {

        return;

    }


    container.innerHTML =
        "<p>Loading doctors...</p>";


    try {

        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}/doctors`,
                {
                    headers:
                        getHospitalAuthHeaders()
                }
            );


        if (
            handleHospitalAuthFailure(
                response
            )
        ) {

            return;

        }


        const data =
            await readJsonResponse(
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


        const doctors =
            Array.isArray(data)
                ? data
                : (
                    Array.isArray(
                        data.doctors
                    )
                        ? data.doctors
                        : []
                );


        container.innerHTML = "";


        if (
            doctors.length === 0
        ) {

            container.innerHTML =
                "<p>No doctors added yet.</p>";

            return;

        }


        doctors.forEach(
            function (doctor) {

                const card =
                    document.createElement(
                        "div"
                    );


                card.className =
                    "doctor-card";


                const days =
                    doctor.available_days
                        ? doctor.available_days
                            .split(",")
                            .map(
                                day =>
                                    day.trim()
                            )
                            .filter(
                                Boolean
                            )
                            .join(", ")
                        : "Not specified";


                const startTime =
                    doctor.start_time ||
                    "";


                const endTime =
                    doctor.end_time ||
                    "";


                const consultationHours =
                    startTime &&
                    endTime
                        ? `${startTime} - ${endTime}`
                        : "Not specified";


                const available =
                    doctor.is_available !==
                    false;


                const statusText =
                    available
                        ? "Available"
                        : "Unavailable";


                const statusClass =
                    available
                        ? "doctor-available"
                        : "doctor-unavailable";


                card.innerHTML = `

                    <h3>
                        ${escapeHtml(
                            doctor.name ||
                            "Doctor"
                        )}
                    </h3>

                    <p>
                        <strong>
                            Department:
                        </strong>
                        ${escapeHtml(
                            doctor.department ||
                            "Not specified"
                        )}
                    </p>

                    <p>
                        <strong>
                            Specialization:
                        </strong>
                        ${escapeHtml(
                            doctor.specialization ||
                            "Not specified"
                        )}
                    </p>

                    <p>
                        <strong>
                            Experience:
                        </strong>
                        ${escapeHtml(
                            doctor.experience ||
                            "Not specified"
                        )}
                    </p>

                    <p>
                        <strong>
                            Available Days:
                        </strong>
                        ${escapeHtml(
                            days
                        )}
                    </p>

                    <p>
                        <strong>
                            Consultation Hours:
                        </strong>
                        ${escapeHtml(
                            consultationHours
                        )}
                    </p>

                    <p>
                        <strong>
                            Status:
                        </strong>

                        <span
                            class="${statusClass}"
                        >
                            ${statusText}
                        </span>
                    </p>

                    <button
                        type="button"
                        onclick="deleteDoctor(${Number(
                            doctor.id
                        )})"
                    >
                        Delete
                    </button>

                `;


                container.appendChild(
                    card
                );

            }
        );


    } catch (error) {

        console.error(
            "LOAD DOCTORS ERROR:",
            error
        );


        container.innerHTML =
            `<p>${escapeHtml(
                error.message ||
                "Unable to load doctors."
            )}</p>`;

    }

}


// =========================================================
// DELETE DOCTOR
// =========================================================

async function deleteDoctor(
    doctorId
) {

    const hospitalId =
        requireHospitalLogin();


    if (!hospitalId) {

        return;

    }


    if (!doctorId) {

        return;

    }


    const confirmed =
        confirm(
            "Are you sure you want to delete this doctor?"
        );


    if (!confirmed) {

        return;

    }


    try {

        const response =
            await fetch(
                `${API}/doctors/${doctorId}`,
                {

                    method: "DELETE",

                    headers:
                        getHospitalAuthHeaders()

                }
            );


        if (
            handleHospitalAuthFailure(
                response
            )
        ) {

            return;

        }


        const data =
            await readJsonResponse(
                response
            );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                    data,
                    "Unable to delete doctor."
                )
            );

        }


        alert(
            "Doctor deleted successfully."
        );


        await loadDoctors();


    } catch (error) {

        console.error(
            "DELETE DOCTOR ERROR:",
            error
        );


        alert(
            error.message ||
            "Unable to delete doctor."
        );

    }

}


// =========================================================
// ADD DOCTOR
// =========================================================

async function addDoctor() {

    const hospitalId =
        requireHospitalLogin();


    if (!hospitalId) {

        return;

    }


    const name =
        document.getElementById(
            "doctorName"
        )?.value.trim();


    const department =
        document.getElementById(
            "doctorDepartment"
        )?.value.trim();


    const specialization =
        document.getElementById(
            "doctorSpecialization"
        )?.value.trim();


    const experience =
        document.getElementById(
            "doctorExperience"
        )?.value.trim();


    const availableDays =
        Array.from(
            document.querySelectorAll(
                'input[name="doctorAvailableDays"]:checked'
            )
        ).map(
            function (checkbox) {

                return checkbox.value;

            }
        );


    const startTime =
        document.getElementById(
            "doctorStartTime"
        )?.value || "";


    const endTime =
        document.getElementById(
            "doctorEndTime"
        )?.value || "";


    const isAvailable =
        document.getElementById(
            "doctorIsAvailable"
        )?.value === "true";


    if (!name) {

        alert(
            "Please enter doctor name."
        );

        return;

    }


    if (!department) {

        alert(
            "Please enter doctor department."
        );

        return;

    }


    if (
        availableDays.length === 0
    ) {

        alert(
            "Please select at least one available day."
        );

        return;

    }


    if (
        !startTime ||
        !endTime
    ) {

        alert(
            "Please select consultation start and end times."
        );

        return;

    }


    if (
        startTime >= endTime
    ) {

        alert(
            "End time must be later than start time."
        );

        return;

    }


    try {

        const response =
            await fetch(
                `${API}/hospitals/${hospitalId}/doctors`,
                {

                    method: "POST",

                    headers:
                        getHospitalAuthHeaders(
                            true
                        ),

                    body:
                        JSON.stringify({

                            name,

                            department,

                            specialization:
                                specialization || "",

                            experience:
                                experience || "",

                            available_days:
                                availableDays.join(","),

                            start_time:
                                startTime,

                            end_time:
                                endTime,

                            is_available:
                                isAvailable

                        })

                }
            );


        if (
            handleHospitalAuthFailure(
                response
            )
        ) {

            return;

        }


        const data =
            await readJsonResponse(
                response
            );


        if (!response.ok) {

            throw new Error(
                getErrorMessage(
                    data,
                    "Unable to add doctor."
                )
            );

        }


        alert(
            "Doctor added successfully."
        );


        [
            "doctorName",

            "doctorDepartment",

            "doctorSpecialization",

            "doctorExperience",

            "doctorStartTime",

            "doctorEndTime"

        ].forEach(
            function (id) {

                const element =
                    document.getElementById(
                        id
                    );


                if (element) {

                    element.value = "";

                }

            }
        );


        document
            .querySelectorAll(
                'input[name="doctorAvailableDays"]'
            )
            .forEach(
                function (checkbox) {

                    checkbox.checked =
                        false;

                }
            );


        const statusElement =
            document.getElementById(
                "doctorIsAvailable"
            );


        if (statusElement) {

            statusElement.value =
                "true";

        }


        await loadDoctors();


    } catch (error) {

        console.error(
            "ADD DOCTOR ERROR:",
            error
        );


        alert(
            error.message ||
            "Unable to add doctor."
        );

    }

}


// =========================================================
// HTML ESCAPE
// =========================================================

function escapeHtml(
    value
) {

    if (
        value === null ||
        value === undefined
    ) {

        return "";

    }


    return String(value)

        .replace(
            /&/g,
            "&amp;"
        )

        .replace(
            /</g,
            "&lt;"
        )

        .replace(
            />/g,
            "&gt;"
        )

        .replace(
            /"/g,
            "&quot;"
        )

        .replace(
            /'/g,
            "&#039;"
        );

}


// =========================================================
// PAGE LOAD
// =========================================================

document.addEventListener(
    "DOMContentLoaded",
    function () {

        const loginForm =
            document.getElementById(
                "hospitalLoginForm"
            );


        if (loginForm) {

            loginForm.addEventListener(
                "submit",
                hospitalLogin
            );

        }


        if (
            document.getElementById(
                "profileName"
            )
        ) {

            loadProfile();

        }


        if (
            document.getElementById(
                "doctorsList"
            )
        ) {

            loadDoctors();

        }


        checkBackend();

    }
);