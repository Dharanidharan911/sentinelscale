"""
SentinelScale — Async HTTP Traffic Generator
Dispatches realistic HTTP requests against the Demo API according to a ScenarioDefinition.
"""
import asyncio
import random
import time
import uuid
from typing import List, Optional
import httpx
from app.harness.models import EndpointTarget, ObservedRequestEvent, ScenarioDefinition


class AsyncTrafficGenerator:
    """
    Generates actual HTTP traffic against a target API and captures empirical request events.
    Supports in-memory ASGI transports (for fast unit testing) and live network endpoints.
    """

    def __init__(
        self,
        base_url: str = "http://demo-api:8000",
        client: Optional[httpx.AsyncClient] = None,
        max_concurrency: int = 50,
    ):
        self.base_url = base_url.rstrip("/")
        self._custom_client = client
        self.max_concurrency = max_concurrency

    async def generate_traffic(
        self,
        scenario: ScenarioDefinition,
        rate_limit_pacing: bool = False,
    ) -> List[ObservedRequestEvent]:
        """
        Execute the scenario by generating HTTP requests against demo-api.
        
        Args:
            scenario: The typed scenario specification.
            rate_limit_pacing: If True, pauses between request batches to simulate
                               real-time pacing. If False (default for tests), dispatches
                               requests at maximum throughput while recording accurate timestamps.
        
        Returns:
            List of ObservedRequestEvent capturing every dispatched request.
        """
        total_requests = max(1, int(scenario.target_rps * scenario.duration_seconds))
        trace_id = scenario.trace_id or f"trace-{uuid.uuid4().hex[:16]}"
        events: List[ObservedRequestEvent] = []

        semaphore = asyncio.Semaphore(self.max_concurrency)
        client = self._custom_client or httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        close_client = self._custom_client is None

        # Pre-sample requests according to scenario weights
        sampled_endpoints = random.choices(
            scenario.endpoints,
            weights=[ep.weight for ep in scenario.endpoints],
            k=total_requests,
        )
        sampled_ips = random.choices(
            scenario.client_ips,
            weights=scenario.ip_weights,
            k=total_requests,
        )
        sampled_uas = random.choices(
            scenario.user_agents,
            weights=scenario.ua_weights,
            k=total_requests,
        )

        start_epoch = time.time()
        time_step = scenario.duration_seconds / float(total_requests)

        async def _dispatch_single_request(
            idx: int,
            endpoint: EndpointTarget,
            client_ip: str,
            user_agent: str,
        ) -> ObservedRequestEvent:
            async with semaphore:
                headers = {
                    "X-Forwarded-For": client_ip,
                    "User-Agent": user_agent,
                    "X-Trace-ID": trace_id,
                }
                
                req_start = time.perf_counter()
                event_time = start_epoch + (idx * time_step)
                
                try:
                    if endpoint.method.upper() == "POST":
                        resp = await client.post(
                            endpoint.path,
                            json=endpoint.body or {},
                            headers=headers,
                        )
                    else:
                        resp = await client.get(
                            endpoint.path,
                            headers=headers,
                        )
                    status_code = resp.status_code
                except Exception:
                    # In case of network / connection failure, record as 500 error
                    status_code = 500
                
                latency_ms = round((time.perf_counter() - req_start) * 1000, 2)
                
                return ObservedRequestEvent(
                    timestamp=event_time,
                    method=endpoint.method,
                    path=endpoint.path,
                    status_code=status_code,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    latency_ms=latency_ms,
                )

        try:
            tasks = [
                _dispatch_single_request(i, sampled_endpoints[i], sampled_ips[i], sampled_uas[i])
                for i in range(total_requests)
            ]
            
            if rate_limit_pacing:
                # Batch dispatch with pacing
                batch_size = max(1, int(scenario.target_rps))
                for b_start in range(0, total_requests, batch_size):
                    batch_tasks = tasks[b_start : b_start + batch_size]
                    batch_results = await asyncio.gather(*batch_tasks)
                    events.extend(batch_results)
                    await asyncio.sleep(1.0)
            else:
                events = await asyncio.gather(*tasks)

        finally:
            if close_client:
                await client.aclose()

        return events

