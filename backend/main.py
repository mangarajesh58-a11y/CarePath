# ============================================================
# CarePath - FastAPI Backend
# ============================================================

import os
import hmac
import hashlib
import secrets
import uuid
import smtplib
from email.message import EmailMessage

from datetime import datetime,date, timedelta
from typing import Optional

import razorpay

from dotenv import load_dotenv

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
)

from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    inspect,
    text,
    func,
)

from sqlalchemy.orm import Session

from passlib.context import CryptContext

from database import Base, engine, SessionLocal

from models import (
    Patient,
    Hospital,
    Doctor,
    Token,
    Admin,
    RegistrationOTP,
)
from fastapi.responses import FileResponse

import mimetypes

# ============================================================
# ENVIRONMENT
# ============================================================

# ============================================================
# ENVIRONMENT
# ============================================================

from pathlib import Path

# Load the .env file located in the same folder as main.py
ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=False)

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

# Check configuration without displaying secret values
print("Environment file exists:", ENV_FILE.is_file())
print("Razorpay Key ID loaded:", bool(RAZORPAY_KEY_ID))
print("Razorpay Key Secret loaded:", bool(RAZORPAY_KEY_SECRET))
print("Google Client ID loaded:", bool(GOOGLE_CLIENT_ID))


# ============================================================
# SETTINGS
# ============================================================

PLATFORM_FEE = 10

PLATFORM_NAME = "CarePath"

# ============================================================
# HOSPITAL CERTIFICATE UPLOAD
# ============================================================

UPLOAD_DIR = os.path.join(
    os.path.dirname(__file__),
    "uploads",
    "hospital_certificates",
)

os.makedirs(
    UPLOAD_DIR,
    exist_ok=True,
)

ALLOWED_CERTIFICATE_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}

MAX_CERTIFICATE_SIZE = 10 * 1024 * 1024  # 10 MB

# Public hospital photos used on the patient browsing cards.
HOSPITAL_PHOTO_DIR = os.path.join(
    os.path.dirname(__file__),
    "uploads",
    "hospital_photos",
)
os.makedirs(HOSPITAL_PHOTO_DIR, exist_ok=True)

ALLOWED_HOSPITAL_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_HOSPITAL_PHOTO_SIZE = 5 * 1024 * 1024  # 5 MB


# ============================================================
# PASSWORD HASHING
# ============================================================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


def hash_password(password: str):

    return pwd_context.hash(password)


def verify_password(
    password: str,
    hashed_password: str,
):

    try:

        return pwd_context.verify(
            password,
            hashed_password,
        )

    except Exception:

        return False


# ============================================================
# RAZORPAY
# ============================================================

razorpay_client = None

if (
    RAZORPAY_KEY_ID
    and RAZORPAY_KEY_SECRET
    and RAZORPAY_KEY_ID != "YOUR_RAZORPAY_KEY_ID"
    and RAZORPAY_KEY_SECRET != "YOUR_RAZORPAY_KEY_SECRET"
):

    razorpay_client = razorpay.Client(
        auth=(
            RAZORPAY_KEY_ID,
            RAZORPAY_KEY_SECRET,
        )
    )


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="CarePath API",
    version="11.0.0",
)
# Keep hospital certificates in a private folder.
# Do not expose certificates through a public static URL.
CERTIFICATE_DIR = os.path.join(
    os.path.dirname(__file__),
    "uploads",
    "hospital_certificates",
)

os.makedirs(CERTIFICATE_DIR, exist_ok=True)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "https://carepath-patient-mx5v.vercel.app",
        "https://carepath-hospital-ten.vercel.app",
        "https://carepath-admin.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
def send_otp_email(receiver_email: str, otp: str):
    sender_email = os.getenv("SMTP_EMAIL")
    app_password = os.getenv("SMTP_APP_PASSWORD")

    if not sender_email or not app_password:
        raise RuntimeError(
            "SMTP_EMAIL or SMTP_APP_PASSWORD is missing."
        )

    message = EmailMessage()
    message["Subject"] = "CarePath Registration OTP"
    message["From"] = sender_email
    message["To"] = receiver_email

    message.set_content(
        f"""Hello,

Your CarePath registration verification code is: {otp}

This code expires in 5 minutes.

If you did not request this code, please ignore this email.

CarePath Team
"""
    )

    try:
        with smtplib.SMTP(
            "smtp.gmail.com", 587, timeout=20
        ) as server:
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(message)

    except Exception as exc:
        logging.exception("Gmail SMTP email sending failed")
        raise RuntimeError(
            f"Unable to send OTP email: {exc}"
        ) from exc
# ============================================================
# DATABASE SESSION
# ============================================================

def get_db():

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()


# ============================================================
# CREATE TABLES
# ============================================================

Base.metadata.create_all(
    bind=engine
)


# ============================================================
# DATABASE MIGRATION
# ============================================================

