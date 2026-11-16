# Focused Index Benchmark

Final decision: both experimental indexes were removed after the comparison showed no clear latency gain. The after-index dataset records the temporary experimental schema, not the current submission schema. Reconsider indexes only with larger representative data and repeatable benefits that justify their write/storage costs.

Three repetitions per case, 50 VUs only; nine runs before and nine after. Same workload scripts, fixtures, backend versions, diagnostic SQL counts and serving configuration. Each run uses 15s warm-up, 6s drain gap, 60s measurement and 200ms think time. No other load levels, browser audits or write benchmarks are included.

Measured requests: 127,326 before and 127,189 after.

p95 is a range of three individual-run percentiles in milliseconds; throughput is the median of measured-window rates including think time. No pooled percentile is claimed.

| API | Before p95 ms | After p95 ms | Before req/s | After req/s | Before/after max invalid | SQL before/after |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| catalogue_page_1 | 13.00–19.18 | 14.23–20.85 | 240.49 | 240.90 | 0.00% / 0.00% | 3 / 3 |
| catalogue_page_100 | 36.58–38.31 | 36.50–39.54 | 226.23 | 225.65 | 0.00% / 0.00% | 3 / 3 |
| activity_page_1 | 11.86–16.30 | 12.82–19.84 | 240.38 | 240.61 | 0.00% / 0.00% | 4 / 4 |

## Observed Query Plans

These are optimizer estimates for the actual ORM data queries, captured outside timing runs. They do not establish measured execution durations or show the separate pagination COUNT query.

| API | Before selected keys | After selected keys | Sort before / after |
| --- | --- | --- | --- |
| catalogue_page_1 | PRIMARY | PRIMARY | no / no |
| catalogue_page_100 | PRIMARY, unique_merchant_product_sku | PRIMARY, unique_merchant_product_sku | yes / yes |
| activity_page_1 | product FK | audit_product_time_idx | yes / yes |

The separately captured post-index pagination COUNT selects `product_merchant_id_idx`. A corresponding pre-index COUNT plan was not captured, so this is an after-only observation, not a measured COUNT speedup.

## Scope and Limits

- Product index: `(merchant_id, id)`. Activity index: `(product_id, created_at DESC, id DESC)`.
- Activity contains only 6 existing records for the measured product. Its latency is smoke-scale evidence, not a large-history result.
- Indexes change access paths, not ORM query counts or endpoint behavior. See retained before/after query plans for optimizer choices.
- Timing differences may reflect local variability. Small differences or overlapping ranges do not establish a reliable speedup.
- Django runserver/Vite are development servers. Host/cache state is not fully controlled, and throughput is not maximum production capacity.
- No stock/audit fixtures were seeded or changed. Temporary benchmark users were removed. Historical baseline/optimized datasets remain untouched.
- Additional index storage and maintenance costs are not quantified here. In particular, the audit index adds maintenance on adjustment audit inserts; write-load testing was outside this focused run.
- Deep OFFSET pagination and COUNT work remain even with an ordered index.

## Evidence

- [indexes-before-50vu measurements](indexes-before-50vu/api-runs.json), [provenance](indexes-before-50vu/manifest.json), [query plans](indexes-before-50vu/query-plans.json), [resources](indexes-before-50vu/resources.json).
- [indexes-after-50vu measurements](indexes-after-50vu/api-runs.json), [provenance](indexes-after-50vu/manifest.json), [query plans](indexes-after-50vu/query-plans.json), [resources](indexes-after-50vu/resources.json).

Regenerate with `python3 benchmarks/compare_indexes.py` after both datasets are complete and consolidated.
