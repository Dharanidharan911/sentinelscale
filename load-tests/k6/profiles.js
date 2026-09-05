/**
 * SentinelScale k6 Workload Profiles Definition
 *
 * Defines stage configurations, target VUs, and test thresholds for different traffic patterns:
 * 1. smoke: Rapid validation (10s @ 2 VUs)
 * 2. baseline / normal: Normal steady-state diurnal traffic (warmup -> steady -> cooldown)
 * 3. sustained / sustained_high: Heavy sustained peak utilization
 * 4. spike: Sudden flash crowd / surge event
 * 5. recovery: Step-down after high load to test scale-down stabilization
 * 6. burst: Rapid pulsing traffic bursts
 */

export function getProfileConfig(profileName = 'baseline') {
  const vuScale = parseFloat(__ENV.VU_SCALE || '1.0');
  const durScale = parseFloat(__ENV.DURATION_SCALE || '1.0');

  const scaleVu = (vu) => Math.max(1, Math.round(vu * vuScale));
  const scaleDur = (sec) => `${Math.max(2, Math.round(sec * durScale))}s`;

  const profiles = {
    // 1. Smoke test: Quick 10s health & readiness validation
    smoke: {
      stages: [
        { duration: scaleDur(10), target: scaleVu(2) },
      ],
      thresholds: {
        http_req_failed: ['rate<0.01'],
        http_req_duration: ['p(95)<500'],
        checks: ['rate>0.99'],
      },
    },

    // 2. Baseline / Normal profile: Steady-state normal demand
    baseline: {
      stages: [
        { duration: scaleDur(10), target: scaleVu(5) },   // Phase 1: Warm-up
        { duration: scaleDur(30), target: scaleVu(8) },   // Phase 2: Steady baseline
        { duration: scaleDur(10), target: scaleVu(0) },   // Phase 3: Cooldown
      ],
      thresholds: {
        http_req_failed: ['rate<0.05'],
        http_req_duration: ['p(95)<1000'],
        checks: ['rate>0.95'],
      },
    },
    normal: {
      stages: [
        { duration: scaleDur(10), target: scaleVu(5) },   // Phase 1: Warm-up
        { duration: scaleDur(30), target: scaleVu(8) },   // Phase 2: Steady baseline
        { duration: scaleDur(10), target: scaleVu(0) },   // Phase 3: Cooldown
      ],
      thresholds: {
        http_req_failed: ['rate<0.05'],
        http_req_duration: ['p(95)<1000'],
        checks: ['rate>0.95'],
      },
    },

    // 3. Spike profile: Sudden legitimate flash crowd / surge event
    spike: {
      stages: [
        { duration: scaleDur(10), target: scaleVu(5) },   // Warm-up
        { duration: scaleDur(10), target: scaleVu(10) },  // Steady baseline
        { duration: scaleDur(10), target: scaleVu(35) },  // Rapid surge spike
        { duration: scaleDur(20), target: scaleVu(35) },  // Sustained peak surge
        { duration: scaleDur(10), target: scaleVu(5) },   // Cooldown
        { duration: scaleDur(10), target: scaleVu(0) },   // Tear-down
      ],
      thresholds: {
        http_req_failed: ['rate<0.10'],
        http_req_duration: ['p(95)<2000'],
        checks: ['rate>0.90'],
      },
    },

    // 4. Sustained / Sustained High profile: Heavy load sustained over extended period
    sustained: {
      stages: [
        { duration: scaleDur(15), target: scaleVu(25) },  // Ramp up
        { duration: scaleDur(45), target: scaleVu(30) },  // Sustained plateau
        { duration: scaleDur(15), target: scaleVu(0) },   // Ramp down
      ],
      thresholds: {
        http_req_failed: ['rate<0.05'],
        http_req_duration: ['p(95)<1500'],
        checks: ['rate>0.95'],
      },
    },
    sustained_high: {
      stages: [
        { duration: scaleDur(15), target: scaleVu(25) },  // Ramp up
        { duration: scaleDur(45), target: scaleVu(30) },  // Sustained plateau
        { duration: scaleDur(15), target: scaleVu(0) },   // Ramp down
      ],
      thresholds: {
        http_req_failed: ['rate<0.05'],
        http_req_duration: ['p(95)<1500'],
        checks: ['rate>0.95'],
      },
    },

    // 5. Recovery profile: High load returning towards baseline with stabilization observation
    recovery: {
      stages: [
        { duration: scaleDur(10), target: scaleVu(25) },  // High load warmup
        { duration: scaleDur(25), target: scaleVu(30) },  // Peak load
        { duration: scaleDur(10), target: scaleVu(5) },   // Step-down to baseline
        { duration: scaleDur(20), target: scaleVu(5) },   // Steady low demand
        { duration: scaleDur(10), target: scaleVu(0) },   // Cooldown
      ],
      thresholds: {
        http_req_failed: ['rate<0.05'],
        http_req_duration: ['p(95)<1500'],
        checks: ['rate>0.95'],
      },
    },

    // 6. Burst profile: Pulsing bursts of traffic
    burst: {
      stages: [
        { duration: scaleDur(10), target: scaleVu(5) },   // Warmup
        { duration: scaleDur(10), target: scaleVu(35) },  // Burst 1
        { duration: scaleDur(10), target: scaleVu(5) },   // Intermission
        { duration: scaleDur(10), target: scaleVu(35) },  // Burst 2
        { duration: scaleDur(10), target: scaleVu(0) },   // Cooldown
      ],
      thresholds: {
        http_req_failed: ['rate<0.10'],
        http_req_duration: ['p(95)<2000'],
        checks: ['rate>0.90'],
      },
    },
  };

  const key = profileName.toLowerCase().trim();
  const selected = profiles[key] || profiles.baseline;
  return selected;
}