def add_column_if_missing(
    table_name,
    column_name,
    column_definition,
):

    inspector = inspect(engine)

    existing_columns = {
        column["name"]
        for column in inspector.get_columns(
            table_name
        )
    }

    if column_name in existing_columns:

        return

    with engine.begin() as connection:

        connection.execute(
            text(
                f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name}
                {column_definition}
                """
            )
        )


def run_database_migration():
    

    # --------------------------------------------------------
    # HOSPITALS
    # --------------------------------------------------------

    hospital_columns = {

    "image_url":
        "VARCHAR(500) NULL",

    "password":
        "VARCHAR(255) NULL",

    "registration_number":
        "VARCHAR(255) NULL",

    "issuing_authority":
        "VARCHAR(255) NULL",

    "license_expiry_date":
        "DATE NULL",

    "license_certificate":
        "VARCHAR(500) NULL",

    "certificate_original_name":
        "VARCHAR(500) NULL",

    "certificate_content_type":
        "VARCHAR(100) NULL",

    "certificate_uploaded_at":
        "DATESTEMP NULL",

    "certificate_verification_status":
        "VARCHAR(30) NOT NULL DEFAULT 'PENDING'",

        "google_id":
            "VARCHAR(255) NULL",

        "latitude":
            "VARCHAR(50) NULL",

        "longitude":
            "VARCHAR(50) NULL",

        "token_fee":
            "INT NOT NULL DEFAULT 0",

        "approval_status":
            "VARCHAR(30) NOT NULL DEFAULT 'PENDING'",

        "rejection_reason":
            "TEXT NULL",

        "is_published":
            "BOOLEAN NOT NULL DEFAULT FALSE",

        "payment_account_name":
            "VARCHAR(255) NULL",

        "payment_account_number":
            "VARCHAR(100) NULL",

        "payment_ifsc":
            "VARCHAR(30) NULL",

        "payment_upi":
            "VARCHAR(100) NULL",

        "payment_account_status":
            "VARCHAR(30) NULL DEFAULT 'NOT_ADDED'",

        "razorpay_account_id":
            "VARCHAR(255) NULL",

        "created_at":
            "DATETIME NULL",
    }


    for column_name, definition in hospital_columns.items():

        try:

            add_column_if_missing(
                "hospitals",
                column_name,
                definition,
            )

        except Exception as error:

            print(
                f"Hospital migration warning "
                f"({column_name}):",
                error,
            )


    # --------------------------------------------------------
    # PATIENTS
    # --------------------------------------------------------

    patient_columns = {

        "phone":
            "VARCHAR(50) NULL",

        "password":
            "VARCHAR(255) NULL",

        "google_id":
            "VARCHAR(255) NULL",

        "created_at":
            "DATETIME NULL",
    }


    for column_name, definition in patient_columns.items():

        try:

            add_column_if_missing(
                "patients",
                column_name,
                definition,
            )

        except Exception as error:

            print(
                f"Patient migration warning "
                f"({column_name}):",
                error,
            )


    # --------------------------------------------------------
    # DOCTORS
    # --------------------------------------------------------

    doctor_columns = {

        "specialization":
            "VARCHAR(255) NULL",

        "experience":
            "VARCHAR(100) NULL",

        "created_at":
            "DATETIME NULL",
    }


    for column_name, definition in doctor_columns.items():

        try:

            add_column_if_missing(
                "doctors",
                column_name,
                definition,
            )

        except Exception as error:

            print(
                f"Doctor migration warning "
                f"({column_name}):",
                error,
            )


    # --------------------------------------------------------
    # TOKENS
    # --------------------------------------------------------

    token_columns = {

        "hospital_id":
            "INT NULL",

        "platform":
            "VARCHAR(100) NULL",

        "token_fee":
            "INT NOT NULL DEFAULT 0",

        "platform_fee":
            f"INT NOT NULL DEFAULT {PLATFORM_FEE}",

        "total_amount":
            f"INT NOT NULL DEFAULT {PLATFORM_FEE}",

        "payment_status":
            "VARCHAR(50) DEFAULT 'pending'",

        "razorpay_order_id":
            "VARCHAR(255) NULL",

        "razorpay_payment_id":
            "VARCHAR(255) NULL",

        "razorpay_signature":
            "VARCHAR(500) NULL",

        "status":
            "VARCHAR(50) DEFAULT 'waiting'",

        "created_at":
            "DATETIME NULL",
    }


    for column_name, definition in token_columns.items():

        try:

            add_column_if_missing(
                "tokens",
                column_name,
                definition,
            )

        except Exception as error:

            print(
                f"Token migration warning "
                f"({column_name}):",
                error,
            )


    # --------------------------------------------------------
    # ADMINS
    # --------------------------------------------------------

    admin_columns = {

        "password":
            "VARCHAR(255) NULL",

        "created_at":
            "DATETIME NULL",
    }


    for column_name, definition in admin_columns.items():

        try:

            add_column_if_missing(
                "admins",
                column_name,
                definition,
            )

        except Exception as error:

            print(
                f"Admin migration warning "
                f"({column_name}):",
                error,
            )


try:

    run_database_migration()

except Exception as error:

    print(
        "Database migration warning:",
        error,
    )


# ============================================================
# PYDANTIC SCHEMAS
# ============================================================

class PatientRegister(BaseModel):

    full_name: str

    email: str

    phone: Optional[str] = None

    password: str

class RegistrationOTPRequest(BaseModel):
    role: str
    email: str
    


class RegistrationOTPVerifyRequest(BaseModel):
    role: str
    email: str
    otp: str


@app.post("/registration/request-otp")
def request_registration_otp(
    data: RegistrationOTPRequest,
    db: Session = Depends(get_db),
):
    role = data.role.strip().lower()
    email = data.email.strip().lower()

    if role not in ["patient", "hospital"]:
        raise HTTPException(
            status_code=400,
            detail="Role must be patient or hospital",
        )

    if not email or "@" not in email:
        raise HTTPException(
            status_code=400,
            detail="Please provide a valid email address",
        )

    if role == "patient":
        existing = (
            db.query(Patient)
            .filter(Patient.email == email)
            .first()
        )
    else:
        existing = (
            db.query(Hospital)
            .filter(Hospital.email == email)
            .first()
        )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="This email is already registered",
        )

    otp = f"{secrets.randbelow(1000000):06d}"
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()

    try:
        db.query(RegistrationOTP).filter(
            RegistrationOTP.role == role,
            RegistrationOTP.contact_method == "email",
            RegistrationOTP.contact_value == email,
        ).delete(synchronize_session=False)

        otp_record = RegistrationOTP(
            role=role,
            contact_method="email",
            contact_value=email,
            otp_hash=otp_hash,
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            attempts=0,
            verified=False,
        )

        db.add(otp_record)
        db.commit()

        send_otp_email(email, otp)

    
    except Exception:
        import logging
        logging.exception("Registration OTP request failed")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to send OTP. Check your email configuration.",
        )
    return {
        "success": True,
        "message": "OTP sent to your email address",
    }

@app.post("/registration/verify-otp")
def verify_registration_otp(
    data: RegistrationOTPVerifyRequest,
    db: Session = Depends(get_db),
):
    role = data.role.strip().lower()
    email = data.email.strip().lower()
    otp = data.otp.strip()

    if role not in ["patient", "hospital"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid registration role",
        )

    if len(otp) != 6 or not otp.isdigit():
        raise HTTPException(
            status_code=400,
            detail="Enter a valid 6-digit OTP",
        )

    otp_record = (
        db.query(RegistrationOTP)
        .filter(
            RegistrationOTP.role == role,
            RegistrationOTP.contact_method == "email",
            RegistrationOTP.contact_value == email,
            RegistrationOTP.verified == False,
        )
        .order_by(RegistrationOTP.created_at.desc())
        .first()
    )

    if not otp_record:
        raise HTTPException(
            status_code=400,
            detail="OTP not found. Please request a new OTP.",
        )

    if otp_record.expires_at <= datetime.utcnow():
        db.delete(otp_record)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="OTP expired. Please request a new OTP.",
        )

    if otp_record.attempts >= 5:
        db.delete(otp_record)
        db.commit()
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please request a new OTP.",
        )

    otp_record.attempts += 1
    submitted_hash = hashlib.sha256(otp.encode()).hexdigest()

    if not hmac.compare_digest(
        submitted_hash,
        otp_record.otp_hash,
    ):
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Incorrect OTP. Please try again.",
        )

    otp_record.verified = True
    db.commit()

    return {
        "success": True,
        "message": "Email verified successfully",
    }

class PatientLogin(BaseModel):

    email: str

    password: str


class HospitalRegister(BaseModel):

    name: str

    email: str

    phone: Optional[str] = None

    city: Optional[str] = None

    address: Optional[str] = None

    description: Optional[str] = None

    license_id: Optional[str] = None

    token_fee: int = 0

    password: str


class HospitalLogin(BaseModel):

    email: str

    password: str


class HospitalUpdate(BaseModel):

    phone: Optional[str] = None

    city: Optional[str] = None

    address: Optional[str] = None

    description: Optional[str] = None

    token_fee: Optional[int] = None

    latitude: Optional[str] = None

    longitude: Optional[str] = None


class GoogleCredentialRequest(BaseModel):

    credential: str


class GenericGoogleLoginRequest(BaseModel):

    credential: str

    role: str


class DoctorCreate(BaseModel):

    hospital_id: int

    name: str

    department: str

    specialization: Optional[str] = None

    experience: Optional[str] = None

class HospitalDoctorCreate(BaseModel):
    name: str
    department: str
    specialization: Optional[str] = None
    experience: Optional[str] = None

    # Doctor availability
    available_days: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    is_available: bool = True

class TokenRequest(BaseModel):

    patient_name: str

    hospital: str

    department: str

    doctor: str

    razorpay_order_id: str

    razorpay_payment_id: str

    razorpay_signature: str


class CreateOrderRequest(BaseModel):

    patient_name: str

    hospital: str

    department: str

    doctor: str


class PaymentAccountRequest(BaseModel):

    account_name: Optional[str] = None

    account_number: Optional[str] = None

    ifsc: Optional[str] = None

    upi: Optional[str] = None


class AdminLoginRequest(BaseModel):

    email: str

    password: str


class AdminActionRequest(BaseModel):

    reason: Optional[str] = ""


# ============================================================
# HELPER - HOSPITAL RESPONSE
# ============================================================

def hospital_to_dict(hospital):

    return {
        "id": hospital.id,
        "name": hospital.name,
        "email": hospital.email,
        "phone": hospital.phone,
        "city": hospital.city,
        "address": hospital.address,
        "description": hospital.description,
        "image_url": hospital.image_url,

        "license_id": hospital.license_id,

        # Certificate information
        "registration_number": hospital.registration_number,
        "issuing_authority": hospital.issuing_authority,

        "license_expiry_date": (
            hospital.license_expiry_date.isoformat()
            if hospital.license_expiry_date
            else None
        ),

        "certificate_original_name": (
            hospital.certificate_original_name
        ),

        "certificate_content_type": (
            hospital.certificate_content_type
        ),

        "certificate_uploaded_at": (
            hospital.certificate_uploaded_at.isoformat()
            if hospital.certificate_uploaded_at
            else None
        ),

        "certificate_verification_status": (
            hospital.certificate_verification_status
        ),

        # Hospital approval information
        "approval_status": hospital.approval_status,
        "rejection_reason": hospital.rejection_reason,
        "is_published": hospital.is_published,

        "token_fee": hospital.token_fee,
        "latitude": hospital.latitude,
        "longitude": hospital.longitude,

        "payment_account_status": (
            hospital.payment_account_status
        ),

        "razorpay_account_id": (
            hospital.razorpay_account_id
        ),
    }
# ============================================================
# HELPER - DOCTOR RESPONSE
# ============================

def doctor_to_dict(doctor):

    return {
        "id": doctor.id,
        "hospital_id": doctor.hospital_id,
        "name": doctor.name,
        "department": doctor.department,
        "specialization": doctor.specialization,
        "experience": doctor.experience,

        # Doctor availability details
        "available_days": doctor.available_days,
        "start_time": doctor.start_time,
        "end_time": doctor.end_time,
        "is_available": doctor.is_available,
    }

# ============================================================
# HELPER - TOKEN RESPONSE
# ============================================================

def token_to_dict(
    token
):

    return {

        "id":
            token.id,

        "patient_name":
            token.patient_name,

        "hospital":
            token.hospital,

        "hospital_id":
            token.hospital_id,

        "department":
            token.department,

        "doctor":
            token.doctor,

        "token_number":
            token.token_number,

        "platform":
            token.platform or PLATFORM_NAME,

        "token_fee":
            token.token_fee,

        "platform_fee":
            token.platform_fee,

        "total_amount":
            token.total_amount,

        "payment_status":
            token.payment_status,

        "razorpay_order_id":
            token.razorpay_order_id,

        "razorpay_payment_id":
            token.razorpay_payment_id,

        "status":
            token.status,

        "created_at":
            (
                token.created_at.isoformat()
                if token.created_at
                else None
            ),
    }


# ============================================================
# GOOGLE VERIFICATION
# ============================================================

def verify_google_credential(
    credential: str
):

    if not GOOGLE_CLIENT_ID:

        raise HTTPException(
            status_code=500,
            detail=(
                "GOOGLE_CLIENT_ID is not configured "
                "in backend .env"
            ),
        )

    try:

        google_data = (
            id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                GOOGLE_CLIENT_ID,
            )
        )

    except Exception as error:

        print(
            "Google verification error:",
            error,
        )

        raise HTTPException(
            status_code=401,
            detail="Invalid Google credential",
        )

    email = (
        google_data.get("email") or ""
    ).strip().lower()

    google_id = (
        google_data.get("sub") or ""
    )

    name = (
        google_data.get("name")
        or "Google User"
    )

    email_verified = google_data.get(
        "email_verified",
        False,
    )

    if not email:

        raise HTTPException(
            status_code=400,
            detail="Google email not available",
        )

    if not email_verified:

        raise HTTPException(
            status_code=401,
            detail="Google email is not verified",
        )

    if not google_id:

        raise HTTPException(
            status_code=400,
            detail="Google account ID not available",
        )

    return {

        "email":
            email,

        "google_id":
            google_id,

        "name":
            name,
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {

        "success": True,

        "message":
            "CarePath API is running",

        "version":
            "11.0.0",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return {

        "success": True,

        "status":
            "healthy",
    }


# ============================================================
# PATIENT REGISTER
# ============================================================
@app.post("/patients/register")
def register_patient(
    data: PatientRegister,
    db: Session = Depends(get_db),
):
    # Get and normalize registration details
    full_name = data.full_name.strip()
    email = data.email.strip().lower()

    phone = (
        data.phone.strip()
        if data.phone
        else None
    )

    # Validate required fields
    if not full_name:
        raise HTTPException(
            status_code=400,
            detail="Full name is required",
        )

    if not email:
        raise HTTPException(
            status_code=400,
            detail="Email is required",
        )

    if len(data.password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least 6 characters",
        )

    # Check whether email OTP has been verified
    otp_record = (
        db.query(RegistrationOTP)
        .filter(
            RegistrationOTP.role == "patient",
            RegistrationOTP.contact_method == "email",
            RegistrationOTP.contact_value == email,
            RegistrationOTP.verified == True,
        )
        .order_by(
            RegistrationOTP.created_at.desc()
        )
        .first()
    )

    if not otp_record:
        raise HTTPException(
            status_code=400,
            detail=(
                "Please verify your email with OTP "
                "before registering."
            ),
        )

    # Check OTP verification expiry
    if otp_record.expires_at <= datetime.utcnow():
        db.delete(otp_record)
        db.commit()

        raise HTTPException(
            status_code=400,
            detail=(
                "Email verification expired. "
                "Please request a new OTP."
            ),
        )

    # Check for an existing email
    existing_email = (
        db.query(Patient)
        .filter(
            Patient.email == email
        )
        .first()
    )

    if existing_email:
        raise HTTPException(
            status_code=400,
            detail="Email already registered",
        )

    # Check for an existing phone number
    if phone:
        existing_phone = (
            db.query(Patient)
            .filter(
                Patient.phone == phone
            )
            .first()
        )

        if existing_phone:
            raise HTTPException(
                status_code=400,
                detail="Phone number already registered",
            )

    # Create patient
    patient = Patient(
        full_name=full_name,
        email=email,
        phone=phone,
        password=hash_password(
            data.password
        ),
    )

    try:
        db.add(patient)
        db.commit()
        db.refresh(patient)

        # Delete OTP after successful registration
        db.delete(otp_record)
        db.commit()

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Patient registration failed. Please try again.",
        )

    # Return registration response
    return {
        "success": True,
        "message": "Patient registered successfully",
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "email": patient.email,
            "phone": patient.phone,
        },
    }
# ============================================================
# PATIENT LOGIN
# ============================================================

@app.post("/patients/login")
def patient_login(
    data: PatientLogin,
    db: Session = Depends(get_db),
):

    login_value = data.email.strip()

    patient = (
        db.query(Patient)
        .filter(
            (
                Patient.email ==
                login_value.lower()
            )
            |
            (
                Patient.phone ==
                login_value
            )
        )
        .first()
    )

    if not patient:

        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid email/phone "
                "or password"
            ),
        )

    if not verify_password(
        data.password,
        patient.password,
    ):

        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid email/phone "
                "or password"
            ),
        )

    return {

        "success": True,

        "message":
            "Patient login successful",

        "patient": {

            "id":
                patient.id,

            "full_name":
                patient.full_name,

            "email":
                patient.email,

            "phone":
                patient.phone,
        },
    }


# ============================================================
# PATIENT GOOGLE LOGIN
# ============================================================

@app.post("/patients/google-login")
def patient_google_login(
    data: GoogleCredentialRequest,
    db: Session = Depends(get_db),
):

    google_data = verify_google_credential(
        data.credential
    )

    email = google_data["email"]

    patient = (
        db.query(Patient)
        .filter(
            Patient.email == email
        )
        .first()
    )

    if not patient:

        temporary_password = (
            secrets.token_urlsafe(24)
        )

        patient = Patient(

            full_name=
                google_data["name"],

            email=email,

            password=
                hash_password(
                    temporary_password
                ),

            google_id=
                google_data["google_id"],
        )

        db.add(patient)

        db.commit()

        db.refresh(patient)

    else:

        patient.google_id = (
            google_data["google_id"]
        )

        if (
            not patient.full_name
            or
            patient.full_name
            == "Google Patient"
        ):

            patient.full_name = (
                google_data["name"]
            )

        db.commit()

        db.refresh(patient)

    return {

        "success": True,

        "message":
            "Google login successful",

        "patient": {

            "id":
                patient.id,

            "full_name":
                patient.full_name,

            "email":
                patient.email,

            "phone":
                patient.phone,
        },
    }


# ============================================================
# GENERIC GOOGLE LOGIN
#
# Supports:
#     role = patient
#     role = hospital
#     role = admin
#
# The admin account must already exist.
# ============================================================

@app.post("/auth/google")
def generic_google_login(
    data: GenericGoogleLoginRequest,
    db: Session = Depends(get_db),
):

    role = data.role.strip().lower()

    google_data = verify_google_credential(
        data.credential
    )

    email = google_data["email"]

    google_id = google_data["google_id"]

    name = google_data["name"]


    # --------------------------------------------------------
    # PATIENT
    # --------------------------------------------------------

    if role == "patient":

        patient = (
            db.query(Patient)
            .filter(
                Patient.email == email
            )
            .first()
        )

        if not patient:

            patient = Patient(

                full_name=name,

                email=email,

                password=hash_password(
                    secrets.token_urlsafe(24)
                ),

                google_id=google_id,
            )

            db.add(patient)

        else:

            patient.google_id = google_id

        db.commit()

        db.refresh(patient)

        return {

            "success": True,

            "role":
                "patient",

            "message":
                "Google login successful",

            "patient": {

                "id":
                    patient.id,

                "full_name":
                    patient.full_name,

                "email":
                    patient.email,

                "phone":
                    patient.phone,
            },
        }


    # --------------------------------------------------------
    # HOSPITAL
    # --------------------------------------------------------

    if role == "hospital":

        hospital = (
            db.query(Hospital)
            .filter(
                Hospital.email == email
            )
            .first()
        )

        if not hospital:

            raise HTTPException(
                status_code=404,
                detail=(
                    "Hospital is not registered "
                    "with this Google email."
                ),
            )

        hospital.google_id = google_id

        db.commit()

        db.refresh(hospital)

        return {

            "success": True,

            "role":
                "hospital",

            "message":
                "Google login successful",

            "hospital":
                hospital_to_dict(
                    hospital
                ),
        }


    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if role == "admin":

        admin = (
            db.query(Admin)
            .filter(
                func.lower(Admin.email) == email.strip().lower()
            )
            .first()
        )

        if not admin:

            raise HTTPException(
                status_code=403,
                detail=(
                    "This Google account is "
                    "not registered as an admin."
                ),
            )

        return {

            "success": True,

            "role":
                "admin",

            "message":
                "Google admin login successful",

            "admin": {

                "id":
                    admin.id,

                "email":
                    admin.email,
            },
        }


    raise HTTPException(
        status_code=400,
        detail=(
            "Invalid role. "
            "Use patient, hospital or admin."
        ),
    )




# ============================================================
# HOSPITAL REGISTER
# ============================================================

@app.post("/hospitals")
async def register_hospital(
    name: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    description: Optional[str] = Form(None),

    registration_number: str = Form(...),
    issuing_authority: str = Form(...),

    license_expiry_date: Optional[str] = Form(None),

    token_fee: int = Form(0),
    password: str = Form(...),

    license_certificate: UploadFile = File(...),

    db: Session = Depends(get_db),
):
        # Normalize hospital email
    email = email.strip().lower()

    # Check whether hospital email OTP is verified
    otp_record = (
        db.query(RegistrationOTP)
        .filter(
            RegistrationOTP.role == "hospital",
            RegistrationOTP.contact_method == "email",
            RegistrationOTP.contact_value == email,
            RegistrationOTP.verified == True,
        )
        .order_by(
            RegistrationOTP.created_at.desc()
        )
        .first()
    )

    if not otp_record:
        raise HTTPException(
            status_code=400,
            detail=(
                "Please verify your hospital email "
                "with OTP before registering."
            ),
        )

    # Check OTP expiry
    if otp_record.expires_at <= datetime.utcnow():
        db.delete(otp_record)
        db.commit()

        raise HTTPException(
            status_code=400,
            detail=(
                "Email verification expired. "
                "Please request a new OTP."
            ),
        )

    # --------------------------------------------------------
    # CLEAN DATA
    # --------------------------------------------------------

    name = name.strip()

    email = email.strip().lower()

    registration_number = (
        registration_number.strip()
    )

    issuing_authority = (
        issuing_authority.strip()
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if not name:

        raise HTTPException(
            status_code=400,
            detail="Hospital name is required",
        )

    if not email:

        raise HTTPException(
            status_code=400,
            detail="Hospital email is required",
        )

    if not registration_number:

        raise HTTPException(
            status_code=400,
            detail="Registration number is required",
        )

    if not issuing_authority:

        raise HTTPException(
            status_code=400,
            detail="Issuing authority is required",
        )

    if len(password) < 6:

        raise HTTPException(
            status_code=400,
            detail=(
                "Password must contain "
                "at least 6 characters"
            ),
        )

    if token_fee < 0:

        raise HTTPException(
            status_code=400,
            detail="Token fee cannot be negative",
        )

    # --------------------------------------------------------
    # CHECK EMAIL
    # --------------------------------------------------------

    existing = (
        db.query(Hospital)
        .filter(
            Hospital.email == email
        )
        .first()
    )

    if existing:

        raise HTTPException(
            status_code=400,
            detail="Hospital email already registered",
        )

    # --------------------------------------------------------
    # CHECK CERTIFICATE
    # --------------------------------------------------------

    if not license_certificate:

        raise HTTPException(
            status_code=400,
            detail="Hospital registration certificate is required",
        )

    content_type = (
        license_certificate.content_type
        or ""
    ).lower()

    if content_type not in ALLOWED_CERTIFICATE_TYPES:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid certificate format. "
                "Only PDF, JPG and PNG files are allowed."
            ),
        )

    # --------------------------------------------------------
    # READ CERTIFICATE
    # --------------------------------------------------------

    certificate_data = await (
        license_certificate.read()
    )

    if not certificate_data:

        raise HTTPException(
            status_code=400,
            detail="Certificate file is empty",
        )

    if len(certificate_data) > MAX_CERTIFICATE_SIZE:

        raise HTTPException(
            status_code=400,
            detail="Certificate file must be 10 MB or smaller",
        )

    # --------------------------------------------------------
    # FILE EXTENSION
    # --------------------------------------------------------

    original_name = (
        license_certificate.filename
        or "certificate"
    )

    extension = os.path.splitext(
        original_name
    )[1].lower()

    allowed_extensions = {
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
    }

    if extension not in allowed_extensions:

        raise HTTPException(
            status_code=400,
            detail="Invalid certificate file extension",
        )

    # --------------------------------------------------------
    # UNIQUE FILE NAME
    # --------------------------------------------------------

    unique_name = (
        f"hospital_"
        f"{secrets.token_hex(16)}"
        f"{extension}"
    )

    certificate_path = os.path.join(
        UPLOAD_DIR,
        unique_name,
    )

    # --------------------------------------------------------
    # SAVE FILE
    # --------------------------------------------------------

    try:

        with open(
            certificate_path,
            "wb",
        ) as file:

            file.write(
                certificate_data
            )

    except Exception as error:

        print(
            "Certificate save error:",
            error,
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to save certificate",
        )

    # --------------------------------------------------------
    # EXPIRY DATE
    # --------------------------------------------------------

    expiry_date = None

    if license_expiry_date:

        try:

            expiry_date = date.fromisoformat(
                license_expiry_date
            )

        except ValueError:

            # Delete uploaded file
            try:

                os.remove(
                    certificate_path
                )

            except Exception:
                pass

            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid license expiry date. "
                    "Use YYYY-MM-DD."
                ),
            )

    # --------------------------------------------------------
    # CREATE HOSPITAL
    # --------------------------------------------------------

    hospital = Hospital(

        name=name,

        email=email,

        phone=(
            phone.strip()
            if phone
            else None
        ),

        city=(
            city.strip()
            if city
            else None
        ),

        address=(
            address.strip()
            if address
            else None
        ),

        description=(
            description.strip()
            if description
            else None
        ),

        registration_number=
            registration_number,

        issuing_authority=
            issuing_authority,

        license_expiry_date=
            expiry_date,

        license_certificate=
            unique_name,

        certificate_original_name=
            original_name,

        certificate_content_type=
            content_type,

        certificate_uploaded_at=
            datetime.utcnow(),

        certificate_verification_status=
            "PENDING",

        # Keep old field compatible
        license_id=
            registration_number,

        password=
            hash_password(password),

        token_fee=
            token_fee,

        approval_status=
            "PENDING",

        is_published=
            False,

        payment_account_status=
            "NOT_ADDED",
    )
    db.add(hospital)

    db.commit()

    db.refresh(hospital)

    # Delete verified OTP after successful registration
    db.delete(otp_record)

    db.commit()
    
    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return {

        "success": True,

        "message": (
            "Hospital registered successfully. "
            "Certificate is waiting for admin verification."
        ),

        "hospital":
            hospital_to_dict(
                hospital
            ),
            
    }

# ============================================================
# HOSPITAL EMAIL AND PASSWORD LOGIN
# ============================================================

@app.post("/hospitals/login")
def hospital_login(
    data: HospitalLogin,
    db: Session = Depends(get_db),
):
    email = data.email.strip().lower()

    hospital = (
        db.query(Hospital)
        .filter(Hospital.email == email)
        .first()
    )

    if not hospital or not verify_password(
        data.password,
        hospital.password or "",
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid hospital email or password",
        )

    return {
        "success": True,
        "message": "Hospital login successful",
        "hospital": hospital_to_dict(hospital),
    }
# ============================================================
# HOSPITAL GOOGLE LOGIN
# ============================================================

@app.post("/hospitals/google-login")
def hospital_google_login(
    data: GoogleCredentialRequest,
    db: Session = Depends(get_db),
):

    google_data = verify_google_credential(
        data.credential
    )

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.email ==
            google_data["email"]
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail=(
                "Hospital not registered with "
                "this Google email. Please register "
                "the hospital first."
            ),
        )

    hospital.google_id = (
        google_data["google_id"]
    )

    db.commit()

    db.refresh(hospital)

    return {

        "success": True,

        "message":
            "Google login successful",

        "hospital":
            hospital_to_dict(hospital),
    }


# ============================================================
# GET PUBLISHED HOSPITALS
#
# Patient App uses this endpoint.
#
# Hospital appears only when:
#
# approval_status = APPROVED
# AND
# is_published = TRUE
# ============================================================

@app.post("/hospitals/{hospital_id}/photo")
async def upload_hospital_photo(
    hospital_id: int,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a public hospital cover photo for patient browsing cards."""
    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == hospital_id)
        .first()
    )
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    content_type = (photo.content_type or "").lower()
    if content_type not in ALLOWED_HOSPITAL_PHOTO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Please upload a JPG, PNG, or WEBP image.",
        )

    content = await photo.read(MAX_HOSPITAL_PHOTO_SIZE + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The photo is empty.")
    if len(content) > MAX_HOSPITAL_PHOTO_SIZE:
        raise HTTPException(status_code=413, detail="Photo must be 5 MB or smaller.")

    extension = ALLOWED_HOSPITAL_PHOTO_TYPES[content_type]
    filename = f"hospital_{hospital_id}_{uuid.uuid4().hex}{extension}"
    destination = os.path.join(HOSPITAL_PHOTO_DIR, filename)
    with open(destination, "wb") as output_file:
        output_file.write(content)

    old_url = hospital.image_url
    hospital.image_url = f"/hospital-photos/{filename}"
    db.commit()
    db.refresh(hospital)

    # Remove the previous uploaded photo after the new photo is saved.
    if old_url and old_url.startswith("/hospital-photos/"):
        old_name = os.path.basename(old_url)
        old_path = os.path.join(HOSPITAL_PHOTO_DIR, old_name)
        if os.path.isfile(old_path) and old_name != filename:
            try:
                os.remove(old_path)
            except OSError:
                pass

    return {
        "success": True,
        "message": "Hospital photo uploaded successfully.",
        "hospital": hospital_to_dict(hospital),
    }


@app.get("/hospital-photos/{filename}")
def get_hospital_photo(filename: str):
    """Serve only generated hospital photo filenames, never certificates."""
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name.startswith("hospital_"):
        raise HTTPException(status_code=404, detail="Photo not found")
    file_path = os.path.join(HOSPITAL_PHOTO_DIR, safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Photo not found")
    media_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type)


@app.get("/hospitals")
def get_hospitals(
    db: Session = Depends(get_db),
):

    hospitals = (
        db.query(Hospital)
        .filter(
            Hospital.approval_status ==
            "APPROVED",

            Hospital.is_published ==
            True,
        )
        .order_by(
            Hospital.name.asc()
        )
        .all()
    )

    return [

        hospital_to_dict(hospital)

        for hospital in hospitals
    ]


# ============================================================
# GET HOSPITAL BY ID
# ============================================================

@app.get("/hospitals/{hospital_id}")
def get_hospital(
    hospital_id: int,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    return hospital_to_dict(
        hospital
    )

# ============================================================
# DELETE DOCTOR
# ============================================================

@app.delete("/doctors/{doctor_id}")
def delete_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
):
    doctor = (
        db.query(Doctor)
        .filter(Doctor.id == doctor_id)
        .first()
    )

    if not doctor:
        raise HTTPException(
            status_code=404,
            detail="Doctor not found",
        )

    db.delete(doctor)
    db.commit()

    return {
        "success": True,
        "message": "Doctor deleted successfully",
    }

# ============================================================
# UPDATE HOSPITAL PROFILE
# ============================================================

@app.put("/hospitals/{hospital_id}")
def update_hospital(
    hospital_id: int,
    data: HospitalUpdate,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )
    
    if hospital.certificate_verification_status != "VERIFIED":
        raise HTTPException(
            status_code=400,
            detail="Verify the hospital certificate before approval",
        )

    if data.phone is not None:

        hospital.phone = (
            data.phone.strip()
        )

    if data.city is not None:

        hospital.city = (
            data.city.strip()
        )

    if data.address is not None:

        hospital.address = (
            data.address.strip()
        )

    if data.description is not None:

        hospital.description = (
            data.description.strip()
        )

    if data.token_fee is not None:

        if data.token_fee < 0:

            raise HTTPException(
                status_code=400,
                detail="Token fee cannot be negative",
            )

        hospital.token_fee = (
            data.token_fee
        )

    if data.latitude is not None:

        hospital.latitude = (
            data.latitude
        )

    if data.longitude is not None:

        hospital.longitude = (
            data.longitude
        )

    db.commit()

    db.refresh(hospital)

    return {

        "success": True,

        "message":
            "Hospital profile updated successfully",

        "hospital":
            hospital_to_dict(hospital),
    }


# ============================================================
# SAVE HOSPITAL LOCATION
# ============================================================

@app.put(
    "/hospitals/{hospital_id}/location"
)
def save_hospital_location(
    hospital_id: int,
    latitude: str,
    longitude: str,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    hospital.latitude = latitude

    hospital.longitude = longitude

    db.commit()

    db.refresh(hospital)

    return {

        "success": True,

        "message":
            "Hospital location saved",

        "latitude":
            hospital.latitude,

        "longitude":
            hospital.longitude,
    }


# ============================================================
# HOSPITAL DEPARTMENTS
# ============================================================

@app.get(
    "/hospitals/{hospital_id}/departments"
)
def get_departments(
    hospital_id: int,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    doctors = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id ==
            hospital_id
        )
        .all()
    )

    departments = sorted(
        list(
            {
                doctor.department
                for doctor in doctors
                if doctor.department
            }
        )
    )

    return departments


# ============================================================
# GET DOCTORS
# ============================================================

@app.get("/doctors")
def get_doctors(
    hospital_id: Optional[int] = None,
    department: Optional[str] = None,
    db: Session = Depends(get_db),
):

    query = db.query(Doctor)

    if hospital_id is not None:

        query = query.filter(
            Doctor.hospital_id ==
            hospital_id
        )

    if department:

        query = query.filter(
            Doctor.department ==
            department
        )

    doctors = (
        query
        .order_by(
            Doctor.name.asc()
        )
        .all()
    )

    return [

        doctor_to_dict(doctor)

        for doctor in doctors
    ]


# ============================================================
# GET HOSPITAL DOCTORS
# ============================================================

@app.get(
    "/hospitals/{hospital_id}/doctors"
)
def get_hospital_doctors(
    hospital_id: int,
    department: Optional[str] = None,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    query = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id ==
            hospital_id
        )
    )

    if department:

        query = query.filter(
            Doctor.department ==
            department
        )

    doctors = (
        query
        .order_by(
            Doctor.name.asc()
        )
        .all()
    )

    return [

        doctor_to_dict(doctor)

        for doctor in doctors
    ]


