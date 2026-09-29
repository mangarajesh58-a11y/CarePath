
from main import Admin, hash_password
from database import SessionLocal

db = SessionLocal()

try:
    email = input("Enter your existing admin email: ").strip().lower()
    new_password = input("Enter your new password: ").strip()

    if not email or not new_password:
        print("Email and password are required.")
    elif len(new_password) < 8:
        print("Password must contain at least 8 characters.")
    else:
        admin = db.query(Admin).filter(
            Admin.email == email
        ).first()

        if admin:
            admin.password = hash_password(new_password)
            db.commit()
            print("Admin password reset successfully.")
        else:
            print("Admin account not found.")

except Exception as error:
    db.rollback()
    print("Error:", error)
finally:
    db.close()