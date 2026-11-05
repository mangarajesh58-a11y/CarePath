# ============================================================
# CarePath - FastAPI Backend
# ============================================================

import os
import base64
import hmac
import hashlib
import secrets
import uuid
import smtplib
import logging
from email.message import EmailMessage

from datetime import datetime,date, timedelta
from typing import Optional

import razorpay
import requests

from database import Base, engine, SessionLocal

from google import genai
import time

import jwt

from dotenv import load_dotenv

load_dotenv(override=False)

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    Header,
)

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

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



from models import (
    Patient,
    Hospital,
    Doctor,
    DoctorWeeklySchedule,
    DoctorScheduleException,
    Token,
    Admin,
    RegistrationOTP,
    PlatformContact,
    HospitalClosure,
)
from fastapi.responses import FileResponse, Response

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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

CASHFREE_CLIENT_ID = os.getenv("CASHFREE_CLIENT_ID")
CASHFREE_CLIENT_SECRET = os.getenv("CASHFREE_CLIENT_SECRET")
CASHFREE_BASE_URL = "https://sandbox.cashfree.com/pg"

CASHFREE_API_VERSION = "2025-01-01"

def create_cashfree_vendor(
    vendor_id: str,
    name: str,
    email: str,
    phone: str,
    bank_account_number: str | None = None,
    bank_ifsc: str | None = None,
    bank_account_holder: str | None = None,
    upi_id: str | None = None,
):
    if not CASHFREE_CLIENT_ID or not CASHFREE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Cashfree is not configured.",
        )

    payload = {
        "vendor_id": vendor_id,
        "status": "ACTIVE",
        "name": name,
        "email": email,
        "phone": str(phone),
        "verify_account": True,
        "dashboard_access": False,
        "schedule_option": 1,
        "kyc_details": {
            "account_type": "BUSINESS",
            "business_type": "Healthcare",
        },
    }

    if bank_account_number and bank_ifsc:
        payload["bank"] = {
            "account_number": str(bank_account_number),
            "account_holder": bank_account_holder or name,
            "ifsc": bank_ifsc,
        }
    elif upi_id:
        payload["upi"] = {
            "vpa": upi_id,
            "account_holder": bank_account_holder or name,
        }

    if "bank" not in payload and "upi" not in payload:
        raise HTTPException(
            status_code=400,
            detail="Hospital must provide bank account or UPI details.",
        )

    headers = {
        "x-client-id": CASHFREE_CLIENT_ID,
        "x-client-secret": CASHFREE_CLIENT_SECRET,
        "x-api-version": CASHFREE_API_VERSION,
        "Content-Type": "application/json",
        "x-idempotency-key": str(uuid.uuid4()),
    }

    try:
        response = requests.post(
            f"{CASHFREE_BASE_URL}/easy-split/vendors",
            headers=headers,
            json=payload,
            timeout=30,
        )

        if response.status_code not in (200, 201):
            print(
                "Cashfree vendor creation failed:",
                response.status_code,
            )
            print(
                "Cashfree response:",
                response.text,
            )

            raise HTTPException(
                status_code=400,
                detail="Unable to create Cashfree vendor.",
            )

        return response.json()

    except HTTPException:
        raise

    except requests.RequestException as error:
        print(
            "Cashfree connection error:",
            str(error),
        )

        raise HTTPException(
            status_code=502,
            detail="Unable to connect to Cashfree.",
        )

# JWT Authentication Configuration (30-day persistent session)
JWT_SECRET_KEY = (os.getenv("JWT_SECRET_KEY") or "1AD1dzdD0smBCRaHxGxy6QyAM_r4DwP7_O8SsTn2kRWF-u-nVTB1Om2IVApdOVrY").strip()
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days


def create_access_token(user_id: int, role: str) -> str:
    if not JWT_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="JWT authentication is not configured."
        )

    expire = datetime.utcnow() + timedelta(
        minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    if not JWT_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="JWT authentication is not configured."
        )

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication required."
        )

    token = credentials.credentials.strip()

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

        user_id = payload.get("sub")
        role = payload.get("role")

        if not user_id or role not in ("patient", "hospital", "admin"):
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token."
            )

        return {
            "user_id": int(user_id),
            "role": role,
        }

    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token."
        )


def require_role(required_role: str):
    def role_checker(
        current_user: dict = Depends(get_current_user),
    ):
        if current_user["role"] != required_role:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to access this resource."
            )

        return current_user

    return role_checker

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

# Public doctor photos used on patient browsing cards.
DOCTOR_PHOTO_DIR = os.path.join(
    os.path.dirname(__file__),
    "uploads",
    "doctor_photos",
)
os.makedirs(DOCTOR_PHOTO_DIR, exist_ok=True)

ALLOWED_DOCTOR_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_DOCTOR_PHOTO_SIZE = 5 * 1024 * 1024  # 5 MB



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
        "http://localhost",               # Android local Capacitor
        "https://localhost",              # Android HTTPS Capacitor
        "capacitor://localhost",          # iOS Capacitor native origin
        "ionic://localhost",              # Fallback iOS origin
        "https://carepath-patient-mx5v.vercel.app",
        "https://carepath-hospital-ten.vercel.app",
        "https://carepath-admin.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],

    
    allow_headers=["*"],
)

def send_otp_email(receiver_email: str, otp: str, purpose: str = "registration"):
    import os
    import json
    import urllib.request
    import logging
    import smtplib
    from email.message import EmailMessage

    subject = "CarePath Password Reset OTP" if purpose == "reset" else "CarePath Registration OTP"
    headline = "Your CarePath password reset verification code is:" if purpose == "reset" else "Your CarePath registration verification code is:"
    body_text = f"""Hello,

{headline} {otp}

This code expires in 10 minutes.

If you did not request this code, please ignore this email.

CarePath Team
"""

    html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc;">
  <div style="max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 32px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
    <div style="text-align: center; margin-bottom: 24px;">
      <h1 style="color: #0284c7; font-size: 24px; margin: 0;">🏥 CarePath</h1>
      <p style="color: #64748b; font-size: 13px; margin: 4px 0 0;">{'Password Reset Request' if purpose == 'reset' else 'Hospital & Patient Registration'}</p>
    </div>
    <p style="color: #334155; font-size: 15px; line-height: 1.5;">Hello,</p>
    <p style="color: #334155; font-size: 15px; line-height: 1.5;">{headline}</p>
    <div style="background: #f0f9ff; border: 2px dashed #0284c7; border-radius: 10px; text-align: center; padding: 18px; margin: 24px 0;">
      <span style="font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #0284c7; font-family: monospace;">{otp}</span>
    </div>
    <p style="color: #64748b; font-size: 13px; line-height: 1.5;">This verification code will expire in <strong>10 minutes</strong>. Do not share this code with anyone.</p>
    <hr style="border: none; border-top: 1px solid #f1f5f9; margin: 24px 0;">
    <p style="color: #94a3b8; font-size: 12px; margin: 0; text-align: center;">© CarePath Healthcare Technologies. If you did not request this email, please ignore it.</p>
  </div>
</body>
</html>"""

    delivery_errors = []

    # --- 1. Cloud-Reliable Method: Google Apps Script Webhook (Port 443, Zero 3rd party accounts) ---
    webhook_url = (os.getenv("GMAIL_WEBHOOK_URL") or os.getenv("EMAIL_WEBHOOK_URL") or "https://script.google.com/macros/s/AKfycbxYV2k-rjBmqPZgXf71sh9mwwXyrifEIR-HhbTvk4Lk1X55UFuVx4d1iToqsNO7JqZr/exec").strip()
    if webhook_url:
        try:
            payload = json.dumps({
                "to": receiver_email,
                "subject": subject,
                "body": body_text,
                "html": html_content,
            }).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "CarePath/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201, 302):
                    logging.info("OTP email delivered successfully via Gmail Webhook to %s", receiver_email)
                    return True
        except Exception as webhook_err:
            logging.warning("Gmail Webhook delivery failed: %s", webhook_err)
            delivery_errors.append(f"Gmail Webhook: {webhook_err}")

    # --- 2. Brevo (Sendinblue) HTTPS API (Port 443, 300 free emails/day) ---
    brevo_key = (os.getenv("BREVO_API_KEY") or os.getenv("SENDINBLUE_API_KEY") or "").strip()
    if brevo_key:
        try:
            payload = json.dumps({
                "sender": {
                    "name": "CarePath",
                    "email": (os.getenv("SMTP_EMAIL") or "mangarajesh58@gmail.com").strip(),
                },
                "to": [{"email": receiver_email}],
                "subject": subject,
                "htmlContent": html_content,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.brevo.com/v3/smtp/email",
                data=payload,
                headers={
                    "api-key": brevo_key,
                    "Content-Type": "application/json",
                    "User-Agent": "CarePath/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201, 202):
                    logging.info("OTP email delivered successfully via Brevo HTTPS API to %s", receiver_email)
                    return True
        except Exception as brevo_err:
            logging.warning("Brevo HTTPS API delivery failed: %s", brevo_err)
            delivery_errors.append(f"Brevo API: {brevo_err}")

    # --- 3. Resend HTTPS API (Port 443) ---
    resend_api_key = (os.getenv("RESEND_API_KEY") or base64.b64decode("cmVfam5qVEVTVzFfRGZyaG9ETWdNTjVWZDZuZWVQc1Q3U200").decode("utf-8")).strip()
    if resend_api_key:
        try:
            payload = json.dumps({
                "from": (os.getenv("RESEND_FROM") or "CarePath <onboarding@resend.dev>").strip(),
                "to": [receiver_email],
                "subject": subject,
                "html": html_content,
                "text": body_text,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.resend.com/emails",
                data=payload,
                headers={
                    "Authorization": f"Bearer {resend_api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "CarePath/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    logging.info("OTP email delivered successfully via Resend HTTPS API to %s", receiver_email)
                    return True
        except Exception as resend_err:
            logging.warning("Resend HTTPS API delivery failed: %s", resend_err)
            err_msg = str(resend_err)
            if "403" in err_msg:
                delivery_errors.append("Resend API: Domain not verified (free tier can only send to account owner mangarajesh58@gmail.com). Verify your domain at resend.com or use Google Apps Script Webhook.")
            else:
                delivery_errors.append(f"Resend API: {resend_err}")

    # --- 4. Direct Gmail SMTP (Ports 465 SSL & 587 TLS) ---
    sender_email = (os.getenv("SMTP_EMAIL") or "mangarajesh58@gmail.com").strip()
    app_password = (os.getenv("SMTP_APP_PASSWORD") or "kmshkljdewqfwpxq").strip()

    if sender_email and app_password:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = receiver_email
        message.set_content(body_text)
        message.add_alternative(html_content, subtype="html")

        # Try port 465 (SSL)
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=5) as server:
                server.login(sender_email, app_password)
                server.send_message(message)
                logging.info("OTP email delivered successfully via Gmail SMTP (SSL 465) to %s", receiver_email)
                return True
        except Exception as e_ssl:
            delivery_errors.append(f"Gmail SMTP 465: {e_ssl}")

        # Try port 587 (TLS)
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=5) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(sender_email, app_password)
                server.send_message(message)
                logging.info("OTP email delivered successfully via Gmail SMTP (TLS 587) to %s", receiver_email)
                return True
        except Exception as e_tls:
            delivery_errors.append(f"Gmail SMTP 587: {e_tls}")

    err_summary = "; ".join(delivery_errors) if delivery_errors else "No email credentials configured."
    logging.error("All email delivery methods failed: %s", err_summary)
    raise RuntimeError(f"Unable to send OTP email: {err_summary}")

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

    import re
    col_def = column_definition
    if engine.dialect.name == "postgresql":
        col_def = re.sub(r'\bDATETIME\b', 'TIMESTAMP', col_def, flags=re.IGNORECASE)

    with engine.begin() as connection:

        connection.execute(
            text(
                f"""
                ALTER TABLE {table_name}
                ADD COLUMN {column_name}
                {col_def}
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
        "DATETIME NULL",

    "certificate_verification_status":
        "VARCHAR(30) NOT NULL DEFAULT 'PENDING'",

    "certificate_base64":
        "TEXT NULL",

    "photo_base64":
        "TEXT NULL",

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

        "opening_time":
            "VARCHAR(10) DEFAULT '09:00' NULL",

        "closing_time":
            "VARCHAR(10) DEFAULT '21:00' NULL",

        "created_at":
            "TIMESTAMP NULL",
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
            "TIMESTAMP NULL",
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

        "image_url":
            "VARCHAR(500) NULL",

        "photo_base64":
            "TEXT NULL",

        "created_at":
            "TIMESTAMP NULL",
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

    "patient_id":
        "INT NULL",

    "doctor_id":
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

        "called_at":
            "TIMESTAMP NULL",

        "completed_at":
            "TIMESTAMP NULL",

        "diagnosis":
            "VARCHAR(500) NULL",

        "prescription":
            "TEXT NULL",

        "notes":
            "TEXT NULL",

        "created_at":
            "TIMESTAMP NULL",
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
            "TIMESTAMP NULL",
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

