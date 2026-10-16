"""
config.py
---------
Central configuration for the BADS Transaction Generator.

All tunable parameters live here. No numeric constants should be scattered
across other modules. Import this module wherever a setting is needed.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths  (relative so the generator is portable across machines)
# ---------------------------------------------------------------------------
BASE_DIR        = Path(__file__).resolve().parent.parent   # transaction_generator/
DATA_DIR        = BASE_DIR / "data"
SCENARIOS_DIR   = DATA_DIR / "scenarios"
LOGS_DIR        = BASE_DIR / "logs"

OUTPUT_TRANSACTIONS_FILE    = DATA_DIR / "generated_transactions.csv"
OUTPUT_MINUTE_VOLUME_FILE   = DATA_DIR / "minute_transaction_volume.csv"
OUTPUT_CUSTOMERS_FILE       = DATA_DIR / "customers.csv"
GROUND_TRUTH_FILE           = DATA_DIR / "scenario_ground_truth.csv"
LOG_FILE                    = LOGS_DIR / "generator.log"

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
RANDOM_SEED = 42

# ---------------------------------------------------------------------------
# Customer population
# ---------------------------------------------------------------------------
NUM_CUSTOMERS = 500          # Reduced default for faster dev runs; scale to 5000 for full runs

# Distribution of customer types  (must sum to 1.0)
CUSTOMER_TYPE_DISTRIBUTION = {
    "INDIVIDUAL": 0.75,
    "BUSINESS":   0.20,
    "CORPORATE":  0.05,
}

# ---------------------------------------------------------------------------
# Simulation time
# ---------------------------------------------------------------------------
SIMULATION_DAYS = 30          # Default historical simulation length (days)

# ---------------------------------------------------------------------------
# Transaction volume baseline
# BASE_TRANSACTIONS_PER_MINUTE is the mean volume under normal conditions
# during peak hours on a normal weekday.  The behaviour model scales this
# up and down according to time-of-day and day-of-week weights.
# ---------------------------------------------------------------------------
BASE_TRANSACTIONS_PER_MINUTE = 100

# Batch size for writing to disk (number of transactions per flush)
WRITE_BATCH_SIZE = 10_000

# ---------------------------------------------------------------------------
# Transaction types and their base probability weights
# (weights are normalised internally; they do not need to sum to 1)
# ---------------------------------------------------------------------------
TRANSACTION_TYPE_WEIGHTS = {
    "DEPOSIT":          0.12,
    "WITHDRAWAL":       0.10,
    "TRANSFER":         0.18,
    "PAYMENT":          0.20,
    "PURCHASE":         0.22,
    "ATM_WITHDRAWAL":   0.10,
    "MOBILE_TRANSFER":  0.08,
}

# ---------------------------------------------------------------------------
# Channels and their base probability weights
# ---------------------------------------------------------------------------
CHANNEL_WEIGHTS = {
    "ATM":    0.15,
    "MOBILE": 0.30,
    "WEB":    0.18,
    "POS":    0.20,
    "BRANCH": 0.10,
    "AGENT":  0.07,
}

# ---------------------------------------------------------------------------
# Ethiopian locations (synthetic)
# ---------------------------------------------------------------------------
LOCATIONS = [
    "Addis Ababa",
    "Bahir Dar",
    "Debre Birhan",
    "Adama",
    "Hawassa",
    "Dire Dawa",
    "Jimma",
    "Mekelle",
    "Gondar",
    "Dessie",
    "Arba Minch",
    "Shashamane",
    "Nekemte",
    "Harar",
    "Woldia",
]

# Weight of each location (proportional to simulated population / activity)
LOCATION_WEIGHTS = [
    0.35,   # Addis Ababa — dominant financial hub
    0.08,
    0.04,
    0.08,
    0.07,
    0.07,
    0.05,
    0.05,
    0.05,
    0.04,
    0.03,
    0.03,
    0.03,
    0.02,
    0.01,
]

CURRENCY = "ETB"

# ---------------------------------------------------------------------------
# Amount distributions per transaction type
# Each entry: (distribution, params)
# Distributions: "lognormal", "gamma", "uniform"
# lognormal params: (mean_log, sigma_log)   — mean/std of the log
# gamma params:     (shape, scale)
# uniform params:   (low, high)
# ---------------------------------------------------------------------------
AMOUNT_DISTRIBUTIONS = {
    # Small-to-medium cash-like deposits
    "DEPOSIT":        ("lognormal", (6.5, 0.9)),    # median ≈ 665 ETB
    # Moderate withdrawals
    "WITHDRAWAL":     ("lognormal", (6.0, 0.8)),    # median ≈ 403 ETB
    # Wide range for transfers
    "TRANSFER":       ("lognormal", (7.5, 1.2)),    # median ≈ 1808 ETB
    # Bill payments — moderate
    "PAYMENT":        ("lognormal", (6.2, 0.7)),    # median ≈ 493 ETB
    # Retail purchases — typically smaller
    "PURCHASE":       ("lognormal", (5.5, 0.8)),    # median ≈ 245 ETB
    # ATM cash — capped, round numbers
    "ATM_WITHDRAWAL": ("lognormal", (5.8, 0.6)),    # median ≈ 330 ETB
    # Mobile P2P transfers
    "MOBILE_TRANSFER":("lognormal", (6.8, 1.0)),    # median ≈ 898 ETB
}

# Customer-type multipliers on top of the base amount distribution
CUSTOMER_TYPE_AMOUNT_MULTIPLIER = {
    "INDIVIDUAL": 1.0,
    "BUSINESS":   4.0,
    "CORPORATE":  15.0,
}

# ---------------------------------------------------------------------------
# Time-of-day weights  (index 0 = 00:00–00:59, index 23 = 23:00–23:59)
# These are *relative* weights; the behaviour model normalises them.
# ---------------------------------------------------------------------------
HOUR_WEIGHTS = [
    0.10,   # 00
    0.07,   # 01
    0.05,   # 02
    0.04,   # 03
    0.04,   # 04
    0.08,   # 05
    0.15,   # 06
    0.35,   # 07  morning ramp-up
    0.65,   # 08
    0.90,   # 09  business hours open
    1.00,   # 10  peak morning
    0.95,   # 11
    0.85,   # 12  lunch dip
    0.80,   # 13
    0.90,   # 14  afternoon peak
    0.95,   # 15
    0.90,   # 16
    0.85,   # 17  evening activity
    0.80,   # 18
    0.70,   # 19
    0.55,   # 20
    0.40,   # 21
    0.25,   # 22
    0.15,   # 23
]

# ---------------------------------------------------------------------------
# Day-of-week weights  (0=Monday … 6=Sunday)
# ---------------------------------------------------------------------------
DAY_OF_WEEK_WEIGHTS = {
    0: 1.00,   # Monday
    1: 1.00,   # Tuesday
    2: 1.00,   # Wednesday
    3: 1.02,   # Thursday
    4: 1.05,   # Friday  (pre-weekend boost)
    5: 0.70,   # Saturday
    6: 0.45,   # Sunday
}

# ---------------------------------------------------------------------------
# Seasonal/Monthly patterns (Ethiopian calendar considerations)
# Month multipliers: 1=January ... 12=December (Gregorian calendar)
# ---------------------------------------------------------------------------
MONTH_WEIGHTS = {
    1:  1.05,   # January - New Year spending aftermath
    2:  1.00,   # February - normal
    3:  1.10,   # March - pre-Easter preparation
    4:  1.25,   # April - HIGH (Ethiopian New Year Meskerem, fiscal year end)
    5:  1.15,   # May - post-holiday spending
    6:  1.08,   # June - mid-year
    7:  1.05,   # July - summer activities
    8:  1.00,   # August - normal
    9:  1.12,   # September - Ethiopian New Year (Enkutatash), school fees
    10: 1.08,   # October - Meskel holiday period
    11: 1.10,   # November - pre-Christmas shopping
    12: 1.20,   # December - Christmas, end of year (Gregorian calendar)
}

# ---------------------------------------------------------------------------
# Ethiopian Public Holidays (approximate Gregorian dates - some vary by year)
# Format: (month, day, "holiday_name", volume_multiplier)
# multiplier < 1.0 = banks closed/low activity
# multiplier > 1.0 = high activity (day before/after holiday)
# ---------------------------------------------------------------------------
ETHIOPIAN_HOLIDAYS = [
    # Major holidays where banks are closed or have very low activity
    (1, 7, "Ethiopian Christmas (Genna)", 0.30),
    (1, 19, "Epiphany (Timket)", 0.35),
    (3, 2, "Battle of Adwa Victory Day", 0.40),
    (5, 1, "International Labour Day", 0.35),
    (5, 5, "Patriots Victory Day", 0.40),
    (5, 28, "Derg Downfall Day", 0.40),
    (9, 11, "Ethiopian New Year (Enkutatash)", 0.25),
    (9, 27, "Meskel (Finding of True Cross)", 0.30),
    (12, 25, "Christmas (Gregorian)", 0.25),
    
    # Islamic holidays (approximate - lunar calendar, dates shift)
    # Eid al-Fitr and Eid al-Adha (using 2024 approximate dates)
    (4, 10, "Eid al-Fitr", 0.30),
    (6, 16, "Eid al-Adha (Arafa)", 0.30),
    (9, 15, "Mawlid (Prophet's Birthday)", 0.40),
]

# Days before holidays typically have HIGH activity (people withdraw cash)
HOLIDAY_PRE_DAY_MULTIPLIER = 1.50   # Day before holiday = +50% volume
HOLIDAY_POST_DAY_MULTIPLIER = 1.20  # Day after holiday = +20% volume

# ---------------------------------------------------------------------------
# Special periods with sustained high/low activity
# Format: (start_month, start_day, end_month, end_day, "period_name", multiplier)
# ---------------------------------------------------------------------------
SPECIAL_PERIODS = [
    # Ethiopian fiscal year end (high business transactions)
    (6, 25, 7, 10, "Fiscal Year End Rush", 1.35),
    
    # Back to school season (September)
    (9, 1, 9, 20, "Back to School Season", 1.25),
    
    # Christmas shopping season (December)
    (12, 10, 12, 24, "Christmas Shopping Season", 1.40),
    
    # Ethiopian Easter week (variable, using April approximation)
    (4, 15, 4, 22, "Easter Week", 1.30),
    
    # Ramadan month (lower daytime activity - approximate dates)
    (3, 11, 4, 9, "Ramadan Period", 0.85),
]

# ---------------------------------------------------------------------------
# Weekend patterns - Ethiopian weekends
# Saturday is a half-working day for many businesses
# Sunday is the main day off
# ---------------------------------------------------------------------------
WEEKEND_SATURDAY_MULTIPLIER = 0.70  # Saturday - partial banking
WEEKEND_SUNDAY_MULTIPLIER = 0.45    # Sunday - minimal activity

# ---------------------------------------------------------------------------
# Long-term trend
# A small upward drift applied linearly over the simulation period.
# 0.0 = flat, 0.10 = +10% growth by the final day.
# ---------------------------------------------------------------------------
LONG_TERM_TREND_RATE = 0.05     # 5% total growth across the full period

# ---------------------------------------------------------------------------
# Noise
# Gaussian noise added to the per-minute volume (sigma as fraction of mean)
# ---------------------------------------------------------------------------
VOLUME_NOISE_SIGMA = 0.08

# ---------------------------------------------------------------------------
# Anomaly / scenario probabilities
# These control how often a new scenario begins on any given minute.
# ---------------------------------------------------------------------------
SPIKE_PROBABILITY = 0.0015     # probability per minute that a new SPIKE starts
DROP_PROBABILITY  = 0.0008     # probability per minute that a new DROP starts

# Duration ranges (minutes)
MIN_SPIKE_DURATION = 10
MAX_SPIKE_DURATION = 30

MIN_DROP_DURATION  = 10
MAX_DROP_DURATION  = 30

# Intensity ranges (multiplier applied to normal volume)
SPIKE_MULTIPLIER_MIN = 1.8
SPIKE_MULTIPLIER_MAX = 3.0

DROP_MULTIPLIER_MIN  = 0.15
DROP_MULTIPLIER_MAX  = 0.55

# Fraction of scenario transactions that carry scenario_label != NORMAL
# (the rest are still generated normally alongside the extra/missing volume)
# This label is for ground-truth evaluation only.
SCENARIO_LABEL_FIELD = "scenario_label"   # column name in the output CSV

# ---------------------------------------------------------------------------
# Real-time simulation
# ---------------------------------------------------------------------------
# Default speed multiplier: 1 simulated second = 1 real second.
# speed=60 means 1 simulated minute takes 1 real second.
DEFAULT_REALTIME_SPEED = 60     # 1 sim-minute = 1 real-second by default

# ---------------------------------------------------------------------------
# Validation thresholds
# ---------------------------------------------------------------------------
MAX_REASONABLE_AMOUNT    = 5_000_000   # ETB — flag if any single txn exceeds this
MIN_REASONABLE_AMOUNT    = 1.0         # ETB — flag amounts below this
MAX_REASONABLE_TXN_MIN   = 10_000      # warn if any minute exceeds this
MIN_REASONABLE_TXN_MIN   = 0           # zero is valid (very quiet minute)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = "INFO"
