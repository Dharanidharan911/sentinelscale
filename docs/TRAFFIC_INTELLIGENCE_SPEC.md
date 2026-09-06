# SentinelScale — Traffic Intelligence Feature Specification

## 1. Overview
This specification formally defines the traffic features evaluated by **Module 1: Traffic Intelligence** (`services/traffic-intelligence`).

To maintain scientific integrity, this document distinguishes between features that **currently exist** and are extracted from real/current inputs, versus features that are **not currently available** in the current telemetry ingestion layer.

---

## 2. Feature Matrix

### Category A: Volume Features

#### 1. `total_requests`
- **Definition**: Total count of HTTP requests recorded within the observation window.
- **Unit**: Count (integer)
- **Expected Range**: $[0, \infty)$
- **Source**: `TrafficTelemetryInput.total_requests`
- **Calculation**: Direct integer telemetry field.
- **Missing-value Behavior**: If telemetry is absent, defaults to 0.
- **Why it matters**: Provides sample size context for error rates and distribution percentages.
- **Used by Rules**: Yes (normalizes status code error rates and data completeness).
- **Suitable for ML**: Yes.
- **Status**: **CURRENTLY AVAILABLE**

#### 2. `total_rps`
- **Definition**: Average requests per second observed across the evaluation window.
- **Unit**: Requests / second ($\text{req/sec}$)
- **Expected Range**: $[0.0, \infty)$
- **Source**: `TrafficTelemetryInput.total_rps`
- **Calculation**: $\text{total\_requests} / \text{window\_seconds}$ (or provided by telemetry aggregator).
- **Missing-value Behavior**: Defaults to 0.0.
- **Why it matters**: Primary operational volume metric consumed by Platform to estimate capacity requirements.
- **Used by Rules**: Yes (used to partition legitimate vs suspicious RPS).
- **Suitable for ML**: Yes.
- **Status**: **CURRENTLY AVAILABLE**

#### 3. `burst_ratio`
- **Definition**: Ratio of observed total RPS to the expected historical or baseline RPS for the given service/window.
- **Unit**: Dimensionless ratio
- **Expected Range**: $[0.0, \infty)$ (typically $0.5$ to $10.0+$)
- **Source**: Derived in `FeatureExtractor.extract`
- **Calculation**: 
  $$\text{burst\_ratio} = \begin{cases} \text{round}(\text{total\_rps} / \text{baseline\_rps}, 3) & \text{if } \text{baseline\_rps} > 0 \\ 1.0 & \text{otherwise} \end{cases}$$
- **Missing-value Behavior**: If `baseline_rps` is omitted or 0, defaults to $1.0$ (nominal rate).
- **Why it matters**: Differentiates standard organic traffic from sudden traffic surges and volumetric floods.
- **Used by Rules**: Yes (`BurstDetector` evaluates nominal, elevated $\ge 1.75$, spike $\ge 2.5$, extreme $\ge 4.0$).
- **Suitable for ML**: Yes (high importance feature for anomaly detection).
- **Status**: **CURRENTLY AVAILABLE**

#### 4. `request_frequency`
- **Definition**: Fine-grained instantaneous inter-request arrival frequency per micro-window.
- **Unit**: Milliseconds ($\text{ms}$)
- **Status**: **NOT CURRENTLY AVAILABLE** (Aggregated telemetry ingestion does not currently stream individual packet timestamps).

---

### Category B: Client Behavior Features

