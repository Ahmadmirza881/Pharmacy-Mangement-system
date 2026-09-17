"""
Mumtaz Pharmacy - Database Layer (SQLite)
Handles local persistent storage for staff, shifts, biometric attendance logs,
advance salary records, and month-end payroll sheets.
"""

import sqlite3
import os
import uuid
import re
from datetime import datetime, date, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "mumtaz_attendance.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -64000")   # 64MB in-memory query cache
    conn.execute("PRAGMA temp_store = MEMORY")   # Store temp tables/sorts in RAM
    conn.execute("PRAGMA mmap_size = 268435456") # 256MB memory-mapped I/O
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
    if "is_temp_delivery_staff" not in existing_staff_cols:
        cursor.execute("ALTER TABLE staff ADD COLUMN is_temp_delivery_staff INTEGER DEFAULT 0")
    if "source_note" not in existing_staff_cols:
        cursor.execute("ALTER TABLE staff ADD COLUMN source_note TEXT DEFAULT ''")

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
        added_by TEXT DEFAULT 'Admin',
        approval_status TEXT DEFAULT 'APPROVED',
        approved_by TEXT DEFAULT '',
        approved_at TEXT DEFAULT '',
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
        added_by TEXT DEFAULT 'Admin',
        approval_status TEXT DEFAULT 'APPROVED',
        approved_by TEXT DEFAULT '',
        approved_at TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers (id)
    );
    """)

    # 8b. Unified Staff Approval Requests Table (New Customers, Credit Purchases, Settlements)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff_approval_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_type TEXT NOT NULL,
        customer_id INTEGER,
        customer_name TEXT,
        reference_id INTEGER,
        amount REAL DEFAULT 0.0,
        payment_method TEXT DEFAULT 'Cash',
        details TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        payload_json TEXT DEFAULT '',
        status TEXT DEFAULT 'PENDING',
        added_by TEXT DEFAULT 'Staff (Counter)',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        approved_by TEXT DEFAULT '',
        approved_at TEXT DEFAULT ''
    );
    """)

    cursor.execute("PRAGMA table_info(customers)")
    existing_cust_cols = {row[1] for row in cursor.fetchall()}
    if "added_by" not in existing_cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN added_by TEXT DEFAULT 'Admin'")
    if "approval_status" not in existing_cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN approval_status TEXT DEFAULT 'APPROVED'")
    if "approved_by" not in existing_cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN approved_by TEXT DEFAULT ''")
    if "approved_at" not in existing_cust_cols:
        cursor.execute("ALTER TABLE customers ADD COLUMN approved_at TEXT DEFAULT ''")

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
    if "added_by" not in existing_ck_cols:
        cursor.execute("ALTER TABLE customer_khata ADD COLUMN added_by TEXT DEFAULT 'Admin'")
    if "approval_status" not in existing_ck_cols:
        cursor.execute("ALTER TABLE customer_khata ADD COLUMN approval_status TEXT DEFAULT 'APPROVED'")
    if "approved_by" not in existing_ck_cols:
        cursor.execute("ALTER TABLE customer_khata ADD COLUMN approved_by TEXT DEFAULT ''")
    if "approved_at" not in existing_ck_cols:
        cursor.execute("ALTER TABLE customer_khata ADD COLUMN approved_at TEXT DEFAULT ''")

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
        "admin_whatsapp_number": "03166868169",
        "admin_name": "Pharmacy Owner / Manager",
        "pharmacy_name": "Mumtaz Pharmacy",
        "otp_expiry_minutes": "5",
        "admin_master_pin": "1370",
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
    if "token" not in existing_otp_cols:
        cursor.execute("ALTER TABLE otp_verifications ADD COLUMN token TEXT DEFAULT ''")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_otp_token ON otp_verifications(token)")
    if "master_pin_attempts" not in existing_otp_cols:
        cursor.execute("ALTER TABLE otp_verifications ADD COLUMN master_pin_attempts INTEGER DEFAULT 0")

    # 12. Deliveries Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER,
        delivery_person_name TEXT NOT NULL,
        delivery_person_phone TEXT NOT NULL,
        is_guest_delivery INTEGER DEFAULT 0,
        customer_name TEXT NOT NULL,
        customer_phone TEXT NOT NULL,
        customer_address TEXT NOT NULL,
        invoice_no TEXT NOT NULL,
        bill_amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'Cash on Delivery',
        notes TEXT DEFAULT '',
        status TEXT DEFAULT 'PENDING',       -- PENDING, APPROVED, OUT_FOR_DELIVERY, DELIVERED, REJECTED, CANCELLED
        approval_status TEXT DEFAULT 'PENDING',
        approved_by TEXT DEFAULT '',
        approved_at TEXT DEFAULT '',
        rejection_reason TEXT DEFAULT '',
        dispatch_pin_verified INTEGER DEFAULT 1,
        admin_wa_sent INTEGER DEFAULT 0,
        customer_wa_sent INTEGER DEFAULT 0,
        return_pin_verified INTEGER DEFAULT 0,
        return_wa_sent INTEGER DEFAULT 0,
        dispatched_at TEXT DEFAULT '',
        delivered_at TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (staff_id) REFERENCES staff (id)
    );
    """)

    cursor.execute("PRAGMA table_info(deliveries)")
    existing_deliv_cols = {row[1] for row in cursor.fetchall()}
    if "rejection_reason" not in existing_deliv_cols:
        cursor.execute("ALTER TABLE deliveries ADD COLUMN rejection_reason TEXT DEFAULT ''")
    if "return_pin_verified" not in existing_deliv_cols:
        cursor.execute("ALTER TABLE deliveries ADD COLUMN return_pin_verified INTEGER DEFAULT 0")
    if "return_wa_sent" not in existing_deliv_cols:
        cursor.execute("ALTER TABLE deliveries ADD COLUMN return_wa_sent INTEGER DEFAULT 0")

    # High-Performance Indexes for Zero Table-Scans & Instant Query Processing
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_status ON deliveries(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_approval ON deliveries(approval_status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_created ON deliveries(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_invoice ON deliveries(invoice_no)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_staff ON deliveries(staff_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance_logs(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_staff_date ON attendance_logs(staff_id, date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_status ON attendance_logs(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leaves_staff_date ON leaves(staff_id, date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_advances_staff_settled ON advance_salaries(staff_id, is_settled, date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_khata_cust_date ON customer_khata(customer_id, date DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customer_khata_settled ON customer_khata(is_settled)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_logs(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_date ON activity_logs(date, category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_staff_pin ON staff(pin, is_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_staff_phone ON staff(phone)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_otp_token ON otp_verifications(token)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_otp_staff_action ON otp_verifications(staff_id, action, is_used)")

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

def get_admin_master_pin() -> str:
    """Retrieves current Admin Master PIN, defaulting to 1370."""
    return get_setting("admin_master_pin", "1370") or "1370"

def set_admin_master_pin(new_pin: str):
    """Saves or updates Admin Master PIN."""
    set_setting("admin_master_pin", str(new_pin).strip())

def create_otp_record(staff_id: int, otp_code: str, action: str, target_phone: str, expiry_minutes: int = 5, token: str = None):
    """Invalidates old pending OTPs and creates a new OTP record with secure token. Returns (new record ID, token)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_at = now + timedelta(minutes=expiry_minutes)
    if not token:
        token = f"tok_{uuid.uuid4().hex[:12]}"
    cursor.execute("""
        UPDATE otp_verifications 
        SET is_used = 1 
        WHERE staff_id = ? AND action = ? AND is_used = 0
    """, (staff_id, action))
    cursor.execute("""
        INSERT INTO otp_verifications (staff_id, otp_code, action, target_phone, token, is_used, attempts, master_pin_attempts, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
    """, (staff_id, otp_code, action, target_phone, token, expires_at.strftime("%Y-%m-%d %H:%M:%S"), now_str))
    otp_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return otp_id, token

