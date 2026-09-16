import unittest
from fastapi.testclient import TestClient
from main import app
import database

client = TestClient(app)

class TestPinOtpAttendance(unittest.TestCase):
    def setUp(self):
        database.init_db()

    def test_01_admin_settings_get_and_update(self):
        res = client.get('/api/settings')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('admin_whatsapp_number', data)

        new_phone = '0300-9876543'
        update_res = client.post('/api/settings', json={'admin_whatsapp_number': new_phone})
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(database.get_setting('admin_whatsapp_number'), new_phone)

        # Restore test default
        client.post('/api/settings', json={'admin_whatsapp_number': '0300-1234567'})

    def test_02_pin_otp_flow_in_and_out(self):
        staff_res = client.get('/api/staff')
        self.assertEqual(staff_res.status_code, 200)
        staff_list = staff_res.json()
        self.assertGreater(len(staff_list), 0)
        staff = staff_list[0]
        staff_id = staff['id']
        staff_pin = staff.get('pin') or '1001'

        # Wrong PIN
        fail_res = client.post('/api/attendance/request-pin-otp', json={
            'staff_id': staff_id,
            'pin': '9999'
        })
        self.assertEqual(fail_res.status_code, 400)

        # Correct PIN
        req_res = client.post('/api/attendance/request-pin-otp', json={
            'staff_id': staff_id,
            'pin': staff_pin
        })
        self.assertEqual(req_res.status_code, 200)
        req_data = req_res.json()
        self.assertTrue(req_data['success'])
        self.assertIn('action', req_data)
        self.assertIn('target_masked_phone', req_data)

        # Active OTPs
        active_otps_res = client.get('/api/attendance/active-otps')
        active_otps = active_otps_res.json()
        self.assertGreater(len(active_otps), 0)
        latest_otp = active_otps[0]['otp_code']

        # Wrong OTP
        wrong_verify_res = client.post('/api/attendance/verify-pin-otp', json={
            'staff_id': staff_id,
            'otp_code': '0000'
        })
        self.assertEqual(wrong_verify_res.status_code, 400)

        # Correct OTP
        ok_verify_res = client.post('/api/attendance/verify-pin-otp', json={
            'staff_id': staff_id,
            'otp_code': latest_otp
        })
        self.assertEqual(ok_verify_res.status_code, 200)
        verify_data = ok_verify_res.json()
        self.assertTrue(verify_data['success'])
        self.assertIn('punch_type', verify_data)

if __name__ == '__main__':
    unittest.main()
