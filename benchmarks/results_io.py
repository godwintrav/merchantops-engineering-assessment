"""Read working-run files or immutable consolidated benchmark evidence."""

import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def load_manifest(folder):
    path = folder / "manifest.json"
    return read(path) if path.exists() else None


def load_profile(folder):
    manifest = load_manifest(folder)
    if not manifest:
        return read(folder / "profile.json")
    reference = manifest["profile"]
    path = (folder / reference["path"]).resolve()
    if not path.is_relative_to(folder.parent.resolve()):
        raise ValueError("Profile reference must stay within results/")
    if hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
        raise ValueError("Shared profile hash does not match")
    return read(path)


def api_record(data, manifest, run_id):
    metrics = data["metrics"]
    options = manifest["arguments"]
    latency = metrics["endpoint_duration"]["values"]
    clock = metrics.get("measurement_clock_ms", {}).get("values", {})
    return {
        "run_id": run_id,
        "case": options["case"],
        "vus": options["vus"],
        "samples": metrics["endpoint_requests"]["values"]["count"],
        "min_ms": latency["min"],
        "median_ms": latency["med"],
        "p95_ms": latency["p(95)"],
        "p99_ms": latency["p(99)"],
        "max_ms": latency["max"],
        "invalid_rate": metrics["endpoint_invalid"]["values"]["rate"],
        "http_failure_rate": metrics["endpoint_http_failed"]["values"]["rate"],
        "requests_per_second": data["benchmark"]["measured_requests_per_second"],
        "measured_window_seconds": data["benchmark"]["measured_request_window_seconds"],
        "first_request_epoch_ms": clock.get("min"),
        "last_request_epoch_ms": clock.get("max"),
        "checks": metrics.get("checks", {}).get("values", {}),
        "thresholds": {
            name: metric["thresholds"]
            for name, metric in metrics.items()
            if name.startswith("endpoint_") and "thresholds" in metric
        },
        "exit_code": manifest["exit_code"],
    }


def api_runs(folder):
    if load_manifest(folder):
        for row in read(folder / "api-runs.json")["runs"]:
            yield {**row, "file": f"{folder.name}/api-runs.json"}
        return
    for path in sorted((folder / "api").glob("api-*.json")):
        if ".manifest." in path.name or ".resources." in path.name:
            continue
        manifest = read(path.with_suffix(".manifest.json"))
        row = api_record(read(path), manifest, path.stem)
        yield {**row, "file": f"{folder.name}/api/{path.name}"}


def browser_runs(folder, kind):
    """Yield original browser payloads with batch ID and exit code."""
    manifest = load_manifest(folder)
    if manifest:
        path = folder / f"{kind}-runs.json"
        if not path.exists():
            return
        exits = {run["run_id"]: run["exit_code"] for run in manifest["runs"]}
        for row in read(path)["runs"]:
            yield row["run_id"], row["data"], exits[row["run_id"]]
        return
    for path in sorted((folder / "browser").glob(f"{kind}-*.json")):
        if ".manifest." not in path.name:
            yield path.stem, read(path), read(path.with_suffix(".manifest.json"))[
                "exit_code"
            ]


def resource_runs(folder):
    if load_manifest(folder):
        yield from read(folder / "resources.json")["runs"]
        return
    for path in sorted((folder / "api").glob("*.resources.json")):
        yield {
            "run_id": path.name.removesuffix(".resources.json"),
            "samples": read(path),
        }


def run_context(folder):
    manifest = load_manifest(folder)
    if manifest:
        return manifest["matrix"], manifest["environment"]
    states = sorted(folder.glob("matrix-*.json"))
    environment = folder / "environment.json"
    return (
        read(states[-1]) if states else {},
        read(environment) if environment.exists() else {},
    )
