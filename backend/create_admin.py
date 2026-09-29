from main import Admin, hash_password
from database import SessionLocal


# ==========================================
# CREATE DATABASE SESSION
# ==========================================

db = SessionLocal()


try:

    # ==========================================
    # GET ADMIN DETAILS
    # ==========================================

    email = input(
        "Enter admin email: "
    ).strip().lower()

    password = input(
        "Enter admin password: "
    ).strip()


    # ==========================================
    # VALIDATION
    # ==========================================

    if not email:

        print(
            "Admin email is required."
        )

        exit()


    if not password:

        print(
            "Admin password is required."
        )

        exit()


    if len(password) < 6:

        print(
            "Admin password must contain "
            "at least 6 characters."
        )

        exit()


    # ==========================================
    # CHECK EXISTING ADMIN
    # ==========================================

    existing_admin = (
        db.query(Admin)
        .filter(
            Admin.email == email
        )
        .first()
    )


    if existing_admin:

        print()
        print(
            "Admin with this email "
            "already exists."
        )

    else:

        # ==========================================
        # CREATE ADMIN
        # ==========================================

        admin = Admin(

            email=email,

            password=hash_password(
                password
            )
        )


        db.add(admin)

        db.commit()

        db.refresh(admin)


        # ==========================================
        # SUCCESS
        # ==========================================

        print()

        print(
            "================================"
        )

        print(
            "Admin created successfully!"
        )

        print(
            "================================"
        )

        print(
            "Admin ID:",
            admin.id
        )

        print(
            "Admin Email:",
            admin.email
        )

finally:

    db.close()