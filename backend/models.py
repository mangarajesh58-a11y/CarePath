from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Float

from database import Base

# ==========================================

# HOSPITAL

# ==========================================

class Hospital(Base):


__tablename__ = "hospitals"

id = Column(
    Integer,
    primary_key=True,
    index=True
)

name = Column(
    String(150),
    nullable=False
)

location = Column(
    String(150),
    nullable=False
)

address = Column(
    String(300),
    nullable=False
)

phone = Column(
    String(20),
    nullable=True
)

description = Column(
    String(500),
    nullable=True
)

facilities = Column(
    String(1000),
    nullable=True
)

departments = Column(
    String(1000),
    nullable=True
)
```

# ==========================================

# DOCTOR

# ==========================================

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
    String(150),
    nullable=False
)

department = Column(
    String(150),
    nullable=False
)


# ==========================================

# TOKEN + RAZORPAY PAYMENT

# ==========================================

class Token(Base):


__tablename__ = "tokens"

id = Column(
    Integer,
    primary_key=True,
    index=True
)

patient_name = Column(
    String(150),
    nullable=False
)

hospital_id = Column(
    Integer,
    nullable=False
)

hospital_name = Column(
    String(150),
    nullable=False
)

department = Column(
    String(150),
    nullable=False
)

doctor = Column(
    String(150),
    nullable=False
)

token_number = Column(
    Integer,
    nullable=False
)


# ======================================
# PAYMENT DETAILS
# ======================================

token_fee = Column(
    Float,
    default=0
)

platform_fee = Column(
    Float,
    default=10
)

total_amount = Column(
    Float,
    default=0
)

payment_status = Column(
    String(50),
    default="pending"
)


# ======================================
# RAZORPAY DETAILS
# ======================================

razorpay_order_id = Column(
    String(150),
    nullable=True
)

razorpay_payment_id = Column(
    String(150),
    nullable=True
)

razorpay_signature = Column(
    String(300),
    nullable=True
)


# ======================================
# TOKEN STATUS
# ======================================

status = Column(
    String(50),
    default="waiting"
)

