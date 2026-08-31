# SentinelScale Local Development & Contributor Guide

Welcome to the **SentinelScale** repository. This guide details everything required to set up your environment, run the service stack, execute tests, deploy to local Kubernetes, and follow our 3-developer team workflow.

---

## 1. Prerequisites

Ensure you have the following installed on your development workstation:
- **Python 3.12+**
- **Docker Engine & Docker Compose** (v2+)
- **Git** (v2.30+)
- *(Optional for K8s)*: `kubectl`, `minikube` or `kind`

---

## 2. Local Environment Setup

### 2.1 Clone and Configure Environment

```bash
# Clone the repository
git clone <repository_url> sentinelscale
cd sentinelscale

# Copy environment template
cp .env.example .env
```

### 2.2 Python Virtual Environment

Create and activate a root virtual environment for local development and testing:

```bash
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Install development & test dependencies
pip install --upgrade pip
pip install pytest httpx pydantic pydantic-settings jsonschema flake8 uvicorn fastapi
```

---

## 3. Running Services Locally

### 3.1 Option A: Docker Compose (Recommended)

Start the full microservices stack including Prometheus with a single command:

```bash
docker-compose up --build
```

#### Service URLs & Health Endpoints:
- **Demo API**: [http://localhost:8000](http://localhost:8000) (`/health`, `/ready`, `/products`, `/docs`)
- **Traffic Intelligence**: [http://localhost:8001](http://localhost:8001) (`/health`, `/ready`, `/api/v1/traffic/assess`, `/docs`)
- **Demand Intelligence**: [http://localhost:8002](http://localhost:8002) (`/health`, `/ready`, `/api/v1/demand/forecast`, `/docs`)
- **Platform & Decision Engine**: [http://localhost:8003](http://localhost:8003) (`/health`, `/ready`, `/api/v1/resources/current`, `/docs`)
- **Prometheus Dashboard**: [http://localhost:9090](http://localhost:9090)

### 3.2 Option B: Running Individual Services with Uvicorn

```bash
# Traffic Intelligence
cd services/traffic-intelligence
uvicorn app.main:app --port 8001 --reload

# Demand Intelligence
cd services/demand-intelligence
uvicorn app.main:app --port 8002 --reload

# Platform
cd services/platform
uvicorn app.main:app --port 8003 --reload

# Demo API
cd demo-api
uvicorn app.main:app --port 8000 --reload
```

---

## 4. Running the Test Suite

Run all unit tests and contract conformance checks across all services:

```bash
# Run all tests from repository root
pytest -v

# Run service-specific tests
pytest services/traffic-intelligence/tests -v
pytest services/demand-intelligence/tests -v
pytest services/platform/tests -v
pytest demo-api/tests -v
```

---

## 5. Kubernetes Deployment

To deploy SentinelScale to a local Kubernetes cluster (Minikube / Kind):

```bash
# 1. Create the namespace
kubectl apply -f infrastructure/kubernetes/namespace.yaml

# 2. Deploy all services
kubectl apply -f infrastructure/kubernetes/demo-api/
kubectl apply -f infrastructure/kubernetes/traffic-intelligence/
kubectl apply -f infrastructure/kubernetes/demand-intelligence/
kubectl apply -f infrastructure/kubernetes/platform/

# 3. Verify deployment status
kubectl get pods -n sentinelscale
kubectl get services -n sentinelscale
```

---

## 6. Team Git Workflow & Module Ownership

The repository is structured for three developers working in parallel without merge conflicts or domain overlap.

### 6.1 Branch Ownership Structure

```
main (Protected, always deployable)
 ├── member1/traffic-intelligence (Module 1 Lead)
 ├── member2/demand-intelligence (Module 2 Lead)
 └── member3/platform (Module 3 & Decision Engine Lead)
```

- `main`: Protected production-ready branch. No direct commits after initial bootstrap.
- `member1/traffic-intelligence`: Dedicated branch for Traffic Intelligence feature development.
- `member2/demand-intelligence`: Dedicated branch for Demand Intelligence feature development.
- `member3/platform`: Dedicated branch for Platform, Resource Observer, and Decision Engine development.
- Feature branches (e.g. `feature/m1-burst-detector` or `feature/m2-prophet-forecaster`) branch off their respective member branch.

### 6.2 The Seven Golden Rules for Contributors

1. **Strict Service Boundaries**: Never modify another module's internal code in `services/<other-module>/` without cross-team coordination.
2. **Contract Immutability**: Never silently modify JSON Schemas in `contracts/` or `CONTRACTS.md`. Any contract change requires explicit team review.
3. **Pydantic & JSON Schema Synchronization**: When a contract is versioned, update both the JSON Schema in `contracts/` and the Pydantic models in each consuming service.
4. **Mock Isolation**: Keep mock implementations isolated in `app/mock/`. When introducing real ML models or Kubernetes clients, do not break the mock fallback.
5. **No Secrets in Git**: Never commit `.env`, private keys, or API tokens. Always use `.env.example`.
6. **Every Feature Needs Tests**: Every PR must include unit tests and schema conformance validation tests.
7. **Keep Main Green**: `main` must pass all tests and be deployable via Docker Compose at all times.
