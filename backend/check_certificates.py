from database import SessionLocal
from models import Hospital

db = SessionLocal()
try:
    hospitals = (
        db.query(
            Hospital.id,
            Hospital.name,
            Hospital.license_certificate,
        )
        .order_by(Hospital.id)
        .all()
    )

    for hospital_id, name, filename in hospitals:
        print(
            f"ID: {hospital_id} | "
            f"Hospital: {name} | "
            f"Certificate: {filename}"
        )
finally:
    db.close()
