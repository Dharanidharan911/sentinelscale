# AGENTS.md — AI Agent Master Instructions for SentinelScale

> **This file is the entry point for every AI agent, new chat session, or contributor starting work on this repository.**
> Read this file first. Do not skip it.

---

## What Is SentinelScale?

SentinelScale is a **security-aware cloud resource intelligence platform** that solves the problem of Economic Denial of Sustainability (EDoS): traditional Kubernetes HPA scales out blindly when attack traffic (DDoS, bots, scrapers) causes CPU spikes, wasting money and destabilizing infrastructure.

SentinelScale distinguishes *legitimate* traffic demand from *malicious* surges, and makes infrastructure scaling decisions based only on real business demand — while suppressing wasteful scale-out during attacks.

---

## Where to Find Documentation

| What you need | Where to look |
| :--- | :--- |
| Project overview & current state | [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) |
| Implementation status & what's next | [`docs/PROGRESS.md`](docs/PROGRESS.md) |
| Full architecture & design | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Data flow between components | [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md) |
| API contracts (inputs/outputs) | [`docs/API_CONTRACTS.md`](docs/API_CONTRACTS.md) |
| Why decisions were made (ADRs) | [`docs/DECISIONS.md`](docs/DECISIONS.md) |
| Module 1 — Traffic Intelligence | [`docs/MODULE_1.md`](docs/MODULE_1.md) |
| Module 2A — Demand Intelligence | [`docs/MODULE_2A.md`](docs/MODULE_2A.md) |
| Module 2B — Hybrid Telemetry (NOT IMPLEMENTED) | [`docs/MODULE_2B.md`](docs/MODULE_2B.md) |
| Module 3 — Platform & Decision Engine | [`docs/MODULE_3.md`](docs/MODULE_3.md) |
| JSON Schema contracts | [`contracts/`](contracts/) |
| Developer setup & git workflow | [`DEVELOPMENT.md`](DEVELOPMENT.md) |
| Original architecture document | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Original contracts document | [`CONTRACTS.md`](CONTRACTS.md) |
| ADRs | [`docs/decisions/`](docs/decisions/) |

---

## How to Understand the Repository Before Coding

**Step 1 — Read documentation in this order:**
1. `AGENTS.md` (this file)
2. `docs/PROJECT_CONTEXT.md`
3. `docs/PROGRESS.md`
4. The relevant `docs/MODULE_*.md` for the module you are working on

**Step 2 — Inspect source code for the module you will work on:**
- Read `app/models/` — understand data structures and contracts
- Read `app/services/` — understand business logic
- Read `app/api/` — understand HTTP endpoints
- Read `tests/` — understand what is already tested and expected behavior

**Step 3 — Never assume previous chat history is available.** The repository documentation is the source of truth.

---

## Architecture Summary

```
[Incoming API Traffic]
         │
    [API Gateway] ──► [Prometheus Telemetry]
         │                     │
    [demo-api]                 │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
              [Module 1]  [Module 2]  [Module 3 Observer]
              Traffic     Demand      Resource
              Intelligence Intelligence State
                    │          │          │
                    └──────────┼──────────┘
                               ▼
                     [Module 3 Decision Engine]
                               │
                     [Policy Guardrails]
                               │
                    HOLD / SCALE / RATE_LIMIT
                    (dry_run=true, shadow_mode=true)
```

### Module Ownership

| Module | Directory | Port | Owner Branch |
| :--- | :--- | :--- | :--- |
| Traffic Intelligence | `services/traffic-intelligence/` | 8001 | `member1/traffic-intelligence` |
| Demand Intelligence | `services/demand-intelligence/` | 8002 | `member2/demand-intelligence` |
| Platform & Decision Engine | `services/platform/` | 8003 | `member3/platform` |
| Demo API (target workload) | `demo-api/` | 8000 | (shared) |

---

## Module Boundary Rules

These are hard rules. Violating them breaks team isolation and contract integrity.

1. **Never modify another module's `services/` code** without explicit cross-team coordination.
2. **JSON Schema contracts in `contracts/` are frozen** — no silent changes. Any breaking change requires a version bump and team review.
3. **Pydantic models must stay synchronized with JSON Schemas** — when a schema changes, update the Pydantic model in every consuming service too.
4. **Mock implementations live in `app/mock/`** — always preserve them as fallback even after adding real providers.
5. **The Decision Engine and Policy Guardrails must remain deterministic** — no LLM, random sampling, or non-deterministic logic in the actuation path.
6. **`dry_run=True` and `shadow_mode=True` are safety invariants** — never autonomously mutate Kubernetes replicas until explicitly authorized.

---

## Coding Conventions

- **Language**: Python 3.12+
- **API framework**: FastAPI with async/await throughout
- **Data validation**: Pydantic v2 — all models use `BaseModel` with explicit `Field(...)` constraints
- **Settings**: `pydantic-settings` with `BaseSettings` from `.env` files
- **HTTP client**: `httpx.AsyncClient` for all inter-service calls
- **Logging**: Structured JSON via `StructuredLoggingMiddleware` (in `app/logging.py` of each service)
- **Style**: Standard Python naming — `snake_case` for functions/variables, `PascalCase` for classes
- **Imports**: Absolute from service root (e.g. `from app.models.resource import ResourceState`)
- **No subprocess-based tool calls** (especially no `kubectl` or shell commands in application code)
- **No hard-coded credentials** — all configuration via environment variables

