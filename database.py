"""
Mumtaz Pharmacy - Database Layer (SQLite)
Handles local persistent storage for staff, shifts, biometric attendance logs,
advance salary records, and month-end payroll sheets.
"""

import sqlite3
import os
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(__file__), "mumtaz_attendance.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Shifts Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        start_time TEXT NOT NULL,      -- "09:00" (HH:MM 24h)
        end_time TEXT NOT NULL,        -- "17:00"
        grace_minutes INTEGER DEFAULT 15,
        half_day_minutes INTEGER DEFAULT 240, -- worked < 4 hours = half day
        is_night_shift INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Staff Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        cnic TEXT,
        address TEXT DEFAULT '',
        role TEXT NOT NULL,            -- "Pharmacist", "Counter Sales", "Runner"
        designation TEXT DEFAULT '',
        monthly_salary REAL NOT NULL,
        joining_date TEXT DEFAULT '',
        shift_id INTEGER NOT NULL,
        fingerprint_id TEXT,           -- Template or registered token
        police_report INTEGER DEFAULT 0, -- 1 = Yes (Verified), 0 = No (Pending)
        allowed_leaves INTEGER DEFAULT 2, -- Dynamic monthly paid leaves quota
        daily_hours REAL DEFAULT 8.0,     -- Required daily work duty in hours
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (shift_id) REFERENCES shifts (id)
    );
    """)

    # Safe dynamic column migrations for existing databases
    cursor.execute("PRAGMA table_info(staff)")
    existing_staff_cols = {row[1] for row in cursor.fetchall()}
    if "address" not in existing_staff_cols:
        cursor.execute("ALTER TABLE staff ADD COLUMN address TEXT DEFAULT ''")
    if "designation" not in existing_staff_cols:
        cursor.execute("ALTER TABLE staff ADD COLUMN designation TEXT DEFAULT ''")
        cursor.execute("UPDATE staff SET designation = role WHERE designation IS NULL OR designation = ''")
    if "joining_date" not in existing_staff_cols:
        cursor.execute("ALTER TABLE staff ADD COLUMN joining_date TEXT DEFAULT '2026-01-01'")
    if "police_report" not in existing_staff_cols:
        cursor.execute("ALTER TABLE staff ADD COLUMN police_report INTEGER DEFAULT 0")
    if "allowed_leaves" not in existing_staff_cols:
        cursor.execute("ALTER TABLE staff ADD COLUMN allowed_leaves INTEGER DEFAULT 2")
    if "daily_hours" not in existing_staff_cols:
        cursor.execute("ALTER TABLE staff ADD COLUMN daily_hours REAL DEFAULT 8.0")

    # 3. Attendance Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        date TEXT NOT NULL,            -- "YYYY-MM-DD"
        time_in TEXT,                  -- "HH:MM:SS"
        time_out TEXT,                 -- "HH:MM:SS"
        status TEXT NOT NULL,          -- "ON_TIME", "LATE", "HALF_DAY", "ABSENT", "APPROVED_LEAVE"
        worked_minutes INTEGER DEFAULT 0,
        late_minutes INTEGER DEFAULT 0,
        overtime_minutes INTEGER DEFAULT 0,
        punch_method TEXT DEFAULT "FINGERPRINT", -- "FINGERPRINT", "MANUAL_OVERRIDE"
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(staff_id, date),
        FOREIGN KEY (staff_id) REFERENCES staff (id)
    );
    """)

    # 4. Advance Salary / Khata Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS advance_salaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        entry_type TEXT DEFAULT 'ADVANCE', -- 'ADVANCE' or 'MEDICINE_CREDIT'
        amount REAL NOT NULL,
        date TEXT NOT NULL,            -- "YYYY-MM-DD"
        reason TEXT,
        is_settled INTEGER DEFAULT 0,  -- 1 once deducted in month-end payroll
        settled_payroll_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (staff_id) REFERENCES staff (id)
    );
    """)

    cursor.execute("PRAGMA table_info(advance_salaries)")
    existing_adv_cols = {row[1] for row in cursor.fetchall()}
    if "entry_type" not in existing_adv_cols:
        cursor.execute("ALTER TABLE advance_salaries ADD COLUMN entry_type TEXT DEFAULT 'ADVANCE'")
    if "settled_at" not in existing_adv_cols:
        cursor.execute("ALTER TABLE advance_salaries ADD COLUMN settled_at TEXT DEFAULT ''")
    if "settlement_type" not in existing_adv_cols:
        cursor.execute("ALTER TABLE advance_salaries ADD COLUMN settlement_type TEXT DEFAULT ''")
    if "notes" not in existing_adv_cols:
        cursor.execute("ALTER TABLE advance_salaries ADD COLUMN notes TEXT DEFAULT ''")
    if "settled_payroll_month" not in existing_adv_cols:
        cursor.execute("ALTER TABLE advance_salaries ADD COLUMN settled_payroll_month INTEGER DEFAULT 0")
    if "settled_payroll_year" not in existing_adv_cols:
        cursor.execute("ALTER TABLE advance_salaries ADD COLUMN settled_payroll_year INTEGER DEFAULT 0")

    # 5. Leave Approvals Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leaves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        reason TEXT,
        approved_by TEXT DEFAULT "Owner",
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(staff_id, date),
        FOREIGN KEY (staff_id) REFERENCES staff (id)
    );
    """)

    # 6. Monthly Payroll Records Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payroll_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        month INTEGER NOT NULL,        -- 1 to 12
        year INTEGER NOT NULL,         -- 2026
        days_in_month INTEGER NOT NULL,
        basic_salary REAL NOT NULL,
        daily_wage REAL NOT NULL,
        present_days INTEGER DEFAULT 0,
        absent_days INTEGER DEFAULT 0,
        absent_cut REAL DEFAULT 0,
        late_count INTEGER DEFAULT 0,
        late_cut REAL DEFAULT 0,
        half_days INTEGER DEFAULT 0,
        extra_half_days INTEGER DEFAULT 0,
        half_day_cut REAL DEFAULT 0,
        extra_half_day_cut REAL DEFAULT 0,
        leaves_count INTEGER DEFAULT 0,
        extra_leaves INTEGER DEFAULT 0,
        extra_leave_cut REAL DEFAULT 0,
        overtime_minutes INTEGER DEFAULT 0,
        overtime_pay REAL DEFAULT 0,
        advances_deducted REAL DEFAULT 0,
        net_payable REAL NOT NULL,
        status TEXT DEFAULT "GENERATED", -- "GENERATED", "PAID"
        paid_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(staff_id, month, year),
        FOREIGN KEY (staff_id) REFERENCES staff (id)
    );
    """)

    cursor.execute("PRAGMA table_info(payroll_records)")
    existing_pr_cols = {row[1] for row in cursor.fetchall()}
    if "leaves_count" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN leaves_count INTEGER DEFAULT 0")
    if "extra_leaves" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN extra_leaves INTEGER DEFAULT 0")
    if "extra_leave_cut" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN extra_leave_cut REAL DEFAULT 0")
    if "extra_half_days" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN extra_half_days INTEGER DEFAULT 0")
    if "extra_half_day_cut" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN extra_half_day_cut REAL DEFAULT 0")
    if "status" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN status TEXT DEFAULT 'GENERATED'")
    if "paid_at" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN paid_at TEXT DEFAULT ''")
    if "payment_method" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN payment_method TEXT DEFAULT 'Cash'")
    if "notes" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN notes TEXT DEFAULT ''")
    if "short_hours_cut" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN short_hours_cut REAL DEFAULT 0")
    if "short_minutes" not in existing_pr_cols:
        cursor.execute("ALTER TABLE payroll_records ADD COLUMN short_minutes INTEGER DEFAULT 0")

    # Populate Default Shifts if empty
    cursor.execute("SELECT COUNT(*) FROM shifts")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO shifts (name, start_time, end_time, grace_minutes, half_day_minutes) VALUES
        ('Morning Shift', '09:00', '17:00', 15, 240),
        ('Evening / Night Shift', '17:00', '01:00', 15, 240)
        """)

    # Populate Sample Staff for Mumtaz Pharmacy if empty
    cursor.execute("SELECT COUNT(*) FROM staff")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO staff (name, phone, cnic, address, role, designation, monthly_salary, joining_date, shift_id, fingerprint_id) VALUES
        ('Ali Raza', '0300-1234567', '35202-1234567-1', 'House 14, St 3, Model Town, Lahore', 'Senior Pharmacist', 'Senior Pharmacist', 45000, '2025-01-15', 1, 'FP_ALI_001'),
        ('Bilal Ahmed', '0321-7654321', '35202-7654321-3', 'Plot 88, Block B, Faisal Town, Lahore', 'Counter Sales & Billing', 'Counter Sales & Billing', 32000, '2025-06-01', 1, 'FP_BILAL_002'),
        ('Usman Tariq', '0333-9876543', '35202-9876543-5', 'Main Bazar, Kot Lakhpat, Lahore', 'Store Runner & Dispenser', 'Store Runner & Dispenser', 25000, '2025-11-20', 2, 'FP_USMAN_003')
        """)
    else:
        # Ensure existing staff rows have populated designation and address if blank
        cursor.execute("""
            UPDATE staff SET designation = role WHERE designation IS NULL OR designation = ''
        """)
        cursor.execute("""
            UPDATE staff SET joining_date = '2025-01-01' WHERE joining_date IS NULL OR joining_date = ''
        """)
        cursor.execute("""
            UPDATE staff SET address = 'Lahore, Pakistan' WHERE address IS NULL OR address = ''
        """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Mumtaz Pharmacy Attendance Database initialized successfully.")
