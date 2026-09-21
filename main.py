"""
Mumtaz Pharmacy - Biometric Staff Attendance & Payroll API Server
FastAPI application providing endpoints for biometric punches, live roster,
shift scheduling, staff advance khata, and 1-click month-end payroll.
"""

from fastapi import FastAPI, HTTPException, Query, File, UploadFile, Response, Body
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta
import os
import io
import openpyxl
import calendar
import re
import urllib.parse
import random
import json

from database import (
    init_db, get_db_connection, log_activity, get_today_activities,
    get_setting, set_setting, get_all_settings, create_otp_record,
    verify_and_consume_otp, get_active_otps, get_pin_otp_audit_logs,
    mark_otp_notified, get_admin_master_pin, set_admin_master_pin,
    verify_and_reveal_otp_by_token, get_otp_by_token,
    register_or_get_delivery_staff, verify_rider_pin, get_delivery_by_id, get_staff_by_id,
    create_delivery, confirm_delivery_dispatch, complete_delivery_return, confirm_delivery_return,
    reconcile_delivery, get_deliveries_list, get_active_deliveries_for_return,
    get_delivery_stats_today, convert_temp_rider_to_permanent,
    get_delivery_wa_templates, save_delivery_wa_templates,
    create_leave_request, get_leave_requests_by_staff_pin, get_pending_leave_requests, review_leave_request,
    reassign_customer_staff, reassign_khata_bill_staff
)
from payroll_engine import process_punch, calculate_monthly_payroll, calculate_custom_range_payroll
from biometric_service import biometric_service
from whatsapp_service import whatsapp_service
from license_manager import get_license_state, is_system_blocked, check_remote_sheet, start_license_monitor

from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

app = FastAPI(title="Mumtaz Pharmacy Attendance & Payroll System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enable high-speed compression for HTML, JS, JSON responses (>1KB)
app.add_middleware(GZipMiddleware, minimum_size=1000)

class LicenseEnforcementMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Allow static files, home page, and license API endpoints even if locked
        if path.startswith("/static") or path == "/" or path.startswith("/api/license"):
            return await call_next(request)

        # If system is blocked by developer, reject mutating requests
        if request.method in ["POST", "PUT", "DELETE", "PATCH"] and is_system_blocked():
            license_info = get_license_state()
            return JSONResponse(
                status_code=403,
                content={
                    "detail": license_info.get("message", "System License Locked"),
                    "license_blocked": True,
                    "developer_contact": license_info.get("developer_contact", "")
                }
            )
        return await call_next(request)

app.add_middleware(LicenseEnforcementMiddleware)

# Startup: Initialize DB and Remote License Monitor
@app.on_event("startup")
def on_startup():
    init_db()
    start_license_monitor()

# --- Request Models ---
class PunchRequest(BaseModel):
    staff_id: int
    method: Optional[str] = "FINGERPRINT"
    custom_time: Optional[str] = None # For testing past or specific punch times

class PinOtpRequest(BaseModel):
    staff_id: int
    pin: str
    action: Optional[str] = None # Optional: user can explicitly choose 'IN' or 'OUT'
    custom_time: Optional[str] = None

class PinOtpVerify(BaseModel):
    staff_id: int
    otp_code: str
    custom_time: Optional[str] = None

class CheckoutPinRequest(BaseModel):
    staff_id: int
    pin: str
    custom_time: Optional[str] = None

class ConfirmCheckoutRequest(BaseModel):
    staff_id: int
    otp_id: Optional[int] = None  # OTP record ID from verify-checkout-pin (for notify time tracking)
    custom_time: Optional[str] = None  # Optional override for exact punch time

class OtpRevealRequest(BaseModel):
    token: str
    master_pin: str

class SettingsUpdate(BaseModel):
    admin_whatsapp_number: Optional[str] = None
    admin_name: Optional[str] = None
    pharmacy_name: Optional[str] = None
    otp_expiry_minutes: Optional[str] = None
    admin_master_pin: Optional[str] = None

class WhatsAppTestRequest(BaseModel):
    phone: Optional[str] = None
    message: Optional[str] = None

class LeaveRequestCreate(BaseModel):
    staff_id: Optional[int] = None
    staff_name: Optional[str] = None
    pin: str
    leave_date: str
    leave_type: Optional[str] = "FULL_DAY"
    reason: str

class LeaveReviewRequest(BaseModel):
    action: str  # "APPROVE" or "REJECT"
    admin_notes: Optional[str] = ""
    reviewed_by: Optional[str] = "Admin"

class DeliveryReturnConfirm(BaseModel):
    rider_pin: Optional[str] = None
    delivery_result: Optional[str] = "DELIVERED"
    payment_status: Optional[str] = "FULL"
    paid_amount: Optional[float] = 0.0
    payment_method: Optional[str] = "Cash on Delivery"
    return_reason: Optional[str] = ""
    return_notes: Optional[str] = ""

class StaffCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    cnic: Optional[str] = None
    address: Optional[str] = None
    designation: str = "Pharmacist"
    monthly_salary: float
    joining_date: Optional[str] = None
    shift_id: int = 1
    fingerprint_id: Optional[str] = None
    police_report: Optional[int] = 0
    allowed_leaves: Optional[int] = 2
    daily_hours: Optional[float] = 8.0
    pin: Optional[str] = None

class StaffUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    cnic: Optional[str] = None
    address: Optional[str] = None
    designation: Optional[str] = None
    monthly_salary: Optional[float] = None
    joining_date: Optional[str] = None
    shift_id: Optional[int] = None
    fingerprint_id: Optional[str] = None
    police_report: Optional[int] = None
    allowed_leaves: Optional[int] = None
    daily_hours: Optional[float] = None
    pin: Optional[str] = None
    is_temp_delivery_staff: Optional[int] = None

class AdvanceCreate(BaseModel):
    staff_id: int
    entry_type: Optional[str] = "ADVANCE" # "ADVANCE" or "MEDICINE_CREDIT"
    amount: float
    reason: Optional[str] = "Advance from Till"
    date_str: Optional[str] = None

class AdvanceSettleRequest(BaseModel):
    settled_at: Optional[str] = None
    settlement_type: Optional[str] = "Direct Settlement"
    notes: Optional[str] = None
    amount: Optional[float] = None # Optional: if less than advance amount, recorded as partial settlement

class PayrollDisburseRequest(BaseModel):
    staff_id: int
    month: int
    year: int
    paid_at: Optional[str] = None
    payment_method: Optional[str] = "Cash"
    notes: Optional[str] = ""

class LeaveCreate(BaseModel):
    staff_id: int
    date: str
    reason: Optional[str] = "Approved Medical / Personal Leave"
    leave_type: Optional[str] = "FULL_DAY" # "FULL_DAY" or "HALF_DAY"

class LeaveUpdate(BaseModel):
    date: Optional[str] = None
    reason: Optional[str] = None
    leave_type: Optional[str] = None

class AttendanceOverride(BaseModel):
    staff_id: int
    date: str
    time_in: Optional[str] = None
    time_out: Optional[str] = None
    status: str # "ON_TIME", "LATE", "HALF_DAY", "ABSENT"
    notes: Optional[str] = "Manual Admin Adjustment"

# --- Customer Khata Models ---
class CustomerCreate(BaseModel):
    name: str
    phone: str
    address: Optional[str] = ""
    credit_limit: Optional[float] = 15000.0
    added_by: Optional[str] = "Admin"
    approval_status: Optional[str] = None
    is_staff: Optional[bool] = False

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    credit_limit: Optional[float] = None
    is_active: Optional[int] = None
    added_by: Optional[str] = None

class CustomerReassignStaff(BaseModel):
    new_staff: str
    reassign_bills: Optional[bool] = True

class KhataBillReassignStaff(BaseModel):
    new_staff: str

class CustomerKhataCreate(BaseModel):
    customer_id: int
    invoice_no: Optional[str] = None
    date: Optional[str] = None
    item_description: str
    amount: float
    notes: Optional[str] = ""
    added_by: Optional[str] = "Admin"
    approval_status: Optional[str] = None
    is_staff: Optional[bool] = False

class CustomerKhataSettle(BaseModel):
    settled_at: Optional[str] = None
    payment_method: Optional[str] = "Cash"
    notes: Optional[str] = ""
    amount: Optional[float] = None # Optional amount: if less than invoice amount, recorded as partial payment
    is_staff: Optional[bool] = False
    added_by: Optional[str] = "Admin"

class CustomerSettleAll(BaseModel):
    settled_at: Optional[str] = None
    payment_method: Optional[str] = "Cash"
    notes: Optional[str] = ""
    amount: Optional[float] = None # Optional amount: if less than total balance, settled partially across pending invoices (FIFO)
    is_staff: Optional[bool] = False
    added_by: Optional[str] = "Admin"

class BatchApproveRequest(BaseModel):
    request_ids: Optional[List[int]] = None
    approve_all: Optional[bool] = False
    staff_assignments: Optional[Dict[str, str]] = None

# --- API Endpoints ---

@app.get("/api/status")
@app.get("/api/health")
def get_system_status():
    return {
        "status": "ok",
        "system": "Mumtaz Pharmacy Management System",
        "version": "2.4",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/activities/today")
def get_activities_today(date: Optional[str] = None, category: Optional[str] = "ALL", limit: Optional[int] = 50):
    """Returns today's real-time operational activity log for the Dashboard."""
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    return get_today_activities(target_date=target_date, limit=limit, category=category)

@app.post("/api/punch")
def punch_attendance(req: PunchRequest):
    """Executes a biometric fingerprint punch (IN or OUT)."""
    punch_dt = datetime.now()
    if req.custom_time:
        try:
            punch_dt = datetime.strptime(req.custom_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    result = process_punch(req.staff_id, punch_dt=punch_dt, method=req.method)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))

    # Log real-time activity for dashboard
    staff_name = result.get("staff_name", f"Staff #{req.staff_id}")
    punch_type = result.get("punch_type", "IN")
    status = result.get("status", "ON_TIME")
    status_label = "On-Time" if status == "ON_TIME" else ("Late Arrival" if status == "LATE" else status)
    time_str = result.get("time", punch_dt.strftime("%I:%M:%S %p"))
    date_str = punch_dt.strftime("%Y-%m-%d")

    log_activity(
        category="ATTENDANCE",
        action_type=f"PUNCH_{punch_type}",
        title=f"Biometric Punch {punch_type}: {staff_name}",
        description=f"Recorded at {time_str} • Status: {status_label} ({req.method})",
        staff_name=staff_name,
        date_str=date_str,
        time_str=time_str
    )

    return result

# =====================================================================
# PIN + WHATSAPP OTP ATTENDANCE ENDPOINTS
# =====================================================================

@app.post("/api/attendance/request-pin-otp")
def request_pin_otp(req: PinOtpRequest):
    """
    Validates staff PIN and initiates WhatsApp OTP verification.
    - If Check-IN: OTP is dispatched to Admin's configured WhatsApp number.
    - If Check-OUT: OTP is dispatched to Staff's registered WhatsApp number.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.*, coalesce(nullif(s.designation, ''), s.role) as designation, sh.name as shift_name
        FROM staff s
        JOIN shifts sh ON s.shift_id = sh.id
        WHERE s.id = ? AND s.is_active = 1
    """, (req.staff_id,))
    staff = cursor.fetchone()

    if not staff:
        conn.close()
        raise HTTPException(status_code=404, detail="Staff member not found or inactive.")

    # 1. Verify Secret PIN
    saved_pin = str(staff["pin"] or "").strip()
    entered_pin = str(req.pin or "").strip()
    if not saved_pin or saved_pin != entered_pin:
        conn.close()
        raise HTTPException(status_code=400, detail="Ghalat PIN! Barah-e-karam apni 4-digit secret PIN sahi darj karein.")

    # 2. Determine Action (IN or OUT): explicit user choice or auto-detection
    if req.action and req.action.upper() in ["IN", "OUT"]:
        action = req.action.upper()
        conn.close()
    else:
        today_str = date.today().strftime("%Y-%m-%d")
        if req.custom_time:
            try:
                today_str = datetime.strptime(req.custom_time, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
            except ValueError:
                pass

        cursor.execute("SELECT time_in, time_out FROM attendance_logs WHERE staff_id = ? AND date = ?", (req.staff_id, today_str))
        log = cursor.fetchone()
        conn.close()

        if not log or not log["time_in"]:
            action = "IN"
        elif log["time_in"] and not log["time_out"]:
            action = "OUT"
        else:
            action = "OUT" # Update/overwrite checkout if punched again

    # 3. Determine Target Destination Phone (Admin receives WhatsApp link for both Check-IN & Check-OUT)
    target_phone = get_setting("admin_whatsapp_number", "03166868169")
    target_type = "ADMIN"
    target_label = "Admin WhatsApp"

    # 4. Generate 4-digit OTP, unique token & record in DB
    otp_code = f"{random.randint(1000, 9999)}"
    expiry_mins = int(get_setting("otp_expiry_minutes", "5") or "5")
    otp_id, token = create_otp_record(req.staff_id, otp_code, action, target_phone, expiry_minutes=expiry_mins)

    # 5. Build Local Wi-Fi Reveal Link & Dispatch WhatsApp Message
    local_ip = whatsapp_service.get_local_ip()
    reveal_link = f"http://{local_ip}:8000/otp-verify?token={token}"

    dispatch_info = whatsapp_service.send_otp(
        target_phone=target_phone,
        staff_name=staff["name"],
        designation=staff["designation"],
        otp_code=otp_code,
        action=action,
        reveal_link=reveal_link
    )

    # 6. Audit activity log
    log_activity(
        category="ATTENDANCE",
        action_type=f"OTP_REQUEST_{action}",
        title=f"OTP Requested ({action}): {staff['name']}",
        description=f"Sent to {target_label} ({whatsapp_service.mask_phone(target_phone)}) • Link Token: {token[:10]}...",
        staff_name=staff["name"]
    )

    return {
        "success": True,
        "staff_id": staff["id"],
        "staff_name": staff["name"],
        "designation": staff["designation"],
        "action": action,
        "target_type": target_type,
        "target_label": target_label,
        "target_masked_phone": whatsapp_service.mask_phone(target_phone),
        "direct_link": dispatch_info.get("direct_link", ""),
        "reveal_link": reveal_link,
        "token": token,
        "expiry_minutes": expiry_mins,
        "otp_code": otp_code, # Sent for immediate simulation / offline testing fallback
        "message": f"Confirmation link has been sent to {target_label} ({whatsapp_service.mask_phone(target_phone)})."
    }

@app.post("/api/attendance/verify-pin-otp")
def verify_pin_otp(req: PinOtpVerify):
    """
    Validates the 4-digit OTP provided by Staff/Admin and records the punch (IN or OUT).
    """
    is_valid, action, message = verify_and_consume_otp(req.staff_id, req.otp_code)
    if not is_valid:
        raise HTTPException(status_code=400, detail=message)

    punch_dt = datetime.now()
    if req.custom_time:
        try:
            punch_dt = datetime.strptime(req.custom_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    # Process punch via authoritative payroll engine with force_action
    result = process_punch(req.staff_id, punch_dt=punch_dt, method="PIN_OTP", force_action=action)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))

    staff_name = result.get("staff_name", f"Staff #{req.staff_id}")
    punch_type = result.get("punch_type", action or "IN")
    status = result.get("status", "ON_TIME")
    status_label = "On-Time" if status == "ON_TIME" else ("Late Arrival" if status == "LATE" else status)
    time_str = result.get("time", punch_dt.strftime("%I:%M:%S %p"))
    date_str = punch_dt.strftime("%Y-%m-%d")

    log_activity(
        category="ATTENDANCE",
        action_type=f"PUNCH_{punch_type}",
        title=f"PIN+OTP Attendance {punch_type}: {staff_name}",
        description=f"Verified via OTP at {time_str} • Status: {status_label} (PIN_OTP)",
        staff_name=staff_name,
        date_str=date_str,
        time_str=time_str
    )

    result["verification_method"] = "PIN_OTP"
    return result

@app.get("/api/attendance/active-otps")
def get_live_otps():
    """Returns active pending OTP requests for live Admin monitoring."""
    return get_active_otps()

