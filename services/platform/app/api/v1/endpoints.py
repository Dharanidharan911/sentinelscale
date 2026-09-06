from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from app.config.settings import settings
from app.models.anomaly import AnomalyAssessment
from app.models.context import DecisionContext, PolicyOverrides
from app.models.decision import ScalingDecision
from app.models.evaluation import EvaluationResult
from app.models.experiment import ExperimentResult, ExperimentRunSummary
from app.models.history import HistoryStats, StoredObservation
from app.models.intelligence import HistoricalDivergence, HistoricalSummary, HistoricalTrends
from app.models.prediction import PredictiveForecast
from app.models.resource import ResourceState
from app.services.context_aggregator import AggregationError, ContextAggregatorService
from app.services.decision_engine import DecisionEngine
from app.services.evaluation.base import HPAEvaluationService
from app.services.evaluation.factory import get_evaluation_service
from app.services.experiments.reader import ExperimentResultsReader, get_experiment_reader
from app.services.history.base import DecisionHistoryStore
from app.services.history.factory import get_history_store
from app.services.intelligence.anomaly import AnomalyIntelligenceService
from app.services.intelligence.base import HistoricalIntelligenceService
from app.services.intelligence.factory import (
    get_anomaly_intelligence_service,
    get_historical_intelligence_service,
    get_predictive_intelligence_service,
)
from app.services.intelligence.predictive_base import PredictiveIntelligenceService
from app.services.resource_observer import ResourceObserverService
from app.services.telemetry.base import ResourceTelemetryProvider, TelemetryProviderError
from app.services.telemetry.factory import get_telemetry_provider

router = APIRouter(tags=["Platform & Resource Intelligence"])


class OrchestrationRequest(BaseModel):
    namespace: str = Field(default="sentinelscale", description="Target Kubernetes namespace.")
    workload: str = Field(default="demo-api", description="Target workload / Deployment name.")
    window_seconds: int = Field(default=60, ge=1, description="Observation time window for Traffic Intelligence.")
    forecast_horizon_seconds: int = Field(default=300, ge=1, description="Forecasting horizon for Demand Intelligence.")
    policy_overrides: Optional[PolicyOverrides] = Field(default=None, description="Optional runtime policy constraints.")


def get_resource_observer(
    provider: ResourceTelemetryProvider = Depends(get_telemetry_provider)
) -> ResourceObserverService:
    return ResourceObserverService(provider=provider)


def get_decision_engine() -> DecisionEngine:
    return DecisionEngine()


def get_context_aggregator(
    observer: ResourceObserverService = Depends(get_resource_observer),
    engine: DecisionEngine = Depends(get_decision_engine),
) -> ContextAggregatorService:
    return ContextAggregatorService(
        resource_observer=observer,
        decision_engine=engine,
    )


def get_history_repository() -> DecisionHistoryStore:
    return get_history_store()


