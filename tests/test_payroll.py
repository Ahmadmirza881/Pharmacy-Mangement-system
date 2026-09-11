"""
Automated Unit Tests for Mumtaz Pharmacy Attendance & Payroll Rules
Tests client budget rules:
- Daily wage calculation across month lengths
- 2 Paid Leaves per month quota & extra leave deduction
- 4 Half-Days per month allowance & extra half-day deduction
- Advance & Medicine Credit Khata deduction
- Verification that late penalties and overtime pay are zero
"""

import unittest
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import init_db, get_db_connection
from payroll_engine import calculate_daily_wage, calculate_monthly_payroll

class TestPayrollEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        # Clean test state for Ali (staff_id = 1) in test month September 2026
        conn = get_db_connection()
        conn.execute("DELETE FROM attendance_logs WHERE staff_id = 1 AND date LIKE '2026-09-%'")
        conn.execute("DELETE FROM leaves WHERE staff_id = 1 AND date LIKE '2026-09-%'")
        conn.execute("DELETE FROM advance_salaries WHERE staff_id = 1")
        conn.commit()
        conn.close()

    def test_daily_wage_calculation(self):
        # 30-day month
        wage_30 = calculate_daily_wage(30000.0, 30)
        self.assertEqual(wage_30, 1000.0)

        # 31-day month
        wage_31 = calculate_daily_wage(31000.0, 31)
        self.assertEqual(wage_31, 1000.0)

    def test_two_leaves_quota_and_extra_leave_deduction(self):
        conn = get_db_connection()
        # Insert 3 approved leaves for Ali in September 2026
        # Allowed: 2 leaves. Extra: 1 leave.
        # Daily wage for Ali (45000 / 30) = 1500.0
        conn.execute("INSERT INTO leaves (staff_id, date, reason) VALUES (1, '2026-09-05', 'Sick')")
        conn.execute("INSERT INTO leaves (staff_id, date, reason) VALUES (1, '2026-09-06', 'Sick')")
        conn.execute("INSERT INTO leaves (staff_id, date, reason) VALUES (1, '2026-09-07', 'Personal')")
        
        # Mark all other 27 days as ON_TIME present
        for d in range(1, 31):
            if d not in (5, 6, 7):
                dt_str = f"2026-09-{d:02d}"
                conn.execute("""
                    INSERT INTO attendance_logs (staff_id, date, time_in, time_out, status, worked_minutes)
                    VALUES (1, ?, '09:00:00', '17:00:00', 'ON_TIME', 480)
                """, (dt_str,))
        conn.commit()
        conn.close()

        payroll = calculate_monthly_payroll(staff_id=1, month=9, year=2026)
        self.assertEqual(payroll["leaves_count"], 3)
        self.assertEqual(payroll["extra_leaves"], 1)
        self.assertEqual(payroll["extra_leave_cut"], 1500.0)
        self.assertEqual(payroll["absent_days"], 0)
        # Net payable = 45000 - 1500 = 43500
        self.assertEqual(payroll["net_payable"], 43500.0)

    def test_four_half_days_quota_and_extra_half_day_deduction(self):
        conn = get_db_connection()
        # Insert 5 half-days for Ali in September 2026
        # Allowed: 4 half-days. Extra: 1 half-day.
        # Deduction: 1 * (0.5 * 1500) = 750.0
        for d in range(1, 6):
            dt_str = f"2026-09-{d:02d}"
            conn.execute("""
                INSERT INTO attendance_logs (staff_id, date, time_in, time_out, status, worked_minutes)
                VALUES (1, ?, '09:00:00', '12:00:00', 'HALF_DAY', 180)
            """, (dt_str,))

        # Remaining 25 days full present
        for d in range(6, 31):
            dt_str = f"2026-09-{d:02d}"
            conn.execute("""
                INSERT INTO attendance_logs (staff_id, date, time_in, time_out, status, worked_minutes)
                VALUES (1, ?, '09:00:00', '17:00:00', 'ON_TIME', 480)
            """, (dt_str,))
        conn.commit()
        conn.close()

        payroll = calculate_monthly_payroll(staff_id=1, month=9, year=2026)
        self.assertEqual(payroll["half_days"], 5)
        self.assertEqual(payroll["extra_half_days"], 1)
        self.assertEqual(payroll["extra_half_day_cut"], 750.0)
        # Net payable = 45000 - 750 = 44250
        self.assertEqual(payroll["net_payable"], 44250.0)

    def test_advance_and_medicine_credit_deduction(self):
        conn = get_db_connection()
        # Cash advance of Rs. 2000
        conn.execute("""
            INSERT INTO advance_salaries (staff_id, amount, date, reason, entry_type)
            VALUES (1, 2000.0, '2026-09-10', 'Emergency Cash', 'ADVANCE')
        """)
        # Medicine Credit of Rs. 1500
        conn.execute("""
            INSERT INTO advance_salaries (staff_id, amount, date, reason, entry_type)
            VALUES (1, 1500.0, '2026-09-12', 'Panadol & Surbex Z for Home', 'MEDICINE_CREDIT')
        """)
        
        # All 30 days present
        for d in range(1, 31):
            dt_str = f"2026-09-{d:02d}"
            conn.execute("""
                INSERT INTO attendance_logs (staff_id, date, time_in, time_out, status, worked_minutes)
                VALUES (1, ?, '09:00:00', '17:00:00', 'ON_TIME', 480)
            """, (dt_str,))
        conn.commit()
        conn.close()

        payroll = calculate_monthly_payroll(staff_id=1, month=9, year=2026)
        self.assertEqual(payroll["advances_deducted"], 3500.0)
        # Net payable = 45000 - 3500 = 41500
        self.assertEqual(payroll["net_payable"], 41500.0)

    def test_no_late_penalty_and_no_overtime_pay(self):
        conn = get_db_connection()
        # Ali is late 6 times (in old rules, 6 lates would deduct 1 full day wage)
        # In new client scope: automated late penalty is strictly excluded!
        for d in range(1, 7):
            dt_str = f"2026-09-{d:02d}"
            conn.execute("""
                INSERT INTO attendance_logs (staff_id, date, time_in, time_out, status, late_minutes, overtime_minutes, worked_minutes)
                VALUES (1, ?, '09:45:00', '19:00:00', 'LATE', 45, 120, 555)
            """, (dt_str,))

        for d in range(7, 31):
            dt_str = f"2026-09-{d:02d}"
            conn.execute("""
                INSERT INTO attendance_logs (staff_id, date, time_in, time_out, status, worked_minutes)
                VALUES (1, ?, '09:00:00', '17:00:00', 'ON_TIME', 480)
            """, (dt_str,))
        conn.commit()
        conn.close()

        payroll = calculate_monthly_payroll(staff_id=1, month=9, year=2026)
        self.assertEqual(payroll["late_count"], 6)
        self.assertEqual(payroll["late_cut"], 0.0)
        self.assertEqual(payroll.get("overtime_pay", 0.0), 0.0)
        # Net payable remains full basic salary: 45000
        self.assertEqual(payroll["net_payable"], 45000.0)

if __name__ == "__main__":
    unittest.main()