@app.delete("/api/attendance/active-otps/{otp_id}")
@app.post("/api/attendance/active-otps/{otp_id}/delete")
def delete_active_otp_endpoint(otp_id: int):
    """Admin removes an active/pending OTP verification code."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM otp_verifications WHERE id = ?", (otp_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Verification code not found.")
    cursor.execute("DELETE FROM otp_verifications WHERE id = ?", (otp_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Verification code deleted successfully."}


@app.get("/api/attendance/audit-log")
def get_audit_log(date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format")):
    """
    Returns complete PIN vs OTP verification audit trail.
    Enables Admin to compare PIN keyed-in time against OTP verified time at the end of the day.
    """
    return get_pin_otp_audit_logs(date_str=date)


@app.post("/api/attendance/verify-checkout-pin")
def verify_checkout_pin(req: CheckoutPinRequest):
    """
    STEP 1 of 2-step checkout:
    Verifies staff PIN for Check-OUT. Does NOT record any punch yet.
    Records PIN entry time in audit log (otp_verifications.created_at).
    Returns otp_id + WhatsApp notification link — staff must click to notify Admin.
    Actual punch is only recorded when /confirm-checkout is called.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.*, coalesce(nullif(s.designation, ''), s.role) as designation, sh.name as shift_name
        FROM staff s
        JOIN shifts sh ON s.shift_id = sh.id
        WHERE s.id = ? AND s.is_active = 1
    """, (req.staff_id,))
    staff = cursor.fetchone()
    conn.close()

    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found or inactive.")

    # Verify PIN only — no punch recorded here
    saved_pin = str(staff["pin"] or "").strip()
    entered_pin = str(req.pin or "").strip()
    if not saved_pin or saved_pin != entered_pin:
        raise HTTPException(status_code=400, detail="Ghalat PIN! Barah-e-karam apni 4-digit secret PIN sahi darj karein.")

    # ✅ Record PIN entry time in audit log (created_at = now, verified_at = empty until notify)
    admin_phone = get_setting("admin_whatsapp_number", "03166868169")
    otp_id, token = create_otp_record(
        req.staff_id, "OUT_PIN", "OUT",
        staff["phone"] or admin_phone,
        expiry_minutes=30  # 30 min window to send notification
    )

    # Build admin WhatsApp notification link
    time_str = datetime.now().strftime("%I:%M %p")
    admin_phone_digits = ''.join(c for c in admin_phone if c.isdigit())
    staff_name = staff["name"]
    wa_msg = (f"MUMTAZ PHARMACY%0A"
              f"%E2%9C%85 {staff_name} ne {time_str} par Check-OUT kiya hai.%0A"
              f"PIN verified — Checkout confirm kiya ja raha hai.")
    wa_link = f"https://wa.me/{admin_phone_digits}?text={wa_msg}"

    return {
        "success": True,
        "pin_verified": True,
        "otp_id": otp_id,  # Pass this to confirm-checkout to record notify time
        "staff_id": staff["id"],
        "staff_name": staff_name,
        "time": time_str,
        "admin_wa_link": wa_link,
        "admin_phone_masked": whatsapp_service.mask_phone(admin_phone),
        "message": "PIN sahi hai. Admin ko notify karen phir checkout record hoga."
    }


@app.post("/api/attendance/confirm-checkout")
def confirm_checkout(req: ConfirmCheckoutRequest):
    """
    STEP 2 of 2-step checkout:
    Called AFTER staff clicks the WhatsApp Admin-notify button.
    1. Records verified_at (notify time) in otp_verifications for audit diff tracking.
    2. Records the actual OUT punch in attendance.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.*, coalesce(nullif(s.designation, ''), s.role) as designation
        FROM staff s WHERE s.id = ? AND s.is_active = 1
    """, (req.staff_id,))
    staff = cursor.fetchone()
    conn.close()

    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found or inactive.")

    # ✅ Record notify time in audit log (verified_at = now → diff = PIN time vs Notify time)
    if req.otp_id:
        mark_otp_notified(req.otp_id)

    # Record the OUT punch now
    punch_dt = datetime.now()
    if req.custom_time:
        try:
            punch_dt = datetime.strptime(req.custom_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    result = process_punch(req.staff_id, punch_dt=punch_dt, method="PIN_NOTIFY", force_action="OUT")
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))

    staff_name = result.get("staff_name", staff["name"])
    time_str = result.get("time", punch_dt.strftime("%I:%M %p"))
    date_str = punch_dt.strftime("%Y-%m-%d")

    # Log activity
    log_activity(
        category="ATTENDANCE",
        action_type="PUNCH_OUT",
        title=f"Check-OUT Confirmed: {staff_name}",
        description=f"OUT recorded at {time_str} — Admin notified via WhatsApp (PIN_NOTIFY)",
        staff_name=staff_name,
        date_str=date_str,
        time_str=time_str
    )

    result["checkout_method"] = "PIN_NOTIFY"
    return result


# =====================================================================
# SYSTEM SETTINGS & WHATSAPP CONFIGURATION ENDPOINTS
# =====================================================================

@app.get("/api/settings")
def get_system_settings():
    """Returns persistent system settings."""
    settings = get_all_settings()
    settings["whatsapp_status"] = whatsapp_service.status
    return settings

@app.post("/api/settings")
def update_system_settings(data: SettingsUpdate):
    """Updates persistent system settings, including Admin WhatsApp alert number."""
    updated = {}
    if data.admin_whatsapp_number is not None:
        set_setting("admin_whatsapp_number", data.admin_whatsapp_number.strip())
        updated["admin_whatsapp_number"] = data.admin_whatsapp_number.strip()
    if data.admin_name is not None:
        set_setting("admin_name", data.admin_name.strip())
        updated["admin_name"] = data.admin_name.strip()
    if data.pharmacy_name is not None:
        set_setting("pharmacy_name", data.pharmacy_name.strip())
        updated["pharmacy_name"] = data.pharmacy_name.strip()
    if data.otp_expiry_minutes is not None:
        set_setting("otp_expiry_minutes", data.otp_expiry_minutes.strip())
        updated["otp_expiry_minutes"] = data.otp_expiry_minutes.strip()
    if data.admin_master_pin is not None:
        set_admin_master_pin(data.admin_master_pin.strip())
        updated["admin_master_pin"] = data.admin_master_pin.strip()

    admin_phone = get_setting("admin_whatsapp_number", "03166868169")
    log_activity(
        category="SETTINGS",
        action_type="SETTINGS_UPDATED",
        title="Admin Alert Settings Updated",
        description=f"Admin WhatsApp alert settings saved.",
        staff_name="Admin"
    )

    return {
        "success": True,
        "message": "Settings updated successfully.",
        "settings": get_all_settings()
    }

# =====================================================================
# MOBILE OTP REVEAL VIA ADMIN MASTER PIN ENDPOINTS & WEB VIEW
# =====================================================================

@app.get("/otp-verify", response_class=HTMLResponse)
def get_otp_verify_page(token: Optional[str] = Query(None)):
    """Serves minimal mobile page for Admin Master PIN OTP reveal."""
    staff_name = "Staff Member"
    designation = "Staff"
    action_label = "Check-IN"
    time_str = datetime.now().strftime("%I:%M %p")

    if token:
        record = get_otp_by_token(token)
        if record:
            staff_name = record.get("staff_name") or "Staff Member"
            designation = record.get("designation") or record.get("role") or "Staff"
            action_label = "Duty Check-IN" if record.get("action") == "IN" else "Duty Check-OUT"
            if record.get("created_at"):
                try:
                    dt = datetime.strptime(record["created_at"].split(".")[0], "%Y-%m-%d %H:%M:%S")
                    time_str = dt.strftime("%I:%M %p")
                except Exception:
                    pass

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mumtaz Pharmacy — Admin OTP Verification</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
        body {{ background: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 16px; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 20px; width: 100%; max-width: 420px; padding: 28px 24px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); text-align: center; }}
        .logo-badge {{ width: 56px; height: 56px; background: #059669; border-radius: 16px; display: inline-flex; align-items: center; justify-content: center; margin: 0 auto 12px auto; font-weight: 900; font-size: 24px; color: #ffffff; }}
        .title {{ font-size: 20px; font-weight: 800; color: #ffffff; letter-spacing: -0.5px; }}
        .subtitle {{ font-size: 13px; color: #94a3b8; margin-top: 4px; margin-bottom: 20px; }}
        .staff-card {{ background: #0f172a; border: 1px solid #334155; border-radius: 12px; padding: 12px 16px; margin-bottom: 20px; text-align: left; }}
        .pin-box {{ margin-bottom: 20px; }}
        .pin-input {{ width: 180px; height: 54px; background: #0f172a; border: 2px solid #334155; border-radius: 14px; font-size: 28px; font-weight: 700; text-align: center; letter-spacing: 12px; color: #10b981; outline: none; transition: all 0.2s; }}
        .pin-input:focus {{ border-color: #10b981; box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.2); }}
        .btn {{ width: 100%; padding: 14px; background: #10b981; color: #ffffff; border: none; border-radius: 12px; font-size: 15px; font-weight: 700; cursor: pointer; transition: background 0.2s, transform 0.1s; }}
        .btn:hover {{ background: #059669; }}
        .btn:active {{ transform: scale(0.98); }}
        .btn:disabled {{ background: #475569; cursor: not-allowed; }}
        .error-banner {{ background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; color: #fca5a5; font-size: 13px; font-weight: 600; padding: 10px 14px; border-radius: 10px; margin-top: 14px; display: none; }}
        .reveal-box {{ background: #0f172a; border: 2px dashed #10b981; border-radius: 16px; padding: 24px; margin-top: 16px; }}
        .otp-code {{ font-size: 42px; font-weight: 900; letter-spacing: 16px; color: #34d399; font-family: monospace; text-indent: 16px; margin: 12px 0; }}
        .timer {{ font-size: 13px; font-weight: 700; color: #fbbf24; margin-top: 8px; }}
        .hidden {{ display: none !important; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="logo-badge">MP</div>
        <div class="title">Mumtaz Pharmacy</div>
        <div class="subtitle">Secure Admin OTP Gateway</div>

        <!-- STAFF DETAILS CARD -->
        <div class="staff-card">
            <div style="font-size: 11px; font-weight: 700; color: #10b981; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 3px;">Staff Check-IN Request</div>
            <div id="staff-name-hdr" style="font-size: 16px; font-weight: 800; color: #ffffff;">👤 {staff_name}</div>
            <div id="staff-sub-hdr" style="font-size: 12px; font-weight: 600; color: #94a3b8; margin-top: 2px;">{designation} • <span style="color: #38bdf8;">{action_label}</span> • <span style="color: #cbd5e1;">{time_str}</span></div>
        </div>

        <div id="pin-section">
            <p style="font-size: 14px; color: #cbd5e1; margin-bottom: 16px; font-weight: 600;">🔒 Enter Admin Master Password (PIN):</p>
            <div class="pin-box">
                <input type="password" id="master-pin" class="pin-input" maxlength="6" inputmode="numeric" placeholder="••••" autofocus autocomplete="off" onkeydown="if(event.key==='Enter') submitMasterPin()">
            </div>
            <button id="reveal-btn" onclick="submitMasterPin()" class="btn">🔓 UNLOCK &amp; GET OTP</button>
            <div id="error-alert" class="error-banner"></div>
        </div>

        <div id="otp-section" class="hidden">
            <div class="reveal-box">
                <div style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px;">STAFF CONFIRMATION OTP</div>
                <div id="otp-display" class="otp-code">----</div>
                <button onclick="copyOtp()" style="margin-top: 8px; background: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; color: #34d399; font-weight: 700; font-size: 13px; padding: 6px 14px; border-radius: 8px; cursor: pointer;">📋 Copy OTP Code</button>
                <div id="timer-display" class="timer">⏱️ Valid for 05:00</div>
            </div>

            <p style="font-size: 13px; color: #94a3b8; margin-top: 16px;">Yeh 4-digit code staff ko batayein ya confirm karein.</p>
        </div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const token = urlParams.get('token');
        let countdownInterval = null;

        if (!token) {{
            showError("Ghair-mootabar (invalid) link! URL mein token nahi mila.");
            document.getElementById('reveal-btn').disabled = true;
        }} else {{
            // Focus PIN input for Admin
            setTimeout(() => {{
                const el = document.getElementById('master-pin');
                if (el) el.focus();
            }}, 200);
        }}

        function copyOtp() {{
            const code = document.getElementById('otp-display').innerText.replace(/\s+/g, '');
            if (navigator.clipboard) {{
                navigator.clipboard.writeText(code);
                alert("OTP Code Copied: " + code);
            }}
        }}

        async function submitMasterPin() {{
            const pin = document.getElementById('master-pin').value.trim();
            const errBox = document.getElementById('error-alert');
            const btn = document.getElementById('reveal-btn');
            errBox.style.display = 'none';

            if (!pin || pin.length < 4) {{
                showError("Barah-e-karam 4-digit Admin Master PIN darj karein.");
                return;
            }}

            btn.disabled = true;
            btn.innerText = "Getting OTP...";

            try {{
                const res = await fetch('/api/otp/reveal', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ token: token, master_pin: pin }})
                }});

                const data = await res.json();

                if (!res.ok || !data.success) {{
                    showError(data.detail || data.message || "Ghalat Admin Master PIN!");
                    btn.disabled = false;
                    btn.innerText = "🟢 GET OTP CODE NOW";
                    return;
                }}

                // Success! Reveal OTP
                document.getElementById('pin-section').classList.add('hidden');
                document.getElementById('otp-section').classList.remove('hidden');
                document.getElementById('otp-display').innerText = data.otp_code;
                if (data.staff_name) {{
                    document.getElementById('staff-name-hdr').innerText = "👤 " + data.staff_name;
                }}

                startCountdown(data.expires_in_seconds || 300);
            }} catch (err) {{
                showError("Network error. Make sure you are connected to the Pharmacy Wi-Fi.");
                btn.disabled = false;
                btn.innerText = "🟢 GET OTP CODE NOW";
            }}
        }}

        function showError(msg) {{
            const errBox = document.getElementById('error-alert');
            errBox.innerText = msg;
            errBox.style.display = 'block';
        }}

        function startCountdown(seconds) {{
            let rem = seconds;
            updateTimerDisplay(rem);
            countdownInterval = setInterval(() => {{
                rem--;
                if (rem <= 0) {{
                    clearInterval(countdownInterval);
                    document.getElementById('timer-display').innerText = "❌ EXPIRED (Naya code mangwayein)";
                    document.getElementById('timer-display').style.color = "#ef4444";
                    document.getElementById('otp-display').style.opacity = "0.3";
                }} else {{
                    updateTimerDisplay(rem);
                }}
            }}, 1000);
        }}

        function updateTimerDisplay(sec) {{
            const m = Math.floor(sec / 60);
            const s = sec % 60;
            const mStr = String(m).padStart(2, '0');
            const sStr = String(s).padStart(2, '0');
            document.getElementById('timer-display').innerText = `⏱️ Valid for ${{mStr}}:${{sStr}}`;
        }}

        document.getElementById('master-pin').addEventListener('keypress', (e) => {{
            if (e.key === 'Enter') submitMasterPin();
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content, status_code=200)

@app.post("/api/otp/reveal")
def reveal_otp(req: OtpRevealRequest):
    """Reveals the 4-digit OTP code if token and Admin Master PIN are valid."""
    is_valid, otp_code, record, message = verify_and_reveal_otp_by_token(req.token, req.master_pin)
    if not is_valid:
        raise HTTPException(status_code=400, detail=message)

    expires_at_dt = datetime.strptime(record["expires_at"], "%Y-%m-%d %H:%M:%S")
    remaining_secs = max(0, int((expires_at_dt - datetime.now()).total_seconds()))

    return {
        "success": True,
        "otp_code": otp_code,
        "staff_name": record.get("staff_name", "Staff"),
        "action": record.get("action", "IN"),
        "expires_in_seconds": remaining_secs,
        "message": message
    }

@app.post("/api/settings/test-whatsapp")
def test_whatsapp(req: WhatsAppTestRequest):
    """Sends a test WhatsApp message to the admin or specified phone number."""
    phone = req.phone or get_setting("admin_whatsapp_number", "03166868169")
    result = whatsapp_service.send_test_message(phone, custom_text=req.message)
    return {
        "success": True,
        "message": f"Test WhatsApp message dispatched to {whatsapp_service.mask_phone(phone)}.",
        "details": result
    }

@app.get("/api/whatsapp/messages")
def get_recent_whatsapp_dispatches():
    """Returns recent dispatched WhatsApp messages."""
    return whatsapp_service.get_recent_messages()

# =====================================================================
# STAFF LEAVE REQUEST & ADMIN REVIEW ENDPOINTS
# =====================================================================

@app.post("/api/staff/leave-request")
def apply_leave_request(req: LeaveRequestCreate):
    """Staff submits leave request via 4-digit PIN."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if req.staff_id:
        cursor.execute("SELECT id, name, pin FROM staff WHERE id = ? AND is_active = 1", (req.staff_id,))
        staff = cursor.fetchone()
        if not staff:
            conn.close()
            raise HTTPException(status_code=400, detail="Selected staff member nahi mila.")
        if staff["pin"] != req.pin.strip():
            conn.close()
            raise HTTPException(status_code=400, detail="Ghalat 4-digit Secret PIN! Selected staff member ke PIN se match nahi ho raha.")
    elif req.staff_name and req.staff_name.strip():
        cursor.execute("SELECT id, name, pin FROM staff WHERE name = ? AND is_active = 1", (req.staff_name.strip(),))
        staff = cursor.fetchone()
        if not staff:
            conn.close()
            raise HTTPException(status_code=400, detail="Selected staff member nahi mila.")
        if staff["pin"] != req.pin.strip():
            conn.close()
            raise HTTPException(status_code=400, detail="Ghalat 4-digit Secret PIN! Selected staff member ke PIN se match nahi ho raha.")
    else:
        cursor.execute("SELECT id, name, pin FROM staff WHERE pin = ? AND is_active = 1", (req.pin.strip(),))
        staff = cursor.fetchone()
        if not staff:
            conn.close()
            raise HTTPException(status_code=400, detail="Ghalat 4-digit Secret PIN! Leave request submit nahi ho saki.")
    
    conn.close()
    
    leave_rec = create_leave_request(
        staff_id=staff["id"],
        staff_name=staff["name"],
        leave_date=req.leave_date.strip(),
        leave_type=req.leave_type or "FULL_DAY",
        reason=req.reason.strip()
    )

    log_activity(
        category="LEAVES",
        action_type="LEAVE_REQUESTED",
        title=f"Leave Requested: {staff['name']}",
        description=f"Date: {req.leave_date} ({req.leave_type}) • Reason: {req.reason}",
        staff_name=staff["name"]
    )

    return {
        "success": True,
        "leave_request": leave_rec,
        "message": f"Leave request for {staff['name']} on {req.leave_date} submitted successfully!"
    }

@app.get("/api/staff/leave-requests")
def get_staff_leave_requests(pin: str = Query(...), staff_id: Optional[int] = Query(None)):
    """Staff checks their leave requests via selected staff member and 4-digit PIN."""
    result = get_leave_requests_by_staff_pin(pin, staff_id)
    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=400, detail=result.get("detail", "Invalid PIN or staff member not found"))
    return result

