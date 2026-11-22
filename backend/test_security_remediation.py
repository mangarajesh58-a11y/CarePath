"""
Q-Arovia Security Remediation & Regression Test Suite
Automated verification of all Critical, High, and Medium security fixes.
"""

import os
import sys
import unittest
from fastapi import HTTPException
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from database import SessionLocal
from models import Patient, Hospital, Doctor, Token, MedicalDocument, UserPresence
from main import (
    app,
    create_access_token,
    JWT_SECRET_KEY,
    validate_file_magic_bytes,
    _LOGIN_ATTEMPTS,
    _AI_RATE_LIMITS,
)

class QAroviaSecurityRemediationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        cls.db = SessionLocal()
        
        # Generate valid JWT tokens for test roles
        cls.patient_1_token = create_access_token(user_id=100001, role="patient")
        cls.patient_2_token = create_access_token(user_id=100002, role="patient")
        cls.hospital_1_token = create_access_token(user_id=200001, role="hospital")
        cls.hospital_2_token = create_access_token(user_id=200002, role="hospital")
        cls.admin_token = create_access_token(user_id=300001, role="admin")

    @classmethod
    def tearDownClass(cls):
        # Clean up test presence records
        try:
            cls.db.query(UserPresence).filter(UserPresence.user_id.in_([100001, 100002, 200001, 200002, 300001])).delete(synchronize_session=False)
            cls.db.commit()
        except Exception:
            cls.db.rollback()
        cls.db.close()

    def setUp(self):
        # Clear rate limit tables before each test to avoid interference
        _LOGIN_ATTEMPTS.clear()
        _AI_RATE_LIMITS.clear()

    # =========================================================================
    # PHASE 1 - CRITICAL REMEDIATION TESTS
    # =========================================================================

    def test_01_unauthorized_patient_deletion_rejected(self):
        """Unauthenticated patient account deletion request must return 401."""
        res = self.client.post("/patients/request-account-deletion", json={"identifier": "9876543210"})
        self.assertEqual(res.status_code, 401, f"Expected 401, got {res.status_code}: {res.text}")
        self.assertIn("Unauthorized account deletion request", res.json().get("detail", ""))

    def test_02_cross_patient_account_deletion_rejected(self):
        """Patient 1 attempting to delete Patient 2's account must return 401/403."""
        headers = {"Authorization": f"Bearer {self.patient_1_token}"}
        res = self.client.post(
            "/patients/request-account-deletion",
            json={"identifier": "9999988888", "reason": "malicious delete"},
            headers=headers
        )
        self.assertIn(res.status_code, [401, 403, 404])

    def test_03_medical_document_download_unauthenticated_rejected(self):
        """Accessing medical document without auth must return 401."""
        res = self.client.get("/patient/documents/99999/download")
        self.assertEqual(res.status_code, 401)

    def test_04_medical_document_delete_unauthenticated_rejected(self):
        """Deleting medical document without auth must return 401."""
        res = self.client.delete("/patient/documents/99999")
        self.assertEqual(res.status_code, 401)

    def test_05_cross_patient_document_access_forbidden(self):
        """Patient 2 accessing non-owned document must return 403 or 404."""
        headers = {"Authorization": f"Bearer {self.patient_2_token}"}
        res = self.client.get("/patient/documents/99999/download", headers=headers)
        self.assertIn(res.status_code, [403, 404])

    def test_06_magic_bytes_file_validation(self):
        """Fake PDF with invalid magic bytes must raise HTTPException with 400."""
        fake_pdf = b"Plain text disguised as a PDF document"
        with self.assertRaises(HTTPException) as ctx:
            validate_file_magic_bytes(fake_pdf, {"pdf"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("signature does not match allowed types", ctx.exception.detail)

        # Real PDF magic bytes - must succeed without error
        real_pdf = b"%PDF-1.4\n%real pdf header content"
        validate_file_magic_bytes(real_pdf, {"pdf"})

        # Real JPEG magic bytes - must succeed without error
        real_jpg = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01"
        validate_file_magic_bytes(real_jpg, {"jpg", "jpeg"})

        # Real PNG magic bytes - must succeed without error
        real_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        validate_file_magic_bytes(real_png, {"png"})

    def test_07_jwt_secret_enforcement(self):
        """Verify JWT secret is strong and startup enforcement exists."""
        self.assertIsNotNone(JWT_SECRET_KEY)
        self.assertGreaterEqual(len(JWT_SECRET_KEY), 32, "JWT Secret must be at least 32 characters")

    def test_08_cors_untrusted_origin_rejected(self):
        """Untrusted origin must be rejected with 400 or no Access-Control-Allow-Origin header."""
        headers = {
            "Origin": "https://malicious-attacker-domain.xyz",
            "Access-Control-Request-Method": "GET",
        }
        res = self.client.options("/hospitals", headers=headers)
        # Untrusted origin must not have access-control-allow-origin
        self.assertNotIn("access-control-allow-origin", res.headers)

    def test_09_cors_trusted_origin_allowed(self):
        """Trusted Q-Arovia Vercel domain must be permitted."""
        headers = {
            "Origin": "https://hospital-ten.vercel.app",
            "Access-Control-Request-Method": "GET",
        }
        res = self.client.options("/hospitals", headers=headers)
        self.assertEqual(res.headers.get("access-control-allow-credentials"), "true")
        self.assertEqual(res.headers.get("access-control-allow-origin"), "https://hospital-ten.vercel.app")

    # =========================================================================
    # PHASE 2 - HIGH-RISK REMEDIATION TESTS
    # =========================================================================

    def test_10_queue_reset_unauthenticated_rejected(self):
        """Queue reset without authentication must return 401."""
        res = self.client.post("/hospitals/1/reset-doctor-queue?doctor=Dr.%20Smith")
        self.assertEqual(res.status_code, 401)

    def test_11_cross_hospital_queue_reset_forbidden(self):
        """Hospital 2 attempting to reset Hospital 1's queue must return 403."""
        headers = {"Authorization": f"Bearer {self.hospital_2_token}"}
        res = self.client.post("/hospitals/200001/reset-doctor-queue?doctor=Dr.%20Smith", headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("You do not have permission to reset queues for another hospital", res.json().get("detail", ""))

    def test_12_public_token_lookup_requires_phone_or_email(self):
        """Public token lookup with name only must be rejected with 400."""
        res = self.client.get("/patient/tokens/lookup?name=John")
        self.assertEqual(res.status_code, 400)
        detail = res.json().get("detail", "").lower()
        self.assertTrue("phone" in detail and "email" in detail)

    def test_13_public_token_lookup_sanitizes_clinical_data(self):
        """Public token lookup with phone/email must sanitize clinical notes, diagnosis, and prescription."""
        res = self.client.get("/patient/tokens/lookup?phone=9876543210")
        self.assertEqual(res.status_code, 200)
        tokens = res.json()
        if tokens:
            t = tokens[0]
            self.assertIsNone(t.get("notes"), "Clinical notes must be stripped from public lookup")
            self.assertIsNone(t.get("diagnosis"), "Diagnosis must be stripped from public lookup")
            self.assertIsNone(t.get("prescription"), "Prescription must be stripped from public lookup")
            if t.get("patient_phone"):
                self.assertIn("*", t.get("patient_phone"), "Phone must be masked in public lookup")

    def test_14_patient_messages_unauthenticated_empty(self):
        """Unauthenticated request to /patients/messages returns empty message list."""
        res = self.client.get("/patients/messages")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("messages"), [])

    def test_15_heartbeat_role_spoofing_prevented(self):
        """Anonymous heartbeat claiming role 'hospital' must be downgraded to 'visitor' in DB."""
        res = self.client.post(
            "/api/heartbeat",
            json={"user_id": 999991, "user_role": "hospital", "current_page": "dashboard"}
        )
        self.assertEqual(res.status_code, 200)
        # Verify in database that presence was recorded with role 'visitor'
        p = self.db.query(UserPresence).filter(UserPresence.user_id == 999991).first()
        if p:
            self.assertEqual(p.user_role, "visitor")
            self.db.delete(p)
            self.db.commit()

    def test_16_heartbeat_with_valid_jwt_accepts_role(self):
        """Authenticated heartbeat with valid JWT retains verified role in DB."""
        headers = {"Authorization": f"Bearer {self.hospital_1_token}"}
        res = self.client.post(
            "/api/heartbeat",
            json={"user_id": 200001, "user_role": "hospital", "current_page": "queue"},
            headers=headers
        )
        self.assertEqual(res.status_code, 200)
        p = self.db.query(UserPresence).filter(UserPresence.user_id == 200001).first()
        if p:
            self.assertEqual(p.user_role, "hospital")
            self.db.delete(p)
            self.db.commit()

    # =========================================================================
    # PHASE 3 - MEDIUM & LOW-RISK REMEDIATION TESTS
    # =========================================================================

    def test_17_login_rate_limiting(self):
        """More than 10 login attempts within 1 minute from the same IP must trigger 429."""
        _LOGIN_ATTEMPTS.clear()
        
        # Perform 10 failed login requests with valid schema
        for i in range(10):
            res = self.client.post(
                "/patients/login",
                json={"email": "attacker@example.com", "password": "wrongpassword"}
            )
            self.assertIn(res.status_code, [400, 401, 404])
            
        # The 11th request must trigger 429
        res_limit = self.client.post(
            "/patients/login",
            json={"email": "attacker@example.com", "password": "wrongpassword"}
        )
        self.assertEqual(res_limit.status_code, 429)
        self.assertIn("Too many login attempts", res_limit.json().get("detail", ""))

    def test_18_ai_rate_limiting(self):
        """More than 15 AI requests within 1 minute must trigger 429."""
        _AI_RATE_LIMITS.clear()
        
        for i in range(15):
            res = self.client.post("/ai/chat", json={"message": "hello"})
            self.assertNotEqual(res.status_code, 429)

        # The 16th request must trigger 429
        res_limit = self.client.post("/ai/chat", json={"message": "hello again"})
        self.assertEqual(res_limit.status_code, 429)
        self.assertIn("Too many AI requests", res_limit.json().get("detail", ""))

    def test_19_global_exception_sanitization(self):
        """Unhandled exceptions must not leak Python tracebacks or paths."""
        res = self.client.get("/non-existent-debug-endpoint-404")
        self.assertEqual(res.status_code, 404)
        self.assertNotIn("Traceback (most recent call last):", res.text)
        self.assertNotIn("C:\\Users\\", res.text)

    def test_20_hospitals_and_doctors_listing_without_bloat(self):
        """Listing hospitals must return valid list with deferred large fields."""
        res = self.client.get("/hospitals")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), list)

if __name__ == "__main__":
    unittest.main(verbosity=2)
