import os

from dotenv import load_dotenv

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    text
)

from sqlalchemy.orm import Session

from pydantic import BaseModel

from passlib.context import CryptContext

from google.oauth2 import id_token
from google.auth.transport import requests

from database import Base, engine, SessionLocal


# =========================================================
# LOAD ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# CONFIGURATION
# =========================================================

GOOGLE_CLIENT_ID = os.getenv(
    "GOOGLE_CLIENT_ID",
    "124194505435-5rpj0kjdj3fgkle4vhp18gg89qs4he3l.apps.googleusercontent.com"
)

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")


# =========================================================
# PASSWORD HASHING
# =========================================================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


# =========================================================
# RAZORPAY
# =========================================================

razorpay_client = None

try:

    import razorpay

    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:

        razorpay_client = razorpay.Client(
            auth=(
                RAZORPAY_KEY_ID,
                RAZORPAY_KEY_SECRET
            )
        )

except ImportError:

    razorpay_client = None


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI(
    title="HospitalCare API",
    version="4.0.0"
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


# =========================================================
# DATABASE MODELS
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
        unique=True
    )

    phone = Column(
        String(50),
        nullable=False,
        unique=True
    )

    password = Column(
        String(255),
        nullable=False
    )


class Hospital(Base):

    __tablename__ = "hospitals"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    name = Column(
        String(255),
        nullable=False
    )

    email = Column(
        String(255),
        nullable=True
    )

    phone = Column(
        String(50),
        nullable=True
    )

    city = Column(
        String(255),
        nullable=False
    )

    address = Column(
        String(500),
        nullable=True
    )

    description = Column(
        Text,
        nullable=True
    )

    password_hash = Column(
        String(255),
        nullable=True
    )

    license_id = Column(
        String(255),
        nullable=True,
        unique=True
    )

    approval_status = Column(
        String(50),
        default="PENDING",
        nullable=False
    )

    is_published = Column(
        Boolean,
        default=False,
        nullable=False
    )


