# Performance Comparison

Matched evidence: baseline-full/baseline-stress versus optimized-full/optimized-stress.
Each revision has 90 API runs: 349,602 baseline and 528,199 optimized measured requests. Maximum per-run invalid-response rates: 0.00% baseline, 0.00% optimized. HTTP failure rates: 0.00% baseline, 0.00% optimized.

## API Latency and Throughput

p95 columns are ranges of three individual-run percentiles in milliseconds, not pooled or averaged p95s. Throughput columns are medians of the three measured-window rates, including 200ms think time. Latency includes unsuccessful responses if present; interpret it alongside failure rates.

| Scenario | VUs | Before p95 ms | After p95 ms | Before req/s | After req/s | After max invalid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| catalogue_page_1 | 1 | 19.74–19.86 | 9.96–11.06 | 4.56 | 4.74 | 0.00% |
| catalogue_page_1 | 5 | 46.29–47.85 | 21.26–22.38 | 20.63 | 23.13 | 0.00% |
| catalogue_page_1 | 10 | 67.19–69.58 | 29.22–30.78 | 41.81 | 45.76 | 0.00% |
| catalogue_page_1 | 25 | 77.61–88.01 | 21.14–24.13 | 106.56 | 118.81 | 0.00% |
| catalogue_page_1 | 50 | 151.76–173.74 | 17.17–21.60 | 172.46 | 241.00 | 0.00% |
| catalogue_page_1 | 100 | 470.05–474.17 | 133.68–180.41 | 173.25 | 334.89 | 0.00% |
| editor_2_variants | 1 | 12.91–13.40 | 11.33–11.70 | 4.69 | 4.73 | 0.00% |
| editor_2_variants | 5 | 25.81–26.74 | 22.66–22.88 | 22.52 | 22.54 | 0.00% |
| editor_2_variants | 10 | 32.09–34.91 | 34.05–34.44 | 45.51 | 45.02 | 0.00% |
| editor_2_variants | 25 | 23.92–25.00 | 20.95–25.27 | 117.73 | 118.79 | 0.00% |
| editor_2_variants | 50 | 25.92–28.80 | 24.01–25.43 | 235.70 | 237.37 | 0.00% |
| editor_2_variants | 100 | 99.90–104.98 | 113.51–116.88 | 394.44 | 354.45 | 0.00% |
| editor_25_variants | 1 | 28.38–28.88 | 12.46–12.88 | 4.40 | 4.70 | 0.00% |
| editor_25_variants | 5 | 72.65–72.87 | 26.53–26.90 | 19.04 | 22.40 | 0.00% |
| editor_25_variants | 10 | 80.34–89.96 | 29.91–36.90 | 40.73 | 45.23 | 0.00% |
| editor_25_variants | 25 | 101.33–134.47 | 21.08–24.66 | 95.28 | 118.95 | 0.00% |
| editor_25_variants | 50 | 397.53–404.53 | 22.44–25.23 | 98.70 | 237.96 | 0.00% |
| editor_25_variants | 100 | 1015.04–1026.90 | 188.72–192.07 | 95.14 | 278.32 | 0.00% |
| editor_50_variants | 1 | 41.39–42.49 | 14.26–14.70 | 4.17 | 4.66 | 0.00% |
| editor_50_variants | 5 | 109.14–110.13 | 31.86–32.46 | 16.90 | 22.42 | 0.00% |
| editor_50_variants | 10 | 155.55–164.13 | 31.33–33.04 | 34.68 | 45.94 | 0.00% |
| editor_50_variants | 25 | 348.76–380.09 | 25.83–27.83 | 54.76 | 117.32 | 0.00% |
| editor_50_variants | 50 | 829.39–837.74 | 21.26–22.13 | 54.40 | 238.10 | 0.00% |
| editor_50_variants | 100 | 1932.24–1965.33 | 282.33–283.05 | 52.34 | 226.04 | 0.00% |
| activity_page_1 | 1 | 9.82–10.02 | 11.16–11.27 | 4.75 | 4.70 | 0.00% |
| catalogue_page_100 | 1 | 21.13–21.98 | 16.73–17.09 | 4.54 | 4.56 | 0.00% |
| catalogue_page_50 | 1 | 21.15–21.77 | 15.44–15.87 | 4.54 | 4.59 | 0.00% |
| search_common | 1 | 21.06–21.60 | 13.68–13.91 | 4.53 | 4.63 | 0.00% |
| search_none | 1 | 10.52–10.87 | 12.26–12.53 | 4.74 | 4.66 | 0.00% |
| search_selective | 1 | 12.15–13.32 | 13.09–13.22 | 4.71 | 4.65 | 0.00% |

