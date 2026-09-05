# SentinelScale k6 Load Testing Harness

> **Modular, reproducible k6 load-testing suite generating realistic multi-stage traffic against the SentinelScale Demo API (`demo-api`) to drive telemetry into Prometheus and Grafana.**

---

## 1. Overview

The SentinelScale k6 Load Testing Harness simulates multi-stage, human-paced user journeys across the target application workload (`demo-api`). It is designed to generate authentic, non-fabricated HTTP traffic that produces real telemetry observed by Prometheus and visualized in Grafana.

---

## 2. Workload Profiles

All profiles are defined in [`load-tests/k6/profiles.js`](k6/profiles.js):

| Profile | Target VUs | Stage Breakdown | Purpose |
| :--- | :--- | :--- | :--- |
| **`smoke`** | 2 VUs | 10s @ 2 VUs | Rapid sanity check for CI / quick validation |
| **`baseline`** | 10 VUs | 10s warmup (5 VUs) -> 30s steady (10 VUs) -> 10s cooldown (0 VUs) | Normal diurnal traffic baseline |
| **`spike`** | 35 VUs | 10s warmup -> 15s baseline -> 10s surge -> 20s peak -> 10s cooldown -> 10s recovery | Legitimate flash crowd / surge event |
| **`sustained`**| 25 VUs | 15s ramp-up -> 60s sustained plateau -> 15s ramp-down | High-utilization stress testing |

---

## 3. User Journey Transaction Mix

The master workload script ([`load-tests/k6/workload.js`](k6/workload.js)) generates a realistic traffic distribution across valid Demo API endpoints:

- **35% Catalog Browsing**: `GET /products`, `GET /products?category={cat}&limit=10`
- **25% Keyword Search**: `GET /search?q={query}` (e.g. `security`, `compute`, `pod`, `waf`)
- **20% Product Details**: `GET /products/{id}` (`prod-001` through `prod-005`)
- **10% User Authentication**: `POST /login`
- **6% Cart Operations**: `POST /cart`
- **4% Checkout Processing**: `POST /checkout`

Pacing: Randomized think time between 100ms and 300ms between requests.

---

## 4. Configuration & Environment Variables

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `TARGET_URL` | `http://demo-api:8000` (Docker) or `http://localhost:8000` (Host) | Target workload address |
| `PROFILE` | `baseline` | Workload profile (`smoke`, `baseline`, `spike`, `sustained`) |
| `VU_SCALE` | `1.0` | Scaling multiplier for Virtual Users |
| `DURATION_SCALE`| `1.0` | Scaling multiplier for stage durations |

---

## 5. Execution Instructions

### 5.1 Running via Docker Compose (Recommended)

Make sure the SentinelScale Compose stack is running:
```bash
docker compose up -d
```

Run k6 using the dedicated `load-test` profile:

```bash
# Run default baseline profile
docker compose --profile load-test run --rm k6

# Run smoke test profile (quick 10s validation)
docker compose --profile load-test run --rm -e PROFILE=smoke k6

# Run spike / surge profile
docker compose --profile load-test run --rm -e PROFILE=spike k6

# Run sustained high-load profile
docker compose --profile load-test run --rm -e PROFILE=sustained k6
```

### 5.2 Running via Standalone Docker Container

```bash
docker run --rm -i \
  --network sentinelscale_sentinelscale-net \
  -v "${PWD}/load-tests/k6:/scripts:ro" \
  -e TARGET_URL=http://demo-api:8000 \
  -e PROFILE=baseline \
  grafana/k6:0.50.0 run /scripts/workload.js
```

### 5.3 Running on Host (with installed k6 CLI)

```bash
k6 run -e TARGET_URL=http://localhost:8000 -e PROFILE=baseline load-tests/k6/workload.js
```

---

## 6. Observability in Grafana & Prometheus

While a load test is running:
1. Open Grafana at [http://localhost:3000](http://localhost:3000).
2. Navigate to the **`SentinelScale — Infrastructure Observability`** dashboard.
3. Observe real-time changes across:
   - **Total Request Rate (RPS)**
   - **Request Rate by Endpoint**
   - **P95 Latency (ms)**
   - **Process & Container CPU Rate**
   - **Resident Memory Working Set**
