/**
 * SentinelScale k6 Load Test — Master Workload Generator
 *
 * Simulates realistic multi-stage traffic against the Demo API.
 * Configurable via environment variables:
 * - TARGET_URL: Target service address (default: http://localhost:8000 or http://demo-api:8000)
 * - PROFILE: Workload profile ['smoke', 'baseline', 'spike', 'sustained'] (default: baseline)
 * - VU_SCALE: Scaling factor for Virtual Users (default: 1.0)
 * - DURATION_SCALE: Scaling factor for stage durations (default: 1.0)
 */

import { sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';
import {
  checkHealth,
  listProducts,
  getProduct,
  searchProducts,
  loginUser,
  updateCart,
  checkout,
  SAMPLE_PRODUCT_IDS,
  SEARCH_KEYWORDS,
  CATEGORIES,
} from './endpoints.js';
import { getProfileConfig } from './profiles.js';

// Configuration
const TARGET_URL = (__ENV.TARGET_URL || 'http://localhost:8000').replace(/\/+$/, '');
const PROFILE = __ENV.PROFILE || 'baseline';

// Load profile configuration (stages & thresholds)
const profileConfig = getProfileConfig(PROFILE);

export const options = {
  stages: profileConfig.stages,
  thresholds: profileConfig.thresholds,
  tags: {
    workload_profile: PROFILE,
    target_service: 'demo-api',
  },
};

// Custom metrics for specific transaction types
const browseDuration = new Trend('sentinel_browse_duration_ms');
const searchDuration = new Trend('sentinel_search_duration_ms');
const checkoutDuration = new Trend('sentinel_checkout_duration_ms');
const totalTransactions = new Counter('sentinel_transactions_total');

// Helper to pick random item from array
function pickRandom(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

export default function () {
  const roll = Math.random();
  const userId = `user_${__VU}_${__ITER}`;

  if (roll < 0.35) {
    // 1. Browse product catalog (35% probability)
    const category = Math.random() > 0.5 ? pickRandom(CATEGORIES) : null;
    const start = Date.now();
    listProducts(TARGET_URL, category, 10);
    browseDuration.add(Date.now() - start);
    totalTransactions.add(1);

  } else if (roll < 0.60) {
    // 2. Keyword Search (25% probability)
    const query = pickRandom(SEARCH_KEYWORDS);
    const start = Date.now();
    searchProducts(TARGET_URL, query);
    searchDuration.add(Date.now() - start);
    totalTransactions.add(1);

  } else if (roll < 0.80) {
    // 3. View single product detail (20% probability)
    const productId = pickRandom(SAMPLE_PRODUCT_IDS);
    const start = Date.now();
    getProduct(TARGET_URL, productId);
    browseDuration.add(Date.now() - start);
    totalTransactions.add(1);

  } else if (roll < 0.90) {
    // 4. User Login Authentication (10% probability)
    loginUser(TARGET_URL, `user_${__VU}`, 'secure_demo_pass');
    totalTransactions.add(1);

  } else if (roll < 0.96) {
    // 5. Add to Cart (6% probability)
    const productId = pickRandom(SAMPLE_PRODUCT_IDS);
    updateCart(TARGET_URL, userId, productId, Math.floor(Math.random() * 3) + 1);
    totalTransactions.add(1);

  } else {
    // 6. Complete Checkout (4% probability)
    const cartId = `cart_${__VU}_${__ITER}`;
    const start = Date.now();
    checkout(TARGET_URL, cartId);
    checkoutDuration.add(Date.now() - start);
    totalTransactions.add(1);
  }

  // Realistic user pacing (think time between 100ms and 300ms)
  sleep(0.1 + Math.random() * 0.2);
}

