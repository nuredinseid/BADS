"""
behavior_model.py
-----------------
Time-based behavioural model for the BADS Transaction Generator.

Responsibilities
~~~~~~~~~~~~~~~~
* Compute the expected transaction volume for any given calendar minute,
  reflecting realistic time-of-day, day-of-week, and long-term trend patterns.
* Provide channel and transaction-type probability adjustments that vary by
  time of day (e.g. Branch is zero outside business hours).
* Keep all temporal logic in one place so the transaction generator and
  scenario engine can share it without duplication.
"""

import logging
import math
import numpy as np
from datetime import datetime
from typing import Dict

from .config import (
    BASE_TRANSACTIONS_PER_MINUTE,
    HOUR_WEIGHTS,
    DAY_OF_WEEK_WEIGHTS,
    MONTH_WEIGHTS,
    ETHIOPIAN_HOLIDAYS,
    HOLIDAY_PRE_DAY_MULTIPLIER,
    HOLIDAY_POST_DAY_MULTIPLIER,
    SPECIAL_PERIODS,
    LONG_TERM_TREND_RATE,
    VOLUME_NOISE_SIGMA,
    SIMULATION_DAYS,
    TRANSACTION_TYPE_WEIGHTS,
    CHANNEL_WEIGHTS,
)

logger = logging.getLogger(__name__)

# Pre-normalise the hour weights so they represent fractions of the peak hour
_HOUR_WEIGHTS_NORM = np.array(HOUR_WEIGHTS, dtype=float)
_HOUR_WEIGHTS_NORM = _HOUR_WEIGHTS_NORM / _HOUR_WEIGHTS_NORM.max()


