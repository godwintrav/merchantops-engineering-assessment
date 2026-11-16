# Engineering Report

The read optimizations, inventory workflow and reliability improvements are implemented. Local verification passes **87 MySQL backend tests and 14 Playwright tests**. Setup and verification were also exercised in a separate Compose project with fresh volumes; publishing the final commits and submitting the repository URL remain outstanding.

## Findings and Priorities

Four avoidable costs dominated the investigation:

1. Catalogue rendering awaited a list and 25 sequential detail requests, although the list already supplied the displayed fields.
2. Category serialization performed a lookup per product: 28 diagnostic queries for a full page.
3. Editor inventory/pricing queries grew with variant count: 8/54/104 queries for 2/25/50 variants.
4. The editor requested product details separately to obtain its image.

Removing redundant requests and batching relationship access took priority over caching. The baseline 50-variant editor plateaued near 52–55 requests/sec at 25–100 users while latency rose. Search/index changes and Redis lacked sufficient evidence to justify their complexity before these direct fixes.

## Performance Evidence

**Method:** three repetitions per API scenario/load; core cases at 1/5/10/25/50/100 virtual users, secondary search/pagination/activity cases at one user. Each run used 15s warm-up, a 6s drain gap, 60s measurement and 200ms think time. Authentication/preflight and SQL profiling were outside measured endpoint metrics. Validations checked response content, not only HTTP status.

The original read-optimization comparison retains 90 selected API runs per revision: **349,602 baseline requests and 528,199 optimized requests**, with zero measured HTTP/content failures in the selected evidence. Fixture counts/IDs match: 2,500 merchant products, 5,071 variants and one activity record. Manifests retain exact timestamps, execution contexts, script hashes and source snapshots, including the optimized application's uncommitted patch. The baseline reference is `0d1602b`; the measured optimized source is `6fb8ac4` plus its recorded patch. Read timings were captured before the inventory UI/reliability extension; they are not new load measurements of that extension.

The retained environment uses Django runserver (`DEBUG=True`), Vite dev and MySQL 8.4.13 on an Apple M5 Pro host, with Docker allocated 18 CPUs/~7.75 GiB. Recorded backend versions and primary workload fingerprints match. Exact baseline frontend Node patch was not recorded; prior host/socket/cache state was not fully controlled. Stress manifests identify the source executions of the retained 50/100-user observations.

| API | SQL before → after | 100-VU p95 before → after (ms) | Median req/s before → after |
| --- | ---: | ---: | ---: |
| Catalogue, 25 products | 28 → 3 | 470.05–474.17 → 133.68–180.41 | 173.25 → 334.89 |
| Editor, 2 variants | 8 → 5 | 99.90–104.98 → 113.51–116.88 | 394.44 → 354.45 |
| Editor, 25 variants | 54 → 5 | 1015.04–1026.90 → 188.72–192.07 | 95.14 → 278.32 |
| Editor, 50 variants | 104 → 5 | 1932.24–1965.33 → 282.33–283.05 | 52.34 → 226.04 |

p95 entries are ranges of three individual-run percentiles, not averaged/pooled percentiles. Throughput is the median of measured-window rates including think time, not maximum capacity. At 50 VUs, catalogue p95 decreased from 151.76–173.74 to 17.17–21.60 ms; the 50-variant editor decreased from 829.39–837.74 to 21.26–22.13 ms. The ordinary editor at 100 VUs was slower; the results do not support claiming every path improved.

Playwright timing captured nine observations per workflow, measuring action-to-validated-DOM readiness including automation overhead:

| Workflow | Median before → after (ms) | API requests before → after |
| --- | ---: | ---: |
| Catalogue navigation | 166.25 → 66.09 | 26 → 1 |
| Next page | 204.16 → 81.66 | 26 → 1 |
| Selective search | 348.28 → 332.23 | 2 → 1 |
| Editor, 2 variants | 66.36 → 76.43 | 2 → 1 |
| Editor, 25 variants | 65.06 → 63.59 | 2 → 1 |
| Editor, 50 variants | 81.93 → 63.46 | 2 → 1 |

Search includes its 300ms debounce. The ordinary-editor browser median increased 15.17%. Three warm, unthrottled Lighthouse audits also showed LCP/FCP increasing from 64.47 to 77.67 ms, with CLS/TBT remaining zero. These initial-paint diagnostics can precede catalogue readiness and are not field Core Web Vitals.

Reproduce workloads using [benchmark instructions](benchmarks/README.md). Review [all comparisons](benchmarks/results/comparison.md), [high-load tables](benchmarks/results/stress-comparison.md), and manifests for [baseline full](benchmarks/results/baseline-full/manifest.json), [baseline stress](benchmarks/results/baseline-stress/manifest.json), [optimized full](benchmarks/results/optimized-full/manifest.json) and [optimized stress](benchmarks/results/optimized-stress/manifest.json). Consolidation verified metrics, resources, browser payloads and reconstructed provenance against the working files before pruning duplicate artifacts. Baseline evidence remains unchanged.

