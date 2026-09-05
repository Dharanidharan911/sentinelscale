/**
 * SentinelScale k6 Load Test - Demo API Endpoints Module
 *
 * Implements realistic API interaction helpers representing genuine user journeys:
 * - Product browsing & catalog pagination
 * - Keyword search
 * - Single item product detail retrieval
 * - User authentication (login)
 * - Cart updates
 * - Checkout processing
 * - Health / ready probes
 */

import http from 'k6/http';
import { check } from 'k6';

export const SAMPLE_PRODUCT_IDS = [
  'prod-001',
  'prod-002',
  'prod-003',
  'prod-004',
  'prod-005',
];

export const SEARCH_KEYWORDS = [
  'security',
  'compute',
  'telemetry',
  'pod',
  'waf',
  'rate',
  'mesh',
];

export const CATEGORIES = [
  'security',
  'compute',
  'telemetry',
  'networking',
];

const JSON_HEADERS = {
  'Content-Type': 'application/json',
  'Accept': 'application/json',
};

/**
 * Health check probe
 */
export function checkHealth(baseUrl) {
  const res = http.get(`${baseUrl}/health`, { headers: JSON_HEADERS, tags: { endpoint: 'health' } });
  return check(res, {
    'health status is 200': (r) => r.status === 200,
  });
}

/**
 * Browse products catalog
 */
export function listProducts(baseUrl, category = null, limit = 10) {
  let url = `${baseUrl}/products?limit=${limit}`;
  if (category) {
    url += `&category=${category}`;
  }
  const res = http.get(url, { headers: JSON_HEADERS, tags: { endpoint: 'products_list' } });
  return check(res, {
    'products list status is 200': (r) => r.status === 200,
    'products list returns array': (r) => {
      try {
        const body = JSON.parse(r.body);
        return Array.isArray(body);
      } catch (e) {
        return false;
      }
    },
  });
}

/**
 * Get product detail by ID
 */
export function getProduct(baseUrl, productId) {
  const res = http.get(`${baseUrl}/products/${productId}`, { headers: JSON_HEADERS, tags: { endpoint: 'product_detail' } });
  return check(res, {
    'product detail status is 200': (r) => r.status === 200,
    'product detail has id': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.id === productId;
      } catch (e) {
        return false;
      }
    },
  });
}

/**
 * Search products by keyword
 */
export function searchProducts(baseUrl, query) {
  const res = http.get(`${baseUrl}/search?q=${encodeURIComponent(query)}`, { headers: JSON_HEADERS, tags: { endpoint: 'search' } });
  return check(res, {
    'search status is 200': (r) => r.status === 200,
    'search returns array': (r) => {
      try {
        const body = JSON.parse(r.body);
        return Array.isArray(body);
      } catch (e) {
        return false;
      }
    },
  });
}

/**
 * Authenticate user
 */
export function loginUser(baseUrl, username = 'demo_user', password = 'password123') {
  const payload = JSON.stringify({ username, password });
  const res = http.post(`${baseUrl}/login`, payload, { headers: JSON_HEADERS, tags: { endpoint: 'login' } });
  return check(res, {
    'login status is 200': (r) => r.status === 200,
    'login returns token': (r) => {
      try {
        const body = JSON.parse(r.body);
        return !!body.token;
      } catch (e) {
        return false;
      }
    },
  });
}

/**
 * Add item to cart
 */
export function updateCart(baseUrl, userId, productId, quantity = 1) {
  const payload = JSON.stringify({
    user_id: userId,
    items: [{ product_id: productId, quantity: quantity }],
  });
  const res = http.post(`${baseUrl}/cart`, payload, { headers: JSON_HEADERS, tags: { endpoint: 'cart' } });
  return check(res, {
    'cart status is 200': (r) => r.status === 200,
    'cart returns cart_id': (r) => {
      try {
        const body = JSON.parse(r.body);
        return !!body.cart_id;
      } catch (e) {
        return false;
      }
    },
  });
}

/**
 * Process order checkout
 */
export function checkout(baseUrl, cartId = 'cart-test-01') {
  const payload = JSON.stringify({
    cart_id: cartId,
    payment_method: 'credit_card',
    shipping_address: '100 Enterprise Way, Suite 400, Cloud City, CC 94016',
  });
  const res = http.post(`${baseUrl}/checkout`, payload, { headers: JSON_HEADERS, tags: { endpoint: 'checkout' } });
  return check(res, {
    'checkout status is 200': (r) => r.status === 200,
    'checkout status is completed': (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.status === 'completed';
      } catch (e) {
        return false;
      }
    },
  });
}