#### 5. `ip_concentration` (`top_ip_ratio`)
- **Definition**: Proportion of total requests originating from the top single client IP (or top $N$ IPs/CIDR subnet).
- **Unit**: Ratio $[0.0, 1.0]$
- **Expected Range**: $0.01$ (broad organic distribution) to $1.0$ (single-source flood).
- **Source**: `TrafficTelemetryInput.top_ip_ratio`
- **Calculation**: $\text{requests\_from\_top\_ip} / \text{total\_requests}$.
- **Missing-value Behavior**: Defaults to $0.0$.
- **Why it matters**: Credential stuffing, scraping, and simple DoS attacks frequently originate from highly concentrated IP origins, whereas organic traffic is distributed across diverse users.
- **Used by Rules**: Yes (`TrafficScorer` applies critical penalty when $\ge 0.70$, high penalty when $\ge 0.40$).
- **Suitable for ML**: Yes (vital signal for bot swarms and DDoS).
- **Status**: **CURRENTLY AVAILABLE**

#### 6. `unique_ip_count`
- **Definition**: Distinct client IP addresses recorded during the window.
- **Unit**: Count (integer)
- **Expected Range**: $[0, \infty)$
- **Source**: `TrafficTelemetryInput.unique_ip_count`
- **Calculation**: Cardinality of distinct client IPs.
- **Missing-value Behavior**: Defaults to `None` / 0.
- **Why it matters**: Corroborates IP concentration. High RPS with low unique IP count signals aggressive automation.
- **Used by Rules**: Indirectly (used in data completeness scoring).
- **Suitable for ML**: Yes.
- **Status**: **CURRENTLY AVAILABLE**

#### 7. `ip_entropy`
- **Definition**: Shannon entropy computed over the complete client IP distribution: $H(X) = -\sum P(x) \log_2 P(x)$.
- **Unit**: Bits
- **Status**: **NOT CURRENTLY AVAILABLE** (Current telemetry model ingests summary concentration ratio `top_ip_ratio`, not full IP cardinality histograms).

#### 8. `ua_anomaly_ratio` (`non_standard_ua_ratio`)
- **Definition**: Proportion of requests presenting non-standard, empty, script, or automated tool User-Agents (e.g. `curl`, `python-requests`, headless browsers).
- **Unit**: Ratio $[0.0, 1.0]$
- **Expected Range**: $[0.0, 1.0]$ (typically $< 0.05$ in legitimate consumer traffic; $> 0.60$ in attack floods).
- **Source**: `TrafficTelemetryInput.non_standard_ua_ratio`
- **Calculation**: $\text{requests\_with\_non\_standard\_ua} / \text{total\_requests}$.
- **Missing-value Behavior**: Defaults to $0.0$.
- **Why it matters**: Highly informative for identifying unsophisticated scrapers, automated brute-force tools, and botnets.
- **Used by Rules**: Yes (`TrafficScorer` applies critical penalty when $\ge 0.65$, high penalty when $\ge 0.35$).
- **Suitable for ML**: Yes.
- **Status**: **CURRENTLY AVAILABLE**

#### 9. `bot_indicators`
- **Definition**: Fine-grained JA3/JA4 TLS fingerprint anomalies and HTTP/2 header order fingerprinting.
- **Unit**: Categorical / score
- **Status**: **NOT CURRENTLY AVAILABLE** (TLS fingerprinting is not yet terminated or forwarded by the demo gateway).

---

### Category C: HTTP Behavior Features

#### 10. `error_rate`
- **Definition**: Ratio of HTTP 4xx (client error) and 5xx (server error) responses relative to total requests.
- **Unit**: Ratio $[0.0, 1.0]$
- **Expected Range**: $[0.0, 1.0]$ (normal organic APIs typically experience $< 0.05$).
- **Source**: `TrafficTelemetryInput.status_codes`
- **Calculation**: 
  $$\text{error\_rate} = \frac{\text{status\_4xx} + \text{status\_5xx}}{\text{status\_2xx} + \text{status\_3xx} + \text{status\_4xx} + \text{status\_5xx}}$$
- **Missing-value Behavior**: Defaults to $0.0$ if status codes are omitted or total requests is 0.
- **Why it matters**: Attacking traffic (probing, path scanning, credential stuffing) experiences disproportionately high error rates (401, 403, 404, 429, 500).
- **Used by Rules**: Yes (`TrafficScorer` penalizes error rate $\ge 0.15$ and critical $\ge 0.35$).
- **Suitable for ML**: Yes.
- **Status**: **CURRENTLY AVAILABLE**