### Focused Index Study: 50 VUs Only

Experimental indexes on Product `(merchant_id, id)` and AuditLog `(product_id, created_at DESC, id DESC)` were added temporarily for evaluation and then removed from the final implementation. A separate focused study repeated catalogue first/deep pages and activity three times before and after, at **50 VUs only**: 18 runs, 127,326 before/127,189 after requests, with zero HTTP/content failures or interrupted iterations. Fixtures/query budgets were unchanged and temporary accounts were removed.

| API | Before p95 range (ms) | After p95 range (ms) | Median req/s before → after |
| --- | ---: | ---: | ---: |
| Catalogue first page | 13.00–19.18 | 14.23–20.85 | 240.49 → 240.90 |
| Catalogue deep page | 36.58–38.31 | 36.50–39.54 | 226.23 → 225.65 |
| Activity | 11.86–16.30 | 12.82–19.84 | 240.38 → 240.61 |

**No clear end-to-end speedup was demonstrated at this dataset size.** During the experimental after-phase, MySQL selected the product index for the separately inspected pagination COUNT, but retained the previous catalogue data-query paths, including deep-page sorting. Activity selected the new index yet still sorted after the actor join. A pre-index COUNT plan was not captured, so no COUNT speedup is claimed. Activity has only six records; large-history benefits and write-maintenance costs remain unquantified. The indexes were left out because the before/after comparison did not demonstrate a clear query-time improvement, while index storage and write-maintenance costs would remain. They should be reconsidered only with larger representative datasets and repeatable measured benefits.

[Full index evidence](benchmarks/results/index-comparison.md) retains per-run measurements, actual schema/index definitions, query plans and resources independently of the original results. Expanded/consolidated summaries were identical before pruning. All 87 backend and 14 browser regressions passed with the experimental indexes; activity pagination additionally verifies descending-ID ordering across equal timestamps. After removal, all 87 backend tests, Django checks, migration-drift checks and formatting checks passed again. Only the experimental indexes were rolled back; application data and required constraints were preserved.

## Implementation

**Reads:** catalogue rendering consumes the list directly; `select_related("category")` eliminates category lookups. Editors join inventory, prefetch ID-ordered price rules, and include `image_url`, removing the extra detail request. Merchant filtering, ordering, decimal formatting, missing-inventory `null`, cancellation and existing editing behavior remain intact. Populated catalogue pages use three diagnostic queries; nonempty editors use five regardless of tested variant count. Empty searches/editors use two/four. Counts consistently exclude session/authentication SQL.

**Adjustments:** `POST /api/products/{product_id}/variants/{variant_id}/adjustments/?merchant_id=…` accepts a nonzero JSON integer `delta` and a trimmed 1–500-character `reason`. Strings, floats, booleans and unexpected fields are rejected. Delta/result limits are explicit application bounds of ±2,147,483,647 and 0–2,147,483,647 respectively. The session supplies the actor; merchant/product/variant scoping prevents cross-merchant writes. Missing inventory is not implicitly created.

The [inventory service](backend/catalog/services/inventory.py) locks the inventory row inside `transaction.atomic()`, reads quantity/reservations after locking, checks the new quantity, and commits stock plus one `inventory.adjusted` audit together. Audit JSON records variant/operator snapshots, reason, delta and before/after/reserved quantities; the record supplies its timestamp. Stock locking is scoped to the affected inventory rather than an entire product or merchant.

The inventory-tab modal provides an advisory preview, accessible focus handling and pending/error/success feedback. A separate inventory-state map avoids triggering the editor's general-draft reset. Activity renders both inventory adjustments and existing product changes. Pending requests guard duplicate handlers/navigation; uncertain outcomes retain retry identity rather than automatically resending writes.

**Reliability:** migration `0004_inventoryoperation` persists merchant-scoped UUID keys bound to operator, target and normalized payload. A database uniqueness constraint serializes duplicate claims; the key, stock, audit and outcome commit atomically. Identical authorized replays return 200 with the original adjustment and a fresh inventory snapshot; new operations return 201. Conflicting reuse returns 409. MySQL lock waits are bounded to five seconds on the service connection and restored afterward; recognized timeout/deadlock errors return safe 503 `inventory_busy` responses with `Retry-After: 1`. Other database errors are not disguised as stock conflicts.

The UI stores the key/payload in session storage before sending, restores uncertain operations after same-tab reload, and offers manual same-key retry. Confirmed success clears retry details; a new intended operation receives a new key. Unavailable storage prevents sending, and incomplete success responses retain the key until verified.

## Correctness

