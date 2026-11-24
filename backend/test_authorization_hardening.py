"""
Q-Arovia Healthcare Platform - Comprehensive Authorization Hardening & Negative Tests
Validates complete server-side access control, tenant isolation, role barriers, and IDOR prevention.
"""

import os
import sys
import time
import base64
import hmac
import hashlib
import json
import unittest
from datetime import datetime, timedelta
import jwt
from fastapi.testclient import TestClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from database import SessionLocal
from models import Patient, Hospital, Doctor, Token, MedicalDocument, HospitalDirectMessage, UserSession
from main import (
    app,
    create_access_token,
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    create_user_session,
    rotate_user_session,
    CASHFREE_CLIENT_SECRET,
)

class QAroviaAuthorizationHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)
        cls.db = SessionLocal()

        # Clean any old test artifacts
        cls.cleanup_test_data()

        # 1. Create Patient A & Patient B
        cls.patient_a = Patient(
            id=9901,
            full_name="Alice Anderson",
            email="alice.test@example.com",
            phone="9100000001",
            password="hashed_pw_alice",
        )
        cls.patient_b = Patient(
            id=9902,
            full_name="Bob Brown",
            email="bob.test@example.com",
            phone="9100000002",
            password="hashed_pw_bob",
        )
        cls.db.add_all([cls.patient_a, cls.patient_b])
        cls.db.commit()

        # 2. Create Hospital A & Hospital B
        cls.hospital_a = Hospital(
            id=9801,
            name="Alpha Health City",
            email="admin@alphahealth.com",
            phone="9200000001",
            city="Hyderabad",
            address="Road 1, Banjara Hills",
            approval_status="approved",
            is_published=True,
        )
        cls.hospital_b = Hospital(
            id=9802,
            name="Beta Care Hospital",
            email="admin@betacare.com",
            phone="9200000002",
            city="Bengaluru",
            address="Whitefield Main Rd",
            approval_status="approved",
            is_published=True,
        )
        cls.db.add_all([cls.hospital_a, cls.hospital_b])
        cls.db.commit()

        # 3. Create Doctors for Hospital A & Hospital B
        cls.doctor_a = Doctor(
            id=9701,
            hospital_id=cls.hospital_a.id,
            name="Dr. Alpha Specialist",
            department="Cardiology",
            token_fee=500,
            is_available=True,
        )
        cls.doctor_b = Doctor(
            id=9702,
            hospital_id=cls.hospital_b.id,
            name="Dr. Beta Specialist",
            department="Neurology",
            token_fee=600,
            is_available=True,
        )
        cls.db.add_all([cls.doctor_a, cls.doctor_b])
        cls.db.commit()

        # 4. Create Tokens
        # Token A owned by Patient A at Hospital A
        cls.token_a = Token(
            id=9601,
            token_number=1,
            patient_id=cls.patient_a.id,
            hospital_id=cls.hospital_a.id,
            doctor_id=cls.doctor_a.id,
            patient_name=cls.patient_a.full_name,
            patient_phone=cls.patient_a.phone,
            patient_email=cls.patient_a.email,
            hospital=cls.hospital_a.name,
            department="Cardiology",
            doctor=cls.doctor_a.name,
            status="waiting",
            appointment_date=datetime.utcnow().date() + timedelta(days=1),
            diagnosis="Private Cardiac Check",
            prescription="Rx Aspirin 75mg",
            notes="Confidential patient notes A",
        )
        # Token B owned by Patient B at Hospital B
        cls.token_b = Token(
            id=9602,
            token_number=1,
            patient_id=cls.patient_b.id,
            hospital_id=cls.hospital_b.id,
            doctor_id=cls.doctor_b.id,
            patient_name=cls.patient_b.full_name,
            patient_phone=cls.patient_b.phone,
            patient_email=cls.patient_b.email,
            hospital=cls.hospital_b.name,
            department="Neurology",
            doctor=cls.doctor_b.name,
            status="waiting",
            appointment_date=datetime.utcnow().date() + timedelta(days=1),
            diagnosis="Private Neuro Check",
            prescription="Rx Levetiracetam 500mg",
            notes="Confidential patient notes B",
        )
        cls.db.add_all([cls.token_a, cls.token_b])
        cls.db.commit()

        # 5. Create Medical Document for Token A
        cls.doc_a = MedicalDocument(
            id=9501,
            token_id=cls.token_a.id,
            patient_id=cls.patient_a.id,
            hospital_id=cls.hospital_a.id,
            original_filename="cardiac_ecg.pdf",
            stored_filename="test_cardiac_ecg_9901.pdf",
            file_type="application/pdf",
            file_size=1024,
        )
        # Create Medical Document for Token B
        cls.doc_b = MedicalDocument(
            id=9502,
            token_id=cls.token_b.id,
            patient_id=cls.patient_b.id,
            hospital_id=cls.hospital_b.id,
            original_filename="brain_mri.pdf",
            stored_filename="test_brain_mri_9902.pdf",
            file_type="application/pdf",
            file_size=2048,
        )
        cls.db.add_all([cls.doc_a, cls.doc_b])
        cls.db.commit()

        # 6. Messages
        cls.inquiry_for_hospital_a = HospitalDirectMessage(
            id=9401,
            hospital_id=cls.hospital_a.id,
            sender_role="patient",
            sender_name="Alice",
            patient_phone=cls.patient_a.phone,
            patient_id=cls.patient_a.id,
            subject="Question for Hospital A",
            message="What is the visiting hour?",
            priority="normal",
            is_read=False,
            created_at=datetime.utcnow(),
        )
        cls.inquiry_for_hospital_b = HospitalDirectMessage(
            id=9402,
            hospital_id=cls.hospital_b.id,
            sender_role="patient",
            sender_name="Bob",
            patient_phone=cls.patient_b.phone,
            patient_id=cls.patient_b.id,
            subject="Question for Hospital B",
            message="Is wheelchair available?",
            priority="normal",
            is_read=False,
            created_at=datetime.utcnow(),
        )
        cls.db.add_all([cls.inquiry_for_hospital_a, cls.inquiry_for_hospital_b])
        cls.db.commit()

        # Generate JWT access tokens
        cls.token_patient_a = create_access_token(user_id=cls.patient_a.id, role="patient")
        cls.token_patient_b = create_access_token(user_id=cls.patient_b.id, role="patient")
        cls.token_hospital_a = create_access_token(user_id=cls.hospital_a.id, role="hospital")
        cls.token_hospital_b = create_access_token(user_id=cls.hospital_b.id, role="hospital")
        cls.token_admin = create_access_token(user_id=1, role="admin")

    @classmethod
    def tearDownClass(cls):
        cls.cleanup_test_data()
        cls.db.close()

    @classmethod
    def cleanup_test_data(cls):
        try:
            cls.db.query(MedicalDocument).filter(MedicalDocument.id.in_([9501, 9502])).delete(synchronize_session=False)
            cls.db.query(HospitalDirectMessage).filter(HospitalDirectMessage.id.in_([9401, 9402])).delete(synchronize_session=False)
            cls.db.query(Token).filter(Token.id.in_([9601, 9602])).delete(synchronize_session=False)
            cls.db.query(Doctor).filter(Doctor.id.in_([9701, 9702])).delete(synchronize_session=False)
            cls.db.query(Hospital).filter(Hospital.id.in_([9801, 9802])).delete(synchronize_session=False)
            cls.db.query(Patient).filter(Patient.id.in_([9901, 9902])).delete(synchronize_session=False)
            cls.db.query(UserSession).filter(UserSession.user_id.in_([9901, 9902, 9801, 9802])).delete(synchronize_session=False)
            cls.db.commit()
        except Exception:
            cls.db.rollback()

    # =========================================================================
    # A. AUTHENTICATION TESTS
    # =========================================================================

    def test_a1_missing_token_returns_401(self):
        resp = self.client.get("/patients/me")
        self.assertEqual(resp.status_code, 401)

    def test_a2_invalid_token_returns_401(self):
        resp = self.client.get("/patients/me", headers={"Authorization": "Bearer invalid_gibberish_token"})
        self.assertEqual(resp.status_code, 401)

    def test_a3_expired_token_returns_401(self):
        # Create a token expired 1 hour ago
        expired_payload = {
            "sub": str(self.patient_a.id),
            "role": "patient",
            "exp": datetime.utcnow() - timedelta(hours=1),
        }
        expired_token = jwt.encode(expired_payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        resp = self.client.get("/patients/me", headers={"Authorization": f"Bearer {expired_token}"})
        self.assertEqual(resp.status_code, 401)

    def test_a4_tampered_jwt_signature_returns_401(self):
        # Signed with a different secret
        tampered_token = jwt.encode({"sub": str(self.patient_a.id), "role": "patient"}, "WRONG_SECRET_KEY_12345", algorithm=JWT_ALGORITHM)
        resp = self.client.get("/patients/me", headers={"Authorization": f"Bearer {tampered_token}"})
        self.assertEqual(resp.status_code, 401)

    def test_a5_refresh_token_reuse_revokes_all_sessions(self):
        # Create session
        access, refresh, sess = create_user_session(self.db, user_id=self.patient_a.id, role="patient")
        # First rotation succeeds
        new_acc, new_ref = rotate_user_session(self.db, refresh)
        self.assertTrue(new_acc)
        self.assertTrue(new_ref)

        # Re-using the consumed refresh token triggers reuse detection
        resp = self.client.post("/auth/refresh", json={"refresh_token": refresh})
        self.assertEqual(resp.status_code, 401)
        self.assertIn("reuse detected", resp.json().get("detail", "").lower())

    # =========================================================================
    # B. ROLE & PRIVILEGE BOUNDARY TESTS
    # =========================================================================

    def test_b1_patient_accessing_hospital_endpoint_returns_403(self):
        resp = self.client.get("/hospital/tokens", headers={"Authorization": f"Bearer {self.token_patient_a}"})
        self.assertEqual(resp.status_code, 403)

    def test_b2_patient_accessing_admin_endpoint_returns_403(self):
        resp = self.client.get("/admin/ledger", headers={"Authorization": f"Bearer {self.token_patient_a}"})
        self.assertEqual(resp.status_code, 403)

    def test_b3_hospital_accessing_admin_endpoint_returns_403(self):
        resp = self.client.get("/admin/ledger", headers={"Authorization": f"Bearer {self.token_hospital_a}"})
        self.assertEqual(resp.status_code, 403)

    def test_b4_role_elevation_attempt_in_jwt_is_rejected(self):
        # Patient attempts to forge admin claim in JWT without valid key
        forged_admin = jwt.encode({"sub": str(self.patient_a.id), "role": "admin"}, "attacker_key", algorithm=JWT_ALGORITHM)
        resp = self.client.get("/admin/ledger", headers={"Authorization": f"Bearer {forged_admin}"})
        self.assertEqual(resp.status_code, 401)

    # =========================================================================
    # C. IDOR & PATIENT ISOLATION TESTS
    # =========================================================================

    def test_c1_patient_a_cannot_view_patient_b_single_token(self):
        # Patient A queries Token B
        resp = self.client.get(f"/patient/tokens/{self.token_b.id}", headers={"Authorization": f"Bearer {self.token_patient_a}"})
        self.assertEqual(resp.status_code, 403)

    def test_c2_patient_a_cannot_query_patient_b_tokens_via_query_params(self):
        # Patient A provides Patient B's email or phone in query parameter
        resp = self.client.get(
            f"/patient/tokens?email={self.patient_b.email}&phone={self.patient_b.phone}",
            headers={"Authorization": f"Bearer {self.token_patient_a}"}
        )
        self.assertEqual(resp.status_code, 200)
        tokens = resp.json()
        # Must NOT return Token B!
        token_ids = [t["id"] for t in tokens]
        self.assertNotIn(self.token_b.id, token_ids)

    def test_c3_patient_a_cannot_cancel_patient_b_appointment(self):
        # Patient A attempts to cancel Token B
        resp = self.client.post(
            f"/patient/tokens/{self.token_b.id}/cancel",
            headers={"Authorization": f"Bearer {self.token_patient_a}"}
        )
        self.assertEqual(resp.status_code, 403)
        # Token B remains untouched
        self.db.refresh(self.token_b)
        self.assertEqual(self.token_b.status, "waiting")

    def test_c4_unauthenticated_token_lookup_cannot_enumerate_patient_id(self):
        # Unauthenticated attacker queries by patient_id only
        resp = self.client.get(f"/patient/tokens/lookup?patient_id={self.patient_a.id}")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("phone number or email address is required", resp.json().get("detail", "").lower())

    def test_c5_unauthenticated_token_lookup_strips_clinical_details(self):
        # Unauthenticated lookup with valid phone
        resp = self.client.get(f"/patient/tokens/lookup?phone={self.patient_a.phone}")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()
        if items:
            for item in items:
                self.assertNotIn("diagnosis", item)
                self.assertNotIn("prescription", item)
                self.assertNotIn("notes", item)
                # Phone masked
                self.assertIn("****", item.get("patient_phone", ""))

    # =========================================================================
    # D. HOSPITAL MULTI-TENANT ISOLATION TESTS
    # =========================================================================

    def test_d1_hospital_a_cannot_access_hospital_b_tokens(self):
        resp = self.client.get(f"/hospitals/{self.hospital_b.id}/tokens", headers={"Authorization": f"Bearer {self.token_hospital_a}"})
        self.assertEqual(resp.status_code, 403)

    def test_d2_hospital_a_cannot_modify_hospital_b_doctor(self):
        resp = self.client.patch(
            f"/doctors/{self.doctor_b.id}",
            json={"name": "Hacked Doctor Name"},
            headers={"Authorization": f"Bearer {self.token_hospital_a}"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_d3_hospital_a_cannot_delete_hospital_b_doctor(self):
        resp = self.client.delete(f"/doctors/{self.doctor_b.id}", headers={"Authorization": f"Bearer {self.token_hospital_a}"})
        self.assertEqual(resp.status_code, 403)

    def test_d4_hospital_a_cannot_update_hospital_b_profile(self):
        resp = self.client.put(
            f"/hospitals/{self.hospital_b.id}",
            json={"phone": "9999999999"},
            headers={"Authorization": f"Bearer {self.token_hospital_a}"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_d5_hospital_a_cannot_call_or_complete_hospital_b_token(self):
        resp = self.client.put(f"/tokens/{self.token_b.id}/call", headers={"Authorization": f"Bearer {self.token_hospital_a}"})
        self.assertIn(resp.status_code, [403, 404])
        resp_comp = self.client.put(f"/tokens/{self.token_b.id}/complete", headers={"Authorization": f"Bearer {self.token_hospital_a}"})
        self.assertIn(resp_comp.status_code, [403, 404])

    # =========================================================================
    # E. MEDICAL DOCUMENTS AUTHORIZATION TESTS
    # =========================================================================

    def test_e1_patient_a_cannot_download_patient_b_medical_document(self):
        resp = self.client.get(
            f"/patient/documents/{self.doc_b.id}/download",
            headers={"Authorization": f"Bearer {self.token_patient_a}"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_e2_patient_a_cannot_delete_patient_b_medical_document(self):
        resp = self.client.delete(
            f"/patient/documents/{self.doc_b.id}",
            headers={"Authorization": f"Bearer {self.token_patient_a}"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_e3_hospital_a_cannot_access_hospital_b_patient_document(self):
        resp = self.client.get(
            f"/patient/documents/{self.doc_b.id}/download",
            headers={"Authorization": f"Bearer {self.token_hospital_a}"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_e4_batch_documents_unauthenticated_returns_401(self):
        resp = self.client.get(f"/patient/tokens-documents-batch?token_ids={self.token_a.id}")
        self.assertEqual(resp.status_code, 401)

    def test_e5_batch_documents_patient_a_cannot_retrieve_patient_b_docs(self):
        # Patient A requests batch with both Token A and Token B
        resp = self.client.get(
            f"/patient/tokens-documents-batch?token_ids={self.token_a.id},{self.token_b.id}",
            headers={"Authorization": f"Bearer {self.token_patient_a}"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json().get("documents_by_token", {})
        # Must contain Token A, must NOT contain Token B
        self.assertIn(str(self.token_a.id), data)
        self.assertNotIn(str(self.token_b.id), data)

    # =========================================================================
    # F. PAYMENT WEBHOOK SECURITY TESTS
    # =========================================================================

    def test_f1_cashfree_webhook_missing_signature_returns_401(self):
        resp = self.client.post("/payments/cashfree-webhook", json={"event": "TEST"})
        self.assertEqual(resp.status_code, 401)

    def test_f2_cashfree_webhook_expired_timestamp_returns_400(self):
        # Timestamp older than 300 seconds
        old_ts = str(time.time() - 400)
        resp = self.client.post(
            "/payments/cashfree-webhook",
            json={"event": "TEST"},
            headers={"x-webhook-signature": "dummy_sig", "x-webhook-timestamp": old_ts}
        )
        self.assertEqual(resp.status_code, 400)

    def test_f3_cashfree_webhook_invalid_signature_returns_400(self):
        now_ts = str(time.time())
        resp = self.client.post(
            "/payments/cashfree-webhook",
            content=b'{"event":"TEST"}',
            headers={"x-webhook-signature": "invalid_hmac_sig", "x-webhook-timestamp": now_ts}
        )
        self.assertEqual(resp.status_code, 400)

    def test_f4_cashfree_webhook_valid_signature_accepted(self):
        now_ts = str(time.time())
        body = json.dumps({
            "type": "PAYMENT_SUCCESS_WEBHOOK",
            "data": {
                "order": {"order_id": "test_order_9999"},
                "payment": {"cf_payment_id": "cf_test_9999", "payment_status": "SUCCESS"}
            }
        }).encode("utf-8")

        # Generate HMAC-SHA256 signature using server secret
        data_to_sign = now_ts.encode("utf-8") + body
        sig_bytes = hmac.new(CASHFREE_CLIENT_SECRET.encode("utf-8"), data_to_sign, hashlib.sha256).digest()
        sig = base64.b64encode(sig_bytes).decode("utf-8")

        resp = self.client.post(
            "/payments/cashfree-webhook",
            content=body,
            headers={
                "x-webhook-signature": sig,
                "x-webhook-timestamp": now_ts,
                "content-type": "application/json"
            }
        )
        self.assertEqual(resp.status_code, 200)

    # =========================================================================
    # G. MESSAGING & INQUIRY AUTHORIZATION TESTS
    # =========================================================================

    def test_g1_unauthenticated_mark_messages_read_by_id_returns_401(self):
        resp = self.client.post("/patients/messages/mark-read", json={"message_ids": [self.inquiry_for_hospital_a.id]})
        self.assertEqual(resp.status_code, 401)

    def test_g2_patient_a_cannot_mark_patient_b_messages_read(self):
        # Patient A provides Patient B's phone
        resp = self.client.post(
            "/patients/messages/mark-read",
            json={"phone": self.patient_b.phone},
            headers={"Authorization": f"Bearer {self.token_patient_a}"}
        )
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