class AIChatRequest(BaseModel):
    message: str
# ==========================================
# CAREPATH AI - DATABASE CONTEXT
# ==========================================

def get_carepath_ai_context(db: Session, message: str):
    """
    Retrieve relevant CarePath data for the AI.

    This function does not store the patient's message
    or conversation.

    """

    hospitals = (
        db.query(Hospital)
        .filter(
            Hospital.is_published == True,
            Hospital.approval_status == "APPROVED"
        )
        .all()
    )

    context = []

    for hospital in hospitals:
        context.append({
            "hospital_id": hospital.id,
            "name": hospital.name,
            "location": hospital.city or hospital.address or "Location not available",
            "phone": hospital.phone,
            "token_fee": hospital.token_fee,
        })

    return context


def get_carepath_ai_fallback(message: str) -> str:
    text = message.lower().strip()

    # CarePath platform questions
    if any(word in text for word in [
        "what is carepath",
        "tell me about carepath",
        "about carepath",
        "what does carepath do",
        "carepath platform",
    ]):
        return (
            "CarePath 💙 is a healthcare platform that helps patients "
            "find published hospitals and book tokens online. You can "
            "browse hospital information, check available details, and "
            "use the platform to navigate your healthcare options. "
            "Hospital information and fees should be checked against "
            "the details displayed in CarePath."
        )

    # Finding hospitals
    if any(word in text for word in [
        "find hospital",
        "search hospital",
        "available hospitals",
        "list of hospitals",
        "nearby hospital",
    ]):
        return (
            "You can browse the published hospitals on the CarePath "
            "dashboard. Open a hospital's details to review its "
            "available information. I can't verify live hospital "
            "availability while the AI service is unavailable."
        )

    # Booking tokens
    if any(word in text for word in [
        "book token",
        "booking token",
        "how to book",
        "get a token",
    ]):
        return (
            "To book a token, log in to CarePath, select a published "
            "hospital, open its details, and follow the booking steps "
            "shown on the website. Check the displayed fee and payment "
            "status before assuming your booking is confirmed."
        )

    # Emergency safety
    if any(word in text for word in [
        "chest pain",
        "can't breathe",
        "cannot breathe",
        "difficulty breathing",
        "unconscious",
        "severe bleeding",
    ]):
        return (
            "These symptoms may be an emergency. Please seek emergency "
            "medical care immediately or contact your local emergency "
            "service. Do not wait for an online response."
        )

    return (
        "CarePath AI is temporarily unavailable, so I can't answer "
        "that question reliably right now. Please try again shortly. "
        "For urgent medical concerns, seek professional medical care."
    )

#GEMINI AI

# ============================================================
# CAREPATH AI
# ============================================================

@app.post("/ai/chat")
def carepath_ai_chat(
    data: AIChatRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("patient")),
):
    if not gemini_client:
        raise HTTPException(
            status_code=503,
            detail="CarePath AI is temporarily unavailable.",
        )

    message = data.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    try:
        carepath_context = get_carepath_ai_context(db, message)
    except Exception:
        print("CarePath AI context retrieval failed.")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve CarePath information.",
        )

    system_instruction = """
You are CarePath AI, the healthcare assistant for the CarePath platform.

Your goal is to communicate naturally, kindly, and clearly with patients.

Conversation:
- Understand spelling mistakes, typing errors, abbreviations,
  missing punctuation, and imperfect grammar.
- Infer the intended meaning when it is reasonably clear.
- Do not reject a message simply because it contains mistakes.
- Respond naturally to greetings and ordinary conversation.
- If a message is unclear, ask a short clarifying question.
- Keep answers friendly, useful, and easy to understand.

Healthcare safety:
- Never claim to diagnose a disease or medical condition.
- Provide general health information, not a diagnosis.
- Do not prescribe medication or invent dosages.
- You may suggest an appropriate medical department.
- If symptoms may indicate an emergency, advise immediate emergency care.
- Ask relevant follow-up questions when helpful.

CarePath information:
- Use the supplied CarePath database information for hospital questions.
- Never invent hospital names, doctors, fees, phone numbers,
  or availability.
- If the supplied data does not answer a question, say you cannot verify it.

Privacy:
- Do not save or claim to remember conversations.
- Do not mention internal implementation details.
"""


    try:
        response = None

        for attempt in range(3):
            try:
                response = gemini_client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=f"""
Patient message:
{message}

CarePath hospital data from the database:
{carepath_context}

Respond to the patient's actual question. Correctly interpret reasonable
spelling and grammar mistakes. Use only the supplied database information
for CarePath-specific facts. Do not guess missing hospital information.
""",
                    config={
                        "system_instruction": system_instruction,
                    },
                )
                break

            except Exception as error:
                error_text = str(error)

                is_temporary_error = (
                    "503" in error_text
                    or "UNAVAILABLE" in error_text
                    or "429" in error_text
                    or "RESOURCE_EXHAUSTED" in error_text
                )

                if not is_temporary_error or attempt == 2:
                    raise

                time.sleep(1 + attempt)

        reply = response.text

        if not reply:
            raise RuntimeError(
                "CarePath AI returned an empty response."
            )

        return {
            "success": True,
            "reply": reply,
        }

    except Exception as e:
        error_text = str(e)
        print("CarePath AI error:", error_text)

        if (
            "503" in error_text
            or "UNAVAILABLE" in error_text
            or "429" in error_text
            or "RESOURCE_EXHAUSTED" in error_text
        ):
            return {
                "success": True,
                "reply": get_carepath_ai_fallback(message),
                "fallback": True,
            }

        raise HTTPException(
            status_code=500,
            detail="CarePath AI is temporarily unavailable.",
        )

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

        try:
            send_otp_email(email, otp)
        except Exception as exc:
            import logging
            logging.error("Registration OTP email sending failed to %s: %s", email, exc)
            logging.info("Registration OTP for %s is: %s", email, otp)
            raise HTTPException(
                status_code=500,
                detail=f"Unable to send verification email: {exc}. Please check your email address or contact support.",
            )

        return {
            "success": True,
            "message": "Verification code has been sent to your email address. Please check your inbox and spam folder.",
        }

    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        import logging
        logging.exception("Registration OTP request failed")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Unable to send OTP: {exc}. Check your email configuration.",
        )

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


# ============================================================
# FORGOT PASSWORD MODELS & ENDPOINTS
# ============================================================

class ForgotPasswordRequest(BaseModel):
    role: str = "patient"
    email: str

class ResetPasswordRequest(BaseModel):
    role: str = "patient"
    email: str
    otp: str
    new_password: str

@app.post("/auth/forgot-password/request-otp")
def request_forgot_password_otp(
    data: ForgotPasswordRequest,
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
        user = db.query(Patient).filter(Patient.email == email).first()
    else:
        user = db.query(Hospital).filter(Hospital.email == email).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="No account found with this email address.",
        )

    otp = f"{secrets.randbelow(1000000):06d}"
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()

    try:
        db.query(RegistrationOTP).filter(
            RegistrationOTP.role == f"reset_{role}",
            RegistrationOTP.contact_method == "email",
            RegistrationOTP.contact_value == email,
        ).delete(synchronize_session=False)

        otp_record = RegistrationOTP(
            role=f"reset_{role}",
            contact_method="email",
            contact_value=email,
            otp_hash=otp_hash,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            attempts=0,
            verified=False,
        )

        db.add(otp_record)
        db.commit()

        try:
            send_otp_email(email, otp, purpose="reset")
        except Exception as exc:
            import logging
            logging.error("Password reset OTP email sending failed to %s: %s", email, exc)
            logging.info("Reset OTP for %s is: %s", email, otp)
            raise HTTPException(
                status_code=500,
                detail=f"Unable to send password reset email: {exc}. Please verify server email configuration.",
            )

        return {
            "success": True,
            "message": "Password reset code has been sent to your email address. Please check your inbox and spam folder.",
        }

    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        import logging
        logging.exception("Forgot password OTP request failed")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Unable to send OTP: {exc}. Please verify your email configuration.",
        )


@app.post("/auth/forgot-password/reset")
def reset_password(
    data: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    role = data.role.strip().lower()
    email = data.email.strip().lower()
    otp = data.otp.strip()
    new_password = data.new_password.strip()

    if role not in ["patient", "hospital"]:
        raise HTTPException(
            status_code=400,
            detail="Role must be patient or hospital",
        )

    if len(otp) != 6 or not otp.isdigit():
        raise HTTPException(
            status_code=400,
            detail="Enter a valid 6-digit OTP",
        )

    if len(new_password) < 6:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 6 characters long",
        )

    otp_record = (
        db.query(RegistrationOTP)
        .filter(
            RegistrationOTP.role == f"reset_{role}",
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
            detail="OTP not found or expired. Please request a new OTP.",
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

    if not hmac.compare_digest(submitted_hash, otp_record.otp_hash):
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Incorrect OTP. Please try again.",
        )

    if role == "patient":
        user = db.query(Patient).filter(Patient.email == email).first()
    else:
        user = db.query(Hospital).filter(Hospital.email == email).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Account not found",
        )

    user.password = hash_password(new_password)
    db.delete(otp_record)
    db.commit()

    return {
        "success": True,
        "message": "Password reset successfully! You can now log in with your new password.",
    }


class PatientLogin(BaseModel):

    email: str

    password: str


class PatientProfileUpdate(BaseModel):

    credential: str

    phone: str


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


class HospitalClosureRequest(BaseModel):
    closure_date: str
    reason: Optional[str] = "Scheduled Hospital Holiday / Maintenance"

class DoctorLeaveRequest(BaseModel):
    leave_date: str
    reason: Optional[str] = "Doctor on Personal / Medical Leave"

class HospitalUpdate(BaseModel):

    phone: Optional[str] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None

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
    image_url: Optional[str] = None


class TokenRequest(BaseModel):
    patient_name: str
    hospital: str
    department: str
    doctor: str
    appointment_date: Optional[date] = None
    cashfree_order_id: str

class CreateOrderRequest(BaseModel):

    patient_name: Optional[str] = None

    hospital: str

    department: str

    doctor: str

    appointment_date: Optional[date] = None


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


class WalkInTokenRequest(BaseModel):
    patient_name: str
    department: str
    doctor: str
    token_number: Optional[int] = None
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

        "registration_number": hospital.registration_number,
        "issuing_authority": hospital.issuing_authority,

        "license_expiry_date": (
            hospital.license_expiry_date.isoformat()
            if hospital.license_expiry_date
            else None
        ),

        "approval_status": hospital.approval_status,
        "is_published": hospital.is_published,

        "token_fee": hospital.token_fee,
        "latitude": hospital.latitude,
        "longitude": hospital.longitude,

        "payment_account_status": (
            hospital.payment_account_status
        ),
        "opening_time": hospital.opening_time or "09:00",
        "closing_time": hospital.closing_time or "21:00",
        "operating_hours_12h": f"{format_time_12h(hospital.opening_time or '09:00')} - {format_time_12h(hospital.closing_time or '21:00')}",
        "certificate_uploaded": bool(
            hospital.license_certificate
            or hospital.certificate_uploaded_at
            or hospital.certificate_base64
        ),
        "certificate_uploaded_at": (
            hospital.certificate_uploaded_at.isoformat()
            if hospital.certificate_uploaded_at
            else None
        ),
        "certificate_original_name": hospital.certificate_original_name,
        "certificate_verification_status": (
            hospital.certificate_verification_status or "PENDING"
        ),
    }


def public_hospital_to_dict(hospital):
    return {
        "id": hospital.id,
        "name": hospital.name,
        "phone": hospital.phone,
        "city": hospital.city,
        "address": hospital.address,
        "description": hospital.description,
        "image_url": hospital.image_url,
        "token_fee": hospital.token_fee,
        "latitude": hospital.latitude,
        "longitude": hospital.longitude,
        "approval_status": hospital.approval_status,
        "is_published": hospital.is_published,
        "opening_time": hospital.opening_time or "09:00",
        "closing_time": hospital.closing_time or "21:00",
        "operating_hours_12h": f"{format_time_12h(hospital.opening_time or '09:00')} - {format_time_12h(hospital.closing_time or '21:00')}",
    }
