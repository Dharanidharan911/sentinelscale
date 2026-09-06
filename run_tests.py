#!/usr/bin/env python3
"""
SentinelScale Isolated Test Runner
Executes test suites for each independent microservice in completely separate subprocesses
with strictly isolated service-specific PYTHONPATH environments.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# Strict execution order as specified
SERVICES = [
    {
        "name": "Demo API",
        "service_dir": REPO_ROOT / "demo-api",
        "test_dir": "demo-api/tests",
    },
    {
        "name": "Traffic Intelligence",
        "service_dir": REPO_ROOT / "services" / "traffic-intelligence",
        "test_dir": "services/traffic-intelligence/tests",
    },
    {
        "name": "Demand Intelligence",
        "service_dir": REPO_ROOT / "services" / "demand-intelligence",
        "test_dir": "services/demand-intelligence/tests",
    },
    {
        "name": "Platform & Decision Engine",
        "service_dir": REPO_ROOT / "services" / "platform",
        "test_dir": "services/platform/tests",
    },
    {
        "name": "Control Center",
        "service_dir": REPO_ROOT / "services" / "control-center",
        "test_dir": "services/control-center/tests",
    },
]



def run_service_tests(service_info: dict) -> int:
    service_name = service_info["name"]
    service_path = str(service_info["service_dir"])
    test_rel_path = service_info["test_dir"]

    # Construct clean child environment inheriting system env but setting PYTHONPATH strictly to this service root
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = service_path

    # Clean any Pytest options that might override pythonpath
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        test_rel_path,
        "-v",
        "-o",
        f"pythonpath={service_path}",
    ]

    print(f"\n>> [{service_name}] Running isolated pytest suite...")
    print(f"   Service Root : {service_path}")
    print(f"   Test Target  : {test_rel_path}")

    # Stream stdout and stderr directly to terminal
    result = subprocess.run(
        cmd,
        env=child_env,
        cwd=str(REPO_ROOT),
    )
    return result.returncode


def main() -> int:
    print("=" * 70)
    print(" SentinelScale Subprocess-Isolated Microservice Test Runner")
    print("=" * 70)

    failed_services = []

    for service in SERVICES:
        ret = run_service_tests(service)
        if ret != 0:
            failed_services.append(service["name"])

    print("\n" + "=" * 70)
    print(" TEST EXECUTION SUMMARY")
    print("=" * 70)

    for service in SERVICES:
        status = "FAILED" if service["name"] in failed_services else "PASSED"
        print(f" - {service['name']:<35} : {status}")

    print("=" * 70)

    if not failed_services:
        print(" ALL 4 SERVICE TEST SUITES PASSED SUCCESSFULLY")
        print("=" * 70)
        return 0
    else:
        print(f" FAILED: {len(failed_services)} test suite(s) failed.")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
