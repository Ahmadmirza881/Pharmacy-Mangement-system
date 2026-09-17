"""
Mumtaz Pharmacy - Biometric Staff Attendance & Payroll API Server
FastAPI application providing endpoints for biometric punches, live roster,
shift scheduling, staff advance khata, and 1-click month-end payroll.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta
import os
import calendar
import re
import urllib.parse
import random

from database import (
    init_db, get_db_connection, log_activity, get_today_activities,
    get_setting, set_setting, get_all_settings, create_otp_record,
    verify_and_consume_otp, get_active_otps, get_pin_otp_audit_logs,
    mark_otp_notified, get_admin_master_pin, set_admin_master_pin,
    verify_and_reveal_otp_by_token, get_otp_by_token
)
from payroll_engine import process_punch, calculate_monthly_payroll, calculate_custom_range_payroll
from biometric_service import biometric_service
from whatsapp_service import whatsapp_service

from fastapi.middleware.gzip import GZipMiddleware

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

# Startup: Initialize DB
@app.on_event("startup")
def on_startup():
    init_db()

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

class StaffCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    cnic: Optional[str] = None
    address: Optional[str] = None
    designation: str = "Pharmacist"
    monthly_salary: float
    joining_date: Optional[str] = None
    shift_id: int
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

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    credit_limit: Optional[float] = None
    is_active: Optional[int] = None

class CustomerKhataCreate(BaseModel):
    customer_id: int
    invoice_no: Optional[str] = None
    date: Optional[str] = None
    item_description: str
    amount: float
    notes: Optional[str] = ""

class CustomerKhataSettle(BaseModel):
    settled_at: Optional[str] = None
    payment_method: Optional[str] = "Cash"
    notes: Optional[str] = ""
    amount: Optional[float] = None # Optional amount: if less than invoice amount, recorded as partial payment

class CustomerSettleAll(BaseModel):
    settled_at: Optional[str] = None
    payment_method: Optional[str] = "Cash"
    notes: Optional[str] = ""
    amount: Optional[float] = None # Optional amount: if less than total balance, settled partially across pending invoices (FIFO)

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
    cursor.execute("""
        INSERT INTO customers (name, phone, address, credit_limit)
        VALUES (?, ?, ?, ?)
    """, (data.name.strip(), data.phone.strip(), (data.address or "").strip(), data.credit_limit or 15000.0))
    customer_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"success": True, "id": customer_id, "message": f"Customer '{data.name}' registered successfully."}

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

    cursor.execute("""
        UPDATE customers
        SET name = ?, phone = ?, address = ?, credit_limit = ?, is_active = ?
        WHERE id = ?
    """, (new_name, new_phone, new_address, new_limit, new_active, customer_id))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Customer '{new_name}' updated successfully."}

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

    cursor.execute("""
        INSERT INTO customer_khata (customer_id, invoice_no, date, item_description, amount, is_settled, notes)
        VALUES (?, ?, ?, ?, ?, 0, ?)
    """, (data.customer_id, invoice_no.strip(), entry_date, data.item_description.strip(), data.amount, (data.notes or "").strip()))
    entry_id = cursor.lastrowid
    conn.commit()

    # Get updated balance
    cursor.execute("SELECT SUM(amount) FROM customer_khata WHERE customer_id = ? AND is_settled = 0", (data.customer_id,))
    new_balance = cursor.fetchone()[0] or 0.0
    conn.close()

    log_activity(
        category="CUSTOMER_KHATA",
        action_type="CUSTOMER_KHATA_ADDED",
        title=f"Customer Credit: {customer['name']}",
        description=f"Invoice #{invoice_no}: {data.item_description.strip()} (Rs. {data.amount:,.2f})",
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
        "message": f"Credit purchase of Rs. {data.amount:,.2f} recorded for {customer['name']} ({invoice_no})."
    }

@app.post("/api/customer-khata/{entry_id}/settle")
def settle_customer_khata(entry_id: int, data: CustomerKhataSettle):
    """Marks a single customer credit invoice as settled in full or in part."""
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

    # Determine if full or partial
    is_partial = False
    if data.amount is not None and 0 < data.amount < orig_amount:
        is_partial = True
        paid_amt = round(float(data.amount), 2)
        rem_amt = round(orig_amount - paid_amt, 2)

        audit_note = f"Partial payment Rs. {paid_amt:,.2f} received on {settle_date} via {pay_method}"
        if notes_val:
            audit_note += f" ({notes_val})"

        # 1. Update this entry to be the settled portion
        cursor.execute("""
            UPDATE customer_khata
            SET amount = ?,
                is_settled = 1,
                settled_at = ?,
                payment_method = ?,
                notes = CASE WHEN notes != '' THEN notes || ' | ' || ? ELSE ? END
            WHERE id = ?
        """, (paid_amt, settle_date, pay_method, audit_note, audit_note, entry_id))

        # 2. Insert new entry for remaining unpaid balance
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
        # Full settlement
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

        # Recalculate customer balance
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
    """Settles all or partial customer balance across pending invoices (FIFO)."""
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
            "total_outstanding": total_outstanding,
            "debtor_count": len(debtors)
        },
        "debtors": debtors,
        "recent_transactions": recent_transactions
    }

# Mount static files for the frontend UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
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

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

