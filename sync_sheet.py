"""
Update Google Sheet URL in Database and Sync Immediately
"""
import sqlite3
import os
import shutil
from database import set_setting, get_setting
import license_manager

USER_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSfr_cSKOVos8DntYSABNtZ3H-ZimhfRRP8PMwtFfY_9G2umncm5YAd_0DJHIyGRgyh4OBIMC_0rZFi/pub?output=csv"

def update_and_sync():
    print("[1/3] Setting Google Sheet URL in database...")
    set_setting("google_sheet_csv_url", USER_URL)
    print("URL set to:", get_setting("google_sheet_csv_url"))

    print("\n[2/3] Checking Google Sheet live now...")
    res = license_manager.check_remote_sheet(timeout=8)
    print("Sync Result:", res)

    state = license_manager.get_license_state()
    print("\n[3/3] Current System State:")
    print("  -> Status:", state.get("status"))
    print("  -> Blocked?:", state.get("blocked"))
    print("  -> Message:", state.get("message"))

    # Also copy updated database to READY_FOR_CLIENT folder
    dist_db = os.path.join(os.path.dirname(__file__), "READY_FOR_CLIENT", "FOR_MAIN_SERVER_PC", "MumtazPharmacy_Server", "mumtaz_attendance.db")
    src_db = os.path.join(os.path.dirname(__file__), "mumtaz_attendance.db")
    if os.path.exists(src_db) and os.path.exists(os.path.dirname(dist_db)):
        shutil.copy2(src_db, dist_db)
        print("\n[OK] Updated database copied to READY_FOR_CLIENT folder as well!")

if __name__ == "__main__":
    update_and_sync()
