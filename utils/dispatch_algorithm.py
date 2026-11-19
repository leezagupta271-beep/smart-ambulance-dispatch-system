import math
from models.database import get_db_connection

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance in kilometers between two points
    on the earth (specified in decimal degrees) using Haversine formula.
    """
    R = 6371.0  # Earth radius in kilometers

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    distance = R * c
    return round(distance, 2)

def check_traffic_penalty(pickup_lat, pickup_lon):
    """
    Check if the pickup location or route is near known traffic-prone areas stored in SQLite.
    Returns (traffic_severity, total_delay_minutes, affected_area_name, alternative_route)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM traffic_areas")
    traffic_areas = cursor.fetchall()
    conn.close()

    max_delay = 0
    detected_severity = "Low"
    affected_area = None
    alt_route = None

    for area in traffic_areas:
        dist = haversine_distance(pickup_lat, pickup_lon, area['latitude'], area['longitude'])
        # If emergency location is within 3.5 km of a traffic bottleneck
        if dist <= 3.5:
            delay = area['delay_minutes']
            if delay > max_delay:
                max_delay = delay
                detected_severity = area['severity']
                affected_area = area['area_name']
                alt_route = area['alternative_route']

    return {
        "severity": detected_severity,
        "delay_minutes": max_delay,
        "affected_area": affected_area,
        "alternative_route": alt_route
    }

def calculate_priority_score(emergency_type, severity, description=""):
    """
    NLP & Rule-based Priority Score & Symptom Extractor.
    Returns (priority_score, symptoms_list)
    """
    symptoms_map = {
        'Cardiac': ['Chest pain', 'Shortness of breath', 'Profuse sweating', 'Radiation to left arm'],
        'Accident': ['Multiple trauma', 'Possible fracture', 'Severe bleeding', 'Scene hazard'],
        'Stroke': ['Facial numbness', 'Speech difficulty', 'Arm weakness', 'Sudden confusion'],
        'Breathing Problem': ['Severe hypoxia risk', 'Wheezing', 'Respiratory distress'],
        'Injury': ['Localized trauma', 'Loss of mobility', 'Acute pain'],
        'General': ['Acute illness', 'Pain reported', 'Urgent transport requested']
    }

    base_symptoms = symptoms_map.get(emergency_type, symptoms_map['General']).copy()
    
    # Analyze description keywords to refine symptoms & score
    desc_lower = (description or "").lower()
    keyword_bonus = 0
    
    if "unconscious" in desc_lower or "fainted" in desc_lower:
        base_symptoms.append("Unconsciousness reported")
        keyword_bonus += 8
    if "bleed" in desc_lower or "blood" in desc_lower:
        base_symptoms.append("Active hemorrhage")
        keyword_bonus += 6
    if "chest" in desc_lower or "cardiac" in desc_lower:
        keyword_bonus += 5
    if "choking" in desc_lower or "gasping" in desc_lower:
        base_symptoms.append("Severe airway compromise")
        keyword_bonus += 10

    if severity == 'Critical':
        base_score = 90
    elif severity == 'High':
        base_score = 75
    elif severity == 'Medium':
        base_score = 55
    else:
        base_score = 35

    final_score = min(100, max(10, base_score + keyword_bonus))
    return final_score, base_symptoms

def get_resource_requirements(emergency_type, description=""):
    """Translate an emergency into the capabilities needed for allocation."""
    requirements = {
        'Cardiac': {'ambulance': ['cardiac', 'defibrillator', 'ecg'], 'hospital': ['cardiology', 'icu']},
        'Stroke': {'ambulance': ['als', 'oxygen'], 'hospital': ['icu', 'cardiology']},
        'Accident': {'ambulance': ['trauma', 'oxygen', 'trauma kit'], 'hospital': ['trauma', 'icu']},
        'Breathing Problem': {'ambulance': ['oxygen', 'ventilator'], 'hospital': ['icu']},
        'Injury': {'ambulance': ['trauma', 'oxygen'], 'hospital': ['trauma']},
        'General': {'ambulance': ['oxygen'], 'hospital': []}
    }
    selected = requirements.get(emergency_type, requirements['General']).copy()
    text = (description or '').lower()
    if any(word in text for word in ['unconscious', 'gasping', 'critical']):
        selected['ambulance'] = list(dict.fromkeys(selected['ambulance'] + ['als', 'oxygen']))
        selected['hospital'] = list(dict.fromkeys(selected['hospital'] + ['icu']))
    return selected

