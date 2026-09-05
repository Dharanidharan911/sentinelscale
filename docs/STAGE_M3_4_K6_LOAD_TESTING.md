# Stage M3-4 — k6 Load Testing Report

> **Comprehensive report on the modular k6 load testing harness, multi-stage traffic profiles, Docker Compose profile integration, and live Prometheus/Grafana validation.**

---

## 1. Executive Summary

Stage M3-4 implements a reproducible, modular, and realistic **k6 load-testing layer** for SentinelScale.

The load testing suite generates controlled, authentic HTTP workloads across the target Demo API (`demo-api`), simulating realistic multi-stage user journeys (catalog browsing, keyword search, product detail retrieval, user authentication, cart management, and checkout). This traffic exercises the live Prometheus scraping pipeline and Grafana infrastructure observability dashboard with empirical, non-fabricated telemetry, laying the foundation for subsequent Kubernetes scaling experimentation.

---

## 2. Architecture & Location of k6 Assets

All load-testing assets are organized cleanly under [`load-tests/`](../load-tests/):

```text
load-tests/
├── README.md                  # Comprehensive load test usage documentation
└── k6/
    ├── endpoints.js           # Modular API action helpers for Demo API
    ├── profiles.js            # Workload profile definitions & threshold rules
    └── workload.js            # Master parameterizable k6 scenario script
```

### Key Modules:
1. **[`endpoints.js`](../load-tests/k6/endpoints.js)**: Contains structured HTTP requests for `listProducts`, `getProduct`, `searchProducts`, `loginUser`, `updateCart`, `checkout`, and `checkHealth` with response schema validation checks.
2. **[`profiles.js`](../load-tests/k6/profiles.js)**: Configures multi-phase VU stage ramps, cooldowns, and validation thresholds for 4 distinct profiles (`smoke`, `baseline`, `spike`, `sustained`), supporting dynamic `VU_SCALE` and `DURATION_SCALE` multipliers.
3. **[`workload.js`](../load-tests/k6/workload.js)**: Master test entrypoint executing a weighted realistic user journey with human think-time pacing (100–300ms) and custom transaction latency tracking (`sentinel_browse_duration_ms`, `sentinel_search_duration_ms`, `sentinel_checkout_duration_ms`).

---

## 3. Workload Profiles & Transaction Distribution

### 3.1 Workload Profiles & Stage Breakdown

All profiles define discrete stages representing realistic traffic ramps:

| Profile | Target VUs | Nominal Stages Breakdown | Nominal Duration | Purpose |
| :--- | :--- | :--- | :---: | :--- |
| **`smoke`** | 2 VUs | 10s @ 2 VUs | **10s** | Rapid sanity check for CI / automated tests |
| **`baseline`** | 10 VUs | 10s warmup (5 VUs) -> 30s steady (10 VUs) -> 10s cooldown (0 VUs) | **50s** | Normal diurnal traffic baseline |
| **`spike`** | 35 VUs | 10s warmup (5 VUs) -> 15s baseline (10 VUs) -> 10s surge (35 VUs) -> 20s peak (35 VUs) -> 10s cooldown (5 VUs) -> 10s recovery (0 VUs) | **75s** | Legitimate flash crowd / surge event |
| **`sustained`**| 25 VUs | 15s ramp-up (25 VUs) -> 60s plateau (25 VUs) -> 15s ramp-down (0 VUs) | **90s** | Heavy sustained peak utilization |

### 3.2 Dynamic Multipliers (`VU_SCALE` & `DURATION_SCALE`)
The test harness provides two scaling environment variables for fast CI execution or high-capacity stress testing:
- **`DURATION_SCALE`** (default `1.0`): Scales each stage's duration (e.g. `DURATION_SCALE=0.5` on `baseline` yields a 25s run; `DURATION_SCALE=0.3` on `spike` yields a 23s run).
- **`VU_SCALE`** (default `1.0`): Scales target VUs across all stages proportionally.

### 3.3 Realistic User Journey Mix
- **35% Catalog Browsing**: `GET /products`, `GET /products?category={cat}&limit=10`
- **25% Keyword Search**: `GET /search?q={query}` (`security`, `compute`, `pod`, `waf`, `mesh`)
- **20% Product Detail**: `GET /products/{id}` (`prod-001` through `prod-005`)
- **10% User Authentication**: `POST /login`
- **6% Cart Operations**: `POST /cart`
- **4% Checkout Processing**: `POST /checkout`
- **Pacing**: Randomized think time between 100ms and 300ms between transactions.

---

## 4. Configuration & Docker Integration

The k6 runner is integrated into [`docker-compose.yml`](../docker-compose.yml) under the `load-test` and `tools` profiles:

