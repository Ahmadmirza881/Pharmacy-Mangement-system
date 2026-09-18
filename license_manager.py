"""
Mumtaz Pharmacy - Remote License & Kill-Switch Manager (Google Sheets Integration)
==================================================================================
Provides fail-open, zero-disturbance remote licensing:
1. When OFFLINE: System continues running indefinitely with ZERO interruptions.
2. When ONLINE: Periodically checks developer's Google Sheet CSV in a silent background thread.
3. When BLOCKED by developer in Google Sheet:
   - Sets persistent local lock in database.
   - Locks UI and rejects sensitive API operations.
   - Remains locked even if client unplugs internet or reboots PC.
4. When UNBLOCKED (marked ACTIVE in Google Sheet):
   - Automatically lifts the lock as soon as online verification succeeds.
"""

import threading
import time
import urllib.request
import csv
import io
from datetime import datetime
from database import get_setting, set_setting, log_activity

# Default fallback settings
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSfr_cSKOVos8DntYSABNtZ3H-ZimhfRRP8PMwtFfY_9G2umncm5YAd_0DJHIyGRgyh4OBIMC_0rZFi/pub?output=csv"
DEFAULT_BLOCK_MESSAGE = "Software License Suspended. Please contact developer for renewal."
DEFAULT_DEV_CONTACT = "0316-6868169"
TARGET_PHARMACY_NAME = "Mumtaz Pharmacy"

_monitor_started = False
_lock = threading.Lock()

def get_license_state() -> dict:
    """Returns the current local licensing status without network delay."""
    status = get_setting("license_status", "ACTIVE")
    message = get_setting("license_block_message", DEFAULT_BLOCK_MESSAGE)
    contact = get_setting("license_dev_contact", DEFAULT_DEV_CONTACT)
    last_checked = get_setting("license_last_checked", "Never")
    sheet_url = get_setting("google_sheet_csv_url", DEFAULT_SHEET_URL)
    
    is_blocked = (status.upper() == "BLOCKED")
    return {
        "blocked": is_blocked,
        "status": status.upper(),
        "message": message,
        "developer_contact": contact,
        "last_checked": last_checked,
        "has_sheet_url": bool(sheet_url.strip())
    }

def is_system_blocked() -> bool:
    """Fast check used by endpoints to verify if system is currently locked."""
    status = get_setting("license_status", "ACTIVE")
    return status.upper() == "BLOCKED"

def check_remote_sheet(timeout: int = 5) -> dict:
    """
    Connects to the Google Sheet CSV URL and verifies license status.
    Fail-Open Design: Any network drop, timeout, or DNS failure is quietly ignored.
    """
    sheet_url = get_setting("google_sheet_csv_url", DEFAULT_SHEET_URL).strip()
    if not sheet_url:
        # No URL configured yet; remain in current state without error
        return {"success": True, "message": "No Google Sheet URL configured. Running in local mode."}

    try:
        req = urllib.request.Request(
            sheet_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MumtazPharmacyLicense/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8", errors="ignore")

        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            return {"success": False, "message": "Remote sheet is empty"}

        # Normalize header
        headers = [h.strip().lower() for h in rows[0]]
        pharmacy_idx = -1
        status_idx = -1
        msg_idx = -1
        contact_idx = -1

        for idx, h in enumerate(headers):
            if "pharmacy" in h or "name" in h or "client" in h:
                pharmacy_idx = idx
            elif "status" in h:
                status_idx = idx
            elif "message" in h or "msg" in h or "reason" in h:
                msg_idx = idx
            elif "contact" in h or "phone" in h:
                contact_idx = idx

        # Fallback to column index 0=Name, 1=Status, 2=Message, 3=Contact if headers not detected
        if status_idx == -1 and len(headers) >= 2:
            pharmacy_idx = 0
            status_idx = 1
            msg_idx = 2 if len(headers) > 2 else -1
            contact_idx = 3 if len(headers) > 3 else -1

        # Look for target row
        matched_row = None
        for row in rows[1:]:
            if not row or len(row) <= status_idx:
                continue
            name_val = row[pharmacy_idx].strip().lower() if pharmacy_idx != -1 and len(row) > pharmacy_idx else ""
            if "mumtaz" in name_val or name_val == "all" or len(rows) == 2:
                matched_row = row
                break

        if not matched_row and len(rows) >= 2:
            matched_row = rows[1]  # Take the first data row if only 1 client listed

        if matched_row and status_idx != -1 and len(matched_row) > status_idx:
            remote_status = matched_row[status_idx].strip().upper()
            remote_msg = matched_row[msg_idx].strip() if (msg_idx != -1 and len(matched_row) > msg_idx and matched_row[msg_idx].strip()) else DEFAULT_BLOCK_MESSAGE
            remote_contact = matched_row[contact_idx].strip() if (contact_idx != -1 and len(matched_row) > contact_idx and matched_row[contact_idx].strip()) else DEFAULT_DEV_CONTACT

            current_status = get_setting("license_status", "ACTIVE").upper()

            if "BLOCK" in remote_status or "SUSPEND" in remote_status or "EXPIRE" in remote_status:
                # Developer triggered BLOCK
                set_setting("license_status", "BLOCKED")
                set_setting("license_block_message", remote_msg)
                set_setting("license_dev_contact", remote_contact)
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                set_setting("license_last_checked", now_str)

                if current_status != "BLOCKED":
                    try:
                        log_activity(
                            category="SECURITY",
                            action_type="LICENSE_BLOCKED",
                            title="System License Locked",
                            description=f"Remote lock signal received: {remote_msg}"
                        )
                    except Exception:
                        pass
                return {"success": True, "status": "BLOCKED", "message": remote_msg}

            elif "ACTIVE" in remote_status or "APPROV" in remote_status or "OK" in remote_status:
                # System is ACTIVE
                set_setting("license_status", "ACTIVE")
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                set_setting("license_last_checked", now_str)

                if current_status == "BLOCKED":
                    try:
                        log_activity(
                            category="SECURITY",
                            action_type="LICENSE_RESTORED",
                            title="System License Restored",
                            description="Remote active status verified. Software unlocked."
                        )
                    except Exception:
                        pass
                return {"success": True, "status": "ACTIVE", "message": "License verified active"}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        set_setting("license_last_checked", now_str)
        return {"success": True, "status": "ACTIVE", "message": "Check completed"}

    except Exception as e:
        # FAIL-OPEN: Silent pass. Do not change local status, do not bother the user.
        return {"success": False, "message": f"Network check skipped (offline mode): {str(e)}"}

def _license_worker():
    """Background daemon thread running periodically."""
    # First check after small initial delay
    time.sleep(10)
    check_remote_sheet(timeout=5)

    # Then check every 1 hour (3600 seconds)
    while True:
        try:
            time.sleep(3600)
            check_remote_sheet(timeout=5)
        except Exception:
            pass

def start_license_monitor():
    """Starts the background thread once."""
    global _monitor_started
    with _lock:
        if not _monitor_started:
            t = threading.Thread(target=_license_worker, daemon=True, name="LicenseMonitorThread")
            t.start()
            _monitor_started = True