@router.get("/resources/current", response_model=ResourceState)
async def get_current_resources(
    namespace: str = Query(default="sentinelscale", description="Kubernetes namespace"),
    workload: str = Query(default="demo-api", description="Workload/Deployment name"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
    observer: ResourceObserverService = Depends(get_resource_observer),
) -> ResourceState:
    """
    Retrieve real-time resource utilization and capacity state for a target workload.
    """
    try:
        return await observer.get_current_resource_state(
            namespace=namespace,
            workload=workload,
            trace_id=x_trace_id
        )
    except TelemetryProviderError as err:
        raise HTTPException(
            status_code=502,
            detail=f"Telemetry Provider Failure: {err.message}"
        ) from err


@router.post("/decision/evaluate", response_model=ScalingDecision)
async def evaluate_decision(
    context: DecisionContext,
    engine: DecisionEngine = Depends(get_decision_engine),
) -> ScalingDecision:
    """
    Direct evaluation: Evaluate a scaling decision from a pre-constructed DecisionContext.
    Calculates security-aware recommendation, baseline HPA comparison,
    and enforces safety guardrails in dry-run mode.
    Preserved for backward compatibility and deterministic replays.
    """
    return await engine.evaluate_decision(context)


@router.post("/decision/orchestrate", response_model=ScalingDecision)
async def orchestrate_decision(
    request: OrchestrationRequest = OrchestrationRequest(),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
    aggregator: ContextAggregatorService = Depends(get_context_aggregator),
) -> ScalingDecision:
    """
    Phase 3B Orchestration: Concurrently queries Traffic Intelligence (Module 1),
    Demand Intelligence (Module 2), and Resource State (Module 3), constructs a canonical
    DecisionContext, and executes the deterministic DecisionEngine to return a ScalingDecision.
    """
    try:
        return await aggregator.orchestrate_decision(
            namespace=request.namespace,
            workload=request.workload,
            window_seconds=request.window_seconds,
            forecast_horizon_seconds=request.forecast_horizon_seconds,
            policy_overrides=request.policy_overrides,
            trace_id=x_trace_id,
        )
    except AggregationError as agg_err:
        raise HTTPException(
            status_code=502,
            detail=f"Decision Orchestration Failure: [{agg_err.source}] {agg_err.message}",
        ) from agg_err
    except TelemetryProviderError as tel_err:
        raise HTTPException(
            status_code=502,
            detail=f"Telemetry Provider Failure: {tel_err.message}",
        ) from tel_err


@router.post("/decision/aggregate", response_model=DecisionContext)
async def aggregate_decision_context(
    request: OrchestrationRequest = OrchestrationRequest(),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
    aggregator: ContextAggregatorService = Depends(get_context_aggregator),
) -> DecisionContext:
    """
    Phase 3B Context Aggregation: Concurrently queries Traffic Intelligence, Demand Intelligence,
    and Resource State, and returns the aggregated, schema-compliant DecisionContext without evaluation.
    """
    try:
        return await aggregator.aggregate_context(
            namespace=request.namespace,
            workload=request.workload,
            window_seconds=request.window_seconds,
            forecast_horizon_seconds=request.forecast_horizon_seconds,
            policy_overrides=request.policy_overrides,
            trace_id=x_trace_id,
        )
    except AggregationError as agg_err:
        raise HTTPException(
            status_code=502,
            detail=f"Decision Context Aggregation Failure: [{agg_err.source}] {agg_err.message}",
        ) from agg_err
    except TelemetryProviderError as tel_err:
        raise HTTPException(
            status_code=502,
            detail=f"Telemetry Provider Failure: {tel_err.message}",
        ) from tel_err


# ==============================================================================
# Phase 4B: Read-Only Decision History & Audit Endpoints
# ==============================================================================

@router.get("/history", response_model=List[StoredObservation])
async def list_history(
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of records to return."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
    success: Optional[bool] = Query(default=None, description="Filter by evaluation success status."),
    action: Optional[str] = Query(default=None, description="Filter by scaling action (e.g. HOLD, SCALE)."),
    trace_id: Optional[str] = Query(default=None, description="Filter by distributed trace ID."),
    store: DecisionHistoryStore = Depends(get_history_repository),
) -> List[StoredObservation]:
    """
    Retrieve historical observation evaluations ordered newest-first with pagination and filters.
    """
    return store.list_observations(
        limit=limit,
        offset=offset,
        success=success,
        action=action,
        trace_id=trace_id,
    )


@router.get("/history/stats", response_model=HistoryStats)
async def get_history_stats(
    store: DecisionHistoryStore = Depends(get_history_repository),
) -> HistoryStats:
    """
    Retrieve summary metrics for recorded observations.
    """
    return store.get_stats(retention_days=settings.DECISION_HISTORY_RETENTION_DAYS)


@router.get("/history/{observation_id}", response_model=StoredObservation)
async def get_history_item(
    observation_id: str,
    store: DecisionHistoryStore = Depends(get_history_repository),
) -> StoredObservation:
    """
    Retrieve full audit fidelity for a single observation record by UUID.
    """
    observation = store.get_observation(observation_id=observation_id)
    if not observation:
        raise HTTPException(status_code=404, detail=f"Observation '{observation_id}' not found.")
    return observation


# ==============================================================================
# Phase 5A: Read-Only Historical Intelligence Foundation Endpoints
# ==============================================================================

def get_historical_intelligence() -> HistoricalIntelligenceService:
    return get_historical_intelligence_service()


@router.get("/intelligence/history/summary", response_model=HistoricalSummary)
async def get_history_summary(
    window: Optional[str] = Query(default=None, description="Pre-defined time window (5m, 15m, 1h, 6h, 24h, 7d)."),
    start_time: Optional[str] = Query(default=None, description="ISO-8601 start timestamp for custom range."),
    end_time: Optional[str] = Query(default=None, description="ISO-8601 end timestamp for custom range."),
    service: HistoricalIntelligenceService = Depends(get_historical_intelligence),
) -> HistoricalSummary:
    """
    Retrieve comprehensive statistical summary of historical observations,
    scaling actions, demand trends, traffic risk, and baseline HPA divergence.
    """
    try:
        return service.get_summary(window=window, start_time=start_time, end_time=end_time)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err)) from val_err