@app.get("/api/admin/leave-requests/pending")
def get_admin_pending_leave_requests():
    """Admin retrieves all pending leave requests and count for badge."""
    pending = get_pending_leave_requests()
    return {
        "success": True,
        "pending_count": len(pending),
        "pending_requests": pending
    }

@app.post("/api/admin/leave-requests/{request_id}/review")
def review_leave_request_endpoint(request_id: int, req: LeaveReviewRequest):
    """Admin approves or rejects a pending leave request."""
    try:
        updated = review_leave_request(
            request_id=request_id,
            action=req.action,
            admin_notes=req.admin_notes or "",
            reviewed_by=req.reviewed_by or "Admin"
        )
        return {
            "success": True,
            "leave_request": updated,
            "message": f"Leave request {req.action.lower()}d successfully."
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/admin/leave-requests/{request_id}")
@app.post("/api/admin/leave-requests/{request_id}/delete")
def delete_leave_request_endpoint(request_id: int):
    """Admin permanently deletes a leave request application."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM leave_requests WHERE id = ?", (request_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Leave request not found.")
    cursor.execute("DELETE FROM leave_requests WHERE id = ?", (request_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Leave request deleted successfully."}

@app.get("/api/attendance/today")
def get_today_attendance(target_date: Optional[str] = Query(None, alias="date")):
    """Returns today's live roster and statistics for the Owner Dashboard."""
    today_str = target_date if (target_date and len(target_date) == 10) else date.today().strftime("%Y-%m-%d")
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all active staff with attendance logs and leaves
    cursor.execute("""
        SELECT s.id, s.name, s.role, coalesce(nullif(s.designation, ''), s.role) as designation, s.monthly_salary,
               s.daily_hours, s.allowed_leaves, sh.name as shift_name,
               sh.start_time, sh.end_time,
               a.time_in, a.time_out, a.status, a.late_minutes, a.worked_minutes, a.overtime_minutes,
               l.reason as leave_reason, coalesce(l.leave_type, 'FULL_DAY') as leave_type
        FROM staff s
        JOIN shifts sh ON s.shift_id = sh.id
        LEFT JOIN attendance_logs a ON s.id = a.staff_id AND a.date = ?
        LEFT JOIN leaves l ON s.id = l.staff_id AND l.date = ?
        WHERE s.is_active = 1
        ORDER BY s.id ASC
    """, (today_str, today_str))
    rows = cursor.fetchall()
    conn.close()

    roster = []
    total_staff = len(rows)
    present_count = 0
    late_count = 0
    absent_count = 0
    leave_count = 0

    for r in rows:
        item = dict(r)
        status = item.get("status")

        daily_hours = float(item.get("daily_hours") or 8.0)
        req_mins = int(daily_hours * 60)
        item["daily_hours"] = daily_hours
        item["required_minutes"] = req_mins

        # Calculate target_out if currently checked in
        if item.get("time_in") and not item.get("time_out"):
            try:
                t_parts = item["time_in"].split(":")
                t_h, t_m = int(t_parts[0]), int(t_parts[1])
                t_in_dt = datetime.now().replace(hour=t_h, minute=t_m, second=0)
                t_target = t_in_dt + timedelta(minutes=req_mins)
                item["target_out"] = t_target.strftime("%I:%M %p")
            except Exception:
                item["target_out"] = ""
        else:
            item["target_out"] = ""

        if item.get("leave_reason") or status == "LEAVE":
            item["status"] = "LEAVE"
            leave_count += 1
        elif not status:
            # Has not punched in yet today (Flexible duty: pending check-in)
            item["status"] = "PENDING"
        else:
            if status in ("ON_TIME", "PRESENT", "HALF_DAY", "SHORT_HOURS"):
                present_count += 1
            elif status == "LATE":
                present_count += 1
                late_count += 1
            elif status == "LEAVE":
                leave_count += 1
            elif status == "ABSENT":
                absent_count += 1

        roster.append(item)

    return {
        "date": today_str,
        "total_staff": total_staff,
        "present_count": present_count,
        "late_count": late_count,
        "absent_count": absent_count,
        "leave_count": leave_count,
        "pending_count": max(0, total_staff - present_count - absent_count - leave_count),
        "roster": roster
    }

@app.put("/api/attendance/override")
def override_attendance(data: AttendanceOverride):
    """Admin manual override to adjust punch times and status (Feature 18)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    worked_minutes = 0
    if data.time_in and data.time_out:
        try:
            t1 = datetime.strptime(data.time_in, "%H:%M:%S" if len(data.time_in.split(':')) == 3 else "%H:%M")
            t2 = datetime.strptime(data.time_out, "%H:%M:%S" if len(data.time_out.split(':')) == 3 else "%H:%M")
            worked_minutes = max(0, int((t2 - t1).total_seconds() // 60))
        except Exception:
            pass

    cursor.execute("""
        INSERT INTO attendance_logs (staff_id, date, time_in, time_out, status, worked_minutes, punch_method, notes)
        VALUES (?, ?, ?, ?, ?, ?, 'MANUAL_ADMIN', ?)
        ON CONFLICT(staff_id, date) DO UPDATE SET
            time_in = excluded.time_in,
            time_out = excluded.time_out,
            status = excluded.status,
            worked_minutes = excluded.worked_minutes,
            punch_method = 'MANUAL_ADMIN',
            notes = excluded.notes
    """, (data.staff_id, data.date, data.time_in, data.time_out, data.status, worked_minutes, data.notes))
    conn.commit()

    cursor.execute("SELECT name FROM staff WHERE id = ?", (data.staff_id,))
    staff_row = cursor.fetchone()
    staff_name = staff_row["name"] if staff_row else f"Staff #{data.staff_id}"
    conn.close()

    log_activity(
        category="ATTENDANCE",
        action_type="ATTENDANCE_OVERRIDE",
        title=f"Attendance Adjusted: {staff_name}",
        description=f"Status set to {data.status} for {data.date} (In: {data.time_in or 'None'}, Out: {data.time_out or 'None'})",
        staff_name=staff_name,
        date_str=data.date
    )

    return {"success": True, "message": f"Attendance for staff #{data.staff_id} on {data.date} updated successfully."}

@app.get("/api/attendance/monthly")
def get_monthly_attendance(month: int = Query(..., ge=1, le=12), year: int = Query(..., ge=2020)):
    """Returns monthly attendance matrix for all active staff (Feature 6)."""
    _, days_in_month = calendar.monthrange(year, month)
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-{days_in_month:02d}"

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, role, coalesce(nullif(designation, ''), role) as designation FROM staff WHERE is_active = 1 ORDER BY id ASC")
    staff = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT staff_id, date, status, time_in, time_out, worked_minutes
        FROM attendance_logs
        WHERE date BETWEEN ? AND ?
    """, (start_date, end_date))
    logs = cursor.fetchall()

    cursor.execute("""
        SELECT staff_id, date FROM leaves
        WHERE date BETWEEN ? AND ?
    """, (start_date, end_date))
    leaves = cursor.fetchall()
    conn.close()

    logs_map = {}
    for l in logs:
        logs_map[(l["staff_id"], l["date"])] = l["status"]

    leaves_map = {(lv["staff_id"], lv["date"]) for lv in leaves}

    matrix = []
    for s in staff:
        sid = s["id"]
        days_data = {}
        short_hours_count = 0
        present_count = 0
        late_count = 0
        half_day_count = 0
        absent_count = 0
        leave_count = 0

        for d in range(1, days_in_month + 1):
            dt_str = f"{year}-{month:02d}-{d:02d}"
            if (sid, dt_str) in leaves_map:
                st = "LEAVE"
                leave_count += 1
            elif (sid, dt_str) in logs_map:
                st = logs_map[(sid, dt_str)]
                if st in ("ON_TIME", "PRESENT"):
                    present_count += 1
                elif st == "LATE":
                    late_count += 1
                elif st == "HALF_DAY":
                    half_day_count += 1
                elif st == "SHORT_HOURS":
                    short_hours_count += 1
                    present_count += 1
                elif st == "ABSENT":
                    absent_count += 1
            else:
                today_str = date.today().strftime("%Y-%m-%d")
                if dt_str <= today_str:
                    st = "ABSENT"
                    absent_count += 1
                else:
                    st = "—"
            days_data[d] = st

        matrix.append({
            "staff_id": sid,
            "name": s["name"],
            "designation": s["designation"],
            "days": days_data,
            "present_count": present_count,
            "late_count": late_count,
            "short_hours_count": short_hours_count,
            "half_day_count": half_day_count,
            "absent_count": absent_count,
            "leave_count": leave_count
        })

    return {
        "month": month,
        "year": year,
        "days_in_month": days_in_month,
        "matrix": matrix
    }

@app.get("/api/staff")
def list_staff(search: Optional[str] = None):
    """Lists all registered staff members with their shift details, with search filter."""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
        SELECT s.*, coalesce(nullif(s.designation, ''), s.role) as designation, sh.name as shift_name, sh.start_time, sh.end_time
        FROM staff s
        JOIN shifts sh ON s.shift_id = sh.id
        WHERE s.is_active = 1
    """
    params = []
    if search and search.strip():
        term = f"%{search.strip()}%"
        query += " AND (s.name LIKE ? OR s.phone LIKE ? OR s.cnic LIKE ? OR s.role LIKE ? OR s.designation LIKE ? OR s.address LIKE ?)"
        params.extend([term, term, term, term, term, term])

    query += " ORDER BY s.id ASC"
    cursor.execute(query, params)
    staff = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return staff

@app.post("/api/staff")
def create_staff(data: StaffCreate):
    """Adds a new staff member with assigned shift, full profiling, and salary."""
    conn = get_db_connection()
    cursor = conn.cursor()
    joining_date = data.joining_date or date.today().strftime("%Y-%m-%d")
    address = data.address or ""
    designation = data.designation or "Pharmacist"
    police_report = 1 if data.police_report in (1, "1", "yes", "YES", True) else 0
    allowed_leaves = data.allowed_leaves if data.allowed_leaves is not None else 2
    daily_hours = data.daily_hours if data.daily_hours is not None else 8.0
    pin = (data.pin or "").strip() or f"{random.randint(1000, 9999)}"
    cursor.execute("""
        INSERT INTO staff (name, phone, cnic, address, role, designation, monthly_salary, joining_date, shift_id, fingerprint_id, police_report, allowed_leaves, daily_hours, pin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (data.name, data.phone, data.cnic, address, designation, designation, data.monthly_salary, joining_date, data.shift_id, data.fingerprint_id, police_report, allowed_leaves, daily_hours, pin))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()

    log_activity(
        category="STAFF",
        action_type="STAFF_ADDED",
        title=f"New Staff Registered: {data.name}",
        description=f"Designation: {designation} • Salary: Rs. {data.monthly_salary:,.2f} • PIN Assigned",
        staff_name=data.name
    )

    return {"success": True, "staff_id": new_id, "pin": pin, "message": f"Staff member '{data.name}' registered successfully with PIN {pin}."}

@app.put("/api/staff/{staff_id}")
def update_staff(staff_id: int, data: StaffUpdate):
    """Updates profile details for an existing staff member."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM staff WHERE id = ? AND is_active = 1", (staff_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Staff member not found")

    fields = []
    values = []
    if data.name is not None:
        fields.append("name = ?")
        values.append(data.name)
    if data.phone is not None:
        fields.append("phone = ?")
        values.append(data.phone)
    if data.cnic is not None:
        fields.append("cnic = ?")
        values.append(data.cnic)
    if data.address is not None:
        fields.append("address = ?")
        values.append(data.address)
    if data.designation is not None:
        fields.append("designation = ?")
        values.append(data.designation)
        fields.append("role = ?")
        values.append(data.designation)
    if data.monthly_salary is not None:
        fields.append("monthly_salary = ?")
        values.append(data.monthly_salary)
    if data.joining_date is not None:
        fields.append("joining_date = ?")
        values.append(data.joining_date)
    if data.shift_id is not None:
        fields.append("shift_id = ?")
        values.append(data.shift_id)
    if data.fingerprint_id is not None:
        fields.append("fingerprint_id = ?")
        values.append(data.fingerprint_id)
    if data.police_report is not None:
        fields.append("police_report = ?")
        values.append(1 if data.police_report in (1, "1", "yes", "YES", True) else 0)
    if data.allowed_leaves is not None:
        fields.append("allowed_leaves = ?")
        values.append(data.allowed_leaves)
    if data.daily_hours is not None:
        fields.append("daily_hours = ?")
        values.append(data.daily_hours)
    if data.pin is not None:
        fields.append("pin = ?")
        values.append(data.pin.strip())
    if data.is_temp_delivery_staff is not None:
        fields.append("is_temp_delivery_staff = ?")
        values.append(int(data.is_temp_delivery_staff))

    if fields:
        values.append(staff_id)
        cursor.execute(f"UPDATE staff SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    conn.close()
    return {"success": True, "message": "Staff member updated successfully."}

@app.post("/api/staff/{staff_id}/toggle-police-report")
def toggle_police_report(staff_id: int):
    """Toggles police report verification status (0 <-> 1) for a staff member."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, police_report FROM staff WHERE id = ? AND is_active = 1", (staff_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Staff member not found")
    
    current_status = row["police_report"] or 0
    new_status = 0 if current_status == 1 else 1
    cursor.execute("UPDATE staff SET police_report = ? WHERE id = ?", (new_status, staff_id))
    conn.commit()
    conn.close()
    return {
        "success": True, 
        "police_report": new_status, 
        "message": f"Police report for {row['name']} updated to {'Yes (Verified)' if new_status == 1 else 'No (Pending)'}."
    }

@app.delete("/api/staff/{staff_id}")
def delete_staff(staff_id: int):
    """Soft-deletes / deactivates a staff member."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE staff SET is_active = 0 WHERE id = ?", (staff_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Staff member deactivated successfully."}

@app.get("/api/staff/{staff_id}/history")
def get_staff_history(staff_id: int):
    """Returns complete staff dossier: bio, attendance history, leaves, advances/credits."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.*, coalesce(nullif(s.designation, ''), s.role) as designation, sh.name as shift_name, sh.start_time, sh.end_time
        FROM staff s
        JOIN shifts sh ON s.shift_id = sh.id
        WHERE s.id = ?
    """, (staff_id,))
    staff = cursor.fetchone()
    if not staff:
        conn.close()
        raise HTTPException(status_code=404, detail="Staff not found")

    # 1. Attendance logs history
    cursor.execute("""
        SELECT * FROM attendance_logs WHERE staff_id = ? ORDER BY date DESC LIMIT 60
    """, (staff_id,))
    attendance = [dict(r) for r in cursor.fetchall()]

    # 2. Leaves history
    cursor.execute("""
        SELECT * FROM leaves WHERE staff_id = ? ORDER BY date DESC
    """, (staff_id,))
    leaves = [dict(r) for r in cursor.fetchall()]

    # 3. Advances & Medicine Credit Khata
    cursor.execute("""
        SELECT * FROM advance_salaries WHERE staff_id = ? ORDER BY date DESC
    """, (staff_id,))
    advances = [dict(r) for r in cursor.fetchall()]

    # Calculate summary counters
    cursor.execute("SELECT COUNT(*) FROM attendance_logs WHERE staff_id = ? AND status IN ('ON_TIME', 'PRESENT', 'LATE', 'HALF_DAY')", (staff_id,))
    total_present_days = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM leaves WHERE staff_id = ?", (staff_id,))
    total_leaves = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(amount) FROM advance_salaries WHERE staff_id = ? AND is_settled = 0", (staff_id,))
    res_adv = cursor.fetchone()[0]
    unsettled_advances = res_adv if res_adv else 0.0

    conn.close()

    return {
        "profile": dict(staff),
        "total_present_days": total_present_days,
        "total_leaves": total_leaves,
        "unsettled_advances": unsettled_advances,
        "attendance": attendance,
        "leaves": leaves,
        "advances": advances
    }

@app.get("/api/shifts")
def list_shifts():
    """Lists all available work shifts."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shifts ORDER BY id ASC")
    shifts = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return shifts

@app.get("/api/advances")
def list_advances():
    """Lists all cash advances taken by staff from counter drawer."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.*, s.name as staff_name, s.role
        FROM advance_salaries a
        JOIN staff s ON a.staff_id = s.id
        ORDER BY a.id DESC
    """)
    advances = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return advances