# ============================================================
# ADD DOCTOR
# ============================================================


@app.post("/doctors")
def add_doctor(
    data: DoctorCreate,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            data.hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    name = data.name.strip()

    department = data.department.strip()

    if not name:

        raise HTTPException(
            status_code=400,
            detail="Doctor name is required",
        )

    if not department:

        raise HTTPException(
            status_code=400,
            detail="Department is required",
        )

    doctor = Doctor(

        hospital_id=
            data.hospital_id,

        name=name,

        department=department,

        specialization=(
            data.specialization.strip()
            if data.specialization
            else None
        ),

        experience=(
            data.experience.strip()
            if data.experience
            else None
        ),
    )

    db.add(doctor)

    db.commit()

    db.refresh(doctor)

    return {

        "success": True,

        "message":
            "Doctor added successfully",

        "doctor":
            doctor_to_dict(doctor),
    }

# ============================================================
# HOSPITAL PAYMENT ACCOUNT
# ============================================================

@app.put(
    "/hospitals/{hospital_id}/payment-account"
)
def save_payment_account(
    hospital_id: int,
    data: PaymentAccountRequest,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    if (
        not data.account_name
        and
        not data.upi
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Add bank account or UPI details"
            ),
        )

    hospital.payment_account_name = (
        data.account_name
    )

    hospital.payment_account_number = (
        data.account_number
    )

    hospital.payment_ifsc = (
        data.ifsc
    )

    hospital.payment_upi = (
        data.upi
    )

    hospital.payment_account_status = (
        "PENDING"
    )

    db.commit()

    db.refresh(hospital)

    return {

        "success": True,

        "message":
            (
                "Payment account details saved. "
                "Waiting for verification."
            ),

        "payment_account_status":
            hospital.payment_account_status,

        "razorpay_account_id":
            hospital.razorpay_account_id,
    }


# ============================================================
# GET PAYMENT ACCOUNT
# ============================================================

@app.get(
    "/hospitals/{hospital_id}/payment-account"
)
def get_payment_account(
    hospital_id: int,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    return {

        "hospital_id":
            hospital.id,

        "account_name":
            hospital.payment_account_name,

        "account_number":
            hospital.payment_account_number,

        "ifsc":
            hospital.payment_ifsc,

        "upi":
            hospital.payment_upi,

        "status":
            hospital.payment_account_status,

        "razorpay_account_id":
            hospital.razorpay_account_id,
    }


# ============================================================
# FIND PUBLISHED HOSPITAL
# ============================================================

def find_published_hospital(
    db,
    hospital_name,
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.name ==
            hospital_name,

            Hospital.approval_status ==
            "APPROVED",

            Hospital.is_published ==
            True,
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail=(
                "Hospital not found "
                "or not published"
            ),
        )

    return hospital


# ============================================================
# CREATE RAZORPAY ORDER
# ============================================================

@app.post("/api/create-order")
@app.post("/payments/create-order")
def create_razorpay_order(
    data: CreateOrderRequest,
    db: Session = Depends(get_db),
):

    if not razorpay_client:

        raise HTTPException(
            status_code=500,
            detail=(
                "Razorpay is not configured. "
                "Check RAZORPAY_KEY_ID and "
                "RAZORPAY_KEY_SECRET in .env"
            ),
        )

    patient_name = (
        data.patient_name.strip()
    )

    hospital_name = (
        data.hospital.strip()
    )

    department_name = (
        data.department.strip()
    )

    doctor_name = (
        data.doctor.strip()
    )

    if not patient_name:

        raise HTTPException(
            status_code=400,
            detail="Patient name is required",
        )

    if not hospital_name:

        raise HTTPException(
            status_code=400,
            detail="Hospital is required",
        )

    if not department_name:

        raise HTTPException(
            status_code=400,
            detail="Department is required",
        )

    if not doctor_name:

        raise HTTPException(
            status_code=400,
            detail="Doctor is required",
        )

    hospital = find_published_hospital(
        db,
        hospital_name,
    )

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id ==
            hospital.id,

            Doctor.department ==
            department_name,

            Doctor.name ==
            doctor_name,
        )
        .first()
    )

    if not doctor:

        raise HTTPException(
            status_code=404,
            detail="Doctor not found",
        )

    token_fee = int(
        hospital.token_fee or 0
    )

    platform_fee = PLATFORM_FEE

    total_amount = (
        token_fee +
        platform_fee
    )

    if total_amount <= 0:

        raise HTTPException(
            status_code=400,
            detail="Invalid payment amount",
        )

    amount_paise = (
        total_amount * 100
    )

    try:

        order = (
            razorpay_client.order.create(
                {

                    "amount":
                        amount_paise,

                    "currency":
                        "INR",

                    "receipt":
                        (
                            "carepath_"
                            f"{hospital.id}_"
                            f"{secrets.token_hex(4)}"
                        ),
                }
            )
        )

        return {

            "success": True,

            "order_id":
                order["id"],

            "key_id":
                RAZORPAY_KEY_ID,

            "razorpay_key_id":
                RAZORPAY_KEY_ID,

            "amount":
                amount_paise,

            "currency":
                "INR",

            "token_fee":
                token_fee,

            "platform_fee":
                platform_fee,

            "total_amount":
                total_amount,

            "hospital_id":
                hospital.id,

            "razorpay_account_id":
                hospital.razorpay_account_id,
        }

    except Exception as error:

        print(
            "Razorpay order error:",
            error,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to create "
                "Razorpay order"
            ),
        )


