"""
main.py
-------
CLI entry point for the BADS Transaction Generator.

Usage
-----
Historical mode (generate a complete dataset):
    python -m src.main --mode historical --days 30
    python -m src.main --mode historical --days 60 --seed 42 --customers 1000

Real-time simulation mode (emit transactions over time):
    python -m src.main --mode realtime --speed 60
    python -m src.main --mode realtime --speed 600 --days 7

Optional overrides:
    --output-dir  <path>   Override the data/ output directory
    --base-tpm    <int>    Override BASE_TRANSACTIONS_PER_MINUTE
    --spike-prob  <float>  Override SPIKE_PROBABILITY
    --drop-prob   <float>  Override DROP_PROBABILITY

The generator writes:
    data/customers.csv
    data/generated_transactions.csv
    data/minute_transaction_volume.csv
    data/scenario_ground_truth.csv
    logs/generator.log
"""

import argparse
import csv
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap logging BEFORE importing any project module so that every
# logger created during import also writes to the file.
# ---------------------------------------------------------------------------
def _setup_logging(log_level: str = "INFO") -> None:
    from src.config import LOG_FILE, LOGS_DIR
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # Force UTF-8 on the stream handler so special chars don't crash on Windows CP1252
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.stream = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

    logging.basicConfig(
        level=numeric_level,
        format=fmt,
        handlers=[
            stream_handler,
            logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
        ],
    )


# ---------------------------------------------------------------------------
# Imports (after logging setup)
# ---------------------------------------------------------------------------
from src.config import (
    BASE_TRANSACTIONS_PER_MINUTE,
    DATA_DIR,
    DEFAULT_REALTIME_SPEED,
    DROP_PROBABILITY,
    NUM_CUSTOMERS,
    OUTPUT_CUSTOMERS_FILE,
    OUTPUT_MINUTE_VOLUME_FILE,
    OUTPUT_TRANSACTIONS_FILE,
    RANDOM_SEED,
    SIMULATION_DAYS,
    SPIKE_PROBABILITY,
)
from src.customer_generator import CustomerGenerator
from src.behavior_model import BehaviorModel
from src.anomaly_scenarios import ScenarioEngine
from src.transaction_generator import TransactionGenerator
from src.data_validator import DataValidator

