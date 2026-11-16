#!/usr/bin/env python3
"""Generate matched before/after tables from working or consolidated results."""

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import median

from results_io import (
    api_runs,
    browser_runs,
    load_manifest,
    load_profile,
    read,
    run_context,
)

RESULTS = Path(__file__).resolve().parent / "results"
CORE = [
    "catalogue_page_1",
    "editor_2_variants",
    "editor_25_variants",
    "editor_50_variants",
]
NAMES = [
    "Catalogue",
    "Editor: 2 variants",
    "Editor: 25 variants",
    "Editor: 50 variants",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def dataset(label):
    require(label.replace("-", "").replace("_", "").isalnum(), "Use simple labels")
    folder = RESULTS / label
    state, _ = run_context(folder)
    require(
        state.get("status") in ("complete", "complete_with_threshold_failures"),
        f"{label} is incomplete",
    )
    require(
        state.get("temporary_account_removed") is True, f"{label} cleanup unverified"
    )
    return folder, list(api_runs(folder))


def workload_fingerprints(folder):
    manifest = load_manifest(folder)
    contexts = (
        list(manifest["contexts"].values())
        if manifest
        else [read(path) for path in folder.rglob("*.manifest.json")]
    )
    primary = (
        "benchmarks/k6/api.js",
        "benchmarks/browser/common.mjs",
        "benchmarks/browser/workflows.mjs",
        "benchmarks/browser/lighthouse.mjs",
        "backend/catalog/management/commands/benchmark_profile.py",
    )
    require(bool(contexts), "Missing workload provenance")
    fingerprints = {
        tuple(context["harness_sha256"][path] for path in primary)
        for context in contexts
    }
    require(len(fingerprints) == 1, f"Primary workloads changed within {folder.name}")
    return fingerprints.pop()


def grouped(rows):
    result = defaultdict(list)
    for row in rows:
        require(
            row["samples"] > 0 and row["exit_code"] in (0, 99), "Invalid measurement"
        )
        result[(row["case"], row["vus"])].append(row)
    require(
        all(len(runs) == 3 for runs in result.values()),
        "Expected three runs per case/load",
    )
    return result


def tail(rows):
    values = [row["p95_ms"] for row in rows]
    return f"{min(values):.2f}–{max(values):.2f}"


def rate(rows):
    return f"{median(row['requests_per_second'] for row in rows):.2f}"


def workflows(folder):
    result = defaultdict(list)
    for _, data, exit_code in browser_runs(folder, "browser"):
        require(
            exit_code == 0 and data["schema_version"] == 2, "Incompatible browser batch"
        )
        for row in data["results"]:
            require(row["errors"] == 0, "Browser workflow errors recorded")
            result[row["name"]].append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-full", default="baseline-full")
    parser.add_argument("--before-stress", default="baseline-stress")
    parser.add_argument("--after-full", default="optimized-full")
    parser.add_argument("--after-stress", default="optimized-stress")
    args = parser.parse_args()
    before_full, before_rows = dataset(args.before_full)
    before_stress, before_extra = dataset(args.before_stress)
    after_full, after_rows = dataset(args.after_full)
    after_stress, after_extra = dataset(args.after_stress)
    folders = (before_full, before_stress, after_full, after_stress)
    require(
        len({workload_fingerprints(folder) for folder in folders}) == 1,
        "Primary workload fingerprints differ between revisions",
    )
    before = grouped(before_rows + before_extra)
    after = grouped(after_rows + after_extra)
    require(before.keys() == after.keys(), "Scenario/load combinations differ")
    original_profile = load_profile(before_full)
    optimized_profile = load_profile(after_full)
    for folder in (before_stress, after_full, after_stress):
        profile = load_profile(folder)
        require(
            profile["fixtures"] == original_profile["fixtures"],
            "Fixture counts/IDs differ",
        )
        require(
            profile["scenarios"] == original_profile["scenarios"],
            "Workload definitions differ",
        )
        require(
            profile["environment"] == original_profile["environment"],
            "Recorded backend versions/settings differ",
        )
    before_browser, after_browser = workflows(before_full), workflows(after_full)
    require(before_browser.keys() == after_browser.keys(), "Browser workflows differ")
    require(
        all(len(rows) == 9 for rows in before_browser.values()),
        "Expected nine baseline browser samples",
    )
    require(
        all(len(rows) == 9 for rows in after_browser.values()),
        "Expected nine optimized browser samples",
    )
    total_before = sum(r["samples"] for r in before_rows + before_extra)
    total_after = sum(r["samples"] for r in after_rows + after_extra)
    fail_before = max(r["invalid_rate"] for r in before_rows + before_extra)
    fail_after = max(r["invalid_rate"] for r in after_rows + after_extra)
    http_before = max(r["http_failure_rate"] for r in before_rows + before_extra)
    http_after = max(r["http_failure_rate"] for r in after_rows + after_extra)
    lines = [
        "# Performance Comparison",
        "",
        f"Matched evidence: {args.before_full}/{args.before_stress} versus {args.after_full}/{args.after_stress}.",
        f"Each revision has 90 API runs: {total_before:,} baseline and {total_after:,} optimized measured requests. "
        f"Maximum per-run invalid-response rates: {fail_before:.2%} baseline, {fail_after:.2%} optimized. "
        f"HTTP failure rates: {http_before:.2%} baseline, {http_after:.2%} optimized.",
        "",
        "## API Latency and Throughput",
        "",
        "p95 columns are ranges of three individual-run percentiles in milliseconds, not pooled or averaged p95s. "
        "Throughput columns are medians of the three measured-window rates, including 200ms think time. "
        "Latency includes unsuccessful responses if present; interpret it alongside failure rates.",
        "",
        "| Scenario | VUs | Before p95 ms | After p95 ms | Before req/s | After req/s | After max invalid |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    keys = sorted(
        before,
        key=lambda key: (CORE.index(key[0]) if key[0] in CORE else 4, key[0], key[1]),
    )
    for key in keys:
        old, new = before[key], after[key]
        lines.append(
            f"| {key[0]} | {key[1]} | {tail(old)} | {tail(new)} | {rate(old)} | {rate(new)} | "
            f"{max(r['invalid_rate'] for r in new):.2%} |"
        )
    old_queries = {
        row["scenario"]: row["queries"] for row in original_profile["query_profiles"]
    }
    new_queries = {
        row["scenario"]: row["queries"] for row in optimized_profile["query_profiles"]
    }
    failed = [
        row
        for row in after_rows + after_extra
        if row["invalid_rate"] or row["http_failure_rate"] or row["exit_code"]
    ]
    if failed:
        lines += [
            "",
            "## Reliability Finding",
            "",
            f"{len(failed)} optimized runs failed zero-error thresholds. They remain included "
            "in all tables; their latency/throughput is not a clean success result. "
            f"See [{args.after_stress} measurements]({args.after_stress}/api-runs.json) for per-run failure rates. "
            "No failed repetition was discarded or replaced.",
            "",
        ]
    lines += [
        "",
        "## Diagnostic SQL Queries",
        "",
        "Forced-authenticated captures exclude session/authentication queries.",
        "",
        "| Scenario | Before | After |",
        "| --- | ---: | ---: |",
    ]
    for case in CORE:
        lines.append(f"| {case} | {old_queries[case]} | {new_queries[case]} |")
    lines += [
        "",
        "## Browser Workflows",
        "",
        "Nine samples per workflow per revision. Times are action-to-validated-DOM readiness, including automation "
        "overhead, not exact paint. Negative percentage changes mean a lower observed median; positive values "
        "mean a higher median. All workflows are shown, including those without a timing improvement.",
        "",
        "| Workflow | Before median ms | After median ms | Median change | Before API calls | After API calls |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for name in sorted(before_browser):
        old, new = before_browser[name], after_browser[name]
        old_time, new_time = median(r["duration_ms"] for r in old), median(
            r["duration_ms"] for r in new
        )
        old_calls = ", ".join(str(x) for x in sorted({r["requests"] for r in old}))
        new_calls = ", ".join(str(x) for x in sorted({r["requests"] for r in new}))
        lines.append(
            f"| {name} | {old_time:.2f} | {new_time:.2f} | {(new_time / old_time - 1) * 100:+.2f}% | "
            f"{old_calls} | {new_calls} |"
        )
    lighthouse = {}
    for label, folder in (("before", before_full), ("after", after_full)):
        batches = list(browser_runs(folder, "lighthouse"))
        require(
            len(batches) == 3 and all(code == 0 for _, _, code in batches),
            "Expected three successful Lighthouse audits",
        )
        lighthouse[label] = [data for _, data, _ in batches]
    lines += [
        "",
        "## Lighthouse Diagnostics",
        "",
        "Three warm, unthrottled desktop audits per revision. These initial-load metrics "
        "can precede catalogue readiness and are not field Core Web Vitals.",
        "",
        "| Metric | Before median | After median | Unit |",
        "| --- | ---: | ---: | --- |",
    ]
    for metric, values in lighthouse["before"][0]["metrics"].items():
        old = median(data["metrics"][metric]["value"] for data in lighthouse["before"])
        new = median(data["metrics"][metric]["value"] for data in lighthouse["after"])
        lines.append(f"| {metric} | {old:.2f} | {new:.2f} | {values['unit']} |")
    lines += [
        "",
        "## Method and Limits",
        "",
        "- Same primary API/browser/Lighthouse scripts, seeded fixture IDs/counts, 15s warm-up, 6s drain gap, "
        "60s measurement, 200ms think time, sequential case ordering, and Docker resource sampling.",
        "- Same recorded Python/Django/MySQL/debug settings, host, Docker resource limits and configured "
        "Django runserver/Vite serving mode. Exact frontend Node patch version was not recorded in the original "
        "baseline; the optimized manifest records the current version.",
        "- These are local development comparisons, not production capacity, fixed-arrival-rate limits, or field Core Web Vitals.",
        "- VUs share one merchant-member session per run and target hot fixtures. Fast routes can approach the "
        "load generator's think-time ceiling; reported throughput is not maximum server capacity.",
        "- Search includes its existing 300ms debounce. Browser samples and automation overhead limit interpretation "
        "of small timing differences; request counts and SQL budgets are separate deterministic checks.",
        "- Optimized stress combines original 50-VU observations with the subsequent 100-VU rerun. Original per-run provenance is retained; prior host/socket/cache state was not identical. The rerun supersedes the earlier 100-VU execution and does not demonstrate a connection-failure fix.",
        "- Editor responses now include image_url. Underlying business fixtures are unchanged; the response field is additive.",
        "- Activity history has one record: smoke coverage only. Inventory-adjustment write contention is not tested here.",
        "- Resources, browser/Lighthouse payloads and exact per-run provenance remain in the consolidated evidence. "
        "Sampled resource peaks are not continuous maxima or normalized cost per request.",
        "",
        "## Evidence",
        "",
    ]
    for label in (
        args.before_full,
        args.before_stress,
        args.after_full,
        args.after_stress,
    ):
        lines.append(
            f"- [{label} API runs]({label}/api-runs.json), [metadata]({label}/manifest.json), "
            f"[resources]({label}/resources.json)."
        )
    lines += [
        "",
        "Use the [benchmark README](../README.md) for reproduction, report generation and consolidation. "
        "The source of every table is retained per-run data; successful transient logs and duplicate working files are pruned.",
        "",
    ]
    (RESULTS / "comparison.md").write_text("\n".join(lines))
    stress = [
        "# High-Load Before/After Comparison",
        "",
        "Each cell is a range of three run p95 values in milliseconds. The 25-user control is included alongside 50/100 VUs.",
        "",
        "| API | Before 25 | After 25 | Before 50 | After 50 | Before 100 | After 100 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case, name in zip(CORE, NAMES):
        cells = [
            value
            for vus in (25, 50, 100)
            for value in (tail(before[(case, vus)]), tail(after[(case, vus)]))
        ]
        stress.append("| " + " | ".join([name, *cells]) + " |")
    stress += [
        "",
        "## Throughput",
        "",
        "Median measured-window requests/sec. Includes think time; not maximum capacity.",
        "",
        "| API | Before 25 | After 25 | Before 50 | After 50 | Before 100 | After 100 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case, name in zip(CORE, NAMES):
        cells = [
            value
            for vus in (25, 50, 100)
            for value in (rate(before[(case, vus)]), rate(after[(case, vus)]))
        ]
        stress.append("| " + " | ".join([name, *cells]) + " |")
    stress += [
        "",
        f"Maximum per-run invalid-response rate: {fail_before:.2%} baseline, {fail_after:.2%} optimized. "
        + (
            "Some runs failed zero-error thresholds; interpret latency alongside failures. "
            if failed
            else "All selected runs passed zero-error thresholds. "
        )
        + "Passing validation is not a latency SLO. See [full comparison](comparison.md) for all load levels, "
        "browser/SQL evidence, raw-data links, methodology and limitations.",
        "",
    ]
    (RESULTS / "stress-comparison.md").write_text("\n".join(stress))
    print("Generated matched API, query, browser, and stress comparison tables.")


if __name__ == "__main__":
    main()