| Guarantee | Evidence |
| --- | --- |
| Strict amount/reason validation | API tests reject zero, fractions, booleans, numeric strings, missing/unknown fields and invalid reasons. |
| Reservations and quantity limits | Exact reserved boundary succeeds; underflow/overflow is rejected without stock/audit effects. |
| Authorization and CSRF | Anonymous/nonmember/mismatched-target requests fail; real session clients require a valid CSRF token; replays reauthorize. |
| Accurate audit history | Tests compare actor/variant snapshots, reason, delta, timestamp and before/after chains. Activity renders escaped reason text and operator snapshots. |
| Atomic persistence | Injected failures before/after audit insertion and while saving the operation outcome roll back all writes. Independent connections observe neither write before commit and both afterward. |
| Concurrent writes | Real MySQL worker connections preserve both increments, reject unsafe competing decrements/overflow, read fresh reservations after waiting, and allow an unrelated variant to proceed. |
| Safe retries/contention | Concurrent duplicate keys produce one stock/audit/key result; payload/operator conflicts fail. Real lock waits return 503, restore session settings, and allow same-key recovery. |
| Existing behavior | Catalogue/editor query and request budgets, general editing, merchant isolation, constraints, modal guards, dirty drafts and activity rendering remain covered. |

Concurrency tests use `TransactionTestCase`, committed fixtures, distinct MySQL connection IDs, barriers/events and bounded waits; they do not use sleeps as proof of overlap. Mocks inject failures, while stock, locks, transactions and assertions run against MySQL.

All **87 backend tests and 14 browser tests pass**, as do Django checks, migration-drift checks, Python formatting and the frontend production build. Two authenticated isolated-fixture browser checks additionally verified persistence and response-loss recovery: dropping the HTTP response after commit and retrying retained one stock change, one audit and one key. Temporary fixtures were removed.

Run from the repository root with services running:

```bash
docker compose exec backend python manage.py test catalog --keepdb
docker compose exec backend python manage.py check
docker compose exec backend python manage.py makemigrations --check --dry-run
docker compose exec frontend npm run build
cd benchmarks
nvm use 22
npm ci
export PLAYWRIGHT_BROWSERS_PATH=/tmp/merchantops-playwright
npx playwright install chromium
npx playwright test
```

Fresh setup passed in an isolated Compose project with alternate ports and new volumes, including all migrations, fixtures, demo provisioning, the backend/browser suites and build. Running setup again preserved fixture/query profiles and the chosen demo password. An authenticated walkthrough verified one-request catalogue/editor loading, a real correction, one audit, same-key replay and preserved unsaved edits. The existing development database was kept separate. [CI](.github/workflows/verify.yml) configures the same MySQL, build and browser gates; its hosted execution awaits pushing the workflow. [README](README.md) contains setup, API/retry and browser prerequisites; [demo steps](docs/DEMO.md) provide a short review path.

## Trade-offs and Remaining Work

- Local development-server timings and closed-user hot-fixture workloads do not establish production capacity. Production workers/connection lifecycle, realistic arrival rates and multi-user session workloads need separate measurements. The earlier intermittent connection-establishment issue was not established as fixed by a successful selected execution.
- The original activity baseline had one record and the focused index study had six. The experimental indexes were removed; larger histories and read/write measurements are needed before reconsidering them; further substring-search changes need separate evidence. Redis remains conditional and must preserve merchant scoping, freshness and authoritative MySQL adjustment validation.
- API idempotency keys are optional for compatibility; callers omitting them have no duplicate protection. The UI always supplies one. Recovery needs the same key; closing the tab/losing storage requires checking history. Different keys cannot identify the same real-world intent automatically.
- Server keys have no automatic expiry and consume storage. They survive product/operator deletion through stored scalar identity; merchant deletion cascades them. Audit actor deletion nulls its FK, while product deletion cascades activity. This is not a tamper-proof or deletion-proof ledger.
- Request authorization does not instantly revoke an already-running authorized transaction. Lock timeouts bound database lock waits, not every network/request failure. Read batching bounds round trips, while payload size and serialization still grow with related data.
- Final commits, public-fork visibility, hosted CI and repository-URL submission must be confirmed before the assessment deadline. No upstream pull request is required.

### Improvements I Would Add Next

The following improvements are deferred and are not included in the measured gains above:

- **Indexes justified by larger datasets:** the catalogue and activity index candidates were benchmarked at 50 VUs before and after installation. Their timing ranges overlapped and throughput was essentially unchanged, so they were removed and left out of the final schema. Reconsider selected indexes only when larger representative datasets, query plans and repeated benchmarks show a meaningful query-time benefit that justifies storage and write costs. See the [retained index study](benchmarks/results/index-comparison.md).
- **Redis caching for frequently requested read routes:** I would add cache-aside Redis caching to suitable catalogue/product read responses to reduce repeated database work and load. Select routes using request frequency, query cost and measured cache-hit rates. Authorize requests before serving merchant-scoped entries; include relevant search/page parameters in keys. Invalidate affected entries after successful transaction commit, set bounded TTLs, and fall back to MySQL if Redis is unavailable. Stock adjustment validation, row locking, audit creation and idempotency remain authoritative in MySQL. Benchmark cached versus uncached latency, throughput and database load before reporting benefits.
