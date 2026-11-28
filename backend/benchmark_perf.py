"""
Zero-Wait Performance Benchmark Suite for Q-Arovia Hospital Application
Measures latency and response times for core Hospital App endpoints.
"""
import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from fastapi.testclient import TestClient
from database import SessionLocal
from models import Hospital
from main import app, create_access_token

def run_benchmarks():
    client = TestClient(app, raise_server_exceptions=False)
    db = SessionLocal()
    
    try:
        hospital = db.query(Hospital).first()
        if not hospital:
            print("No hospital found in database!")
            return
        
        hospital_id = hospital.id
        print(f"Testing with Hospital ID: {hospital_id} ({hospital.name})")
        
        token = create_access_token(user_id=hospital_id, role="hospital")
        headers = {"Authorization": f"Bearer {token}"}
        
        endpoints = [
            ("GET Doctors (deferred photo)", f"/hospitals/{hospital_id}/doctors", headers),
            ("GET Live Queue", f"/hospitals/{hospital_id}/live-queue", headers),
            ("GET Tokens (Scoped today)", f"/hospitals/{hospital_id}/tokens?date=2026-11-28", headers),
            ("GET Collection Summary (Bounded)", f"/hospitals/{hospital_id}/collection-summary", headers),
        ]
        
        print("\n========================================================")
        print("   Q-AROVIA ZERO-WAIT HOSPITAL APP LATENCY BENCHMARK    ")
        print("========================================================")
        for name, path, hdrs in endpoints:
            latencies = []
            status_codes = []
            # Warmup
            res = client.get(path, headers=hdrs)
            status_codes.append(res.status_code)
            
            # 5 iterations
            for _ in range(5):
                t0 = time.perf_counter()
                r = client.get(path, headers=hdrs)
                t1 = time.perf_counter()
                latencies.append((t1 - t0) * 1000)
                status_codes.append(r.status_code)
                
            avg_lat = sum(latencies) / len(latencies)
            min_lat = min(latencies)
            max_lat = max(latencies)
            print(f"[{status_codes[0]}] {name:<35}: Avg={avg_lat:6.2f}ms | Min={min_lat:6.2f}ms | Max={max_lat:6.2f}ms")
        print("========================================================\n")
    finally:
        db.close()

if __name__ == "__main__":
    run_benchmarks()
