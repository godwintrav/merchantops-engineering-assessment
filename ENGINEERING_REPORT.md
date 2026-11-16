# Engineering Report

**Status — November 16, 2026:** baseline investigation and catalogue request consolidation are complete. Backend query optimizations, inventory adjustments, and the final optimized benchmark matrices remain pending. This report records verified results as implementation progresses.

## Findings and Priorities

Investigation covered catalogue browsing, search, pagination, ordinary/complex product editors, and existing activity history. Source inspection, SQL query capture, browser workflows, and API load tests identified four priorities:

1. **Catalogue request waterfall:** the frontend fetched a list, then sequentially fetched every product's details before rendering. A full page required 26 API requests despite the list already containing all displayed fields.
2. **Catalogue category N+1:** serialization accessed categories without eager loading, producing 28 diagnostic SQL queries for 25 products.
3. **Editor query amplification:** inventory and pricing were queried separately for each variant. Query count grew as `4 + 2 × variants`: 8, 54, and 104 queries for 2, 25, and 50 variants.
4. **Redundant editor request:** the frontend fetched product details alongside editor data to obtain `image_url`.

The complex editors showed the strongest load-related degradation. The 50-variant editor's throughput stayed near 52–55 requests/sec across 25/50/100 virtual users while p95 latency increased substantially. Direct query/request reductions take priority over introducing caching. Search and pagination were lower priorities at the measured dataset size.

## Performance Evidence

### Method

The baseline contains **90 k6 runs and 349,602 measured requests**, with zero HTTP/content-validation failures: three repetitions per scenario/load combination. Core APIs were tested at 1/5/10/25 VUs, followed by 50/100-VU stress tests. Secondary search, pagination, and activity cases ran at one VU.

Each API run used 15 seconds of warm-up, a 6-second drain gap, 60 seconds of measurement, and 200 ms think time. Authentication/preflight occurred outside measured endpoint metrics. Cases ran sequentially against fixed fixtures: 2,500 merchant products, 5,071 variants, and one activity record. Fixture/query profiles were checked afterward; temporary accounts were removed.

Playwright recorded nine samples per workflow using action-to-validated-DOM readiness and API request counts. Three Lighthouse audits supplied warm initial-load diagnostics. SQL capture and ORM-generated EXPLAIN plans were collected separately from timing runs. Percentiles below are ranges of individual-run p95s, not pooled or averaged percentiles.

### Baseline

| API | Diagnostic SQL queries | p95 at 25 VUs | p95 at 100 VUs |
| --- | ---: | ---: | ---: |
| Catalogue, 25 products | 28 | 77.61–88.01 ms | 470.05–474.17 ms |
| Editor, 2 variants | 8 | 23.92–25.00 ms | 99.90–104.98 ms |
| Editor, 25 variants | 54 | 101.33–134.47 ms | 1015.04–1026.90 ms |
| Editor, 50 variants | 104 | 348.76–380.09 ms | 1932.24–1965.33 ms |

Baseline browser medians were 166.25 ms for catalogue readiness and 204.16 ms for the next page, each requiring 26 API requests. Selective search took 348.28 ms, including the existing 300 ms debounce. Lighthouse median LCP was 64.47 ms, occurring before catalogue readiness; LCP alone would miss the workflow delay.

### Verified Change So Far

| Catalogue workflow | Baseline API requests | After hydration removal |
| --- | ---: | ---: |
| Open a full page | 26 | 1 |
| Load the next page | 26 | 1 |
| Selective search, one result | 2 | 1 |

The after counts were verified in nine authenticated workflow observations and automated regression checks. These were implementation checks, not the final optimized timing matrix. **Comparable after-change latency/throughput results remain pending**; no timing improvement percentages are claimed yet.

Reproduction commands are in [benchmarks/README.md](benchmarks/README.md). See [baseline findings](benchmarks/results/comparison.md), [stress comparisons](benchmarks/results/stress-comparison.md), and consolidated evidence under [baseline-full](benchmarks/results/baseline-full/manifest.json) and [baseline-stress](benchmarks/results/baseline-stress/manifest.json). Manifests preserve environment, commits, exact script contexts, run options, timestamps, and exit codes. Final optimized runs will use separate labels and the same consolidated format, with matching fixtures and measurement conditions.

## Implementation

**Completed:** [CatalogueView.vue](frontend/src/views/CatalogueView.vue) now renders `products.list()` directly. The per-product detail loop and intermediate hydration array were removed. The existing request cancellation, loading/error handling, search debounce, and pagination flow remain in place through `useResource()` and the existing route watchers.

**Next:** eager-load catalogue categories; batch editor inventory/prices; include `image_url` in the editor response and remove its extra request. Add bounded-query/editor request checks, then repeat the comparable benchmark matrices. Inventory-adjustment implementation remains pending.

## Correctness

[Catalogue browser tests](benchmarks/tests/catalogue.spec.mjs) verify displayed names, SKUs, categories, statuses, images, links, response ordering, pagination, search, empty/loading states, and error/retry behavior while enforcing request counts. The main regression test failed against the original hydration implementation and passed after removal. Both tests and the frontend production build pass. Authenticated checks against the real backend confirmed one request for all nine observed catalogue workflows; their temporary account was removed.

The existing 46 backend tests and Django checks passed during baseline setup, covering existing constraints, authentication, merchant access, product updates, and activity. They are not evidence that the new adjustment guarantees have been implemented.

**Inventory adjustment verification is pending:** tests must establish strict nonzero integer/reason validation, reservation boundaries, independent-connection MySQL concurrency safety, atomic stock/audit rollback, accurate operator/variant/before-and-after audit details, merchant isolation, CSRF protection, and usable UI feedback. The existing stock constraint is a safeguard, not a substitute for those transaction and concurrency tests.

## Trade-offs and Remaining Work

- Measurements use the supplied Django runserver/Vite development environment on one host. They support local before/after comparisons, not production capacity claims. VUs share one authenticated merchant-member session per run and target hot fixtures; closed-user load with think time does not establish fixed-arrival-rate capacity.
- Browser readiness includes automation overhead and is not exact paint timing. Small browser samples support medians/ranges; local Lighthouse diagnostics are not field Core Web Vitals. Search debounce is included explicitly.
- One activity record cannot establish history-scale performance. Larger isolated datasets are needed before prioritizing activity, substring-search, or deep-pagination indexes. EXPLAIN estimates are not actual execution measurements.
- Redis remains conditional on measured need after direct fixes. Any adoption must address merchant scoping, authorization, invalidation, freshness, and outage behavior; adjustment validation must remain authoritative in MySQL.
- Inventory functionality, failure/concurrency verification, and final comparable optimized measurements are required before submission. The report will be revised around the final implementation and results.