@router.get("/intelligence/history/trends", response_model=HistoricalTrends)
async def get_history_trends(
    window: Optional[str] = Query(default=None, description="Pre-defined time window (5m, 15m, 1h, 6h, 24h, 7d)."),
    start_time: Optional[str] = Query(default=None, description="ISO-8601 start timestamp for custom range."),
    end_time: Optional[str] = Query(default=None, description="ISO-8601 end timestamp for custom range."),
    bucket_seconds: Optional[int] = Query(default=None, ge=1, description="Optional custom bucket duration in seconds."),
    service: HistoricalIntelligenceService = Depends(get_historical_intelligence),
) -> HistoricalTrends:
    """
    Retrieve chronological time-bucketed historical trends for metric visualization.
    """
    try:
        return service.get_trends(
            window=window,
            start_time=start_time,
            end_time=end_time,
            bucket_seconds=bucket_seconds,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err)) from val_err


@router.get("/intelligence/history/divergence", response_model=HistoricalDivergence)
async def get_history_divergence(
    window: Optional[str] = Query(default=None, description="Pre-defined time window (5m, 15m, 1h, 6h, 24h, 7d)."),
    start_time: Optional[str] = Query(default=None, description="ISO-8601 start timestamp for custom range."),
    end_time: Optional[str] = Query(default=None, description="ISO-8601 end timestamp for custom range."),
    service: HistoricalIntelligenceService = Depends(get_historical_intelligence),
) -> HistoricalDivergence:
    """
    Retrieve detailed comparative analysis and divergence metrics between SentinelScale
    and naive reactive HPA recommendations.
    """
    try:
        return service.get_divergence(window=window, start_time=start_time, end_time=end_time)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err)) from val_err


# ==============================================================================
# Phase 5B: Read-Only Behavioral Baseline & Anomaly Intelligence Endpoints
# ==============================================================================

def get_anomaly_intelligence() -> AnomalyIntelligenceService:
    return get_anomaly_intelligence_service()


