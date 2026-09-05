# SentinelScale — Stage F3: M2 Observation Dispatcher & Dynamic Demand Forecast Integration

## 1. Overview & Purpose

Stage F3 completes the dynamic coupling between historical legitimate demand accumulation (Stage F2) and Module 2 Demand Intelligence (`POST /api/v1/demand/forecast`), feeding the generated `DemandForecast` into Platform's `DecisionContext` and `DecisionEngine`.

```text
Actual / Generated Traffic
          ↓
[Stage F1] Traffic Harness / Live Telemetry
          ↓
Module 1 — Traffic Intelligence (`POST /api/v1/traffic/assess`)
          ↓ TrafficAssessment
[Stage F2] DemandObservationAccumulator (Validation + Security Filter + Deduplication)
          ↓ DemandObservation[] (Ordered, legitimate time series)
[Stage F3] DemandIntelligenceClient (`POST /api/v1/demand/forecast`)
          ↓ DemandForecast
Module 3 ContextAggregatorService → DecisionContext
          ↓
Module 3 DecisionEngine → Deterministic ScalingDecision
```

---

## 2. Key Architectural Invariants Enforced

1. **Strict Service Layer Boundary & HTTP Isolation**:
   - Platform communicates with Module 2 exclusively via HTTP `POST /api/v1/demand/forecast`.
   - Zero internal Python imports from `services/demand-intelligence/**` or `services/traffic-intelligence/**`.
2. **Frozen v1.0.0 Contracts**:
   - Zero changes to JSON Schemas in `contracts/**`.
   - `ForecastRequest`, `DemandObservation`, and `DemandForecast` adhere strictly to published schemas.
3. **Data Provenance & Zero Fabrication**:
   - Outgoing `DemandObservation[]` records to Module 2 originate strictly from validated, security-filtered historical assessments stored in SQLite.
   - If observation history is empty, `observations=None` is passed so Module 2 defaults gracefully.
4. **Security Isolation (EDoS Prevention)**:
   - Hostile/suspicious DDoS traffic detected by Module 1 is rejected by Stage F2 accumulator and is never dispatched to Module 2 as demand.
5. **Safety Invariants**:
   - `dry_run = True` and `shadow_mode = True` remain actively enforced. Zero mutations to Kubernetes infrastructure.

---

## 3. Implementation Details

### `DemandIntelligenceClient` (`services/platform/app/clients/demand_client.py`)
- Extended `fetch_forecast()` method signature:
  ```python
  async def fetch_forecast(
      self,
      forecast_horizon_seconds: int = 300,
      trace_id: Optional[str] = None,
      target_service: Optional[str] = "demo-api",
      historical_window_seconds: Optional[int] = 3600,
      observations: Optional[List[DemandObservation]] = None,
  ) -> DemandForecast:
  ```
- Automatically serializes `DemandObservation` objects into JSON request body.
- Sets `X-Trace-ID` distributed tracing header and `trace_id` in the request body.
- Propagates upstream HTTP failures, timeouts, and contract validation errors as `UpstreamDemandIntelligenceError`.

### `ContextAggregatorService` (`services/platform/app/services/context_aggregator.py`)
- Injects `DemandObservationAccumulator` (singleton from `get_demand_accumulator()`).
- Prior to concurrent gathering, queries `demand_accumulator.get_historical_demand_observations()` for the target service within `DEMAND_OBSERVATION_HISTORY_WINDOW_SECONDS`.
- Passes retrieved observations (or `None` if empty) to `demand_client.fetch_forecast()`.
- Upon successful receipt of a new `TrafficAssessment` from Module 1, asynchronously records it in the accumulator for future cycles.

---

## 4. Verification & Testing

The dedicated test suite `services/platform/tests/test_demand_dispatch.py` verifies:
- `test_f2_observations_retrieved_and_passed_to_m2`: Historical observations retrieved and passed to M2.
- `test_outgoing_payload_matches_f2_accumulator_provenance`: Data provenance and exact match with SQLite records.
- `test_m2_http_contract_conformance`: Conformance to `ForecastRequest` schema.
- `test_m2_demand_forecast_response_parsing_and_validation`: Response validation against `DemandForecast` v1.0.0.
- `test_trace_id_propagation_throughout_f3`: Trace ID propagation across all dispatch headers and payloads.
- `test_empty_observation_history_handling`: Graceful handling of empty history (`observations=None`).
- `test_m2_error_handling_mapped_to_aggregation_error`: Mapping upstream HTTP 500, timeouts, and malformed JSON to `AggregationError`.
- `test_security_provenance_suspicious_traffic_filtered_before_m2`: Verification that hostile traffic is excluded from demand dispatch.
- `test_full_aggregation_into_decision_context_preserves_decision_engine`: End-to-end orchestration producing deterministic `ScalingDecision`.

### Test Suite Execution
- `python -m pytest services/platform/tests/test_demand_dispatch.py -v` → **9 passed**
- Full Platform Suite: **222 passed, 2 skipped**
- Complete Repository Test Runner (`python run_tests.py`): **336 passed, 2 skipped (0 failed)**

