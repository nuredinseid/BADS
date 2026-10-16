"""
models.py
---------
Data model definitions for the BADS Transaction Generator.

Uses Python dataclasses for lightweight, typed, serialisable records.
These are plain data containers — no business logic lives here.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
import uuid


# ---------------------------------------------------------------------------
# Customer / Account
# ---------------------------------------------------------------------------

@dataclass
class Customer:
    """
    Represents a synthetic bank customer and their primary account.

    Fields
    ------
    customer_id         : Unique identifier, e.g. CUS000001
    account_id          : Primary account identifier, e.g. ACC100001
    customer_type       : INDIVIDUAL | BUSINESS | CORPORATE
    age_group           : Age bracket (for INDIVIDUAL) — not used for Business/Corp
    home_location       : Primary city/region for this customer
    normal_daily_volume : Expected number of transactions per day under normal conditions
    normal_amount_mean  : Centre of the customer's typical transaction amount (log-scale)
    normal_amount_sigma : Spread of the customer's typical transaction amount (log-scale)
    preferred_channel   : Channel this customer tends to use most
    balance             : Current synthetic account balance (updated during generation)
    """
    customer_id:          str
    account_id:           str
    customer_type:        str           # INDIVIDUAL | BUSINESS | CORPORATE
    age_group:            str           # e.g. "18-25", "26-35", "36-50", "51+"
    home_location:        str
    normal_daily_volume:  float         # mean transactions/day for this customer
    normal_amount_mean:   float         # lognormal mean (log-scale)
    normal_amount_sigma:  float         # lognormal sigma (log-scale)
    preferred_channel:    str
    balance:              float = 10_000.0   # initial synthetic balance (ETB)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    """
    Represents a single synthetic banking transaction.

    Core fields are mandatory.  Optional fields are populated where meaningful
    and left as None otherwise; they are written as empty strings in CSV output.

    The `scenario_label` field is a ground-truth marker injected by the
    scenario engine.  It must NOT be used by the BADS detection pipeline —
    it exists solely to evaluate whether the detector found injected events.
    """
    # --- Mandatory fields ---
    transaction_id:     str
    customer_id:        str
    account_id:         str
    timestamp:          datetime
    amount:             float
    transaction_type:   str     # DEPOSIT | WITHDRAWAL | TRANSFER | PAYMENT |
                                # PURCHASE | ATM_WITHDRAWAL | MOBILE_TRANSFER
    channel:            str     # ATM | MOBILE | WEB | POS | BRANCH | AGENT
    location:           str
    currency:           str
    status:             str     # SUCCESS | FAILED | PENDING

    # --- Optional / enrichment fields ---
    merchant_id:        Optional[str]   = None
    device_id:          Optional[str]   = None
    balance_before:     Optional[float] = None
    balance_after:      Optional[float] = None
    beneficiary_account: Optional[str] = None

    # --- Ground-truth label (do NOT expose to detection pipeline) ---
    scenario_label:     str = "NORMAL"   # NORMAL | SPIKE | DROP | ...

    def to_dict(self) -> dict:
        """Return a flat dict suitable for CSV serialisation."""
        d = asdict(self)
        # Convert datetime to ISO string
        d["timestamp"] = self.timestamp.strftime("%Y-%m-%dT%H:%M:%S")
        # Replace None with empty string for clean CSV output
        for k, v in d.items():
            if v is None:
                d[k] = ""
        return d

    @staticmethod
    def csv_columns() -> list:
        """Ordered list of CSV column names, matching to_dict() output."""
        return [
            "transaction_id",
            "customer_id",
            "account_id",
            "timestamp",
            "amount",
            "transaction_type",
            "channel",
            "location",
            "currency",
            "status",
            "merchant_id",
            "device_id",
            "balance_before",
            "balance_after",
            "beneficiary_account",
            "scenario_label",
        ]


# ---------------------------------------------------------------------------
# Scenario (injected anomaly period)
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    """
    Represents a single controlled anomaly period injected by the scenario engine.

    This is written to scenario_ground_truth.csv for later BADS evaluation.
    It is NOT included inside individual transaction records (only the
    `scenario_label` tag on each Transaction references it by type).

    Fields
    ------
    scenario_id     : Unique identifier, e.g. SC001
    scenario_type   : SPIKE | DROP | NORMAL (for completeness)
    start_time      : When the anomaly period begins
    end_time        : When the anomaly period ends
    duration_minutes: Calculated duration
    intensity       : Multiplier applied (e.g. 2.4 for a SPIKE, 0.3 for a DROP)
    affected_channel: Channel targeted by the scenario (None = all channels)
    affected_location: Location targeted (None = all locations)
    description     : Human-readable summary
    """
    scenario_id:         str
    scenario_type:       str          # SPIKE | DROP
    start_time:          datetime
    end_time:            datetime
    duration_minutes:    int
    intensity:           float        # volume multiplier
    affected_channel:    Optional[str] = None
    affected_location:   Optional[str] = None
    description:         str          = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start_time"] = self.start_time.strftime("%Y-%m-%d %H:%M:%S")
        d["end_time"]   = self.end_time.strftime("%Y-%m-%d %H:%M:%S")
        for k, v in d.items():
            if v is None:
                d[k] = ""
        return d

    @staticmethod
    def csv_columns() -> list:
        return [
            "scenario_id",
            "scenario_type",
            "start_time",
            "end_time",
            "duration_minutes",
            "intensity",
            "affected_channel",
            "affected_location",
            "description",
        ]


# ---------------------------------------------------------------------------
# Minute-level volume record
# ---------------------------------------------------------------------------

@dataclass
class MinuteVolume:
    """
    Aggregated transaction count and total amount for a single calendar minute.

    This is the primary time-series fed into Prophet for forecasting.

    Fields
    ------
    timestamp         : The minute bucket (seconds always 00)
    transaction_count : Number of transactions in this minute
    total_amount      : Sum of transaction amounts in this minute
    scenario_label    : Dominant label in this minute (NORMAL | SPIKE | DROP)
    """
    timestamp:         datetime
    transaction_count: int
    total_amount:      float
    scenario_label:    str = "NORMAL"

    def to_dict(self) -> dict:
        return {
            "timestamp":         self.timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
            "transaction_count": self.transaction_count,
            "total_amount":      round(self.total_amount, 2),
            "scenario_label":    self.scenario_label,
        }

    @staticmethod
    def csv_columns() -> list:
        return ["timestamp", "transaction_count", "total_amount", "scenario_label"]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def new_transaction_id(counter: int) -> str:
    """Generate a zero-padded transaction ID, e.g. TX00000001."""
    return f"TX{counter:08d}"


def new_scenario_id(counter: int) -> str:
    """Generate a zero-padded scenario ID, e.g. SC001."""
    return f"SC{counter:03d}"
