from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import random
import time
from models.database import get_db_connection
from utils.dispatch_algorithm import (
    haversine_distance,
    check_traffic_penalty,
    calculate_priority_score,
    find_best_ambulance,
    find_nearest_hospital
)

api_bp = Blueprint('api', __name__, url_prefix='/api')

VALID_AMBULANCE_STATUSES = {'AVAILABLE', 'ASSIGNED', 'ON_THE_WAY', 'ARRIVED', 'MAINTENANCE', 'OFFLINE'}
VALID_BOOKING_STATUSES = {'ASSIGNED', 'ON_THE_WAY', 'ARRIVED', 'COMPLETED', 'CANCELLED'}

def current_patient_id(cursor):
    """Return the signed-in patient's profile id, or None for guest intake."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    cursor.execute("SELECT id FROM patients WHERE user_id = ?", (user_id,))
    patient = cursor.fetchone()
    return patient['id'] if patient else None

def is_operator():
    return session.get('user_role') in {'operator', 'hospital'}

def not_found(message):
    return jsonify({"success": False, "message": message}), 404
def management_access_denied():
    if session.get('user_id') and not is_operator():
        return jsonify({"success": False, "message": "Operator access is required for this action."}), 403
    return None

# ==========================================
# 1. AUTHENTICATION & USER MANAGEMENT
# ==========================================

@api_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    phone = data.get('phone', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', 'patient').strip().lower()

    if not name or not email or not password:
        return jsonify({"success": False, "message": "Name, email, and password are required fields."}), 400
    if len(name) < 2 or '@' not in email or len(password) < 6:
        return jsonify({"success": False, "message": "Enter a valid name, email, and password of at least 6 characters."}), 400

    if role not in ['patient', 'hospital', 'operator']:
        role = 'patient'

    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if email already exists
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"success": False, "message": "An account with this email already exists."}), 409

    hashed_pw = generate_password_hash(password)
    cursor.execute('''
        INSERT INTO users (name, email, phone, password, role)
        VALUES (?, ?, ?, ?, ?)
    ''', (name, email, phone, hashed_pw, role))
    user_id = cursor.lastrowid

    # If patient, create patient profile
    if role == 'patient':
        age = data.get('age', 30)
        gender = data.get('gender', 'Unspecified')
        blood_group = data.get('blood_group', 'O+')
        medical_condition = data.get('medical_condition', 'None')
        emergency_contact = data.get('emergency_contact', phone)
        cursor.execute('''
            INSERT INTO patients (user_id, name, age, gender, blood_group, medical_condition, emergency_contact)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, name, age, gender, blood_group, medical_condition, emergency_contact))

    conn.commit()
    conn.close()

    session['user_id'] = user_id
    session['user_name'] = name
    session['user_role'] = role

    return jsonify({
        "success": True,
        "message": "User registered successfully!",
        "user": {"id": user_id, "name": name, "email": email, "role": role}
    }), 201

@api_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    conn.close()

    if not user or not check_password_hash(user['password'], password):
        return jsonify({"success": False, "message": "Invalid email or password."}), 401

    session['user_id'] = user['id']
    session['user_name'] = user['name']
    session['user_role'] = user['role']

    return jsonify({
        "success": True,
        "message": f"Welcome back, {user['name']}!",
        "user": {
            "id": user['id'],
            "name": user['name'],
            "email": user['email'],
            "role": user['role']
        }
    })

@api_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully."})

@api_bp.route('/current_user', methods=['GET'])
def current_user():
    if 'user_id' in session:
        return jsonify({
            "authenticated": True,
            "user": {
                "id": session['user_id'],
                "name": session.get('user_name', 'Operator'),
                "role": session.get('user_role', 'operator')
            }
        })
    return jsonify({"authenticated": False, "user": None})

# ==========================================
# 2. EMERGENCY BOOKING & DISPATCH API
# ==========================================

# Known Ludhiana landmarks lat/lon lookup table
LOCATION_COORDS = {
    'bharat nagar chowk': (30.9020, 75.8450),
    'gt road': (30.9160, 75.8560),
    'model town': (30.8910, 75.8380),
    'civil lines': (30.9080, 75.8350),
    'ferozepur road': (30.8850, 75.8200),
    'ring road': (30.8950, 75.8300),
    'mall road': (30.8980, 75.8480),
    'haibowal': (30.9120, 75.8250),
    'sarabha nagar': (30.8880, 75.8150),
    'clock tower': (30.9110, 75.8510)
}

def get_coordinates_for_location(loc_name):
    loc_clean = loc_name.lower().strip()
    for key, coords in LOCATION_COORDS.items():
        if key in loc_clean:
            return coords
    # Default fallback near Ludhiana center if location is unknown
    return (30.9020, 75.8450)

@api_bp.route('/book-ambulance', methods=['POST'])
@api_bp.route('/emergency/create', methods=['POST'])
def book_ambulance():
    data = request.get_json() or {}
    caller_name = data.get('caller_name', session.get('user_name', '')).strip()
    description = data.get('description', '').strip()
    pickup_location = data.get('pickup_location', '').strip()
    emergency_type = data.get('emergency_type', '').strip()
    severity = data.get('severity', '').strip().title()
    patient_count = data.get('patients', '1 patient').strip()
    requested_at_raw = (data.get('requested_at') or data.get('date_time') or data.get('datetime') or '').strip()

    if not caller_name or not pickup_location or not emergency_type or not description:
        return jsonify({"success": False, "message": "Caller name, description, pickup location, and emergency type are required."}), 400
    if severity not in {'Critical', 'High', 'Medium', 'Low'}:
        return jsonify({"success": False, "message": "Please select a valid emergency severity."}), 400

    try:
        if requested_at_raw:
            requested_at = datetime.fromisoformat(requested_at_raw.replace('Z', '+00:00'))
            requested_at_value = requested_at.strftime('%Y-%m-%d %H:%M:%S')
        else:
            requested_at_value = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        requested_at_value = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1. Resolve coordinates for pickup location
    pickup_lat, pickup_lon = get_coordinates_for_location(pickup_location)

    # 2. Calculate priority score and extract symptoms
    priority_score, symptoms = calculate_priority_score(emergency_type, severity, description)

    # 3. Execute Smart Ambulance Dispatch Algorithm
    best_ambulance, alternatives, traffic_info = find_best_ambulance(pickup_lat, pickup_lon, emergency_type, severity, description)

    if not best_ambulance:
        return jsonify({
            "success": False,
            "message": "No available ambulances found in the network right now."
        }), 404

    # 4. Execute Nearest Hospital Selection Algorithm
    best_hospital, alt_hospitals = find_nearest_hospital(pickup_lat, pickup_lon, emergency_type)

    if not best_hospital:
        return jsonify({"success": False, "message": "No emergency hospital is currently available. Please try again shortly."}), 503

    dest_name = best_hospital['name']
    hospital_id = best_hospital['id']

    # 5. Generate unique booking code
    booking_code = f"REQ-{random.randint(1000, 9999)}"

    # 6. Store Booking in SQLite
    conn = get_db_connection()
    cursor = conn.cursor()
    patient_id = current_patient_id(cursor)

    for _ in range(5):
        cursor.execute("SELECT 1 FROM bookings WHERE booking_code = ?", (booking_code,))
        if not cursor.fetchone():
            break
        booking_code = f"REQ-{random.randint(1000, 9999)}"

    cursor.execute('''
        INSERT INTO bookings (
            booking_code, patient_id, ambulance_id, hospital_id, caller_name,
            pickup_location, pickup_lat, pickup_lon, destination, emergency_type,
            priority, priority_score, booking_status, description, requested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        booking_code, 1, best_ambulance['id'], hospital_id, caller_name,
        pickup_location, pickup_lat, pickup_lon, dest_name, emergency_type,
        severity, priority_score, 'ASSIGNED', description, requested_at_value
    ))
    booking_id = cursor.lastrowid

    # 7. Update Ambulance status in SQLite
    cursor.execute('''
        UPDATE ambulances
        SET status = 'ASSIGNED', current_location = ?
        WHERE id = ?
    ''', (f"Assigned to {booking_code} ({pickup_location})", best_ambulance['id']))

    # 8. Store Hospital Notification in SQLite
    notif_msg = (
        f"INCOMING EMERGENCY: {booking_code} ({emergency_type} / {severity}). "
        f"Ambulance {best_ambulance['ambulance_number']} assigned. "
        f"ETA: {best_ambulance['eta_minutes']} min. Patient count: {patient_count}."
    )
    cursor.execute('''
        INSERT INTO notifications (booking_id, hospital_id, message, status)
        VALUES (?, ?, ?, ?)
    ''', (booking_id, hospital_id, notif_msg, 'UNREAD'))

    # 9. Store Initial Ambulance Tracking Point
    cursor.execute('''
        INSERT INTO ambulance_tracking (ambulance_id, latitude, longitude)
        VALUES (?, ?, ?)
    ''', (best_ambulance['id'], best_ambulance['latitude'], best_ambulance['longitude']))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": "Ambulance dispatched successfully!",
        "booking": {
            "id": booking_id,
            "booking_code": booking_code,
            "caller_name": caller_name,
            "emergency_type": emergency_type,
            "severity": severity,
            "priority_score": priority_score,
            "symptoms": symptoms,
            "patient_count": patient_count,
            "pickup_location": pickup_location,
            "requested_at": requested_at_value
        },
        "assigned_ambulance": best_ambulance,
        "alternative_ambulances": alternatives,
        "traffic_info": traffic_info,
        "recommended_hospital": best_hospital,
        "alternative_hospitals": alt_hospitals
    }), 201

# ==========================================
# 3. AMBULANCE & FLEET MANAGEMENT API
# ==========================================

@api_bp.route('/ambulances', methods=['GET'])
def get_ambulances():
    status_filter = request.args.get('status', 'all')
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
        SELECT a.*, b.booking_code, b.caller_name AS assigned_patient,
               b.pickup_lat AS assigned_pickup_lat, b.pickup_lon AS assigned_pickup_lon
        FROM ambulances a
        LEFT JOIN bookings b ON b.id = (
            SELECT latest.id FROM bookings latest
            WHERE latest.ambulance_id = a.id
              AND latest.booking_status IN ('ASSIGNED', 'ON_THE_WAY', 'ARRIVED')
            ORDER BY latest.id DESC LIMIT 1
        )
    '''
    if status_filter == 'available':
        cursor.execute(query + " WHERE a.status = 'AVAILABLE' ORDER BY a.id ASC")
    elif status_filter == 'route':
        cursor.execute(query + " WHERE a.status IN ('ASSIGNED', 'ON_THE_WAY') ORDER BY a.id ASC")
    elif status_filter == 'critical':
        cursor.execute(query + " WHERE a.ambulance_type LIKE '%ALS%' ORDER BY a.id ASC")
    else:
        cursor.execute(query + " ORDER BY a.id ASC")

    rows = cursor.fetchall()
    conn.close()

    ambulances = []
    for row in rows:
        eta_minutes = None
        if row['assigned_pickup_lat'] is not None and row['status'] in {'ASSIGNED', 'ON_THE_WAY', 'ARRIVED'}:
            distance = haversine_distance(row['latitude'], row['longitude'], row['assigned_pickup_lat'], row['assigned_pickup_lon'])
            eta_minutes = max(2, round((distance / 35.0) * 60.0))
        ambulances.append({
            "id": row['id'],
            "ambulance_number": row['ambulance_number'],
            "driver_name": row['driver_name'],
            "driver_phone": row['driver_phone'],
            "latitude": row['latitude'],
            "longitude": row['longitude'],
            "status": row['status'],
            "current_location": row['current_location'],
            "type": row['ambulance_type'],
            "equipment": row['equipment'].split(' · ') if row['equipment'] else [],
            "assigned_patient": row['assigned_patient'],
            "booking_code": row['booking_code'],
            "eta_minutes": eta_minutes
        })

    return jsonify({"success": True, "ambulances": ambulances})

@api_bp.route('/ambulances/<int:amb_id>/status', methods=['PUT', 'POST'])
def update_ambulance_status(amb_id):
    data = request.get_json() or {}
    denied = management_access_denied()
    if denied:
        return denied
    new_status = data.get('status', 'AVAILABLE').upper()
    if new_status not in VALID_AMBULANCE_STATUSES:
        return jsonify({"success": False, "message": "Invalid ambulance status."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE ambulances SET status = ? WHERE id = ?", (new_status, amb_id))
    if cursor.rowcount == 0:
        conn.close()
        return not_found("Ambulance not found.")
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"Ambulance #{amb_id} status updated to {new_status}."})

@api_bp.route('/ambulances/<int:amb_id>/location', methods=['POST'])
def update_ambulance_location(amb_id):
    data = request.get_json() or {}
    lat = data.get('latitude')
    lon = data.get('longitude')
    loc_name = data.get('location_name', 'En Route')

    if lat is None or lon is None:
        return jsonify({"success": False, "message": "Latitude and longitude required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE ambulances SET latitude = ?, longitude = ?, current_location = ? WHERE id = ?", (lat, lon, loc_name, amb_id))
    cursor.execute("INSERT INTO ambulance_tracking (ambulance_id, latitude, longitude) VALUES (?, ?, ?)", (amb_id, lat, lon))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"Location updated for ambulance {amb_id}."})

@api_bp.route('/ambulances/<int:amb_id>/simulate-movement', methods=['POST'])
def simulate_ambulance_movement(amb_id):
    """Move an ambulance one deterministic step toward its active pickup location."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT a.*, b.id AS booking_id, b.booking_code, b.pickup_location,
               b.pickup_lat, b.pickup_lon, b.booking_status
        FROM ambulances a
        LEFT JOIN bookings b ON b.id = (
            SELECT latest.id FROM bookings latest
            WHERE latest.ambulance_id = a.id
              AND latest.booking_status IN ('ASSIGNED', 'ON_THE_WAY', 'ARRIVED')
            ORDER BY latest.id DESC LIMIT 1
        )
        WHERE a.id = ?
    ''', (amb_id,))
    amb = cursor.fetchone()
    if not amb:
        conn.close()
        return jsonify({"success": False, "message": "Ambulance not found."}), 404

    if amb['pickup_lat'] is None or amb['pickup_lon'] is None:
        conn.close()
        return jsonify({
            "success": True,
            "moved": False,
            "ambulance_id": amb_id,
            "status": amb['status'],
            "message": "This ambulance has no active pickup route to simulate.",
            "new_position": {"latitude": amb['latitude'], "longitude": amb['longitude']}
        })

    remaining_distance = haversine_distance(amb['latitude'], amb['longitude'], amb['pickup_lat'], amb['pickup_lon'])
    step_ratio = 0.35
    new_lat = amb['latitude'] + (amb['pickup_lat'] - amb['latitude']) * step_ratio
    new_lon = amb['longitude'] + (amb['pickup_lon'] - amb['longitude']) * step_ratio
    reached_pickup = remaining_distance <= 0.15
    if reached_pickup:
        new_lat, new_lon = amb['pickup_lat'], amb['pickup_lon']
    new_status = 'ARRIVED' if reached_pickup else 'ON_THE_WAY'
    location_name = f"At pickup: {amb['pickup_location']}" if reached_pickup else f"En route to {amb['pickup_location']}"

    cursor.execute("UPDATE ambulances SET latitude = ?, longitude = ?, status = ?, current_location = ? WHERE id = ?", (new_lat, new_lon, new_status, location_name, amb_id))
    cursor.execute("UPDATE bookings SET booking_status = ? WHERE id = ?", (new_status, amb['booking_id']))
    cursor.execute("INSERT INTO ambulance_tracking (ambulance_id, booking_id, latitude, longitude, status) VALUES (?, ?, ?, ?, ?)", (amb_id, amb['booking_id'], new_lat, new_lon, new_status))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "ambulance_id": amb_id,
        "booking_id": amb['booking_id'],
        "booking_code": amb['booking_code'],
        "status": new_status,
        "location": location_name,
        "remaining_distance_km": haversine_distance(new_lat, new_lon, amb['pickup_lat'], amb['pickup_lon']),
        "new_position": {"latitude": new_lat, "longitude": new_lon}
    })

# ==========================================
# 4. BOOKING & TRACKING API
# ==========================================

@api_bp.route('/bookings', methods=['GET'])
@api_bp.route('/emergencies', methods=['GET'])
def get_bookings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT b.*, a.ambulance_number, a.status as amb_status, h.name as hospital_name
        FROM bookings b
        LEFT JOIN ambulances a ON b.ambulance_id = a.id
        LEFT JOIN hospitals h ON b.hospital_id = h.id
        ORDER BY b.created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()

    bookings = []
    for r in rows:
        bookings.append({
            "id": r['id'],
            "booking_code": r['booking_code'],
            "caller_name": r['caller_name'],
            "pickup_location": r['pickup_location'],
            "destination": r['destination'],
            "emergency_type": r['emergency_type'],
            "priority": r['priority'],
            "priority_score": r['priority_score'],
            "booking_status": r['booking_status'],
            "ambulance_number": r['ambulance_number'] or "Unassigned",
            "hospital_name": r['hospital_name'] or "Not specified",
            "description": r['description'],
            "created_at": r['created_at']
        })

    return jsonify({"success": True, "bookings": bookings})

@api_bp.route('/booking/<int:booking_id>/tracking', methods=['GET'])
def get_booking_tracking(booking_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT b.*, a.ambulance_number, a.driver_name, a.driver_phone,
               a.latitude as amb_lat, a.longitude as amb_lon, a.status as amb_status,
               h.name as hosp_name, h.address as hosp_address, h.latitude as hosp_lat, h.longitude as hosp_lon
        FROM bookings b
        JOIN ambulances a ON b.ambulance_id = a.id
        LEFT JOIN hospitals h ON b.hospital_id = h.id
        WHERE b.id = ?
    ''', (booking_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "message": "Booking not found."}), 404

    # Calculate remaining distance and ETA
    dist_to_pickup = haversine_distance(row['amb_lat'], row['amb_lon'], row['pickup_lat'], row['pickup_lon'])
    eta_min = max(2, round((dist_to_pickup / 35.0) * 60.0))

    return jsonify({
        "success": True,
        "tracking": {
            "booking_id": row['id'],
            "booking_code": row['booking_code'],
            "status": row['booking_status'],
            "pickup_location": row['pickup_location'],
            "pickup_coords": {"latitude": row['pickup_lat'], "longitude": row['pickup_lon']},
            "destination": row['destination'],
            "hospital_coords": {"latitude": row['hosp_lat'], "longitude": row['hosp_lon']},
            "ambulance": {
                "id": row['ambulance_id'],
                "number": row['ambulance_number'],
                "driver_name": row['driver_name'],
                "driver_phone": row['driver_phone'],
                "status": row['amb_status'],
                "current_coords": {"latitude": row['amb_lat'], "longitude": row['amb_lon']}
            },
            "distance_km": dist_to_pickup,
            "eta_minutes": eta_min
        }
    })

