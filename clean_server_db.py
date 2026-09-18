"""
Clean dummy data ONLY from the Server deliverable database:
READY_FOR_CLIENT/FOR_MAIN_SERVER_PC/MumtazPharmacy_Server/mumtaz_attendance.db

Leaves the developer's root database untouched!
"""
import sqlite3
import os

DIST_DB = os.path.join(
    os.path.dirname(__file__),
    "READY_FOR_CLIENT",
    "FOR_MAIN_SERVER_PC",
    "MumtazPharmacy_Server",
    "mumtaz_attendance.db"
)

def clean_database():
    if not os.path.exists(DIST_DB):
        print(f"[ERROR] Database file not found at: {DIST_DB}")
        return

    print("Target DB to clean:", DIST_DB)
    conn = sqlite3.connect(DIST_DB)
    cursor = conn.cursor()

    # Tables to completely empty for the client's fresh production install
    tables_to_clear = [
        "staff",
        "attendance_logs",
        "leaves",
        "advance_salaries",
        "payroll_records",
        "customers",
        "customer_khata",
        "staff_approval_requests",
        "activity_logs",
        "otp_verifications",
        "deliveries",
        "leave_requests"
    ]

    for t in tables_to_clear:
        try:
            cursor.execute(f"DELETE FROM {t}")
            print(f" [CLEANED] Table '{t}' wiped.")
        except sqlite3.OperationalError as e:
            print(f" [SKIP] Table '{t}' ({e})")

    # Reset auto-increment counters in sqlite_sequence
    try:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('" + "','".join(tables_to_clear) + "')")
    except Exception:
        pass

    # Verify shifts and system_settings are preserved
    cursor.execute("SELECT COUNT(*) FROM shifts")
    shifts_count = cursor.fetchone()[0]

    cursor.execute("SELECT key, value FROM system_settings WHERE key IN ('google_sheet_csv_url', 'license_status', 'pharmacy_name')")
    settings = cursor.fetchall()

    conn.commit()
    conn.close()

    print("\n" + "=" * 60)
    print(" [SUCCESS] SERVER DATABASE IS NOW 100% CLEAN & READY FOR CLIENT!")
    print(f" Shifts preserved: {shifts_count} shifts")
    print(f" Settings preserved: {settings}")
    print("=" * 60)

if __name__ == "__main__":
    clean_database()
