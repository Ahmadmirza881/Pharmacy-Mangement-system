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
        self.assertIn('admin_master_pin', data)

        new_phone = '0300-9876543'
        new_master_pin = '7860'
        update_res = client.post('/api/settings', json={'admin_whatsapp_number': new_phone, 'admin_master_pin': new_master_pin})
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(database.get_setting('admin_whatsapp_number'), new_phone)
        self.assertEqual(database.get_admin_master_pin(), new_master_pin)

        # Restore test defaults
        client.post('/api/settings', json={'admin_whatsapp_number': '03166868169', 'admin_master_pin': '1370'})

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
        self.assertIn('token', req_data)
        self.assertIn('reveal_link', req_data)
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

    def test_03_explicit_user_action_choice(self):
        staff_res = client.get('/api/staff')
        staff = staff_res.json()[0]
        staff_id = staff['id']
        staff_pin = staff.get('pin') or '1001'

        # Explicitly choose IN
        res_in = client.post('/api/attendance/request-pin-otp', json={
            'staff_id': staff_id,
            'pin': staff_pin,
            'action': 'IN'
        })
        self.assertEqual(res_in.status_code, 200)
        self.assertEqual(res_in.json()['action'], 'IN')
        self.assertEqual(res_in.json()['target_type'], 'ADMIN')

        # Explicitly choose OUT
        res_out = client.post('/api/attendance/request-pin-otp', json={
            'staff_id': staff_id,
            'pin': staff_pin,
            'action': 'OUT'
        })
        self.assertEqual(res_out.status_code, 200)
        self.assertEqual(res_out.json()['action'], 'OUT')
        self.assertEqual(res_out.json()['target_type'], 'ADMIN')

    def test_04_master_pin_otp_reveal_flow(self):
        # Set Master PIN to 7860
        client.post('/api/settings', json={'admin_master_pin': '7860'})

        staff_res = client.get('/api/staff')
        staff = staff_res.json()[0]
        staff_id = staff['id']
        staff_pin = staff.get('pin') or '1001'

        # Request Check-IN OTP
        req_res = client.post('/api/attendance/request-pin-otp', json={
            'staff_id': staff_id,
            'pin': staff_pin,
            'action': 'IN'
        })
        self.assertEqual(req_res.status_code, 200)
        data = req_res.json()
        token = data['token']

        # GET /otp-verify page
        html_res = client.get(f'/otp-verify?token={token}')
        self.assertEqual(html_res.status_code, 200)
        self.assertIn('Mumtaz Pharmacy', html_res.text)

        # POST /api/otp/reveal with Wrong Master PIN
        wrong_pin_res = client.post('/api/otp/reveal', json={
            'token': token,
            'master_pin': '0000'
        })
        self.assertEqual(wrong_pin_res.status_code, 400)
        self.assertIn('Ghalat Admin Master PIN', wrong_pin_res.json()['detail'])

        # POST /api/otp/reveal with Correct Master PIN
        reveal_res = client.post('/api/otp/reveal', json={
            'token': token,
            'master_pin': '7860'
        })
        self.assertEqual(reveal_res.status_code, 200)
        reveal_data = reveal_res.json()
        self.assertTrue(reveal_data['success'])
        self.assertEqual(reveal_data['otp_code'], data['otp_code'])

        # Restore default Master PIN
        client.post('/api/settings', json={'admin_master_pin': '1370'})

if __name__ == '__main__':
    unittest.main()
