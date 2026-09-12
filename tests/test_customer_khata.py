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
        self.assertEqual(haji['wa_phone'], '923001234567')

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
        self.assertIn('recent_transactions', data)

if __name__ == '__main__':
    unittest.main()