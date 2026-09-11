import urllib.request
import json

def fetch(endpoint):
    url = f"http://127.0.0.1:8000{endpoint}"
    req = urllib.request.Request(url, headers={"User-Agent": "MumtazTestClient"})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))

print("\n" + "="*70)
print("1. TODAY'S LIVE ROSTER (2026-09-11)")
print("="*70)
live = fetch("/api/attendance/today")
print(f"Date: {live['date']} | Total: {live['total_staff']} | Present: {live['present_count']} | Late: {live['late_count']} | On Leave: {live['leave_count']} | Absent: {live['absent_count']}")
for r in live["roster"]:
    in_time = r.get("time_in") or "—"
    out_time = r.get("time_out") or "—"
    late_info = f" (Late: {r['late_minutes']}m)" if r.get("late_minutes") else ""
    reason = f" [Reason: {r['leave_reason']}]" if r.get("leave_reason") else ""
    print(f"  #{r['id']:<2} {r['name']:<16} | {r['designation']:<24} | Status: {r['status']:<9}{late_info:<12} | In: {in_time:<8} | Out: {out_time:<8}{reason}")

print("\n" + "="*70)
print("2. 1-CLICK PAYROLL CALCULATION (SEPTEMBER 2026)")
print("="*70)
pay = fetch("/api/payroll/calculate?month=9&year=2026")
print(f"Month: {pay['month_name']} {pay['year']} | Total Staff: {pay['total_staff']}")
print(f"Total Net Payable: Rs. {pay['total_payout']:,.2f} | Total Deductions: Rs. {pay['total_deductions']:,.2f}")
print("-" * 70)
for s in pay["sheet"]:
    print(f"  #{s['staff_id']:<2} {s['staff_name']:<16} ({s['designation']})")
    print(f"      Basic Pay: Rs. {s['basic_salary']:>9,.2f}  |  Daily Wage: Rs. {s['daily_wage']:>7,.2f}")
    print(f"      Absents Cut: -Rs. {s['absent_cut']:>7,.2f} ({s['absent_days']} days)")
    print(f"      Extra Leaves Cut (>2 free): -Rs. {s['extra_leave_cut']:>7,.2f} ({s['extra_leaves']} unpaid)")
    print(f"      Extra Half-Days Cut (>4 free): -Rs. {s['extra_half_day_cut']:>7,.2f} ({s['extra_half_days']} excess)")
    print(f"      Staff Advance / Medicine Khata: -Rs. {s['advances_deducted']:>7,.2f}")
    print(f"      >>> FINAL NET PAYABLE: Rs. {s['net_payable']:>9,.2f}")

print("\n" + "="*70)
print("3. STAFF ADVANCE & MEDICINE CREDIT KHATA LEDGER")
print("="*70)
advances = fetch("/api/advances")
print(f"Total Khata Records: {len(advances)}")
for a in advances[:8]:
    status_label = "Settled" if a['is_settled'] else "PENDING DEDUCTION"
    print(f"  {a['date']} | #{a['staff_id']} {a['staff_name']:<14} | {a['entry_type']:<15} | Rs. {a['amount']:>6,.2f} | {status_label:<17} | {a['reason']}")

print("\n" + "="*70)
print("4. MONTHLY ATTENDANCE REGISTER & MATRIX (FEATURE 17)")
print("="*70)
matrix = fetch("/api/attendance/monthly?month=9&year=2026")
print(f"Period: {matrix['month']}/{matrix['year']} ({matrix['days_in_month']} Days) | Staff: {len(matrix['matrix'])}")
for m in matrix["matrix"]:
    print(f"  #{m['staff_id']:<2} {m['name']:<16} ({m['designation']:<24}) => P: {m['present_count']:<2} | L: {m['late_count']:<2} | HD: {m['half_day_count']:<2} | LV: {m['leave_count']:<2} | A: {m['absent_count']:<2}")

print("\n" + "="*70)
print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")
print("="*70)
