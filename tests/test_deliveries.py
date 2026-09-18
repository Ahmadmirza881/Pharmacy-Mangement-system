import pytest
from fastapi.testclient import TestClient
from main import app
from database import get_db_connection, init_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_check_and_register_temp_rider():
    test_phone = "03007771122"
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM deliveries WHERE delivery_person_phone = ? OR staff_id IN (SELECT id FROM staff WHERE phone = ?)", (test_phone, test_phone))
        conn.execute("DELETE FROM attendance_logs WHERE staff_id IN (SELECT id FROM staff WHERE phone = ?)", (test_phone,))
        conn.execute("DELETE FROM leaves WHERE staff_id IN (SELECT id FROM staff WHERE phone = ?)", (test_phone,))
        conn.execute("DELETE FROM leave_requests WHERE staff_id IN (SELECT id FROM staff WHERE phone = ?)", (test_phone,))
        conn.execute("DELETE FROM advance_salaries WHERE staff_id IN (SELECT id FROM staff WHERE phone = ?)", (test_phone,))
        conn.execute("DELETE FROM payroll_records WHERE staff_id IN (SELECT id FROM staff WHERE phone = ?)", (test_phone,))
        conn.execute("DELETE FROM otp_verifications WHERE staff_id IN (SELECT id FROM staff WHERE phone = ?)", (test_phone,))
        conn.execute("DELETE FROM staff WHERE phone = ?", (test_phone,))
        conn.commit()
    finally:
        conn.close()

    payload = {
        "phone": test_phone,
        "name": "Kashif Rider"
    }
    resp = client.post("/api/deliveries/check-rider", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Kashif Rider"
    assert data["phone"] == test_phone
    assert data["pin"] == "1122" # Last 4 digits of phone
    assert data["is_temp"] is True
    assert data["staff_id"] is not None

def test_dispatch_delivery_success_and_invalid_pin():
    # 1. Test with invalid PIN
    invalid_payload = {
        "rider_type": "NEW",
        "rider_name": "Hamza Delivery",
        "rider_phone": "03123456789",
        "rider_pin": "0000", # Wrong pin (should be 6789)
        "customer_name": "Tariq Customer",
        "customer_phone": "03211234567",
        "customer_address": "House 10, St 5, Model Town, Lahore",
        "invoice_no": "INV-DEL-101",
        "bill_amount": 2450.0,
        "payment_method": "Cash on Delivery",
        "notes": "Call before arrival"
    }
    resp_fail = client.post("/api/deliveries/dispatch", json=invalid_payload)
    assert resp_fail.status_code == 400
    assert "Invalid 4-digit PIN" in resp_fail.json()["detail"]

    # 2. Test with correct PIN (6789)
    valid_payload = dict(invalid_payload)
    valid_payload["rider_pin"] = "6789"
    resp_ok = client.post("/api/deliveries/dispatch", json=valid_payload)
    assert resp_ok.status_code == 200
    res_data = resp_ok.json()
    assert res_data["success"] is True
    deliv = res_data["delivery"]
    assert deliv["invoice_no"] == "INV-DEL-101"
    assert deliv["status"] == "PENDING_DISPATCH"
    assert deliv["approval_status"] == "PENDING"
    
    # Confirm dispatch -> OUT_FOR_DELIVERY
    conf_disp = client.post(f"/api/deliveries/{deliv['id']}/confirm-dispatch")
    assert conf_disp.status_code == 200
    confirmed_deliv = conf_disp.json()["delivery"]
    assert confirmed_deliv["status"] == "OUT_FOR_DELIVERY"
    assert confirmed_deliv["dispatched_at"] != ""

    # Verify WhatsApp payloads
    wa = res_data["whatsapp"]
    assert "admin_message" in wa
    assert "customer_message" in wa
    assert "INV-DEL-101" in wa["admin_message"]
    assert "Tariq Customer" in wa["admin_message"]
    assert "INV-DEL-101" in wa["customer_message"]

def test_active_deliveries_and_rider_return():
    # Dispatch an order with auto_confirm True
    dispatch_payload = {
        "rider_type": "NEW",
        "rider_name": "Usman Rider",
        "rider_phone": "03335551234",
        "rider_pin": "1234",
        "customer_name": "Ahmed Ali",
        "customer_phone": "03004445555",
        "customer_address": "Gulberg 3, Lahore",
        "invoice_no": "INV-DEL-202",
        "bill_amount": 1500.0,
        "payment_method": "Cash on Delivery",
        "auto_confirm": True
    }
    disp_resp = client.post("/api/deliveries/dispatch", json=dispatch_payload)
    assert disp_resp.status_code == 200
    deliv_id = disp_resp.json()["delivery"]["id"]

    # Verify order is in active deliveries
    act_resp = client.get("/api/deliveries/active")
    assert act_resp.status_code == 200
    active_ids = [d["id"] for d in act_resp.json()]
    assert deliv_id in active_ids

    # Return with wrong PIN
    ret_fail = client.post(f"/api/deliveries/{deliv_id}/return", json={"rider_pin": "9999"})
    assert ret_fail.status_code == 400

    # Return with correct PIN & auto_confirm
    ret_ok = client.post(f"/api/deliveries/{deliv_id}/return", json={"rider_pin": "1234", "auto_confirm": True})
    assert ret_ok.status_code == 200
    ret_data = ret_ok.json()
    assert ret_data["success"] is True
    assert ret_data["delivery"]["status"] == "DELIVERED"
    # IMPORTANT: Admin financial approval must remain PENDING until end of day!
    assert ret_data["delivery"]["approval_status"] == "PENDING"
    assert ret_data["delivery"]["delivered_at"] != ""

    # Check return WhatsApp message
    wa_ret = ret_data["whatsapp"]
    assert "admin_message" in wa_ret
    assert "Usman Rider" in wa_ret["admin_message"]
    assert "INV-DEL-202" in wa_ret["admin_message"]
    assert "1,500" in wa_ret["admin_message"]

def test_whatsapp_templates_get_and_save():
    # 1. GET templates
    r_get = client.get("/api/deliveries/templates")
    assert r_get.status_code == 200
    tmpl_data = r_get.json()
    assert "admin_dispatch" in tmpl_data
    assert "customer_dispatch" in tmpl_data
    assert "admin_return" in tmpl_data

    # 2. POST update templates
    custom_admin = "CUSTOM ADMIN DISPATCH #{invoice} to {customer_name}"
    r_post = client.post("/api/deliveries/templates", json={
        "admin_dispatch": custom_admin
    })
    assert r_post.status_code == 200
    assert r_post.json()["success"] is True
    assert r_post.json()["templates"]["admin_dispatch"] == custom_admin

def test_admin_end_of_day_reconciliation_approve_and_reject():
    # Create two deliveries and return them
    p1 = {
        "rider_type": "NEW",
        "rider_name": "Bilal Rider",
        "rider_phone": "03451112233",
        "rider_pin": "2233",
        "customer_name": "Farhan Customer",
        "customer_phone": "03221234567",
        "customer_address": "DHA Phase 5, Lahore",
        "invoice_no": "INV-REC-001",
        "bill_amount": 3200.0
    }
    p2 = {
        "rider_type": "NEW",
        "rider_name": "Bilal Rider",
        "rider_phone": "03451112233",
        "rider_pin": "2233",
        "customer_name": "Sajid Customer",
        "customer_phone": "03239876543",
        "customer_address": "Faisal Town, Lahore",
        "invoice_no": "INV-REC-002",
        "bill_amount": 1800.0
    }
    d1 = client.post("/api/deliveries/dispatch", json=p1).json()["delivery"]
    d2 = client.post("/api/deliveries/dispatch", json=p2).json()["delivery"]

    client.post(f"/api/deliveries/{d1['id']}/return", json={"rider_pin": "2233"})
    client.post(f"/api/deliveries/{d2['id']}/return", json={"rider_pin": "2233"})

    # 1. Admin APPROVES d1
    appr_resp = client.post(f"/api/deliveries/{d1['id']}/reconcile", json={
        "action": "APPROVE",
        "approved_by": "Executive Admin"
    })
    assert appr_resp.status_code == 200
    appr_deliv = appr_resp.json()["delivery"]
    assert appr_deliv["approval_status"] == "APPROVED"
    assert appr_deliv["approved_by"] == "Executive Admin"
    assert appr_deliv["rejection_reason"] == ""

    # 2. Admin REJECTS d2 with reason
    rej_resp = client.post(f"/api/deliveries/{d2['id']}/reconcile", json={
        "action": "REJECT",
        "approved_by": "Executive Admin",
        "rejection_reason": "Cash short by Rs. 500, rider called for clarification"
    })
    assert rej_resp.status_code == 200
    rej_deliv = rej_resp.json()["delivery"]
    assert rej_deliv["approval_status"] == "REJECTED"
    assert rej_deliv["rejection_reason"] == "Cash short by Rs. 500, rider called for clarification"

    # 3. Check delivery stats KPI
    stats_resp = client.get("/api/deliveries/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["total_today"] >= 2
    assert stats["total_reconciled_cash"] >= 3200.0

def test_convert_temporary_rider_to_permanent():
    import time
    unique_phone = f"0319{int(time.time()*1000)%10000000:07d}"
    # Check rider exists
    reg = client.post("/api/deliveries/check-rider", json={"name": f"Rider {unique_phone[-4:]}", "phone": unique_phone}).json()
    staff_id = reg["staff_id"]
    assert reg["is_temp"] is True

    # Convert to permanent
    conv_resp = client.put(f"/api/staff/{staff_id}/convert-rider", json={
        "designation": "Senior Delivery Specialist",
        "monthly_salary": 38000.0,
        "shift_id": 1,
        "cnic": "35202-9988776-1",
        "address": "Model Town Link Road, Lahore"
    })
    assert conv_resp.status_code == 200
    updated_staff = conv_resp.json()["staff"]
    assert updated_staff["is_temp_delivery_staff"] == 0
    assert updated_staff["designation"] == "Senior Delivery Specialist"
    assert updated_staff["monthly_salary"] == 38000.0

def test_dispatch_existing_staff():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, pin FROM staff WHERE pin IS NOT NULL AND pin != '' LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if row:
        staff_id = row["id"]
        pin = str(row["pin"])
        payload = {
            "rider_type": "EXISTING",
            "staff_id": staff_id,
            "rider_pin": pin,
            "customer_name": "Test Existing Customer",
            "customer_phone": "03001112233",
            "customer_address": "Test Street 10",
            "bill_amount": 950.0,
            "payment_method": "Cash on Delivery"
        }
        resp = client.post("/api/deliveries/dispatch", json=payload)
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["delivery"]["staff_id"] == staff_id

