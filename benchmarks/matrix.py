#!/usr/bin/env python3
"""Sequential, resumable read-only load matrix. Optional temporary auth user only."""

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"


def capture(command):
    return subprocess.check_output(command, cwd=ROOT, text=True).strip()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--temporary-user", action="store_true")
    parser.add_argument("--loads", type=int, nargs="+", default=[1, 5, 10, 25])
    parser.add_argument(
        "--api-only", action="store_true", help="Only the four core API cases"
    )
    parser.add_argument(
        "--allow-threshold-failures",
        action="store_true",
        help="Record k6 threshold failures and continue stress diagnostics",
    )
    args = parser.parse_args()
    if any(load < 1 for load in args.loads) or len(set(args.loads)) != len(args.loads):
        parser.error("Loads must be distinct positive integers")
    if not args.label.replace("-", "").replace("_", "").isalnum():
        parser.error("Use a simple label")
    folder = BENCH / "results" / args.label
    if (folder / "manifest.json").exists():
        parser.error(
            "Consolidated evidence is sealed; choose a new label for measurements"
        )
    profile = json.loads((folder / "profile.json").read_text())
    logs = folder / "logs"
    logs.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    state_path = folder / f"matrix-{stamp}.json"
    containers = capture(["docker", "compose", "ps", "-q"]).splitlines()
    cpus, memory, version = capture(
        ["docker", "info", "--format", "{{.NCPU}} {{.MemTotal}} {{.ServerVersion}}"]
    ).split()
    env = dict(os.environ)
    env["BENCH_ENVIRONMENT_NOTES"] = (
        f"Compose development baseline: Django runserver DEBUG=True, Vite dev; "
        f"Docker Engine {version}, {cpus} CPUs, {memory} bytes RAM; "
        "k6 Docker 1.0.0; 15s warmup + 6s drain gap + 60s measured; 200ms think time; "
        "existing seeded fixtures, original seed not independently verified; "
        "unthrottled desktop Chromium; temporary nonstaff member if requested. "
        "Docker resource samples collected every 15s during API tests."
    )
    state = {
        "started_utc": now(),
        "status": "running",
        "pid": os.getpid(),
        "environment": env["BENCH_ENVIRONMENT_NOTES"],
        "temporary_username": None,
        "plan": {
            "core_cases": 4,
            "loads": args.loads,
            "repetitions": 3,
            "api_only": args.api_only,
            "allow_threshold_failures": args.allow_threshold_failures,
        },
        "completed": [],
        "skipped": [],
        "failures": [],
        "active": None,
    }
    state_path.write_text(json.dumps(state, indent=2) + "\n")

    def persist():
        state_path.write_text(json.dumps(state, indent=2) + "\n")

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    username = None
    current = None
    try:
        if args.temporary_user:
            username = "benchmark_" + uuid.uuid4().hex[:12]
            env["BENCH_USERNAME"] = username
            env["BENCH_PASSWORD"] = secrets.token_urlsafe(32)
            code = """import os,sys,json
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
from catalog.models import Merchant
data=json.load(sys.stdin)
merchant=Merchant.objects.get(pk=data['merchant'])
user=get_user_model().objects.create_user(username=data['username'],password=data['password'])
merchant.members.add(user)
"""
            subprocess.run(
                ["docker", "compose", "exec", "-T", "backend", "python", "-c", code],
                input=json.dumps(
                    {
                        "username": username,
                        "password": env["BENCH_PASSWORD"],
                        "merchant": profile["merchant_id"],
                    }
                ),
                text=True,
                cwd=ROOT,
                check=True,
            )
            state["temporary_username"] = username
            persist()
        elif not env.get("BENCH_USERNAME") or not env.get("BENCH_PASSWORD"):
            parser.error("Set credentials or explicitly use --temporary-user")

        def execute(action, run, case="catalogue_page_1", vus=1, reuse=True):
            nonlocal current
            filename = (
                f"api-{case}-{vus}vu-{run}.json"
                if action == "api"
                else f"{action}-{run}.json"
            )
            result = folder / ("api" if action == "api" else "browser") / filename
            manifest = result.with_suffix(".manifest.json")
            if result.exists() or manifest.exists():
                if not (result.exists() and manifest.exists()):
                    raise RuntimeError(f"Incomplete existing result: {filename}")
                meta = json.loads(manifest.read_text())
                if meta.get("exit_code") != 0:
                    raise RuntimeError(
                        f"Existing failed result: {filename}; preserve it and choose a new label/run"
                    )
                if action == "api":
                    spec = meta["arguments"]
                    expected_hash = hashlib.sha256(
                        (BENCH / "k6/api.js").read_bytes()
                    ).hexdigest()
                    if (
                        spec["duration"] != "60s"
                        or spec["warmup_seconds"] != 15
                        or meta["harness_sha256"].get("benchmarks/k6/api.js")
                        != expected_hash
                    ):
                        raise RuntimeError(
                            f"Existing run has different API methodology: {filename}"
                        )
                if not reuse:
                    raise RuntimeError(f"Refusing to overwrite {filename}")
                state["skipped"].append(filename)
                persist()
                return
            state["active"] = filename
            persist()
            command = [
                sys.executable,
                str(BENCH / "run.py"),
                action,
                "--label",
                args.label,
                "--run",
                run,
            ]
            if action == "api":
                command.extend(["--case", case, "--vus", str(vus), "--k6-docker"])
            logfile = logs / (filename + ".log")
            resources = []
            with logfile.open("x") as stream:
                current = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    env=env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                next_sample = time.monotonic() + 15
                while current.poll() is None:
                    if action == "api" and time.monotonic() >= next_sample:
                        snapshot = subprocess.run(
                            [
                                "docker",
                                "stats",
                                "--no-stream",
                                "--format",
                                "{{json .}}",
                                *containers,
                            ],
                            capture_output=True,
                            text=True,
                            timeout=15,
                        )
                        resources.append(
                            {
                                "utc": now(),
                                "exit_code": snapshot.returncode,
                                "containers": [
                                    json.loads(line)
                                    for line in snapshot.stdout.splitlines()
                                    if line.startswith("{")
                                ],
                            }
                        )
                        next_sample = time.monotonic() + 15
                    time.sleep(1)
                exit_code = current.returncode
                current = None
            if resources:
                result.with_suffix(".resources.json").write_text(
                    json.dumps(resources, indent=2) + "\n"
                )
            if exit_code:
                state["failures"].append({"file": filename, "exit_code": exit_code})
                persist()
                if not (
                    exit_code == 99
                    and args.allow_threshold_failures
                    and result.exists()
                ):
                    raise RuntimeError(
                        f"Run failed ({exit_code}): {filename}; see {logfile.relative_to(ROOT)}"
                    )
            data = json.loads(result.read_text())
            state["completed"].append(filename)
            state["active"] = None
            persist()
            if action == "api":
                latency = data["metrics"]["endpoint_duration"]["values"]
                errors = data["metrics"]["endpoint_invalid"]["values"]["rate"]
                print(
                    f"{'PASS' if exit_code == 0 else 'THRESHOLD_FAIL'} {filename}: n={latency['count']}, p95={latency['p(95)']:.2f}ms, invalid={errors:.1%}",
                    flush=True,
                )
            else:
                print(f"PASS {filename}", flush=True)

        # Schema v1 browser-01 is retained but excluded from the rAF baseline.
        if not args.api_only:
            for number in (2, 3, 4):
                execute("browser", f"{number:02d}")
            for number in (1, 2, 3):
                execute("lighthouse", f"{number:02d}")
        core = [
            "catalogue_page_1",
            "editor_2_variants",
            "editor_25_variants",
            "editor_50_variants",
        ]
        for vus in args.loads:
            for case in core:
                for number in (1, 2, 3):
                    execute("api", f"{number:02d}", case, vus)
        if not args.api_only:
            for scenario in profile["scenarios"]:
                if scenario["name"] not in core:
                    for number in (1, 2, 3):
                        execute("api", f"{number:02d}", scenario["name"], 1)
        state["status"] = (
            "complete_with_threshold_failures" if state["failures"] else "complete"
        )
    except BaseException as exc:
        state["status"] = (
            "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        )
        state["error"] = str(exc)
        raise
    finally:
        if current and current.poll() is None:
            os.killpg(current.pid, signal.SIGTERM)
            current.wait(timeout=30)
        if username:
            cleanup = """import os,sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
get_user_model().objects.filter(username=sys.stdin.read().strip()).delete()
"""
            removed = subprocess.run(
                ["docker", "compose", "exec", "-T", "backend", "python", "-c", cleanup],
                input=username,
                text=True,
                cwd=ROOT,
            )
            state["temporary_account_removed"] = removed.returncode == 0
        state["finished_utc"] = now()
        persist()
        print(f"Matrix {state['status']}: {state_path.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
