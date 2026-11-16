# Performance Baseline and Comparison

The complete baseline was recorded on November 15, 2026. Optimizations have not been applied yet.

- **66 successful k6 runs**, covering 22 scenario/load combinations with three repetitions each.
- **119,156 measured API requests**, with zero HTTP or content-validation failures.
- **Nine browser samples per workflow**, across six workflows, plus three Lighthouse audits.
- Fixtures and query profiles were unchanged at the end; the temporary benchmark account was removed.

See the [per-run API evidence](baseline-full/api-runs.json), [run metadata and environment](baseline-full/manifest.json), [browser samples](baseline-full/browser-runs.json), [Lighthouse audits](baseline-full/lighthouse-runs.json), [fixture/query profile](baseline-full/profile.json), [query plans](baseline-full/query-plans.json), and [resource samples](baseline-full/resources.json).

## Core API Results

Values below are ranges of individual run p95 values in milliseconds, not pooled percentiles.

| Endpoint | SQL queries | p95 at 1 VU | p95 at 25 VUs | Optimized |
| --- | ---: | ---: | ---: | --- |
| Catalogue, 25 products | 28 | 19.74–19.86 | 77.61–88.01 | Pending |
| Editor, 2 variants | 8 | 12.91–13.40 | 23.92–25.00 | Pending |
| Editor, 25 variants | 54 | 28.38–28.88 | 101.33–134.47 | Pending |
| Editor, 50 variants | 104 | 41.39–42.49 | 348.76–380.09 | Pending |

The full report also includes 5- and 10-user results, throughput, p99 ranges, and sample counts. Latencies are not monotonic at every load; the closed workload, scheduling, and local environment matter. Do not infer a general capacity curve from these points.

## Browser Results

Nine samples per workflow, using animation-frame checks for validated DOM readiness:

| Workflow | Median ms | API requests | Optimized |
| --- | ---: | ---: | --- |
| Open catalogue | 166.25 | 26 | Pending |
| Next catalogue page | 204.16 | 26 | Pending |
| Selective search | 348.28 | 2 | Pending |
| Open ordinary editor | 66.36 | 2 | Pending |
| Open 25-variant editor | 65.06 | 2 | Pending |
| Open 50-variant editor | 81.93 | 2 | Pending |

Search includes the existing 300ms debounce. Initial-load Lighthouse median LCP was 64.47ms, with CLS 0 and TBT 0 under warm, unthrottled desktop conditions. LCP occurs before catalogue readiness and is not the primary business-workflow metric.

## Priorities Supported by the Evidence

1. **Eliminate catalogue request hydration.** The list already provides the displayed fields; remove 25 sequential detail requests per full page.
2. **Join catalogue categories.** The serializer causes one additional category lookup per result. Target constant query count without changing pagination/search semantics.
3. **Batch editor inventory and prices.** Query count follows 4 + 2 × variant count. This is the clearest backend growth problem; the 50-variant editor reaches 349–380ms p95 at 25 users.
4. **Consolidate editor responses.** Include image_url and remove the extra detail request, while preserving existing editor fields and ordering.
5. **Re-measure before adding Redis or indexes.** Current results do not justify using caching to hide these avoidable requests and queries.

## Secondary Findings and Limits

- Middle/last-page p95 is 21.13–21.98ms at one user. Common search is 21.06–21.60ms; selective search is 12.15–13.32ms; no-match search is 10.52–10.87ms.
- EXPLAIN shows a filesort for the last-page base query using the merchant/SKU index, and primary-index scans with substring filters for search. These are optimizer estimates, not measured row counts. Larger datasets may justify further work; they are lower priorities than the confirmed query/request amplification.
- Activity p95 is 9.82–10.02ms, but only one activity record exists. This is smoke evidence, not history-scale evidence.
- Sampled service peaks: backend CPU 122.02%, MySQL CPU 25.85%; memory peaks 1.43% and 6.93% of the Docker VM allocation respectively. Samples do not establish causality or continuous maxima.
- Tests used the supplied Django runserver/Vite development configuration on one host. These are controlled local comparisons, not production capacity or field Core Web Vitals claims. Keep serving mode, fixtures, workload, readiness method and telemetry the same for optimized comparisons.
- Only completed datasets are retained. Exploratory runs and duplicate working files were removed after verifying consolidation; all measured repetitions and distinct metadata contexts remain.
- Adjustment/write contention and Redis benchmarks remain deferred until those features exist. A large-history activity fixture remains follow-up work.

## Reproduce and Compare

Follow [the benchmark README](../README.md) for setup and exact commands. The sequential matrix is run with benchmarks/matrix.py; benchmarks/summarize.py regenerates the detailed report without averaging run percentiles. Record future results under a new label and preserve this baseline. No before/after improvement percentages are claimed until optimized runs exist.

## Higher-Load Continuation

An additional 24 runs at 50 and 100 VUs completed with 230,446 measured requests and no failures or interrupted iterations. The 50-variant editor reached 1.932–1.965 seconds p95 at 100 VUs while throughput remained near 52–55 req/s across the higher loads. See the [stress comparison](stress-comparison.md) for the full 25/50/100-user tables and limitations.