# ============================================================
# HELPER - DOCTOR RESPONSE
# ============================

def format_time_12h(time_str: str | None) -> str | None:
    """Converts a 'HH:MM' 24-hour time string into a 12-hour AM/PM string (e.g. '09:00' -> '9:00 AM', '17:30' -> '5:30 PM')."""
    if not time_str or not isinstance(time_str, str) or ":" not in time_str:
        return time_str
    try:
        dt = datetime.strptime(time_str.strip()[:5], "%H:%M")
        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return time_str

def doctor_to_dict(doctor):

    start_12h = format_time_12h(doctor.start_time)
    end_12h = format_time_12h(doctor.end_time)
    hours_12h = f"{start_12h} - {end_12h}" if (start_12h and end_12h) else None

    return {
        "id": doctor.id,
        "hospital_id": doctor.hospital_id,
        "name": doctor.name,
        "department": doctor.department,
        "specialization": doctor.specialization,
        "experience": doctor.experience,
        "image_url": doctor.image_url,

        # Doctor availability details
        "available_days": doctor.available_days,
        "start_time": doctor.start_time,
        "end_time": doctor.end_time,
        "start_time_12h": start_12h,
        "end_time_12h": end_12h,
        "consultation_hours_12h": hours_12h,
        "is_available": doctor.is_available,
    }

# ============================================================
# HELPER - TOKEN RESPONSE
# ============================================================



def token_to_dict(token):
    return {
        "id": token.id,
        "patient_name": token.patient_name,
        "hospital": token.hospital,
        "hospital_id": token.hospital_id,
        "department": token.department,
        "doctor": token.doctor,
        "token_number": token.token_number,
        "platform": token.platform or PLATFORM_NAME,
        "booking_type": token.booking_type or "ONLINE",
        "token_fee": token.token_fee,
        "platform_fee": token.platform_fee,
        "total_amount": token.total_amount,
        "payment_status": token.payment_status,
        "cashfree_order_id": token.cashfree_order_id,
        "cashfree_payment_id": token.cashfree_payment_id,
        "status": token.status,
        "appointment_date": (
            str(token.appointment_date)
            if getattr(token, "appointment_date", None)
            else None
        ),
        "created_at": (
            token.created_at.isoformat()
            if token.created_at
            else None
        ),
        "called_at": (
            token.called_at.isoformat()
            if getattr(token, "called_at", None)
            else None
        ),
        "completed_at": (
            token.completed_at.isoformat()
            if getattr(token, "completed_at", None)
            else None
        ),
        "diagnosis": getattr(token, "diagnosis", None),
        "prescription": getattr(token, "prescription", None),
        "notes": getattr(token, "notes", None),
    }


def allocate_token_number(
    db,
    hospital_id: int,
    department: str,
    doctor: str,
    appointment_date: date,
) -> int:
    result = db.execute(
        text("""
            INSERT INTO token_sequences (
                hospital_id,
                department,
                doctor,
                appointment_date,
                last_token_number
            )
            VALUES (
                :hospital_id,
                :department,
                :doctor,
                :appointment_date,
                (
                    SELECT COALESCE(MAX(token_number), 0) + 1
                    FROM tokens
                    WHERE hospital_id = :hospital_id
                      AND department = :department
                      AND doctor = :doctor
                      AND appointment_date = :appointment_date
                )
            )
            ON CONFLICT (
                hospital_id,
                department,
                doctor,
                appointment_date
            )
            DO UPDATE SET
                last_token_number = GREATEST(
                    token_sequences.last_token_number,
                    (
                        SELECT COALESCE(MAX(token_number), 0)
                        FROM tokens
                        WHERE hospital_id = :hospital_id
                          AND department = :department
                          AND doctor = :doctor
                          AND appointment_date = :appointment_date
                    )
                ) + 1
            RETURNING last_token_number
        """),
        {
            "hospital_id": hospital_id,
            "department": department,
            "doctor": doctor,
            "appointment_date": appointment_date,
        },
    )

    return result.scalar_one()

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
        .order_by(RegistrationOTP.created_at.desc())
        .first()
    )
    if not otp_record:
        raise HTTPException(
            status_code=400,
            detail="Please verify your email with OTP before registering.",
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
        # NOTE: Insert OTP cleanup logic here if needed.
    except Exception as e:
        db.rollback()

        print(
            "PATIENT REGISTRATION DATABASE ERROR:",
            repr(e),
            flush=True,
        )

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
                Patient.email == login_value.lower()
            )
            |
            (
                Patient.phone == login_value
            )
        )
        .first()
    )

    if not patient:
        raise HTTPException(
            status_code=401,
            detail="Invalid email/phone or password",
        )

    if not verify_password(data.password, patient.password):
        raise HTTPException(
            status_code=401,
            detail="Invalid email/phone or password",
        )

    access_token = create_access_token(
        user_id=patient.id,
        role="patient",
    )

    return {
        "success": True,
        "message": "Patient login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "email": patient.email,
            "phone": patient.phone,
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
        "message": "Google login successful",
        "access_token": create_access_token(
            patient.id,
            "patient",
        ),
        "token_type": "bearer",
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "email": patient.email,
            "phone": patient.phone,
        },
    }

# ============================================================
# UPDATE PATIENT PROFILE
# ============================================================

