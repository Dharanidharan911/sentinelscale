# Module 3: Platform, Resource Intelligence & Decision Engine

The Platform service (`services/platform`) is responsible for observing infrastructure capacity, comparing scaling recommendations against traditional Kubernetes Horizontal Pod Autoscaler (HPA) baselines, and executing deterministic policy-guarded scaling evaluations.

---

## Telemetry Provider Architecture (Phase 1)

The **Resource Observer** delegates metric collection to a pluggable `ResourceTelemetryProvider` interface. This cleanly decouples infrastructure query mechanics from canonical `ResourceState` generation.

```
ResourceObserverService
          │
          ▼
ResourceTelemetryProvider (ABC)
   ├── MockTelemetryProvider        <-- Active (development & tests)
   ├── PrometheusTelemetryProvider  <-- Scheduled (Phase 1 expansion)
   └── KubernetesTelemetryProvider  <-- Scheduled (Phase 1 expansion)
```

### Key Components

- **`ResourceTelemetryProvider`** (`app.services.telemetry.base`):
  Abstract interface defining `fetch_resource_state(namespace, workload, trace_id) -> ResourceState`.
- **`TelemetryProviderError`** (`app.services.telemetry.base`):
  Explicit domain exception raised when metrics cannot be queried or reached. Surfaces as HTTP 502 at the API gateway rather than silently returning fake data.
- **`MockTelemetryProvider`** (`app.services.telemetry.mock_provider`):
  Deterministic mock provider for unit testing and local development.
- **`get_telemetry_provider`** (`app.services.telemetry.factory`):
  Provider factory driven by the `TELEMETRY_PROVIDER` setting (`"mock"`, `"prometheus"`, `"kubernetes"`).

---

## Configuration

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `TELEMETRY_PROVIDER` | `mock` | Active provider (`mock`, `prometheus`, `kubernetes`) |
| `PORT` | `8003` | Service port |
| `SENTINEL_DRY_RUN` | `true` | Safety flag: prevents mutating cluster actions |
| `SENTINEL_SHADOW_MODE` | `true` | Enables baseline HPA comparison telemetry |

---

## Running Platform Tests

```bash
# From repository root
python -m pytest services/platform/tests -v -o pythonpath=services/platform
```