logger = logging.getLogger("bads.main")


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="BADS Simulated Banking Transaction Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main --mode historical --days 30
  python -m src.main --mode historical --days 90 --seed 42 --customers 5000
  python -m src.main --mode realtime   --speed 60
  python -m src.main --mode realtime   --speed 600 --days 7
        """,
    )

    parser.add_argument(
        "--mode",
        choices=["historical", "realtime"],
        default="historical",
        help="Generation mode (default: historical)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=SIMULATION_DAYS,
        help=f"Number of days to simulate (default: {SIMULATION_DAYS})",
    )
    parser.add_argument(
        "--customers",
        type=int,
        default=NUM_CUSTOMERS,
        help=f"Number of synthetic customers (default: {NUM_CUSTOMERS})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=RANDOM_SEED,
        help=f"Random seed for reproducibility (default: {RANDOM_SEED})",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=DEFAULT_REALTIME_SPEED,
        help=(
            "Real-time simulation speed multiplier: simulated-minutes per real-second. "
            f"speed=60 -> 1 sim-min = 1 real-sec (default: {DEFAULT_REALTIME_SPEED})"
        ),
    )
    parser.add_argument(
        "--base-tpm",
        type=float,
        default=BASE_TRANSACTIONS_PER_MINUTE,
        dest="base_tpm",
        help=f"Base transactions per minute at peak hours (default: {BASE_TRANSACTIONS_PER_MINUTE})",
    )
    parser.add_argument(
        "--spike-prob",
        type=float,
        default=SPIKE_PROBABILITY,
        dest="spike_prob",
        help=f"Per-minute spike start probability (default: {SPIKE_PROBABILITY})",
    )
    parser.add_argument(
        "--drop-prob",
        type=float,
        default=DROP_PROBABILITY,
        dest="drop_prob",
        help=f"Per-minute drop start probability (default: {DROP_PROBABILITY})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        dest="output_dir",
        help="Override output directory (default: data/ inside the project)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        dest="start_date",
        help=(
            "Simulation start date in YYYY-MM-DD format. "
            "Defaults to today at 00:00:00."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Helper: resolve output paths (allow --output-dir override)
# ---------------------------------------------------------------------------

def _resolve_paths(output_dir: Path | None):
    if output_dir is None:
        return (
            OUTPUT_TRANSACTIONS_FILE,
            OUTPUT_MINUTE_VOLUME_FILE,
            OUTPUT_CUSTOMERS_FILE,
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    return (
        output_dir / "generated_transactions.csv",
        output_dir / "minute_transaction_volume.csv",
        output_dir / "customers.csv",
    )


# ---------------------------------------------------------------------------
# Progress bar helper (no external dependencies)
# ---------------------------------------------------------------------------

def _progress_bar(current: int, total: int, width: int = 40) -> str:
    filled = int(width * current / total) if total > 0 else 0
    bar    = "█" * filled + "░" * (width - filled)
    pct    = 100.0 * current / total if total > 0 else 0
    return f"[{bar}] {pct:5.1f}%"


# ---------------------------------------------------------------------------
# Historical mode
# ---------------------------------------------------------------------------

def run_historical(args: argparse.Namespace) -> None:
    txn_path, vol_path, cus_path = _resolve_paths(args.output_dir)

    # --- Parse start date ---
    if args.start_date:
        try:
            start_time = datetime.strptime(args.start_date, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid --start-date format. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        start_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    logger.info("=" * 55)
    logger.info("  BADS Transaction Generator  —  HISTORICAL MODE")
    logger.info("=" * 55)
    logger.info("  Start date   : %s", start_time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("  Days         : %d", args.days)
    logger.info("  Customers    : %d", args.customers)
    logger.info("  Base TPM     : %.0f", args.base_tpm)
    logger.info("  Spike prob   : %.4f", args.spike_prob)
    logger.info("  Drop prob    : %.4f", args.drop_prob)
    logger.info("  Seed         : %d", args.seed)
    logger.info("  Output dir   : %s", txn_path.parent)
    logger.info("=" * 55)

    # --- Step 1: Customers ---
    print("\nGenerating customers...")
    cust_gen = CustomerGenerator(num_customers=args.customers, seed=args.seed)
    customers = cust_gen.generate()
    cust_gen.save_to_csv()
    print(f"  {len(customers):,} customers created  ->  {cus_path}")

    # --- Step 2: Build model components ---
    behavior = BehaviorModel(
        base_tpm   = args.base_tpm,
        total_days = args.days,
        seed       = args.seed + 1,
    )
    scenario_engine = ScenarioEngine(
        seed              = args.seed + 2,
        spike_probability = args.spike_prob,
        drop_probability  = args.drop_prob,
    )

    # --- Step 3: Generate transactions ---
    print("\nGenerating transactions...")
    gen = TransactionGenerator(
        customers       = customers,
        behavior_model  = behavior,
        scenario_engine = scenario_engine,
        seed            = args.seed + 3,
        output_txn_file = txn_path,
        output_vol_file = vol_path,
    )

    # Patch output paths if overridden
    gen.output_txn_file = txn_path
    gen.output_vol_file = vol_path

    gen.generate_historical(start_time=start_time, simulation_days=args.days)
    print(f"  Transactions  ->  {txn_path}")
    print(f"  Minute volume ->  {vol_path}")

    # --- Step 4: Save ground truth ---
    print("\nSaving scenario ground truth...")
    scenario_engine.save_ground_truth()
    print(f"  Ground truth  ->  {txn_path.parent / 'scenario_ground_truth.csv'}")

    # --- Step 5: Validate ---
    print("\nValidating data...")
    validator = DataValidator(
        txn_file      = txn_path,
        vol_file      = vol_path,
        customer_file = cus_path,
    )
    result = validator.validate()
    validator.print_summary(
        result           = result,
        simulation_days  = args.days,
        scenario_summary = scenario_engine.summary(),
    )

    if not result.passed:
        logger.error("Validation failed with %d error(s).", len(result.errors))
        sys.exit(1)

    print("Generation completed successfully.\n")


# ---------------------------------------------------------------------------
# Real-time mode
# ---------------------------------------------------------------------------

def run_realtime(args: argparse.Namespace) -> None:
    import time

    txn_path, vol_path, cus_path = _resolve_paths(args.output_dir)

    if args.start_date:
        try:
            start_time = datetime.strptime(args.start_date, "%Y-%m-%d")
        except ValueError:
            logger.error("Invalid --start-date format. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        start_time = datetime.now().replace(second=0, microsecond=0)

    logger.info("=" * 55)
    logger.info("  BADS Transaction Generator  —  REAL-TIME MODE")
    logger.info("=" * 55)
    logger.info("  Start time   : %s", start_time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("  Speed        : %.1fx  (1 sim-min = %.2f real-sec)",
                args.speed, 60.0 / args.speed)
    logger.info("  Max days     : %s", str(args.days) if args.days else "unlimited")
    logger.info("  Customers    : %d", args.customers)
    logger.info("  Seed         : %d", args.seed)
    logger.info("=" * 55)
    print("Press Ctrl+C to stop.\n")

    # --- Customers ---
    print("Generating customers...")
    cust_gen = CustomerGenerator(num_customers=args.customers, seed=args.seed)
    customers = cust_gen.generate()
    cust_gen.save_to_csv()
    print(f"  {len(customers):,} customers ready.\n")

    behavior = BehaviorModel(
        base_tpm   = args.base_tpm,
        total_days = args.days if args.days else 365,
        seed       = args.seed + 1,
    )
    scenario_engine = ScenarioEngine(
        seed              = args.seed + 2,
        spike_probability = args.spike_prob,
        drop_probability  = args.drop_prob,
    )
    gen = TransactionGenerator(
        customers       = customers,
        behavior_model  = behavior,
        scenario_engine = scenario_engine,
        seed            = args.seed + 3,
        output_txn_file = txn_path,
        output_vol_file = vol_path,
    )

    txn_path.parent.mkdir(parents=True, exist_ok=True)

    # Open files for streaming write
    with open(txn_path, "w", newline="", encoding="utf-8") as txn_f, \
         open(vol_path, "w", newline="", encoding="utf-8") as vol_f:

        from src.models import Transaction, MinuteVolume
        txn_writer = csv.DictWriter(txn_f, fieldnames=Transaction.csv_columns())
        vol_writer = csv.DictWriter(vol_f, fieldnames=MinuteVolume.csv_columns())
        txn_writer.writeheader()
        vol_writer.writeheader()

        total_txns    = 0
        real_sec_per_min = 60.0 / args.speed
        max_minutes   = (args.days * 1440) if args.days else None
        minute_idx    = 0
        current_ts    = start_time

        try:
            from src.behavior_model import BehaviorModel as _BM
            while True:
                if max_minutes and minute_idx >= max_minutes:
                    break

                elapsed_days = minute_idx / 1440.0
                multiplier, label = scenario_engine.get_minute_state(current_ts)
                base_count = behavior.sample_volume(current_ts, elapsed_days)
                count      = max(0, int(round(base_count * multiplier)))

                minute_amount = 0.0
                for _ in range(count):
                    txn = gen._generate_one_transaction(current_ts, label)
                    txn_writer.writerow(txn.to_dict())
                    minute_amount += txn.amount
                    total_txns += 1

                from src.models import MinuteVolume
                mv = MinuteVolume(
                    timestamp         = current_ts,
                    transaction_count = count,
                    total_amount      = round(minute_amount, 2),
                    scenario_label    = label,
                )
                vol_writer.writerow(mv.to_dict())
                txn_f.flush()
                vol_f.flush()

                print(
                    f"  {current_ts.strftime('%Y-%m-%d %H:%M')}  "
                    f"txns={count:4d}  label={label:<6}  total={total_txns:,}",
                    flush=True,
                )

                current_ts  += __import__("datetime").timedelta(minutes=1)
                minute_idx  += 1
                time.sleep(real_sec_per_min)

        except KeyboardInterrupt:
            print("\n\nSimulation interrupted by user.")

    scenario_engine.save_ground_truth()
    print(f"\nReal-time simulation stopped. {total_txns:,} transactions written.")
    print(f"  Transactions  -> {txn_path}")
    print(f"  Minute volume -> {vol_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Parse args first (without logging) to get log level
    parser = _build_parser()
    args   = parser.parse_args()

    _setup_logging(args.log_level)

    if args.mode == "historical":
        run_historical(args)
    elif args.mode == "realtime":
        run_realtime(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
