"""
Database migration script to add dynamic fee calculation fields to tokens,
platform_contacts, and create the platform_fee_configs table.
Safe and idempotent: uses IF NOT EXISTS / check before alter.
"""
from sqlalchemy import text
from main import engine, SessionLocal
import logging

logging.basicConfig(level=logging.INFO)

def run_migration():
    logging.info("Starting safe dynamic fee system migration...")
    
    with engine.connect() as conn:
        # 1. Create platform_fee_configs table if not exists
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS platform_fee_configs (
                id SERIAL PRIMARY KEY,
                version INTEGER NOT NULL DEFAULT 1,
                platform_fee NUMERIC(10, 2) NOT NULL DEFAULT 10.00,
                gst_percentage NUMERIC(5, 2) NOT NULL DEFAULT 18.00,
                gateway_fee_percentage NUMERIC(5, 2) NOT NULL DEFAULT 2.00,
                gateway_fee_gst NUMERIC(5, 2) NOT NULL DEFAULT 18.00,
                gateway_fee_basis VARCHAR(50) NOT NULL DEFAULT 'hospital_fee',
                pass_gateway_fee_to_patient BOOLEAN NOT NULL DEFAULT TRUE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_by VARCHAR(255) NULL,
                created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.commit()
        logging.info("platform_fee_configs table verified.")

        # 2. Add columns to platform_contacts if not exists
        columns_contact = [
            ("gst_percentage", "NUMERIC(5, 2) DEFAULT 18.00"),
            ("gateway_fee_percentage", "NUMERIC(5, 2) DEFAULT 2.00"),
            ("gateway_fee_gst", "NUMERIC(5, 2) DEFAULT 18.00"),
            ("gateway_fee_basis", "VARCHAR(50) DEFAULT 'hospital_fee'"),
            ("pass_gateway_fee_to_patient", "BOOLEAN DEFAULT TRUE"),
            ("fee_configuration_version", "INTEGER DEFAULT 1"),
        ]
        for col_name, col_def in columns_contact:
            try:
                conn.execute(text(f"ALTER TABLE platform_contacts ADD COLUMN IF NOT EXISTS {col_name} {col_def};"))
                conn.commit()
                logging.info(f"Verified column platform_contacts.{col_name}")
            except Exception as e:
                logging.warning(f"Note on platform_contacts.{col_name}: {e}")

        # 3. Add fee snapshot columns to tokens if not exists
        columns_tokens = [
            ("hospital_token_fee", "NUMERIC(10, 2) NULL"),
            ("gst_percentage", "NUMERIC(5, 2) NULL"),
            ("gst_amount", "NUMERIC(10, 2) NULL"),
            ("gateway_fee_percentage", "NUMERIC(5, 2) NULL"),
            ("gateway_fee_gst", "NUMERIC(5, 2) NULL"),
            ("gateway_fee_amount", "NUMERIC(10, 2) NULL"),
            ("total_extra_fee", "NUMERIC(10, 2) NULL"),
            ("final_amount", "NUMERIC(10, 2) NULL"),
            ("fee_configuration_version", "INTEGER NULL DEFAULT 1"),
        ]
        for col_name, col_def in columns_tokens:
            try:
                conn.execute(text(f"ALTER TABLE tokens ADD COLUMN IF NOT EXISTS {col_name} {col_def};"))
                conn.commit()
                logging.info(f"Verified column tokens.{col_name}")
            except Exception as e:
                logging.warning(f"Note on tokens.{col_name}: {e}")

        # 4. Populate initial row in platform_fee_configs if empty
        res = conn.execute(text("SELECT count(*) FROM platform_fee_configs;")).scalar()
        if res == 0:
            # Check existing platform_fee from platform_contacts
            current_pf = conn.execute(text("SELECT platform_fee FROM platform_contacts LIMIT 1;")).scalar() or 10.00
            conn.execute(text("""
                INSERT INTO platform_fee_configs (
                    version, platform_fee, gst_percentage, gateway_fee_percentage,
                    gateway_fee_gst, gateway_fee_basis, pass_gateway_fee_to_patient,
                    is_active, created_by
                ) VALUES (
                    1, :pf, 18.00, 2.00, 18.00, 'hospital_fee', TRUE, TRUE, 'system_init'
                );
            """), {"pf": float(current_pf)})
            conn.commit()
            logging.info(f"Initialized active platform_fee_config v1 with platform_fee={current_pf}")

    logging.info("Migration completed successfully!")

if __name__ == "__main__":
    run_migration()