def find_best_ambulance(pickup_lat, pickup_lon, emergency_type, priority, description=""):
    """
    Main Smart Ambulance Dispatch Algorithm:
    1. Retrieve available ambulances from SQLite database.
    2. Compute Haversine distance from ambulance to patient pickup location.
    3. Evaluate traffic-prone areas and calculate travel time (ETA).
    4. Match ambulance capabilities (Cardiac ALS vs Trauma ALS vs BLS) with patient emergency.
    5. Rank candidate ambulances and select the optimal match.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ambulances WHERE status = 'AVAILABLE' ORDER BY id ASC")
    available_ambulances = cursor.fetchall()
    
    conn.close()

    if not available_ambulances:
        return None, [], {"severity": "Low", "delay_minutes": 0}

    traffic_info = check_traffic_penalty(pickup_lat, pickup_lon)
    requirements = get_resource_requirements(emergency_type, description)

    ranked_candidates = []
    
    for amb in available_ambulances:
        amb_lat = amb['latitude']
        amb_lon = amb['longitude']
        amb_id = amb['id']
        amb_number = amb['ambulance_number']
        amb_type = amb['ambulance_type']
        equipment = amb['equipment']
        location_name = amb['current_location']
        
        # 1. Haversine distance in km
        dist_km = haversine_distance(amb_lat, amb_lon, pickup_lat, pickup_lon)
        
        # 2. Base travel time assuming average city speed of 35 km/h
        base_travel_minutes = (dist_km / 35.0) * 60.0
        
        # 3. Add traffic delay penalty
        total_eta_minutes = max(2, round(base_travel_minutes + traffic_info['delay_minutes']))
        
        # 4. Equipment and capability match score
        resource_text = f"{amb_type} {equipment or ''}".lower()
        matched_resources = [resource for resource in requirements['ambulance'] if resource in resource_text]
        missing_resources = [resource for resource in requirements['ambulance'] if resource not in resource_text]
        type_match_score = 0
        if emergency_type == 'Cardiac' and 'Cardiac' in amb_type:
            type_match_score += 25
        elif emergency_type == 'Accident' and 'Trauma' in amb_type:
            type_match_score += 25
        elif emergency_type == 'Stroke' and ('ALS' in amb_type or 'Cardiac' in amb_type):
            type_match_score += 20
        else:
            type_match_score += 10
        resource_factor = len(matched_resources) * 8 - len(missing_resources) * 4
            
        # 5. Composite Ranking Score breakdown
        distance_factor = max(0, round(40 - dist_km * 3, 1))
        traffic_factor = max(0, round(20 - traffic_info['delay_minutes'] * 2, 1))
        availability_factor = 25 if amb['status'] == 'AVAILABLE' else 10
        priority_weight = {'Critical': 1.25, 'High': 1.15, 'Medium': 1.05, 'Low': 1.0}.get(priority, 1.0)
        priority_factor = round(type_match_score * priority_weight, 1)

        ranking_score = distance_factor + traffic_factor + availability_factor + priority_factor + resource_factor

        selection_reason = (
            f"Nearest available {amb_type} unit ({dist_km} km away) with {total_eta_minutes} min ETA. "
            f"Resource match {len(matched_resources)}/{len(requirements['ambulance'])}; "
            f"equipped with {equipment or 'standard care kit'} for {emergency_type} emergency."
        )

        candidate = {
            "id": amb_id,
            "ambulance_number": amb_number,
            "driver_name": amb['driver_name'],
            "driver_phone": amb['driver_phone'],
            "type": amb_type,
            "location": location_name,
            "latitude": amb_lat,
            "longitude": amb_lon,
            "distance_km": dist_km,
            "eta_minutes": total_eta_minutes,
            "equipment": equipment.split(' · ') if equipment else [],
            "matched_resources": matched_resources,
            "missing_resources": missing_resources,
            "ranking_score": round(ranking_score, 1),
            "score_breakdown": {
                "distance_factor": distance_factor,
                "traffic_factor": traffic_factor,
                "availability_factor": availability_factor,
                "priority_factor": priority_factor
                ,"resource_factor": resource_factor
            },
            "selection_reason": selection_reason,
            "status": amb['status']
        }
        ranked_candidates.append(candidate)

    # Sort by ranking_score descending
    ranked_candidates.sort(key=lambda x: x['ranking_score'], reverse=True)
    
    best_ambulance = ranked_candidates[0]
    alternatives = ranked_candidates[1:3]

    traffic_info['resource_requirements'] = requirements
    return best_ambulance, alternatives, traffic_info

def find_nearest_hospital(pickup_lat, pickup_lon, emergency_type=None):
    """
    Finds and ranks hospitals from SQLite based on Haversine distance,
    bed availability, and emergency department capabilities.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM hospitals WHERE emergency_available = 1 AND status = 'ACTIVE' AND available_beds > 0")
    hospitals = cursor.fetchall()
    conn.close()

    if not hospitals:
        return None, []

    ranked_hospitals = []
    requirements = get_resource_requirements(emergency_type or 'General')

    for hosp in hospitals:
        dist_km = haversine_distance(pickup_lat, pickup_lon, hosp['latitude'], hosp['longitude'])
        eta_minutes = max(3, round((dist_km / 40.0) * 60.0))
        
        # Capability check
        is_icu = bool(hosp['icu_available'])
        is_cardio = bool(hosp['cardiology_available'])
        is_trauma = bool(hosp['trauma_available'])
        avail_beds = hosp['available_beds']
        total_beds = hosp['total_beds']
        bed_percentage = round((avail_beds / total_beds) * 100) if total_beds > 0 else 0
        
        suitability_score = 100 - (dist_km * 4) + (avail_beds * 2)
        
        if emergency_type == 'Cardiac' and is_cardio:
            suitability_score += 20
        elif emergency_type == 'Accident' and is_trauma:
            suitability_score += 20

        matched_hospital_resources = []
        if 'icu' in requirements['hospital'] and is_icu:
            matched_hospital_resources.append('ICU')
        if 'cardiology' in requirements['hospital'] and is_cardio:
            matched_hospital_resources.append('Cardiology')
        if 'trauma' in requirements['hospital'] and is_trauma:
            matched_hospital_resources.append('Trauma Care')
        suitability_score += len(matched_hospital_resources) * 15

        hosp_data = {
            "id": hosp['id'],
            "name": hosp['name'],
            "address": hosp['address'],
            "latitude": hosp['latitude'],
            "longitude": hosp['longitude'],
            "distance_km": dist_km,
            "eta_minutes": eta_minutes,
            "available_beds": avail_beds,
            "total_beds": total_beds,
            "bed_percentage": bed_percentage,
            "icu_available": is_icu,
            "cardiology_available": is_cardio,
            "trauma_available": is_trauma,
            "matched_resources": matched_hospital_resources,
            "resource_requirements": requirements['hospital'],
            "suitability_score": round(suitability_score, 1)
        }
        ranked_hospitals.append(hosp_data)

    ranked_hospitals.sort(key=lambda x: x['suitability_score'], reverse=True)
    best_hospital = ranked_hospitals[0]
    alternatives = ranked_hospitals[1:]

    return best_hospital, alternatives