#### 11. `single_endpoint_ratio`
- **Definition**: Proportion of requests hitting a single concentrated URL route within the target service.
- **Unit**: Ratio $[0.0, 1.0]$
- **Expected Range**: $[0.0, 1.0]$
- **Source**: `TrafficTelemetryInput.single_endpoint_ratio`
- **Calculation**: $\max(\text{requests\_per\_endpoint}) / \text{total\_requests}$.
- **Missing-value Behavior**: Defaults to $0.0$.
- **Why it matters**: Identifies targeted endpoint floods (e.g. hitting `/api/v1/auth/login` or expensive search endpoints).
- **Used by Rules**: Yes (emits `single_endpoint_flood` signal when $\ge 0.85$).
- **Suitable for ML**: Yes.
- **Status**: **CURRENTLY AVAILABLE**

#### 12. `invalid_path_ratio`
- **Definition**: Percentage of requests to unmapped URLs (404 vulnerability scanner probes like `/wp-admin`, `/.env`).
- **Unit**: Ratio $[0.0, 1.0]$
- **Status**: **NOT CURRENTLY AVAILABLE** (Currently subsumed inside `status_4xx` count).

#### 13. `http_method_distribution`
- **Definition**: Breakdown of GET vs POST vs PUT vs DELETE methods.
- **Unit**: Categorical distribution
- **Status**: **NOT CURRENTLY AVAILABLE** (Method distribution is not currently collected in `TrafficTelemetryInput`).

---

### Category D: Temporal & Reliability Features

#### 14. `window_seconds`
- **Definition**: Observation time duration over which telemetry was captured.
- **Unit**: Seconds ($\text{s}$)
- **Expected Range**: $[1, \infty)$ (typically 60s).
- **Source**: `AssessmentRequest.window_seconds`
- **Calculation**: Provided in request (validated $\ge 1$).
- **Missing-value Behavior**: Defaults to 60.
- **Why it matters**: Short windows ($< 30\text{s}$) have higher variance and lower statistical confidence.
- **Used by Rules**: Yes (`TrafficScorer` scales confidence score linearly up to 60 seconds).
- **Suitable for ML**: Yes.
- **Status**: **CURRENTLY AVAILABLE**

#### 15. `data_completeness`
- **Definition**: Fraction of expected telemetry fields present and non-null in the input payload.
- **Unit**: Ratio $[0.0, 1.0]$
- **Source**: Derived in `FeatureExtractor.extract`
- **Calculation**: Proportion of 5 evaluated optional telemetry fields present.
- **Missing-value Behavior**: $0.0$ if no telemetry provided.
- **Why it matters**: Governs assessment confidence and informs whether to classify as `unknown`.
- **Used by Rules**: Yes (weights confidence score directly).
- **Suitable for ML**: Yes.
- **Status**: **CURRENTLY AVAILABLE**

#### 16. `rolling_rps` & `inter_arrival_variance`
- **Definition**: Sub-second inter-arrival variance and exponential rolling averages across multiple evaluation windows.
- **Unit**: Various
- **Status**: **NOT CURRENTLY AVAILABLE** (Current service operates stateless evaluation per window request; multi-window time-series buffering is planned for Phase M1-4/Prometheus integration).

---

## 3. Summary of Available Feature Vector for Machine Learning
The exact feature vector currently extractable and available for model training or benchmarking consists of **7 continuous features**:

$$\mathbf{x} = \begin{bmatrix} \text{total\_rps} \\ \text{burst\_ratio} \\ \text{error\_rate} \\ \text{ip\_concentration} \\ \text{ua\_anomaly\_ratio} \\ \text{single\_endpoint\_ratio} \\ \text{data\_completeness} \end{bmatrix}$$
