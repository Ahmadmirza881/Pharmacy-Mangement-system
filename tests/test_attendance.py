"""
Unit Tests for Sub-Plan 2: Attendance & Shift Management
Tests:
- Punch IN / OUT
- Status classification (ON_TIME, LATE, HALF_DAY)
- Manual Admin Attendance Override (Feature 18)
- Monthly Attendance Matrix API (Feature 6)
"""

import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app
from database import init_db, get_db_connection

class TestAttendanceSubplan(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        conn = get_db_connection()
        conn.execute("DELETE FROM attendance_logs WHERE date IN ('2026-09-01', '2026-09-02')")
        conn.commit()
        conn.close()
        cls.client = TestClient(app)

    def test_01_punch_in_and_out(self):
        # Ali Raza (id=1)
        # Punch IN at 09:05 AM
        res_in = self.client.post("/api/punch", json={
            "staff_id": 1,
            "custom_time": "2026-09-01 09:05:00"
        })
        self.assertEqual(res_in.status_code, 200)
        data_in = res_in.json()
        self.assertTrue(data_in["success"])
        self.assertEqual(data_in["punch_type"], "IN")
        self.assertEqual(data_in["status"], "ON_TIME")

        # Punch OUT at 17:15 PM
        res_out = self.client.post("/api/punch", json={
            "staff_id": 1,
            "custom_time": "2026-09-01 17:15:00"
        })
        self.assertEqual(res_out.status_code, 200)
        data_out = res_out.json()
        self.assertTrue(data_out["success"])
        self.assertEqual(data_out["punch_type"], "OUT")
        self.assertGreater(data_out["worked_minutes"], 400)

    def test_02_manual_admin_override(self):
        # Admin manually overrides Bilal Ahmed (id=2) attendance for 2026-09-02
        override_payload = {
            "staff_id": 2,
            "date": "2026-09-02",
            "time_in": "09:30:00",
            "time_out": "17:00:00",
            "status": "LATE",
            "notes": "Admin manually verified late due to rain"
        }
        res = self.client.put("/api/attendance/override", json=override_payload)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # Verify in DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM attendance_logs WHERE staff_id = 2 AND date = '2026-09-02'")
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "LATE")
        self.assertEqual(row["punch_method"], "MANUAL_ADMIN")
        self.assertEqual(row["time_in"], "09:30:00")

    def test_03_monthly_attendance_matrix(self):
        res = self.client.get("/api/attendance/monthly?month=9&year=2026")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["month"], 9)
        self.assertEqual(data["days_in_month"], 30)
        self.assertIn("matrix", data)
        self.assertTrue(len(data["matrix"]) >= 2)
        
        # Ali should have 1st as ON_TIME / PRESENT
        ali_data = next((m for m in data["matrix"] if m["staff_id"] == 1), None)
        self.assertIsNotNone(ali_data)
        self.assertIn(ali_data["days"]["1"], ("ON_TIME", "PRESENT"))

if __name__ == "__main__":
    unittest.main()