# ==========================================
# 5. HOSPITALS & NOTIFICATIONS API
# ==========================================

@api_bp.route('/hospitals', methods=['GET'])
def get_hospitals():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM hospitals ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    hospitals = []
    for h in rows:
        avail_beds = h['available_beds']
        total_beds = h['total_beds']
        pct = round((avail_beds / total_beds) * 100) if total_beds > 0 else 0
        hospitals.append({
            "id": h['id'],
            "name": h['name'],
            "address": h['address'],
            "latitude": h['latitude'],
            "longitude": h['longitude'],
            "emergency_available": bool(h['emergency_available']),
            "status": h['status'] or 'ACTIVE',
            "available_beds": avail_beds,
            "total_beds": total_beds,
            "bed_percentage": pct,
            "icu_available": bool(h['icu_available']),
            "cardiology_available": bool(h['cardiology_available']),
            "trauma_available": bool(h['trauma_available'])
        })

    return jsonify({"success": True, "hospitals": hospitals})

@api_bp.route('/notifications', methods=['GET'])
def get_notifications():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT n.*, h.name as hospital_name
        FROM notifications n
        JOIN hospitals h ON n.hospital_id = h.id
        ORDER BY n.created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()

    notifications = []
    for r in rows:
        notifications.append({
            "id": r['id'],
            "booking_id": r['booking_id'],
            "hospital_id": r['hospital_id'],
            "hospital_name": r['hospital_name'],
            "message": r['message'],
            "status": r['status'],
            "created_at": r['created_at']
        })

    return jsonify({"success": True, "notifications": notifications})