```yaml
  k6:
    image: grafana/k6:0.50.0
    container_name: sentinelscale-k6
    profiles:
      - load-test
      - tools
    volumes:
      - ./load-tests/k6:/scripts:ro
    environment:
      - TARGET_URL=${TARGET_URL:-http://demo-api:8000}
      - PROFILE=${PROFILE:-baseline}
      - VU_SCALE=${VU_SCALE:-1.0}
      - DURATION_SCALE=${DURATION_SCALE:-1.0}
    command: run /scripts/workload.js
    networks:
      - sentinelscale-net
```

### Environment Variables

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `TARGET_URL` | `http://demo-api:8000` (Docker) / `http://localhost:8000` (Host) | Target endpoint address |
| `PROFILE` | `baseline` | Active workload profile (`smoke`, `baseline`, `spike`, `sustained`) |
| `VU_SCALE` | `1.0` | Scaling multiplier for Virtual Users |
| `DURATION_SCALE`| `1.0` | Scaling multiplier for stage durations |

---

## 5. Live Validation Results & Metric Reconciliation

### 5.1 Nominal Full-Duration Executions (`DURATION_SCALE=1.0`)

| Profile | Nominal Duration | Total Requests | Total Checks | Checks Pass Rate | Average RPS | P95 Latency | Error Rate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`smoke`** | 10.0s | 48 | 96 | **100.00%** | 4.73 req/s | 3.08 ms | **0.00%** |
| **`baseline`** | 50.2s | 1,467 | 2,934 | **100.00%** | 29.23 req/s | 3.08 ms | **0.00%** |
| **`spike`** | 75.1s | 6,381 | 12,762 | **100.00%** | 84.92 req/s | 3.53 ms | **0.00%** |

### 5.2 Scaled Fast-Validation Executions (`DURATION_SCALE < 1.0`)

| Profile | `DURATION_SCALE` | Scaled Duration | Total Requests | Total Checks | Checks Pass Rate | Average RPS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`baseline`** | `0.5` | 25.2s | 731 | 1,462 | **100.00%** | 28.96 req/s |
| **`spike`** | `0.3` | 23.1s | 1,932 | 3,864 | **100.00%** | 83.46 req/s |

### 5.3 Request-to-Check Ratio Reconciliation
In k6 execution summaries, checks are evaluated per assertion. Each transaction helper function in [`load-tests/k6/endpoints.js`](../load-tests/k6/endpoints.js) executes **exactly two assertions**:
1. HTTP status code verification (`r.status === 200`).
2. Response payload schema integrity verification (e.g. array type check, `product.id` presence, `cart_id` presence, `token` presence, or `checkout.status === 'completed'`).

Consequently, for every request executed, exactly 2 checks are evaluated:
- Nominal Baseline: `1,467 requests * 2 checks = 2,934 checks` (100% passed).
- Nominal Spike: `6,381 requests * 2 checks = 12,762 checks` (100% passed).
- Fast Baseline: `731 requests * 2 checks = 1,462 checks` (100% passed).
- Fast Spike: `1,932 requests * 2 checks = 3,864 checks` (100% passed).

### 5.4 Telemetry Observability Verification
- **Prometheus**: Real-time counter `http_requests_total` scraped every 2 seconds, incrementing continuously across the live validation runs.
- **Grafana**: The `SentinelScale — Infrastructure Observability` dashboard accurately rendered dynamic request rate spikes (up to 85+ RPS), P95 latency distribution, and CPU/memory utilization changes.

---

## 6. Test Suite Baseline

- **k6 Load Testing Unit Tests** ([`services/platform/tests/test_k6_load_testing.py`](../services/platform/tests/test_k6_load_testing.py)):
  - `test_k6_script_files_exist_and_structure_valid`: **PASSED**
  - `test_docker_compose_k6_profile_configuration`: **PASSED**
  - `test_load_tests_readme_documentation`: **PASSED**
- **Subprocess-Isolated Full Test Suite** (`python run_tests.py`):
  - Demo API: **9 passed**
  - Traffic Intelligence: **5 passed**
  - Demand Intelligence: **100 passed**
  - Platform & Decision Engine: **254 passed**
  - **Total: 368 tests passed, 0 failed**

---

## 7. Safety Invariants & Scope Boundaries

- **`dry_run = True` & `shadow_mode = True`** preserved unconditionally.
- **`SENTINEL_AUTONOMOUS_ACTIONS_ENABLED = False`**.
- **Kubernetes Mutations**: Exactly **0**.
- **Frozen Contracts in `contracts/`**: **v1.0.0 (Unchanged)**.
- **What M3-4 Does NOT Claim**: Stage M3-4 establishes a workload generation harness for Docker Compose and future testbeds; it does not claim to execute physical Kubernetes HPA pod scaling, which is reserved for Stages M3-5 through M3-8.
