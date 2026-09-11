"""
Automated Unit Tests for Mumtaz Pharmacy Attendance & Payroll Rules
Tests:
- Daily wage calculation across different month lengths
- Shift grace period & late arrival detection
- Punch In / Out cycle & overtime accumulation
- Month-end payroll calculation with absent cuts, late penalties, and advances
"""

import unittest
import os
import sys
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import init_db, get_db_connection
from payroll_engine import calculate_daily_wage, process_punch, calculate_monthly_payroll

class TestPayrollEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def test_daily_wage_calculation(self):
        # 30-day month (April/June/Sept/Nov)
        wage_30 = calculate_daily_wage(30000.0, 30)
        self.assertEqual(wage_30, 1000.0)

        # 31-day month (Jan/March/May/July/Aug/Oct/Dec)
        wage_31 = calculate_daily_wage(31000.0, 31)
        self.assertEqual(wage_31, 1000.0)

        # 28-day month (February)
        wage_28 = calculate_daily_wage(28000.0, 28)
        self.assertEqual(wage_28, 1000.0)

        # Salary with fractional result
        wage_frac = calculate_daily_wage(35000.0, 30)
        self.assertEqual(wage_frac, 1166.67)

    def test_punch_on_time_within_grace(self):
        # Ali Raza (Shift 1: 09:00 to 17:00, Grace: 15 mins)
        # Punch at 09:10 AM (Within grace period)
        punch_time = datetime(2026, 9, 15, 9, 10, 0)
        res = process_punch(staff_id=1, punch_dt=punch_time)
        
        self.assertTrue(res["success"])
        self.assertEqual(res["punch_type"], "IN")
        self.assertEqual(res["status"], "ON_TIME")
        self.assertEqual(res["late_minutes"], 0)

    def test_punch_out_and_overtime(self):
        # Ali Raza (Shift 1: Ends at 17:00)
        # Punch OUT at 18:30 (1 hour 30 mins = 90 mins overtime)
        punch_out_time = datetime(2026, 9, 15, 18, 30, 0)
        res = process_punch(staff_id=1, punch_dt=punch_out_time)
        
        self.assertTrue(res["success"])
        self.assertEqual(res["punch_type"], "OUT")
        self.assertEqual(res["overtime_minutes"], 90)
        self.assertGreaterEqual(res["worked_minutes"], 500)

    def test_monthly_payroll_math(self):
        # Insert advance for Ali
        conn = get_db_connection()
        conn.execute("DELETE FROM advance_salaries WHERE staff_id = 1")
        conn.execute("""
            INSERT INTO advance_salaries (staff_id, amount, date, reason)
            VALUES (1, 2000.0, '2026-09-10', 'Emergency Cash from Drawer')
        """)
        conn.commit()
        conn.close()

        # Calculate payroll for September 2026 (30 days)
        # Ali basic salary = 45000, daily wage = 1500.0
        payroll = calculate_monthly_payroll(staff_id=1, month=9, year=2026)

        self.assertEqual(payroll["basic_salary"], 45000.0)
        self.assertEqual(payroll["daily_wage"], 1500.0)
        self.assertEqual(payroll["advances_deducted"], 2000.0)
        self.assertGreater(payroll["net_payable"], 0)

if __name__ == "__main__":
    unittest.main()
