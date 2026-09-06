/**
 * SentinelScale Control Center — Frontend Controller
 * Real-time polling, Platform API proxy client, and Decision Explainability Engine
 */

(function () {
  "use strict";

  const POLLING_INTERVAL_MS = 4000;
  let isEvaluating = false;
  let latestTraceId = null;
  let lastEvaluationTime = null;
  let lastObservedCpu = 0;
  let lastObservedRps = 0;

  // DOM Elements - Header & Global
  const elSyncStatus = document.getElementById("sync-status");
  const elLastUpdated = document.getElementById("last-updated");
  const btnEvaluate = document.getElementById("btn-evaluate");
  const elEvalAlertBanner = document.getElementById("eval-alert-banner");
  const elEvalAlertMessage = document.getElementById("eval-alert-message");

  // Safety Elements
  const elSafetyShadow = document.getElementById("safety-shadow");
  const elSafetyDryRun = document.getElementById("safety-dryrun");
  const elSafetyAutonomous = document.getElementById("safety-autonomous");
  const elSafetyMutations = document.getElementById("safety-mutations");

  // Resource Elements (Card 1)
  const elRunningPods = document.getElementById("res-running-pods");
  const elDesiredPending = document.getElementById("res-desired-pending");
  const elCpuVal = document.getElementById("res-cpu-val");
  const elCpuFill = document.getElementById("res-cpu-fill");
  const elMemVal = document.getElementById("res-mem-val");
  const elMemFill = document.getElementById("res-mem-fill");
  const elCapacity = document.getElementById("res-capacity");
  const elRateP95 = document.getElementById("res-rate-p95");

  // Traffic Elements (Card 2)
  const elTrafficClass = document.getElementById("traffic-classification");
  const elTrafficRiskVal = document.getElementById("traffic-risk-val");
  const elTrafficRiskFill = document.getElementById("traffic-risk-fill");
  const elTrafficTotal = document.getElementById("traffic-total-rps");
  const elTrafficLegit = document.getElementById("traffic-legit-rps");
  const elTrafficSusp = document.getElementById("traffic-susp-rps");
  const elTrafficSignals = document.getElementById("traffic-signals");

  // Demand Elements (Card 3)
  const elDemandPred = document.getElementById("demand-pred-rps");
  const elDemandBounds = document.getElementById("demand-bounds");
  const elDemandConf = document.getElementById("demand-conf");
  const elDemandTime = document.getElementById("demand-time");
  const elDemandHorizon = document.getElementById("demand-horizon");

  // Decision Hero Elements
  const elHpaPods = document.getElementById("hpa-pods");
  const elSsPods = document.getElementById("ss-pods");
  const elDeltaPill = document.getElementById("delta-pill");
  const elDeltaNarrative = document.getElementById("delta-narrative");
  const elActionTag = document.getElementById("decision-action-tag");
  const elPolicyTag = document.getElementById("decision-policy-tag");
  const elReason = document.getElementById("decision-reason");
  const elContributingSignals = document.getElementById("contributing-signals");
  const elDecisionId = document.getElementById("decision-id");
  const elTraceId = document.getElementById("decision-trace-id");
  const elConfidence = document.getElementById("decision-confidence");
  const elTimestamp = document.getElementById("decision-timestamp");
  const elDecisionAge = document.getElementById("decision-age");
  const elHistoryBody = document.getElementById("history-tbody");
  const elTempoShortcut = document.getElementById("tempo-shortcut");

  // Causal Pipeline Elements
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
      elTempoShortcut.href = `http://localhost:3000/explore?left={"datasource":"tempo","queries":[{"query":"${latestTraceId}"}]}`;
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

      // Refresh resource & history
      await Promise.all([fetchResourceState(), fetchDecisionHistory()]);
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

  // Periodic Polling
  setInterval(() => {
    fetchResourceState();
    fetchDecisionHistory();
  }, POLLING_INTERVAL_MS);

  // Clock & Age Tracker tick every second
  setInterval(updateClock, 1000);

})();


