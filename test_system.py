import unittest
import json
import random
import os
from app import app
from models.database import init_db, seed_db, DB_PATH

class SmartAmbulanceSystemTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        if os.path.exists(DB_PATH):
            try:
                os.remove(DB_PATH)
            except Exception:
                pass
        init_db()
        seed_db()

    def test_01_health_and_home_route(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Smart Ambulance', response.data)

    def test_02_auth_register_and_login(self):
        # Register test user
        reg_payload = {
            "name": "Dr. Aarav Patel",
            "email": "aarav@test.org",
            "phone": "9988776655",
            "password": "securepassword",
            "role": "patient"
        }
        res = self.client.post('/api/register', json=reg_payload)
        self.assertIn(res.status_code, [201, 409])

        # Login test user
        login_payload = {"email": "aarav@test.org", "password": "securepassword"}
        res = self.client.post('/api/login', json=login_payload)
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])

        # Check current user session
        res = self.client.get('/api/current_user')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['authenticated'])

    def test_03_smart_ambulance_dispatch_booking(self):
        booking_payload = {
            "caller_name": "Testing Caller",
            "description": "Unconscious patient with cardiac arrest symptoms",
            "pickup_location": "Bharat Nagar Chowk",
            "emergency_type": "Cardiac",
            "severity": "Critical",
            "patients": "1 patient",
            "requested_at": "2026-09-22T18:30"
        }
        res = self.client.post('/api/book-ambulance', json=booking_payload)
        self.assertEqual(res.status_code, 201)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertIn('assigned_ambulance', data)
        self.assertIn('recommended_hospital', data)
        self.assertIn('requested_at', data['booking'])
        self.assertEqual(data['assigned_ambulance']['ambulance_number'], 'AMB-104')
        self.assertEqual(data['recommended_hospital']['name'], 'CityCare Emergency Hospital')

    def test_04_tracking_and_fleet_endpoints(self):
        # Fetch fleet
        res = self.client.get('/api/ambulances')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])

        # Simulate movement
        res = self.client.post('/api/ambulances/1/simulate-movement')
        self.assertEqual(res.status_code, 200)

        # Get tracking for booking #1
        res = self.client.get('/api/booking/1/tracking')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertIn('distance_km', data['tracking'])

    def test_05_hospitals_and_notifications(self):
        # Fetch hospitals
        res = self.client.get('/api/hospitals')
        self.assertEqual(res.status_code, 200)

        # Fetch notifications
        res = self.client.get('/api/notifications')
        self.assertEqual(res.status_code, 200)

        # Acknowledge notification
        res = self.client.post('/api/notifications/1/acknowledge')
        self.assertEqual(res.status_code, 200)

    def test_06_dashboard_stats(self):
        res = self.client.get('/api/dashboard/stats')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertIn('metrics', data)
        self.assertIn('emergency_queue', data)

    def test_07_booking_lifecycle_and_admin_crud(self):
        # 1. Update booking lifecycle status to COMPLETED
        res = self.client.post('/api/bookings/1/status', json={"status": "COMPLETED"})
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])

        # Verify assigned ambulance (ID 1) returned to AVAILABLE
        res = self.client.get('/api/ambulances')
        data = json.loads(res.data)
        amb1 = next(a for a in data['ambulances'] if a['id'] == 1)
        self.assertEqual(amb1['status'], 'AVAILABLE')

        # 2. Add new Ambulance via Admin API
        amb_code = f"AMB-{random.randint(10000, 99999)}"
        new_amb = {
            "ambulance_number": amb_code,
            "driver_name": "Test Driver",
            "driver_phone": "9999988888",
            "latitude": 30.9100,
            "longitude": 75.8500,
            "ambulance_type": "Cardiac ALS",
            "equipment": "Defibrillator · Oxygen"
        }
        res = self.client.post('/api/ambulances', json=new_amb)
        self.assertEqual(res.status_code, 201)

        # 3. Update Hospital Bed Capacity via Admin API
        res = self.client.put('/api/hospitals/1', json={"available_beds": 25})
        self.assertEqual(res.status_code, 200)

        # 4. Add Traffic Area via Admin API
        traffic_payload = {
            "area_name": "Mall Road Flyover",
            "latitude": 30.8990,
            "longitude": 75.8490,
            "severity": "Heavy",
            "delay_minutes": 7,
            "alternative_route": "Bypass via Fountain Chowk"
        }
        res = self.client.post('/api/traffic-areas', json=traffic_payload)
        self.assertEqual(res.status_code, 201)

        # 5. Delete endpoints test
        res = self.client.delete('/api/ambulances/6')
        self.assertEqual(res.status_code, 200)

        res = self.client.delete('/api/hospitals/3')
        self.assertEqual(res.status_code, 200)

        res = self.client.delete('/api/traffic-areas/1')
        self.assertEqual(res.status_code, 200)

if __name__ == '__main__':
    unittest.main()
