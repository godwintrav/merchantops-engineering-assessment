#!/usr/bin/env python3
"""Run from the repository root. Does not provision users or modify fixtures."""

import argparse
import datetime
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"


def capture(command):
    return subprocess.check_output(command, cwd=ROOT, text=True).strip()


def write_new(path, data):
    with path.open("x") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["profile", "api", "browser", "lighthouse"])
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--run", default="01")
    parser.add_argument("--case", default="catalogue_page_1")
    parser.add_argument("--vus", type=int, default=1)
    parser.add_argument("--duration", default="60s")
    parser.add_argument("--warmup-seconds", type=int, default=15)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--k6-docker",
        action="store_true",
        help="Use pinned k6 container on the backend network",
    )
    args = parser.parse_args()
    for value in (args.label, args.run, args.case):
        if not value or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in value
        ):
            parser.error("label/run/case must be simple names without path separators")
    if args.vus < 1 or args.repetitions < 1 or args.warmup_seconds < 1:
        parser.error("vus, repetitions and warmup must be positive")

    directory = BENCH / "results" / args.label
    if (directory / "manifest.json").exists():
        parser.error(
            "Consolidated evidence is sealed; choose a new label for measurements"
        )
    directory.mkdir(parents=True, exist_ok=True)
    profile = directory / "profile.json"
    if args.action == "profile":
        if profile.exists():
            parser.error("Profile already exists; use a new label to preserve evidence")
        username = os.environ.get("BENCH_USERNAME", "demo_operator")
        command = [
            "docker",
            "compose",
            "exec",
            "-T",
            "backend",
            "python",
            "manage.py",
            "benchmark_profile",
            "--username",
            username,
        ]
        data = json.loads(capture(command))
        write_new(profile, data)
        output = profile
    else:
        if not profile.exists():
            parser.error("Run profile first for this label")
        if args.action == "api" and args.case not in {
            scenario["name"]
            for scenario in json.loads(profile.read_text())["scenarios"]
        }:
            parser.error("Unknown case; choose a scenario name from profile.json")
        folder = directory / (
            "browser" if args.action in ("browser", "lighthouse") else "api"
        )
        folder.mkdir(exist_ok=True)
        name = (
            f"{args.action}-{args.case}-{args.vus}vu-{args.run}.json"
            if args.action == "api"
            else f"{args.action}-{args.run}.json"
        )
        output = folder / name
        if output.exists() or output.with_suffix(".manifest.json").exists():
            parser.error("Run already exists; choose another --run")
        env = {
            **os.environ,
            "BENCH_CONFIG": str(profile),
            "RESULT_PATH": str(output),
            "VUS": str(args.vus),
            "CASE": args.case,
            "DURATION": args.duration,
            "WARMUP_SECONDS": str(args.warmup_seconds),
            "REPETITIONS": str(args.repetitions),
        }
        if args.action == "api":
            command = ["k6", "run", str(BENCH / "k6" / "api.js")]
            if args.k6_docker:
                container = capture(["docker", "compose", "ps", "-q", "backend"])
                if not container:
                    parser.error("Backend container must be running")
                env.update(
                    {
                        "BASE_URL": os.environ.get("BASE_URL", "http://127.0.0.1:8000"),
                        "BENCH_CONFIG": f"/scripts/results/{args.label}/profile.json",
                        "RESULT_PATH": f"/output/{output.name}",
                    }
                )
                command = [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "container:" + container,
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "-v",
                    f"{BENCH}:/scripts:ro",
                    "-v",
                    f"{folder}:/output",
                ]
                for key in (
                    "BENCH_USERNAME",
                    "BENCH_PASSWORD",
                    "BASE_URL",
                    "BENCH_CONFIG",
                    "RESULT_PATH",
                    "VUS",
                    "CASE",
                    "DURATION",
                    "WARMUP_SECONDS",
                ):
                    command.extend(["-e", key])
                command.extend(["grafana/k6:1.0.0", "run", "/scripts/k6/api.js"])
        else:
            script = "workflows.mjs" if args.action == "browser" else "lighthouse.mjs"
            command = ["node", str(BENCH / "browser" / script)]

    # Record at start, including failures. Never serialize environment credentials.
    scripts = [
        p
        for p in BENCH.rglob("*")
        if p.is_file()
        and not any(
            part in ("node_modules", "results", "__pycache__") for part in p.parts
        )
    ]
    scripts.append(ROOT / "backend/catalog/management/commands/benchmark_profile.py")
    manifest = {
        "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "application_commit": capture(["git", "rev-parse", "HEAD"]),
        "working_tree_status": capture(["git", "status", "--short"]),
        "host": {
            "system": platform.platform(),
            "architecture": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "arguments": vars(args),
        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "harness_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(scripts)
        },
        "base_url": (
            env["BASE_URL"]
            if args.action == "api" and args.k6_docker
            else os.environ.get("BASE_URL", "http://127.0.0.1:8002")
        ),
        "frontend_url": os.environ.get("FRONTEND_URL", "http://127.0.0.1:5173"),
        "environment_notes": os.environ.get(
            "BENCH_ENVIRONMENT_NOTES",
            "UNRECORDED: document Docker limits, serving mode, hardware, fixture seed",
        ),
        "exit_code": None,
    }
    manifest_path = output.with_suffix(".manifest.json")
    write_new(manifest_path, manifest)
    code = 0
    if args.action != "profile":
        try:
            code = subprocess.call(command, cwd=ROOT, env=env)
        except FileNotFoundError as exc:
            print(f"Missing executable: {exc.filename}. See benchmarks/README.md")
            code = 127
    manifest["exit_code"] = code
    manifest["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Result: {output.relative_to(ROOT)}; exit code: {code}")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
