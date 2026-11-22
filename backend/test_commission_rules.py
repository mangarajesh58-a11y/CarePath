"""
CarePath Platform Commission Validation & Rounding Rules Test Suite
Automated verification of Rules 1 through 7.
"""

import os
import sys
import unittest
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from fastapi.testclient import TestClient
from database import SessionLocal
from models import Admin, Patient, Hospital, Doctor, Token, PlatformContact, AdminAuditLog
from main import (
    app,
    calculate_commission,
    get_current_commission_percentage,
    create_access_token,
    get_or_create_contact_settings,
)


class CarePathCommissionRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        cls.db = SessionLocal()

        # Generate tokens
        cls.admin_token = create_access_token(user_id=999901, role="admin")
        cls.patient_token = create_access_token(user_id=999902, role="patient")
        cls.hospital_token = create_access_token(user_id=999903, role="hospital")

        # Ensure contact settings exist
        contact = get_or_create_contact_settings(cls.db)
        contact.commission_percentage = Decimal("10.00")
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        # Cleanup test records
        try:
            cls.db.query(Token).filter(Token.id.in_([88801, 88802, 88803])).delete(synchronize_session=False)
            cls.db.query(AdminAuditLog).filter(AdminAuditLog.target_id == "commission_percentage").delete(synchronize_session=False)
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        finally:
            cls.db.close()

    # -------------------------------------------------------------
    # RULE 1 & 4 & 7: CALCULATION ENGINE & ROUNDING (EXACT PAISA)
    # -------------------------------------------------------------
    def test_01_commission_standard_rates_reconciliation(self):
        """Test standard percentages (0%, 5%, 7.5%, 10%, 100%) and decimal rates with zero-leak reconciliation."""
        test_matrix = [
            # (amount, percentage, expected_commission, expected_hospital)
            ("100.00", "0.00", Decimal("0.00"), Decimal("100.00")),
            ("500.00", "5.00", Decimal("25.00"), Decimal("475.00")),
            ("1000.00", "7.50", Decimal("75.00"), Decimal("925.00")),
            ("250.00", "10.00", Decimal("25.00"), Decimal("225.00")),
            ("500.00", "100.00", Decimal("500.00"), Decimal("0.00")),
            ("1200.00", "2.50", Decimal("30.00"), Decimal("1170.00")),
            ("1500.00", "5.75", Decimal("86.25"), Decimal("1413.75")),
            ("800.00", "10.25", Decimal("82.00"), Decimal("718.00")),
        ]

        for amt, pct, exp_comm, exp_hosp in test_matrix:
            result = calculate_commission(amt, pct, is_eligible=True)
            self.assertEqual(result["commission_amount"], exp_comm)
            self.assertEqual(result["hospital_amount"], exp_hosp)
            # Mathematical exact reconciliation
            self.assertEqual(
                result["commission_amount"] + result["hospital_amount"],
                Decimal(amt),
                f"Reconciliation failed for amount {amt} at {pct}%",
            )

    def test_02_fractional_paisa_round_half_up(self):
        """Test fractional paisa amounts and verify ROUND_HALF_UP behavior."""
        # Case A: 10.33 at 7.5% -> 10.33 * 0.075 = 0.77475 -> 0.77 (4 < 5 rounds down)
        res_a = calculate_commission("10.33", "7.5", is_eligible=True)
        self.assertEqual(res_a["commission_amount"], Decimal("0.77"))
        self.assertEqual(res_a["hospital_amount"], Decimal("9.56"))
        self.assertEqual(res_a["commission_amount"] + res_a["hospital_amount"], Decimal("10.33"))

        # Case B: 10.35 at 7.5% -> 10.35 * 0.075 = 0.77625 -> 0.78 (6 >= 5 rounds up)
        res_b = calculate_commission("10.35", "7.5", is_eligible=True)
        self.assertEqual(res_b["commission_amount"], Decimal("0.78"))
        self.assertEqual(res_b["hospital_amount"], Decimal("9.57"))
        self.assertEqual(res_b["commission_amount"] + res_b["hospital_amount"], Decimal("10.35"))

        # Case C: 1.00 at 2.5% -> 1.00 * 0.025 = 0.025 -> 0.03 (exact half rounds up)
        res_c = calculate_commission("1.00", "2.5", is_eligible=True)
        self.assertEqual(res_c["commission_amount"], Decimal("0.03"))
        self.assertEqual(res_c["hospital_amount"], Decimal("0.97"))
        self.assertEqual(res_c["commission_amount"] + res_c["hospital_amount"], Decimal("1.00"))

        # Case D: Large amount with odd fractional paisa
        res_d = calculate_commission("78912.43", "8.33", is_eligible=True)
        self.assertEqual(
            res_d["commission_amount"] + res_d["hospital_amount"],
            Decimal("78912.43"),
        )

    def test_03_ineligible_bookings_yield_zero_commission(self):
        """Cancelled, failed, unpaid, and refunded bookings must yield zero commission."""
        amounts = ["0.00", "50.00", "500.00", "1500.00"]
        for amt in amounts:
            res = calculate_commission(amt, "10.00", is_eligible=False)
            self.assertEqual(res["commission_amount"], Decimal("0.00"))
            self.assertEqual(res["hospital_amount"], Decimal("0.00"))

    # -------------------------------------------------------------
    # RULE 1 & 6: VALIDATION & ERROR HANDLING
    # -------------------------------------------------------------
    def test_04_invalid_percentages_rejected(self):
        """Rejects negative, >100%, and non-numeric values before calculation."""
        invalid_rates = ["-5.00", "-0.01", "100.01", "150.00", "abc", "NaN", "Infinity"]
        for rate in invalid_rates:
            with self.assertRaises(ValueError):
                calculate_commission("500.00", rate, is_eligible=True)

    # -------------------------------------------------------------
    # RULE 2: ADMIN VALIDATION & AUTHORIZATION AUDIT
    # -------------------------------------------------------------
    def test_05_admin_can_read_commission_settings(self):
        """Only CarePath admin can read commission settings."""
        # Unauthenticated request rejected
        resp_unauth = self.client.get("/admin/commission")
        self.assertEqual(resp_unauth.status_code, 401)

        # Patient request rejected
        resp_patient = self.client.get(
            "/admin/commission",
            headers={"Authorization": f"Bearer {self.patient_token}"},
        )
        self.assertEqual(resp_patient.status_code, 403)

        # Hospital request rejected
        resp_hosp = self.client.get(
            "/admin/commission",
            headers={"Authorization": f"Bearer {self.hospital_token}"},
        )
        self.assertEqual(resp_hosp.status_code, 403)

        # Admin request succeeds
        resp_admin = self.client.get(
            "/admin/commission",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp_admin.status_code, 200)
        data = resp_admin.json()
        self.assertTrue(data["success"])
        self.assertIn("commission_percentage", data)

    def test_06_update_commission_requires_confirmation(self):
        """Updating commission percentage requires explicit admin confirmation (confirmed=True)."""
        payload = {"commission_percentage": 12.5, "confirmed": False}
        resp = self.client.put(
            "/admin/commission",
            json=payload,
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("confirmation is required", resp.json()["detail"].lower())

    def test_07_update_commission_validates_range(self):
        """API rejects negative, >100%, empty, and non-numeric percentages."""
        # Negative percentage rejected
        r1 = self.client.put(
            "/admin/commission",
            json={"commission_percentage": -5.0, "confirmed": True},
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(r1.status_code, 400)
        self.assertIn("negative", r1.json()["detail"].lower())

        # Percentage > 100 rejected
        r2 = self.client.put(
            "/admin/commission",
            json={"commission_percentage": 105.0, "confirmed": True},
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(r2.status_code, 400)
        self.assertIn("cannot exceed 100", r2.json()["detail"].lower())

        # Empty string rejected
        r3 = self.client.put(
            "/admin/commission",
            json={"commission_percentage": "", "confirmed": True},
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(r3.status_code, 400)

        # Invalid text rejected
        r4 = self.client.put(
            "/admin/commission",
            json={"commission_percentage": "invalid_text", "confirmed": True},
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(r4.status_code, 400)

    def test_08_admin_can_update_commission_with_audit_log(self):
        """Admin updating commission succeeds, writes audit log, and records timestamp."""
        new_rate = 7.50
        resp = self.client.put(
            "/admin/commission",
            json={"commission_percentage": new_rate, "confirmed": True},
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["commission_percentage"], 7.50)

        # Check Audit Log in DB
        audit_log = (
            self.db.query(AdminAuditLog)
            .filter(
                AdminAuditLog.action == "UPDATE_COMMISSION",
                AdminAuditLog.target_id == "commission_percentage",
            )
            .order_by(AdminAuditLog.created_at.desc())
            .first()
        )
        self.assertIsNotNone(audit_log)
        self.assertIn("7.5", audit_log.details)

    # -------------------------------------------------------------
    # RULE 5: HISTORICAL TRANSACTION PROTECTION
    # -------------------------------------------------------------
    def test_09_historical_transaction_protection(self):
        """
        Verify that changing the admin commission percentage does NOT retroactively
        change existing transaction commissions in the ledger.
        """
        # Step 1: Clean up any old test token and create Token with 10% commission on ₹500 OPD fee
        self.db.query(Token).filter(Token.id == 88801).delete(synchronize_session=False)
        self.db.commit()

        # Find any existing hospital or use dummy
        hosp = self.db.query(Hospital).first()
        hosp_id = hosp.id if hosp else 1
        hosp_name = hosp.name if hosp else "Test Hospital"

        token_1 = Token(
            id=88801,
            patient_id=999902,
            patient_name="Rajesh Patient",
            hospital=hosp_name,
            hospital_id=hosp_id,
            department="General",
            doctor="Dr. Test",
            token_number=999,
            appointment_date=date(2026, 11, 20),
            token_fee=500,
            platform_fee=10,
            total_amount=510,
            payment_status="paid",
            status="completed",
            commission_percentage=Decimal("10.00"),
            commission_amount=Decimal("50.00"),
            hospital_amount=Decimal("450.00"),
        )
        self.db.add(token_1)
        self.db.commit()

        # Step 2: Admin changes commission percentage to 25%
        resp_update = self.client.put(
            "/admin/commission",
            json={"commission_percentage": 25.00, "confirmed": True},
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp_update.status_code, 200)

        # Step 3: Fetch Admin Ledger
        resp_ledger = self.client.get(
            "/admin/ledger",
            headers={"Authorization": f"Bearer {self.admin_token}"},
        )
        self.assertEqual(resp_ledger.status_code, 200)
        ledger_data = resp_ledger.json()["ledger"]

        hosp_ledger = next((h for h in ledger_data if h["hospital_id"] == hosp_id), None)
        self.assertIsNotNone(hosp_ledger)

        # Token 88801 stored commission must remain ₹50.00 (NOT recomputed as ₹125.00!)
        token_in_db = self.db.query(Token).filter(Token.id == 88801).first()
        self.assertEqual(token_in_db.commission_amount, Decimal("50.00"))
        self.assertEqual(token_in_db.hospital_amount, Decimal("450.00"))
        self.assertEqual(token_in_db.commission_percentage, Decimal("10.00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