@api_bp.route('/notifications/<int:notif_id>/acknowledge', methods=['POST'])
def acknowledge_notification(notif_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET status = 'ACKNOWLEDGED' WHERE id = ?", (notif_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Notification #{notif_id} acknowledged."})

# ==========================================
# 6. TRAFFIC AREAS & DASHBOARD STATS API
# ==========================================

@api_bp.route('/traffic-areas', methods=['GET'])
def get_traffic_areas():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM traffic_areas ORDER BY severity DESC")
    rows = cursor.fetchall()
    conn.close()

    areas = []
    for r in rows:
        areas.append({
            "id": r['id'],
            "area_name": r['area_name'],
            "latitude": r['latitude'],
            "longitude": r['longitude'],
            "severity": r['severity'],
            "delay_minutes": r['delay_minutes'],
            "alternative_route": r['alternative_route']
        })

    return jsonify({"success": True, "traffic_areas": areas})

@api_bp.route('/dashboard/stats', methods=['GET'])
@api_bp.route('/dashboard', methods=['GET'])
def dashboard_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    period_days = request.args.get('period', '7')
    period_days = int(period_days) if period_days in {'7', '30'} else 7

    # Total & Available Ambulances
    cursor.execute("SELECT COUNT(*) FROM ambulances")
    total_ambulances = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ambulances WHERE status = 'AVAILABLE'")
    available_ambulances = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ambulances WHERE status IN ('ASSIGNED', 'ON_THE_WAY')")
    on_route_ambulances = cursor.fetchone()[0]

    # Active emergencies
    cursor.execute("SELECT COUNT(*) FROM bookings WHERE booking_status IN ('ASSIGNED', 'ON_THE_WAY', 'ARRIVED')")
    active_emergencies = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM bookings WHERE priority = 'Critical' AND booking_status IN ('ASSIGNED', 'ON_THE_WAY', 'ARRIVED')")
    critical_cases = cursor.fetchone()[0]

    # Hospital stats
    cursor.execute("SELECT COUNT(*) FROM hospitals WHERE emergency_available = 1 AND status = 'ACTIVE'")
    available_hospitals = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM hospitals")
    total_hospitals = cursor.fetchone()[0]

    # Fetch latest active booking for hero dispatch snapshot
    cursor.execute('''
        SELECT b.*, a.ambulance_number, a.driver_name, a.driver_phone, a.latitude as amb_lat, a.longitude as amb_lon,
               h.name as hospital_name
        FROM bookings b
        LEFT JOIN ambulances a ON b.ambulance_id = a.id
        LEFT JOIN hospitals h ON b.hospital_id = h.id
        WHERE b.booking_status IN ('ASSIGNED', 'ON_THE_WAY', 'ARRIVED')
        ORDER BY b.id DESC
        LIMIT 1
    ''')
    active_row = cursor.fetchone()

    latest_active_booking = None
    if active_row:
        dist = haversine_distance(active_row['amb_lat'], active_row['amb_lon'], active_row['pickup_lat'], active_row['pickup_lon']) if active_row['amb_lat'] else 5.0
        eta = max(3, round((dist / 35.0) * 60.0))
        latest_active_booking = {
            "id": active_row['id'],
            "booking_code": active_row['booking_code'],
            "caller_name": active_row['caller_name'],
            "pickup_location": active_row['pickup_location'],
            "destination": active_row['hospital_name'] or active_row['destination'] or "District Hospital",
            "emergency_type": active_row['emergency_type'],
            "priority": active_row['priority'],
            "status": active_row['booking_status'],
            "ambulance_number": active_row['ambulance_number'] or "Assigned Unit",
            "driver_name": active_row['driver_name'] or "On-Duty Driver",
            "driver_phone": active_row['driver_phone'] or "Emergency Line",
            "hospital_name": active_row['hospital_name'] or "Receiving Hospital",
            "eta_minutes": eta,
            "distance_km": dist
        }

    # Active queue list
    cursor.execute('''
        SELECT b.id, b.booking_code, b.pickup_location, b.priority, b.emergency_type, b.booking_status,
               a.ambulance_number, a.latitude as amb_lat, a.longitude as amb_lon, b.pickup_lat, b.pickup_lon
        FROM bookings b
        LEFT JOIN ambulances a ON b.ambulance_id = a.id
        WHERE b.booking_status IN ('ASSIGNED', 'ON_THE_WAY', 'ARRIVED')
        ORDER BY b.id DESC
        LIMIT 6
    ''')
    queue_rows = cursor.fetchall()

    queue = []
    total_eta_sum = 0
    count_eta = 0
    for q in queue_rows:
        dist = haversine_distance(q['amb_lat'], q['amb_lon'], q['pickup_lat'], q['pickup_lon']) if q['amb_lat'] else 4.5
        eta = max(3, round((dist / 35.0) * 60.0))
        total_eta_sum += eta
        count_eta += 1
        queue.append({
            "id": q['id'],
            "booking_code": q['booking_code'],
            "location": q['pickup_location'],
            "severity": q['priority'],
            "type": q['emergency_type'],
            "status": q['booking_status'],
            "ambulance": q['ambulance_number'] or "Dispatch Unit",
            "eta_min": f"{eta} min"
        })

    avg_eta = round(total_eta_sum / count_eta) if count_eta > 0 else None

    # Analytics use the emergency's recorded request time, falling back to creation time.
    cursor.execute('''
        SELECT b.emergency_type, b.booking_status, b.priority,
               a.latitude AS amb_lat, a.longitude AS amb_lon,
               b.pickup_lat, b.pickup_lon
        FROM bookings b
        LEFT JOIN ambulances a ON b.ambulance_id = a.id
        WHERE datetime(COALESCE(b.requested_at, b.created_at)) >= datetime('now', ?)
    ''', (f'-{period_days} days',))
    analytics_rows = cursor.fetchall()
    emergency_types = []
    status_counts = {}
    priority_counts = {}
    analytics_eta_sum = 0
    analytics_eta_count = 0
    for row in analytics_rows:
        status_counts[row['booking_status']] = status_counts.get(row['booking_status'], 0) + 1
        priority_counts[row['priority']] = priority_counts.get(row['priority'], 0) + 1
        if row['booking_status'] in {'ASSIGNED', 'ON_THE_WAY', 'ARRIVED'}:
            dist = haversine_distance(row['amb_lat'], row['amb_lon'], row['pickup_lat'], row['pickup_lon']) if row['amb_lat'] else 4.5
            analytics_eta_sum += max(3, round((dist / 35.0) * 60.0))
            analytics_eta_count += 1

    cursor.execute('''
        SELECT emergency_type, COUNT(*) AS total
        FROM bookings
        WHERE datetime(COALESCE(requested_at, created_at)) >= datetime('now', ?)
        GROUP BY emergency_type ORDER BY total DESC
    ''', (f'-{period_days} days',))
    emergency_types = [{'type': row['emergency_type'], 'count': row['total']} for row in cursor.fetchall()]
    status_summary = [{'status': status, 'count': count} for status, count in status_counts.items()]
    priority_summary = [{'priority': priority, 'count': count} for priority, count in priority_counts.items()]
    analytics_total = len(analytics_rows)
    active_routes = status_counts.get('ASSIGNED', 0) + status_counts.get('ON_THE_WAY', 0)
    at_hospitals = status_counts.get('ARRIVED', 0)
    waiting_dispatch = status_counts.get('WAITING', 0) + status_counts.get('PENDING', 0)
    analytics_avg_eta = round(analytics_eta_sum / analytics_eta_count) if analytics_eta_count else None

    cursor.execute("SELECT id, ambulance_number, latitude, longitude, status FROM ambulances ORDER BY id ASC")
    fleet_map = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT id, name, latitude, longitude FROM hospitals WHERE status = 'ACTIVE'")
    hospital_map = [dict(row) for row in cursor.fetchall()]

    cursor.execute('''
        SELECT id, booking_code, pickup_location, pickup_lat, pickup_lon, priority, booking_status
        FROM bookings
        WHERE booking_status IN ('ASSIGNED', 'ON_THE_WAY', 'ARRIVED')
        ORDER BY id DESC
    ''')
    emergency_map = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT area_name, latitude, longitude, severity, delay_minutes FROM traffic_areas ORDER BY delay_minutes DESC")
    traffic_map = [dict(row) for row in cursor.fetchall()]
    utilization = round((on_route_ambulances / total_ambulances) * 100) if total_ambulances else 0

    conn.close()

    return jsonify({
        "success": True,
        "metrics": {
            "total_ambulances": total_ambulances,
            "available_ambulances": available_ambulances,
            "on_route_ambulances": on_route_ambulances,
            "active_emergencies": active_emergencies,
            "critical_cases": critical_cases,
            "available_hospitals": available_hospitals,
            "total_hospitals": total_hospitals,
            "average_eta_min": avg_eta
        },
        "latest_active_booking": latest_active_booking,
        "emergency_queue": queue,
        "map": {
            "ambulances": fleet_map,
            "hospitals": hospital_map,
            "emergencies": emergency_map,
            "traffic": traffic_map
        },
        "analytics": {
            "period_days": period_days,
            "emergency_types": emergency_types,
            "status_summary": status_summary,
            "priority_summary": priority_summary,
            "total_cases": analytics_total,
            "average_eta_min": analytics_avg_eta,
            "utilization_percent": utilization,
            "active_routes": active_routes,
            "at_hospitals": at_hospitals,
            "waiting_dispatch": waiting_dispatch,
            "completed_cases": status_counts.get('COMPLETED', 0)
        }
    })

