# BADS Transaction Generator

Simulated Banking Transaction Generator for the **Bank Anomaly Detection System (BADS)**.

This component generates realistic synthetic banking transactions that will be
fed into the BADS streaming and detection pipeline (Kafka → Prophet → Isolation
Forest → Hybrid Detection Engine).

---

## Project Structure

```
transaction_generator/
├── src/
│   ├── __init__.py
│   ├── config.py               ← all configuration constants
│   ├── models.py               ← Customer, Transaction, Scenario dataclasses
│   ├── customer_generator.py   ← synthetic customer population
│   ├── behavior_model.py       ← time-of-day / day-of-week patterns
│   ├── anomaly_scenarios.py    ← SPIKE / DROP scenario injection
│   ├── transaction_generator.py← core generation engine
│   ├── data_validator.py       ← post-generation validation & summary
│   └── main.py                 ← CLI entry point
│
├── data/                       ← generated output (git-ignored)
│   ├── customers.csv
│   ├── generated_transactions.csv
│   ├── minute_transaction_volume.csv
│   ├── scenario_ground_truth.csv
│   └── scenarios/
│
├── logs/                       ← generator.log (git-ignored)
├── requirements.txt
├── README.md
└── .gitignore
```

---

## Installation (Windows)

### 1 — Create and activate a virtual environment

```powershell
cd "c:\Users\Noor\Desktop\final year\transaction_generator"
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution, run once:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 2 — Install dependencies

```powershell
pip install -r requirements.txt
```

---

## Usage

All commands must be run from inside the `transaction_generator/` directory
with the virtual environment active.

### Historical mode — generate a complete dataset

```powershell
python -m src.main --mode historical --days 30
python -m src.main --mode historical --days 60 --seed 42
python -m src.main --mode historical --days 90 --customers 5000 --seed 42
```

### Real-time simulation mode

```powershell
# 1 simulated minute = 1 real second
python -m src.main --mode realtime --speed 60

# Faster: 10 simulated minutes = 1 real second
python -m src.main --mode realtime --speed 600

