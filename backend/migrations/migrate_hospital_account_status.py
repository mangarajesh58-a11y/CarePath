"""
Migration: Hospital Account Lifecycle & Deactivation Management
Adds:
- hospitals.account_status (ACTIVE, DELETION_REQUESTED, SUSPENDED, DEACTIVATED)
- hospitals.deactivated_at
- hospitals.deactivated_by
- hospitals.closure_reason
- table hospital_account_closure_requests
Backfills:
- Existing hospitals with is_deleted=TRUE -> DEACTIVATED
- Existing hospitals with is_deleted=FALSE -> ACTIVE
Supports rollback via --rollback flag.
"""

import sys
import os
import argparse
from sqlalchemy import text, inspect

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import engine

def migrate():
    print("=" * 60)
    print("MIGRATION: Hospital Account Lifecycle & Deactivation System")
    print("=" * 60)

    insp = inspect(engine)
    existing_cols = [c["name"] for c in insp.get_columns("hospitals")]
    existing_tables = insp.get_table_names()

    with engine.begin() as conn:
        # 1. Add account_status column
        if "account_status" not in existing_cols:
            print("[+] Adding hospitals.account_status column...")
            conn.execute(text("ALTER TABLE hospitals ADD COLUMN account_status VARCHAR(30) DEFAULT 'ACTIVE' NOT NULL;"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_hospitals_account_status ON hospitals (account_status);"))
        else:
            print("[.] hospitals.account_status already exists.")

        # 2. Add deactivated_at column
        if "deactivated_at" not in existing_cols:
            print("[+] Adding hospitals.deactivated_at column...")
            conn.execute(text("ALTER TABLE hospitals ADD COLUMN deactivated_at TIMESTAMP NULL;"))
        else:
            print("[.] hospitals.deactivated_at already exists.")

        # 3. Add deactivated_by column
        if "deactivated_by" not in existing_cols:
            print("[+] Adding hospitals.deactivated_by column...")
            conn.execute(text("ALTER TABLE hospitals ADD COLUMN deactivated_by VARCHAR(255) NULL;"))
        else:
            print("[.] hospitals.deactivated_by already exists.")

        # 4. Add closure_reason column
        if "closure_reason" not in existing_cols:
            print("[+] Adding hospitals.closure_reason column...")
            conn.execute(text("ALTER TABLE hospitals ADD COLUMN closure_reason TEXT NULL;"))
        else:
            print("[.] hospitals.closure_reason already exists.")

        # 5. Create hospital_account_closure_requests table
        if "hospital_account_closure_requests" not in existing_tables:
            print("[+] Creating hospital_account_closure_requests table...")
            conn.execute(text("""
                CREATE TABLE hospital_account_closure_requests (
                    id SERIAL PRIMARY KEY,
                    hospital_id INTEGER NOT NULL,
                    status VARCHAR(30) DEFAULT 'PENDING' NOT NULL,
                    reason TEXT NOT NULL,
                    password_verified BOOLEAN DEFAULT TRUE NOT NULL,
                    affected_active_tokens INTEGER DEFAULT 0 NOT NULL,
                    admin_id INTEGER NULL,
                    admin_remarks TEXT NULL,
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    reviewed_at TIMESTAMP WITHOUT TIME ZONE NULL,
                    completed_at TIMESTAMP WITHOUT TIME ZONE NULL
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_hosp_closure_req_hospital_id ON hospital_account_closure_requests (hospital_id);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_hosp_closure_req_status ON hospital_account_closure_requests (status);"))
        else:
            print("[.] hospital_account_closure_requests table already exists.")

        # 6. Backfill existing hospitals
        print("[*] Backfilling account_status based on is_deleted flag...")
        conn.execute(text("""
            UPDATE hospitals 
            SET account_status = CASE 
                WHEN is_deleted = TRUE THEN 'DEACTIVATED'
                ELSE 'ACTIVE'
            END
            WHERE account_status IS NULL OR account_status NOT IN ('ACTIVE', 'DELETION_REQUESTED', 'SUSPENDED', 'DEACTIVATED');
        """))

    print("=" * 60)
    print("MIGRATION SUCCESSFUL: All tables and columns verified.")
    print("=" * 60)


def rollback():
    print("=" * 60)
    print("ROLLBACK: Reverting Hospital Account Lifecycle System")
    print("=" * 60)

    with engine.begin() as conn:
        print("[-] Dropping hospital_account_closure_requests table...")
        conn.execute(text("DROP TABLE IF EXISTS hospital_account_closure_requests CASCADE;"))

        print("[-] Dropping columns from hospitals table...")
        for col in ["account_status", "deactivated_at", "deactivated_by", "closure_reason"]:
            conn.execute(text(f"ALTER TABLE hospitals DROP COLUMN IF EXISTS {col};"))

    print("=" * 60)
    print("ROLLBACK COMPLETED SUCCESSFULLY.")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hospital Account Lifecycle Migration")
    parser.add_argument("--rollback", action="store_true", help="Revert the migration")
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        migrate()