# ============================================================
# RAZORPAY SIGNATURE
# ============================================================

def verify_razorpay_signature(
    order_id,
    payment_id,
    signature,
):

    if not RAZORPAY_KEY_SECRET:

        return False

    generated_signature = hmac.new(

        RAZORPAY_KEY_SECRET.encode(
            "utf-8"
        ),

        (
            order_id
            + "|"
            + payment_id
        ).encode(
            "utf-8"
        ),

        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        generated_signature,
        signature,
    )


# ============================================================
# CREATE TOKEN AFTER PAYMENT
# ============================================================

@app.post("/tokens")
@app.post("/payments/verify")
def create_token(
    data: TokenRequest,
    db: Session = Depends(get_db),
):

    if not data.razorpay_order_id:

        raise HTTPException(
            status_code=400,
            detail="Razorpay order ID is required",
        )

    if not data.razorpay_payment_id:

        raise HTTPException(
            status_code=400,
            detail="Razorpay payment ID is required",
        )

    if not data.razorpay_signature:

        raise HTTPException(
            status_code=400,
            detail="Razorpay signature is required",
        )


    # --------------------------------------------------------
    # CHECK SIGNATURE
    # --------------------------------------------------------

    valid_signature = (
        verify_razorpay_signature(
            data.razorpay_order_id,
            data.razorpay_payment_id,
            data.razorpay_signature,
        )
    )

    if not valid_signature:

        raise HTTPException(
            status_code=400,
            detail="Invalid Razorpay payment signature",
        )


    # --------------------------------------------------------
    # CHECK RAZORPAY
    # --------------------------------------------------------

    if not razorpay_client:

        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured",
        )


    try:

        payment = (
            razorpay_client.payment.fetch(
                data.razorpay_payment_id
            )
        )

        payment_order_id = (
            payment.get("order_id")
        )

        if (
            payment_order_id
            != data.razorpay_order_id
        ):

            raise HTTPException(
                status_code=400,
                detail="Payment order mismatch",
            )

        payment_status = (
            payment.get("status")
        )
        if payment_status != "captured":
            raise HTTPException(
                status_code=400,
                detail="Payment has not been captured successfully",
            )

    except HTTPException:

        raise

    except Exception as error:

        print(
            "Payment verification error:",
            error,
        )

        raise HTTPException(
            status_code=400,
            detail=(
                "Unable to verify "
                "Razorpay payment"
            ),
        )


    # --------------------------------------------------------
    # FIND HOSPITAL
    # --------------------------------------------------------

    hospital = find_published_hospital(
        db,
        data.hospital,
    )


    # --------------------------------------------------------
    # FIND DOCTOR
    # --------------------------------------------------------

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id ==
            hospital.id,

            Doctor.department ==
            data.department,

            Doctor.name ==
            data.doctor,
        )
        .first()
    )

    if not doctor:

        raise HTTPException(
            status_code=404,
            detail="Doctor not found",
        )


    # --------------------------------------------------------
    # CALCULATE PAYMENT
    # --------------------------------------------------------

    token_fee = int(
        hospital.token_fee or 0
    )

    platform_fee = PLATFORM_FEE

    total_amount = (
        token_fee +
        platform_fee
    )

    expected_amount_paise = (
        total_amount * 100
    )

    actual_amount_paise = int(
        payment.get(
            "amount",
            0,
        )
    )

    if (
        actual_amount_paise
        != expected_amount_paise
    ):

        raise HTTPException(
            status_code=400,
            detail="Payment amount mismatch",
        )


    # --------------------------------------------------------
    # PREVENT DUPLICATE PAYMENT
    # --------------------------------------------------------

    existing_token = (
        db.query(Token)
        .filter(
            Token.razorpay_payment_id ==
            data.razorpay_payment_id
        )
        .first()
    )

    if existing_token:

        return {

            "success": True,

            "message":
                "Token already created",

            "token":
                token_to_dict(
                    existing_token
                ),
        }
            # --------------------------------------------------------
    # NEXT TOKEN NUMBER
    # Per hospital + department + doctor + date
    # --------------------------------------------------------

    today = date.today()

    latest_token = (
        db.query(Token)
        .filter(
            Token.hospital_id == hospital.id,
            Token.department == data.department.strip(),
            Token.doctor == data.doctor.strip(),
            func.date(Token.created_at) == today,
        )
        .order_by(
            Token.token_number.desc()
        )
        .first()
    )

    if latest_token:
        next_token_number = latest_token.token_number + 1
    else:
        next_token_number = 1

    # --------------------------------------------------------
    # CREATE TOKEN
    # --------------------------------------------------------

    token = Token(
        patient_name=data.patient_name.strip(),
        hospital=hospital.name,
        hospital_id=hospital.id,
        department=data.department.strip(),
        doctor=data.doctor.strip(),
        token_number=next_token_number,
        platform=PLATFORM_NAME,
        token_fee=token_fee,
        platform_fee=platform_fee,
        total_amount=total_amount,
        payment_status="paid",
        razorpay_order_id=data.razorpay_order_id,
        razorpay_payment_id=data.razorpay_payment_id,
        razorpay_signature=data.razorpay_signature,
        status="waiting",
    )

    db.add(token)
    db.commit()
    db.refresh(token)

    return {
        "success": True,
        "message": "Hospital token created successfully",
        "token": token_to_dict(token),
    }

