"""
Automated Verification Suite for Mumtaz Pharmacy Feature Enhancements
Tests:
1. Live Roster Today API (Present, Late, Leave, Absent metrics & active logs)
2. August 2026 Historical Payroll Calculation & Itemized Deductions
3. Advance Khata Direct Settlement API & Audit Tracking
4. September 2026 Payroll & Ledger Status
"""

import unittest
from fastapi.testclient import TestClient
from main import app
from seed_data import seed
from database import get_db_connection

class TestMumtazFeatureEnhancements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Re-seed database to pristine realistic state
        seed()
        cls.client = TestClient(app)

    def test_1_today_live_roster_metrics(self):
        """Feature 1: Verify Today's Live Roster counts and staff states."""
        res = self.client.get("/api/attendance/today")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["total_staff"], 7)
        self.assertEqual(data["present_count"], 5)
        self.assertEqual(data["late_count"], 1)
        self.assertEqual(data["leave_count"], 1)
        self.assertEqual(data["absent_count"], 1)

        # Check Bilal is Late
        bilal = next(s for s in data["roster"] if s["id"] == 2)
        self.assertEqual(bilal["status"], "LATE")
        self.assertEqual(bilal["late_minutes"], 25)

        # Check Tariq is on Leave
        tariq = next(s for s in data["roster"] if s["id"] == 6)
        self.assertEqual(tariq["status"], "LEAVE")
        self.assertIn("flu", tariq["leave_reason"].lower())

        # Check Kashif is Absent
        kashif = next(s for s in data["roster"] if s["id"] == 7)
        self.assertEqual(kashif["status"], "ABSENT")

    def test_2_august_2026_payroll_and_itemized_advances(self):
        """Feature 2: Past month (August 2026) payroll calculation with itemized deductions."""
        res = self.client.get("/api/payroll/calculate?month=8&year=2026")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        sheet = {row["staff_id"]: row for row in data["sheet"]}

        # 1. Ali Raza: Basic 45,000, 3 leaves (1 extra unpaid = 1,451.61), Adv 2,500
        ali = sheet[1]
        self.assertEqual(ali["basic_salary"], 45000.0)
        self.assertEqual(ali["extra_leaves"], 1)
        self.assertEqual(ali["extra_leave_cut"], 1451.61)
        self.assertEqual(ali["advances_deducted"], 2500.0)
        self.assertEqual(len(ali["advances_list"]), 1)
        self.assertEqual(ali["advances_list"][0]["entry_type"], "MEDICINE_CREDIT")
        self.assertEqual(ali["advances_list"][0]["amount"], 2500.0)
        self.assertEqual(ali["net_payable"], 41048.39)

        # 2. Bilal Ahmed: Basic 35,000, Adv 4,000
        bilal = sheet[2]
        self.assertEqual(bilal["advances_deducted"], 4000.0)
        self.assertEqual(len(bilal["advances_list"]), 1)
        self.assertEqual(bilal["advances_list"][0]["entry_type"], "ADVANCE")
        self.assertEqual(bilal["advances_list"][0]["amount"], 4000.0)

        # 3. Hamza Farooq: Basic 40,000, 5 half-days (1 excess = 645.16), Adv 1,800
        hamza = sheet[4]
        self.assertEqual(hamza["half_days"], 5)
        self.assertEqual(hamza["extra_half_days"], 1)
        self.assertEqual(hamza["extra_half_day_cut"], 645.16)
        self.assertEqual(hamza["advances_deducted"], 1800.0)
        self.assertEqual(hamza["net_payable"], 37554.84)

        # 4. Zainab Bibi: Basic 30,000, 3 leaves (1 extra = 967.74), Adv 2,500
        zainab = sheet[5]
        self.assertEqual(zainab["extra_leaves"], 1)
        self.assertEqual(zainab["extra_leave_cut"], 967.74)
        self.assertEqual(zainab["advances_deducted"], 2500.0)
        self.assertEqual(zainab["net_payable"], 26532.26)

        # 5. Tariq Mehmood: Basic 28,000, 7 absents = 6,322.61
        tariq = sheet[6]
        self.assertEqual(tariq["absent_days"], 7)
        self.assertEqual(tariq["absent_cut"], 6322.61)
        self.assertEqual(tariq["net_payable"], 21677.39)

    def test_3_direct_advance_settlement_and_audit(self):
        """Feature 3: Direct Settlement API with date, type, and audit notes."""
        # Find an unsettled September advance
        res = self.client.get("/api/advances")
        advances = res.json()
        unsettled = [a for a in advances if a["is_settled"] == 0]
        self.assertGreater(len(unsettled), 0)

        target = unsettled[0]
        target_id = target["id"]

        # Settle it via Direct Counter Settlement
        payload = {
            "settled_at": "2026-09-12",
            "settlement_type": "Cash Return at Counter Drawer",
            "notes": "Returned full amount to drawer during evening shift - Receipt #098"
        }
        settle_res = self.client.post(f"/api/advances/{target_id}/settle", json=payload)
        self.assertEqual(settle_res.status_code, 200)
        res_data = settle_res.json()
        self.assertTrue(res_data["success"])
        self.assertEqual(res_data["settled_at"], "2026-09-12")
        self.assertEqual(res_data["settlement_type"], "Cash Return at Counter Drawer")
        self.assertEqual(res_data["notes"], "Returned full amount to drawer during evening shift - Receipt #098")

        # Verify in database directly
        conn = get_db_connection()
        row = conn.execute("SELECT * FROM advance_salaries WHERE id = ?", (target_id,)).fetchone()
        conn.close()
        self.assertEqual(row["is_settled"], 1)
        self.assertEqual(row["settled_at"], "2026-09-12")
        self.assertEqual(row["settlement_type"], "Cash Return at Counter Drawer")
        self.assertEqual(row["notes"], "Returned full amount to drawer during evening shift - Receipt #098")

    def test_4_monthly_attendance_matrix_api(self):
        """Feature 4: Verify Monthly attendance matrix returns all days and staff."""
        res = self.client.get("/api/attendance/monthly?month=8&year=2026")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["days_in_month"], 31)
        self.assertEqual(len(data["matrix"]), 7)
        for staff_row in data["matrix"]:
            self.assertIn("days", staff_row)
            self.assertEqual(len(staff_row["days"]), 31)
            self.assertIn("present_count", staff_row)
            self.assertIn("late_count", staff_row)
            self.assertIn("half_day_count", staff_row)
            self.assertIn("leave_count", staff_row)
            self.assertIn("absent_count", staff_row)

if __name__ == "__main__":
    unittest.main()
