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

def process_punch(staff_id: int, punch_dt: datetime = None, method: str = "FINGERPRINT", force_action: str = None):
    """
    Authoritative Attendance Punch Engine with Flexible Arrival Time.
    If force_action is specified ('IN' or 'OUT'), respects user's explicit choice.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if not punch_dt:
        punch_dt = datetime.now()

    punch_date_str = punch_dt.strftime("%Y-%m-%d")
    punch_time_str = punch_dt.strftime("%H:%M:%S")

    # Fetch staff and shift info
    cursor.execute("""
        SELECT s.id, s.name, s.shift_id, s.daily_hours, s.allowed_leaves, sh.name as shift_name, 
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

    daily_hours = float(staff["daily_hours"]) if ("daily_hours" in staff.keys() and staff["daily_hours"]) else 8.0
    required_minutes = int(daily_hours * 60)

    # Determine action: explicit force_action takes precedence over automatic detection
    target_action = force_action.upper() if force_action and force_action.upper() in ["IN", "OUT"] else None
    if not target_action:
        target_action = "IN" if not log else "OUT"

    # 1. PUNCH IN (Flexible Start)
    if target_action == "IN":
        target_out_dt = punch_dt + timedelta(minutes=required_minutes)
        target_out_str = target_out_dt.strftime("%I:%M %p")
        status = "ON_TIME"
        late_minutes = 0

        if not log:
            cursor.execute("""
                INSERT INTO attendance_logs 
                (staff_id, date, time_in, status, late_minutes, punch_method)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (staff_id, punch_date_str, punch_time_str, status, late_minutes, method))
        else:
            # Overwrite/update time_in if explicitly re-checking in
            cursor.execute("""
                UPDATE attendance_logs 
                SET time_in = ?, status = ?, punch_method = ?
                WHERE id = ?
            """, (punch_time_str, status, method, log["id"]))
        conn.commit()
        conn.close()

        msg = f"Welcome {staff['name']}! Time-IN recorded at {punch_time_str}. Target duty completion: {target_out_str} ({daily_hours:g} hrs)."
        return {
            "success": True,
            "punch_type": "IN",
            "staff_name": staff["name"],
            "time": punch_time_str,
            "status": status,
            "late_minutes": 0,
            "target_out": target_out_str,
            "daily_hours": daily_hours,
            "message": msg
        }

    # 2. PUNCH OUT (Checks daily required hours)
    else:
        time_in_str = log["time_in"]
        time_in_dt = datetime.strptime(f"{punch_date_str} {time_in_str}", "%Y-%m-%d %H:%M:%S")

        worked_seconds = max(0, (punch_dt - time_in_dt).total_seconds())
        worked_minutes = int(worked_seconds // 60)

        overtime_minutes = max(0, worked_minutes - required_minutes)
        short_minutes = max(0, required_minutes - worked_minutes)

        if worked_minutes >= required_minutes:
            status = "ON_TIME"
        else:
            status = "SHORT_HOURS"

        cursor.execute("""
            UPDATE attendance_logs
            SET time_out = ?, worked_minutes = ?, overtime_minutes = ?, status = ?
            WHERE id = ?
        """, (punch_time_str, worked_minutes, overtime_minutes, status, log["id"]))
        conn.commit()
        conn.close()

        hours = worked_minutes // 60
        mins = worked_minutes % 60
        if worked_minutes >= required_minutes:
            msg = f"Goodbye {staff['name']}! Time-OUT recorded at {punch_time_str}. (Worked: {hours}h {mins}m — Full Duty Completed!)"
        else:
            sh_h = short_minutes // 60
            sh_m = short_minutes % 60
            msg = f"Goodbye {staff['name']}! Time-OUT recorded at {punch_time_str}. (Worked: {hours}h {mins}m — Short by {sh_h}h {sh_m}m)."

        return {
            "success": True,
            "punch_type": "OUT",
            "staff_name": staff["name"],
            "time": punch_time_str,
            "status": status,
            "worked_minutes": worked_minutes,
            "short_minutes": short_minutes,
            "overtime_minutes": overtime_minutes,
            "daily_hours": daily_hours,
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

    allowed_leaves = staff["allowed_leaves"] if ("allowed_leaves" in staff.keys() and staff["allowed_leaves"] is not None) else 2
    daily_hours = float(staff["daily_hours"]) if ("daily_hours" in staff.keys() and staff["daily_hours"]) else 8.0
    hourly_wage = round(daily_wage / daily_hours, 2)
    minute_wage = hourly_wage / 60.0
    req_minutes = int(daily_hours * 60)

    # 1. Fetch all attendance logs for this month
    cursor.execute("""
        SELECT * FROM attendance_logs
        WHERE staff_id = ? AND date BETWEEN ? AND ?
    """, (staff_id, start_date_str, end_date_str))
    logs = cursor.fetchall()

    present_days = 0
    late_count = 0
    half_days = 0
    total_short_minutes = 0
    short_days_count = 0
    total_overtime_mins = 0
    logged_dates = set()

    for log in logs:
        logged_dates.add(log["date"])
        status = log["status"]
        worked = log["worked_minutes"] or 0

        if status in ("ON_TIME", "LATE", "PRESENT"):
            present_days += 1
            if status == "LATE":
                late_count += 1
        elif status == "HALF_DAY":
            half_days += 1
            present_days += 1
        elif status == "SHORT_HOURS":
            present_days += 1
            if worked < req_minutes:
                deficit = req_minutes - worked
                total_short_minutes += deficit
                short_days_count += 1
        elif log["time_in"]:
            present_days += 1
            if log["time_out"] and worked < req_minutes:
                deficit = req_minutes - worked
                total_short_minutes += deficit
                short_days_count += 1

        total_overtime_mins += log["overtime_minutes"] or 0

    # 2. Fetch approved leaves for this month (supporting Full-Day and Half-Day leaves)
    cursor.execute("""
        SELECT date, coalesce(leave_type, 'FULL_DAY') as leave_type FROM leaves
        WHERE staff_id = ? AND date BETWEEN ? AND ?
    """, (staff_id, start_date_str, end_date_str))
    leave_rows = cursor.fetchall()
    leave_dates = {row["date"] for row in leave_rows}

    # 3. Calculate Absent days (past days up to today or month end with no log and no leave)
    today = date.today()
    eval_end_day = days_in_month
    if year == today.year and month == today.month:
        eval_end_day = today.day # only evaluate up to today if calculating current month

    # Respect staff joining_date if registered mid-month
    j_dt = None
    if staff["joining_date"]:
        try:
            j_dt = datetime.strptime(staff["joining_date"], "%Y-%m-%d").date()
        except Exception:
            pass

    eval_start_day = 1
    if j_dt and j_dt.year == year and j_dt.month == month:
        eval_start_day = max(1, j_dt.day)

    absent_days = 0
    for day_num in range(eval_start_day, eval_end_day + 1):
        cur_date_str = f"{year}-{month:02d}-{day_num:02d}"
        if cur_date_str not in logged_dates and cur_date_str not in leave_dates:
            absent_days += 1

    # Deductions Math
    absent_cut = round(absent_days * daily_wage, 2)

    # Dynamic Paid Leaves Quota: Full Day = 1.0, Half Day = 0.5
    leaves_count = 0.0
    for row in leave_rows:
        if row["leave_type"] == "HALF_DAY":
            leaves_count += 0.5
        else:
            leaves_count += 1.0

    extra_leaves = max(0.0, leaves_count - allowed_leaves)
    extra_leave_cut = round(extra_leaves * daily_wage, 2)

    # Half-day policy (for legacy HALF_DAY status logs)
    extra_half_days = max(0, half_days - 4)
    extra_half_day_cut = round(extra_half_days * (0.5 * daily_wage), 2)
    half_day_cut = extra_half_day_cut

    # Short Hours Deficit Deduction (Hourly wage deduction)
    short_hours_cut = round(total_short_minutes * minute_wage, 2)

    # Client Scope Check: Late Penalties & Overtime are strictly EXCLUDED from automatic wage cuts/additions
    late_cut = 0.0
    overtime_pay = 0.0

    # 4. Fetch unsettled advances and medicine credits, plus advances settled in this month's payroll
    cursor.execute("""
        SELECT id, amount, date, reason, entry_type, settlement_type, settled_at FROM advance_salaries
        WHERE staff_id = ? AND (
            (settled_payroll_month = ? AND settled_payroll_year = ?)
            OR (is_settled = 1 AND settled_at BETWEEN ? AND ? AND (settlement_type LIKE '%Salary%' OR settlement_type = ''))
            OR (is_settled = 0 AND date <= ?)
        )
    """, (staff_id, month, year, start_date_str, end_date_str, end_date_str))
    advances = cursor.fetchall()
    advances_total = sum(adv["amount"] for adv in advances)

    # Final Net Payable Formula:
    # Basic Salary - Absent Cuts - Extra Leave Cuts - Extra Half-Day Cuts - Short Hours Cuts - Advance Deductions
    net_payable = round(
        basic_salary - absent_cut - extra_leave_cut - extra_half_day_cut - short_hours_cut - advances_total,
        2
    )
    if net_payable < 0:
        net_payable = 0.0

    # Save / Update Payroll Record in DB
    cursor.execute("""
        INSERT INTO payroll_records 
        (staff_id, month, year, days_in_month, basic_salary, daily_wage,
         present_days, absent_days, absent_cut, late_count, late_cut,
         half_days, extra_half_days, half_day_cut, extra_half_day_cut,
         leaves_count, extra_leaves, extra_leave_cut,
         overtime_minutes, overtime_pay,
         advances_deducted, short_hours_cut, short_minutes, net_payable)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            extra_half_days = excluded.extra_half_days,
            half_day_cut = excluded.half_day_cut,
            extra_half_day_cut = excluded.extra_half_day_cut,
            leaves_count = excluded.leaves_count,
            extra_leaves = excluded.extra_leaves,
            extra_leave_cut = excluded.extra_leave_cut,
            overtime_minutes = excluded.overtime_minutes,
            overtime_pay = excluded.overtime_pay,
            advances_deducted = excluded.advances_deducted,
            short_hours_cut = excluded.short_hours_cut,
            short_minutes = excluded.short_minutes,
            net_payable = excluded.net_payable
    """, (staff_id, month, year, days_in_month, basic_salary, daily_wage,
          present_days, absent_days, absent_cut, late_count, late_cut,
          half_days, extra_half_days, half_day_cut, extra_half_day_cut,
          leaves_count, extra_leaves, extra_leave_cut,
          total_overtime_mins, overtime_pay,
          advances_total, short_hours_cut, total_short_minutes, net_payable))

    cursor.execute("""
        SELECT status, paid_at, payment_method, notes 
        FROM payroll_records 
        WHERE staff_id = ? AND month = ? AND year = ?
    """, (staff_id, month, year))
    pr_row = cursor.fetchone()
    pr_status = pr_row["status"] if pr_row and pr_row["status"] else "GENERATED"
    pr_paid_at = pr_row["paid_at"] if pr_row and pr_row["paid_at"] else ""
    pr_payment_method = pr_row["payment_method"] if pr_row and "payment_method" in pr_row.keys() and pr_row["payment_method"] else "Cash"
    pr_notes = pr_row["notes"] if pr_row and "notes" in pr_row.keys() and pr_row["notes"] else ""

    conn.commit()
    conn.close()

    return {
        "staff_id": staff_id,
        "staff_name": staff["name"],
        "phone": staff["phone"] if "phone" in staff.keys() else "",
        "role": staff["role"],
        "designation": staff["designation"] if "designation" in staff.keys() and staff["designation"] else staff["role"],
        "month": month,
        "year": year,
        "days_in_month": days_in_month,
        "basic_salary": basic_salary,
        "daily_wage": daily_wage,
        "daily_hours": daily_hours,
        "hourly_wage": hourly_wage,
        "allowed_leaves": allowed_leaves,
        "present_days": present_days,
        "absent_days": absent_days,
        "absent_cut": absent_cut,
        "late_count": late_count,
        "late_cut": 0.0,
        "half_days": half_days,
        "extra_half_days": extra_half_days,
        "half_day_cut": half_day_cut,
        "extra_half_day_cut": extra_half_day_cut,
        "short_hours_cut": short_hours_cut,
        "total_short_minutes": total_short_minutes,
        "short_days_count": short_days_count,
        "leaves_count": leaves_count,
        "extra_leaves": extra_leaves,
        "extra_leave_cut": extra_leave_cut,
        "advances_deducted": advances_total,
        "advances_list": [dict(a) for a in advances],
        "net_payable": net_payable,
        "status": pr_status,
        "paid_at": pr_paid_at,
        "payment_method": pr_payment_method,
        "notes": pr_notes
    }


def calculate_custom_range_payroll(staff_id: int, from_date_str: str = None, to_date_str: str = None) -> dict:
    """
    Calculates flexible rolling date-range payroll for an employee.
    Handles:
    - Custom pay dates (e.g. 4th Sept to 17th Sept for employee paid on 3rd Sept).
    - New employees starting from their joining_date (ignoring days prior to joining).
    - Deduction of unsettled advances and medicine credits up to to_date.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM staff WHERE id = ?", (staff_id,))
    staff = cursor.fetchone()
    if not staff:
        conn.close()
        raise ValueError(f"Staff #{staff_id} not found.")

    today_dt = date.today()
    if not to_date_str:
        to_date_str = today_dt.strftime("%Y-%m-%d")

    to_dt = datetime.strptime(to_date_str, "%Y-%m-%d").date()

    if not from_date_str:
        # Check if staff has a previous paid payroll record
        cursor.execute("""
            SELECT paid_at, year, month FROM payroll_records 
            WHERE staff_id = ? AND status = 'PAID' 
            ORDER BY year DESC, month DESC LIMIT 1
        """, (staff_id,))
        last_paid = cursor.fetchone()

        if last_paid and last_paid["paid_at"]:
            try:
                l_paid_dt = datetime.strptime(last_paid["paid_at"].split()[0], "%Y-%m-%d").date()
                from_dt = l_paid_dt + timedelta(days=1)
            except Exception:
                from_dt = date(to_dt.year, to_dt.month, 1)
        else:
            # Check joining_date
            j_date_str = staff["joining_date"] or ""
            if j_date_str:
                try:
                    from_dt = datetime.strptime(j_date_str, "%Y-%m-%d").date()
                except Exception:
                    from_dt = date(to_dt.year, to_dt.month, 1)
            else:
                from_dt = date(to_dt.year, to_dt.month, 1)
    else:
        from_dt = datetime.strptime(from_date_str, "%Y-%m-%d").date()

    if from_dt > to_dt:
        from_dt = to_dt

    from_date_str = from_dt.strftime("%Y-%m-%d")
    to_date_str = to_dt.strftime("%Y-%m-%d")

    # Calendar math
    _, days_in_month = calendar.monthrange(to_dt.year, to_dt.month)
    basic_salary = float(staff["monthly_salary"])
    daily_wage = round(basic_salary / days_in_month, 2)

    allowed_leaves = staff["allowed_leaves"] if ("allowed_leaves" in staff.keys() and staff["allowed_leaves"] is not None) else 2
    daily_hours = float(staff["daily_hours"]) if ("daily_hours" in staff.keys() and staff["daily_hours"]) else 8.0
    hourly_wage = round(daily_wage / daily_hours, 2)
    minute_wage = hourly_wage / 60.0
    req_minutes = int(daily_hours * 60)

    # 1. Fetch attendance logs for range
    cursor.execute("""
        SELECT * FROM attendance_logs
        WHERE staff_id = ? AND date BETWEEN ? AND ?
    """, (staff_id, from_date_str, to_date_str))
    logs = cursor.fetchall()

    present_days = 0
    late_count = 0
    half_days = 0
    total_short_minutes = 0
    short_days_count = 0
    total_overtime_mins = 0
    logged_dates = set()

    for log in logs:
        logged_dates.add(log["date"])
        status = log["status"]
        worked = log["worked_minutes"] or 0

        if status in ("ON_TIME", "LATE", "PRESENT"):
            present_days += 1
            if status == "LATE":
                late_count += 1
        elif status == "HALF_DAY":
            half_days += 1
            present_days += 1
        elif status == "SHORT_HOURS":
            present_days += 1
            if worked < req_minutes:
                deficit = req_minutes - worked
                total_short_minutes += deficit
                short_days_count += 1
        elif log["time_in"]:
            present_days += 1
            if log["time_out"] and worked < req_minutes:
                deficit = req_minutes - worked
                total_short_minutes += deficit
                short_days_count += 1

        total_overtime_mins += log["overtime_minutes"] or 0

    # 2. Fetch approved leaves for range
    cursor.execute("""
        SELECT date, coalesce(leave_type, 'FULL_DAY') as leave_type FROM leaves
        WHERE staff_id = ? AND date BETWEEN ? AND ?
    """, (staff_id, from_date_str, to_date_str))
    leave_rows = cursor.fetchall()
    leave_dates = {row["date"] for row in leave_rows}

    # 3. Calculate Absent days (evaluating only days from max(from_dt, joining_date) to to_dt)
    j_dt = None
    if staff["joining_date"]:
        try:
            j_dt = datetime.strptime(staff["joining_date"], "%Y-%m-%d").date()
        except Exception:
            pass

    eval_start_dt = max(from_dt, j_dt) if j_dt else from_dt

    absent_days = 0
    curr_dt = eval_start_dt
    total_days_in_period = (to_dt - from_dt).days + 1
    total_evaluated_days = (to_dt - eval_start_dt).days + 1 if eval_start_dt <= to_dt else 0

    while curr_dt <= to_dt:
        c_str = curr_dt.strftime("%Y-%m-%d")
        if c_str not in logged_dates and c_str not in leave_dates:
            absent_days += 1
        curr_dt += timedelta(days=1)

    # Base earned salary for this period
    earned_base_salary = round(total_evaluated_days * daily_wage, 2)
    absent_cut = round(absent_days * daily_wage, 2)

    # Leave quota
    leaves_count = 0.0
    for row in leave_rows:
        leaves_count += 0.5 if row["leave_type"] == "HALF_DAY" else 1.0

    prop_allowed_leaves = round(allowed_leaves * (total_evaluated_days / days_in_month), 1)
    extra_leaves = max(0.0, leaves_count - prop_allowed_leaves)
    extra_leave_cut = round(extra_leaves * daily_wage, 2)

    short_hours_cut = round(total_short_minutes * minute_wage, 2)

    # 4. Fetch unsettled advances
    cursor.execute("""
        SELECT id, amount, date, reason, entry_type FROM advance_salaries
        WHERE staff_id = ? AND is_settled = 0 AND date <= ?
    """, (staff_id, to_date_str))
    advances = cursor.fetchall()
    advances_total = sum(adv["amount"] for adv in advances)

    net_payable = max(0.0, round(
        earned_base_salary - absent_cut - extra_leave_cut - short_hours_cut - advances_total,
        2
    ))

    conn.close()

    return {
        "staff_id": staff_id,
        "staff_name": staff["name"],
        "phone": staff["phone"] if "phone" in staff.keys() else "",
        "role": staff["role"],
        "designation": staff["designation"] if ("designation" in staff.keys() and staff["designation"]) else staff["role"],
        "joining_date": staff["joining_date"],
        "from_date": from_date_str,
        "to_date": to_date_str,
        "total_days_in_period": total_days_in_period,
        "evaluated_working_days": total_evaluated_days,
        "basic_salary": basic_salary,
        "daily_wage": daily_wage,
        "earned_base_salary": earned_base_salary,
        "present_days": present_days,
        "absent_days": absent_days,
        "absent_cut": absent_cut,
        "short_hours_cut": short_hours_cut,
        "total_short_minutes": total_short_minutes,
        "leaves_count": leaves_count,
        "extra_leaves": extra_leaves,
        "extra_leave_cut": extra_leave_cut,
        "advances_deducted": advances_total,
        "advances_list": [dict(a) for a in advances],
        "net_payable": net_payable
    }