def get_otp_by_token(token: str):
    """Retrieves OTP verification record by unique link token."""
    if not token:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.*, s.name as staff_name, coalesce(nullif(s.designation, ''), s.role) as designation
        FROM otp_verifications o
        JOIN staff s ON o.staff_id = s.id
        WHERE o.token = ?
    """, (token,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def verify_and_reveal_otp_by_token(token: str, master_pin: str):
    """
    Validates token and Admin Master PIN to reveal OTP code.
    Returns (success: bool, otp_code: str|None, record_info: dict|None, message: str).
    """
    if not token:
        return False, None, None, "Invalid link token."

    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        SELECT o.*, s.name as staff_name, coalesce(nullif(s.designation, ''), s.role) as designation
        FROM otp_verifications o
        JOIN staff s ON o.staff_id = s.id
        WHERE o.token = ?
    """, (token,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False, None, None, "Yeh link ghair-mootabar (invalid) hai ya nahi mila."

    record = dict(row)

    if record["is_used"] == 1:
        conn.close()
        return False, None, record, "Yeh link pehle hi istemal ho chuka hai."

    if record["expires_at"] < now_str:
        cursor.execute("UPDATE otp_verifications SET is_used = 1 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        return False, None, record, "Yeh link expire ho chuka hai (5 min limit)."

    current_attempts = record.get("master_pin_attempts") or 0
    if current_attempts >= 3:
        cursor.execute("UPDATE otp_verifications SET is_used = 1 WHERE id = ?", (record["id"],))
        conn.commit()
        conn.close()
        return False, None, record, "Bohat zyada ghalat Admin Master PIN enter kiye gaye hain. Link disabled."

    admin_pin = get_admin_master_pin()
    if str(master_pin).strip() != str(admin_pin).strip():
        new_attempts = current_attempts + 1
        if new_attempts >= 3:
            cursor.execute("UPDATE otp_verifications SET master_pin_attempts = ?, is_used = 1 WHERE id = ?", (new_attempts, record["id"]))
            conn.commit()
            conn.close()
            return False, None, record, "Ghalat Admin Master PIN! Max 3 attempts poori ho gayi hain. Link disabled."
        else:
            cursor.execute("UPDATE otp_verifications SET master_pin_attempts = ? WHERE id = ?", (new_attempts, record["id"]))
            conn.commit()
            conn.close()
            remaining = 3 - new_attempts
            return False, None, record, f"Ghalat Admin Master PIN! Dobara koshish karein ({remaining} attempts baqi)."

    # Success: Admin Master PIN matches!
    conn.close()
    return True, record["otp_code"], record, "Admin Master PIN verified successfully."


def mark_otp_notified(otp_id: int) -> bool:
    """
    For OUT checkout: marks the OTP record as 'notified' by setting verified_at
    and is_used=1 when staff clicks the WhatsApp notify-admin button.
    Safety: only updates if still is_used=0 (not already consumed) and created today.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        """UPDATE otp_verifications 
           SET is_used = 1, verified_at = ? 
           WHERE id = ? AND is_used = 0 AND date(created_at) = ?""",
        (now_str, otp_id, today_str)
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
                elif diff_seconds < 300:
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

# =====================================================================
# HOME DELIVERY SYSTEM DATABASE HELPERS
# =====================================================================

def register_or_get_delivery_staff(name: str, phone: str) -> dict:
    """
    Finds existing staff by phone or creates a new temporary delivery staff record.
    PIN is automatically set to the last 4 digits of the phone number.
    Tagged with is_temp_delivery_staff=1 so Admin can review in Staff Tab.
    """
    clean_digits = re.sub(r'[^0-9]', '', phone or '')
    default_pin = clean_digits[-4:] if len(clean_digits) >= 4 else "1234"
    clean_phone = phone.strip()
    clean_name = name.strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if staff with this phone already exists
    phone_candidates = [clean_phone]
    if len(clean_digits) >= 10:
        phone_candidates.append(f"0{clean_digits[-10:]}")
        phone_candidates.append(clean_digits[-10:])
    placeholders = " OR ".join(["phone = ?" for _ in phone_candidates])
    cursor.execute(f"SELECT * FROM staff WHERE {placeholders} LIMIT 1", tuple(phone_candidates))
    existing = cursor.fetchone()

    if existing:
        res = dict(existing)
        conn.close()
        return {
            "staff_id": res["id"],
            "name": res["name"],
            "phone": res["phone"],
            "pin": res["pin"] or default_pin,
            "is_new": False,
            "is_temp": bool(res.get("is_temp_delivery_staff", 0))
        }

    # Fetch default shift id (Morning shift or id 1)
    cursor.execute("SELECT id FROM shifts ORDER BY id ASC LIMIT 1")
    shift_row = cursor.fetchone()
    shift_id = shift_row["id"] if shift_row else 1

    cursor.execute("""
        INSERT INTO staff (
            name, phone, role, designation, monthly_salary, shift_id,
            pin, is_temp_delivery_staff, source_note, is_active
        ) VALUES (?, ?, 'Delivery Staff', 'Delivery Rider (Temporary)', 0.0, ?, ?, 1, 'Auto-registered via Delivery Portal', 1)
    """, (clean_name, clean_phone, shift_id, default_pin))
    new_staff_id = cursor.lastrowid
    conn.commit()
    conn.close()

    log_activity(
        category="STAFF",
        action_type="STAFF_ADDED",
        title=f"New Delivery Staff: {clean_name}",
        description=f"Auto-registered via Delivery Form • PIN: {default_pin} • Review in Staff Tab",
        staff_name=clean_name
    )

    return {
        "staff_id": new_staff_id,
        "name": clean_name,
        "phone": clean_phone,
        "pin": default_pin,
        "is_new": True,
        "is_temp": True
    }

def get_staff_by_id(staff_id: int) -> dict:
    """Returns single staff record dictionary by staff ID."""
    if not staff_id:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM staff WHERE id = ?", (staff_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def verify_rider_pin(staff_id: int = None, phone: str = None, pin: str = "") -> tuple:
    """Verifies 4-digit PIN against the staff record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if staff_id:
        cursor.execute("SELECT id, name, pin, is_active FROM staff WHERE id = ?", (staff_id,))
    elif phone:
        clean_phone = phone.strip()
        clean_digits = re.sub(r'[^0-9]', '', clean_phone)
        cursor.execute("SELECT id, name, pin, is_active FROM staff WHERE phone = ? OR phone = ?", 
                       (clean_phone, f"0{clean_digits[-10:]}" if len(clean_digits) >= 10 else clean_phone))
    else:
        conn.close()
        return False, "Staff ID or phone required"
    
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False, "Rider staff record not found"
    if not row["is_active"]:
        return False, "Staff member is inactive"
    
    actual_pin = str(row["pin"] or "").strip()
    provided_pin = str(pin or "").strip()
    if actual_pin and actual_pin == provided_pin:
        return True, "PIN verified successfully"
    return False, "Invalid 4-digit PIN for selected rider"

def get_delivery_by_id(delivery_id: int) -> dict:
    """Returns single delivery with joined staff details and rider aliases."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.*, 
               s.name as staff_name,
               s.role as staff_role,
               s.designation as staff_designation,
               s.is_temp_delivery_staff
        FROM deliveries d
        LEFT JOIN staff s ON d.staff_id = s.id
        WHERE d.id = ?
    """, (delivery_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if not d.get("rider_name"):
        d["rider_name"] = d.get("delivery_person_name") or d.get("staff_name") or "Rider"
    if not d.get("rider_phone"):
        d["rider_phone"] = d.get("delivery_person_phone") or ""
    if not d.get("delivery_address"):
        d["delivery_address"] = d.get("customer_address") or ""
    if not d.get("customer_address"):
        d["customer_address"] = d.get("delivery_address") or ""
    if d.get("total_amount") is None and d.get("bill_amount") is not None:
        d["total_amount"] = d.get("bill_amount")
    if d.get("bill_amount") is None and d.get("total_amount") is not None:
        d["bill_amount"] = d.get("total_amount")
    return d

def create_delivery(
    staff_id: int,
    delivery_person_name: str,
    delivery_person_phone: str,
    customer_name: str,
    customer_phone: str,
    customer_address: str,
    invoice_no: str,
    bill_amount: float,
    payment_method: str = "Cash on Delivery",
    notes: str = "",
    is_guest_delivery: int = 0,
    dispatch_pin_verified: int = 1,
    admin_wa_sent: int = 1,
    customer_wa_sent: int = 1,
    initial_status: str = "OUT_FOR_DELIVERY"
) -> dict:
    """Inserts a new delivery order. Dispatched with initial_status (default OUT_FOR_DELIVERY) and approval_status PENDING."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO deliveries (
            staff_id, delivery_person_name, delivery_person_phone, is_guest_delivery,
            customer_name, customer_phone, customer_address, invoice_no, bill_amount,
            payment_method, notes, status, approval_status, dispatch_pin_verified,
            admin_wa_sent, customer_wa_sent, return_pin_verified, return_wa_sent,
            dispatched_at, delivered_at
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, 'PENDING', ?,
            ?, ?, 0, 0,
            ?, ''
        )
    """, (
        staff_id, delivery_person_name, delivery_person_phone, is_guest_delivery,
        customer_name, customer_phone, customer_address, invoice_no, float(bill_amount or 0.0),
        payment_method, notes, initial_status, dispatch_pin_verified,
        admin_wa_sent, customer_wa_sent,
        now_str
    ))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()

    log_activity(
        category="DELIVERY",
        action_type="DISPATCHED",
        title=f"Delivery Dispatched: {invoice_no}",
        description=f"Rider {delivery_person_name} dispatched to {customer_name} • Rs. {float(bill_amount or 0.0):,.0f} ({payment_method})",
        staff_name=delivery_person_name,
        amount=float(bill_amount or 0.0)
    )

    return get_delivery_by_id(new_id)

def confirm_delivery_dispatch(delivery_id: int) -> dict:
    """Confirms WhatsApp alerts sent and transitions delivery status to OUT_FOR_DELIVERY."""
    deliv = get_delivery_by_id(delivery_id)
    if not deliv:
        raise ValueError("Delivery record not found")
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE deliveries
        SET status = 'OUT_FOR_DELIVERY',
            dispatched_at = CASE WHEN dispatched_at IS NULL OR dispatched_at = '' THEN ? ELSE dispatched_at END,
            admin_wa_sent = 1,
            customer_wa_sent = 1
        WHERE id = ?
    """, (now_str, delivery_id))
    conn.commit()
    conn.close()
    return get_delivery_by_id(delivery_id)

def complete_delivery_return(delivery_id: int, rider_pin: str, return_wa_sent: int = 1) -> dict:
    """Verifies rider PIN and marks delivery as PENDING_RETURN (or DELIVERED) while leaving financial approval_status as PENDING."""
    deliv = get_delivery_by_id(delivery_id)
    if not deliv:
        raise ValueError("Delivery record not found")
    
    if deliv.get("status") == "DELIVERED":
        return deliv

    staff_id = deliv.get("staff_id")
    if staff_id:
        ok, msg = verify_rider_pin(staff_id=staff_id, pin=rider_pin)
        if not ok:
            raise ValueError(msg)
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE deliveries
        SET status = 'PENDING_RETURN',
            delivered_at = ?,
            return_pin_verified = 1,
            return_wa_sent = ?
        WHERE id = ?
    """, (now_str, return_wa_sent, delivery_id))
    conn.commit()
    conn.close()

    return get_delivery_by_id(delivery_id)

def confirm_delivery_return(delivery_id: int) -> dict:
    """Confirms return alert sent and updates status to DELIVERED."""
    deliv = get_delivery_by_id(delivery_id)
    if not deliv:
        raise ValueError("Delivery record not found")
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE deliveries
        SET status = 'DELIVERED',
            delivered_at = CASE WHEN delivered_at IS NULL OR delivered_at = '' THEN ? ELSE delivered_at END,
            return_pin_verified = 1,
            return_wa_sent = 1
        WHERE id = ?
    """, (now_str, delivery_id))
    conn.commit()
    conn.close()

    log_activity(
        category="DELIVERY",
        action_type="DELIVERED",
        title=f"Delivery Returned: {deliv['invoice_no']}",
        description=f"Rider {deliv['delivery_person_name']} returned • Invoice {deliv['invoice_no']} • Cash Collected: Rs. {float(deliv.get('bill_amount', 0)):,.0f}",
        staff_name=deliv["delivery_person_name"],
        amount=float(deliv.get("bill_amount", 0))
    )

    return get_delivery_by_id(delivery_id)

def reconcile_delivery(delivery_id: int, action: str, approved_by: str = "Admin", rejection_reason: str = "") -> dict:
    """Admin End-of-Day audit reconciliation: marks APPROVED or REJECTED with reason."""
    deliv = get_delivery_by_id(delivery_id)
    if not deliv:
        raise ValueError("Delivery record not found")
    
    action_upper = action.upper().strip()
    if action_upper not in ["APPROVE", "REJECT", "REOPEN"]:
        raise ValueError("Invalid action. Must be APPROVE, REJECT, or REOPEN")
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if action_upper == "APPROVE":
        new_approval_status = "APPROVED"
        clean_reason = ""
    elif action_upper == "REJECT":
        new_approval_status = "REJECTED"
        clean_reason = rejection_reason.strip()
    else:  # REOPEN
        new_approval_status = "PENDING"
        clean_reason = ""
        approved_by = None
        now_str = None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE deliveries
        SET approval_status = ?,
            approved_by = ?,
            approved_at = ?,
            rejection_reason = ?
        WHERE id = ?
    """, (new_approval_status, approved_by, now_str, clean_reason, delivery_id))
    conn.commit()
    conn.close()

    action_text = "Approved" if new_approval_status == "APPROVED" else f"Rejected ({clean_reason})"
    log_activity(
        category="DELIVERY",
        action_type=f"RECONCILE_{new_approval_status}",
        title=f"Delivery {new_approval_status.title()}: {deliv['invoice_no']}",
        description=f"Admin {approved_by} marked {action_text} for Invoice #{deliv['invoice_no']} • Rs. {float(deliv.get('bill_amount', 0)):,.0f}",
        staff_name=deliv["delivery_person_name"],
        amount=float(deliv.get("bill_amount", 0))
    )

    return get_delivery_by_id(delivery_id)

