"""
Mumtaz Pharmacy - Biometric Staff Attendance & Payroll API Server
FastAPI application providing endpoints for biometric punches, live roster,
shift scheduling, staff advance khata, and 1-click month-end payroll.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta
import os
import calendar
import re
import urllib.parse

from database import init_db, get_db_connection
from payroll_engine import process_punch, calculate_monthly_payroll
from biometric_service import biometric_service

app = FastAPI(title="Mumtaz Pharmacy Attendance & Payroll System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup: Initialize DB
@app.on_event("startup")
def on_startup():
    init_db()

# --- Request Models ---
class PunchRequest(BaseModel):
    staff_id: int
    method: Optional[str] = "FINGERPRINT"
    custom_time: Optional[str] = None # For testing past or specific punch times

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

class CustomerSettleAll(BaseModel):
    settled_at: Optional[str] = None
    payment_method: Optional[str] = "Cash"
    notes: Optional[str] = ""

# --- API Endpoints ---

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
    return result

@app.get("/api/attendance/today")
def get_today_attendance():
    """Returns today's live roster and statistics for the Owner Dashboard."""
    today_str = date.today().strftime("%Y-%m-%d")
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all active staff with attendance logs and leaves
    cursor.execute("""
        SELECT s.id, s.name, s.role, coalesce(nullif(s.designation, ''), s.role) as designation, s.monthly_salary,
               s.daily_hours, s.allowed_leaves, sh.name as shift_name,
               sh.start_time, sh.end_time,
               a.time_in, a.time_out, a.status, a.late_minutes, a.worked_minutes, a.overtime_minutes,
               l.reason as leave_reason
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
    conn.close()
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
    cursor.execute("""
        INSERT INTO staff (name, phone, cnic, address, role, designation, monthly_salary, joining_date, shift_id, fingerprint_id, police_report, allowed_leaves, daily_hours)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (data.name, data.phone, data.cnic, address, designation, designation, data.monthly_salary, joining_date, data.shift_id, data.fingerprint_id, police_report, allowed_leaves, daily_hours))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"success": True, "staff_id": new_id, "message": f"Staff member '{data.name}' registered successfully."}

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
    conn.commit()
    conn.close()
    label = "Medicine credit" if entry_type == "MEDICINE_CREDIT" else "Cash advance"
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

    cursor.execute("""
        UPDATE advance_salaries
        SET is_settled = 1, settled_at = ?, settlement_type = ?, notes = ?, settled_payroll_month = ?, settled_payroll_year = ?
        WHERE id = ?
    """, (settled_date, settlement_type, notes_val, month_val, year_val, advance_id))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": f"Advance #{advance_id} for {adv['staff_name']} (Rs. {adv['amount']:,.2f}) settled successfully via '{settlement_type}' on {settled_date}.",
        "advance_id": advance_id,
        "settled_at": settled_date,
        "settlement_type": settlement_type,
        "notes": notes_val
    }

@app.post("/api/leaves")
def approve_leave(data: LeaveCreate):
    """Approves an emergency/sick leave so salary is not cut."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO leaves (staff_id, date, reason)
        VALUES (?, ?, ?)
        ON CONFLICT(staff_id, date) DO UPDATE SET reason = excluded.reason
    """, (data.staff_id, data.date, data.reason))
    cursor.execute("""
        UPDATE attendance_logs 
        SET status = 'LEAVE', notes = coalesce(nullif(notes, ''), ?)
        WHERE staff_id = ? AND date = ? AND status = 'ABSENT'
    """, (f"Approved Leave: {data.reason}", data.staff_id, data.date))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Leave approved for date {data.date}."}

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
    """Marks a single customer credit invoice as settled in full."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customer_khata WHERE id = ?", (entry_id,))
    entry = cursor.fetchone()
    if not entry:
        conn.close()
        raise HTTPException(status_code=404, detail="Khata entry not found")

    settle_date = data.settled_at or date.today().isoformat()
    pay_method = data.payment_method or "Cash"
    notes_val = data.notes or ""

    cursor.execute("""
        UPDATE customer_khata
        SET is_settled = 1,
            settled_at = ?,
            payment_method = ?,
            notes = CASE WHEN notes != '' THEN notes || ' | ' || ? ELSE ? END
        WHERE id = ?
    """, (settle_date, pay_method, notes_val, notes_val, entry_id))
    conn.commit()

    # Recalculate customer balance
    cursor.execute("SELECT SUM(amount) FROM customer_khata WHERE customer_id = ? AND is_settled = 0", (entry["customer_id"],))
    updated_balance = cursor.fetchone()[0] or 0.0
    conn.close()

    return {
        "success": True,
        "entry_id": entry_id,
        "settled_at": settle_date,
        "payment_method": pay_method,
        "amount": entry["amount"],
        "updated_balance": updated_balance,
        "message": f"Invoice {entry['invoice_no']} (Rs. {entry['amount']:,.2f}) settled in full via {pay_method}."
    }

@app.post("/api/customers/{customer_id}/settle-all")
def settle_all_customer_balance(customer_id: int, data: CustomerSettleAll):
    """Marks ALL currently pending invoices of a customer as settled in full."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    customer = cursor.fetchone()
    if not customer:
        conn.close()
        raise HTTPException(status_code=404, detail="Customer not found")

    cursor.execute("SELECT * FROM customer_khata WHERE customer_id = ? AND is_settled = 0", (customer_id,))
    pending_items = cursor.fetchall()
    if not pending_items:
        conn.close()
        return {"success": True, "message": "Koi pending balance mojood nahi.", "settled_count": 0, "settled_amount": 0}

    settle_date = data.settled_at or date.today().isoformat()
    pay_method = data.payment_method or "Cash"
    total_cleared = sum(item["amount"] for item in pending_items)
    audit_note = f"Full balance settled on {settle_date} via {pay_method}"
    if data.notes:
        audit_note += f" - {data.notes}"

    cursor.execute("""
        UPDATE customer_khata
        SET is_settled = 1,
            settled_at = ?,
            payment_method = ?,
            notes = CASE WHEN notes != '' THEN notes || ' | ' || ? ELSE ? END
        WHERE customer_id = ? AND is_settled = 0
    """, (settle_date, pay_method, audit_note, audit_note, customer_id))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "customer_id": customer_id,
        "customer_name": customer["name"],
        "settled_count": len(pending_items),
        "settled_amount": total_cleared,
        "settled_at": settle_date,
        "payment_method": pay_method,
        "message": f"Full balance of Rs. {total_cleared:,.2f} ({len(pending_items)} invoices) for {customer['name']} settled via {pay_method}."
    }

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
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
