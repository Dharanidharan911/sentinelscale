# SentinelScale API Gateway Layer

## Role & Purpose
The API Gateway layer sits in front of backend cloud services (such as `demo-api`), acting as the primary point of ingress.

## Responsibilities
- Ingress traffic routing and TLS termination
- Ingestion of real-time telemetry into Prometheus and OpenTelemetry
- Request tagging with distributed tracing identifiers (`X-Trace-ID`, `X-Request-ID`)
- Future enforcement point for mitigation policies:
  - Header inspection
  - Adaptive Rate Limiting (Token Bucket / Leaky Bucket)
  - IP Filtering & Challenge Injection
  - WAF Integration

## Gateway Implementations
- **Local / Docker**: Envoy or Nginx Reverse Proxy with telemetry exporter.
- **Kubernetes**: Ingress-NGINX or Envoy Gateway controller.