DEFAULT_WA_TEMPLATES = {
    "admin_dispatch": "🚀 *MUMTAZ PHARMACY — ORDER DISPATCHED*\n━━━━━━━━━━━━━━━━━━━━\n🧾 *Invoice:* #{invoice}\n💰 *Bill Amount:* Rs. {amount} ({payment_method})\n👤 *Customer:* {customer_name} ({customer_phone})\n📍 *Address:* {address}\n🛵 *Rider:* {rider_name} ({rider_phone})\n⏰ *Dispatched At:* {time}\n{notes}\n━━━━━━━━━━━━━━━━━━━━\n⚠️ *Admin Audit:* Operational OUT_FOR_DELIVERY • Pending End-of-Day cash reconciliation.",
    "customer_dispatch": "📦 *MUMTAZ PHARMACY — YOUR ORDER IS ON THE WAY!*\n━━━━━━━━━━━━━━━━━━━━\nDear *{customer_name}*,\nYour medicine / pharmacy order has been dispatched.\n\n🧾 *Invoice:* #{invoice}\n💰 *Amount Payable:* Rs. {amount} ({payment_method})\n🛵 *Delivery Rider:* {rider_name}\n📞 *Rider Contact:* {rider_phone}\n\nOur rider will arrive shortly. Please have the exact cash ready if paying on delivery.\nThank you for choosing Mumtaz Pharmacy! 🏥\n📍 Model Town, Lahore",
    "admin_return": "✅ *MUMTAZ PHARMACY — RIDER RETURN CONFIRMATION*\n━━━━━━━━━━━━━━━━━━━━\n🛵 *Rider:* {rider_name} has returned to the pharmacy.\n🧾 *Invoice:* #{invoice}\n👤 *Customer:* {customer_name}\n💵 *Cash Collected:* Rs. {amount}\n⏰ *Return Time:* {time}\n━━━━━━━━━━━━━━━━━━━━\n📋 *Status:* Operational DELIVERED • Please verify hisaab & click Approve in Admin Portal."
}