# Run 7 simulated days then stop
python -m src.main --mode realtime --speed 600 --days 7
```

### Override scenario probabilities

```powershell
python -m src.main --mode historical --days 30 --spike-prob 0.005 --drop-prob 0.002
```

### Full option reference

| Flag             | Default   | Description                                             |
|------------------|-----------|---------------------------------------------------------|
| `--mode`         | historical| `historical` or `realtime`                              |
| `--days`         | 30        | Simulated days                                          |
| `--customers`    | 500       | Number of synthetic customers                           |
| `--seed`         | 42        | Random seed (reproducibility)                           |
| `--speed`        | 60        | Realtime speed (sim-min per real-sec)                   |
| `--base-tpm`     | 100       | Base transactions per minute at peak                    |
| `--spike-prob`   | 0.0015    | Per-minute spike start probability                      |
| `--drop-prob`    | 0.0008    | Per-minute drop start probability                       |
| `--output-dir`   | data/     | Override output directory                               |
| `--start-date`   | today     | Simulation start date (YYYY-MM-DD)                      |
| `--log-level`    | INFO      | DEBUG / INFO / WARNING / ERROR                          |

---

## Output Files

### `data/customers.csv`
One row per synthetic customer.

| Column               | Description                                      |
|----------------------|--------------------------------------------------|
| customer_id          | Unique ID, e.g. CUS000001                        |
| account_id           | Primary account ID, e.g. ACC100001              |
| customer_type        | INDIVIDUAL / BUSINESS / CORPORATE                |
| age_group            | Age bracket (INDIVIDUAL only)                    |
| home_location        | Primary city                                     |
| normal_daily_volume  | Expected transactions/day                        |
| normal_amount_mean   | Log-scale mean for personal amounts              |
| normal_amount_sigma  | Log-scale sigma for personal amounts             |
| preferred_channel    | ATM / MOBILE / WEB / POS / BRANCH / AGENT       |
| balance              | Synthetic opening balance (ETB)                  |

---

### `data/generated_transactions.csv`
One row per transaction.

| Column              | Description                                       |
|---------------------|---------------------------------------------------|
| transaction_id      | Unique ID, e.g. TX00000001                       |
| customer_id         | References customers.csv                          |
| account_id          | References customers.csv                          |
| timestamp           | ISO format YYYY-MM-DDTHH:MM:SS                   |
| amount              | Transaction amount in ETB                         |
| transaction_type    | DEPOSIT / WITHDRAWAL / TRANSFER / PAYMENT / PURCHASE / ATM_WITHDRAWAL / MOBILE_TRANSFER |
| channel             | ATM / MOBILE / WEB / POS / BRANCH / AGENT        |
| location            | Ethiopian city (synthetic)                        |
| currency            | ETB                                               |
| status              | SUCCESS / FAILED / PENDING                        |
| merchant_id         | For PURCHASE / PAYMENT transactions               |
| device_id           | Synthetic device identifier                       |
| balance_before      | Account balance before transaction                |
| balance_after       | Account balance after transaction                 |
| beneficiary_account | For TRANSFER / MOBILE_TRANSFER                   |
| scenario_label      | **Ground-truth only** — NORMAL / SPIKE / DROP    |

> ⚠️ `scenario_label` is for BADS evaluation only. The detection pipeline must
> NOT read this column.

---

### `data/minute_transaction_volume.csv`
One row per calendar minute — the primary time-series for Prophet forecasting.

| Column            | Description                                         |
|-------------------|-----------------------------------------------------|
| timestamp         | Minute bucket (seconds = 00)                        |
| transaction_count | Number of transactions in this minute               |
| total_amount      | Sum of transaction amounts in this minute (ETB)     |
| scenario_label    | Dominant label in this minute                       |

---

### `data/scenario_ground_truth.csv`
One row per injected anomaly period.

| Column            | Description                                         |
|-------------------|-----------------------------------------------------|
| scenario_id       | Unique ID, e.g. SC001                               |
| scenario_type     | SPIKE / DROP                                        |
| start_time        | When the event began                                |
| end_time          | When the event ended                                |
| duration_minutes  | Length of the event                                 |
| intensity         | Volume multiplier (e.g. 2.4 for SPIKE, 0.3 for DROP)|
| affected_channel  | Restricted channel (empty = all)                    |
| affected_location | Restricted location (empty = all)                   |
| description       | Human-readable summary                              |

---

## Normal Behaviour Model

### Time-of-day
Transaction volume follows a realistic daily curve:

```
00–05 → very low (0.04–0.10×)
05–07 → low (0.08–0.15×)
07–09 → morning ramp-up (0.35–0.65×)
09–12 → high (0.90–1.00×)  ← peak
12–14 → moderate (0.80–0.85×)
14–17 → high again (0.90–0.95×)
17–20 → tapering evening (0.70–0.85×)
20–23 → low (0.25–0.55×)
```

### Day-of-week
Weekdays have higher volume than weekends:

```
Mon–Thu  ×1.00–1.02
Friday   ×1.05   (pre-weekend boost)
Saturday ×0.70
Sunday   ×0.45
```

### Channel hours
- **BRANCH**: weekdays 08:00–17:00 only
- **ATM**: active 07:00–22:00, minimal overnight
- **POS**: boosted 10:00–20:00 (retail hours)
- **MOBILE/WEB**: 24 hours, peak evenings
- **AGENT**: 08:00–18:00 only

### Long-term trend
Volume grows by 5 % linearly across the simulation period, mimicking realistic
banking growth for Prophet to learn.

---

## SPIKE / DROP Scenario Injection

### How it works

The `ScenarioEngine` rolls dice every simulated minute. If a roll falls below
the configured probability threshold, a new sustained anomaly period begins.

```
Normal minute:   volume = BehaviorModel.sample_volume() × 1.0
SPIKE minute:    volume = BehaviorModel.sample_volume() × [1.8 – 3.0]
DROP minute:     volume = BehaviorModel.sample_volume() × [0.15 – 0.55]
```

Scenarios last **10 – 30 minutes** by default, creating sustained events that
the BADS continuous event detector is designed to identify.

### Example SPIKE event

```
13:20  normal  (98 txns)
13:21  normal  (102 txns)
13:22  normal  (95 txns)
13:23  SPIKE   (218 txns)   ← ×2.2 multiplier
13:24  SPIKE   (231 txns)
13:25  SPIKE   (205 txns)
...
13:35  SPIKE   (226 txns)
13:36  normal  (101 txns)
```

### Configuring scenarios

Edit `src/config.py` or pass CLI flags:

```python
SPIKE_PROBABILITY      = 0.0015   # ~1 spike every ~11 hours of simulation
DROP_PROBABILITY       = 0.0008

