"""
Mumtaz Pharmacy - Realistic Seed Data Generator
Populates last 2-3 months (July 2026, August 2026, September 2026) of realistic:
- Staff Directory (6 employees with full CNIC, Address, Designation, Salary, Joining Date)
- Daily Attendance Logs (On Time, Late, Half-Days, Absents)
- Approved Leaves (Testing 2-leave quota: some <= 2 leaves, some > 2 leaves)
- Half-Days (Testing 4-half-day quota: some <= 4, some > 4)
- Staff Khata Ledger (Cash Advances from counter till & Medicine Credits from store)
- Today's Live Roster (Mix of Present, Late, Half-Day, Active On-Duty, and Approved Leave)
- Pre-calculated Payroll records for July & August, with September ready for 1-Click Calculation!
"""

import sqlite3
import os
from datetime import date, datetime, timedelta
import calendar
from database import DB_PATH, init_db
from payroll_engine import calculate_monthly_payroll

def seed():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("[1/6] Clearing old records to ensure clean realistic sample data...")
    cursor.execute("DELETE FROM attendance_logs")
    cursor.execute("DELETE FROM leaves")
    cursor.execute("DELETE FROM advance_salaries")
    cursor.execute("DELETE FROM payroll_records")
    cursor.execute("DELETE FROM staff")

    print("[2/6] Seeding Staff Directory (6 Mumtaz Pharmacy Team Members)...")
    staff_members = [
        (1, 'Ali Raza', '0300-1234567', '35202-1234567-1', 'House 14, St 3, Model Town, Lahore', 'Senior Pharmacist', 'Senior Pharmacist', 45000.0, '2025-01-15', 1, 'FP_ALI_001', 1, 2, 8.0, 1),
        (2, 'Bilal Ahmed', '0321-7654321', '35202-7654321-3', 'Plot 88, Block B, Faisal Town, Lahore', 'Counter Sales & Billing', 'Counter Sales & Billing', 35000.0, '2025-05-10', 1, 'FP_BILAL_002', 1, 2, 8.0, 1),
        (3, 'Usman Tariq', '0333-9876543', '35202-9876543-5', 'Main Bazar, Kot Lakhpat, Lahore', 'Store Runner & Dispenser', 'Store Runner & Dispenser', 26000.0, '2025-11-20', 2, 'FP_USMAN_003', 0, 1, 8.0, 1),
        (4, 'Hamza Farooq', '0312-4455667', '35201-4455667-7', 'St 8, Gulberg III, Lahore', 'Assistant Pharmacist', 'Assistant Pharmacist', 40000.0, '2025-08-01', 1, 'FP_HAMZA_004', 1, 2, 8.0, 1),
        (5, 'Zainab Bibi', '0345-8899001', '35202-8899001-2', 'Allama Iqbal Town, Lahore', 'Cashier & Inventory', 'Cashier & Inventory', 30000.0, '2026-02-15', 1, 'FP_ZAINAB_005', 1, 2, 8.0, 1),
        (6, 'Tariq Mehmood', '0308-3344556', '35202-3344556-9', 'Sector B, Township, Lahore', 'Night Shift Dispenser', 'Night Shift Dispenser', 28000.0, '2026-04-01', 2, 'FP_TARIQ_006', 0, 2, 8.0, 1),
        (7, 'Muhammad Kashif', '0302-5566778', '35202-5566778-4', 'St 5, Samanabad, Lahore', 'Helper & Delivery Boy', 'Helper & Delivery Boy', 22000.0, '2026-05-01', 1, 'FP_KASHIF_007', 1, 2, 8.0, 1)
    ]

    cursor.executemany("""
        INSERT INTO staff (id, name, phone, cnic, address, role, designation, monthly_salary, joining_date, shift_id, fingerprint_id, police_report, allowed_leaves, daily_hours, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, staff_members)

    print("[3/6] Seeding Approved Leaves for July, August & September 2026...")
    leaves_data = [
        # July 2026: Ali took 2 leaves (Quota = 2 -> 0 deduction)
        (1, '2026-07-10', 'Family wedding in Faisalabad'),
        (1, '2026-07-11', 'Family wedding in Faisalabad'),
        # July 2026: Bilal took 1 leave
        (2, '2026-07-18', 'Severe Migraine'),
        # July 2026: Zainab took 2 leaves
        (5, '2026-07-22', 'Sister Engagement'),
        (5, '2026-07-23', 'Sister Engagement'),

        # August 2026: Ali took 3 leaves (Quota = 2 -> 1 EXTRA UNPAID LEAVE!)
        (1, '2026-08-05', 'Typhoid fever recovery'),
        (1, '2026-08-06', 'Typhoid fever recovery'),
        (1, '2026-08-07', 'Doctor appointment & rest'),
        # August 2026: Bilal took 2 leaves (Quota = 2 -> 0 deduction)
        (2, '2026-08-14', 'Independence Day family event'),
        (2, '2026-08-15', 'Personal urgent work'),
        # August 2026: Hamza took 2 leaves
        (4, '2026-08-20', 'Dental surgery'),
        (4, '2026-08-21', 'Post-surgery bed rest'),
        # August 2026: Zainab took 3 leaves (Quota = 2 -> 1 EXTRA LEAVE!)
        (5, '2026-08-10', 'Viral fever'),
        (5, '2026-08-11', 'Viral fever'),
        (5, '2026-08-12', 'Doctor checkup'),

        # September 2026 (Current Month):
        (1, '2026-09-04', 'Urgent home renovation'),
        (2, '2026-09-02', 'Cousin Nikkah'),
        (2, '2026-09-03', 'Cousin Walima'),
        (2, '2026-09-08', 'Vehicle emergency repair'), # Bilal 3rd leave in Sept = 1 EXTRA!
        (4, '2026-09-05', 'Back pain physiotherapy'),
        # Tariq is on approved leave today!
        (6, date.today().strftime("%Y-%m-%d"), 'Severe seasonal flu & fever')
    ]

    cursor.executemany("""
        INSERT INTO leaves (staff_id, date, reason)
        VALUES (?, ?, ?)
    """, leaves_data)

    print("[4/6] Seeding Staff Khata (Cash Advances & Medicine Credits)...")
    # July entries (Settled via July 2026 Payroll)
    july_khata = [
        (1, 'ADVANCE', 3000.0, '2026-07-05', 'Emergency Cash for Utility Bills', 1, '2026-07-31', 'Deducted from July 2026 Salary', 7, 2026),
        (2, 'MEDICINE_CREDIT', 1200.0, '2026-07-12', 'Augmentin 625mg + Panadol for Family', 1, '2026-07-31', 'Deducted from July 2026 Salary', 7, 2026),
        (3, 'ADVANCE', 2000.0, '2026-07-15', 'Counter Cash Advance', 1, '2026-07-31', 'Deducted from July 2026 Salary', 7, 2026),
    ]
    cursor.executemany("""
        INSERT INTO advance_salaries (staff_id, entry_type, amount, date, reason, is_settled, settled_at, settlement_type, settled_payroll_month, settled_payroll_year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, july_khata)

    # August entries (Settled via August 2026 Payroll)
    august_khata = [
        (1, 'MEDICINE_CREDIT', 2500.0, '2026-08-08', 'Surbex Z, Calpol, Insulin for Father', 1, '2026-08-31', 'Deducted from August 2026 Salary', 8, 2026),
        (2, 'ADVANCE', 4000.0, '2026-08-12', 'Cash Advance for School Fees', 1, '2026-08-31', 'Deducted from August 2026 Salary', 8, 2026),
        (4, 'MEDICINE_CREDIT', 1800.0, '2026-08-18', 'Antibiotics & Inhaler', 1, '2026-08-31', 'Deducted from August 2026 Salary', 8, 2026),
        (5, 'ADVANCE', 2500.0, '2026-08-20', 'Cash for Mother Medicine', 1, '2026-08-31', 'Deducted from August 2026 Salary', 8, 2026),
    ]
    cursor.executemany("""
        INSERT INTO advance_salaries (staff_id, entry_type, amount, date, reason, is_settled, settled_at, settlement_type, settled_payroll_month, settled_payroll_year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, august_khata)

    # September entries (UNSETTLED - Ready for 1-Click Payroll & Direct UI Settlement!)
    sept_khata = [
        (1, 'ADVANCE', 4000.0, '2026-09-02', 'Emergency Cash from Drawer', 0, '', '', 0, 0),
        (1, 'MEDICINE_CREDIT', 2200.0, '2026-09-07', 'Diabetes Meter Strips & Glucophage', 0, '', '', 0, 0),
        (2, 'ADVANCE', 3000.0, '2026-09-04', 'Counter Cash Advance', 0, '', '', 0, 0),
        (3, 'MEDICINE_CREDIT', 1500.0, '2026-09-06', 'Panadol CF, Arinac & Brufen', 0, '', '', 0, 0),
        (4, 'ADVANCE', 2000.0, '2026-09-09', 'Cash Advance for Bike Fuel & Repair', 0, '', '', 0, 0),
        (5, 'MEDICINE_CREDIT', 1100.0, '2026-09-10', 'Multivitamins & Baby Diapers', 0, '', '', 0, 0)
    ]
    cursor.executemany("""
        INSERT INTO advance_salaries (staff_id, entry_type, amount, date, reason, is_settled, settled_at, settlement_type, settled_payroll_month, settled_payroll_year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sept_khata)

    print("[5/6] Seeding Daily Attendance Logs (July, August, September)...")
    leave_dates_set = {(row[0], row[1]) for row in leaves_data}

    today = date.today()
    max_sept_day = today.day if (today.year == 2026 and today.month == 9) else 12

    logs_to_insert = []
    months_plan = [
        (7, 2026, 31),
        (8, 2026, 31),
        (9, 2026, max_sept_day) # Up to today
    ]

    for m, y, max_days in months_plan:
        for d in range(1, max_days + 1):
            date_str = f"{y}-{m:02d}-{d:02d}"
            dt_obj = datetime(y, m, d)
            is_sunday = dt_obj.weekday() == 6

            for s_id in range(1, 8):
                # If on approved leave, skip attendance log (leaves table handles it)
                if (s_id, date_str) in leave_dates_set:
                    continue

                # Pharmacy rotational off on Sunday for runner & night dispenser
                if is_sunday and s_id in (3, 6):
                    continue

                # Default values:
                status = "ON_TIME"
                time_in = "09:00:00" if s_id not in (3, 6) else "17:00:00"
                time_out = "17:05:00" if s_id not in (3, 6) else "01:05:00"
                worked_minutes = 480
                late_minutes = 0

                # Patterns:
                # August: Hamza (s_id=4) took 5 half-days (breaching 4 quota!)
                if m == 8 and s_id == 4 and d in (2, 8, 16, 23, 28):
                    status = "HALF_DAY"
                    time_in = "09:00:00"
                    time_out = "12:30:00"
                    worked_minutes = 210

                # Lates in July / August / September:
                elif (d in (3, 15, 22) and s_id == 2) or (d == 7 and s_id == 1) or (d == 6 and s_id == 4):
                    status = "LATE"
                    time_in = "09:28:00" if s_id not in (3, 6) else "17:35:00"
                    late_minutes = 28
                    worked_minutes = 452

                # Absents:
                elif (m == 8 and d in (12, 26) and s_id == 6) or (m == 7 and d == 20 and s_id == 3):
                    # Marked absent (no log inserted)
                    continue

                # TODAY live roster state:
                if (m == today.month and y == today.year and d == today.day) or (m == 9 and d == max_sept_day and y == 2026):
                    if s_id == 1:
                        # Ali: Senior Pharmacist, morning shift, checked in on time, completed shift
                        status = "ON_TIME"
                        time_in = "08:55:00"
                        time_out = "17:05:00"
                        worked_minutes = 490
                    elif s_id == 2:
                        # Bilal: Counter sales, morning shift, checked in late, currently on duty!
                        status = "LATE"
                        time_in = "09:25:00"
                        late_minutes = 25
                        time_out = None
                        worked_minutes = 0
                    elif s_id == 3:
                        # Usman: Evening shift (17:00 - 01:00), checked in, currently on duty!
                        status = "ON_TIME"
                        time_in = "17:00:00"
                        time_out = None
                        worked_minutes = 0
                    elif s_id == 4:
                        # Hamza: Assistant Pharmacist, morning shift, checked in on time, completed shift
                        status = "ON_TIME"
                        time_in = "08:58:00"
                        time_out = "17:02:00"
                        worked_minutes = 484
                    elif s_id == 5:
                        # Zainab: Cashier, morning shift, half-day worked 09:00 to 13:00 and checked out
                        status = "HALF_DAY"
                        time_in = "09:00:00"
                        time_out = "13:00:00"
                        worked_minutes = 240
                    elif s_id == 6:
                        # Tariq: Night shift, on approved medical leave today (handled by leaves table)
                        continue
                    elif s_id == 7:
                        # Kashif: Helper & Delivery Boy, Morning Shift, UNEXCUSED ABSENT TODAY!
                        status = "ABSENT"
                        time_in = None
                        time_out = None
                        worked_minutes = 0
                        late_minutes = 0

                logs_to_insert.append((
                    s_id, date_str, time_in, time_out, status, worked_minutes, late_minutes, "FINGERPRINT"
                ))

    cursor.executemany("""
        INSERT INTO attendance_logs 
        (staff_id, date, time_in, time_out, status, worked_minutes, late_minutes, punch_method)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, logs_to_insert)

    conn.commit()
    conn.close()

    print("[6/6] Pre-calculating historical Payroll sheets for July 2026 & August 2026...")
    # Calculate July 2026 payroll for all staff
    for s_id in range(1, 8):
        calculate_monthly_payroll(s_id, 7, 2026)

    # Calculate August 2026 payroll for all staff
    for s_id in range(1, 8):
        calculate_monthly_payroll(s_id, 8, 2026)

    print("SUCCESS! Mumtaz Pharmacy database seeded with realistic 3-month operational data.")
    print("Today's Live Roster, Staff Directory, Advance Khata, and 1-Click Payroll are ready for testing.")

if __name__ == "__main__":
    seed()