@app.post("/api/advances")
def create_advance(data: AdvanceCreate):
    """Records an advance cash payout or medicine credit given to staff."""
    date_str = data.date_str or date.today().strftime("%Y-%m-%d")
    entry_type = data.entry_type or "ADVANCE"
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO advance_salaries (staff_id, entry_type, amount, date, reason)
        VALUES (?, ?, ?, ?, ?)
    """, (data.staff_id, entry_type, data.amount, date_str, data.reason))
    new_id = cursor.lastrowid
    cursor.execute("SELECT name FROM staff WHERE id = ?", (data.staff_id,))
    s_row = cursor.fetchone()
    staff_name = s_row["name"] if s_row else f"Staff #{data.staff_id}"
    conn.commit()
    conn.close()

    label = "Medicine Credit" if entry_type == "MEDICINE_CREDIT" else "Cash Advance"
    log_activity(
        category="STAFF_KHATA",
        action_type="ADVANCE_ADDED",
        title=f"Staff Khata ({label}): {staff_name}",
        description=f"Rs. {data.amount:,.2f} recorded • Reason: {data.reason or 'Staff advance'}",
        staff_name=staff_name,
        amount=data.amount,
        date_str=date_str
    )

    return {"success": True, "id": new_id, "message": f"{label} of Rs. {data.amount:,.2f} recorded successfully."}

@app.post("/api/advances/{advance_id}/settle")
def settle_advance(advance_id: int, req: Optional[AdvanceSettleRequest] = None):
    """Direct settlement of a staff advance or medicine credit with audit tracking."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.*, s.name as staff_name 
        FROM advance_salaries a 
        JOIN staff s ON a.staff_id = s.id 
        WHERE a.id = ?
    """, (advance_id,))
    adv = cursor.fetchone()
    if not adv:
        conn.close()
        raise HTTPException(status_code=404, detail="Advance record not found")

    settled_date = (req.settled_at if req and req.settled_at else date.today().strftime("%Y-%m-%d"))
    settlement_type = (req.settlement_type if req and req.settlement_type else "Direct Counter Settlement")
    notes_val = (req.notes.strip() if req and req.notes else "")

    # Only assign settled payroll month/year if deducted via salary
    month_val = 0
    year_val = 0
    if "salary" in settlement_type.lower():
        try:
            parts = settled_date.split("-")
            year_val = int(parts[0])
            month_val = int(parts[1])
        except Exception:
            pass

    orig_amount = float(adv["amount"])
    if req and req.amount is not None and 0 < req.amount < orig_amount:
        paid_amt = round(float(req.amount), 2)
        rem_amt = round(orig_amount - paid_amt, 2)

        audit_note = f"Partial payment Rs. {paid_amt:,.2f} on {settled_date} via {settlement_type}"
        if notes_val:
            audit_note += f" ({notes_val})"

        # 1. Update this advance entry to be the settled portion
        cursor.execute("""
            UPDATE advance_salaries
            SET amount = ?,
                is_settled = 1,
                settled_at = ?,
                settlement_type = ?,
                notes = CASE WHEN notes != '' THEN notes || ' | ' || ? ELSE ? END,
                settled_payroll_month = ?,
                settled_payroll_year = ?
            WHERE id = ?
        """, (paid_amt, settled_date, settlement_type, audit_note, audit_note, month_val, year_val, advance_id))

        # 2. Insert new entry for remaining unpaid balance
        cursor.execute("""
            INSERT INTO advance_salaries (staff_id, entry_type, amount, date, reason, is_settled)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (adv["staff_id"], adv["entry_type"], rem_amt, adv["date"], f"{adv['reason']} (Baqaya / Remainder)"))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "partial": True,
            "advance_id": advance_id,
            "paid_amount": paid_amt,
            "remaining_amount": rem_amt,
            "settled_at": settled_date,
            "settlement_type": settlement_type,
            "notes": notes_val,
            "message": f"Partial settlement of Rs. {paid_amt:,.2f} recorded for {adv['staff_name']}. Baqaya remaining: Rs. {rem_amt:,.2f}."
        }
    else:
        # Full settlement
        cursor.execute("""
            UPDATE advance_salaries
            SET is_settled = 1, settled_at = ?, settlement_type = ?, notes = ?, settled_payroll_month = ?, settled_payroll_year = ?
            WHERE id = ?
        """, (settled_date, settlement_type, notes_val, month_val, year_val, advance_id))
        conn.commit()
        conn.close()

        log_activity(
            category="STAFF_KHATA",
            action_type="ADVANCE_SETTLED",
            title=f"Staff Khata Settled: {adv['staff_name']}",
            description=f"Rs. {adv['amount']:,.2f} settled via {settlement_type}",
            staff_name=adv['staff_name'],
            amount=adv['amount'],
            date_str=settled_date
        )

        return {
            "success": True,
            "partial": False,
            "message": f"Advance #{advance_id} for {adv['staff_name']} (Rs. {adv['amount']:,.2f}) settled successfully via '{settlement_type}' on {settled_date}.",
            "advance_id": advance_id,
            "settled_at": settled_date,
            "settlement_type": settlement_type,
            "notes": notes_val
        }

@app.post("/api/advances/clear-settled")
def clear_settled_advances():
    """Permanently deletes all settled staff khata / advance records (admin purge)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM advance_salaries WHERE is_settled = 1")
    count = cursor.fetchone()[0] or 0
    if count == 0:
        conn.close()
        return {"success": True, "deleted_count": 0, "message": "Koi settled staff khata record mojood nahi hai."}
    
    cursor.execute("DELETE FROM advance_salaries WHERE is_settled = 1")
    conn.commit()
    conn.close()
    return {"success": True, "deleted_count": count, "message": f"{count} settled staff khata records kamyabi se delete ho gaye."}

@app.delete("/api/advances/{advance_id}")
@app.post("/api/advances/{advance_id}/delete")
def delete_advance_salary(advance_id: int):
    """Admin permanently deletes an individual staff advance entry."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT a.*, s.name as staff_name FROM advance_salaries a JOIN staff s ON a.staff_id = s.id WHERE a.id = ?", (advance_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Advance record not found")
    adv = dict(row)

    cursor.execute("DELETE FROM advance_salaries WHERE id = ?", (advance_id,))
    conn.commit()
    conn.close()

    log_activity(
        category="STAFF_KHATA",
        action_type="ADVANCE_DELETED",
        title=f"Staff Advance Deleted: {adv['staff_name']}",
        description=f"Admin deleted advance entry of Rs. {adv['amount']:,.2f} for {adv['staff_name']}",
        staff_name="Admin"
    )

    return {"success": True, "advance_id": advance_id, "message": f"Advance of Rs. {adv['amount']:,.2f} deleted."}

@app.post("/api/leaves")
def approve_leave(data: LeaveCreate):
    """Approves an emergency/sick leave (Full-Day or Half-Day) so salary is not cut."""
    conn = get_db_connection()
    cursor = conn.cursor()
    leave_type = data.leave_type or "FULL_DAY"
    cursor.execute("""
        INSERT INTO leaves (staff_id, date, reason, leave_type)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(staff_id, date) DO UPDATE SET reason = excluded.reason, leave_type = excluded.leave_type
    """, (data.staff_id, data.date, data.reason, leave_type))
    note_label = f"Approved {'Half-Day' if leave_type == 'HALF_DAY' else ''} Leave: {data.reason}".strip()
    cursor.execute("""
        UPDATE attendance_logs 
        SET status = 'LEAVE', notes = coalesce(nullif(notes, ''), ?)
        WHERE staff_id = ? AND date = ? AND status = 'ABSENT'
    """, (note_label, data.staff_id, data.date))
    cursor.execute("SELECT name FROM staff WHERE id = ?", (data.staff_id,))
    s_row = cursor.fetchone()
    staff_name = s_row["name"] if s_row else f"Staff #{data.staff_id}"
    conn.commit()
    conn.close()

    type_label = "Half-Day (0.5)" if leave_type == "HALF_DAY" else "Full-Day (1.0)"
    log_activity(
        category="LEAVE",
        action_type="LEAVE_APPLIED",
        title=f"Leave Approved ({type_label}): {staff_name}",
        description=f"Date: {data.date} • Reason: {data.reason}",
        staff_name=staff_name,
        date_str=data.date
    )

    return {"success": True, "message": f"{'Half-Day' if leave_type == 'HALF_DAY' else 'Full-Day'} leave approved for date {data.date}."}

@app.get("/api/leaves")
def get_leaves():
    """Returns all approved leaves with staff details and leave type."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT l.id, l.staff_id, s.name as staff_name, s.designation, s.role, s.allowed_leaves,
               l.date, l.reason, coalesce(l.leave_type, 'FULL_DAY') as leave_type, l.approved_by, l.created_at
        FROM leaves l
        JOIN staff s ON l.staff_id = s.id
        ORDER BY l.date DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@app.put("/api/leaves/{leave_id}")
def update_leave(leave_id: int, data: LeaveUpdate):
    """Updates an existing leave record (date, reason, leave_type)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT staff_id, date, reason, coalesce(leave_type, 'FULL_DAY') as leave_type FROM leaves WHERE id = ?", (leave_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Leave record not found")
    
    staff_id = row["staff_id"]
    old_date = row["date"]
    new_date = data.date if data.date is not None else row["date"]
    new_reason = data.reason if data.reason is not None else row["reason"]
    new_type = data.leave_type if data.leave_type is not None else row["leave_type"]

    # Check for conflict if date changed
    if new_date != old_date:
        cursor.execute("SELECT id FROM leaves WHERE staff_id = ? AND date = ? AND id != ?", (staff_id, new_date, leave_id))
        if cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="Is staff ki is date par pehle se leave darj hai.")

    cursor.execute("UPDATE leaves SET date = ?, reason = ?, leave_type = ? WHERE id = ?", (new_date, new_reason, new_type, leave_id))

    # Update attendance_logs status if date changed
    if new_date != old_date:
        cursor.execute("""
            UPDATE attendance_logs 
            SET status = 'ABSENT', notes = NULL 
            WHERE staff_id = ? AND date = ? AND status = 'LEAVE'
        """, (staff_id, old_date))

    note_label = f"Approved {'Half-Day' if new_type == 'HALF_DAY' else ''} Leave: {new_reason}".strip()
    cursor.execute("""
        UPDATE attendance_logs 
        SET status = 'LEAVE', notes = coalesce(nullif(notes, ''), ?)
        WHERE staff_id = ? AND date = ? AND status = 'ABSENT'
    """, (note_label, staff_id, new_date))

    cursor.execute("SELECT name FROM staff WHERE id = ?", (staff_id,))
    s_row = cursor.fetchone()
    staff_name = s_row["name"] if s_row else f"Staff #{staff_id}"

    conn.commit()
    conn.close()

    type_label = "Half-Day (0.5)" if new_type == "HALF_DAY" else "Full-Day (1.0)"
    log_activity(
        category="LEAVE",
        action_type="LEAVE_EDITED",
        title=f"Leave Updated ({type_label}): {staff_name}",
        description=f"Date: {new_date} • Reason: {new_reason}",
        staff_name=staff_name,
        date_str=new_date
    )

    return {"success": True, "message": "Leave updated successfully."}

@app.delete("/api/leaves/{leave_id}")
def delete_leave(leave_id: int):
    """Deletes an approved leave record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT staff_id, date FROM leaves WHERE id = ?", (leave_id,))
    row = cursor.fetchone()
    staff_name = ""
    leave_date = ""
    if row:
        cursor.execute("SELECT name FROM staff WHERE id = ?", (row["staff_id"],))
        s_row = cursor.fetchone()
        staff_name = s_row["name"] if s_row else f"Staff #{row['staff_id']}"
        leave_date = row["date"]
        cursor.execute("""
            UPDATE attendance_logs 
            SET status = 'ABSENT', notes = NULL 
            WHERE staff_id = ? AND date = ? AND status = 'LEAVE'
        """, (row["staff_id"], row["date"]))

    cursor.execute("DELETE FROM leaves WHERE id = ?", (leave_id,))
    conn.commit()
    conn.close()

    log_activity(
        category="LEAVE",
        action_type="LEAVE_DELETED",
        title=f"Leave Cancelled: {staff_name}",
        description=f"Leave on {leave_date} cancelled from records",
        staff_name=staff_name,
        date_str=leave_date
    )

    return {"success": True, "message": "Leave deleted."}

@app.get("/api/payroll/calculate")
def get_payroll(month: int = Query(..., ge=1, le=12), year: int = Query(..., ge=2020)):
    """Computes month-end payroll for all active staff."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM staff WHERE is_active = 1")
    staff_ids = [row["id"] for row in cursor.fetchall()]
    conn.close()

    results = []
    total_payout = 0.0
    total_deductions = 0.0

    for sid in staff_ids:
        payroll = calculate_monthly_payroll(sid, month, year)
        results.append(payroll)
        total_payout += payroll["net_payable"]
        total_deductions += (
            payroll.get("absent_cut", 0.0) +
            payroll.get("extra_leave_cut", 0.0) +
            payroll.get("extra_half_day_cut", 0.0) +
            payroll.get("advances_deducted", 0.0)
        )

    return {
        "month": month,
        "year": year,
        "month_name": calendar.month_name[month],
        "total_staff": len(results),
        "total_payout": round(total_payout, 2),
        "total_deductions": round(total_deductions, 2),
        "sheet": results
    }

@app.get("/api/payroll/calculate-range")
def get_range_payroll(
    staff_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None
):
    """
    Computes custom rolling date-range payroll for individual or all staff members.
    Supports calculating salary from last paid date (e.g. 3rd to 17th) or joining date.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if staff_id:
        cursor.execute("SELECT id FROM staff WHERE id = ? AND is_active = 1", (staff_id,))
    else:
        cursor.execute("SELECT id FROM staff WHERE is_active = 1")

    staff_ids = [row["id"] for row in cursor.fetchall()]
    conn.close()

    if not staff_ids:
        raise HTTPException(status_code=404, detail="No active staff found.")

    results = []
    total_payout = 0.0

    for sid in staff_ids:
        payroll = calculate_custom_range_payroll(sid, from_date_str=from_date, to_date_str=to_date)
        results.append(payroll)
        total_payout += payroll["net_payable"]

    return {
        "from_date": from_date,
        "to_date": to_date,
        "total_staff": len(results),
        "total_payout": round(total_payout, 2),
        "sheet": results
    }

@app.post("/api/payroll/disburse")
def disburse_salary(data: PayrollDisburseRequest):
    """
    Marks staff member's monthly salary as PAID with payment date, method, and audit notes.
    Automatically settles all pending Khata entries (advances and medicine credits)
    deducted in this payroll.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Verify staff exists
    cursor.execute("SELECT id, name FROM staff WHERE id = ? AND is_active = 1", (data.staff_id,))
    staff = cursor.fetchone()
    if not staff:
        conn.close()
        raise HTTPException(status_code=404, detail="Staff member not found")

    # 2. Ensure payroll is calculated and recorded in payroll_records
    payroll_data = calculate_monthly_payroll(data.staff_id, data.month, data.year)

    paid_date = data.paid_at if data.paid_at and data.paid_at.strip() else date.today().strftime("%Y-%m-%d")
    payment_method = data.payment_method if data.payment_method and data.payment_method.strip() else "Cash"
    notes_val = data.notes.strip() if data.notes else ""

    # 3. Mark payroll record as PAID
    cursor.execute("""
        UPDATE payroll_records
        SET status = 'PAID', paid_at = ?, payment_method = ?, notes = ?
        WHERE staff_id = ? AND month = ? AND year = ?
    """, (paid_date, payment_method, notes_val, data.staff_id, data.month, data.year))

    # 4. Auto-settle all unsettled advances and medicine credits for this staff member up to this month's end
    days_in_month = calendar.monthrange(data.year, data.month)[1]
    end_date_str = f"{data.year}-{data.month:02d}-{days_in_month:02d}"
    month_name = calendar.month_name[data.month]
    settlement_type = f"Deducted from {month_name} {data.year} Salary"
    auto_note = f"Auto-settled via {month_name} {data.year} salary payment ({paid_date} via {payment_method})"
    if notes_val:
        auto_note += f" - {notes_val}"

    # Find which advances will be settled
    cursor.execute("""
        SELECT id, amount, entry_type, date 
        FROM advance_salaries 
        WHERE staff_id = ? AND is_settled = 0 AND date <= ?
    """, (data.staff_id, end_date_str))
    pending_advances = cursor.fetchall()
    auto_settled_count = len(pending_advances)
    auto_settled_amount = sum(row["amount"] for row in pending_advances)

    if auto_settled_count > 0:
        cursor.execute("""
            UPDATE advance_salaries
            SET is_settled = 1,
                settled_at = ?,
                settlement_type = ?,
                settled_payroll_month = ?,
                settled_payroll_year = ?,
                notes = ?
            WHERE staff_id = ? AND is_settled = 0 AND date <= ?
        """, (paid_date, settlement_type, data.month, data.year, auto_note, data.staff_id, end_date_str))

    conn.commit()
    conn.close()

    # Re-calculate to return updated payroll info
    updated_payroll = calculate_monthly_payroll(data.staff_id, data.month, data.year)

    log_activity(
        category="PAYROLL",
        action_type="SALARY_PAID",
        title=f"Salary Disbursed: {staff['name']}",
        description=f"Rs. {updated_payroll['net_payable']:,.2f} for {month_name} {data.year} ({payment_method})",
        staff_name=staff["name"],
        amount=updated_payroll["net_payable"],
        date_str=paid_date
    )

    return {
        "success": True,
        "message": f"Salary for {staff['name']} ({month_name} {data.year}) marked as PAID on {paid_date} via {payment_method}. {auto_settled_count} Khata advance(s) totalling Rs. {auto_settled_amount:,.2f} auto-settled.",
        "staff_id": data.staff_id,
        "staff_name": staff["name"],
        "month": data.month,
        "year": data.year,
        "paid_at": paid_date,
        "payment_method": payment_method,
        "net_payable": updated_payroll["net_payable"],
        "auto_settled_advances_count": auto_settled_count,
        "auto_settled_advances_amount": auto_settled_amount
    }

# =====================================================================
# CUSTOMER UDHAR & SERIES KHATA LEDGER ENDPOINTS
# =====================================================================

def format_whatsapp_number(phone: str) -> str:
    digits = re.sub(r'[^0-9]', '', phone or '')
    if digits.startswith('03') and len(digits) == 11:
        return '92' + digits[1:]
    elif digits.startswith('3') and len(digits) == 10:
        return '92' + digits
    elif digits.startswith('92') and len(digits) == 12:
        return digits
    return digits

