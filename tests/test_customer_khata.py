import unittest
from fastapi.testclient import TestClient
from main import app
import database

client = TestClient(app)

class TestCustomerKhataModule(unittest.TestCase):
    def setUp(self):
        database.init_db()

    def test_1_get_customers_and_kpis(self):
        res = client.get('/api/customers')
        self.assertEqual(res.status_code, 200)
        customers = res.json()
        self.assertGreaterEqual(len(customers), 4)

        haji = next((c for c in customers if c['name'] == 'Haji Abdul Rehman'), None)
        self.assertIsNotNone(haji)
        self.assertGreater(haji['credit_limit'], 0)
        self.assertIn(haji['wa_phone'], ['923001234567', '923166868169'])

        kpi_res = client.get('/api/customer-khata/kpis')
        self.assertEqual(kpi_res.status_code, 200)
        kpis = kpi_res.json()
        self.assertIn('total_outstanding', kpis)
        self.assertIn('this_week_credit', kpis)
        self.assertIn('this_week_recovered', kpis)
        self.assertIn('active_debtors_count', kpis)
        self.assertGreater(kpis['total_outstanding'], 0)

    def test_2_create_customer(self):
        payload = {
            'name': 'Dr. Farooq Sheikh',
            'phone': '0301-4455667',
            'address': 'Sheikh Clinic, Model Town C Block, Lahore',
            'credit_limit': 30000.0
        }
        res = client.post('/api/customers', json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        new_id = data['id']

        get_res = client.get(f'/api/customers/{new_id}/ledger')
        self.assertEqual(get_res.status_code, 200)
        ledger_data = get_res.json()
        self.assertEqual(ledger_data['customer']['name'], 'Dr. Farooq Sheikh')
        self.assertEqual(ledger_data['summary']['current_balance'], 0.0)

    def test_3_add_series_khata_and_balance_accumulation(self):
        c_res = client.post('/api/customers', json={
            'name': 'Testing Series Client',
            'phone': '0322-9988771',
            'address': 'Lahore',
            'credit_limit': 20000.0
        })
        cust_id = c_res.json()['id']

        p1 = client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-9001',
            'date': '2026-09-10',
            'item_description': 'Panadol 500mg, Brufen 400mg',
            'amount': 1500.0,
            'notes': 'First bill'
        })
        self.assertEqual(p1.status_code, 200)
        self.assertEqual(p1.json()['new_balance'], 1500.0)

        p2 = client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-9002',
            'date': '2026-09-11',
            'item_description': 'Augmentin 625mg, Surbex Z',
            'amount': 2300.0,
            'notes': 'Second bill'
        })
        self.assertEqual(p2.status_code, 200)
        self.assertEqual(p2.json()['new_balance'], 3800.0)

        ledger = client.get(f'/api/customers/{cust_id}/ledger').json()
        self.assertEqual(len(ledger['ledger']), 2)
        self.assertEqual(ledger['summary']['total_credit'], 3800.0)
        self.assertEqual(ledger['summary']['current_balance'], 3800.0)
        self.assertEqual(ledger['summary']['pending_count'], 2)

    def test_4_full_settlement_of_single_invoice(self):
        c_res = client.post('/api/customers', json={
            'name': 'Testing Settlement Client',
            'phone': '0333-1122339',
            'address': 'Lahore',
            'credit_limit': 10000.0
        })
        cust_id = c_res.json()['id']

        inv_res = client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-SETTLE-1',
            'date': '2026-09-10',
            'item_description': 'Disprin & Paracetamol',
            'amount': 750.0
        })
        entry_id = inv_res.json()['id']

        settle_res = client.post(f'/api/customer-khata/{entry_id}/settle', json={
            'settled_at': '2026-09-12',
            'payment_method': 'EasyPaisa',
            'notes': 'TID: 88721673'
        })
        self.assertEqual(settle_res.status_code, 200)
        s_data = settle_res.json()
        self.assertTrue(s_data['success'])
        self.assertEqual(s_data['updated_balance'], 0.0)

        ledger = client.get(f'/api/customers/{cust_id}/ledger').json()
        self.assertEqual(ledger['summary']['current_balance'], 0.0)
        self.assertEqual(ledger['summary']['total_settled'], 750.0)
        self.assertEqual(ledger['ledger'][0]['is_settled'], 1)
        self.assertEqual(ledger['ledger'][0]['payment_method'], 'EasyPaisa')

    def test_5_settle_all_balance(self):
        c_res = client.post('/api/customers', json={
            'name': 'Testing Settle All Client',
            'phone': '0345-7788990',
            'address': 'Lahore',
            'credit_limit': 15000.0
        })
        cust_id = c_res.json()['id']

        client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-SA-1',
            'date': '2026-09-08',
            'item_description': 'Medicine 1',
            'amount': 1000.0
        })
        client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-SA-2',
            'date': '2026-09-09',
            'item_description': 'Medicine 2',
            'amount': 2000.0
        })

        res = client.post(f'/api/customers/{cust_id}/settle-all', json={
            'settled_at': '2026-09-12',
            'payment_method': 'Cash at Counter Till',
            'notes': 'Full balance cleared'
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['settled_count'], 2)
        self.assertEqual(data['settled_amount'], 3000.0)

        ledger = client.get(f'/api/customers/{cust_id}/ledger').json()
        self.assertEqual(ledger['summary']['current_balance'], 0.0)
        self.assertEqual(ledger['summary']['pending_count'], 0)

    def test_6_weekly_report(self):
        res = client.get('/api/customer-khata/weekly-report')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('period', data)
        self.assertIn('summary', data)
        self.assertIn('debtors', data)

    def test_7_customer_update(self):
        c_res = client.post('/api/customers', json={
            'name': 'Testing Update Client',
            'phone': '0300-1112233',
            'address': 'Street 1, Lahore',
            'credit_limit': 10000.0
        })
        cust_id = c_res.json()['id']

        put_res = client.put(f'/api/customers/{cust_id}', json={
            'name': 'Testing Update Client (Renamed)',
            'phone': '0300-9990011',
            'address': 'Model Town C Block',
            'credit_limit': 20000.0
        })
        self.assertEqual(put_res.status_code, 200)
        self.assertTrue(put_res.json()['success'])

        ledger = client.get(f'/api/customers/{cust_id}/ledger').json()
        self.assertEqual(ledger['customer']['name'], 'Testing Update Client (Renamed)')
        self.assertEqual(ledger['customer']['phone'], '0300-9990011')
        self.assertEqual(ledger['customer']['address'], 'Model Town C Block')
        self.assertEqual(ledger['customer']['credit_limit'], 20000.0)

    def test_8_partial_payments(self):
        c_res = client.post('/api/customers', json={
            'name': 'Testing Partial Payment Client',
            'phone': '0311-2223344',
            'credit_limit': 15000.0
        })
        cust_id = c_res.json()['id']

        # Bill 1: 2000
        b1 = client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-PARTIAL-1',
            'date': '2026-09-13',
            'item_description': 'Medicine 1',
            'amount': 2000.0
        }).json()

        # Partial settle bill 1: pay 600 out of 2000
        p_res = client.post(f'/api/customer-khata/{b1["id"]}/settle', json={
            'amount': 600.0,
            'payment_method': 'Cash',
            'notes': 'Partial cash'
        })
        self.assertEqual(p_res.status_code, 200)
        p_data = p_res.json()
        self.assertTrue(p_data['success'])
        self.assertTrue(p_data['partial'])
        self.assertEqual(p_data['paid_amount'], 600.0)
        self.assertEqual(p_data['remaining_amount'], 1400.0)
        self.assertEqual(p_data['updated_balance'], 1400.0)

        # Bill 2: 1600 (Total due now = 1400 + 1600 = 3000)
        client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-PARTIAL-2',
            'date': '2026-09-13',
            'item_description': 'Medicine 2',
            'amount': 1600.0
        })

        # Partial settle customer balance: pay 2000 out of 3000
        sa_res = client.post(f'/api/customers/{cust_id}/settle-all', json={
            'amount': 2000.0,
            'payment_method': 'EasyPaisa',
            'notes': 'Customer paid 2000'
        })
        self.assertEqual(sa_res.status_code, 200)
        sa_data = sa_res.json()
        self.assertTrue(sa_data['success'])
        self.assertTrue(sa_data['partial'])
        self.assertEqual(sa_data['settled_amount'], 2000.0)
        self.assertEqual(sa_data['remaining_balance'], 1000.0)

        ledger = client.get(f'/api/customers/{cust_id}/ledger').json()
        self.assertEqual(ledger['summary']['current_balance'], 1000.0)
        self.assertEqual(ledger['summary']['total_credit'], 3600.0) # 2000 + 1600
        self.assertEqual(ledger['summary']['total_settled'], 2600.0) # 600 + 2000

    def test_9_staff_approval_workflow(self):
        # 1. Create a customer
        c_res = client.post('/api/customers', json={
            'name': 'Testing Approval Client',
            'phone': '0300-8889900',
            'credit_limit': 25000.0
        })
        cust_id = c_res.json()['id']

        # 2. Staff adds entry -> should be PENDING
        p_res = client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-STAFF-101',
            'date': '2026-09-17',
            'item_description': 'Amoxicillin 500mg, Flagyl 400mg',
            'amount': 1850.0,
            'added_by': 'Staff (Counter)',
            'approval_status': 'PENDING'
        })
        self.assertEqual(p_res.status_code, 200)
        entry_id = p_res.json()['id']

        # 3. Check in ledger that entry has PENDING status and added_by Staff
        ledger = client.get(f'/api/customers/{cust_id}/ledger').json()
        entry = next((e for e in ledger['ledger'] if e['id'] == entry_id), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry['approval_status'], 'PENDING')
        self.assertEqual(entry['added_by'], 'Staff (Counter)')

        # 4. Admin approves the entry with assigned staff
        appr_res = client.post(f'/api/customer-khata/{entry_id}/approve', json={
            'approved_by': 'Admin',
            'assigned_staff': 'Tariq Jameel'
        })
        self.assertEqual(appr_res.status_code, 200)
        appr_data = appr_res.json()
        self.assertTrue(appr_data['success'])
        self.assertEqual(appr_data['approval_status'], 'APPROVED')

        # 5. Verify ledger reflects APPROVED status and assigned staff
        ledger_after = client.get(f'/api/customers/{cust_id}/ledger').json()
        entry_after = next((e for e in ledger_after['ledger'] if e['id'] == entry_id), None)
        self.assertIsNotNone(entry_after)
        self.assertEqual(entry_after['approval_status'], 'APPROVED')
        self.assertEqual(entry_after['approved_by'], 'Admin')
        self.assertEqual(entry_after['added_by'], 'Tariq Jameel')

    def test_10_monthly_report(self):
        res = client.get('/api/customer-khata/monthly-report')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('period', data)
        self.assertIn('summary', data)
        self.assertIn('debtors', data)
        self.assertTrue('Month' in data['period'] or 'Sep' in data['period'] or '2026' in data['period'])

    def test_11_staff_request_and_batch_approval(self):
        # 1. Staff registers a new customer
        cust_res = client.post('/api/customers', json={
            'name': 'Staff Added Test Customer',
            'phone': '0300-9988776',
            'address': 'DHA Lahore',
            'credit_limit': 20000.0,
            'is_staff': True,
            'added_by': 'Counter Staff'
        })
        self.assertEqual(cust_res.status_code, 200)
        cust_data = cust_res.json()
        self.assertTrue(cust_data['success'])
        self.assertEqual(cust_data.get('status'), 'PENDING')
        cust_id = cust_data['id']

        # 2. Staff adds a credit purchase
        khata_res = client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-STAFF-1',
            'date': '2026-09-17',
            'item_description': 'Insulin & Syringes',
            'amount': 3500.0,
            'notes': 'Staff counter entry',
            'added_by': 'Counter Staff',
            'approval_status': 'PENDING'
        })
        self.assertEqual(khata_res.status_code, 200)
        khata_data = khata_res.json()
        self.assertTrue(khata_data['success'])
        entry_id = khata_data['id']

        # 3. Check pending requests endpoint
        pending_res = client.get('/api/admin/pending-requests')
        self.assertEqual(pending_res.status_code, 200)
        p_data = pending_res.json()
        self.assertTrue(p_data['success'])
        pending_reqs = p_data['requests']
        req_ids = [r['id'] for r in pending_reqs if r['customer_id'] == cust_id]
        self.assertGreaterEqual(len(req_ids), 2)

        # 4. Batch approve all staff requests for this customer
        batch_res = client.post('/api/admin/pending-requests/approve-all', json={
            'request_ids': req_ids,
            'approved_by': 'Admin'
        })
        self.assertEqual(batch_res.status_code, 200)
        b_data = batch_res.json()
        self.assertTrue(b_data['success'])
        self.assertEqual(b_data['approved_count'], len(req_ids))

        # Verify customer is now APPROVED and ledger has approved entry
        ledger = client.get(f'/api/customers/{cust_id}/ledger').json()
        self.assertEqual(ledger['customer']['approval_status'], 'APPROVED')
        self.assertEqual(ledger['ledger'][0]['approval_status'], 'APPROVED')

    def test_12_staff_settlement_approval_and_rejection(self):
        # Create customer directly as admin
        cust_res = client.post('/api/customers', json={
            'name': 'Staff Settle Test Customer',
            'phone': '0311-5544332',
            'address': 'Gulberg Lahore',
            'credit_limit': 10000.0
        })
        cust_id = cust_res.json()['id']

        # Add invoice
        inv_res = client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-SETTLE-ST',
            'date': '2026-09-17',
            'item_description': 'Panadol Box',
            'amount': 1200.0,
            'approval_status': 'APPROVED'
        })
        entry_id = inv_res.json()['id']

        # Staff records settlement -> queues for admin approval
        settle_res = client.post(f'/api/customer-khata/{entry_id}/settle', json={
            'amount': 1200.0,
            'settled_at': '2026-09-17',
            'payment_method': 'Cash',
            'notes': 'Paid at counter',
            'is_staff': True,
            'added_by': 'Counter Staff'
        })
        self.assertEqual(settle_res.status_code, 200)
        s_data = settle_res.json()
        self.assertTrue(s_data['pending_approval'])

        # Check that invoice is NOT settled yet
        ledger_before = client.get(f'/api/customers/{cust_id}/ledger').json()
        self.assertEqual(ledger_before['ledger'][0]['is_settled'], 0)

        # Find pending request
        p_res = client.get('/api/admin/pending-requests').json()
        matching_reqs = [r for r in p_res['requests'] if r['customer_id'] == cust_id and r['request_type'] == 'SETTLEMENT']
        self.assertEqual(len(matching_reqs), 1)
        req_id = matching_reqs[0]['id']

        # Admin approves the settlement
        appr_res = client.post(f'/api/admin/pending-requests/{req_id}/approve', json={
            'approved_by': 'Admin'
        })
        self.assertEqual(appr_res.status_code, 200)
        self.assertTrue(appr_res.json()['success'])

        # Now invoice MUST be settled
        ledger_after = client.get(f'/api/customers/{cust_id}/ledger').json()
        self.assertEqual(ledger_after['ledger'][0]['is_settled'], 1)
        self.assertEqual(ledger_after['summary']['current_balance'], 0.0)

    def test_13_reassign_customer_staff_and_bills(self):
        # 1. Create a customer with added_by = 'Former Staff'
        cust_res = client.post('/api/customers', json={
            'name': 'Reassign Staff Test Customer',
            'phone': '0300-8877665',
            'address': 'Johar Town Lahore',
            'credit_limit': 15000.0,
            'added_by': 'Former Staff'
        })
        self.assertEqual(cust_res.status_code, 200)
        cust_id = cust_res.json()['id']

        # 2. Add an unsettled bill
        bill_res = client.post('/api/customer-khata', json={
            'customer_id': cust_id,
            'invoice_no': 'INV-REASSIGN-1',
            'date': '2026-09-18',
            'item_description': 'Omega-3 Fish Oil',
            'amount': 2200.0,
            'added_by': 'Former Staff',
            'approval_status': 'APPROVED'
        })
        self.assertEqual(bill_res.status_code, 200)
        entry_id = bill_res.json()['id']

        # 3. Reassign customer responsibility to 'Tariq Jameel' with reassign_bills=True
        reassign_res = client.put(f'/api/customers/{cust_id}/reassign-staff', json={
            'new_staff': 'Tariq Jameel',
            'reassign_bills': True
        })
        self.assertEqual(reassign_res.status_code, 200)
        r_data = reassign_res.json()
        self.assertTrue(r_data['success'])
        self.assertEqual(r_data['new_staff'], 'Tariq Jameel')
        self.assertEqual(r_data['bills_updated'], 1)

        # 4. Verify customer ledger reflects new staff on customer and bill
        ledger = client.get(f'/api/customers/{cust_id}/ledger').json()
        self.assertEqual(ledger['customer']['added_by'], 'Tariq Jameel')
        self.assertEqual(ledger['ledger'][0]['added_by'], 'Tariq Jameel')

        # 5. Test single bill reassignment to 'Ahmed Khan'
        bill_reassign_res = client.put(f'/api/customer-khata/{entry_id}/reassign-staff', json={
            'new_staff': 'Ahmed Khan'
        })
        self.assertEqual(bill_reassign_res.status_code, 200)
        self.assertTrue(bill_reassign_res.json()['success'])

        ledger_after = client.get(f'/api/customers/{cust_id}/ledger').json()
        self.assertEqual(ledger_after['ledger'][0]['added_by'], 'Ahmed Khan')

    @classmethod
    def tearDownClass(cls):
        conn = database.get_db_connection()
        c = conn.cursor()
        test_names = [
            'Testing Series Client',
            'Testing Settlement Client',
            'Testing Settle All Client',
            'Testing Update Client',
            'Testing Update Client (Renamed)',
            'Testing Partial Payment Client',
            'Testing Approval Client',
            'Naveed Iqbal Test',
            'Staff Added Test Customer',
            'Staff Settle Test Customer',
            'Reassign Staff Test Customer'
        ]
        for name in test_names:
            c.execute('DELETE FROM staff_approval_requests WHERE customer_name = ?', (name,))
            c.execute('DELETE FROM customer_khata WHERE customer_id IN (SELECT id FROM customers WHERE name = ?)', (name,))
            c.execute('DELETE FROM customers WHERE name = ?', (name,))
        c.execute('DELETE FROM customer_khata WHERE customer_id IN (SELECT id FROM customers WHERE name = ? AND id != 5)', ('Dr. Farooq Sheikh',))
        c.execute('DELETE FROM customers WHERE name = ? AND id != 5', ('Dr. Farooq Sheikh',))
        conn.commit()
        conn.close()

if __name__ == '__main__':
    unittest.main()