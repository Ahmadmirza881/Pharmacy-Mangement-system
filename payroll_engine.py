"""
Mumtaz Pharmacy - Payroll & Attendance Rules Engine
Core mathematical algorithms for daily wage, absence cuts, late penalties,
overtime calculation, and advance salary reconciliation.
"""

import calendar
from datetime import datetime, date, time, timedelta
from database import get_db_connection

def calculate_daily_wage(monthly_salary: float, days_in_month: int) -> float:
    """Computes accurate daily wage based on specific month's calendar days."""
    if days_in_month <= 0:
        return 0.0
    return round(monthly_salary / days_in_month, 2)

def parse_time_str(time_str: str) -> time:
    """Parses 'HH:MM' or 'HH:MM:SS' string into datetime.time object."""
    parts = time_str.split(":")
    return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)

def process_punch(staff_id: int, punch_dt: datetime = None, method: str = "FINGERPRINT"):
    """
    Handles staff biometric punch (IN or OUT).
    - If no punch exists for today: Registers Time-IN, checks against shift start + grace.
    - If Time-IN exists but no Time-OUT: Registers Time-OUT, calculates worked minutes & overtime.
    - If both exist: Updates Time-OUT to the latest punch.
    """
    if punch_dt is None:
        punch_dt = datetime.now()

    punch_date_str = punch_dt.strftime("%Y-%m-%d")
    punch_time_str = punch_dt.strftime("%H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get staff & shift info
    cursor.execute("""
        SELECT s.id, s.name, s.shift_id, sh.name as shift_name, 
               sh.start_time, sh.end_time, sh.grace_minutes, sh.half_day_minutes, sh.is_night_shift
        FROM staff s
        JOIN shifts sh ON s.shift_id = sh.id
        WHERE s.id = ? AND s.is_active = 1
    """, (staff_id,))
    staff = cursor.fetchone()

    if not staff:
        conn.close()
        return {"success": False, "message": f"Active staff member #{staff_id} not found."}

    # Check today's existing log
    cursor.execute("SELECT * FROM attendance_logs WHERE staff_id = ? AND date = ?", (staff_id, punch_date_str))
    log = cursor.fetchone()

    shift_start = parse_time_str(staff["start_time"])
    shift_end = parse_time_str(staff["end_time"])
    grace_mins = staff["grace_minutes"]
    half_day_mins = staff["half_day_minutes"]

    # 1. PUNCH IN
    if not log:
        punch_time_obj = punch_dt.time()
        shift_start_dt = datetime.combine(punch_dt.date(), shift_start)
        allowed_grace_dt = shift_start_dt + timedelta(minutes=grace_mins)

        is_late = punch_dt > allowed_grace_dt
        status = "LATE" if is_late else "ON_TIME"
        late_minutes = max(0, int((punch_dt - shift_start_dt).total_seconds() // 60)) if is_late else 0

        cursor.execute("""
            INSERT INTO attendance_logs 
            (staff_id, date, time_in, status, late_minutes, punch_method)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (staff_id, punch_date_str, punch_time_str, status, late_minutes, method))
        conn.commit()
        conn.close()

        msg = f"Welcome {staff['name']}! Time-IN recorded at {punch_time_str}."
        if is_late:
            msg += f" (Late by {late_minutes} minutes)"
        else:
            msg += " (On Time)"

        return {
            "success": True,
            "punch_type": "IN",
            "staff_name": staff["name"],
            "time": punch_time_str,
            "status": status,
            "late_minutes": late_minutes,
            "message": msg
        }

    # 2. PUNCH OUT
    else:
        time_in_str = log["time_in"]
        time_in_dt = datetime.strptime(f"{punch_date_str} {time_in_str}", "%Y-%m-%d %H:%M:%S")

        worked_seconds = max(0, (punch_dt - time_in_dt).total_seconds())
        worked_minutes = int(worked_seconds // 60)

        # Overtime: beyond scheduled shift end
        shift_end_dt = datetime.combine(punch_dt.date(), shift_end)
        overtime_minutes = 0
        if punch_dt > shift_end_dt:
            overtime_minutes = int((punch_dt - shift_end_dt).total_seconds() // 60)

        # Half day check: worked less than required half day threshold
        status = log["status"]
        if worked_minutes < half_day_mins:
            status = "HALF_DAY"

        cursor.execute("""
            UPDATE attendance_logs
            SET time_out = ?, worked_minutes = ?, overtime_minutes = ?, status = ?
            WHERE id = ?
        """, (punch_time_str, worked_minutes, overtime_minutes, status, log["id"]))
        conn.commit()
        conn.close()

        hours = worked_minutes // 60
        mins = worked_minutes % 60
        msg = f"Goodbye {staff['name']}! Time-OUT recorded at {punch_time_str}. (Worked: {hours}h {mins}m"
        if overtime_minutes > 0:
            msg += f", Overtime: {overtime_minutes} mins"
        msg += ")"

        return {
            "success": True,
            "punch_type": "OUT",
            "staff_name": staff["name"],
            "time": punch_time_str,
            "status": status,
            "worked_minutes": worked_minutes,
            "overtime_minutes": overtime_minutes,
            "message": msg
        }

def calculate_monthly_payroll(staff_id: int, month: int, year: int) -> dict:
    """
    Computes complete transparent payroll sheet for an employee for a specific month.
    Formulates:
    - Daily Wage
    - Absenteeism cuts
    - Late count & penalty (every 3 lates = 0.5 day wage cut)
    - Half-day cuts
    - Overtime pay additions
    - Unsettled advance deductions
    - Final Net Payable
    """
    _, days_in_month = calendar.monthrange(year, month)
    start_date_str = f"{year}-{month:02d}-01"
    end_date_str = f"{year}-{month:02d}-{days_in_month:02d}"

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get staff basic info
    cursor.execute("SELECT * FROM staff WHERE id = ?", (staff_id,))
    staff = cursor.fetchone()
    if not staff:
        conn.close()
        raise ValueError(f"Staff #{staff_id} not found.")

    basic_salary = staff["monthly_salary"]
    daily_wage = calculate_daily_wage(basic_salary, days_in_month)

    # 1. Fetch all attendance logs for this month
    cursor.execute("""
        SELECT * FROM attendance_logs
        WHERE staff_id = ? AND date BETWEEN ? AND ?
    """, (staff_id, start_date_str, end_date_str))
    logs = cursor.fetchall()

    present_days = 0
    late_count = 0
    half_days = 0
    total_overtime_mins = 0
    logged_dates = set()

    for log in logs:
        logged_dates.add(log["date"])
        if log["status"] in ("ON_TIME", "LATE"):
            present_days += 1
            if log["status"] == "LATE":
                late_count += 1
        elif log["status"] == "HALF_DAY":
            half_days += 1
        total_overtime_mins += log["overtime_minutes"] or 0

    # 2. Fetch approved leaves for this month
    cursor.execute("""
        SELECT date FROM leaves
        WHERE staff_id = ? AND date BETWEEN ? AND ?
    """, (staff_id, start_date_str, end_date_str))
    leave_dates = {row["date"] for row in cursor.fetchall()}

    # 3. Calculate Absent days (past days up to today or month end with no log and no leave)
    today = date.today()
    eval_end_day = days_in_month
    if year == today.year and month == today.month:
        eval_end_day = today.day # only evaluate up to today if calculating current month

    absent_days = 0
    for day_num in range(1, eval_end_day + 1):
        cur_date_str = f"{year}-{month:02d}-{day_num:02d}"
        if cur_date_str not in logged_dates and cur_date_str not in leave_dates:
            # Check if this day is a standard weekly rest day (e.g., if pharmacy gives Sundays off, optional)
            # Default: all unlogged days are marked absent
            absent_days += 1

    # Deductions Math
    absent_cut = round(absent_days * daily_wage, 2)
    
    # Late Penalty Rule: Every 3 late marks = 0.5 Day Wage deduction
    late_penalties_count = late_count // 3
    late_cut = round(late_penalties_count * (daily_wage * 0.5), 2)

    # Half day cut: 0.5 day wage cut per half day
    half_day_cut = round(half_days * (daily_wage * 0.5), 2)

    # Overtime Math: 8 hours shift assumed
    hourly_rate = daily_wage / 8.0
    overtime_pay = round((total_overtime_mins / 60.0) * hourly_rate, 2)

    # 4. Fetch unsettled advances taken by staff
    cursor.execute("""
        SELECT id, amount, date, reason FROM advance_salaries
        WHERE staff_id = ? AND is_settled = 0 AND date <= ?
    """, (staff_id, end_date_str))
    advances = cursor.fetchall()
    advances_total = sum(adv["amount"] for adv in advances)

    # Final Net Payable
    net_payable = round(
        basic_salary - absent_cut - late_cut - half_day_cut - advances_total + overtime_pay, 
        2
    )
    if net_payable < 0:
        net_payable = 0.0

    # Save / Update Payroll Record in DB
    cursor.execute("""
        INSERT INTO payroll_records 
        (staff_id, month, year, days_in_month, basic_salary, daily_wage,
         present_days, absent_days, absent_cut, late_count, late_cut,
         half_days, half_day_cut, overtime_minutes, overtime_pay,
         advances_deducted, net_payable)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(staff_id, month, year) DO UPDATE SET
            days_in_month = excluded.days_in_month,
            basic_salary = excluded.basic_salary,
            daily_wage = excluded.daily_wage,
            present_days = excluded.present_days,
            absent_days = excluded.absent_days,
            absent_cut = excluded.absent_cut,
            late_count = excluded.late_count,
            late_cut = excluded.late_cut,
            half_days = excluded.half_days,
            half_day_cut = excluded.half_day_cut,
            overtime_minutes = excluded.overtime_minutes,
            overtime_pay = excluded.overtime_pay,
            advances_deducted = excluded.advances_deducted,
            net_payable = excluded.net_payable
    """, (staff_id, month, year, days_in_month, basic_salary, daily_wage,
          present_days, absent_days, absent_cut, late_count, late_cut,
          half_days, half_day_cut, total_overtime_mins, overtime_pay,
          advances_total, net_payable))

    conn.commit()
    conn.close()

    return {
        "staff_id": staff_id,
        "staff_name": staff["name"],
        "role": staff["role"],
        "month": month,
        "year": year,
        "days_in_month": days_in_month,
        "basic_salary": basic_salary,
        "daily_wage": daily_wage,
        "present_days": present_days,
        "absent_days": absent_days,
        "absent_cut": absent_cut,
        "late_count": late_count,
        "late_penalties_applied": late_penalties_count,
        "late_cut": late_cut,
        "half_days": half_days,
        "half_day_cut": half_day_cut,
        "overtime_minutes": total_overtime_mins,
        "overtime_pay": overtime_pay,
        "advances_deducted": advances_total,
        "net_payable": net_payable
    }