# ==========================================
# 7. EXTENDED ADMIN & LIFECYCLE MANAGEMENT APIs
# ==========================================

@api_bp.route('/bookings/<int:booking_id>', methods=['GET'])
def get_single_booking(booking_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT b.*, a.ambulance_number, a.driver_name, a.driver_phone, a.latitude as amb_lat, a.longitude as amb_lon,
               h.name as hospital_name, h.address as hospital_address
        FROM bookings b
        LEFT JOIN ambulances a ON b.ambulance_id = a.id
        LEFT JOIN hospitals h ON b.hospital_id = h.id
        WHERE b.id = ?
    ''', (booking_id,))
    r = cursor.fetchone()
    conn.close()

    if not r:
        return jsonify({"success": False, "message": "Booking not found."}), 404

    return jsonify({
        "success": True,
        "booking": {
            "id": r['id'],
            "booking_code": r['booking_code'],
            "caller_name": r['caller_name'],
            "pickup_location": r['pickup_location'],
            "pickup_lat": r['pickup_lat'],
            "pickup_lon": r['pickup_lon'],
            "destination": r['destination'],
            "emergency_type": r['emergency_type'],
            "priority": r['priority'],
            "priority_score": r['priority_score'],
            "booking_status": r['booking_status'],
            "ambulance_id": r['ambulance_id'],
            "ambulance_number": r['ambulance_number'],
            "driver_name": r['driver_name'],
            "driver_phone": r['driver_phone'],
            "hospital_id": r['hospital_id'],
            "hospital_name": r['hospital_name'],
            "description": r['description'],
            "created_at": r['created_at'],
            "assigned_at": r['assigned_at'],
            "completed_at": r['completed_at']
        }
    })

@api_bp.route('/bookings/<int:booking_id>/status', methods=['PUT', 'POST'])
def update_booking_status(booking_id):
    data = request.get_json() or {}
    denied = management_access_denied()
    if denied:
        return denied
    new_status = data.get('status', '').upper()

    if new_status not in VALID_BOOKING_STATUSES:
        return jsonify({"success": False, "message": "Invalid status transition."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT ambulance_id FROM bookings WHERE id = ?", (booking_id,))
    booking = cursor.fetchone()
    if not booking:
        conn.close()
        return jsonify({"success": False, "message": "Booking not found."}), 404

    amb_id = booking['ambulance_id']

    if new_status == 'COMPLETED':
        cursor.execute('''
            UPDATE bookings
            SET booking_status = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_status, booking_id))
        
        # Release assigned ambulance back to AVAILABLE
        if amb_id:
            cursor.execute("UPDATE ambulances SET status = 'AVAILABLE', current_location = 'Base Station' WHERE id = ?", (amb_id,))
    elif new_status == 'CANCELLED':
        cursor.execute("UPDATE bookings SET booking_status = ? WHERE id = ?", (new_status, booking_id))
        if amb_id:
            cursor.execute("UPDATE ambulances SET status = 'AVAILABLE' WHERE id = ?", (amb_id,))
    else:
        cursor.execute("UPDATE bookings SET booking_status = ? WHERE id = ?", (new_status, booking_id))
        if amb_id:
            cursor.execute("UPDATE ambulances SET status = ? WHERE id = ?", (new_status, amb_id))

    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"Booking #{booking_id} status updated to {new_status}."})

