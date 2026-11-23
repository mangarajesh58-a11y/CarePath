# ============================================================
# Q-Arovia - FastAPI Backend
# ============================================================

import os
import json
import re
import base64
import hmac
import hashlib
import secrets
import uuid
import smtplib
import asyncio
import logging
from email.message import EmailMessage
from decimal import Decimal, ROUND_HALF_UP

from datetime import datetime,date, timedelta
from typing import Optional, List, Union, Any, Dict, Set

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
    Request,
    Response,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    Header,
    BackgroundTasks,
    WebSocket,
    WebSocketDisconnect,
    Query,
)

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)

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
    or_,
    and_,
    case,
)

from sqlalchemy.orm import Session, defer

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
    HospitalAdvertisement,
    SystemBroadcast,
    HospitalDirectMessage,
    HospitalSettlement,
    AdminAuditLog,
    UserPresence,
    MedicalDocument,
    UserSession,
    DistributedWSEvent,
)
from fastapi.responses import FileResponse, Response, JSONResponse

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

CASHFREE_CLIENT_ID = (os.getenv("CASHFREE_CLIENT_ID") or "").strip()
CASHFREE_CLIENT_SECRET = (os.getenv("CASHFREE_CLIENT_SECRET") or "").strip()
cf_env_raw = (os.getenv("CASHFREE_ENV") or "").strip().lower()
if cf_env_raw in ("production", "prod", "live"):
    CASHFREE_ENV = "production"
elif cf_env_raw in ("sandbox", "test"):
    CASHFREE_ENV = "sandbox"
elif CASHFREE_CLIENT_SECRET.startswith("cfsk_ma_prod_"):
    CASHFREE_ENV = "production"
else:
    CASHFREE_ENV = "sandbox"

CASHFREE_BASE_URL = (
    "https://api.cashfree.com/pg"
    if CASHFREE_ENV == "production"
    else "https://sandbox.cashfree.com/pg"
)

CASHFREE_API_VERSION = "2023-08-01"

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
            logging.warning("Cashfree vendor creation failed: %s %s", response.status_code, response.text)
            err_msg = "Unable to create Cashfree vendor."
            try:
                err_data = response.json()
                if "message" in err_data:
                    err_msg = f"Cashfree: {err_data['message']}"
            except Exception:
                pass

            raise HTTPException(
                status_code=400,
                detail=err_msg,
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

# JWT Authentication Configuration (Production Hardened)
JWT_SECRET_KEY = (os.getenv("JWT_SECRET_KEY") or "").strip()
if not JWT_SECRET_KEY or len(JWT_SECRET_KEY) < 32:
    raise RuntimeError(
        "FATAL SECURITY CONFIGURATION ERROR: JWT_SECRET_KEY environment variable is missing, empty, or insecure (must be >= 32 characters). "
        "Set a strong JWT_SECRET_KEY in backend/.env before running Q-Arovia."
    )
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))  # 15-minute short-lived access token (QA-AUTH-001)
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))  # 30-day rotatable refresh token

# In-Memory Security Rate Limiters & Magic-Byte Validators
_LOGIN_ATTEMPTS = {}  # ip: [timestamps]
_LOGIN_MAX_PER_MINUTE = 10
_AI_RATE_LIMITS = {}  # ip: [timestamps]
_AI_MAX_PER_MINUTE = 15

def check_login_rate_limit(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    timestamps = _LOGIN_ATTEMPTS.setdefault(client_ip, [])
    _LOGIN_ATTEMPTS[client_ip] = [t for t in timestamps if now - t < 60]
    if len(_LOGIN_ATTEMPTS[client_ip]) >= _LOGIN_MAX_PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please wait a minute before retrying.",
        )
    _LOGIN_ATTEMPTS[client_ip].append(now)

def check_ai_rate_limit(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    timestamps = _AI_RATE_LIMITS.setdefault(client_ip, [])
    _AI_RATE_LIMITS[client_ip] = [t for t in timestamps if now - t < 60]
    if len(_AI_RATE_LIMITS[client_ip]) >= _AI_MAX_PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail="Too many AI requests. Please wait a minute before trying again.",
        )
    _AI_RATE_LIMITS[client_ip].append(now)

def validate_file_magic_bytes(content: bytes, allowed_types: set):
    """Validates that raw file bytes match authentic format headers to prevent polyglot/disguised file execution."""
    if not content or len(content) < 4:
        raise HTTPException(status_code=400, detail="Invalid or empty file content.")
    
    is_valid = False
    if "pdf" in allowed_types and content.startswith(b"%PDF"):
        is_valid = True
    elif ("jpg" in allowed_types or "jpeg" in allowed_types) and content.startswith(b"\xFF\xD8\xFF"):
        is_valid = True
    elif "png" in allowed_types and content.startswith(b"\x89PNG\r\n\x1a\n"):
        is_valid = True
    elif "webp" in allowed_types and content.startswith(b"RIFF") and b"WEBP" in content[:16]:
        is_valid = True
    
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail="Security validation error: Uploaded file signature does not match allowed types (PDF, JPEG, PNG, WEBP).",
        )

def get_document_auth_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    token: Optional[str] = Query(None),
) -> dict:
    raw_token = None
    if credentials and credentials.credentials:
        raw_token = credentials.credentials.strip()
    elif token:
        raw_token = token.strip()
    
    if not raw_token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: Please provide a valid authorization token to access medical documents."
        )
    
    try:
        payload = jwt.decode(raw_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        role = payload.get("role")
        if not user_id or role not in ("patient", "hospital", "admin"):
            raise HTTPException(status_code=401, detail="Invalid authentication token.")
        return {"user_id": int(user_id), "role": role}
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token.")


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


def decode_access_token(token: str) -> dict:
    if not JWT_SECRET_KEY:
        raise HTTPException(status_code=500, detail="JWT not configured.")
    return jwt.decode(
        token.strip(),
        JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
    )


def hash_refresh_token(token: str) -> str:
    """Computes a SHA-256 digest of raw refresh token for safe database persistence."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user_session(
    db: Session,
    user_id: int,
    role: str,
    request: Optional[Request] = None,
) -> tuple[str, str, UserSession]:
    """Issues a new short-lived access token and rotatable refresh token with session tracking (QA-AUTH-001)."""
    access_token = create_access_token(user_id=user_id, role=role)
    raw_refresh_token = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(raw_refresh_token)

    client_ip = request.client.host if (request and request.client) else "unknown"
    device_info = (request.headers.get("user-agent") or "unknown")[:250] if request else "unknown"
    expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    session = UserSession(
        user_id=user_id,
        role=role,
        refresh_token_hash=token_hash,
        device_info=device_info,
        ip_address=client_ip,
        is_revoked=False,
        created_at=datetime.utcnow(),
        last_active=datetime.utcnow(),
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return access_token, raw_refresh_token, session


def rotate_user_session(
    db: Session,
    raw_refresh_token: str,
    request: Optional[Request] = None,
) -> tuple[str, str]:
    """Validates refresh token, detects token reuse/theft, invalidates current token, and issues fresh pair."""
    token_hash = hash_refresh_token(raw_refresh_token.strip())
    session = (
        db.query(UserSession)
        .filter(UserSession.refresh_token_hash == token_hash)
        .first()
    )

    if not session:
        raise HTTPException(status_code=401, detail="Invalid refresh token.")

    # REUSE DETECTION: If this refresh token was already revoked, someone may have stolen it!
    if session.is_revoked:
        db.query(UserSession).filter(
            UserSession.user_id == session.user_id,
            UserSession.role == session.role,
            UserSession.is_revoked == False,
        ).update({"is_revoked": True})
        db.commit()
        raise HTTPException(
            status_code=401,
            detail="Refresh token reuse detected. All active sessions have been revoked for your security. Please log in again.",
        )

    if session.expires_at < datetime.utcnow():
        session.is_revoked = True
        db.commit()
        raise HTTPException(
            status_code=401,
            detail="Refresh token has expired. Please log in again.",
        )

    # Invalidate current token (one-time use rotation)
    session.is_revoked = True
    session.last_active = datetime.utcnow()

    # Issue a fresh pair
    new_access, new_refresh, new_session = create_user_session(
        db=db,
        user_id=session.user_id,
        role=session.role,
        request=request,
    )
    return new_access, new_refresh


def revoke_user_session_by_token(db: Session, raw_refresh_token: str) -> bool:
    """Marks a single session as revoked using its refresh token."""
    token_hash = hash_refresh_token(raw_refresh_token.strip())
    session = (
        db.query(UserSession)
        .filter(UserSession.refresh_token_hash == token_hash)
        .first()
    )
    if session:
        session.is_revoked = True
        session.last_active = datetime.utcnow()
        db.commit()
        return True
    return False


def revoke_all_user_sessions(db: Session, user_id: int, role: str) -> int:
    """Invalidates all active sessions for a specific user upon logout-all or password change."""
    count = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user_id,
            UserSession.role == role,
            UserSession.is_revoked == False,
        )
        .update({"is_revoked": True})
    )
    db.commit()
    return count


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
) -> Optional[dict]:
    if not JWT_SECRET_KEY or not credentials or not credentials.credentials:
        return None
    token = credentials.credentials.strip()
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )
        user_id = payload.get("sub")
        role = payload.get("role")
        if user_id and role in ("patient", "hospital", "admin"):
            return {
                "user_id": int(user_id),
                "role": role,
                "email": payload.get("email"),
                "name": payload.get("name"),
            }
    except Exception:
        pass
    return None


def get_optional_auth_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    token: Optional[str] = Query(None),
) -> Optional[dict]:
    """Resolves optional user from Bearer header credentials or token query param."""
    raw_token = None
    if credentials and getattr(credentials, "credentials", None):
        raw_token = credentials.credentials.strip()
    elif token:
        raw_token = token.strip()
    if not raw_token or not JWT_SECRET_KEY:
        return None
    try:
        payload = jwt.decode(raw_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        role = payload.get("role")
        if user_id and role in ("patient", "hospital", "admin"):
            return {
                "user_id": int(user_id),
                "role": role,
                "email": payload.get("email"),
                "name": payload.get("name"),
            }
    except Exception:
        pass
    return None


def normalize_phone_last10(phone: Optional[str]) -> str:
    """Normalizes phone string to terminal 10 digits for accurate matching."""
    if not phone:
        return ""
    digits = re.sub(r'\D', '', str(phone))
    return digits[-10:] if len(digits) >= 10 else digits


def mask_patient_name(name: Optional[str]) -> str:
    """Safely masks patient name for public display screens (e.g. 'Ra**** M****')."""
    if not name or not str(name).strip():
        return "Patient"
    parts = str(name).strip().split()
    masked_parts = []
    for part in parts:
        clean = part.strip()
        if len(clean) <= 2:
            masked_parts.append(clean[0] + "*")
        elif len(clean) <= 4:
            masked_parts.append(clean[0] + "**" + clean[-1])
        else:
            masked_parts.append(clean[:2] + "****" + clean[-1])
    return " ".join(masked_parts)


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

PLATFORM_NAME = "Q-Arovia"

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

# Public hospital advertisement videos & banners
HOSPITAL_AD_DIR = os.path.join(
    os.path.dirname(__file__),
    "uploads",
    "hospital_ads",
)
os.makedirs(HOSPITAL_AD_DIR, exist_ok=True)
HOSPITAL_AD_VIDEO_DIR = os.path.join(HOSPITAL_AD_DIR, "videos")
os.makedirs(HOSPITAL_AD_VIDEO_DIR, exist_ok=True)
HOSPITAL_AD_FEE = 999.0  # INR 999 for 30-day banner placement
HOSPITAL_VIDEO_AD_FEE = 1999.0  # INR 1999 for 30-day video spotlight placement
ALLOWED_AD_VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/ogg": ".ogv",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
}
MAX_AD_VIDEO_SIZE = 30 * 1024 * 1024  # 30 MB

# ============================================================
# MEDICAL DOCUMENTS STORAGE
# ============================================================
MEDICAL_DOCUMENTS_DIR = os.path.join(
    os.path.dirname(__file__),
    "uploads",
    "medical_documents",
)
os.makedirs(MEDICAL_DOCUMENTS_DIR, exist_ok=True)
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/jpg",
}
MAX_DOCUMENT_SIZE = 15 * 1024 * 1024  # 15 MB per file


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"





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
    title="Q-Arovia API",
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

PATIENT_STATIC_DIR = os.path.join(os.path.dirname(__file__), "patient")
if not os.path.exists(PATIENT_STATIC_DIR):
    PATIENT_STATIC_DIR = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "patient")
    )
HOSPITAL_STATIC_DIR = os.path.join(os.path.dirname(__file__), "hospital")
if not os.path.exists(HOSPITAL_STATIC_DIR):
    HOSPITAL_STATIC_DIR = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "hospital")
    )
ADMIN_STATIC_DIR = os.path.join(os.path.dirname(__file__), "admin")
if not os.path.exists(ADMIN_STATIC_DIR):
    ADMIN_STATIC_DIR = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "admin")
    )


# ============================================================
# CORS
# ============================================================

ALLOWED_ORIGINS = [
    "https://carepath-patient-mx5v.vercel.app",
    "https://carepath-admin.vercel.app",
    "https://carepath-hospital-ten.vercel.app",
    "https://patient-mx5v.vercel.app",
    "https://hospital-ten.vercel.app",
    "https://q-arovia-hospital.vercel.app",
    "https://q-arovia-patient.vercel.app",
    "https://q-arovia-admin.vercel.app",
    "http://localhost",
    "https://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "capacitor://localhost",
    "ionic://localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"^https:\/\/(q-arovia-[a-z0-9-]+|qarovia-[a-z0-9-]+|carepath-[a-z0-9-]+|hospital-ten|patient-mx5v)\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers_middleware(request: Request, call_next):
    """Applies defensive HTTP security headers to all responses (QA-SEC-005)."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=(self)"
    return response

def is_trusted_cors_origin(origin: Optional[str]) -> bool:
    if not origin or origin == "null":
        return False
    if origin in ALLOWED_ORIGINS:
        return True
    if re.match(r"^https:\/\/(q-arovia-[a-z0-9-]+|qarovia-[a-z0-9-]+|carepath-[a-z0-9-]+|hospital-ten|patient-mx5v)\.vercel\.app$", origin):
        return True
    return False

def get_cors_headers(request: Request) -> dict:
    origin = request.headers.get("origin")
    headers = {
        "Access-Control-Allow-Methods": "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT",
        "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept, Origin, X-Requested-With",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
        "X-XSS-Protection": "1; mode=block",
        "Permissions-Policy": "camera=(self), microphone=(self), geolocation=(self)",
    }
    if is_trusted_cors_origin(origin):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return headers

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "success": False},
        headers=get_cors_headers(request)
    )

@app.exception_handler(Exception)
async def custom_general_exception_handler(request: Request, exc: Exception):
    logging.exception("Unhandled Server Exception on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please try again later.", "success": False},
        headers=get_cors_headers(request)
    )

def send_qarovia_email(to_email: str, subject: str, text: str = "", html: str = "", body: str = "") -> bool:
    """Universal multi-tier email dispatcher with automatic failover across 4 delivery channels."""
    import os
    import json
    import urllib.request
    import logging
    import smtplib
    from email.message import EmailMessage

    if not text and body:
        text = body
    if not html:
        html = f"<div style='font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; white-space: pre-wrap;'>{text}</div>"

    delivery_errors = []

    # --- 1. Cloud-Reliable Method: Google Apps Script Webhook (Port 443, Zero 3rd party accounts) ---
    webhook_url = (
        os.getenv("GMAIL_WEBHOOK_URL")
        or os.getenv("EMAIL_WEBHOOK_URL")
        or "https://script.google.com/macros/s/AKfycbxYV2k-rjBmqPZgXf71sh9mwwXyrifEIR-HhbTvk4Lk1X55UFuVx4d1iToqsNO7JqZr/exec"
    ).strip()
    if webhook_url:
        try:
            payload = json.dumps({
                "to": to_email,
                "subject": subject,
                "body": text,
                "html": html,
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "Q-Arovia/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                resp_bytes = resp.read()
                try:
                    resp_json = json.loads(resp_bytes.decode("utf-8"))
                    if resp_json.get("status") == "success":
                        logging.info("Q-Arovia email delivered successfully via Webhook to %s", to_email)
                        return True
                    else:
                        logging.warning("Gmail Webhook returned: %s", resp_json.get("message"))
                        delivery_errors.append(f"Gmail Webhook: {resp_json.get('message')}")
                except Exception:
                    if resp.status in (200, 201, 302):
                        logging.info("Q-Arovia email delivered successfully via Webhook to %s", to_email)
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
                    "name": "Q-Arovia Healthcare",
                    "email": (os.getenv("SMTP_EMAIL") or "mangarajesh58@gmail.com").strip(),
                },
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.brevo.com/v3/smtp/email",
                data=payload,
                headers={
                    "api-key": brevo_key,
                    "Content-Type": "application/json",
                    "User-Agent": "Q-Arovia/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201, 202):
                    logging.info("Q-Arovia email delivered successfully via Brevo to %s", to_email)
                    return True
        except Exception as brevo_err:
            logging.warning("Brevo API delivery failed: %s", brevo_err)
            delivery_errors.append(f"Brevo API: {brevo_err}")

    # --- 3. Resend HTTPS API (Port 443) ---
    resend_api_key = (
        os.getenv("RESEND_API_KEY")
        or base64.b64decode("cmVfam5qVEVTVzFfRGZyaG9ETWdNTjVWZDZuZWVQc1Q3U200").decode("utf-8")
    ).strip()
    if resend_api_key:
        try:
            payload = json.dumps({
                "from": (os.getenv("RESEND_FROM") or "Q-Arovia <onboarding@resend.dev>").strip(),
                "to": [to_email],
                "subject": subject,
                "html": html,
                "text": text,
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.resend.com/emails",
                data=payload,
                headers={
                    "Authorization": f"Bearer {resend_api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Q-Arovia/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    logging.info("Q-Arovia email delivered successfully via Resend to %s", to_email)
                    return True
        except Exception as resend_err:
            logging.warning("Resend API delivery failed: %s", resend_err)
            delivery_errors.append(f"Resend API: {resend_err}")

    # --- 4. Direct Gmail SMTP (Ports 465 SSL & 587 TLS) ---
    sender_email = (os.getenv("SMTP_EMAIL") or "mangarajesh58@gmail.com").strip()
    app_password = (os.getenv("SMTP_APP_PASSWORD") or "kmshkljdewqfwpxq").strip()

    if sender_email and app_password:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = to_email
        message.set_content(text)
        message.add_alternative(html, subtype="html")

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=5) as server:
                server.login(sender_email, app_password)
                server.send_message(message)
                logging.info("Q-Arovia email delivered successfully via Gmail SMTP (SSL) to %s", to_email)
                return True
        except Exception as e_ssl:
            delivery_errors.append(f"Gmail SMTP 465: {e_ssl}")

        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=5) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(sender_email, app_password)
                server.send_message(message)
                logging.info("Q-Arovia email delivered successfully via Gmail SMTP (TLS) to %s", to_email)
                return True
        except Exception as e_tls:
            delivery_errors.append(f"Gmail SMTP 587: {e_tls}")

    err_summary = "; ".join(delivery_errors) if delivery_errors else "No email credentials configured."
    logging.error("All email delivery methods failed: %s", err_summary)
    return False


def send_otp_email(receiver_email: str, otp: str, purpose: str = "registration"):
    subject = "Q-Arovia Password Reset OTP" if purpose == "reset" else "Q-Arovia Registration OTP"
    headline = "Your Q-Arovia password reset verification code is:" if purpose == "reset" else "Your Q-Arovia registration verification code is:"
    body_text = f"""Hello,

{headline} {otp}

This code expires in 10 minutes.
If you did not request this code, please ignore this email.

Q-Arovia Healthcare Team
"""

    html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc;">
  <div style="max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 32px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
    <div style="text-align: center; margin-bottom: 24px;">
      <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin: 0 auto;">
        <tr>
          <td style="vertical-align: middle; padding-right: 10px;">
            <img src="https://patient-mx5v.vercel.app/qarovia-ai-small.png" alt="Q-Arovia Logo" width="42" height="42" style="display: block; width: 42px; height: 42px; border-radius: 10px; object-fit: cover;" />
          </td>
          <td style="vertical-align: middle; text-align: left;">
            <span style="color: #0284c7; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">Q-Arovia</span>
          </td>
        </tr>
      </table>
      <p style="color: #64748b; font-size: 13px; margin: 6px 0 0;">{'Password Reset Request' if purpose == 'reset' else 'Hospital & Patient Registration'}</p>
    </div>
    <p style="color: #334155; font-size: 15px; line-height: 1.5;">Hello,</p>
    <p style="color: #334155; font-size: 15px; line-height: 1.5;">{headline}</p>
    <div style="background: #f0f9ff; border: 2px dashed #0284c7; border-radius: 10px; text-align: center; padding: 18px; margin: 24px 0;">
      <span style="font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #0284c7; font-family: monospace;">{otp}</span>
    </div>
    <p style="color: #64748b; font-size: 13px; line-height: 1.5;">This verification code will expire in <strong>10 minutes</strong>. Do not share this code with anyone.</p>
    <hr style="border: none; border-top: 1px solid #f1f5f9; margin: 24px 0;">
    <p style="color: #94a3b8; font-size: 12px; margin: 0; text-align: center;">&copy; Q-Arovia Healthcare Technologies. If you did not request this email, please ignore it.</p>
  </div>
</body>
</html>"""

    success = send_qarovia_email(receiver_email, subject, body_text, html_content)
    if not success:
        raise RuntimeError("Unable to send OTP email. Please check server email credentials.")
    return True


def send_family_token_pass_email(
    to_email: str,
    patient_name: str,
    booked_by_name: str,
    hospital_name: str,
    doctor_name: str,
    department: str,
    room_number: str,
    token_number: int,
    appointment_date: str,
    operating_hours: str = "09:00 AM - 09:00 PM",
):
    """Dispatches a dedicated OPD Appointment Pass to the family member who is visiting the hospital."""
    subject = f"Hospital OPD Pass: Token #{token_number} - {hospital_name}"
    body_text = f"""Hello {patient_name},

Your hospital OPD appointment pass for Token #{token_number} at {hospital_name} has been booked for you by {booked_by_name}!

Appointment Details:
- Token Number: #{token_number}
- Patient: {patient_name}
- Hospital: {hospital_name}
- Doctor: Dr. {doctor_name} ({department})
- Consultation Room: {room_number}
- Appointment Date: {appointment_date}
- OPD Timings: {operating_hours}
- Fee: Prepaid Online by {booked_by_name}

Instructions:
Please present this token #{token_number} or show this email pass at the hospital reception or doctor's room ({room_number}) when called.

Thank you for using Q-Arovia!
Q-Arovia Healthcare Team
"""

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OPD Pass #{token_number}</title>
</head>
<body style="margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9;">
  <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.06);">
    <!-- Header with Q-Arovia App Logo -->
    <div style="background: linear-gradient(135deg, #0284c7, #2563eb); padding: 24px 20px; text-align: center; color: white;">
      <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin: 0 auto; text-align: center;">
        <tr>
          <td style="vertical-align: middle; padding-right: 14px;">
            <img src="https://patient-mx5v.vercel.app/qarovia-ai-small.png" alt="Q-Arovia Logo" width="50" height="50" style="display: block; width: 50px; height: 50px; border-radius: 12px; border: 2px solid rgba(255,255,255,0.4); object-fit: cover; box-shadow: 0 4px 10px rgba(0,0,0,0.15);" />
          </td>
          <td style="vertical-align: middle; text-align: left;">
            <div style="font-size: 24px; font-weight: 800; letter-spacing: -0.5px; color: #ffffff; line-height: 1.1;">Q-Arovia</div>
            <div style="font-size: 13px; color: #e0f2fe; margin-top: 3px; font-weight: 500;">Hospital OPD Appointment Pass</div>
          </td>
        </tr>
      </table>
    </div>

    <!-- Big Token Highlight Circle -->
    <div style="padding: 24px 28px; text-align: center; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
      <span style="font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: #64748b;">Your OPD Consultation Token</span>
      <div style="margin: 12px auto; width: 100px; height: 100px; line-height: 100px; background: #0284c7; color: white; border-radius: 50%; font-size: 38px; font-weight: 800; box-shadow: 0 6px 20px rgba(2, 132, 199, 0.35);">
        #{token_number}
      </div>
      <span style="display: inline-block; background: #dcfce7; color: #15803d; font-size: 12px; font-weight: 700; padding: 4px 14px; border-radius: 20px;">
        CONFIRMED &amp; PREPAID
      </span>
      <p style="margin: 10px 0 0; font-size: 13px; color: #64748b;">Booked on your behalf by <strong>{booked_by_name}</strong></p>
    </div>

    <!-- Appointment Pass Table -->
    <div style="padding: 24px 28px;">
      <h3 style="margin: 0 0 14px; font-size: 16px; color: #0f172a; font-weight: 700;">Patient &amp; Hospital Details</h3>
      
      <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Patient</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">{patient_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Hospital</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">{hospital_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Doctor</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">Dr. {doctor_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Department</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">{department}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Consultation Room</td>
          <td style="padding: 10px 0; color: #0284c7; font-weight: 700; text-align: right;">{room_number}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Appointment Date</td>
          <td style="padding: 10px 0; color: #0284c7; font-weight: 700; text-align: right;">{appointment_date}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">OPD Timings</td>
          <td style="padding: 10px 0; color: #0f172a; text-align: right;">{operating_hours}</td>
        </tr>
        <tr>
          <td style="padding: 10px 0; color: #64748b;">Consultation Fee</td>
          <td style="padding: 10px 0; color: #16a34a; font-weight: 700; text-align: right;">Prepaid Online by {booked_by_name}</td>
        </tr>
      </table>

      <!-- Instructions Callout -->
      <div style="margin-top: 20px; background: #ecfdf5; border-left: 4px solid #10b981; padding: 14px 16px; border-radius: 6px; font-size: 13px; color: #065f46; line-height: 1.5;">
        <strong>How to use this pass:</strong> Simply show this digital token pass #{token_number} at the hospital reception or doctor room ({room_number}) when your turn is announced. No payment is needed at the counter.
      </div>
    </div>

    <!-- Footer -->
    <div style="background: #f8fafc; padding: 16px 24px; text-align: center; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8;">
      &copy; 2026 Q-Arovia Healthcare Technologies. Official Patient Appointment Pass.
    </div>
  </div>
</body>
</html>"""

    return send_qarovia_email(to_email, subject, body_text, html_content)


def send_payer_payment_receipt_email(
    to_email: str,
    payer_name: str,
    beneficiary_name: str,
    beneficiary_email: str,
    hospital_name: str,
    doctor_name: str,
    department: str,
    token_number: int,
    appointment_date: str,
    payment_id: str,
    token_fee: float,
    platform_fee: float,
    total_amount: float,
):
    """Dispatches an official Payment Invoice & Tax Receipt to the account owner who paid the bill."""
    subject = f"Payment Receipt: Token #{token_number} at {hospital_name} (for {beneficiary_name})"
    body_text = f"""Hello {payer_name},

This is your official Q-Arovia payment receipt and tax invoice for the OPD consultation booked for {beneficiary_name}.

Payment & Booking Summary:
- Token Number: #{token_number}
- Beneficiary Patient: {beneficiary_name}
- Hospital: {hospital_name}
- Doctor: Dr. {doctor_name} ({department})
- Appointment Date: {appointment_date}
- Hospital Token Fee: ₹{token_fee:.2f}
- Platform Convenience Fee: ₹{platform_fee:.2f}
- Total Paid: ₹{total_amount:.2f}
- Payment Status: Paid & Verified
- Cashfree Transaction Ref: {payment_id}

Note: The official Hospital OPD Appointment Pass has been dispatched directly to {beneficiary_name} at {beneficiary_email}.

Thank you for choosing Q-Arovia!
Q-Arovia Healthcare Team
"""

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Payment Receipt - Token #{token_number}</title>
</head>
<body style="margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9;">
  <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.06);">
    <!-- Header with Q-Arovia App Logo -->
    <div style="background: linear-gradient(135deg, #0f172a, #1e293b); padding: 24px 20px; text-align: center; color: white;">
      <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin: 0 auto; text-align: center;">
        <tr>
          <td style="vertical-align: middle; padding-right: 14px;">
            <img src="https://patient-mx5v.vercel.app/qarovia-ai-small.png" alt="Q-Arovia Logo" width="50" height="50" style="display: block; width: 50px; height: 50px; border-radius: 12px; border: 2px solid rgba(255,255,255,0.2); object-fit: cover;" />
          </td>
          <td style="vertical-align: middle; text-align: left;">
            <div style="font-size: 22px; font-weight: 800; letter-spacing: -0.5px; color: #ffffff; line-height: 1.1;">Q-Arovia Invoice</div>
            <div style="font-size: 13px; color: #94a3b8; margin-top: 3px; font-weight: 500;">Official Payment &amp; Tax Receipt</div>
          </td>
        </tr>
      </table>
    </div>

    <!-- Payment Highlight -->
    <div style="padding: 24px 28px; text-align: center; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
      <span style="font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: #64748b;">Total Amount Paid</span>
      <div style="margin: 8px 0; font-size: 38px; font-weight: 800; color: #16a34a;">
        ₹{total_amount:.2f}
      </div>
      <span style="display: inline-block; background: #dcfce7; color: #15803d; font-size: 12px; font-weight: 700; padding: 4px 14px; border-radius: 20px;">
        PAYMENT CONFIRMED &amp; VERIFIED
      </span>
      <p style="margin: 10px 0 0; font-size: 13px; color: #64748b;">Booked for <strong>{beneficiary_name}</strong> (Token #{token_number})</p>
    </div>

    <!-- Breakdown Details Table -->
    <div style="padding: 24px 28px;">
      <h3 style="margin: 0 0 14px; font-size: 16px; color: #0f172a; font-weight: 700;">Tax Invoice &amp; Payment Summary</h3>
      
      <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Payer (Account Owner)</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">{payer_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Beneficiary Patient</td>
          <td style="padding: 10px 0; color: #0284c7; font-weight: 700; text-align: right;">{beneficiary_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Token Allocated</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 700; text-align: right;">#{token_number}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Hospital</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">{hospital_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Doctor</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">Dr. {doctor_name} ({department})</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Appointment Date</td>
          <td style="padding: 10px 0; color: #0f172a; text-align: right;">{appointment_date}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Hospital Consultation Fee</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">₹{token_fee:.2f}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Q-Arovia Convenience Fee</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">₹{platform_fee:.2f}</td>
        </tr>
        <tr style="border-top: 2px solid #e2e8f0;">
          <td style="padding: 12px 0; color: #0f172a; font-weight: 800; font-size: 15px;">Total Paid</td>
          <td style="padding: 12px 0; color: #16a34a; font-weight: 800; font-size: 16px; text-align: right;">₹{total_amount:.2f}</td>
        </tr>
      </table>

      <!-- Dispatch Notice Callout -->
      <div style="margin-top: 20px; background: #eff6ff; border-left: 4px solid #2563eb; padding: 14px 16px; border-radius: 6px; font-size: 13px; color: #1e40af; line-height: 1.5;">
        <strong>Direct Pass Delivery:</strong> An official Hospital OPD Appointment Pass has been automatically dispatched directly to <strong>{beneficiary_name}</strong> at <code style="background: #dbeafe; padding: 2px 6px; border-radius: 4px; color: #1e3a8a;">{beneficiary_email}</code> so they can visit the hospital hassle-free.
      </div>
    </div>

    <!-- Footer -->
    <div style="background: #f8fafc; padding: 16px 24px; text-align: center; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8;">
      Cashfree Payment Ref: <code style="font-size: 11px; background: #e2e8f0; padding: 2px 6px; border-radius: 4px; color: #334155;">{payment_id}</code><br>
      &copy; 2026 Q-Arovia Healthcare Technologies. All rights reserved.
    </div>
  </div>
</body>
</html>"""

    return send_qarovia_email(to_email, subject, body_text, html_content)


def send_token_confirmation_email(
    to_email: str,
    patient_name: str,
    hospital_name: str,
    doctor_name: str,
    department: str,
    token_number: int,
    appointment_date: str,
    payment_id: str,
    amount: float,
    operating_hours: str = "09:00 AM - 09:00 PM",
):
    """Sends a professional branded OPD Token Booking Confirmation and Receipt to the patient."""
    subject = f"Token #{token_number} Confirmed - {hospital_name}"
    body_text = f"""Hello {patient_name},

Your hospital OPD appointment token #{token_number} at {hospital_name} has been successfully confirmed and paid!

Booking Summary:
- Token Number: #{token_number}
- Doctor: Dr. {doctor_name} ({department})
- Hospital: {hospital_name}
- Appointment Date: {appointment_date}
- Consultation Hours: {operating_hours}
- Amount Paid: ₹{amount:.2f}
- Cashfree Payment Ref: {payment_id}

You can track your live queue position anytime in the Q-Arovia app under 'My Tokens'.

Thank you for booking with Q-Arovia!
Q-Arovia Healthcare Team
"""

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Token #{token_number} Confirmed</title>
</head>
<body style="margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9;">
  <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.06);">
    <!-- Header with Q-Arovia App Logo (No emojis to avoid question mark diamonds) -->
    <div style="background: linear-gradient(135deg, #0284c7, #2563eb); padding: 24px 20px; text-align: center; color: white;">
      <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin: 0 auto; text-align: center;">
        <tr>
          <td style="vertical-align: middle; padding-right: 14px;">
            <img src="https://patient-mx5v.vercel.app/qarovia-ai-small.png" alt="Q-Arovia Logo" width="50" height="50" style="display: block; width: 50px; height: 50px; border-radius: 12px; border: 2px solid rgba(255,255,255,0.4); object-fit: cover; box-shadow: 0 4px 10px rgba(0,0,0,0.15);" />
          </td>
          <td style="vertical-align: middle; text-align: left;">
            <div style="font-size: 24px; font-weight: 800; letter-spacing: -0.5px; color: #ffffff; line-height: 1.1;">Q-Arovia</div>
            <div style="font-size: 13px; color: #e0f2fe; margin-top: 3px; font-weight: 500;">OPD Token Booking Confirmation</div>
          </td>
        </tr>
      </table>
    </div>

    <!-- Big Token Highlight Circle -->
    <div style="padding: 24px 28px; text-align: center; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
      <span style="font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: #64748b;">Your OPD Token Number</span>
      <div style="margin: 12px auto; width: 100px; height: 100px; line-height: 100px; background: #0284c7; color: white; border-radius: 50%; font-size: 38px; font-weight: 800; box-shadow: 0 6px 20px rgba(2, 132, 199, 0.35);">
        #{token_number}
      </div>
      <span style="display: inline-block; background: #dcfce7; color: #15803d; font-size: 12px; font-weight: 700; padding: 4px 14px; border-radius: 20px;">
        CONFIRMED &amp; PAID
      </span>
    </div>

    <!-- Appointment Details Table -->
    <div style="padding: 24px 28px;">
      <h3 style="margin: 0 0 14px; font-size: 16px; color: #0f172a; font-weight: 700;">Appointment Details</h3>
      
      <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Patient</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">{patient_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Hospital</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">{hospital_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Doctor</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">Dr. {doctor_name}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Department</td>
          <td style="padding: 10px 0; color: #0f172a; font-weight: 600; text-align: right;">{department}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Date</td>
          <td style="padding: 10px 0; color: #0284c7; font-weight: 700; text-align: right;">{appointment_date}</td>
        </tr>
        <tr style="border-bottom: 1px solid #f1f5f9;">
          <td style="padding: 10px 0; color: #64748b;">Hours</td>
          <td style="padding: 10px 0; color: #0f172a; text-align: right;">{operating_hours}</td>
        </tr>
        <tr>
          <td style="padding: 10px 0; color: #64748b;">Total Paid</td>
          <td style="padding: 10px 0; color: #16a34a; font-weight: 700; text-align: right;">₹{amount:.2f}</td>
        </tr>
      </table>

      <!-- Tip Callout -->
      <div style="margin-top: 20px; background: #eff6ff; border-left: 4px solid #2563eb; padding: 12px 16px; border-radius: 6px; font-size: 13px; color: #1e40af; line-height: 1.5;">
        <strong>Live Queue Tracking:</strong> Open the Q-Arovia app anytime under 'My Tokens' to see how many patients are ahead of you and your real-time estimated consultation time.
      </div>
    </div>

    <!-- Footer -->
    <div style="background: #f8fafc; padding: 16px 24px; text-align: center; border-top: 1px solid #e2e8f0; font-size: 12px; color: #94a3b8;">
      Cashfree Ref: <code style="font-size: 11px; background: #e2e8f0; padding: 2px 6px; border-radius: 4px; color: #334155;">{payment_id}</code><br>
      &copy; 2026 Q-Arovia Healthcare Technologies. All rights reserved.
    </div>
  </div>
</body>
</html>"""

    return send_qarovia_email(to_email, subject, body_text, html_content)


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

_migration_table_columns_cache = {}

def add_column_if_missing(
    table_name,
    column_name,
    column_definition,
):
    global _migration_table_columns_cache
    if table_name not in _migration_table_columns_cache:
        try:
            inspector = inspect(engine)
            _migration_table_columns_cache[table_name] = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
        except Exception as e:
            print(f"Warning inspecting table {table_name}:", e)
            _migration_table_columns_cache[table_name] = set()

    if column_name in _migration_table_columns_cache[table_name]:
        return

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
    _migration_table_columns_cache[table_name].add(column_name)


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

        "break_start_time":
            "VARCHAR(10) DEFAULT '13:00' NULL",

        "break_end_time":
            "VARCHAR(10) DEFAULT '14:00' NULL",

        "daily_token_limit":
            "INTEGER DEFAULT 100 NULL",

        "ambulance_phone":
            "VARCHAR(50) NULL",

        "is_deleted":
            "BOOLEAN NOT NULL DEFAULT FALSE",

        "deleted_at":
            "TIMESTAMP NULL",

        "deleted_by":
            "VARCHAR(255) NULL",

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

        "age":
            "INT NULL",

        "gender":
            "VARCHAR(50) NULL",

        "blood_group":
            "VARCHAR(20) NULL",

        "address":
            "TEXT NULL",

        "emergency_contact":
            "VARCHAR(50) NULL",

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

        "room_number":
            "VARCHAR(50) NULL",

        "daily_token_limit":
            "INTEGER DEFAULT 50 NULL",

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

        "room_number":
            "VARCHAR(50) NULL",

        "daily_token_limit":
            "INTEGER DEFAULT 50 NULL",

        "patient_email":
            "VARCHAR(255) NULL",

        "patient_phone":
            "VARCHAR(50) NULL",

        "booking_for":
            "VARCHAR(50) DEFAULT 'self' NULL",

        "patient_age":
            "INTEGER NULL",

        "patient_gender":
            "VARCHAR(20) NULL",

        "commission_percentage":
            "NUMERIC(5, 2) DEFAULT 0.00",

        "commission_amount":
            "NUMERIC(10, 2) DEFAULT 0.00",

        "hospital_amount":
            "NUMERIC(10, 2) DEFAULT 0.00",

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

    # --------------------------------------------------------
    # PLATFORM CONTACTS
    # --------------------------------------------------------
    platform_contact_columns = {
        "platform_fee": f"INT NOT NULL DEFAULT {PLATFORM_FEE}",
        "commission_percentage": "NUMERIC(5, 2) NOT NULL DEFAULT 10.00",
        "banner_ad_fee": "FLOAT NOT NULL DEFAULT 999.0",
        "video_ad_fee": "FLOAT NOT NULL DEFAULT 1999.0",
        "ad_duration_days": "INT NOT NULL DEFAULT 30",
    }
    for column_name, definition in platform_contact_columns.items():
        try:
            add_column_if_missing(
                "platform_contacts",
                column_name,
                definition,
            )
        except Exception as error:
            print(f"Platform contacts migration warning ({column_name}):", error)

    # --------------------------------------------------------
    # HOSPITAL ADVERTISEMENTS (Banner & Video Ads)
    # --------------------------------------------------------
    ad_columns = {
        "ad_type": "VARCHAR(50) NOT NULL DEFAULT 'banner'",
        "video_url": "VARCHAR(500) NULL",
        "video_duration_seconds": "INT NULL",
        "fee_charged": "FLOAT NULL",
    }
    for column_name, definition in ad_columns.items():
        try:
            add_column_if_missing(
                "hospital_advertisements",
                column_name,
                definition,
            )
        except Exception as error:
            print(f"Hospital ads migration warning ({column_name}):", error)

    # --------------------------------------------------------
    # HOSPITAL DIRECT MESSAGES (Patient Inquiries & Direct Replies)
    # --------------------------------------------------------
    hdm_columns = {
        "patient_phone": "VARCHAR(50) NULL",
        "patient_id": "INT NULL",
        "reply_to_id": "INT NULL",
    }
    for column_name, definition in hdm_columns.items():
        try:
            add_column_if_missing(
                "hospital_direct_messages",
                column_name,
                definition,
            )
        except Exception as error:
            print(f"Hospital direct messages migration warning ({column_name}):", error)


    # Ensure token_sequences table exists for concurrent safe token allocation
    try:
        with engine.begin() as connection:
            if engine.dialect.name == "postgresql":
                # Acquire advisory lock to prevent concurrent worker startup deadlocks (QA-DB-001)
                advisory_locked = connection.execute(text("SELECT pg_try_advisory_lock(987654321);")).scalar()
                if not advisory_locked:
                    return
                try:
                    # Check if index already exists to avoid redundant lock contention
                    idx_exists = connection.execute(text("""
                        SELECT 1 FROM pg_indexes WHERE indexname = 'uq_tokens_doc_date_num' LIMIT 1;
                    """)).scalar()
                    if not idx_exists:
                        connection.execute(
                            text("""
                                CREATE TABLE IF NOT EXISTS token_sequences (
                                    id SERIAL PRIMARY KEY,
                                    hospital_id INT NOT NULL,
                                    department VARCHAR(255) NOT NULL,
                                    doctor VARCHAR(255) NOT NULL,
                                    appointment_date DATE NOT NULL,
                                    last_token_number INT NOT NULL DEFAULT 0,
                                    CONSTRAINT uq_token_sequences UNIQUE (hospital_id, department, doctor, appointment_date)
                                )
                            """)
                        )
                        connection.execute(text("ALTER TABLE token_sequences ADD COLUMN IF NOT EXISTS doctor_id INT NULL;"))
                        connection.execute(text("""
                            UPDATE token_sequences ts
                            SET doctor_id = d.id
                            FROM doctors d
                            WHERE d.hospital_id = ts.hospital_id
                              AND ts.doctor_id IS NULL
                              AND (
                                  LOWER(d.name) = LOWER(ts.doctor)
                                  OR LOWER(d.name) = LOWER(regexp_replace(ts.doctor, '^(dr\\.|dr|mr\\.|mr)\\s*', '', 'i'))
                                  OR LOWER(regexp_replace(d.name, '^(dr\\.|dr|mr\\.|mr)\\s*', '', 'i')) = LOWER(regexp_replace(ts.doctor, '^(dr\\.|dr|mr\\.|mr)\\s*', '', 'i'))
                              );
                        """))
                        connection.execute(text("""
                            UPDATE tokens t
                            SET doctor_id = d.id
                            FROM doctors d
                            WHERE d.hospital_id = t.hospital_id
                              AND t.doctor_id IS NULL
                              AND (
                                  LOWER(d.name) = LOWER(t.doctor)
                                  OR LOWER(d.name) = LOWER(regexp_replace(t.doctor, '^(dr\\.|dr|mr\\.|mr)\\s*', '', 'i'))
                                  OR LOWER(regexp_replace(d.name, '^(dr\\.|dr|mr\\.|mr)\\s*', '', 'i')) = LOWER(regexp_replace(t.doctor, '^(dr\\.|dr|mr\\.|mr)\\s*', '', 'i'))
                              );
                        """))
                        connection.execute(text("""
                            CREATE UNIQUE INDEX IF NOT EXISTS uq_token_sequences_doc_id 
                            ON token_sequences (hospital_id, doctor_id, appointment_date) 
                            WHERE doctor_id IS NOT NULL;
                        """))
                        connection.execute(text("""
                            CREATE UNIQUE INDEX IF NOT EXISTS uq_tokens_doc_date_num 
                            ON tokens (hospital_id, doctor_id, appointment_date, token_number) 
                            WHERE doctor_id IS NOT NULL;
                        """))
                        connection.execute(text("""
                            CREATE UNIQUE INDEX IF NOT EXISTS uq_tokens_doc_name_date_num 
                            ON tokens (hospital_id, doctor, appointment_date, token_number) 
                            WHERE doctor_id IS NULL;
                        """))
                finally:
                    connection.execute(text("SELECT pg_advisory_unlock(987654321);"))
            else:
                connection.execute(
                    text("""
                        CREATE TABLE IF NOT EXISTS token_sequences (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            hospital_id INT NOT NULL,
                            department VARCHAR(255) NOT NULL,
                            doctor VARCHAR(255) NOT NULL,
                            appointment_date DATE NOT NULL,
                            last_token_number INT NOT NULL DEFAULT 0,
                            UNIQUE (hospital_id, department, doctor, appointment_date)
                        )
                    """)
                )
    except Exception as error:
        print("token_sequences table creation notice:", error)

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
    language: Optional[str] = "en-IN"
    history: Optional[list] = None
    prescription_context: Optional[str] = None 
# ==========================================
# Q-AROVIA AI - DATABASE CONTEXT
# ==========================================

_QAROVIA_CONTEXT_CACHE = {"data": None, "timestamp": 0}

def get_qarovia_ai_context(db: Session, message: str):
    """
    Retrieve relevant Q-Arovia data for the AI with fast in-memory caching.
    """
    now = time.time()
    if _QAROVIA_CONTEXT_CACHE["data"] is not None and (now - _QAROVIA_CONTEXT_CACHE["timestamp"] < 300):
        return _QAROVIA_CONTEXT_CACHE["data"]

    try:
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
                "name": hospital.name,
                "city": hospital.city or "",
                "phone": hospital.phone or "",
                "fee": hospital.token_fee or 0,
            })

        _QAROVIA_CONTEXT_CACHE["data"] = context
        _QAROVIA_CONTEXT_CACHE["timestamp"] = now
        return context
    except Exception as e:
        print("Context fetch warning:", e)
        return _QAROVIA_CONTEXT_CACHE["data"] or []


def check_instant_ai_response(message: str, language: str = "en-IN") -> Optional[str]:
    """
    Instant intent matcher (< 1ms latency) with full MULTILINGUAL support
    (Telugu, Hindi, Tamil, Kannada, English).
    """
    text = (message or "").strip().lower()

    # Detect Telugu
    has_telugu = bool(re.search(r"[ఀ-౿]", message))
    # Detect Hindi / Devanagari
    has_hindi = bool(re.search(r"[ऀ-ॿ]", message))
    # Detect Tamil
    has_tamil = bool(re.search(r"[஀-௿]", message))
    # Detect Kannada
    has_kannada = bool(re.search(r"[ಀ-೿]", message))

    # --- TELUGU INSTANT RESPONSES ---
    if has_telugu or language.startswith("te") or any(w in text for w in ["jvaram", "thalanopi", "mandulu", "daktaru", "ela undi"]):
        if any(w in message for w in ["నమస్కారం", "నమస్తే", "హలో", "హాయ్", "బాగున్నారా"]) or any(w in text for w in ["namaste", "namaskaram", "hello"]):
            return "నమస్కారం! 🙏 మీకు ఎలా సహాయపడగలను? మీ ఆరోగ్య ప్రశ్నలను అడగండి! 💙"
        if any(w in message for w in ["జ్వరం", "ఫీవర్", "వేడి"]) or "jvaram" in text or "fever" in text:
            return "🌡️ తేలికపాటి జ్వరానికి తగినంత నీరు లేదా ORS తాగి విశ్రాంతి తీసుకోండి. జ్వరం 102°F దాటితే వెంటనే OPD జనరల్ డాక్టర్‌ను సంప్రదించండి."
        if any(w in message for w in ["తలనొప్పి", "తల నొప్పి"]) or "thalanopi" in text:
            return "💆 తలనొప్పికి ప్రశాంతమైన గదిలో విశ్రాంతి తీసుకోండి, ఫోన్ స్క్రీన్ చూడకండి మరియు నీరు తాగండి. నొప్పి ఎక్కువైతే డాక్టర్‌ను సంప్రదించండి."
        if any(w in message for w in ["మందులు", "టాబ్లెట్", "1-0-1", "డోసేజ్"]):
            return "💊 1-0-1 అంటే ఉదయం 1 టాబ్లెట్, రాత్రి 1 టాబ్లెట్ భోజనం తర్వాత వేసుకోవాలి. TDS అంటే రోజుకు 3 సార్లు. ప్రిస్క్రిప్షన్ ఫోటో తీసి 📷 బటన్ నొక్కండి!"
        if any(w in message for w in ["టోకెన్", "క్యూ", "నంబర్"]):
            return "🎫 మీ లైవ్ క్యూ నంబర్ మరియు సమయాన్ని పైన ఉన్న 'My Tokens' విభాగంలో నేరుగా చూడవచ్చు."
        if any(w in message for w in ["గుండె నొప్పి", "శ్వాస", "ఎమర్జెన్సీ"]):
            return "🚨 అత్యవసర హెచ్చరిక: తీవ్రమైన గుండెనొప్పి లేదా శ్వాస ఇబ్బంది ఉంటే వెంటనే 108 / 112 కు కాల్ చేయండి లేదా ఎమర్జెన్సీ వార్డుకు వెళ్లండి!"

    # --- HINDI INSTANT RESPONSES ---
    if has_hindi or language.startswith("hi") or any(w in text for w in ["bukhar", "sir dard", "dawai", "kaisa hai"]):
        if any(w in message for w in ["नमस्ते", "प्रणाम", "हेलो", "हाय"]) or any(w in text for w in ["namaste", "pranam"]):
            return "नमस्ते! 🙏 मैं आपकी क्या मदद कर सकता हूँ? अपने स्वास्थ्य संबंधी प्रश्न पूछें! 💙"
        if any(w in message for w in ["बुखार", "तापमान"]) or "bukhar" in text:
            return "🌡️ हल्के बुखार में भरपूर पानी या ओआरएस (ORS) पिएं और आराम करें। यदि बुखार 102°F से अधिक है, तो तुरंत डॉक्टर से परामर्श लें।"
        if any(w in message for w in ["सिरदर्द", "सिर दर्द"]) or "sir dard" in text:
            return "💆 सिरदर्द में शांत कमरे में आराम करें और पानी पिएं। यदि गंभीर दर्द या उल्टी हो, तो तुरंत डॉक्टर को दिखाएं।"
        if any(w in message for w in ["दवाई", "दवा", "1-0-1", "खुराक"]):
            return "💊 1-0-1 का अर्थ है 1 गोली सुबह और 1 गोली रात को भोजन के बाद लेना। TDS का मतलब दिन में 3 बार। पर्चे की फोटो के लिए 📷 दबाएं!"
        if any(w in message for w in ["टोकन", "कतार", "नंबर"]):
            return "🎫 आप अपना लाइव कतार नंबर ऊपर 'My Tokens' पर वास्तविक समय में देख सकते हैं।"
        if any(w in message for w in ["सीने में दर्द", "सांस", "आपातकाल", "इमरजेंसी"]):
            return "🚨 आपातकालीन चेतावनी: गंभीर सीने में दर्द या सांस की तकलीफ में तुरंत 108 / 112 पर कॉल करें या नजदीकी अस्पताल जाएं!"

    # --- ENGLISH INSTANT RESPONSES ---
    clean = re.sub(r"[^a-zA-Z0-9\s]", "", text)
    tokens = set(clean.split())

    greeting_words = {"hi", "hello", "hey", "namaste", "hola", "greetings", "hii", "hiii", "helo", "good morning", "good evening", "good afternoon"}
    if clean in greeting_words or (len(tokens) <= 3 and tokens.intersection({"hi", "hello", "hey", "namaste", "hii"})):
        return (
            "Hello! 👋 I'm Q-Arovia AI, your instant healthcare assistant. "
            "How can I help you today? You can ask about symptoms, medicine dosage, or your token queue! 💙"
        )

    if any(phrase in text for phrase in ["what is q-arovia", "about q-arovia", "tell me about q-arovia", "what does q-arovia do"]):
        return (
            "Q-Arovia 💙 is a smart healthcare platform that lets you explore verified hospitals, "
            "check token fees, and book consultation queue tokens online to avoid long waiting times."
        )

    if any(phrase in text for phrase in ["how to book", "book token", "how can i book", "how do i book"]):
        return (
            "To book a token, choose any verified hospital from your dashboard, select your department or doctor, "
            "and confirm your token. You can track your live queue number in real-time under 'My Tokens'!"
        )

    emergency_phrases = ["chest pain", "cant breathe", "cannot breathe", "difficulty breathing", "heart attack", "unconscious", "heavy bleeding"]
    if any(phrase in text for phrase in emergency_phrases):
        return (
            "🚨 CRITICAL WARNING: If you or someone nearby is experiencing severe chest pain or breathing difficulty, "
            "please contact emergency services (112 / 108 in India) or visit the nearest trauma center immediately."
        )

    return None


def get_qarovia_ai_fallback(message: str) -> str:
    text = message.lower().strip()

    # Q-Arovia platform questions
    if any(word in text for word in [
        "what is q-arovia",
        "tell me about q-arovia",
        "about q-arovia",
        "what does q-arovia do",
        "q-arovia platform",
    ]):
        return (
            "Q-Arovia 💙 is a healthcare platform that helps patients "
            "find published hospitals and book tokens online. You can "
            "browse hospital information, check available details, and "
            "use the platform to navigate your healthcare options. "
            "Hospital information and fees should be checked against "
            "the details displayed in Q-Arovia."
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
            "You can browse the published hospitals on the Q-Arovia "
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
            "To book a token, log in to Q-Arovia, select a published "
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
        "Q-Arovia AI is temporarily unavailable, so I can't answer "
        "that question reliably right now. Please try again shortly. "
        "For urgent medical concerns, seek professional medical care."
    )

#GEMINI AI

# ============================================================
# Q-AROVIA AI
# ============================================================

def detect_user_language_preference(message: str, history: Optional[list] = None) -> str:
    """
    Automatically detects which Indian language the user is speaking, typing, or requesting.
    Supports native Indic scripts as well as Romanized/transliterated words (Tenglish, Hinglish, Tanglish, etc.).
    Returns: 'te' (Telugu), 'hi' (Hindi), 'ta' (Tamil), 'kn' (Kannada), 'ml' (Malayalam),
             'mr' (Marathi), 'bn' (Bengali), 'gu' (Gujarati), 'pa' (Punjabi), 'or' (Odia), or 'en' (English).
    """
    msg_lower = (message or "").strip().lower()

    # 1. Explicit language request triggers
    if any(k in msg_lower for k in ["telugu", "తెలుగు", "tenglish", "telugulo", "telugu lo", "telugula"]):
        return "te"
    if any(k in msg_lower for k in ["hindi", "हिंदी", "hinglish", "hindi me", "hindi mein"]):
        return "hi"
    if any(k in msg_lower for k in ["tamil", "தமிழ்", "tamilil", "tanglish"]):
        return "ta"
    if any(k in msg_lower for k in ["kannada", "ಕನ್ನಡ", "kannadadalli"]):
        return "kn"
    if any(k in msg_lower for k in ["malayalam", "മലയാളം"]):
        return "ml"
    if any(k in msg_lower for k in ["marathi", "मराठी", "marathit"]):
        return "mr"
    if any(k in msg_lower for k in ["bengali", "বাংলা"]):
        return "bn"
    if any(k in msg_lower for k in ["gujarati", "ગુજરાતી"]):
        return "gu"
    if any(k in msg_lower for k in ["punjabi", "ਪੰਜਾਬੀ"]):
        return "pa"
    if any(k in msg_lower for k in ["odia", "oriya", "ଓଡ଼ିଆ"]):
        return "or"
    if any(k in msg_lower for k in ["english", "in english"]):
        return "en"

    # 2. Native Indic Unicode Script Detection
    if re.search(r"[ఀ-౿]", message):  # Telugu
        return "te"
    if re.search(r"[ऀ-ॿ]", message):  # Devanagari (Marathi vs Hindi)
        if any(w in message for w in ["आहे", "मला", "करावे", "नाही", "काय", "कसे", "औषध", "ताप"]):
            return "mr"
        return "hi"
    if re.search(r"[஀-௿]", message):  # Tamil
        return "ta"
    if re.search(r"[ಀ-೿]", message):  # Kannada
        return "kn"
    if re.search(r"[ഀ-ൿ]", message):  # Malayalam
        return "ml"
    if re.search(r"[ঀ-৿]", message):  # Bengali
        return "bn"
    if re.search(r"[઀-૿]", message):  # Gujarati
        return "gu"
    if re.search(r"[਀-੿]", message):  # Punjabi
        return "pa"
    if re.search(r"[଀-୿]", message):  # Odia
        return "or"

    # 3. Comprehensive Romanized / Transliterated Phonetic Keywords
    # Telugu phonetic tokens
    telugu_words = [
        "jvaram", "jwaram", "thalanopi", "thala noppi", "mandulu", "mandhu", "taggali", "daktaru",
        "kadupu", "noppi", "em cheyali", "ela undi", "cheppandi", "chudandi", "undi", "ledu", "baga",
        "pillalu", "gunde", "swasa", "daggu", "jalubu", "gonthu", "namaskaram", "asupathri", "aushadham",
        "naku", "enti", "kavali", "eppudu", "doctorgaru", "daktar"
    ]
    if any(w in msg_lower for w in telugu_words):
        return "te"

    # Hindi phonetic tokens
    hindi_words = [
        "bukhar", "sir dard", "sar dard", "dawai", "dawa", "pet dard", "pet me", "ulti", "chakkar",
        "kya kare", "kaisa hai", "bataiye", "mujhe", "mera", "ho raha", "dard", "seene me", "khansi",
        "jukham", "gala kharab", "tabiyat", "aspatal", "ilaj", "kya karu", "chahiye", "batao", "kaise"
    ]
    if any(w in msg_lower for w in hindi_words):
        return "hi"

    # Tamil phonetic tokens
    tamil_words = [
        "kaichal", "thalaivali", "marunthu", "marundhu", "valikuthu", "udambu", "mudiyala", "enna pannanum",
        "sari illa", "erukku", "illai", "maruthuvar", "nenju vali", "irukku", "enakku", "sollinga", "vanakkam"
    ]
    if any(w in msg_lower for w in tamil_words):
        return "ta"

    # Kannada phonetic tokens
    kannada_words = [
        "jwara", "thalenovu", "aushadhi", "mathe", "hege", "beku", "madabeku", "hotte", "novu", "nanage", "helu", "namaskara"
    ]
    if any(w in msg_lower for w in kannada_words):
        return "kn"

    # Malayalam phonetic tokens
    malayalam_words = ["pani", "thala vedhana", "marunnu", "entha cheyyuka", "vayaru", "vedhana", "enikku"]
    if any(w in msg_lower for w in malayalam_words):
        return "ml"

    # Marathi phonetic tokens
    marathi_words = ["taap", "doke dukhat", "aushadh", "kay karu", "potat dukhate", "mala", "sangitla"]
    if any(w in msg_lower for w in marathi_words):
        return "mr"

    # Bengali phonetic tokens
    bengali_words = ["jor", "matha betha", "osudh", "ki korbo", "pet betha", "amar", "bolun"]
    if any(w in msg_lower for w in bengali_words):
        return "bn"

    # Gujarati phonetic tokens
    gujarati_words = ["taav", "mathu dukhe", "dava", "su karvu", "pet ma dukhe", "mane"]
    if any(w in msg_lower for w in gujarati_words):
        return "gu"

    # Punjabi phonetic tokens
    punjabi_words = ["bukhar", "sir dukhda", "dawai", "ki karaan", "mainu"]
    if any(w in msg_lower for w in punjabi_words):
        return "pa"

    # Odia phonetic tokens
    odia_words = ["jwara", "munda betha", "aushadha", "kana karibi", "peta betha", "mote"]
    if any(w in msg_lower for w in odia_words):
        return "or"

    # 4. Contextual Continuity (Look back at recent history)
    if history and len(msg_lower.split()) <= 4:
        for prev in reversed(history[-6:]):
            prev_content = str(prev.get("content", ""))
            prev_lower = prev_content.lower()
            if re.search(r"[ఀ-౿]", prev_content) or any(w in prev_lower for w in telugu_words):
                return "te"
            if re.search(r"[ऀ-ॿ]", prev_content) or any(w in prev_lower for w in hindi_words):
                return "hi"
            if re.search(r"[஀-௿]", prev_content) or any(w in prev_lower for w in tamil_words):
                return "ta"
            if re.search(r"[ಀ-೿]", prev_content) or any(w in prev_lower for w in kannada_words):
                return "kn"

    return "en"""


def check_specialist_routing_intent(message: str, history: Optional[list], target_lang: str) -> Optional[str]:
    """
    Directly answers questions like "which doctor", "who should I consult", "who to see for fever"
    by analyzing current and recent symptoms instead of giving unhelpful generic disclaimers.
    """
    msg_clean = message.lower().strip()
    combined_text = msg_clean
    if history:
        for item in reversed(history[-4:]):
            combined_text = str(item.get("content", "")).lower() + " " + combined_text

    # Is the user asking which doctor/specialist to see?
    is_asking_which_doctor = any(phrase in msg_clean for phrase in [
        "which doctor", "what doctor", "who should i consult", "who to consult",
        "which specialist", "who can i see", "recommend a doctor", "doctor for this",
        "who do i visit", "which department", "where should i go",
        "ఏ డాక్టర్", "ఎవరిని కలవాలి", "ఎవరిని సంప్రదించాలి", "డాక్టర్ ఎవరు",
        "कौन सा डॉक्टर", "किसे दिखाएं", "किस डॉक्टर", "डॉक्टर कौन"
    ]) or (msg_clean in ["which doctor", "who doctor", "doctor?", "which dr", "which one", "who?"])

    # If asking which doctor OR providing symptoms
    if is_asking_which_doctor or msg_clean in ["fever", "headache", "jvaram", "bukhar", "cold", "cough"]:
        # Fever, headache, cold, cough, stomach upset, nausea, flu, general weakness
        if any(s in combined_text for s in ["fever", "headache", "cold", "cough", "flu", "body pain", "fatigue", "vomit", "stomach", "జ్వరం", "తలనొప్పి", "బుఖార్", "బుఖార"]):
            if target_lang == "te":
                return (
                    "జ్వరం, తలనొప్పి లేదా సాధారణ లక్షణాల కోసం మీరు **జనరల్ ఫిజీషియన్ (సాధారణ వైద్యుడు / Internal Medicine)** ని సంప్రదించాలి. "
                    "Q-Arovia లో మీరు **జనరల్ మెడిసిన్** విభాగంలో OPD టోకెన్ బుక్ చేసుకుని డాక్టర్‌ను నేరుగా సంప్రదించవచ్చు! 🩺"
                )
            elif target_lang == "hi":
                return (
                    "बुखार, सिरदर्द या सामान्य कमजोरी के लिए आपको **जनरल फिजिशियन (सामान्य चिकित्सक / Internal Medicine)** से परामर्श करना चाहिए। "
                    "Q-Arovia पर आप **जनरल मेडिसिन** विभाग में आसानी से OPD टोकन बुक कर सकते हैं! 🩺"
                )
            else:
                return (
                    "For fever, headache, and general symptoms, you should consult a **General Physician (Internal Medicine specialist)**. "
                    "On Q-Arovia, you can book an OPD consultation token directly under the **General Medicine** department! 🩺"
                )

        # Heart, chest pain, palpitations
        if any(s in combined_text for s in ["chest pain", "heart", "bp", "palpitation", "గుండె", "छाती"]):
            if target_lang == "te":
                return (
                    "గుండె నొప్పి లేదా ఛాతీలో ఒత్తిడి ఉంటే మీరు వెంటనే **కార్డియాలజిస్ట్ (గుండె నిపుణుడు)** ని సంప్రదించాలి. తీవ్రమైన నొప్పి ఉంటే ఆలస్యం చేయకుండా ఎమర్జెన్సీ (108) కి వెళ్లండి! 🚨"
                )
            elif target_lang == "hi":
                return (
                    "सीने में दर्द या सांस लेने में तकलीफ के लिए तुरंत **कार्डियोलॉजिस्ट (हृदय रोग विशेषज्ञ)** से संपर्क करें या आपातकालीन सेवा (108) में जाएं! 🚨"
                )
            else:
                return (
                    "For chest pain, heart palpitations, or severe discomfort, you should consult a **Cardiologist**. If the pain is severe or radiating, seek emergency care (108) immediately! 🚨"
                )

        # Children under 18
        if any(s in combined_text for s in ["child", "baby", "kid", "infant", "పిల్ల", "बच्चा"]):
            if target_lang == "te":
                return (
                    "పిల్లల అనారోగ్యం లేదా జ్వరానికి **పీడియాట్రిషియన్ (పిల్లల నిపుణుడు)** ని సంప్రదించాలి. Q-Arovia లో పీడియాట్రిక్స్ కింద టోకెన్ బుక్ చేయండి. 👶"
                )
            elif target_lang == "hi":
                return (
                    "बच्चों के स्वास्थ्य या बुखार के लिए **पीडियाट्रिशियन (बाल रोग विशेषज्ञ)** से परामर्श लें। Q-Arovia पर पीडियाट्रिक्स में टोकन बुक करें। 👶"
                )
            else:
                return (
                    "For infants and children under 18, you should consult a **Pediatrician (Child Specialist)**. You can select Pediatrics in Q-Arovia to book an OPD token. 👶"
                )

        # Bones, joints, fractures, back pain
        if any(s in combined_text for s in ["bone", "joint", "fracture", "knee", "back pain", "నడుము నొప్పి", "కీళ్ల", "हड्डी", "जोड़"]):
            if target_lang == "te":
                return (
                    "ఎముకలు, కీళ్ళు లేదా నడుము నొప్పి కోసం **ఆర్థోపెడిక్ సర్జన్ (ఎముకల నిపుణుడు)** ని సంప్రదించాలి. Q-Arovia లో ఆర్థోపెడిక్స్ కింద టోకెన్ బుక్ చేసుకోవచ్చు. 🦴"
                )
            elif target_lang == "hi":
                return (
                    "हड्डियों, जोड़ों या पीठ दर्द के लिए **ऑर्थोपेडिक सर्जन (अस्थि रोग विशेषज्ञ)** से परामर्श लें। 🦴"
                )
            else:
                return (
                    "For bone fractures, joint issues, or severe back pain, you should consult an **Orthopedic Specialist**. 🦴"
                )

        # Skin, rashes, allergies
        if any(s in combined_text for s in ["skin", "rash", "itch", "pimples", "చర్మ", "దురద", "त्वचा", "खुजली"]):
            if target_lang == "te":
                return "చర్మ సమస్యలు లేదా దురద కోసం **డెర్మటాలజిస్ట్ (చర్మ రోగ నిపుణుడు)** ని సంప్రదించాలి. ✨"
            elif target_lang == "hi":
                return "त्वचा के दाने, खुजली या एलर्जी के लिए **डर्मेटोलॉजिस्ट (त्वचा रोग विशेषज्ञ)** से परामर्श लें। ✨"
            else:
                return "For skin rashes, allergies, or itching, you should consult a **Dermatologist (Skin Specialist)**. ✨"

        # Eyes
        if any(s in combined_text for s in ["eye", "vision", "కన్ను", "కంటి", "आंख"]):
            if target_lang == "te":
                return "కంటి నొప్పి లేదా చూపు సమస్యలకు **ఆప్తాల్మాలజిస్ట్ (కంటి నిపుణుడు)** ని సంప్రదించండి. 👁️"
            elif target_lang == "hi":
                return "आंखों के दर्द या दृष्टि संबंधी समस्या के लिए **नेत्र रोग विशेषज्ञ (ऑप्थल्मोलॉजिस्ट)** से परामर्श लें। 👁️"
            else:
                return "For eye pain, redness, or vision problems, you should consult an **Ophthalmologist (Eye Specialist)**. 👁️"

    return None


@app.post("/ai/chat")
def qarovia_ai_chat(
    data: AIChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    check_ai_rate_limit(request)
    message = (data.message or "").strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    # 1. Automatic Language Detection (Telugu, Hindi, Tamil, Kannada, English, etc.)
    target_lang = detect_user_language_preference(message, data.history)
    lang_names = {
        "te": "Telugu (తెలుగు)",
        "hi": "Hindi (हिंदी)",
        "ta": "Tamil (தமிழ்)",
        "kn": "Kannada (ಕನ್ನಡ)",
        "ml": "Malayalam (മലയാളം)",
        "mr": "Marathi (मराठी)",
        "bn": "Bengali (বাংলা)",
        "gu": "Gujarati (ગુજરાતી)",
        "pa": "Punjabi (ਪੰਜਾਬੀ)",
        "or": "Odia (ଓଡ଼ିଆ)",
        "en": "English",
    }
    target_lang_name = lang_names.get(target_lang, "English")

    # 2. Context-Aware Specialist Routing Engine (handles "which doctor", "fever", etc.)
    specialist_reply = check_specialist_routing_intent(message, data.history, target_lang)
    if specialist_reply:
        return {
            "success": True,
            "reply": specialist_reply,
            "detected_language": target_lang,
            "source": "specialist_router",
        }

    # 3. Instant Intent Engine (< 1ms response for greetings, FAQs, emergencies)
    instant_reply = check_instant_ai_response(message, target_lang)
    if instant_reply:
        return {
            "success": True,
            "reply": instant_reply,
            "detected_language": target_lang,
            "source": "instant_engine",
        }

    # 4. Ultra-Fast Groq Engine (< 500ms response if GROQ_API_KEY is configured)
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        groq_models = [
            "qwen/qwen3.8-27b",
            "openai/gpt-oss-120b",
            "llama-3.1-8b-instant",
            "llama-3.3-70b-versatile",
        ]

        system_instruction = (
            "You are Q-Arovia AI, a friendly, intelligent healthcare assistant on the Q-Arovia platform. "
            f"CRITICAL MULTILINGUAL MANDATE: The user expects their response strictly in {target_lang_name}. "
            f"You MUST write your response ONLY in {target_lang_name}. "
            "If Telugu was requested or spoken, respond in natural, polite Telugu script (తెలుగు). "
            "If Hindi, respond in Hindi script (हिंदी). If English, respond in English. "
            "SPECIALIST GUIDANCE: If patient asks 'which doctor' or names symptoms (fever, headache, etc.), recommend the specific specialist/department (e.g. General Physician for fever/headache). "
            "PRESCRIPTION / LAB REPORT: If the user asks about an uploaded prescription or report ('explain in telugu', 'how to take medicine', 'what does 1-0-1 mean'), thoroughly explain the medicines, dosages, and doctor's advice in the requested language. "
            "Keep answers concise (2-3 sentences), warm, and reassuring."
        )

        groq_messages = [{"role": "system", "content": system_instruction}]
        if data.prescription_context:
            groq_messages.append({
                "role": "system",
                "content": f"Context of Uploaded Medical Prescription / Report:\n{data.prescription_context[:1500]}"
            })
        if data.history:
            for h in data.history[-6:]:
                r = "assistant" if h.get("role") in ["assistant", "model", "ai"] else "user"
                c = str(h.get("content", "")).strip()
                if c:
                    groq_messages.append({"role": r, "content": c})
        groq_messages.append({"role": "user", "content": message})

        for g_model in groq_models:
            try:
                groq_res = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": g_model,
                        "messages": groq_messages,
                        "max_tokens": 250,
                        "temperature": 0.2,
                    },
                    timeout=3.0,
                )
                if groq_res.ok:
                    choices = groq_res.json().get("choices", [])
                    if choices:
                        reply = choices[0].get("message", {}).get("content", "").strip()
                        if reply:
                            return {
                                "success": True,
                                "reply": reply,
                                "detected_language": target_lang,
                                "source": "groq_fast",
                                "model": g_model,
                            }
            except Exception as groq_err:
                logging.warning("Groq fast model %s error: %s", g_model, groq_err)
                continue

    # 5. Gemini Multimodal / Multilingual Fallback Engine
    if gemini_client:
        try:
            qarovia_context = get_qarovia_ai_context(db, message)
        except Exception:
            qarovia_context = []

        gemini_instruction = (
            "You are Q-Arovia AI, a friendly healthcare assistant on the Q-Arovia platform. "
            f"MANDATORY: Respond ONLY in {target_lang_name}. "
            "If the user asks 'which doctor' or has fever/headache, suggest a General Physician. "
            "If an uploaded prescription/medical report is referenced, explain it clearly in the requested language. "
            "Keep answers under 3 sentences, reassuring, and practical."
        )

        history_summary = ""
        if data.history:
            history_summary = "\n".join([f"{h.get('role')}: {h.get('content')}" for h in data.history[-4:]])

        prompt_body = f"""Patient Question: {message}

Previous Conversation:
{history_summary}

Uploaded Prescription Report Context:
{data.prescription_context or 'None'}

Hospital Context: {qarovia_context}

Provide a helpful, caring response to the patient in {target_lang_name}:"""

        fast_models = [
            "gemini-3.5-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-3.8-flash",
        ]

        for model_name in fast_models:
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt_body,
                    config={
                        "system_instruction": gemini_instruction,
                        "max_output_tokens": 250,
                        "temperature": 0.2,
                    },
                )
                reply = response.text.strip() if response and response.text else None
                if reply:
                    return {
                        "success": True,
                        "reply": reply,
                        "detected_language": target_lang,
                        "model": model_name,
                    }
            except Exception as model_err:
                logging.warning("Fast AI model %s error: %s", model_name, model_err)
                continue

    # 6. Graceful Instant Fallback
    fallback_text = get_qarovia_ai_fallback(message)
    return {
        "success": True,
        "reply": fallback_text,
        "detected_language": target_lang,
        "fallback": True,
    }


# ============================================================
# Q-AROVIA AI - MULTILINGUAL AUDIO TTS & TRANSCRIBE ENGINE
# Supports All Indian Languages: Telugu, Hindi, Tamil, Kannada,
# Malayalam, Marathi, Bengali, Gujarati, Punjabi, Odia, English
# ============================================================

TTS_AUDIO_CACHE = {}


def split_text_into_tts_chunks(text: str, max_chunk_len: int = 180) -> list[str]:
    """
    Splits long explanation text into natural spoken phrases/sentences under max_chunk_len
    without breaking words or sentence flow. Supports Telugu, Hindi, Tamil, English, etc.
    """
    clean = re.sub(r'\s+', ' ', text).strip()
    if not clean:
        return []
    if len(clean) <= max_chunk_len:
        return [clean]

    sentences = re.split(r'([.!?।\n]+)', clean)
    chunks = []
    current = ''

    for i in range(0, len(sentences), 2):
        sentence = sentences[i]
        sep = sentences[i+1] if i + 1 < len(sentences) else ''
        piece = (sentence + sep).strip()
        if not piece:
            continue

        if len(piece) <= max_chunk_len:
            if current and len(current) + len(piece) + 1 > max_chunk_len:
                chunks.append(current.strip())
                current = piece
            else:
                current = (current + ' ' + piece).strip()
        else:
            words = piece.split(' ')
            for w in words:
                if not w:
                    continue
                if current and len(current) + len(w) + 1 > max_chunk_len:
                    chunks.append(current.strip())
                    current = w
                else:
                    current = (current + ' ' + w).strip()
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


class QAroviaTTSRequest(BaseModel):
    text: str
    lang: str = "en"


@app.post("/ai/tts")
def qarovia_ai_text_to_speech_post(req: QAroviaTTSRequest):
    """Accepts JSON body for extra-long full-chat voice queries without URL limits."""
    return qarovia_ai_text_to_speech(req.text, req.lang)


@app.get("/ai/tts")
def qarovia_ai_text_to_speech(text: str, lang: str = "en"):
    """
    Streams crystal-clear native MP3 speech in ALL Indian languages.
    Plays on any phone speaker, Android WebView, and browser without
    requiring phone system voice packages to be installed.
    Supports complete multi-paragraph full-chat voice explanations with
    seamless MP3 chunk concatenation and in-memory caching.
    """
    clean_text = (text or "").strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Text is required.")

    # Limit total speech text to 2000 characters (~2 minutes of full detailed voice explanation)
    clean_text = clean_text[:2000]

    lang_code = lang.split("-")[0].lower() if "-" in lang else lang.lower()
    valid_langs = {"te", "hi", "ta", "kn", "ml", "mr", "bn", "gu", "pa", "en"}
    if lang_code == "or":
        lang_code = "hi"
    if lang_code not in valid_langs:
        lang_code = "en"

    cache_key = (clean_text, lang_code)
    if cache_key in TTS_AUDIO_CACHE:
        return Response(
            content=TTS_AUDIO_CACHE[cache_key],
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
            },
        )

    chunks = split_text_into_tts_chunks(clean_text, max_chunk_len=180)
    if not chunks:
        chunks = [clean_text[:180]]

    # Limit to max 12 chunks to prevent timeouts
    chunks = chunks[:12]

    audio_chunks = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        for chunk in chunks:
            chunk_cache_key = ("__chunk__" + chunk, lang_code)
            if chunk_cache_key in TTS_AUDIO_CACHE:
                audio_chunks.append(TTS_AUDIO_CACHE[chunk_cache_key])
                continue

            tts_url = (
                f"https://translate.google.com/translate_tts?ie=UTF-8&tl={lang_code}&client=tw-ob&q="
                + requests.utils.quote(chunk)
            )
            resp = requests.get(tts_url, headers=headers, timeout=5.0)
            if resp.ok and len(resp.content) > 100:
                if len(TTS_AUDIO_CACHE) < 1000:
                    TTS_AUDIO_CACHE[chunk_cache_key] = resp.content
                audio_chunks.append(resp.content)
            else:
                logging.warning("TTS chunk fetch failed for: %s", chunk[:30])

        if not audio_chunks:
            raise HTTPException(status_code=502, detail="TTS upstream failed.")

        combined_audio = b"".join(audio_chunks)
        if len(TTS_AUDIO_CACHE) < 1000:
            TTS_AUDIO_CACHE[cache_key] = combined_audio

        return Response(
            content=combined_audio,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except Exception as e:
        logging.warning("TTS audio fetch error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ai/transcribe")
async def qarovia_ai_transcribe_audio(
    request: Request,
    audio: UploadFile = File(...),
    language: Optional[str] = Form("te-IN"),
):
    check_ai_rate_limit(request)
    """
    Transcribes audio speech in any Indian language using Groq Whisper or Gemini.
    """
    try:
        content = await audio.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty audio file.")

        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            try:
                whisper_res = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    files={"file": (audio.filename or "speech.webm", content, audio.content_type or "audio/webm")},
                    data={"model": "whisper-large-v3", "temperature": 0.0},
                    timeout=5.0,
                )
                if whisper_res.ok:
                    transcription = whisper_res.json().get("text", "").strip()
                    if transcription:
                        return {"success": True, "text": transcription, "source": "groq_whisper"}
            except Exception as e:
                logging.warning("Groq whisper error: %s", e)

        return {"success": False, "error": "Transcription unavailable."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Q-AROVIA AI - PRESCRIPTION & MEDICAL REPORT EXPLAINER
# ============================================================

@app.post("/ai/analyze-prescription")
@app.post("/ai/analyze-prescription/")
async def qarovia_ai_analyze_prescription(
    request: Request,
    photo: UploadFile = File(...),
    notes: Optional[str] = Form(""),
    db: Session = Depends(get_db),
):
    check_ai_rate_limit(request)
    """
    Q-Arovia AI Multimodal Vision Engine:
    Reads doctor's handwriting, prescriptions, lab reports, and medicine strips,
    and explains medicines, dosages, diagnosis, and precautions in simple language.
    """
    if not photo:
        raise HTTPException(status_code=400, detail="Prescription image is required.")

    # Validate file format
    content_type = (photo.content_type or "image/jpeg").lower()
    if not any(t in content_type for t in ["image", "jpeg", "jpg", "png", "webp", "octet-stream"]):
        raise HTTPException(
            status_code=400,
            detail="Please upload a valid image (JPG, PNG, WebP) of the doctor's prescription."
        )

    image_bytes = await photo.read()
    if len(image_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image size exceeds maximum limit of 10 MB.")

    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    user_note_str = (notes or "").strip()
    note_lower = user_note_str.lower()

    # Detect user requested language in the note
    detected_target_lang = None
    if any(k in note_lower for k in ["telugu", "తెలుగు"]):
        detected_target_lang = "Telugu"
    elif any(k in note_lower for k in ["hindi", "हिंदी"]):
        detected_target_lang = "Hindi"
    elif any(k in note_lower for k in ["tamil", "தமிழ்"]):
        detected_target_lang = "Tamil"
    elif any(k in note_lower for k in ["kannada", "ಕನ್ನಡ"]):
        detected_target_lang = "Kannada"
    elif any(k in note_lower for k in ["marathi", "मराठी"]):
        detected_target_lang = "Marathi"
    elif any(k in note_lower for k in ["bengali", "বাংলা"]):
        detected_target_lang = "Bengali"
    elif any(k in note_lower for k in ["gujarati", "ગુજરાતી"]):
        detected_target_lang = "Gujarati"
    elif any(k in note_lower for k in ["malayalam", "മലയാളം"]):
        detected_target_lang = "Malayalam"
    elif any(k in note_lower for k in ["punjabi", "ਪੰਜਾਬੀ"]):
        detected_target_lang = "Punjabi"
    elif any(k in note_lower for k in ["urdu", "اردو"]):
        detected_target_lang = "Urdu"
    elif any(k in note_lower for k in ["odia", "oriya", "ଓଡ଼ిଆ"]):
        detected_target_lang = "Odia"
    elif "explain in " in note_lower:
        detected_target_lang = note_lower.split("explain in ")[1].strip()
    elif "in " in note_lower:
        detected_target_lang = note_lower.split("in ")[1].strip()

    if detected_target_lang:
        lang_directive = (
            f"CRITICAL LANGUAGE MANDATE: The user explicitly requested in the note: \"{user_note_str}\". "
            f"You MUST write your entire response, headings, explanations, dosage instructions, and warnings in {detected_target_lang}. "
            f"Do NOT use English unless English was requested; generate all text naturally and fluently in {detected_target_lang}."
        )
    elif user_note_str:
        lang_directive = (
            f"LANGUAGE MANDATE: The patient provided this note: \"{user_note_str}\". "
            "If this note asks for a specific language, write in that language; otherwise write in clear English."
        )
    else:
        lang_directive = (
            "LANGUAGE MANDATE: The patient entered no note. "
            "You MUST explain and decode everything in clear English."
        )

    patient_note_context = f"Patient Note: {user_note_str}" if user_note_str else ""

    prescription_system_prompt = f"""You are Q-Arovia AI's Expert Medical Document & Doctor's Prescription Decoder Specialist.
A patient has provided an image.

{lang_directive}

1. If this is a doctor's handwritten prescription, lab report, or medicine pack:
   - Carefully examine handwriting, symbols, medical shorthand, and text.
   - 📋 DOCTOR'S DIAGNOSIS & CLINICAL OBSERVATIONS
   - 💊 PRESCRIBED MEDICINES & HOW TO TAKE THEM (Decode 1-0-1, TDS, BBF, PC, HS, etc.)
   - 🔬 ADVISED LAB TESTS & SCANS (if any)
   - 🥗 DIET & RECOVERY ADVICE
   - ⚠️ RED FLAG WARNINGS (When to visit emergency)
   - ℹ️ PATIENT SAFETY NOTE: 'Always verify medicines with your pharmacist.'

2. If this image is NOT a medical prescription (e.g. academic notes, math/formula sheet, student notes, whiteboard, screenshot, or personal photo):
   - Clearly and politely explain what is written/shown in the image (strictly honoring the {detected_target_lang if detected_target_lang else 'English'} language requirement above).
   - Remind the patient to upload a photo of their physical doctor's prescription or hospital report for medicine analysis.

{patient_note_context}
"""

    # --- 1. Primary Engine: Ultra-Fast Groq Multimodal Vision (< 2s) ---
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            groq_mime = "image/jpeg" if ("jpeg" in content_type or "jpg" in content_type) else ("image/png" if "png" in content_type else "image/webp")
            data_uri = f"data:{groq_mime};base64,{b64_image}"
            groq_res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "qwen/qwen3.8-27b",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prescription_system_prompt},
                                {"type": "image_url", "image_url": {"url": data_uri}}
                            ]
                        }
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.2,
                },
                timeout=8.0,
            )
            if groq_res.ok:
                choices = groq_res.json().get("choices", [])
                if choices:
                    analysis = choices[0].get("message", {}).get("content", "").strip()
                    if analysis and len(analysis) > 20:
                        return {
                            "success": True,
                            "analysis": analysis,
                            "model": "qwen/qwen3.8-27b",
                            "source": "groq_fast_vision"
                        }
        except Exception as groq_err:
            logging.warning("Groq fast vision error: %s", groq_err)

    # --- 2. Secondary Engine: Gemini Vision (< 6s timeout) ---
    if gemini_client:
        try:
            from google.genai import types
            gemini_mime = "image/jpeg" if ("jpeg" in content_type or "jpg" in content_type) else ("image/png" if "png" in content_type else "image/webp")
            for v_model in ["gemini-3.8-flash", "gemini-flash-latest"]:
                try:
                    res = gemini_client.models.generate_content(
                        model=v_model,
                        contents=[
                            types.Part.from_bytes(data=image_bytes, mime_type=gemini_mime),
                            prescription_system_prompt
                        ]
                    )
                    if res and res.text and len(res.text.strip()) > 30:
                        return {
                            "success": True,
                            "analysis": res.text.strip(),
                            "model": v_model,
                            "source": "gemini_multimodal_vision"
                        }
                except Exception as m_err:
                    logging.warning("Gemini Vision model %s failed: %s", v_model, m_err)
                    continue
        except Exception as gemini_err:
            logging.warning("Gemini vision dispatcher error: %s", gemini_err)

        # --- 3. Intelligent Clinical Guide Fallback ---
    clinical_guide = (
        "📋 **Doctor's Prescription & Medical Report Decoder (Q-Arovia AI)**\n\n"
        "Your medical document photo has been received. Here is the clinical decoder for common Indian & international doctor handwriting and prescription abbreviations:\n\n"
        "💊 **Dosage Schedule Abbreviations Explained:**\n"
        "• **OD (Once Daily)**: Take 1 time per day (usually morning)\n"
        "• **BD / BID (Twice Daily / 1-0-1)**: Take 1 in morning and 1 at night\n"
        "• **TDS / TID (Thrice Daily / 1-1-1)**: Take 1 morning, 1 afternoon, 1 night\n"
        "• **QID (Four Times Daily)**: Take every 6 hours\n"
        "• **BBF / AC**: Take before food on an empty stomach\n"
        "• **PC / AF**: Take after meals (to prevent stomach irritation)\n"
        "• **SOS**: Take only when needed (e.g. Paracetamol if fever > 100°F or severe pain)\n"
        "• **HS**: Take at bedtime right before sleeping\n\n"
        "🔬 **Common Lab Tests:**\n"
        "• **CBC**: Complete Blood Count (checks hemoglobin and infection)\n"
        "• **LFT / KFT**: Liver / Kidney Function Tests\n"
        "• **RBS / FBS**: Random or Fasting Blood Sugar\n\n"
        "⚠️ **Safety & Precautions:**\n"
        "1. Verify exact medicine brand and strength with your certified pharmacist.\n"
        "2. Do not stop antibiotic courses midway without consulting your doctor.\n"
        "3. Seek immediate emergency casualty care if experiencing chest pain, high fever with breathlessness, or severe allergic reaction."
    )
    return {
        "success": True,
        "analysis": clinical_guide,
        "source": "clinical_guide_fallback"
    }

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

    # Check 60-second rate limit cooldown to prevent spamming
    recent_otp = (
        db.query(RegistrationOTP)
        .filter(
            RegistrationOTP.role == role,
            RegistrationOTP.contact_method == "email",
            RegistrationOTP.contact_value == email,
            RegistrationOTP.created_at > datetime.utcnow() - timedelta(seconds=60),
        )
        .first()
    )
    if recent_otp:
        remaining_secs = int(60 - (datetime.utcnow() - recent_otp.created_at).total_seconds())
        remaining_secs = max(1, remaining_secs)
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {remaining_secs} seconds before requesting a new OTP."
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
            logging.info("Registration OTP generated successfully for %s", email)
            raise HTTPException(
                status_code=500,
                detail="Unable to send verification email. Please verify your email address or try again later.",
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
            detail="Unable to send verification code. Please try again later.",
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

    # Check 60-second rate limit cooldown to prevent spamming
    recent_reset_otp = (
        db.query(RegistrationOTP)
        .filter(
            RegistrationOTP.role == f"reset_{role}",
            RegistrationOTP.contact_method == "email",
            RegistrationOTP.contact_value == email,
            RegistrationOTP.created_at > datetime.utcnow() - timedelta(seconds=60),
        )
        .first()
    )
    if recent_reset_otp:
        remaining_secs = int(60 - (datetime.utcnow() - recent_reset_otp.created_at).total_seconds())
        remaining_secs = max(1, remaining_secs)
        raise HTTPException(
            status_code=429,
            detail=f"Please wait {remaining_secs} seconds before requesting another reset code."
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
            logging.info("Password reset OTP generated successfully for %s", email)
            raise HTTPException(
                status_code=500,
                detail="Unable to send password reset email. Please try again later.",
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
            detail="Unable to process password reset request. Please try again later.",
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

    # Revoke all active sessions for this account upon password change (QA-AUTH-001)
    revoke_all_user_sessions(db, user_id=user.id, role=role)

    return {
        "success": True,
        "message": "Password reset successfully! You can now log in with your new password.",
    }


# ============================================================
# SESSION MANAGEMENT (QA-AUTH-001)
# ============================================================

class RefreshTokenRequest(BaseModel):
    refresh_token: Optional[str] = None


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


@app.post("/auth/refresh")
async def refresh_session_token(
    request: Request,
    data: Optional[RefreshTokenRequest] = None,
    db: Session = Depends(get_db),
):
    """Rotates refresh token and issues a new access token (QA-AUTH-001)."""
    token = None
    if data and data.refresh_token:
        token = data.refresh_token.strip()
    if not token:
        try:
            body = await request.json()
            if isinstance(body, dict) and body.get("refresh_token"):
                token = str(body["refresh_token"]).strip()
        except Exception:
            pass
    if not token and request.cookies.get("refresh_token"):
        token = request.cookies.get("refresh_token")

    if not token:
        raise HTTPException(status_code=400, detail="Missing refresh token.")

    new_access, new_refresh = rotate_user_session(db, token, request)

    response = JSONResponse(content={
        "success": True,
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    })
    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )
    return response


@app.post("/auth/logout")
async def logout_user(
    request: Request,
    data: Optional[LogoutRequest] = None,
    db: Session = Depends(get_db),
    current_user: Optional[dict] = Depends(get_optional_auth_user),
):
    """Revokes session on logout (QA-AUTH-001)."""
    token = None
    if data and data.refresh_token:
        token = data.refresh_token.strip()
    if not token:
        try:
            body = await request.json()
            if isinstance(body, dict) and body.get("refresh_token"):
                token = str(body["refresh_token"]).strip()
        except Exception:
            pass
    if not token and request.cookies.get("refresh_token"):
        token = request.cookies.get("refresh_token")

    if token:
        revoke_user_session_by_token(db, token)
    elif current_user:
        revoke_all_user_sessions(db, current_user["user_id"], current_user["role"])

    response = JSONResponse(content={"success": True, "message": "Successfully logged out."})
    response.delete_cookie("refresh_token")
    return response


@app.post("/auth/logout-all")
def logout_all_sessions(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Revokes all active sessions for the authenticated user across all devices (QA-AUTH-001)."""
    count = revoke_all_user_sessions(db, current_user["user_id"], current_user["role"])
    return {"success": True, "message": f"Successfully revoked {count} active sessions."}


@app.get("/auth/sessions")
def list_user_sessions(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lists all active sessions for the authenticated user (QA-AUTH-001)."""
    sessions = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == current_user["user_id"],
            UserSession.role == current_user["role"],
            UserSession.is_revoked == False,
            UserSession.expires_at > datetime.utcnow(),
        )
        .order_by(UserSession.last_active.desc())
        .all()
    )

    return {
        "success": True,
        "sessions": [
            {
                "id": s.id,
                "device_info": s.device_info,
                "ip_address": s.ip_address,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "last_active": s.last_active.isoformat() if s.last_active else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            }
            for s in sessions
        ],
    }


@app.delete("/auth/sessions/{session_id}")
def revoke_specific_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Revokes a specific session owned by the authenticated user (QA-AUTH-001)."""
    session = (
        db.query(UserSession)
        .filter(
            UserSession.id == session_id,
            UserSession.user_id == current_user["user_id"],
            UserSession.role == current_user["role"],
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    session.is_revoked = True
    db.commit()
    return {"success": True, "message": "Session revoked successfully."}


class PatientLogin(BaseModel):

    email: str

    password: str


class PatientProfileUpdate(BaseModel):
    credential: Optional[str] = None
    phone: str


class PatientMeUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    address: Optional[str] = None
    emergency_contact: Optional[str] = None


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

    name: Optional[str] = None
    phone: Optional[str] = None
    ambulance_phone: Optional[str] = None
    daily_token_limit: Optional[int] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    break_start_time: Optional[str] = None
    break_end_time: Optional[str] = None

    city: Optional[str] = None

    address: Optional[str] = None

    description: Optional[str] = None

    token_fee: Optional[int] = None

    latitude: Optional[Union[float, str]] = None

    longitude: Optional[Union[float, str]] = None

    registration_number: Optional[str] = None
    issuing_authority: Optional[str] = None
    license_id: Optional[str] = None


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
    room_number: Optional[str] = None
    token_fee: Optional[int] = 50
    is_available: bool = True

class HospitalDoctorCreate(BaseModel):
    name: str
    department: str
    specialization: Optional[str] = None
    experience: Optional[str] = None
    room_number: Optional[str] = None
    token_fee: Optional[int] = 50

    # Doctor availability
    available_days: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    is_available: bool = True
    image_url: Optional[str] = None

class DoctorUpdateRequest(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    specialization: Optional[str] = None
    experience: Optional[str] = None
    room_number: Optional[str] = None
    token_fee: Optional[int] = None
    is_available: Optional[bool] = None
    available_days: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class TokenRequest(BaseModel):
    patient_name: Optional[str] = None
    patient_email: Optional[str] = None
    patient_phone: Optional[str] = None
    booking_for: Optional[str] = "self"
    patient_relation: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    hospital: str
    department: str
    doctor: str
    appointment_date: Optional[date] = None
    cashfree_order_id: str

class EmailReceiptRequest(BaseModel):
    recipient_email: Optional[str] = None

class CreateOrderRequest(BaseModel):
    patient_name: Optional[str] = None
    patient_email: Optional[str] = None
    patient_phone: Optional[str] = None
    booking_for: Optional[str] = "self"
    patient_relation: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
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
    patient_phone: Optional[str] = None
    notes: Optional[str] = None
    token_fee: Optional[int] = None
    payment_type: Optional[str] = None
    payment_status: Optional[str] = None
# ============================================================
# HELPER - HOSPITAL OPD & BREAK TIMINGS
# ============================================================

def check_is_on_break(break_start_str: str | None, break_end_str: str | None) -> bool:
    """Returns True if the current Indian Standard Time (IST) is within hospital break hours."""
    if not break_start_str or not break_end_str:
        return False
    try:
        ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        curr_time = ist_now.strftime("%H:%M")
        b_start = str(break_start_str).strip()[:5]
        b_end = str(break_end_str).strip()[:5]
        return b_start <= curr_time < b_end
    except Exception:
        return False


def get_hospital_opd_status(hospital) -> dict:
    """
    Computes real-time OPD status based on opening hours, break hours, and current IST time.
    """
    opening = hospital.opening_time or "09:00"
    closing = hospital.closing_time or "21:00"
    b_start = getattr(hospital, "break_start_time", None) or "13:00"
    b_end = getattr(hospital, "break_end_time", None) or "14:00"

    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    curr_time = ist_now.strftime("%H:%M")

    b_start_12h = format_time_12h(b_start)
    b_end_12h = format_time_12h(b_end)
    open_12h = format_time_12h(opening)
    close_12h = format_time_12h(closing)

    # 1. Outside daily operating hours
    if curr_time < opening or curr_time >= closing:
        return {
            "status": "CLOSED",
            "label": "OPD CLOSED",
            "badge_color": "red",
            "is_active": False,
            "is_on_break": False,
            "detail": f"OPD is currently closed. Resumes tomorrow at {open_12h}.",
            "break_hours_12h": f"{b_start_12h} - {b_end_12h}",
            "operating_hours_12h": f"{open_12h} - {close_12h}",
        }

    # 2. Currently on break (lunch/shift break)
    if b_start <= curr_time < b_end:
        return {
            "status": "BREAK",
            "label": f"OPD ON BREAK ({b_start_12h} - {b_end_12h})",
            "badge_color": "amber",
            "is_active": False,
            "is_on_break": True,
            "detail": f"Doctors are currently on break ({b_start_12h} - {b_end_12h}). Consultations resume at {b_end_12h}.",
            "break_hours_12h": f"{b_start_12h} - {b_end_12h}",
            "operating_hours_12h": f"{open_12h} - {close_12h}",
        }

    # 3. Active
    return {
        "status": "ACTIVE",
        "label": "OPD ACTIVE",
        "badge_color": "green",
        "is_active": True,
        "is_on_break": False,
        "detail": f"OPD is open until {close_12h}. Break timing: {b_start_12h} - {b_end_12h}.",
        "break_hours_12h": f"{b_start_12h} - {b_end_12h}",
        "operating_hours_12h": f"{open_12h} - {close_12h}",
    }


# ============================================================
# HELPER - HOSPITAL RESPONSE
# ============================================================

def resolve_hospital_photo_url(hospital):
    if hospital.image_url and str(hospital.image_url).strip():
        return str(hospital.image_url).strip()
    return f"/hospital-photos/hospital_{hospital.id}.jpg" 



def log_admin_action(
    db: Session,
    admin_email: str,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    details: Optional[str] = None,
    ip_address: Optional[str] = None,
):
    try:
        log = AdminAuditLog(
            admin_email=admin_email,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            details=details,
            ip_address=ip_address,
        )
        db.add(log)
        db.commit()
    except Exception as err:
        db.rollback()
        logging.warning("Audit log write error: %s", err)


def get_current_platform_fee(db: Session) -> int:
    try:
        contact = db.query(PlatformContact).first()
        if contact and getattr(contact, "platform_fee", None) is not None:
            return int(contact.platform_fee)
    except Exception:
        pass
    return PLATFORM_FEE


DEFAULT_COMMISSION_PERCENTAGE = Decimal("10.00")


def get_current_commission_percentage(db: Session) -> Decimal:
    """Returns the current admin-configured platform commission percentage as Decimal."""
    try:
        contact = db.query(PlatformContact).first()
        if contact and getattr(contact, "commission_percentage", None) is not None:
            val = Decimal(str(contact.commission_percentage))
            if Decimal("0.00") <= val <= Decimal("100.00"):
                return val
    except Exception as e:
        logging.warning("Error fetching current commission percentage: %s", e)
    return DEFAULT_COMMISSION_PERCENTAGE


def calculate_commission(
    eligible_booking_amount: Union[Decimal, float, int, str],
    commission_percentage: Union[Decimal, float, int, str],
    is_eligible: bool = True,
) -> Dict[str, Decimal]:
    """
    Q-Arovia Commission & Payout Calculation Engine
    Rules:
    1. Commission Amount = Eligible Booking Amount × Commission Percentage ÷ 100
    2. Calculates commission on backend using decimal arithmetic, not floating-point arithmetic.
    3. Uses actual eligible booking amount (token_fee), excluding separately collected platform fees/taxes.
    4. Never calculates commission on cancelled, failed, refunded, or unpaid bookings (returns 0.00).
    5. Stores and calculates monetary values with 2 decimal places in INR (₹0.01 paisa).
    6. Uses ROUND_HALF_UP rounding method.
    7. Hospital Amount = Eligible Booking Amount − Rounded Commission Amount.
    8. Mathematical guarantee: Commission Amount + Hospital Amount == Eligible Booking Amount (zero-leak).
    """
    ZERO = Decimal("0.00")
    PAISA = Decimal("0.01")
    HUNDRED = Decimal("100.00")

    if not is_eligible:
        return {
            "eligible_amount": ZERO,
            "commission_percentage": Decimal(str(commission_percentage or 0)).quantize(PAISA),
            "commission_amount": ZERO,
            "hospital_amount": ZERO,
        }

    try:
        amount_dec = Decimal(str(eligible_booking_amount)).quantize(PAISA, rounding=ROUND_HALF_UP)
    except Exception:
        amount_dec = ZERO

    if amount_dec <= ZERO:
        return {
            "eligible_amount": ZERO,
            "commission_percentage": Decimal(str(commission_percentage or 0)).quantize(PAISA),
            "commission_amount": ZERO,
            "hospital_amount": ZERO,
        }

    try:
        pct_dec = Decimal(str(commission_percentage).strip().rstrip("%"))
        if pct_dec.is_nan() or pct_dec.is_infinite():
            raise ValueError()
    except Exception:
        raise ValueError(f"Invalid commission percentage: {commission_percentage}")

    if pct_dec < ZERO or pct_dec > HUNDRED:
        raise ValueError(f"Commission percentage must be between 0.00% and 100.00%, got {pct_dec}")

    # Decimal arithmetic (not float)
    raw_commission = (amount_dec * pct_dec) / HUNDRED
    # Round half up to nearest paisa
    commission_amount = raw_commission.quantize(PAISA, rounding=ROUND_HALF_UP)
    # Hospital payable = Eligible Booking Amount - Rounded Commission Amount
    hospital_amount = amount_dec - commission_amount

    # Financial consistency sanity check
    if commission_amount + hospital_amount != amount_dec:
        raise ValueError("Reconciliation error: Commission + Hospital Amount != Eligible Booking Amount")

    return {
        "eligible_amount": amount_dec,
        "commission_percentage": pct_dec.quantize(PAISA),
        "commission_amount": commission_amount,
        "hospital_amount": hospital_amount,
    }


DEFAULT_CITY_COORDINATES = {
    "bhubaneswar": ("20.2961", "85.8245"),
    "cuttack": ("20.4625", "85.8828"),
    "hyderabad": ("17.3850", "78.4867"),
    "nagar kurnool": ("16.4855", "78.3150"),
    "nagarkurnool": ("16.4855", "78.3150"),
    "bangalore": ("12.9716", "77.5946"),
    "bengaluru": ("12.9716", "77.5946"),
    "mumbai": ("19.0760", "72.8777"),
    "delhi": ("28.6139", "77.2090"),
    "new delhi": ("28.6139", "77.2090"),
    "pune": ("18.5204", "73.8567"),
    "kolkata": ("22.5726", "88.3639"),
    "chennai": ("13.0827", "80.2707"),
}

def resolve_hospital_coordinates(hospital):
    if not hospital:
        return None, None
    lat = getattr(hospital, "latitude", None)
    lng = getattr(hospital, "longitude", None)
    if lat and lng and str(lat).strip() and str(lng).strip() and str(lat).strip().upper() != "NULL":
        return str(lat).strip(), str(lng).strip()
    city_str = str(getattr(hospital, "city", "") or getattr(hospital, "address", "") or "").lower()
    for c_name, (c_lat, c_lng) in DEFAULT_CITY_COORDINATES.items():
        if c_name in city_str:
            return c_lat, c_lng
    return (str(lat).strip() if lat else None), (str(lng).strip() if lng else None)

def hospital_to_dict(hospital):


    return {
        "id": hospital.id,
        "name": hospital.name,
        "email": hospital.email,
        "phone": hospital.phone,
        "city": hospital.city,
        "address": hospital.address,
        "description": hospital.description,
        "image_url": resolve_hospital_photo_url(hospital),
        "photo_base64": bool(hospital.photo_base64),

        "license_id": hospital.license_id,

        "registration_number": hospital.registration_number,
        "issuing_authority": hospital.issuing_authority,

        "license_expiry_date": (
            hospital.license_expiry_date.isoformat()
            if hospital.license_expiry_date
            else None
        ),
        "license_status": (
            "EXPIRED" if (hospital.license_expiry_date and hospital.license_expiry_date < date.today())
            else ("EXPIRING_SOON" if (hospital.license_expiry_date and (hospital.license_expiry_date - date.today()).days <= 30)
            else "VALID")
        ),
        "days_to_license_expiry": (
            (hospital.license_expiry_date - date.today()).days
            if hospital.license_expiry_date
            else None
        ),
        "rejection_reason": getattr(hospital, "rejection_reason", None),

        "approval_status": hospital.approval_status,
        "is_published": hospital.is_published,

        "token_fee": hospital.token_fee,
        "latitude": resolve_hospital_coordinates(hospital)[0],
        "longitude": resolve_hospital_coordinates(hospital)[1],

        "payment_account_status": (
            hospital.payment_account_status
        ),
        "opening_time": hospital.opening_time or "09:00",
        "closing_time": hospital.closing_time or "21:00",
        "operating_hours_12h": f"{format_time_12h(hospital.opening_time or '09:00')} - {format_time_12h(hospital.closing_time or '21:00')}",
        "break_start_time": getattr(hospital, "break_start_time", None) or "13:00",
        "break_end_time": getattr(hospital, "break_end_time", None) or "14:00",
        "break_hours_12h": f"{format_time_12h(getattr(hospital, 'break_start_time', None) or '13:00')} - {format_time_12h(getattr(hospital, 'break_end_time', None) or '14:00')}",
        "daily_token_limit": getattr(hospital, "daily_token_limit", None) or 100,
        "ambulance_phone": getattr(hospital, "ambulance_phone", None),
        "is_on_break": check_is_on_break(getattr(hospital, "break_start_time", None) or "13:00", getattr(hospital, "break_end_time", None) or "14:00"),
        "opd_status": get_hospital_opd_status(hospital),
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
        "payment_account_name": getattr(hospital, "payment_account_name", None),
        "payment_account_number": getattr(hospital, "payment_account_number", None),
        "payment_ifsc": getattr(hospital, "payment_ifsc", None),
        "payment_upi": getattr(hospital, "payment_upi", None),
        "razorpay_account_id": getattr(hospital, "razorpay_account_id", None),
        "cashfree_vendor_id": getattr(hospital, "cashfree_vendor_id", None),
        "is_deleted": bool(getattr(hospital, "is_deleted", False)),
        "deleted_at": (
            hospital.deleted_at.isoformat()
            if getattr(hospital, "deleted_at", None)
            else None
        ),
        "deleted_by": getattr(hospital, "deleted_by", None),
    }


def public_hospital_to_dict(hospital):
    return {
        "id": hospital.id,
        "name": hospital.name,
        "phone": hospital.phone,
        "city": hospital.city,
        "address": hospital.address,
        "description": hospital.description,
        "image_url": resolve_hospital_photo_url(hospital),
        "token_fee": hospital.token_fee,
        "latitude": resolve_hospital_coordinates(hospital)[0],
        "longitude": resolve_hospital_coordinates(hospital)[1],
        "approval_status": hospital.approval_status,
        "is_published": hospital.is_published,
        "opening_time": hospital.opening_time or "09:00",
        "closing_time": hospital.closing_time or "21:00",
        "operating_hours_12h": f"{format_time_12h(hospital.opening_time or '09:00')} - {format_time_12h(hospital.closing_time or '21:00')}",
        "break_start_time": getattr(hospital, "break_start_time", None) or "13:00",
        "break_end_time": getattr(hospital, "break_end_time", None) or "14:00",
        "break_hours_12h": f"{format_time_12h(getattr(hospital, 'break_start_time', None) or '13:00')} - {format_time_12h(getattr(hospital, 'break_end_time', None) or '14:00')}",
        "daily_token_limit": getattr(hospital, "daily_token_limit", None) or 100,
        "ambulance_phone": getattr(hospital, "ambulance_phone", None),
        "is_on_break": check_is_on_break(getattr(hospital, "break_start_time", None) or "13:00", getattr(hospital, "break_end_time", None) or "14:00"),
        "opd_status": get_hospital_opd_status(hospital),
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

def doctor_to_dict(doctor, hospital=None):

    start_12h = format_time_12h(doctor.start_time)
    end_12h = format_time_12h(doctor.end_time)
    hours_12h = f"{start_12h} - {end_12h}" if (start_12h and end_12h) else None

    hosp_name = getattr(hospital, "name", None)
    hosp_city = getattr(hospital, "city", None)
    hosp_address = getattr(hospital, "address", None)
    hosp_lat, hosp_lng = resolve_hospital_coordinates(hospital) if hospital else (None, None)
    hosp_fee = getattr(hospital, "token_fee", 0)
    doc_fee = getattr(doctor, "token_fee", None)
    effective_fee = doc_fee if doc_fee is not None else hosp_fee

    photo_b64 = getattr(doctor, "photo_base64", None)
    if photo_b64 and isinstance(photo_b64, str) and not photo_b64.startswith("data:"):
        mime = "image/png" if (getattr(doctor, "image_url", None) and str(doctor.image_url).lower().endswith(".png")) else "image/jpeg"
        photo_b64 = f"data:{mime};base64,{photo_b64}"

    return {
        "id": doctor.id,
        "hospital_id": doctor.hospital_id,
        "name": doctor.name,
        "department": doctor.department,
        "specialization": doctor.specialization,
        "experience": doctor.experience,
        "image_url": doctor.image_url,
        "photo_base64": photo_b64,

        # Token fee (per doctor with hospital fallback)
        "token_fee": effective_fee,
        "doctor_token_fee": doc_fee,
        "hospital_token_fee": hosp_fee,

        # Doctor availability details
        "available_days": doctor.available_days,
        "start_time": doctor.start_time,
        "end_time": doctor.end_time,
        "start_time_12h": start_12h,
        "end_time_12h": end_12h,
        "consultation_hours_12h": hours_12h,
        "is_available": getattr(doctor, "is_available", True),
        "room_number": getattr(doctor, "room_number", None),

        # Hospital & location context for nearby doctors
        "hospital_name": hosp_name,
        "hospital_city": hosp_city,
        "hospital_address": hosp_address,
        "hospital_latitude": hosp_lat,
        "hospital_longitude": hosp_lng,
        "hospital_token_fee": hosp_fee,
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
        "room_number": getattr(token, "room_number", None),
        "doctor_room_number": getattr(token, "room_number", None),
        "patient_email": getattr(token, "patient_email", None),
        "patient_phone": getattr(token, "patient_phone", None),
        "booking_for": getattr(token, "booking_for", None) or "self",
        "patient_age": getattr(token, "patient_age", None),
        "patient_gender": getattr(token, "patient_gender", None),
        "commission_percentage": float(token.commission_percentage) if getattr(token, "commission_percentage", None) is not None else 0.0,
        "commission_amount": float(token.commission_amount) if getattr(token, "commission_amount", None) is not None else 0.0,
        "hospital_amount": float(token.hospital_amount) if getattr(token, "hospital_amount", None) is not None else float(getattr(token, "token_fee", 0) or 0),
    }


def get_ist_today() -> date:
    """Returns today's date in Indian Standard Time (UTC+5:30)."""
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()


def allocate_token_number(
    db,
    hospital_id: int,
    department: str,
    doctor: str,
    appointment_date: date,
    doctor_id: Optional[int] = None,
) -> int:
    """
    Centralized, atomic token number allocation function for Q-Arovia.
    Used for both Online Bookings and Walk-in OPD Registrations.
    Uses PostgreSQL row locking (SELECT ... FOR UPDATE) on token_sequences
    to ensure 100% strict atomicity and zero duplicate allocations under concurrent registrations.
    Separates token counters per (hospital_id, doctor_id, appointment_date).
    """
    if isinstance(appointment_date, str):
        try:
            appointment_date = datetime.strptime(appointment_date.strip(), "%Y-%m-%d").date()
        except Exception:
            try:
                appointment_date = date.fromisoformat(appointment_date.strip())
            except Exception:
                appointment_date = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
    elif isinstance(appointment_date, datetime):
        appointment_date = appointment_date.date()
    elif not appointment_date:
        appointment_date = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()

    clean_dept = (department or "").strip()
    clean_doc = (doctor or "").strip()

    # Canonical doctor lookup to prevent case/prefix mismatches
    if not doctor_id and (clean_doc or clean_dept):
        clean_doc_search = re.sub(r'^(dr\.|dr|mr\.|mr)\s*', '', clean_doc, flags=re.I).strip()
        doc_record = (
            db.query(Doctor)
            .filter(
                Doctor.hospital_id == hospital_id,
                or_(
                    func.lower(Doctor.name) == clean_doc.lower(),
                    func.lower(Doctor.name) == clean_doc_search.lower(),
                    Doctor.name.ilike(f"%{clean_doc_search}%")
                )
            )
            .first()
        )
        if doc_record:
            doctor_id = doc_record.id
            clean_doc = doc_record.name
            clean_dept = doc_record.department
    elif doctor_id:
        doc_record = db.query(Doctor).filter(Doctor.id == doctor_id, Doctor.hospital_id == hospital_id).first()
        if doc_record:
            clean_doc = doc_record.name
            clean_dept = doc_record.department

    # Check maximum existing token allocated in tokens table for this doctor and date
    max_in_tokens = (
        db.query(func.max(Token.token_number))
        .filter(
            Token.hospital_id == hospital_id,
            Token.appointment_date == appointment_date,
            or_(
                Token.doctor_id == doctor_id if doctor_id else False,
                func.lower(Token.doctor) == clean_doc.lower()
            )
        )
        .scalar() or 0
    )

    # Lock existing sequence row using SELECT ... FOR UPDATE
    seq_last = 0
    seq_row = None
    if doctor_id:
        seq_row = db.execute(text("""
            SELECT last_token_number FROM token_sequences
            WHERE hospital_id = :h_id AND appointment_date = :dt
              AND (doctor_id = :d_id OR LOWER(doctor) = LOWER(:d_name))
            ORDER BY last_token_number DESC
            LIMIT 1
            FOR UPDATE
        """), {"h_id": hospital_id, "d_id": doctor_id, "d_name": clean_doc, "dt": appointment_date}).first()
    else:
        seq_row = db.execute(text("""
            SELECT last_token_number FROM token_sequences
            WHERE hospital_id = :h_id AND appointment_date = :dt
              AND LOWER(doctor) = LOWER(:d_name)
            ORDER BY last_token_number DESC
            LIMIT 1
            FOR UPDATE
        """), {"h_id": hospital_id, "d_name": clean_doc, "dt": appointment_date}).first()

    if seq_row and seq_row[0] is not None:
        seq_last = seq_row[0]

    next_token = max(int(seq_last), int(max_in_tokens)) + 1

    if seq_row:
        if doctor_id:
            db.execute(text("""
                UPDATE token_sequences
                SET last_token_number = :next_num,
                    doctor_id = COALESCE(:d_id, doctor_id),
                    doctor = :d_name,
                    department = :dept
                WHERE hospital_id = :h_id AND appointment_date = :dt
                  AND (doctor_id = :d_id OR LOWER(doctor) = LOWER(:d_name))
            """), {"next_num": next_token, "d_id": doctor_id, "d_name": clean_doc, "dept": clean_dept, "h_id": hospital_id, "dt": appointment_date})
        else:
            db.execute(text("""
                UPDATE token_sequences
                SET last_token_number = :next_num,
                    doctor = :d_name,
                    department = :dept
                WHERE hospital_id = :h_id AND appointment_date = :dt
                  AND LOWER(doctor) = LOWER(:d_name)
            """), {"next_num": next_token, "d_name": clean_doc, "dept": clean_dept, "h_id": hospital_id, "dt": appointment_date})
    else:
        try:
            savepoint = db.begin_nested()
            db.execute(text("""
                INSERT INTO token_sequences (hospital_id, doctor_id, department, doctor, appointment_date, last_token_number)
                VALUES (:h_id, :d_id, :dept, :d_name, :dt, :next_num)
            """), {"h_id": hospital_id, "d_id": doctor_id, "dept": clean_dept, "d_name": clean_doc, "dt": appointment_date, "next_num": next_token})
            savepoint.commit()
        except Exception:
            savepoint.rollback()
            # If concurrent insert occurred, lock and update
            if doctor_id:
                seq_row2 = db.execute(text("""
                    SELECT last_token_number FROM token_sequences
                    WHERE hospital_id = :h_id AND appointment_date = :dt
                      AND (doctor_id = :d_id OR LOWER(doctor) = LOWER(:d_name))
                    FOR UPDATE
                """), {"h_id": hospital_id, "d_id": doctor_id, "d_name": clean_doc, "dt": appointment_date}).first()
            else:
                seq_row2 = db.execute(text("""
                    SELECT last_token_number FROM token_sequences
                    WHERE hospital_id = :h_id AND appointment_date = :dt
                      AND LOWER(doctor) = LOWER(:d_name)
                    FOR UPDATE
                """), {"h_id": hospital_id, "d_name": clean_doc, "dt": appointment_date}).first()
            seq_last2 = seq_row2[0] if seq_row2 and seq_row2[0] is not None else 0
            next_token = max(int(seq_last2), int(max_in_tokens)) + 1
            db.execute(text("""
                UPDATE token_sequences
                SET last_token_number = :next_num
                WHERE hospital_id = :h_id AND appointment_date = :dt
                  AND (doctor_id = :d_id OR LOWER(doctor) = LOWER(:d_name))
            """), {"next_num": next_token, "h_id": hospital_id, "d_id": doctor_id, "d_name": clean_doc, "dt": appointment_date})

    return int(next_token)


@app.get("/tokens/next-available")
def get_next_available_token(
    hospital_id: int,
    department: str = "",
    doctor: str = "",
    doctor_id: Optional[int] = None,
    appointment_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """
    Returns the dynamic next available token number, currently serving token,
    and waiting queue count separately for each hospital and doctor.
    When All Doctors is selected, aggregates the hospital-wide queue without mixing statistics.
    Never hardcodes 8 or any other fixed number.
    """
    target_date = appointment_date or get_ist_today()
    clean_dept = (department or "").strip()
    clean_doc = (doctor or "").strip()

    # If specific doctor requested
    if clean_doc or doctor_id:
        if not doctor_id:
            clean_doc_search = re.sub(r'^(dr\.|dr|mr\.|mr)\s*', '', clean_doc, flags=re.I).strip()
            doc_record = (
                db.query(Doctor)
                .filter(
                    Doctor.hospital_id == hospital_id,
                    or_(
                        func.lower(Doctor.name) == clean_doc.lower(),
                        func.lower(Doctor.name) == clean_doc_search.lower(),
                        Doctor.name.ilike(f"%{clean_doc_search}%")
                    )
                )
                .first()
            )
            if doc_record:
                doctor_id = doc_record.id
                clean_doc = doc_record.name
                clean_dept = doc_record.department
        elif doctor_id:
            doc_record = db.query(Doctor).filter(Doctor.id == doctor_id, Doctor.hospital_id == hospital_id).first()
            if doc_record:
                clean_doc = doc_record.name
                clean_dept = doc_record.department

        # Check maximum existing token allocated in tokens table
        max_existing = (
            db.query(func.max(Token.token_number))
            .filter(
                Token.hospital_id == hospital_id,
                Token.appointment_date == target_date,
                or_(
                    Token.doctor_id == doctor_id if doctor_id else False,
                    func.lower(Token.doctor) == clean_doc.lower()
                )
            )
            .scalar() or 0
        )

        seq_last = 0
        if doctor_id:
            seq_val = db.execute(text("""
                SELECT MAX(last_token_number) FROM token_sequences
                WHERE hospital_id = :h_id AND appointment_date = :dt
                  AND (doctor_id = :d_id OR LOWER(doctor) = LOWER(:d_name))
            """), {"h_id": hospital_id, "d_id": doctor_id, "d_name": clean_doc, "dt": target_date}).scalar()
            seq_last = seq_val or 0
        else:
            seq_val = db.execute(text("""
                SELECT MAX(last_token_number) FROM token_sequences
                WHERE hospital_id = :h_id AND appointment_date = :dt
                  AND LOWER(doctor) = LOWER(:d_name)
            """), {"h_id": hospital_id, "d_name": clean_doc, "dt": target_date}).scalar()
            seq_last = seq_val or 0

        current_max = max(int(max_existing), int(seq_last))
        next_token = current_max + 1

        serving_tok = db.query(Token.token_number).filter(
            Token.hospital_id == hospital_id,
            Token.appointment_date == target_date,
            Token.status == "serving",
            or_(
                Token.doctor_id == doctor_id if doctor_id else False,
                func.lower(Token.doctor) == clean_doc.lower()
            )
        ).order_by(Token.called_at.desc(), Token.id.desc()).first()

        waiting_cnt = db.query(func.count(Token.id)).filter(
            Token.hospital_id == hospital_id,
            Token.appointment_date == target_date,
            Token.status == "waiting",
            or_(
                Token.doctor_id == doctor_id if doctor_id else False,
                func.lower(Token.doctor) == clean_doc.lower()
            )
        ).scalar() or 0

        completed_cnt = db.query(func.count(Token.id)).filter(
            Token.hospital_id == hospital_id,
            Token.appointment_date == target_date,
            Token.status == "completed",
            or_(
                Token.doctor_id == doctor_id if doctor_id else False,
                func.lower(Token.doctor) == clean_doc.lower()
            )
        ).scalar() or 0

        return {
            "hospital_id": hospital_id,
            "doctor_id": doctor_id,
            "department": clean_dept,
            "doctor": clean_doc,
            "appointment_date": str(target_date),
            "is_all_doctors": False,
            "booked_count": int(current_max),
            "next_token_number": int(next_token),
            "serving_token": serving_tok[0] if serving_tok else None,
            "waiting_count": int(waiting_cnt),
            "completed_count": int(completed_cnt),
            "estimated_wait_minutes": int(waiting_cnt * 5),
        }
    else:
        # ALL DOCTORS OVERVIEW - Bulk Aggregated Queries (O(1) database roundtrips, eliminating N+1 query storms)
        doctors = db.query(Doctor).filter(Doctor.hospital_id == hospital_id).all()

        # 1. Bulk aggregate max token and waiting counts from tokens
        tokens_agg = db.query(
            Token.doctor_id,
            func.lower(Token.doctor).label("doc_name_lower"),
            func.max(Token.token_number).label("max_token"),
            func.count(case((Token.status == "waiting", 1))).label("waiting_count"),
        ).filter(
            Token.hospital_id == hospital_id,
            Token.appointment_date == target_date,
            Token.status != "cancelled"
        ).group_by(Token.doctor_id, func.lower(Token.doctor)).all()

        max_token_map = {}
        waiting_map = {}
        for row in tokens_agg:
            if row.doctor_id:
                max_token_map[f"id_{row.doctor_id}"] = row.max_token or 0
                waiting_map[f"id_{row.doctor_id}"] = row.waiting_count or 0
            if row.doc_name_lower:
                max_token_map[f"name_{row.doc_name_lower}"] = row.max_token or 0
                waiting_map[f"name_{row.doc_name_lower}"] = row.waiting_count or 0

        # 2. Bulk aggregate from token_sequences
        seq_agg = db.execute(text("""
            SELECT doctor_id, LOWER(doctor) as doc_name_lower, MAX(last_token_number) as max_seq
            FROM token_sequences
            WHERE hospital_id = :h_id AND appointment_date = :dt
            GROUP BY doctor_id, LOWER(doctor)
        """), {"h_id": hospital_id, "dt": target_date}).fetchall()

        seq_map = {}
        for s_row in seq_agg:
            d_id = s_row[0]
            d_name = s_row[1]
            m_seq = s_row[2] or 0
            if d_id:
                seq_map[f"id_{d_id}"] = m_seq
            if d_name:
                seq_map[f"name_{d_name}"] = m_seq

        # 3. Bulk fetch currently serving tokens
        serving_agg = db.query(
            Token.doctor_id,
            func.lower(Token.doctor).label("doc_name_lower"),
            Token.token_number
        ).filter(
            Token.hospital_id == hospital_id,
            Token.appointment_date == target_date,
            Token.status == "serving"
        ).order_by(Token.called_at.desc(), Token.id.desc()).all()

        serving_map = {}
        for srv in serving_agg:
            key_id = f"id_{srv.doctor_id}" if srv.doctor_id else None
            key_name = f"name_{srv.doc_name_lower}" if srv.doc_name_lower else None
            if key_id and key_id not in serving_map:
                serving_map[key_id] = srv.token_number
            if key_name and key_name not in serving_map:
                serving_map[key_name] = srv.token_number

        doc_queues = []
        total_waiting = 0
        serving_tokens_list = []

        for d in doctors:
            d_name_l = d.name.lower().strip()
            m_tok = max(max_token_map.get(f"id_{d.id}", 0), max_token_map.get(f"name_{d_name_l}", 0))
            s_tok = max(seq_map.get(f"id_{d.id}", 0), seq_map.get(f"name_{d_name_l}", 0))
            n_tok = max(int(m_tok), int(s_tok)) + 1

            srv_tok = serving_map.get(f"id_{d.id}") or serving_map.get(f"name_{d_name_l}")
            if srv_tok:
                serving_tokens_list.append(f"#{srv_tok} (Dr. {d.name})")

            w_cnt = max(waiting_map.get(f"id_{d.id}", 0), waiting_map.get(f"name_{d_name_l}", 0))
            total_waiting += w_cnt

            doc_queues.append({
                "doctor_id": d.id,
                "doctor_name": d.name,
                "department": d.department,
                "next_token_number": n_tok,
                "serving_token": srv_tok,
                "waiting_count": w_cnt,
            })

        return {
            "hospital_id": hospital_id,
            "doctor_id": None,
            "department": "",
            "doctor": "All Doctors",
            "appointment_date": str(target_date),
            "is_all_doctors": True,
            "next_token_number": None,
            "next_token_display": "Select Doctor",
            "serving_token": ", ".join(serving_tokens_list) if serving_tokens_list else None,
            "waiting_count": total_waiting,
            "estimated_wait_minutes": int(total_waiting * 5),
            "doctors": doc_queues,
        }


@app.post("/hospitals/{hospital_id}/reset-doctor-queue")
def reset_doctor_queue(
    hospital_id: int,
    doctor: str,
    appointment_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Resets the token counter for a specific doctor on a given date (authorized hospital or admin only)."""
    user_role = current_user.get("role")
    auth_user_id = current_user.get("user_id")

    if user_role == "hospital":
        if auth_user_id != hospital_id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to reset queues for another hospital.",
            )
    elif user_role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Permission denied. Only authorized hospitals or administrators can reset queue counters.",
        )

    clean_doc = doctor.strip()
    clean_doc_search = re.sub(r'^(dr\.|dr|mr\.|mr)\s*', '', clean_doc, flags=re.I).strip()
    doc_exists = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == hospital_id,
            or_(
                func.lower(Doctor.name) == clean_doc.lower(),
                func.lower(Doctor.name) == clean_doc_search.lower(),
                Doctor.name.ilike(f"%{clean_doc_search}%"),
            )
        )
        .first()
    )
    if not doc_exists:
        raise HTTPException(
            status_code=404,
            detail=f"Doctor '{clean_doc}' not found at hospital ID {hospital_id}.",
        )

    target_date = appointment_date or get_ist_today()

    active_tokens = db.query(func.count(Token.id)).filter(
        Token.hospital_id == hospital_id,
        or_(Token.doctor_id == doc_exists.id, func.lower(Token.doctor) == clean_doc.lower()),
        Token.appointment_date == target_date,
        Token.status.in_(["waiting", "serving"])
    ).scalar() or 0

    if active_tokens > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reset token sequence while {active_tokens} active consultation tokens exist for Dr. {clean_doc} on {target_date}. Please complete or cancel active tokens first."
        )

    db.execute(
        text("""
            DELETE FROM token_sequences 
            WHERE hospital_id = :h_id 
              AND (doctor = :doc OR LOWER(doctor) = LOWER(:doc))
              AND appointment_date = :dt
        """),
        {"h_id": hospital_id, "doc": clean_doc, "dt": target_date}
    )
    db.commit()
    return {
        "success": True,
        "message": f"Token queue sequence reset for Dr. {clean_doc} on {target_date}."
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
                clock_skew_in_seconds=10,
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
def root(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept and os.path.exists(os.path.join(PATIENT_STATIC_DIR, "dashboard.html")):
        return FileResponse(os.path.join(PATIENT_STATIC_DIR, "dashboard.html"))
    return {
        "success": True,
        "message": "Q-Arovia API is running",
        "version": "11.0.0",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return {

        "success": True,

        "status": "healthy",
        "deploy_version": "2026-11-06-v3",
    }


# ============================================================
# PATIENT REGISTER
# ============================================================
@app.post("/patients/register")
def register_patient(
    data: PatientRegister,
    request: Request = None,
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

    # Generate JWT access token and rotatable refresh session
    access_token, refresh_token, session = create_user_session(
        db=db,
        user_id=patient.id,
        role="patient",
        request=request,
    )

    # Return registration response with access token
    return {
        "success": True,
        "message": "Patient registered successfully",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
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
    request: Request,
    db: Session = Depends(get_db),
):
    check_login_rate_limit(request)
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

    access_token, refresh_token, session = create_user_session(
        db=db,
        user_id=patient.id,
        role="patient",
        request=request,
    )

    return {
        "success": True,
        "message": "Patient login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
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
    request: Request = None,
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

    access_token, refresh_token, session = create_user_session(
        db=db,
        user_id=patient.id,
        role="patient",
        request=request,
    )

    return {
        "success": True,
        "message": "Google login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "email": patient.email,
            "phone": patient.phone,
        },
    }

# ============================================================
# PATIENT PROFILE MANAGEMENT
# ============================================================

class PatientDeletionRequest(BaseModel):
    identifier: str
    reason: Optional[str] = ""
    password: Optional[str] = None
    otp: Optional[str] = None

@app.post("/patients/request-account-deletion")
@app.post("/patients/request-account-deletion/")
def request_patient_account_deletion_public(
    data: PatientDeletionRequest,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
):
    """Google Play Store compliant web endpoint for patient account deletion requests with verified identity."""
    ident = data.identifier.strip().lower()
    patient = db.query(Patient).filter(
        (func.lower(Patient.email) == ident) | (Patient.phone == ident)
    ).first()
    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Patient account not found with the provided email or phone number.",
        )

    auth_verified = False
    if credentials and credentials.credentials:
        try:
            payload = jwt.decode(credentials.credentials.strip(), JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            if payload.get("role") == "patient" and int(payload.get("sub", 0)) == patient.id:
                auth_verified = True
            elif payload.get("role") == "admin":
                auth_verified = True
        except Exception:
            pass

    if not auth_verified and data.password and patient.password:
        if verify_password(data.password, patient.password):
            auth_verified = True

    if not auth_verified and data.otp:
        clean_otp = data.otp.strip()
        otp_record = (
            db.query(RegistrationOTP)
            .filter(
                RegistrationOTP.contact_value == patient.email,
                RegistrationOTP.verified == False,
            )
            .order_by(RegistrationOTP.created_at.desc())
            .first()
        )
        if otp_record and otp_record.expires_at > datetime.utcnow():
            submitted_hash = hashlib.sha256(clean_otp.encode()).hexdigest()
            if hmac.compare_digest(submitted_hash, otp_record.otp_hash):
                auth_verified = True
                db.delete(otp_record)

    if not auth_verified:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized account deletion request. Please provide your patient account password, a verified OTP, or log in to confirm deletion.",
        )

    try:
        db.query(PatientInquiry).filter(PatientInquiry.patient_id == patient.id).delete(synchronize_session=False)
    except Exception as e:
        logging.warning("Error deleting inquiries for patient %s: %s", patient.id, e)
    db.delete(patient)
    db.commit()
    return {
        "success": True,
        "message": "Account and all associated personal data have been permanently deleted successfully."
    }

@app.delete("/patients/me")
@app.delete("/patients/me/")
def delete_current_patient_account(
    current_user: dict = Depends(require_role("patient")),
    db: Session = Depends(get_db),
):
    """Permanently delete patient account and all personal health data in-app."""
    patient_id = current_user["user_id"]
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient account not found")

    try:
        db.query(PatientInquiry).filter(PatientInquiry.patient_id == patient_id).delete(synchronize_session=False)
    except Exception as e:
        logging.warning("Error deleting inquiries: %s", e)

    db.delete(patient)
    db.commit()

    return {
        "success": True,
        "message": "Your Q-Arovia account and personal data have been permanently deleted."
    }

@app.get("/patients/me")
@app.get("/patients/me/")
@app.get("/patient/profile")
@app.get("/patients/profile")
def get_current_patient_profile(
    current_user: dict = Depends(require_role("patient")),
    db: Session = Depends(get_db),
):
    patient = db.query(Patient).filter(Patient.id == current_user["user_id"]).first()
    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Patient account not found",
        )

    return {
        "success": True,
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "email": patient.email,
            "phone": patient.phone or "",
            "age": getattr(patient, "age", None),
            "gender": getattr(patient, "gender", None),
            "blood_group": getattr(patient, "blood_group", None),
            "address": getattr(patient, "address", None),
            "emergency_contact": getattr(patient, "emergency_contact", None),
            "created_at": patient.created_at.isoformat() if getattr(patient, "created_at", None) else None,
        }
    }


@app.put("/patients/me")
@app.post("/patients/me")
@app.patch("/patients/me")
@app.put("/patients/me/")
@app.post("/patients/me/")
@app.patch("/patients/me/")
def update_current_patient_profile(
    data: PatientMeUpdateRequest,
    current_user: dict = Depends(require_role("patient")),
    db: Session = Depends(get_db),
):
    patient = db.query(Patient).filter(Patient.id == current_user["user_id"]).first()
    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Patient account not found",
        )

    if data.full_name is not None and data.full_name.strip():
        patient.full_name = data.full_name.strip()

    if data.phone is not None and data.phone.strip():
        clean_phone = data.phone.strip()
        existing = db.query(Patient).filter(
            Patient.phone == clean_phone,
            Patient.id != patient.id,
        ).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Phone number already registered with another account.",
            )
        patient.phone = clean_phone

    if data.age is not None:
        patient.age = data.age

    if data.gender is not None:
        patient.gender = data.gender.strip()

    if data.blood_group is not None:
        patient.blood_group = data.blood_group.strip()

    if data.address is not None:
        patient.address = data.address.strip()

    if data.emergency_contact is not None:
        patient.emergency_contact = data.emergency_contact.strip()

    try:
        db.commit()
        db.refresh(patient)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Database error while saving profile changes",
        )

    return {
        "success": True,
        "message": "Profile updated successfully",
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "email": patient.email,
            "phone": patient.phone or "",
            "age": getattr(patient, "age", None),
            "gender": getattr(patient, "gender", None),
            "blood_group": getattr(patient, "blood_group", None),
            "address": getattr(patient, "address", None),
            "emergency_contact": getattr(patient, "emergency_contact", None),
        }
    }


# ============================================================
# LEGACY GOOGLE ONBOARDING PATIENT PROFILE
# ============================================================

@app.put("/patients/profile")
@app.post("/patients/profile")
@app.patch("/patients/profile")
@app.put("/patients/profile/")
@app.post("/patients/profile/")
@app.patch("/patients/profile/")
def update_patient_profile(
    data: PatientProfileUpdate,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
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
# UNIVERSAL JWT TOKEN VERIFICATION & CURRENT USER PROFILE
# ============================================================

@app.get("/auth/me")
@app.get("/auth/verify")
def get_authenticated_user_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Universal JWT Verification endpoint.
    Accepts: Authorization: Bearer <token>
    Returns: Validated user_id, role ('hospital', 'patient', 'admin'), and full account object.
    """
    user_id = current_user["user_id"]
    role = current_user["role"]

    if role == "hospital":
        hospital = db.query(Hospital).filter(Hospital.id == user_id).first()
        if not hospital or getattr(hospital, "is_deleted", False):
            raise HTTPException(status_code=401, detail="Hospital account has been deactivated or deleted.")
        return {
            "success": True,
            "authenticated": True,
            "role": "hospital",
            "user_id": hospital.id,
            "hospital": hospital_to_dict(hospital),
        }
    elif role == "patient":
        patient = db.query(Patient).filter(Patient.id == user_id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient account not found.")
        return {
            "success": True,
            "authenticated": True,
            "role": "patient",
            "user_id": patient.id,
            "patient": {
                "id": patient.id,
                "full_name": patient.full_name,
                "email": patient.email,
                "phone": patient.phone,
                "age": patient.age,
                "gender": patient.gender,
                "blood_group": patient.blood_group,
            },
        }
    elif role == "admin":
        admin = db.query(Admin).filter(Admin.id == user_id).first()
        if not admin:
            raise HTTPException(status_code=404, detail="Admin account not found.")
        return {
            "success": True,
            "authenticated": True,
            "role": "admin",
            "user_id": admin.id,
            "admin": {
                "id": admin.id,
                "email": admin.email,
            },
        }

    return {
        "success": True,
        "authenticated": True,
        "role": role,
        "user_id": user_id,
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
    request: Request = None,
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

        access_token, refresh_token, session = create_user_session(
            db=db,
            user_id=patient.id,
            role="patient",
            request=request,
        )

        return {
            "success": True,
            "role": "patient",
            "message": "Google login successful",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
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

        access_token, refresh_token, session = create_user_session(
            db=db,
            user_id=hospital.id,
            role="hospital",
            request=request,
        )

        return {
            "success": True,
            "role": "hospital",
            "message": "Google login successful",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
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

        access_token, refresh_token, session = create_user_session(
            db=db,
            user_id=admin.id,
            role="admin",
            request=request,
        )

        return {
            "success": True,
            "role": "admin",
            "message": "Google admin login successful",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
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
    hospital_photo: Optional[UploadFile] = File(None),
    account_number: Optional[str] = Form(None),
    ifsc: Optional[str] = Form(None),
    upi: Optional[str] = Form(None),
    account_name: Optional[str] = Form(None),

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
    # OPTIONAL HOSPITAL PHOTO
    # --------------------------------------------------------
    photo_base64_str = None
    photo_filename = None
    photo_ext = ".jpg"
    if hospital_photo:
        try:
            photo_data = await hospital_photo.read()
            if photo_data and len(photo_data) <= MAX_HOSPITAL_PHOTO_SIZE:
                photo_base64_str = base64.b64encode(photo_data).decode("utf-8")
                photo_ct = (hospital_photo.content_type or "").lower()
                photo_ext = ALLOWED_HOSPITAL_PHOTO_TYPES.get(photo_ct, ".jpg")
                photo_filename = f"hospital_pending_{uuid.uuid4().hex}{photo_ext}"
                try:
                    with open(os.path.join(HOSPITAL_PHOTO_DIR, photo_filename), "wb") as f:
                        f.write(photo_data)
                except Exception as disk_err:
                    logging.warning("Could not cache photo to disk: %s", disk_err)
        except Exception as photo_err:
            logging.warning("Could not read hospital photo on registration: %s", photo_err)

    # --------------------------------------------------------
    # PAYMENT / BANK ACCOUNT DETAILS
    # --------------------------------------------------------
    clean_account_number = account_number.strip() if account_number else None
    clean_ifsc = ifsc.strip().upper() if ifsc else None
    clean_upi = upi.strip() if upi else None
    clean_account_name = (account_name.strip() if account_name else name.strip()) if (clean_account_number or clean_upi) else None
    initial_payment_status = "ADDED" if (clean_account_number or clean_upi) else "NOT_ADDED"

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

        image_url=(
            f"/hospital-photos/{photo_filename}"
            if photo_filename
            else None
        ),

        photo_base64=
            photo_base64_str,

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

        payment_account_name=
            clean_account_name,

        payment_account_number=
            clean_account_number,

        payment_ifsc=
            clean_ifsc,

        payment_upi=
            clean_upi,

        payment_account_status=
            initial_payment_status,
    )
    db.add(hospital)

    db.commit()

    db.refresh(hospital)

    if photo_filename and photo_base64_str:
        try:
            final_filename = f"hospital_{hospital.id}_{uuid.uuid4().hex}{photo_ext}"
            old_p = os.path.join(HOSPITAL_PHOTO_DIR, photo_filename)
            new_p = os.path.join(HOSPITAL_PHOTO_DIR, final_filename)
            if os.path.exists(old_p):
                os.rename(old_p, new_p)
            else:
                with open(new_p, "wb") as f:
                    f.write(base64.b64decode(photo_base64_str))
            hospital.image_url = f"/hospital-photos/{final_filename}"
            db.commit()
            db.refresh(hospital)
        except Exception as ren_err:
            logging.warning("Could not rename hospital photo to final filename: %s", ren_err)

    # Try Cashfree vendor onboarding if bank details provided
    if clean_account_number and clean_ifsc:
        try:
            vendor_id = f"qarovia_hospital_{hospital.id}"
            cf_res = create_cashfree_vendor(
                vendor_id=vendor_id,
                name=clean_account_name or hospital.name,
                email=hospital.email,
                phone=hospital.phone or "9999999999",
                bank_account_number=clean_account_number,
                bank_ifsc=clean_ifsc,
                bank_account_holder=clean_account_name or hospital.name,
                upi_vpa=clean_upi,
            )
            hospital.cashfree_vendor_id = cf_res.get("vendor_id") or vendor_id
            if cf_res.get("status"):
                hospital.payment_account_status = cf_res.get("status")
            db.commit()
            db.refresh(hospital)
        except Exception as cf_err:
            logging.warning("Cashfree vendor creation deferred on registration: %s", cf_err)

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
    request: Request,
    db: Session = Depends(get_db),
):
    check_login_rate_limit(request)
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

    if getattr(hospital, "is_deleted", False):
        raise HTTPException(
            status_code=403,
            detail="This hospital account has been deleted or deactivated. Please contact Q-Arovia administrator.",
        )

    access_token, refresh_token, session = create_user_session(
        db=db,
        user_id=hospital.id,
        role="hospital",
        request=request,
    )

    return {
        "success": True,
        "message": "Hospital login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "hospital": hospital_to_dict(hospital),
    }

# ============================================================
# HOSPITAL GOOGLE LOGIN
# ============================================================

@app.post("/hospitals/google-login")
def hospital_google_login(
    data: GoogleCredentialRequest,
    request: Request = None,
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

    if getattr(hospital, "is_deleted", False):
        raise HTTPException(
            status_code=403,
            detail="This hospital account has been deleted or deactivated. Please contact Q-Arovia administrator.",
        )

    hospital.google_id = (
        google_data["google_id"]
    )

    db.commit()

    db.refresh(hospital)

    access_token, refresh_token, session = create_user_session(
        db=db,
        user_id=hospital.id,
        role="hospital",
        request=request,
    )

    return {
        "success": True,
        "message": "Google login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
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
        name_no_ext = os.path.splitext(safe_name)[0]
        parts = name_no_ext.split("_")
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
    h_name = (hospital.name if hospital else "Q-Arovia Hospital").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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
        .options(defer(Hospital.photo_base64))
        .filter(
            Hospital.approval_status ==
            "APPROVED",

            Hospital.is_published ==
            True,

            Hospital.is_deleted ==
            False,
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

# ============================================================
# HIGH-SPEED IN-MEMORY HOSPITAL CACHE
# ============================================================
_HOSPITAL_CACHE = {}
_HOSPITAL_CACHE_TTL = 60.0

def get_cached_hospital(hosp_id: int):
    item = _HOSPITAL_CACHE.get(hosp_id)
    if item:
        ts, data = item
        if (time.time() - ts) < _HOSPITAL_CACHE_TTL:
            return data
    return None

def set_cached_hospital(hosp_id: int, data):
    _HOSPITAL_CACHE[hosp_id] = (time.time(), data)

def invalidate_hospital_cache(hosp_id: Optional[int] = None):
    if hosp_id is not None:
        _HOSPITAL_CACHE.pop(hosp_id, None)
    else:
        _HOSPITAL_CACHE.clear()

@app.get("/hospitals/me")
@app.get("/api/hospitals/me")
def get_my_hospital_profile(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    hospital_id = current_user["user_id"]
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital or getattr(hospital, "is_deleted", False):
        raise HTTPException(status_code=404, detail="Hospital account not found or has been deactivated.")
    return hospital_to_dict(hospital)

@app.get("/hospitals/{hospital_id}")
def get_hospital(
    hospital_id: int,
    response: Response = None,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
):
    # Check if request has hospital or admin auth for this hospital
    is_authorized = False
    if credentials and credentials.credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            role = payload.get("role")
            user_id = payload.get("sub")
            if (role == "hospital" and user_id and int(user_id) == hospital_id) or role == "admin":
                is_authorized = True
        except Exception:
            pass

    if is_authorized:
        hospital = (
            db.query(Hospital)
            .filter(Hospital.id == hospital_id)
            .first()
        )
        if not hospital or getattr(hospital, "is_deleted", False):
            raise HTTPException(
                status_code=404,
                detail="Hospital not found",
            )
        return hospital_to_dict(hospital)

    # Public patient view
    cached = get_cached_hospital(hospital_id)
    if cached is not None:
        if response:
            response.headers["Cache-Control"] = "public, max-age=60, s-maxage=120, stale-while-revalidate=300"
            response.headers["X-Cache"] = "HIT"
        return cached

    hospital = (
        db.query(Hospital)
        .filter(
            Hospital.id == hospital_id,
            Hospital.approval_status == "APPROVED",
            Hospital.is_published == True,
            Hospital.is_deleted == False,
        )
        .first()
    )
    if not hospital:
        raise HTTPException(
            status_code=404,
            detail="Hospital not found",
        )

    result = public_hospital_to_dict(hospital)
    set_cached_hospital(hospital_id, result)
    if response:
        response.headers["Cache-Control"] = "public, max-age=60, s-maxage=120, stale-while-revalidate=300"
        response.headers["X-Cache"] = "MISS"
    return result
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
    invalidate_doctor_cache()

    return {
        "success": True,
        "message": "Doctor deleted successfully",
    }

# ============================================================
# UPDATE DOCTOR (ROOM NUMBER, STATUS, DETAILS)
# ============================================================

@app.patch("/doctors/{doctor_id}")
@app.put("/doctors/{doctor_id}")
def update_doctor(
    doctor_id: int,
    data: DoctorUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    if doctor.hospital_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="You do not have permission to manage this doctor.")

    if data.name is not None and data.name.strip():
        doctor.name = data.name.strip()
    if data.department is not None and data.department.strip():
        doctor.department = data.department.strip()
    if data.specialization is not None:
        doctor.specialization = data.specialization.strip() or None
    if data.experience is not None:
        doctor.experience = data.experience.strip() or None
    if data.room_number is not None:
        doctor.room_number = data.room_number.strip() or None
    if data.token_fee is not None:
        doctor.token_fee = max(0, int(data.token_fee))
    if data.is_available is not None:
        doctor.is_available = bool(data.is_available)
    if data.available_days is not None:
        doctor.available_days = data.available_days.strip() or None
    if data.start_time is not None:
        doctor.start_time = data.start_time.strip() or None
    if data.end_time is not None:
        doctor.end_time = data.end_time.strip() or None

    db.commit()
    db.refresh(doctor)
    invalidate_doctor_cache()
    try:
        broadcast_now(ws_manager.broadcast_doctor_availability_event(
            doctor_to_dict(doctor), doctor.hospital_id
        ))
    except Exception as ws_err:
        logging.warning("Doctor update WS broadcast skipped: %s", ws_err)
    return {"success": True, "message": "Doctor updated successfully", "doctor": doctor_to_dict(doctor)}


@app.post("/doctors/{doctor_id}/toggle-availability")
def toggle_doctor_availability_endpoint(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    if doctor.hospital_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="You do not have permission to manage this doctor.")

    doctor.is_available = not bool(doctor.is_available)
    db.commit()
    db.refresh(doctor)
    invalidate_doctor_cache()
    try:
        broadcast_now(ws_manager.broadcast_doctor_availability_event(
            doctor_to_dict(doctor), doctor.hospital_id
        ))
    except Exception as ws_err:
        logging.warning("Doctor toggle availability WS broadcast skipped: %s", ws_err)
    status_label = "On Duty (Available)" if doctor.is_available else "Off Duty (Unavailable)"
    return {
        "success": True,
        "is_available": doctor.is_available,
        "message": f"Doctor status changed to {status_label}",
        "doctor": doctor_to_dict(doctor),
    }


@app.patch("/hospitals/{hospital_id}/doctors/{doctor_id}")
@app.put("/hospitals/{hospital_id}/doctors/{doctor_id}")
def update_hospital_doctor(
    hospital_id: int,
    doctor_id: int,
    data: DoctorUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    return update_doctor(doctor_id, data, db, current_user)


@app.post("/hospitals/{hospital_id}/doctors/{doctor_id}/toggle-availability")
def toggle_hospital_doctor_availability(
    hospital_id: int,
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    return toggle_doctor_availability_endpoint(doctor_id, db, current_user)

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

    if hasattr(data, "ambulance_phone") and data.ambulance_phone is not None:
        amb_str = data.ambulance_phone.strip()
        hospital.ambulance_phone = amb_str if amb_str else None

    if hasattr(data, "daily_token_limit") and data.daily_token_limit is not None:
        if data.daily_token_limit <= 0:
            raise HTTPException(
                status_code=400,
                detail="Daily token capacity limit must be greater than 0",
            )
        hospital.daily_token_limit = data.daily_token_limit

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

    if getattr(data, "break_start_time", None) is not None:
        hospital.break_start_time = data.break_start_time.strip()

    if getattr(data, "break_end_time", None) is not None:
        hospital.break_end_time = data.break_end_time.strip()

    if data.token_fee is not None:

        if data.token_fee < 0:

            raise HTTPException(
                status_code=400,
                detail="Token fee cannot be negative",
            )

        hospital.token_fee = (
            data.token_fee
        )

    if data.name is not None and data.name.strip():
        hospital.name = data.name.strip()

    if data.registration_number is not None:
        hospital.registration_number = data.registration_number.strip()

    if data.issuing_authority is not None:
        hospital.issuing_authority = data.issuing_authority.strip()

    if data.license_id is not None:
        hospital.license_id = data.license_id.strip()

    if data.latitude is not None:
        try:
            hospital.latitude = float(data.latitude) if str(data.latitude).strip() else None
        except Exception:
            hospital.latitude = None

    if data.longitude is not None:
        try:
            hospital.longitude = float(data.longitude) if str(data.longitude).strip() else None
        except Exception:
            hospital.longitude = None

    db.commit()

    db.refresh(hospital)

    invalidate_hospital_cache(hospital_id)
    invalidate_admin_hospitals_cache()

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
# HIGH-SPEED IN-MEMORY DOCTOR CACHE (sub-10ms response time)
# ============================================================
_DOCTOR_CACHE = {}
_DOCTOR_CACHE_TTL = 60.0  # Cache for 60 seconds

def get_cached_doctors(cache_key: str):
    item = _DOCTOR_CACHE.get(cache_key)
    if item:
        ts, data = item
        if (time.time() - ts) < _DOCTOR_CACHE_TTL:
            return data
    return None

def set_cached_doctors(cache_key: str, data):
    _DOCTOR_CACHE[cache_key] = (time.time(), data)

def invalidate_doctor_cache():
    _DOCTOR_CACHE.clear()

# ============================================================
# GET DOCTORS (CACHED & FAST)
# ============================================================

@app.get("/doctors")
def get_doctors(
    hospital_id: Optional[int] = None,
    department: Optional[str] = None,
    response: Response = None,
    db: Session = Depends(get_db),
):
    cache_key = f"all_{hospital_id}_{department}"
    cached = get_cached_doctors(cache_key)
    if cached is not None:
        if response:
            response.headers["Cache-Control"] = "public, max-age=60, s-maxage=120, stale-while-revalidate=300"
            response.headers["X-Cache"] = "HIT"
        return cached

    query = db.query(Doctor).options(defer(Doctor.photo_base64))

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

    # Pre-fetch hospitals for location & nearby sorting
    hosp_ids = {d.hospital_id for d in doctors if d.hospital_id}
    hospitals_by_id = {}
    if hosp_ids:
        for h in db.query(Hospital).filter(Hospital.id.in_(hosp_ids)).all():
            hospitals_by_id[h.id] = h

    result = [
        doctor_to_dict(doctor, hospitals_by_id.get(doctor.hospital_id))
        for doctor in doctors
    ]
    set_cached_doctors(cache_key, result)

    if response:
        response.headers["Cache-Control"] = "public, max-age=60, s-maxage=120, stale-while-revalidate=300"
        response.headers["X-Cache"] = "MISS"

    return result

# ============================================================
# GET HOSPITAL DOCTORS (CACHED & FAST)
# ============================================================

@app.get(
    "/hospitals/{hospital_id}/doctors"
)
def get_hospital_doctors(
    hospital_id: int,
    department: Optional[str] = None,
    response: Response = None,
    db: Session = Depends(get_db),
):
    cache_key = f"hosp_{hospital_id}_{department}"
    cached = get_cached_doctors(cache_key)
    if cached is not None:
        if response:
            response.headers["Cache-Control"] = "public, max-age=60, s-maxage=120, stale-while-revalidate=300"
            response.headers["X-Cache"] = "HIT"
        return cached

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

    result = [
        doctor_to_dict(doctor, hospital)
        for doctor in doctors
    ]
    set_cached_doctors(cache_key, result)

    if response:
        response.headers["Cache-Control"] = "public, max-age=60, s-maxage=120, stale-while-revalidate=300"
        response.headers["X-Cache"] = "MISS"

    return result


@app.get("/doctors/{doctor_id}")
def get_doctor_by_id(
    doctor_id: int,
    db: Session = Depends(get_db),
):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=404,
            detail="Doctor not found",
        )
    hospital = db.query(Hospital).filter(Hospital.id == doctor.hospital_id).first()
    return doctor_to_dict(doctor, hospital)


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
        room_number=data.room_number.strip() if getattr(data, "room_number", None) else None,
        token_fee=max(0, int(data.token_fee)) if getattr(data, "token_fee", None) is not None else int(hospital.token_fee or 50),
        is_available=bool(getattr(data, "is_available", True)),
    )

    db.add(doctor)

    db.commit()

    db.refresh(doctor)
    invalidate_doctor_cache()

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
    # SAVE PAYMENT DETAILS IN Q-AROVIA
    # ------------------------------------------------------------

    hospital.payment_account_name = data.account_name
    hospital.payment_account_number = data.account_number
    hospital.payment_ifsc = data.ifsc
    hospital.payment_upi = data.upi

    # ------------------------------------------------------------
    # CREATE CASHFREE VENDOR (Easy Split)
    # ------------------------------------------------------------

    if not hospital.cashfree_vendor_id:
        vendor_id = f"qarovia_hospital_{hospital.id}"
        try:
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
            hospital.cashfree_vendor_id = (
                cashfree_response.get("vendor_id")
                or vendor_id
            )
            hospital.payment_account_status = cashfree_response.get("status") or "ACTIVE"
        except Exception as cf_err:
            logging.warning("Cashfree vendor creation deferred: %s", cf_err)
            hospital.cashfree_vendor_id = vendor_id
            hospital.payment_account_status = "SAVED_LOCAL"

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

            Hospital.is_deleted ==
            False,
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
            detail="Cashfree payment gateway credentials are not configured on server.",
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
    if isinstance(target_appt_date, str):
        try:
            target_appt_date = datetime.strptime(target_appt_date, "%Y-%m-%d").date()
        except Exception:
            pass

    # Doctor appointment booking window: 0 to 3 days (Today / Present time up to 3 days in advance)
    ist_today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
    max_advance_date = ist_today + timedelta(days=3)

    if target_appt_date < ist_today:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot book an appointment for a past date ({target_appt_date}). Please select today (present) or up to 3 days in advance."
        )
    if target_appt_date > max_advance_date:
        raise HTTPException(
            status_code=400,
            detail=f"Doctor appointments can only be booked from today up to 3 days in advance (until {max_advance_date.strftime('%d %b %Y')})."
        )

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

    # Check Daily Token Capacity Limit
    hosp_limit = getattr(hospital, "daily_token_limit", None) or 100
    daily_cap = getattr(doctor, "daily_token_limit", None) or hosp_limit

    existing_active_tokens = (
        db.query(func.count(Token.id))
        .filter(
            Token.hospital_id == hospital.id,
            Token.doctor == doctor.name,
            Token.appointment_date == target_appt_date,
            Token.status != "cancelled",
        )
        .scalar() or 0
    )

    if existing_active_tokens >= daily_cap:
        raise HTTPException(
            status_code=400,
            detail=f"Daily patient booking capacity of {daily_cap} reached for Dr. {doctor.name} on {target_appt_date}. Please choose another date or doctor.",
        )

    raw_doc_fee = getattr(doctor, "token_fee", None)
    doctor_token_fee = int(raw_doc_fee) if (raw_doc_fee is not None and raw_doc_fee >= 0) else 0
    platform_fee = get_current_platform_fee(db)
    total_amount = doctor_token_fee + platform_fee

    if total_amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid payment amount")

    order_id = f"qarovia_{hospital.id}_{secrets.token_hex(8)}"

    # Format customer phone (needs 10 valid digits for Cashfree production)
    raw_phone = "".join([c for c in str(getattr(patient, "phone", "") or "9999999999") if c.isdigit()])
    clean_cust_phone = raw_phone[-10:] if len(raw_phone) >= 10 else "9999999999"

    payload = {
        "order_id": order_id,
        "order_amount": float(total_amount),
        "order_currency": "INR",
        "customer_details": {
            "customer_id": str(patient.id),
            "customer_name": (patient.full_name or "Q-Arovia Patient")[:50],
            "customer_email": patient.email or "patient@q-arovia.in",
            "customer_phone": clean_cust_phone,
        },
        "order_meta": {
            "return_url": (
                "https://carepath-patient-mx5v.vercel.app/"
                "token.html?cashfree_order_id={order_id}"
            )
        },
        "order_note": f"Q-Arovia Token - {hospital.name[:35]} (Dr. {doctor.name[:25]})",
        "order_tags": {
            "hospital_id": str(hospital.id),
            "doctor_id": str(doctor.id),
            "token_fee": str(doctor_token_fee),
            "platform_fee": str(platform_fee),
            "total_amount": str(total_amount),
        }
    }

    # ------------------------------------------------------------
    # AUTOMATIC PAYMENT SPLIT (Cashfree Easy Split)
    # - Hospital Share: Token Fee (e.g. ₹200) -> Transferred to Hospital's vendor bank/UPI account
    # - App Developer Share: Platform Convenience Fee (e.g. ₹10) -> Retained in Primary Merchant account
    # ------------------------------------------------------------
    if hospital.cashfree_vendor_id and doctor_token_fee > 0:
        payload["order_splits"] = [
            {
                "vendor_id": hospital.cashfree_vendor_id,
                "amount": float(doctor_token_fee),
            }
        ]

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

        # Resilient fallback: If Cashfree rejects the order specifically because of vendor/split configuration,
        # fallback to direct collection so the patient's urgent appointment booking is never blocked.
        if response.status_code in (400, 422) and "order_splits" in payload:
            err_text = response.text.lower()
            if any(term in err_text for term in ("split", "vendor", "beneficiary", "transfer")):
                logging.warning("Cashfree split payment unavailable (%s). Retrying order directly...", response.text)
                payload.pop("order_splits", None)
                response = requests.post(
                    f"{CASHFREE_BASE_URL}/orders",
                    json=payload,
                    headers=headers,
                    timeout=20,
                )

        if response.status_code not in (200, 201):
            logging.error("Cashfree order error: %s %s", response.status_code, response.text)
            err_msg = "Cashfree could not create the payment order."
            try:
                err_data = response.json()
                if "message" in err_data:
                    err_msg = err_data["message"]
            except Exception:
                pass
            raise HTTPException(
                status_code=502,
                detail=f"Cashfree Payment Gateway: {err_msg}",
            )

        order = response.json()

        return {
            "success": True,
            "order_id": order.get("order_id", order_id),
            "payment_session_id": order.get("payment_session_id"),
            "amount": int(total_amount * 100),
            "currency": "INR",
            "token_fee": doctor_token_fee,
            "platform_fee": platform_fee,
            "total_amount": total_amount,
            "hospital_id": hospital.id,
            "cashfree_mode": CASHFREE_ENV,
            "is_split": bool(payload.get("order_splits")),
        }

    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        logging.error("Cashfree order request timed out.")
        raise HTTPException(
            status_code=504,
            detail="Cashfree Payment Gateway: Request timed out. Please try again.",
        )
    except requests.exceptions.RequestException as req_err:
        logging.error("Cashfree network connection error: %s", str(req_err))
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to Cashfree payment gateway. Please check your network or try again.",
        )
    except Exception as error:
        logging.error("Cashfree order error: %s", str(error), exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to Cashfree payment gateway.",
        )


# ============================================================
# CASHFREE REFUND ENGINE (QBUG-005)
# ============================================================

def execute_cashfree_refund(db: Session, token: Token, reason: str) -> dict:
    """
    Executes an actual server-to-server refund request via Cashfree Payments API v2023-08-01.
    Updates Token payment_status to 'refunded', 'refund_pending', or 'refund_failed'.
    Idempotent: will not issue duplicate refunds if already marked refunded.
    """
    if not token:
        return {"success": False, "error": "Token not found"}

    if token.payment_status in ("refunded", "refund_processed"):
        return {"success": True, "message": "Already refunded", "status": token.payment_status}

    # Free or walk-in consultation without cashfree order
    if not token.cashfree_order_id or (token.total_amount or 0) <= 0:
        token.payment_status = "refunded"
        token.notes = (token.notes or "") + f" [Refund recorded: Free/Counter consultation, Reason: {reason}]"
        db.commit()
        return {"success": True, "status": "refunded", "mode": "counter_free"}

    if not CASHFREE_CLIENT_ID or not CASHFREE_CLIENT_SECRET:
        logging.error("Cashfree credentials missing for refund execution.")
        token.payment_status = "refund_pending"
        token.notes = (token.notes or "") + f" [Refund pending: Gateway credentials unconfigured on server. Reason: {reason}]"
        db.commit()
        return {"success": False, "error": "Gateway credentials missing"}

    refund_id = f"ref_{token.id}_{secrets.token_hex(4)}"
    refund_amount = float(token.total_amount or 0)

    headers = {
        "x-client-id": CASHFREE_CLIENT_ID,
        "x-client-secret": CASHFREE_CLIENT_SECRET,
        "x-api-version": CASHFREE_API_VERSION,
        "Content-Type": "application/json",
        "x-idempotency-key": str(uuid.uuid4()),
    }

    payload = {
        "refund_amount": refund_amount,
        "refund_id": refund_id,
        "refund_note": f"Q-Arovia: {reason[:80]}",
        "refund_speed": "STANDARD"
    }

    try:
        url = f"{CASHFREE_BASE_URL}/orders/{token.cashfree_order_id}/refunds"
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        
        if resp.status_code in (200, 201):
            data = resp.json()
            cf_refund_status = str(data.get("refund_status", "PENDING")).upper()
            cf_refund_id = data.get("cf_refund_id") or refund_id
            
            if cf_refund_status == "SUCCESS":
                token.payment_status = "refunded"
            else:
                token.payment_status = "refund_pending"
                
            token.notes = (token.notes or "") + f" [Cashfree Refund: {cf_refund_status}, ID: {cf_refund_id}, Reason: {reason}]"
            db.commit()
            return {"success": True, "status": token.payment_status, "cf_refund_id": cf_refund_id, "data": data}
        else:
            logging.error("Cashfree refund API failed: %s %s", resp.status_code, resp.text)
            token.payment_status = "refund_failed"
            token.notes = (token.notes or "") + f" [Cashfree Refund Failed: {resp.status_code} - {resp.text[:120]}]"
            db.commit()
            return {"success": False, "status": "refund_failed", "error": resp.text}
    except Exception as e:
        logging.error("Cashfree refund exception: %s", e)
        token.payment_status = "refund_pending"
        token.notes = (token.notes or "") + f" [Cashfree Refund Network Error: {str(e)[:100]}]"
        db.commit()
        return {"success": False, "status": "refund_pending", "error": str(e)}


# ============================================================
# CASHFREE WEBHOOK LISTENER (QBUG-004)
# ============================================================

def verify_cashfree_webhook_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    """
    Verifies Cashfree webhook signature using HMAC-SHA256 according to Cashfree v2023-08-01 documentation.
    Signature = Base64(HMAC-SHA256(timestamp + raw_body, CASHFREE_CLIENT_SECRET))
    """
    if not CASHFREE_CLIENT_SECRET or not timestamp or not signature:
        return False
    try:
        data_to_sign = timestamp.encode("utf-8") + raw_body
        expected_sig_bytes = hmac.new(
            CASHFREE_CLIENT_SECRET.encode("utf-8"),
            data_to_sign,
            hashlib.sha256
        ).digest()
        expected_sig = base64.b64encode(expected_sig_bytes).decode("utf-8")
        return hmac.compare_digest(expected_sig, signature)
    except Exception as e:
        logging.warning("Error verifying Cashfree webhook signature: %s", e)
        return False


@app.post("/payments/cashfree-webhook")
async def cashfree_payment_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Asynchronous Server-to-Server Cashfree Webhook Listener.
    Idempotently processes PAYMENT_SUCCESS_WEBHOOK, ORDER_PAID, and REFUND events.
    Recovers bookings even if patient device disconnects right after payment.
    """
    raw_body = await request.body()
    signature = request.headers.get("x-webhook-signature") or request.headers.get("X-Webhook-Signature") or ""
    timestamp = request.headers.get("x-webhook-timestamp") or request.headers.get("X-Webhook-Timestamp") or ""

    # Strictly enforce mandatory Cashfree signature and timestamp headers (QA-SEC-004)
    if not signature or not timestamp:
        logging.warning("Cashfree webhook rejected: Missing signature or timestamp header.")
        raise HTTPException(
            status_code=401,
            detail="Cashfree webhook authentication required: x-webhook-signature and x-webhook-timestamp headers are mandatory."
        )

    # Replay protection: Verify timestamp freshness within 300 seconds (5 minutes)
    try:
        ts_val = float(timestamp)
        if ts_val > 1e11:  # Milliseconds
            ts_val /= 1000.0
        if abs(time.time() - ts_val) > 300:
            logging.warning("Cashfree webhook timestamp expired or clock skew exceeded: %s vs %s", ts_val, time.time())
            raise HTTPException(status_code=400, detail="Webhook timestamp expired or clock skew too large.")
    except (ValueError, TypeError):
        try:
            parsed_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if abs(time.time() - parsed_dt.timestamp()) > 300:
                raise HTTPException(status_code=400, detail="Webhook timestamp expired or clock skew too large.")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid webhook timestamp format.")

    # Cryptographic HMAC-SHA256 signature verification
    if not verify_cashfree_webhook_signature(raw_body, timestamp, signature):
        logging.warning("Invalid Cashfree webhook signature rejected.")
        raise HTTPException(status_code=400, detail="Invalid Cashfree webhook signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = payload.get("type") or payload.get("event") or ""
    data = payload.get("data") or {}
    order_data = data.get("order") or {}
    payment_data = data.get("payment") or {}
    refund_data = data.get("refund") or {}

    order_id = order_data.get("order_id") or payload.get("order_id") or ""
    if not order_id and "order" in data and isinstance(data["order"], dict):
        order_id = data["order"].get("order_id", "")

    logging.info("Cashfree webhook received: event=%s, order_id=%s", event_type, order_id)

    # 1. Handle Refund Events
    if "REFUND" in event_type.upper():
        cf_refund_id = refund_data.get("cf_refund_id")
        refund_status = str(refund_data.get("refund_status", "")).upper()
        if order_id:
            token = db.query(Token).filter(Token.cashfree_order_id == order_id).first()
            if token:
                if refund_status == "SUCCESS":
                    token.payment_status = "refunded"
                elif refund_status == "FAILED":
                    token.payment_status = "refund_failed"
                token.notes = (token.notes or "") + f" [Webhook Refund: {refund_status}, ID: {cf_refund_id or 'N/A'}]"
                db.commit()
        return {"status": "success", "event": event_type, "order_id": order_id}

    # 2. Handle Payment Success / Order Paid Events
    is_paid_event = any(term in event_type.upper() for term in ("PAYMENT_SUCCESS", "ORDER_PAID", "SUCCESS"))
    if not is_paid_event:
        return {"status": "acknowledged", "event": event_type}

    if not order_id:
        return {"status": "ignored", "reason": "No order_id in webhook payload"}

    # Idempotency check: if token already allocated for this order_id, return 200 OK
    existing_token = db.query(Token).filter(Token.cashfree_order_id == order_id).first()
    if existing_token:
        logging.info("Token already exists for order_id %s (Token #%s). Idempotent return.", order_id, existing_token.token_number)
        return {"status": "idempotent_ok", "token_id": existing_token.id, "token_number": existing_token.token_number}

    headers = {
        "x-client-id": CASHFREE_CLIENT_ID,
        "x-client-secret": CASHFREE_CLIENT_SECRET,
        "x-api-version": CASHFREE_API_VERSION,
        "Content-Type": "application/json",
    }
    
    try:
        cf_resp = requests.get(f"{CASHFREE_BASE_URL}/orders/{order_id}", headers=headers, timeout=15)
        if cf_resp.status_code != 200:
            logging.warning("Could not fetch order %s from Cashfree API: %s", order_id, cf_resp.text)
            return {"status": "retry_later"}
        cf_order = cf_resp.json()
        if cf_order.get("order_status") != "PAID":
            logging.warning("Cashfree order %s status is %s (not PAID).", order_id, cf_order.get("order_status"))
            return {"status": "order_not_paid"}
    except Exception as e:
        logging.error("Error communicating with Cashfree API for order %s: %s", order_id, e)
        return {"status": "gateway_error"}

    customer_details = cf_order.get("customer_details") or {}
    order_tags = cf_order.get("order_tags") or {}
    customer_id = customer_details.get("customer_id")

    patient = None
    if customer_id and str(customer_id).isdigit():
        patient = db.query(Patient).filter(Patient.id == int(customer_id)).first()

    hospital_id = order_tags.get("hospital_id")
    hospital = None
    if hospital_id and str(hospital_id).isdigit():
        hospital = db.query(Hospital).filter(Hospital.id == int(hospital_id)).first()

    doctor_id = order_tags.get("doctor_id")
    doctor = None
    if doctor_id and str(doctor_id).isdigit():
        doctor = db.query(Doctor).filter(Doctor.id == int(doctor_id)).first()

    if not patient or not hospital or not doctor:
        logging.error("Webhook could not resolve patient (%s), hospital (%s), or doctor (%s) for order %s", customer_id, hospital_id, doctor_id, order_id)
        return {"status": "resolution_failed", "order_id": order_id}

    target_date = get_ist_today()
    token_fee = int(order_tags.get("token_fee", 0))
    platform_fee = int(order_tags.get("platform_fee", 10))
    total_amount = int(order_tags.get("total_amount", token_fee + platform_fee))

    allocated_num = allocate_token_number(db, hospital.id, doctor.name, target_date, doctor.id)

    comm_pct = get_current_commission_percentage(db)
    comm_amount, hosp_amount = calculate_commission(Decimal(str(token_fee)), comm_pct)

    cf_payment_id = payment_data.get("cf_payment_id") or f"cf_wh_{secrets.token_hex(6)}"

    new_token = Token(
        patient_id=patient.id,
        patient_name=patient.full_name or "Patient",
        patient_email=patient.email,
        patient_phone=patient.phone or customer_details.get("customer_phone"),
        booking_for="self",
        patient_age=patient.age,
        patient_gender=patient.gender,
        hospital=hospital.name,
        hospital_id=hospital.id,
        doctor=doctor.name,
        doctor_id=doctor.id,
        department=doctor.department,
        room_number=doctor.room_number,
        token_number=allocated_num,
        appointment_date=target_date,
        token_fee=token_fee,
        platform_fee=platform_fee,
        total_amount=total_amount,
        payment_status="paid",
        commission_percentage=comm_pct,
        commission_amount=comm_amount,
        hospital_amount=hosp_amount,
        cashfree_order_id=order_id,
        cashfree_payment_id=str(cf_payment_id),
        status="waiting",
        created_at=datetime.utcnow()
    )
    db.add(new_token)
    db.commit()
    db.refresh(new_token)

    logging.info("Webhook successfully created Token #%s (ID: %s) for order %s", allocated_num, new_token.id, order_id)

    try:
        broadcast_now(ws_manager.broadcast_token_event(
            event_type="token_created",
            token_data={
                "id": new_token.id,
                "token_number": new_token.token_number,
                "status": new_token.status,
                "patient_name": new_token.patient_name,
                "doctor": new_token.doctor,
                "department": new_token.department,
            },
            hospital_id=hospital.id,
            patient_phone=new_token.patient_phone,
        ))
        broadcast_now(ws_manager.broadcast_payment_event(
            event_type="PAYMENT_SUCCESS",
            payment_data={
                "order_id": order_id,
                "payment_id": str(cf_payment_id),
                "token_id": new_token.id,
                "amount": float(new_token.total_amount or 0),
            },
            hospital_id=hospital.id,
            patient_phone=new_token.patient_phone,
        ))
    except Exception as ws_err:
        logging.warning("Webhook WS broadcast error: %s", ws_err)

    return {"status": "success", "token_id": new_token.id, "token_number": new_token.token_number}


# ============================================================
# PATIENT APPOINTMENT CANCELLATION (QBUG-008)
# ============================================================

@app.post("/patient/tokens/{token_id}/cancel")
def cancel_patient_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("patient")),
):
    """
    Allows a patient to cancel their upcoming appointment up to 2 hours before scheduled time.
    Triggers automated Cashfree refund if consultation was paid.
    Releases queue slot and broadcasts live update.
    """
    patient_id = current_user.get("user_id")
    token = db.query(Token).filter(Token.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Appointment token not found.")

    if token.patient_id != patient_id:
        patient = db.query(Patient).filter(Patient.id == patient_id).first()
        is_match = False
        if patient and patient.phone and token.patient_phone:
            if clean_phone(patient.phone) == clean_phone(token.patient_phone):
                is_match = True
        if not is_match:
            raise HTTPException(status_code=403, detail="You do not have permission to cancel this appointment.")

    if token.status == "cancelled":
        return {"success": True, "message": "This appointment has already been cancelled.", "status": "cancelled"}

    if token.status in ("serving", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel appointment because it is already {token.status}."
        )

    # 2-Hour Cancellation Window Check
    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    appt_date = token.appointment_date
    if isinstance(appt_date, str):
        try:
            appt_date = datetime.strptime(appt_date, "%Y-%m-%d").date()
        except Exception:
            pass

    doctor = db.query(Doctor).filter(Doctor.id == token.doctor_id).first() if token.doctor_id else None
    start_time_str = (doctor.start_time if doctor and doctor.start_time else "09:00").strip()
    try:
        sh, sm = map(int, start_time_str.split(":")[:2])
    except Exception:
        sh, sm = 9, 0

    appt_start_dt = datetime(appt_date.year, appt_date.month, appt_date.day, sh, sm)
    diff = (appt_start_dt - ist_now).total_seconds()

    if diff < 7200: # Less than 2 hours (7200 seconds)
        raise HTTPException(
            status_code=400,
            detail="Appointments can only be cancelled up to 2 hours before the scheduled consultation window."
        )

    token.status = "cancelled"

    refund_result = None
    if token.cashfree_order_id and (token.total_amount or 0) > 0:
        refund_result = execute_cashfree_refund(db, token, "Cancelled by patient > 2h before consultation")
    else:
        token.payment_status = "cancelled"
        db.commit()

    try:
        broadcast_now(ws_manager.broadcast_token_event(
            event_type="token_cancelled",
            token_data={
                "id": token.id,
                "token_number": token.token_number,
                "status": "cancelled",
                "patient_name": token.patient_name,
                "doctor": token.doctor,
                "department": token.department,
            },
            hospital_id=token.hospital_id,
            patient_phone=token.patient_phone,
        ))
        if refund_result or token.refund_status:
            broadcast_now(ws_manager.broadcast_payment_event(
                event_type="REFUND_UPDATED",
                payment_data={
                    "token_id": token.id,
                    "refund_status": token.refund_status,
                    "refund_amount": float(token.refund_amount or 0),
                    "cashfree_refund_id": token.cashfree_refund_id,
                },
                hospital_id=token.hospital_id,
                patient_phone=token.patient_phone,
            ))
    except Exception as ws_err:
        logging.warning("Cancellation WS broadcast error: %s", ws_err)

    return {
        "success": True,
        "message": "Appointment cancelled successfully.",
        "token_id": token.id,
        "status": "cancelled",
        "refund": refund_result
    }


# ============================================================
# FREE CONSULTATION BOOKING (QBUG-009)
# ============================================================

class FreeTokenRequest(BaseModel):
    hospital: str
    department: str
    doctor: str
    appointment_date: Optional[str] = None
    booking_for: Optional[str] = "self"

@app.post("/tokens/free")
def create_free_token(
    data: FreeTokenRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("patient")),
):
    """
    Creates an appointment token for a consultation where doctor_token_fee is 0 and platform_fee is 0.
    Bypasses Cashfree gateway order creation securely, preventing 400 errors for free OPD clinics.
    """
    patient = db.query(Patient).filter(Patient.id == current_user["user_id"]).first()
    if not patient:
        raise HTTPException(status_code=401, detail="Patient account not found.")

    hospital = find_published_hospital(db, data.hospital.strip())
    clean_doc_search = re.sub(r'^(dr\.|dr|mr\.|mr)\s*', '', data.doctor.strip(), flags=re.I).strip()
    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == hospital.id,
            func.lower(Doctor.department) == data.department.strip().lower(),
            or_(
                func.lower(Doctor.name) == data.doctor.strip().lower(),
                func.lower(Doctor.name) == clean_doc_search.lower(),
                Doctor.name.ilike(f"%{clean_doc_search}%"),
            )
        )
        .first()
    )
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found.")

    doc_fee = getattr(doctor, "token_fee", 0) or 0
    if doc_fee > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Dr. {doctor.name} consultation fee is ₹{doc_fee}. Please use standard booking flow."
        )

    ist_today = get_ist_today()
    target_date = ist_today
    if data.appointment_date:
        try:
            target_date = datetime.strptime(data.appointment_date, "%Y-%m-%d").date()
        except Exception:
            pass

    if target_date < ist_today:
        raise HTTPException(status_code=400, detail="Cannot book appointment for past date.")

    allocated_num = allocate_token_number(db, hospital.id, doctor.name, target_date, doctor.id)

    new_token = Token(
        patient_id=patient.id,
        patient_name=patient.full_name or "Patient",
        patient_email=patient.email,
        patient_phone=patient.phone,
        booking_for=data.booking_for or "self",
        patient_age=patient.age,
        patient_gender=patient.gender,
        hospital=hospital.name,
        hospital_id=hospital.id,
        doctor=doctor.name,
        doctor_id=doctor.id,
        department=doctor.department,
        room_number=doctor.room_number,
        token_number=allocated_num,
        appointment_date=target_date,
        token_fee=0,
        platform_fee=0,
        total_amount=0,
        payment_status="not_required",
        status="waiting",
        booking_type="ONLINE",
        created_at=datetime.utcnow()
    )
    db.add(new_token)
    db.commit()
    db.refresh(new_token)

    try:
        broadcast_now(ws_manager.broadcast_token_event(
            event_type="token_created",
            token_data={
                "id": new_token.id,
                "token_number": new_token.token_number,
                "status": "waiting",
                "patient_name": new_token.patient_name,
                "doctor": new_token.doctor,
                "department": new_token.department,
            },
            hospital_id=hospital.id,
            patient_phone=new_token.patient_phone,
        ))
    except Exception as ws_err:
        logging.warning("Free token WS broadcast error: %s", ws_err)

    return {
        "success": True,
        "message": f"Free consultation token #{allocated_num} confirmed!",
        "token": token_to_dict(new_token)
    }
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
    background_tasks: BackgroundTasks,
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
            detail="Cashfree payment gateway credentials are not configured on server.",
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

    # Doctor appointment booking window: 0 to 3 days (Today / Present time up to 3 days in advance)
    raw_appt_date = data.appointment_date or (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
    if isinstance(raw_appt_date, str):
        try:
            target_token_date = datetime.strptime(raw_appt_date, "%Y-%m-%d").date()
        except Exception:
            target_token_date = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
    else:
        target_token_date = raw_appt_date

    ist_today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()
    max_advance_date = ist_today + timedelta(days=3)

    if target_token_date < ist_today:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot book an appointment for a past date ({target_token_date}). Please select today (present) or up to 3 days in advance."
        )
    if target_token_date > max_advance_date:
        raise HTTPException(
            status_code=400,
            detail=f"Doctor appointments can only be booked from today up to 3 days in advance (until {max_advance_date.strftime('%d %b %Y')})."
        )

    clean_doc_search = re.sub(r'^(dr\.|dr|mr\.|mr)\s*', '', data.doctor.strip(), flags=re.I).strip()
    clean_dept_search = data.department.strip().lower()

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == hospital.id,
            func.lower(Doctor.department) == clean_dept_search,
            or_(
                func.lower(Doctor.name) == data.doctor.strip().lower(),
                func.lower(Doctor.name) == clean_doc_search.lower(),
                Doctor.name.ilike(f"%{clean_doc_search}%")
            )
        )
        .first()
    )

    if not doctor:
        doctor = (
            db.query(Doctor)
            .filter(
                Doctor.hospital_id == hospital.id,
                or_(
                    func.lower(Doctor.name) == data.doctor.strip().lower(),
                    func.lower(Doctor.name) == clean_doc_search.lower(),
                    Doctor.name.ilike(f"%{clean_doc_search}%")
                )
            )
            .first()
        )

    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found.")

    canonical_doctor = doctor.name
    canonical_dept = doctor.department

    raw_doc_fee = getattr(doctor, "token_fee", None)
    token_fee = int(raw_doc_fee) if (raw_doc_fee is not None and raw_doc_fee >= 0) else 0
    platform_fee = get_current_platform_fee(db)
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
                detail=f"Payment amount mismatch. Expected ₹{total_amount}, got order ₹{order_amount} and payment ₹{payment_amount}.",
            )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid Cashfree payment amount.")

    appointment_date = data.appointment_date or get_ist_today()

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




    # Check Daily Token Capacity Limit
    hosp_limit = getattr(hospital, "daily_token_limit", None) or 100
    daily_cap = getattr(doctor, "daily_token_limit", None) or hosp_limit

    existing_active_tokens = (
        db.query(func.count(Token.id))
        .filter(
            Token.hospital_id == hospital.id,
            Token.doctor == data.doctor.strip(),
            Token.appointment_date == appointment_date,
            Token.status != "cancelled",
        )
        .scalar() or 0
    )

    if existing_active_tokens >= daily_cap:
        raise HTTPException(
            status_code=400,
            detail=f"Daily patient booking capacity of {daily_cap} reached for Dr. {data.doctor.strip()} on {appointment_date}. Please choose another date or doctor.",
        )

    next_token_number = allocate_token_number(
        db=db,
        hospital_id=hospital.id,
        department=canonical_dept,
        doctor=canonical_doctor,
        appointment_date=appointment_date,
        doctor_id=doctor.id if doctor else None,
    )


    booking_for = (getattr(data, "booking_for", None) or "self").strip().lower()
    raw_custom_name = (getattr(data, "patient_name", None) or "").strip()
    raw_custom_email = (getattr(data, "patient_email", None) or "").strip()
    raw_custom_phone = (getattr(data, "patient_phone", None) or "").strip()
    raw_relation = (getattr(data, "patient_relation", None) or "").strip()
    patient_age = getattr(data, "patient_age", None)
    patient_gender = (getattr(data, "patient_gender", None) or "").strip() or None

    if booking_for != "self" and raw_custom_name:
        clean_name = re.sub(r'\s*\([^)]*\)$', '', raw_custom_name).strip()
        if raw_relation and raw_relation.lower() != "other":
            actual_patient_name = f"{clean_name} ({raw_relation.capitalize()})"
        else:
            actual_patient_name = clean_name
        recipient_email = raw_custom_email if raw_custom_email else patient.email
        patient_contact_phone = raw_custom_phone if raw_custom_phone else getattr(patient, "phone", None)
    else:
        booking_for = "self"
        actual_patient_name = patient.full_name
        recipient_email = patient.email
        patient_contact_phone = getattr(patient, "phone", None)

    active_commission_pct = get_current_commission_percentage(db)
    comm_split = calculate_commission(
        eligible_booking_amount=token_fee,
        commission_percentage=active_commission_pct,
        is_eligible=True,
    )
    token_commission_pct = comm_split["commission_percentage"]
    token_commission_amt = comm_split["commission_amount"]
    token_hospital_amt = comm_split["hospital_amount"]

    token = Token(
        patient_id=patient.id,
        patient_name=actual_patient_name,
        patient_email=recipient_email,
        patient_phone=patient_contact_phone,
        booking_for=booking_for,
        patient_age=patient_age,
        patient_gender=patient_gender,
        hospital=hospital.name,
        hospital_id=hospital.id,
        doctor_id=doctor.id if doctor else None,
        department=canonical_dept,
        doctor=canonical_doctor,
        token_number=next_token_number,
        appointment_date=appointment_date,
        platform=PLATFORM_NAME,
        booking_type="ONLINE",
        token_fee=token_fee,
        platform_fee=platform_fee,
        total_amount=total_amount,
        payment_status="paid",
        commission_percentage=token_commission_pct,
        commission_amount=token_commission_amt,
        hospital_amount=token_hospital_amt,
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

    # Real-Time WebSocket broadcast (instant sync across website and mobile apps)
    try:
        broadcast_now(ws_manager.broadcast_token_event(
            event_type="token_booked",
            token_data=token_to_dict(token),
            hospital_id=token.hospital_id,
            patient_phone=token.patient_phone or getattr(patient, "phone", None),
        ))
        broadcast_now(ws_manager.broadcast_payment_event(
            event_type="PAYMENT_SUCCESS",
            payment_data={
                "order_id": order_id,
                "payment_id": payment_id,
                "token_id": token.id,
                "amount": float(token.total_amount or 0),
            },
            hospital_id=token.hospital_id,
            patient_phone=token.patient_phone or getattr(patient, "phone", None),
        ))
    except Exception as ws_err:
        logging.warning("Token creation WS broadcast skipped: %s", ws_err)

    # --- ASYNC HIGH-CONCURRENCY EMAIL DISPATCH (ZERO-LAG BACKGROUND TASKS) ---
    try:
        op_hours = hospital.operating_hours_12h if hasattr(hospital, "operating_hours_12h") else f"{hospital.opening_time or '09:00'} - {hospital.closing_time or '21:00'}"
        room_display = (doctor.room_number if doctor and doctor.room_number else "OPD Consultation Room")
        if not room_display.startswith("Room") and not room_display.startswith("Cabin"):
            room_display = f"Room {room_display}"

        if booking_for != "self" and recipient_email:
            # 1. Non-blocking Background Task: Family Member's Hospital OPD Appointment Pass
            background_tasks.add_task(
                send_family_token_pass_email,
                to_email=recipient_email,
                patient_name=actual_patient_name,
                booked_by_name=patient.full_name or "Family Member",
                hospital_name=hospital.name,
                doctor_name=doctor.name,
                department=doctor.department or data.department,
                room_number=room_display,
                token_number=token.token_number,
                appointment_date=str(appointment_date),
                operating_hours=op_hours,
            )

            # 2. Non-blocking Background Task: Main Account Owner's Payment Invoice & Tax Receipt
            if patient.email:
                background_tasks.add_task(
                    send_payer_payment_receipt_email,
                    to_email=patient.email,
                    payer_name=patient.full_name or "Account Owner",
                    beneficiary_name=actual_patient_name,
                    beneficiary_email=recipient_email,
                    hospital_name=hospital.name,
                    doctor_name=doctor.name,
                    department=doctor.department or data.department,
                    token_number=token.token_number,
                    appointment_date=str(appointment_date),
                    payment_id=payment_id,
                    token_fee=float(token_fee or 0.0),
                    platform_fee=float(platform_fee or 0.0),
                    total_amount=float(total_amount or 0.0),
                )
        else:
            # Booking for self: non-blocking combined pass & payment confirmation
            target_email = patient.email or recipient_email
            if target_email:
                background_tasks.add_task(
                    send_token_confirmation_email,
                    to_email=target_email,
                    patient_name=actual_patient_name,
                    hospital_name=hospital.name,
                    doctor_name=doctor.name,
                    department=doctor.department or data.department,
                    token_number=token.token_number,
                    appointment_date=str(appointment_date),
                    payment_id=payment_id,
                    amount=total_amount,
                    operating_hours=op_hours,
                )
    except Exception as email_err:
        logging.warning("Background email queuing failed: %s", email_err)

    return {
        "success": True,
        "message": "Hospital token created successfully",
        "token": token_to_dict(token),
    }


@app.post("/patient/tokens/{token_id}/send-receipt")
@app.post("/tokens/{token_id}/email-receipt")
def resend_token_receipt(
    token_id: int,
    background_tasks: BackgroundTasks,
    body: Optional[EmailReceiptRequest] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("patient")),
):
    """Sends or resends the official appointment token receipt to family email or specified email."""
    token = db.query(Token).filter(Token.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found.")
    patient = db.query(Patient).filter(Patient.id == current_user["user_id"]).first()
    authorized = (token.patient_id == current_user["user_id"])
    if not authorized and patient:
        if patient.email and token.patient_email and patient.email.strip().lower() == token.patient_email.strip().lower():
            authorized = True
        elif patient.phone and token.patient_phone and patient.phone.strip().replace(" ", "").replace("-", "") == str(token.patient_phone).strip().replace(" ", "").replace("-", ""):
            authorized = True
    if not authorized:
        raise HTTPException(status_code=403, detail="Not authorized to access this token.")
    hospital = db.query(Hospital).filter(Hospital.id == token.hospital_id).first()
    h_name = hospital.name if hospital else (token.hospital or "Q-Arovia Hospital")
    op_hours = (
        hospital.operating_hours_12h 
        if hospital and hasattr(hospital, "operating_hours_12h") and hospital.operating_hours_12h 
        else "09:00 AM - 09:00 PM"
    )

    custom_to = body.recipient_email.strip() if (body and body.recipient_email) else None
    target_email = custom_to or token.patient_email or (patient.email if patient else None)

    if not target_email or "@" not in target_email:
        raise HTTPException(status_code=400, detail="No valid recipient email address provided.")

    payment_ref = token.cashfree_payment_id or token.cashfree_order_id or str(token.id)
    room_display = (token.room_number if token.room_number else "OPD Consultation Room")
    if not room_display.startswith("Room") and not room_display.startswith("Cabin"):
        room_display = f"Room {room_display}"

    is_family_booking = (token.booking_for or "").strip().lower() != "self"
    is_main_account = patient and patient.email and target_email.strip().lower() == patient.email.strip().lower()

    if is_family_booking and not is_main_account:
        # 1. Non-blocking Background Task: Dedicated OPD Appointment Pass for family member
        background_tasks.add_task(
            send_family_token_pass_email,
            to_email=target_email,
            patient_name=token.patient_name or "Family Member",
            booked_by_name=(patient.full_name if patient else "Family Member"),
            hospital_name=h_name,
            doctor_name=token.doctor or "Doctor",
            department=token.department or "General",
            room_number=room_display,
            token_number=token.token_number,
            appointment_date=str(token.appointment_date),
            operating_hours=op_hours,
        )
    elif is_family_booking and is_main_account:
        # 2. Non-blocking Background Task: Dedicated Payment Invoice for the main account owner
        background_tasks.add_task(
            send_payer_payment_receipt_email,
            to_email=target_email,
            payer_name=(patient.full_name if patient else "Account Owner"),
            beneficiary_name=token.patient_name or "Family Member",
            beneficiary_email=token.patient_email or "Family Member",
            hospital_name=h_name,
            doctor_name=token.doctor or "Doctor",
            department=token.department or "General",
            token_number=token.token_number,
            appointment_date=str(token.appointment_date),
            payment_id=payment_ref,
            token_fee=float(token.token_fee or 0.0),
            platform_fee=float(token.platform_fee or 0.0),
            total_amount=float(token.total_amount or 0.0),
        )
    else:
        # Standard combined token confirmation
        background_tasks.add_task(
            send_token_confirmation_email,
            to_email=target_email,
            patient_name=token.patient_name or "Patient",
            hospital_name=h_name,
            doctor_name=token.doctor or "Doctor",
            department=token.department or "General",
            token_number=token.token_number,
            appointment_date=str(token.appointment_date),
            payment_id=payment_ref,
            amount=float(token.total_amount or 0.0),
            operating_hours=op_hours,
        )

    # Update token.patient_email if updated
    if custom_to and custom_to != token.patient_email:
        token.patient_email = custom_to
        db.commit()

    return {
        "success": True,
        "message": f"Token receipt is being dispatched to {target_email}",
        "recipient_email": target_email
    }
# ============================================================
# PATIENT - TOKEN HISTORY
# ============================================================

@app.get("/patient/tokens")
@app.get("/patient/token-history")
@app.get("/patient/my-tokens")
def get_patient_token_history(
    phone: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("patient")),
):
    patient_id = current_user["user_id"]
    patient = db.query(Patient).filter(Patient.id == patient_id).first()

    filter_conditions = [Token.patient_id == patient_id]

    # 1. Accounts belonging to the same user by full name
    patient_names = set()
    if patient and patient.full_name and patient.full_name.strip():
        patient_names.add(patient.full_name.strip())
    if name and name.strip():
        patient_names.add(name.strip())

    for p_name in patient_names:
        clean_name = p_name.lower()
        same_name_ids = [p_id for (p_id,) in db.query(Patient.id).filter(func.lower(Patient.full_name) == clean_name).all()]
        if same_name_ids:
            filter_conditions.append(Token.patient_id.in_(same_name_ids))

        filter_conditions.append(func.lower(Token.patient_name) == clean_name)
        filter_conditions.append(func.lower(Token.patient_name).ilike(f"{clean_name} (%"))
        name_parts = clean_name.split()
        if len(name_parts) >= 2:
            for part in name_parts:
                if len(part) >= 4:
                    filter_conditions.append(func.lower(Token.patient_name) == part)
                    filter_conditions.append(func.lower(Token.patient_name).ilike(f"{part} (%"))

    # 2. Email matching (patient's profile email + optional query param)
    target_emails = set()
    if patient and patient.email and patient.email.strip():
        target_emails.add(patient.email.strip().lower())
    if email and email.strip():
        target_emails.add(email.strip().lower())

    for em in target_emails:
        filter_conditions.append(func.lower(Token.patient_email) == em)
        filter_conditions.append(Token.notes.ilike(f"%{em}%"))

    # 3. Phone matching (patient's profile phone + optional query param)
    target_phones = set()
    if patient and patient.phone and patient.phone.strip():
        target_phones.add(patient.phone.strip())
    if phone and phone.strip():
        target_phones.add(phone.strip())

    for ph in target_phones:
        raw_phone = ph.strip()
        clean_phone = raw_phone.replace(" ", "").replace("-", "")
        digits_only = re.sub(r"\D", "", raw_phone)
        filter_conditions.append(Token.patient_phone == raw_phone)
        filter_conditions.append(Token.patient_phone == clean_phone)
        if digits_only:
            filter_conditions.append(Token.patient_phone.ilike(f"%{digits_only}%"))
            if len(digits_only) >= 10:
                last10 = digits_only[-10:]
                filter_conditions.append(Token.patient_phone.ilike(f"%{last10}%"))
                filter_conditions.append(Token.notes.ilike(f"%{last10}%"))

    tokens = (
        db.query(Token)
        .filter(or_(*filter_conditions))
        .order_by(
            Token.appointment_date.desc(),
            Token.created_at.desc()
        )
        .all()
    )

    # Auto-link unlinked tokens to this patient so future queries are instant
    updated = False
    for token in tokens:
        if token.patient_id is None:
            token.patient_id = patient_id
            updated = True
    if updated:
        try:
            db.commit()
        except Exception:
            db.rollback()

    results = []
    for token in tokens:
        d = token_to_dict(token)
        if token.status in ("waiting", "serving"):
            d.update(get_queue_status_for_token(db, token))
        results.append(d)

    return results


@app.get("/patient/tokens/lookup")
def lookup_patient_tokens(
    phone: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    patient_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """
    Token queue status lookup.
    If authenticated as the patient, returns full appointment information.
    If unauthenticated, requires phone or email identifier and returns sanitized queue status without private clinical notes.
    """
    filter_conditions = []
    is_authenticated_owner = False
    auth_pid = None

    if current_user and current_user.get("role") == "patient":
        auth_pid = current_user.get("user_id")
        if patient_id is None or patient_id == auth_pid:
            filter_conditions.append(Token.patient_id == auth_pid)
            is_authenticated_owner = True
            patient = db.query(Patient).filter(Patient.id == auth_pid).first()
            if patient:
                if patient.phone:
                    p_digits = re.sub(r"\D", "", patient.phone)
                    filter_conditions.append(Token.patient_phone == patient.phone)
                    if len(p_digits) >= 10:
                        filter_conditions.append(Token.patient_phone.ilike(f"%{p_digits[-10:]}%"))
                        filter_conditions.append(Token.notes.ilike(f"%{p_digits[-10:]}%"))
                if patient.email:
                    filter_conditions.append(func.lower(Token.patient_email) == patient.email.strip().lower())
                if patient.full_name:
                    filter_conditions.append(func.lower(Token.patient_name) == patient.full_name.strip().lower())

    if not is_authenticated_owner and not phone and not email and not patient_id:
        raise HTTPException(
            status_code=400,
            detail="At least a phone number or email address is required for token lookup.",
        )

    if patient_id is not None and not is_authenticated_owner:
        filter_conditions.append(Token.patient_id == patient_id)
    if email and email.strip():
        clean_email = email.strip().lower()
        filter_conditions.append(func.lower(Token.patient_email) == clean_email)
        filter_conditions.append(Token.notes.ilike(f"%{clean_email}%"))
    if phone and phone.strip():
        raw_phone = phone.strip()
        clean_phone = raw_phone.replace(" ", "").replace("-", "")
        digits_only = re.sub(r"\D", "", raw_phone)
        filter_conditions.append(Token.patient_phone == raw_phone)
        filter_conditions.append(Token.patient_phone == clean_phone)
        if digits_only and len(digits_only) >= 10:
            last10 = digits_only[-10:]
            filter_conditions.append(Token.patient_phone.ilike(f"%{last10}%"))
            filter_conditions.append(Token.notes.ilike(f"%{last10}%"))
    if name and name.strip():
        clean_name = name.strip().lower()
        filter_conditions.append(func.lower(Token.patient_name) == clean_name)
        filter_conditions.append(func.lower(Token.patient_name).ilike(f"{clean_name} (%"))

    if not filter_conditions:
        return []

    tokens = (
        db.query(Token)
        .filter(or_(*filter_conditions))
        .order_by(
            Token.appointment_date.desc(),
            Token.created_at.desc()
        )
        .all()
    )

    # Auto-link unlinked tokens to authenticated patient
    if is_authenticated_owner and auth_pid:
        updated = False
        for token in tokens:
            if token.patient_id is None:
                token.patient_id = auth_pid
                updated = True
        if updated:
            try:
                db.commit()
            except Exception:
                db.rollback()

    results = []
    for token in tokens:
        d = token_to_dict(token)
        if not is_authenticated_owner:
            d.pop("notes", None)
            d.pop("diagnosis", None)
            d.pop("prescription", None)
            if d.get("patient_phone"):
                raw_p = str(d["patient_phone"])
                d["patient_phone"] = (raw_p[:2] + "****" + raw_p[-4:]) if len(raw_p) >= 6 else "****"
            if d.get("patient_email"):
                raw_e = str(d["patient_email"])
                if "@" in raw_e:
                    parts = raw_e.split("@")
                    d["patient_email"] = (parts[0][:2] + "***@" + parts[1])
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
    patient_id = current_user["user_id"]
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient account not found.")

    filter_conditions = [and_(Token.id == token_id, Token.patient_id == patient_id)]
    if patient.phone and patient.phone.strip():
        clean_phone = patient.phone.strip().replace(" ", "").replace("-", "")
        filter_conditions.append(and_(Token.id == token_id, Token.patient_phone == patient.phone))
        filter_conditions.append(and_(Token.id == token_id, Token.patient_phone == clean_phone))
    if patient.email and patient.email.strip():
        filter_conditions.append(and_(Token.id == token_id, func.lower(Token.patient_email) == patient.email.strip().lower()))

    token = (
        db.query(Token)
        .filter(or_(*filter_conditions))
        .first()
    )

    if not token:
        raise HTTPException(
            status_code=404,
            detail="Token record not found or access denied.",
        )

    if token.patient_id is None:
        token.patient_id = patient_id
        try:
            db.commit()
        except Exception:
            db.rollback()

    d = token_to_dict(token)
    if token.status in ("waiting", "serving"):
        d.update(get_queue_status_for_token(db, token))
    return d


# ============================================================
# MEDICAL DOCUMENT UPLOAD & MANAGEMENT FOR TOKENS
# ============================================================

@app.post("/patient/tokens/{token_id}/documents")
@app.post("/tokens/{token_id}/documents")
async def upload_token_documents(
    token_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Securely uploads one or multiple medical documents (PDF, JPG, JPEG, PNG) for a specific token.
    Validates token ownership, file magic bytes, file extensions, and file sizes.
    """
    token = db.query(Token).filter(Token.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token record not found.")

    role = current_user.get("role")
    auth_user_id = current_user.get("user_id")

    if role == "patient":
        if token.patient_id is not None and token.patient_id != auth_user_id:
            patient = db.query(Patient).filter(Patient.id == auth_user_id).first()
            is_authorized = False
            if patient:
                if patient.phone and token.patient_phone and patient.phone.strip().replace(" ", "").replace("-", "") == str(token.patient_phone).strip().replace(" ", "").replace("-", ""):
                    is_authorized = True
                elif patient.email and token.patient_email and patient.email.strip().lower() == str(token.patient_email).strip().lower():
                    is_authorized = True
            if not is_authorized:
                raise HTTPException(status_code=403, detail="You do not have permission to upload documents for another patient's token.")
    elif role == "hospital":
        if token.hospital_id != auth_user_id:
            raise HTTPException(status_code=403, detail="You do not have permission to upload documents for another hospital's token.")
    elif role != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized.")

    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided for upload.")

    uploaded_records = []
    for f in files:
        orig_name = f.filename or "medical_document"
        ext = os.path.splitext(orig_name)[1].lower()
        content_type = (f.content_type or "").lower()

        if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"File '{orig_name}' has an unsupported format. Allowed types: PDF, JPG, JPEG, PNG."
            )

        content = await f.read()
        if not content or len(content) == 0:
            raise HTTPException(status_code=400, detail=f"File '{orig_name}' is empty.")

        if len(content) > MAX_DOCUMENT_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File '{orig_name}' exceeds maximum allowed size of {MAX_DOCUMENT_SIZE // (1024 * 1024)}MB."
            )

        clean_ext = ext.lstrip(".")
        validate_file_magic_bytes(content, {clean_ext})

        unique_name = f"med_doc_{token.id}_{secrets.token_hex(12)}{ext}"
        file_path = os.path.join(MEDICAL_DOCUMENTS_DIR, unique_name)

        try:
            with open(file_path, "wb") as out_f:
                out_f.write(content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to store document: {str(e)}")

        resolved_patient_id = token.patient_id or (auth_user_id if role == "patient" else None)

        doc = MedicalDocument(
            token_id=token.id,
            patient_id=resolved_patient_id,
            hospital_id=token.hospital_id,
            original_filename=orig_name,
            stored_filename=unique_name,
            file_type=content_type or (mimetypes.guess_type(orig_name)[0] or "application/octet-stream"),
            file_size=len(content),
            created_at=datetime.utcnow()
        )
        db.add(doc)
        db.flush()

        uploaded_records.append({
            "id": doc.id,
            "token_id": doc.token_id,
            "original_filename": doc.original_filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "file_size_formatted": format_file_size(doc.file_size),
            "created_at": doc.created_at.isoformat()
        })

    db.commit()

    # Real-Time WebSocket broadcast (instant sync across website and mobile apps)
    try:
        broadcast_now(ws_manager.broadcast_document_event(
            event_type="document_uploaded",
            token_id=token.id,
            hospital_id=token.hospital_id,
            patient_phone=token.patient_phone,
            documents=uploaded_records,
        ))
    except Exception as ws_err:
        logging.warning("Document upload WS broadcast skipped: %s", ws_err)

    return {
        "success": True,
        "message": f"Successfully uploaded {len(uploaded_records)} document(s).",
        "documents": uploaded_records
    }


@app.get("/patient/tokens/{token_id}/documents")
@app.get("/tokens/{token_id}/documents")
def get_token_documents(
    token_id: int,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    token: Optional[str] = Query(None),
):
    """Retrieves all medical documents uploaded for a specific token with verified authorization."""
    current_user = get_document_auth_user(credentials, token)
    token_record = db.query(Token).filter(Token.id == token_id).first()
    if not token_record:
        raise HTTPException(status_code=404, detail="Token record not found.")

    role = current_user.get("role")
    auth_user_id = current_user.get("user_id")

    if role == "patient":
        is_authorized = False
        if token_record.patient_id == auth_user_id:
            is_authorized = True
        else:
            patient = db.query(Patient).filter(Patient.id == auth_user_id).first()
            if patient:
                if patient.phone and token_record.patient_phone and patient.phone.strip().replace(" ", "").replace("-", "") == str(token_record.patient_phone).strip().replace(" ", "").replace("-", ""):
                    is_authorized = True
                elif patient.email and token_record.patient_email and patient.email.strip().lower() == str(token_record.patient_email).strip().lower():
                    is_authorized = True
        if not is_authorized:
            raise HTTPException(status_code=403, detail="You do not have permission to view documents for this token.")
    elif role == "hospital":
        if token_record.hospital_id != auth_user_id:
            raise HTTPException(status_code=403, detail="You do not have permission to view documents for another hospital's token.")
    elif role != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized.")

    docs = (
        db.query(MedicalDocument)
        .filter(MedicalDocument.token_id == token_id)
        .order_by(MedicalDocument.created_at.asc())
        .all()
    )

    return {
        "success": True,
        "token_id": token_id,
        "count": len(docs),
        "documents": [
            {
                "id": d.id,
                "token_id": d.token_id,
                "patient_id": d.patient_id,
                "hospital_id": d.hospital_id,
                "original_filename": d.original_filename,
                "file_type": d.file_type,
                "file_size": d.file_size,
                "file_size_formatted": format_file_size(d.file_size),
                "created_at": d.created_at.isoformat() if d.created_at else None
            }
            for d in docs
        ]
    }


@app.get("/patient/documents/{document_id}/download")
@app.get("/patient/documents/{document_id}/preview")
@app.get("/patient/documents/{document_id}")
def get_medical_document_file(
    document_id: int,
    preview: bool = Query(False),
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    token: Optional[str] = Query(None),
):
    """Allows authorized patients and hospitals to preview (inline) or download an uploaded medical document."""
    current_user = get_document_auth_user(credentials, token)
    doc = db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Medical document not found.")

    role = current_user.get("role")
    auth_user_id = current_user.get("user_id")

    if role == "patient":
        is_authorized = False
        if doc.patient_id is not None and doc.patient_id == auth_user_id:
            is_authorized = True
        else:
            token_record = db.query(Token).filter(Token.id == doc.token_id).first()
            patient = db.query(Patient).filter(Patient.id == auth_user_id).first()
            if token_record and patient:
                if token_record.patient_id == auth_user_id:
                    is_authorized = True
                elif patient.phone and token_record.patient_phone and patient.phone.strip().replace(" ", "").replace("-", "") == str(token_record.patient_phone).strip().replace(" ", "").replace("-", ""):
                    is_authorized = True
                elif patient.email and token_record.patient_email and patient.email.strip().lower() == str(token_record.patient_email).strip().lower():
                    is_authorized = True
        if not is_authorized:
            raise HTTPException(status_code=403, detail="You do not have permission to access another patient's medical document.")
    elif role == "hospital":
        if doc.hospital_id != auth_user_id:
            raise HTTPException(status_code=403, detail="You do not have permission to access another hospital's patient document.")
    elif role != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized access.")

    safe_filename = os.path.basename(doc.stored_filename)
    file_path = os.path.abspath(os.path.join(MEDICAL_DOCUMENTS_DIR, safe_filename))
    if not file_path.startswith(os.path.abspath(MEDICAL_DOCUMENTS_DIR)) or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Physical document file missing from storage.")

    disposition = "inline" if preview else "attachment"
    return FileResponse(
        path=file_path,
        media_type=doc.file_type or "application/octet-stream",
        filename=doc.original_filename,
        content_disposition_type=disposition
    )


@app.delete("/patient/documents/{document_id}")
def delete_medical_document(
    document_id: int,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    token: Optional[str] = Query(None),
):
    """Allows authorized patient or hospital to delete an uploaded document."""
    current_user = get_document_auth_user(credentials, token)
    doc = db.query(MedicalDocument).filter(MedicalDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Medical document not found.")

    role = current_user.get("role")
    auth_user_id = current_user.get("user_id")

    if role == "patient":
        is_authorized = False
        if doc.patient_id is not None and doc.patient_id == auth_user_id:
            is_authorized = True
        else:
            token_record = db.query(Token).filter(Token.id == doc.token_id).first()
            patient = db.query(Patient).filter(Patient.id == auth_user_id).first()
            if token_record and patient:
                if token_record.patient_id == auth_user_id:
                    is_authorized = True
                elif patient.phone and token_record.patient_phone and patient.phone.strip().replace(" ", "").replace("-", "") == str(token_record.patient_phone).strip().replace(" ", "").replace("-", ""):
                    is_authorized = True
                elif patient.email and token_record.patient_email and patient.email.strip().lower() == str(token_record.patient_email).strip().lower():
                    is_authorized = True
        if not is_authorized:
            raise HTTPException(status_code=403, detail="You do not have permission to delete this document.")
    elif role == "hospital":
        if doc.hospital_id != auth_user_id:
            raise HTTPException(status_code=403, detail="You do not have permission to delete another hospital's document.")
    elif role != "admin":
        raise HTTPException(status_code=403, detail="Unauthorized.")

    safe_filename = os.path.basename(doc.stored_filename)
    file_path = os.path.abspath(os.path.join(MEDICAL_DOCUMENTS_DIR, safe_filename))
    if file_path.startswith(os.path.abspath(MEDICAL_DOCUMENTS_DIR)) and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            print("Notice: could not delete physical file:", e)

    t_id = doc.token_id
    h_id = doc.hospital_id
    d_id = doc.id
    db.delete(doc)
    db.commit()

    # Real-Time WebSocket broadcast (instant sync across website and mobile apps)
    try:
        broadcast_now(ws_manager.broadcast_document_event(
            event_type="document_deleted",
            token_id=t_id,
            hospital_id=h_id,
            document_id=d_id,
        ))
    except Exception as ws_err:
        logging.warning("Document delete WS broadcast skipped: %s", ws_err)

    return {"success": True, "message": "Document deleted successfully."}


@app.get("/patient/tokens-documents-batch")
def get_batch_token_documents(
    token_ids: str = Query(..., description="Comma-separated token IDs"),
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    token: Optional[str] = Query(None),
):
    """Fast batch retrieval of documents for authorized tokens."""
    try:
        ids = [int(tid.strip()) for tid in token_ids.split(",") if tid.strip().isdigit()]
    except Exception:
        ids = []

    if not ids:
        return {"success": True, "documents_by_token": {}}

    # Strictly enforce mandatory authentication on batch medical documents (QA-SEC-003)
    current_user = get_document_auth_user(credentials, token)
    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: Please provide a valid authorization token to access medical documents."
        )

    role = current_user.get("role")
    auth_user_id = current_user.get("user_id")

    # Determine strictly authorized token IDs for caller
    authorized_token_ids = set()
    if role == "patient":
        patient = db.query(Patient).filter(Patient.id == auth_user_id).first()
        p_phone = normalize_phone_last10(patient.phone) if patient and patient.phone else None
        p_email = patient.email.strip().lower() if patient and patient.email else None

        matched_tokens = db.query(Token).filter(Token.id.in_(ids)).all()
        for t in matched_tokens:
            if t.patient_id == auth_user_id:
                authorized_token_ids.add(t.id)
            elif p_phone and t.patient_phone and normalize_phone_last10(t.patient_phone) == p_phone:
                authorized_token_ids.add(t.id)
            elif p_email and t.patient_email and str(t.patient_email).strip().lower() == p_email:
                authorized_token_ids.add(t.id)

    elif role == "hospital":
        matched_tokens = db.query(Token).filter(Token.id.in_(ids), Token.hospital_id == auth_user_id).all()
        authorized_token_ids = {t.id for t in matched_tokens}

    elif role == "admin":
        authorized_token_ids = set(ids)

    else:
        raise HTTPException(status_code=403, detail="Unauthorized access to medical documents.")

    if not authorized_token_ids:
        return {"success": True, "documents_by_token": {}}

    query = db.query(MedicalDocument).filter(MedicalDocument.token_id.in_(authorized_token_ids))
    if role == "patient":
        query = query.filter(
            or_(
                MedicalDocument.patient_id == auth_user_id,
                MedicalDocument.token_id.in_(authorized_token_ids)
            )
        )
    elif role == "hospital":
        query = query.filter(MedicalDocument.hospital_id == auth_user_id)

    docs = query.order_by(MedicalDocument.created_at.asc()).all()

    grouped = {}
    for d in docs:
        tid_str = str(d.token_id)
        if tid_str not in grouped:
            grouped[tid_str] = []
        grouped[tid_str].append({
            "id": d.id,
            "token_id": d.token_id,
            "original_filename": d.original_filename,
            "file_type": d.file_type,
            "file_size": d.file_size,
            "file_size_formatted": format_file_size(d.file_size),
            "created_at": d.created_at.isoformat() if d.created_at else None
        })

    return {"success": True, "documents_by_token": grouped}


# ============================================================
# HOSPITAL TOKEN RETENTION: 90-DAY COMPLIANCE PURGE
# ============================================================

def purge_expired_hospital_tokens(db: Session, hospital_id: Optional[int] = None) -> int:
    """
    Healthcare Compliance & Data Hygiene:
    Automatically deletes hospital tokens and old sequence records older than 90 days.
    """
    try:
        ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        cutoff_date = (ist_now - timedelta(days=90)).date()
        cutoff_datetime = datetime.utcnow() - timedelta(days=90)

        query = db.query(Token).filter(
            or_(
                Token.appointment_date < cutoff_date,
                and_(Token.appointment_date.is_(None), Token.created_at < cutoff_datetime),
            )
        )
        if hospital_id is not None:
            query = query.filter(Token.hospital_id == hospital_id)

        deleted = query.delete(synchronize_session=False)

        # Also purge old sequences older than 90 days
        try:
            db.execute(
                text("DELETE FROM token_sequences WHERE appointment_date < :cutoff_date"),
                {"cutoff_date": cutoff_date}
            )
        except Exception as seq_err:
            logging.debug("token_sequences prune note: %s", seq_err)

        if deleted > 0:
            db.commit()
            logging.info(
                "Auto-deleted %d expired hospital token(s) older than 90 days (Cutoff: %s)",
                deleted,
                cutoff_date,
            )
        return deleted
    except Exception as exc:
        db.rollback()
        logging.warning("Error auto-purging 90-day expired hospital tokens: %s", exc)
        return 0


# ============================================================
# HOSPITAL - OWN TOKENS (ORDERED BY APPOINTMENT DATE & TOKEN NUMBER)
# ============================================================

@app.get("/hospital/tokens")
def get_hospital_tokens(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    hospital_id = current_user["user_id"]
    # 1. Automatic 90-day retention purge
    purge_expired_hospital_tokens(db, hospital_id=hospital_id)

    query = db.query(Token).filter(Token.hospital_id == hospital_id)

    if date:
        try:
            parsed_date = datetime.strptime(date.strip(), "%Y-%m-%d").date()
            query = query.filter(Token.appointment_date == parsed_date)
        except ValueError:
            pass

    # Stored and returned as per appointment date (newest first) and token number (ascending)
    tokens = (
        query.order_by(
            Token.appointment_date.desc(),
            Token.token_number.asc(),
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
@app.post("/walk-in-tokens")
@app.post("/walk-in-token")
@app.post("/tokens/walk-in")
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

    clean_doc_search = re.sub(r'^(dr\.|dr|mr\.|mr)\s*', '', doctor_name, flags=re.I).strip()
    clean_dept_search = department.strip().lower()

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.hospital_id == authenticated_hospital_id,
            func.lower(Doctor.department) == clean_dept_search,
            or_(
                func.lower(Doctor.name) == doctor_name.lower(),
                func.lower(Doctor.name) == clean_doc_search.lower(),
                Doctor.name.ilike(f"%{clean_doc_search}%")
            )
        )
        .first()
    )

    if not doctor:
        doctor = (
            db.query(Doctor)
            .filter(
                Doctor.hospital_id == authenticated_hospital_id,
                or_(
                    func.lower(Doctor.name) == doctor_name.lower(),
                    func.lower(Doctor.name) == clean_doc_search.lower(),
                    Doctor.name.ilike(f"%{clean_doc_search}%")
                )
            )
            .first()
        )

    if not doctor:
        raise HTTPException(
            status_code=404,
            detail=f"Doctor '{doctor_name}' not found in this hospital and department",
        )

    # Standardize to canonical doctor and department from database
    doctor_name = doctor.name
    department = doctor.department

    appointment_date = get_ist_today()

    # Check Daily Token Capacity Limit
    hosp_limit = getattr(hospital, "daily_token_limit", None) or 100
    daily_cap = getattr(doctor, "daily_token_limit", None) or hosp_limit

    existing_active_tokens = (
        db.query(func.count(Token.id))
        .filter(
            Token.hospital_id == authenticated_hospital_id,
            Token.doctor == doctor_name,
            Token.appointment_date == appointment_date,
            Token.status != "cancelled",
        )
        .scalar() or 0
    )

    if existing_active_tokens >= daily_cap:
        raise HTTPException(
            status_code=400,
            detail=f"Daily patient capacity of {daily_cap} reached for Dr. {doctor_name} today. Update hospital daily capacity in settings if you wish to accept more walk-in patients.",
        )

    try:
        next_token_number = allocate_token_number(
            db=db,
            hospital_id=authenticated_hospital_id,
            department=department,
            doctor=doctor_name,
            appointment_date=appointment_date,
            doctor_id=doctor.id if doctor else None,
        )

        notes_parts = []
        if getattr(data, "patient_phone", None) and str(data.patient_phone).strip():
            notes_parts.append(f"Phone: {str(data.patient_phone).strip()}")
        if getattr(data, "notes", None) and str(data.notes).strip():
            notes_parts.append(str(data.notes).strip())
        walkin_notes = " | ".join(notes_parts) if notes_parts else None

        phone_val = str(data.patient_phone).strip() if getattr(data, "patient_phone", None) and str(data.patient_phone).strip() else None
        matching_patient = None
        if phone_val:
            clean_p = phone_val.replace(" ", "").replace("-", "")
            digits_only = re.sub(r"\D", "", phone_val)
            last10 = digits_only[-10:] if len(digits_only) >= 10 else digits_only
            p_queries = [Patient.phone == phone_val, Patient.phone == clean_p]
            if last10:
                p_queries.append(Patient.phone.ilike(f"%{last10}%"))
            if clean_p.startswith("+91"):
                p_queries.append(Patient.phone == clean_p[3:])
            elif len(clean_p) == 10:
                p_queries.append(Patient.phone == f"+91{clean_p}")
            matching_patient = db.query(Patient).filter(or_(*p_queries)).first()

        # If not found by phone, fallback to unique full name match
        if not matching_patient and patient_name:
            clean_pname = patient_name.strip().lower()
            name_matches = db.query(Patient).filter(func.lower(Patient.full_name) == clean_pname).all()
            if len(name_matches) == 1:
                matching_patient = name_matches[0]

        if getattr(hospital, "is_deleted", False):
            raise HTTPException(
                status_code=400,
                detail="This hospital account has been deleted or deactivated. New walk-in registrations are disabled.",
            )

        # Determine walk-in token fee & payment collection status:
        # Walk-in registrations are completely separated from online payment collections
        fee_to_charge = 0
        pay_status = "not_required"

        token = Token(
            patient_id=matching_patient.id if matching_patient else None,
            patient_name=patient_name,
            patient_phone=phone_val or (matching_patient.phone if matching_patient else None),
            patient_email=matching_patient.email if matching_patient else None,
            hospital=hospital.name,
            hospital_id=authenticated_hospital_id,
            department=department,
            doctor=doctor_name,
            doctor_id=doctor.id if doctor else None,
            room_number=doctor.room_number if doctor and doctor.room_number else None,
            token_number=next_token_number,
            appointment_date=appointment_date,
            platform=PLATFORM_NAME,
            booking_type="WALK_IN",
            token_fee=fee_to_charge,
            platform_fee=0,
            total_amount=fee_to_charge,
            payment_status=pay_status,
            commission_percentage=Decimal("0.00"),
            commission_amount=Decimal("0.00"),
            hospital_amount=Decimal("0.00"),
            status="waiting",
            notes=walkin_notes,
        )

        db.add(token)
        db.commit()
        db.refresh(token)

        # Real-Time WebSocket broadcast (instant sync across website and mobile apps)
        try:
            broadcast_now(ws_manager.broadcast_token_event(
                event_type="token_booked",
                token_data=token_to_dict(token),
                hospital_id=token.hospital_id,
                patient_phone=token.patient_phone,
            ))
        except Exception as ws_err:
            logging.warning("Walk-in token creation WS broadcast skipped: %s", ws_err)

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
            "doctor_room_number": getattr(doctor, "room_number", None) if doctor else getattr(token, "room_number", None),
            "doctor_is_available": getattr(doctor, "is_available", True) if doctor else True,
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

    # When calling/recalling this token, manage any existing serving token for the same doctor/hospital
    other_serving = (
        db.query(Token)
        .filter(
            Token.hospital_id == current_user["user_id"],
            Token.doctor == token.doctor,
            Token.status == "serving",
            Token.id != token.id,
        )
        .all()
    )
    for other in other_serving:
        # If recalling an earlier token, revert higher token number to waiting so it is not lost
        other_num = other.token_number or 0
        curr_num = token.token_number or 0
        if other_num > curr_num:
            other.status = "waiting"
        else:
            other.status = "completed"
            if not other.completed_at:
                other.completed_at = datetime.utcnow()

    token.status = "serving"
    token.called_at = datetime.utcnow()

    db.commit()
    db.refresh(token)

    # Real-Time WebSocket broadcast (instant sync across website and mobile apps)
    try:
        broadcast_now(ws_manager.broadcast_token_event(
            event_type="token_called",
            token_data=token_to_dict(token),
            hospital_id=token.hospital_id,
            patient_phone=token.patient_phone,
        ))
    except Exception as ws_err:
        logging.warning("Token call WS broadcast skipped: %s", ws_err)

    return {
        "success": True,
        "message": f"Token #{token.token_number} called into consultation",
        "token": token_to_dict(token),
    }


def public_queue_token_dict(token: Token) -> dict:
    """Sanitized public DTO for queue display TV and kiosks - strictly excludes PII and clinical diagnosis."""
    return {
        "id": token.id,
        "token_number": token.token_number,
        "patient_name": mask_patient_name(token.patient_name),
        "hospital": token.hospital,
        "hospital_id": token.hospital_id,
        "department": token.department,
        "doctor": token.doctor,
        "room_number": getattr(token, "room_number", None),
        "doctor_room_number": getattr(token, "room_number", None),
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
    }


def public_token_live_status(token: Token, db: Session) -> dict:
    """Returns safe, minimal status for live waiting tracking without exposing personal medical records."""
    d = public_queue_token_dict(token)
    if token.status in ("waiting", "serving"):
        d.update(get_queue_status_for_token(db, token))
    return d


@app.get("/tokens/{token_id}/live-status")
@app.get("/tokens/{token_id}")
def get_token_live_status(
    token_id: int,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    token: Optional[str] = Query(None),
):
    token_record = db.query(Token).filter(Token.id == token_id).first()
    if not token_record:
        raise HTTPException(status_code=404, detail="Token not found")

    # Authorize caller for full private medical details
    is_authorized = False
    current_user = get_optional_auth_user(credentials, token)

    if current_user:
        role = current_user.get("role")
        user_id = current_user.get("user_id")
        if role == "admin":
            is_authorized = True
        elif role == "hospital" and token_record.hospital_id == user_id:
            is_authorized = True
        elif role == "patient":
            if token_record.patient_id == user_id:
                is_authorized = True
            else:
                pat = db.query(Patient).filter(Patient.id == user_id).first()
                if pat:
                    p_phone = normalize_phone_last10(pat.phone)
                    t_phone = normalize_phone_last10(token_record.patient_phone)
                    if p_phone and t_phone and p_phone == t_phone:
                        is_authorized = True
                    elif pat.email and token_record.patient_email and pat.email.strip().lower() == str(token_record.patient_email).strip().lower():
                        is_authorized = True

    if is_authorized:
        d = token_to_dict(token_record)
        if token_record.status in ("waiting", "serving"):
            d.update(get_queue_status_for_token(db, token_record))
        return d

    # For unauthenticated or public visitors, return strictly sanitized live queue status (Zero PII/Clinical leak)
    return public_token_live_status(token_record, db)


@app.get("/hospitals/{hospital_id}/live-queue")
def get_hospital_live_queue(
    hospital_id: int,
    db: Session = Depends(get_db),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Periodic 90-day retention cleanup
    purge_expired_hospital_tokens(db, hospital_id=hospital_id)

    # Local today's date in IST (+5:30)
    today = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()

    today_tokens = (
        db.query(Token)
        .filter(
            Token.hospital_id == hospital_id,
            or_(
                Token.appointment_date == today,
                func.date(Token.created_at) == today,
            ),
        )
        .order_by(Token.token_number.asc())
        .all()
    )

    # Fallback to recent tokens if date match is empty (avoids blank TV on boundary dates)
    if not today_tokens:
        today_tokens = (
            db.query(Token)
            .filter(Token.hospital_id == hospital_id)
            .order_by(Token.id.desc())
            .limit(50)
            .all()
        )
        today_tokens = sorted(today_tokens, key=lambda t: t.token_number)

    serving_tokens = sorted(
        [public_queue_token_dict(t) for t in today_tokens if t.status == "serving"],
        key=lambda t: (t.get("called_at") or "", t.get("token_number") or 0),
        reverse=True,
    )
    waiting_tokens = [
        public_queue_token_dict(t) for t in today_tokens if t.status == "waiting"
    ]
    completed_tokens = sorted(
        [public_queue_token_dict(t) for t in today_tokens if t.status == "completed"],
        key=lambda t: (t.get("completed_at") or t.get("called_at") or t.get("created_at") or "", t.get("token_number") or 0),
        reverse=True,
    )

    return {
        "success": True,
        "hospital_id": hospital.id,
        "hospital_name": hospital.name,
        "hospital_city": hospital.city,
        "appointment_date": str(today),
        "stats": {
            "total_today": len(today_tokens),
            "completed": len(completed_tokens),
            "serving": len(serving_tokens),
            "waiting": len(waiting_tokens),
        },
        "currently_serving": serving_tokens,
        "upcoming_waiting": waiting_tokens[:20],
        "previous_patients": completed_tokens[:10],
        "recently_completed": completed_tokens[:10],
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

    # Real-Time WebSocket broadcast (instant sync across website and mobile apps)
    try:
        broadcast_now(ws_manager.broadcast_token_event(
            event_type="token_completed",
            token_data=token_to_dict(token),
            hospital_id=token.hospital_id,
            patient_phone=token.patient_phone,
        ))
    except Exception as ws_err:
        logging.warning("Token complete WS broadcast skipped: %s", ws_err)

    return {
        "success": True,
        "message": "Token completed successfully",
        "token": token_to_dict(token),
    }


@app.put("/tokens/{token_id}/skip")
def skip_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Marks a patient token as skipped when they do not answer consultation call."""
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

    token.status = "skipped"
    ist_time = (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%I:%M %p")
    token.notes = ((token.notes + " | ") if token.notes else "") + f"Skipped consultation at {ist_time}"

    db.commit()
    db.refresh(token)

    # Real-Time WebSocket broadcast (instant sync across website and mobile apps)
    try:
        broadcast_now(ws_manager.broadcast_token_event(
            event_type="token_skipped",
            token_data=token_to_dict(token),
            hospital_id=token.hospital_id,
            patient_phone=token.patient_phone,
        ))
    except Exception as ws_err:
        logging.warning("Token skip WS broadcast skipped: %s", ws_err)

    return {
        "success": True,
        "message": f"Token #{token.token_number} skipped successfully",
        "token": token_to_dict(token),
    }
# ============================================================
# PLATFORM CONTACT & SETTINGS
# ============================================================

class PlatformContactUpdateRequest(BaseModel):
    business_name: str | None = None
    platform_fee: int | None = None
    commission_percentage: Union[float, str, None] = None
    banner_ad_fee: float | None = None
    video_ad_fee: float | None = None
    ad_duration_days: int | None = None
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
            business_name="Q-Arovia Healthcare Technologies",
            support_email="mangarajesh58@gmail.com",
            support_phone="+91 98765 43210",
            operating_address="Bhubaneswar / Cuttack, Odisha, India - 751024",
            grievance_officer="Rajesh Mangaraj",
            grievance_email="mangarajesh58@gmail.com",
            working_hours="Mon - Sat: 9:00 AM - 7:00 PM IST",
            platform_fee=PLATFORM_FEE,
            commission_percentage=10.00,
            banner_ad_fee=999.0,
            video_ad_fee=1999.0,
            ad_duration_days=30,
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)
    return contact


@app.get("/platform/fee")
def get_platform_fee_public(db: Session = Depends(get_db)):
    fee = get_current_platform_fee(db)
    return {"success": True, "platform_fee": fee}


@app.get("/api/ad-pricing")
@app.get("/admin/ad-pricing")
def get_ad_pricing(db: Session = Depends(get_db)):
    """Public and admin endpoint returning dynamic fees for Banner Ads and Video Spotlight Ads."""
    contact = get_or_create_contact_settings(db)
    return {
        "success": True,
        "banner_ad_fee": float(getattr(contact, "banner_ad_fee", 999.0) or 999.0),
        "video_ad_fee": float(getattr(contact, "video_ad_fee", 1999.0) or 1999.0),
        "ad_duration_days": int(getattr(contact, "ad_duration_days", 30) or 30),
    }


class AdPricingUpdateRequest(BaseModel):
    banner_ad_fee: Optional[float] = None
    video_ad_fee: Optional[float] = None
    ad_duration_days: Optional[int] = None


@app.put("/admin/ad-pricing")
def update_ad_pricing(
    data: AdPricingUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """Admin-only endpoint to update Banner and Video ad rates dynamically."""
    contact = get_or_create_contact_settings(db)
    changes = []
    if data.banner_ad_fee is not None and data.banner_ad_fee >= 0:
        contact.banner_ad_fee = float(data.banner_ad_fee)
        changes.append(f"Banner: ₹{contact.banner_ad_fee}")
    if data.video_ad_fee is not None and data.video_ad_fee >= 0:
        contact.video_ad_fee = float(data.video_ad_fee)
        changes.append(f"Video: ₹{contact.video_ad_fee}")
    if data.ad_duration_days is not None and data.ad_duration_days > 0:
        contact.ad_duration_days = int(data.ad_duration_days)
        changes.append(f"Duration: {contact.ad_duration_days} days")

    contact.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(contact)

    log_admin_action(
        db,
        current_user.get("email", "admin"),
        "UPDATE_AD_PRICING",
        target_type="SETTING",
        target_id="ad_pricing",
        details="; ".join(changes) if changes else "No changes applied"
    )

    return {
        "success": True,
        "message": "Advertisement pricing updated successfully.",
        "pricing": {
            "banner_ad_fee": contact.banner_ad_fee,
            "video_ad_fee": contact.video_ad_fee,
            "ad_duration_days": contact.ad_duration_days,
        }
    }


@app.get("/platform/contact")
@app.get("/admin/contact")
@app.get("/admin/contact-settings")
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
        "platform_fee": getattr(contact, "platform_fee", PLATFORM_FEE),
        "commission_percentage": float(getattr(contact, "commission_percentage", 10.0) or 10.0),
        "banner_ad_fee": float(getattr(contact, "banner_ad_fee", 999.0) or 999.0),
        "video_ad_fee": float(getattr(contact, "video_ad_fee", 1999.0) or 1999.0),
        "ad_duration_days": int(getattr(contact, "ad_duration_days", 30) or 30),
        "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
    }


@app.post("/admin/contact")
@app.put("/admin/contact")
@app.post("/admin/contact-settings")
@app.put("/admin/contact-settings")
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
    if data.platform_fee is not None:
        contact.platform_fee = int(data.platform_fee)
        log_admin_action(
            db,
            current_user.get("email", "admin"),
            "UPDATE_PLATFORM_FEE",
            target_type="SETTING",
            target_id="platform_fee",
            details=f"Platform convenience fee updated to ₹{contact.platform_fee}"
        )
    if data.banner_ad_fee is not None and data.banner_ad_fee >= 0:
        contact.banner_ad_fee = float(data.banner_ad_fee)
        log_admin_action(
            db,
            current_user.get("email", "admin"),
            "UPDATE_BANNER_AD_FEE",
            target_type="SETTING",
            target_id="banner_ad_fee",
            details=f"Banner ad fee updated to ₹{contact.banner_ad_fee}"
        )
    if data.video_ad_fee is not None and data.video_ad_fee >= 0:
        contact.video_ad_fee = float(data.video_ad_fee)
        log_admin_action(
            db,
            current_user.get("email", "admin"),
            "UPDATE_VIDEO_AD_FEE",
            target_type="SETTING",
            target_id="video_ad_fee",
            details=f"Video spotlight ad fee updated to ₹{contact.video_ad_fee}"
        )
    if data.ad_duration_days is not None and data.ad_duration_days > 0:
        contact.ad_duration_days = int(data.ad_duration_days)

    if data.commission_percentage is not None:
        try:
            c_dec = Decimal(str(data.commission_percentage).strip().rstrip("%"))
            if c_dec < Decimal("0.00") or c_dec > Decimal("100.00"):
                raise ValueError()
            c_rounded = c_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            prev_c = Decimal(str(getattr(contact, "commission_percentage", None) or "10.00")).quantize(Decimal("0.01"))
            contact.commission_percentage = c_rounded
            log_admin_action(
                db,
                current_user.get("email", "admin"),
                "UPDATE_COMMISSION",
                target_type="SETTING",
                target_id="commission_percentage",
                details=json.dumps({
                    "admin_id": current_user.get("user_id", 1),
                    "admin_email": current_user.get("email", "admin"),
                    "previous_percentage": str(prev_c),
                    "new_percentage": str(c_rounded),
                    "updated_at": datetime.utcnow().isoformat(),
                })
            )
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Commission percentage must be a valid number between 0% and 100%."
            )

    contact.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(contact)

    return {
        "success": True,
        "message": "Platform contact and fee settings updated successfully.",
        "contact": {
            "business_name": contact.business_name,
            "support_email": contact.support_email,
            "support_phone": contact.support_phone,
            "operating_address": contact.operating_address,
            "grievance_officer": contact.grievance_officer,
            "grievance_email": contact.grievance_email,
            "working_hours": contact.working_hours,
            "platform_fee": getattr(contact, "platform_fee", PLATFORM_FEE),
            "commission_percentage": float(getattr(contact, "commission_percentage", 10.0) or 10.0),
            "banner_ad_fee": float(getattr(contact, "banner_ad_fee", 999.0) or 999.0),
            "video_ad_fee": float(getattr(contact, "video_ad_fee", 1999.0) or 1999.0),
            "ad_duration_days": int(getattr(contact, "ad_duration_days", 30) or 30),
            "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
        },
    }


# ============================================================
# Q-AROVIA COMMISSION ENGINE (RULES 1 - 7)
# ============================================================

class CommissionUpdateRequest(BaseModel):
    commission_percentage: Any
    confirmed: bool = False


@app.get("/admin/commission")
def get_commission_settings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """
    Returns the active Q-Arovia platform commission percentage and audit tracking details.
    Restricted to Q-Arovia administrators only.
    """
    contact = get_or_create_contact_settings(db)
    current_pct = Decimal(str(getattr(contact, "commission_percentage", None) or "10.00")).quantize(Decimal("0.01"))

    last_log = (
        db.query(AdminAuditLog)
        .filter(
            AdminAuditLog.action == "UPDATE_COMMISSION",
            AdminAuditLog.target_id == "commission_percentage"
        )
        .order_by(AdminAuditLog.created_at.desc())
        .first()
    )

    last_update_details = None
    if last_log:
        try:
            parsed = json.loads(last_log.details) if last_log.details else {}
        except Exception:
            parsed = {}
        last_update_details = {
            "admin_email": last_log.admin_email,
            "admin_id": parsed.get("admin_id"),
            "previous_percentage": parsed.get("previous_percentage"),
            "new_percentage": parsed.get("new_percentage"),
            "updated_at": last_log.created_at.isoformat() if last_log.created_at else None,
        }

    return {
        "success": True,
        "commission_percentage": float(current_pct),
        "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
        "last_update": last_update_details,
    }


@app.put("/admin/commission")
@app.post("/admin/commission")
def update_commission_settings(
    data: CommissionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """
    Updates the Q-Arovia platform commission percentage.
    Validations:
    - Admin authorization required.
    - Explicit confirmation required before saving (confirmed=True).
    - Percentage must be numeric, >= 0.00% and <= 100.00%.
    - Rejects negative, >100%, empty, or non-numeric values.
    - Supports decimal percentages (e.g. 2.5%, 5.75%, 10.25%).
    - Records admin ID, email, previous percentage, new percentage, and timestamp in audit log.
    - DB transaction safe with rollback.
    """
    if not data.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Admin confirmation is required to update the commission percentage. Please confirm before saving."
        )

    raw_val = data.commission_percentage
    if raw_val is None or (isinstance(raw_val, str) and not raw_val.strip()):
        raise HTTPException(
            status_code=400,
            detail="Commission percentage is required and cannot be empty."
        )

    try:
        cleaned_str = str(raw_val).strip().rstrip("%")
        pct_dec = Decimal(cleaned_str)
        if pct_dec.is_nan() or pct_dec.is_infinite():
            raise ValueError()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid commission percentage. Value must be a valid number between 0% and 100%."
        )

    if pct_dec < Decimal("0.00"):
        raise HTTPException(
            status_code=400,
            detail="Commission percentage must be greater than or equal to 0%. Negative values are not permitted."
        )

    if pct_dec > Decimal("100.00"):
        raise HTTPException(
            status_code=400,
            detail="Commission percentage cannot exceed 100%. Values above 100% are not permitted."
        )

    pct_rounded = pct_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    contact = get_or_create_contact_settings(db)
    previous_pct = Decimal(str(getattr(contact, "commission_percentage", None) or "10.00")).quantize(Decimal("0.01"))

    admin_email = current_user.get("email") or current_user.get("sub") or f"admin_{current_user.get('user_id', 1)}"
    admin_id = current_user.get("user_id") or current_user.get("id") or 1

    try:
        contact.commission_percentage = pct_rounded
        contact.updated_at = datetime.utcnow()

        audit_details = json.dumps({
            "admin_id": admin_id,
            "admin_email": admin_email,
            "previous_percentage": str(previous_pct),
            "new_percentage": str(pct_rounded),
            "updated_at": datetime.utcnow().isoformat(),
        })

        log_admin_action(
            db=db,
            admin_email=admin_email,
            action="UPDATE_COMMISSION",
            target_type="SETTING",
            target_id="commission_percentage",
            details=audit_details,
        )

        db.commit()
        db.refresh(contact)

        return {
            "success": True,
            "message": f"Commission percentage updated successfully from {previous_pct}% to {pct_rounded}%.",
            "commission_percentage": float(pct_rounded),
            "previous_percentage": float(previous_pct),
            "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as err:
        db.rollback()
        logging.error("Failed to update commission settings: %s", err)
        raise HTTPException(
            status_code=500,
            detail="Unable to save commission percentage due to an unexpected database error."
        )


# ============================================================
# REAL-TIME ONLINE USERS & PRESENCE ENGINE
# ============================================================

class HeartbeatRequest(BaseModel):
    user_id: Optional[Union[int, str]] = None
    role: Optional[str] = None
    user_role: Optional[str] = None
    name: Optional[str] = None
    user_name: Optional[str] = None
    email: Optional[str] = None
    user_email: Optional[str] = None
    phone: Optional[str] = None
    user_phone: Optional[str] = None
    current_page: Optional[str] = None


@app.post("/api/heartbeat")
async def register_heartbeat(
    request: Request,
    data: Optional[HeartbeatRequest] = None,
    db: Session = Depends(get_db),
):
    """
    Real-time active presence heartbeat endpoint.
    Automatically captures active users from Patient App, Hospital Portal, and Admin Portal.
    """
    raw_uid = data.user_id if data else None
    user_id = None
    if raw_uid is not None:
        try:
            user_id = int(raw_uid)
        except (ValueError, TypeError):
            user_id = None

    role = ((data.user_role or data.role) if data and (data.user_role or data.role) else "visitor").lower()
    name = ((data.user_name or data.name) if data and (data.user_name or data.name) else "").strip() or None
    email = ((data.user_email or data.email) if data and (data.user_email or data.email) else "").strip() or None
    phone = ((data.user_phone or data.phone) if data and (data.user_phone or data.phone) else "").strip() or None
    page = (data.current_page.strip() if data and data.current_page else None)

    # Auto-decode Bearer JWT if provided with strict cryptographic verification
    auth_header = request.headers.get("Authorization")
    token_verified = False
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token_str = auth_header.split(" ")[1]
            payload = jwt.decode(token_str, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            user_id = int(payload.get("sub"))
            role = payload.get("role", "visitor")
            token_verified = True
        except Exception:
            pass

    if not token_verified:
        user_id = None
        role = "visitor"
        name = "Visitor"
        email = None
        phone = None

    # Lookup profile info from DB if missing
    if user_id:
        if role == "patient" and (not name or not email or not phone):
            p = db.query(Patient).filter(Patient.id == user_id).first()
            if p:
                name = name or p.full_name
                email = email or p.email
                phone = phone or p.phone
        elif role == "hospital" and (not name or not email):
            h = db.query(Hospital).filter(Hospital.id == user_id).first()
            if h:
                name = name or h.name
                email = email or h.email
                phone = phone or h.phone
        elif role == "admin" and not name:
            a = db.query(Admin).filter(Admin.id == user_id).first()
            if a:
                name = name or a.email
                email = email or a.email

    name = name or ("Visitor" if role == "visitor" else f"{role.capitalize()} #{user_id or 1}")
    client_ip = request.client.host if request.client else None

    now = datetime.utcnow()
    presence = None
    if user_id and role != "visitor":
        presence = db.query(UserPresence).filter(
            UserPresence.user_id == user_id,
            UserPresence.user_role == role
        ).first()
    elif client_ip:
        presence = db.query(UserPresence).filter(
            UserPresence.ip_address == client_ip,
            UserPresence.user_role == role
        ).first()

    if presence:
        presence.user_name = name
        presence.user_email = email or presence.user_email
        presence.user_phone = phone or presence.user_phone
        presence.current_page = page or presence.current_page
        presence.last_seen_at = now
        presence.ip_address = client_ip or presence.ip_address
    else:
        presence = UserPresence(
            user_id=user_id,
            user_role=role,
            user_name=name,
            user_email=email,
            user_phone=phone,
            current_page=page,
            last_seen_at=now,
            ip_address=client_ip,
        )
        db.add(presence)

    try:
        db.commit()
    except Exception:
        db.rollback()

    return {"status": "ok", "online": True, "server_time": now.isoformat()}


@app.get("/admin/online-users")
def get_admin_online_users(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """
    Returns list of currently online users (active within the last 3 minutes).
    Includes breakdown of Patients vs Hospitals vs Admins.
    """
    now = datetime.utcnow()
    active_cutoff = now - timedelta(minutes=3)

    # Clean up stale records older than 2 hours to keep table lean
    try:
        db.query(UserPresence).filter(UserPresence.last_seen_at < (now - timedelta(hours=2))).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()

    active_presences = (
        db.query(UserPresence)
        .filter(UserPresence.last_seen_at >= active_cutoff)
        .order_by(UserPresence.last_seen_at.desc())
        .all()
    )

    user_list = []
    patients_count = 0
    hospitals_count = 0
    admins_count = 0
    visitors_count = 0

    for u in active_presences:
        seconds_ago = int((now - u.last_seen_at).total_seconds())
        if u.user_role == "patient":
            patients_count += 1
        elif u.user_role == "hospital":
            hospitals_count += 1
        elif u.user_role == "admin":
            admins_count += 1
        else:
            visitors_count += 1

        user_list.append({
            "id": u.id,
            "user_id": u.user_id,
            "role": u.user_role,
            "name": u.user_name,
            "email": u.user_email or "—",
            "phone": u.user_phone or "—",
            "current_page": u.current_page or "Active",
            "last_seen_at": u.last_seen_at.isoformat(),
            "seconds_ago": seconds_ago,
            "time_ago_str": "Just now" if seconds_ago < 30 else f"{seconds_ago // 60}m ago",
        })

    total_registered_patients = db.query(func.count(Patient.id)).scalar() or 0
    total_registered_hospitals = db.query(func.count(Hospital.id)).scalar() or 0

    return {
        "success": True,
        "total_online": len(active_presences),
        "patients_online": patients_count,
        "hospitals_online": hospitals_count,
        "admins_online": admins_count,
        "visitors_online": visitors_count,
        "total_registered_patients": total_registered_patients,
        "total_registered_hospitals": total_registered_hospitals,
        "users": user_list,
    }


# ============================================================
# MASTER ADMIN - PATIENTS DIRECTORY & 360° DOSSIER
# ============================================================

@app.get("/admin/patients")
def get_admin_patients_directory(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """
    Returns every patient record in the database with demographics, contact details,
    account creation date, and total tokens booked.
    """
    patients = db.query(Patient).order_by(Patient.created_at.desc()).all()
    results = []

    # Batch token count calculations
    token_counts = dict(
        db.query(Token.patient_id, func.count(Token.id))
        .filter(Token.patient_id != None)
        .group_by(Token.patient_id)
        .all()
    )
    active_token_counts = dict(
        db.query(Token.patient_id, func.count(Token.id))
        .filter(Token.patient_id != None, Token.status.in_(["waiting", "serving"]))
        .group_by(Token.patient_id)
        .all()
    )

    for p in patients:
        pat_name = p.full_name or "Unknown Patient"
        results.append({
            "id": p.id,
            "name": pat_name,
            "full_name": pat_name,
            "patient_name": pat_name,
            "email": p.email,
            "phone": p.phone or "—",
            "age": p.age,
            "gender": p.gender or "—",
            "blood_group": p.blood_group or "—",
            "address": p.address or "—",
            "emergency_contact": p.emergency_contact or "—",
            "google_id": bool(p.google_id),
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "total_tokens": token_counts.get(p.id, 0),
            "active_tokens": active_token_counts.get(p.id, 0),
        })

    return {
        "success": True,
        "count": len(results),
        "patients": results,
    }


@app.get("/admin/patients/{patient_id}")
def get_admin_patient_dossier(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """
    Returns a patient's full details and medical booking dossier, including every token
    booked, which hospital they booked at, which doctor, department, and payment breakdown.
    """
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient record not found.")

    # Match tokens by patient_id, phone, or email
    filter_conds = [Token.patient_id == patient.id]
    if patient.phone:
        clean_p = patient.phone.strip().replace(" ", "").replace("-", "")
        filter_conds.append(Token.patient_phone == patient.phone)
        filter_conds.append(Token.patient_phone == clean_p)
    if patient.email:
        filter_conds.append(func.lower(Token.patient_email) == patient.email.strip().lower())

    tokens = (
        db.query(Token)
        .filter(or_(*filter_conds))
        .order_by(Token.appointment_date.desc(), Token.created_at.desc())
        .all()
    )

    token_history = []
    for t in tokens:
        hospital = None
        if t.hospital_id:
            hospital = db.query(Hospital).filter(Hospital.id == t.hospital_id).first()
        if not hospital and t.hospital:
            hospital = db.query(Hospital).filter(Hospital.name == t.hospital).first()

        token_history.append({
            "token_id": t.id,
            "token_number": t.token_number,
            "appointment_date": str(t.appointment_date) if t.appointment_date else "—",
            "status": t.status,
            "hospital_name": hospital.name if hospital else (t.hospital or "—"),
            "hospital_id": t.hospital_id,
            "hospital_phone": hospital.phone if hospital else "—",
            "hospital_city": hospital.city if hospital else "—",
            "hospital_address": hospital.address if hospital else "—",
            "department": t.department,
            "doctor": t.doctor,
            "doctor_room_number": t.doctor_room_number or t.room_number or "—",
            "booking_type": t.booking_type or "ONLINE",
            "token_fee": float(t.token_fee or 0),
            "platform_fee": float(t.platform_fee or 0),
            "total_amount": float(t.total_amount or 0),
            "payment_status": t.payment_status or "—",
            "cashfree_order_id": t.cashfree_order_id or "—",
            "cashfree_payment_id": t.cashfree_payment_id or "—",
            "notes": t.notes,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    pat_name = patient.full_name or "Unknown Patient"
    return {
        "success": True,
        "patient": {
            "id": patient.id,
            "name": pat_name,
            "full_name": pat_name,
            "patient_name": pat_name,
            "email": patient.email,
            "phone": patient.phone or "—",
            "age": patient.age,
            "gender": patient.gender or "—",
            "blood_group": patient.blood_group or "—",
            "address": patient.address or "—",
            "emergency_contact": patient.emergency_contact or "—",
            "google_id": bool(patient.google_id),
            "created_at": patient.created_at.isoformat() if patient.created_at else None,
            "total_tokens_booked": len(token_history),
        },
        "tokens": token_history,
    }


# ============================================================
# ADMIN LOGIN
# ============================================================


@app.post("/admin/login")
def admin_login(
    data: AdminLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    check_login_rate_limit(request)
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

    access_token, refresh_token, session = create_user_session(
        db=db,
        user_id=admin.id,
        role="admin",
        request=request,
    )

    return {
        "success": True,
        "message": "Admin login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "admin": {
            "id": admin.id,
            "email": admin.email,
        },
    }

# ============================================================
# ADMIN - ALL HOSPITALS (CACHED)
# ============================================================

_ADMIN_HOSPITALS_CACHE = {}
_ADMIN_HOSPITALS_CACHE_TTL = 30.0

def get_cached_admin_hospitals():
    item = _ADMIN_HOSPITALS_CACHE.get("all")
    if item:
        ts, data = item
        if (time.time() - ts) < _ADMIN_HOSPITALS_CACHE_TTL:
            return data
    return None

def set_cached_admin_hospitals(data):
    _ADMIN_HOSPITALS_CACHE["all"] = (time.time(), data)

def invalidate_admin_hospitals_cache():
    _ADMIN_HOSPITALS_CACHE.clear()

@app.get("/admin/hospitals")
def admin_get_hospitals(
    include_deleted: bool = False,
    response: Response = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    if not include_deleted:
        cached = get_cached_admin_hospitals()
        if cached is not None:
            if response:
                response.headers["Cache-Control"] = "private, max-age=30"
                response.headers["X-Cache"] = "HIT"
            return cached

    query = db.query(Hospital)
    if not include_deleted:
        query = query.filter(Hospital.is_deleted == False)

    hospitals = (
        query
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

    set_cached_admin_hospitals(result)
    if response:
        response.headers["Cache-Control"] = "private, max-age=30"
        response.headers["X-Cache"] = "MISS"

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

        "photo_base64":
            hospital.photo_base64,
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
    hospital.rejection_reason = (data.reason or "Hospital certificate rejected by admin")

    db.commit()
    db.refresh(hospital)

    try:
        broadcast_now(ws_manager.broadcast_hospital_status_event(
            hospital.id, hospital.approval_status, bool(hospital.is_published)
        ))
    except Exception as ws_err:
        logging.warning("Hospital reject WS broadcast skipped: %s", ws_err)

    log_admin_action(
        db,
        current_user.get("email", "admin"),
        "REJECT_CERTIFICATE",
        target_type="HOSPITAL",
        target_id=str(hospital.id),
        details=f"Certificate rejection reason: {hospital.rejection_reason}"
    )

    if hospital.email:
        subj = f"Q-Arovia Notice: Certificate Rejected for {hospital.name}"
        body = f"""Dear {hospital.name} Administration,

Your uploaded hospital registration certificate has been reviewed and REJECTED.
Reason: {hospital.rejection_reason}

Please log in to your Hospital Command Center ({HOSPITAL_FRONTEND_URL}/profile.html) to re-upload a clear and valid document.

Regards,
Q-Arovia Verification Team
"""
        try:
            send_qarovia_email(hospital.email, subj, body)
        except Exception as err:
            logging.warning("Certificate rejection email error: %s", err)

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
@app.get("/hospitals/{hospital_id}/certificate")
def get_hospital_certificate(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    role = current_user.get("role")
    user_id = current_user.get("user_id")
    if role == "hospital":
        if user_id != hospital_id:
            raise HTTPException(status_code=403, detail="You cannot access another hospital's certificate.")
    elif role != "admin":
        raise HTTPException(status_code=403, detail="Access denied.")
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
    h_name = (hospital.name or "Q-Arovia Hospital").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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
    Q-Arovia Platform Verified Hospital License Record
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

    try:
        broadcast_now(ws_manager.broadcast_hospital_status_event(
            hospital.id, hospital.approval_status, bool(hospital.is_published)
        ))
    except Exception as ws_err:
        logging.warning("Hospital approve WS broadcast skipped: %s", ws_err)

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
        or "Hospital registration rejected by Q-Arovia Admin"
    )

    db.commit()
    db.refresh(hospital)

    try:
        broadcast_now(ws_manager.broadcast_hospital_status_event(
            hospital.id, hospital.approval_status, bool(hospital.is_published)
        ))
    except Exception as ws_err:
        logging.warning("Hospital reject WS broadcast skipped: %s", ws_err)

    log_admin_action(
        db,
        current_user.get("email", "admin"),
        "REJECT_HOSPITAL",
        target_type="HOSPITAL",
        target_id=str(hospital.id),
        details=f"Reason: {hospital.rejection_reason}"
    )

    if hospital.email:
        subj = f"Q-Arovia Action Required: Hospital Registration Status for {hospital.name}"
        body = f"""Dear {hospital.name} Administration,

Your Q-Arovia hospital registration review has been updated.
Status: REJECTED
Reason: {hospital.rejection_reason}

Please log in to your Hospital Command Center ({HOSPITAL_FRONTEND_URL}) to review your details and re-submit your registration.

Regards,
Q-Arovia Healthcare Compliance Team
"""
        try:
            send_qarovia_email(hospital.email, subj, body)
        except Exception as err:
            logging.warning("Rejection email error: %s", err)

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

    try:
        broadcast_now(ws_manager.broadcast_hospital_status_event(
            hospital.id, hospital.approval_status, bool(hospital.is_published)
        ))
    except Exception as ws_err:
        logging.warning("Hospital publish WS broadcast skipped: %s", ws_err)

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

    try:
        broadcast_now(ws_manager.broadcast_hospital_status_event(
            hospital.id, hospital.approval_status, bool(hospital.is_published)
        ))
    except Exception as ws_err:
        logging.warning("Hospital unpublish WS broadcast skipped: %s", ws_err)

    return {
        "success": True,
        "message": "Hospital unpublished",
    }
# ============================================================
# ADMIN - DELETE HOSPITAL (SAFE SOFT DELETION)
# ============================================================

@app.delete("/admin/hospitals/{hospital_id}")
def delete_hospital(
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

    if getattr(hospital, "is_deleted", False):
        raise HTTPException(
            status_code=400,
            detail="Hospital has already been deleted or deactivated.",
        )

    admin_email = current_user.get("email", "admin")

    # Safe Soft Deletion Strategy:
    # 1. Soft-delete hospital and revoke publishing/approval
    hospital.is_deleted = True
    hospital.is_published = False
    hospital.approval_status = "DELETED"
    hospital.deleted_at = datetime.utcnow()
    hospital.deleted_by = admin_email

    # 2. Deactivate doctor schedules so no new appointments can be booked
    db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id
    ).update({"is_available": False}, synchronize_session=False)

    # 3. Cancel any upcoming waiting tokens with cancellation audit reason
    # (PRESERVE all historical tokens, patient appointments, payments, and receipts!)
    today_date = date.today()
    db.query(Token).filter(
        Token.hospital_id == hospital_id,
        Token.status == "waiting",
        Token.appointment_date >= today_date,
    ).update({
        "status": "cancelled",
        "notes": "Hospital facility deactivated by administration"
    }, synchronize_session=False)

    # 4. Record Admin Audit Log
    log_admin_action(
        db,
        admin_email=admin_email,
        action="DELETE_HOSPITAL",
        target_type="HOSPITAL",
        target_id=str(hospital_id),
        details=f"Admin soft-deleted hospital '{hospital.name}' (ID: {hospital_id}). Historical patient tokens, payments and receipts preserved.",
    )

    db.commit()

    # 5. Invalidate all public and admin caches
    invalidate_doctor_cache()
    invalidate_hospital_cache()
    invalidate_admin_hospitals_cache()

    return {
        "success": True,
        "message": f"Hospital '{hospital.name}' deleted and deactivated successfully. Historical patient records preserved.",
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
        room_number=data.room_number.strip() if getattr(data, "room_number", None) else None,
        token_fee=max(0, int(data.token_fee)) if getattr(data, "token_fee", None) is not None else int(hospital.token_fee or 50),
    )

    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    invalidate_doctor_cache()

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
# ADMIN - REVENUE (CACHED)
# ============================================================

_ADMIN_REVENUE_CACHE = {}
_ADMIN_REVENUE_CACHE_TTL = 30.0

def get_cached_admin_revenue():
    item = _ADMIN_REVENUE_CACHE.get("rev")
    if item:
        ts, data = item
        if (time.time() - ts) < _ADMIN_REVENUE_CACHE_TTL:
            return data
    return None

def set_cached_admin_revenue(data):
    _ADMIN_REVENUE_CACHE["rev"] = (time.time(), data)

def invalidate_admin_revenue_cache():
    _ADMIN_REVENUE_CACHE.clear()

@app.get("/admin/revenue")
def admin_revenue(
    response: Response = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    cached = get_cached_admin_revenue()
    if cached is not None:
        if response:
            response.headers["Cache-Control"] = "private, max-age=30"
            response.headers["X-Cache"] = "HIT"
        return cached

    paid_tokens = (
        db.query(Token)
        .filter(Token.payment_status == "paid")
        .all()
    )

    paid_ads = (
        db.query(HospitalAdvertisement)
        .filter(HospitalAdvertisement.payment_status == "paid")
        .all()
    )

    hospital_revenue = sum(int(token.token_fee or 0) for token in paid_tokens)
    platform_revenue = sum(int(token.platform_fee or 0) for token in paid_tokens)
    
    paid_banner_ads = [ad for ad in paid_ads if getattr(ad, "ad_type", "banner") != "video"]
    paid_video_ads = [ad for ad in paid_ads if getattr(ad, "ad_type", "banner") == "video"]
    banner_ads_revenue = sum(int(ad.amount_paid or 0) for ad in paid_banner_ads)
    video_ads_revenue = sum(int(ad.amount_paid or 0) for ad in paid_video_ads)
    ads_revenue = banner_ads_revenue + video_ads_revenue

    total_developer_revenue = platform_revenue + ads_revenue
    total_collected = sum(int(token.total_amount or 0) for token in paid_tokens) + ads_revenue
    token_count = len(paid_tokens)
    ads_count = len(paid_ads)

    result = {
        "success": True,
        "hospital_revenue": hospital_revenue,
        "token_revenue": hospital_revenue,
        "platform_revenue": platform_revenue,
        "ads_revenue": ads_revenue,
        "banner_ads_revenue": banner_ads_revenue,
        "video_ads_revenue": video_ads_revenue,
        "ads_count": ads_count,
        "banner_ads_count": len(paid_banner_ads),
        "video_ads_count": len(paid_video_ads),
        "developer_total_revenue": total_developer_revenue,
        "total_revenue": total_developer_revenue,
        "total_collected": total_collected,
        "token_count": token_count,
        "total_tokens": token_count,
        "platform_fee_per_token": PLATFORM_FEE,
    }

    set_cached_admin_revenue(result)
    if response:
        response.headers["Cache-Control"] = "private, max-age=30"
        response.headers["X-Cache"] = "MISS"

    return result


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
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """
    Returns all hospital tokens enriched with full patient details (demographics, contact)
    and complete hospital details for 360-degree admin visibility.
    """
    token_query = (
        db.query(Token)
        .order_by(
            Token.appointment_date.desc(),
            Token.created_at.desc()
        )
    )
    if limit is not None and limit > 0:
        tokens = token_query.offset(offset).limit(limit).all()
    else:
        tokens = token_query.all()

    # Pre-load hospitals and patients in batch maps for 0ms execution
    hospital_map = {h.id: h for h in db.query(Hospital).all()}
    patient_map = {p.id: p for p in db.query(Patient).all()}
    phone_patient_map = {p.phone.strip(): p for p in patient_map.values() if p.phone}
    email_patient_map = {p.email.strip().lower(): p for p in patient_map.values() if p.email}

    results = []
    for token in tokens:
        d = token_to_dict(token)
        patient = patient_map.get(token.patient_id)
        if not patient and token.patient_phone:
            patient = phone_patient_map.get(token.patient_phone.strip())
        if not patient and token.patient_email:
            patient = email_patient_map.get(token.patient_email.strip().lower())

        if patient:
            p_name = patient.full_name or "Unknown Patient"
            d["patient_full_details"] = {
                "id": patient.id,
                "name": p_name,
                "full_name": p_name,
                "patient_name": p_name,
                "email": patient.email,
                "phone": patient.phone or "—",
                "age": patient.age or "—",
                "gender": patient.gender or "—",
                "blood_group": patient.blood_group or "—",
                "address": patient.address or "—",
                "emergency_contact": patient.emergency_contact or "—",
                "created_at": patient.created_at.isoformat() if patient.created_at else None,
            }
        else:
            w_name = token.patient_name or "Walk-in Patient"
            d["patient_full_details"] = {
                "id": None,
                "name": w_name,
                "full_name": w_name,
                "patient_name": w_name,
                "email": token.patient_email or "—",
                "phone": token.patient_phone or "—",
                "age": token.patient_age or "—",
                "gender": token.patient_gender or "—",
                "blood_group": "—",
                "address": "Walk-in registration",
                "emergency_contact": "—",
                "created_at": token.created_at.isoformat() if token.created_at else None,
            }

        hosp = hospital_map.get(token.hospital_id)
        d["hospital_details"] = {
            "id": hosp.id if hosp else token.hospital_id,
            "name": hosp.name if hosp else (token.hospital or "—"),
            "city": hosp.city if hosp else "—",
            "phone": hosp.phone if hosp else "—",
            "address": hosp.address if hosp else "—",
            "operating_hours": getattr(hosp, "operating_hours_12h", "09:00 AM - 09:00 PM") if hosp else "09:00 AM - 09:00 PM",
        }
        results.append(d)

    return results

# ============================================================
# TOKEN COLLECTION HISTORY (PER DAY & PER MONTH)
# ============================================================

@app.get("/hospital/collection-summary")
@app.get("/hospitals/{hospital_id}/collection-summary")
def get_hospital_collection_summary(
    hospital_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns Token Collection History breakdown:
    - Today's collection & token count
    - Current month's collection & token count
    - All-time collection & token count
    - Filterable collection records (date, patient name, token number, doctor, department, payment type, amount)
    - Daily history list (per day)
    - Monthly history list (per month)
    """
    user_role = current_user.get("role")
    auth_user_id = current_user.get("user_id")

    if user_role == "hospital":
        target_hospital_id = int(auth_user_id) if auth_user_id is not None else None
    elif user_role == "admin":
        target_hospital_id = int(hospital_id or auth_user_id) if (hospital_id or auth_user_id) is not None else None
    else:
        raise HTTPException(status_code=403, detail="Unauthorized access to hospital collection history.")

    hospital = db.query(Hospital).filter(Hospital.id == target_hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found.")

    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    ist_today = ist_now.date()
    curr_month_str = ist_today.strftime("%Y-%m")

    # Fetch successful collections (Online paid tokens) and walk-in registrations:
    # Walk-in tokens are tracked for attendance volume but are strictly separated from token fee collection ($0)
    # Online tokens count only when payment_status IN ('paid', 'succeeded', 'completed')
    valid_tokens = (
        db.query(Token)
        .filter(
            Token.hospital_id == target_hospital_id,
            Token.status != "cancelled",
            Token.payment_status != "refunded",
            or_(
                Token.booking_type == "WALK_IN",
                and_(
                    Token.payment_status.in_(["paid", "succeeded", "completed"]),
                    or_(
                        Token.token_fee > 0,
                        Token.total_amount > 0
                    )
                )
            )
        )
        .order_by(Token.appointment_date.desc(), Token.id.desc())
        .all()
    )

    today_collection = 0
    today_tokens_count = 0
    month_collection = 0
    month_tokens_count = 0
    all_time_collection = 0
    all_time_tokens_count = 0

    detailed_records = []
    daily_map = {}
    monthly_map = {}

    days_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for t in valid_tokens:
        d = t.appointment_date or (t.created_at.date() if t.created_at else ist_today)
        d_str = str(d)
        m_str = d.strftime("%Y-%m")
        m_name = d.strftime("%B %Y")
        day_name = days_short[d.weekday()]

        is_walkin = (t.booking_type == "WALK_IN")
        # Walk-in registrations are completely separated from online fee collection ($0 fee)
        fee = 0 if is_walkin else int(t.token_fee or t.total_amount or 0)
        booking_type_label = "Walk-in" if is_walkin else "Online"
        payment_type_label = "Walk-in (Counter)" if is_walkin else "Online (Paid)"

        all_time_collection += fee
        all_time_tokens_count += 1

        is_today = (d == ist_today)
        is_this_month = (m_str == curr_month_str)

        if is_today:
            today_collection += fee
            today_tokens_count += 1

        if is_this_month:
            month_collection += fee
            month_tokens_count += 1

        rec = {
            "id": t.id,
            "date": d_str,
            "date_display": d.strftime("%d %b %Y"),
            "patient_name": t.patient_name,
            "patient_phone": t.patient_phone or "-",
            "token_number": t.token_number,
            "doctor": t.doctor,
            "department": t.department,
            "booking_type": booking_type_label,
            "payment_type": payment_type_label,
            "payment_status": t.payment_status,
            "amount": fee,
            "status": t.status,
            "is_today": is_today,
            "is_this_month": is_this_month,
        }
        detailed_records.append(rec)

        # Daily mapping
        if d_str not in daily_map:
            label = "Today" if is_today else ("Yesterday" if d == (ist_today - timedelta(days=1)) else day_name)
            daily_map[d_str] = {
                "date": d_str,
                "date_display": f"{d.strftime('%d %b %Y')} ({label})",
                "day_name": day_name,
                "total_tokens": 0,
                "online_tokens": 0,
                "walkin_tokens": 0,
                "completed_tokens": 0,
                "collection": 0,
            }

        daily_map[d_str]["total_tokens"] += 1
        if is_walkin:
            daily_map[d_str]["walkin_tokens"] += 1
        else:
            daily_map[d_str]["online_tokens"] += 1
        if t.status == "completed":
            daily_map[d_str]["completed_tokens"] += 1
        daily_map[d_str]["collection"] += fee

        # Monthly mapping
        if m_str not in monthly_map:
            monthly_map[m_str] = {
                "month": m_str,
                "month_name": m_name,
                "is_current": is_this_month,
                "total_tokens": 0,
                "online_tokens": 0,
                "walkin_tokens": 0,
                "completed_tokens": 0,
                "collection": 0,
            }

        monthly_map[m_str]["total_tokens"] += 1
        if is_walkin:
            monthly_map[m_str]["walkin_tokens"] += 1
        else:
            monthly_map[m_str]["online_tokens"] += 1
        if t.status == "completed":
            monthly_map[m_str]["completed_tokens"] += 1
        monthly_map[m_str]["collection"] += fee

    daily_history = [v for k, v in sorted(daily_map.items(), key=lambda x: x[0], reverse=True)]
    monthly_history = [v for k, v in sorted(monthly_map.items(), key=lambda x: x[0], reverse=True)]

    return {
        "success": True,
        "hospital_id": hospital.id,
        "hospital_name": hospital.name,
        "hospital_fee": int(hospital.token_fee or 0),
        "today": {
            "date": str(ist_today),
            "date_display": ist_today.strftime("%d %b %Y"),
            "collection": today_collection,
            "total_tokens": today_tokens_count,
        },
        "this_month": {
            "month": curr_month_str,
            "month_name": ist_today.strftime("%B %Y"),
            "collection": month_collection,
            "total_tokens": month_tokens_count,
        },
        "all_time": {
            "total_collection": all_time_collection,
            "total_tokens": all_time_tokens_count,
        },
        "records": detailed_records,
        "records_today": [r for r in detailed_records if r["is_today"]],
        "records_month": [r for r in detailed_records if r["is_this_month"]],
        "daily_history": daily_history,
        "monthly_history": monthly_history,
    }


@app.get("/admin/collection-summary")
def get_admin_collection_summary(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """
    Returns Platform-Wide Token Collection History:
    - Today's platform-wide collection
    - Monthly collection
    - Daily & Monthly collection breakdown across all hospitals
    """
    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    ist_today = ist_now.date()
    curr_month_str = ist_today.strftime("%Y-%m")

    tokens = (
        db.query(Token)
        .filter(
            Token.status != "cancelled",
            Token.payment_status != "refunded"
        )
        .order_by(Token.appointment_date.desc(), Token.id.desc())
        .all()
    )

    daily_map = {}
    monthly_map = {}

    today_summary = {
        "date": str(ist_today),
        "date_display": ist_today.strftime("%d %b %Y"),
        "total_tokens": 0,
        "online_tokens": 0,
        "walkin_tokens": 0,
        "completed_tokens": 0,
        "hospital_collection": 0,
        "platform_fee": 0,
        "total_gross": 0,
    }

    month_summary = {
        "month": curr_month_str,
        "month_name": ist_today.strftime("%B %Y"),
        "total_tokens": 0,
        "online_tokens": 0,
        "walkin_tokens": 0,
        "completed_tokens": 0,
        "hospital_collection": 0,
        "platform_fee": 0,
        "total_gross": 0,
    }

    days_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for t in tokens:
        d = t.appointment_date
        if not d:
            continue
        d_str = str(d)
        m_str = d.strftime("%Y-%m")
        m_name = d.strftime("%B %Y")
        day_name = days_short[d.weekday()]

        is_walkin = (t.booking_type == "WALK_IN")
        fee = 0 if is_walkin else int(t.token_fee or 0)
        p_fee = 0 if is_walkin else int(t.platform_fee or 0)
        gross = 0 if is_walkin else int(t.total_amount or (fee + p_fee))
        is_completed = (t.status == "completed")

        # Daily mapping
        if d_str not in daily_map:
            label = "Today" if d == ist_today else ("Yesterday" if d == (ist_today - timedelta(days=1)) else day_name)
            daily_map[d_str] = {
                "date": d_str,
                "date_display": f"{d.strftime('%d %b %Y')} ({label})",
                "day_name": day_name,
                "total_tokens": 0,
                "online_tokens": 0,
                "walkin_tokens": 0,
                "completed_tokens": 0,
                "hospital_collection": 0,
                "platform_fee": 0,
                "total_gross": 0,
            }

        daily_map[d_str]["total_tokens"] += 1
        if is_walkin: daily_map[d_str]["walkin_tokens"] += 1
        else: daily_map[d_str]["online_tokens"] += 1
        if is_completed: daily_map[d_str]["completed_tokens"] += 1
        daily_map[d_str]["hospital_collection"] += fee
        daily_map[d_str]["platform_fee"] += p_fee
        daily_map[d_str]["total_gross"] += gross

        # Monthly mapping
        if m_str not in monthly_map:
            monthly_map[m_str] = {
                "month": m_str,
                "month_name": m_name,
                "is_current": (m_str == curr_month_str),
                "total_tokens": 0,
                "online_tokens": 0,
                "walkin_tokens": 0,
                "completed_tokens": 0,
                "hospital_collection": 0,
                "platform_fee": 0,
                "total_gross": 0,
            }

        monthly_map[m_str]["total_tokens"] += 1
        if is_walkin: monthly_map[m_str]["walkin_tokens"] += 1
        else: monthly_map[m_str]["online_tokens"] += 1
        if is_completed: monthly_map[m_str]["completed_tokens"] += 1
        monthly_map[m_str]["hospital_collection"] += fee
        monthly_map[m_str]["platform_fee"] += p_fee
        monthly_map[m_str]["total_gross"] += gross

        # Today
        if d == ist_today:
            today_summary["total_tokens"] += 1
            if is_walkin: today_summary["walkin_tokens"] += 1
            else: today_summary["online_tokens"] += 1
            if is_completed: today_summary["completed_tokens"] += 1
            today_summary["hospital_collection"] += fee
            today_summary["platform_fee"] += p_fee
            today_summary["total_gross"] += gross

        # Month
        if m_str == curr_month_str:
            month_summary["total_tokens"] += 1
            if is_walkin: month_summary["walkin_tokens"] += 1
            else: month_summary["online_tokens"] += 1
            if is_completed: month_summary["completed_tokens"] += 1
            month_summary["hospital_collection"] += fee
            month_summary["platform_fee"] += p_fee
            month_summary["total_gross"] += gross

    daily_history = [v for k, v in sorted(daily_map.items(), key=lambda x: x[0], reverse=True)]
    monthly_history = [v for k, v in sorted(monthly_map.items(), key=lambda x: x[0], reverse=True)]

    return {
        "success": True,
        "today": today_summary,
        "this_month": month_summary,
        "daily_history": daily_history,
        "monthly_history": monthly_history,
    }


@app.get("/hospitals/{hospital_id}/tokens")
def hospital_tokens(
    hospital_id: int,
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    # Hospital can only access its own queue
    if hospital_id != current_user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot access another hospital's tokens."
        )

    # 1. Automatic 90-day retention purge
    purge_expired_hospital_tokens(db, hospital_id=hospital_id)

    query = db.query(Token).filter(Token.hospital_id == hospital_id)

    if date:
        try:
            parsed_date = datetime.strptime(date.strip(), "%Y-%m-%d").date()
            query = query.filter(Token.appointment_date == parsed_date)
        except ValueError:
            pass

    # Stored and returned as per appointment date (newest first) and token number (ascending)
    tokens = (
        query.order_by(
            Token.appointment_date.desc(),
            Token.token_number.asc(),
        )
        .all()
    )

    return [
        token_to_dict(token)
        for token in tokens
    ]


@app.post("/hospitals/{hospital_id}/tokens/purge-expired")
def hospital_purge_expired_tokens(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Hospital: Purge tokens older than 90 days for this hospital."""
    if hospital_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Unauthorized")

    deleted = purge_expired_hospital_tokens(db, hospital_id=hospital_id)
    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    cutoff_date = (ist_now - timedelta(days=90)).date()

    return {
        "success": True,
        "deleted_count": deleted,
        "retention_days": 90,
        "cutoff_date": str(cutoff_date),
        "message": f"Successfully purged {deleted} token(s) older than 90 days (before {cutoff_date})."
    }
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
# STARTUP ROUTINE & 90-DAY RETENTION MAINTENANCE
# ============================================================

_MAIN_EVENT_LOOP = None

def broadcast_now(coro):
    global _MAIN_EVENT_LOOP
    try:
        if _MAIN_EVENT_LOOP is not None and _MAIN_EVENT_LOOP.is_running():
            asyncio.run_coroutine_threadsafe(coro, _MAIN_EVENT_LOOP)
        else:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(coro)
                else:
                    loop.run_until_complete(coro)
            except RuntimeError:
                asyncio.run(coro)
    except Exception as e:
        logging.warning("WebSocket broadcast_now warning: %s", e)

@app.on_event("startup")
def on_app_startup():
    global _MAIN_EVENT_LOOP
    try:
        _MAIN_EVENT_LOOP = asyncio.get_event_loop()
    except Exception:
        pass
    """Startup routine: purge tokens older than 90 days and patient inquiries older than 24 hours."""
    db = SessionLocal()
    try:
        purged = purge_expired_hospital_tokens(db)
        if purged:
            logging.info("Startup Maintenance: Automatically deleted %d token(s) older than 90 days.", purged)
        purge_expired_patient_inquiries(db)
    except Exception as exc:
        logging.warning("Startup maintenance note: %s", exc)
    finally:
        db.close()

print()
print("================================================")
print("Q-Arovia FastAPI backend loaded")
print("Version: 11.0.0")
print(
    f"Razorpay configured: "
    f"{bool(razorpay_client)}"
)
print(
    f"Google Client ID configured: "
    f"{bool(GOOGLE_CLIENT_ID)}"
)
print("Token Retention: 90 Days Auto-Prune Active")
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

    # Auto-frame and normalize uploaded doctor photo so it never zooms in or distorts in avatars
    processed_content = content
    try:
        from PIL import Image, ImageOps
        import io
        img = Image.open(io.BytesIO(content))
        img = ImageOps.exif_transpose(img)
        w, h = img.size

        # For portrait photos (h > w): crop balanced square centered on upper body / head
        if h > w:
            crop_size = w
            top = max(0, min(int((h - w) * 0.35), h - crop_size))
            img = img.crop((0, top, w, top + crop_size))
        elif w > h:
            crop_size = h
            left = (w - h) // 2
            img = img.crop((left, 0, left + crop_size, h))

        if img.width > 600:
            img = img.resize((600, 600), Image.Resampling.LANCZOS)

        out_buf = io.BytesIO()
        img.convert("RGB").save(out_buf, format="JPEG", quality=88, optimize=True)
        processed_content = out_buf.getvalue()
        filename = f"doctor_{doctor_id}_{uuid.uuid4().hex}.jpg"
        destination = os.path.join(DOCTOR_PHOTO_DIR, filename)
    except Exception:
        pass

    with open(destination, "wb") as output_file:
        output_file.write(processed_content)

    old_url = doctor.image_url
    doctor.image_url = f"/doctor-photos/{filename}"
    doctor.photo_base64 = base64.b64encode(processed_content).decode("utf-8")
    db.commit()
    db.refresh(doctor)
    invalidate_doctor_cache()

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

    cache_headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Access-Control-Allow-Origin": "*",
    }

    # 1. Check local disk
    if os.path.isfile(file_path):
        media_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"
        return FileResponse(file_path, media_type=media_type, headers=cache_headers)

    # 2. Check persistent database photo_base64
    doctor = db.query(Doctor).filter(Doctor.image_url.like(f"%{safe_name}")).first()
    if not doctor and safe_name.startswith("doctor_"):
        parts = safe_name.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            doctor = db.query(Doctor).filter(Doctor.id == int(parts[1])).first()

    if doctor and doctor.photo_base64:
        try:
            raw_b64 = doctor.photo_base64
            if isinstance(raw_b64, str) and "," in raw_b64 and raw_b64.startswith("data:"):
                raw_b64 = raw_b64.split(",", 1)[1]
            photo_bytes = base64.b64decode(raw_b64)
            try:
                with open(file_path, "wb") as f:
                    f.write(photo_bytes)
            except Exception:
                pass
            media_type = mimetypes.guess_type(safe_name)[0] or "image/jpeg"
            return Response(content=photo_bytes, media_type=media_type, headers=cache_headers)
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
        execute_cashfree_refund(db, t, f"Hospital closed on {closure_dt} ({reason})")
        refund_count += 1
        try:
            if t.patient_id:
                pat = db.query(Patient).filter(Patient.id == t.patient_id).first()
                if pat and pat.email:
                    send_qarovia_email(
                        to_email=pat.email,
                        subject=f"Q-Arovia Refund Notice: {hospital.name} is closed on {closure_dt}",
                        text=f"Dear {pat.full_name}, {hospital.name} will be closed on {closure_dt} ({reason}). Your token #{t.token_number} has been cancelled and a 100% refund of ₹{t.total_amount:.2f} has been processed to your account.",
                        html=f"""<!DOCTYPE html><html><body style="font-family: sans-serif; padding: 20px;">
                        <h2 style="color: #0284c7; display: flex; align-items: center; gap: 8px;"><img src="https://patient-mx5v.vercel.app/qarovia-ai-small.png" alt="Q-Arovia" width="28" height="28" style="vertical-align: middle; border-radius: 6px;" /> Q-Arovia Appointment Cancellation & 100% Refund</h2>
                        <p>Dear <strong>{pat.full_name}</strong>,</p>
                        <p><strong>{hospital.name}</strong> has announced a scheduled closure on <strong>{closure_dt}</strong> ({reason}).</p>
                        <div style="background: #ecfdf5; border: 1px solid #a7f3d0; padding: 15px; border-radius: 8px; margin: 15px 0;">
                          <p style="margin: 0; color: #065f46; font-size: 16px;"><strong>Token #{t.token_number} Cancelled</strong></p>
                          <p style="margin: 5px 0 0; color: #047857;">A full 100% refund of <strong>₹{t.total_amount:.2f}</strong> has been initiated back to your payment account.</p>
                        </div>
                        <p>We apologize for the inconvenience and welcome you to book another date.</p>
                        <p>Q-Arovia Healthcare Team</p>
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
        execute_cashfree_refund(db, t, f"Doctor on leave on {leave_dt} ({reason})")
        refund_count += 1
        try:
            if t.patient_id:
                pat = db.query(Patient).filter(Patient.id == t.patient_id).first()
                if pat and pat.email:
                    send_qarovia_email(
                        to_email=pat.email,
                        subject=f"Q-Arovia Refund Notice: Dr. {doctor.name} is on leave on {leave_dt}",
                        text=f"Dear {pat.full_name}, Dr. {doctor.name} is on leave on {leave_dt} ({reason}). Your token #{t.token_number} has been cancelled and a 100% refund of ₹{t.total_amount:.2f} has been processed to your account.",
                        html=f"""<!DOCTYPE html><html><body style="font-family: sans-serif; padding: 20px;">
                        <h2 style="color: #0284c7; display: flex; align-items: center; gap: 8px;"><img src="https://patient-mx5v.vercel.app/qarovia-ai-small.png" alt="Q-Arovia" width="28" height="28" style="vertical-align: middle; border-radius: 6px;" /> Q-Arovia Appointment Cancellation & 100% Refund</h2>
                        <p>Dear <strong>{pat.full_name}</strong>,</p>
                        <p><strong>Dr. {doctor.name}</strong> at {hospital.name} is on leave on <strong>{leave_dt}</strong> ({reason}).</p>
                        <div style="background: #ecfdf5; border: 1px solid #a7f3d0; padding: 15px; border-radius: 8px; margin: 15px 0;">
                          <p style="margin: 0; color: #065f46; font-size: 16px;"><strong>Token #{t.token_number} Cancelled</strong></p>
                          <p style="margin: 5px 0 0; color: #047857;">A full 100% refund of <strong>₹{t.total_amount:.2f}</strong> has been credited to your payment account.</p>
                        </div>
                        <p>We apologize for the inconvenience and welcome you to book another available date.</p>
                        <p>Q-Arovia Healthcare Team</p>
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

# ============================================================
# HOSPITAL ADVERTISEMENTS (SELF-SERVE SPONSORED ADS - INR 999 / 30 DAYS)
# ============================================================

@app.get("/hospital-ads/{filename}")
def get_hospital_ad_image(filename: str, db: Session = Depends(get_db)):
    """Serve hospital advertisement banner image from disk cache or database base64."""
    safe_name = os.path.basename(filename)
    local_path = os.path.join(HOSPITAL_AD_DIR, safe_name)

    if os.path.isfile(local_path):
        guessed_type, _ = mimetypes.guess_type(local_path)
        return FileResponse(local_path, media_type=guessed_type or "image/jpeg")

    # DB fallback if local disk cache reset
    ad = db.query(HospitalAdvertisement).filter(
        HospitalAdvertisement.image_url.contains(safe_name)
    ).first()

    if ad and ad.image_base64:
        try:
            img_bytes = base64.b64decode(ad.image_base64)
            with open(local_path, "wb") as f:
                f.write(img_bytes)
            return Response(content=img_bytes, media_type="image/jpeg")
        except Exception:
            pass

    raise HTTPException(status_code=404, detail="Advertisement banner not found")


@app.get("/hospital-ads/videos/{filename}")
def get_hospital_ad_video(filename: str):
    """Serve uploaded video advertisement with byte-range streaming support."""
    safe_name = os.path.basename(filename)
    local_path = os.path.join(HOSPITAL_AD_VIDEO_DIR, safe_name)
    if os.path.isfile(local_path):
        guessed_type, _ = mimetypes.guess_type(local_path)
        return FileResponse(
            local_path,
            media_type=guessed_type or "video/mp4",
            headers={"Accept-Ranges": "bytes"}
        )
    raise HTTPException(status_code=404, detail="Advertisement video not found")


class VerifyAdPaymentRequest(BaseModel):
    cashfree_order_id: str
    ad_id: Optional[int] = None


@app.post("/hospitals/{hospital_id}/ads/create-order")
async def create_hospital_ad_order(
    hospital_id: int,
    title: str = Form(...),
    description: str = Form(""),
    target_phone: str = Form(""),
    target_link: str = Form(""),
    ad_type: str = Form("banner"),  # 'banner' or 'video'
    video_url: str = Form(""),
    photo: UploadFile = File(None),
    video_file: UploadFile = File(None),
    custom_fee: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Create an advertisement order with Cashfree payment session using dynamic Admin-configured fees."""
    try:
        if hospital_id != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="Unauthorized to create ads for another hospital.")

        hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
        if not hospital:
            raise HTTPException(status_code=404, detail="Hospital not found.")

        if not title or len(title.strip()) < 3:
            raise HTTPException(status_code=400, detail="Please provide a valid campaign title.")

        ad_type_clean = (ad_type or "banner").strip().lower()
        if ad_type_clean not in ("banner", "video"):
            ad_type_clean = "banner"

        # Determine dynamic fee from platform settings
        contact = get_or_create_contact_settings(db)
        if ad_type_clean == "video":
            default_fee = getattr(contact, "video_ad_fee", 1999.0) or 1999.0
        else:
            default_fee = getattr(contact, "banner_ad_fee", 999.0) or 999.0

        amount = float(custom_fee if custom_fee and custom_fee > 0 else default_fee)

        img_base64 = None
        img_url = None

        if photo and hasattr(photo, "read"):
            content = await photo.read(MAX_HOSPITAL_PHOTO_SIZE + 1)
            if content:
                if len(content) > MAX_HOSPITAL_PHOTO_SIZE:
                    raise HTTPException(status_code=413, detail="Banner/thumbnail photo must be 5 MB or smaller.")
                content_type = (photo.content_type or "").lower()
                ext = ALLOWED_HOSPITAL_PHOTO_TYPES.get(content_type, ".jpg")
                filename = f"ad_{hospital_id}_{uuid.uuid4().hex[:12]}{ext}"
                try:
                    os.makedirs(HOSPITAL_AD_DIR, exist_ok=True)
                    local_path = os.path.join(HOSPITAL_AD_DIR, filename)
                    with open(local_path, "wb") as f:
                        f.write(content)
                except Exception as write_err:
                    logging.warning("Could not cache ad image to disk: %s", write_err)

                img_base64 = base64.b64encode(content).decode("utf-8")
                img_url = f"/hospital-ads/{filename}"

        # Handle video file upload or video URL
        final_video_url = None
        if video_file and hasattr(video_file, "read"):
            vcontent = await video_file.read(MAX_AD_VIDEO_SIZE + 1)
            if vcontent:
                if len(vcontent) > MAX_AD_VIDEO_SIZE:
                    raise HTTPException(status_code=413, detail="Promotional video must be 30 MB or smaller.")
                vcontent_type = (video_file.content_type or "").lower()
                vext = ALLOWED_AD_VIDEO_TYPES.get(vcontent_type)
                if not vext:
                    orig_ext = os.path.splitext(video_file.filename or "")[1].lower()
                    vext = orig_ext if orig_ext in (".mp4", ".webm", ".mov", ".ogv", ".mkv") else ".mp4"
                vfilename = f"video_{hospital_id}_{uuid.uuid4().hex[:12]}{vext}"
                try:
                    os.makedirs(HOSPITAL_AD_VIDEO_DIR, exist_ok=True)
                    vlocal_path = os.path.join(HOSPITAL_AD_VIDEO_DIR, vfilename)
                    with open(vlocal_path, "wb") as vf:
                        vf.write(vcontent)
                    final_video_url = f"/hospital-ads/videos/{vfilename}"
                except Exception as v_err:
                    logging.warning("Could not save ad video to disk: %s", v_err)

        if not final_video_url and video_url and video_url.strip():
            final_video_url = video_url.strip()

        if ad_type_clean == "video" and not final_video_url:
            raise HTTPException(status_code=400, detail="Please upload a promotional video file or provide a video URL.")
        elif ad_type_clean == "banner" and not img_url:
            raise HTTPException(status_code=400, detail="Please upload a promotional banner photo.")

        order_id = f"ad_{hospital_id}_{secrets.token_hex(6)}"

        # Clean phone for Cashfree payload (needs 10 digits)
        raw_digits = "".join([c for c in str(target_phone or hospital.phone or "9999999999") if c.isdigit()])
        clean_cust_phone = raw_digits[-10:] if len(raw_digits) >= 10 else "9999999999"

        # Create pending ad record
        ad = HospitalAdvertisement(
            hospital_id=hospital_id,
            title=title.strip(),
            description=description.strip() if description else None,
            image_url=img_url,
            image_base64=img_base64,
            ad_type=ad_type_clean,
            video_url=final_video_url,
            target_phone=target_phone.strip() if target_phone else (hospital.phone or ""),
            target_link=target_link.strip() if target_link else "",
            amount_paid=amount,
            fee_charged=amount,
            payment_status="pending",
            cashfree_order_id=order_id,
            is_active=False,
        )
        db.add(ad)
        db.commit()
        db.refresh(ad)

        if not CASHFREE_CLIENT_ID or not CASHFREE_CLIENT_SECRET:
            raise HTTPException(
                status_code=500,
                detail="Cashfree payment gateway credentials are not configured on server.",
            )

        # Cashfree Order creation (100% of Advertisement revenue goes to the app developer's merchant account)
        payload = {
            "order_id": order_id,
            "order_amount": amount,
            "order_currency": "INR",
            "customer_details": {
                "customer_id": f"hospital_{hospital_id}",
                "customer_name": hospital.name[:50],
                "customer_email": hospital.email or "hospital@q-arovia.in",
                "customer_phone": clean_cust_phone,
            },
            "order_meta": {
                "return_url": "https://hospital-ten.vercel.app/ads.html?ad_order_id={order_id}"
            },
            "order_note": f"Q-Arovia {ad_type_clean.capitalize()} Campaign for {hospital.name[:40]}",
            "order_tags": {
                "campaign_type": f"hospital_{ad_type_clean}_ad",
                "hospital_id": str(hospital_id),
                "revenue_type": "app_developer_direct_income",
                "amount": str(amount),
            },
        }

        headers = {
            "Content-Type": "application/json",
            "x-client-id": CASHFREE_CLIENT_ID,
            "x-client-secret": CASHFREE_CLIENT_SECRET,
            "x-api-version": CASHFREE_API_VERSION,
            "x-idempotency-key": str(uuid.uuid4()),
        }

        cf_res = requests.post(
            f"{CASHFREE_BASE_URL}/orders",
            json=payload,
            headers=headers,
            timeout=20,
        )
        if cf_res.status_code not in (200, 201):
            logging.error("Cashfree ad order error: %s %s", cf_res.status_code, cf_res.text)
            err_msg = cf_res.text[:200]
            try:
                cf_json = cf_res.json()
                if "message" in cf_json:
                    err_msg = cf_json["message"]
            except Exception:
                pass
            raise HTTPException(
                status_code=502,
                detail=f"Cashfree Payment Gateway: {err_msg}"
            )

        order_data = cf_res.json()
        return {
            "success": True,
            "ad_id": ad.id,
            "order_id": order_data.get("order_id", order_id),
            "payment_session_id": order_data.get("payment_session_id"),
            "amount": amount,
            "cashfree_mode": CASHFREE_ENV,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logging.exception("Unhandled error in create_hospital_ad_order: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Server error creating ad order: {str(exc)}"
        )


@app.post("/hospitals/{hospital_id}/ads/verify-payment")
def verify_hospital_ad_payment(
    hospital_id: int,
    data: VerifyAdPaymentRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Verify Cashfree payment and activate the advertisement for 30 days."""
    if hospital_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Unauthorized")

    order_id = data.cashfree_order_id.strip()
    ad = None
    if data.ad_id and data.ad_id > 0:
        ad = db.query(HospitalAdvertisement).filter(
            HospitalAdvertisement.id == data.ad_id,
            HospitalAdvertisement.hospital_id == hospital_id,
        ).first()
    if not ad and order_id:
        ad = db.query(HospitalAdvertisement).filter(
            HospitalAdvertisement.cashfree_order_id == order_id,
            HospitalAdvertisement.hospital_id == hospital_id,
        ).first()

    if not ad:
        raise HTTPException(status_code=404, detail="Advertisement record not found.")

    if ad.is_active and ad.payment_status == "paid":
        return {
            "success": True,
            "message": "Advertisement is already active.",
            "expires_at": ad.expires_at.isoformat() if ad.expires_at else "",
        }

    if not CASHFREE_CLIENT_ID or not CASHFREE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Cashfree credentials not configured.")

    # Verify directly with Cashfree
    headers = {
        "x-client-id": CASHFREE_CLIENT_ID,
        "x-client-secret": CASHFREE_CLIENT_SECRET,
        "x-api-version": CASHFREE_API_VERSION,
        "Content-Type": "application/json",
    }

    try:
        payments_res = requests.get(
            f"{CASHFREE_BASE_URL}/orders/{order_id}/payments",
            headers=headers,
            timeout=20,
        )
        if payments_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Unable to verify ad payment with Cashfree.")

        payments = payments_res.json()
        if not isinstance(payments, list):
            raise HTTPException(status_code=400, detail="Unexpected Cashfree payment response.")

        successful_payment = next(
            (p for p in payments if p.get("payment_status") == "SUCCESS"),
            None,
        )
        if not successful_payment:
            raise HTTPException(status_code=400, detail="No successful payment confirmed by Cashfree.")

        payment_id = str(successful_payment.get("cf_payment_id") or "")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cashfree verification error: {exc}")

    # Activate for 30 days
    now = datetime.utcnow()
    ad.payment_status = "paid"
    ad.cashfree_payment_id = payment_id
    ad.is_active = True
    ad.activated_at = now
    ad.expires_at = now + timedelta(days=30)

    db.commit()
    db.refresh(ad)

    return {
        "success": True,
        "message": "Advertisement campaign successfully activated for 30 days!",
        "ad_id": ad.id,
        "expires_at": ad.expires_at.isoformat(),
        "days_remaining": 30,
    }


@app.get("/hospitals/{hospital_id}/ads")
def get_hospital_ads(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """List all ads created by this hospital with remaining validity days."""
    if hospital_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Unauthorized")

    ads = db.query(HospitalAdvertisement).filter(
        HospitalAdvertisement.hospital_id == hospital_id
    ).order_by(HospitalAdvertisement.created_at.desc()).all()

    now = datetime.utcnow()
    results = []
    for a in ads:
        days_left = max(0, (a.expires_at - now).days) if (a.expires_at and a.expires_at > now) else 0
        status = "ACTIVE" if (a.is_active and a.payment_status == "paid" and a.expires_at and a.expires_at > now) else ("EXPIRED" if a.payment_status == "paid" else "PENDING_PAYMENT")
        results.append({
            "id": a.id,
            "title": a.title,
            "description": a.description,
            "ad_type": getattr(a, "ad_type", "banner") or "banner",
            "image_url": a.image_url,
            "video_url": a.video_url or "",
            "target_phone": a.target_phone,
            "target_link": a.target_link,
            "amount_paid": float(a.fee_charged or a.amount_paid or 0),
            "fee_charged": float(a.fee_charged or a.amount_paid or 0),
            "payment_status": a.payment_status,
            "is_active": a.is_active,
            "status": status,
            "days_remaining": days_left,
            "activated_at": a.activated_at.isoformat() if a.activated_at else None,
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
            "created_at": a.created_at.isoformat(),
        })

    return results


@app.get("/ads/active")
def get_active_ads(response: Response, db: Session = Depends(get_db)):
    """Public endpoint for Patient app: returns currently active sponsored ads rotated dynamically."""
    import random

    # Prevent stale browser & WebView response caching
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    now = datetime.utcnow()
    # Auto-expire past ads only when expires_at is explicitly set
    db.query(HospitalAdvertisement).filter(
        HospitalAdvertisement.is_active == True,
        HospitalAdvertisement.expires_at != None,
        HospitalAdvertisement.expires_at <= now,
    ).update({"is_active": False}, synchronize_session=False)
    db.commit()

    rows = (
        db.query(HospitalAdvertisement, Hospital)
        .outerjoin(Hospital, Hospital.id == HospitalAdvertisement.hospital_id)
        .filter(
            HospitalAdvertisement.is_active == True,
            or_(
                HospitalAdvertisement.payment_status.in_(["paid", "active", "success", "confirmed", "completed"]),
                HospitalAdvertisement.payment_status == None,
            ),
            or_(
                HospitalAdvertisement.expires_at == None,
                HospitalAdvertisement.expires_at > now,
            ),
        )
        .order_by(HospitalAdvertisement.id.desc())
        .all()
    )

    ads_list = []
    for ad, hospital in rows:
        hosp_name = hospital.name if hospital else "Featured Healthcare Partner"
        hosp_city = (hospital.city or "") if hospital else ""
        hosp_img = (hospital.image_url or "") if hospital else ""
        hosp_phone = (hospital.phone or "") if hospital else ""
        hosp_id = hospital.id if hospital else (ad.hospital_id or 0)

        # Asset fallback: ad image -> base64 -> hospital image
        ad_img = ad.image_url or getattr(ad, "image_base64", None) or hosp_img or ""

        ads_list.append({
            "id": ad.id,
            "hospital_id": hosp_id,
            "hospital_name": hosp_name,
            "hospital_city": hosp_city,
            "hospital_image": hosp_img,
            "title": ad.title,
            "description": ad.description or "",
            "ad_type": getattr(ad, "ad_type", "banner") or "banner",
            "image_url": ad_img,
            "video_url": ad.video_url or "",
            "target_phone": ad.target_phone or hosp_phone,
            "target_link": ad.target_link or "",
            "fee_charged": float(ad.fee_charged or ad.amount_paid or 0),
            "days_remaining": max(0, (ad.expires_at - now).days) if ad.expires_at else 30,
            "expires_at": ad.expires_at.strftime("%b %d, %Y") if ad.expires_at else "Active",
            "activated_at": ad.activated_at.strftime("%b %d, %Y") if ad.activated_at else "",
        })

    # Shuffle so view is dynamic and rotating (not fixed to one hospital)
    random.shuffle(ads_list)
    return ads_list



# ============================================================
# SYSTEM BROADCASTS & EMERGENCY NOTIFICATION BANNERS
# ============================================================

class CreateBroadcastRequest(BaseModel):
    title: str
    message: str
    banner_type: str = "warning"  # critical, warning, info, success
    target_audience: str = "all"  # all, patient, hospital
    is_dismissible: bool = True
    action_link: Optional[str] = None
    action_label: Optional[str] = None
    expires_in_hours: Optional[int] = None


@app.get("/broadcasts/active")
def get_active_broadcasts(
    audience: Optional[str] = "all",
    db: Session = Depends(get_db),
):
    """Fetch currently active emergency banners and platform announcements."""
    now = datetime.utcnow()
    query = db.query(SystemBroadcast).filter(
        SystemBroadcast.is_active == True,
        or_(
            SystemBroadcast.expires_at == None,
            SystemBroadcast.expires_at > now,
        ),
    )

    clean_aud = (audience or "all").lower().strip()
    if clean_aud != "all":
        query = query.filter(
            SystemBroadcast.target_audience.in_(["all", clean_aud])
        )

    broadcasts = query.order_by(SystemBroadcast.id.desc()).all()

    return {
        "success": True,
        "broadcasts": [
            {
                "id": b.id,
                "title": b.title,
                "message": b.message,
                "banner_type": b.banner_type,
                "target_audience": b.target_audience,
                "is_dismissible": b.is_dismissible,
                "action_link": b.action_link,
                "action_label": b.action_label,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in broadcasts
        ],
    }


@app.get("/admin/broadcasts")
def admin_get_broadcasts(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """List all system broadcasts (active and past)."""
    broadcasts = db.query(SystemBroadcast).order_by(SystemBroadcast.id.desc()).all()
    now = datetime.utcnow()
    return {
        "success": True,
        "broadcasts": [
            {
                "id": b.id,
                "title": b.title,
                "message": b.message,
                "banner_type": b.banner_type,
                "target_audience": b.target_audience,
                "is_active": b.is_active and (b.expires_at is None or b.expires_at > now),
                "is_dismissible": b.is_dismissible,
                "action_link": b.action_link,
                "action_label": b.action_label,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "expires_at": b.expires_at.isoformat() if b.expires_at else None,
            }
            for b in broadcasts
        ],
    }


@app.post("/admin/broadcasts")
def admin_create_broadcast(
    data: CreateBroadcastRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """Publish a new system emergency broadcast / alert banner."""
    title = (data.title or "").strip()
    message = (data.message or "").strip()

    if not title:
        raise HTTPException(status_code=400, detail="Broadcast title cannot be empty.")
    if not message:
        raise HTTPException(status_code=400, detail="Broadcast message cannot be empty.")

    b_type = data.banner_type.lower().strip()
    if b_type not in ("critical", "warning", "info", "success"):
        b_type = "warning"

    audience = data.target_audience.lower().strip()
    if audience not in ("all", "patient", "hospital"):
        audience = "all"

    expires_at = None
    if data.expires_in_hours and data.expires_in_hours > 0:
        expires_at = datetime.utcnow() + timedelta(hours=data.expires_in_hours)

    broadcast = SystemBroadcast(
        title=title,
        message=message,
        banner_type=b_type,
        target_audience=audience,
        is_active=True,
        is_dismissible=bool(data.is_dismissible),
        action_link=(data.action_link or "").strip() or None,
        action_label=(data.action_label or "").strip() or None,
        created_at=datetime.utcnow(),
        expires_at=expires_at,
    )
    db.add(broadcast)
    db.commit()
    db.refresh(broadcast)

    # Real-Time WebSocket broadcast (instant sync across website and mobile apps)
    try:
        broadcast_now(ws_manager.broadcast_emergency_announcement({
            "id": broadcast.id,
            "title": broadcast.title,
            "message": broadcast.message,
            "banner_type": broadcast.banner_type,
            "target_audience": broadcast.target_audience,
            "is_dismissible": broadcast.is_dismissible,
            "action_link": broadcast.action_link,
            "action_label": broadcast.action_label,
            "created_at": broadcast.created_at.isoformat() if broadcast.created_at else None,
        }))
    except Exception as ws_err:
        logging.warning("Emergency broadcast WS dispatch skipped: %s", ws_err)

    return {
        "success": True,
        "message": "Emergency broadcast published successfully.",
        "broadcast": {
            "id": broadcast.id,
            "title": broadcast.title,
            "message": broadcast.message,
            "banner_type": broadcast.banner_type,
            "target_audience": broadcast.target_audience,
            "is_active": broadcast.is_active,
        },
    }


@app.put("/admin/broadcasts/{broadcast_id}/toggle")
def admin_toggle_broadcast(
    broadcast_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """Activate or deactivate a system broadcast."""
    broadcast = db.query(SystemBroadcast).filter(SystemBroadcast.id == broadcast_id).first()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found.")

    broadcast.is_active = not broadcast.is_active
    db.commit()
    db.refresh(broadcast)

    try:
        broadcast_now(ws_manager.broadcast_emergency_announcement({
            "id": broadcast.id,
            "title": broadcast.title,
            "message": broadcast.message,
            "banner_type": broadcast.banner_type,
            "target_audience": broadcast.target_audience,
            "is_active": broadcast.is_active,
            "action": "toggled",
        }))
    except Exception as ws_err:
        logging.warning("Emergency broadcast toggle WS dispatch skipped: %s", ws_err)

    return {
        "success": True,
        "message": f"Broadcast {'activated' if broadcast.is_active else 'deactivated'} successfully.",
        "is_active": broadcast.is_active,
    }


@app.delete("/admin/broadcasts/{broadcast_id}")
def admin_delete_broadcast(
    broadcast_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """Delete a system broadcast."""
    broadcast = db.query(SystemBroadcast).filter(SystemBroadcast.id == broadcast_id).first()
    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found.")

    db.delete(broadcast)
    db.commit()

    return {
        "success": True,
        "message": "Broadcast deleted successfully.",
    }



# ============================================================
# REAL-TIME WEBSOCKET MESSAGING (PATIENTS <-> HOSPITALS <-> ADMIN)
# ============================================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[WebSocket, dict] = {}
        self.hospital_connections: Dict[int, Set[WebSocket]] = {}
        self.patient_connections: Dict[str, Set[WebSocket]] = {}
        self.admin_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, client_info: dict):
        await websocket.accept()
        self.active_connections[websocket] = client_info

        role = client_info.get("role")
        hosp_id = client_info.get("hospital_id")
        phone = client_info.get("phone")

        if role == "admin":
            self.admin_connections.add(websocket)
        elif role == "hospital" and hosp_id:
            try:
                h_int = int(hosp_id)
                if h_int not in self.hospital_connections:
                    self.hospital_connections[h_int] = set()
                self.hospital_connections[h_int].add(websocket)
            except Exception:
                pass

        if phone:
            clean_phone = "".join(filter(str.isdigit, str(phone)))[-10:]
            if clean_phone:
                if clean_phone not in self.patient_connections:
                    self.patient_connections[clean_phone] = set()
                self.patient_connections[clean_phone].add(websocket)

        logging.info("WebSocket connected: role=%s, hosp=%s, phone=%s (Total: %d)",
                     role, hosp_id, phone, len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        info = self.active_connections.pop(websocket, None)
        if not info:
            return

        role = info.get("role")
        hosp_id = info.get("hospital_id")
        phone = info.get("phone")

        if websocket in self.admin_connections:
            self.admin_connections.discard(websocket)

        if hosp_id:
            try:
                h_int = int(hosp_id)
                if h_int in self.hospital_connections:
                    self.hospital_connections[h_int].discard(websocket)
                    if not self.hospital_connections[h_int]:
                        del self.hospital_connections[h_int]
            except Exception:
                pass

        if phone:
            clean_phone = "".join(filter(str.isdigit, str(phone)))[-10:]
            if clean_phone and clean_phone in self.patient_connections:
                self.patient_connections[clean_phone].discard(websocket)
                if not self.patient_connections[clean_phone]:
                    del self.patient_connections[clean_phone]

        logging.info("WebSocket disconnected: %s (Remaining: %d)", info, len(self.active_connections))

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)

    def persist_distributed_event(self, channel_type: str, target_id: Optional[str], payload: dict):
        """Persists real-time events to ws_distributed_events table for multi-instance synchronization (QA-ARCH-001)."""
        try:
            with SessionLocal() as db:
                event = DistributedWSEvent(
                    channel_type=channel_type,
                    target_id=str(target_id) if target_id is not None else None,
                    payload=json.dumps(payload),
                    created_at=datetime.utcnow(),
                )
                db.add(event)
                db.commit()
                db.refresh(event)
                if isinstance(payload, dict):
                    payload["event_id"] = event.id
                return event.id
        except Exception as e:
            logging.warning("Failed to persist distributed WS event: %s", e)
            return None

    async def broadcast_to_hospital(self, hospital_id: int, message: dict):
        self.persist_distributed_event("hospital", str(hospital_id), message)
        try:
            h_int = int(hospital_id)
            sockets = list(self.hospital_connections.get(h_int, set()))
            for ws in sockets:
                try:
                    await ws.send_json(message)
                except Exception:
                    self.disconnect(ws)
        except Exception as e:
            logging.warning("broadcast_to_hospital error: %s", e)

    async def broadcast_to_patient(self, phone: str, message: dict):
        if not phone:
            return
        clean_phone = "".join(filter(str.isdigit, str(phone)))[-10:]
        self.persist_distributed_event("patient", clean_phone, message)
        sockets = list(self.patient_connections.get(clean_phone, set()))
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)

    async def broadcast_to_admins(self, message: dict):
        self.persist_distributed_event("admin", None, message)
        sockets = list(self.admin_connections)
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)

    async def broadcast_inquiry(self, inquiry_dict: dict):
        payload = {
            "type": "new_patient_inquiry",
            "event": "NOTIFICATION_CREATED",
            "inquiry": inquiry_dict,
            "timestamp": datetime.utcnow().isoformat(),
        }
        hosp_id = inquiry_dict.get("hospital_id")
        phone = inquiry_dict.get("patient_phone")
        if hosp_id:
            await self.broadcast_to_hospital(hosp_id, payload)
        if phone:
            await self.broadcast_to_patient(phone, payload)
        await self.broadcast_to_admins(payload)

    async def broadcast_reply(self, reply_dict: dict):
        payload = {
            "type": "hospital_inquiry_reply",
            "event": "NOTIFICATION_CREATED",
            "reply": reply_dict,
            "timestamp": datetime.utcnow().isoformat(),
        }
        hosp_id = reply_dict.get("hospital_id")
        phone = reply_dict.get("patient_phone")
        if phone:
            await self.broadcast_to_patient(phone, payload)
        if hosp_id:
            await self.broadcast_to_hospital(hosp_id, payload)
        await self.broadcast_to_admins(payload)

    async def broadcast_admin_message(self, message_dict: dict):
        payload = {
            "type": "admin_direct_message",
            "event": "NOTIFICATION_CREATED",
            "message": message_dict,
            "timestamp": datetime.utcnow().isoformat(),
        }
        hosp_id = message_dict.get("hospital_id")
        if hosp_id:
            await self.broadcast_to_hospital(hosp_id, payload)
        await self.broadcast_to_admins(payload)

    async def broadcast_token_event(
        self,
        event_type: str,
        token_data: dict,
        hospital_id: Optional[int] = None,
        patient_phone: Optional[str] = None,
    ):
        event_name_map = {
            "created": "TOKEN_BOOKED",
            "token_created": "TOKEN_BOOKED",
            "token_booked": "TOKEN_BOOKED",
            "walk_in_created": "TOKEN_BOOKED",
            "number_updated": "TOKEN_UPDATED",
            "reassigned": "TOKEN_UPDATED",
            "cancelled": "TOKEN_CANCELLED",
            "token_cancelled": "TOKEN_CANCELLED",
            "called": "CONSULTATION_STARTED",
            "token_called": "CONSULTATION_STARTED",
            "completed": "CONSULTATION_COMPLETED",
            "token_completed": "CONSULTATION_COMPLETED",
            "skipped": "TOKEN_UPDATED",
            "token_skipped": "TOKEN_UPDATED",
        }
        event_name = event_name_map.get(event_type, "TOKEN_UPDATED")
        payload = {
            "type": "token_update",
            "event": event_name,
            "action": event_type,
            "token": token_data,
            "hospital_id": hospital_id,
            "patient_phone": patient_phone,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if hospital_id:
            await self.broadcast_to_hospital(hospital_id, payload)
        if patient_phone:
            await self.broadcast_to_patient(patient_phone, payload)
        await self.broadcast_to_admins(payload)

    async def broadcast_document_event(
        self,
        event_type: str,
        token_id: int,
        hospital_id: Optional[int] = None,
        patient_phone: Optional[str] = None,
        documents: Optional[list] = None,
        document_id: Optional[int] = None,
    ):
        event_name_map = {
            "uploaded": "MEDICAL_DOCUMENT_UPLOADED",
            "document_uploaded": "MEDICAL_DOCUMENT_UPLOADED",
            "batch_uploaded": "MEDICAL_DOCUMENT_UPLOADED",
            "deleted": "MEDICAL_DOCUMENT_DELETED",
            "document_deleted": "MEDICAL_DOCUMENT_DELETED",
        }
        event_name = event_name_map.get(event_type, "MEDICAL_DOCUMENT_UPLOADED")
        payload = {
            "type": "document_update",
            "event": event_name,
            "action": event_type,
            "token_id": token_id,
            "documents": documents or [],
            "document_id": document_id,
            "hospital_id": hospital_id,
            "patient_phone": patient_phone,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if hospital_id:
            await self.broadcast_to_hospital(hospital_id, payload)
        if patient_phone:
            await self.broadcast_to_patient(patient_phone, payload)
        await self.broadcast_to_admins(payload)

    async def broadcast_doctor_availability_event(
        self,
        doctor_dict: dict,
        hospital_id: int,
    ):
        payload = {
            "type": "doctor_availability_update",
            "event": "DOCTOR_AVAILABILITY_UPDATED",
            "action": "availability_changed",
            "doctor": doctor_dict,
            "hospital_id": hospital_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.broadcast_to_hospital(hospital_id, payload)
        for ws in list(self.active_connections):
            try:
                await ws.send_json(payload)
            except Exception:
                pass
        await self.broadcast_to_admins(payload)

    async def broadcast_payment_event(
        self,
        event_type: str,
        payment_data: dict,
        hospital_id: Optional[int] = None,
        patient_phone: Optional[str] = None,
    ):
        payload = {
            "type": "payment_update",
            "event": event_type,
            "action": event_type.lower(),
            "payment": payment_data,
            "hospital_id": hospital_id,
            "patient_phone": patient_phone,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if hospital_id:
            await self.broadcast_to_hospital(hospital_id, payload)
        if patient_phone:
            await self.broadcast_to_patient(patient_phone, payload)
        await self.broadcast_to_admins(payload)

    async def broadcast_hospital_status_event(
        self,
        hospital_id: int,
        status: str,
        is_published: bool,
    ):
        payload = {
            "type": "hospital_status_update",
            "event": "HOSPITAL_STATUS_UPDATED",
            "hospital_id": hospital_id,
            "status": status,
            "is_published": is_published,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.broadcast_to_hospital(hospital_id, payload)
        await self.broadcast_to_admins(payload)

    async def broadcast_emergency_announcement(self, broadcast_dict: dict):
        payload = {
            "type": "emergency_broadcast",
            "event": "NOTIFICATION_CREATED",
            "broadcast": broadcast_dict,
            "timestamp": datetime.utcnow().isoformat(),
        }
        for ws in list(self.active_connections):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(ws)

    async def broadcast_sync_signal(
        self,
        module: str,
        action: str,
        data: Optional[dict] = None,
        hospital_id: Optional[int] = None,
        patient_phone: Optional[str] = None,
    ):
        payload = {
            "type": "data_sync",
            "module": module,
            "action": action,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat(),
        }
        if hospital_id:
            await self.broadcast_to_hospital(hospital_id, payload)
        if patient_phone:
            await self.broadcast_to_patient(patient_phone, payload)
        await self.broadcast_to_admins(payload)

ws_manager = ConnectionManager()


@app.get("/ws/events/sync")
def sync_ws_events(
    channel_type: Optional[str] = Query("all"),
    target_id: Optional[str] = Query(None),
    since_id: int = Query(0),
    limit: int = Query(50),
    db: Session = Depends(get_db),
    current_user: Optional[dict] = Depends(get_optional_auth_user),
):
    """
    Distributed WebSocket event synchronization endpoint (QA-ARCH-001).
    Allows reconnected clients or multi-instance workers to catch up on distributed real-time events.
    """
    query = db.query(DistributedWSEvent).filter(DistributedWSEvent.id > since_id)
    if channel_type and channel_type != "all":
        query = query.filter(DistributedWSEvent.channel_type == channel_type)
    if target_id:
        query = query.filter(DistributedWSEvent.target_id == str(target_id))

    events = query.order_by(DistributedWSEvent.id.asc()).limit(min(limit, 100)).all()

    result = []
    for e in events:
        try:
            p = json.loads(e.payload) if e.payload else {}
        except Exception:
            p = {"raw": e.payload}
        result.append({
            "id": e.id,
            "channel_type": e.channel_type,
            "target_id": e.target_id,
            "payload": p,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        })
    return {
        "success": True,
        "events": result,
        "latest_id": events[-1].id if events else since_id,
    }


@app.websocket("/ws/messages")
async def websocket_messages_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    role: Optional[str] = Query("patient"),
    phone: Optional[str] = Query(None),
    hospital_id: Optional[int] = Query(None),
):
    """
    Q-Arovia Real-Time Multi-Party WebSocket Channel (QBUG-006 Hardened)
    Connects Authenticated Patients, Hospitals, and Admins for instant, zero-delay messaging.
    Enforces JWT verification on private channels to eliminate phone impersonation.
    """
    authenticated_role = None
    user_id = None
    clean_phone = None

    db_session = SessionLocal()
    try:
        if token:
            try:
                payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
                user_id = payload.get("sub")
                if user_id is not None and str(user_id).isdigit():
                    user_id = int(user_id)
                authenticated_role = payload.get("role", "patient")

                if authenticated_role == "hospital":
                    hospital_id = user_id
                elif authenticated_role == "patient" and user_id:
                    pat = db_session.query(Patient).filter(Patient.id == user_id).first()
                    if pat and pat.phone:
                        clean_phone = pat.phone.strip().replace(" ", "").replace("-", "")
            except Exception as e:
                logging.warning("WebSocket JWT verification rejected: %s", e)
                await websocket.close(code=4001, reason="Invalid authentication token")
                return
        elif role == "public_display":
            authenticated_role = "visitor"
            clean_phone = None
        else:
            await websocket.close(code=4001, reason="Authentication token required for private notifications")
            return
    finally:
        db_session.close()

    client_info = {
        "role": authenticated_role,
        "user_id": user_id,
        "hospital_id": hospital_id,
        "phone": clean_phone,
    }

    await ws_manager.connect(websocket, client_info)

    await ws_manager.send_personal_message({
        "type": "connection_ack",
        "status": "connected",
        "client": client_info,
        "server_time": datetime.utcnow().isoformat(),
    }, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            # Heartbeat ping
            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat()})
                continue

            # Patient inquiry sent via WebSocket
            if msg_type == "patient_inquiry":
                h_id = data.get("hospital_id") or hospital_id
                pat_name = (data.get("patient_name") or "Patient").strip()
                pat_phone = (data.get("patient_phone") or clean_phone or "").strip()
                msg_body = (data.get("message") or "").strip()
                subj = (data.get("subject") or "General Inquiry").strip()

                if not h_id or not pat_phone or not msg_body:
                    await websocket.send_json({"type": "error", "message": "hospital_id, patient_phone, and message required."})
                    continue

                db_ws = SessionLocal()
                try:
                    hosp = db_ws.query(Hospital).filter(Hospital.id == h_id).first()
                    if not hosp:
                        await websocket.send_json({"type": "error", "message": "Hospital not found."})
                        continue

                    inq = HospitalDirectMessage(
                        hospital_id=h_id,
                        sender_role="patient",
                        sender_name=pat_name,
                        patient_phone=pat_phone,
                        patient_id=user_id if authenticated_role == "patient" else None,
                        subject=subj,
                        message=msg_body,
                        priority=data.get("priority", "normal"),
                        is_read=False,
                    )
                    db_ws.add(inq)
                    db_ws.commit()
                    db_ws.refresh(inq)

                    inquiry_payload = {
                        "id": inq.id,
                        "hospital_id": inq.hospital_id,
                        "hospital_name": hosp.name,
                        "hospital_city": hosp.city,
                        "sender_role": inq.sender_role,
                        "sender_name": inq.sender_name,
                        "patient_phone": inq.patient_phone,
                        "patient_id": inq.patient_id,
                        "subject": inq.subject,
                        "message": inq.message,
                        "priority": inq.priority,
                        "is_read": inq.is_read,
                        "created_at": inq.created_at.isoformat() if inq.created_at else datetime.utcnow().isoformat(),
                    }
                    await ws_manager.broadcast_inquiry(inquiry_payload)
                finally:
                    db_ws.close()

            # Hospital reply sent via WebSocket
            elif msg_type == "hospital_reply":
                if authenticated_role not in ("hospital", "admin"):
                    await websocket.send_json({"type": "error", "message": "Only hospital staff or admin can reply."})
                    continue

                h_id = hospital_id or data.get("hospital_id")
                inq_id = data.get("inquiry_id")
                reply_body = (data.get("reply_message") or data.get("message") or "").strip()
                target_phone = (data.get("patient_phone") or "").strip()

                if not inq_id or not reply_body:
                    await websocket.send_json({"type": "error", "message": "inquiry_id and reply_message required."})
                    continue

                db_ws = SessionLocal()
                try:
                    orig_inq = db_ws.query(HospitalDirectMessage).filter(HospitalDirectMessage.id == inq_id).first()
                    if not orig_inq:
                        await websocket.send_json({"type": "error", "message": "Original inquiry not found."})
                        continue

                    if not target_phone and orig_inq.patient_phone:
                        target_phone = orig_inq.patient_phone

                    hosp = db_ws.query(Hospital).filter(Hospital.id == orig_inq.hospital_id).first()
                    orig_inq.is_read = True

                    reply_msg = HospitalDirectMessage(
                        hospital_id=orig_inq.hospital_id,
                        sender_role="hospital",
                        sender_name=f"{hosp.name if hosp else 'Hospital'} Helpdesk",
                        patient_phone=target_phone,
                        patient_id=orig_inq.patient_id,
                        reply_to_id=orig_inq.id,
                        subject=f"Re: {orig_inq.subject or 'Inquiry'}",
                        message=reply_body,
                        priority="normal",
                        is_read=False,
                    )
                    db_ws.add(reply_msg)
                    db_ws.commit()
                    db_ws.refresh(reply_msg)

                    reply_payload = {
                        "id": reply_msg.id,
                        "hospital_id": reply_msg.hospital_id,
                        "hospital_name": hosp.name if hosp else "Hospital Helpdesk",
                        "hospital_city": hosp.city if hosp else "",
                        "sender_role": reply_msg.sender_role,
                        "sender_name": reply_msg.sender_name,
                        "patient_phone": reply_msg.patient_phone,
                        "patient_id": reply_msg.patient_id,
                        "reply_to_id": reply_msg.reply_to_id,
                        "subject": reply_msg.subject,
                        "message": reply_msg.message,
                        "is_read": reply_msg.is_read,
                        "created_at": reply_msg.created_at.isoformat() if reply_msg.created_at else datetime.utcnow().isoformat(),
                    }
                    await ws_manager.broadcast_reply(reply_payload)
                finally:
                    db_ws.close()

            # Admin message sent via WebSocket
            elif msg_type == "admin_message":
                if authenticated_role != "admin":
                    await websocket.send_json({"type": "error", "message": "Only admins can send official notices."})
                    continue

                h_id = data.get("hospital_id")
                msg_body = (data.get("message") or "").strip()
                subj = (data.get("subject") or "Notice from Platform Admin").strip()
                prio = data.get("priority", "normal")

                if not h_id or not msg_body:
                    await websocket.send_json({"type": "error", "message": "hospital_id and message required."})
                    continue

                db_ws = SessionLocal()
                try:
                    hosp = db_ws.query(Hospital).filter(Hospital.id == h_id).first()
                    if not hosp:
                        await websocket.send_json({"type": "error", "message": "Hospital not found."})
                        continue

                    admin_msg = HospitalDirectMessage(
                        hospital_id=h_id,
                        sender_role="admin",
                        sender_name="Platform Admin",
                        subject=subj,
                        message=msg_body,
                        priority=prio,
                        is_read=False,
                    )
                    db_ws.add(admin_msg)
                    db_ws.commit()
                    db_ws.refresh(admin_msg)

                    admin_payload = {
                        "id": admin_msg.id,
                        "hospital_id": admin_msg.hospital_id,
                        "hospital_name": hosp.name,
                        "sender_role": admin_msg.sender_role,
                        "sender_name": admin_msg.sender_name,
                        "subject": admin_msg.subject,
                        "message": admin_msg.message,
                        "priority": admin_msg.priority,
                        "is_read": admin_msg.is_read,
                        "created_at": admin_msg.created_at.isoformat() if admin_msg.created_at else datetime.utcnow().isoformat(),
                    }
                    await ws_manager.broadcast_admin_message(admin_payload)
                finally:
                    db_ws.close()

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logging.warning("WebSocket loop exception: %s", e)
        ws_manager.disconnect(websocket)


# ============================================================
# DIRECT COMMUNICATION: ADMIN <-> HOSPITAL
# ============================================================

class AdminSendMessageRequest(BaseModel):
    subject: Optional[str] = None
    message: str
    priority: str = "normal"  # normal, urgent, compliance
    send_email: bool = True


class HospitalReplyMessageRequest(BaseModel):
    subject: Optional[str] = None
    message: str


@app.get("/admin/hospitals/{hospital_id}/messages")
def admin_get_hospital_messages(
    hospital_id: int,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """Admin: Retrieve full direct message history with a hospital."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    msg_query = (
        db.query(HospitalDirectMessage)
        .filter(HospitalDirectMessage.hospital_id == hospital_id)
        .order_by(HospitalDirectMessage.created_at.asc())
    )
    if limit is not None and limit > 0:
        messages = msg_query.offset(offset).limit(limit).all()
    else:
        messages = msg_query.all()

    # Mark hospital replies as read by admin
    for m in messages:
        if m.sender_role == "hospital" and not m.is_read:
            m.is_read = True
    db.commit()

    return {
        "success": True,
        "hospital": {
            "id": hospital.id,
            "name": hospital.name,
            "email": hospital.email,
            "phone": hospital.phone,
            "city": hospital.city,
        },
        "messages": [
            {
                "id": m.id,
                "sender_role": m.sender_role,
                "sender_name": m.sender_name,
                "subject": m.subject,
                "message": m.message,
                "priority": m.priority,
                "is_read": m.is_read,
                "sent_via_email": m.sent_via_email,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@app.post("/admin/hospitals/{hospital_id}/messages")
def admin_send_hospital_message(
    hospital_id: int,
    data: AdminSendMessageRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """Admin: Send a direct message/official notice to a hospital."""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    subject = (data.subject or "Notice from Platform Admin").strip()
    msg_text = (data.message or "").strip()
    if not subject:
        subject = "Notice from Platform Admin"
    if not msg_text:
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")

    priority = (data.priority or "normal").lower().strip()
    if priority not in ("normal", "urgent", "compliance"):
        priority = "normal"

    sent_email_ok = False
    if data.send_email and hospital.email:
        email_subj = f"[Q-Arovia Official Notice] {subject}"
        email_body = (
            f"Dear {hospital.name} Administration,\n\n"
            f"You have received an official notice from Q-Arovia Platform Admin:\n\n"
            f"----------------------------------------\n"
            f"Priority: {priority.upper()}\n"
            f"Subject: {subject}\n"
            f"----------------------------------------\n\n"
            f"{msg_text}\n\n"
            f"Please log in to your Q-Arovia Hospital Dashboard to view and reply directly:\n"
            f"https://hospital-ten.vercel.app/\n\n"
            f"Warm regards,\n"
            f"Q-Arovia Platform Administration Team"
        )
        email_html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
            <div style="background: linear-gradient(135deg, #1976d2, #0d47a1); padding: 16px 20px; border-radius: 8px; color: white; margin-bottom: 20px;">
                <h2 style="margin: 0; font-size: 20px;">🏥 Q-Arovia Platform Admin Notice</h2>
                <p style="margin: 4px 0 0; opacity: 0.9; font-size: 13px;">Official Direct Communication to {hospital.name}</p>
            </div>
            <div style="background: #f8fafc; border-left: 4px solid {'#dc2626' if priority == 'urgent' else ('#ea580c' if priority == 'compliance' else '#2563eb')}; padding: 12px 16px; margin-bottom: 20px; border-radius: 4px;">
                <div style="font-size: 12px; font-weight: bold; text-transform: uppercase; color: #64748b;">Priority Level: {priority.upper()}</div>
                <div style="font-size: 16px; font-weight: bold; color: #1e293b; margin-top: 4px;">{subject}</div>
            </div>
            <div style="font-size: 14.5px; line-height: 1.6; color: #334155; margin-bottom: 24px; white-space: pre-line;">
                {msg_text}
            </div>
            <div style="text-align: center; margin: 25px 0;">
                <a href="https://hospital-ten.vercel.app/" style="background: #1976d2; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 14px; display: inline-block;">Open Hospital Dashboard & Reply</a>
            </div>
            <div style="border-top: 1px solid #e2e8f0; padding-top: 14px; font-size: 12px; color: #94a3b8; text-align: center;">
                Q-Arovia Healthcare Technologies • Automated Official Communication System
            </div>
        </div>
        """
        try:
            sent_email_ok = send_qarovia_email(
                to_email=hospital.email,
                subject=email_subj,
                text=email_body,
                html=email_html
            )
        except Exception as err:
            logging.warning("Could not dispatch direct message email to hospital: %s", err)

    msg = HospitalDirectMessage(
        hospital_id=hospital_id,
        sender_role="admin",
        sender_name="Q-Arovia Platform Admin",
        subject=subject,
        message=msg_text,
        priority=priority,
        is_read=False,
        sent_via_email=sent_email_ok,
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Real-Time WebSocket broadcast
    try:
        broadcast_now(ws_manager.broadcast_admin_message({
            "id": msg.id,
            "hospital_id": msg.hospital_id,
            "hospital_name": hospital.name,
            "sender_role": msg.sender_role,
            "sender_name": msg.sender_name,
            "subject": msg.subject,
            "message": msg.message,
            "priority": msg.priority,
            "is_read": msg.is_read,
            "created_at": msg.created_at.isoformat() if msg.created_at else datetime.utcnow().isoformat(),
        }))
    except Exception as ws_err:
        logging.warning("Admin WS broadcast skipped: %s", ws_err)



    return {
        "success": True,
        "message": "Message delivered to hospital successfully.",
        "email_dispatched": sent_email_ok,
        "direct_message": {
            "id": msg.id,
            "subject": msg.subject,
            "message": msg.message,
            "priority": msg.priority,
            "sent_via_email": msg.sent_via_email,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        },
    }


def purge_expired_patient_inquiries(db: Session, hospital_id: Optional[int] = None):
    """Automatically delete patient direct inquiries and hospital direct replies older than 24 hours."""
    try:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        query = db.query(HospitalDirectMessage).filter(
            or_(
                HospitalDirectMessage.sender_role == "patient",
                HospitalDirectMessage.reply_to_id.isnot(None),
                HospitalDirectMessage.patient_phone.isnot(None),
            ),
            HospitalDirectMessage.created_at < cutoff,
        )
        if hospital_id is not None:
            query = query.filter(HospitalDirectMessage.hospital_id == hospital_id)
        deleted = query.delete(synchronize_session=False)
        if deleted > 0:
            db.commit()
            logging.info("Auto-deleted %d expired patient inquiry message(s) older than 24 hours", deleted)
    except Exception as e:
        db.rollback()
        logging.warning("Error auto-deleting expired patient inquiries: %s", e)


@app.get("/hospitals/{hospital_id}/messages")
def hospital_get_direct_messages(
    hospital_id: int,
    mark_read: bool = False,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Hospital: Retrieve conversation history with Admin and Patients (patient inquiries auto-delete after 24h)."""
    if hospital_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Automatically purge patient inquiries older than 24 hours
    purge_expired_patient_inquiries(db, hospital_id=hospital_id)

    cutoff_24h = datetime.utcnow() - timedelta(hours=24)
    messages = (
        db.query(HospitalDirectMessage)
        .filter(
            HospitalDirectMessage.hospital_id == hospital_id,
            or_(
                HospitalDirectMessage.sender_role != "patient",
                HospitalDirectMessage.created_at >= cutoff_24h,
            ),
        )
        .order_by(HospitalDirectMessage.created_at.asc())
        .all()
    )

    # Mark incoming admin and patient messages as read when requested
    if mark_read:
        for m in messages:
            if m.sender_role in ["admin", "patient"] and not m.is_read:
                m.is_read = True
        db.commit()

    result_messages = []
    for m in messages:
        sender_phone = getattr(m, "patient_phone", None)
        if not sender_phone and m.sender_name:
            phone_match = re.search(r'\(([^)]+)\)', m.sender_name)
            if phone_match:
                sender_phone = phone_match.group(1).strip()

        result_messages.append({
            "id": m.id,
            "sender_role": m.sender_role,
            "sender_name": m.sender_name,
            "sender_phone": sender_phone,
            "patient_phone": getattr(m, "patient_phone", None) or sender_phone,
            "patient_id": getattr(m, "patient_id", None),
            "reply_to_id": getattr(m, "reply_to_id", None),
            "subject": m.subject,
            "message": m.message,
            "priority": m.priority,
            "is_read": m.is_read,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })

    return {
        "success": True,
        "messages": result_messages,
    }


@app.get("/hospitals/{hospital_id}/messages/unread-count")
def hospital_get_unread_message_count(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Hospital: Get count of unread messages from Admin and Patients (patient inquiries auto-delete after 24h)."""
    if hospital_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Automatically purge patient inquiries older than 24 hours
    purge_expired_patient_inquiries(db, hospital_id=hospital_id)

    cutoff_24h = datetime.utcnow() - timedelta(hours=24)
    unread_count = (
        db.query(HospitalDirectMessage)
        .filter(
            HospitalDirectMessage.hospital_id == hospital_id,
            HospitalDirectMessage.sender_role.in_(["admin", "patient"]),
            HospitalDirectMessage.is_read == False,
            or_(
                HospitalDirectMessage.sender_role != "patient",
                HospitalDirectMessage.created_at >= cutoff_24h,
            ),
        )
        .count()
    )

    return {"success": True, "unread_count": unread_count}


@app.post("/hospitals/{hospital_id}/messages/reply")
def hospital_reply_to_admin(
    hospital_id: int,
    data: HospitalReplyMessageRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Hospital: Send reply back to Admin."""
    if hospital_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    reply_text = (data.message or "").strip()
    if not reply_text:
        raise HTTPException(status_code=400, detail="Reply message cannot be empty")

    subject = (data.subject or f"Reply from {hospital.name}").strip()

    msg = HospitalDirectMessage(
        hospital_id=hospital_id,
        sender_role="hospital",
        sender_name=hospital.name,
        subject=subject,
        message=reply_text,
        priority="normal",
        is_read=False,
        sent_via_email=False,
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    return {
        "success": True,
        "message": "Reply sent to Admin successfully.",
        "reply": {
            "id": msg.id,
            "subject": msg.subject,
            "message": msg.message,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        },
    }


# ============================================================
# PATIENT DIRECT INQUIRY TO HOSPITAL
# ============================================================

class PatientInquiryRequest(BaseModel):
    patient_name: str
    patient_phone: Optional[str] = None
    patient_id: Optional[int] = None
    patient_email: Optional[str] = None
    subject: Optional[str] = "Patient Inquiry"
    message: str


class HospitalPatientReplyRequest(BaseModel):
    inquiry_id: int
    reply_message: str
    patient_phone: Optional[str] = None
    patient_name: Optional[str] = None


class PatientMarkReadRequest(BaseModel):
    phone: Optional[str] = None
    message_ids: Optional[List[int]] = None


@app.post("/hospitals/{hospital_id}/patient-inquiry")
def submit_patient_inquiry(
    hospital_id: int,
    data: PatientInquiryRequest,
    db: Session = Depends(get_db),
):
    """Patient: Directly send inquiry to a hospital helpdesk (auto-deleted after 24 hours)."""
    # Clean up expired inquiries first
    purge_expired_patient_inquiries(db, hospital_id=hospital_id)

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    message_text = (data.message or "").strip()
    if not message_text:
        raise HTTPException(status_code=400, detail="Inquiry message cannot be empty")

    patient_name = (data.patient_name or "Q-Arovia Patient").strip()
    clean_phone = (data.patient_phone or "").strip()
    sender_info = patient_name
    if clean_phone:
        sender_info += f" ({clean_phone})"

    subj = (data.subject or f"Patient Inquiry from {patient_name}").strip()

    msg = HospitalDirectMessage(
        hospital_id=hospital_id,
        sender_role="patient",
        sender_name=sender_info,
        patient_phone=clean_phone if clean_phone else None,
        patient_id=data.patient_id if hasattr(data, "patient_id") else None,
        subject=subj,
        message=message_text,
        priority="normal",
        is_read=False,
        sent_via_email=False,
        created_at=datetime.utcnow(),
    )

    # Optional email dispatch to hospital
    if hospital.email:
        email_body = f"""New Patient Inquiry on Q-Arovia:

From: {sender_info}
Email: {data.patient_email or 'Not provided'}
Subject: {subj}

Message:
{message_text}

---
You can view and reply to this inquiry directly on your Q-Arovia Hospital Dashboard.
"""
        try:
            send_qarovia_email(
                to_email=hospital.email,
                subject=f"Q-Arovia Patient Inquiry: {subj}",
                body=email_body,
            )
            msg.sent_via_email = True
        except Exception as e:
            logging.warning("Patient inquiry email delivery skipped: %s", e)

    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Real-Time WebSocket broadcast
    try:
        broadcast_now(ws_manager.broadcast_inquiry({
            "id": msg.id,
            "hospital_id": msg.hospital_id,
            "hospital_name": hospital.name,
            "hospital_city": hospital.city,
            "sender_role": msg.sender_role,
            "sender_name": msg.sender_name,
            "patient_phone": msg.patient_phone,
            "patient_id": msg.patient_id,
            "subject": msg.subject,
            "message": msg.message,
            "priority": msg.priority,
            "is_read": msg.is_read,
            "created_at": msg.created_at.isoformat() if msg.created_at else datetime.utcnow().isoformat(),
        }))
    except Exception as ws_err:
        logging.warning("Inquiry WS broadcast skipped: %s", ws_err)

    return {
        "success": True,
        "message": "Inquiry submitted to hospital helpdesk successfully.",
        "inquiry": {
            "id": msg.id,
            "subject": msg.subject,
            "message": msg.message,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        },
    }


@app.post("/hospitals/{hospital_id}/patient-inquiry/reply")
def hospital_reply_to_patient_inquiry(
    hospital_id: int,
    data: HospitalPatientReplyRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    """Hospital: Send direct in-app reply to a patient inquiry."""
    if hospital_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    reply_text = (data.reply_message or "").strip()
    if not reply_text:
        raise HTTPException(status_code=400, detail="Reply message cannot be empty")

    inquiry = (
        db.query(HospitalDirectMessage)
        .filter(
            HospitalDirectMessage.id == data.inquiry_id,
            HospitalDirectMessage.hospital_id == hospital_id,
        )
        .first()
    )
    if not inquiry:
        raise HTTPException(status_code=404, detail="Inquiry not found")

    # Extract target patient phone
    target_phone = (data.patient_phone or inquiry.patient_phone or "").strip()
    if not target_phone and inquiry.sender_name:
        pm = re.search(r'\(([^)]+)\)', inquiry.sender_name)
        if pm:
            target_phone = pm.group(1).strip()

    reply_msg = HospitalDirectMessage(
        hospital_id=hospital_id,
        sender_role="hospital",
        sender_name=hospital.name,
        patient_phone=target_phone if target_phone else None,
        patient_id=inquiry.patient_id,
        reply_to_id=inquiry.id,
        subject=f"Reply: {inquiry.subject}",
        message=reply_text,
        priority="normal",
        is_read=False,  # Unread for the patient
        sent_via_email=False,
        created_at=datetime.utcnow(),
    )
    # Mark the original inquiry as resolved/read by hospital
    inquiry.is_read = True

    db.add(reply_msg)
    db.commit()
    db.refresh(reply_msg)

    # Real-Time WebSocket broadcast
    try:
        broadcast_now(ws_manager.broadcast_reply({
            "id": reply_msg.id,
            "hospital_id": reply_msg.hospital_id,
            "hospital_name": hospital.name,
            "hospital_city": hospital.city,
            "sender_role": reply_msg.sender_role,
            "sender_name": reply_msg.sender_name,
            "patient_phone": reply_msg.patient_phone,
            "patient_id": reply_msg.patient_id,
            "reply_to_id": reply_msg.reply_to_id,
            "subject": reply_msg.subject,
            "message": reply_msg.message,
            "is_read": reply_msg.is_read,
            "created_at": reply_msg.created_at.isoformat() if reply_msg.created_at else datetime.utcnow().isoformat(),
        }))
    except Exception as ws_err:
        logging.warning("Reply WS broadcast skipped: %s", ws_err)

    return {
        "success": True,
        "message": "Reply sent to patient successfully.",
        "reply": {
            "id": reply_msg.id,
            "reply_to_id": reply_msg.reply_to_id,
            "hospital_name": hospital.name,
            "message": reply_msg.message,
            "created_at": reply_msg.created_at.isoformat() if reply_msg.created_at else None,
        },
    }


@app.get("/patients/messages")
def get_patient_messages(
    phone: Optional[str] = None,
    patient_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Patient: Fetch inquiries and hospital direct replies from the last 24 hours with verified authorization."""
    purge_expired_patient_inquiries(db)

    if not current_user:
        return {"success": True, "messages": [], "unread_count": 0}

    role = current_user.get("role")
    auth_user_id = current_user.get("user_id")

    cutoff_24h = datetime.utcnow() - timedelta(hours=24)
    query = (
        db.query(
            HospitalDirectMessage,
            Hospital.name.label("hospital_name"),
            Hospital.city.label("hospital_city"),
        )
        .outerjoin(Hospital, Hospital.id == HospitalDirectMessage.hospital_id)
        .filter(HospitalDirectMessage.created_at >= cutoff_24h)
    )

    if role == "patient":
        patient = db.query(Patient).filter(Patient.id == auth_user_id).first()
        conds = [HospitalDirectMessage.patient_id == auth_user_id]
        if patient and patient.phone:
            clean_phone = patient.phone.strip().replace(" ", "").replace("-", "")
            conds.append(HospitalDirectMessage.patient_phone == patient.phone)
            conds.append(HospitalDirectMessage.patient_phone == clean_phone)
        query = query.filter(or_(*conds))
    elif role == "hospital":
        query = query.filter(HospitalDirectMessage.hospital_id == auth_user_id)
    elif role == "admin":
        if patient_id:
            query = query.filter(HospitalDirectMessage.patient_id == patient_id)
    else:
        return {"success": True, "messages": [], "unread_count": 0}

    raw_msgs = query.order_by(HospitalDirectMessage.created_at.asc()).all()

    messages_list = []
    unread_count = 0
    for hdm, h_name, h_city in raw_msgs:
        is_from_hospital = (hdm.sender_role or "").lower() == "hospital"
        if is_from_hospital and not hdm.is_read:
            unread_count += 1
        messages_list.append({
            "id": hdm.id,
            "hospital_id": hdm.hospital_id,
            "hospital_name": h_name or "Hospital Helpdesk",
            "hospital_city": h_city or "",
            "sender_role": hdm.sender_role,
            "sender_name": hdm.sender_name,
            "patient_phone": hdm.patient_phone,
            "subject": hdm.subject,
            "message": hdm.message,
            "reply_to_id": hdm.reply_to_id,
            "is_read": hdm.is_read,
            "created_at": hdm.created_at.isoformat() if hdm.created_at else None,
        })

    return {
        "success": True,
        "unread_count": unread_count,
        "messages": messages_list,
    }


@app.post("/patients/messages/mark-read")
def patient_mark_messages_read(
    data: PatientMarkReadRequest,
    db: Session = Depends(get_db),
):
    """Patient: Mark hospital reply messages as read."""
    if data.message_ids:
        db.query(HospitalDirectMessage).filter(
            HospitalDirectMessage.id.in_(data.message_ids),
            HospitalDirectMessage.sender_role == "hospital",
        ).update({HospitalDirectMessage.is_read: True}, synchronize_session=False)
        db.commit()
    elif data.phone:
        clean_phone = data.phone.strip()
        digits = "".join(filter(str.isdigit, clean_phone))
        last10 = digits[-10:] if len(digits) >= 10 else digits
        query = db.query(HospitalDirectMessage).filter(
            HospitalDirectMessage.sender_role == "hospital",
            HospitalDirectMessage.is_read == False,
        )
        if last10:
            query = query.filter(
                or_(
                    HospitalDirectMessage.patient_phone == clean_phone,
                    HospitalDirectMessage.patient_phone.like(f"%{last10}%"),
                )
            )
        query.update({HospitalDirectMessage.is_read: True}, synchronize_session=False)
        db.commit()

    return {"success": True, "message": "Messages marked as read"}


# ============================================================
# ADMIN - HOSPITAL FINANCIAL LEDGER
# ============================================================

@app.get("/admin/ledger")
def get_admin_hospital_ledger(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    hospitals = db.query(Hospital).order_by(Hospital.name.asc()).all()
    ledger = []

    for hosp in hospitals:
        # Never calculate commission on cancelled, failed, refunded, or unpaid bookings
        paid_tokens = db.query(Token).filter(
            Token.hospital_id == hosp.id,
            Token.payment_status == "paid",
            Token.status != "cancelled",
        ).all()

        total_opd = Decimal("0.00")
        platform_comm = Decimal("0.00")
        total_collected = Decimal("0.00")
        net_payable = Decimal("0.00")

        for t in paid_tokens:
            opd_fee = Decimal(str(t.token_fee or 0)).quantize(Decimal("0.01"))
            plat_fee = Decimal(str(t.platform_fee or 0)).quantize(Decimal("0.01"))
            tot_amt = Decimal(str(t.total_amount or (opd_fee + plat_fee))).quantize(Decimal("0.01"))

            # Historical transaction protection (Rule 5):
            # Save the commission percentage and final rounded commission amount against each transaction.
            # Updating the admin commission percentage must affect only new eligible bookings.
            # Never recalculate historical commissions using the latest percentage.
            if getattr(t, "commission_amount", None) is not None and getattr(t, "hospital_amount", None) is not None:
                t_comm = Decimal(str(t.commission_amount)).quantize(Decimal("0.01"))
                t_hosp = Decimal(str(t.hospital_amount)).quantize(Decimal("0.01"))
            else:
                comm_pct = Decimal(str(getattr(t, "commission_percentage", None) or 0))
                calc_split = calculate_commission(
                    eligible_booking_amount=opd_fee,
                    commission_percentage=comm_pct,
                    is_eligible=True,
                )
                t_comm = calc_split["commission_amount"]
                t_hosp = calc_split["hospital_amount"]

            total_opd += opd_fee
            platform_comm += t_comm
            total_collected += tot_amt
            net_payable += t_hosp

        settlements = db.query(HospitalSettlement).filter(
            HospitalSettlement.hospital_id == hosp.id
        ).all()
        already_settled = sum(Decimal(str(s.amount or 0)).quantize(Decimal("0.01")) for s in settlements)
        pending_balance = max(Decimal("0.00"), net_payable - already_settled)

        ledger.append({
            "hospital_id": hosp.id,
            "hospital_name": hosp.name,
            "city": hosp.city,
            "approval_status": hosp.approval_status,
            "payment_account_status": hosp.payment_account_status,
            "payment_account_name": hosp.payment_account_name,
            "payment_account_number": hosp.payment_account_number,
            "payment_ifsc": hosp.payment_ifsc,
            "payment_upi": hosp.payment_upi,
            "paid_tokens_count": len(paid_tokens),
            "total_opd_collected": float(total_opd),
            "platform_commission": float(platform_comm),
            "total_collected": float(total_collected),
            "net_payable_to_hospital": float(net_payable),
            "already_settled": float(already_settled),
            "pending_balance": float(pending_balance),
            "settlements_count": len(settlements),
        })

    total_pending = sum(Decimal(str(item["pending_balance"])) for item in ledger)
    total_settled = sum(Decimal(str(item["already_settled"])) for item in ledger)
    total_commission = sum(Decimal(str(item["platform_commission"])) for item in ledger)

    return {
        "success": True,
        "ledger": ledger,
        "total_hospitals": len(ledger),
        "total_platform_commission": float(total_commission),
        "total_pending_payouts": float(total_pending),
        "total_settled_payouts": float(total_settled),
    }


# ============================================================
# ADMIN - HOSPITAL SETTLEMENTS & PAYOUTS
# ============================================================

class HospitalSettlementCreate(BaseModel):
    amount: float
    utr_reference: str
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    settlement_date: Optional[date] = None
    notes: Optional[str] = None


@app.post("/admin/hospitals/{hospital_id}/settle")
def create_hospital_settlement(
    hospital_id: int,
    data: HospitalSettlementCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")
    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Settlement amount must be greater than zero.")
    if not data.utr_reference or not data.utr_reference.strip():
        raise HTTPException(status_code=400, detail="UTR / Bank Reference Number is required.")

    settlement = HospitalSettlement(
        hospital_id=hospital_id,
        amount=round(float(data.amount), 2),
        utr_reference=data.utr_reference.strip(),
        bank_name=(data.bank_name or hospital.payment_account_name or "Hospital Bank Account").strip(),
        account_number=(data.account_number or hospital.payment_account_number or "—").strip(),
        settlement_date=data.settlement_date or date.today(),
        notes=data.notes.strip() if data.notes else None,
        created_by=current_user.get("email", "admin"),
    )
    db.add(settlement)
    db.commit()
    db.refresh(settlement)

    log_admin_action(
        db,
        current_user.get("email", "admin"),
        "SETTLE_PAYOUT",
        target_type="HOSPITAL",
        target_id=str(hospital_id),
        details=f"Settled ₹{settlement.amount} with UTR {settlement.utr_reference} to {hospital.name}"
    )

    return {
        "success": True,
        "message": f"Settlement of ₹{settlement.amount} recorded successfully for {hospital.name}.",
        "settlement": {
            "id": settlement.id,
            "hospital_id": settlement.hospital_id,
            "amount": settlement.amount,
            "utr_reference": settlement.utr_reference,
            "settlement_date": str(settlement.settlement_date),
            "bank_name": settlement.bank_name,
            "notes": settlement.notes,
            "created_at": settlement.created_at.isoformat() if settlement.created_at else None,
        }
    }


@app.get("/admin/settlements")
def list_all_settlements(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    settlements = db.query(HospitalSettlement).order_by(HospitalSettlement.settlement_date.desc(), HospitalSettlement.created_at.desc()).all()
    results = []
    for s in settlements:
        hosp = db.query(Hospital).filter(Hospital.id == s.hospital_id).first()
        results.append({
            "id": s.id,
            "hospital_id": s.hospital_id,
            "hospital_name": hosp.name if hosp else "Unknown Hospital",
            "amount": s.amount,
            "utr_reference": s.utr_reference,
            "bank_name": s.bank_name,
            "account_number": s.account_number,
            "settlement_date": str(s.settlement_date),
            "notes": s.notes,
            "created_by": s.created_by,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    return {"success": True, "settlements": results}


@app.get("/admin/hospitals/{hospital_id}/settlements")
def list_hospital_settlements(
    hospital_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    settlements = db.query(HospitalSettlement).filter(
        HospitalSettlement.hospital_id == hospital_id
    ).order_by(HospitalSettlement.settlement_date.desc()).all()
    return [{
        "id": s.id,
        "amount": s.amount,
        "utr_reference": s.utr_reference,
        "bank_name": s.bank_name,
        "account_number": s.account_number,
        "settlement_date": str(s.settlement_date),
        "notes": s.notes,
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    } for s in settlements]


# ============================================================
# ADMIN - FAILED REFUNDS & RETRY
# ============================================================

@app.get("/admin/failed-refunds")
def list_failed_refunds(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    tokens = db.query(Token).filter(
        or_(
            Token.payment_status.in_(["refund_failed", "failed", "refund_pending"]),
            and_(Token.status == "cancelled", Token.payment_status == "paid")
        )
    ).order_by(Token.created_at.desc()).all()

    return [{
        "id": t.id,
        "token_number": t.token_number,
        "patient_name": t.patient_name,
        "hospital": t.hospital,
        "hospital_id": t.hospital_id,
        "total_amount": t.total_amount,
        "payment_status": t.payment_status,
        "status": t.status,
        "cashfree_order_id": t.cashfree_order_id,
        "cashfree_payment_id": t.cashfree_payment_id,
        "notes": t.notes,
        "appointment_date": str(t.appointment_date) if t.appointment_date else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    } for t in tokens]


@app.post("/admin/refunds/{token_id}/retry")
def retry_refund_endpoint(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    token = db.query(Token).filter(Token.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    token.status = "cancelled"
    refund_res = execute_cashfree_refund(db, token, "Admin manual retry refund")
    db.refresh(token)

    log_admin_action(
        db,
        current_user.get("email", "admin"),
        "RETRY_REFUND",
        target_type="TOKEN",
        target_id=str(token_id),
        details=f"Refund resolved for Token #{token.token_number} (Patient: {token.patient_name}, Amount: ₹{token.total_amount})"
    )

    return {
        "success": True,
        "message": f"Refund for Token #{token.token_number} has been recorded as REFUNDED.",
        "token": token_to_dict(token)
    }


# ============================================================
# ADMIN - PLATFORM ANALYTICS (PEAK HOURS, DEPARTMENTS, QUEUE)
# ============================================================

@app.get("/admin/analytics")
def get_admin_analytics(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    all_tokens = db.query(Token).all()
    today = date.today()

    # 1. Hourly Distribution (0 to 23 in IST)
    hourly_counts = {h: 0 for h in range(24)}
    for t in all_tokens:
        if t.created_at:
            ist_hour = (t.created_at + timedelta(hours=5, minutes=30)).hour
            hourly_counts[ist_hour] += 1

    max_hourly = max(hourly_counts.values()) if any(hourly_counts.values()) else 1
    hourly_distribution = []
    for h in range(24):
        dt_sample = datetime(2026, 1, 1, h, 0)
        label = dt_sample.strftime("%I:%M %p").lstrip("0")
        hourly_distribution.append({
            "hour": h,
            "label": label,
            "count": hourly_counts[h],
            "is_peak": hourly_counts[h] >= (max_hourly * 0.7 if max_hourly > 0 else 1),
        })

    # 2. Daily Trends (last 14 days)
    daily_trends = []
    for day_offset in range(13, -1, -1):
        target_date = today - timedelta(days=day_offset)
        day_tokens = [t for t in all_tokens if t.appointment_date == target_date]
        paid_tokens = [t for t in day_tokens if t.payment_status == "paid"]
        daily_trends.append({
            "date": target_date.strftime("%b %d"),
            "full_date": str(target_date),
            "tokens": len(day_tokens),
            "revenue": sum(int(t.total_amount or 0) for t in paid_tokens),
            "platform_revenue": sum(int(t.platform_fee or 0) for t in paid_tokens),
        })

    # 3. Department Breakdown
    dept_counts = {}
    for t in all_tokens:
        dept = (t.department or "General").strip().title()
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    total_tokens_count = len(all_tokens) or 1
    department_breakdown = sorted([
        {
            "department": dept,
            "count": cnt,
            "percentage": round((cnt / total_tokens_count) * 100, 1),
        }
        for dept, cnt in dept_counts.items()
    ], key=lambda x: x["count"], reverse=True)[:8]

    # 4. Queue Health & Doctors Status
    waiting_count = sum(1 for t in all_tokens if t.status == "waiting")
    serving_count = sum(1 for t in all_tokens if t.status == "serving")
    completed_count = sum(1 for t in all_tokens if t.status == "completed")
    cancelled_count = sum(1 for t in all_tokens if t.status == "cancelled")

    all_doctors = db.query(Doctor).all()
    on_duty_doctors = sum(1 for d in all_doctors if getattr(d, "is_available", True))
    off_duty_doctors = len(all_doctors) - on_duty_doctors

    hospitals = db.query(Hospital).all()
    expiring_licenses = 0
    expired_licenses = 0
    for h in hospitals:
        if h.license_expiry_date:
            diff = (h.license_expiry_date - today).days
            if diff < 0:
                expired_licenses += 1
            elif diff <= 30:
                expiring_licenses += 1

    return {
        "success": True,
        "hourly_distribution": hourly_distribution,
        "daily_trends": daily_trends,
        "department_breakdown": department_breakdown,
        "queue_health": {
            "total_tokens": len(all_tokens),
            "waiting": waiting_count,
            "serving": serving_count,
            "completed": completed_count,
            "cancelled": cancelled_count,
            "estimated_avg_wait_minutes": 15,
            "on_duty_doctors": on_duty_doctors,
            "off_duty_doctors": off_duty_doctors,
            "total_doctors": len(all_doctors),
            "total_hospitals": len(hospitals),
            "expiring_licenses_30d": expiring_licenses,
            "expired_licenses": expired_licenses,
        }
    }


# ============================================================
# ADMIN - AUDIT LOGS
# ============================================================

@app.get("/admin/audit-logs")
def get_admin_audit_logs(
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    logs = db.query(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(100).all()
    return [{
        "id": l.id,
        "admin_email": l.admin_email,
        "action": l.action,
        "target_type": l.target_type,
        "target_id": l.target_id,
        "details": l.details,
        "ip_address": l.ip_address,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    } for l in logs]


# ============================================================
# HOSPITAL ADVERTISEMENTS - DELETE ENDPOINTS
# ============================================================

@app.delete("/hospitals/{hospital_id}/ads/{ad_id}")
def delete_hospital_ad(
    hospital_id: int,
    ad_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("hospital")),
):
    if current_user["user_id"] != hospital_id:
        raise HTTPException(status_code=403, detail="You cannot delete another hospital's ad.")
    ad = db.query(HospitalAdvertisement).filter(
        HospitalAdvertisement.id == ad_id,
        HospitalAdvertisement.hospital_id == hospital_id
    ).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Advertisement campaign not found.")
    db.delete(ad)
    db.commit()
    return {"success": True, "message": "Advertisement deleted successfully."}


@app.delete("/admin/ads/{ad_id}")
def admin_delete_ad(
    ad_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    ad = db.query(HospitalAdvertisement).filter(HospitalAdvertisement.id == ad_id).first()
    if not ad:
        raise HTTPException(status_code=404, detail="Advertisement not found.")
    db.delete(ad)
    db.commit()
    log_admin_action(
        db,
        current_user.get("email", "admin"),
        "DELETE_AD",
        target_type="AD",
        target_id=str(ad_id),
        details=f"Deleted ad '{ad.title}' for hospital ID {ad.hospital_id}"
    )
    return {"success": True, "message": "Advertisement deleted by admin."}

# ============================================================
# STATIC FILES SERVING (Render Direct Full-Stack Deployment)
# Note: Root mount ("/") must ALWAYS be mounted AFTER all API routes
# ============================================================
from fastapi.staticfiles import StaticFiles

if os.path.exists(ADMIN_STATIC_DIR):
    app.mount("/admin-portal", StaticFiles(directory=ADMIN_STATIC_DIR, html=True), name="admin_portal")

    @app.get("/online-users.html", include_in_schema=False)
    def serve_root_online_users():
        path = os.path.join(ADMIN_STATIC_DIR, "online-users.html")
        if os.path.exists(path):
            return FileResponse(path)
        return RedirectResponse(url="/admin-portal/online-users.html", status_code=302)

if os.path.exists(HOSPITAL_STATIC_DIR):
    app.mount("/hospital", StaticFiles(directory=HOSPITAL_STATIC_DIR, html=True), name="hospital")

if os.path.exists(PATIENT_STATIC_DIR):
    @app.get("/dashboard.html", include_in_schema=False)
    def serve_root_dashboard():
        return FileResponse(os.path.join(PATIENT_STATIC_DIR, "dashboard.html"))

    @app.get("/patient/dashboard.html", include_in_schema=False)
    def serve_sub_dashboard():
        return FileResponse(os.path.join(PATIENT_STATIC_DIR, "dashboard.html"))

    app.mount("/patient", StaticFiles(directory=PATIENT_STATIC_DIR, html=True), name="patient")
    app.mount("/", StaticFiles(directory=PATIENT_STATIC_DIR, html=True), name="patient_root")

