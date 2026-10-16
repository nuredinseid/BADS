# BADS Real-Time Web Dashboard

## What It Does

The web dashboard generates banking transactions **in real-time** — 1 simulated minute every 1 real second — and displays them on a live updating web page.

You'll see:
- **Live transaction counts** updating every second
- **Real-time charts** showing volume and amounts
- **SPIKE and DROP events** highlighted in red/orange as they happen
- **Total transactions** accumulated since start
- **Current scenario status** (NORMAL / SPIKE / DROP)

---

## Quick Start

### Option 1: Using the PowerShell script

```powershell
.\RUN_DASHBOARD.ps1
```

### Option 2: Manual start

```powershell
.venv\Scripts\Activate.ps1
pip install flask
python web_app.py
```

Then open your browser to: **http://localhost:5000**

---

## What You'll See

### Dashboard Layout

```
┌────────────────────────────────────────────────────────────────┐
│  🏦 BADS Real-Time Transaction Generator                       │
│  ● Generating transactions every second...                     │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [Current Time]  [Total Transactions]  [Scenario]  [This Min] │
│    10:15:42           45,234           SPIKE         152 txns  │
│                                         x2.4                    │
│                                                                 │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Transaction Volume (Last 60 Minutes)                          │
│  ╔════════════════════════════════════════════════════════╗   │
│  ║                                                ▲       ║   │
│  ║                                              ▲ █ ▲     ║   │
│  ║                                            ▲ █ █ █ ▲   ║   │
│  ║    ▁▂▁▂▂▁▂▁▂▁▂▁▂▁▂▁▂▁▂▁▂▁▂▁▂▁▂▁▂▁█ █ █ █ █ █     ║   │
│  ╚════════════════════════════════════════════════════════╝   │
│                                                                 │
│  Transaction Amount (ETB)                                      │
│  ╔════════════════════════════════════════════════════════╗   │
│  ║  █     █         █                 █ █ █ █ █ █        ║   │
│  ║  █  █  █  █   █  █     █  █  █  █ █ █ █ █ █ █  █     ║   │
│  ╚════════════════════════════════════════════════════════╝   │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### Color Coding

- **Blue/Green**: Normal operations
- **Red**: SPIKE event (volume 1.8x – 3.0x higher than expected)
- **Orange**: DROP event (volume 0.15x – 0.55x lower than expected)

---

## How It Works

### The Generator Loop

Every 1 real second:

1. **Calculate expected volume** for the current simulated minute
   - Based on time-of-day (9am = busy, 3am = quiet)
   - Based on day-of-week (Monday = busy, Sunday = quiet)

2. **Check for scenarios**
   - Is a SPIKE or DROP event active?
   - If yes, multiply volume by intensity (e.g., ×2.5 for SPIKE)

3. **Generate that many transactions**
   - Pick random customers
   - Sample amounts from realistic distributions
   - Choose channels based on hour

4. **Update the dashboard**
   - Add the minute's data to the chart
   - Update total transaction count
   - Show current scenario status

### Example Timeline

```
00:00  Start (simulated midnight)
00:01  Generate 8 transactions (quiet night)
00:02  Generate 7 transactions
...
09:45  Generate 78 transactions (morning rush)
09:46  SPIKE STARTS — generate 142 transactions (×1.9)
09:47  SPIKE — generate 156 transactions
09:48  SPIKE — generate 138 transactions
...
10:03  SPIKE — generate 145 transactions
10:04  SPIKE ENDS — back to 82 transactions
10:05  Generate 76 transactions (normal)
```

All of this happens **live** — you see the chart spike in red as the event occurs.

---

## Use Cases

### 1. Live Demo for Presentations

Run the dashboard during your project presentation to show:
- How the banking system generates transactions continuously
- How SPIKE and DROP events look in real-time
- The realistic time-of-day volume patterns

### 2. Testing the BADS Pipeline

Once you build the Prophet + Isolation Forest detector:
1. Run this dashboard (generates data)
2. Run your BADS detector (consumes data from Kafka)
3. Compare: Did BADS detect the SPIKE that just appeared on the dashboard?

### 3. Understanding the Data

Watch the generator for 5–10 minutes to get an intuitive feel for:
- Normal transaction volume ranges
- How intense a ×2.5 SPIKE really is
- What a DROP (×0.3) looks like compared to normal

---

## Controlling the Generator

The generator **auto-starts** when you run `web_app.py`.

To stop it: Press **Ctrl+C** in the terminal.

---

## Configuration

Edit `web_app.py` to change:

```python
# Line 55: Number of customers
state.customers = CustomerGenerator(num_customers=200, seed=RANDOM_SEED).generate()

