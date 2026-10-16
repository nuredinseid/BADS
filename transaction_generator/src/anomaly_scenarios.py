"""
anomaly_scenarios.py
--------------------
Controlled anomaly scenario injection for the BADS Transaction Generator.

Design principles
~~~~~~~~~~~~~~~~~
* The ScenarioEngine is responsible for deciding WHEN an anomaly period begins
  and ends, and WHAT its intensity is.
* It does NOT generate transactions itself — it only tells the transaction
  generator whether a given minute is inside an anomaly period and how to
  scale the volume.
* Scenarios are sustained periods (multiple consecutive minutes), NOT isolated
  single-transaction anomalies.
* All injected scenarios are recorded in scenario_ground_truth.csv for later
  BADS evaluation.  These labels must NOT be fed into the detection pipeline.

Supported scenario types
~~~~~~~~~~~~~~~~~~~~~~~~
  SPIKE  — volume significantly above the normal expected rate
  DROP   — volume significantly below the normal expected rate

The design leaves room for future extensions:
  HIGH_VALUE_BURST, CHANNEL_SURGE, LOCATION_SURGE, TRANSACTION_FLOOD
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import (
    SPIKE_PROBABILITY,
    DROP_PROBABILITY,
    MIN_SPIKE_DURATION,
    MAX_SPIKE_DURATION,
    MIN_DROP_DURATION,
    MAX_DROP_DURATION,
    SPIKE_MULTIPLIER_MIN,
    SPIKE_MULTIPLIER_MAX,
    DROP_MULTIPLIER_MIN,
    DROP_MULTIPLIER_MAX,
    GROUND_TRUTH_FILE,
)
from .models import Scenario, new_scenario_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Active scenario state (lightweight internal representation)
# ---------------------------------------------------------------------------

@dataclass
class _ActiveScenario:
    """Tracks an in-progress scenario across consecutive minutes."""
    scenario_id:       str
    scenario_type:     str          # SPIKE | DROP
    start_time:        datetime
    end_time:          datetime     # exclusive
    intensity:         float        # volume multiplier
    affected_channel:  Optional[str]
    affected_location: Optional[str]

    def is_active(self, ts: datetime) -> bool:
        return self.start_time <= ts < self.end_time

    def label(self) -> str:
        return self.scenario_type  # "SPIKE" or "DROP"


# ---------------------------------------------------------------------------
# ScenarioEngine
# ---------------------------------------------------------------------------

class ScenarioEngine:
    """
    Manages scenario injection over the course of the simulation.

    Usage
    -----
    engine = ScenarioEngine(seed=42)

    # At the start of each simulated minute:
    multiplier, label = engine.get_minute_state(current_timestamp)

    # After simulation:
    engine.save_ground_truth()

    Parameters
    ----------
    seed               : RNG seed for reproducibility.
    spike_probability  : Per-minute probability that a new SPIKE begins.
    drop_probability   : Per-minute probability that a new DROP begins.
    """

    def __init__(
        self,
        seed:              int   = 0,
        spike_probability: float = SPIKE_PROBABILITY,
        drop_probability:  float = DROP_PROBABILITY,
    ):
        self._rng              = np.random.default_rng(seed)
        self.spike_probability = spike_probability
        self.drop_probability  = drop_probability

        self._active: Optional[_ActiveScenario] = None   # only one at a time
        self._completed: List[Scenario]          = []
        self._scenario_counter                   = 0

    # ------------------------------------------------------------------
    # Main per-minute interface
    # ------------------------------------------------------------------

    def get_minute_state(self, ts: datetime) -> Tuple[float, str]:
        """
        Evaluate the scenario state for the minute starting at `ts`.

        Returns
        -------
        (volume_multiplier, scenario_label)
          volume_multiplier : 1.0 = normal; >1.0 = spike; <1.0 = drop
          scenario_label    : "NORMAL" | "SPIKE" | "DROP"

        Side-effects
        ------------
        May start a new scenario, or close a finished one.
        """
        # 1. Check if the current active scenario has ended
        if self._active is not None and not self._active.is_active(ts):
            self._close_active(ts)

        # 2. Try to start a new scenario (only when none is running)
        if self._active is None:
            self._maybe_start_scenario(ts)

        # 3. Return the current state
        if self._active is not None and self._active.is_active(ts):
            return self._active.intensity, self._active.label()

        return 1.0, "NORMAL"

    # ------------------------------------------------------------------
    # Convenience: inject a scenario explicitly (for testing / CLI)
    # ------------------------------------------------------------------

    def inject_scenario(
        self,
        scenario_type:     str,
        start_time:        datetime,
        duration_minutes:  int,
        intensity:         Optional[float] = None,
        affected_channel:  Optional[str]   = None,
        affected_location: Optional[str]   = None,
    ) -> None:
        """
        Force-inject a scenario at a specific time regardless of probability.

        Useful for:
          * CLI --inject-scenario flags
          * Unit testing
          * Guaranteed scenario placement for evaluation datasets

        Parameters
        ----------
        scenario_type    : "SPIKE" or "DROP"
        start_time       : When the scenario begins
        duration_minutes : How long it lasts
        intensity        : Override the volume multiplier (uses default range if None)
        affected_channel : Restrict to a specific channel (None = all)
        affected_location: Restrict to a specific location (None = all)
        """
        if intensity is None:
            intensity = self._sample_intensity(scenario_type)

        end_time = start_time + timedelta(minutes=duration_minutes)
        self._scenario_counter += 1
        sid = new_scenario_id(self._scenario_counter)

        self._active = _ActiveScenario(
            scenario_id       = sid,
            scenario_type     = scenario_type,
            start_time        = start_time,
            end_time          = end_time,
            intensity         = intensity,
            affected_channel  = affected_channel,
            affected_location = affected_location,
        )
        logger.info(
            "Injected %s scenario %s: %s to %s (x%.2f)",
            scenario_type, sid,
            start_time.strftime("%Y-%m-%d %H:%M"),
            end_time.strftime("%Y-%m-%d %H:%M"),
            intensity,
        )

    # ------------------------------------------------------------------
    # Ground truth persistence
    # ------------------------------------------------------------------

    def save_ground_truth(self) -> None:
        """Write all completed scenarios to scenario_ground_truth.csv."""
        GROUND_TRUTH_FILE.parent.mkdir(parents=True, exist_ok=True)

        if not self._completed:
            logger.info("No scenarios were injected — ground truth file will be empty.")
            rows = []
        else:
            rows = [s.to_dict() for s in self._completed]

        df = pd.DataFrame(rows, columns=Scenario.csv_columns()) if rows else \
             pd.DataFrame(columns=Scenario.csv_columns())

        df.to_csv(GROUND_TRUTH_FILE, index=False)
        logger.info(
            "Ground truth saved -> %s  (%d scenario(s))",
            GROUND_TRUTH_FILE, len(self._completed)
        )

    # ------------------------------------------------------------------
    # Summary statistics
    # ------------------------------------------------------------------

    def summary(self) -> Dict:
        spikes = [s for s in self._completed if s.scenario_type == "SPIKE"]
        drops  = [s for s in self._completed if s.scenario_type == "DROP"]
        return {
            "total_scenarios": len(self._completed),
            "spike_count":     len(spikes),
            "drop_count":      len(drops),
            "scenarios":       self._completed,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _maybe_start_scenario(self, ts: datetime) -> None:
        """Roll dice and potentially start a new SPIKE or DROP."""
        roll = self._rng.random()

        if roll < self.spike_probability:
            self._start_new_scenario("SPIKE", ts)
        elif roll < self.spike_probability + self.drop_probability:
            self._start_new_scenario("DROP", ts)

    def _start_new_scenario(self, scenario_type: str, ts: datetime) -> None:
        """Create and activate a new scenario of the given type."""
        duration = int(self._rng.integers(
            low  = MIN_SPIKE_DURATION if scenario_type == "SPIKE" else MIN_DROP_DURATION,
            high = MAX_SPIKE_DURATION if scenario_type == "SPIKE" else MAX_DROP_DURATION,
            endpoint=True,
        ))
        intensity  = self._sample_intensity(scenario_type)
        end_time   = ts + timedelta(minutes=duration)

        self._scenario_counter += 1
        sid = new_scenario_id(self._scenario_counter)

        self._active = _ActiveScenario(
            scenario_id       = sid,
            scenario_type     = scenario_type,
            start_time        = ts,
            end_time          = end_time,
            intensity         = intensity,
            affected_channel  = None,
            affected_location = None,
        )
        logger.debug(
            "Scenario %s started: type=%s start=%s end=%s intensity=%.2f",
            sid, scenario_type,
            ts.strftime("%Y-%m-%d %H:%M"),
            end_time.strftime("%Y-%m-%d %H:%M"),
            intensity,
        )

    def _close_active(self, ts: datetime) -> None:
        """Finalise the active scenario and move it to the completed list."""
        a = self._active
        duration = int((a.end_time - a.start_time).total_seconds() / 60)

        completed_scenario = Scenario(
            scenario_id       = a.scenario_id,
            scenario_type     = a.scenario_type,
            start_time        = a.start_time,
            end_time          = a.end_time,
            duration_minutes  = duration,
            intensity         = a.intensity,
            affected_channel  = a.affected_channel,
            affected_location = a.affected_location,
            description       = self._describe(a),
        )
        self._completed.append(completed_scenario)
        logger.debug(
            "Scenario %s completed at %s (duration=%d min)",
            a.scenario_id, ts.strftime("%Y-%m-%d %H:%M"), duration,
        )
        self._active = None

    def _sample_intensity(self, scenario_type: str) -> float:
        """Sample a random intensity multiplier for the given scenario type."""
        if scenario_type == "SPIKE":
            return round(float(self._rng.uniform(SPIKE_MULTIPLIER_MIN, SPIKE_MULTIPLIER_MAX)), 3)
        else:
            return round(float(self._rng.uniform(DROP_MULTIPLIER_MIN, DROP_MULTIPLIER_MAX)), 3)

    @staticmethod
    def _describe(a: _ActiveScenario) -> str:
        duration = int((a.end_time - a.start_time).total_seconds() / 60)
        ch_str   = f"channel={a.affected_channel}" if a.affected_channel   else "all channels"
        loc_str  = f"location={a.affected_location}" if a.affected_location else "all locations"
        return (
            f"{a.scenario_type} x{a.intensity:.2f} for {duration} min "
            f"({ch_str}, {loc_str})"
        )
