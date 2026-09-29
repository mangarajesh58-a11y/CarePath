from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    Date,
    DateTime,
)

from datetime import datetime
from database import Base
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import Boolean
from sqlalchemy import Date
from sqlalchemy import DateTime

from datetime import datetime

from database import Base


# =========================================================
# PATIENT MODEL
# =========================================================

class Patient(Base):

    __tablename__ = "patients"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    full_name = Column(
        String(255),
        nullable=False
    )

    email = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True
    )

    phone = Column(
        String(50),
        nullable=True,
        unique=True
    )

    password = Column(
        String(255),
        nullable=False
    )

    google_id = Column(
        String(255),
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


# =========================================================
# HOSPITAL MODEL
# =========================================================

class Hospital(Base):

    __tablename__ = "hospitals"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    # =====================================================
    # BASIC INFORMATION
    # =====================================================

    name = Column(
        String(255),
        nullable=False
    )

    email = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True
    )

    phone = Column(
        String(50),
        nullable=True
    )

    city = Column(
        String(255),
        nullable=True
    )

    address = Column(
        Text,
        nullable=True
    )

    description = Column(
        Text,
        nullable=True
    )

    image_url = Column(
        String(500),
        nullable=True
    )

    # =====================================================
    # HOSPITAL REGISTRATION / LICENSE
    # =====================================================

    registration_number = Column(
        String(255),
        nullable=True
    )

    issuing_authority = Column(
        String(255),
        nullable=True
    )

    license_expiry_date = Column(
        Date,
        nullable=True
    )

    license_certificate = Column(
        String(500),
        nullable=True
    )

    certificate_original_name = Column(
        String(500),
        nullable=True
    )

    certificate_content_type = Column(
        String(100),
        nullable=True
    )

    certificate_uploaded_at = Column(
        DateTime,
        nullable=True
    )

    # PENDING / VERIFIED / REJECTED

    certificate_verification_status = Column(
        String(30),
        default="PENDING",
        nullable=False
    )

    # Old field kept for compatibility
    license_id = Column(
        String(255),
        nullable=True
    )

    # =====================================================
    # LOGIN
    # =====================================================

    password = Column(
        String(255),
        nullable=False
    )

    google_id = Column(
        String(255),
        nullable=True
    )

    # =====================================================
    # LOCATION
    # =====================================================

    latitude = Column(
        String(50),
        nullable=True
    )

    longitude = Column(
        String(50),
        nullable=True
    )

    # =====================================================
    # TOKEN FEE
    # =====================================================

    token_fee = Column(
        Integer,
        default=0,
        nullable=False
    )

    # =====================================================
    # HOSPITAL APPROVAL
    # =====================================================

    approval_status = Column(
        String(30),
        default="PENDING",
        nullable=False
    )

    rejection_reason = Column(
        Text,
        nullable=True
    )

    is_published = Column(
        Boolean,
        default=False,
        nullable=False
    )

    # =====================================================
    # PAYMENT ACCOUNT
    # =====================================================

    payment_account_name = Column(
        String(255),
        nullable=True
    )

    payment_account_number = Column(
        String(100),
        nullable=True
    )

    payment_ifsc = Column(
        String(30),
        nullable=True
    )

    payment_upi = Column(
        String(100),
        nullable=True
    )

    payment_account_status = Column(
        String(30),
        default="NOT_ADDED",
        nullable=True
    )

    # =====================================================
    # RAZORPAY LINKED ACCOUNT
    # =====================================================

    razorpay_account_id = Column(
        String(255),
        nullable=True
    )

    # =====================================================
    # CREATED DATE
    # =====================================================

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


# =========================================================
# DOCTOR MODEL
# =========================================================

class Doctor(Base):

    __tablename__ = "doctors"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    hospital_id = Column(
        Integer,
        nullable=False,
        index=True
    )

    name = Column(
        String(255),
        nullable=False
    )

    department = Column(
        String(255),
        nullable=False
    )

    specialization = Column(
        String(255),
        nullable=True
    )

    experience = Column(
        String(100),
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


# =========================================================
# TOKEN MODEL
# =========================================================

class Token(Base):

    __tablename__ = "tokens"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    patient_name = Column(
        String(255),
        nullable=False
    )

    hospital = Column(
        String(255),
        nullable=False,
        index=True
    )

    hospital_id = Column(
        Integer,
        nullable=True,
        index=True
    )

    department = Column(
        String(255),
        nullable=False
    )

    doctor = Column(
        String(255),
        nullable=False
    )

    token_number = Column(
        Integer,
        nullable=False
    )

    # =====================================================
    # PLATFORM
    # =====================================================

    platform = Column(
        String(100),
        default="HospitalCare"
    )

    # =====================================================
    # PAYMENT
    # =====================================================

    token_fee = Column(
        Integer,
        default=0,
        nullable=False
    )

    platform_fee = Column(
        Integer,
        default=10,
        nullable=False
    )

    total_amount = Column(
        Integer,
        default=10,
        nullable=False
    )

    payment_status = Column(
        String(50),
        default="pending"
    )

    # =====================================================
    # RAZORPAY
    # =====================================================

    razorpay_order_id = Column(
        String(255),
        nullable=True
    )

    razorpay_payment_id = Column(
        String(255),
        nullable=True
    )

    razorpay_signature = Column(
        String(500),
        nullable=True
    )

    # =====================================================
    # TOKEN STATUS
    # =====================================================

    status = Column(
        String(50),
        default="waiting"
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


# =========================================================
# ADMIN MODEL
# =========================================================

class Admin(Base):

    __tablename__ = "admins"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    email = Column(
        String(255),
        nullable=False,
        unique=True
    )

    password = Column(
        String(255),
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )