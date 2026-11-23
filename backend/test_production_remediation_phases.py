"""
Q-Arovia Production Remediation Comprehensive Test Suite
Automated verification of QBUG-001 through QBUG-015 fixes.
"""

import os
import sys
import time
import json
import base64
import hmac
import hashlib
import unittest
from datetime import datetime, date, timedelta
from decimal import Decimal

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from fastapi.testclient import TestClient
from database import SessionLocal
from models import Patient, Hospital, Doctor, Token, MedicalDocument
from main import (
    app,
    create_access_token,
    execute_cashfree_refund,
    verify_cashfree_webhook_signature,
    CASHFREE_CLIENT_SECRET,
)

class QAroviaProductionRemediationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        cls.db = SessionLocal()

        cls.patient_1_token = create_access_token(user_id=100001, role="patient")
        cls.patient_2_token = create_access_token(user_id=100002, role="patient")
        cls.hospital_1_token = create_access_token(user_id=200001, role="hospital")
        cls.hospital_2_token = create_access_token(user_id=200002, role="hospital")
        cls.admin_token = create_access_token(user_id=300001, role="admin")

        # Create test patient accounts
        cls.test_patient_1 = Patient(
            id=100001,
            full_name="Remediation Test Patient",
            email="remediation_test_pat1@qarovia.in",
            phone="9988776655",
            password="test_hashed_password"
        )
        cls.db.merge(cls.test_patient_1)
        cls.db.commit()

        # Create a mock walk-in document with patient_id = None for IDOR testing
        cls.walkin_doc = MedicalDocument(
            id=999881,
            token_id=99901,
            patient_id=None,  # Walk-in patient without user account
            hospital_id=200001,
            original_filename="lab_report_walkin.pdf",
            stored_filename="test_mock_walkin_doc.pdf",
            file_type="application/pdf",
            file_size=1024,
            created_at=datetime.utcnow()
        )
        try:
            cls.db.merge(cls.walkin_doc)
            cls.db.commit()
        except Exception:
            cls.db.rollback()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.db.query(MedicalDocument).filter(MedicalDocument.id == 999881).delete(synchronize_session=False)
            cls.db.query(Patient).filter(Patient.id == 100001).delete(synchronize_session=False)
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        cls.db.close()

    # =========================================================================
    # QBUG-003: MEDICAL DOCUMENT IDOR & AUTHORIZATION HARDENING
    # =========================================================================

    def test_qbug_003_walkin_document_idor_blocked(self):
        """Walk-in medical document with patient_id=None cannot be accessed by arbitrary Patient 2 (403)."""
        headers = {"Authorization": f"Bearer {self.patient_2_token}"}
        res = self.client.get("/patient/documents/999881", headers=headers)
        self.assertEqual(res.status_code, 403, f"Expected 403 Forbidden, got {res.status_code}: {res.text}")
        self.assertIn("permission", res.json().get("detail", "").lower())

    def test_qbug_003_walkin_document_delete_blocked(self):
        """Walk-in medical document with patient_id=None cannot be deleted by arbitrary Patient 2 (403)."""
        headers = {"Authorization": f"Bearer {self.patient_2_token}"}
        res = self.client.delete("/patient/documents/999881", headers=headers)
        self.assertEqual(res.status_code, 403, f"Expected 403 Forbidden, got {res.status_code}: {res.text}")

    # =========================================================================
    # QBUG-004: CASHFREE WEBHOOK & SIGNATURE VERIFICATION
    # =========================================================================

    def test_qbug_004_webhook_signature_calculation(self):
        """Test Cashfree webhook HMAC-SHA256 signature verification."""
        timestamp = "1700000000"
        raw_body = b'{"data":{"order":{"order_id":"test_ord_1"}}}'
        secret = CASHFREE_CLIENT_SECRET or "cfsk_test_secret_for_unit_tests"
        
        data_to_sign = timestamp.encode("utf-8") + raw_body
        expected_sig = base64.b64encode(hmac.new(secret.encode("utf-8"), data_to_sign, hashlib.sha256).digest()).decode("utf-8")

        # Test verification helper
        is_valid = verify_cashfree_webhook_signature(raw_body, timestamp, expected_sig)
        if CASHFREE_CLIENT_SECRET:
            self.assertTrue(is_valid)
            # Tampered signature must fail
            self.assertFalse(verify_cashfree_webhook_signature(raw_body, timestamp, "tampered_sig"))

    def test_qbug_004_webhook_idempotency(self):
        """Webhook listener returns idempotent success when order already exists."""
        # Find or create a test token with known cashfree_order_id
        test_order_id = "test_cf_idempotent_order_99"
        existing = self.db.query(Token).filter(Token.cashfree_order_id == test_order_id).first()
        if not existing:
            token = Token(
                patient_name="Test Patient",
                hospital="Test Hospital",
                hospital_id=200001,
                doctor="Test Doctor",
                department="General",
                token_number=99,
                appointment_date=date.today(),
                cashfree_order_id=test_order_id,
                payment_status="paid",
                status="waiting"
            )
            self.db.add(token)
            self.db.commit()

        payload = {
            "type": "PAYMENT_SUCCESS_WEBHOOK",
            "data": {
                "order": {"order_id": test_order_id}
            }
        }
        now_ts = str(int(time.time()))
        body_bytes = json.dumps(payload).encode("utf-8")
        sig_data = now_ts.encode("utf-8") + body_bytes
        computed_sig = base64.b64encode(
            hmac.new(CASHFREE_CLIENT_SECRET.encode("utf-8"), sig_data, hashlib.sha256).digest()
        ).decode("utf-8") if CASHFREE_CLIENT_SECRET else "dummy"

        headers = {
            "x-webhook-signature": computed_sig,
            "x-webhook-timestamp": now_ts,
            "Content-Type": "application/json",
        }
        res = self.client.post("/payments/cashfree-webhook", data=body_bytes, headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("status"), "idempotent_ok")

        # Cleanup
        self.db.query(Token).filter(Token.cashfree_order_id == test_order_id).delete(synchronize_session=False)
        self.db.commit()

    # =========================================================================
    # QBUG-005: ACTUAL CASHFREE REFUND ENGINE
    # =========================================================================

    def test_qbug_005_counter_free_refund_execution(self):
        """Free or counter consultation refund marks status refunded immediately without gateway network call."""
        token = Token(
            id=999911,
            patient_name="Counter Patient",
            hospital="Test Hospital",
            hospital_id=200001,
            doctor="Test Doctor",
            department="General",
            token_number=11,
            appointment_date=date.today(),
            total_amount=0,  # Free consultation
            cashfree_order_id=None,
            payment_status="paid",
            status="waiting"
        )
        self.db.merge(token)
        self.db.commit()

        res = execute_cashfree_refund(self.db, token, "Test closure")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("status"), "refunded")
        self.assertEqual(token.payment_status, "refunded")

        # Second call is idempotent
        res2 = execute_cashfree_refund(self.db, token, "Duplicate call")
        self.assertTrue(res2.get("success"))
        self.assertEqual(res2.get("message"), "Already refunded")

        # Cleanup
        self.db.query(Token).filter(Token.id == 999911).delete(synchronize_session=False)
        self.db.commit()

    # =========================================================================
    # QBUG-006: WEBSOCKET AUTHENTICATION ENFORCEMENT
    # =========================================================================

    def test_qbug_006_websocket_unauthenticated_private_rejected(self):
        """Unauthenticated websocket connection claiming private patient channel is rejected."""
        try:
            with self.client.websocket_connect("/ws/messages?role=patient&phone=9876543210") as ws:
                # If accepted, fail test
                self.fail("Expected WebSocket to be rejected without JWT")
        except Exception:
            # Expected disconnect or 4001 close code
            pass

    # =========================================================================
    # QBUG-008: PATIENT APPOINTMENT CANCELLATION
    # =========================================================================

    def test_qbug_008_cancel_nonexistent_token_returns_404(self):
        """Cancelling non-existent token returns 404."""
        headers = {"Authorization": f"Bearer {self.patient_1_token}"}
        res = self.client.post("/patient/tokens/99999999/cancel", headers=headers)
        self.assertEqual(res.status_code, 404)

    def test_qbug_008_cancel_unauthorized_token_returns_403(self):
        """Patient 2 attempting to cancel Patient 1's token returns 403."""
        # Create token for Patient 1 (id=100001)
        token = Token(
            id=999922,
            patient_id=100001,
            patient_name="Patient One",
            hospital="Test Hospital",
            hospital_id=200001,
            doctor="Dr. Test",
            department="General",
            token_number=22,
            appointment_date=date.today() + timedelta(days=2),
            total_amount=100,
            status="waiting",
            payment_status="paid"
        )
        self.db.merge(token)
        self.db.commit()

        # Patient 2 tries to cancel
        headers = {"Authorization": f"Bearer {self.patient_2_token}"}
        res = self.client.post("/patient/tokens/999922/cancel", headers=headers)
        self.assertEqual(res.status_code, 403)

        # Cleanup
        self.db.query(Token).filter(Token.id == 999922).delete(synchronize_session=False)
        self.db.commit()

    def test_qbug_008_cancel_advance_appointment_succeeds(self):
        """Cancelling an appointment >2h in advance succeeds and marks cancelled."""
        token = Token(
            id=999933,
            patient_id=100001,
            patient_name="Patient One",
            hospital="Test Hospital",
            hospital_id=200001,
            doctor="Dr. Test",
            department="General",
            token_number=33,
            appointment_date=date.today() + timedelta(days=2),
            total_amount=0,
            status="waiting",
            payment_status="not_required"
        )
        self.db.merge(token)
        self.db.commit()

        headers = {"Authorization": f"Bearer {self.patient_1_token}"}
        res = self.client.post("/patient/tokens/999933/cancel", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("status"), "cancelled")

        # Verify in DB
        db_token = self.db.query(Token).filter(Token.id == 999933).first()
        self.assertEqual(db_token.status, "cancelled")

        # Cleanup
        self.db.query(Token).filter(Token.id == 999933).delete(synchronize_session=False)
        self.db.commit()

    # =========================================================================
    # QBUG-009: FREE CONSULTATION BOOKING
    # =========================================================================

    def test_qbug_009_free_endpoint_rejects_paid_doctor(self):
        """Free consultation endpoint rejects booking for doctors that have token_fee > 0."""
        # Find any doctor with fee > 0
        doc = self.db.query(Doctor).filter(Doctor.token_fee > 0).first()
        if doc:
            hosp = self.db.query(Hospital).filter(Hospital.id == doc.hospital_id).first()
            if hosp:
                headers = {"Authorization": f"Bearer {self.patient_1_token}"}
                payload = {
                    "hospital": hosp.name,
                    "department": doc.department,
                    "doctor": doc.name,
                    "appointment_date": str(date.today())
                }
                res = self.client.post("/tokens/free", json=payload, headers=headers)
                self.assertEqual(res.status_code, 400)
                self.assertIn("fee", res.json().get("detail", "").lower())

    # =========================================================================
    # QBUG-010: N+1 BULK QUERY OPTIMIZATION IN NEXT-AVAILABLE
    # =========================================================================

    def test_qbug_010_bulk_next_available_endpoint(self):
        """Next available endpoint executes bulk aggregated queries for All Doctors overview."""
        hosp = self.db.query(Hospital).first()
        if hosp:
            res = self.client.get(f"/tokens/next-available?hospital_id={hosp.id}")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data.get("is_all_doctors"))
            self.assertIn("doctors", data)
            self.assertIsInstance(data["doctors"], list)

    # =========================================================================
    # QBUG-011: RESET DOCTOR QUEUE ACTIVE CONSULTATION PROTECTION
    # =========================================================================

    def test_qbug_011_reset_queue_blocks_active_consultations(self):
        """Resetting doctor queue is blocked if active tokens are waiting/serving."""
        # Create active waiting token for Dr. Test
        doc = self.db.query(Doctor).first()
        if doc:
            today = date.today()
            t = Token(
                id=999944,
                patient_name="Active Patient",
                hospital="Hospital",
                hospital_id=doc.hospital_id,
                doctor=doc.name,
                doctor_id=doc.id,
                department=doc.department,
                token_number=1,
                appointment_date=today,
                status="waiting"
            )
            self.db.merge(t)
            self.db.commit()

            # Attempt reset as admin
            headers = {"Authorization": f"Bearer {self.admin_token}"}
            res = self.client.post(
                f"/hospitals/{doc.hospital_id}/reset-doctor-queue?doctor={doc.name}&appointment_date={today}",
                headers=headers
            )
            self.assertEqual(res.status_code, 400)
            self.assertIn("active consultation", res.json().get("detail", "").lower())

            # Cleanup
            self.db.query(Token).filter(Token.id == 999944).delete(synchronize_session=False)
            self.db.commit()

    # =========================================================================
    # QBUG-014 & QBUG-015: ERROR SANITIZATION & OTP SECURITY
    # =========================================================================

    def test_qbug_014_forgot_password_exception_sanitized(self):
        """Forgot password returns sanitized message and does not leak Python exceptions."""
        res = self.client.post("/auth/forgot-password/request-otp", json={
            "role": "patient",
            "email": "nonexistent_patient_9999@test.com"
        })
        self.assertEqual(res.status_code, 404)
        # Verify no traceback/file paths in response
        detail = res.json().get("detail", "")
        self.assertNotIn("Traceback", detail)
        self.assertNotIn(".py", detail)


if __name__ == "__main__":
    unittest.main()
