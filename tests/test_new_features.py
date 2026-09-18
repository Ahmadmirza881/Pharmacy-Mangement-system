import pytest
from fastapi.testclient import TestClient
from main import app
import database

client = TestClient(app)

def test_otp_expiry_setting():
    # 1. Update setting
    res = client.post("/api/settings", json={"otp_expiry_minutes": "10"})
    assert res.status_code == 200
    
    # 2. Verify setting read
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM system_settings WHERE key = 'otp_expiry_minutes'")
    val = c.fetchone()['value']
    conn.close()
    assert val == "10"

def test_leave_request_workflow():
    # Fetch active staff or create temporary staff
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, pin, name FROM staff WHERE is_active = 1 LIMIT 1")
    staff = c.fetchone()
    conn.close()
    
    if not staff:
        staff_id = database.add_staff("Test Worker", "Pharmacist", 30000, "03001112233", "1234")
        pin = "1234"
        name = "Test Worker"
    else:
        staff_id = staff["id"]
        pin = staff["pin"]
        name = staff["name"]

    # 1. Submit leave request
    payload = {
        "pin": pin,
        "leave_date": "2026-09-20",
        "leave_type": "FULL_DAY",
        "reason": "Family Function"
    }
    res = client.post("/api/staff/leave-request", json=payload)
    assert res.status_code == 200
    req_data = res.json()
    assert req_data["success"] is True
    req_id = req_data["leave_request"]["id"]

    # 2. Check staff leave status
    res = client.get(f"/api/staff/leave-requests?pin={pin}")
    assert res.status_code == 200
    requests = res.json()["leave_requests"]
    assert any(r["id"] == req_id and r["status"] == "PENDING" for r in requests)

    # 3. Check admin pending count
    res = client.get("/api/admin/leave-requests/pending")
    assert res.status_code == 200
    pending_data = res.json()
    assert pending_data["pending_count"] >= 1

    # 4. Admin Review - Approve
    res = client.post(f"/api/admin/leave-requests/{req_id}/review", json={"action": "APPROVE", "admin_notes": "Granted"})
    assert res.status_code == 200

    # 5. Check staff leave status updated with staff_id and quota verification
    res = client.get(f"/api/staff/leave-requests?pin={pin}&staff_id={staff['id']}")
    assert res.status_code == 200
    data = res.json()
    assert data["staff"]["name"] == staff["name"]
    assert "remaining_quota" in data["staff"]
    requests = data["leave_requests"]
    assert any(r["id"] == req_id and r["status"] == "APPROVED" for r in requests)

    # 6. Check mismatch between staff_id and wrong PIN returns 400
    res_bad = client.get(f"/api/staff/leave-requests?pin=9999&staff_id={staff['id']}")
    assert res_bad.status_code == 400

def test_khata_reports_all_time():
    res1 = client.get("/api/customer-khata/reports/general-all-time")
    assert res1.status_code == 200
    assert res1.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    res2 = client.get("/api/customer-khata/reports/overdue-pending")
    assert res2.status_code == 200
    assert res2.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def test_customer_import_excel():
    # Sample template test
    res = client.get("/api/customers/sample-template")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def test_delivery_charges_and_partial_settlement():
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, name FROM staff WHERE is_active = 1 LIMIT 1")
    staff_row = c.fetchone()
    conn.close()

    staff_id = staff_row["id"] if staff_row else 1
    rider_name = staff_row["name"] if staff_row else "Hamza Rider"

    # Create delivery
    deliv_rec = database.create_delivery(
        staff_id=staff_id,
        delivery_person_name=rider_name,
        delivery_person_phone="03001234567",
        customer_name="Test Customer",
        customer_phone="03009998877",
        customer_address="House 12, Street 5",
        invoice_no="INV-TEST-999",
        bill_amount=1000.0,
        payment_method="Cash",
        notes="Test dispatch",
        delivery_charges=150.0
    )
    deliv_id = deliv_rec["id"]

    # Confirm Return / Settlement with Partial Payment
    settle_payload = {
        "delivery_result": "DELIVERED",
        "payment_status": "PARTIAL",
        "paid_amount": 500.0,
        "payment_method": "Cash",
        "return_reason": "",
        "return_notes": ""
    }
    res = client.post(f"/api/deliveries/{deliv_id}/confirm-return", json=settle_payload)
    assert res.status_code == 200

    # Verify balance math: net total = 1000 + 150 = 1150. Paid = 500. Balance = 650.
    conn = database.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT bill_amount, delivery_charges, paid_amount, balance_amount, status FROM deliveries WHERE id = ?", (deliv_id,))
    d = c.fetchone()
    conn.close()
    net_total = float(d["bill_amount"]) + float(d["delivery_charges"])
    assert net_total == 1150.0
    assert float(d["paid_amount"]) == 500.0
    assert float(d["balance_amount"]) == 650.0

    # Transfer balance to Khata
    res = client.post(f"/api/deliveries/{deliv_id}/transfer-to-khata")
    assert res.status_code == 200
    assert res.json()["success"] is True

def test_staff_completed_deliveries_today():
    res = client.get("/api/deliveries/staff/completed-today")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

def test_all_time_delivery_excel():
    res = client.get("/api/deliveries/reports/all-time")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