---

## Testing Requirements

Every change must:
1. Pass the full test suite: `python run_tests.py`
2. Add tests for all new behaviors — unit tests at minimum, contract conformance tests for any schema-producing code
3. Not break existing tests in any of the 4 services

### Running Tests

```bash
# Recommended: run all 4 services isolated (from repo root)
python run_tests.py

# Or run a single service (from repo root):
$env:PYTHONPATH="$PWD\services\platform"  # Windows
python -m pytest services/platform/tests -v
```

Each service runs with its own isolated `PYTHONPATH` — never mix service roots.

### Current Test Baseline (verified passing)
- Demo API: **9 passed**
- Traffic Intelligence: **5 passed**
- Demand Intelligence: **5 passed**
- Platform & Decision Engine: **44 passed, 1 skipped**
- **Total: 63 tests passing**

---

## Git & Branch Expectations

| Branch | Purpose |
| :--- | :--- |
| `main` | Protected. Always deployable. No direct commits after bootstrap. |
| `member1/traffic-intelligence` | Module 1 development |
| `member2/demand-intelligence` | Module 2 development |
| `member3/platform` | Module 3 development (current working branch) |

- Feature branches: `feature/m3-k8s-hybrid-telemetry` (branch off the member branch)
- Commit messages: `[Module 3] Add hybrid Prometheus+K8s telemetry aggregation`
- Every PR must include tests and must not break `main`

### What NOT to commit
- `.env` files (credentials/secrets)
- Model weights or binary artifacts (use `models/` placeholder with external registry)
- Generated datasets or large log files

---

## Rules for Modifying Existing Modules

| Situation | Rule |
| :--- | :--- |
| Bug fix in your own module | OK — add regression test |
| New feature in your own module | OK — follow testing requirements above |
| Modify another module's internals | Requires team coordination |
| Change a JSON Schema contract | Requires version bump + team review |
| Add a new `TELEMETRY_PROVIDER` option | OK in `services/platform/` — update factory.py and `__init__.py` |
| Add a new dependency | Add to service-specific `requirements.txt` only; avoid global footprint |

---

## Rules for Changing APIs/Contracts

1. **JSON Schemas** in `contracts/` are public interfaces — treat them like published APIs
2. **Breaking changes** (rename field, change type, add required field, remove field) require `MAJOR` version bump in `contract_version`
3. **Additive changes** (new optional field) require `MINOR` version bump
4. **All consuming services** must be updated when a schema changes (search for usages of the schema file)
5. Run `test_contract_conformance.py` in all services after any schema change

---

## Rules for Adding Dependencies

- Add to the **service-specific** `requirements.txt` only (e.g. `services/platform/requirements.txt`)
- Do not add to all services unless genuinely cross-cutting
- Prefer packages already in use (httpx, pydantic, fastapi)
- Heavy ML dependencies (torch, numpy, prophet, scikit-learn) belong only in the module that uses them
- No Kafka, Redis, Airflow, or Spark unless explicitly approved — keep local stack lightweight

---

## Documentation That Must Be Updated After Changes

After completing any feature or fix, update:

| Document | When to update |
| :--- | :--- |
| `docs/PROGRESS.md` | Always — mark completed tasks, update current state |
| `docs/MODULE_*.md` | When you change a module's implementation |
| `docs/API_CONTRACTS.md` | When you add or change an API endpoint |
| `docs/DECISIONS.md` | When you make a significant architectural choice |
| `docs/DATA_FLOW.md` | When data flow or transformations change |
| `services/platform/README.md` | When Platform telemetry providers change |
| `AGENTS.md` (this file) | When the agent workflow changes |

---

## How to Hand Off Work to Another Agent

Before finishing a session:

1. Run `python run_tests.py` and confirm all tests pass
2. Run `git diff --check` to confirm no whitespace errors
3. Update `docs/PROGRESS.md` with:
   - What was completed
   - What is in-progress (if any)
   - The exact recommended next step
4. Commit all changes with a descriptive message
5. Leave no uncommitted changes except intentionally untracked files

The receiving agent must NEVER rely on chat history. The repository + `docs/PROGRESS.md` must tell the complete story.

---

## Standard Agent Workflow

Every agent working on this repository MUST follow this workflow exactly:

```
START
  ↓
Read AGENTS.md (this file)
  ↓
Read docs/PROJECT_CONTEXT.md
  ↓
Read docs/PROGRESS.md
  ↓
Read the relevant docs/MODULE_*.md for your task
  ↓
Inspect relevant source code files
  ↓
Understand existing behavior thoroughly
  ↓
Plan changes (create implementation plan if significant)
  ↓
Implement (smallest correct change)
  ↓
Run tests: python run_tests.py
  ↓
Validate integration with dependent modules
  ↓
Update docs/PROGRESS.md
  ↓
Update other relevant docs (MODULE_*.md, API_CONTRACTS.md, DATA_FLOW.md)
  ↓
git commit with descriptive message
  ↓
HANDOFF: Leave docs/PROGRESS.md with clear next step
```

**The agent must NEVER assume that previous chat history is available.**
**The repository documentation must be sufficient for another agent to continue the work.**
