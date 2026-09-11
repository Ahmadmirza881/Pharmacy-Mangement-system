"""
Mumtaz Pharmacy - Biometric Staff Attendance & Payroll API Server
FastAPI application providing endpoints for biometric punches, live roster,
shift scheduling, staff advance khata, and 1-click month-end payroll.
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
import os
import calendar

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
    role: str
    monthly_salary: float
    shift_id: int
    fingerprint_id: Optional[str] = None

class AdvanceCreate(BaseModel):
    staff_id: int
    amount: float
    reason: Optional[str] = "Advance from Till"
    date_str: Optional[str] = None

class LeaveCreate(BaseModel):
    staff_id: int
    date: str
    reason: Optional[str] = "Approved Medical / Personal Leave"

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

    # Get all active staff
    cursor.execute("""
        SELECT s.id, s.name, s.role, s.monthly_salary, sh.name as shift_name,
               sh.start_time, sh.end_time,
               a.time_in, a.time_out, a.status, a.late_minutes, a.worked_minutes, a.overtime_minutes
        FROM staff s
        JOIN shifts sh ON s.shift_id = sh.id
        LEFT JOIN attendance_logs a ON s.id = a.staff_id AND a.date = ?
        WHERE s.is_active = 1
        ORDER BY s.id ASC
    """, (today_str,))
    rows = cursor.fetchall()
    conn.close()

    roster = []
    total_staff = len(rows)
    present_count = 0
    late_count = 0
    absent_count = 0

    for r in rows:
        item = dict(r)
        status = item.get("status")
        if not status:
            # Has not punched in yet today
            # If current time is 2 hours past shift start, mark as ABSENT, else PENDING
            now_time = datetime.now().time()
            shift_parts = item["start_time"].split(":")
            shift_h, shift_m = int(shift_parts[0]), int(shift_parts[1])
            cutoff_dt = datetime.now().replace(hour=shift_h + 2, minute=shift_m, second=0)

            if datetime.now() > cutoff_dt:
                item["status"] = "ABSENT"
                absent_count += 1
            else:
                item["status"] = "PENDING"
        else:
            if status in ("ON_TIME", "LATE", "HALF_DAY"):
                present_count += 1
                if status == "LATE":
                    late_count += 1
            elif status == "ABSENT":
                absent_count += 1

        roster.append(item)

    return {
        "date": today_str,
        "total_staff": total_staff,
        "present_count": present_count,
        "late_count": late_count,
        "absent_count": absent_count,
        "pending_count": total_staff - present_count - absent_count,
        "roster": roster
    }

@app.get("/api/staff")
def list_staff():
    """Lists all registered staff members with their shift details."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.*, sh.name as shift_name, sh.start_time, sh.end_time
        FROM staff s
        JOIN shifts sh ON s.shift_id = sh.id
        WHERE s.is_active = 1
        ORDER BY s.id ASC
    """)
    staff = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return staff

@app.post("/api/staff")
def create_staff(data: StaffCreate):
    """Adds a new staff member with assigned shift and salary."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO staff (name, phone, cnic, role, monthly_salary, shift_id, fingerprint_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (data.name, data.phone, data.cnic, data.role, data.monthly_salary, data.shift_id, data.fingerprint_id))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"success": True, "staff_id": new_id, "message": f"Staff member '{data.name}' registered successfully."}

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
    """Records an advance cash payout given to staff."""
    date_str = data.date_str or date.today().strftime("%Y-%m-%d")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO advance_salaries (staff_id, amount, date, reason)
        VALUES (?, ?, ?, ?)
    """, (data.staff_id, data.amount, date_str, data.reason))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Advance of Rs. {data.amount:,.2f} recorded successfully."}

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
    total_payout = 0
    total_deductions = 0

    for sid in staff_ids:
        payroll = calculate_monthly_payroll(sid, month, year)
        results.append(payroll)
        total_payout += payroll["net_payable"]
        total_deductions += (payroll["absent_cut"] + payroll["late_cut"] + payroll["half_day_cut"] + payroll["advances_deducted"])

    return {
        "month": month,
        "year": year,
        "month_name": calendar.month_name[month],
        "total_staff": len(results),
        "total_payout": total_payout,
        "total_deductions": total_deductions,
        "sheet": results
    }

# Mount static files for the frontend UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
