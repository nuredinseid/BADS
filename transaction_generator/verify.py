"""
verify.py
---------
Quick end-to-end smoke test for the BADS Transaction Generator.
Run from the transaction_generator/ directory:

    python verify.py

Generates 3 simulated days with 100 customers, validates, and prints a summary.
Exits with code 0 on success, 1 on any error.
"""
import sys
import os

# Ensure we can import src.*
sys.path.insert(0, os.path.dirname(__file__))

# Bootstrap logging
import logging
logging.basicConfig(
    level=logging.WARNING,   # suppress INFO noise during smoke test
    format="%(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

print("=" * 50)
print("  BADS Transaction Generator — Smoke Test")
print("=" * 50)

# ── Step 1: Imports ────────────────────────────────
print("\n[1/5] Importing modules...", flush=True)
try:
    from src.config import (
        DATA_DIR, LOGS_DIR, OUTPUT_TRANSACTIONS_FILE,
        OUTPUT_MINUTE_VOLUME_FILE, OUTPUT_CUSTOMERS_FILE,
    )
    from src.models import Customer, Transaction, Scenario, MinuteVolume
    from src.customer_generator import CustomerGenerator
    from src.behavior_model import BehaviorModel
    from src.anomaly_scenarios import ScenarioEngine
    from src.transaction_generator import TransactionGenerator
    from src.data_validator import DataValidator
    print("    OK — all modules imported.")
except Exception as e:
    print(f"    FAILED: {e}")
    sys.exit(1)

# ── Step 2: Generate customers ─────────────────────
print("\n[2/5] Generating 100 synthetic customers...", flush=True)
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    cust_gen  = CustomerGenerator(num_customers=100, seed=42)
    customers = cust_gen.generate()
    cust_gen.save_to_csv()
    assert len(customers) == 100, f"Expected 100 customers, got {len(customers)}"
    types = {c.customer_type for c in customers}
    assert types.issubset({"INDIVIDUAL", "BUSINESS", "CORPORATE"})
    print(f"    OK — {len(customers)} customers, types: {types}")
except Exception as e:
    print(f"    FAILED: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ── Step 3: Behavior model ─────────────────────────
print("\n[3/5] Testing BehaviorModel...", flush=True)
try:
    from datetime import datetime
    bm = BehaviorModel(base_tpm=100, total_days=3, seed=99)

    # Peak hour (10:00 Tuesday) should give higher volume than 3am Sunday
    ts_peak  = datetime(2026, 10, 6, 10, 0)   # Tuesday 10am
    ts_quiet = datetime(2026, 10, 11, 3, 0)   # Sunday  3am
    peak_vol  = bm.expected_volume(ts_peak,  elapsed_days=1.0)
    quiet_vol = bm.expected_volume(ts_quiet, elapsed_days=1.0)

    assert peak_vol > quiet_vol, (
        f"Peak volume ({peak_vol:.1f}) should exceed quiet volume ({quiet_vol:.1f})"
    )
    print(f"    OK — peak={peak_vol:.1f} tpm, quiet={quiet_vol:.1f} tpm")

    # Channel probs should sum to ~1
    cp = bm.channel_probs(ts_peak)
    total = sum(cp.values())
    assert abs(total - 1.0) < 1e-6, f"Channel probs sum={total}"
    print(f"    OK — channel probs sum to {total:.6f}")
except Exception as e:
    print(f"    FAILED: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ── Step 4: Generate 3 days of transactions ────────
print("\n[4/5] Generating 3 days of transactions (100 customers)...", flush=True)
try:
    from datetime import datetime

    behavior = BehaviorModel(base_tpm=100, total_days=3, seed=43)
    scenario_engine = ScenarioEngine(
        seed=44,
        spike_probability=0.01,   # high prob to ensure at least one scenario
        drop_probability=0.005,
    )

    gen = TransactionGenerator(
        customers       = customers,
        behavior_model  = behavior,
        scenario_engine = scenario_engine,
        seed            = 45,
        output_txn_file = OUTPUT_TRANSACTIONS_FILE,
        output_vol_file = OUTPUT_MINUTE_VOLUME_FILE,
    )

    start = datetime(2026, 10, 1, 0, 0, 0)
    gen.generate_historical(start_time=start, simulation_days=3)

    total = gen.total_transactions
    assert total > 0, "No transactions were generated!"
    print(f"    OK — {total:,} transactions generated.")

    # Save ground truth
    scenario_engine.save_ground_truth()
    summary = scenario_engine.summary()
    print(f"    OK — {summary['spike_count']} spike(s), {summary['drop_count']} drop(s) injected.")
except Exception as e:
    print(f"    FAILED: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# ── Step 5: Validate ───────────────────────────────
print("\n[5/5] Validating output files...", flush=True)
try:
    validator = DataValidator(
        txn_file      = OUTPUT_TRANSACTIONS_FILE,
        vol_file      = OUTPUT_MINUTE_VOLUME_FILE,
        customer_file = OUTPUT_CUSTOMERS_FILE,
    )
    result = validator.validate()

    if result.errors:
        for e in result.errors:
            print(f"    ERROR: {e}")
        sys.exit(1)

    if result.warnings:
        for w in result.warnings:
            print(f"    WARN: {w}")

    validator.print_summary(
        result           = result,
        simulation_days  = 3,
        scenario_summary = summary,
    )
    print("Smoke test PASSED.\n")
    sys.exit(0)

except Exception as e:
    print(f"    FAILED: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)
