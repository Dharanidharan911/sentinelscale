# SentinelScale — Stage F1: Telemetry Extraction & Scenario Input Harness

## 1. Overview & Architecture

Stage F1 implements the **Scenario Input & Telemetry Extraction Harness** for SentinelScale. It replaces static fixture injection with dynamic HTTP request generation against the `demo-api` workload, captures empirical request events, aggregates window telemetry, and invokes Module 1 (`POST /api/v1/traffic/assess`) to produce genuine, data-driven `TrafficAssessment` results.

```text
┌─────────────────────────┐
│   Scenario Definition   │ (Canonical: Steady, Flash Crowd, Hostile Flood, Mixed)
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ AsyncTrafficGenerator   │ ──(HTTP GET/POST with X-Forwarded-For, UA, X-Trace-ID)──► [demo-api]
└───────────┬─────────────┘
            │ (Captures ObservedRequestEvents: timestamp, status_code, IP, UA, latency)
            ▼
┌─────────────────────────┐
│   TelemetryCollector    │ (Derives total_rps, error_rate, top_ip_ratio, bot_ua_ratio)
└───────────┬─────────────┘
            │
            ▼ TrafficTelemetryInput
┌─────────────────────────┐
│   ScenarioRunner / M1   │ ──(POST /api/v1/traffic/assess)──► [Traffic Intelligence :8001]
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│  TrafficAssessment v1.0 │ (Evaluated dynamically by M1 deterministic rule pipeline)
└─────────────────────────┘
```

---

## 2. Canonical Scenario Definitions

The harness supports 4 canonical scenarios defined in [`services/platform/app/harness/models.py`](file:///c:/SentinelScale/services/platform/app/harness/models.py):

| Scenario | Target RPS | Client IP Distribution | User-Agent Profile | Endpoint Targets | Purpose |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **A. Steady Legitimate** | 50.0 | 50 distributed IPs (uniform) | Organic browser UAs (Chrome, Safari, Firefox) | `/products`, `/products/{id}`, `/cart` | Establish baseline organic demand; low risk (<0.30), 0 suspicious RPS. |
| **B. Legitimate Flash Crowd** | 250.0 | 100 distributed IPs (uniform) | Organic browser UAs | `/products`, `/products/{id}`, `/search` | High-volume surge with organic spread; burst ratio $\ge 4.0$, low risk, `organic_demand_surge`. |
| **C. Hostile L7 Flood** | 300.0 | 3 IPs (90% concentrated on single IP) | Bot / automated UAs (`curl`, `python-requests`, empty) | `/products/invalid-id` (404), `/login` empty (400) | High-volume attack; top-IP ratio $\ge 0.70$, bot UA ratio $\ge 0.70$, high error rate; flags `malicious` (risk $\ge 0.80$). |
| **D. Mixed Traffic** | 150.0 | 30 legitimate IPs (60%) + 1 scraper IP (40%) | 60% Browser UAs + 40% Bot UAs | Legitimate product catalog + crawler probe endpoints | Mixed traffic; partitions rates into legitimate vs suspicious RPS. |

---

## 3. Telemetry Provenance & Derivation Formulas

Every field in [`TrafficTelemetryInput`](file:///c:/SentinelScale/services/platform/app/models/traffic_contract.py) is derived directly from empirical `ObservedRequestEvent` instances captured during generation:

| Telemetry Field | Raw Measurement Source | Aggregation Formula |
| :--- | :--- | :--- |
| `total_requests` | Count of dispatched HTTP responses | $N = \text{len}(\text{events})$ |
| `total_rps` | Effective request rate over window | $\text{round}(N / \text{window\_seconds}, 2)$ |
| `status_codes` | HTTP response status codes | Partition into 2xx, 3xx, 4xx, 5xx buckets |
| `top_ip_ratio` | `X-Forwarded-For` header distribution | $\max_{ip}(\text{count}(ip)) / N$ |
| `unique_ip_count` | Distinct `X-Forwarded-For` IPs | $\text{len}(\text{unique}(ips))$ |
| `non_standard_ua_ratio` | `User-Agent` string inspection | $\sum \mathbb{I}(\text{is\_bot\_ua}(ua)) / N$ |
| `single_endpoint_ratio` | Normalized request URL path | $\max_{path}(\text{count}(path)) / N$ |

---

## 4. How to Run the Harness

### Running via Pytest Unit Suite
```bash
$env:PYTHONPATH="$PWD\services\platform"
python -m pytest services/platform/tests/test_traffic_harness.py -v
```

### Running Against Live Services (Local / Docker Compose)
```bash
$env:PYTHONPATH="$PWD\services\platform"
python -m pytest services/platform/tests/test_traffic_harness_live.py -v
```

---

## 5. Scope Boundaries (What F1 Does NOT Implement)

* **F1 does NOT yet accumulate historical demand observations** (Scheduled for Stage F2).
* **F1 does NOT yet dispatch observations to Module 2** (Scheduled for Stage F3).
* **F1 does NOT yet modify ContextAggregator orchestration** (Scheduled for Stage F4).
* **F1 does NOT mutate Kubernetes infrastructure** (`dry_run=true`, `shadow_mode=true` strictly preserved).

