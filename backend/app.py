import sys
import os
# Ensure the backend directory is in the system path for module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from math import radians, sin, cos, sqrt, atan2
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import requests
import re
import random
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from database import init_db

app = Flask(__name__, static_folder='../', static_url_path='/')
CORS(app)

# Initialize database
init_db()

@app.route("/")
def home():
    return app.send_static_file("login.html")

@app.route("/<path:path>")
def serve_static(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return app.send_static_file(path)
    else:
        return app.send_static_file("login.html")

# ---------------- UTILS ----------------
def get_connection():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    return sqlite3.connect(os.path.join(BASE_DIR, "users.db"))



def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


def estimate_transport_cost(distance_km, is_international, same_state=False, flight_possible=True):
    transport = {}

    if not is_international:
        transport["bus"] = int(distance_km * 3)
        transport["train"] = int(distance_km * 2)

        # Flights only available for distances >= 300km, not in same state, and if an airport is nearby
        if distance_km >= 300 and not same_state and flight_possible:
            if distance_km < 500:
                flight_rate = 9
            elif distance_km < 1500:
                flight_rate = 7
            else:
                flight_rate = 6

            transport["flight"] = int(distance_km * flight_rate)
    else:
        if distance_km < 3000:
            flight_rate = 15
        elif distance_km < 7000:
            flight_rate = 12
        else:
            flight_rate = 10

        transport["flight"] = int(distance_km * flight_rate)

    return transport


# ---------------- REGISTER ----------------
@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json()

    name = data.get("name")
    email = data.get("email")
    phone = data.get("phone")
    password = data.get("password")
    question = data.get("security_question")
    answer = data.get("security_answer")

    if not all([name, email, phone, password, question, answer]):
        return jsonify({"success": False, "message": "All fields required"}), 400

    # Password validation
    if len(password) < 8:
        return jsonify({"success": False, "message": "Password must be at least 8 characters long"}), 400
    if not re.search(r'[A-Z]', password):
        return jsonify({"success": False, "message": "Password must contain at least one uppercase letter"}), 400
    if not re.search(r'[a-z]', password):
        return jsonify({"success": False, "message": "Password must contain at least one lowercase letter"}), 400
    if not re.search(r'\d', password):
        return jsonify({"success": False, "message": "Password must contain at least one number"}), 400
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return jsonify({"success": False, "message": "Password must contain at least one special character"}), 400

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO users (name, email, phone, password, security_question, security_answer)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, email, phone, password, question, answer))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "message": "Email already exists"}), 400
    finally:
        conn.close()

    return jsonify({"success": True})


# ---------------- LOGIN ----------------
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT password FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "message": "Email not found"}), 404

    if row[0] != password:
        return jsonify({"success": False, "message": "Invalid password"}), 403

    return jsonify({"success": True})


# ---------------- GET SECURITY QUESTION ----------------
@app.route("/api/get-security-question", methods=["POST"])
def get_security_question():
    data = request.get_json()
    email = data.get("email")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT security_question FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "message": "Email not found"}), 404

    return jsonify({"success": True, "securityQuestion": row[0]})