# ============================================================
# GET ALL TOKENS
# ============================================================

@app.get("/tokens")
def get_tokens(
    hospital: Optional[str] = None,
    hospital_id: Optional[int] = None,
    department: Optional[str] = None,
    doctor: Optional[str] = None,
    payment_status: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):

    query = db.query(Token)


    if hospital:

        query = query.filter(
            Token.hospital ==
            hospital
        )


    if hospital_id is not None:

        query = query.filter(
            Token.hospital_id ==
            hospital_id
        )


    if department:

        query = query.filter(
            Token.department ==
            department
        )


    if doctor:

        query = query.filter(
            Token.doctor ==
            doctor
        )


    if payment_status:

        query = query.filter(
            Token.payment_status ==
            payment_status
        )


    if status:

        query = query.filter(
            Token.status ==
            status
        )


    tokens = (
        query
        .order_by(
            Token.created_at.desc()
        )
        .all()
    )


    return [

        token_to_dict(token)

        for token in tokens
    ]


# ============================================================
# PATIENT TOKEN
# ============================================================

@app.get(
    "/patient-token/{token_id}"
)
def get_patient_token(
    token_id: int,
    db: Session = Depends(get_db),
):

    token = (
        db.query(Token)
        .filter(
            Token.id ==
            token_id
        )
        .first()
    )

    if not token:

        raise HTTPException(
            status_code=404,
            detail="Token not found",
        )

    return {

        "success": True,

        "token":
            token_to_dict(token),
    }


