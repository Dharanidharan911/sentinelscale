# SentinelScale — Stage F2: Historical Demand Observation Accumulator

## 1. Overview & Responsibility

Stage F2 implements the **Platform-side Historical Demand Observation Accumulator**.
Its primary responsibility is to transform successive `TrafficAssessment` outputs from Module 1 into a bounded, chronologically sorted, deduplicated time series of `DemandObservation` records suitable for Module 2's `POST /api/v1/demand/forecast` endpoint.

```text
┌─────────────────────────┐
│   Module 1 Assessment   │ (Evaluated by Traffic Intelligence)
└───────────┬─────────────┘
            │ TrafficAssessment (legitimate_rps_estimate, timestamp)
            ▼
┌───────────────────────────────────────────────────────────────┐
│ Stage F2: DemandObservationAccumulator                        │
│ 1. Validate: finite epoch timestamps, finite RPS >= 0         │
│ 2. Security Filtering: exclude malicious / suspicious bursts  │
│ 3. Deduplicate: idempotent storage by event_id / timestamp    │
│ 4. Persist: stores in central SQLite database                 │
└───────────┬───────────────────────────────────────────────────┘
            │
            ▼ List[DemandObservation] (Strictly ascending chronological order)
┌─────────────────────────┐
│ Stage F3: Dispatcher    │ ──(ForecastRequest.observations)──► [Module 2 :8002]
└─────────────────────────┘
```

---

## 2. Data Provenance & Invariants

Every `DemandObservation` is constructed strictly from validated, threat-filtered Module 1 assessments:

| `DemandObservation` Field | Provenance Source | Invariant & Conversion |
| :--- | :--- | :--- |
| `timestamp` (float) | `TrafficAssessment.timestamp` (ISO-8601 string) | Converted to positive, finite Unix epoch seconds (`float`). |
| `rps` (float) | `TrafficAssessment.legitimate_rps_estimate` | Strictly non-negative (`>= 0.0`) and finite float. |

> [!CRITICAL]
> **Security Invariant**: Attack traffic must NEVER become accumulated legitimate demand.
> If a `TrafficAssessment` is classified as `malicious` or exceeds security thresholds (`risk_score > 0.80`, `legitimacy_score < 0.20`, or `confidence < 0.30`), the accumulator filters it out and logs an explanation, ensuring malicious bursts never pollute the historical demand baseline.

---

## 3. Storage Architecture

The accumulator reuses Platform's centralized SQLite persistence infrastructure ([`services/platform/app/services/history/sqlite_store.py`](file:///c:/SentinelScale/services/platform/app/services/history/sqlite_store.py)), avoiding duplicate databases or parallel caching layers.

### Schema (`demand_observations` table)
```sql
CREATE TABLE IF NOT EXISTS demand_observations (
    event_id TEXT PRIMARY KEY,
    target_service TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    timestamp_epoch REAL NOT NULL,
    timestamp_iso TEXT NOT NULL,
    legitimate_rps REAL NOT NULL,
    risk_score REAL NOT NULL,
    legitimacy_score REAL NOT NULL,
    confidence REAL NOT NULL,
    classification TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_demand_obs_target_time ON demand_observations(target_service, timestamp_epoch ASC);
CREATE INDEX IF NOT EXISTS idx_demand_obs_epoch ON demand_observations(timestamp_epoch);
```

---

## 4. API for Stage F3

The accumulator provides a clean Platform-side API:

```python
from app.services.history import get_demand_accumulator

accumulator = get_demand_accumulator()

# 1. Ingestion Path (Called when M1 produces an assessment)
obs = accumulator.record_traffic_assessment(
    assessment=traffic_assessment,
    target_service="demo-api"
)

# 2. Retrieval Path (Used by F3 to populate ForecastRequest.observations)
observations = accumulator.get_historical_demand_observations(
    target_service="demo-api",
    historical_window_seconds=3600,
    now_epoch=time.time()
)
```

The returned list contains `DemandObservation(timestamp=..., rps=...)` objects:
* Guaranteed sorted chronologically (`T1 < T2 < ...`).
* Bounded by the requested historical lookback window.
* Free of duplicate timestamps.
* Strictly isolated by `target_service`.

---

## 5. Scope & Boundary Invariants

* **Stage F2 does NOT call Module 2**.
* **Stage F2 does NOT perform time-series forecasting**.
* **Stage F2 does NOT make scaling decisions**.
* **Stage F2 does NOT modify Member 1 or Member 2 code or tests**.
* **Frozen JSON Schema contracts in `contracts/` remain unmodified (`v1.0.0`)**.