# ---------------- RESET PASSWORD ----------------
@app.route("/api/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json()

    email = data.get("email")
    answer = data.get("security_answer")
    new_password = data.get("new_password")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT security_answer FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()

    if not row or row[0].lower() != answer.lower():
        conn.close()
        return jsonify({"success": False, "message": "Invalid credentials"}), 403

    cursor.execute("UPDATE users SET password = ? WHERE email = ?", (new_password, email))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Password reset successful"})


# Whitelist of cities/regions known to have nearby airports
CITIES_WITH_AIRPORTS = {
    # Odisha
    "bhubaneswar", "jharsuguda", "rourkela", "jeypore",
    # Andhra Pradesh / Telangana
    "hyderabad", "visakhapatnam", "vijayawada", "tirupati",
    # Arunachal Pradesh / Assam / Northeast
    "itanagar", "guwahati", "imphal", "agartala", "aizawl", "kohima",
    # Bihar
    "patna",
    # Chhattisgarh
    "raipur",
    # Goa
    "goa", "panaji",
    # Gujarat
    "ahmedabad", "surat", "vadodara", "rajkot",
    # Himachal Pradesh  ← Gaggal Airport serves Dharamshala/Kangra
    "dharamshala", "dharamsala", "kangra", "mcleod ganj", "mcleodganj", "shimla", "kullu", "manali",
    # J&K / Ladakh
    "srinagar", "leh", "jammu", "ladakh",
    # Jharkhand
    "ranchi",
    # Karnataka
    "bangalore", "bengaluru", "mysore", "mangalore", "hubballi",
    # Kerala
    "kochi", "thiruvananthapuram", "kozhikode", "kannur",
    # Madhya Pradesh
    "indore", "bhopal", "jabalpur", "khajuraho",
    # Maharashtra
    "mumbai", "pune", "aurangabad", "nagpur", "nashik",
    # Manipur / Meghalaya
    "imphal", "shillong",
    # Punjab / Haryana / Delhi
    "amritsar", "chandigarh", "ludhiana", "delhi", "new delhi", "gurgaon",
    # Rajasthan
    "jaipur", "jodhpur", "udaipur", "jaisalmer",
    # Sikkim / West Bengal
    "gangtok", "kolkata", "bagdogra", "siliguri", "darjeeling",
    # Tamil Nadu
    "chennai", "coimbatore", "madurai", "tiruchirappalli", "trichy",
    # Uttar Pradesh
    "lucknow", "varanasi", "agra", "prayagraj", "allahabad",
    # Uttarakhand
    "dehradun", "pantnagar",
    # International
    "paris", "london", "dubai", "singapore", "bangkok", "bali", "tokyo",
    "new york", "los angeles", "barcelona", "rome", "sydney", "amsterdam",
    "maldives", "iceland",
}

def has_airport(lat, lon, city_name=None):
    """
    Checks if there is an airport near the given location.
    1. Checks the city_name directly against the whitelist (fastest, most reliable).
    2. Falls back to reverse geocoding the coordinates and checking the whitelist.
    3. Last resort: TomTom API with name validation.
    """
    # ── Step 1: Direct name check (most reliable) ──
    if city_name:
        if city_name.lower() in CITIES_WITH_AIRPORTS:
            print(f"Airport confirmed via direct name: {city_name}")
            return True
        # Also check if any whitelist entry is contained in the city name (handles partial matches)
        for known in CITIES_WITH_AIRPORTS:
            if known in city_name.lower() or city_name.lower() in known:
                print(f"Airport confirmed via partial match: {city_name} ~ {known}")
                return True

    # ── Step 2: Reverse geocode the coordinates ──
    try:
        geo_url = "https://nominatim.openstreetmap.org/reverse"
        res = requests.get(
            geo_url,
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "TravelMateApp/1.0"},
            timeout=5
        )
        if res.status_code == 200:
            data = res.json()
            address = data.get("address", {})
            candidates = [
                address.get("city", ""),
                address.get("town", ""),
                address.get("village", ""),
                address.get("county", ""),
                address.get("state_district", ""),
                address.get("suburb", ""),
            ]
            for name in candidates:
                if name and name.lower() in CITIES_WITH_AIRPORTS:
                    print(f"Airport confirmed via reverse geocode: {name}")
                    return True
    except Exception as e:
        print(f"Airport reverse-geocode error: {e}")

    # ── Step 3: TomTom fallback (airports only, with name validation) ──
    try:
        TOMTOM_KEY = "MS39QFw2ocwUvr3eBI6C9sVkiVfjoTYK"
        tomtom_url = "https://api.tomtom.com/search/2/poiSearch/airport.json"
        params = {
            "lat": lat,
            "lon": lon,
            "radius": 100000,
            "limit": 5,
            "categorySet": "7315",
            "key": TOMTOM_KEY
        }
        res = requests.get(tomtom_url, params=params, timeout=5)
        if res.status_code == 200:
            results = res.json().get("results", [])
            airport_keywords = ["airport", "aerodrome", "air base", "airfield", "airstrip"]
            for r in results:
                poi_name = r.get("poi", {}).get("name", "").lower()
                if any(kw in poi_name for kw in airport_keywords):
                    print(f"Airport confirmed via TomTom: {poi_name}")
                    return True
    except Exception as e:
        print(f"TomTom airport check error: {e}")

    return False