# Line 56: Base transactions per minute
state.behavior_model = BehaviorModel(base_tpm=80, total_days=365, seed=RANDOM_SEED + 1)

# Line 57: Scenario probabilities (higher = more frequent events)
state.scenario_engine = ScenarioEngine(seed=RANDOM_SEED + 2)
```

To increase SPIKE/DROP frequency, edit `src/config.py`:

```python
SPIKE_PROBABILITY = 0.005   # default: 0.0015 (increase for more spikes)
DROP_PROBABILITY  = 0.003   # default: 0.0008
```

---

## Technical Details

### Architecture

```
┌──────────────────┐
│  Flask Web App   │  ← Serves HTML + API
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Generator Thread │  ← Runs in background
│  (1 min/second)  │
└────────┬─────────┘
         │
         ├─→ BehaviorModel (time patterns)
         ├─→ ScenarioEngine (SPIKE/DROP)
         └─→ TransactionGenerator (creates txns)
```

### API Endpoints

- `GET /` — Dashboard HTML page
- `GET /api/state` — Current generator state (JSON)
- `POST /api/start` — Start generator (not needed, auto-starts)
- `POST /api/stop` — Stop generator

### Data Format

The `/api/state` endpoint returns:

```json
{
  "running": true,
  "current_minute": "2026-10-02T10:15:00",
  "elapsed_minutes": 615,
  "total_transactions": 45234,
  "current_scenario": "SPIKE",
  "scenario_intensity": 2.4,
  "num_customers": 200,
  "minute_data": [
    {"timestamp": "10:15:00", "count": 152, "amount": 523420.50, "scenario_label": "SPIKE", "intensity": 2.4},
    {"timestamp": "10:14:00", "count": 145, "amount": 489320.75, "scenario_label": "SPIKE", "intensity": 2.4},
    ...
  ]
}
```

---

## Troubleshooting

### Port 5000 already in use

Change the port in `web_app.py` (last line):

```python
app.run(debug=False, host='0.0.0.0', port=5001, threaded=True)
```

Then open: http://localhost:5001

### Charts not updating

Check the browser console (F12) for JavaScript errors. The dashboard fetches `/api/state` every second — if that fails, charts won't update.

### Generator runs too fast/slow

The generator sleeps exactly 1.0 seconds per simulated minute. If your system is under heavy load, it might drift slightly. This is normal and doesn't affect functionality.

---

## Next Steps

1. **Run it now**: `.\RUN_DASHBOARD.ps1`
2. **Let it run for 10 minutes** — you'll see at least 1 SPIKE or DROP event
3. **Take screenshots** for your project documentation
4. **When you build the Kafka pipeline**: modify `web_app.py` to send transactions to Kafka instead of just counting them

---

## For Your Final Year Report

Include screenshots showing:
- The dashboard during normal operation
- The dashboard during a SPIKE (red chart)
- The dashboard during a DROP (orange chart)
- A caption explaining that this demonstrates the simulated banking environment generating realistic transaction patterns with controlled anomaly injection

This is a powerful visual demonstration that your transaction generator works exactly as designed.
