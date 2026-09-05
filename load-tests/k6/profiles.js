/**
 * SentinelScale k6 Workload Profiles Definition
 *
 * Defines stage configurations, target VUs, and test thresholds for different traffic patterns:
 * 1. smoke: Rapid validation (10s @ 2 VUs)
 * 2. baseline: Normal steady-state diurnal traffic (warmup -> steady -> cooldown)
 * 3. spike: Legitimate flash crowd / surge event
 * 4. sustained: Heavy sustained peak utilization
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

    // 2. Baseline profile: Normal steady-state diurnal traffic pattern
    baseline: {
      stages: [
        { duration: scaleDur(10), target: scaleVu(5) },   // Phase 1: Warm-up
        { duration: scaleDur(30), target: scaleVu(10) },  // Phase 2: Steady baseline
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
        { duration: scaleDur(15), target: scaleVu(10) },  // Steady baseline
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

    // 4. Sustained profile: High load sustained over extended period
    sustained: {
      stages: [
        { duration: scaleDur(15), target: scaleVu(25) },  // Ramp up
        { duration: scaleDur(60), target: scaleVu(25) },  // Sustained plateau
        { duration: scaleDur(15), target: scaleVu(0) },   // Ramp down
      ],
      thresholds: {
        http_req_failed: ['rate<0.05'],
        http_req_duration: ['p(95)<1500'],
        checks: ['rate>0.95'],
      },
    },
  };

  const selected = profiles[profileName.toLowerCase()] || profiles.baseline;
  return selected;
}

