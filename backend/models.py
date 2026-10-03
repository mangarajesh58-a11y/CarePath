
from datetime import datetime
from datetime import datetime, date

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    Date,
    DateTime,
)

from database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    phone = Column(String(50), nullable=True, unique=True)
    password = Column(String(255), nullable=False)
    google_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Hospital(Base):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, index=True)

    # Basic information
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    phone = Column(String(50), nullable=True)
    city = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)

    # Registration and license
    registration_number = Column(String(255), nullable=True)
    issuing_authority = Column(String(255), nullable=True)
    license_expiry_date = Column(Date, nullable=True)
    license_certificate = Column(String(500), nullable=True)
    certificate_original_name = Column(String(500), nullable=True)
    certificate_content_type = Column(String(100), nullable=True)
    certificate_uploaded_at = Column(DateTime, nullable=True)
    certificate_verification_status = Column(
        String(30), default="PENDING", nullable=False
    )
    license_id = Column(String(255), nullable=True)

    # Login
    password = Column(String(255), nullable=False)
    google_id = Column(String(255), nullable=True)

    # Location
    latitude = Column(String(50), nullable=True)
    longitude = Column(String(50), nullable=True)

    # Token fee (Indian rupees)
    token_fee = Column(Integer, default=0, nullable=False)
    appointment_date = Column(Date, nullable=False, index=True)

    # Approval and publishing
    approval_status = Column(
        String(30), default="PENDING", nullable=False
    )
    rejection_reason = Column(Text, nullable=True)
    is_published = Column(Boolean, default=False, nullable=False)

    # Hospital payment account
    payment_account_name = Column(String(255), nullable=True)
    payment_account_number = Column(String(100), nullable=True)
    payment_ifsc = Column(String(30), nullable=True)
    payment_upi = Column(String(100), nullable=True)
    payment_account_status = Column(
        String(30), default="NOT_ADDED", nullable=True
    )

    # Razorpay linked account
    razorpay_account_id = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    hospital_id = Column(Integer, nullable=False, index=True)

    name = Column(String(255), nullable=False)
    department = Column(String(255), nullable=False)
    specialization = Column(String(255), nullable=True)
    experience = Column(String(100), nullable=True)

    # Doctor availability
    available_days = Column(String(255), nullable=True)
    start_time = Column(String(10), nullable=True)
    end_time = Column(String(10), nullable=True)
    is_available = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class Token(Base):
    __tablename__ = "tokens"

    id = Column(Integer, primary_key=True, index=True)
    patient_name = Column(String(255), nullable=False)
    hospital = Column(String(255), nullable=False, index=True)
    hospital_id = Column(Integer, nullable=True, index=True)
    department = Column(String(255), nullable=False)
    doctor = Column(String(255), nullable=False)
    token_number = Column(Integer, nullable=False)

    # Platform
    platform = Column(String(100), default="CarePath")

    # Payment amounts in rupees
    token_fee = Column(Integer, default=0, nullable=False)
    platform_fee = Column(Integer, default=10, nullable=False)
    total_amount = Column(Integer, default=10, nullable=False)
    payment_status = Column(String(50), default="pending")

    # Razorpay
    razorpay_order_id = Column(String(255), nullable=True)
    razorpay_payment_id = Column(String(255), nullable=True)
    razorpay_signature = Column(String(500), nullable=True)

    # Token status
    status = Column(String(50), default="waiting")
    created_at = Column(DateTime, default=datetime.utcnow)


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True)
    password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class RegistrationOTP(Base):
    __tablename__ = "registration_otps"

    id = Column(Integer, primary_key=True, index=True)

    # patient or hospital
    role = Column(String(20), nullable=False)

    # email or phone
    contact_method = Column(String(10), nullable=False)
    contact_value = Column(String(255), nullable=False, index=True)

    # Store a hash of the OTP, never the plain OTP
    otp_hash = Column(String(255), nullable=False)

    # Expiration and verification tracking
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    verified = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)