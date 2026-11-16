#!/usr/bin/env python3
"""Consolidate completed evidence; verify against originals before optional pruning."""

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from results_io import api_record, load_profile, read

RESULTS = Path(__file__).resolve().parent / "results"
VARIABLE = {"arguments", "started_utc", "finished_utc", "exit_code"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def raw_payloads(folder, kind):
    return [
        {"run_id": path.stem, "data": read(path)}
        for path in sorted((folder / "browser").glob(f"{kind}-*.json"))
        if ".manifest." not in path.name
    ]


def raw_resources(folder):
    return [
        {"run_id": path.name.removesuffix(".resources.json"), "samples": read(path)}
        for path in sorted((folder / "api").glob("*.resources.json"))
    ]


def raw_api(folder):
    return [
        api_record(read(path), read(path.with_suffix(".manifest.json")), path.stem)
        for path in sorted((folder / "api").glob("api-*.json"))
        if ".manifest." not in path.name and ".resources." not in path.name
    ]


def verify_originals(folder):
    manifest = read(folder / "manifest.json")
    require(load_profile(folder) == read(folder / "profile.json"), "Profile changed")
    require(
        read(folder / "api-runs.json")["runs"] == raw_api(folder),
        "Measured API values changed",
    )
    for kind in ("browser", "lighthouse"):
        path = folder / f"{kind}-runs.json"
        expected = raw_payloads(folder, kind)
        require(
            (read(path)["runs"] if path.exists() else []) == expected,
            f"{kind} samples changed",
        )
    require(
        read(folder / "resources.json")["runs"] == raw_resources(folder),
        "Resource samples changed",
    )
    require(
        manifest["environment"] == read(folder / "environment.json"),
        "Environment changed",
    )
    original_manifests = list(folder.rglob("*.manifest.json"))
    require(len(original_manifests) == len(manifest["runs"]), "Manifest count changed")
    by_id = {run["run_id"]: run for run in manifest["runs"]}
    for path in original_manifests:
        run_id = path.name.removesuffix(".manifest.json")
        record = by_id[run_id]
        reconstructed = {
            **manifest["contexts"][record["context"]],
            **{key: record[key] for key in VARIABLE},
        }
        require(reconstructed == read(path), f"Run metadata changed: {run_id}")
        result = path.with_name(run_id + ".json")
        require(
            digest(result) == record["original_result_sha256"],
            f"Source changed: {run_id}",
        )


def prune(folder):
    # Called only after originals have been compared with consolidated evidence.
    for name in ("api", "browser", "logs"):
        shutil.rmtree(folder / name, ignore_errors=True)
    for path in folder.glob("matrix-*.json"):
        path.unlink()
    for name in (
        "profile.manifest.json",
        "environment.json",
        "summary.md",
        "summary.json",
    ):
        (folder / name).unlink(missing_ok=True)
    if read(folder / "manifest.json")["profile"]["path"] != "profile.json":
        (folder / "profile.json").unlink()


def compact(folder, profile_ref, remove):
    if (folder / "manifest.json").exists():
        if (folder / "api").exists():
            verify_originals(folder)
            if remove:
                prune(folder)
        else:
            load_profile(folder)  # Validate the shared evidence reference.
        return
    states = sorted(folder.glob("matrix-*.json"))
    require(len(states) == 1, "Only a single completed matrix can be consolidated")
    state = read(states[0])
    require(
        state["status"] == "complete" and state["temporary_account_removed"],
        "Matrix is not complete/cleaned up",
    )
    paths = sorted(folder.rglob("*.manifest.json"))
    require(paths, "No original manifests found")
    contexts, runs = {}, []
    for path in paths:
        original = read(path)
        require(
            original["exit_code"] == 0,
            "Keep failed attempts in working format for diagnosis",
        )
        context = {key: value for key, value in original.items() if key not in VARIABLE}
        context_id = hashlib.sha256(
            json.dumps(context, sort_keys=True).encode()
        ).hexdigest()[:16]
        require(contexts.get(context_id, context) == context, "Context hash collision")
        contexts[context_id] = context
        run_id = path.name.removesuffix(".manifest.json")
        runs.append(
            {
                "run_id": run_id,
                "context": context_id,
                **{key: original[key] for key in VARIABLE},
                "original_result_sha256": digest(path.with_name(run_id + ".json")),
            }
        )
    require(len({run["run_id"] for run in runs}) == len(runs), "Duplicate run IDs")
    reference = profile_ref or "profile.json"
    reference_path = (folder / reference).resolve()
    require(
        reference_path.is_relative_to(RESULTS.resolve()),
        "Profile reference must stay in results/",
    )
    require(
        digest(reference_path) == digest(folder / "profile.json"),
        "Shared profile differs",
    )
    matrix = {
        key: value
        for key, value in state.items()
        if key not in {"pid", "temporary_username", "active", "completed", "skipped"}
    }
    matrix["completed_runs"] = len(state["completed"])
    matrix["reused_runs"] = len(state["skipped"])
    manifest = {
        "schema_version": 1,
        "sealed": True,
        "consolidated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "profile": {"path": reference, "sha256": digest(reference_path)},
        "environment": read(folder / "environment.json"),
        "matrix": matrix,
        "contexts": contexts,
        "runs": runs,
        "notes": [
            "contexts pool identical metadata; each run references its exact original context.",
            "Run arguments, timestamps, exit codes and original result hashes are preserved.",
            "API rows retain measured metrics; setup/warm-up/native duplicate metrics are intentionally omitted.",
            "Successful console logs, checkpoints and private Lighthouse dumps are not retained.",
        ],
    }
    outputs = {
        "api-runs.json": {
            "schema_version": 1,
            "units": {"duration": "milliseconds", "throughput": "requests/second"},
            "runs": raw_api(folder),
        },
        "resources.json": {"schema_version": 1, "runs": raw_resources(folder)},
    }
    for kind in ("browser", "lighthouse"):
        payloads = raw_payloads(folder, kind)
        if payloads:
            outputs[f"{kind}-runs.json"] = {"schema_version": 1, "runs": payloads}
    with tempfile.TemporaryDirectory(prefix=".compact-", dir=RESULTS) as staging:
        stage = Path(staging)
        for name, data in outputs.items():
            require(not (folder / name).exists(), f"Refusing to overwrite {name}")
            dump(stage / name, data)
        dump(stage / "manifest.json", manifest)
        for name in outputs:
            os.replace(stage / name, folder / name)
        os.replace(stage / "manifest.json", folder / "manifest.json")
    verify_originals(folder)
    if remove:
        prune(folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--profile-ref", help="Optional shared profile path relative to the dataset"
    )
    parser.add_argument(
        "--prune", action="store_true", help="Remove verified working-run inputs"
    )
    args = parser.parse_args()
    require(
        args.label.replace("-", "").replace("_", "").isalnum(), "Use a simple label"
    )
    folder = RESULTS / args.label
    compact(folder, args.profile_ref, args.prune)
    print(f"Verified consolidated evidence: {folder}")


if __name__ == "__main__":
    main()
