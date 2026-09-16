"""
Mumtaz Pharmacy - Database Layer (SQLite)
Handles local persistent storage for staff, shifts, biometric attendance logs,
advance salary records, and month-end payroll sheets.
"""

import sqlite3
import os
from datetime import datetime, date, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "mumtaz_attendance.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
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
        pin TEXT DEFAULT '1001',          -- 4-digit secret PIN for attendance
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
    if "pin" not in existing_staff_cols:
        cursor.execute("ALTER TABLE staff ADD COLUMN pin TEXT DEFAULT '1001'")
        cursor.execute("UPDATE staff SET pin = printf('%04d', 1000 + id) WHERE pin IS NULL OR pin = '' OR pin = '1001'")

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
        leave_type TEXT DEFAULT "FULL_DAY", -- "FULL_DAY" (1.0) or "HALF_DAY" (0.5)
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

    # 7. Customers Master Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        address TEXT DEFAULT '',
        credit_limit REAL DEFAULT 15000.0,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 8. Customer Khata Series Ledger Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customer_khata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        invoice_no TEXT NOT NULL,
        date TEXT NOT NULL,
        item_description TEXT NOT NULL,
        amount REAL NOT NULL,
        is_settled INTEGER DEFAULT 0,
        settled_at TEXT DEFAULT '',
        payment_method TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers (id)
    );
    """)

    cursor.execute("PRAGMA table_info(customer_khata)")
    existing_ck_cols = {row[1] for row in cursor.fetchall()}
    if "invoice_no" not in existing_ck_cols:
        cursor.execute("ALTER TABLE customer_khata ADD COLUMN invoice_no TEXT DEFAULT ''")
    if "settled_at" not in existing_ck_cols:
        cursor.execute("ALTER TABLE customer_khata ADD COLUMN settled_at TEXT DEFAULT ''")
    if "payment_method" not in existing_ck_cols:
        cursor.execute("ALTER TABLE customer_khata ADD COLUMN payment_method TEXT DEFAULT ''")
    if "notes" not in existing_ck_cols:
        cursor.execute("ALTER TABLE customer_khata ADD COLUMN notes TEXT DEFAULT ''")

    # Migration: leave_type in leaves table
    cursor.execute("PRAGMA table_info(leaves)")
    existing_leave_cols = {row[1] for row in cursor.fetchall()}
    if "leave_type" not in existing_leave_cols:
        cursor.execute("ALTER TABLE leaves ADD COLUMN leave_type TEXT DEFAULT 'FULL_DAY'")

    # 9. Real-Time Activity Logs Table (Audit Feed)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,       -- "ATTENDANCE", "LEAVE", "STAFF_KHATA", "CUSTOMER_KHATA", "PAYROLL", "STAFF"
        action_type TEXT NOT NULL,    -- "PUNCH_IN", "PUNCH_OUT", "LEAVE_APPLIED", "LEAVE_EDITED", "LEAVE_DELETED", "ADVANCE_ADDED", "ADVANCE_SETTLED", "CUSTOMER_KHATA_ADDED", "CUSTOMER_KHATA_SETTLED", "SALARY_PAID", "STAFF_ADDED", "STAFF_UPDATED"
        title TEXT NOT NULL,          -- e.g. "Biometric Punch IN: Ali Raza"
        description TEXT NOT NULL,    -- e.g. "Time-IN recorded at 08:02 AM • Status: ON_TIME"
        staff_name TEXT DEFAULT '',   -- e.g. "Ali Raza"
        amount REAL DEFAULT 0.0,      -- e.g. 4000.0 or 0.0
        date TEXT NOT NULL,           -- "YYYY-MM-DD"
        time TEXT NOT NULL,           -- "HH:MM:SS" or "08:02:15 AM"
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 10. System Settings Table (Stores Admin WhatsApp number, kiosk configs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    default_settings = {
        "admin_whatsapp_number": "0300-1234567",
        "admin_name": "Pharmacy Owner / Manager",
        "pharmacy_name": "Mumtaz Pharmacy",
        "otp_expiry_minutes": "5",
        "whatsapp_service_status": "READY"
    }
    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (k, v))

    # 11. OTP Verifications Table (Tracks active & past PIN-triggered OTPs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS otp_verifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        otp_code TEXT NOT NULL,
        action TEXT NOT NULL,            -- "IN" or "OUT"
        target_phone TEXT NOT NULL,
        is_used INTEGER DEFAULT 0,
        attempts INTEGER DEFAULT 0,
        expires_at TIMESTAMP NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (staff_id) REFERENCES staff (id)
    );
    """)

    cursor.execute("PRAGMA table_info(otp_verifications)")
    existing_otp_cols = {row[1] for row in cursor.fetchall()}
    if "verified_at" not in existing_otp_cols:
        cursor.execute("ALTER TABLE otp_verifications ADD COLUMN verified_at TEXT DEFAULT ''")


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

    # Populate Sample Regular Customers and Khata Ledger if empty
    cursor.execute("SELECT COUNT(*) FROM customers")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO customers (id, name, phone, address, credit_limit) VALUES
        (1, 'Haji Abdul Rehman', '0300-1234567', 'House 22, Model Town, Lahore', 25000.0),
        (2, 'Chaudhry Akram', '0321-7654321', 'Al-Madina Chowk, Faisal Town, Lahore', 20000.0),
        (3, 'Malik Tariq', '0333-9876543', 'Plot 15, Kot Lakhpat, Lahore', 15000.0),
        (4, 'Mian Shahid', '0345-1122334', 'Main Market, Peco Road, Lahore', 10000.0)
        """)

        cursor.execute("""
        INSERT INTO customer_khata (customer_id, invoice_no, date, item_description, amount, is_settled, settled_at, payment_method, notes) VALUES
        (1, 'INV-1001', '2026-09-02', 'Augmentin 625mg (2 packs), Panadol Extend', 2450.0, 1, '2026-09-05', 'Cash', 'Counter cash settlement'),
        (1, 'INV-1045', '2026-09-08', 'Getryl 2mg (3 boxes), Lipiget 20mg', 3800.0, 0, '', '', 'Monthly chronic prescription'),
        (2, 'INV-1032', '2026-09-06', 'Insulin Mixtard 30, Syringes 100u, Glucometer Strips', 5200.0, 0, '', '', 'Diabetic supplies for father'),
        (2, 'INV-1067', '2026-09-10', 'Nexum 40mg, Concor 5mg', 2850.0, 0, '', '', 'Regular cardiac & stomach dose'),
        (3, 'INV-1054', '2026-09-09', 'Surbex Z (2 bottles), CaC 1000 Plus (2 tubes)', 1650.0, 0, '', '', 'Vitamins & immunity boost'),
        (4, 'INV-1018', '2026-09-04', 'Brufen 400mg, Flagyl 400mg, ORS 10 sachets', 1100.0, 1, '2026-09-07', 'EasyPaisa', 'Paid via EasyPaisa TID: 871923'),
        (4, 'INV-1078', '2026-09-11', 'Panadol CF, Arinac Forte, Lofnac Gel', 1450.0, 0, '', '', 'Flu & muscle ache medicine')
        """)

    conn.commit()
    conn.close()

def log_activity(category: str, action_type: str, title: str, description: str, 
                 staff_name: str = "", amount: float = 0.0, 
                 date_str: str = None, time_str: str = None):
    """
    Logs any real-time operational action (punch, leave, advance, khata, payroll disburse).
    """
    try:
        now = datetime.now()
        d_str = date_str or now.strftime("%Y-%m-%d")
        t_str = time_str or now.strftime("%I:%M:%S %p")
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO activity_logs (category, action_type, title, description, staff_name, amount, date, time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (category, action_type, title, description, staff_name or "", float(amount or 0.0), d_str, t_str))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging activity: {e}")

def sync_today_activities(target_date: str = None):
    """
    Auto-backfills any existing actions for target_date into activity_logs if missing,
    ensuring all of today's attendance, leaves, advances, and payouts show up immediately.
    """
    target_date = target_date or datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if we already have activities for this date
    cursor.execute("SELECT COUNT(*) FROM activity_logs WHERE date = ?", (target_date,))
    existing_count = cursor.fetchone()[0]

    if existing_count == 0:
        # 1. Backfill Attendance Punches & Absents for target_date
        cursor.execute("""
            SELECT a.id, a.staff_id, s.name, a.time_in, a.time_out, a.status, a.late_minutes, a.worked_minutes, a.created_at
            FROM attendance_logs a
            JOIN staff s ON a.staff_id = s.id
            WHERE a.date = ?
            ORDER BY a.time_in ASC, a.id ASC
        """, (target_date,))
        att_rows = cursor.fetchall()

        for row in att_rows:
            s_name = row["name"]
            status = row["status"]
            time_in = row["time_in"]
            time_out = row["time_out"]

            if time_in:
                late_txt = f" (Late by {row['late_minutes']} mins)" if row["late_minutes"] > 0 else " (On-Time)"
                log_activity(
                    category="ATTENDANCE",
                    action_type="PUNCH_IN",
                    title=f"Biometric Punch IN: {s_name}",
                    description=f"Staff punched IN at {time_in}{late_txt} — Shift duty started.",
                    staff_name=s_name,
                    date_str=target_date,
                    time_str=time_in
                )
            elif status == "APPROVED_LEAVE":
                log_activity(
                    category="LEAVE",
                    action_type="LEAVE_APPROVED",
                    title=f"Leave on Roster: {s_name}",
                    description=f"Approved leave scheduled for {target_date}.",
                    staff_name=s_name,
                    date_str=target_date,
                    time_str="09:00:00 AM"
                )
            elif status == "ABSENT":
                log_activity(
                    category="ATTENDANCE",
                    action_type="ABSENT_MARKED",
                    title=f"Absence Recorded: {s_name}",
                    description=f"No punch recorded for shift duty.",
                    staff_name=s_name,
                    date_str=target_date,
                    time_str="09:15:00 AM"
                )

            if time_out:
                h = (row["worked_minutes"] or 0) // 60
                m = (row["worked_minutes"] or 0) % 60
                log_activity(
                    category="ATTENDANCE",
                    action_type="PUNCH_OUT",
                    title=f"Biometric Punch OUT: {s_name}",
                    description=f"Staff punched OUT at {time_out} — Completed {h}h {m}m shift duty.",
                    staff_name=s_name,
                    date_str=target_date,
                    time_str=time_out
                )

        # 2. Backfill Advances/Khata for target_date
        cursor.execute("""
            SELECT a.id, a.staff_id, s.name, a.entry_type, a.amount, a.reason, a.created_at
            FROM advance_salaries a
            JOIN staff s ON a.staff_id = s.id
            WHERE a.date = ?
        """, (target_date,))
        adv_rows = cursor.fetchall()
        for row in adv_rows:
            type_label = "Medicine Credit" if row["entry_type"] == "MEDICINE_CREDIT" else "Cash Advance"
            log_activity(
                category="STAFF_KHATA",
                action_type="ADVANCE_ADDED",
                title=f"Staff Khata ({type_label}): {row['name']}",
                description=f"Rs. {row['amount']:,.2f} issued for {row['reason'] or 'Staff Advance'}",
                staff_name=row["name"],
                amount=row["amount"],
                date_str=target_date,
                time_str="11:30:00 AM"
            )

        # 3. Backfill Customer Khata for target_date
        cursor.execute("""
            SELECT k.id, c.name, k.invoice_no, k.item_description, k.amount, k.is_settled
            FROM customer_khata k
            JOIN customers c ON k.customer_id = c.id
            WHERE k.date = ?
        """, (target_date,))
        ck_rows = cursor.fetchall()
        for row in ck_rows:
            log_activity(
                category="CUSTOMER_KHATA",
                action_type="CUSTOMER_KHATA_ADDED",
                title=f"Customer Credit: {row['name']}",
                description=f"Invoice #{row['invoice_no']} for {row['item_description']}",
                staff_name=row["name"],
                amount=row["amount"],
                date_str=target_date,
                time_str="12:15:00 PM"
            )

    conn.close()

def get_today_activities(target_date: str = None, limit: int = 50, category: str = "ALL"):
    target_date = target_date or datetime.now().strftime("%Y-%m-%d")
    sync_today_activities(target_date)

    conn = get_db_connection()
    cursor = conn.cursor()

    if category and category != "ALL":
        cursor.execute("""
            SELECT * FROM activity_logs 
            WHERE date = ? AND category = ?
            ORDER BY id DESC LIMIT ?
        """, (target_date, category, limit))
    else:
        cursor.execute("""
            SELECT * FROM activity_logs 
            WHERE date = ? 
            ORDER BY id DESC LIMIT ?
        """, (target_date, limit))

    rows = cursor.fetchall()
    activities = [dict(r) for r in rows]

    # Calculate summary counts for badges
    cursor.execute("""
        SELECT category, COUNT(*) as cnt 
        FROM activity_logs 
        WHERE date = ? 
        GROUP BY category
    """, (target_date,))
    cat_counts = {r["category"]: r["cnt"] for r in cursor.fetchall()}

    conn.close()

    return {
        "date": target_date,
        "total_count": len(activities),
        "category_counts": cat_counts,
        "activities": activities
    }

# =====================================================================
# SYSTEM SETTINGS & PIN OTP HELPER FUNCTIONS
# =====================================================================

def get_setting(key: str, default: str = None) -> str:
    """Retrieves a setting value by key."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    """Saves or updates a setting value."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO system_settings (key, value, updated_at) 
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
    """, (key, str(value), now_str))
    conn.commit()
    conn.close()

def get_all_settings() -> dict:
    """Returns all key-value settings as a dictionary."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM system_settings")
    rows = cursor.fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def create_otp_record(staff_id: int, otp_code: str, action: str, target_phone: str, expiry_minutes: int = 5) -> int:
    """Invalidates old pending OTPs and creates a new OTP record. Returns new record ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()
    expires_at = now + timedelta(minutes=expiry_minutes)
    cursor.execute("""
        UPDATE otp_verifications 
        SET is_used = 1 
        WHERE staff_id = ? AND action = ? AND is_used = 0
    """, (staff_id, action))
    cursor.execute("""
        INSERT INTO otp_verifications (staff_id, otp_code, action, target_phone, is_used, attempts, expires_at)
        VALUES (?, ?, ?, ?, 0, 0, ?)
    """, (staff_id, otp_code, action, target_phone, expires_at.strftime("%Y-%m-%d %H:%M:%S")))
    otp_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return otp_id


def mark_otp_notified(otp_id: int) -> bool:
    """
    For OUT checkout: marks the OTP record as 'notified' by setting verified_at
    and is_used=1 when staff clicks the WhatsApp notify-admin button.
    This records the exact notify time for the Admin audit log.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE otp_verifications SET is_used = 1, verified_at = ? WHERE id = ?",
        (now_str, otp_id)
    )
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated

