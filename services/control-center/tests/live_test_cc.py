import urllib.request
import urllib.parse
import json

print("=== 1. CONTROL CENTER LIVE HEALTH & ROOT ===")
endpoints = [
    ("GET", "http://localhost:8080/health", None),
    ("GET", "http://localhost:8080/ready", None),
    ("GET", "http://localhost:8080/version", None),
    ("GET", "http://localhost:8080/", None),
    ("GET", "http://localhost:8080/api/proxy/version", None),
    ("GET", "http://localhost:8080/api/proxy/resources/current?namespace=default&workload=demo-api", None),
    ("GET", "http://localhost:8080/api/proxy/history?limit=5", None),
    ("POST", "http://localhost:8080/api/proxy/decision/orchestrate", {"namespace": "default", "workload": "demo-api"}),
]

for method, url, body_data in endpoints:
    try:
        data = json.dumps(body_data).encode("utf-8") if body_data else None
        headers = {"Content-Type": "application/json"} if body_data else {}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8")
            print(f"[{method}] {url:<75} -> {resp.status} OK (len: {len(content)})")
            if "orchestrate" in url or "version" in url:
                print(f"       Response snippet: {content[:150]}")
    except Exception as e:
        print(f"[{method}] {url:<75} -> FAIL: {e}")

