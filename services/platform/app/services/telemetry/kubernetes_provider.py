import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import httpx
from app.config.settings import settings
from app.logging import logger
from app.models.resource import ResourceState
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.quantity_parser import parse_cpu_quantity, parse_memory_quantity


class KubernetesTelemetryProvider(ResourceTelemetryProvider):
    """
    Production-grade Kubernetes Resource Telemetry Provider.
    Queries the official Kubernetes REST API to observe real Deployment replica specs,
    Pod lifecycle phases, and aggregate container resource limits and requests.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        ca_cert_path: Optional[str] = None,
    ):
        self.timeout_seconds = timeout_seconds or settings.KUBERNETES_TIMEOUT_SECONDS
        self._custom_client = http_client

        # 1. Determine API Server URL & Authentication Credentials
        in_cluster_token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        in_cluster_ca_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")

        if api_url:
            self.api_url = api_url.rstrip("/")
            self.token = token or settings.KUBERNETES_TOKEN
            self.ca_cert = ca_cert_path
        elif in_cluster_token_path.exists():
            # In-Cluster ServiceAccount Mode
            self.api_url = "https://kubernetes.default.svc"
            self.token = in_cluster_token_path.read_text(encoding="utf-8").strip()
            self.ca_cert = str(in_cluster_ca_path) if in_cluster_ca_path.exists() else None
        else:
            # Local Development Mode
            self.api_url = (settings.KUBERNETES_API_URL or "http://localhost:8001").rstrip("/")
            self.token = token or settings.KUBERNETES_TOKEN
            self.ca_cert = ca_cert_path

    @property
    def provider_name(self) -> str:
        return "kubernetes"

    def _build_client(self) -> httpx.AsyncClient:
        """Create configured async HTTP client with authentication headers and TLS."""
        if self._custom_client:
            return self._custom_client

        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        verify = self.ca_cert if self.ca_cert else True
        return httpx.AsyncClient(
            base_url=self.api_url,
            headers=headers,
            timeout=self.timeout_seconds,
            verify=verify
        )

    async def _execute_k8s_request(
        self,
        endpoint: str,
        operation: str,
        params: Optional[Dict[str, str]] = None,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute an asynchronous REST call to the Kubernetes API server.
        Converts HTTP status codes (404, 403, 401, 500) and timeouts into TelemetryProviderError.
        """
        start_time = time.perf_counter()
        client = self._build_client()
        close_client = self._custom_client is None

        try:
            response = await client.get(endpoint, params=params)
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

            if response.status_code == 404:
                logger.warning(
                    f"Kubernetes resource not found on {operation}: {endpoint}",
                    extra={
                        "service": "platform",
                        "provider": self.provider_name,
                        "trace_id": trace_id,
                        "operation": operation,
                        "status_code": 404,
                        "latency_ms": latency_ms,
                    }
                )
                raise TelemetryProviderError(
                    provider_name=self.provider_name,
                    message=f"Kubernetes resource not found for {operation}: {response.text[:200]}"
                )

            if response.status_code in (401, 403):
                logger.error(
                    f"Kubernetes permission failure on {operation}: HTTP {response.status_code}",
                    extra={
                        "service": "platform",
                        "provider": self.provider_name,
                        "trace_id": trace_id,
                        "operation": operation,
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                    }
                )
                raise TelemetryProviderError(
                    provider_name=self.provider_name,
                    message=f"Kubernetes authorization failure (HTTP {response.status_code}) on {operation}"
                )

            if response.status_code != 200:
                raise TelemetryProviderError(
                    provider_name=self.provider_name,
                    message=f"Kubernetes API error (HTTP {response.status_code}) on {operation}: {response.text[:200]}"
                )

            try:
                return response.json()
            except Exception as json_err:
                raise TelemetryProviderError(
                    provider_name=self.provider_name,
                    message=f"Malformed JSON response from Kubernetes API on {operation}",
                    original_error=json_err
                ) from json_err

        except httpx.TimeoutException as timeout_err:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                f"Kubernetes API timeout on '{operation}' after {self.timeout_seconds}s",
                extra={
                    "service": "platform",
                    "provider": self.provider_name,
                    "trace_id": trace_id,
                    "operation": operation,
                    "latency_ms": latency_ms,
                }
            )
            raise TelemetryProviderError(
                provider_name=self.provider_name,
                message=f"Kubernetes API query timed out on {operation} after {self.timeout_seconds}s",
                original_error=timeout_err
            ) from timeout_err
        except httpx.RequestError as req_err:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                f"Kubernetes API connection error on '{operation}'",
                extra={
                    "service": "platform",
                    "provider": self.provider_name,
                    "trace_id": trace_id,
                    "operation": operation,
                    "latency_ms": latency_ms,
                }
            )
            raise TelemetryProviderError(
                provider_name=self.provider_name,
                message=f"Failed to connect to Kubernetes API server at {self.api_url}: {str(req_err)}",
                original_error=req_err
            ) from req_err
        finally:
            if close_client:
                await client.aclose()

    async def get_deployment_spec(
        self,
        namespace: str,
        workload: str,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Query apps/v1 Deployment to extract spec.replicas and selector matchLabels.
        """
        endpoint = f"/apis/apps/v1/namespaces/{namespace}/deployments/{workload}"
        return await self._execute_k8s_request(
            endpoint=endpoint,
            operation="get_deployment",
            trace_id=trace_id
        )

    async def list_pods(
        self,
        namespace: str,
        label_selector: str,
        trace_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query core/v1 Pods matching labelSelector in the given namespace.
        """
        endpoint = f"/api/v1/namespaces/{namespace}/pods"
        params = {"labelSelector": label_selector} if label_selector else None
        data = await self._execute_k8s_request(
            endpoint=endpoint,
            operation="list_pods",
            params=params,
            trace_id=trace_id
        )
        return data.get("items", [])

    def _aggregate_pod_resources(
        self,
        active_pods: List[Dict[str, Any]]
    ) -> Tuple[float, float, int, int]:
        """
        Aggregate CPU requests/limits and memory requests/limits across containers
        in all active running target Pods.
        """
        total_cpu_requests = 0.0
        total_cpu_limits = 0.0
        total_mem_requests = 0
        total_mem_limits = 0

        for pod in active_pods:
            spec = pod.get("spec", {})
            containers = spec.get("containers", [])
            for container in containers:
                resources = container.get("resources", {})
                reqs = resources.get("requests", {})
                limits = resources.get("limits", {})

                total_cpu_requests += parse_cpu_quantity(reqs.get("cpu"))
                total_cpu_limits += parse_cpu_quantity(limits.get("cpu"))
                total_mem_requests += parse_memory_quantity(reqs.get("memory"))
                total_mem_limits += parse_memory_quantity(limits.get("memory"))

        return (
            round(total_cpu_requests, 4),
            round(total_cpu_limits, 4),
            total_mem_requests,
            total_mem_limits,
        )

    async def fetch_resource_state(
        self,
        namespace: str = "sentinelscale",
        workload: str = "demo-api",
        trace_id: Optional[str] = None
    ) -> ResourceState:
        """
        Fetch real Kubernetes workload state:
          1. Query target Deployment for desired replicas & label selector.
          2. Query actual Pods matching the selector.
          3. Count running, pending, and failed pods.
          4. Aggregate real container CPU and memory requests/limits.
          5. Assemble canonical ResourceState.
        """
        trace = trace_id or f"trace-{uuid.uuid4().hex[:16]}"

        # 1. Fetch Deployment Metadata & Desired Replicas
        deployment_obj = await self.get_deployment_spec(
            namespace=namespace,
            workload=workload,
            trace_id=trace
        )
        dep_spec = deployment_obj.get("spec", {})
        desired_pods = dep_spec.get("replicas", 1)

        # 2. Extract Label Selector
        match_labels = dep_spec.get("selector", {}).get("matchLabels", {})
        if match_labels:
            label_selector_str = ",".join(f"{k}={v}" for k, v in match_labels.items())
        else:
            label_selector_str = f"app={workload}"

        # 3. Fetch Actual Workload Pods
        pods = await self.list_pods(
            namespace=namespace,
            label_selector=label_selector_str,
            trace_id=trace
        )

        # 4. Discriminate Pod Phases
        running_pods_list: List[Dict[str, Any]] = []
        pending_pods_count = 0

        for pod in pods:
            phase = pod.get("status", {}).get("phase", "Unknown")
            if phase == "Running":
                running_pods_list.append(pod)
            elif phase == "Pending":
                pending_pods_count += 1
            else:
                logger.info(
                    f"Pod '{pod.get('metadata', {}).get('name')}' in non-active phase '{phase}'",
                    extra={
                        "service": "platform",
                        "provider": self.provider_name,
                        "trace_id": trace,
                        "pod_phase": phase,
                    }
                )

        running_pods_count = len(running_pods_list)

        # 5. Aggregate Resource Requests and Limits from Actual Running Pods
        if running_pods_count > 0:
            cpu_req, cpu_lim, mem_req, mem_lim = self._aggregate_pod_resources(running_pods_list)
        else:
            # When 0 pods are running, calculate per-pod spec limits from Deployment template
            template_containers = dep_spec.get("template", {}).get("spec", {}).get("containers", [])
            single_pod = {"spec": {"containers": template_containers}}
            cpu_req, cpu_lim, mem_req, mem_lim = self._aggregate_pod_resources([single_pod])

        # 6. Derived Capacity Metrics
        current_capacity_rps = running_pods_count * settings.DEFAULT_POD_RPS_CAPACITY
        estimated_required_capacity_rps = 1.0  # Baseline when traffic telemetry is not coupled

        return ResourceState(
            event_id=str(uuid.uuid4()),
            trace_id=trace,
            timestamp=datetime.now(timezone.utc).isoformat(),
            contract_version=settings.CONTRACT_VERSION,
            service_version=settings.SERVICE_VERSION,
            target_namespace=namespace,
            target_workload=workload,
            cpu_utilization=0.0,
            memory_utilization=0.0,
            cpu_requested_cores=cpu_req,
            cpu_limit_cores=cpu_lim,
            memory_requested_bytes=mem_req,
            memory_limit_bytes=mem_lim,
            running_pods=running_pods_count,
            desired_pods=desired_pods,
            pending_pods=pending_pods_count,
            request_rate=0.0,
            p95_latency_ms=0.0,
            error_rate=0.0,
            current_capacity_rps=round(current_capacity_rps, 2),
            estimated_required_capacity_rps=estimated_required_capacity_rps,
            estimated_resource_waste=0.0,
        )