MIN_SPIKE_DURATION     = 10       # minutes
MAX_SPIKE_DURATION     = 30
SPIKE_MULTIPLIER_MIN   = 1.8
SPIKE_MULTIPLIER_MAX   = 3.0

MIN_DROP_DURATION      = 10
MAX_DROP_DURATION      = 30
DROP_MULTIPLIER_MIN    = 0.15
DROP_MULTIPLIER_MAX    = 0.55
```

---

## Example Generated Records

### Transaction
```json
{
  "transaction_id":      "TX00004217",
  "customer_id":         "CUS000123",
  "account_id":          "ACC100123",
  "timestamp":           "2026-10-02T09:31:00",
  "amount":              1250.50,
  "transaction_type":    "TRANSFER",
  "channel":             "MOBILE",
  "location":            "Addis Ababa",
  "currency":            "ETB",
  "status":              "SUCCESS",
  "merchant_id":         "",
  "device_id":           "DEV047821",
  "balance_before":      32450.75,
  "balance_after":       31200.25,
  "beneficiary_account": "ACC100442",
  "scenario_label":      "NORMAL"
}
```

### Minute volume
```csv
timestamp,transaction_count,total_amount,scenario_label
2026-10-02T09:31:00,97,84320.40,NORMAL
2026-10-02T09:32:00,104,91850.70,NORMAL
2026-10-02T09:33:00,221,193402.15,SPIKE
```

### Validation output
```
=============================================
     BADS TRANSACTION GENERATOR SUMMARY
=============================================
  Customers:                           500
  Transactions:                  2,149,312
  Simulation period:                30 day(s)

  Normal transactions:              97.8%
  Scenario transactions:             2.2%

  Spike events:                         6
  Drop events:                          3

  Avg transactions/minute:           49.5
  Max transactions/minute:            157
  Min transactions/minute:              0

  Validation:                   PASSED ✓
=============================================
```

---

## Future Kafka Integration

The generator is designed so that adding a Kafka producer requires **no changes**
to the core generation logic.

Current architecture:

```
TransactionGenerator._generate_one_transaction()
              │
              ▼
        Transaction object
              │
              ▼
        CSV Writer  ← current output
```

Future architecture:

```
TransactionGenerator._generate_one_transaction()
              │
              ▼
        Transaction object
              │
        ┌─────┴──────┐
        │             │
   CSV Writer    KafkaProducer  ← add this class
                      │
                 Kafka topic: banking.transactions
```

To add Kafka, create `src/kafka_producer.py` with a class that accepts a
`Transaction` object and calls `producer.send(topic, txn.to_dict())`.
Then pass it as an output sink to `TransactionGenerator` alongside the CSV writer.

No changes to `CustomerGenerator`, `BehaviorModel`, `ScenarioEngine`, or
`models.py` will be required.

---

## Reproducibility

Pass the same `--seed` value to get an identical dataset:

```powershell
python -m src.main --mode historical --days 30 --seed 42
# Produces identical output every time
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│           BADS Transaction Generator         │
│                                              │
│  CustomerGenerator   →  Customer pool        │
│  BehaviorModel       →  Volume + channel     │
│                          weights per minute  │
│  ScenarioEngine      →  SPIKE / DROP         │
│                          multipliers          │
│  TransactionGenerator→  Orchestrates above   │
│                          builds Transaction  │
│                          objects             │
│  DataValidator       →  Post-generation      │
│                          validation          │
│                                              │
│  Output:                                     │
│    customers.csv                             │
│    generated_transactions.csv                │
│    minute_transaction_volume.csv             │
│    scenario_ground_truth.csv                 │
└─────────────────────────────────────────────┘
              │
              │   (future)
              ▼
     Kafka → BADS Detection Pipeline
```