@app.get("/api/customers")
def get_customers():
    """Returns all customers with aggregated series khata metrics."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            c.id, c.name, c.phone, c.address, c.credit_limit, c.is_active, c.created_at,
            COALESCE(SUM(k.amount), 0) as total_credit,
            COALESCE(SUM(CASE WHEN k.is_settled = 1 THEN k.amount ELSE 0 END), 0) as total_settled,
            COALESCE(SUM(CASE WHEN k.is_settled = 0 THEN k.amount ELSE 0 END), 0) as current_balance,
            COALESCE(SUM(CASE WHEN k.is_settled = 0 THEN 1 ELSE 0 END), 0) as pending_invoices_count,
            COUNT(k.id) as total_invoices_count
        FROM customers c
        LEFT JOIN customer_khata k ON c.id = k.customer_id
        GROUP BY c.id
        ORDER BY current_balance DESC, c.name ASC
    """)
    rows = cursor.fetchall()
    customers = []
    for r in rows:
        c_dict = dict(r)
        c_dict["credit_limit"] = float(c_dict["credit_limit"])
        c_dict["total_credit"] = float(c_dict["total_credit"])
        c_dict["total_settled"] = float(c_dict["total_settled"])
        c_dict["current_balance"] = float(c_dict["current_balance"])
        limit_used_pct = round((c_dict["current_balance"] / c_dict["credit_limit"]) * 100, 1) if c_dict["credit_limit"] > 0 else 0
        c_dict["limit_used_pct"] = min(100.0, limit_used_pct)
        c_dict["wa_phone"] = format_whatsapp_number(c_dict["phone"])
        customers.append(c_dict)
    conn.close()
    return customers

@app.post("/api/customers")
def create_customer(data: CustomerCreate):
    """Registers a new customer account."""
    conn = get_db_connection()
    cursor = conn.cursor()
    added_by = (data.added_by or "Admin").strip()
    is_staff = bool(data.is_staff or ("Staff" in added_by))
    if data.approval_status:
        approval_status = data.approval_status.strip()
    else:
        approval_status = "PENDING" if is_staff else "APPROVED"

    approved_by = "Admin" if approval_status == "APPROVED" else ""
    approved_at = datetime.now().isoformat() if approval_status == "APPROVED" else ""

    cursor.execute("""
        INSERT INTO customers (name, phone, address, credit_limit, added_by, approval_status, approved_by, approved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (data.name.strip(), data.phone.strip(), (data.address or "").strip(), data.credit_limit or 15000.0, added_by, approval_status, approved_by, approved_at))
    customer_id = cursor.lastrowid

    if approval_status == "PENDING":
        details_txt = f"New Customer: {data.name.strip()} • Phone: {data.phone.strip()} • Limit: Rs. {(data.credit_limit or 15000.0):,.2f}"
        if data.address:
            details_txt += f" • Addr: {data.address.strip()}"
        cursor.execute("""
            INSERT INTO staff_approval_requests (request_type, customer_id, customer_name, reference_id, amount, details, notes, status, added_by)
            VALUES ('NEW_CUSTOMER', ?, ?, ?, ?, ?, ?, 'PENDING', ?)
        """, (customer_id, data.name.strip(), customer_id, data.credit_limit or 15000.0, details_txt, "New Customer Added by Staff", added_by))

    conn.commit()
    conn.close()
    msg = f"Customer '{data.name}' registered successfully." if approval_status == "APPROVED" else f"Customer '{data.name}' registered (Pending Admin Approval)."
    return {"success": True, "id": customer_id, "status": approval_status, "approval_status": approval_status, "message": msg}

@app.put("/api/customers/{customer_id}")
def update_customer(customer_id: int, data: CustomerUpdate):
    """Updates customer profile."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    existing = cursor.fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Customer not found")

    new_name = data.name.strip() if data.name is not None else existing["name"]
    new_phone = data.phone.strip() if data.phone is not None else existing["phone"]
    new_address = data.address.strip() if data.address is not None else existing["address"]
    new_limit = data.credit_limit if data.credit_limit is not None else existing["credit_limit"]
    new_active = data.is_active if data.is_active is not None else existing["is_active"]
    new_staff = data.added_by.strip() if data.added_by is not None else existing["added_by"]

    cursor.execute("""
        UPDATE customers
        SET name = ?, phone = ?, address = ?, credit_limit = ?, is_active = ?, added_by = ?
        WHERE id = ?
    """, (new_name, new_phone, new_address, new_limit, new_active, new_staff, customer_id))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Customer '{new_name}' updated successfully."}

@app.delete("/api/customers/{customer_id}")
@app.post("/api/customers/{customer_id}/delete")
def delete_customer_endpoint(customer_id: int):
    """Admin permanently deletes a customer and their ledger history."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Customer not found")
    cust = dict(row)

    cursor.execute("DELETE FROM customer_khata WHERE customer_id = ?", (customer_id,))
    cursor.execute("DELETE FROM staff_approval_requests WHERE customer_id = ?", (customer_id,))
    cursor.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    conn.commit()
    conn.close()

    log_activity(
        category="CUSTOMER_KHATA",
        action_type="CUSTOMER_DELETED",
        title=f"Customer Deleted: {cust['name']}",
        description=f"Admin deleted customer '{cust['name']}' and all associated ledger records.",
        staff_name="Admin"
    )

    return {"success": True, "customer_id": customer_id, "message": f"Customer '{cust['name']}' and all ledger records deleted."}

@app.put("/api/customers/{customer_id}/reassign-staff")
def reassign_customer_staff_endpoint(customer_id: int, data: CustomerReassignStaff):
    """Admin transfers customer khata responsibility to another staff member."""
    try:
        res = reassign_customer_staff(
            customer_id=customer_id,
            new_staff=data.new_staff.strip(),
            reassign_bills=bool(data.reassign_bills)
        )
        log_activity(
            category="CUSTOMER_KHATA",
            action_type="STAFF_REASSIGNED",
            title=f"Khata Responsibility Reassigned: {res['customer_name']}",
            description=f"Assigned staff changed from '{res['old_staff']}' to '{res['new_staff']}' ({res['bills_updated']} bills updated)",
            staff_name=res['new_staff']
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.put("/api/customer-khata/{entry_id}/reassign-staff")
def reassign_khata_bill_staff_endpoint(entry_id: int, data: KhataBillReassignStaff):
    """Admin changes the handling staff member for an individual credit invoice."""
    try:
        res = reassign_khata_bill_staff(
            entry_id=entry_id,
            new_staff=data.new_staff.strip()
        )
        log_activity(
            category="CUSTOMER_KHATA",
            action_type="BILL_STAFF_REASSIGNED",
            title=f"Bill Staff Changed: #{res['invoice_no']}",
            description=f"Invoice #{res['invoice_no']} staff changed from '{res['old_staff']}' to '{res['new_staff']}'",
            staff_name=res['new_staff']
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/api/customers/{customer_id}/ledger")
def get_customer_ledger(customer_id: int):
    """Returns chronological series khata ledger for a customer."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    customer_row = cursor.fetchone()
    if not customer_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Customer not found")

    customer = dict(customer_row)
    cursor.execute("""
        SELECT * FROM customer_khata
        WHERE customer_id = ?
        ORDER BY date ASC, id ASC
    """, (customer_id,))
    entries = [dict(r) for r in cursor.fetchall()]
    conn.close()

    total_credit = sum(e["amount"] for e in entries)
    total_settled = sum(e["amount"] for e in entries if e["is_settled"] == 1)
    current_balance = sum(e["amount"] for e in entries if e["is_settled"] == 0)
    pending_count = sum(1 for e in entries if e["is_settled"] == 0)

    customer["wa_phone"] = format_whatsapp_number(customer["phone"])

    return {
        "customer": customer,
        "summary": {
            "total_credit": total_credit,
            "total_settled": total_settled,
            "current_balance": current_balance,
            "pending_count": pending_count,
            "total_entries": len(entries)
        },
        "ledger": entries
    }

@app.post("/api/customer-khata")
def add_customer_khata(data: CustomerKhataCreate):
    """Adds a new credit purchase entry into customer's series khata."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE id = ?", (data.customer_id,))
    customer = cursor.fetchone()
    if not customer:
        conn.close()
        raise HTTPException(status_code=404, detail="Customer not found")

    entry_date = data.date or date.today().isoformat()
    invoice_no = data.invoice_no
    if not invoice_no or not invoice_no.strip():
        cursor.execute("SELECT MAX(id) FROM customer_khata")
        max_id = cursor.fetchone()[0] or 1000
        invoice_no = f"INV-{1000 + max_id + 1}"

    added_by = (data.added_by or "Admin").strip()
    is_staff = bool(data.is_staff or (added_by and added_by.lower() != "admin"))
    if data.approval_status:
        approval_status = data.approval_status.strip()
    else:
        approval_status = "PENDING" if is_staff else "APPROVED"

    approved_by = "Admin" if approval_status == "APPROVED" else ""
    approved_at = datetime.now().isoformat() if approval_status == "APPROVED" else ""

    cursor.execute("""
        INSERT INTO customer_khata (customer_id, invoice_no, date, item_description, amount, is_settled, notes, added_by, approval_status, approved_by, approved_at)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
    """, (
        data.customer_id,
        invoice_no.strip(),
        entry_date,
        data.item_description.strip(),
        data.amount,
        (data.notes or "").strip(),
        added_by,
        approval_status,
        approved_by,
        approved_at
    ))
    entry_id = cursor.lastrowid

    if approval_status == "PENDING":
        details_txt = f"Invoice #{invoice_no}: {data.item_description.strip()} • Amount: Rs. {data.amount:,.2f}"
        if data.notes:
            details_txt += f" • Notes: {data.notes.strip()}"
        cursor.execute("""
            INSERT INTO staff_approval_requests (request_type, customer_id, customer_name, reference_id, amount, details, notes, status, added_by)
            VALUES ('CREDIT_PURCHASE', ?, ?, ?, ?, ?, ?, 'PENDING', ?)
        """, (data.customer_id, customer["name"], entry_id, data.amount, details_txt, data.notes or "", added_by))

    conn.commit()

    # Get updated balance
    cursor.execute("SELECT SUM(amount) FROM customer_khata WHERE customer_id = ? AND is_settled = 0", (data.customer_id,))
    new_balance = cursor.fetchone()[0] or 0.0
    conn.close()

    status_tag = f" [{approval_status}]" if approval_status != "APPROVED" else ""
    log_activity(
        category="CUSTOMER_KHATA",
        action_type="CUSTOMER_KHATA_ADDED",
        title=f"Customer Credit: {customer['name']}{status_tag}",
        description=f"Invoice #{invoice_no}: {data.item_description.strip()} (Rs. {data.amount:,.2f}) • By: {added_by}",
        staff_name=customer["name"],
        amount=data.amount,
        date_str=entry_date
    )

    return {
        "success": True,
        "id": entry_id,
        "invoice_no": invoice_no,
        "amount": data.amount,
        "customer_name": customer["name"],
        "new_balance": new_balance,
        "added_by": added_by,
        "approval_status": approval_status,
        "message": f"Credit purchase of Rs. {data.amount:,.2f} recorded for {customer['name']} ({invoice_no}). Status: {approval_status}"
    }

@app.post("/api/customer-khata/{entry_id}/approve")
def approve_customer_khata(entry_id: int, data: Optional[Dict[str, Any]] = Body(None)):
    """Admin approves a customer khata entry submitted by staff."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT k.*, c.name as customer_name FROM customer_khata k JOIN customers c ON k.customer_id = c.id WHERE k.id = ?", (entry_id,))
    entry_row = cursor.fetchone()
    if not entry_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Khata entry not found")

    entry = dict(entry_row)
    now_str = datetime.now().isoformat()
    staff_to_use = (data.get("assigned_staff") if isinstance(data, dict) else None) or entry.get("added_by") or "Staff (Counter)"
    staff_to_use = str(staff_to_use).strip()

    cursor.execute("""
        UPDATE customer_khata
        SET added_by = ?, approval_status = 'APPROVED', approved_by = 'Admin', approved_at = ?
        WHERE id = ?
    """, (staff_to_use, now_str, entry_id))
    cursor.execute("""
        UPDATE staff_approval_requests
        SET status = 'APPROVED', added_by = ?, approved_by = 'Admin', approved_at = ?
        WHERE request_type = 'CREDIT_PURCHASE' AND reference_id = ?
    """, (staff_to_use, now_str, entry_id))
    conn.commit()

    cursor.execute("SELECT SUM(amount) FROM customer_khata WHERE customer_id = ? AND is_settled = 0", (entry["customer_id"],))
    new_balance = cursor.fetchone()[0] or 0.0
    conn.close()

    log_activity(
        category="CUSTOMER_KHATA",
        action_type="CUSTOMER_KHATA_APPROVED",
        title=f"Khata Approved: {entry['customer_name']}",
        description=f"Invoice #{entry['invoice_no']} (Rs. {entry['amount']:,.2f}) approved by Admin.",
        staff_name=entry["customer_name"],
        amount=entry["amount"],
        date_str=date.today().isoformat()
    )

    return {
        "success": True,
        "id": entry_id,
        "invoice_no": entry["invoice_no"],
        "approval_status": "APPROVED",
        "approved_by": "Admin",
        "new_balance": new_balance,
        "message": f"Invoice {entry['invoice_no']} approved successfully by Admin."
    }

@app.delete("/api/customer-khata/{entry_id}")
@app.post("/api/customer-khata/{entry_id}/delete")
def delete_customer_khata_entry(entry_id: int):
    """Admin permanently deletes an individual credit invoice/khata entry."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT k.*, c.name as customer_name 
        FROM customer_khata k 
        JOIN customers c ON k.customer_id = c.id 
        WHERE k.id = ?
    """, (entry_id,))
    entry_row = cursor.fetchone()
    if not entry_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Khata entry not found")

    entry = dict(entry_row)
    customer_id = entry["customer_id"]
    customer_name = entry["customer_name"]
    inv_no = entry.get("invoice_no") or f"#{entry_id}"
    amount = float(entry.get("amount") or 0.0)

    # 1. Delete from customer_khata table
    cursor.execute("DELETE FROM customer_khata WHERE id = ?", (entry_id,))

    # 2. Clean up any related staff approval requests
    cursor.execute("""
        DELETE FROM staff_approval_requests 
        WHERE reference_id = ? AND request_type IN ('CREDIT_PURCHASE', 'SETTLEMENT', 'KHATA_SETTLEMENT')
    """, (entry_id,))

    conn.commit()

    # 3. Recalculate remaining customer balance
    cursor.execute("SELECT SUM(amount) FROM customer_khata WHERE customer_id = ? AND is_settled = 0", (customer_id,))
    new_balance = cursor.fetchone()[0] or 0.0
    conn.close()

    # 4. Log audit activity
    log_activity(
        category="CUSTOMER_KHATA",
        action_type="CUSTOMER_KHATA_DELETED",
        title=f"Khata Entry Deleted: #{inv_no}",
        description=f"Admin deleted khata bill #{inv_no} (Rs. {amount:,.2f}) for '{customer_name}'.",
        staff_name="Admin",
        amount=amount,
        date_str=date.today().isoformat()
    )

    return {
        "success": True,
        "id": entry_id,
        "customer_id": customer_id,
        "new_balance": new_balance,
        "message": f"Khata bill #{inv_no} (Rs. {amount:,.2f}) successfully deleted."
    }

# --- Admin Unified Approval Center Endpoints ---