class BehaviorModel:
    """
    Computes time-dependent transaction rate and channel/type distributions.

    Parameters
    ----------
    base_tpm    : Base transactions-per-minute at peak conditions.
    total_days  : Total simulation length in days (used for trend calculation).
    seed        : RNG seed for reproducible Gaussian noise.
    """

    def __init__(
        self,
        base_tpm:   float = BASE_TRANSACTIONS_PER_MINUTE,
        total_days: int   = SIMULATION_DAYS,
        seed:       int   = 0,
    ):
        self.base_tpm   = base_tpm
        self.total_days = total_days
        self._rng       = np.random.default_rng(seed)

        # Cache normalised weights
        self._dow_max     = max(DAY_OF_WEEK_WEIGHTS.values())
        self._type_probs  = self._normalise(TRANSACTION_TYPE_WEIGHTS)
        self._chan_probs   = self._normalise(CHANNEL_WEIGHTS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def expected_volume(self, ts: datetime, elapsed_days: float = 0.0) -> float:
        """
        Return the expected (mean) number of transactions for the minute
        starting at `ts`.

        Parameters
        ----------
        ts           : The timestamp of the minute.
        elapsed_days : How many days have elapsed since the simulation start
                       (used for the long-term trend calculation).
        """
        hour_factor = _HOUR_WEIGHTS_NORM[ts.hour]
        dow_factor  = DAY_OF_WEEK_WEIGHTS[ts.weekday()] / self._dow_max
        trend_factor = self._trend_factor(elapsed_days)
        
        # NEW: Add seasonal/monthly factor
        month_factor = MONTH_WEIGHTS.get(ts.month, 1.0)
        
        # NEW: Add holiday factor
        holiday_factor = self._get_holiday_factor(ts)
        
        # NEW: Add special period factor
        special_period_factor = self._get_special_period_factor(ts)

        expected = (self.base_tpm * hour_factor * dow_factor * 
                   month_factor * holiday_factor * special_period_factor * 
                   trend_factor)
        return max(0.0, expected)

    def sample_volume(self, ts: datetime, elapsed_days: float = 0.0) -> int:
        """
        Draw a realistic transaction count for the given minute by adding
        Gaussian noise around the expected volume.

        Returns an integer (≥ 0).
        """
        mu    = self.expected_volume(ts, elapsed_days)
        sigma = mu * VOLUME_NOISE_SIGMA
        count = int(round(max(0.0, self._rng.normal(mu, sigma))))
        return count

    def transaction_type_probs(self, ts: datetime) -> Dict[str, float]:
        """
        Return a dict of {transaction_type: probability} adjusted for the
        current hour.

        Rules applied
        ~~~~~~~~~~~~~
        * BRANCH is only available 08:00–17:00 on weekdays.
        * ATM_WITHDRAWAL is boosted slightly during daytime (07:00–20:00).
        * MOBILE_TRANSFER is uniformly available.
        """
        probs = dict(self._type_probs)  # copy

        hour    = ts.hour
        is_wday = ts.weekday() < 5

        # Branch closed outside business hours
        if not (8 <= hour < 17 and is_wday):
            probs["PAYMENT"]  = probs.get("PAYMENT", 0) * 0.5  # fewer bill payments too
            probs["DEPOSIT"]  = probs.get("DEPOSIT", 0) * 0.6
            probs.pop("BRANCH", None)   # handled in channel probs instead

        # ATM slightly boosted daytime
        if 7 <= hour < 20:
            probs["ATM_WITHDRAWAL"] = probs.get("ATM_WITHDRAWAL", 0) * 1.3

        # Late-night: mostly mobile/ATM
        if hour < 6 or hour >= 22:
            probs["MOBILE_TRANSFER"] = probs.get("MOBILE_TRANSFER", 0) * 1.5
            probs["ATM_WITHDRAWAL"]  = probs.get("ATM_WITHDRAWAL",  0) * 1.2

        return self._normalise(probs)

    def channel_probs(self, ts: datetime) -> Dict[str, float]:
        """
        Return a dict of {channel: probability} adjusted for the current hour.

        Rules applied
        ~~~~~~~~~~~~~
        * BRANCH only active 08:00–17:00 on weekdays.
        * ATM boosted 07:00–22:00, low overnight.
        * MOBILE/WEB available 24 h, peak evenings.
        * POS boosted 10:00–20:00 (shopping hours).
        * AGENT active 08:00–18:00.
        """
        probs = dict(self._chan_probs)
        hour    = ts.hour
        is_wday = ts.weekday() < 5

        # Branch
        if not (8 <= hour < 17 and is_wday):
            probs["BRANCH"] = 0.0
        else:
            probs["BRANCH"] = probs.get("BRANCH", 0) * 1.2

        # ATM
        if 7 <= hour < 22:
            probs["ATM"] = probs.get("ATM", 0) * 1.3
        elif hour < 5:
            probs["ATM"] = probs.get("ATM", 0) * 0.2

        # POS (retail hours)
        if 10 <= hour < 20:
            probs["POS"] = probs.get("POS", 0) * 1.4
        else:
            probs["POS"] = probs.get("POS", 0) * 0.5

        # Mobile peak evenings
        if 18 <= hour < 23:
            probs["MOBILE"] = probs.get("MOBILE", 0) * 1.3

        # Agent — daytime only
        if not (8 <= hour < 18):
            probs["AGENT"] = 0.0

        # Web — slightly boosted evenings
        if 18 <= hour < 23:
            probs["WEB"] = probs.get("WEB", 0) * 1.2

        return self._normalise(probs)

    def smooth_hour_weight(self, hour: float) -> float:
        """
        Return a smoothly interpolated hour weight for a fractional hour value.
        Uses cosine interpolation between the two surrounding integer-hour weights.

        Useful for any code that wants sub-hourly granularity.
        """
        h0 = int(hour) % 24
        h1 = (h0 + 1) % 24
        frac = hour - int(hour)
        w0 = _HOUR_WEIGHTS_NORM[h0]
        w1 = _HOUR_WEIGHTS_NORM[h1]
        # Cosine interpolation for a smooth curve
        t = (1 - math.cos(math.pi * frac)) / 2
        return w0 * (1 - t) + w1 * t

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(weights: Dict[str, float]) -> Dict[str, float]:
        """Return a copy of `weights` normalised so values sum to 1.0."""
        total = sum(weights.values())
        if total <= 0:
            # Fallback: uniform distribution
            n = len(weights)
            return {k: 1.0 / n for k in weights}
        return {k: v / total for k, v in weights.items()}

    def _trend_factor(self, elapsed_days: float) -> float:
        """
        Linear growth trend.  At elapsed_days=0 the factor is 1.0.
        At elapsed_days=total_days it is (1 + LONG_TERM_TREND_RATE).
        """
        if self.total_days <= 0:
            return 1.0
        frac = min(elapsed_days / self.total_days, 1.0)
        return 1.0 + LONG_TERM_TREND_RATE * frac
    
    def _get_holiday_factor(self, ts: datetime) -> float:
        """
        Return a volume multiplier based on Ethiopian holidays.
        
        Returns:
        - Holiday multiplier if it's a holiday (typically < 1.0, banks closed/low activity)
        - HOLIDAY_PRE_DAY_MULTIPLIER (1.5) if it's the day before a holiday
        - HOLIDAY_POST_DAY_MULTIPLIER (1.2) if it's the day after a holiday
        - 1.0 otherwise (normal day)
        """
        from datetime import timedelta
        
        month = ts.month
        day = ts.day
        
        # Check if today is a holiday
        for h_month, h_day, h_name, h_multiplier in ETHIOPIAN_HOLIDAYS:
            if month == h_month and day == h_day:
                return h_multiplier
        
        # Check if tomorrow is a holiday (today = pre-holiday)
        tomorrow = ts + timedelta(days=1)
        for h_month, h_day, h_name, h_multiplier in ETHIOPIAN_HOLIDAYS:
            if tomorrow.month == h_month and tomorrow.day == h_day:
                return HOLIDAY_PRE_DAY_MULTIPLIER
        
        # Check if yesterday was a holiday (today = post-holiday)
        yesterday = ts - timedelta(days=1)
        for h_month, h_day, h_name, h_multiplier in ETHIOPIAN_HOLIDAYS:
            if yesterday.month == h_month and yesterday.day == h_day:
                return HOLIDAY_POST_DAY_MULTIPLIER
        
        return 1.0  # Normal day
    
    def _get_special_period_factor(self, ts: datetime) -> float:
        """
        Return a volume multiplier for special periods like:
        - Fiscal year end (June-July)
        - Back to school (September)
        - Christmas shopping (December)
        - Ramadan period
        - Easter week
        """
        month = ts.month
        day = ts.day
        
        for start_m, start_d, end_m, end_d, period_name, multiplier in SPECIAL_PERIODS:
            # Simple date range check (works for same year ranges)
            if start_m == end_m:
                # Same month
                if month == start_m and start_d <= day <= end_d:
                    return multiplier
            elif start_m < end_m:
                # Spans multiple months
                if (month == start_m and day >= start_d) or \
                   (month == end_m and day <= end_d) or \
                   (start_m < month < end_m):
                    return multiplier
            else:
                # Wraps around year end (e.g., Dec to Jan)
                if (month == start_m and day >= start_d) or \
                   (month == end_m and day <= end_d) or \
                   (month > start_m or month < end_m):
                    return multiplier
        
        return 1.0  # No special period