# ============================================================
# NEXT PATIENT
# ============================================================

@app.post("/next-patient")
def next_patient(
    hospital: Optional[str] = None,
    hospital_id: Optional[int] = None,
    department: Optional[str] = None,
    doctor: Optional[str] = None,
    db: Session = Depends(get_db),
):

    if hospital_id is not None:

        hospital_object = (
            db.query(Hospital)
            .filter(
                Hospital.id ==
                hospital_id
            )
            .first()
        )

        if not hospital_object:

            raise HTTPException(
                status_code=404,
                detail="Hospital not found",
            )

        hospital = (
            hospital_object.name
        )


    if not hospital:

        raise HTTPException(
            status_code=400,
            detail="Hospital is required",
        )


    if not department:

        raise HTTPException(
            status_code=400,
            detail="Department is required",
        )


    if not doctor:

        raise HTTPException(
            status_code=400,
            detail="Doctor is required",
        )


    # --------------------------------------------------------
    # COMPLETE CURRENT SERVING TOKEN
    # --------------------------------------------------------

    current = (
        db.query(Token)
        .filter(
            Token.hospital ==
            hospital,

            Token.department ==
            department,

            Token.doctor ==
            doctor,

            Token.status ==
            "serving",
        )
        .first()
    )


    if current:

        current.status = "completed"


    # --------------------------------------------------------
    # FIND NEXT PATIENT
    # --------------------------------------------------------

    next_token = (
        db.query(Token)
        .filter(
            Token.hospital ==
            hospital,

            Token.department ==
            department,

            Token.doctor ==
            doctor,

            Token.status ==
            "waiting",

            Token.payment_status ==
            "paid",
        )
        .order_by(
            Token.token_number.asc()
        )
        .first()
    )


    if not next_token:

        db.commit()

        raise HTTPException(
            status_code=404,
            detail="No waiting patients",
        )


    next_token.status = "serving"

    db.commit()

    db.refresh(next_token)


    return {

        "success": True,

        "message":
            (
                f"Token "
                f"{next_token.token_number} "
                "is now being served"
            ),

        "token": {

            "id":
                next_token.id,

            "token_number":
                next_token.token_number,

            "patient_name":
                next_token.patient_name,

            "doctor":
                next_token.doctor,

            "department":
                next_token.department,

            "status":
                next_token.status,
        },
    }


