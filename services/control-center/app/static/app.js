// ==============================================================================
// SentinelScale Control Center — Operator Console Frontend Controller
// Stage: M3-11C (Scaling Comparison, Historical Trends & Anomaly Intelligence)
// ==============================================================================

(function () {
  "use strict";

  const POLLING_INTERVAL_MS = 4000;
  let isEvaluating = false;
  let selectedTrendWindow = "1h";
  let selectedHistoryAction = "";
  let lastEvaluationTime = null;
  let latestTraceId = null;
  let lastObservedCpu = 0;
  let lastObservedRps = 0;

  // DOM Elements — Top Bar & Safety
  const elSyncStatus = document.getElementById("sync-status");
  const elLastUpdated = document.getElementById("last-updated");
  const btnEvaluate = document.getElementById("btn-evaluate");
  const elSafetyShadow = document.getElementById("safety-shadow");
  const elSafetyDryRun = document.getElementById("safety-dryrun");
  const elSafetyAutonomous = document.getElementById("safety-autonomous");
  const elSafetyMutations = document.getElementById("safety-mutations");

  // DOM Elements — Tri-Intelligence
  const elRunningPods = document.getElementById("res-running-pods");
  const elDesiredPending = document.getElementById("res-desired-pending");
  const elCpuVal = document.getElementById("res-cpu-val");
  const elCpuFill = document.getElementById("res-cpu-fill");
  const elMemVal = document.getElementById("res-mem-val");
  const elMemFill = document.getElementById("res-mem-fill");
  const elCapacity = document.getElementById("res-capacity");
  const elRateP95 = document.getElementById("res-rate-p95");

  const elTrafficClass = document.getElementById("traffic-classification");
  const elTrafficRiskVal = document.getElementById("traffic-risk-val");
  const elTrafficRiskFill = document.getElementById("traffic-risk-fill");
  const elTrafficTotal = document.getElementById("traffic-total-rps");
  const elTrafficLegit = document.getElementById("traffic-legit-rps");
  const elTrafficSusp = document.getElementById("traffic-susp-rps");
  const elTrafficSignals = document.getElementById("traffic-signals");

  const elDemandPred = document.getElementById("demand-pred-rps");
  const elDemandBounds = document.getElementById("demand-bounds-rps");
  const elDemandConf = document.getElementById("demand-confidence");
  const elDemandTime = document.getElementById("demand-generated-at");
  const elDemandHorizon = document.getElementById("demand-horizon");

  // DOM Elements — Decision & Comparison Hero
  const elHpaPods = document.getElementById("hpa-pods-val");
  const elSsPods = document.getElementById("ss-pods-val");
  const elDeltaPill = document.getElementById("comparison-delta-pill");
  const elDeltaNarrative = document.getElementById("comparison-narrative");
  const elActionTag = document.getElementById("decision-action-tag");
  const elPolicyTag = document.getElementById("decision-policy-tag");
  const elReason = document.getElementById("decision-reason");
  const elContributingSignals = document.getElementById("contributing-signals");
  const elDecisionId = document.getElementById("decision-id");
  const elTraceId = document.getElementById("decision-trace-id");
  const elConfidence = document.getElementById("decision-confidence");
  const elTimestamp = document.getElementById("decision-timestamp");
  const elDecisionAge = document.getElementById("decision-age");
  const elEvalAlertBanner = document.getElementById("eval-alert-banner");
  const elEvalAlertMessage = document.getElementById("eval-alert-message");
  const elTempoShortcut = document.getElementById("tempo-shortcut");

  // DOM Elements — Causal Pipeline
  const elCausalRawRps = document.getElementById("causal-raw-rps");
  const elCausalRawCpu = document.getElementById("causal-raw-cpu");
  const elCausalRiskScore = document.getElementById("causal-risk-score");
  const elCausalFilteredRps = document.getElementById("causal-filtered-rps");
  const elCausalLegitRps = document.getElementById("causal-legit-rps");
  const elCausalDemandConf = document.getElementById("causal-demand-conf");
  const elCausalCapacityRps = document.getElementById("causal-capacity-rps");
  const elCausalHeadroom = document.getElementById("causal-headroom");
  const elCausalPolicyName = document.getElementById("causal-policy-name");
  const elCausalFinalAction = document.getElementById("causal-final-action");
  const elCausalFinalPods = document.getElementById("causal-final-pods");

  // DOM Elements — M3-11C Trends & Anomalies
  const elTrendWindowBadge = document.getElementById("trend-window-badge");
  const elTrendSvg = document.getElementById("trend-chart-svg");
  const elTstatAvgDemand = document.getElementById("tstat-avg-demand");
  const elTstatPeakRisk = document.getElementById("tstat-peak-risk");
  const elTstatAvgDiv = document.getElementById("tstat-avg-div");
  const elTstatBuckets = document.getElementById("tstat-buckets");

  const elAnomalyOverallBadge = document.getElementById("anomaly-overall-badge");
  const elAnomalySampleCount = document.getElementById("anomaly-sample-count");
  const elAnomalyExplanationBox = document.getElementById("anomaly-explanation-container");
  const elAnomalyExplanationText = document.getElementById("anomaly-explanation-text");
  const elAnomalySignalsGrid = document.getElementById("anomaly-signals-grid");
  const elAnomalyPatternContainer = document.getElementById("anomaly-pattern-container");
  const elAnomalyPatternChips = document.getElementById("anomaly-pattern-chips");

  // DOM Elements — M3-11C Decision History
  const elHistoryTotalBadge = document.getElementById("history-total-badge");
  const elHistSuccessRate = document.getElementById("hist-success-rate");
  const elHistRetention = document.getElementById("hist-retention");
  const elHistoryBody = document.getElementById("history-tbody");

  // DOM Elements — M3-11D Benchmark Experiments
  const elExpTotalBadge = document.getElementById("exp-total-badge");
  const elExpSelect = document.getElementById("experiment-select");
  const elExpScenarioName = document.getElementById("exp-scenario-name");
  const elExpScenarioId = document.getElementById("exp-scenario-id");
  const elExpDurationPill = document.getElementById("exp-duration-pill");
  const elExpDivergencePill = document.getElementById("exp-divergence-pill");
  const elExpGuardrailsPill = document.getElementById("exp-guardrails-pill");
  const elExpSafetyPill = document.getElementById("exp-safety-pill");
  const elExpGrafanaLink = document.getElementById("exp-grafana-link");
  const elExpHpaPeakInit = document.getElementById("exp-hpa-peak-init");
  const elExpHpaReplicaHours = document.getElementById("exp-hpa-replica-hours");
  const elExpHpaPodSeconds = document.getElementById("exp-hpa-pod-seconds");
  const elExpHpaScaleEvents = document.getElementById("exp-hpa-scale-events");
  const elExpSsPeakInit = document.getElementById("exp-ss-peak-init");
  const elExpSsReplicaHours = document.getElementById("exp-ss-replica-hours");
  const elExpSsPodSeconds = document.getElementById("exp-ss-pod-seconds");
  const elExpSsDecisionsCount = document.getElementById("exp-ss-decisions-count");
  const elExpDeltaBadge = document.getElementById("exp-delta-badge");
  const elExpDeltaPodSeconds = document.getElementById("exp-delta-pod-seconds");
  const elExpDeltaReplicaHours = document.getElementById("exp-delta-replica-hours");
  const elExpDeltaMaxDiff = document.getElementById("exp-delta-max-diff");
  const elExpDeltaClassification = document.getElementById("exp-delta-classification");
  const elExpKpiGuardrailBadge = document.getElementById("exp-kpi-guardrail-badge");
  const elExpWorkloadReqsRps = document.getElementById("exp-workload-reqs-rps");
  const elExpWorkloadPeakRps = document.getElementById("exp-workload-peak-rps");
  const elExpGuardrailP95 = document.getElementById("exp-guardrail-p95");
  const elExpGuardrailErrors = document.getElementById("exp-guardrail-errors");
  const elExpChartContainer = document.getElementById("exp-chart-container");
  const elExpChartSvg = document.getElementById("exp-chart-svg");
  const elExpChartTooltip = document.getElementById("exp-chart-tooltip");
  const elExpPhasesChips = document.getElementById("exp-phases-chips");
  const elExpActionsChips = document.getElementById("exp-actions-chips");

  let loadedExperiments = [];
  let currentSelectedExperimentId = null;

  function updateClock() {
    const now = new Date();
    elLastUpdated.textContent = now.toTimeString().split(" ")[0];
    updateDecisionAge();
  }

  function updateDecisionAge() {
    if (!lastEvaluationTime) {
      elDecisionAge.textContent = "NOT EVALUATED";
      elDecisionAge.className = "age-badge";
      return;
    }
    const elapsedSec = Math.floor((Date.now() - lastEvaluationTime.getTime()) / 1000);
    if (elapsedSec < 5) {
      elDecisionAge.textContent = "JUST NOW";
      elDecisionAge.className = "age-badge";
    } else if (elapsedSec < 60) {
      elDecisionAge.textContent = `${elapsedSec}s AGO`;
      elDecisionAge.className = "age-badge";
    } else {
      const min = Math.floor(elapsedSec / 60);
      elDecisionAge.textContent = `${min}m ${elapsedSec % 60}s AGO (STALE)`;
      elDecisionAge.className = "age-badge age-badge-stale";
    }
  }

  async function fetchSafetyState() {
    try {
      const res = await fetch("/api/proxy/version");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      elSafetyShadow.textContent = data.shadow_mode ? "ACTIVE" : "INACTIVE";
      elSafetyDryRun.textContent = data.dry_run ? "ACTIVE" : "DISABLED";
      elSafetyAutonomous.textContent = data.autonomous_actions_enabled ? "ENABLED" : "DISABLED";
      elSafetyMutations.textContent = "0 (READ-ONLY)";
    } catch (err) {
      console.warn("Safety state fetch error:", err);
      elSafetyShadow.textContent = "ACTIVE (ENV)";
      elSafetyDryRun.textContent = "ACTIVE (ENV)";
    }
  }

  async function fetchResourceState() {
    try {
      const res = await fetch("/api/proxy/resources/current?namespace=default&workload=demo-api");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      elRunningPods.textContent = data.running_pods !== undefined ? data.running_pods : "--";
      elDesiredPending.textContent = `${data.desired_pods ?? "--"} / ${data.pending_pods ?? "--"}`;

      const cpuPct = Math.round((data.cpu_utilization || 0) * 100);
      lastObservedCpu = cpuPct;
      elCpuVal.textContent = `${cpuPct}%`;
      elCpuFill.style.width = `${Math.min(100, Math.max(0, cpuPct))}%`;
      if (cpuPct > 80) elCpuFill.style.backgroundColor = "#f43f5e";
      else if (cpuPct > 60) elCpuFill.style.backgroundColor = "#f59e0b";
      else elCpuFill.style.backgroundColor = "#06b6d4";

      const memPct = Math.round((data.memory_utilization || 0) * 100);
      elMemVal.textContent = `${memPct}%`;
      elMemFill.style.width = `${Math.min(100, Math.max(0, memPct))}%`;

      elCapacity.textContent = data.current_capacity_rps ? `${data.current_capacity_rps.toFixed(1)} RPS` : "-- RPS";

      const rps = data.request_rate !== undefined ? data.request_rate.toFixed(1) : "--";
      lastObservedRps = data.request_rate || 0;
      const p95 = data.p95_latency_ms !== undefined ? data.p95_latency_ms.toFixed(1) : "--";
      elRateP95.textContent = `${rps} RPS / ${p95} ms`;

      updateClock();
      elSyncStatus.textContent = "LIVE (4s)";
    } catch (err) {
      console.warn("Resource state fetch error:", err);
      elSyncStatus.textContent = "DEGRADED (RETRYING)";
    }
  }

  // ============================================================================
  // M3-11C: HISTORICAL TRENDS RENDERING (Browser-Native SVG)
  // ============================================================================

  window.selectTrendWindow = function (win) {
    selectedTrendWindow = win;
    document.querySelectorAll(".window-controls .btn-tab").forEach(btn => {
      btn.classList.toggle("active", btn.getAttribute("data-window") === win);
    });
    elTrendWindowBadge.textContent = `${win.toUpperCase()} WINDOW`;
    fetchHistoricalTrends();
  };

  function renderTrendChart(trends) {
    if (!trends || !trends.buckets || trends.buckets.length === 0) {
      elTrendSvg.innerHTML = `
        <text x="270" y="90" text-anchor="middle" fill="#64748b" font-family="monospace" font-size="12">
          Insufficient trend observations recorded for this window.
        </text>
      `;
      elTstatAvgDemand.textContent = "-- RPS";
      elTstatPeakRisk.textContent = "--";
      elTstatAvgDiv.textContent = "--";
      elTstatBuckets.textContent = "0";
      return;
    }

    const buckets = trends.buckets;
    const count = buckets.length;
    elTstatBuckets.textContent = `${count}`;

    // Compute stats across buckets
    let sumDemand = 0, demandCount = 0;
    let peakRisk = 0;
    let sumDiv = 0, divCount = 0;

    buckets.forEach(b => {
      if (b.average_predicted_legitimate_rps !== null && b.average_predicted_legitimate_rps !== undefined) {
        sumDemand += b.average_predicted_legitimate_rps;
        demandCount++;
      }
      if (b.average_traffic_risk !== null && b.average_traffic_risk !== undefined) {
        if (b.average_traffic_risk > peakRisk) peakRisk = b.average_traffic_risk;
      }
      if (b.average_divergence !== null && b.average_divergence !== undefined) {
        sumDiv += b.average_divergence;
        divCount++;
      }
    });

    elTstatAvgDemand.textContent = demandCount > 0 ? `${(sumDemand / demandCount).toFixed(1)} RPS` : "-- RPS";
    elTstatPeakRisk.textContent = peakRisk.toFixed(2);
    elTstatAvgDiv.textContent = divCount > 0 ? `${(sumDiv / divCount).toFixed(1)}` : "--";

    // Chart dimensions
    const width = 540;
    const height = 180;
    const padX = 40;
    const padY = 20;
    const plotW = width - padX - 15;
    const plotH = height - padY - 25;

    // Find max RPS value for scale
    let maxRps = 200;
    buckets.forEach(b => {
      const d = b.average_predicted_legitimate_rps || 0;
      const c = b.average_current_capacity_rps || 0;
      if (d > maxRps) maxRps = d;
      if (c > maxRps) maxRps = c;
    });
    maxRps = Math.ceil(maxRps * 1.15);

    // Build SVG Grid & Axes
    let svgContent = `
      <!-- Grid Lines -->
      <line x1="${padX}" y1="${padY}" x2="${width - 15}" y2="${padY}" class="chart-grid-line" />
      <line x1="${padX}" y1="${padY + plotH / 2}" x2="${width - 15}" y2="${padY + plotH / 2}" class="chart-grid-line" />
      <line x1="${padX}" y1="${padY + plotH}" x2="${width - 15}" y2="${padY + plotH}" class="chart-grid-line" />

      <!-- Y-Axis Labels (RPS) -->
      <text x="${padX - 5}" y="${padY + 4}" text-anchor="end" class="chart-axis-text">${maxRps}</text>
      <text x="${padX - 5}" y="${padY + plotH / 2 + 3}" text-anchor="end" class="chart-axis-text">${Math.round(maxRps / 2)}</text>
      <text x="${padX - 5}" y="${padY + plotH + 2}" text-anchor="end" class="chart-axis-text">0</text>
    `;

    // Coordinates generator
    const getX = (idx) => count === 1 ? padX + plotW / 2 : padX + (idx / (count - 1)) * plotW;
    const getY_Rps = (val) => padY + plotH - ((val || 0) / maxRps) * plotH;
    const getY_Risk = (val) => padY + plotH - (Math.min(1.0, Math.max(0, val || 0))) * plotH;
    const getY_Pods = (val) => padY + plotH - (Math.min(10, Math.max(0, val || 0)) / 10) * plotH;

    // Generate Path Data
    const ptsDemand = [];
    const ptsCapacity = [];
    const ptsRisk = [];
    const ptsPods = [];

    buckets.forEach((b, idx) => {
      const x = getX(idx);
      const d = b.average_predicted_legitimate_rps ?? 0;
      const c = b.average_current_capacity_rps ?? 0;
      const r = b.average_traffic_risk ?? 0;
      const p = b.average_recommended_pods ?? 0;

      ptsDemand.push(`${x.toFixed(1)},${getY_Rps(d).toFixed(1)}`);
      ptsCapacity.push(`${x.toFixed(1)},${getY_Rps(c).toFixed(1)}`);
      ptsRisk.push(`${x.toFixed(1)},${getY_Risk(r).toFixed(1)}`);
      ptsPods.push(`${x.toFixed(1)},${getY_Pods(p).toFixed(1)}`);
    });

    // Area fill for demand
    if (ptsDemand.length > 0) {
      const firstX = getX(0).toFixed(1);
      const lastX = getX(count - 1).toFixed(1);
      const baseLineY = (padY + plotH).toFixed(1);
      const areaPath = `M ${firstX},${baseLineY} L ${ptsDemand.join(" L ")} L ${lastX},${baseLineY} Z`;
      svgContent += `<path d="${areaPath}" class="chart-area-demand" />`;
    }

    // Capacity Line (Dashed Blue)
    if (ptsCapacity.length > 0) {
      svgContent += `<polyline points="${ptsCapacity.join(" ")}" class="chart-line-capacity" />`;
    }

    // Demand Line (Solid Cyan)
    if (ptsDemand.length > 0) {
      svgContent += `<polyline points="${ptsDemand.join(" ")}" class="chart-line-demand" />`;
    }

    // Risk Line (Rose Red)
    if (ptsRisk.length > 0) {
      svgContent += `<polyline points="${ptsRisk.join(" ")}" class="chart-line-risk" />`;
    }

    // Pods Line (Emerald Green)
    if (ptsPods.length > 0) {
      svgContent += `<polyline points="${ptsPods.join(" ")}" class="chart-line-pods" />`;
    }

    // X-Axis Time Labels (First, Middle, Last)
    const firstTime = buckets[0].bucket_start ? buckets[0].bucket_start.split("T")[1]?.slice(0, 5) : "";
    const lastTime = buckets[count - 1].bucket_end ? buckets[count - 1].bucket_end.split("T")[1]?.slice(0, 5) : "";
    svgContent += `
      <text x="${padX}" y="${height - 5}" text-anchor="start" class="chart-axis-text">${firstTime}</text>
      <text x="${width - 15}" y="${height - 5}" text-anchor="end" class="chart-axis-text">${lastTime}</text>
    `;

    elTrendSvg.innerHTML = svgContent;
  }

  async function fetchHistoricalTrends() {
    try {
      const res = await fetch(`/api/proxy/intelligence/trends?window=${selectedTrendWindow}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderTrendChart(data);
    } catch (err) {
      console.warn("Historical trends fetch error:", err);
    }
  }

  // ============================================================================
  // M3-11C: ANOMALY INTELLIGENCE RENDERING
  // ============================================================================

  function renderAnomalyAssessment(data) {
    if (!data) return;

    const sev = (data.overall_severity || "NORMAL").toUpperCase();
    elAnomalyOverallBadge.textContent = sev;
    elAnomalyOverallBadge.className = `card-badge badge-anomaly badge-anomaly-${sev.toLowerCase()}`;

    const sampleCount = data.signals && data.signals.length > 0 ? (data.signals[0].sample_count ?? "--") : "--";
    elAnomalySampleCount.textContent = `Baseline: ${sampleCount} samples`;

    // Explanation
    elAnomalyExplanationText.textContent = data.explanation || "All operational metrics within expected baseline range.";
    if (sev === "ANOMALOUS") {
      elAnomalyExplanationBox.style.borderLeftColor = "var(--rose-danger)";
    } else if (sev === "ELEVATED") {
      elAnomalyExplanationBox.style.borderLeftColor = "var(--amber-warning)";
    } else {
      elAnomalyExplanationBox.style.borderLeftColor = "var(--emerald-green)";
    }

    // Signals Grid
    const signals = data.signals || [];
    if (signals.length === 0) {
      elAnomalySignalsGrid.innerHTML = `<div class="loading-cell" style="grid-column: 1 / -1;">No active signals to evaluate.</div>`;
    } else {
      elAnomalySignalsGrid.innerHTML = signals.map(sig => {
        const sigSev = (sig.severity || "NORMAL").toUpperCase();
        const cardClass = sigSev === "ANOMALOUS" ? "sig-anomalous" : (sigSev === "ELEVATED" ? "sig-elevated" : "");
        const sevClass = sigSev === "ANOMALOUS" ? "status-red-text" : (sigSev === "ELEVATED" ? "status-amber-text" : "status-green-text");

        const metricName = sig.metric.replace(/_/g, " ").toUpperCase();
        const curr = sig.current_value !== null && sig.current_value !== undefined ? Number(sig.current_value).toFixed(1) : "--";
        const mean = sig.baseline_mean !== null && sig.baseline_mean !== undefined ? Number(sig.baseline_mean).toFixed(1) : "--";
        const z = sig.z_score !== null && sig.z_score !== undefined ? `z: ${Number(sig.z_score).toFixed(1)}` : "z: 0.0";
        const dir = sig.direction === "HIGHER_THAN_BASELINE" ? "▲ HIGH" : (sig.direction === "LOWER_THAN_BASELINE" ? "▼ LOW" : "● NORMAL");

        return `
          <div class="anomaly-signal-card ${cardClass}">
            <div class="signal-top-row">
              <span class="signal-name">${metricName}</span>
              <span class="signal-sev-pill ${sevClass}">${sigSev}</span>
            </div>
            <div class="signal-details-row">
              <span>Val: <strong>${curr}</strong> (μ: ${mean})</span>
              <span>${dir} (${z})</span>
            </div>
          </div>
        `;
      }).join("");
    }

    // Pattern Notes
    const notes = data.pattern_notes || [];
    if (notes.length > 0) {
      elAnomalyPatternContainer.style.display = "flex";
      elAnomalyPatternChips.innerHTML = notes.map(n => `<span class="pattern-chip">${n}</span>`).join("");
    } else {
      elAnomalyPatternContainer.style.display = "none";
    }
  }

  async function fetchAnomalyAssessment() {
    try {
      const res = await fetch(`/api/proxy/intelligence/anomalies?window=${selectedTrendWindow}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderAnomalyAssessment(data);
    } catch (err) {
      console.warn("Anomaly assessment fetch error:", err);
    }
  }

  // ============================================================================
  // M3-11C: EXTENDED DECISION HISTORY & AUDIT TRAIL
  // ============================================================================

  window.filterHistoryAction = function (action) {
    selectedHistoryAction = action;
    fetchDecisionHistory();
  };

  window.refreshHistory = function () {
    fetchDecisionHistory();
    fetchHistoryStats();
  };

  async function fetchHistoryStats() {
    try {
      const res = await fetch("/api/proxy/history/stats");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const total = data.total_observations ?? 0;
      elHistoryTotalBadge.textContent = `${total} OBSERVATIONS`;
      const sRate = data.success_rate !== undefined ? `${Math.round(data.success_rate * 100)}%` : "100%";
      elHistSuccessRate.textContent = sRate;
      elHistRetention.textContent = `${data.retention_days || 7} Days`;
    } catch (err) {
      console.warn("History stats fetch error:", err);
    }
  }

  function renderHistoryTable(observations) {
    if (!observations || observations.length === 0) {
      elHistoryBody.innerHTML = `<tr><td colspan="9" class="loading-cell">No recorded observations found for filter.</td></tr>`;
      return;
    }

    elHistoryBody.innerHTML = observations.map(obs => {
      const timeStr = obs.timestamp ? obs.timestamp.split("T")[1]?.slice(0, 8) || obs.timestamp : "--";
      const action = obs.action || (obs.success ? "HOLD" : "ERROR");
      const actionClass = action === "SCALE" ? "status-cyan" : (action === "HOLD" ? "status-green" : "status-red-text");
      const ssPods = obs.recommended_pods ?? "--";
      const hpaPods = obs.baseline_hpa_recommended_pods ?? "--";

      let deltaStr = "--";
      let deltaClass = "status-green-text";
      if (obs.pod_delta_vs_baseline !== null && obs.pod_delta_vs_baseline !== undefined) {
        const delta = obs.pod_delta_vs_baseline;
        deltaStr = delta > 0 ? `+${delta}` : `${delta}`;
        if (delta < 0) deltaClass = "status-green-text";
        else if (delta > 0) deltaClass = "status-cyan-text";
        else deltaClass = "status-muted-text";
      }

      const demandStr = obs.predicted_legitimate_rps !== undefined && obs.predicted_legitimate_rps !== null
        ? `${Number(obs.predicted_legitimate_rps).toFixed(1)} RPS`
        : "--";
      const riskStr = obs.traffic_risk !== undefined && obs.traffic_risk !== null
        ? Number(obs.traffic_risk).toFixed(2)
        : "--";

      const statusTag = obs.success !== false
        ? `<span class="badge badge-outline" style="color: var(--emerald-green); border-color: rgba(16,185,129,0.4);">SUCCESS</span>`
        : `<span class="badge badge-outline" style="color: var(--rose-danger); border-color: rgba(244,63,94,0.4);">FAILED</span>`;

      const traceShort = obs.trace_id ? obs.trace_id.slice(0, 10) + "..." : "--";
      const traceLink = obs.trace_id
        ? `<a href="http://localhost:3000/explore?left=%7B%22datasource%22:%22tempo%22,%22queries%22:%5B%7B%22query%22:%22${obs.trace_id}%22%7D%5D%7D" target="_blank" class="trace-link" title="${obs.trace_id}">${traceShort}</a>`
        : "--";

      return `
        <tr>
          <td>${timeStr}</td>
          <td><span class="safety-val ${actionClass}">${action}</span></td>
          <td><strong>${ssPods}</strong></td>
          <td>${hpaPods}</td>
          <td><span class="${deltaClass}">${deltaStr}</span></td>
          <td>${demandStr}</td>
          <td>${riskStr}</td>
          <td>${statusTag}</td>
          <td>${traceLink}</td>
        </tr>
      `;
    }).join("");
  }

  async function fetchDecisionHistory() {
    try {
      let url = "/api/proxy/history?limit=10";
      if (selectedHistoryAction) {
        url += `&action=${encodeURIComponent(selectedHistoryAction)}`;
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const observations = await res.json();
      renderHistoryTable(observations);

      if (observations.length > 0 && !isEvaluating && !lastEvaluationTime) {
        const latest = observations[0];
        if (latest.scaling_decision_json) {
          try {
            const dec = JSON.parse(latest.scaling_decision_json);
            populateDecisionHero(dec);
          } catch (_) {
            populateDecisionFromObservation(latest);
          }
        } else {
          populateDecisionFromObservation(latest);
        }
      }
    } catch (err) {
      console.warn("History fetch error:", err);
    }
  }

  function updateDeltaStyling(delta, hpaPods, ssPods) {
    if (delta === undefined || delta === null || isNaN(delta)) {
      elDeltaPill.textContent = "DELTA: -- PODS";
      elDeltaPill.className = "delta-pill delta-neutral";
      elDeltaNarrative.textContent = "Waiting for operator evaluation...";
      return;
    }

    const deltaSign = delta > 0 ? `+${delta}` : `${delta}`;
    elDeltaPill.textContent = `DELTA: ${deltaSign} PODS`;

    if (delta < 0) {
      elDeltaPill.className = "delta-pill delta-suppressed";
      const savedPods = Math.abs(delta);
      elDeltaNarrative.textContent = `Suppressed +${savedPods} unnecessary pod${savedPods > 1 ? "s" : ""} vs reactive baseline by filtering attack traffic.`;
    } else if (delta > 0) {
      elDeltaPill.className = "delta-pill delta-proactive";
      elDeltaNarrative.textContent = `Proactively provisioning +${delta} additional pod${delta > 1 ? "s" : ""} to handle expected legitimate demand surge.`;
    } else {
      elDeltaPill.className = "delta-pill delta-neutral";
      elDeltaNarrative.textContent = `Full agreement: both SentinelScale and HPA recommend ${ssPods} pods.`;
    }
  }

  function renderContributingSignals(signals, riskScore) {
    if (!signals || signals.length === 0) {
      if (riskScore !== undefined && riskScore > 0.6) {
        elContributingSignals.innerHTML = `<span class="signal-tag signal-tag-active">Elevated Traffic Risk (${(riskScore || 0).toFixed(2)})</span>`;
      } else {
        elContributingSignals.innerHTML = `<span class="signal-tag signal-tag-normal">Normal Traffic Profile</span>`;
      }
      return;
    }

    elContributingSignals.innerHTML = signals.map(sig => {
      const isSuspicious = sig.includes("attack") || sig.includes("spike") || sig.includes("rapid") || sig.includes("fanout") || sig.includes("bot") || sig.includes("anomaly") || sig.includes("high");
      const tagClass = isSuspicious ? "signal-tag-active" : "signal-tag-normal";
      return `<span class="signal-tag ${tagClass}">${sig.replace(/_/g, " ")}</span>`;
    }).join("");
  }

  function updateCausalPipeline(data) {
    if (!data) return;

    // 1. Raw Workload
    const rawRps = data.total_rps ?? data.observed_rps ?? lastObservedRps;
    const rawCpu = data.cpu_utilization !== undefined ? Math.round(data.cpu_utilization * 100) : lastObservedCpu;
    elCausalRawRps.textContent = `${Number(rawRps).toFixed(1)} RPS`;
    elCausalRawCpu.textContent = `CPU: ${rawCpu}%`;

    // 2. Traffic Risk & Filtering
    const risk = data.traffic_risk ?? data.risk_score ?? 0;
    elCausalRiskScore.textContent = `Risk: ${risk.toFixed(2)}`;
    const filteredRps = data.suspicious_rps_estimate !== undefined 
      ? `${Number(data.suspicious_rps_estimate).toFixed(1)} RPS`
      : (risk > 0.5 ? "Surge Filtered" : "0.0 RPS");
    elCausalFilteredRps.textContent = `Filtered: ${filteredRps}`;

    // 3. Legitimate Demand
    const legitRps = data.predicted_legitimate_rps ?? data.legitimate_rps_estimate ?? 0;
    elCausalLegitRps.textContent = `${Number(legitRps).toFixed(1)} RPS`;
    const demandConf = Math.round((data.demand_confidence ?? data.confidence ?? 0.95) * 100);
    elCausalDemandConf.textContent = `Conf: ${demandConf}%`;

    // 4. Cluster Capacity vs Demand
    const capRps = data.current_capacity_rps ?? 150.0;
    elCausalCapacityRps.textContent = `${Number(capRps).toFixed(1)} RPS`;
    const headroom = Number(capRps) - Number(legitRps);
    const headroomSign = headroom >= 0 ? `+${headroom.toFixed(0)} RPS` : `${headroom.toFixed(0)} RPS`;
    elCausalHeadroom.textContent = `Headroom: ${headroomSign}`;

    // 5. Policy Guardrails
    elCausalPolicyName.textContent = data.policy || "default_policy";

    // 6. Final Action
    const action = data.action || "HOLD";
    const recommendedPods = data.recommended_pods ?? "--";
    elCausalFinalAction.textContent = action;
    elCausalFinalPods.textContent = `${recommendedPods} Pods`;
  }

  function populateDecisionFromObservation(obs) {
    if (!obs) return;
    const hpaPods = obs.baseline_hpa_recommended_pods ?? "--";
    const ssPods = obs.recommended_pods ?? "--";
    const delta = obs.pod_delta_vs_baseline;

    elHpaPods.textContent = hpaPods;
    elSsPods.textContent = ssPods;
    updateDeltaStyling(delta, hpaPods, ssPods);

    elActionTag.textContent = `ACTION: ${obs.action || "HOLD"}`;
    elReason.textContent = obs.reason || "Decision successfully evaluated under baseline conditions.";
    elDecisionId.textContent = obs.id ? obs.id.slice(0, 18) + "..." : "--";
    elTraceId.textContent = obs.trace_id || "--";
    elConfidence.textContent = obs.confidence ? `${Math.round(obs.confidence * 100)}%` : "95%";
    elTimestamp.textContent = obs.completed_at || obs.timestamp || "--";

    if (obs.traffic_risk !== null && obs.traffic_risk !== undefined) {
      elTrafficRiskVal.textContent = obs.traffic_risk.toFixed(2);
      elTrafficRiskFill.style.width = `${Math.round(obs.traffic_risk * 100)}%`;
    }
    if (obs.predicted_legitimate_rps !== null && obs.predicted_legitimate_rps !== undefined) {
      elDemandPred.textContent = `${obs.predicted_legitimate_rps.toFixed(1)} RPS`;
    }

    updateCausalPipeline({
      action: obs.action,
      recommended_pods: obs.recommended_pods,
      predicted_legitimate_rps: obs.predicted_legitimate_rps,
      traffic_risk: obs.traffic_risk,
      policy: "default_safety_policy"
    });

    renderContributingSignals([], obs.traffic_risk);
  }

  function populateDecisionHero(dec) {
    if (!dec) return;
    const hpaPods = dec.baseline_hpa_recommended_pods ?? "--";
    const ssPods = dec.recommended_pods ?? "--";
    const delta = dec.pod_delta_vs_baseline;

    elHpaPods.textContent = hpaPods;
    elSsPods.textContent = ssPods;
    updateDeltaStyling(delta, hpaPods, ssPods);

    elActionTag.textContent = `ACTION: ${dec.action || "HOLD"}`;
    if (dec.action === "HOLD") {
      elActionTag.style.borderColor = "var(--emerald-green)";
      elActionTag.style.color = "var(--emerald-green)";
      elActionTag.style.background = "rgba(16, 185, 129, 0.15)";
    } else if (dec.action === "SCALE") {
      elActionTag.style.borderColor = "var(--cyan-primary)";
      elActionTag.style.color = "var(--cyan-primary)";
      elActionTag.style.background = "rgba(6, 182, 212, 0.15)";
    } else {
      elActionTag.style.borderColor = "var(--amber-warning)";
      elActionTag.style.color = "var(--amber-warning)";
      elActionTag.style.background = "rgba(245, 158, 11, 0.15)";
    }

    elPolicyTag.textContent = `POLICY: ${dec.policy || "default_safety_policy"}`;
    elReason.textContent = dec.reason || "Decision evaluated against real traffic telemetry.";
    elDecisionId.textContent = dec.decision_id ? dec.decision_id.slice(0, 18) + "..." : "--";
    elTraceId.textContent = dec.trace_id || "--";
    elConfidence.textContent = dec.confidence ? `${Math.round(dec.confidence * 100)}%` : "--%";
    elTimestamp.textContent = dec.timestamp ? dec.timestamp.replace("T", " ").slice(0, 19) + " UTC" : "--";

    lastEvaluationTime = new Date();
    updateDecisionAge();

    latestTraceId = dec.trace_id;
    if (latestTraceId && elTempoShortcut) {
      elTempoShortcut.href = `http://localhost:3000/explore?left=%7B%22datasource%22:%22tempo%22,%22queries%22:%5B%7B%22query%22:%22${latestTraceId}%22%7D%5D%7D`;
    }

    updateCausalPipeline({
      action: dec.action,
      recommended_pods: dec.recommended_pods,
      predicted_legitimate_rps: dec.predicted_legitimate_rps,
      current_capacity_rps: dec.current_capacity_rps,
      traffic_risk: dec.traffic_risk,
      policy: dec.policy,
      confidence: dec.confidence
    });
  }

  function populateContextCards(ctx) {
    if (!ctx) return;

    // Traffic Assessment (M1)
    if (ctx.traffic_assessment) {
      const t = ctx.traffic_assessment;
      elTrafficClass.textContent = (t.classification || "UNKNOWN").toUpperCase();
      elTrafficClass.className = `status-pill status-${t.classification || "legitimate"}`;

      const risk = t.risk_score || 0;
      elTrafficRiskVal.textContent = risk.toFixed(2);
      elTrafficRiskFill.style.width = `${Math.round(risk * 100)}%`;

      elTrafficTotal.textContent = `${(t.total_rps || 0).toFixed(1)} RPS`;
      elTrafficLegit.textContent = `${(t.legitimate_rps_estimate || 0).toFixed(1)} RPS`;
      elTrafficSusp.textContent = `${(t.suspicious_rps_estimate || 0).toFixed(1)} RPS`;

      const signals = t.top_signals && t.top_signals.length ? t.top_signals : [];
      const signalsStr = signals.length ? signals.join(", ") : "Normal Profile";
      const conf = Math.round((t.confidence || 1.0) * 100);
      elTrafficSignals.textContent = `${signalsStr} (conf: ${conf}%)`;

      renderContributingSignals(signals, risk);
    }

    // Demand Forecast (M2)
    if (ctx.demand_forecast) {
      const d = ctx.demand_forecast;
      elDemandPred.textContent = `${(d.predicted_legitimate_rps || 0).toFixed(1)} RPS`;
      if (elDemandHorizon) {
        elDemandHorizon.textContent = `${d.forecast_horizon_seconds || 300}s (${Math.round((d.forecast_horizon_seconds || 300) / 60)}m)`;
      }
      elDemandBounds.textContent = `${(d.lower_bound_rps || 0).toFixed(1)} .. ${(d.upper_bound_rps || 0).toFixed(1)} RPS`;
      elDemandConf.textContent = `${Math.round((d.confidence || 0.95) * 100)}%`;
      elDemandTime.textContent = d.generated_at ? d.generated_at.split("T")[1]?.slice(0, 8) || d.generated_at : "--";
    }
  }

  // ==============================================================================
  // STAGE M3-11D: EMPIRICAL BENCHMARK EXPERIMENTS CONTROLLER
  // ==============================================================================

  async function fetchExperiments() {
    try {
      const res = await fetch("/api/proxy/experiments");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      loadedExperiments = await res.json();

      elExpTotalBadge.textContent = `${loadedExperiments.length} TRIALS LOADED`;

      if (loadedExperiments.length === 0) {
        elExpSelect.innerHTML = `<option value="">No experiment trials found</option>`;
        return;
      }

      // Populate dropdown
      const prevSelected = currentSelectedExperimentId || elExpSelect.value;
      elExpSelect.innerHTML = loadedExperiments.map(exp => {
        return `<option value="${exp.run_id}">${exp.scenario_name} (${exp.run_id})</option>`;
      }).join("");

      // Preserve selection or default to first
      const exists = loadedExperiments.some(e => e.run_id === prevSelected);
      const targetId = exists ? prevSelected : loadedExperiments[0].run_id;
      elExpSelect.value = targetId;
      currentSelectedExperimentId = targetId;

      await fetchExperimentDetail(targetId);
    } catch (err) {
      console.warn("Experiments list fetch error:", err);
      elExpTotalBadge.textContent = "FETCH ERROR";
    }
  }

  async function fetchExperimentDetail(runId) {
    if (!runId) return;
    try {
      const res = await fetch(`/api/proxy/experiments/${runId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const exp = await res.json();
      currentSelectedExperimentId = runId;
      renderExperiment(exp);
    } catch (err) {
      console.error(`Failed to fetch experiment detail for ${runId}:`, err);
    }
  }

  function renderExperiment(exp) {
    if (!exp) return;

    // Header & Meta Strip
    elExpScenarioName.textContent = exp.scenario_name;
    elExpScenarioId.textContent = `(${exp.scenario_id} / ${exp.run_id})`;
    elExpDurationPill.textContent = `${exp.duration_seconds.toFixed(1)}s`;

    // Divergence Classification Pill
    const divClass = exp.comparison_summary.divergence_classification;
    if (divClass === "agreement") {
      elExpDivergencePill.textContent = "AGREEMENT (BASELINE MATCH)";
      elExpDivergencePill.className = "status-pill status-legitimate";
    } else if (divClass === "sentinelscale_recommends_fewer") {
      elExpDivergencePill.textContent = "SUPPRESSED OVERPROVISIONING";
      elExpDivergencePill.className = "status-pill status-suspicious";
    } else if (divClass === "sentinelscale_recommends_more") {
      elExpDivergencePill.textContent = "PROACTIVE SCALE-UP";
      elExpDivergencePill.className = "status-pill status-cyan-pill";
    } else {
      elExpDivergencePill.textContent = "MIXED ADAPTATION";
      elExpDivergencePill.className = "status-pill";
    }

    // Guardrails Pill
    const guardrailsPassed = exp.performance_guardrails.guardrails_passed;
    elExpGuardrailsPill.textContent = `GUARDRAILS: ${guardrailsPassed ? "PASSED" : "VIOLATED"}`;
    elExpGuardrailsPill.className = `status-pill ${guardrailsPassed ? "status-legitimate" : "status-attack"}`;

    // Grafana Deep-Link with exact trial timeframe
    if (exp.start_time && exp.end_time) {
      const fromMs = new Date(exp.start_time).getTime();
      const toMs = new Date(exp.end_time).getTime();
      elExpGrafanaLink.href = `http://localhost:3000/d/sentinelscale-unified-obs?from=${fromMs}&to=${toMs}`;
    }

    // 1. HPA KPI Card
    elExpHpaPeakInit.textContent = `${exp.hpa_summary.peak_replicas} / ${exp.hpa_summary.initial_replicas}`;
    elExpHpaReplicaHours.textContent = exp.hpa_summary.replica_hours.toFixed(4);
    elExpHpaPodSeconds.textContent = `${exp.hpa_summary.pod_seconds.toFixed(1)} s`;
    const upEvents = exp.hpa_summary.scale_up_events_count ?? 0;
    const downEvents = exp.hpa_summary.scale_down_events_count ?? 0;
    elExpHpaScaleEvents.textContent = `${upEvents} up / ${downEvents} down`;

    // 2. SentinelScale KPI Card
    elExpSsPeakInit.textContent = `${exp.sentinelscale_summary.peak_recommended_pods} / ${exp.sentinelscale_summary.initial_recommended_pods}`;
    elExpSsReplicaHours.textContent = exp.sentinelscale_summary.replica_hours.toFixed(4);
    elExpSsPodSeconds.textContent = `${exp.sentinelscale_summary.pod_seconds.toFixed(1)} s`;
    elExpSsDecisionsCount.textContent = `${exp.sentinelscale_summary.decisions_count} cycles`;

    // 3. Comparison Delta KPI Card
    const podDelta = exp.comparison_summary.pod_seconds_delta;
    const repDelta = exp.comparison_summary.replica_hours_delta;
    elExpDeltaPodSeconds.textContent = `${podDelta >= 0 ? "+" : ""}${podDelta.toFixed(1)} s`;
    elExpDeltaReplicaHours.textContent = `${repDelta >= 0 ? "+" : ""}${repDelta.toFixed(4)}`;
    elExpDeltaMaxDiff.textContent = `${exp.comparison_summary.max_replica_difference} pods`;
    elExpDeltaClassification.textContent = exp.comparison_summary.divergence_classification;

    if (podDelta < 0) {
      elExpDeltaBadge.className = "exp-kpi-badge badge-delta";
      elExpDeltaBadge.textContent = "SAVINGS";
    } else if (podDelta > 0) {
      elExpDeltaBadge.className = "exp-kpi-badge badge-ss";
      elExpDeltaBadge.textContent = "PROACTIVE";
    } else {
      elExpDeltaBadge.className = "exp-kpi-badge";
      elExpDeltaBadge.textContent = "MATCH";
    }

    // 4. Workload & Performance Guardrails
    elExpWorkloadReqsRps.textContent = `${exp.workload_summary.total_requests.toLocaleString()} reqs / ${exp.workload_summary.average_rps.toFixed(1)} RPS`;
    elExpWorkloadPeakRps.textContent = `${exp.workload_summary.peak_rps.toFixed(1)} RPS`;
    elExpGuardrailP95.textContent = `${exp.workload_summary.p95_latency_ms.toFixed(2)} ms / ${exp.performance_guardrails.p95_latency_guardrail_ms.toFixed(0)} ms`;
    elExpGuardrailErrors.textContent = `${(exp.workload_summary.error_rate * 100).toFixed(2)}% / ${(exp.performance_guardrails.error_rate_guardrail * 100).toFixed(1)}%`;
    elExpKpiGuardrailBadge.textContent = guardrailsPassed ? "PASSED" : "VIOLATED";
    elExpKpiGuardrailBadge.className = `exp-kpi-badge ${guardrailsPassed ? "badge-guardrails" : "badge-hpa"}`;

    // Lifecycle Phases Chips
    if (exp.phases && exp.phases.length > 0) {
      elExpPhasesChips.innerHTML = exp.phases.map(p => {
        return `<span class="phase-chip">${p.phase_name} (+${p.elapsed_seconds.toFixed(1)}s)</span>`;
      }).join("");
    } else {
      elExpPhasesChips.innerHTML = `<span class="phase-chip">Continuous Trial</span>`;
    }

    // Action Distribution Chips
    const actions = exp.sentinelscale_summary.action_distribution || {};
    const actionKeys = Object.keys(actions);
    if (actionKeys.length > 0) {
      elExpActionsChips.innerHTML = actionKeys.map(k => {
        return `<span class="action-chip">${k}: ${actions[k]}</span>`;
      }).join("");
    } else {
      elExpActionsChips.innerHTML = `<span class="action-chip">No actions recorded</span>`;
    }

    // Render High-Resolution SVG Timeline
    renderExperimentChart(exp);
  }

  function renderExperimentChart(exp) {
    const points = exp.timeseries || [];
    if (points.length === 0) {
      elExpChartSvg.innerHTML = `
        <text x="400" y="110" fill="#64748b" font-family="monospace" font-size="13" text-anchor="middle">
          No high-resolution timeseries points recorded for this trial.
        </text>
      `;
      return;
    }

    const svgWidth = 800;
    const svgHeight = 220;
    const pad = { top: 25, right: 35, bottom: 35, left: 45 };
    const plotW = svgWidth - pad.left - pad.right;
    const plotH = svgHeight - pad.top - pad.bottom;

    // Determine domain
    const maxElapsed = Math.max(
      exp.duration_seconds || 1,
      ...points.map(p => p.elapsed_seconds || 0)
    );

    let maxReplicas = Math.max(
      4,
      ...points.map(p => Math.max(p.hpa_replicas || 2, p.sentinelscale_recommended_pods || 2))
    );
    maxReplicas = Math.ceil(maxReplicas + 1);

    const getX = (sec) => pad.left + (sec / maxElapsed) * plotW;
    const getY = (val) => pad.top + plotH - (val / maxReplicas) * plotH;

    let svgHtml = "";

    // 1. Grid lines and Y-axis labels
    const yTicks = Math.min(maxReplicas, 6);
    for (let i = 0; i <= yTicks; i++) {
      const val = Math.round((i / yTicks) * maxReplicas);
      const y = getY(val);
      svgHtml += `
        <line x1="${pad.left}" y1="${y}" x2="${svgWidth - pad.right}" y2="${y}" stroke="#162238" stroke-width="1" />
        <text x="${pad.left - 8}" y="${y + 4}" fill="#64748b" font-family="monospace" font-size="10" text-anchor="end">${val}</text>
      `;
    }

    // 2. X-axis ticks
    const xTicksCount = 5;
    for (let i = 0; i <= xTicksCount; i++) {
      const sec = (i / xTicksCount) * maxElapsed;
      const x = getX(sec);
      svgHtml += `
        <line x1="${x}" y1="${pad.top}" x2="${x}" y2="${pad.top + plotH}" stroke="#162238" stroke-width="1" />
        <text x="${x}" y="${svgHeight - 12}" fill="#64748b" font-family="monospace" font-size="10" text-anchor="middle">${sec.toFixed(0)}s</text>
      `;
    }

    // 3. Phase boundary vertical lines and labels
    if (exp.phases && exp.phases.length > 0) {
      exp.phases.forEach((phase, idx) => {
        if (phase.elapsed_seconds > 0 && phase.elapsed_seconds < maxElapsed) {
          const px = getX(phase.elapsed_seconds);
          svgHtml += `
            <line x1="${px}" y1="${pad.top}" x2="${px}" y2="${pad.top + plotH}" stroke="#475569" stroke-width="1" stroke-dasharray="3,3" />
            <text x="${px + 4}" y="${pad.top + 10 + (idx % 2) * 12}" fill="#94a3b8" font-family="monospace" font-size="9" text-anchor="start">${phase.phase_name}</text>
          `;
        }
      });
    }

    // 4. Construct Step Paths
    // HPA Step Path
    let hpaPath = "";
    let ssPath = "";

    points.forEach((pt, i) => {
      const x = getX(pt.elapsed_seconds);
      const yHpa = getY(pt.hpa_replicas);
      const ySs = getY(pt.sentinelscale_recommended_pods);

      if (i === 0) {
        hpaPath = `M ${x} ${yHpa}`;
        ssPath = `M ${x} ${ySs}`;
      } else {
        const prevPt = points[i - 1];
        const prevX = getX(prevPt.elapsed_seconds);
        // Step interpolation: horizontal to current X, then vertical
        hpaPath += ` H ${x} V ${yHpa}`;
        ssPath += ` H ${x} V ${ySs}`;
      }
    });

    // Render HPA Path (Amber dashed)
    svgHtml += `
      <path d="${hpaPath}" fill="none" stroke="#f59e0b" stroke-width="2.5" stroke-dasharray="4,4" />
    `;

    // Render SentinelScale Path (Cyan solid)
    svgHtml += `
      <path d="${ssPath}" fill="none" stroke="#06b6d4" stroke-width="2.5" />
    `;

    // 5. Render interactive invisible hover trigger points
    points.forEach((pt, idx) => {
      const cx = getX(pt.elapsed_seconds);
      const cyHpa = getY(pt.hpa_replicas);
      const cySs = getY(pt.sentinelscale_recommended_pods);

      svgHtml += `
        <circle cx="${cx}" cy="${cyHpa}" r="4" fill="#f59e0b" opacity="0.8" />
        <circle cx="${cx}" cy="${cySs}" r="4" fill="#06b6d4" opacity="0.8" />
        <rect x="${cx - 8}" y="${pad.top}" width="16" height="${plotH}" fill="transparent" 
              data-idx="${idx}" class="exp-chart-hitbox" style="cursor: crosshair;" />
      `;
    });

    elExpChartSvg.innerHTML = svgHtml;

    // Bind hover tooltips
    const hitboxes = elExpChartSvg.querySelectorAll(".exp-chart-hitbox");
    hitboxes.forEach(box => {
      box.addEventListener("mousemove", (e) => {
        const idx = parseInt(box.getAttribute("data-idx"), 10);
        const pt = points[idx];
        if (!pt) return;

        const rect = elExpChartContainer.getBoundingClientRect();
        const posX = e.clientX - rect.left;
        const posY = e.clientY - rect.top;

        const delta = pt.replica_delta;
        const deltaStr = delta >= 0 ? `+${delta}` : `${delta}`;

        elExpChartTooltip.innerHTML = `
          <div style="font-weight: 700; color: #38bdf8; margin-bottom: 2px;">Elapsed: ${pt.elapsed_seconds.toFixed(1)}s</div>
          <div>HPA Replicas: <span style="color: #f59e0b; font-weight: 600;">${pt.hpa_replicas}</span></div>
          <div>SentinelScale: <span style="color: #06b6d4; font-weight: 600;">${pt.sentinelscale_recommended_pods}</span> (Δ ${deltaStr})</div>
          <div>Action: <strong>${pt.sentinelscale_action || "HOLD"}</strong></div>
          ${pt.hpa_cpu_percent !== undefined && pt.hpa_cpu_percent !== null ? `<div>Target CPU: ${pt.hpa_cpu_percent}%</div>` : ""}
        `;

        // Position tooltip inside container bounds
        const tooltipW = 180;
        const leftPos = Math.min(Math.max(10, posX + 15), rect.width - tooltipW - 10);
        const topPos = Math.max(10, Math.min(posY - 60, rect.height - 100));

        elExpChartTooltip.style.left = `${leftPos}px`;
        elExpChartTooltip.style.top = `${topPos}px`;
        elExpChartTooltip.style.display = "block";
      });

      box.addEventListener("mouseleave", () => {
        elExpChartTooltip.style.display = "none";
      });
    });
  }

  window.selectExperiment = function (runId) {
    if (!runId) return;
    fetchExperimentDetail(runId);
  };

  window.refreshExperiments = function () {
    fetchExperiments();
  };

  window.triggerEvaluation = async function () {
    if (isEvaluating) return;
    isEvaluating = true;

    btnEvaluate.disabled = true;
    btnEvaluate.innerHTML = `<span class="btn-icon">⏳</span><span class="btn-text">Evaluating State...</span>`;
    elEvalAlertBanner.style.display = "none";

    try {
      // 1. Fetch live aggregated context to populate M1/M2 cards
      const aggPromise = fetch("/api/proxy/decision/aggregate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ namespace: "default", workload: "demo-api" })
      }).then(r => r.ok ? r.json() : null).catch(() => null);

      // 2. Fetch live scaling decision orchestration
      const orchPromise = fetch("/api/proxy/decision/orchestrate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ namespace: "default", workload: "demo-api" })
      }).then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      });

      const [ctx, decision] = await Promise.all([aggPromise, orchPromise]);

      if (ctx) populateContextCards(ctx);
      if (decision) populateDecisionHero(decision);

      // Refresh all intelligence, resource & history feeds
      await Promise.all([
        fetchResourceState(),
        fetchDecisionHistory(),
        fetchHistoricalTrends(),
        fetchAnomalyAssessment(),
        fetchHistoryStats(),
        fetchExperiments()
      ]);
    } catch (err) {
      console.error("Evaluation error:", err);
      elEvalAlertMessage.textContent = `Evaluation failed: ${err.message}. Ensure Platform (:8003) and Prometheus are reachable.`;
      elEvalAlertBanner.style.display = "flex";
      elReason.textContent = `Evaluation failed: ${err.message}. Ensure upstream microservices and Prometheus are running.`;
    } finally {
      isEvaluating = false;
      btnEvaluate.disabled = false;
      btnEvaluate.innerHTML = `<span class="btn-icon">⚡</span><span class="btn-text">Evaluate Current State</span>`;
    }
  };

  // Initial Load
  fetchSafetyState();
  fetchResourceState();
  fetchDecisionHistory();
  fetchHistoricalTrends();
  fetchAnomalyAssessment();
  fetchHistoryStats();
  fetchExperiments();

  // Periodic Polling
  setInterval(() => {
    fetchResourceState();
    fetchDecisionHistory();
    fetchHistoricalTrends();
    fetchAnomalyAssessment();
    fetchHistoryStats();
  }, POLLING_INTERVAL_MS);

  // Clock & Age Tracker tick every second
  setInterval(updateClock, 1000);

})();

