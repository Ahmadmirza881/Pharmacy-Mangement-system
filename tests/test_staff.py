"""
Unit Tests for Sub-Plan 1: Staff Profiling & Management
Tests:
- Staff creation with complete profile (CNIC, Address, Designation, Salary, Joining Date)
- Staff search filter
- Staff profile updates (Edit)
- Staff deactivation (Delete)
- Complete Staff History dossier retrieval
"""

import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app
from database import init_db

class TestStaffManagement(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def test_01_create_staff_full_profile(self):
        payload = {
            "name": "Kashif Mahmood",
            "phone": "0301-9988776",
            "cnic": "35201-1234567-9",
            "address": "Street 5, Allama Iqbal Town, Lahore",
            "designation": "Assistant Pharmacist",
            "monthly_salary": 38000.0,
            "joining_date": "2026-03-01",
            "shift_id": 1,
            "fingerprint_id": "FP_KASHIF_004"
        }
        res = self.client.post("/api/staff", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn("staff_id", data)
        TestStaffManagement.created_staff_id = data["staff_id"]

    def test_02_search_staff(self):
        # Search by name
        res = self.client.get("/api/staff?search=Kashif")
        self.assertEqual(res.status_code, 200)
        staff_list = res.json()
        self.assertTrue(any(s["name"] == "Kashif Mahmood" for s in staff_list))

        # Search by CNIC
        res_cnic = self.client.get("/api/staff?search=35201-1234567-9")
        self.assertEqual(res_cnic.status_code, 200)
        staff_list_cnic = res_cnic.json()
        self.assertEqual(len(staff_list_cnic), 1)
        self.assertEqual(staff_list_cnic[0]["name"], "Kashif Mahmood")
        self.assertEqual(staff_list_cnic[0]["address"], "Street 5, Allama Iqbal Town, Lahore")
        self.assertEqual(staff_list_cnic[0]["designation"], "Assistant Pharmacist")

    def test_03_update_staff_profile(self):
        staff_id = TestStaffManagement.created_staff_id
        update_payload = {
            "designation": "Lead Pharmacist",
            "monthly_salary": 42000.0,
            "address": "Apartment 4B, Gulberg III, Lahore"
        }
        res = self.client.put(f"/api/staff/{staff_id}", json=update_payload)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # Verify updated values
        res_get = self.client.get("/api/staff")
        updated_staff = next(s for s in res_get.json() if s["id"] == staff_id)
        self.assertEqual(updated_staff["designation"], "Lead Pharmacist")
        self.assertEqual(updated_staff["monthly_salary"], 42000.0)
        self.assertEqual(updated_staff["address"], "Apartment 4B, Gulberg III, Lahore")

    def test_04_get_staff_history(self):
        staff_id = TestStaffManagement.created_staff_id
        res = self.client.get(f"/api/staff/{staff_id}/history")
        self.assertEqual(res.status_code, 200)
        history = res.json()
        self.assertIn("profile", history)
        self.assertEqual(history["profile"]["name"], "Kashif Mahmood")
        self.assertIn("attendance", history)
        self.assertIn("leaves", history)
        self.assertIn("advances", history)
        self.assertIn("total_present_days", history)
        self.assertIn("unsettled_advances", history)

    def test_05_delete_staff(self):
        staff_id = TestStaffManagement.created_staff_id
        res = self.client.delete(f"/api/staff/{staff_id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # Verify staff is excluded from active list
        res_get = self.client.get("/api/staff")
        self.assertFalse(any(s["id"] == staff_id for s in res_get.json()))

if __name__ == "__main__":
    unittest.main()