# ============================================================
# COMPLETE TOKEN
# ============================================================

@app.put(
    "/tokens/{token_id}/complete"
)
def complete_token(
    token_id: int,
    db: Session = Depends(get_db),
):

    token = (
        db.query(Token)
        .filter(
            Token.id ==
            token_id
        )
        .first()
    )

    if not token:

        raise HTTPException(
            status_code=404,
            detail="Token not found",
        )

    token.status = "completed"

    db.commit()

    db.refresh(token)

    return {

        "success": True,

        "message":
            "Token completed successfully",

        "token":
            token_to_dict(token),
    }


# ============================================================
# ADMIN LOGIN
# ============================================================

@app.post("/admin/login")
def admin_login(
    data: AdminLoginRequest,
    db: Session = Depends(get_db),
):

    email = data.email.strip().lower()


    admin = (
        db.query(Admin)
        .filter(
            Admin.email ==
            email
        )
        .first()
    )


    # --------------------------------------------------------
    # DEVELOPMENT DEFAULT ADMIN
    # --------------------------------------------------------

    if not admin:

        if (
            email ==
            "admin@CAREPATH.com"
            and
            data.password ==
            "admin123"
        ):

            admin = Admin(

                email=email,

                password=
                    hash_password(
                        data.password
                    ),
            )

            db.add(admin)

            db.commit()

            db.refresh(admin)

        else:

            raise HTTPException(
                status_code=401,
                detail="Invalid admin credentials",
            )


    else:

        if not verify_password(
            data.password,
            admin.password,
        ):

            raise HTTPException(
                status_code=401,
                detail="Invalid admin credentials",
            )


    return {

        "success": True,

        "message":
            "Admin login successful",

        "admin": {

            "id":
                admin.id,

            "email":
                admin.email,
        },
    }


# ============================================================
# ADMIN - ALL HOSPITALS
# ============================================================

@app.get("/admin/hospitals")
def admin_get_hospitals(
    db: Session = Depends(get_db),
):

    hospitals = (
        db.query(Hospital)
        .order_by(
            Hospital.id.desc()
        )
        .all()
    )

    result = []


    for hospital in hospitals:

        doctor_count = (
            db.query(Doctor)
            .filter(
                Doctor.hospital_id ==
                hospital.id
            )
            .count()
        )


        token_count = (
            db.query(Token)
            .filter(
                Token.hospital_id ==
                hospital.id
            )
            .count()
        )


        paid_count = (
            db.query(Token)
            .filter(
                Token.hospital_id ==
                hospital.id,

                Token.payment_status ==
                "paid",
            )
            .count()
        )


        hospital_data = (
            hospital_to_dict(
                hospital
            )
        )


        hospital_data.update({

            "doctor_count":
                doctor_count,

            "token_count":
                token_count,

            "paid_token_count":
                paid_count,

            "payment_account_name":
                hospital.payment_account_name,

            "payment_account_number":
                hospital.payment_account_number,

            "payment_ifsc":
                hospital.payment_ifsc,

            "payment_upi":
                hospital.payment_upi,
        })


        result.append(
            hospital_data
        )


    return result


# ============================================================
# ADMIN - ONE HOSPITAL
# ============================================================

@app.get(
    "/admin/hospitals/{hospital_id}"
)
def admin_get_hospital(
    hospital_id: int,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )


    doctor_count = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id ==
            hospital_id
        )
        .count()
    )


    token_count = (
        db.query(Token)
        .filter(
            Token.hospital_id ==
            hospital_id
        )
        .count()
    )


    result = hospital_to_dict(
        hospital
    )


    result.update({

        "doctor_count":
            doctor_count,

        "token_count":
            token_count,

        "payment_account_name":
            hospital.payment_account_name,

        "payment_account_number":
            hospital.payment_account_number,

        "payment_ifsc":
            hospital.payment_ifsc,

        "payment_upi":
            hospital.payment_upi,
    })


    return result

# ============================================================
# ADMIN - VERIFY HOSPITAL CERTIFICATE
# ============================================================

@app.put("/admin/hospitals/{hospital_id}/certificate/verify")
def verify_hospital_certificate(
    hospital_id: int,
    db: Session = Depends(get_db),
):
    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == hospital_id)
        .first()
    )

    if not hospital:
        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    if not hospital.license_certificate:
        raise HTTPException(
            status_code=400,
            detail="No certificate uploaded",
        )

    certificate_path = os.path.join(
        UPLOAD_DIR,
        hospital.license_certificate,
    )

    if not os.path.isfile(certificate_path):
        raise HTTPException(
            status_code=404,
            detail="Certificate file is missing",
        )

    # Record the admin's decision only after inspecting
    # the certificate in the Admin App.
    hospital.certificate_verification_status = "VERIFIED"

    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Hospital certificate verified successfully",
        "hospital": hospital_to_dict(hospital),
    }#============================================================
# ADMIN - VIEW HOSPITAL CERTIFICATE
# Supports PDF, JPG, JPEG, PNGF
# ============================================================

@app.get("/admin/hospitals/{hospital_id}/certificate")
def get_hospital_certificate(
    hospital_id: int,
    db: Session = Depends(get_db),
):
    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == hospital_id)
        .first()
    )

    if not hospital:
        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    if not hospital.license_certificate:
        raise HTTPException(
            status_code=404,
            detail="No certificate has been uploaded.",
        )

    # Build the saved certificate file path
    certificate_path = os.path.join(
        os.path.dirname(__file__),
        "uploads",
        "hospital_certificates",
        hospital.license_certificate,
    )

    # Check whether the file exists
    if not os.path.isfile(certificate_path):
        raise HTTPException(
            status_code=404,
            detail="Certificate file is missing from the server.",
        )

    # Detect the actual file type from its extension
    media_type, _ = mimetypes.guess_type(certificate_path)

    allowed_types = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }

    extension = os.path.splitext(certificate_path)[1].lower()

    if extension not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail="Unsupported certificate file type.",
        )

    # Return the file inline so the browser can display it
    return FileResponse(
        path=certificate_path,
        media_type=allowed_types[extension],
        content_disposition_type="inline",
    )
#   db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Hospital certificate verified successfully",
        "hospital": hospital_to_dict(hospital),
    }
    #============================================================
# ADMIN - REJECT HOSPITAL CERTIFICATE
# ============================================================

@app.put(
    "/admin/hospitals/{hospital_id}/certificate/reject"
)
def reject_hospital_certificate(
    hospital_id: int,
    data: AdminActionRequest,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == hospital_id)
        .first()
    )

    if not hospital:
        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    hospital.certificate_verification_status = "REJECTED"

    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Hospital certificate rejected",
        "reason": data.reason or "Certificate rejected by admin",
        "hospital": hospital_to_dict(hospital),
    }

# ============================================================
# ADMIN - APPROVE HOSPITAL
# ============================================================


# ============================================================
# ADMIN - APPROVE HOSPITAL
# ============================================================

@app.put("/admin/hospitals/{hospital_id}/approve")
def approve_hospital(
    hospital_id: int,
    db: Session = Depends(get_db),
):
    # Find hospital
    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == hospital_id)
        .first()
    )

    if not hospital:
        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    # Require certificate verification first
    if hospital.certificate_verification_status != "VERIFIED":
        raise HTTPException(
            status_code=400,
            detail="Verify the hospital certificate before approval",
        )

    # Approve hospital
    hospital.approval_status = "APPROVED"
    hospital.rejection_reason = None

    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Hospital approved successfully",
        "hospital": hospital_to_dict(hospital),
    }
# ============================================================
# ADMIN - REJECT HOSPITAL
# ============================================================

@app.put(
    "/admin/hospitals/{hospital_id}/reject"
)
def reject_hospital(
    hospital_id: int,
    data: AdminActionRequest,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )


    hospital.approval_status = (
        "REJECTED"
    )

    hospital.is_published = False

    hospital.rejection_reason = (
        data.reason
        or
        "Hospital registration rejected"
    )


    db.commit()

    db.refresh(hospital)


    return {

        "success": True,

        "message":
            "Hospital rejected successfully",

        "hospital":
            hospital_to_dict(
                hospital
            ),
    }


# ============================================================
# ADMIN - PUBLISH HOSPITAL
# ============================================================

@app.put(
    "/admin/hospitals/{hospital_id}/publish"
)
def publish_hospital(
    hospital_id: int,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )


    if (
        hospital.approval_status
        !=
        "APPROVED"
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Approve hospital "
                "before publishing"
            ),
        )


    hospital.is_published = True

    db.commit()

    db.refresh(hospital)


    return {

        "success": True,

        "message":
            "Hospital published to Patient App",

        "hospital":
            hospital_to_dict(
                hospital
            ),
    }


# ============================================================
# ADMIN - UNPUBLISH HOSPITAL
# ============================================================

@app.put(
    "/admin/hospitals/{hospital_id}/unpublish"
)
def unpublish_hospital(
    hospital_id: int,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )


    hospital.is_published = False

    db.commit()

    db.refresh(hospital)


    return {

        "success": True,

        "message":
            "Hospital unpublished",
    }

