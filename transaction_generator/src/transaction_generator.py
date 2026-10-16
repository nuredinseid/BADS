"""
transaction_generator.py
------------------------
Core transaction generation engine for the BADS Transaction Generator.

Architecture
~~~~~~~~~~~~
                      ┌─────────────────────┐
                      │  TransactionGenerator│
                      │  (orchestrator)      │
                      └──────────┬──────────┘
                                 │  uses
          ┌──────────────────────┼──────────────────────┐
          │                      │                       │
   BehaviorModel          ScenarioEngine          CustomerPool
  (volume / channel        (SPIKE / DROP           (list of
   / type weights)          multiplier)             Customer objects)
          │                      │                       │
          └──────────────────────┼───────────────────────┘
                                 │
                         Transaction objects
                                 │
                    ┌────────────┴────────────┐
                    │                         │
              CSV Writer               [future] KafkaProducer
           (this phase)                  (next phase)

Key design decisions
~~~~~~~~~~~~~~~~~~~~
* The engine generates data minute-by-minute for easy aggregation.
* Each minute's transaction count is determined by BehaviorModel + ScenarioEngine.
* Individual transactions are then sampled from the customer pool and enriched
  with realistic amounts, channels, types, etc.
* The engine writes in configurable batch sizes to avoid holding all data in RAM.
* The scenario_label field on each Transaction carries the ground-truth tag for
  later BADS evaluation — it must not be consumed by the detector.
"""

import csv
import logging
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import numpy as np

from .behavior_model import BehaviorModel
from .anomaly_scenarios import ScenarioEngine
from .config import (
    AMOUNT_DISTRIBUTIONS,
    CHANNEL_WEIGHTS,
    CURRENCY,
    CUSTOMER_TYPE_AMOUNT_MULTIPLIER,
    LOCATIONS,
    LOCATION_WEIGHTS,
    OUTPUT_TRANSACTIONS_FILE,
    OUTPUT_MINUTE_VOLUME_FILE,
    RANDOM_SEED,
    SIMULATION_DAYS,
    TRANSACTION_TYPE_WEIGHTS,
    WRITE_BATCH_SIZE,
    BASE_TRANSACTIONS_PER_MINUTE,
)
from .models import (
    Customer,
    MinuteVolume,
    Transaction,
    new_transaction_id,
)

logger = logging.getLogger(__name__)

# Merchant ID pool (synthetic)
_MERCHANT_POOL = [f"MER{i:05d}" for i in range(1, 2001)]

# Status probabilities: mostly SUCCESS
_STATUS_WEIGHTS = {"SUCCESS": 0.96, "FAILED": 0.025, "PENDING": 0.015}