def verify_and_consume_otp(staff_id: int, otp_code: str):
    """
    Validates the provided OTP.
    Returns (True, action, message) if valid, or (False, None, error_message).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        SELECT * FROM otp_verifications
        WHERE staff_id = ? AND is_used = 0
        ORDER BY id DESC LIMIT 1
    """, (staff_id,))
    record = cursor.fetchone()

    if not record:
        conn.close()
        return False, None, "Koi active confirmation code nahi mila. Barah-e-karam dobara PIN enter karein."

    if record["expires_at"] < now_str:
        cursor.execute("UPDATE otp_verifications SET is_used = 1 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        return False, None, "Yeh confirmation code expire ho chuka hai (5 min limit). Barah-e-karam naya code mangwayein."

    if record["attempts"] >= 5:
        cursor.execute("UPDATE otp_verifications SET is_used = 1 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        return False, None, "Bohat zyada ghalat attempts ki gayi hain. Barah-e-karam naya code mangwayein."

    if str(record["otp_code"]).strip() != str(otp_code).strip():
        cursor.execute("UPDATE otp_verifications SET attempts = attempts + 1 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        return False, None, "Ghalat confirmation code! Barah-e-karam check kar ke dobara enter karein."

    # Mark as successfully used with exact verification timestamp
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE otp_verifications SET is_used = 1, verified_at = ? WHERE id = ?", (now_str, record["id"]))
    conn.commit()
    action = record["action"]
    conn.close()
    return True, action, "Confirmation Code verified successfully."

def get_active_otps(limit: int = 10):
    """Returns recently generated active/pending OTPs for real-time admin monitoring."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        SELECT o.*, s.name as staff_name, s.designation, s.phone as staff_phone
        FROM otp_verifications o
        JOIN staff s ON o.staff_id = s.id
        WHERE o.is_used = 0 AND o.expires_at >= ?
        ORDER BY o.id DESC LIMIT ?
    """, (now_str, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_pin_otp_audit_logs(date_str: str = None, limit: int = 100):
    """
    Returns complete PIN vs OTP timing audit log for Admin inspection.
    Enables Admin to verify at the end of the day if PIN and OTP times match.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute("""
        SELECT o.*, s.name as staff_name, s.role, coalesce(nullif(s.designation, ''), s.role) as designation,
               s.phone as staff_phone
        FROM otp_verifications o
        JOIN staff s ON o.staff_id = s.id
        WHERE date(o.created_at) = ? OR o.created_at LIKE ?
        ORDER BY o.id DESC LIMIT ?
    """, (date_str, f"{date_str}%", limit))
    rows = cursor.fetchall()
    conn.close()

    result = []
    now_dt = datetime.now()
    for r in rows:
        item = dict(r)
        created_raw = item.get("created_at") or ""
        verified_raw = item.get("verified_at") or ""
        diff_seconds = None
        diff_str = "Pending OTP"
        status_label = "PENDING"
        
        c_dt = None
        v_dt = None
        if created_raw:
            try:
                c_dt = datetime.strptime(created_raw.split(".")[0], "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        if verified_raw:
            try:
                v_dt = datetime.strptime(verified_raw.split(".")[0], "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        if item.get("is_used") == 1:
            status_label = "VERIFIED"
            if c_dt and v_dt:
                diff_seconds = max(0, int((v_dt - c_dt).total_seconds()))
                if diff_seconds < 60:
                    diff_str = f"⚡ {diff_seconds}s (Same-Time)"
                elif diff_seconds < 120:
                    m = diff_seconds // 60
                    s = diff_seconds % 60
                    diff_str = f"✅ {m}m {s}s"
                else:
                    m = diff_seconds // 60
                    s = diff_seconds % 60
                    diff_str = f"⏱️ {m}m {s}s (Delayed)"
            else:
                diff_str = "⚡ Instant (<1m)"
        else:
            exp_str = item.get("expires_at") or ""
            if exp_str and exp_str < now_dt.strftime("%Y-%m-%d %H:%M:%S"):
                status_label = "EXPIRED"
                diff_str = "⏳ Expired"
            else:
                status_label = "PENDING"
                diff_str = "⏳ Pending"

        item["diff_seconds"] = diff_seconds
        item["diff_str"] = diff_str
        item["audit_status"] = status_label
        result.append(item)
    return result

if __name__ == "__main__":
    init_db()
    print("Mumtaz Pharmacy Attendance Database initialized successfully.")