# ============================================================
# ADMIN - DELETE HOSPITAL
# ============================================================

@app.delete("/admin/hospitals/{hospital_id}")
def delete_hospital(
    hospital_id: int,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id == hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    # --------------------------------------------------------
    # Delete doctors
    # --------------------------------------------------------

    db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id
    ).delete(
        synchronize_session=False
    )

    # --------------------------------------------------------
    # Delete tokens linked by hospital_id
    # --------------------------------------------------------

    db.query(Token).filter(
        Token.hospital_id == hospital_id
    ).delete(
        synchronize_session=False
    )

    # --------------------------------------------------------
    # Delete old tokens without hospital_id
    # --------------------------------------------------------

    db.query(Token).filter(
        Token.hospital == hospital.name,
        Token.hospital_id == None,
    ).delete(
        synchronize_session=False
    )

    # --------------------------------------------------------
    # Delete hospital
    # --------------------------------------------------------

    db.delete(hospital)

    db.commit()

    return {
        "success": True,
        "message": "Hospital deleted successfully",
    }

# ============================================================
# ADD DOCTOR TO SPECIFIC HOSPITAL
# ============================================================

@app.post("/hospitals/{hospital_id}/doctors")
def add_hospital_doctor(
    hospital_id: int,
    data: HospitalDoctorCreate,
    db: Session = Depends(get_db),
):
    # Check hospital
    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == hospital_id)
        .first()
    )

    if not hospital:
        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    # Clean data
    name = data.name.strip()
    department = data.department.strip()

    specialization = (
        data.specialization.strip()
        if data.specialization
        else None
    )

    experience = (
        data.experience.strip()
        if data.experience
        else None
    )

    # Validate required fields
    if not name:
        raise HTTPException(
            status_code=400,
            detail="Doctor name is required",
        )

    if not department:
        raise HTTPException(
            status_code=400,
            detail="Department is required",
        )

    # Validate available days
    valid_days = {
        "Monday", "Tuesday", "Wednesday",
        "Thursday", "Friday", "Saturday", "Sunday"
    }

    available_days = []

    if data.available_days:
        available_days = [
            day.strip().capitalize()
            for day in data.available_days.split(",")
            if day.strip()
        ]

        invalid_days = [
            day for day in available_days
            if day not in valid_days
        ]

        if invalid_days:
            raise HTTPException(
                status_code=400,
                detail="Invalid availability day: "
                + ", ".join(invalid_days),
            )

        available_days = list(dict.fromkeys(available_days))

    # Validate consultation times
    from datetime import datetime

    start_time = (
        data.start_time.strip()
        if data.start_time
        else None
    )

    end_time = (
        data.end_time.strip()
        if data.end_time
        else None
    )

    if bool(start_time) != bool(end_time):
        raise HTTPException(
            status_code=400,
            detail="Enter both start time and end time.",
        )

    if start_time and end_time:
        try:
            start = datetime.strptime(start_time, "%H:%M")
            end = datetime.strptime(end_time, "%H:%M")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Times must use HH:MM format, for example 09:00.",
            )

        if start >= end:
            raise HTTPException(
                status_code=400,
                detail="End time must be later than start time.",
            )

    # Create doctor
    doctor = Doctor(
        hospital_id=hospital_id,
        name=name,
        department=department,
        specialization=specialization,
        experience=experience,
        available_days=",".join(available_days) or None,
        start_time=start_time,
        end_time=end_time,
        is_available=data.is_available,
    )

    db.add(doctor)
    db.commit()
    db.refresh(doctor)

    return {
        "success": True,
        "message": "Doctor added successfully",
        "doctor": doctor_to_dict(doctor),
    }

    # --------------------------------------------------------
    # CHECK HOSPITAL
    # --------------------------------------------------------

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id == hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    # --------------------------------------------------------
    # CLEAN DATA
    # --------------------------------------------------------

    name = data.name.strip()

    department = data.department.strip()

    specialization = (
        data.specialization.strip()
        if data.specialization
        else None
    )

    experience = (
        data.experience.strip()
        if data.experience
        else None
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if not name:

        raise HTTPException(
            status_code=400,
            detail="Doctor name is required",
        )

    if not department:

        raise HTTPException(
            status_code=400,
            detail="Department is required",
        )

    # --------------------------------------------------------
    # CREATE DOCTOR
    # --------------------------------------------------------

    doctor = Doctor(

        hospital_id=hospital_id,

        name=name,

        department=department,

        specialization=specialization,

        experience=experience,
    )

    db.add(doctor)

    db.commit()

    db.refresh(doctor)

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return {

        "success": True,

        "message":
            "Doctor added successfully",

        "doctor":
            doctor_to_dict(doctor),
    }
# ============================================================
# ADMIN - APPROVE PAYMENT ACCOUNT
# ============================================================

@app.put(
    "/admin/hospitals/{hospital_id}/payment-account/approve"
)
def approve_payment_account(
    hospital_id: int,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )


    if (
        not hospital.payment_account_name
        and
        not hospital.payment_upi
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Payment account details "
                "not added"
            ),
        )


    hospital.payment_account_status = (
        "APPROVED"
    )

    db.commit()

    db.refresh(hospital)


    return {

        "success": True,

        "message":
            (
                "Payment account marked "
                "as approved."
            ),

        "note":
            (
                "Approval does not automatically "
                "create a Razorpay linked account."
            ),
    }


# ============================================================
# ADMIN - REJECT PAYMENT ACCOUNT
# ============================================================

@app.put(
    "/admin/hospitals/{hospital_id}/payment-account/reject"
)
def reject_payment_account(
    hospital_id: int,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )


    hospital.payment_account_status = (
        "REJECTED"
    )

    db.commit()


    return {

        "success": True,

        "message":
            "Payment account rejected",
    }


# ============================================================
# ADMIN - REVENUE
# ============================================================

@app.get("/admin/revenue")
def admin_revenue(
    db: Session = Depends(get_db),
):

    paid_tokens = (
        db.query(Token)
        .filter(
            Token.payment_status ==
            "paid"
        )
        .all()
    )


    hospital_revenue = sum(

        int(
            token.token_fee or 0
        )

        for token in paid_tokens
    )


    platform_revenue = sum(

        int(
            token.platform_fee or 0
        )

        for token in paid_tokens
    )


    total_collected = sum(

        int(
            token.total_amount or 0
        )

        for token in paid_tokens
    )


    token_count = len(
        paid_tokens
    )


    return {

        "success": True,

        "hospital_revenue":
            hospital_revenue,

        "token_revenue":
            hospital_revenue,

        "platform_revenue":
            platform_revenue,

        "total_revenue":
            platform_revenue,

        "total_collected":
            total_collected,

        "token_count":
            token_count,

        "total_tokens":
            token_count,

        "platform_fee_per_token":
            PLATFORM_FEE,
    }


# ============================================================
# ADMIN - PAYMENT LIST
# ============================================================

@app.get("/admin/payments")
def admin_payments(
    db: Session = Depends(get_db),
):

    payments = (
        db.query(Token)
        .filter(
            Token.payment_status ==
            "paid"
        )
        .order_by(
            Token.created_at.desc()
        )
        .all()
    )


    return [

        token_to_dict(payment)

        for payment in payments
    ]


# ============================================================
# ADMIN - TOKEN LIST
# ============================================================

@app.get("/admin/tokens")
def admin_tokens(
    db: Session = Depends(get_db),
):

    tokens = (
        db.query(Token)
        .order_by(
            Token.created_at.desc()
        )
        .all()
    )


    return [

        token_to_dict(token)

        for token in tokens
    ]


# ============================================================
# ADMIN - HOSPITAL REVENUE
# ============================================================

@app.get(
    "/admin/hospitals/{hospital_id}/revenue"
)
def admin_hospital_revenue(
    hospital_id: int,
    db: Session = Depends(get_db),
):

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id ==
            hospital_id
        )
        .first()
    )

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )


    paid_tokens = (
        db.query(Token)
        .filter(
            Token.hospital_id ==
            hospital_id,

            Token.payment_status ==
            "paid",
        )
        .all()
    )


    hospital_revenue = sum(

        int(
            token.token_fee or 0
        )

        for token in paid_tokens
    )


    platform_revenue = sum(

        int(
            token.platform_fee or 0
        )

        for token in paid_tokens
    )


    total_collected = sum(

        int(
            token.total_amount or 0
        )

        for token in paid_tokens
    )


    return {

        "success": True,

        "hospital_id":
            hospital.id,

        "hospital":
            hospital.name,

        "paid_tokens":
            len(paid_tokens),

        "hospital_revenue":
            hospital_revenue,

        "platform_revenue":
            platform_revenue,

        "total_collected":
            total_collected,
    }


# ============================================================
# STARTUP INFORMATION
# ============================================================

print()
print("================================================")
print("CarePath FastAPI backend loaded")
print("Version: 11.0.0")
print(
    f"Razorpay configured: "
    f"{bool(razorpay_client)}"
)
print(
    f"Google Client ID configured: "
    f"{bool(GOOGLE_CLIENT_ID)}"
)
print("================================================")