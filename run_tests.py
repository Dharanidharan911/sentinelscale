#!/usr/bin/env python3
"""
SentinelScale Test Runner
Executes test suites across all independent microservices.
"""
import subprocess
import sys

SERVICES = [
    ("Demo API", "demo-api/tests", "demo-api"),
    ("Traffic Intelligence", "services/traffic-intelligence/tests", "services/traffic-intelligence"),
    ("Demand Intelligence", "services/demand-intelligence/tests", "services/demand-intelligence"),
    ("Platform & Decision Engine", "services/platform/tests", "services/platform"),
]


def run_all_tests():
    total_failed = 0
    print("=" * 60)
    print(" Running SentinelScale Microservices Test Suite")
    print("=" * 60)

    for name, test_dir, python_path in SERVICES:
        print(f"\n>> Testing {name} ({test_dir})...")
        cmd = [
            sys.executable, "-m", "pytest", test_dir, "-v",
            "-o", f"pythonpath={python_path}"
        ]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"FAILED: {name}")
            total_failed += 1
        else:
            print(f"PASSED: {name}")

    print("\n" + "=" * 60)
    if total_failed == 0:
        print(" ALL 4 SERVICE TEST SUITES PASSED SUCCESSFULLY")
        print("=" * 60)
        return 0
    else:
        print(f" {total_failed} TEST SUITE(S) FAILED")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