class TransactionGenerator:
    """
    Generates a stream of synthetic banking transactions.

    Parameters
    ----------
    customers        : List of Customer objects (from CustomerGenerator).
    behavior_model   : BehaviorModel instance.
    scenario_engine  : ScenarioEngine instance.
    seed             : RNG seed for reproducibility.
    output_txn_file  : Path to the raw transactions CSV.
    output_vol_file  : Path to the minute-volume CSV.
    """

    def __init__(
        self,
        customers:       List[Customer],
        behavior_model:  BehaviorModel,
        scenario_engine: ScenarioEngine,
        seed:            int  = RANDOM_SEED,
        output_txn_file: Path = OUTPUT_TRANSACTIONS_FILE,
        output_vol_file: Path = OUTPUT_MINUTE_VOLUME_FILE,
    ):
        self.customers       = customers
        self.behavior_model  = behavior_model
        self.scenario_engine = scenario_engine
        self.seed            = seed
        self.output_txn_file = output_txn_file
        self.output_vol_file = output_vol_file

        # Seed all random sources
        self._rng   = np.random.default_rng(seed)
        random.seed(seed)

        # Internal counters
        self._txn_counter   = 0
        self._total_txns    = 0
        self._normal_txns   = 0
        self._scenario_txns = 0

        # Pre-compute normalised location weights
        lw = np.array(LOCATION_WEIGHTS, dtype=float)
        self._loc_probs = lw / lw.sum()

        # Pre-compute status probs
        statuses, sw = zip(*_STATUS_WEIGHTS.items())
        sw = np.array(sw, dtype=float)
        self._statuses   = list(statuses)
        self._status_probs = sw / sw.sum()

        # Minute-volume accumulator
        self._minute_volumes: List[MinuteVolume] = []

    # ------------------------------------------------------------------
    # Historical mode: generate all at once
    # ------------------------------------------------------------------

    def generate_historical(
        self,
        start_time:      datetime,
        simulation_days: int = SIMULATION_DAYS,
    ) -> None:
        """
        Generate `simulation_days` worth of transactions starting from
        `start_time`, writing output in batches.

        Progress is logged at each day boundary.
        """
        self.output_txn_file.parent.mkdir(parents=True, exist_ok=True)
        self.output_vol_file.parent.mkdir(parents=True, exist_ok=True)

        total_minutes = simulation_days * 24 * 60
        current_ts    = start_time

        txn_batch: List[dict] = []
        txn_file_open = False

        logger.info("Starting historical generation: %d days, %d minutes total.",
                    simulation_days, total_minutes)

        with open(self.output_txn_file, "w", newline="", encoding="utf-8") as txn_f, \
             open(self.output_vol_file, "w", newline="", encoding="utf-8") as vol_f:

            txn_writer = csv.DictWriter(txn_f, fieldnames=Transaction.csv_columns())
            vol_writer = csv.DictWriter(vol_f, fieldnames=MinuteVolume.csv_columns())
            txn_writer.writeheader()
            vol_writer.writeheader()

            for minute_idx in range(total_minutes):
                elapsed_days = minute_idx / 1440.0

                # Day-level progress log
                if minute_idx % 1440 == 0:
                    day_num = (minute_idx // 1440) + 1
                    logger.info("  Day %d / %d", day_num, simulation_days)

                # --- Determine this minute's scenario state ---
                multiplier, scenario_label = self.scenario_engine.get_minute_state(current_ts)

                # --- Sample how many transactions this minute ---
                base_count = self.behavior_model.sample_volume(current_ts, elapsed_days)
                count = max(0, int(round(base_count * multiplier)))

                # --- Generate individual transactions ---
                minute_amount = 0.0
                for _ in range(count):
                    txn = self._generate_one_transaction(
                        ts             = current_ts,
                        scenario_label = scenario_label,
                    )
                    txn_batch.append(txn.to_dict())
                    minute_amount += txn.amount
                    self._total_txns += 1
                    if scenario_label == "NORMAL":
                        self._normal_txns += 1
                    else:
                        self._scenario_txns += 1

                    # Flush batch to disk
                    if len(txn_batch) >= WRITE_BATCH_SIZE:
                        txn_writer.writerows(txn_batch)
                        txn_batch.clear()

                # --- Record minute-level volume ---
                mv = MinuteVolume(
                    timestamp         = current_ts,
                    transaction_count = count,
                    total_amount      = round(minute_amount, 2),
                    scenario_label    = scenario_label,
                )
                vol_writer.writerow(mv.to_dict())

                current_ts += timedelta(minutes=1)

            # Final flush
            if txn_batch:
                txn_writer.writerows(txn_batch)

        logger.info(
            "Historical generation complete — %d transactions written.",
            self._total_txns,
        )

    # ------------------------------------------------------------------
    # Real-time simulation mode
    # ------------------------------------------------------------------

    def generate_realtime(
        self,
        start_time: datetime,
        speed:      float = 60.0,
        max_days:   Optional[int] = None,
    ):
        """
        Yield transactions one simulated minute at a time with a real-time
        delay between minutes.

        This is a *generator function* — the caller is responsible for
        consuming yielded Transaction objects and applying any delay.

        Parameters
        ----------
        start_time : Simulation start timestamp.
        speed      : Simulated-minutes per real-second.
                     speed=60 -> 1 sim-minute takes 1 real-second.
                     speed=1  -> real-time (1 sim-second = 1 real-second).
        max_days   : Stop after this many simulated days (None = run forever).
        """
        import time

        real_seconds_per_sim_minute = 60.0 / speed
        current_ts   = start_time
        minute_idx   = 0
        max_minutes  = (max_days * 1440) if max_days else None

        logger.info(
            "Real-time simulation started. Speed=%.1fx  (%.2f real-s per sim-minute).",
            speed, real_seconds_per_sim_minute,
        )

        while True:
            if max_minutes is not None and minute_idx >= max_minutes:
                logger.info("Real-time simulation reached max_days limit — stopping.")
                break

            elapsed_days = minute_idx / 1440.0
            multiplier, scenario_label = self.scenario_engine.get_minute_state(current_ts)

            base_count = self.behavior_model.sample_volume(current_ts, elapsed_days)
            count      = max(0, int(round(base_count * multiplier)))

            for _ in range(count):
                txn = self._generate_one_transaction(current_ts, scenario_label)
                self._total_txns += 1
                yield txn

            current_ts  += timedelta(minutes=1)
            minute_idx  += 1

            time.sleep(real_seconds_per_sim_minute)

    # ------------------------------------------------------------------
    # Core transaction builder
    # ------------------------------------------------------------------

    def _generate_one_transaction(
        self,
        ts:             datetime,
        scenario_label: str,
    ) -> Transaction:
        """
        Build a single realistic Transaction for the given minute.

        Steps
        -----
        1. Pick a customer from the pool (weighted by their daily volume).
        2. Sample transaction type and channel for this hour.
        3. Sample an amount from the customer's distribution * type modifier.
        4. Compute balance_before / balance_after.
        5. Assign merchant, device, beneficiary as appropriate.
        """
        self._txn_counter += 1
        customer = self._pick_customer()

        # --- Type and channel (hour-aware) ---
        txn_type = self._sample_transaction_type(ts)
        channel  = self._sample_channel(ts, customer)

        # --- Amount ---
        amount = self._sample_amount(txn_type, customer)

        # --- Balance simulation ---
        balance_before = round(max(0.0, customer.balance), 2)
        if txn_type in ("DEPOSIT",):
            customer.balance += amount
        else:
            customer.balance = max(0.0, customer.balance - amount)
        balance_after = round(customer.balance, 2)

        # --- Location (biased toward customer's home city) ---
        location = self._sample_location(customer)

        # --- Status ---
        status = str(self._rng.choice(self._statuses, p=self._status_probs))

        # --- Optional enrichment ---
        merchant_id        = None
        beneficiary_acct   = None
        device_id          = f"DEV{self._rng.integers(1, 100_000):06d}"

        if txn_type in ("PURCHASE", "PAYMENT", "POS"):
            merchant_id = random.choice(_MERCHANT_POOL)

        if txn_type in ("TRANSFER", "MOBILE_TRANSFER"):
            # Pick a random beneficiary that is not the sender
            bene_idx = int(self._rng.integers(0, len(self.customers)))
            beneficiary_acct = self.customers[bene_idx].account_id

        txn = Transaction(
            transaction_id      = new_transaction_id(self._txn_counter),
            customer_id         = customer.customer_id,
            account_id          = customer.account_id,
            timestamp           = ts,
            amount              = amount,
            transaction_type    = txn_type,
            channel             = channel,
            location            = location,
            currency            = CURRENCY,
            status              = status,
            merchant_id         = merchant_id,
            device_id           = device_id,
            balance_before      = balance_before,
            balance_after       = balance_after,
            beneficiary_account = beneficiary_acct,
            scenario_label      = scenario_label,
        )
        return txn

    # ------------------------------------------------------------------
    # Sampling helpers
    # ------------------------------------------------------------------

    def _pick_customer(self) -> Customer:
        """
        Pick a customer, loosely weighted by their normal_daily_volume.
        Higher-volume customers appear more frequently.
        """
        idx = int(self._rng.integers(0, len(self.customers)))
        return self.customers[idx]

    def _sample_transaction_type(self, ts: datetime) -> str:
        type_probs = self.behavior_model.transaction_type_probs(ts)
        types  = list(type_probs.keys())
        probs  = np.array(list(type_probs.values()), dtype=float)
        probs /= probs.sum()
        return str(self._rng.choice(types, p=probs))

    def _sample_channel(self, ts: datetime, customer: Customer) -> str:
        chan_probs = self.behavior_model.channel_probs(ts)

        # Blend global probs with customer's preferred channel (30 % pull)
        prefs = {c: 0.0 for c in chan_probs}
        prefs[customer.preferred_channel] = 0.30

        blended = {
            c: 0.70 * chan_probs.get(c, 0.0) + 0.30 * prefs.get(c, 0.0)
            for c in chan_probs
        }
        channels = list(blended.keys())
        probs    = np.array(list(blended.values()), dtype=float)
        if probs.sum() == 0:
            probs = np.ones(len(probs))
        probs /= probs.sum()
        return str(self._rng.choice(channels, p=probs))

    def _sample_amount(self, txn_type: str, customer: Customer) -> float:
        """
        Sample a transaction amount using:
          1. The base lognormal distribution for this transaction type.
          2. A customer-level shift (their personal amount_mean).
          3. A customer-type multiplier (BUSINESS / CORPORATE are larger).
        """
        dist_name, params = AMOUNT_DISTRIBUTIONS.get(
            txn_type, ("lognormal", (6.0, 0.8))
        )

        if dist_name == "lognormal":
            base_mean, base_sigma = params
            # Blend the type baseline with the customer's personal mean
            blended_mean  = 0.6 * base_mean + 0.4 * customer.normal_amount_mean
            blended_sigma = 0.7 * base_sigma + 0.3 * customer.normal_amount_sigma
            raw = float(self._rng.lognormal(mean=blended_mean, sigma=blended_sigma))
        elif dist_name == "gamma":
            shape, scale = params
            raw = float(self._rng.gamma(shape=shape, scale=scale))
        else:  # uniform
            low, high = params
            raw = float(self._rng.uniform(low=low, high=high))

        multiplier = CUSTOMER_TYPE_AMOUNT_MULTIPLIER.get(customer.customer_type, 1.0)
        amount = round(max(1.0, raw * multiplier), 2)
        return amount

    def _sample_location(self, customer: Customer) -> str:
        """
        70 % of transactions occur in the customer's home location;
        30 % occur at a random location weighted by city activity.
        """
        if self._rng.random() < 0.70:
            return customer.home_location
        return str(self._rng.choice(LOCATIONS, p=self._loc_probs))

    # ------------------------------------------------------------------
    # Summary statistics
    # ------------------------------------------------------------------

    @property
    def total_transactions(self) -> int:
        return self._total_txns

    @property
    def normal_transactions(self) -> int:
        return self._normal_txns

    @property
    def scenario_transactions(self) -> int:
        return self._scenario_txns