@router.get("/intelligence/anomalies", response_model=AnomalyAssessment)
async def get_anomalies(
    window: Optional[str] = Query(default=None, description="Pre-defined baseline window (5m, 15m, 1h, 6h, 24h, 7d)."),
    start_time: Optional[str] = Query(default=None, description="ISO-8601 start timestamp for baseline window."),
    end_time: Optional[str] = Query(default=None, description="ISO-8601 end timestamp for baseline window."),
    observation_id: Optional[str] = Query(default=None, description="Optional UUID of specific historical observation to assess."),
    predicted_legitimate_rps: Optional[float] = Query(default=None, description="Current predicted legitimate RPS."),
    traffic_risk: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="Current assessed traffic risk score."),
    current_capacity_rps: Optional[float] = Query(default=None, description="Current cluster capacity in RPS."),
    recommended_pods: Optional[int] = Query(default=None, ge=1, description="Current recommended pods."),
    current_pods: Optional[int] = Query(default=None, ge=1, description="Current running pods."),
    baseline_hpa_recommended_pods: Optional[int] = Query(default=None, ge=1, description="Current baseline HPA recommended pods."),
    pod_delta_vs_baseline: Optional[int] = Query(default=None, description="Current signed divergence vs reactive HPA."),
    history_store: DecisionHistoryStore = Depends(get_history_repository),
    anomaly_service: AnomalyIntelligenceService = Depends(get_anomaly_intelligence),
) -> AnomalyAssessment:
    """
    Evaluate current metrics against historical behavioral baselines to detect anomalies.
    Purely read-only; does not trigger evaluations, query upstream microservices, or mutate state.
    """
    obs_context: Optional[StoredObservation] = None
    current_vals: dict[str, float] = {}

    if observation_id is not None:
        obs = history_store.get_observation(observation_id=observation_id)
        if not obs:
            raise HTTPException(status_code=404, detail=f"Observation '{observation_id}' not found.")
        obs_context = obs
        if obs.predicted_legitimate_rps is not None:
            current_vals["predicted_legitimate_rps"] = obs.predicted_legitimate_rps
        if obs.traffic_risk is not None:
            current_vals["traffic_risk"] = obs.traffic_risk
        if obs.current_capacity_rps is not None:
            current_vals["current_capacity_rps"] = obs.current_capacity_rps
        if obs.recommended_pods is not None:
            current_vals["recommended_pods"] = float(obs.recommended_pods)
        if obs.current_pods is not None:
            current_vals["current_pods"] = float(obs.current_pods)
        if obs.baseline_hpa_recommended_pods is not None:
            current_vals["baseline_hpa_recommended_pods"] = float(obs.baseline_hpa_recommended_pods)
        if obs.pod_delta_vs_baseline is not None:
            current_vals["pod_delta_vs_baseline"] = float(obs.pod_delta_vs_baseline)
    else:
        # Check query param overrides
        if predicted_legitimate_rps is not None:
            current_vals["predicted_legitimate_rps"] = predicted_legitimate_rps
        if traffic_risk is not None:
            current_vals["traffic_risk"] = traffic_risk
        if current_capacity_rps is not None:
            current_vals["current_capacity_rps"] = current_capacity_rps
        if recommended_pods is not None:
            current_vals["recommended_pods"] = float(recommended_pods)
        if current_pods is not None:
            current_vals["current_pods"] = float(current_pods)
        if baseline_hpa_recommended_pods is not None:
            current_vals["baseline_hpa_recommended_pods"] = float(baseline_hpa_recommended_pods)
        if pod_delta_vs_baseline is not None:
            current_vals["pod_delta_vs_baseline"] = float(pod_delta_vs_baseline)

        # If no values provided at all, fallback to latest successful observation in history
        if not current_vals:
            latest = history_store.list_observations(limit=1, success=True)
            if latest:
                obs_context = latest[0]
                if obs_context.predicted_legitimate_rps is not None:
                    current_vals["predicted_legitimate_rps"] = obs_context.predicted_legitimate_rps
                if obs_context.traffic_risk is not None:
                    current_vals["traffic_risk"] = obs_context.traffic_risk
                if obs_context.current_capacity_rps is not None:
                    current_vals["current_capacity_rps"] = obs_context.current_capacity_rps
                if obs_context.recommended_pods is not None:
                    current_vals["recommended_pods"] = float(obs_context.recommended_pods)
                if obs_context.current_pods is not None:
                    current_vals["current_pods"] = float(obs_context.current_pods)
                if obs_context.baseline_hpa_recommended_pods is not None:
                    current_vals["baseline_hpa_recommended_pods"] = float(obs_context.baseline_hpa_recommended_pods)
                if obs_context.pod_delta_vs_baseline is not None:
                    current_vals["pod_delta_vs_baseline"] = float(obs_context.pod_delta_vs_baseline)

    try:
        return anomaly_service.assess_anomalies(
            current_values=current_vals,
            window=window,
            start_time=start_time,
            end_time=end_time,
            observation_context=obs_context,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err)) from val_err


# ==============================================================================
# Phase 5C: Read-Only Adaptive Predictive Intelligence Endpoints
# ==============================================================================

def get_predictive_intelligence() -> PredictiveIntelligenceService:
    return get_predictive_intelligence_service()


