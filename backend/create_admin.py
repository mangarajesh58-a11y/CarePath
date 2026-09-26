from database import SessionLocal
from main import Admin, hash_password


db = SessionLocal()

try:
    name = input("Enter admin name: ").strip()
    email = input("Enter admin email: ").strip()
    password = input("Enter admin password: ")

    existing_admin = (
        db.query(Admin)
        .filter(Admin.email == email)
        .first()
    )

    if existing_admin:
        print("Admin already exists!")
    else:
        admin = Admin(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role="admin"
        )

        db.add(admin)
        db.commit()

        print()
        print("================================")
        print("Admin created successfully!")
        print("Email:", email)
        print("================================")

finally:
    db.close()