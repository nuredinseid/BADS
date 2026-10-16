"""
customer_generator.py
---------------------
Generates a synthetic population of bank customers and their accounts.

Design principles
~~~~~~~~~~~~~~~~~
* Every customer has stable, internally consistent behaviour parameters that
  are set once at creation time and reused throughout the simulation.
* Business accounts transact more frequently and with larger amounts than
  Individual accounts.  Corporate accounts sit at the top of the scale.
* No real personal information is used.  All names, IDs and values are
  synthetic.
* The population is fully reproducible given the same random seed.
"""

import logging
import numpy as np
import pandas as pd
from typing import List

from .config import (
    NUM_CUSTOMERS,
    CUSTOMER_TYPE_DISTRIBUTION,
    LOCATIONS,
    LOCATION_WEIGHTS,
    CHANNEL_WEIGHTS,
    RANDOM_SEED,
    OUTPUT_CUSTOMERS_FILE,
)
from .models import Customer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-type behavioural parameters
# These define the *range* from which each customer's personal parameters
# are drawn.  Individual variation keeps customers distinct from one another.
# ---------------------------------------------------------------------------

_TYPE_PARAMS = {
    #                  daily_vol_mean  daily_vol_sigma  amount_mean(log) amount_sigma(log)
    "INDIVIDUAL": dict(daily_vol_mean=3.5,  daily_vol_sigma=1.5,  amount_mean=6.0,  amount_sigma=0.8),
    "BUSINESS":   dict(daily_vol_mean=18.0, daily_vol_sigma=6.0,  amount_mean=8.0,  amount_sigma=0.9),
    "CORPORATE":  dict(daily_vol_mean=60.0, daily_vol_sigma=15.0, amount_mean=10.0, amount_sigma=1.0),
}

_AGE_GROUPS = ["18-25", "26-35", "36-50", "51+"]
_AGE_GROUP_WEIGHTS = [0.18, 0.32, 0.32, 0.18]


class CustomerGenerator:
    """
    Generates and manages the synthetic customer population.

    Usage
    -----
    gen = CustomerGenerator(num_customers=500, seed=42)
    customers = gen.generate()          # List[Customer]
    gen.save_to_csv()                   # writes data/customers.csv
    """

    def __init__(self, num_customers: int = NUM_CUSTOMERS, seed: int = RANDOM_SEED):
        self.num_customers = num_customers
        self.seed = seed
        self._rng = np.random.default_rng(seed)
        self._customers: List[Customer] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self) -> List[Customer]:
        """
        Build the full customer population.

        Returns a list of Customer objects with stable behavioural parameters.
        Call this once before running the transaction generator.
        """
        logger.info("Generating %d synthetic customers …", self.num_customers)

        customer_types = self._sample_customer_types()
        locations      = self._sample_locations()
        channels       = self._sample_preferred_channels()

        customers = []
        for i in range(self.num_customers):
            ctype   = customer_types[i]
            params  = _TYPE_PARAMS[ctype]

            # Daily transaction volume — clamp to at least 1
            daily_vol = max(1.0, self._rng.normal(
                params["daily_vol_mean"], params["daily_vol_sigma"]
            ))

            # Personal amount distribution (log-scale parameters)
            amt_mean  = self._rng.normal(params["amount_mean"],  0.15)
            amt_sigma = max(0.3, self._rng.normal(params["amount_sigma"], 0.05))

            age_group = (
                self._rng.choice(_AGE_GROUPS, p=_AGE_GROUP_WEIGHTS)
                if ctype == "INDIVIDUAL"
                else "N/A"
            )

            customer = Customer(
                customer_id          = f"CUS{i+1:06d}",
                account_id           = f"ACC{100_000 + i + 1:06d}",
                customer_type        = ctype,
                age_group            = age_group,
                home_location        = locations[i],
                normal_daily_volume  = round(daily_vol, 2),
                normal_amount_mean   = round(amt_mean,  4),
                normal_amount_sigma  = round(amt_sigma, 4),
                preferred_channel    = channels[i],
                balance              = self._initial_balance(ctype),
            )
            customers.append(customer)

        self._customers = customers
        logger.info("Customer generation complete — %d customers created.", len(customers))
        return customers

    def save_to_csv(self) -> None:
        """Write the customer population to data/customers.csv."""
        if not self._customers:
            logger.warning("No customers to save — call generate() first.")
            return
        OUTPUT_CUSTOMERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        rows = [c.to_dict() for c in self._customers]
        df = pd.DataFrame(rows)
        df.to_csv(OUTPUT_CUSTOMERS_FILE, index=False)
        logger.info("Customers saved -> %s", OUTPUT_CUSTOMERS_FILE)

    @property
    def customers(self) -> List[Customer]:
        return self._customers

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sample_customer_types(self) -> List[str]:
        """Draw customer types according to the configured distribution."""
        types = list(CUSTOMER_TYPE_DISTRIBUTION.keys())
        probs = list(CUSTOMER_TYPE_DISTRIBUTION.values())
        return list(self._rng.choice(types, size=self.num_customers, p=probs))

    def _sample_locations(self) -> List[str]:
        """Assign a home location to each customer."""
        # Normalise weights in case they don't sum to exactly 1
        w = np.array(LOCATION_WEIGHTS, dtype=float)
        w = w / w.sum()
        return list(self._rng.choice(LOCATIONS, size=self.num_customers, p=w))

    def _sample_preferred_channels(self) -> List[str]:
        """Each customer has a preferred channel sampled from the global weights."""
        channels = list(CHANNEL_WEIGHTS.keys())
        weights  = np.array(list(CHANNEL_WEIGHTS.values()), dtype=float)
        weights  = weights / weights.sum()
        return list(self._rng.choice(channels, size=self.num_customers, p=weights))

    def _initial_balance(self, customer_type: str) -> float:
        """Set a realistic synthetic opening balance per customer type."""
        if customer_type == "INDIVIDUAL":
            return round(float(self._rng.lognormal(mean=9.5, sigma=0.8)), 2)   # ~13 000 ETB median
        elif customer_type == "BUSINESS":
            return round(float(self._rng.lognormal(mean=11.5, sigma=0.9)), 2)  # ~98 000 ETB median
        else:  # CORPORATE
            return round(float(self._rng.lognormal(mean=13.5, sigma=1.0)), 2)  # ~730 000 ETB median