# ---------------- TRIP DETAILS (MAP + HOTELS) ----------------
@app.route("/api/trip-details", methods=["POST"])
def trip_details():
    data = request.get_json()
    source = data.get("source")
    destination = data.get("destination")
    days = data.get("days", 1)

    if not source or not destination:
        return jsonify({"success": False, "message": "Source or destination missing"}), 400

    # Check destination in database first
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT latitude, longitude, country, currency, is_international,
               budget_per_day, medium_per_day, luxury_per_day, category
        FROM destinations WHERE name LIKE ?
    """, (f"%{destination}%",))
    
    dest_record = cursor.fetchone()
    conn.close()

    geo_url = "https://nominatim.openstreetmap.org/search"

    def geocode(place):
        try:
            response = requests.get(
                geo_url,
                params={
                    "q": place,
                    "format": "json",
                    "limit": 1
                },
                headers={"User-Agent": "TravelMateApp/1.0"},
                timeout=5
            )
            response.raise_for_status()
            res = response.json()
        except requests.exceptions.RequestException as e:
            print(f"Geocoding error for {place}: {e}")
            return None

        if not res:
            return None

        addr = res[0].get("address", {})
        state = addr.get("state", "") or addr.get("region", "") or addr.get("county", "")
        return float(res[0]["lat"]), float(res[0]["lon"]), addr, state

    # 1️⃣ Geocode source
    source_geo = geocode(source)
    if not source_geo:
        return jsonify({"success": False, "message": "Invalid source city"}), 400

    src_lat, src_lon, src_addr, src_state = source_geo

    # 2️⃣ Use database or geocode destination
    if dest_record:
        dest_lat, dest_lon, dest_country, currency, is_international, budget_day, medium_day, luxury_day, dest_state = dest_record
    else:
        dest_geo = geocode(destination)
        if not dest_geo:
            return jsonify({"success": False, "message": "Invalid destination city"}), 400
        dest_lat, dest_lon, dest_addr, dest_state = dest_geo
        src_country = src_addr.get("country_code", "")
        dest_country = dest_addr.get("country_code", "")
        is_international = src_country != dest_country
        currency = "USD" if is_international else "INR"
        budget_day = 500 if not is_international else 100
        medium_day = 1000 if not is_international else 200
        luxury_day = 2500 if not is_international else 500

    # 3️⃣ Distance calculation
    distance = calculate_distance(src_lat, src_lon, dest_lat, dest_lon)

    # Check if same state (no domestic flights within state)
    same_state = src_state == dest_state and not is_international

    # Check if both source and destination have nearby airports
    # Pass city names directly so the whitelist check works immediately
    flight_possible = True
    if not is_international:
        flight_possible = has_airport(src_lat, src_lon, source) and has_airport(dest_lat, dest_lon, destination)

    # 4️⃣ Transport cost
    transport_costs = estimate_transport_cost(distance, is_international, same_state=same_state, flight_possible=flight_possible)
    extra_cost = 1000

    # 5️⃣ Per-day accommodation costs
    accommodation_costs = {
        "budget": {
            "per_day": budget_day,
            "total": budget_day * days
        },
        "medium": {
            "per_day": medium_day,
            "total": medium_day * days
        },
        "luxury": {
            "per_day": luxury_day,
            "total": luxury_day * days
        },
        "currency": currency,
        "days": days
    }

    # Determine cheapest transport cost
    available_transports = [cost for cost in transport_costs.values() if cost is not None]
    cheapest_transport = min(available_transports) if available_transports else 0

    # Total budgets including accommodation, extra, and cheapest transport
    total_budgets = {
        "budget": {
            "accommodation": accommodation_costs["budget"]["total"],
            "transport": cheapest_transport,
            "extra": extra_cost,
            "total": accommodation_costs["budget"]["total"] + extra_cost + cheapest_transport
        },
        "medium": {
            "accommodation": accommodation_costs["medium"]["total"],
            "transport": cheapest_transport,
            "extra": extra_cost,
            "total": accommodation_costs["medium"]["total"] + extra_cost + cheapest_transport
        },
        "luxury": {
            "accommodation": accommodation_costs["luxury"]["total"],
            "transport": cheapest_transport,
            "extra": extra_cost,
            "total": accommodation_costs["luxury"]["total"] + extra_cost + cheapest_transport
        },
        "currency": currency
    }

    # 6️⃣ FETCH HOTELS FROM TOMTOM
    TOMTOM_KEY = "MS39QFw2ocwUvr3eBI6C9sVkiVfjoTYK"

    tomtom_url = "https://api.tomtom.com/search/2/poiSearch/hotel.json"

    params = {
        "lat": dest_lat,
        "lon": dest_lon,
        "radius": 15000,
        "limit": 20,
        "key": TOMTOM_KEY
    }

    tt_response = requests.get(tomtom_url, params=params)

    hotels = []

    if tt_response.status_code == 200:
        tt_data = tt_response.json()

        for result in tt_data.get("results", []):
            hotels.append({
                "name": result.get("poi", {}).get("name", "Unnamed Hotel"),
                "lat": result.get("position", {}).get("lat"),
                "lon": result.get("position", {}).get("lon")
            })

    # 7️⃣ FINAL RESPONSE
    return jsonify({
        "success": True,
        "data": {
            "source": source,
            "destination": destination,
            "latitude": dest_lat,
            "longitude": dest_lon,
            "hotels": hotels,
            "distance_km": int(distance),
            "transport": transport_costs,
            "extra_cost": extra_cost,
            "accommodation_costs": accommodation_costs,
            "total_budgets": total_budgets,
            "is_international": is_international
        }
    })

# ---------------- AI WEATHER PREDICTION & LIVE FETCH ----------------
# Train a simple Random Forest on synthetic data on startup
def train_weather_model():
    data = []
    labels = []
    for _ in range(1500):
        temp = random.uniform(-20, 50)
        wind = random.uniform(0, 120)
        precip = random.uniform(0, 100)
        
        # Determine safety
        unsafe = False
        if wind > 60: unsafe = True  # High wind
        if precip > 40: unsafe = True # Heavy rain
        if temp < -5 or temp > 40: unsafe = True # Extreme temp
        
        # Add noise
        if random.random() < 0.05:
            unsafe = not unsafe
            
        data.append([temp, wind, precip])
        labels.append(0 if unsafe else 1)

    df = pd.DataFrame(data, columns=['temp', 'wind', 'precip'])
    clf = RandomForestClassifier(n_estimators=50, random_state=42)
    
    # Supress UserWarning for skipping feature names during prediction
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        clf.fit(df.values, labels)
    return clf

weather_ai_model = train_weather_model()

@app.route("/api/ai-weather-analysis", methods=["POST"])
def ai_weather_analysis():
    data = request.get_json()
    lat = data.get("lat")
    lon = data.get("lon")
    
    if lat is None or lon is None:
        return jsonify({"success": False, "message": "Missing coordinates"}), 400

    # 1. Fetch live weather from FREE Open-Meteo API
    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&hourly=precipitation,windspeed_10m&timezone=auto"
    
    try:
        res = requests.get(weather_url, timeout=5)
        if res.status_code != 200:
            return jsonify({"success": False, "message": "Weather API failed"}), 502
            
        weather_data = res.json()
        current = weather_data.get("current_weather", {})
        
        temp = current.get("temperature", 25)
        wind = current.get("windspeed", 0)
        
        # Get approx precipitation from hourly (next hour)
        hourly_precip = weather_data.get("hourly", {}).get("precipitation", [0])
        precip = hourly_precip[0] if hourly_precip else 0
        
        # Predict using our ML model
        # 1 = Safe, 0 = Unsafe
        prediction = weather_ai_model.predict([[temp, wind, precip]])[0]
        
        warnings_list = []
        if wind > 40: warnings_list.append("High winds anticipated.")
        if wind > 60: warnings_list.append("Dangerously high winds! Proceed with caution.")
        if precip > 20: warnings_list.append("Rainy conditions expected.")
        if precip > 40: warnings_list.append("Heavy downpour/storm predicted.")
        if temp > 38: warnings_list.append("Extreme heat wave. Stay hydrated!")
        if temp < 0: warnings_list.append("Freezing temperatures expected.")
        
        is_safe = bool(prediction == 1)

        # 2. Fetch Global Real-Life Events from GDACS API
        gdacs_url = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP?version=v1"
        global_events_detected = []
        try:
            gdacs_res = requests.get(gdacs_url, timeout=5)
            if gdacs_res.status_code == 200:
                gdacs_data = gdacs_res.json()
                features = gdacs_data.get("features", [])                
                for feature in features:
                    geom = feature.get("geometry", {})
                    if geom.get("type") == "Point":
                        coords = geom.get("coordinates", [])
                        if len(coords) == 2:
                            event_lon, event_lat = coords[0], coords[1]
                            dist = calculate_distance(lat, lon, event_lat, event_lon)
                            
                            # If event is within 500km, consider it a risk
                            if dist < 500:
                                props = feature.get("properties", {})
                                event_name = props.get("name", "Unknown Event")
                                alert_level = props.get("alertlevel", "Unknown")
                                global_events_detected.append({
                                    "name": event_name,
                                    "distance": int(dist),
                                    "alert_level": alert_level
                                })
        except Exception as e:
            print(f"GDACS Error: {e}")
            pass

        # Adjust safety and warnings based on real-life events
        if global_events_detected:
            is_safe = False
            for ev in global_events_detected:
                warnings_list.append(f"GLOBAL ALERT: {ev['name']} detected {ev['distance']}km away ({ev['alert_level']} Alert).")

        if is_safe and not warnings_list:
            ai_suggestion = "Conditions are stable. It's completely safe for your travel plans!"
        elif is_safe:
            ai_suggestion = "Generally safe to travel, but be mindful of minor weather disturbances."
        else:
            if global_events_detected:
                ai_suggestion = "AI Safety Warning: Real-life catastrophic events detected nearby. Travel is HIGHLY discouraged!"
            else:
                ai_suggestion = "AI Safety Warning: Weather conditions look hostile. Traveling is NOT recommended right now."

        return jsonify({
            "success": True,
            "data": {
                "temperature": temp,
                "windspeed": wind,
                "precipitation": precip,
                "condition_code": current.get("weathercode", 0),
                "is_safe": is_safe,
                "warnings": warnings_list,
                "ai_suggestion": ai_suggestion,
                "global_events": global_events_detected
            }
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)