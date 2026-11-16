#!/usr/bin/env python3
"""Compare the focused 50-VU index study without rewriting original benchmarks."""

import argparse
from pathlib import Path

from compare_results import dataset, grouped, rate, require, tail, workload_fingerprints
from results_io import load_profile, read

RESULTS = Path(__file__).resolve().parent / "results"
CASES = ("catalogue_page_1", "catalogue_page_100", "activity_page_1")


def plan_summary(folder, case):
    names = {
        "catalogue_page_1": "catalogue_first_page",
        "catalogue_page_100": "catalogue_last_page",
        "activity_page_1": "activity",
    }
    plan = read(folder / "query-plans.json")["plans"][names[case]]
    keys, sorts = set(), []

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "key":
                    keys.add(
                        "product FK"
                        if str(item).startswith("catalog_auditlog_product_id_")
                        else item
                    )
                if key == "using_filesort":
                    sorts.append(item)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(plan)
    return ", ".join(sorted(keys)), "yes" if any(sorts) else "no"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", default="indexes-before-50vu")
    parser.add_argument("--after", default="indexes-after-50vu")
    args = parser.parse_args()
    before_folder, old_rows = dataset(args.before)
    after_folder, new_rows = dataset(args.after)
    before, after = grouped(old_rows), grouped(new_rows)
    expected = {(case, 50) for case in CASES}
    require(
        before.keys() == after.keys() == expected, "Expected three cases at 50 VUs only"
    )
    require(
        workload_fingerprints(before_folder) == workload_fingerprints(after_folder),
        "Primary workloads differ",
    )
    original = load_profile(before_folder)
    require(
        original == load_profile(after_folder),
        "Fixtures, scenarios or query profiles changed",
    )
    queries = {row["scenario"]: row["queries"] for row in original["query_profiles"]}
    activity = next(
        row["count"]
        for row in original["scenarios"]
        if row["name"] == "activity_page_1"
    )
    lines = [
        "# Focused Index Benchmark",
        "",
        "Final decision: both experimental indexes were removed after the comparison showed no clear latency gain. "
        "The after-index dataset records the temporary experimental schema, not the current submission schema. "
        "Reconsider indexes only with larger representative data and repeatable benefits that justify their write/storage costs.",
        "",
        "Three repetitions per case, 50 VUs only; nine runs before and nine after. "
        "Same workload scripts, fixtures, backend versions, diagnostic SQL counts and serving configuration. "
        "Each run uses 15s warm-up, 6s drain gap, 60s measurement and 200ms think time. "
        "No other load levels, browser audits or write benchmarks are included.",
        "",
        f"Measured requests: {sum(r['samples'] for r in old_rows):,} before and "
        f"{sum(r['samples'] for r in new_rows):,} after.",
        "",
        "p95 is a range of three individual-run percentiles in milliseconds; throughput is the "
        "median of measured-window rates including think time. No pooled percentile is claimed.",
        "",
        "| API | Before p95 ms | After p95 ms | Before req/s | After req/s | Before/after max invalid | SQL before/after |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for case in CASES:
        old, new = before[(case, 50)], after[(case, 50)]
        lines.append(
            f"| {case} | {tail(old)} | {tail(new)} | {rate(old)} | {rate(new)} | "
            f"{max(r['invalid_rate'] for r in old):.2%} / {max(r['invalid_rate'] for r in new):.2%} | "
            f"{queries[case]} / {queries[case]} |"
        )
    lines += [
        "",
        "## Observed Query Plans",
        "",
        "These are optimizer estimates for the actual ORM data queries, captured outside timing runs. "
        "They do not establish measured execution durations or show the separate pagination COUNT query.",
        "",
        "| API | Before selected keys | After selected keys | Sort before / after |",
        "| --- | --- | --- | --- |",
    ]
    for case in CASES:
        old_key, old_sort = plan_summary(before_folder, case)
        new_key, new_sort = plan_summary(after_folder, case)
        lines.append(f"| {case} | {old_key} | {new_key} | {old_sort} / {new_sort} |")
    count = read(after_folder / "query-plans.json").get("pagination_count_after_only")
    if count:
        key = count.get("query_block", {}).get("table", {}).get("key", "unknown")
        lines += [
            "",
            f"The separately captured post-index pagination COUNT selects `{key}`. "
            "A corresponding pre-index COUNT plan was not captured, so this is an after-only observation, not a measured COUNT speedup.",
        ]
    lines += [
        "",
        "## Scope and Limits",
        "",
        "- Product index: `(merchant_id, id)`. Activity index: `(product_id, created_at DESC, id DESC)`.",
        f"- Activity contains only {activity} existing records for the measured product. Its latency is smoke-scale evidence, not a large-history result.",
        "- Indexes change access paths, not ORM query counts or endpoint behavior. See retained before/after query plans for optimizer choices.",
        "- Timing differences may reflect local variability. Small differences or overlapping ranges do not establish a reliable speedup.",
        "- Django runserver/Vite are development servers. Host/cache state is not fully controlled, and throughput is not maximum production capacity.",
        "- No stock/audit fixtures were seeded or changed. Temporary benchmark users were removed. Historical baseline/optimized datasets remain untouched.",
        "- Additional index storage and maintenance costs are not quantified here. In particular, the audit index adds maintenance on adjustment audit inserts; write-load testing was outside this focused run.",
        "- Deep OFFSET pagination and COUNT work remain even with an ordered index.",
        "",
        "## Evidence",
        "",
    ]
    for label in (args.before, args.after):
        lines.append(
            f"- [{label} measurements]({label}/api-runs.json), [provenance]({label}/manifest.json), "
            f"[query plans]({label}/query-plans.json), [resources]({label}/resources.json)."
        )
    lines += [
        "",
        "Regenerate with `python3 benchmarks/compare_indexes.py` after both datasets are complete and consolidated.",
        "",
    ]
    (RESULTS / "index-comparison.md").write_text("\n".join(lines))
    print("Generated focused index comparison.")


if __name__ == "__main__":
    main()