def get_delivery_wa_templates() -> dict:
    """Returns dict of WhatsApp message templates from settings table or defaults."""
    return {
        "admin_dispatch": get_setting("wa_template_admin_dispatch", DEFAULT_WA_TEMPLATES["admin_dispatch"]),
        "customer_dispatch": get_setting("wa_template_customer_dispatch", DEFAULT_WA_TEMPLATES["customer_dispatch"]),
        "admin_return": get_setting("wa_template_admin_return", DEFAULT_WA_TEMPLATES["admin_return"])
    }

def save_delivery_wa_templates(templates: dict) -> dict:
    """Saves custom WhatsApp message templates into settings table."""
    if "admin_dispatch" in templates and templates["admin_dispatch"] is not None:
        set_setting("wa_template_admin_dispatch", str(templates["admin_dispatch"]).strip())
    if "customer_dispatch" in templates and templates["customer_dispatch"] is not None:
        set_setting("wa_template_customer_dispatch", str(templates["customer_dispatch"]).strip())
    if "admin_return" in templates and templates["admin_return"] is not None:
        set_setting("wa_template_admin_return", str(templates["admin_return"]).strip())
    return get_delivery_wa_templates()

def get_deliveries_list(
    status: str = None, 
    approval_status: str = None,
    date_str: str = None, 
    search: str = None, 
    limit: int = 200
) -> list:
    """Returns list of deliveries with optional filters for operational status, approval status, date, and search."""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT d.*, 
               s.name as staff_name,
               s.role as staff_role,
               s.designation as staff_designation,
               s.is_temp_delivery_staff
        FROM deliveries d
        LEFT JOIN staff s ON d.staff_id = s.id
        WHERE 1=1
    """
    params = []

    if status and status.upper() != "ALL":
        query += " AND d.status = ?"
        params.append(status.upper())

    if approval_status and approval_status.upper() != "ALL":
        query += " AND d.approval_status = ?"
        params.append(approval_status.upper())

    if date_str:
        query += " AND (date(d.created_at) = ? OR d.created_at LIKE ?)"
        params.extend([date_str, f"{date_str}%"])

    if search:
        s_pattern = f"%{search.strip()}%"
        query += " AND (d.invoice_no LIKE ? OR d.customer_name LIKE ? OR d.customer_phone LIKE ? OR d.delivery_person_name LIKE ? OR d.customer_address LIKE ?)"
        params.extend([s_pattern, s_pattern, s_pattern, s_pattern, s_pattern])

    query += " ORDER BY d.id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    res = []
    for r in rows:
        d = dict(r)
        if not d.get("rider_name"):
            d["rider_name"] = d.get("delivery_person_name") or d.get("staff_name") or "Rider"
        if not d.get("rider_phone"):
            d["rider_phone"] = d.get("delivery_person_phone") or ""
        if not d.get("delivery_address"):
            d["delivery_address"] = d.get("customer_address") or ""
        if not d.get("customer_address"):
            d["customer_address"] = d.get("delivery_address") or ""
        if d.get("total_amount") is None and d.get("bill_amount") is not None:
            d["total_amount"] = d.get("bill_amount")
        if d.get("bill_amount") is None and d.get("total_amount") is not None:
            d["bill_amount"] = d.get("total_amount")
        res.append(d)
    return res

def get_active_deliveries_for_return() -> list:
    """Returns all deliveries currently OUT_FOR_DELIVERY waiting for rider return."""
    return get_deliveries_list(status="OUT_FOR_DELIVERY", limit=100)

def get_delivery_stats_today(date_str: str = None) -> dict:
    """Returns aggregated KPIs for today's deliveries."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            COUNT(*) as total_today,
            SUM(CASE WHEN status = 'OUT_FOR_DELIVERY' THEN 1 ELSE 0 END) as out_for_delivery,
            SUM(CASE WHEN status = 'DELIVERED' THEN 1 ELSE 0 END) as delivered_today,
            SUM(CASE WHEN approval_status = 'PENDING' THEN 1 ELSE 0 END) as pending_approval,
            SUM(CASE WHEN approval_status = 'APPROVED' THEN 1 ELSE 0 END) as approved_today,
            SUM(CASE WHEN approval_status = 'REJECTED' THEN 1 ELSE 0 END) as rejected_today,
            COALESCE(SUM(CASE WHEN approval_status = 'APPROVED' THEN bill_amount ELSE 0 END), 0) as total_reconciled_cash,
            COALESCE(SUM(CASE WHEN status = 'DELIVERED' THEN bill_amount ELSE 0 END), 0) as total_delivered_amount,
            COALESCE(SUM(bill_amount), 0) as total_order_amount
        FROM deliveries
        WHERE date(created_at) = ? OR created_at LIKE ?
    """, (date_str, f"{date_str}%"))

    row = cursor.fetchone()
    conn.close()

    if row:
        res = dict(row)
        for k in res:
            if res[k] is None:
                res[k] = 0
        return res
    return {
        "total_today": 0, "out_for_delivery": 0, "delivered_today": 0,
        "pending_approval": 0, "approved_today": 0, "rejected_today": 0,
        "total_reconciled_cash": 0.0, "total_delivered_amount": 0.0, "total_order_amount": 0.0
    }

def convert_temp_rider_to_permanent(
    staff_id: int, 
    designation: str = "Delivery Incharge", 
    monthly_salary: float = 0.0, 
    shift_id: int = 1, 
    cnic: str = "", 
    address: str = ""
) -> dict:
    """Converts a temporary rider into permanent staff."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE staff
        SET is_temp_delivery_staff = 0,
            designation = ?,
            monthly_salary = ?,
            shift_id = ?,
            cnic = COALESCE(NULLIF(?, ''), cnic),
            address = COALESCE(NULLIF(?, ''), address)
        WHERE id = ?
    """, (designation, monthly_salary, shift_id, cnic, address, staff_id))
    conn.commit()
    cursor.execute("SELECT * FROM staff WHERE id = ?", (staff_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        log_activity(
            category="STAFF",
            action_type="STAFF_UPDATED",
            title=f"Staff Made Permanent: {row['name']}",
            description=f"Converted from Temporary Rider to {designation} • Monthly Salary: Rs. {monthly_salary:,.0f}",
            staff_name=row['name']
        )
        return dict(row)
    return {}

if __name__ == "__main__":
    init_db()
    print("Mumtaz Pharmacy Attendance Database initialized successfully.")

