# SentinelScale — Traffic Intelligence (Module 1) Context

## 1. Module Responsibility
- Ingests API traffic telemetry (request rate, error rates, client IP distributions, User-Agent distributions, path dispersion).
- Analyzes traffic behavior and detects anomalous bursts/spikes.
- Assesses security risks and estimates legitimate vs. suspicious/malicious traffic demand.
- Computes risk score, legitimacy score, confidence score, and categorical traffic classification (`legitimate`, `suspicious`, `malicious`, `unknown`).
- Emits explainability signals (`top_signals`).
- Produces canonical `TrafficAssessment` contract consumed downstream by Platform (Module 3).

## 2. Architecture Constraints
- **Strict Boundary**: Module 1 produces evidence only. Never make scaling decisions, interact with Kubernetes HPA/API, or predict future demand (owned by Module 2 and Module 3).
- **No Heavy External Systems**: No LLMs, no Kafka/Redis/Spark/Airflow. Maintain clean, deterministic, microservice design.
- **Contract Immutability**: `contracts/traffic/traffic_assessment.schema.json` is the ground truth. All outputs must pass strict JSON schema and Pydantic validation.
- **Observability**: Maintain structured JSON logging with `request_id`, `trace_id`, `service`, `endpoint`, and `latency_ms`.

## 3. Current Implementation Status
- **Service Port**: `8001`
- **Endpoints**:
  - `GET /health` -> `{"status": "ok", "service": "traffic-intelligence"}`
  - `GET /ready` -> `{"status": "ready", "service": "traffic-intelligence"}`
  - `GET /version` -> `{"service": "traffic-intelligence", "service_version": "0.1.0", "contract_version": "1.0.0", "model_version": "traffic-rules-v1"}`
  - `POST /api/v1/traffic/assess` -> `TrafficAssessment` contract payload
- **Current Model**: Deterministic rule-based intelligence pipeline (`traffic-rules-v1`) with isolated mock fallback in `app/mock/generator.py`.

## 4. Contract Location
- Formal JSON Schema: `contracts/traffic/traffic_assessment.schema.json`
- Pydantic models: `services/traffic-intelligence/app/models/traffic.py`
- Downstream consumer: `services/platform/app/clients/traffic_client.py`

## 5. Important Design Decisions
- **Deterministic Pipeline First (`traffic-rules-v1`)**:
  - Modular pipeline structure:
    - `app/pipeline/features.py`: FeatureExtractor normalizing raw rates, error rates, IP concentration, UA anomaly ratio, single-endpoint ratio, and data completeness.
    - `app/pipeline/burst_detector.py`: Evaluates burst ratios into `nominal`, `elevated`, `spike`, and `extreme` categories.
    - `app/pipeline/scorer.py`: Computes risk score $\in [0.0, 1.0]$, legitimacy score $\in [0.0, 1.0]$, confidence score $\in [0.0, 1.0]$, and strictly partitions total RPS into `legitimate_rps_estimate` and `suspicious_rps_estimate`.
    - `app/pipeline/classifier.py`: Maps scores and features into `legitimate`, `suspicious`, `malicious`, or `unknown`, generating top explainability signals.
    - `app/pipeline/engine.py`: Orchestrates request assessment with backward-compatible defaults when telemetry is omitted.
- **Backward Compatible Ingestion**: `AssessmentRequest` supports an optional `telemetry: Optional[TrafficTelemetryInput] = None`. Standard callers providing only `window_seconds` receive a deterministic evaluation without breaking.
- **Strict Invariants**:
  - `legitimate_rps_estimate + suspicious_rps_estimate == total_rps` (rounded to 2 decimal places).
  - All outputs validated against `contracts/traffic/traffic_assessment.schema.json`.

## 6. Completed Phases
- **Phase 0**: Bootstrap verification and test harness setup.
- **Phase 1**: Implementation of deterministic intelligence pipeline (`traffic-rules-v1`), including 6 realistic benchmark scenario test suites and API validation.

## 7. Remaining Phases
- **Phase 2**: Synthetic telemetry dataset generator and offline benchmark suite.
- **Phase 3**: Machine Learning model integration (Isolation Forest / XGBoost) with deterministic rule fallback.
- **Phase 4**: Prometheus telemetry collector client (ingesting real API gateway metrics).

## 8. Test & Verification Status
- All 18 Traffic Intelligence unit and scenario tests pass.
- All 4 microservices pass in repository test runner (`python run_tests.py` -> 43 total passed).
- Test execution command:
  ```powershell
  python -m pytest services/traffic-intelligence/tests -v -o pythonpath=services/traffic-intelligence
  ```

## 9. Integration Notes for Member 2 & Member 3
- **Member 2 (Demand Intelligence)**: Module 1 operates asynchronously and independently of Demand Intelligence.
- **Member 3 (Platform / Decision Engine)**: Platform calls `POST /api/v1/traffic/assess` and uses `legitimate_rps_estimate`, `risk_score`, and `classification` to make security-aware scaling and rate-limiting decisions.
