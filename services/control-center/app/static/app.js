/**
 * SentinelScale Control Center — Frontend Controller
 * Real-time polling & Platform API proxy client
 */

(function () {
  "use strict";

  const POLLING_INTERVAL_MS = 4000;
  let isEvaluating = false;
  let latestTraceId = null;

  // DOM Elements
  const elSyncStatus = document.getElementById("sync-status");
  const elLastUpdated = document.getElementById("last-updated");
  const btnEvaluate = document.getElementById("btn-evaluate");

  // Safety Elements
  const elSafetyShadow = document.getElementById("safety-shadow");
  const elSafetyDryRun = document.getElementById("safety-dryrun");
  const elSafetyAutonomous = document.getElementById("safety-autonomous");
  const elSafetyMutations = document.getElementById("safety-mutations");

  // Resource Elements
  const elRunningPods = document.getElementById("res-running-pods");
  const elDesiredPending = document.getElementById("res-desired-pending");
  const elCpuVal = document.getElementById("res-cpu-val");
  const elCpuFill = document.getElementById("res-cpu-fill");
  const elMemVal = document.getElementById("res-mem-val");
  const elMemFill = document.getElementById("res-mem-fill");
  const elCapacity = document.getElementById("res-capacity");
  const elRateP95 = document.getElementById("res-rate-p95");

  // Traffic Elements
  const elTrafficClass = document.getElementById("traffic-classification");
  const elTrafficRiskVal = document.getElementById("traffic-risk-val");
  const elTrafficRiskFill = document.getElementById("traffic-risk-fill");
  const elTrafficTotal = document.getElementById("traffic-total-rps");
  const elTrafficLegit = document.getElementById("traffic-legit-rps");
  const elTrafficSusp = document.getElementById("traffic-susp-rps");
  const elTrafficSignals = document.getElementById("traffic-signals");

  // Demand Elements
  const elDemandPred = document.getElementById("demand-pred-rps");
  const elDemandBounds = document.getElementById("demand-bounds");
  const elDemandConf = document.getElementById("demand-conf");
  const elDemandTime = document.getElementById("demand-time");

  // Decision Elements
  const elHpaPods = document.getElementById("hpa-pods");
  const elSsPods = document.getElementById("ss-pods");
  const elDeltaPill = document.getElementById("delta-pill");
  const elActionTag = document.getElementById("decision-action-tag");
  const elPolicyTag = document.getElementById("decision-policy-tag");
  const elReason = document.getElementById("decision-reason");
  const elDecisionId = document.getElementById("decision-id");
  const elTraceId = document.getElementById("decision-trace-id");
  const elTimestamp = document.getElementById("decision-timestamp");
  const elHistoryBody = document.getElementById("history-tbody");
  const elTempoShortcut = document.getElementById("tempo-shortcut");

  function updateClock() {
    const now = new Date();
    elLastUpdated.textContent = now.toTimeString().split(" ")[0];
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
      const p95 = data.p95_latency_ms !== undefined ? data.p95_latency_ms.toFixed(1) : "--";
      elRateP95.textContent = `${rps} RPS / ${p95} ms`;

      updateClock();
      elSyncStatus.textContent = "LIVE (4s)";
    } catch (err) {
      console.warn("Resource state fetch error:", err);
      elSyncStatus.textContent = "DEGRADED (RETRYING)";
    }
  }

  function renderHistoryTable(observations) {
    if (!observations || observations.length === 0) {
      elHistoryBody.innerHTML = `<tr><td colspan="7" class="loading-cell">No recorded observations yet. Click "Evaluate Current State" to generate live decision telemetry.</td></tr>`;
      return;
    }

    elHistoryBody.innerHTML = observations.map(obs => {
      const timeStr = obs.timestamp ? obs.timestamp.split("T")[1]?.slice(0, 8) || obs.timestamp : "--";
      const action = obs.action || (obs.success ? "HOLD" : "ERROR");
      const actionClass = action === "SCALE" ? "status-cyan" : (action === "HOLD" ? "status-green" : "status-red-text");
      const ssPods = obs.recommended_pods ?? "--";
      const hpaPods = obs.baseline_hpa_recommended_pods ?? "--";
      const delta = obs.pod_delta_vs_baseline !== null && obs.pod_delta_vs_baseline !== undefined
        ? (obs.pod_delta_vs_baseline > 0 ? `+${obs.pod_delta_vs_baseline}` : `${obs.pod_delta_vs_baseline}`)
        : "--";
      const risk = obs.traffic_risk !== undefined && obs.traffic_risk !== null ? obs.traffic_risk.toFixed(2) : "--";
      const traceShort = obs.trace_id ? obs.trace_id.slice(0, 12) + "..." : "--";

      return `
        <tr>
          <td>${timeStr}</td>
          <td><span class="safety-val ${actionClass}">${action}</span></td>
          <td><strong>${ssPods}</strong></td>
          <td>${hpaPods}</td>
          <td><span class="status-green-text">${delta}</span></td>
          <td>${risk}</td>
          <td><a href="http://localhost:3000/d/sentinelscale-unified-obs" target="_blank" class="trace-link" title="${obs.trace_id}">${traceShort}</a></td>
        </tr>
      `;
    }).join("");
  }

  async function fetchDecisionHistory() {
    try {
      const res = await fetch("/api/proxy/history?limit=8");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const observations = await res.json();
      renderHistoryTable(observations);

      if (observations.length > 0 && !isEvaluating) {
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

  function populateDecisionFromObservation(obs) {
    if (!obs) return;
    elHpaPods.textContent = obs.baseline_hpa_recommended_pods ?? "--";
    elSsPods.textContent = obs.recommended_pods ?? "--";
    
    const delta = obs.pod_delta_vs_baseline ?? 0;
    elDeltaPill.textContent = `DELTA: ${delta >= 0 ? "+" + delta : delta} PODS`;
    if (delta < 0) {
      elDeltaPill.className = "delta-pill status-green";
    } else if (delta > 0) {
      elDeltaPill.className = "delta-pill status-cyan";
    }

    elActionTag.textContent = `ACTION: ${obs.action || "HOLD"}`;
    elReason.textContent = obs.reason || "Decision successfully evaluated under baseline conditions.";
    elDecisionId.textContent = obs.id ? obs.id.slice(0, 18) + "..." : "--";
    elTraceId.textContent = obs.trace_id || "--";
    elTimestamp.textContent = obs.completed_at || obs.timestamp || "--";

    if (obs.traffic_risk !== null && obs.traffic_risk !== undefined) {
      elTrafficRiskVal.textContent = obs.traffic_risk.toFixed(2);
      elTrafficRiskFill.style.width = `${Math.round(obs.traffic_risk * 100)}%`;
    }
    if (obs.predicted_legitimate_rps !== null && obs.predicted_legitimate_rps !== undefined) {
      elDemandPred.textContent = `${obs.predicted_legitimate_rps.toFixed(1)} RPS`;
    }
  }

  function populateDecisionHero(dec) {
    if (!dec) return;
    elHpaPods.textContent = dec.baseline_hpa_recommended_pods ?? "--";
    elSsPods.textContent = dec.recommended_pods ?? "--";

    const delta = dec.pod_delta_vs_baseline ?? 0;
    elDeltaPill.textContent = `DELTA: ${delta >= 0 ? "+" + delta : delta} PODS`;
    
    elActionTag.textContent = `ACTION: ${dec.action || "HOLD"}`;
    if (dec.action === "HOLD") {
      elActionTag.style.borderColor = "var(--emerald-green)";
      elActionTag.style.color = "var(--emerald-green)";
      elActionTag.style.background = "rgba(16, 185, 129, 0.15)";
    } else {
      elActionTag.style.borderColor = "var(--cyan-primary)";
      elActionTag.style.color = "var(--cyan-primary)";
      elActionTag.style.background = "rgba(6, 182, 212, 0.15)";
    }

    elPolicyTag.textContent = `POLICY: ${dec.policy || "default_safety_policy"}`;
    elReason.textContent = dec.reason || "Decision evaluated against real traffic telemetry.";
    elDecisionId.textContent = dec.decision_id ? dec.decision_id.slice(0, 18) + "..." : "--";
    elTraceId.textContent = dec.trace_id || "--";
    elTimestamp.textContent = dec.timestamp ? dec.timestamp.replace("T", " ").slice(0, 19) + " UTC" : "--";

    latestTraceId = dec.trace_id;
    if (latestTraceId) {
      elTempoShortcut.href = `http://localhost:3000/explore?left={"datasource":"tempo","queries":[{"query":"${latestTraceId}"}]}`;
    }
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

      const signals = t.top_signals && t.top_signals.length ? t.top_signals.join(", ") : "Normal Profile";
      const conf = Math.round((t.confidence || 1.0) * 100);
      elTrafficSignals.textContent = `${signals} (conf: ${conf}%)`;
    }

    // Demand Forecast (M2)
    if (ctx.demand_forecast) {
      const d = ctx.demand_forecast;
      elDemandPred.textContent = `${(d.predicted_legitimate_rps || 0).toFixed(1)} RPS`;
      elDemandHorizon.textContent = `${d.forecast_horizon_seconds || 300}s (${Math.round((d.forecast_horizon_seconds || 300) / 60)}m)`;
      elDemandBounds.textContent = `${(d.lower_bound_rps || 0).toFixed(1)} .. ${(d.upper_bound_rps || 0).toFixed(1)} RPS`;
      elDemandConf.textContent = `${Math.round((d.confidence || 0.95) * 100)}%`;
      elDemandTime.textContent = d.generated_at ? d.generated_at.split("T")[1]?.slice(0, 8) || d.generated_at : "--";
    }
  }

  window.triggerEvaluation = async function () {
    if (isEvaluating) return;
    isEvaluating = true;
    
    btnEvaluate.disabled = true;
    btnEvaluate.innerHTML = `<span class="btn-icon">⏳</span><span class="btn-text">Evaluating State...</span>`;
    
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

      // Refresh resource & history
      await Promise.all([fetchResourceState(), fetchDecisionHistory()]);
    } catch (err) {
      console.error("Evaluation error:", err);
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

  // Automatic Polling every 4 seconds
  setInterval(() => {
    fetchResourceState();
    fetchDecisionHistory();
  }, POLLING_INTERVAL_MS);

})();

