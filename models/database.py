import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'patient',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    # 2. Patients table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            blood_group TEXT,
            medical_condition TEXT,
            emergency_contact TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
    ''')

    # 3. Ambulances table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ambulances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ambulance_number TEXT UNIQUE NOT NULL,
            driver_name TEXT,
            driver_phone TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'AVAILABLE',
            current_location TEXT,
            ambulance_type TEXT DEFAULT 'Cardiac ALS',
            equipment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    # 4. Hospitals table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hospitals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            emergency_available INTEGER DEFAULT 1,
            available_beds INTEGER DEFAULT 10,
            total_beds INTEGER DEFAULT 50,
            status TEXT DEFAULT 'ACTIVE',
            icu_available INTEGER DEFAULT 1,
            cardiology_available INTEGER DEFAULT 1,
            trauma_available INTEGER DEFAULT 1
        );
    ''')

    # 5. Bookings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_code TEXT UNIQUE NOT NULL,
            patient_id INTEGER,
            ambulance_id INTEGER,
            hospital_id INTEGER,
            caller_name TEXT NOT NULL,
            pickup_location TEXT NOT NULL,
            pickup_lat REAL NOT NULL,
            pickup_lon REAL NOT NULL,
            destination TEXT,
            emergency_type TEXT NOT NULL,
            priority TEXT NOT NULL,
            priority_score INTEGER DEFAULT 50,
            booking_status TEXT NOT NULL DEFAULT 'ASSIGNED',
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients (id),
            FOREIGN KEY (ambulance_id) REFERENCES ambulances (id),
            FOREIGN KEY (hospital_id) REFERENCES hospitals (id)
        );
    ''')

    # 6. Traffic Areas table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS traffic_areas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            area_name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            severity TEXT NOT NULL DEFAULT 'Moderate',
            delay_minutes INTEGER DEFAULT 5,
            alternative_route TEXT
        );
    ''')

    # 7. Notifications table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            hospital_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            notification_type TEXT DEFAULT 'DISPATCH_ALERT',
            status TEXT NOT NULL DEFAULT 'UNREAD',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings (id) ON DELETE CASCADE,
            FOREIGN KEY (hospital_id) REFERENCES hospitals (id) ON DELETE CASCADE
        );
    ''')

    # 8. Ambulance Tracking table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ambulance_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ambulance_id INTEGER NOT NULL,
            booking_id INTEGER,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            status TEXT DEFAULT 'ON_THE_WAY',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ambulance_id) REFERENCES ambulances (id) ON DELETE CASCADE,
            FOREIGN KEY (booking_id) REFERENCES bookings (id) ON DELETE CASCADE
        );
    ''')

    # Schema migrations for existing databases
    def add_column_if_missing(table_name, column_name, column_def=""):
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row['name'] for row in cursor.fetchall()]
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}".strip())

    add_column_if_missing('bookings', 'assigned_at', 'TIMESTAMP')
    add_column_if_missing('bookings', 'completed_at', 'TIMESTAMP')
    add_column_if_missing('bookings', 'requested_at', "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    add_column_if_missing('ambulances', 'created_at', 'TIMESTAMP')
    add_column_if_missing('hospitals', 'status', "TEXT DEFAULT 'ACTIVE'")
    add_column_if_missing('notifications', 'notification_type', "TEXT DEFAULT 'DISPATCH_ALERT'")
    add_column_if_missing('ambulance_tracking', 'booking_id', 'INTEGER')
    add_column_if_missing('ambulance_tracking', 'status', "TEXT DEFAULT 'ON_THE_WAY'")

    conn.commit()
    conn.close()

def seed_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Seed Users
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.executemany('''
            INSERT INTO users (name, email, phone, password, role)
            VALUES (?, ?, ?, ?, ?)
        ''', [
            ('Admin Operator', 'operator@smartdispatch.org', '9876543210', generate_password_hash('admin123'), 'operator'),
            ('CityCare Hospital', 'citycare@hospital.org', '9876543211', generate_password_hash('hospital123'), 'hospital'),
            ('Priya Sharma', 'priya@gmail.com', '9876543212', generate_password_hash('patient123'), 'patient')
        ])

        # Seed Patient record for Priya Sharma (user_id = 3)
        cursor.execute('''
            INSERT INTO patients (user_id, name, age, gender, blood_group, medical_condition, emergency_contact)
            VALUES (3, 'Priya Sharma', 34, 'Female', 'O+', 'Hypertension', '9876543212')
        ''')

    # Seed Ambulances
    cursor.execute("SELECT COUNT(*) FROM ambulances")
    if cursor.fetchone()[0] == 0:
        cursor.executemany('''
            INSERT INTO ambulances (ambulance_number, driver_name, driver_phone, latitude, longitude, status, current_location, ambulance_type, equipment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', [
            ('AMB-104', 'Rajesh Kumar', '9812345601', 30.9010, 75.8420, 'AVAILABLE', 'Bharat Nagar Base', 'Cardiac ALS', 'Defibrillator · Oxygen · ECG Monitor'),
            ('AMB-108', 'Suresh Singh', '9812345602', 30.9150, 75.8550, 'AVAILABLE', 'GT Road Base', 'Trauma ALS', 'Ventilator · Trauma Kit · Oxygen'),
            ('AMB-101', 'Amit Sharma', '9812345603', 30.8950, 75.8300, 'ON_THE_WAY', 'Ring Road Sector 4', 'Cardiac ALS', 'Defibrillator · Oxygen'),
            ('AMB-107', 'Vikas Verma', '9812345604', 30.8850, 75.8200, 'ON_THE_WAY', 'Ferozepur Road', 'Advanced BLS', 'Oxygen · Splints · First Aid'),
            ('AMB-103', 'Gurpreet Singh', '9812345605', 30.9100, 75.8600, 'AVAILABLE', 'CityCare Base', 'General EMS', 'Oxygen · Patient Monitor'),
            ('AMB-110', 'Deepak Gill', '9812345606', 30.9200, 75.8700, 'MAINTENANCE', 'Central Service Workshop', 'Neonatal ALS', 'Ventilator · Incubator · ICU Kit')
        ])

    # Seed Hospitals
    cursor.execute("SELECT COUNT(*) FROM hospitals")
    if cursor.fetchone()[0] == 0:
        cursor.executemany('''
            INSERT INTO hospitals (name, address, latitude, longitude, emergency_available, available_beds, total_beds, icu_available, cardiology_available, trauma_available)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', [
            ('CityCare Emergency Hospital', 'South District, Mall Road, Ludhiana', 30.8980, 75.8480, 1, 18, 42, 1, 1, 1),
            ('District General Hospital', 'Central District, Civil Lines, Ludhiana', 30.9080, 75.8350, 1, 6, 60, 0, 1, 1),
            ('Northside Medical Centre', 'North District, GT Road, Ludhiana', 30.9250, 75.8650, 1, 12, 28, 1, 0, 1)
        ])

    # Seed Traffic Areas
    cursor.execute("SELECT COUNT(*) FROM traffic_areas")
    if cursor.fetchone()[0] == 0:
        cursor.executemany('''
            INSERT INTO traffic_areas (area_name, latitude, longitude, severity, delay_minutes, alternative_route)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', [
            ('Bharat Nagar Chowk', 30.9022, 75.8458, 'Heavy', 8, 'Via Link Road & Pakhowal Road Bypass'),
            ('Ring Road Crossing', 30.8940, 75.8320, 'Moderate', 4, 'Via Model Town Main Boulevard'),
            ('GT Road Flyover', 30.9180, 75.8580, 'Heavy', 6, 'Via Old City Inner Ring')
        ])

    # Seed Demo Bookings
    cursor.execute("SELECT COUNT(*) FROM bookings")
    if cursor.fetchone()[0] == 0:
        cursor.executemany('''
            INSERT INTO bookings (booking_code, patient_id, ambulance_id, hospital_id, caller_name, pickup_location, pickup_lat, pickup_lon, destination, emergency_type, priority, priority_score, booking_status, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', [
            ('REQ-2410', 1, 1, 1, 'Priya Sharma', 'Bharat Nagar Chowk', 30.9020, 75.8450, 'CityCare Emergency Hospital', 'Cardiac', 'Critical', 92, 'ASSIGNED', 'Patient experiencing severe chest pain and breathlessness.'),
            ('REQ-2408', 1, 2, 2, 'Ramesh Kumar', 'GT Road Flyover', 30.9160, 75.8560, 'District General Hospital', 'Accident', 'High', 78, 'ON_THE_WAY', 'Motorcycle collision with trauma injury.'),
            ('REQ-2407', 1, 3, 1, 'Anita Roy', 'Model Town', 30.8910, 75.8380, 'CityCare Emergency Hospital', 'Breathing Problem', 'Medium', 58, 'ARRIVED', 'Asthma exacerbation, conscious patient.')
        ])

        # Seed Notifications for Hospital 1
        cursor.executemany('''
            INSERT INTO notifications (booking_id, hospital_id, message, status)
            VALUES (?, ?, ?, ?)
        ''', [
            (1, 1, 'INCOMING EMERGENCY: REQ-2410 (Cardiac / Critical). Ambulance AMB-104 dispatched. ETA: 9 min.', 'UNREAD'),
            (3, 1, 'PATIENT ARRIVING: REQ-2407 (Breathing Problem / Medium). Ambulance AMB-101 arrived.', 'ACKNOWLEDGED')
        ])

    # Seed cases are historical examples, not live incidents on the operations board.
    cursor.execute('''
        UPDATE bookings
        SET booking_status = 'COMPLETED', completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
        WHERE booking_code IN ('REQ-2410', 'REQ-2408', 'REQ-2407')
    ''')
    cursor.execute('''
        UPDATE ambulances
        SET status = 'AVAILABLE', current_location = 'Base Station'
        WHERE ambulance_number IN ('AMB-104', 'AMB-108', 'AMB-101')
          AND status IN ('ASSIGNED', 'ON_THE_WAY', 'ARRIVED')
    ''')

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    seed_db()
    print("Database initialized and seeded successfully.")