class Doctor(Base):

    __tablename__ = "doctors"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    hospital_id = Column(
        Integer,
        nullable=False
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


class Token(Base):

    __tablename__ = "tokens"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    patient_name = Column(
        String(100),
        nullable=False
    )

    hospital = Column(
        String(255),
        nullable=False
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

    platform_fee = Column(
        Integer,
        default=10
    )

    payment_status = Column(
        String(50),
        default="pending"
    )

    status = Column(
        String(50),
        default="waiting"
    )

    razorpay_order_id = Column(
        String(255),
        nullable=True
    )

    razorpay_payment_id = Column(
        String(255),
        nullable=True
    )


# =========================================================
# CREATE TABLES
# =========================================================

Base.metadata.create_all(
    bind=engine
)


# =========================================================
# DATABASE SESSION
# =========================================================

def get_db():

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()


# =========================================================
# PYDANTIC MODELS
# =========================================================


class PatientRegisterRequest(BaseModel):

    full_name: str
    email: str
    phone: str
    password: str


class PatientLoginRequest(BaseModel):

    login: str
    password: str


class HospitalRequest(BaseModel):

    name: str
    email: str
    phone: str
    city: str
    address: str = ""
    description: str = ""
    license_id: str
    password: str


class HospitalLoginRequest(BaseModel):

    login: str
    password: str


class DoctorRequest(BaseModel):

    name: str
    department: str
    experience: str = ""
    specialization: str = ""


class TokenRequest(BaseModel):

    patient_name: str
    hospital: str
    department: str
    doctor: str
    razorpay_order_id: str
    razorpay_payment_id: str


class GoogleLoginRequest(BaseModel):

    credential: str
    role: str = "patient"


class CreateOrderRequest(BaseModel):

    patient_name: str
    hospital: str
    department: str
    doctor: str


class VerifyPaymentRequest(BaseModel):

    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def home():

    return {
        "success": True,
        "message": "HospitalCare API is running"
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return {
        "success": True,
        "status": "ok",
        "message": "HospitalCare backend is healthy"
    }


# =========================================================
# DATABASE TEST
# =========================================================

@app.get("/test-db")
def test_database(
    db: Session = Depends(get_db)
):

    try:

        db.execute(
            text("SELECT 1")
        )

        return {
            "success": True,
            "message": "Database connection is working"
        }

    except Exception as e:

        return {
            "success": False,
            "message": "Database connection failed",
            "error": str(e)
        }


# =========================================================
# GOOGLE LOGIN
# =========================================================

@app.post("/auth/google")
def google_login(
    data: GoogleLoginRequest
):

    try:

        google_user = id_token.verify_oauth2_token(
            data.credential,
            requests.Request(),
            GOOGLE_CLIENT_ID
        )

        return {
            "success": True,
            "message": "Google login successful",
            "role": data.role,
            "user": {
                "google_id": google_user.get("sub"),
                "name": google_user.get("name"),
                "email": google_user.get("email"),
                "picture": google_user.get("picture")
            }
        }

    except ValueError:

        raise HTTPException(
            status_code=401,
            detail="Invalid Google token"
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Google login error: {str(e)}"
        )


# =========================================================
# PATIENT REGISTER
# =========================================================

@app.post("/patients/register")
def register_patient(
    data: PatientRegisterRequest,
    db: Session = Depends(get_db)
):

    full_name = data.full_name.strip()
    email = data.email.strip().lower()
    phone = data.phone.strip()
    password = data.password.strip()

    if not full_name:

        raise HTTPException(
            status_code=400,
            detail="Full name is required"
        )

    if not email:

        raise HTTPException(
            status_code=400,
            detail="Email is required"
        )

    if not phone:

        raise HTTPException(
            status_code=400,
            detail="Phone number is required"
        )

    if len(password) < 6:

        raise HTTPException(
            status_code=400,
            detail="Password must contain at least 6 characters"
        )

    if db.query(Patient).filter(
        Patient.email == email
    ).first():

        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    if db.query(Patient).filter(
        Patient.phone == phone
    ).first():

        raise HTTPException(
            status_code=400,
            detail="Phone number already registered"
        )

    try:

        patient = Patient(
            full_name=full_name,
            email=email,
            phone=phone,
            password=pwd_context.hash(password)
        )

        db.add(patient)
        db.commit()
        db.refresh(patient)

        return {
            "success": True,
            "message": "Patient registered successfully",
            "patient": {
                "id": patient.id,
                "full_name": patient.full_name,
                "email": patient.email,
                "phone": patient.phone
            }
        }

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Unable to register patient: {str(e)}"
        )


# =========================================================
# PATIENT LOGIN
# =========================================================

@app.post("/patients/login")
def login_patient(
    data: PatientLoginRequest,
    db: Session = Depends(get_db)
):

    login_value = data.login.strip()
    password = data.password.strip()

    patient = db.query(Patient).filter(
        (Patient.email == login_value.lower()) |
        (Patient.phone == login_value)
    ).first()

    if not patient:

        raise HTTPException(
            status_code=401,
            detail="Invalid email/phone or password"
        )

    try:

        valid = pwd_context.verify(
            password,
            patient.password
        )

    except Exception:

        valid = False

    if not valid:

        raise HTTPException(
            status_code=401,
            detail="Invalid email/phone or password"
        )

    return {
        "success": True,
        "message": "Login successful",
        "patient": {
            "id": patient.id,
            "full_name": patient.full_name,
            "email": patient.email,
            "phone": patient.phone
        }
    }


# =========================================================
# CREATE HOSPITAL
# =========================================================

@app.post("/hospitals")
def create_hospital(
    data: HospitalRequest,
    db: Session = Depends(get_db)
):

    name = data.name.strip()
    email = data.email.strip().lower()
    phone = data.phone.strip()
    city = data.city.strip()
    address = data.address.strip()
    description = data.description.strip()
    license_id = data.license_id.strip()
    password = data.password.strip()

    if not name:

        raise HTTPException(
            status_code=400,
            detail="Hospital name is required"
        )

    if not email:

        raise HTTPException(
            status_code=400,
            detail="Hospital email is required"
        )

    if not phone:

        raise HTTPException(
            status_code=400,
            detail="Hospital phone is required"
        )

    if not city:

        raise HTTPException(
            status_code=400,
            detail="City is required"
        )

    if not license_id:

        raise HTTPException(
            status_code=400,
            detail="License ID is required"
        )

    if len(password) < 6:

        raise HTTPException(
            status_code=400,
            detail="Password must contain at least 6 characters"
        )

    existing_license = db.query(Hospital).filter(
        Hospital.license_id == license_id
    ).first()

    if existing_license:

        raise HTTPException(
            status_code=400,
            detail="This license ID is already registered"
        )

    existing_email = db.query(Hospital).filter(
        Hospital.email == email
    ).first()

    if existing_email:

        raise HTTPException(
            status_code=400,
            detail="This hospital email is already registered"
        )

    try:

        hospital = Hospital(

            name=name,

            email=email,

            phone=phone,

            city=city,

            address=address,

            description=description,

            password_hash=pwd_context.hash(
                password
            ),

            license_id=license_id,

            approval_status="PENDING",

            is_published=False
        )

        db.add(hospital)

        db.commit()

        db.refresh(hospital)

        return {

            "success": True,

            "message":
                "Hospital submitted for admin verification",

            "hospital": {

                "id":
                    hospital.id,

                "name":
                    hospital.name,

                "email":
                    hospital.email,

                "phone":
                    hospital.phone,

                "city":
                    hospital.city,

                "address":
                    hospital.address or "",

                "description":
                    hospital.description or "",

                "license_id":
                    hospital.license_id,

                "approval_status":
                    hospital.approval_status,

                "is_published":
                    hospital.is_published
            }
        }

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Unable to save hospital: {str(e)}"
        )


# =========================================================
# HOSPITAL LOGIN
# =========================================================

@app.post("/hospitals/login")
def hospital_login(
    data: HospitalLoginRequest,
    db: Session = Depends(get_db)
):

    login_value = data.login.strip()
    password = data.password.strip()

    hospital = db.query(Hospital).filter(
        Hospital.email == login_value.lower()
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=401,
            detail="Invalid hospital email or password"
        )

    if not hospital.password_hash:

        raise HTTPException(
            status_code=401,
            detail="Hospital password is not configured"
        )

    try:

        valid = pwd_context.verify(
            password,
            hospital.password_hash
        )

    except Exception:

        valid = False

    if not valid:

        raise HTTPException(
            status_code=401,
            detail="Invalid hospital email or password"
        )

    return {

        "success": True,

        "message":
            "Hospital login successful",

        "hospital": {

            "id":
                hospital.id,

            "name":
                hospital.name,

            "email":
                hospital.email,

            "phone":
                hospital.phone or "",

            "city":
                hospital.city,

            "address":
                hospital.address or "",

            "license_id":
                hospital.license_id or "",

            "approval_status":
                hospital.approval_status,

            "is_published":
                hospital.is_published
        }
    }


# =========================================================
# PATIENT HOSPITAL LIST
# ONLY APPROVED + PUBLISHED HOSPITALS
# =========================================================

@app.get("/hospitals")
def get_hospitals(
    db: Session = Depends(get_db)
):

    hospitals = db.query(Hospital).filter(

        Hospital.approval_status == "APPROVED",

        Hospital.is_published == True

    ).order_by(
        Hospital.name.asc()
    ).all()

    result = []

    for hospital in hospitals:

        result.append({

            "id":
                hospital.id,

            "name":
                hospital.name,

            "city":
                hospital.city,

            "address":
                hospital.address or "",

            "description":
                hospital.description or ""
        })

    return result


# =========================================================
# GET ONE HOSPITAL
# =========================================================

@app.get("/hospitals/{hospital_id}")
def get_hospital(
    hospital_id: int,
    db: Session = Depends(get_db)
):

    hospital = db.query(Hospital).filter(
        Hospital.id == hospital_id
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    return {

        "success": True,

        "id":
            hospital.id,

        "name":
            hospital.name,

        "email":
            hospital.email or "",

        "phone":
            hospital.phone or "",

        "city":
            hospital.city,

        "address":
            hospital.address or "",

        "description":
            hospital.description or "",

        "license_id":
            hospital.license_id or "",

        "approval_status":
            hospital.approval_status,

        "is_published":
            hospital.is_published
    }


# =========================================================
# ADD DOCTOR
# =========================================================

@app.post("/hospitals/{hospital_id}/doctors")
def create_doctor(
    hospital_id: int,
    data: DoctorRequest,
    db: Session = Depends(get_db)
):

    hospital = db.query(Hospital).filter(
        Hospital.id == hospital_id
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    doctor_name = data.name.strip()
    department = data.department.strip()
    experience = data.experience.strip()
    specialization = data.specialization.strip()

    if not doctor_name:

        raise HTTPException(
            status_code=400,
            detail="Doctor name is required"
        )

    if not department:

        raise HTTPException(
            status_code=400,
            detail="Department is required"
        )

    try:

        doctor = Doctor(

            hospital_id=hospital_id,

            name=doctor_name,

            department=department,

            experience=experience,

            specialization=specialization
        )

        db.add(doctor)

        db.commit()

        db.refresh(doctor)

        return {

            "success": True,

            "message":
                "Doctor saved successfully",

            "doctor": {

                "id":
                    doctor.id,

                "hospital_id":
                    doctor.hospital_id,

                "name":
                    doctor.name,

                "department":
                    doctor.department,

                "experience":
                    doctor.experience or "",

                "specialization":
                    doctor.specialization or ""
            }
        }

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Unable to save doctor: {str(e)}"
        )


# =========================================================
# GET DOCTORS
# =========================================================

@app.get("/hospitals/{hospital_id}/doctors")
def get_doctors(
    hospital_id: int,
    department: str = None,
    db: Session = Depends(get_db)
):

    hospital = db.query(Hospital).filter(
        Hospital.id == hospital_id
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    query = db.query(Doctor).filter(
        Doctor.hospital_id == hospital_id
    )

    if department:

        query = query.filter(
            Doctor.department == department.strip()
        )

    doctors = query.order_by(
        Doctor.name.asc()
    ).all()

    result = []

    for doctor in doctors:

        result.append({

            "id":
                doctor.id,

            "hospital_id":
                doctor.hospital_id,

            "name":
                doctor.name,

            "department":
                doctor.department,

            "experience":
                doctor.experience or "",

            "specialization":
                doctor.specialization or ""
        })

    return result


# =========================================================
# GET DEPARTMENTS
# =========================================================

@app.get("/hospitals/{hospital_id}/departments")
def get_departments(
    hospital_id: int,
    db: Session = Depends(get_db)
):

    hospital = db.query(Hospital).filter(
        Hospital.id == hospital_id
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    departments = db.query(
        Doctor.department
    ).filter(
        Doctor.hospital_id == hospital_id
    ).distinct().order_by(
        Doctor.department.asc()
    ).all()

    return [

        department[0].strip()

        for department in departments

        if department[0]

    ]


# =========================================================
# DELETE DOCTOR
# =========================================================

@app.delete("/doctors/{doctor_id}")
def delete_doctor(
    doctor_id: int,
    db: Session = Depends(get_db)
):

    doctor = db.query(Doctor).filter(
        Doctor.id == doctor_id
    ).first()

    if not doctor:

        raise HTTPException(
            status_code=404,
            detail="Doctor not found"
        )

    try:

        db.delete(doctor)

        db.commit()

        return {

            "success": True,

            "message":
                "Doctor removed successfully"
        }

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Unable to delete doctor: {str(e)}"
        )


# =========================================================
# ADMIN - GET ALL HOSPITALS
# =========================================================

@app.get("/admin/hospitals")
def admin_hospitals(
    db: Session = Depends(get_db)
):

    hospitals = db.query(
        Hospital
    ).order_by(
        Hospital.id.desc()
    ).all()

    result = []

    for hospital in hospitals:

        doctor_count = db.query(
            Doctor
        ).filter(
            Doctor.hospital_id == hospital.id
        ).count()

        result.append({

            "id":
                hospital.id,

            "name":
                hospital.name,

            "email":
                hospital.email or "",

            "phone":
                hospital.phone or "",

            "city":
                hospital.city,

            "address":
                hospital.address or "",

            "description":
                hospital.description or "",

            "license_id":
                hospital.license_id or "",

            "approval_status":
                hospital.approval_status,

            "is_published":
                hospital.is_published,

            "doctor_count":
                doctor_count
        })

    return result


# =========================================================
# ADMIN - GET SINGLE HOSPITAL
# =========================================================

@app.get("/admin/hospitals/{hospital_id}")
def admin_get_hospital(
    hospital_id: int,
    db: Session = Depends(get_db)
):

    hospital = db.query(Hospital).filter(
        Hospital.id == hospital_id
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    doctor_count = db.query(
        Doctor
    ).filter(
        Doctor.hospital_id == hospital_id
    ).count()

    return {

        "id":
            hospital.id,

        "name":
            hospital.name,

        "email":
            hospital.email or "",

        "phone":
            hospital.phone or "",

        "city":
            hospital.city,

        "address":
            hospital.address or "",

        "description":
            hospital.description or "",

        "license_id":
            hospital.license_id or "",

        "approval_status":
            hospital.approval_status,

        "is_published":
            hospital.is_published,

        "doctor_count":
            doctor_count
    }


# =========================================================
# ADMIN - APPROVE HOSPITAL
# =========================================================

@app.put("/admin/hospitals/{hospital_id}/approve")
def approve_hospital(
    hospital_id: int,
    db: Session = Depends(get_db)
):

    hospital = db.query(Hospital).filter(
        Hospital.id == hospital_id
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    if not hospital.license_id:

        raise HTTPException(
            status_code=400,
            detail="Hospital does not have a license ID"
        )

    hospital.approval_status = "APPROVED"

    # Approval does NOT automatically publish
    hospital.is_published = False

    db.commit()

    db.refresh(hospital)

    return {

        "success": True,

        "message":
            "Hospital approved successfully",

        "hospital": {

            "id":
                hospital.id,

            "approval_status":
                hospital.approval_status,

            "is_published":
                hospital.is_published
        }
    }


# =========================================================
# ADMIN - REJECT HOSPITAL
# =========================================================

@app.put("/admin/hospitals/{hospital_id}/reject")
def reject_hospital(
    hospital_id: int,
    db: Session = Depends(get_db)
):

    hospital = db.query(Hospital).filter(
        Hospital.id == hospital_id
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    hospital.approval_status = "REJECTED"

    hospital.is_published = False

    db.commit()

    db.refresh(hospital)

    return {

        "success": True,

        "message":
            "Hospital rejected",

        "hospital": {

            "id":
                hospital.id,

            "approval_status":
                hospital.approval_status,

            "is_published":
                hospital.is_published
        }
    }


# =========================================================
# ADMIN - PUBLISH HOSPITAL
# =========================================================

@app.put("/admin/hospitals/{hospital_id}/publish")
def publish_hospital(
    hospital_id: int,
    db: Session = Depends(get_db)
):

    hospital = db.query(Hospital).filter(
        Hospital.id == hospital_id
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    if hospital.approval_status != "APPROVED":

        raise HTTPException(
            status_code=400,
            detail="Hospital must be approved before publishing"
        )

    hospital.is_published = True

    db.commit()

    db.refresh(hospital)

    return {

        "success": True,

        "message":
            "Hospital published successfully",

        "hospital": {

            "id":
                hospital.id,

            "approval_status":
                hospital.approval_status,

            "is_published":
                hospital.is_published
        }
    }


# =========================================================
# ADMIN - UNPUBLISH HOSPITAL
# =========================================================

@app.put("/admin/hospitals/{hospital_id}/unpublish")
def unpublish_hospital(
    hospital_id: int,
    db: Session = Depends(get_db)
):

    hospital = db.query(Hospital).filter(
        Hospital.id == hospital_id
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    hospital.is_published = False

    db.commit()

    db.refresh(hospital)

    return {

        "success": True,

        "message":
            "Hospital unpublished successfully",

        "hospital": {

            "id":
                hospital.id,

            "approval_status":
                hospital.approval_status,

            "is_published":
                hospital.is_published
        }
    }


# =========================================================
# ADMIN - DELETE HOSPITAL
# =========================================================

@app.delete("/admin/hospitals/{hospital_id}")
def delete_hospital(
    hospital_id: int,
    db: Session = Depends(get_db)
):

    hospital = db.query(Hospital).filter(
        Hospital.id == hospital_id
    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    try:

        # Delete doctors belonging to hospital
        db.query(Doctor).filter(
            Doctor.hospital_id == hospital_id
        ).delete(
            synchronize_session=False
        )

        # Delete hospital
        db.delete(hospital)

        db.commit()

        return {

            "success": True,

            "message":
                "Hospital and its doctors deleted successfully"
        }

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Unable to delete hospital: {str(e)}"
        )


# =========================================================
# RAZORPAY CREATE ORDER
# =========================================================

@app.post("/api/create-order")
def create_razorpay_order(
    data: CreateOrderRequest,
    db: Session = Depends(get_db)
):

    if not razorpay_client:

        raise HTTPException(
            status_code=500,
            detail=(
                "Razorpay is not configured. "
                "Check RAZORPAY_KEY_ID and "
                "RAZORPAY_KEY_SECRET in .env"
            )
        )

    patient_name = data.patient_name.strip()
    hospital_name = data.hospital.strip()
    department_name = data.department.strip()
    doctor_name = data.doctor.strip()

    hospital = db.query(Hospital).filter(

        Hospital.name == hospital_name,

        Hospital.approval_status == "APPROVED",

        Hospital.is_published == True

    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found or not published"
        )

    doctor = db.query(Doctor).filter(

        Doctor.hospital_id == hospital.id,

        Doctor.department == department_name,

        Doctor.name == doctor_name

    ).first()

    if not doctor:

        raise HTTPException(
            status_code=404,
            detail="Doctor not found"
        )

    amount_rupees = 10

    amount_paise = amount_rupees * 100

    try:

        order = razorpay_client.order.create({

            "amount":
                amount_paise,

            "currency":
                "INR",

            "receipt":
                f"hospitalcare_{hospital.id}"
        })

        return {

            "success": True,

            "order_id":
                order["id"],

            "key_id":
                RAZORPAY_KEY_ID,

            "amount":
                amount_paise,

            "currency":
                "INR",

            "token_fee":
                0,

            "platform_fee":
                10,

            "total_amount":
                amount_rupees
        }

    except Exception as e:

        print(
            "Razorpay order error:",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to create Razorpay order"
        )


# =========================================================
# VERIFY PAYMENT
# =========================================================

@app.post("/api/verify-payment")
def verify_payment(
    data: VerifyPaymentRequest
):

    if not razorpay_client:

        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured"
        )

    try:

        razorpay_client.utility.verify_payment_signature({

            "razorpay_order_id":
                data.razorpay_order_id,

            "razorpay_payment_id":
                data.razorpay_payment_id,

            "razorpay_signature":
                data.razorpay_signature

        })

        return {

            "success": True,

            "message":
                "Payment verified successfully",

            "razorpay_order_id":
                data.razorpay_order_id,

            "razorpay_payment_id":
                data.razorpay_payment_id
        }

    except Exception:

        raise HTTPException(
            status_code=400,
            detail="Payment verification failed"
        )


# =========================================================
# CREATE TOKEN
# =========================================================

@app.post("/tokens")
def create_token(
    data: TokenRequest,
    db: Session = Depends(get_db)
):

    patient_name = data.patient_name.strip()

    hospital_name = data.hospital.strip()

    department_name = data.department.strip()

    doctor_name = data.doctor.strip()

    order_id = data.razorpay_order_id.strip()

    payment_id = data.razorpay_payment_id.strip()

    if not patient_name:

        raise HTTPException(
            status_code=400,
            detail="Patient name is required"
        )

    if not order_id:

        raise HTTPException(
            status_code=400,
            detail="Razorpay order ID is required"
        )

    if not payment_id:

        raise HTTPException(
            status_code=400,
            detail="Razorpay payment ID is required"
        )

    existing_payment = db.query(Token).filter(
        Token.razorpay_payment_id == payment_id
    ).first()

    if existing_payment:

        raise HTTPException(
            status_code=400,
            detail="This payment has already been used"
        )

    hospital = db.query(Hospital).filter(

        Hospital.name == hospital_name,

        Hospital.approval_status == "APPROVED",

        Hospital.is_published == True

    ).first()

    if not hospital:

        raise HTTPException(
            status_code=404,
            detail="Hospital not found or not published"
        )

    doctor = db.query(Doctor).filter(

        Doctor.hospital_id == hospital.id,

        Doctor.department == department_name,

        Doctor.name == doctor_name

    ).first()

    if not doctor:

        raise HTTPException(
            status_code=404,
            detail="Doctor not found"
        )

    if not razorpay_client:

        raise HTTPException(
            status_code=500,
            detail="Razorpay is not configured"
        )

    try:

        payment = razorpay_client.payment.fetch(
            payment_id
        )

        payment_order_id = payment.get(
            "order_id"
        )

        payment_status = payment.get(
            "status"
        )

        if payment_order_id != order_id:

            raise HTTPException(
                status_code=400,
                detail="Payment does not belong to this order"
            )

        if payment_status not in [
            "authorized",
            "captured"
        ]:

            raise HTTPException(
                status_code=400,
                detail="Payment has not been completed"
            )

    except HTTPException:

        raise

    except Exception:

        raise HTTPException(
            status_code=400,
            detail="Unable to verify Razorpay payment"
        )

    latest = db.query(Token).filter(

        Token.hospital == hospital_name,

        Token.department == department_name,

        Token.doctor == doctor_name

    ).order_by(

        Token.token_number.desc()

    ).first()

    if latest:

        new_token = (
            latest.token_number + 1
        )

    else:

        new_token = 1

    current = db.query(Token).filter(

        Token.hospital == hospital_name,

        Token.department == department_name,

        Token.doctor == doctor_name,

        Token.status == "serving"

    ).order_by(

        Token.token_number.desc()

    ).first()

    current_token = (

        current.token_number

        if current

        else 0
    )

    people_ahead = (

        new_token -

        current_token -

        1
    )

    if people_ahead < 0:

        people_ahead = 0

    try:

        token = Token(

            patient_name=
                patient_name,

            hospital=
                hospital_name,

            department=
                department_name,

            doctor=
                doctor_name,

            token_number=
                new_token,

            platform_fee=
                10,

            payment_status=
                "paid",

            status=
                "waiting",

            razorpay_order_id=
                order_id,

            razorpay_payment_id=
                payment_id
        )

        db.add(token)

        db.commit()

        db.refresh(token)

        return {

            "success": True,

            "message":
                "Payment successful and token created",

            "id":
                token.id,

            "token":
                new_token,

            "token_number":
                new_token,

            "current_token":
                current_token,

            "people_ahead":
                people_ahead,

            "platform_fee":
                10,

            "payment_status":
                "paid",

            "status":
                "waiting"
        }

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Unable to create token: {str(e)}"
        )


# =========================================================
# GET TOKENS
# =========================================================

@app.get("/tokens")
def get_tokens(
    db: Session = Depends(get_db)
):

    tokens = db.query(
        Token
    ).order_by(
        Token.id.desc()
    ).all()

    return [

        {

            "id":
                token.id,

            "patient_name":
                token.patient_name,

            "hospital":
                token.hospital,

            "department":
                token.department,

            "doctor":
                token.doctor,

            "token_number":
                token.token_number,

            "platform_fee":
                token.platform_fee,

            "payment_status":
                token.payment_status,

            "status":
                token.status,

            "razorpay_order_id":
                token.razorpay_order_id,

            "razorpay_payment_id":
                token.razorpay_payment_id
        }

        for token in tokens

    ]


# =========================================================
# PATIENT TOKEN
# =========================================================

@app.get("/patient-token/{token_id}")
def get_patient_token(
    token_id: int,
    db: Session = Depends(get_db)
):

    token = db.query(Token).filter(
        Token.id == token_id
    ).first()

    if not token:

        raise HTTPException(
            status_code=404,
            detail="Token not found"
        )

    current = db.query(Token).filter(

        Token.hospital ==
            token.hospital,

        Token.department ==
            token.department,

        Token.doctor ==
            token.doctor,

        Token.status ==
            "serving"

    ).order_by(

        Token.token_number.desc()

    ).first()

    current_token = (

        current.token_number

        if current

        else 0
    )

    people_ahead = (

        token.token_number -

        current_token -

        1
    )

    if people_ahead < 0:

        people_ahead = 0

    return {

        "success": True,

        "id":
            token.id,

        "token":
            token.token_number,

        "token_number":
            token.token_number,

        "patient_name":
            token.patient_name,

        "hospital":
            token.hospital,

        "department":
            token.department,

        "doctor":
            token.doctor,

        "current_token":
            current_token,

        "people_ahead":
            people_ahead,

        "payment_status":
            token.payment_status,

        "status":
            token.status
    }


# =========================================================
# NEXT PATIENT
# =========================================================

@app.post("/next-patient")
def next_patient(
    hospital: str,
    department: str,
    doctor: str,
    db: Session = Depends(get_db)
):

    hospital = hospital.strip()

    department = department.strip()

    doctor = doctor.strip()

    current = db.query(Token).filter(

        Token.hospital == hospital,

        Token.department == department,

        Token.doctor == doctor,

        Token.status == "serving"

    ).first()

    if current:

        current.status = "completed"

    next_record = db.query(Token).filter(

        Token.hospital == hospital,

        Token.department == department,

        Token.doctor == doctor,

        Token.status == "waiting",

        Token.payment_status == "paid"

    ).order_by(

        Token.token_number.asc()

    ).first()

    if not next_record:

        db.commit()

        return {

            "success": False,

            "message":
                "No waiting patients"
        }

    next_record.status = "serving"

    db.commit()

    db.refresh(next_record)

    return {

        "success": True,

        "message":
            "Patient called",

        "token":
            next_record.token_number,

        "patient":
            next_record.patient_name
    }


# =========================================================
# ADMIN REVENUE
# =========================================================

@app.get("/admin/revenue")
def admin_revenue(
    db: Session = Depends(get_db)
):

    paid_tokens = db.query(Token).filter(
        Token.payment_status == "paid"
    ).all()

    total_tokens = len(
        paid_tokens
    )

    total_revenue = (
        total_tokens * 10
    )

    return {

        "total_tokens":
            total_tokens,

        "fee_per_token":
            10,

        "total_revenue":
            total_revenue
    }