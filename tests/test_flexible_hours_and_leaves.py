"""
Unit Tests for Dynamic Free Leaves Quota & Flexible Work Hours with Hourly Wage Deductions
"""

import unittest
import os
import sys
from datetime import datetime, date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import init_db, get_db_connection
from payroll_engine import calculate_daily_wage, calculate_monthly_payroll, process_punch

class TestFlexibleHoursAndDynamicLeaves(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        conn = get_db_connection()
        # Ensure test staff #1 (Ali) has 45000 salary, 8h duty, 2 allowed leaves
        conn.execute("""
            UPDATE staff 
            SET monthly_salary = 45000.0, daily_hours = 8.0, allowed_leaves = 2
            WHERE id = 1
        """)
        # Clean September 2026 logs for staff 1
        conn.execute("DELETE FROM attendance_logs WHERE staff_id = 1 AND date LIKE '2026-09-%'")
        conn.execute("DELETE FROM leaves WHERE staff_id = 1 AND date LIKE '2026-09-%'")
        conn.execute("DELETE FROM advance_salaries WHERE staff_id = 1")
        conn.commit()
        conn.close()

    def test_1_dynamic_leaves_custom_quota(self):
        """Verify dynamic leaves quota: if allowed_leaves = 1, taking 2 leaves cuts 1 day."""
        conn = get_db_connection()
        # Set allowed_leaves = 1 for Ali
        conn.execute("UPDATE staff SET allowed_leaves = 1 WHERE id = 1")
        # 2 leaves taken
        conn.execute("INSERT INTO leaves (staff_id, date, reason) VALUES (1, '2026-09-01', 'Sick')")
        conn.execute("INSERT INTO leaves (staff_id, date, reason) VALUES (1, '2026-09-02', 'Sick')")
        # 28 full 8-hour days worked (480 mins)
        for d in range(3, 31):
            conn.execute("""
                INSERT INTO attendance_logs (staff_id, date, time_in, time_out, status, worked_minutes)
                VALUES (1, ?, '09:00:00', '17:00:00', 'ON_TIME', 480)
            """, (f"2026-09-{d:02d}",))
        conn.commit()
        conn.close()

        res = calculate_monthly_payroll(1, 9, 2026)
        daily_wage = 45000.0 / 30 # 1500.0
        self.assertEqual(res["allowed_leaves"], 1)
        self.assertEqual(res["leaves_count"], 2)
        self.assertEqual(res["extra_leaves"], 1)
        self.assertEqual(res["extra_leave_cut"], 1500.0)
        self.assertEqual(res["short_hours_cut"], 0.0)
        self.assertEqual(res["absent_cut"], 0.0)
        self.assertEqual(res["net_payable"], 45000.0 - 1500.0)

    def test_2_flexible_duty_and_short_hours_deduction(self):
        """
        Verify hourly deduction:
        Salary = 15000, 30 days -> Daily wage = 500, Daily hours = 8 -> Hourly wage = 62.50.
        Working 6 hours on 1 day (deficit = 2 hours = 120 mins) cuts exactly Rs. 125.
        """
        conn = get_db_connection()
        # Setup staff 2 with 15000 salary, 8h duty, 2 leaves
        conn.execute("""
            UPDATE staff 
            SET monthly_salary = 15000.0, daily_hours = 8.0, allowed_leaves = 2
            WHERE id = 2
        """)
        conn.execute("DELETE FROM attendance_logs WHERE staff_id = 2 AND date LIKE '2026-09-%'")
        conn.execute("DELETE FROM leaves WHERE staff_id = 2 AND date LIKE '2026-09-%'")
        conn.execute("DELETE FROM advance_salaries WHERE staff_id = 2")

        # Day 1: Arrived flexibly at 11:00 AM, left at 05:00 PM (6 hours worked = 360 mins, deficit = 120 mins)
        conn.execute("""
            INSERT INTO attendance_logs (staff_id, date, time_in, time_out, status, worked_minutes)
            VALUES (2, '2026-09-01', '11:00:00', '17:00:00', 'SHORT_HOURS', 360)
        """)

        # Other 29 days: Full 8 hours worked (480 mins)
        for d in range(2, 31):
            conn.execute("""
                INSERT INTO attendance_logs (staff_id, date, time_in, time_out, status, worked_minutes)
                VALUES (2, ?, '10:00:00', '18:00:00', 'ON_TIME', 480)
            """, (f"2026-09-{d:02d}",))

        conn.commit()
        conn.close()

        res = calculate_monthly_payroll(2, 9, 2026)
        self.assertEqual(res["daily_wage"], 500.0)
        self.assertEqual(res["hourly_wage"], 62.50)
        self.assertEqual(res["total_short_minutes"], 120)
        self.assertEqual(res["short_hours_cut"], 125.0) # 2 hours * 62.50 = 125.0
        self.assertEqual(res["absent_cut"], 0.0)
        self.assertEqual(res["extra_leave_cut"], 0.0)
        self.assertEqual(res["net_payable"], 15000.0 - 125.0)

    def test_3_process_punch_flexible_arrival(self):
        """Verify process_punch calculates target out and detects full vs short duty."""
        # Punch IN at 10:15 AM
        in_dt = datetime(2026, 9, 15, 10, 15, 0)
        punch_in_res = process_punch(1, punch_dt=in_dt)
        self.assertTrue(punch_in_res["success"])
        self.assertEqual(punch_in_res["punch_type"], "IN")
        self.assertIn("Target duty completion: 06:15 PM (8 hrs)", punch_in_res["message"])

        # Punch OUT at 06:30 PM (8h 15m worked >= 8h target)
        out_dt = datetime(2026, 9, 15, 18, 30, 0)
        punch_out_res = process_punch(1, punch_dt=out_dt)
        self.assertTrue(punch_out_res["success"])
        self.assertEqual(punch_out_res["punch_type"], "OUT")
        self.assertEqual(punch_out_res["status"], "ON_TIME")
        self.assertIn("Full Duty Completed", punch_out_res["message"])

if __name__ == "__main__":
    unittest.main()