@api_bp.route('/ambulances/available', methods=['GET'])
def get_available_ambulances():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ambulances WHERE status = 'AVAILABLE'")
    rows = cursor.fetchall()
    conn.close()
    return jsonify({"success": True, "ambulances": [dict(r) for r in rows]})

@api_bp.route('/ambulances', methods=['POST'])
def add_ambulance():
    data = request.get_json() or {}
    denied = management_access_denied()
    if denied:
        return denied
    amb_num = data.get('ambulance_number', '').strip().upper()
    driver_name = data.get('driver_name', 'Default Driver').strip()
    driver_phone = data.get('driver_phone', '9800000000').strip()
    lat = data.get('latitude', 30.9000)
    lon = data.get('longitude', 75.8500)
    amb_type = data.get('ambulance_type', 'Cardiac ALS').strip()
    equipment = data.get('equipment', 'Oxygen · First Aid').strip()
    curr_loc = data.get('current_location', 'Central Depot').strip()

    if not amb_num:
        return jsonify({"success": False, "message": "Ambulance number is required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO ambulances (ambulance_number, driver_name, driver_phone, latitude, longitude, status, current_location, ambulance_type, equipment)
            VALUES (?, ?, ?, ?, ?, 'AVAILABLE', ?, ?, ?)
        ''', (amb_num, driver_name, driver_phone, lat, lon, curr_loc, amb_type, equipment))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"Ambulance {amb_num} added successfully."}), 201
    except Exception as e:
        conn.close()
        return jsonify({"success": False, "message": f"Could not add ambulance: {e}"}), 400

@api_bp.route('/ambulances/<int:amb_id>', methods=['PUT'])
def edit_ambulance(amb_id):
    data = request.get_json() or {}
    denied = management_access_denied()
    if denied:
        return denied
    driver_name = data.get('driver_name')
    driver_phone = data.get('driver_phone')
    amb_type = data.get('ambulance_type')
    status = data.get('status')
    location = data.get('current_location')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM ambulances WHERE id = ?", (amb_id,))
    if not cursor.fetchone():
        conn.close()
        return not_found("Ambulance not found.")
    if status and status.upper() not in VALID_AMBULANCE_STATUSES:
        conn.close()
        return jsonify({"success": False, "message": "Invalid ambulance status."}), 400

    if driver_name: cursor.execute("UPDATE ambulances SET driver_name = ? WHERE id = ?", (driver_name, amb_id))
    if driver_phone: cursor.execute("UPDATE ambulances SET driver_phone = ? WHERE id = ?", (driver_phone, amb_id))
    if amb_type: cursor.execute("UPDATE ambulances SET ambulance_type = ? WHERE id = ?", (amb_type, amb_id))
    if status: cursor.execute("UPDATE ambulances SET status = ? WHERE id = ?", (status.upper(), amb_id))
    if location: cursor.execute("UPDATE ambulances SET current_location = ? WHERE id = ?", (location, amb_id))

    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Ambulance #{amb_id} updated."})

@api_bp.route('/hospitals', methods=['POST'])
def add_hospital():
    data = request.get_json() or {}
    denied = management_access_denied()
    if denied:
        return denied
    name = data.get('name', '').strip()
    address = data.get('address', '').strip()
    lat = data.get('latitude', 30.9000)
    lon = data.get('longitude', 75.8500)
    avail_beds = data.get('available_beds', 10)
    total_beds = data.get('total_beds', 40)

    if not name:
        return jsonify({"success": False, "message": "Hospital name is required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO hospitals (name, address, latitude, longitude, emergency_available, available_beds, total_beds)
        VALUES (?, ?, ?, ?, 1, ?, ?)
    ''', (name, address, lat, lon, avail_beds, total_beds))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Hospital '{name}' added successfully."}), 201

@api_bp.route('/hospitals/<int:hosp_id>', methods=['PUT'])
def edit_hospital(hosp_id):
    data = request.get_json() or {}
    denied = management_access_denied()
    if denied:
        return denied
    avail_beds = data.get('available_beds')
    emergency_available = data.get('emergency_available')
    status = data.get('status')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM hospitals WHERE id = ?", (hosp_id,))
    if not cursor.fetchone():
        conn.close()
        return not_found("Hospital not found.")

    if avail_beds is not None:
        cursor.execute("UPDATE hospitals SET available_beds = ? WHERE id = ?", (int(avail_beds), hosp_id))
    if emergency_available is not None:
        cursor.execute("UPDATE hospitals SET emergency_available = ? WHERE id = ?", (1 if emergency_available else 0, hosp_id))
    if status is not None:
        cursor.execute("UPDATE hospitals SET status = ? WHERE id = ?", (status, hosp_id))

    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Hospital #{hosp_id} updated successfully."})

@api_bp.route('/traffic-areas', methods=['POST'])
def add_traffic_area():
    denied = management_access_denied()
    if denied:
        return denied
    data = request.get_json() or {}
    area_name = data.get('area_name', '').strip()
    lat = data.get('latitude', 30.9000)
    lon = data.get('longitude', 75.8500)
    severity = data.get('severity', 'Moderate').strip()
    delay = data.get('delay_minutes', 5)
    alt_route = data.get('alternative_route', 'Bypass via ring road').strip()

    if not area_name or not alt_route or severity not in {'Low', 'Moderate', 'Heavy'}:
        return jsonify({"success": False, "message": "Area, severity, and alternative route are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO traffic_areas (area_name, latitude, longitude, severity, delay_minutes, alternative_route)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (area_name, lat, lon, severity, delay, alt_route))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Traffic area '{area_name}' added."}), 201

@api_bp.route('/ambulances/<int:amb_id>', methods=['DELETE'])
def delete_ambulance(amb_id):
    denied = management_access_denied()
    if denied:
        return denied
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ambulances WHERE id = ?", (amb_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Ambulance #{amb_id} deleted."})

@api_bp.route('/hospitals/<int:hosp_id>', methods=['DELETE'])
def delete_hospital(hosp_id):
    denied = management_access_denied()
    if denied:
        return denied
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM hospitals WHERE id = ?", (hosp_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Hospital #{hosp_id} deleted."})

@api_bp.route('/traffic-areas/<int:area_id>', methods=['DELETE'])
def delete_traffic_area(area_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM traffic_areas WHERE id = ?", (area_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Traffic area #{area_id} deleted."})

@api_bp.route('/notifications/<int:notif_id>/read', methods=['PUT', 'POST'])
def read_notification(notif_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET status = 'ACKNOWLEDGED' WHERE id = ?", (notif_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Notification #{notif_id} marked as read."})

