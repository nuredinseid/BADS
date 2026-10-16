"""
data_validator.py
-----------------
Post-generation data validation and summary reporting for the BADS
Transaction Generator.

Checks performed
~~~~~~~~~~~~~~~~
1.  Transaction IDs are unique
2.  Timestamps are valid ISO datetimes
3.  Amounts are non-negative and within reasonable bounds
4.  Required fields have no missing values
5.  customer_id values exist in the customer file
6.  account_id values exist in the customer file
7.  transaction_type values are in the allowed set
8.  channel values are in the allowed set
9.  currency is consistent
10. status values are in the allowed set
11. Timestamps are monotonically non-decreasing
12. Transaction counts per minute are within reasonable bounds
13. Minute-volume file is consistent with the raw transaction file
14. scenario_label values are in the allowed set

A human-readable summary is printed to stdout and written to the log.
"""

import logging
from pathlib import Path
from typing import List, Optional

import pandas as pd
import numpy as np

from .config import (
    CURRENCY,
    MAX_REASONABLE_AMOUNT,
    MIN_REASONABLE_AMOUNT,
    MAX_REASONABLE_TXN_MIN,
    OUTPUT_TRANSACTIONS_FILE,
    OUTPUT_MINUTE_VOLUME_FILE,
    OUTPUT_CUSTOMERS_FILE,
    TRANSACTION_TYPE_WEIGHTS,
    CHANNEL_WEIGHTS,
)

logger = logging.getLogger(__name__)

# Allowed values
_VALID_TYPES    = set(TRANSACTION_TYPE_WEIGHTS.keys())
_VALID_CHANNELS = set(CHANNEL_WEIGHTS.keys())
_VALID_STATUSES = {"SUCCESS", "FAILED", "PENDING"}
_VALID_LABELS   = {"NORMAL", "SPIKE", "DROP",
                   "HIGH_VALUE_BURST", "CHANNEL_SURGE",
                   "LOCATION_SURGE", "TRANSACTION_FLOOD"}


class ValidationResult:
    """Accumulates validation issues and provides a summary."""

    def __init__(self):
        self.errors:   List[str] = []
        self.warnings: List[str] = []

    def error(self, msg: str):
        self.errors.append(msg)
        logger.error("VALIDATION ERROR: %s", msg)

    def warn(self, msg: str):
        self.warnings.append(msg)
        logger.warning("VALIDATION WARNING: %s", msg)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