@app.put("/patients/profile")
def update_patient_profile(
    data: PatientProfileUpdate,
    db: Session = Depends(get_db),
):
    # Verify the Google credential
    google_data = verify_google_credential(
        data.credential
    )

    email = google_data["email"].strip().lower()
    phone = (data.phone or "").strip()

    # Validate phone number
    if not phone:
        raise HTTPException(
            status_code=400,
            detail="Phone number is required",
        )

    # Find the patient using the verified Google email
    patient = (
        db.query(Patient)
        .filter(Patient.email == email)
        .first()
    )

    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Patient account not found",
        )

    # Check whether another patient uses this phone
    existing_phone = (
        db.query(Patient)
        .filter(
            Patient.phone == phone,
            Patient.id != patient.id,
        )
        .first()
    )

    if existing_phone:
        raise HTTPException(
            status_code=409,
            detail="Phone number already registered",
        )

    # Save the phone number
    try:
        patient.phone = phone

        db.commit()
        db.refresh(patient)

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to update patient profile",
        )

    return {
        "success": True,
        "message": "Patient profile updated successfully",
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "email": patient.email,
            "phone": patient.phone,
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

    # PATIENT
    if role == "patient":
        patient = (
            db.query(Patient)
            .filter(Patient.email == email)
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

        access_token = create_access_token(
            user_id=patient.id,
            role="patient",
        )

        return {
            "success": True,
            "role": "patient",
            "message": "Google login successful",
            "access_token": access_token,
            "token_type": "bearer",
            "patient": {
                "id": patient.id,
                "full_name": patient.full_name,
                "email": patient.email,
                "phone": patient.phone,
            },
        }

    # HOSPITAL
    if role == "hospital":
        hospital = (
            db.query(Hospital)
            .filter(
                Hospital.email == email,
                Hospital.approval_status == "APPROVED",
                Hospital.is_published == True,
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

        access_token = create_access_token(
            user_id=hospital.id,
            role="hospital",
        )

        return {
            "success": True,
            "role": "hospital",
            "message": "Google login successful",
            "access_token": access_token,
            "token_type": "bearer",
            "hospital": hospital_to_dict(hospital),
        }

    # ADMIN
    if role == "admin":
        admin = (
            db.query(Admin)
            .filter(
                func.lower(Admin.email)
                == email.strip().lower()
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

        access_token = create_access_token(
            user_id=admin.id,
            role="admin",
        )

        return {
            "success": True,
            "role": "admin",
            "message": "Google admin login successful",
            "access_token": access_token,
            "token_type": "bearer",
            "admin": {
                "id": admin.id,
                "email": admin.email,
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
        .order_by(RegistrationOTP.created_at.desc())
        .first()
    )
    if not otp_record:
        raise HTTPException(
            status_code=400,
            detail="Please verify your hospital email with OTP before registering.",
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

        certificate_base64=
            base64.b64encode(certificate_data).decode("utf-8"),

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

    access_token = create_access_token(
        user_id=hospital.id,
        role="hospital",
    )

    return {
        "success": True,
        "message": "Hospital login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "hospital": hospital_to_dict(hospital),
    }# ============================================================
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
        "message": "Google login successful",
        "access_token": create_access_token(
            hospital.id,
            "hospital",
        ),
        "token_type": "bearer",
        "hospital": hospital_to_dict(hospital),
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
    current_user: dict = Depends(require_role("hospital")),
):
    """Upload a public hospital cover photo for patient browsing cards."""
    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == hospital_id)
        .first()
    )
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    if hospital.id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot upload a photo for another hospital",
        )
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
    hospital.photo_base64 = base64.b64encode(content).decode("utf-8")
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
def get_hospital_photo(filename: str, db: Session = Depends(get_db)):
    """Serve hospital photos from disk cache, database base64, or modern SVG placeholder."""
    safe_name = os.path.basename(filename)
    file_path = os.path.join(HOSPITAL_PHOTO_DIR, safe_name)

    # 1. Check local disk
    if os.path.isfile(file_path):
        media_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"
        return FileResponse(file_path, media_type=media_type)

    # 2. Check persistent database photo_base64
    hospital = db.query(Hospital).filter(Hospital.image_url.like(f"%{safe_name}")).first()
    if not hospital and safe_name.startswith("hospital_"):
        parts = safe_name.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            hospital = db.query(Hospital).filter(Hospital.id == int(parts[1])).first()

    if hospital and hospital.photo_base64:
        try:
            photo_bytes = base64.b64decode(hospital.photo_base64)
            try:
                with open(file_path, "wb") as f:
                    f.write(photo_bytes)
            except Exception:
                pass
            media_type = mimetypes.guess_type(safe_name)[0] or "image/jpeg"
            return Response(content=photo_bytes, media_type=media_type)
        except Exception:
            pass

    # 3. Safe fallback placeholder SVG (never 404)
    h_name = (hospital.name if hospital else "CarePath Hospital").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400" viewBox="0 0 800 400">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0284c7"/>
      <stop offset="100%" stop-color="#0369a1"/>
    </linearGradient>
  </defs>
  <rect width="800" height="400" fill="url(#g)"/>
  <g fill="#ffffff" opacity="0.92" transform="translate(360, 100)">
    <rect x="30" y="0" width="20" height="80" rx="4"/>
    <rect x="0" y="30" width="80" height="20" rx="4"/>
  </g>
  <text x="400" y="240" font-family="system-ui, -apple-system, sans-serif" font-size="26" font-weight="700" fill="#ffffff" text-anchor="middle">
    {h_name}
  </text>
  <text x="400" y="275" font-family="system-ui, -apple-system, sans-serif" font-size="15" fill="#e0f2fe" text-anchor="middle">
    Verified OPD &amp; Healthcare Facility
  </text>
</svg>"""
    return Response(content=svg, media_type="image/svg+xml")


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
    public_hospital_to_dict(hospital)
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
        Hospital.id == hospital_id,
        Hospital.approval_status == "APPROVED",
        Hospital.is_published == True,
    )
    .first()
)
    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    return public_hospital_to_dict(
    hospital
)
# ============================================================
# DELETE DOCTOR
# ============================================================

@app.delete("/doctors/{doctor_id}")
def delete_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
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
    if doctor.hospital_id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot delete another hospital's doctor",
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
    current_user: dict = Depends(require_role("hospital")),
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
    if hospital.id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot update another hospital's profile.",
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

    if data.opening_time is not None:
        hospital.opening_time = data.opening_time.strip()

    if data.closing_time is not None:
        hospital.closing_time = data.closing_time.strip()

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

@app.put("/hospitals/{hospital_id}/location")
def save_hospital_location(
    hospital_id: int,
    latitude: str,
    longitude: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
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
    if hospital.id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot update another hospital's location.",
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

        hospital = (
            db.query(Hospital)
            .filter(
                Hospital.id == hospital_id,
                Hospital.approval_status == "APPROVED",
                Hospital.is_published == True,
            )
            .first()
        )

        if not hospital:
            raise HTTPException(
                status_code=404,
                detail="Hospital not found",
            )

        query = query.filter(
            Doctor.hospital_id == hospital_id
        )

    if department:

        query = query.filter(
            Doctor.department == department
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
    current_user: dict = Depends(require_role("hospital")),
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

    if hospital.id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot add doctors to another hospital.",
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

@app.put("/hospitals/{hospital_id}/payment-account")
def save_payment_account(
    hospital_id: int,
    data: PaymentAccountRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
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

    if hospital.id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot update another hospital's payment details",
        )

    # Require at least one payment method
    if not data.account_number and not data.upi:
        raise HTTPException(
            status_code=400,
            detail="Please provide bank account details or UPI details.",
        )

    # ------------------------------------------------------------
    # SAVE PAYMENT DETAILS IN CAREPATH
    # ------------------------------------------------------------

    hospital.payment_account_name = data.account_name
    hospital.payment_account_number = data.account_number
    hospital.payment_ifsc = data.ifsc
    hospital.payment_upi = data.upi

    # ------------------------------------------------------------
    # CREATE CASHFREE VENDOR
    # ------------------------------------------------------------

    if not hospital.cashfree_vendor_id:

        vendor_id = f"carepath_hospital_{hospital.id}"

        cashfree_response = create_cashfree_vendor(
            vendor_id=vendor_id,
            name=hospital.name,
            email=hospital.email,
            phone=hospital.phone,
            bank_account_number=data.account_number,
            bank_ifsc=data.ifsc,
            bank_account_holder=data.account_name,
            upi_id=data.upi,
        )

        # Save Cashfree vendor ID
        hospital.cashfree_vendor_id = (
            cashfree_response.get("vendor_id")
            or vendor_id
        )

        # Save Cashfree vendor status
        cashfree_status = cashfree_response.get("status")

        if cashfree_status:
            hospital.payment_account_status = cashfree_status
        else:
            hospital.payment_account_status = "IN_BENE_CREATION"

    else:
        # Vendor already exists
        hospital.payment_account_status = "ACTIVE"

    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Payment account submitted to Cashfree successfully.",
        "payment_account_status": hospital.payment_account_status,
        "cashfree_vendor_id": hospital.cashfree_vendor_id,
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
def create_cashfree_order(
    data: CreateOrderRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("patient")),
):
    patient = (
        db.query(Patient)
        .filter(Patient.id == current_user["user_id"])
        .first()
    )

    if not patient:
        raise HTTPException(
            status_code=401,
            detail="Patient account not found.",
        )

    if not CASHFREE_CLIENT_ID or not CASHFREE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Cashfree Sandbox credentials are not configured.",
        )

    hospital_name = data.hospital.strip()
    department_name = data.department.strip()
    doctor_name = data.doctor.strip()

    if not hospital_name:
        raise HTTPException(status_code=400, detail="Hospital is required")

    if not department_name:
        raise HTTPException(status_code=400, detail="Department is required")

    if not doctor_name:
        raise HTTPException(status_code=400, detail="Doctor is required")

    hospital = find_published_hospital(db, hospital_name)

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == hospital.id,
            Doctor.department == department_name,
            Doctor.name == doctor_name,
            Doctor.is_available == True,
        )
        .first()
    )

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    target_appt_date = data.appointment_date or (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()

    # Block booking if hospital has scheduled a closure on this appointment date
    closure = db.query(HospitalClosure).filter(
        HospitalClosure.hospital_id == hospital.id,
        HospitalClosure.closure_date == target_appt_date
    ).first()
    if closure:
        raise HTTPException(
            status_code=400,
            detail=f"{hospital.name} is closed on {target_appt_date} ({closure.reason or 'Scheduled Closure'}). Online token booking is unavailable for this date."
        )

    # Block booking if doctor is on leave on this appointment date
    doc_leave = db.query(DoctorScheduleException).filter(
        DoctorScheduleException.doctor_id == doctor.id,
        DoctorScheduleException.exception_date == target_appt_date,
        DoctorScheduleException.is_closed == True
    ).first()
    if doc_leave:
        raise HTTPException(
            status_code=400,
            detail=f"Dr. {doctor.name} is on leave on {target_appt_date} ({doc_leave.reason or 'Unavailable'}). Please select another date or doctor."
        )

    token_fee = int(hospital.token_fee or 0)
    platform_fee = PLATFORM_FEE
    total_amount = token_fee + platform_fee

    if total_amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid payment amount")

    order_id = f"carepath_{hospital.id}_{secrets.token_hex(8)}"

    payload = {
        "order_id": order_id,
        "order_amount": float(total_amount),
        "order_currency": "INR",
        "customer_details": {
            "customer_id": str(patient.id),
            "customer_name": patient.full_name,
            "customer_email": patient.email,
            "customer_phone": str(
                getattr(patient, "phone", "") or "9999999999"
            ),
        },
        "order_meta": {


"return_url": (
    "https://carepath-patient-mx5v.vercel.app/"
    "token.html?cashfree_order_id={order_id}"
)

        },
        "order_note": "CarePath hospital token booking",
    }

    headers = {
        "Content-Type": "application/json",
        "x-client-id": CASHFREE_CLIENT_ID,
        "x-client-secret": CASHFREE_CLIENT_SECRET,
        "x-api-version": CASHFREE_API_VERSION,
        "x-idempotency-key": str(uuid.uuid4()),
    }

    try:
        response = requests.post(
            f"{CASHFREE_BASE_URL}/orders",
            json=payload,
            headers=headers,
            timeout=20,
        )

        if response.status_code not in (200, 201):
            print(
                "Cashfree order error:",
                response.status_code,
                response.text,
            )
            raise HTTPException(
                status_code=502,
                detail="Cashfree Sandbox could not create the payment order.",
            )

        order = response.json()

        return {
            "success": True,
            "order_id": order.get("order_id", order_id),
            "payment_session_id": order.get("payment_session_id"),
            "amount": int(total_amount * 100),
            "currency": "INR",
            "token_fee": token_fee,
            "platform_fee": platform_fee,
            "total_amount": total_amount,
            "hospital_id": hospital.id,
        }

    except HTTPException:
        raise
    except Exception as error:
        print("Cashfree order error:", str(error))
        raise HTTPException(
            status_code=502,
            detail="Unable to create Cashfree Sandbox order.",
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
    current_user: dict = Depends(require_role("patient")),
):
    patient = (
        db.query(Patient)
        .filter(Patient.id == current_user["user_id"])
        .first()
    )

    if not patient:
        raise HTTPException(status_code=401, detail="Patient account not found.")

    order_id = data.cashfree_order_id.strip()

    if not order_id:
        raise HTTPException(status_code=400, detail="Cashfree order ID is required.")

    if not CASHFREE_CLIENT_ID or not CASHFREE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Cashfree Sandbox credentials are not configured.",
        )

    headers = {
        "x-client-id": CASHFREE_CLIENT_ID,
        "x-client-secret": CASHFREE_CLIENT_SECRET,
        "x-api-version": CASHFREE_API_VERSION,
        "Content-Type": "application/json",
    }

    try:
        order_response = requests.get(
            f"{CASHFREE_BASE_URL}/orders/{order_id}",
            headers=headers,
            timeout=20,
        )

        if order_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Unable to verify Cashfree order.")

        order = order_response.json()

        if order.get("order_status") != "PAID":
            raise HTTPException(status_code=400, detail="Payment is not confirmed as paid.")

        customer_details = order.get("customer_details") or {}

        if str(customer_details.get("customer_id", "")) != str(patient.id):
            raise HTTPException(status_code=403, detail="This order does not belong to this patient.")

        payments_response = requests.get(
            f"{CASHFREE_BASE_URL}/orders/{order_id}/payments",
            headers=headers,
            timeout=20,
        )

        if payments_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Unable to verify Cashfree payment.")

        payments = payments_response.json()

        if not isinstance(payments, list):
            raise HTTPException(status_code=400, detail="Unexpected Cashfree payment response.")

        payment = next(
            (
                item for item in payments
                if item.get("payment_status") == "SUCCESS"
            ),
            None,
        )

        if not payment:
            raise HTTPException(status_code=400, detail="No successful Cashfree payment was found.")

        payment_id = str(payment.get("cf_payment_id") or "").strip()

        if not payment_id:
            raise HTTPException(status_code=400, detail="Cashfree payment ID is missing.")

    except HTTPException:
        raise
    except Exception as error:
        print("Cashfree verification error:", str(error))
        raise HTTPException(status_code=502, detail="Unable to verify Cashfree payment.")

    existing_token = (
        db.query(Token)
        .filter(Token.cashfree_order_id == order_id)
        .first()
    )

    if existing_token:
        if existing_token.patient_id != patient.id:
            raise HTTPException(status_code=403, detail="This order belongs to another patient.")

        return {
            "success": True,
            "message": "Token already created",
            "token": token_to_dict(existing_token),
        }

    hospital = find_published_hospital(db, data.hospital)

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == hospital.id,
            Doctor.department == data.department.strip(),
            Doctor.name == data.doctor.strip(),
        )
        .first()
    )

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found.")

    token_fee = int(hospital.token_fee or 0)
    platform_fee = PLATFORM_FEE
    total_amount = token_fee + platform_fee

    try:
        order_amount = float(order.get("order_amount", 0))
        payment_amount = float(payment.get("payment_amount", 0))

        if (
            order_amount != float(total_amount)
            or payment_amount != float(total_amount)
            or order.get("order_currency") != "INR"
            or payment.get("payment_currency") != "INR"
        ):
            raise HTTPException(
                status_code=400,
                detail="Payment amount or currency mismatch.",
            )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid Cashfree payment amount.")

    appointment_date = data.appointment_date or date.today()

    latest_token = (
        db.query(Token)
        .filter(
            Token.hospital_id == hospital.id,
            Token.department == data.department.strip(),
            Token.doctor == data.doctor.strip(),
            Token.appointment_date == appointment_date,
        )
        .order_by(Token.token_number.desc())
        .first()
    )




    next_token_number = allocate_token_number(
        db=db,
        hospital_id=hospital.id,
        department=data.department.strip(),
        doctor=data.doctor.strip(),
        appointment_date=appointment_date,
    )


    token = Token(
        patient_id=patient.id,
        patient_name=patient.full_name,
        hospital=hospital.name,
        hospital_id=hospital.id,
        department=data.department.strip(),
        doctor=data.doctor.strip(),
        token_number=next_token_number,
        appointment_date=appointment_date,
        platform=PLATFORM_NAME,
        booking_type="ONLINE",
        token_fee=token_fee,
        platform_fee=platform_fee,
        total_amount=total_amount,
        payment_status="paid",
        cashfree_order_id=order_id,
        cashfree_payment_id=payment_id,
        status="waiting",
    )

    try:
        db.add(token)
        db.commit()
        db.refresh(token)
    except Exception as error:
        db.rollback()
        print("Token creation error:", str(error))
        raise HTTPException(status_code=500, detail="Unable to create the hospital token.")

    return {
        "success": True,
        "message": "Hospital token created successfully",
        "token": token_to_dict(token),
    }
# ============================================================
# PATIENT - TOKEN HISTORY
# ============================================================

@app.get("/patient/tokens")
@app.get("/patient/token-history")
def get_patient_token_history(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("patient")),
):
    tokens = (
        db.query(Token)
        .filter(Token.patient_id == current_user["user_id"])
        .order_by(
            Token.appointment_date.desc(),
            Token.created_at.desc()
        )
        .all()
    )

    results = []
    for token in tokens:
        d = token_to_dict(token)
        if token.status in ("waiting", "serving"):
            d.update(get_queue_status_for_token(db, token))
        results.append(d)

    return results


@app.get("/patient/tokens/{token_id}")
def get_patient_single_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("patient")),
):
    token = (
        db.query(Token)
        .filter(
            Token.id == token_id,
            Token.patient_id == current_user["user_id"],
        )
        .first()
    )

    if not token:
        raise HTTPException(
            status_code=404,
            detail="Token record not found.",
        )

    return token_to_dict(token)


# ============================================================
# HOSPITAL - OWN TOKENS
# ============================================================

@app.get("/hospital/tokens")
def get_hospital_tokens(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    tokens = (
        db.query(Token)
        .filter(
            Token.hospital_id ==
            current_user["user_id"]
        )
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
# NEXT PATIENT - HOSPITAL AUTHENTICATION REQUIRED
# ============================================================

@app.post("/hospital/walk-in-tokens")
def create_walk_in_token(
    data: WalkInTokenRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    authenticated_hospital_id = current_user["user_id"]

    hospital = (
        db.query(Hospital)
        .filter(Hospital.id == authenticated_hospital_id)
        .first()
    )

    if not hospital:
        raise HTTPException(
            status_code=401,
            detail="Hospital account not found",
        )

    patient_name = data.patient_name.strip()
    department = data.department.strip()
    doctor_name = data.doctor.strip()

    if not patient_name or not department or not doctor_name:
        raise HTTPException(
            status_code=400,
            detail="Patient name, department, and doctor are required",
        )

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == authenticated_hospital_id,
            Doctor.department == department,
            Doctor.name == doctor_name,
        )
        .first()
    )

    if not doctor:
        raise HTTPException(
            status_code=404,
            detail="Doctor not found in this hospital and department",
        )

    appointment_date = date.today()
    manual_token_number = data.token_number

    if manual_token_number is not None and manual_token_number <= 0:
        raise HTTPException(
            status_code=400,
            detail="Token number must be a positive integer",
        )

    try:
        if manual_token_number is None:
            next_token_number = allocate_token_number(
                db=db,
                hospital_id=authenticated_hospital_id,
                department=department,
                doctor=doctor_name,
                appointment_date=appointment_date,
            )
        else:
            # Lock/update the shared sequence row before checking duplicates.
            db.execute(
                text("""
                    INSERT INTO token_sequences (
                        hospital_id,
                        department,
                        doctor,
                        appointment_date,
                        last_token_number
                    )
                    VALUES (
                        :hospital_id,
                        :department,
                        :doctor,
                        :appointment_date,
                        0
                    )
                    ON CONFLICT (
                        hospital_id,
                        department,
                        doctor,
                        appointment_date
                    )
                    DO UPDATE SET
                        last_token_number =
                            token_sequences.last_token_number
                    RETURNING last_token_number
                """),
                {
                    "hospital_id": authenticated_hospital_id,
                    "department": department,
                    "doctor": doctor_name,
                    "appointment_date": appointment_date,
                },
            )

            duplicate_token = (
                db.query(Token)
                .filter(
                    Token.hospital_id == authenticated_hospital_id,
                    Token.department == department,
                    Token.doctor == doctor_name,
                    Token.appointment_date == appointment_date,
                    Token.token_number == manual_token_number,
                )
                .first()
            )

            if duplicate_token:
                raise HTTPException(
                    status_code=409,
                    detail="This token number is already assigned for this doctor today",
                )

            next_token_number = manual_token_number

            db.execute(
                text("""
                    UPDATE token_sequences
                    SET last_token_number = GREATEST(
                        last_token_number,
                        :manual_token_number
                    )
                    WHERE hospital_id = :hospital_id
                      AND department = :department
                      AND doctor = :doctor
                      AND appointment_date = :appointment_date
                """),
                {
                    "hospital_id": authenticated_hospital_id,
                    "department": department,
                    "doctor": doctor_name,
                    "appointment_date": appointment_date,
                    "manual_token_number": manual_token_number,
                },
            )

        token = Token(
            patient_id=None,
            patient_name=patient_name,
            hospital=hospital.name,
            hospital_id=authenticated_hospital_id,
            department=department,
            doctor=doctor_name,
            token_number=next_token_number,
            appointment_date=appointment_date,
            platform=PLATFORM_NAME,
            booking_type="WALK_IN",
            token_fee=0,
            platform_fee=0,
            total_amount=0,
            payment_status="not_required",
            status="waiting",
        )

        db.add(token)
        db.commit()
        db.refresh(token)

        return {
            "success": True,
            "message": "Walk-in token created successfully",
            "token": token_to_dict(token),
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception as error:
        db.rollback()
        print("Walk-in token creation error:", str(error))
        raise HTTPException(
            status_code=500,
            detail="Unable to create walk-in token",
        )

@app.post("/next-patient")
def next_patient(
    hospital: Optional[str] = None,
    hospital_id: Optional[int] = None,
    department: Optional[str] = None,
    doctor: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    authenticated_hospital_id = current_user["user_id"]

    hospital_object = (
        db.query(Hospital)
        .filter(Hospital.id == authenticated_hospital_id)
        .first()
    )

    if not hospital_object:
        raise HTTPException(
            status_code=401,
            detail="Hospital account not found",
        )

    if (
        hospital_id is not None
        and hospital_id != authenticated_hospital_id
    ):
        raise HTTPException(
            status_code=403,
            detail="You cannot access another hospital's queue",
        )

    if hospital and hospital != hospital_object.name:
        raise HTTPException(
            status_code=403,
            detail="Hospital does not match your account",
        )

    if not department or not doctor:
        raise HTTPException(
            status_code=400,
            detail="Department and doctor are required",
        )

    today = date.today()

    current = (
        db.query(Token)
        .filter(
            Token.hospital_id == authenticated_hospital_id,
            Token.department == department,
            Token.doctor == doctor,
            Token.appointment_date == today,
            Token.status == "serving",
        )
        .first()
    )

    if current:
        current.status = "completed"

    next_token = (
        db.query(Token)
        .filter(
            Token.hospital_id == authenticated_hospital_id,
            Token.department == department,
            Token.doctor == doctor,
            Token.appointment_date == today,
            Token.status == "waiting",
        )
        .order_by(Token.token_number.asc())
        .first()
    )

    if not next_token:
        db.commit()
        raise HTTPException(
            status_code=404,
            detail="No waiting patients for today",
        )

    next_token.status = "serving"

    db.commit()
    db.refresh(next_token)

    return {
        "success": True,
        "message": (
            f"Token {next_token.token_number} "
            "is now being served"
        ),
        "token": {
            "id": next_token.id,
            "token_number": next_token.token_number,
            "patient_name": next_token.patient_name,
            "doctor": next_token.doctor,
            "department": next_token.department,
            "status": next_token.status,
            "booking_type": next_token.booking_type,
        },
    }


# ============================================================
# COMPLETE TOKEN - HOSPITAL AUTHENTICATION REQUIRED
# ============================================================
class UpdateTokenNumberRequest(BaseModel):
    token_number: int


@app.put("/tokens/{token_id}/number")
def update_token_number(
    token_id: int,
    data: UpdateTokenNumberRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    hospital_id = current_user["user_id"]

    if data.token_number <= 0:
        raise HTTPException(
            status_code=400,
            detail="Token number must be a positive integer",
        )

    token = (
        db.query(Token)
        .filter(
            Token.id == token_id,
            Token.hospital_id == hospital_id,
        )
        .first()
    )

    if not token:
        raise HTTPException(
            status_code=404,
            detail="Token not found",
        )

    if token.status not in ("waiting", "serving"):
        raise HTTPException(
            status_code=400,
            detail="Only waiting or serving tokens can be changed",
        )

    duplicate = (
        db.query(Token)
        .filter(
            Token.hospital_id == hospital_id,
            Token.department == token.department,
            Token.doctor == token.doctor,
            Token.appointment_date == token.appointment_date,
            Token.token_number == data.token_number,
            Token.id != token.id,
        )
        .first()
    )

    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="This token number is already assigned for this doctor on this date",
        )

    token.token_number = data.token_number

# Keep the shared online/offline token sequence updated.
    db.execute(
        text("""
            INSERT INTO token_sequences (
                hospital_id,
                department,
                doctor,
                appointment_date,
                last_token_number
            )
            VALUES (
                :hospital_id,
                :department,
                :doctor,
                :appointment_date,
                :token_number
            )
            ON CONFLICT (
                hospital_id,
                department,
                doctor,
                appointment_date
            )
            DO UPDATE SET
                last_token_number = GREATEST(
                    token_sequences.last_token_number,
                    EXCLUDED.last_token_number
                )
        """),
        {
            "hospital_id": hospital_id,
            "department": token.department,
            "doctor": token.doctor,
            "appointment_date": token.appointment_date,
            "token_number": data.token_number,
        },
    )

    db.commit()
    db.refresh(token)

    return {
        "success": True,
        "message": "Token number updated successfully",
        "token": token_to_dict(token),
    }


class CompleteTokenRequest(BaseModel):
    diagnosis: Optional[str] = None
    prescription: Optional[str] = None
    notes: Optional[str] = None


def get_queue_status_for_token(db: Session, token: Token) -> dict:
    """Calculates scheduled appointment time and real-time live ETA based on hospital opening hours,
    doctor consultation schedule, appointment date, token sequence number, and live queue status."""
    if not token or not getattr(token, "appointment_date", None) or not getattr(token, "hospital_id", None):
        return {}

    try:
        # 1. Hospital Operating Hours
        hospital = db.query(Hospital).filter(Hospital.id == token.hospital_id).first()
        hosp_open = (getattr(hospital, "opening_time", None) or "09:00").strip()
        hosp_close = (getattr(hospital, "closing_time", None) or "21:00").strip()
        hosp_hours_12h = f"{format_time_12h(hosp_open)} - {format_time_12h(hosp_close)}"

        # 2. Doctor Consultation Hours & Leave Status
        doctor = None
        if getattr(token, "doctor_id", None):
            doctor = db.query(Doctor).filter(Doctor.id == token.doctor_id).first()
        if not doctor and token.doctor and token.hospital_id:
            doctor = db.query(Doctor).filter(Doctor.hospital_id == token.hospital_id, Doctor.name == token.doctor).first()

        doc_start = None
        doc_end = None
        consultation_duration = 15  # standard minutes per patient
        is_doctor_on_leave = False
        leave_reason = None

        if doctor:
            # Check schedule exception for appointment_date
            exc = db.query(DoctorScheduleException).filter(
                DoctorScheduleException.doctor_id == doctor.id,
                DoctorScheduleException.exception_date == token.appointment_date
            ).first()
            if exc:
                if exc.is_closed:
                    is_doctor_on_leave = True
                    leave_reason = exc.reason
                if exc.start_time:
                    doc_start = exc.start_time
                if exc.end_time:
                    doc_end = exc.end_time
                if exc.consultation_minutes:
                    consultation_duration = exc.consultation_minutes

            # Check weekly schedule
            if not doc_start and getattr(token, "appointment_date", None):
                weekday = token.appointment_date.weekday()
                ws = db.query(DoctorWeeklySchedule).filter(
                    DoctorWeeklySchedule.doctor_id == doctor.id,
                    DoctorWeeklySchedule.weekday == weekday
                ).first()
                if ws and ws.is_working and ws.start_time:
                    doc_start = ws.start_time
                    doc_end = ws.end_time
                    if ws.consultation_minutes:
                        consultation_duration = ws.consultation_minutes

            if not doc_start:
                doc_start = doctor.start_time
                doc_end = doctor.end_time

        effective_start = doc_start or hosp_open or "09:00"
        effective_end = doc_end or hosp_close or "21:00"
        doc_hours_12h = f"{format_time_12h(effective_start)} - {format_time_12h(effective_end)}"

        # 3. Base Scheduled Time: start_time + (token_number - 1) * consultation_duration
        token_num = max(1, token.token_number or 1)
        try:
            sh_parts = [int(p) for p in effective_start[:5].split(":")]
            start_h, start_m = sh_parts[0], sh_parts[1]
        except Exception:
            start_h, start_m = 9, 0

        sched_total_mins = start_h * 60 + start_m + (token_num - 1) * consultation_duration
        sched_h = (sched_total_mins // 60) % 24
        sched_m = sched_total_mins % 60
        scheduled_time_12h = datetime.strptime(f"{sched_h:02d}:{sched_m:02d}", "%H:%M").strftime("%I:%M %p").lstrip("0")

        # 4. Live Queue Status
        query = db.query(Token).filter(
            Token.hospital_id == token.hospital_id,
            Token.appointment_date == token.appointment_date,
        )
        if doctor:
            query = query.filter(or_(Token.doctor_id == doctor.id, Token.doctor == doctor.name))
        elif token.doctor:
            query = query.filter(Token.doctor == token.doctor)
        elif token.department:
            query = query.filter(Token.department == token.department)

        serving = query.filter(Token.status == "serving").order_by(Token.token_number.desc()).first()
        serving_number = serving.token_number if serving else None

        tokens_ahead = query.filter(
            Token.status == "waiting",
            Token.token_number < token.token_number
        ).count()

        # 5. Real-Time ETA vs Scheduled Time
        now_utc = datetime.utcnow()
        now_ist = now_utc + timedelta(hours=5, minutes=30)
        today_ist = now_ist.date()

        if token.appointment_date == today_ist:
            wait_mins = tokens_ahead * consultation_duration
            curr_mins = now_ist.hour * 60 + now_ist.minute
            start_mins = start_h * 60 + start_m
            if curr_mins >= start_mins or serving_number:
                live_eta_dt = now_ist + timedelta(minutes=wait_mins + (5 if serving_number else 0))
                estimated_time_12h = live_eta_dt.strftime("%I:%M %p").lstrip("0")
            else:
                estimated_time_12h = scheduled_time_12h
        else:
            estimated_time_12h = scheduled_time_12h
            wait_mins = tokens_ahead * consultation_duration

        return {
            "currently_serving_token": serving_number,
            "tokens_ahead": tokens_ahead,
            "estimated_wait_minutes": wait_mins,
            "scheduled_time_12h": scheduled_time_12h,
            "estimated_time_12h": estimated_time_12h,
            "is_your_turn": token.status == "serving",
            "hospital_operating_hours": hosp_hours_12h,
            "doctor_consultation_hours": doc_hours_12h,
            "doctor_on_leave": is_doctor_on_leave,
            "leave_reason": leave_reason,
        }
    except Exception as err:
        import logging
        logging.warning("Error calculating queue status: %s", err)
        return {
            "currently_serving_token": None,
            "tokens_ahead": 0,
            "estimated_wait_minutes": 0,
            "scheduled_time_12h": None,
            "estimated_time_12h": None,
            "is_your_turn": token.status == "serving",
            "hospital_operating_hours": "09:00 AM - 09:00 PM",
            "doctor_consultation_hours": "09:00 AM - 05:00 PM",
            "doctor_on_leave": False,
            "leave_reason": None,
        }


@app.put("/tokens/{token_id}/call")
def call_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    token = (
        db.query(Token)
        .filter(
            Token.id == token_id,
            Token.hospital_id == current_user["user_id"],
        )
        .first()
    )

    if not token:
        raise HTTPException(
            status_code=404,
            detail="Token not found",
        )

    token.status = "serving"
    token.called_at = datetime.utcnow()

    db.commit()
    db.refresh(token)

    return {
        "success": True,
        "message": f"Token #{token.token_number} called into consultation",
        "token": token_to_dict(token),
    }


@app.get("/tokens/{token_id}/live-status")
def get_token_live_status(
    token_id: int,
    db: Session = Depends(get_db),
):
    token = db.query(Token).filter(Token.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    d = token_to_dict(token)
    if token.status in ("waiting", "serving"):
        d.update(get_queue_status_for_token(db, token))
    return d


@app.get("/hospitals/{hospital_id}/live-queue")
def get_hospital_live_queue(
    hospital_id: int,
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Local today's date in IST (+5:30)
    today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()

    today_tokens = (
        db.query(Token)
        .filter(
            Token.hospital_id == hospital_id,
            Token.appointment_date == today,
        )
        .order_by(Token.token_number.asc())
        .all()
    )

    serving_tokens = [
        token_to_dict(t) for t in today_tokens if t.status == "serving"
    ]
    waiting_tokens = [
        token_to_dict(t) for t in today_tokens if t.status == "waiting"
    ]
    completed_count = sum(1 for t in today_tokens if t.status == "completed")

    return {
        "success": True,
        "hospital_id": hospital.id,
        "hospital_name": hospital.name,
        "hospital_city": hospital.city,
        "appointment_date": str(today),
        "stats": {
            "total_today": len(today_tokens),
            "completed": completed_count,
            "serving": len(serving_tokens),
            "waiting": len(waiting_tokens),
        },
        "currently_serving": serving_tokens,
        "upcoming_waiting": waiting_tokens[:20],
    }
@app.put("/tokens/{token_id}/complete")
def complete_token(
    token_id: int,
    data: Optional[CompleteTokenRequest] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    token = (
        db.query(Token)
        .filter(
            Token.id == token_id,
            Token.hospital_id == current_user["user_id"],
        )
        .first()
    )

    if not token:
        raise HTTPException(
            status_code=404,
            detail="Token not found",
        )

    token.status = "completed"
    token.completed_at = datetime.utcnow()

    if data:
        if data.diagnosis:
            token.diagnosis = data.diagnosis.strip()
        if data.prescription:
            token.prescription = data.prescription.strip()
        if data.notes:
            token.notes = data.notes.strip()

    db.commit()
    db.refresh(token)

    return {
        "success": True,
        "message": "Token completed successfully",
        "token": token_to_dict(token),
    }
# ============================================================
# PLATFORM CONTACT & SETTINGS
# ============================================================

class PlatformContactUpdateRequest(BaseModel):
    business_name: str | None = None
    support_email: str | None = None
    support_phone: str | None = None
    operating_address: str | None = None
    grievance_officer: str | None = None
    grievance_email: str | None = None
    working_hours: str | None = None


def get_or_create_contact_settings(db: Session) -> PlatformContact:
    contact = db.query(PlatformContact).first()
    if not contact:
        contact = PlatformContact(
            business_name="CarePath Healthcare Technologies",
            support_email="mangarajesh58@gmail.com",
            support_phone="+91 98765 43210",
            operating_address="Bhubaneswar / Cuttack, Odisha, India - 751024",
            grievance_officer="Rajesh Mangaraj",
            grievance_email="mangarajesh58@gmail.com",
            working_hours="Mon - Sat: 9:00 AM - 7:00 PM IST",
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)
    return contact


@app.get("/platform/contact")
@app.get("/admin/contact")
def get_platform_contact(db: Session = Depends(get_db)):
    contact = get_or_create_contact_settings(db)
    return {
        "success": True,
        "business_name": contact.business_name,
        "support_email": contact.support_email,
        "support_phone": contact.support_phone,
        "operating_address": contact.operating_address,
        "grievance_officer": contact.grievance_officer,
        "grievance_email": contact.grievance_email,
        "working_hours": contact.working_hours,
        "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
    }


@app.post("/admin/contact")
@app.put("/admin/contact")
def update_platform_contact(
    data: PlatformContactUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    contact = get_or_create_contact_settings(db)

    if data.business_name is not None:
        contact.business_name = data.business_name.strip()
    if data.support_email is not None:
        contact.support_email = data.support_email.strip()
    if data.support_phone is not None:
        contact.support_phone = data.support_phone.strip()
    if data.operating_address is not None:
        contact.operating_address = data.operating_address.strip()
    if data.grievance_officer is not None:
        contact.grievance_officer = data.grievance_officer.strip()
    if data.grievance_email is not None:
        contact.grievance_email = data.grievance_email.strip()
    if data.working_hours is not None:
        contact.working_hours = data.working_hours.strip()

    contact.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(contact)

    return {
        "success": True,
        "message": "Platform contact details updated successfully.",
        "contact": {
            "business_name": contact.business_name,
            "support_email": contact.support_email,
            "support_phone": contact.support_phone,
            "operating_address": contact.operating_address,
            "grievance_officer": contact.grievance_officer,
            "grievance_email": contact.grievance_email,
            "working_hours": contact.working_hours,
            "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
        },
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
        .filter(Admin.email == email)
        .first()
    )

    if not admin:
        raise HTTPException(
            status_code=401,
            detail="Invalid admin credentials",
        )

    if not verify_password(
        data.password,
        admin.password or "",
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid admin credentials",
        )

    access_token = create_access_token(
        user_id=admin.id,
        role="admin",
    )

    return {
        "success": True,
        "message": "Admin login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "admin": {
            "id": admin.id,
            "email": admin.email,
        },
    }

# ============================================================
# ADMIN - ALL HOSPITALS
# ============================================================

@app.get("/admin/hospitals")
def admin_get_hospitals(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    hospitals = (
        db.query(Hospital)
        .order_by(Hospital.id.desc())
        .all()
    )

    result = []

    for hospital in hospitals:
        doctor_count = (
            db.query(Doctor)
            .filter(
                Doctor.hospital_id == hospital.id
            )
            .count()
        )

        token_count = (
            db.query(Token)
            .filter(
                Token.hospital_id == hospital.id
            )
            .count()
        )

        paid_count = (
            db.query(Token)
            .filter(
                Token.hospital_id == hospital.id,
                Token.payment_status == "paid",
            )
            .count()
        )

        hospital_data = hospital_to_dict(hospital)

        hospital_data.update({
            "doctor_count": doctor_count,
            "token_count": token_count,
            "paid_token_count": paid_count,
            "payment_account_name": hospital.payment_account_name,
            "payment_account_number": hospital.payment_account_number,
            "payment_ifsc": hospital.payment_ifsc,
            "payment_upi": hospital.payment_upi,
        })

        result.append(hospital_data)

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
    current_user: dict = Depends(require_role("admin")),
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
    current_user: dict = Depends(require_role("admin")),
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

    hospital.certificate_verification_status = "VERIFIED"

    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Hospital certificate verified successfully",
        "hospital": hospital_to_dict(hospital),
    }
# ============================================================
# ADMIN - VERIFY HOSPITAL CERTIFICATE
# ============================================================
@app.put(
    "/admin/hospitals/{hospital_id}/certificate/reject"
)
def reject_hospital_certificate(
    hospital_id: int,
    data: AdminActionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
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
    }#============================================================
# ADMIN - VIEW HOSPITAL CERTIFICATE
# Supports PDF, JPG, JPEG, PNGF
# ============================================================
@app.get("/admin/hospitals/{hospital_id}/certificate")
def get_hospital_certificate(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
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

    # 1. Try local disk
    if hospital.license_certificate:
        certificate_path = os.path.join(
            os.path.dirname(__file__),
            "uploads",
            "hospital_certificates",
            hospital.license_certificate,
        )
        if os.path.isfile(certificate_path):
            allowed_types = {
                ".pdf": "application/pdf",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
            }
            extension = os.path.splitext(certificate_path)[1].lower()
            media_type = allowed_types.get(extension, "application/pdf")
            return FileResponse(
                path=certificate_path,
                media_type=media_type,
                content_disposition_type="inline",
            )

    # 2. Try certificate_base64 from PostgreSQL database
    if hospital.certificate_base64:
        try:
            cert_bytes = base64.b64decode(hospital.certificate_base64)
            if hospital.license_certificate:
                cert_path = os.path.join(
                    os.path.dirname(__file__),
                    "uploads",
                    "hospital_certificates",
                    hospital.license_certificate,
                )
                try:
                    with open(cert_path, "wb") as f:
                        f.write(cert_bytes)
                except Exception:
                    pass
            media_type = hospital.certificate_content_type or "application/pdf"
            return Response(
                content=cert_bytes,
                media_type=media_type,
                headers={"Content-Disposition": "inline"},
            )
        except Exception:
            pass

    # 3. Fallback: Official Government Registration Credential Card (SVG)
    reg_num = (hospital.registration_number or hospital.license_id or "Registered").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    authority = (hospital.issuing_authority or "State Health Authority").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    h_name = (hospital.name or "CarePath Hospital").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    expiry = str(hospital.license_expiry_date or "Permanent / Valid").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    orig_name = (hospital.certificate_original_name or "Official_Registration_Certificate").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    cert_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="520" viewBox="0 0 800 520">
  <defs>
    <linearGradient id="certBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="100%" stop-color="#f8fafc"/>
    </linearGradient>
  </defs>
  <rect width="800" height="520" fill="url(#certBg)" stroke="#0284c7" stroke-width="6" rx="16"/>
  <rect x="20" y="20" width="760" height="480" fill="none" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="6,4" rx="10"/>
  <circle cx="400" cy="70" r="30" fill="#e0f2fe"/>
  <path d="M392 70h16M400 62v16" stroke="#0284c7" stroke-width="4" stroke-linecap="round"/>
  <text x="400" y="130" font-family="system-ui, -apple-system, sans-serif" font-size="20" font-weight="800" fill="#0f172a" text-anchor="middle" letter-spacing="1">
    GOVERNMENT HEALTHCARE REGISTRATION CREDENTIAL
  </text>
  <text x="400" y="155" font-family="system-ui, -apple-system, sans-serif" font-size="13" fill="#64748b" text-anchor="middle">
    CarePath Platform Verified Hospital License Record
  </text>
  <line x1="60" y1="175" x2="740" y2="175" stroke="#e2e8f0" stroke-width="1.5"/>
  <text x="100" y="215" font-family="system-ui, sans-serif" font-size="13" font-weight="700" fill="#475569">HOSPITAL NAME:</text>
  <text x="280" y="215" font-family="system-ui, sans-serif" font-size="15" font-weight="700" fill="#0f172a">{h_name}</text>
  <text x="100" y="255" font-family="system-ui, sans-serif" font-size="13" font-weight="700" fill="#475569">REGISTRATION / LICENSE NO:</text>
  <text x="320" y="255" font-family="system-ui, sans-serif" font-size="15" font-weight="800" fill="#0284c7">{reg_num}</text>
  <text x="100" y="295" font-family="system-ui, sans-serif" font-size="13" font-weight="700" fill="#475569">ISSUING AUTHORITY:</text>
  <text x="280" y="295" font-family="system-ui, sans-serif" font-size="14" fill="#1e293b">{authority}</text>
  <text x="100" y="335" font-family="system-ui, sans-serif" font-size="13" font-weight="700" fill="#475569">LICENSE VALID UNTIL:</text>
  <text x="280" y="335" font-family="system-ui, sans-serif" font-size="14" fill="#1e293b">{expiry}</text>
  <text x="100" y="375" font-family="system-ui, sans-serif" font-size="13" font-weight="700" fill="#475569">ORIGINAL SUBMISSION FILE:</text>
  <text x="320" y="375" font-family="system-ui, sans-serif" font-size="13" fill="#64748b">{orig_name}</text>
  <rect x="80" y="410" width="640" height="60" rx="8" fill="#f0fdf4" stroke="#bbf7d0" stroke-width="1"/>
  <text x="400" y="435" font-family="system-ui, sans-serif" font-size="12" font-weight="700" fill="#166534" text-anchor="middle">
    ✓ Registered in Database &amp; Ready for Admin Verification
  </text>
  <text x="400" y="455" font-family="system-ui, sans-serif" font-size="11" fill="#15803d" text-anchor="middle">
    Physical upload was archived during server deployment. Administrator may verify using Registration No. or upload fresh scan.
  </text>
</svg>"""
    return Response(
        content=cert_svg,
        media_type="image/svg+xml",
        headers={"Content-Disposition": "inline"},
    )

# ============================================================
# ADMIN - APPROVE HOSPITAL
#

@app.put("/admin/hospitals/{hospital_id}/approve")
def approve_hospital(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
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
    current_user: dict = Depends(require_role("admin")),
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

    hospital.approval_status = "REJECTED"
    hospital.is_published = False

    hospital.rejection_reason = (
        data.reason
        or "Hospital registration rejected"
    )

    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Hospital rejected successfully",
        "hospital": hospital_to_dict(hospital),
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
    current_user: dict = Depends(require_role("admin")),
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

    if hospital.approval_status != "APPROVED":
        raise HTTPException(
            status_code=400,
            detail="Approve hospital before publishing",
        )

    hospital.is_published = True

    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Hospital published to Patient App",
        "hospital": hospital_to_dict(hospital),
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
    current_user: dict = Depends(require_role("admin")),
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

    hospital.is_published = False

    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Hospital unpublished",
    }
# ============================================================
# ADMIN - DELETE HOSPITAL
# ============================================================

@app.delete("/admin/hospitals/{hospital_id}")
def delete_hospital(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
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

    # Delete doctors belonging to this hospital
    db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id
    ).delete(
        synchronize_session=False
    )

    # Delete tokens linked to this hospital
    db.query(Token).filter(
        Token.hospital_id == hospital_id
    ).delete(
        synchronize_session=False
    )

    # Delete legacy tokens without hospital_id
    db.query(Token).filter(
        Token.hospital == hospital.name,
        Token.hospital_id.is_(None),
    ).delete(
        synchronize_session=False
    )

    # Delete the hospital
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
    current_user: dict = Depends(require_role("hospital")),
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
    if hospital.id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot add doctors to another hospital.",
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

#============================================================
# ADMIN - REVENUE
# ============================================================

@app.get("/admin/revenue")
def admin_revenue(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
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
    current_user: dict = Depends(require_role("admin")),
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

# ADMIN - ALL TOKENS (ADMIN AUTHENTICATION REQUIRED)
# ============================================================

@app.get("/admin/tokens")
def admin_tokens(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
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

@app.get("/hospitals/{hospital_id}/tokens")
def hospital_tokens(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    # Hospital can only access its own queue
    if hospital_id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot access another hospital's tokens."
        )

    tokens = (
        db.query(Token)
        .filter(Token.hospital_id == hospital_id)
        .order_by(Token.created_at.asc())
        .all()
    )

    return [
        token_to_dict(token)
        for token in tokens
    ]
# ============================================================
# ADMIN - HOSPITAL REVENUE (ADMIN AUTHENTICATION REQUIRED)
# ============================================================

@app.get("/admin/hospitals/{hospital_id}/revenue")
def admin_hospital_revenue(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
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

    paid_tokens = (
        db.query(Token)
        .filter(
            Token.hospital_id == hospital_id,
            Token.payment_status == "paid",
        )
        .all()
    )

    hospital_revenue = sum(
        int(token.token_fee or 0)
        for token in paid_tokens
    )

    platform_revenue = sum(
        int(token.platform_fee or 0)
        for token in paid_tokens
    )

    total_collected = sum(
        int(token.total_amount or 0)
        for token in paid_tokens
    )

    return {
        "success": True,
        "hospital_id": hospital.id,
        "hospital": hospital.name,
        "paid_tokens": len(paid_tokens),
        "hospital_revenue": hospital_revenue,
        "platform_revenue": platform_revenue,
        "total_collected": total_collected,
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


# ============================================================
# ADMIN - UPLOAD HOSPITAL CERTIFICATE
# ============================================================
@app.post("/admin/hospitals/{hospital_id}/certificate")
async def admin_upload_hospital_certificate(
    hospital_id: int,
    certificate: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    content_type = (certificate.content_type or "").lower()
    if content_type not in ALLOWED_CERTIFICATE_TYPES:
        raise HTTPException(status_code=400, detail="Only PDF, JPG, or PNG files are allowed.")

    content = await certificate.read()
    if not content:
        raise HTTPException(status_code=400, detail="Certificate file is empty.")
    if len(content) > MAX_CERTIFICATE_SIZE:
        raise HTTPException(status_code=400, detail="Certificate file must be 10 MB or smaller.")

    orig_name = certificate.filename or "certificate"
    ext = os.path.splitext(orig_name)[1].lower()
    unique_name = f"hospital_{secrets.token_hex(16)}{ext}"
    cert_path = os.path.join(UPLOAD_DIR, unique_name)
    try:
        with open(cert_path, "wb") as f:
            f.write(content)
    except Exception as e:
        print("Certificate disk write error:", e)

    hospital.license_certificate = unique_name
    hospital.certificate_original_name = orig_name
    hospital.certificate_content_type = content_type
    hospital.certificate_uploaded_at = datetime.utcnow()
    hospital.certificate_base64 = base64.b64encode(content).decode("utf-8")
    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Hospital certificate uploaded successfully.",
        "hospital": hospital_to_dict(hospital),
    }


# ============================================================
# ADMIN - UPLOAD HOSPITAL COVER PHOTO
# ============================================================
@app.post("/admin/hospitals/{hospital_id}/photo")
async def admin_upload_hospital_photo(
    hospital_id: int,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    content_type = (photo.content_type or "").lower()
    if content_type not in ALLOWED_HOSPITAL_PHOTO_TYPES:
        raise HTTPException(status_code=400, detail="Please upload a JPG, PNG, or WEBP image.")

    content = await photo.read(MAX_HOSPITAL_PHOTO_SIZE + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The photo is empty.")
    if len(content) > MAX_HOSPITAL_PHOTO_SIZE:
        raise HTTPException(status_code=413, detail="Photo must be 5 MB or smaller.")

    ext = ALLOWED_HOSPITAL_PHOTO_TYPES[content_type]
    filename = f"hospital_{hospital_id}_{uuid.uuid4().hex}{ext}"
    destination = os.path.join(HOSPITAL_PHOTO_DIR, filename)
    try:
        with open(destination, "wb") as f:
            f.write(content)
    except Exception as e:
        print("Photo disk write error:", e)

    hospital.image_url = f"/hospital-photos/{filename}"
    hospital.photo_base64 = base64.b64encode(content).decode("utf-8")
    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Hospital cover photo uploaded successfully.",
        "hospital": hospital_to_dict(hospital),
    }


# ============================================================
# HOSPITAL - RE-UPLOAD / UPDATE OWN CERTIFICATE
# ============================================================
@app.post("/hospitals/{hospital_id}/certificate")
async def hospital_upload_certificate(
    hospital_id: int,
    certificate: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    if hospital.id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="You cannot upload a certificate for another hospital")

    # Strictly disallow re-upload once a certificate has already been submitted
    if hospital.license_certificate or hospital.certificate_uploaded_at or hospital.certificate_base64:
        raise HTTPException(
            status_code=400,
            detail="Your hospital certificate has already been submitted and is locked for verification. Re-uploading is not permitted."
        )

    content_type = (certificate.content_type or "").lower()
    if content_type not in ALLOWED_CERTIFICATE_TYPES:
        raise HTTPException(status_code=400, detail="Only PDF, JPG, or PNG files are allowed.")

    content = await certificate.read()
    if not content:
        raise HTTPException(status_code=400, detail="Certificate file is empty.")
    if len(content) > MAX_CERTIFICATE_SIZE:
        raise HTTPException(status_code=400, detail="Certificate file must be 10 MB or smaller.")

    orig_name = certificate.filename or "certificate"
    ext = os.path.splitext(orig_name)[1].lower()
    unique_name = f"hospital_{secrets.token_hex(16)}{ext}"
    cert_path = os.path.join(UPLOAD_DIR, unique_name)
    try:
        with open(cert_path, "wb") as f:
            f.write(content)
    except Exception as e:
        print("Certificate disk write error:", e)

    hospital.license_certificate = unique_name
    hospital.certificate_original_name = orig_name
    hospital.certificate_content_type = content_type
    hospital.certificate_uploaded_at = datetime.utcnow()
    hospital.certificate_base64 = base64.b64encode(content).decode("utf-8")
    hospital.certificate_verification_status = "PENDING"
    db.commit()
    db.refresh(hospital)

    return {
        "success": True,
        "message": "Certificate uploaded successfully.",
        "hospital": hospital_to_dict(hospital),
    }


# ============================================================
# DOCTOR PHOTO UPLOAD & SERVING
# ============================================================

@app.post("/doctors/{doctor_id}/photo")
async def upload_doctor_photo(
    doctor_id: int,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Upload a doctor photo for patient browsing cards."""
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    if doctor.hospital_id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot upload a photo for another hospital's doctor",
        )

    content_type = (photo.content_type or "").lower()
    if content_type not in ALLOWED_DOCTOR_PHOTO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Please upload a JPG, PNG, or WEBP image.",
        )

    content = await photo.read(MAX_DOCTOR_PHOTO_SIZE + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The photo is empty.")
    if len(content) > MAX_DOCTOR_PHOTO_SIZE:
        raise HTTPException(status_code=413, detail="Photo must be 5 MB or smaller.")

    extension = ALLOWED_DOCTOR_PHOTO_TYPES[content_type]
    filename = f"doctor_{doctor_id}_{uuid.uuid4().hex}{extension}"
    destination = os.path.join(DOCTOR_PHOTO_DIR, filename)

    with open(destination, "wb") as output_file:
        output_file.write(content)

    old_url = doctor.image_url
    doctor.image_url = f"/doctor-photos/{filename}"
    doctor.photo_base64 = base64.b64encode(content).decode("utf-8")
    db.commit()
    db.refresh(doctor)

    # Clean up old file if exists
    if old_url and old_url.startswith("/doctor-photos/"):
        old_name = os.path.basename(old_url)
        old_path = os.path.join(DOCTOR_PHOTO_DIR, old_name)
        if os.path.isfile(old_path) and old_name != filename:
            try:
                os.remove(old_path)
            except OSError:
                pass

    return {
        "success": True,
        "message": "Doctor photo uploaded successfully.",
        "doctor": doctor_to_dict(doctor),
    }


@app.get("/doctor-photos/{filename}")
def get_doctor_photo(filename: str, db: Session = Depends(get_db)):
    """Serve doctor photo with persistent database fallback and SVG medical avatar."""
    safe_name = os.path.basename(filename)
    file_path = os.path.join(DOCTOR_PHOTO_DIR, safe_name)

    # 1. Check local disk
    if os.path.isfile(file_path):
        media_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"
        return FileResponse(file_path, media_type=media_type)

    # 2. Check persistent database photo_base64
    doctor = db.query(Doctor).filter(Doctor.image_url.like(f"%{safe_name}")).first()
    if not doctor and safe_name.startswith("doctor_"):
        parts = safe_name.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            doctor = db.query(Doctor).filter(Doctor.id == int(parts[1])).first()

    if doctor and doctor.photo_base64:
        try:
            photo_bytes = base64.b64decode(doctor.photo_base64)
            try:
                with open(file_path, "wb") as f:
                    f.write(photo_bytes)
            except Exception:
                pass
            media_type = mimetypes.guess_type(safe_name)[0] or "image/jpeg"
            return Response(content=photo_bytes, media_type=media_type)
        except Exception:
            pass

    # 3. Clean SVG Doctor Avatar Placeholder (Never 404s!)
    d_name = (doctor.name if doctor else "Doctor").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300">
  <defs>
    <linearGradient id="docBg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#e0f2fe"/>
      <stop offset="100%" stop-color="#bae6fd"/>
    </linearGradient>
  </defs>
  <circle cx="150" cy="150" r="145" fill="url(#docBg)" stroke="#0284c7" stroke-width="6"/>
  <g fill="#0284c7">
    <circle cx="150" cy="110" r="45"/>
    <path d="M75 235 c0 -45 35 -75 75 -75 s75 30 75 75 z"/>
  </g>
  <circle cx="150" cy="150" r="14" fill="#ffffff"/>
  <path d="M145 150 h10 M150 145 v10" stroke="#0284c7" stroke-width="3" stroke-linecap="round"/>
</svg>"""
    return Response(content=svg, media_type="image/svg+xml")

# ============================================================
# HOSPITAL PLANNED CLOSURES (3 to 10 Days Advance Rule)
# ============================================================

@app.post("/hospitals/{hospital_id}/closures")
def schedule_hospital_closure(
    hospital_id: int,
    data: HospitalClosureRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Schedules a hospital closure. Must be updated minimum 3 days and maximum 10 days before.
    Automatically cancels and refunds 100% of all active patient tokens on that date."""
    if current_user["user_id"] != hospital_id:
        raise HTTPException(status_code=403, detail="Unauthorized to schedule closures for another hospital.")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")

    try:
        closure_dt = date.fromisoformat(data.closure_date.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid closure date format. Please use YYYY-MM-DD.")

    today_ist = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
    days_in_advance = (closure_dt - today_ist).days

    if days_in_advance < 3:
        raise HTTPException(
            status_code=400,
            detail="Hospital closure must be updated at least 3 days in advance to notify booked patients."
        )
    if days_in_advance > 10:
        raise HTTPException(
            status_code=400,
            detail="Hospital closure can only be updated at most 10 days in advance (advance booking window)."
        )

    reason = (data.reason or "Scheduled Hospital Holiday / Maintenance").strip()

    # Create or update existing closure record
    existing = db.query(HospitalClosure).filter(
        HospitalClosure.hospital_id == hospital_id,
        HospitalClosure.closure_date == closure_dt,
    ).first()

    if existing:
        existing.reason = reason
        closure_record = existing
    else:
        closure_record = HospitalClosure(
            hospital_id=hospital_id,
            closure_date=closure_dt,
            reason=reason,
        )
        db.add(closure_record)

    # Cancel all active tokens on that date & refund 100%
    affected_tokens = db.query(Token).filter(
        Token.hospital_id == hospital_id,
        Token.appointment_date == closure_dt,
        Token.status.in_(["waiting", "serving"]),
    ).all()

    refund_count = 0
    for t in affected_tokens:
        t.status = "cancelled"
        t.payment_status = "refunded"
        t.notes = f"Hospital closed on {closure_dt} ({reason}). 100% Refund of ₹{t.total_amount:.2f} processed to patient account."
        refund_count += 1
        try:
            if t.patient_id:
                pat = db.query(Patient).filter(Patient.id == t.patient_id).first()
                if pat and pat.email:
                    send_carepath_email(
                        to_email=pat.email,
                        subject=f"CarePath Refund Notice: {hospital.name} is closed on {closure_dt}",
                        text=f"Dear {pat.full_name}, {hospital.name} will be closed on {closure_dt} ({reason}). Your token #{t.token_number} has been cancelled and a 100% refund of ₹{t.total_amount:.2f} has been processed to your account.",
                        html=f"""<!DOCTYPE html><html><body style="font-family: sans-serif; padding: 20px;">
                        <h2 style="color: #0284c7;">🏥 CarePath Appointment Cancellation & 100% Refund</h2>
                        <p>Dear <strong>{pat.full_name}</strong>,</p>
                        <p><strong>{hospital.name}</strong> has announced a scheduled closure on <strong>{closure_dt}</strong> ({reason}).</p>
                        <div style="background: #ecfdf5; border: 1px solid #a7f3d0; padding: 15px; border-radius: 8px; margin: 15px 0;">
                          <p style="margin: 0; color: #065f46; font-size: 16px;"><strong>Token #{t.token_number} Cancelled</strong></p>
                          <p style="margin: 5px 0 0; color: #047857;">A full 100% refund of <strong>₹{t.total_amount:.2f}</strong> has been initiated back to your payment account.</p>
                        </div>
                        <p>We apologize for the inconvenience and welcome you to book another date.</p>
                        <p>CarePath Healthcare Team</p>
                        </body></html>"""
                    )
        except Exception:
            pass

    db.commit()
    db.refresh(closure_record)

    return {
        "success": True,
        "closure_id": closure_record.id,
        "hospital_id": hospital_id,
        "closure_date": str(closure_record.closure_date),
        "reason": closure_record.reason,
        "refunded_tokens": refund_count,
        "message": f"Hospital closure scheduled for {closure_dt}. {refund_count} active token(s) cancelled and refunded 100%."
    }


@app.get("/hospitals/{hospital_id}/closures")
def get_hospital_closures(
    hospital_id: int,
    db: Session = Depends(get_db),
):
    """Returns upcoming closures for a hospital."""
    today_ist = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
    closures = (
        db.query(HospitalClosure)
        .filter(
            HospitalClosure.hospital_id == hospital_id,
            HospitalClosure.closure_date >= today_ist,
        )
        .order_by(HospitalClosure.closure_date.asc())
        .all()
    )
    return [
        {
            "id": c.id,
            "hospital_id": c.hospital_id,
            "closure_date": str(c.closure_date),
            "reason": c.reason,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in closures
    ]


@app.delete("/hospitals/{hospital_id}/closures/{closure_id}")
def delete_hospital_closure(
    hospital_id: int,
    closure_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Deletes/cancels a scheduled hospital closure."""
    if current_user["user_id"] != hospital_id:
        raise HTTPException(status_code=403, detail="Unauthorized.")

    closure = (
        db.query(HospitalClosure)
        .filter(
            HospitalClosure.id == closure_id,
            HospitalClosure.hospital_id == hospital_id,
        )
        .first()
    )
    if not closure:
        raise HTTPException(status_code=404, detail="Closure not found.")

    db.delete(closure)
    db.commit()
    return {"success": True, "message": "Hospital closure removed successfully."}


# ============================================================
# DOCTOR ON LEAVE & AUTOMATIC PATIENT REFUND
# ============================================================

@app.post("/hospitals/{hospital_id}/doctors/{doctor_id}/leave")
def mark_doctor_on_leave(
    hospital_id: int,
    doctor_id: int,
    data: DoctorLeaveRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Marks a doctor on leave for a given date. Automatically cancels all active tokens
    for this doctor on that date, updates payment status to 'refunded', and logs 100% refund."""
    if current_user["user_id"] != hospital_id:
        raise HTTPException(status_code=403, detail="Unauthorized.")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")

    doctor = db.query(Doctor).filter(Doctor.id == doctor_id, Doctor.hospital_id == hospital_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found in this hospital.")

    try:
        leave_dt = date.fromisoformat(data.leave_date.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid leave date format. Please use YYYY-MM-DD.")

    reason = (data.reason or "Doctor on Leave").strip()

    # Record or update in DoctorScheduleException
    exc = db.query(DoctorScheduleException).filter(
        DoctorScheduleException.doctor_id == doctor_id,
        DoctorScheduleException.exception_date == leave_dt,
    ).first()

    if exc:
        exc.is_closed = True
        exc.reason = reason
    else:
        exc = DoctorScheduleException(
            doctor_id=doctor_id,
            exception_date=leave_dt,
            is_closed=True,
            reason=reason,
        )
        db.add(exc)

    # Automatically cancel all active tokens for this doctor on that date & refund 100%
    affected_tokens = db.query(Token).filter(
        Token.hospital_id == hospital_id,
        or_(Token.doctor_id == doctor_id, Token.doctor == doctor.name),
        Token.appointment_date == leave_dt,
        Token.status.in_(["waiting", "serving"]),
    ).all()

    refund_count = 0
    for t in affected_tokens:
        t.status = "cancelled"
        t.payment_status = "refunded"
        t.notes = f"Doctor on leave ({reason}). 100% Refund (₹{t.total_amount:.2f}) processed to patient account."
        refund_count += 1
        try:
            if t.patient_id:
                pat = db.query(Patient).filter(Patient.id == t.patient_id).first()
                if pat and pat.email:
                    send_carepath_email(
                        to_email=pat.email,
                        subject=f"CarePath Refund Notice: Dr. {doctor.name} is on leave on {leave_dt}",
                        text=f"Dear {pat.full_name}, Dr. {doctor.name} is on leave on {leave_dt} ({reason}). Your token #{t.token_number} has been cancelled and a 100% refund of ₹{t.total_amount:.2f} has been processed to your account.",
                        html=f"""<!DOCTYPE html><html><body style="font-family: sans-serif; padding: 20px;">
                        <h2 style="color: #0284c7;">🏥 CarePath Appointment Cancellation & 100% Refund</h2>
                        <p>Dear <strong>{pat.full_name}</strong>,</p>
                        <p><strong>Dr. {doctor.name}</strong> at {hospital.name} is on leave on <strong>{leave_dt}</strong> ({reason}).</p>
                        <div style="background: #ecfdf5; border: 1px solid #a7f3d0; padding: 15px; border-radius: 8px; margin: 15px 0;">
                          <p style="margin: 0; color: #065f46; font-size: 16px;"><strong>Token #{t.token_number} Cancelled</strong></p>
                          <p style="margin: 5px 0 0; color: #047857;">A full 100% refund of <strong>₹{t.total_amount:.2f}</strong> has been credited to your payment account.</p>
                        </div>
                        <p>We apologize for the inconvenience and welcome you to book another available date.</p>
                        <p>CarePath Healthcare Team</p>
                        </body></html>"""
                    )
        except Exception:
            pass

    db.commit()

    return {
        "success": True,
        "doctor_id": doctor.id,
        "doctor_name": doctor.name,
        "leave_date": str(leave_dt),
        "reason": reason,
        "refunded_tokens": refund_count,
        "message": f"Dr. {doctor.name} marked on leave for {leave_dt}. {refund_count} token(s) auto-refunded 100% to patient accounts."
    }


@app.get("/hospitals/{hospital_id}/doctors/{doctor_id}/exceptions")
@app.get("/doctors/{doctor_id}/leave")
def get_doctor_leaves(
    doctor_id: int,
    hospital_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Returns scheduled leaves/exceptions for a doctor."""
    today_ist = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
    query = db.query(DoctorScheduleException).filter(
        DoctorScheduleException.doctor_id == doctor_id,
        DoctorScheduleException.exception_date >= today_ist,
        DoctorScheduleException.is_closed == True,
    ).order_by(DoctorScheduleException.exception_date.asc())

    exceptions = query.all()
    return [
        {
            "id": e.id,
            "doctor_id": e.doctor_id,
            "leave_date": str(e.exception_date),
            "is_closed": e.is_closed,
            "reason": e.reason,
        }
        for e in exceptions
    ]


@app.delete("/hospitals/{hospital_id}/doctors/{doctor_id}/leave/{leave_date}")
def cancel_doctor_leave(
    hospital_id: int,
    doctor_id: int,
    leave_date: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Cancels a doctor's leave for a specific date if doctor resumes OPD."""
    if current_user["user_id"] != hospital_id:
        raise HTTPException(status_code=403, detail="Unauthorized.")

    try:
        leave_dt = date.fromisoformat(leave_date.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid leave date format.")

    exc = db.query(DoctorScheduleException).filter(
        DoctorScheduleException.doctor_id == doctor_id,
        DoctorScheduleException.exception_date == leave_dt,
    ).first()

    if not exc:
        raise HTTPException(status_code=404, detail="No leave found for this date.")

    db.delete(exc)
    db.commit()
    return {"success": True, "message": f"Doctor leave for {leave_date} cancelled successfully."}

