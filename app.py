from flask import Flask, render_template, jsonify, session, send_from_directory
import os
from models.database import init_db, seed_db
from routes.api_routes import api_bp

app = Flask(__name__, template_folder='templates', static_folder='static')

# Configure secret key for sessions
app.secret_key = os.environ.get('SECRET_KEY', 'smart_ambulance_dispatch_system_secret_key_2026')

# Initialize and seed SQLite database
with app.app_context():
    try:
        init_db()
        seed_db()
        print("[OK] SQLite Database Initialized & Seeded Successfully.")
    except Exception as e:
        print(f"[NOTE] Database initialization notice: {e}")

# Register API Blueprint
app.register_blueprint(api_bp)

# ==========================================
# PAGE ROUTING (PRESERVING SINGLE-PAGE UI)
# ==========================================

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('index.html')

@app.route('/register')
def register_page():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard_page():
    return render_template('index.html')

@app.route('/booking')
def booking_page():
    return render_template('index.html')

@app.route('/tracking')
def tracking_page():
    return render_template('index.html')

@app.route('/hospital')
def hospital_page():
    return render_template('index.html')

# Serve static images if requested directly
@app.route('/images/<path:filename>')
def serve_images(filename):
    return send_from_directory(os.path.join(app.root_path, 'static', 'images'), filename)

# ==========================================
# GLOBAL ERROR HANDLERS
# ==========================================

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({"success": False, "message": "Requested resource or endpoint not found."}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "message": "An internal server error occurred. Please try again."}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print("\n========================================================")
    print("  SMART AMBULANCE DISPATCH SYSTEM - FLASK SERVER RUNNING")
    print(f"  Access Web Application at: http://localhost:{port}")
    print("========================================================\n")
    app.run(host='0.0.0.0', port=port, debug=True)