class DataValidator:
    """
    Validates the generated CSV files and prints a generation summary.

    Parameters
    ----------
    txn_file      : Path to generated_transactions.csv
    vol_file      : Path to minute_transaction_volume.csv
    customer_file : Path to customers.csv
    """

    def __init__(
        self,
        txn_file:      Path = OUTPUT_TRANSACTIONS_FILE,
        vol_file:      Path = OUTPUT_MINUTE_VOLUME_FILE,
        customer_file: Path = OUTPUT_CUSTOMERS_FILE,
    ):
        self.txn_file      = txn_file
        self.vol_file      = vol_file
        self.customer_file = customer_file

    def validate(self) -> ValidationResult:
        """
        Run all validation checks.  Returns a ValidationResult with any
        errors / warnings collected.
        """
        result = ValidationResult()

        # --- Load files ---
        txn_df = self._load_csv(self.txn_file, result, "transactions")
        vol_df = self._load_csv(self.vol_file, result, "minute-volume")
        cus_df = self._load_csv(self.customer_file, result, "customers")

        if txn_df is None:
            result.error("Cannot validate — transaction file could not be loaded.")
            return result

        # --- Run checks ---
        self._check_unique_ids(txn_df, result)
        self._check_required_fields(txn_df, result)
        self._check_amounts(txn_df, result)
        self._check_timestamps(txn_df, result)
        self._check_categorical_fields(txn_df, result)
        self._check_currency(txn_df, result)

        if cus_df is not None:
            self._check_customer_references(txn_df, cus_df, result)

        if vol_df is not None:
            self._check_minute_volume(txn_df, vol_df, result)

        return result

    def print_summary(
        self,
        result:        ValidationResult,
        simulation_days: int            = 0,
        scenario_summary: Optional[dict] = None,
    ) -> None:
        """
        Print a human-readable generation summary to stdout.
        """
        txn_df = self._load_csv(self.txn_file, ValidationResult(), "transactions")
        vol_df = self._load_csv(self.vol_file,  ValidationResult(), "minute-volume")
        cus_df = self._load_csv(self.customer_file, ValidationResult(), "customers")

        # ---- Compute stats ----
        num_customers = len(cus_df) if cus_df is not None else "N/A"

        if txn_df is not None and len(txn_df) > 0:
            total_txns     = len(txn_df)
            normal_txns    = (txn_df["scenario_label"] == "NORMAL").sum()
            scenario_txns  = total_txns - normal_txns
            normal_pct     = 100.0 * normal_txns  / total_txns if total_txns > 0 else 0
            scenario_pct   = 100.0 * scenario_txns / total_txns if total_txns > 0 else 0
        else:
            total_txns = normal_txns = scenario_txns = 0
            normal_pct = scenario_pct = 0.0

        if vol_df is not None and len(vol_df) > 0:
            avg_tpm = vol_df["transaction_count"].mean()
            max_tpm = vol_df["transaction_count"].max()
            min_tpm = vol_df["transaction_count"].min()
        else:
            avg_tpm = max_tpm = min_tpm = 0

        spike_count = scenario_summary.get("spike_count", "N/A") if scenario_summary else "N/A"
        drop_count  = scenario_summary.get("drop_count",  "N/A") if scenario_summary else "N/A"

        validation_str = "PASSED" if result.passed else f"FAILED ({len(result.errors)} error(s))"

        divider = "=" * 45

        lines = [
            "",
            divider,
            "     BADS TRANSACTION GENERATOR SUMMARY",
            divider,
            f"  Customers:                  {num_customers:>12,}",
            f"  Transactions:               {total_txns:>12,}",
            f"  Simulation period:          {simulation_days:>11} day(s)",
            "",
            f"  Normal transactions:        {normal_pct:>11.1f}%",
            f"  Scenario transactions:      {scenario_pct:>11.1f}%",
            "",
            f"  Spike events:               {spike_count!s:>12}",
            f"  Drop events:                {drop_count!s:>12}",
            "",
            f"  Avg transactions/minute:    {avg_tpm:>11.1f}",
            f"  Max transactions/minute:    {max_tpm:>12}",
            f"  Min transactions/minute:    {min_tpm:>12}",
            "",
            f"  Validation:                 {validation_str}",
        ]
        if result.warnings:
            lines.append(f"  Warnings:                   {len(result.warnings)}")
        if result.errors:
            for e in result.errors:
                lines.append(f"    [ERROR] {e}")

        lines.append(divider)
        lines.append("")

        summary_text = "\n".join(lines)
        print(summary_text)
        logger.info(summary_text)

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_unique_ids(self, df: pd.DataFrame, r: ValidationResult):
        dupes = df["transaction_id"].duplicated().sum()
        if dupes > 0:
            r.error(f"Found {dupes} duplicate transaction_id values.")
        else:
            logger.debug("transaction_id uniqueness: OK")

    def _check_required_fields(self, df: pd.DataFrame, r: ValidationResult):
        required = [
            "transaction_id", "customer_id", "account_id", "timestamp",
            "amount", "transaction_type", "channel", "location",
            "currency", "status",
        ]
        for col in required:
            if col not in df.columns:
                r.error(f"Required column missing: '{col}'")
                continue
            nulls = df[col].isnull().sum()
            empties = (df[col].astype(str).str.strip() == "").sum()
            if nulls + empties > 0:
                r.error(f"Column '{col}' has {nulls + empties} missing/empty values.")

    def _check_amounts(self, df: pd.DataFrame, r: ValidationResult):
        if "amount" not in df.columns:
            return
        amounts = pd.to_numeric(df["amount"], errors="coerce")
        negatives = (amounts < 0).sum()
        too_low   = (amounts < MIN_REASONABLE_AMOUNT).sum()
        too_high  = (amounts > MAX_REASONABLE_AMOUNT).sum()

        if negatives > 0:
            r.error(f"{negatives} transactions have negative amounts.")
        if too_low > 0:
            r.warn(f"{too_low} transactions have amounts below {MIN_REASONABLE_AMOUNT} ETB.")
        if too_high > 0:
            r.warn(
                f"{too_high} transactions have amounts above "
                f"{MAX_REASONABLE_AMOUNT:,} ETB (review if unexpected)."
            )

    def _check_timestamps(self, df: pd.DataFrame, r: ValidationResult):
        if "timestamp" not in df.columns:
            return
        ts = pd.to_datetime(df["timestamp"], errors="coerce")
        invalid = ts.isnull().sum()
        if invalid > 0:
            r.error(f"{invalid} transactions have unparseable timestamps.")
        # Timestamps should be non-decreasing (within a minute bucket they may be equal)
        if len(ts.dropna()) > 1:
            diffs = ts.dropna().diff().dropna()
            backward = (diffs.dt.total_seconds() < 0).sum()
            if backward > 0:
                r.warn(
                    f"{backward} timestamp(s) go backward "
                    "(expected if not sorted — check generation order)."
                )

    def _check_categorical_fields(self, df: pd.DataFrame, r: ValidationResult):
        if "transaction_type" in df.columns:
            bad = ~df["transaction_type"].isin(_VALID_TYPES)
            if bad.any():
                r.error(
                    f"{bad.sum()} transactions have unknown transaction_type: "
                    f"{df.loc[bad, 'transaction_type'].unique().tolist()}"
                )
        if "channel" in df.columns:
            bad = ~df["channel"].isin(_VALID_CHANNELS)
            if bad.any():
                r.error(
                    f"{bad.sum()} transactions have unknown channel: "
                    f"{df.loc[bad, 'channel'].unique().tolist()}"
                )
        if "status" in df.columns:
            bad = ~df["status"].isin(_VALID_STATUSES)
            if bad.any():
                r.error(
                    f"{bad.sum()} transactions have unknown status: "
                    f"{df.loc[bad, 'status'].unique().tolist()}"
                )
        if "scenario_label" in df.columns:
            bad = ~df["scenario_label"].isin(_VALID_LABELS)
            if bad.any():
                r.error(
                    f"{bad.sum()} transactions have unknown scenario_label: "
                    f"{df.loc[bad, 'scenario_label'].unique().tolist()}"
                )

    def _check_currency(self, df: pd.DataFrame, r: ValidationResult):
        if "currency" not in df.columns:
            return
        bad = ~(df["currency"] == CURRENCY)
        if bad.any():
            r.warn(f"{bad.sum()} transactions have unexpected currency (expected {CURRENCY}).")

    def _check_customer_references(
        self, txn_df: pd.DataFrame, cus_df: pd.DataFrame, r: ValidationResult
    ):
        valid_cids = set(cus_df["customer_id"].astype(str))
        valid_aids = set(cus_df["account_id"].astype(str))

        if "customer_id" in txn_df.columns:
            unknown_cids = ~txn_df["customer_id"].astype(str).isin(valid_cids)
            if unknown_cids.any():
                r.error(f"{unknown_cids.sum()} transactions reference unknown customer_id.")

        if "account_id" in txn_df.columns:
            unknown_aids = ~txn_df["account_id"].astype(str).isin(valid_aids)
            if unknown_aids.any():
                r.error(f"{unknown_aids.sum()} transactions reference unknown account_id.")

    def _check_minute_volume(
        self, txn_df: pd.DataFrame, vol_df: pd.DataFrame, r: ValidationResult
    ):
        # Check per-minute counts are within bounds
        if "transaction_count" in vol_df.columns:
            counts = pd.to_numeric(vol_df["transaction_count"], errors="coerce")
            too_high = (counts > MAX_REASONABLE_TXN_MIN).sum()
            if too_high > 0:
                r.warn(
                    f"{too_high} minute(s) exceed {MAX_REASONABLE_TXN_MIN} "
                    "transactions — verify scenario intensity settings."
                )

        # Cross-check total count
        if "transaction_count" in vol_df.columns:
            vol_total = pd.to_numeric(vol_df["transaction_count"], errors="coerce").sum()
            txn_total = len(txn_df)
            diff = abs(int(vol_total) - txn_total)
            if diff > 0:
                r.warn(
                    f"Minute-volume total ({int(vol_total):,}) differs from "
                    f"transaction file row count ({txn_total:,}) by {diff}. "
                    "This may be due to failed transactions still being logged."
                )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _load_csv(
        path: Path, result: ValidationResult, label: str
    ) -> Optional[pd.DataFrame]:
        if not path.exists():
            result.error(f"File not found: {path}  ({label})")
            return None
        try:
            df = pd.read_csv(path, low_memory=False)
            logger.debug("Loaded %s: %d rows, %d cols", label, len(df), len(df.columns))
            return df
        except Exception as exc:
            result.error(f"Could not read {label} file ({path}): {exc}")
            return None
