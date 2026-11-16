#!/usr/bin/env python3
"""Summarize saved results without pooling or averaging run percentiles."""

import argparse
from collections import defaultdict
from pathlib import Path
from statistics import median

from results_io import api_runs, browser_runs, load_profile, resource_runs, run_context

ROOT = Path(__file__).resolve().parent


def spread(values, digits=2):
    return f"{min(values):.{digits}f}–{max(values):.{digits}f}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="baseline-full")
    parser.add_argument("--include-threshold-failures", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional report destination")
    args = parser.parse_args()
    if not args.label.replace("-", "").replace("_", "").isalnum():
        parser.error("Use a simple label")
    folder = ROOT / "results" / args.label
    profile = load_profile(folder)
    state, environment = run_context(folder)
    groups = defaultdict(list)
    failed = []
    artifacts = []
    for row in api_runs(folder):
        if row["exit_code"] != 0:
            failed.append(row["run_id"])
            if not (args.include_threshold_failures and row["exit_code"] == 99):
                continue
        if row["samples"] == 0:
            failed.append(row["run_id"] + " (zero samples)")
            continue
        groups[(row["case"], row["vus"])].append(row)
        artifacts.append(row)
    browser = defaultdict(list)
    for run_id, data, exit_code in browser_runs(folder, "browser"):
        if exit_code != 0:
            failed.append(run_id)
            continue
        if data["schema_version"] != 2:
            continue
        for row in data["results"]:
            browser[row["name"]].append({**row, "run_id": run_id})
    lighthouse = defaultdict(list)
    for run_id, data, exit_code in browser_runs(folder, "lighthouse"):
        if exit_code != 0:
            failed.append(run_id)
            continue
        for name, value in data["metrics"].items():
            lighthouse[name].append(value["value"])
    lines = [
        f"# {args.label} Performance Results",
        "",
        f"Evidence folder: {args.label}/. Generated from saved JSON; no optimized comparison yet.",
        "",
        f"Matrix status: {state.get('status', 'not recorded')}. Do not treat a running or partial matrix as complete.",
        "",
        "## Conditions",
        "",
        state.get(
            "environment",
            "See individual run manifests for serving configuration and resource limits.",
        ),
        "",
        f"Host: {environment.get('machdep.cpu.brand_string', 'not recorded')}; "
        f"RAM bytes: {environment.get('hw.memsize', 'not recorded')}. "
        "See the dataset manifest for environment and per-run settings.",
        "",
        f"Fixtures: {profile['fixtures']['products']:,} merchant products, "
        f"{profile['fixtures']['variants']:,} variants, "
        f"{profile['fixtures']['activity_records']} activity record(s). "
        "Activity history is a smoke check, not a history-scale benchmark.",
        "",
        "API runs use 15s warm-up, a 6s drain gap, 60s measured time, and 200ms think time. "
        "The matrix specifies three repetitions per case/load. Tests run sequentially; service CPU/memory "
        "are sampled every 15s. Authentication/setup is outside custom endpoint metrics.",
        "",
        "## API Results",
        "",
        "Median column is the median of individual run medians. p95/p99 columns are ranges of "
        "individual run percentiles, not pooled percentiles. Throughput includes think time and "
        "uses the measured request window. It is not maximum server capacity.",
        "If threshold-failed stress runs are included, latency includes unsuccessful responses; interpret it alongside failure rates, not as success-only latency.",
        "",
        "| Scenario | VUs | Runs | Requests | Typical median ms | Run p95 range ms | Run p99 range ms | Typical req/s | Max invalid rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (case, vus), rows in sorted(groups.items()):
        lines.append(
            f"| {case} | {vus} | {len(rows)} | {sum(r['samples'] for r in rows):,} | "
            f"{median(r['median_ms'] for r in rows):.2f} | "
            f"{spread([r['p95_ms'] for r in rows])} | "
            f"{spread([r['p99_ms'] for r in rows])} | "
            f"{median(r['requests_per_second'] for r in rows):.2f} | "
            f"{max(r['invalid_rate'] for r in rows):.2%} |"
        )
    lines.extend(
        [
            "",
            "## SQL Query Counts",
            "",
            "Separate ORM captures exclude session/authentication SQL. These are query counts, not timings.",
            "",
            "| Scenario | Queries | Response bytes |",
            "| --- | ---: | ---: |",
        ]
    )
    for row in profile["query_profiles"]:
        lines.append(
            f"| {row['scenario']} | {row['queries']} | {row['response_bytes']:,} |"
        )
    lines.extend(
        [
            "",
            "## Browser Workflows",
            "",
            "Only schema-v2 requestAnimationFrame readiness measurements are included. Schema-v1 results "
            "are excluded; assertion retry backoff can inflate their timings. "
            "These measure action-to-validated-DOM readiness and include automation overhead, not exact paint. "
            "Hard navigations use fresh browser contexts with a preflight-warmed backend; later actions are warm.",
            "",
            "| Workflow | Samples | Median ms | Range ms | API request counts | Max API errors |",
            "| --- | ---: | ---: | ---: | --- | ---: |",
        ]
    )
    for name, rows in sorted(browser.items()):
        durations = [r["duration_ms"] for r in rows]
        counts = ", ".join(str(n) for n in sorted({r["requests"] for r in rows}))
        lines.append(
            f"| {name} | {len(rows)} | {median(durations):.2f} | {spread(durations)} | "
            f"{counts} | {max(r['errors'] for r in rows)} |"
        )
    lines.extend(
        [
            "",
            "## Lighthouse",
            "",
            "Warm authenticated desktop loads without throttling or storage reset. Supplementary diagnostics: "
            "LCP does not establish product readiness, and TBT is not INP.",
            "",
            "| Metric | Runs | Median | Range |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for name, values in sorted(lighthouse.items()):
        lines.append(
            f"| {name} | {len(values)} | {median(values):.3f} | {spread(values, 3)} |"
        )
    resource_groups = defaultdict(list)
    for run in resource_runs(folder):
        for snapshot in run["samples"]:
            for container in snapshot.get("containers", []):
                resource_groups[container["Name"]].append(container)
    lines.extend(
        [
            "",
            "## Sampled Service Resources",
            "",
            "Sampled peaks across all API runs, not continuous maxima or causal proof. "
            "Docker CPU can exceed 100% when multiple cores are used.",
            "",
            "| Service | Samples | Highest sampled CPU | Highest sampled memory % |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for name, rows in sorted(resource_groups.items()):
        cpu = max(float(r["CPUPerc"].rstrip("%")) for r in rows)
        memory = max(float(r["MemPerc"].rstrip("%")) for r in rows)
        lines.append(f"| {name} | {len(rows)} | {cpu:.2f}% | {memory:.2f}% |")
    lines.extend(
        [
            "",
            "## Improvement Priorities",
            "",
            "1. Remove catalogue detail-request hydration; the list already supplies displayed fields.",
            "2. Join catalogue categories to eliminate one query per product.",
            "3. Batch editor inventory/prices to eliminate two extra queries per variant.",
            "4. Include image_url in the editor response and remove its extra detail request.",
            "5. Re-measure before deciding whether search indexes or Redis have justified benefit.",
            "",
            "## Evidence and Limitations",
            "",
            "- Run metadata preserves commit, exact script contexts, options, timestamps and exit status in manifest.json (or adjacent working-run manifests).",
            "- This measures development configuration, not production capacity or field Core Web Vitals.",
            "- Search includes the 300ms debounce; do not attribute all workflow time to backend latency.",
            "- Small browser samples, where present, do not support strong browser p95/p99 claims.",
            "- Fixed-user load plus think time does not establish a fixed-arrival-rate capacity limit.",
            "- Adjustment benchmarks require the feature and isolated fixtures first.",
            "- Preserve serving mode, data, API scripts, readiness method and telemetry in optimized comparisons.",
            f"- Included API runs: {len(artifacts)}; successful: {sum(row['exit_code'] == 0 for row in artifacts)}. Failed/empty result files: {len(failed)}.",
        ]
    )
    if failed:
        lines.append("- Failed files: " + ", ".join(failed))
    lines.append("")
    # API-only datasets do not need empty browser/audit tables.
    if not browser:
        start = lines.index("## Browser Workflows")
        end = lines.index("## Lighthouse")
        del lines[start:end]
    if not lighthouse:
        start = lines.index("## Lighthouse")
        end = lines.index("## Sampled Service Resources")
        del lines[start:end]
    output = args.output or folder / "report.md"
    output.write_text("\n".join(lines))
    print(f"Summarized {len(artifacts)} API runs to {output}")


if __name__ == "__main__":
    main()
