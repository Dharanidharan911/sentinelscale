# SentinelScale Load Testing Harness

## Purpose
Simulates multi-tier workload profiles against the `demo-api` through the API Gateway, generating realistic telemetry scenarios to validate SentinelScale intelligence modules.

## Target Scenarios
1. **Legitimate Organic Peak**: Flash sales, promotional events (high volume, high legitimacy score, low risk).
2. **Volumetric DDoS / L7 Flood**: High RPS HTTP floods targeting specific endpoints with spoofed headers (high total RPS, high risk score, low legitimate demand).
3. **Low-and-Slow Credential Stuffing**: Low RPS distributed over many IPs targeting `/login` (high risk, moderate burst, anomalous token requests).
4. **Mixed Traffic Burst**: 70% illegitimate attack traffic + 30% legitimate customers.

## Recommended Tools
- `Locust` (Python distributed load testing)
- `k6` (JavaScript scenario runner)
- `Vegeta` / `wrk2` (Constant-rate HTTP benchmarking)