@router.get("/intelligence/predictions", response_model=PredictiveForecast)
async def get_predictive_forecast(
    window: Optional[str] = Query(default=None, description="Lookback window (e.g. '5m', '15m', '1h', '6h', '24h', '7d')."),
    horizon: Optional[str] = Query(default=None, description="Forecast horizon string (e.g. '5m', '15m', '30m', '1h')."),
    horizon_seconds: Optional[int] = Query(default=None, ge=1, description="Forecast horizon in seconds."),
    start_time: Optional[str] = Query(default=None, description="ISO-8601 start timestamp for custom range."),
    end_time: Optional[str] = Query(default=None, description="ISO-8601 end timestamp for custom range."),
    observation_id: Optional[str] = Query(default=None, description="Specific reference observation ID to anchor prediction."),
    service: PredictiveIntelligenceService = Depends(get_predictive_intelligence),
) -> PredictiveForecast:
    """
    Retrieve deterministic, short-horizon predictive forecast of operational signals,
    capacity pressure, and advisory pod requirements.
    """
    try:
        return service.generate_forecast(
            window=window,
            horizon=horizon,
            horizon_seconds=horizon_seconds,
            start_time=start_time,
            end_time=end_time,
            observation_id=observation_id,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err)) from val_err


# ==============================================================================
# HPA vs. SentinelScale Formal Evaluation Endpoints
# ==============================================================================

def get_evaluation() -> HPAEvaluationService:
    return get_evaluation_service()


@router.post("/evaluation/evaluate", response_model=EvaluationResult)
async def evaluate_hpa_vs_sentinelscale(
    context: DecisionContext,
    service: HPAEvaluationService = Depends(get_evaluation),
) -> EvaluationResult:
    """
    Formally evaluate and compare Traditional Kubernetes HPA vs. SentinelScale
    from a given DecisionContext, outputting comparative metrics and explanations.
    """
    try:
        return await service.evaluate_context(context)
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err)) from val_err


@router.get("/evaluation/hpa-vs-sentinelscale", response_model=EvaluationResult)
async def get_hpa_vs_sentinelscale_evaluation(
    observation_id: Optional[str] = Query(default=None, description="Observation ID to evaluate. Defaults to latest observation."),
    service: HPAEvaluationService = Depends(get_evaluation),
    history_repo: DecisionHistoryStore = Depends(get_history_repository),
) -> EvaluationResult:
    """
    Retrieve formal HPA vs SentinelScale evaluation for a specific observation ID or the latest recorded observation.
    """
    try:
        if observation_id:
            return service.evaluate_observation_id(observation_id)

        # Default to latest successful observation
        latest_records = history_repo.list_observations(limit=1, success=True)
        if not latest_records:
            raise HTTPException(
                status_code=404,
                detail="No historical observations found to evaluate."
            )
        return service.evaluate_observation_id(latest_records[0].id)
    except HTTPException:
        raise
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err)) from val_err


# ==============================================================================
# Empirical M3-8 Comparative Experiment Endpoints (Stage M3-11D)
# ==============================================================================

def get_experiments_service() -> ExperimentResultsReader:
    return get_experiment_reader()


@router.get("/experiments", response_model=List[ExperimentRunSummary])
async def list_experiments(
    scenario_id: Optional[str] = Query(default=None, description="Optional filter by scenario identifier (e.g. 'scenario_a_normal')."),
    service: ExperimentResultsReader = Depends(get_experiments_service),
) -> List[ExperimentRunSummary]:
    """
    Retrieve list of empirical M3-8 HPA vs SentinelScale benchmark experiment trials.
    Strictly read-only discovery of canonical experiment results.
    """
    return service.list_experiments(scenario_id=scenario_id)


@router.get("/experiments/{run_id}", response_model=ExperimentResult)
async def get_experiment_by_run_id(
    run_id: str,
    service: ExperimentResultsReader = Depends(get_experiments_service),
) -> ExperimentResult:
    """
    Retrieve detailed canonical M3-8 experiment result including complete timeseries telemetry.
    """
    experiment = service.get_experiment(run_id=run_id)
    if not experiment:
        raise HTTPException(
            status_code=404,
            detail=f"Experiment trial '{run_id}' not found."
        )
    return experiment

