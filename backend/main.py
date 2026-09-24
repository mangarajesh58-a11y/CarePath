from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Session

from pydantic import BaseModel

from database import Base
from database import engine
from database import SessionLocal


app = FastAPI(
    title="Hospital Token API"
)


# =========================
# CORS
# =========================

app.add_middleware(
    CORSMiddleware,

    allow_origins=["*"],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"]
)


# =========================
# TOKEN TABLE
# =========================

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
        String(100),
        nullable=False
    )

    department = Column(
        String(100),
        nullable=False
    )

    doctor = Column(
        String(100),
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
        default="paid"
    )

    status = Column(
        String(50),
        default="waiting"
    )


# =========================
# CREATE TABLE
# =========================

Base.metadata.create_all(
    bind=engine
)


# =========================
# REQUEST MODEL
# =========================

class TokenRequest(BaseModel):

    patient_name: str

    hospital: str

    department: str

    doctor: str


# =========================
# DATABASE CONNECTION
# =========================

def get_db():

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()


# =========================
# HOME
# =========================

@app.get("/")
def home():

    return {
        "message":
        "Hospital Token API is running"
    }
@app.get("/test-db")
def test_database(db: Session = Depends(get_db)):
    return {"message": "Database connection is working"}


# =========================
# CREATE TOKEN
# =========================

@app.post("/tokens")
def create_token(

    data: TokenRequest,

    db: Session = Depends(get_db)

):

    try:

        # Find latest token
        latest = (

            db.query(Token)

            .filter(

                Token.hospital ==
                data.hospital,

                Token.department ==
                data.department,

                Token.doctor ==
                data.doctor

            )

            .order_by(
                Token.token_number.desc()
            )

            .first()

        )


        # Generate token number
        if latest:

            new_token = (
                latest.token_number + 1
            )

        else:

            new_token = 1


        # Create token
        new_token_record = Token(

            patient_name =
            data.patient_name,

            hospital =
            data.hospital,

            department =
            data.department,

            doctor =
            data.doctor,

            token_number =
            new_token,

            platform_fee =
            10,

            payment_status =
            "paid",

            status =
            "waiting"

        )


        # Add to database
        db.add(
            new_token_record
        )


        # Save to MySQL
        db.commit()


        # Refresh record
        db.refresh(
            new_token_record
        )


        # Find currently serving token
        current = (

            db.query(Token)

            .filter(

                Token.hospital ==
                data.hospital,

                Token.department ==
                data.department,

                Token.doctor ==
                data.doctor,

                Token.status ==
                "serving"

            )

            .order_by(
                Token.token_number.desc()
            )

            .first()

        )


        if current:

            current_token = (
                current.token_number
            )

        else:

            current_token = 0


        people_ahead = (

            new_token
            - current_token
            - 1

        )


        if people_ahead < 0:

            people_ahead = 0


        return {

            "success": True,

            "message":
            "Token saved successfully",

            "id":
            new_token_record.id,

            "token":
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

        print(
            "DATABASE ERROR:",
            str(e)
        )

        return {

            "success": False,

            "message":
            "Token could not be saved",

            "error":
            str(e)

        }


# =========================
# GET ALL TOKENS
# =========================

@app.get("/tokens")
def get_tokens(

    db: Session = Depends(get_db)

):

    tokens = (

        db.query(Token)

        .order_by(
            Token.id.desc()
        )

        .all()

    )


    result = []


    for token in tokens:

        result.append({

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
            token.status

        })


    return result


# =========================
# NEXT PATIENT
# =========================

@app.post("/next-patient")
def next_patient(

    hospital: str,

    department: str,

    doctor: str,

    db: Session = Depends(get_db)

):

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
            "serving"

        )

        .first()

    )


    if current:

        current.status = "completed"


    next_patient = (

        db.query(Token)

        .filter(

            Token.hospital ==
            hospital,

            Token.department ==
            department,

            Token.doctor ==
            doctor,

            Token.status ==
            "waiting"

        )

        .order_by(
            Token.token_number.asc()
        )

        .first()

    )


    if not next_patient:

        db.commit()

        return {

            "message":
            "No waiting patients"

        }


    next_patient.status = "serving"


    db.commit()


    db.refresh(
        next_patient
    )


    return {

        "message":
        "Patient called",

        "token":
        next_patient.token_number,

        "patient":
        next_patient.patient_name

    }


# =========================
# ADMIN REVENUE
# =========================

@app.get("/admin/revenue")
def admin_revenue(

    db: Session = Depends(get_db)

):

    total_tokens = (

        db.query(Token)
        .count()

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
@app.get("/patient-token/{token_id}")
def get_patient_token(
    token_id: int,
    db: Session = Depends(get_db)
):
    token = (
        db.query(Token)
        .filter(Token.id == token_id)
        .first()
    )

    if not token:
        return {
            "success": False,
            "message": "Token not found"
        }

    return {
        "success": True,
        "id": token.id,
        "token": token.token_number,
        "patient_name": token.patient_name,
        "hospital": token.hospital,
        "department": token.department,
        "doctor": token.doctor,
        "status": token.status
    }