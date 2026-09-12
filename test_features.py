import urllib.request
import json

def get(path):
    req = urllib.request.Request(f"http://127.0.0.1:8000{path}")
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode("utf-8"))

def post(path, data):
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:8000{path}", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode("utf-8"))

print("=== 1. TEST TODAY'S LIVE ROSTER ===")
live = get("/api/attendance/today")
print(f"Total: {live['total_staff']}, Present: {live['present_count']}, Late: {live['late_count']}, Leave: {live['leave_count']}, Absent: {live['absent_count']}")
assert live['total_staff'] == 6
print("PASS: Today's live roster endpoint valid.")

print("\n=== 2. TEST AUGUST 2026 (LAST MONTH) PAYROLL ===")
aug_pay = get("/api/payroll/calculate?month=8&year=2026")
print(f"August Payroll Staff: {aug_pay['total_staff']}, Total Payout: Rs. {aug_pay['total_payout']:,.2f}")
ali = next(s for s in aug_pay["sheet"] if s["staff_name"] == "Ali Raza")
print(f"Ali Raza August: Basic={ali['basic_salary']}, ExtraLeaveCut={ali['extra_leave_cut']}, AdvancesDeducted={ali['advances_deducted']}, NetPayable={ali['net_payable']}")
assert ali['advances_deducted'] == 2500.0, f"Expected 2500 advance, got {ali['advances_deducted']}"
assert ali['net_payable'] == 41048.39, f"Expected 41048.39, got {ali['net_payable']}"

bilal = next(s for s in aug_pay["sheet"] if s["staff_name"] == "Bilal Ahmed")
print(f"Bilal Ahmed August: Basic={bilal['basic_salary']}, AdvancesDeducted={bilal['advances_deducted']}, NetPayable={bilal['net_payable']}")
assert bilal['advances_deducted'] == 4000.0, f"Expected 4000 advance, got {bilal['advances_deducted']}"
print("PASS: August 2026 payroll itemized deductions verified!")

print("\n=== 3. TEST ADVANCE DIRECT SETTLEMENT ENDPOINT ===")
advances = get("/api/advances")
unsettled = [a for a in advances if not a["is_settled"]]
print(f"Unsettled advances count: {len(unsettled)}")
assert len(unsettled) > 0, "No unsettled advance found"
test_adv = unsettled[0]
print(f"Testing settlement for advance #{test_adv['id']} ({test_adv['staff_name']} - Rs. {test_adv['amount']})")

settle_res = post(f"/api/advances/{test_adv['id']}/settle", {
    "settled_at": "2026-09-11",
    "settlement_type": "Cash Return at Counter Drawer",
    "notes": "Verified at end-of-day till reconciliation"
})
print("Settlement API Response:", settle_res)
assert settle_res["success"] is True

# Verify that advance is now settled
advances_after = get("/api/advances")
settled_item = next(a for a in advances_after if a["id"] == test_adv["id"])
print(f"Verification: is_settled={settled_item['is_settled']}, settled_at={settled_item['settled_at']}, settlement_type={settled_item['settlement_type']}")
assert settled_item["is_settled"] == 1
assert settled_item["settled_at"] == "2026-09-11"
assert "Cash Return" in settled_item["settlement_type"]
print("PASS: Direct settlement and audit tracking verified!")

print("\n=== 4. TEST MONTHLY ATTENDANCE REGISTER (AUGUST & SEPTEMBER) ===")
rep_aug = get("/api/attendance/monthly?month=8&year=2026")
print(f"August Matrix Days: {rep_aug['days_in_month']}, Staff rows: {len(rep_aug['matrix'])}")
assert rep_aug['days_in_month'] == 31
assert len(rep_aug['matrix']) == 6
print("PASS: Monthly register matrix has 31 days data!")

print("\nALL FEATURE API VERIFICATIONS PASSED SUCCESSFULLY!")