## Diagnostic SQL Queries

Forced-authenticated captures exclude session/authentication queries.

| Scenario | Before | After |
| --- | ---: | ---: |
| catalogue_page_1 | 28 | 3 |
| editor_2_variants | 8 | 5 |
| editor_25_variants | 54 | 5 |
| editor_50_variants | 104 | 5 |

## Browser Workflows

Nine samples per workflow per revision. Times are action-to-validated-DOM readiness, including automation overhead, not exact paint. Negative percentage changes mean a lower observed median; positive values mean a higher median. All workflows are shown, including those without a timing improvement.

| Workflow | Before median ms | After median ms | Median change | Before API calls | After API calls |
| --- | ---: | ---: | ---: | --- | --- |
| catalogue_hard_navigation | 166.25 | 66.09 | -60.25% | 26 | 1 |
| catalogue_next_page | 204.16 | 81.66 | -60.00% | 26 | 1 |
| catalogue_search | 348.28 | 332.23 | -4.61% | 2 | 1 |
| editor_25_variants | 65.06 | 63.59 | -2.25% | 2 | 1 |
| editor_2_variants | 66.36 | 76.43 | +15.17% | 2 | 1 |
| editor_50_variants | 81.93 | 63.46 | -22.54% | 2 | 1 |

## Lighthouse Diagnostics

Three warm, unthrottled desktop audits per revision. These initial-load metrics can precede catalogue readiness and are not field Core Web Vitals.

| Metric | Before median | After median | Unit |
| --- | ---: | ---: | --- |
| largest-contentful-paint | 64.47 | 77.67 | millisecond |
| cumulative-layout-shift | 0.00 | 0.00 | unitless |
| total-blocking-time | 0.00 | 0.00 | millisecond |
| first-contentful-paint | 64.47 | 77.67 | millisecond |

## Method and Limits

- Same primary API/browser/Lighthouse scripts, seeded fixture IDs/counts, 15s warm-up, 6s drain gap, 60s measurement, 200ms think time, sequential case ordering, and Docker resource sampling.
- Same recorded Python/Django/MySQL/debug settings, host, Docker resource limits and configured Django runserver/Vite serving mode. Exact frontend Node patch version was not recorded in the original baseline; the optimized manifest records the current version.
- These are local development comparisons, not production capacity, fixed-arrival-rate limits, or field Core Web Vitals.
- VUs share one merchant-member session per run and target hot fixtures. Fast routes can approach the load generator's think-time ceiling; reported throughput is not maximum server capacity.
- Search includes its existing 300ms debounce. Browser samples and automation overhead limit interpretation of small timing differences; request counts and SQL budgets are separate deterministic checks.
- Optimized stress combines original 50-VU observations with the subsequent 100-VU rerun. Original per-run provenance is retained; prior host/socket/cache state was not identical. The rerun supersedes the earlier 100-VU execution and does not demonstrate a connection-failure fix.
- Editor responses now include image_url. Underlying business fixtures are unchanged; the response field is additive.
- Activity history has one record: smoke coverage only. Inventory-adjustment write contention is not tested here.
- Resources, browser/Lighthouse payloads and exact per-run provenance remain in the consolidated evidence. Sampled resource peaks are not continuous maxima or normalized cost per request.

## Evidence

- [baseline-full API runs](baseline-full/api-runs.json), [metadata](baseline-full/manifest.json), [resources](baseline-full/resources.json).
- [baseline-stress API runs](baseline-stress/api-runs.json), [metadata](baseline-stress/manifest.json), [resources](baseline-stress/resources.json).
- [optimized-full API runs](optimized-full/api-runs.json), [metadata](optimized-full/manifest.json), [resources](optimized-full/resources.json).
- [optimized-stress API runs](optimized-stress/api-runs.json), [metadata](optimized-stress/manifest.json), [resources](optimized-stress/resources.json).

Use the [benchmark README](../README.md) for reproduction, report generation and consolidation. The source of every table is retained per-run data; successful transient logs and duplicate working files are pruned.
