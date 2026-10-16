"""
web_app.py
----------
Real-time BADS Transaction Generator Dashboard

This web application generates banking transactions in real-time (1 simulated minute
per 1 real second) and displays them on a live dashboard with charts and metrics.

Run:
    python web_app.py

Then open: http://localhost:5000
"""

from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import threading
import time
import json
from pathlib import Path
import sys

# Add src to path so we can import our generator modules
sys.path.insert(0, str(Path(__file__).parent))

from src.customer_generator import CustomerGenerator
from src.behavior_model import BehaviorModel
from src.anomaly_scenarios import ScenarioEngine
from src.transaction_generator import TransactionGenerator
from src.config import BASE_TRANSACTIONS_PER_MINUTE, NUM_CUSTOMERS, RANDOM_SEED

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Global state (thread-safe with lock)
# ---------------------------------------------------------------------------
class GeneratorState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.current_minute = None
        self.minute_data = []  # Last 60 minutes of data
        self.total_transactions = 0
        self.current_scenario = "NORMAL"
        self.scenario_intensity = 1.0
        self.customers = []
        self.generator = None
        self.behavior_model = None
        self.scenario_engine = None
        self.start_time = None
        self.elapsed_minutes = 0
        self.recent_files = []  # Track last 5 generated files
        self.current_minute_transactions = []  # Store current minute's transactions
        
    def add_minute(self, data):
        with self.lock:
            self.minute_data.append(data)
            if len(self.minute_data) > 60:  # Keep only last 60 minutes
                self.minute_data.pop(0)
            self.total_transactions += data['count']
            self.current_scenario = data['scenario_label']
            self.scenario_intensity = data.get('intensity', 1.0)
            self.elapsed_minutes += 1
            
    def add_file(self, filename):
        """Track the most recent generated files (keep last 5)"""
        with self.lock:
            self.recent_files.append(filename)
            if len(self.recent_files) > 5:
                self.recent_files.pop(0)
    
    def get_state(self):
        with self.lock:
            return {
                'running': self.running,
                'current_minute': self.current_minute.isoformat() if self.current_minute else None,
                'minute_data': list(self.minute_data),
                'total_transactions': self.total_transactions,
                'current_scenario': self.current_scenario,
                'scenario_intensity': round(self.scenario_intensity, 2),
                'elapsed_minutes': self.elapsed_minutes,
                'num_customers': len(self.customers),
                'recent_files': list(self.recent_files),  # Add recent files to state
            }

state = GeneratorState()

# ---------------------------------------------------------------------------
# Background generator thread
# ---------------------------------------------------------------------------
def generator_thread():
    """Runs in background, generates 1 minute of transactions per second."""
    
    # Initialize generator components
    print("Initializing generator components...")
    state.customers = CustomerGenerator(num_customers=200, seed=RANDOM_SEED).generate()
    state.behavior_model = BehaviorModel(base_tpm=80, total_days=365, seed=RANDOM_SEED + 1)
    state.scenario_engine = ScenarioEngine(seed=RANDOM_SEED + 2)
    
    # Create generator (no file output)
    from src.models import Transaction
    state.generator = TransactionGenerator(
        customers=state.customers,
        behavior_model=state.behavior_model,
        scenario_engine=state.scenario_engine,
        seed=RANDOM_SEED + 3,
        output_txn_file=Path("dummy.csv"),  # Not used
        output_vol_file=Path("dummy.csv"),
    )
    
    state.start_time = datetime.now()  # Use real current time
    state.current_minute = datetime.now().replace(second=0, microsecond=0)
    state.running = True
    
    # Create output directory for minute files
    output_dir = Path("data/minute_files")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Generator started at real time: {state.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Minute files will be saved to: {output_dir}")
    
    while state.running:
        minute_transactions = []
        
        # Generate this minute's transactions
        elapsed_days = state.elapsed_minutes / 1440.0
        multiplier, scenario_label = state.scenario_engine.get_minute_state(state.current_minute)
        
        base_count = state.behavior_model.sample_volume(state.current_minute, elapsed_days)
        count = max(0, int(round(base_count * multiplier)))
        
        # Generate the transactions
        total_amount = 0.0
        for _ in range(count):
            txn = state.generator._generate_one_transaction(state.current_minute, scenario_label)
            total_amount += txn.amount
            minute_transactions.append(txn.to_dict())
        
        # Save this minute's transactions to a JSON file
        timestamp_str = state.current_minute.strftime("%Y%m%d_%H%M%S")
        filename = f"transactions_{timestamp_str}.json"
        filepath = output_dir / filename
        
        minute_file_data = {
            "timestamp": state.current_minute.isoformat(),
            "minute": state.current_minute.strftime("%Y-%m-%d %H:%M:%S"),
            "transaction_count": count,
            "total_amount": round(total_amount, 2),
            "scenario_label": scenario_label,
            "scenario_intensity": multiplier,
            "transactions": minute_transactions
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(minute_file_data, f, indent=2)
        
        # Track this file
        state.add_file(filename)
        
        # Record this minute
        minute_data = {
            'timestamp': state.current_minute.strftime("%H:%M:%S"),
            'count': count,
            'amount': round(total_amount, 2),
            'scenario_label': scenario_label,
            'intensity': multiplier,
            'filename': filename,
        }
        state.add_minute(minute_data)
        
        # Advance time
        state.current_minute += timedelta(minutes=1)
        
        # Sleep 1 second (1 simulated minute)
        time.sleep(1.0)
    
    print("Generator stopped.")

# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('dashboard.html')

@app.route('/api/state')
def api_state():
    """API endpoint returning current generator state."""
    return jsonify(state.get_state())

@app.route('/api/start', methods=['POST'])
def api_start():
    """Start the generator."""
    if not state.running:
        thread = threading.Thread(target=generator_thread, daemon=True)
        thread.start()
        return jsonify({'status': 'started'})
    return jsonify({'status': 'already_running'})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop the generator."""
    state.running = False
    return jsonify({'status': 'stopped'})

@app.route('/api/files/<filename>')
def serve_file(filename):
    """Serve a generated JSON file."""
    filepath = Path("data/minute_files") / filename
    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({'error': 'File not found'}), 404

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print("=" * 60)
    print("  BADS Real-Time Transaction Generator Dashboard")
    print("=" * 60)
    print()
    print("  Open your browser to: http://localhost:5000")
    print()
    print("  The generator will create 1 simulated minute of transactions")
    print("  every 1 real second.")
    print()
    print("=" * 60)
    
    # Auto-start the generator
    thread = threading.Thread(target=generator_thread, daemon=True)
    thread.start()
    
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