@app.get("/api/admin/pending-requests")
def get_pending_staff_requests():
    """Returns all pending staff requests (New Customers, Credit Purchases, Settlements)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM staff_approval_requests
        WHERE status = 'PENDING'
        ORDER BY id DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"success": True, "requests": rows}

@app.post("/api/admin/pending-requests/{request_id}/approve")
def approve_staff_request(request_id: int, data: Optional[Dict[str, Any]] = Body(None)):
    """Admin approves a staff request and executes the corresponding action."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM staff_approval_requests WHERE id = ?", (request_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Request not found")

    req = dict(row)
    now_str = datetime.now().isoformat()
    req_type = req["request_type"]
    staff_to_use = (data.get("assigned_staff") if isinstance(data, dict) else None) or req.get("added_by") or "Staff (Counter)"
    staff_to_use = str(staff_to_use).strip()

    if req_type == "NEW_CUSTOMER":
        cursor.execute("""
            UPDATE customers
            SET added_by = ?, approval_status = 'APPROVED', approved_by = 'Admin', approved_at = ?
            WHERE id = ?
        """, (staff_to_use, now_str, req["reference_id"]))

    elif req_type == "CREDIT_PURCHASE":
        cursor.execute("""
            UPDATE customer_khata
            SET added_by = ?, approval_status = 'APPROVED', approved_by = 'Admin', approved_at = ?
            WHERE id = ?
        """, (staff_to_use, now_str, req["reference_id"]))

    elif req_type == "SETTLEMENT":
        payload = json.loads(req["payload_json"] or "{}")
        entry_id = payload.get("entry_id") or req["reference_id"]
        cursor.execute("SELECT * FROM customer_khata WHERE id = ?", (entry_id,))
        entry_row = cursor.fetchone()
        if entry_row:
            entry = dict(entry_row)
            orig_amount = float(entry["amount"])
            paid_amt = float(payload.get("amount", orig_amount))
            pay_method = payload.get("payment_method", req["payment_method"] or "Cash")
            settle_date = payload.get("settled_at", date.today().isoformat())
            notes_val = payload.get("notes", "")

            if paid_amt < orig_amount:
                rem_amt = round(orig_amount - paid_amt, 2)
                audit_note = f"Partial payment Rs. {paid_amt:,.2f} received on {settle_date} via {pay_method}"
                if notes_val:
                    audit_note += f" ({notes_val})"
                cursor.execute("""
                    UPDATE customer_khata
                    SET amount = ?, is_settled = 1, settled_at = ?, payment_method = ?, added_by = ?,
                        notes = CASE WHEN notes != '' THEN notes || ' | ' || ? ELSE ? END
                    WHERE id = ?
                """, (paid_amt, settle_date, pay_method, staff_to_use, audit_note, audit_note, entry_id))
                cursor.execute("""
                    INSERT INTO customer_khata (customer_id, invoice_no, date, item_description, amount, is_settled, notes, added_by, approval_status, approved_by, approved_at)
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'APPROVED', 'Admin', ?)
                """, (entry["customer_id"], f"{entry['invoice_no']}-REM", entry["date"], f"{entry['item_description']} (Baqaya)", rem_amt, f"Remaining baqaya from {entry['invoice_no']}", staff_to_use, now_str))
            else:
                audit_note = f"Full payment on {settle_date} via {pay_method}"
                if notes_val:
                    audit_note += f" ({notes_val})"
                cursor.execute("""
                    UPDATE customer_khata
                    SET is_settled = 1, settled_at = ?, payment_method = ?, added_by = ?,
                        notes = CASE WHEN notes != '' THEN notes || ' | ' || ? ELSE ? END
                    WHERE id = ?
                """, (settle_date, pay_method, staff_to_use, audit_note, audit_note, entry_id))

    elif req_type == "SETTLE_ALL":
        payload = json.loads(req["payload_json"] or "{}")
        cust_id = payload.get("customer_id") or req["customer_id"]
        pay_method = payload.get("payment_method", req["payment_method"] or "Cash")
        settle_date = payload.get("settled_at", date.today().isoformat())
        paid_amt = float(payload.get("amount", req["amount"]))

        cursor.execute("SELECT * FROM customer_khata WHERE customer_id = ? AND is_settled = 0 ORDER BY date ASC, id ASC", (cust_id,))
        pending_items = [dict(r) for r in cursor.fetchall()]
        remaining_to_allocate = paid_amt

        for item in pending_items:
            if remaining_to_allocate <= 0:
                break
            item_amt = float(item["amount"])
            if remaining_to_allocate >= item_amt:
                cursor.execute("""
                    UPDATE customer_khata
                    SET is_settled = 1, settled_at = ?, payment_method = ?, added_by = ?,
                        notes = CASE WHEN notes != '' THEN notes || ' | Settle-All' ELSE 'Settle-All Payment' END
                    WHERE id = ?
                """, (settle_date, pay_method, staff_to_use, item["id"]))
                remaining_to_allocate -= item_amt
            else:
                rem_amt = round(item_amt - remaining_to_allocate, 2)
                cursor.execute("""
                    UPDATE customer_khata
                    SET amount = ?, is_settled = 1, settled_at = ?, payment_method = ?, added_by = ?,
                        notes = CASE WHEN notes != '' THEN notes || ' | Partial Settle-All' ELSE 'Partial Settle-All' END
                    WHERE id = ?
                """, (remaining_to_allocate, settle_date, pay_method, staff_to_use, item["id"]))
                cursor.execute("""
                    INSERT INTO customer_khata (customer_id, invoice_no, date, item_description, amount, is_settled, notes, added_by, approval_status, approved_by, approved_at)
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?, 'APPROVED', 'Admin', ?)
                """, (cust_id, f"{item['invoice_no']}-REM", item["date"], f"{item['item_description']} (Baqaya)", rem_amt, f"Remaining baqaya from {item['invoice_no']}", staff_to_use, now_str))
                remaining_to_allocate = 0

    cursor.execute("""
        UPDATE staff_approval_requests
        SET status = 'APPROVED', added_by = ?, approved_by = 'Admin', approved_at = ?
        WHERE id = ?
    """, (staff_to_use, now_str, request_id))
    conn.commit()
    conn.close()

    log_activity(
        category="CUSTOMER_KHATA",
        action_type="STAFF_REQUEST_APPROVED",
        title=f"Staff Request Approved: {req['customer_name']}",
        description=f"{req['request_type']} (Rs. {req['amount']:,.2f}) approved by Admin.",
        staff_name=req["customer_name"],
        amount=req["amount"],
        date_str=date.today().isoformat()
    )

    return {"success": True, "request_id": request_id, "status": "APPROVED", "message": f"{req['request_type']} approved successfully by Admin."}

@app.post("/api/admin/pending-requests/{request_id}/reject")
def reject_staff_request(request_id: int):
    """Admin rejects a staff request."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM staff_approval_requests WHERE id = ?", (request_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Request not found")
    req = dict(row)
    now_str = datetime.now().isoformat()

    if req["request_type"] == "NEW_CUSTOMER":
        cursor.execute("UPDATE customers SET is_active = 0, approval_status = 'REJECTED' WHERE id = ?", (req["reference_id"],))
    elif req["request_type"] == "CREDIT_PURCHASE":
        cursor.execute("DELETE FROM customer_khata WHERE id = ?", (req["reference_id"],))

    cursor.execute("""
        UPDATE staff_approval_requests
        SET status = 'REJECTED', approved_by = 'Admin', approved_at = ?
        WHERE id = ?
    """, (now_str, request_id))
    conn.commit()
    conn.close()

    return {"success": True, "request_id": request_id, "status": "REJECTED", "message": "Request rejected by Admin."}

@app.delete("/api/admin/pending-requests/{request_id}")
@app.post("/api/admin/pending-requests/{request_id}/delete")
def delete_staff_request(request_id: int):
    """Admin permanently deletes/cancels a staff request from queue."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM staff_approval_requests WHERE id = ?", (request_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Request not found")
    req = dict(row)

    # If it was a pending credit purchase, also delete the unapproved khata entry
    if req["request_type"] == "CREDIT_PURCHASE" and req.get("reference_id"):
        cursor.execute("DELETE FROM customer_khata WHERE id = ? AND approval_status = 'PENDING'", (req["reference_id"],))
    elif req["request_type"] == "NEW_CUSTOMER" and req.get("reference_id"):
        cursor.execute("DELETE FROM customers WHERE id = ? AND approval_status = 'PENDING'", (req["reference_id"],))

    cursor.execute("DELETE FROM staff_approval_requests WHERE id = ?", (request_id,))
    conn.commit()
    conn.close()

    log_activity(
        category="CUSTOMER_KHATA",
        action_type="STAFF_REQUEST_DELETED",
        title=f"Staff Request Deleted: {req.get('customer_name') or 'Request #' + str(request_id)}",
        description=f"Admin deleted pending {req.get('request_type')} request (Rs. {float(req.get('amount') or 0):,.2f})",
        staff_name="Admin"
    )

    return {"success": True, "request_id": request_id, "message": "Request permanently deleted."}

class BatchDeleteStaffRequests(BaseModel):
    request_ids: Optional[List[int]] = None
    delete_all: bool = False

@app.post("/api/admin/pending-requests/delete-all")
def batch_delete_staff_requests(data: BatchDeleteStaffRequests):
    """Deletes multiple or all pending staff requests."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if data.delete_all or not data.request_ids:
        cursor.execute("SELECT id FROM staff_approval_requests WHERE status = 'PENDING'")
        ids = [r[0] for r in cursor.fetchall()]
    else:
        ids = data.request_ids
    conn.close()

    deleted_count = 0
    for req_id in ids:
        try:
            res = delete_staff_request(req_id)
            if res.get("success"):
                deleted_count += 1
        except Exception:
            pass
    return {"success": True, "deleted_count": deleted_count, "message": f"{deleted_count} requests deleted."}

@app.post("/api/admin/pending-requests/approve-all")
def batch_approve_staff_requests(data: BatchApproveRequest):
    """Approves multiple or all pending staff requests with 1-click."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if data.approve_all or not data.request_ids:
        cursor.execute("SELECT id FROM staff_approval_requests WHERE status = 'PENDING'")
        ids = [r[0] for r in cursor.fetchall()]
    else:
        ids = data.request_ids
    conn.close()

    approved_count = 0
    staff_map = data.staff_assignments or {}
    for req_id in ids:
        try:
            assigned = staff_map.get(str(req_id)) or staff_map.get(req_id)
            body_arg = {"assigned_staff": assigned} if assigned else None
            res = approve_staff_request(req_id, body_arg)
            if res.get("success"):
                approved_count += 1
        except Exception as e:
            print(f"Error approving request {req_id}:", e)

    return {
        "success": True,
        "approved_count": approved_count,
        "message": f"Successfully approved {approved_count} staff requests."
    }

@app.post("/api/customer-khata/{entry_id}/settle")
def settle_customer_khata(entry_id: int, data: CustomerKhataSettle):
    """Marks a single customer credit invoice as settled in full or in part, or queues for admin approval if staff."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customer_khata WHERE id = ?", (entry_id,))
    entry_row = cursor.fetchone()
    if not entry_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Khata entry not found")

    entry = dict(entry_row)
    if entry["is_settled"] == 1:
        conn.close()
        return {"success": True, "message": "Yeh invoice pehle se settled hai.", "already_settled": True}

    settle_date = data.settled_at or date.today().isoformat()
    pay_method = data.payment_method or "Cash"
    notes_val = (data.notes or "").strip()
    orig_amount = float(entry["amount"])

    # If submitted by Staff, queue into staff_approval_requests
    added_by_val = (data.added_by or "Admin").strip()
    is_staff = bool(data.is_staff or (added_by_val and added_by_val.lower() != "admin"))
    if is_staff:
        cursor.execute("SELECT name FROM customers WHERE id = ?", (entry["customer_id"],))
        c_row = cursor.fetchone()
        cust_name = c_row["name"] if c_row else "Customer"

        paid_amt = round(float(data.amount), 2) if (data.amount is not None and data.amount > 0) else orig_amount
        settle_payload = json.dumps({
            "entry_id": entry_id,
            "customer_id": entry["customer_id"],
            "amount": paid_amt,
            "payment_method": pay_method,
            "notes": notes_val,
            "settled_at": settle_date
        })
        details_txt = f"Payment for Invoice #{entry['invoice_no']} • Amount: Rs. {paid_amt:,.2f} via {pay_method}"
        if notes_val:
            details_txt += f" • Notes: {notes_val}"

        cursor.execute("""
            INSERT INTO staff_approval_requests (request_type, customer_id, customer_name, reference_id, amount, payment_method, details, notes, payload_json, status, added_by)
            VALUES ('SETTLEMENT', ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
        """, (entry["customer_id"], cust_name, entry_id, paid_amt, pay_method, details_txt, notes_val, settle_payload, added_by_val))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "pending_approval": True,
            "entry_id": entry_id,
            "amount": paid_amt,
            "payment_method": pay_method,
            "message": f"Settlement payment of Rs. {paid_amt:,.2f} for {entry['invoice_no']} sent to Admin for approval."
        }

    # Admin settlement: direct execution
    is_partial = False
    if data.amount is not None and 0 < data.amount < orig_amount:
        is_partial = True
        paid_amt = round(float(data.amount), 2)
        rem_amt = round(orig_amount - paid_amt, 2)

        audit_note = f"Partial payment Rs. {paid_amt:,.2f} received on {settle_date} via {pay_method}"
        if notes_val:
            audit_note += f" ({notes_val})"

        cursor.execute("""
            UPDATE customer_khata
            SET amount = ?,
                is_settled = 1,
                settled_at = ?,
                payment_method = ?,
                notes = CASE WHEN notes != '' THEN notes || ' | ' || ? ELSE ? END
            WHERE id = ?
        """, (paid_amt, settle_date, pay_method, audit_note, audit_note, entry_id))

        cursor.execute("""
            INSERT INTO customer_khata (customer_id, invoice_no, date, item_description, amount, is_settled, notes)
            VALUES (?, ?, ?, ?, ?, 0, ?)
        """, (entry["customer_id"], f"{entry['invoice_no']}-REM", entry["date"], f"{entry['item_description']} (Baqaya)", rem_amt, f"Remaining baqaya from {entry['invoice_no']} after partial payment of Rs. {paid_amt:,.2f}"))
        conn.commit()

        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM customer_khata WHERE customer_id = ? AND is_settled = 0", (entry["customer_id"],))
        updated_balance = float(cursor.fetchone()[0] or 0.0)
        conn.close()

        return {
            "success": True,
            "partial": True,
            "entry_id": entry_id,
            "paid_amount": paid_amt,
            "remaining_amount": rem_amt,
            "settled_at": settle_date,
            "payment_method": pay_method,
            "updated_balance": updated_balance,
            "message": f"Partial payment of Rs. {paid_amt:,.2f} recorded for {entry['invoice_no']}. Baqaya remaining: Rs. {rem_amt:,.2f}."
        }
    else:
        audit_note = f"Full payment on {settle_date} via {pay_method}"
        if notes_val:
            audit_note += f" ({notes_val})"

        cursor.execute("""
            UPDATE customer_khata
            SET is_settled = 1,
                settled_at = ?,
                payment_method = ?,
                notes = CASE WHEN notes != '' THEN notes || ' | ' || ? ELSE ? END
            WHERE id = ?
        """, (settle_date, pay_method, audit_note, audit_note, entry_id))
        conn.commit()

        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM customer_khata WHERE customer_id = ? AND is_settled = 0", (entry["customer_id"],))
        updated_balance = float(cursor.fetchone()[0] or 0.0)

        cursor.execute("SELECT name FROM customers WHERE id = ?", (entry["customer_id"],))
        c_row = cursor.fetchone()
        cust_name = c_row["name"] if c_row else "Customer"
        conn.close()

        log_activity(
            category="CUSTOMER_KHATA",
            action_type="CUSTOMER_KHATA_SETTLED",
            title=f"Customer Khata Settled: {cust_name}",
            description=f"Invoice #{entry['invoice_no']} of Rs. {orig_amount:,.2f} settled in full via {pay_method}",
            staff_name=cust_name,
            amount=orig_amount,
            date_str=settle_date
        )

        return {
            "success": True,
            "partial": False,
            "entry_id": entry_id,
            "settled_at": settle_date,
            "payment_method": pay_method,
            "amount": orig_amount,
            "updated_balance": updated_balance,
            "message": f"Invoice {entry['invoice_no']} (Rs. {orig_amount:,.2f}) settled in full via {pay_method}."
        }


@app.post("/api/customers/{customer_id}/settle-all")
def settle_all_customer_balance(customer_id: int, data: CustomerSettleAll):
    """Settles all or partial customer balance across pending invoices (FIFO) or queues for admin approval if staff."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    customer = cursor.fetchone()
    if not customer:
        conn.close()
        raise HTTPException(status_code=404, detail="Customer not found")

    cursor.execute("SELECT * FROM customer_khata WHERE customer_id = ? AND is_settled = 0 ORDER BY date ASC, id ASC", (customer_id,))
    pending_items = [dict(r) for r in cursor.fetchall()]
    if not pending_items:
        conn.close()
        return {"success": True, "message": "Koi pending balance mojood nahi.", "settled_count": 0, "settled_amount": 0}

    settle_date = data.settled_at or date.today().isoformat()
    pay_method = data.payment_method or "Cash"
    total_due = sum(item["amount"] for item in pending_items)
    notes_val = (data.notes or "").strip()

    # Determine pay amount (partial or full)
    pay_amount = round(float(data.amount), 2) if (data.amount is not None and float(data.amount) > 0) else total_due
    if pay_amount > total_due:
        pay_amount = total_due

    # If submitted by Staff, queue into staff_approval_requests
    is_staff = bool(data.is_staff or ("Staff" in (data.added_by or "")))
    if is_staff:
        settle_payload = json.dumps({
            "customer_id": customer_id,
            "amount": pay_amount,
            "payment_method": pay_method,
            "notes": notes_val,
            "settled_at": settle_date
        })
        details_txt = f"Settle Balance for {customer['name']} • Amount: Rs. {pay_amount:,.2f} via {pay_method}"
        if notes_val:
            details_txt += f" • Notes: {notes_val}"

        cursor.execute("""
            INSERT INTO staff_approval_requests (request_type, customer_id, customer_name, reference_id, amount, payment_method, details, notes, payload_json, status, added_by)
            VALUES ('SETTLE_ALL', ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 'Staff (Counter)')
        """, (customer_id, customer["name"], customer_id, pay_amount, pay_method, details_txt, notes_val, settle_payload))
        conn.commit()
        conn.close()

        return {
            "success": True,
            "pending_approval": True,
            "customer_id": customer_id,
            "settled_amount": pay_amount,
            "message": f"Settlement request of Rs. {pay_amount:,.2f} for {customer['name']} sent to Admin for approval."
        }

    is_partial = (pay_amount < total_due)
    remaining_to_pay = pay_amount
    settled_count = 0

    for item in pending_items:
        if remaining_to_pay <= 0:
            break

        item_amt = float(item["amount"])
        item_id = item["id"]

        if remaining_to_pay >= item_amt:
            # Full settle of this single invoice
            audit_note = f"Paid on {settle_date} via {pay_method}" + (f" ({notes_val})" if notes_val else "")
            cursor.execute("""
                UPDATE customer_khata
                SET is_settled = 1,
                    settled_at = ?,
                    payment_method = ?,
                    notes = CASE WHEN notes != '' THEN notes || ' | ' || ? ELSE ? END
                WHERE id = ?
            """, (settle_date, pay_method, audit_note, audit_note, item_id))
            remaining_to_pay = round(remaining_to_pay - item_amt, 2)
            settled_count += 1
        else:
            # Partial settle of this invoice: split item
            paid_portion = remaining_to_pay
            rem_portion = round(item_amt - paid_portion, 2)

            audit_note = f"Partial payment Rs. {paid_portion:,.2f} on {settle_date} via {pay_method}" + (f" ({notes_val})" if notes_val else "")
            cursor.execute("""
                UPDATE customer_khata
                SET amount = ?,
                    is_settled = 1,
                    settled_at = ?,
                    payment_method = ?,
                    notes = CASE WHEN notes != '' THEN notes || ' | ' || ? ELSE ? END
                WHERE id = ?
            """, (paid_portion, settle_date, pay_method, audit_note, audit_note, item_id))

            # Insert remaining balance item
            cursor.execute("""
                INSERT INTO customer_khata (customer_id, invoice_no, date, item_description, amount, is_settled, notes)
                VALUES (?, ?, ?, ?, ?, 0, ?)
            """, (customer_id, f"{item['invoice_no']}-REM", item['date'], f"{item['item_description']} (Baqaya)", rem_portion, f"Remaining baqaya from {item['invoice_no']} after partial payment of Rs. {paid_portion:,.2f}"))

            remaining_to_pay = 0
            settled_count += 1
            break

    conn.commit()

    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM customer_khata WHERE customer_id = ? AND is_settled = 0", (customer_id,))
    updated_balance = float(cursor.fetchone()[0] or 0.0)
    conn.close()

    if is_partial:
        return {
            "success": True,
            "partial": True,
            "customer_id": customer_id,
            "customer_name": customer["name"],
            "settled_count": settled_count,
            "settled_amount": pay_amount,
            "remaining_balance": updated_balance,
            "settled_at": settle_date,
            "payment_method": pay_method,
            "message": f"Juzwi Adaigi (Partial payment) of Rs. {pay_amount:,.2f} for {customer['name']} received via {pay_method}. Baqaya balance: Rs. {updated_balance:,.2f}."
        }
    else:
        return {
            "success": True,
            "partial": False,
            "customer_id": customer_id,
            "customer_name": customer["name"],
            "settled_count": settled_count,
            "settled_amount": pay_amount,
            "remaining_balance": updated_balance,
            "settled_at": settle_date,
            "payment_method": pay_method,
            "message": f"Full balance of Rs. {pay_amount:,.2f} ({settled_count} invoices) for {customer['name']} settled via {pay_method}."
        }

@app.post("/api/customer-khata/clear-settled")
def clear_settled_customer_khata():
    """Permanently deletes all settled customer khata records/invoices (admin purge)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM customer_khata WHERE is_settled = 1")
    count = cursor.fetchone()[0] or 0
    if count == 0:
        conn.close()
        return {"success": True, "deleted_count": 0, "message": "Koi settled customer khata record mojood nahi hai."}
    
    cursor.execute("DELETE FROM customer_khata WHERE is_settled = 1")
    conn.commit()
    conn.close()
    return {"success": True, "deleted_count": count, "message": f"{count} settled customer khata records kamyabi se delete ho gaye."}

@app.get("/api/customer-khata/kpis")
def get_customer_khata_kpis():
    """Returns top 4 KPI metrics for Customer Khata dashboard."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Total Outstanding Udhar
    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM customer_khata WHERE is_settled = 0")
    total_outstanding = float(cursor.fetchone()[0])

    # 2. This Week's Credit Given (past 7 days)
    seven_days_ago = (date.today() - timedelta(days=7)).isoformat()
    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM customer_khata WHERE date >= ?", (seven_days_ago,))
    this_week_credit = float(cursor.fetchone()[0])

    # 3. This Week's Recovered (past 7 days)
    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM customer_khata WHERE is_settled = 1 AND settled_at >= ?", (seven_days_ago,))
    this_week_recovered = float(cursor.fetchone()[0])

    # 4. Active Debtors Count
    cursor.execute("SELECT COUNT(DISTINCT customer_id) FROM customer_khata WHERE is_settled = 0")
    active_debtors_count = int(cursor.fetchone()[0])

    # 5. Total Registered Customers
    cursor.execute("SELECT COUNT(*) FROM customers WHERE is_active = 1")
    total_customers_count = int(cursor.fetchone()[0])

    conn.close()

    return {
        "total_outstanding": total_outstanding,
        "this_week_credit": this_week_credit,
        "this_week_recovered": this_week_recovered,
        "active_debtors_count": active_debtors_count,
        "total_customers_count": total_customers_count,
        "since_date": seven_days_ago
    }

@app.get("/api/customer-khata/weekly-report")
def get_customer_khata_weekly_report():
    """Returns weekly audit report of credit given, recoveries, and list of debtors."""
    conn = get_db_connection()
    cursor = conn.cursor()
    today_str = date.today().isoformat()
    seven_days_ago = (date.today() - timedelta(days=7)).isoformat()

    cursor.execute("""
        SELECT k.*, c.name as customer_name, c.phone as customer_phone
        FROM customer_khata k
        JOIN customers c ON k.customer_id = c.id
        WHERE k.date >= ? OR (k.is_settled = 1 AND k.settled_at >= ?)
        ORDER BY k.date DESC, k.id DESC
    """, (seven_days_ago, seven_days_ago))
    recent_transactions = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT 
            c.id, c.name, c.phone, c.address, c.credit_limit,
            COALESCE(SUM(CASE WHEN k.is_settled = 0 THEN k.amount ELSE 0 END), 0) as current_balance,
            COALESCE(SUM(CASE WHEN k.is_settled = 0 THEN 1 ELSE 0 END), 0) as pending_count
        FROM customers c
        LEFT JOIN customer_khata k ON c.id = k.customer_id
        GROUP BY c.id
        HAVING current_balance > 0
        ORDER BY current_balance DESC
    """)
    debtors = [dict(r) for r in cursor.fetchall()]
    conn.close()

    total_given = sum(t["amount"] for t in recent_transactions if t["date"] >= seven_days_ago)
    total_recovered = sum(t["amount"] for t in recent_transactions if t["is_settled"] == 1 and t.get("settled_at", "") >= seven_days_ago)
    total_outstanding = sum(d["current_balance"] for d in debtors)

    return {
        "period": f"{seven_days_ago} to {today_str}",
        "summary": {
            "total_given_week": total_given,
            "total_recovered_week": total_recovered,
            "total_given_period": total_given,
            "total_recovered_period": total_recovered,
            "total_outstanding": total_outstanding,
            "debtor_count": len(debtors)
        },
        "debtors": debtors,
        "recent_transactions": recent_transactions
    }

@app.get("/api/customer-khata/monthly-report")
def get_customer_khata_monthly_report():
    """Returns monthly audit report of credit given, recoveries, and list of debtors for current calendar month."""
    conn = get_db_connection()
    cursor = conn.cursor()
    today = date.today()
    today_str = today.isoformat()
    first_of_month = today.replace(day=1).isoformat()

    cursor.execute("""
        SELECT k.*, c.name as customer_name, c.phone as customer_phone
        FROM customer_khata k
        JOIN customers c ON k.customer_id = c.id
        WHERE k.date >= ? OR (k.is_settled = 1 AND k.settled_at >= ?)
        ORDER BY k.date DESC, k.id DESC
    """, (first_of_month, first_of_month))
    recent_transactions = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT 
            c.id, c.name, c.phone, c.address, c.credit_limit,
            COALESCE(SUM(CASE WHEN k.is_settled = 0 THEN k.amount ELSE 0 END), 0) as current_balance,
            COALESCE(SUM(CASE WHEN k.is_settled = 0 THEN 1 ELSE 0 END), 0) as pending_count
        FROM customers c
        LEFT JOIN customer_khata k ON c.id = k.customer_id
        GROUP BY c.id
        HAVING current_balance > 0
        ORDER BY current_balance DESC
    """)
    debtors = [dict(r) for r in cursor.fetchall()]
    conn.close()

    total_given = sum(t["amount"] for t in recent_transactions if t["date"] >= first_of_month)
    total_recovered = sum(t["amount"] for t in recent_transactions if t["is_settled"] == 1 and t.get("settled_at", "") >= first_of_month)
    total_outstanding = sum(d["current_balance"] for d in debtors)

    return {
        "period": f"{first_of_month} to {today_str} (Current Month)",
        "summary": {
            "total_given_week": total_given,
            "total_recovered_week": total_recovered,
            "total_given_period": total_given,
            "total_recovered_period": total_recovered,
            "total_outstanding": total_outstanding,
            "debtor_count": len(debtors)
        },
        "debtors": debtors,
        "recent_transactions": recent_transactions
    }

# =========================================================================
# HOME DELIVERY SYSTEM ENDPOINTS
# =========================================================================

class DeliveryCheckRiderRequest(BaseModel):
    phone: str
    name: Optional[str] = ""

class DeliveryDispatchRequest(BaseModel):
    rider_type: Optional[str] = "EXISTING"  # "EXISTING" or "NEW"
    staff_id: Optional[int] = None
    rider_name: Optional[str] = None
    rider_phone: Optional[str] = None
    rider_pin: str
    customer_name: str
    customer_phone: str
    customer_address: Optional[str] = None
    delivery_address: Optional[str] = None
    invoice_no: Optional[str] = None
    bill_amount: float
    delivery_charges: Optional[float] = 0.0
    payment_method: Optional[str] = "Cash on Delivery"
    notes: Optional[str] = ""
    is_new_rider: Optional[bool] = False
    auto_confirm: Optional[bool] = False

class DeliveryReturnRequest(BaseModel):
    rider_pin: str
    auto_confirm: Optional[bool] = False

class DeliveryWATemplatesRequest(BaseModel):
    admin_dispatch: Optional[str] = None
    customer_dispatch: Optional[str] = None
    admin_return: Optional[str] = None

class DeliveryReconcileRequest(BaseModel):
    action: str  # "APPROVE" or "REJECT" or "REOPEN"
    rejection_reason: Optional[str] = ""
    approved_by: Optional[str] = "Admin"

class StaffConvertRiderRequest(BaseModel):
    designation: Optional[str] = "Delivery Incharge"
    monthly_salary: Optional[float] = 0.0
    shift_id: Optional[int] = 1
    daily_hours: Optional[float] = 8.0
    allowed_leaves: Optional[int] = 2
    cnic: Optional[str] = ""
    address: Optional[str] = ""

@app.post("/api/deliveries/check-rider")
def check_or_preview_rider(data: DeliveryCheckRiderRequest):
    """
    Checks if a phone belongs to existing staff.
    If not, previews PIN (last 4 digits) and flags as temporary rider candidate.
    """
    clean_p = (data.phone or "").strip()
    digits = re.sub(r"\D", "", clean_p)
    pin = digits[-4:] if len(digits) >= 4 else "0000"

    res = register_or_get_delivery_staff(name=data.name or "Rider", phone=clean_p)
    return {
        "staff_id": res["staff_id"],
        "name": res["name"],
        "phone": res["phone"],
        "pin": pin,
        "is_new": res.get("is_new", False),
        "is_temp": res.get("is_temp", False)
    }

@app.get("/api/deliveries/templates")
def get_wa_templates_endpoint():
    """Returns custom or default WhatsApp message templates."""
    return get_delivery_wa_templates()

@app.post("/api/deliveries/templates")
def save_wa_templates_endpoint(data: DeliveryWATemplatesRequest):
    """Saves custom WhatsApp message templates (Admin only)."""
    updated = save_delivery_wa_templates(data.dict(exclude_none=True))
    return {"success": True, "templates": updated, "message": "WhatsApp templates updated successfully."}

@app.post("/api/deliveries/dispatch")
def dispatch_delivery(data: DeliveryDispatchRequest):
    """
    Real-time dispatch:
    - Auto-registers rider if new (or missing staff_id)
    - Verifies 4-digit rider PIN
    - Prepares WhatsApp alert links for Admin & Customer
    - Marks status PENDING_DISPATCH (or OUT_FOR_DELIVERY if auto_confirm is True)
    """
    staff_id = data.staff_id
    rider_name = (data.rider_name or "").strip()
    rider_phone = (data.rider_phone or "").strip()

    if data.is_new_rider or data.rider_type == "NEW" or not staff_id:
        reg = register_or_get_delivery_staff(rider_name, rider_phone)
        staff_id = reg["staff_id"]
        rider_name = reg["name"]
        rider_phone = reg["phone"]
    elif staff_id and not rider_name:
        st = get_staff_by_id(staff_id)
        if st:
            rider_name = st["name"]
            rider_phone = st["phone"]

    # Verify PIN
    ok, pin_msg = verify_rider_pin(staff_id=staff_id, pin=data.rider_pin)
    if not ok:
        raise HTTPException(status_code=400, detail=pin_msg)

    # Clean invoice
    clean_invoice = (data.invoice_no or "").strip()
    if not clean_invoice:
        clean_invoice = f"INV-{random.randint(10000, 99999)}"

    # Determine address
    clean_address = (data.customer_address or data.delivery_address or "").strip()
    initial_st = "OUT_FOR_DELIVERY" if data.auto_confirm else "PENDING_DISPATCH"

    # Create delivery
    delivery = create_delivery(
        staff_id=staff_id,
        delivery_person_name=rider_name,
        delivery_person_phone=rider_phone,
        customer_name=data.customer_name.strip(),
        customer_phone=data.customer_phone.strip(),
        customer_address=clean_address,
        invoice_no=clean_invoice,
        bill_amount=float(data.bill_amount or 0.0),
        payment_method=data.payment_method or "Cash on Delivery",
        notes=data.notes or "",
        dispatch_pin_verified=1,
        admin_wa_sent=0 if not data.auto_confirm else 1,
        customer_wa_sent=0 if not data.auto_confirm else 1,
        initial_status=initial_st
    )

    admin_phone = get_setting("admin_whatsapp_number") or "03001234567"
    wa_alerts = whatsapp_service.dispatch_delivery_alerts(delivery, admin_phone=admin_phone)

    return {
        "success": True,
        "delivery": delivery,
        "whatsapp": wa_alerts,
        "admin_wa_link": wa_alerts.get("admin_link", ""),
        "customer_wa_link": wa_alerts.get("customer_link", ""),
        "message": f"Delivery for invoice #{clean_invoice} prepared. Send WhatsApp alerts to confirm Out for Delivery."
    }

@app.post("/api/deliveries/{delivery_id}/confirm-dispatch")
def confirm_dispatch_endpoint(delivery_id: int):
    """Confirms WhatsApp alerts sent and marks status as OUT_FOR_DELIVERY."""
    try:
        updated = confirm_delivery_dispatch(delivery_id)
        return {
            "success": True,
            "delivery": updated,
            "message": f"Delivery #{updated['invoice_no']} status updated to OUT_FOR_DELIVERY."
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/deliveries/active")
def list_active_deliveries():
    """Returns deliveries currently OUT_FOR_DELIVERY or PENDING_RETURN for Staff Portal return selection."""
    active = get_deliveries_list(status="OUT_FOR_DELIVERY", limit=100)
    pending_ret = get_deliveries_list(status="PENDING_RETURN", limit=100)
    # Combine lists
    existing_ids = {d["id"] for d in active}
    for d in pending_ret:
        if d["id"] not in existing_ids:
            active.append(d)
    return active

@app.post("/api/deliveries/{delivery_id}/return")
def return_delivery(delivery_id: int, data: DeliveryReturnRequest):
    """
    Rider Return confirmation step 1:
    - Verifies 4-digit PIN against rider
    - Prepares return WhatsApp alert for Admin
    - Marks status PENDING_RETURN (or DELIVERED if auto_confirm is True)
    """
    try:
        updated = complete_delivery_return(delivery_id=delivery_id, rider_pin=data.rider_pin, return_wa_sent=1)
        if data.auto_confirm:
            updated = confirm_delivery_return(delivery_id=delivery_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    admin_phone = get_setting("admin_whatsapp_number") or "03001234567"
    wa_return = whatsapp_service.dispatch_delivery_return_alert(updated, admin_phone=admin_phone)

    return {
        "success": True,
        "delivery": updated,
        "whatsapp": wa_return,
        "admin_wa_link": wa_return.get("admin_link", ""),
        "message": f"Rider PIN verified for invoice #{updated['invoice_no']}. Send WhatsApp alert to Admin to mark as Delivered."
    }

@app.post("/api/deliveries/{delivery_id}/confirm-return")
def confirm_return_endpoint(delivery_id: int, data: Optional[DeliveryReturnConfirm] = None):
    """Confirms return alert sent, saves partial payment / return reasons, and updates status."""
    deliv = get_delivery_by_id(delivery_id)
    if not deliv:
        raise HTTPException(status_code=404, detail="Delivery record not found")

    res_type = (data.delivery_result if data else "DELIVERED") or "DELIVERED"
    res_type = res_type.upper().strip()
    is_delivered = (res_type == "DELIVERED")

    bill = float(deliv.get("bill_amount") or 0.0)
    chg = float(deliv.get("delivery_charges") or 0.0)
    net_total = bill + chg

    if data and data.paid_amount is not None and data.paid_amount > 0:
        paid_amt = float(data.paid_amount)
    else:
        paid_amt = net_total if is_delivered else 0.0

    if is_delivered:
        bal_amt = max(0.0, net_total - paid_amt)
        pay_status = "PARTIAL" if (bal_amt > 0.5) else "FULL"
        final_status = "DELIVERED"
    else:
        paid_amt = 0.0
        bal_amt = 0.0
        pay_status = "UNPAID"
        final_status = "RETURNED"

    pay_method = (data.payment_method if data else "Cash on Delivery") or "Cash on Delivery"
    ret_reason = (data.return_reason if data else "") or ""
    ret_notes = (data.return_notes if data else "") or ""

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE deliveries
        SET status = ?,
            delivery_result = ?,
            payment_status = ?,
            paid_amount = ?,
            balance_amount = ?,
            payment_method = ?,
            return_reason = ?,
            return_notes = ?,
            delivered_at = CASE WHEN delivered_at IS NULL OR delivered_at = '' THEN ? ELSE delivered_at END,
            return_pin_verified = 1,
            return_wa_sent = 1
        WHERE id = ?
    """, (
        final_status, res_type, pay_status, paid_amt, bal_amt, pay_method,
        ret_reason, ret_notes, now_str, delivery_id
    ))
    conn.commit()
    conn.close()

    updated = get_delivery_by_id(delivery_id)

    log_activity(
        category="DELIVERY",
        action_type="DELIVERED" if is_delivered else "RETURNED",
        title=f"Delivery {final_status}: #{updated['invoice_no']}",
        description=f"Rider {updated['delivery_person_name']} • Customer: {updated['customer_name']} • Paid: Rs. {paid_amt:,.0f} | Bal: Rs. {bal_amt:,.0f}" + (f" • Reason: {ret_reason}" if ret_reason else ""),
        staff_name=updated["delivery_person_name"],
        amount=paid_amt
    )

    admin_phone = get_setting("admin_whatsapp_number") or "03001234567"
    wa_return = whatsapp_service.dispatch_delivery_return_alert(updated, admin_phone=admin_phone)

    return {
        "success": True,
        "delivery": updated,
        "whatsapp": wa_return,
        "admin_wa_link": wa_return.get("admin_link", ""),
        "message": f"Delivery #{updated['invoice_no']} updated to {final_status}."
    }

@app.post("/api/deliveries/{delivery_id}/transfer-to-khata")
def transfer_delivery_balance_to_khata(delivery_id: int):
    """1-Click transfers remaining delivery unpaid balance to Customer Khata ledger."""
    deliv = get_delivery_by_id(delivery_id)
    if not deliv:
        raise HTTPException(status_code=404, detail="Delivery record not found")
    
    bal = float(deliv.get("balance_amount") or 0.0)
    if bal <= 0:
        raise HTTPException(status_code=400, detail="Yeh delivery pehle se fully paid hai ya balance 0 hai.")

    if deliv.get("khata_transferred") == 1:
        return {"success": True, "message": "Balance pehle se Customer Khata mein transfer ho chuka hai.", "already_transferred": True}

    cust_name = deliv["customer_name"].strip()
    cust_phone = re.sub(r"[^\d+]", "", deliv.get("customer_phone") or "")

    conn = get_db_connection()
    cursor = conn.cursor()

    if cust_phone:
        cursor.execute("SELECT id FROM customers WHERE phone = ? OR name = ?", (cust_phone, cust_name))
    else:
        cursor.execute("SELECT id FROM customers WHERE name = ?", (cust_name,))
    cust_row = cursor.fetchone()

    if cust_row:
        cust_id = cust_row["id"]
    else:
        cursor.execute("""
            INSERT INTO customers (name, phone, address, credit_limit, is_active)
            VALUES (?, ?, ?, 10000.0, 1)
        """, (cust_name, cust_phone, deliv.get("customer_address") or ""))
        cust_id = cursor.lastrowid

    now_date = date.today().isoformat()
    inv_no = deliv["invoice_no"]
    desc = f"Home Delivery Balance (Invoice #{inv_no})"

    cursor.execute("""
        INSERT INTO customer_khata (customer_id, invoice_no, date, item_description, amount, is_settled, notes, added_by, approval_status, approved_by, approved_at)
        VALUES (?, ?, ?, ?, ?, 0, 'Auto-transferred from Home Delivery', 'Delivery System', 'APPROVED', 'System', ?)
    """, (cust_id, f"DEL-BAL-{inv_no}", now_date, desc, bal, datetime.now().isoformat()))
    
    khata_id = cursor.lastrowid

    cursor.execute("""
        UPDATE deliveries
        SET khata_transferred = 1
        WHERE id = ?
    """, (delivery_id,))
    conn.commit()
    conn.close()

    log_activity(
        category="CUSTOMER_KHATA",
        action_type="DELIVERY_BALANCE_TRANSFERRED",
        title=f"Delivery Balance Transferred: {cust_name}",
        description=f"Invoice #{inv_no} balance of Rs. {bal:,.2f} transferred to Khata Ledger",
        staff_name=cust_name,
        amount=bal
    )

    return {
        "success": True,
        "khata_entry_id": khata_id,
        "balance_amount": bal,
        "message": f"Rs. {bal:,.2f} successfully transferred to {cust_name}'s Customer Khata ledger!"
    }

@app.get("/api/deliveries/staff/completed-today")
def get_staff_completed_deliveries_today():
    """Returns read-only list of today's completed/returned deliveries for Staff Portal."""
    today_str = date.today().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.*, 
               COALESCE(s.name, d.delivery_person_name) as rider_name,
               s.phone as rider_phone
        FROM deliveries d
        LEFT JOIN staff s ON d.staff_id = s.id
        WHERE ((date(d.created_at) = ? OR date(d.delivered_at) = ?) OR d.created_at LIKE ? OR d.delivered_at LIKE ?)
          AND (d.status IN ('DELIVERED', 'RETURNED', 'REJECTED') OR d.delivery_result IN ('DELIVERED', 'RETURNED'))
        ORDER BY d.id DESC
    """, (today_str, today_str, f"{today_str}%", f"{today_str}%"))
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        bill = float(d.get("bill_amount") or 0.0)
        chg = float(d.get("delivery_charges") or 0.0)
        d["net_total"] = bill + chg
        result.append(d)
    return result

@app.get("/api/deliveries/reports/all-time")
def export_all_deliveries_excel():
    """Generates and downloads All-Time Home Deliveries Excel Report (.xlsx)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.*, COALESCE(s.name, d.delivery_person_name) as rider_name
        FROM deliveries d
        LEFT JOIN staff s ON d.staff_id = s.id
        ORDER BY d.created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "All Deliveries"

    headers = [
        "Invoice #", "Customer Name", "Customer Phone", "Delivery Address", "Rider Name",
        "Medicine Bill (Rs.)", "Delivery Charges (Rs.)", "Net Total (Rs.)", "Paid Amount (Rs.)",
        "Balance Amount (Rs.)", "Payment Method", "Payment Status", "Delivery Result / Status",
        "Return Reason", "Approval Status", "Dispatched At", "Completed At"
    ]
    ws.append(headers)

    for r in rows:
        d = dict(r)
        bill = float(d.get("bill_amount") or 0.0)
        chg = float(d.get("delivery_charges") or 0.0)
        net = bill + chg
        paid = float(d.get("paid_amount") or (net if d.get("status") == "DELIVERED" else 0.0))
        bal = float(d.get("balance_amount") or 0.0)
        res_st = d.get("delivery_result") or d.get("status") or "-"

        ws.append([
            d.get("invoice_no") or "-", d.get("customer_name") or "-", d.get("customer_phone") or "-",
            d.get("customer_address") or "-", d.get("rider_name") or "-", bill, chg, net,
            paid, bal, d.get("payment_method") or "-", d.get("payment_status") or "-",
            res_st, d.get("return_reason") or "-", d.get("approval_status") or "-",
            d.get("dispatched_at") or "-", d.get("delivered_at") or "-"
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"All_Deliveries_Report_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# =========================================================================
# ALL-TIME KHATA & CUSTOMER IMPORT ENDPOINTS
# =========================================================================

@app.get("/api/customer-khata/reports/general-all-time")
def export_general_khata_all_time():
    """Generates and downloads All-Time General Khata Excel Report (.xlsx)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.name, c.phone, c.address, c.credit_limit,
               COALESCE(SUM(CASE WHEN k.is_settled = 0 THEN k.amount ELSE 0 END), 0) as pending_balance,
               COALESCE(SUM(CASE WHEN k.is_settled = 1 THEN k.amount ELSE 0 END), 0) as total_settled,
               COALESCE(SUM(k.amount), 0) as total_credit_bills,
               MAX(k.date) as last_transaction_date
        FROM customers c
        LEFT JOIN customer_khata k ON c.id = k.customer_id
        WHERE c.is_active = 1
        GROUP BY c.id
        ORDER BY pending_balance DESC, c.name ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "General Khata All-Time"

    headers = ["Customer ID", "Customer Name", "Phone Number", "Address", "Credit Limit (Rs.)", "Pending Balance (Rs.)", "Total Settled (Rs.)", "Total Credit Bills (Rs.)", "Last Activity Date"]
    ws.append(headers)

    for r in rows:
        ws.append([
            r["id"], r["name"], r["phone"] or "-", r["address"] or "-",
            float(r["credit_limit"] or 0), float(r["pending_balance"] or 0),
            float(r["total_settled"] or 0), float(r["total_credit_bills"] or 0),
            r["last_transaction_date"] or "-"
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"General_Khata_All_Time_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/customer-khata/reports/overdue-pending")
def export_overdue_pending_khata_all_time():
    """Generates and downloads All-Time Overdue / Pending Khata Excel Report (.xlsx)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.name, c.phone, c.address, c.credit_limit,
               SUM(k.amount) as pending_balance,
               COUNT(k.id) as pending_invoices_count,
               MIN(k.date) as oldest_unpaid_date,
               MAX(k.date) as latest_unpaid_date
        FROM customers c
        JOIN customer_khata k ON c.id = k.customer_id
        WHERE c.is_active = 1 AND k.is_settled = 0
        GROUP BY c.id
        HAVING pending_balance > 0
        ORDER BY pending_balance DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pending Overdue Khata"

    headers = ["Customer ID", "Customer Name", "Phone Number", "Address", "Pending Balance (Rs.)", "Credit Limit (Rs.)", "Pending Invoices Count", "Oldest Unpaid Date", "Latest Unpaid Date"]
    ws.append(headers)

    for r in rows:
        ws.append([
            r["id"], r["name"], r["phone"] or "-", r["address"] or "-",
            float(r["pending_balance"] or 0), float(r["credit_limit"] or 0),
            r["pending_invoices_count"], r["oldest_unpaid_date"] or "-", r["latest_unpaid_date"] or "-"
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"Overdue_Pending_Khata_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/customers/sample-template")
def download_customer_sample_template():
    """Returns downloadable Excel sample template for importing customers."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Customers Import Template"

    headers = ["Customer Name", "Phone Number", "Address", "Credit Limit"]
    ws.append(headers)
    ws.append(["Tariq Customer", "03211234567", "Gulberg III, Lahore", 25000])
    ws.append(["Ali Ahmad", "03009876543", "DHA Phase 5, Lahore", 50000])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Customers_Import_Sample_Template.xlsx"}
    )

@app.post("/api/customers/import-excel")
async def import_customers_excel(file: UploadFile = File(...)):
    """Extracts and imports customer names & phone numbers from Excel (.xlsx/.csv)."""
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="Invalid file format! Please upload an Excel (.xlsx) or CSV file.")

    contents = await file.read()
    imported_count = 0
    skipped_count = 0

    try:
        wb = openpyxl.load_workbook(filename=io.BytesIO(contents), data_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if not rows or len(rows) < 2:
            raise HTTPException(status_code=400, detail="Excel file is empty or has no data rows.")

        header = [str(cell or "").strip().lower() for cell in rows[0]]
        
        name_idx = -1
        phone_idx = -1
        address_idx = -1
        limit_idx = -1

        for idx, col in enumerate(header):
            if "name" in col or "customer" in col:
                name_idx = idx
            elif "phone" in col or "mobile" in col or "contact" in col or "number" in col:
                phone_idx = idx
            elif "address" in col or "pata" in col or "location" in col:
                address_idx = idx
            elif "limit" in col or "credit" in col:
                limit_idx = idx

        if name_idx == -1:
            name_idx = 0
        if phone_idx == -1 and len(header) > 1:
            phone_idx = 1

        conn = get_db_connection()
        cursor = conn.cursor()

        for row in rows[1:]:
            if not row or not any(row):
                continue
            cust_name = str(row[name_idx] or "").strip() if name_idx < len(row) else ""
            cust_phone = str(row[phone_idx] or "").strip() if (phone_idx >= 0 and phone_idx < len(row)) else ""
            cust_address = str(row[address_idx] or "").strip() if (address_idx >= 0 and address_idx < len(row)) else ""
            
            raw_limit = row[limit_idx] if (limit_idx >= 0 and limit_idx < len(row)) else 10000.0
            try:
                credit_limit = float(raw_limit or 10000.0)
            except ValueError:
                credit_limit = 10000.0

            if not cust_name:
                continue

            clean_phone = re.sub(r"[^\d+]", "", cust_phone)

            if clean_phone:
                cursor.execute("SELECT id FROM customers WHERE phone = ? OR name = ?", (clean_phone, cust_name))
            else:
                cursor.execute("SELECT id FROM customers WHERE name = ?", (cust_name,))

            existing = cursor.fetchone()
            if existing:
                skipped_count += 1
                continue

            cursor.execute("""
                INSERT INTO customers (name, phone, address, credit_limit, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (cust_name, clean_phone, cust_address, credit_limit))
            imported_count += 1

        conn.commit()
        conn.close()

        log_activity(
            category="CUSTOMERS",
            action_type="CUSTOMERS_IMPORTED",
            title=f"Customers Excel Import: {imported_count} Added",
            description=f"Imported: {imported_count} new customers • Skipped (Duplicates): {skipped_count}",
            staff_name="Admin"
        )

        return {
            "success": True,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "message": f"Successfully imported {imported_count} customers! ({skipped_count} duplicates skipped)."
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse Excel file: {str(e)}")

@app.get("/api/deliveries")
def list_deliveries(
    status: Optional[str] = None,
    approval_status: Optional[str] = None,
    date: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 200
):
    """Admin endpoint: lists deliveries with filters."""
    return get_deliveries_list(
        status=status,
        approval_status=approval_status,
        date_str=date,
        search=search,
        limit=limit
    )

@app.get("/api/deliveries/stats")
def delivery_stats_today(date: Optional[str] = None):
    """Returns today's aggregated delivery metrics."""
    return get_delivery_stats_today(date_str=date)

@app.get("/api/deliveries/{delivery_id}")
def get_delivery_details(delivery_id: int):
    """Returns detailed information for a single delivery."""
    deliv = get_delivery_by_id(delivery_id)
    if not deliv:
        raise HTTPException(status_code=404, detail="Delivery record not found")
    return deliv

@app.post("/api/deliveries/{delivery_id}/reconcile")
def admin_reconcile_delivery_endpoint(delivery_id: int, data: DeliveryReconcileRequest):
    """Admin End-of-Day reconciliation: APPROVE or REJECT with reason."""
    try:
        deliv = reconcile_delivery(
            delivery_id=delivery_id,
            action=data.action,
            approved_by=data.approved_by or "Admin",
            rejection_reason=data.rejection_reason or ""
        )
        return {
            "success": True,
            "delivery": deliv,
            "message": f"Delivery #{deliv['invoice_no']} {deliv['approval_status'].lower()} successfully."
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/deliveries/{delivery_id}")
@app.post("/api/deliveries/{delivery_id}/delete")
def delete_delivery_endpoint(delivery_id: int):
    """Admin permanently deletes a home delivery entry."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Delivery record not found")
    deliv = dict(row)

    cursor.execute("DELETE FROM deliveries WHERE id = ?", (delivery_id,))
    conn.commit()
    conn.close()

    log_activity(
        category="DELIVERY",
        action_type="DELIVERY_DELETED",
        title=f"Delivery Deleted: #{deliv.get('invoice_no')}",
        description=f"Admin deleted delivery for '{deliv.get('customer_name')}' (Bill #{deliv.get('invoice_no')}, Rs. {float(deliv.get('bill_amount') or 0):,.2f})",
        staff_name="Admin"
    )

    return {"success": True, "delivery_id": delivery_id, "message": f"Delivery #{deliv.get('invoice_no')} successfully deleted."}

@app.put("/api/staff/{staff_id}/convert-rider")
def convert_rider_endpoint(staff_id: int, data: StaffConvertRiderRequest):
    """Converts a temporary rider into permanent staff."""
    updated = convert_temp_rider_to_permanent(
        staff_id=staff_id,
        designation=data.designation or "Delivery Incharge",
        monthly_salary=float(data.monthly_salary or 0.0),
        shift_id=data.shift_id or 1,
        cnic=data.cnic or "",
        address=data.address or ""
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Staff member not found")
    return {
        "success": True,
        "staff": updated,
        "message": f"{updated['name']} successfully converted to permanent staff."
    }

# =====================================================================
# REMOTE LICENSE & KILL-SWITCH API ENDPOINTS
# =====================================================================

class LicenseConfigRequest(BaseModel):
    sheet_url: Optional[str] = None
    dev_contact: Optional[str] = None

@app.get("/api/license/status")
def get_license_status_endpoint():
    """Returns current licensing state (blocked flag, message, developer contact)."""
    return get_license_state()

@app.post("/api/license/sync")
def sync_license_endpoint():
    """Triggers immediate Google Sheet remote check."""
    result = check_remote_sheet(timeout=6)
    state = get_license_state()
    return {
        "sync_result": result,
        "state": state
    }

@app.post("/api/license/config")
def config_license_endpoint(data: LicenseConfigRequest):
    """Configures Google Sheet CSV URL and Developer contact phone number."""
    if data.sheet_url is not None:
        set_setting("google_sheet_csv_url", data.sheet_url.strip())
    if data.dev_contact is not None:
        set_setting("license_dev_contact", data.dev_contact.strip())
    return {
        "success": True,
        "message": "License configuration updated successfully.",
        "state": get_license_state()
    }

# Mount static files for the frontend UI (PyInstaller & Development safe)
import sys
if getattr(sys, 'frozen', False):
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    static_dir = os.path.join(base_dir, "static")
    if not os.path.exists(static_dir):
        static_dir = os.path.join(os.path.dirname(sys.executable), "static")
else:
    static_dir = os.path.join(os.path.dirname(__file__), "static")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static_dir")
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    import socket

    local_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            pass

    print("\n" + "=" * 60)
    print(" MUMTAZ PHARMACY SYSTEM - SERVER CHAL RAHA HAI")
    print(f" -> Is PC (Server) par:  http://localhost:8000")
    print(f" -> Dosre PCs (LAN) par:  http://{local_ip}:8000")
    print("=" * 60 + "\n")

    # When bundled as EXE or standalone, reload must be False
    uvicorn.run(app, host="0.0.0.0", port=8000)

