# MerchantOps Benchmarks

Read [before/after findings](results/comparison.md) and [50/100-user findings](results/stress-comparison.md) first. Each revision retains 90 API runs, nine samples per browser workflow, three Lighthouse audits, and every resource sample. Optimized datasets use the same layout as their baseline counterparts.

## Retained results

```text
results/
  comparison.md
  stress-comparison.md
  baseline-full/
    manifest.json
    profile.json
    query-plans.json
    api-runs.json
    browser-runs.json
    lighthouse-runs.json
    resources.json
  baseline-stress/
    manifest.json
    api-runs.json
    resources.json
  optimized-full/     # same seven-file layout as baseline-full
  optimized-stress/   # same three-file layout as baseline-stress
```

- **manifest.json:** shared environment, matrix completion/cleanup, per-run options/timestamps/exit codes, and original result hashes. Each run references a pooled context containing its exact original commit, working-tree state, and script fingerprints. Distinct contexts are preserved rather than overwritten with the latest version.
- **api-runs.json:** measured request counts, min/median/p95/p99/max latency, throughput/window, HTTP/content failure rates, checks, and thresholds. Setup/warm-up and duplicate native metrics are omitted. Durations are milliseconds.
- **browser-runs.json / lighthouse-runs.json:** original measurement payloads grouped by batch ID. Repetition numbers are local to each browser batch; retain the batch ID when comparing samples.
- **resources.json:** all Docker samples grouped by API run ID, including timestamps and service CPU/memory/I/O data. Samples cover warm-up and measured phases, not continuous maxima or load-generator CPU.
- **profile.json / query-plans.json:** fixtures, diagnostic query counts, and ORM-generated optimizer estimates. Stress references the identical full-matrix profile by relative path and SHA-256 in its manifest.

Exploratory runs, successful console logs, checkpoints, duplicate summaries/manifests, and private Lighthouse dumps have been removed. Completed datasets are sealed: use a new label for future measurements. Measurements and historical script fingerprints are immutable; reporting/packaging helpers can evolve separately.

Generate detailed tables from either working files or consolidated evidence without adding files to the retained dataset:

```bash
python3 benchmarks/summarize.py --label baseline-full --output /tmp/merchantops-baseline.md
python3 benchmarks/summarize.py --label baseline-stress --include-threshold-failures --output /tmp/merchantops-stress.md
```

`optimized-stress/` combines the original 50-VU observations with the later complete 100-VU rerun. Its manifest preserves both source executions and the original per-run provenance. The 100-VU rerun supersedes the earlier execution; it is not evidence that an intermittent connection issue was fixed.

## Prepare a new run

Run from the repository root. Keep Compose services running with the catalogue and complex fixtures from setup.sh. Use an active merchant-member account. Host tools: Python 3, Node 22.19+, and Chromium; k6 can run through Docker. With nvm installed, run `nvm install 22` once if needed, then `nvm use 22` in each new terminal before npm/npx commands. An older active Node version can cause an `Unexpected token ?` error.

```bash
cd benchmarks
nvm use 22
npm ci
export PLAYWRIGHT_BROWSERS_PATH=/tmp/merchantops-playwright
npx playwright install chromium
cd ..
export BENCH_USERNAME=demo_operator
```

For individual API/browser/Lighthouse commands, enter credentials locally (zsh):

```bash
read -rs 'BENCH_PASSWORD?Local benchmark password: '
export BENCH_PASSWORD
```

Never commit credentials, cookies, or browser session state. Full matrices can instead use --temporary-user, creating an active nonstaff merchant member with an in-memory password and removing it on completion or handled interruption. This does not change inventory/audit fixtures.

Set BENCH_ENVIRONMENT_NOTES to record serving commands, Docker limits, hardware, fixture seed if known, cache conditions, and tool versions. Choose a fresh label such as candidate:

```bash
python3 benchmarks/run.py profile --label candidate
```

This discovers merchant-local IDs and ordinary/25/50-variant products, and captures query counts through a force-authenticated Django API client. Counts exclude session/authentication SQL and are collected separately from latency tests. It does not seed or reset data. Activity tests only cover existing history; a large-history benchmark needs documented fixtures.

## Catalogue and editor regression checks

With the frontend running, use Node 22.19+ and the installed Chromium binary:

```bash
cd benchmarks
nvm use 22
export PLAYWRIGHT_BROWSERS_PATH=/tmp/merchantops-playwright
npm run test:catalogue
npm run test:editor
npx playwright test  # all 14 tests, including inventory API-helper and workflow checks
```

These Playwright tests mock the product API, so they require no credentials or database fixtures. Catalogue checks verify one list request per load/page/search, displayed fields and ordering, loading/empty states, and error/retry behavior. Editor checks cover one GET for ordinary/complex products, populated/blank image paths, tab navigation, and image-only PATCH updates. Inventory checks also cover POST/CSRF, draft preservation, pending/error handling, activity rendering, same-key retries after response loss/reload, busy responses and unavailable retry storage. These are correctness/request-budget checks, separate from the authenticated timing benchmarks below.

## Individual measurements

```bash
python3 benchmarks/run.py api --label candidate --case catalogue_page_1 --vus 1 --run 01 --k6-docker
python3 benchmarks/run.py browser --label candidate --run 01
python3 benchmarks/run.py lighthouse --label candidate --run 01
```

API cases are listed in the new profile. Change --case, --vus and --run to collect repetitions. --k6-docker uses pinned grafana/k6:1.0.0 on the backend network at port 8000; host k6 defaults to port 8002. Keep execution mode equivalent before/after. BASE_URL and FRONTEND_URL override targets. Direct k6 invocation must point BENCH_CONFIG at the working profile.

k6 uses 15s warm-up, a 6s drain gap, 60s measured time, and 200ms think time. Custom endpoint metrics exclude setup and warm-up. Throughput spans first measured request start to last completion, including think-time gaps and drain. Native counter rates use the whole test duration and are not substitutes. Content checks validate expected IDs/counts, not just status codes. Default thresholds enforce valid responses and nonempty measurements; no latency SLO is implied.

Playwright records three repetitions per invocation: catalogue hard navigation, pagination, selective search, and 2/25/50-variant editor navigation. It measures Node monotonic action-to-validated-DOM readiness, including automation overhead, not exact paint timing. Animation-frame checks avoid assertion retry-backoff; no arbitrary sleeps or network-idle completion checks are used. Search includes the 300ms debounce. Fresh contexts have a cold browser cache but a preflight-warmed backend; subsequent actions are warm. Default viewport is 1440×900, unthrottled Chromium. The UI merchant must match the profile. Byte totals include Resource Timing entries completed by readiness, excluding the document; cached transfer bytes may be zero.

Lighthouse uses a temporary authenticated profile with storage reset disabled: warm, unthrottled desktop diagnostics. LCP can precede product readiness; TBT is not INP. Full JSON/HTML dumps remain in ignored .private folders until optional inspection/sanitization; compact metric summaries are the retained evidence. Diagnostic traces should run separately from timing runs.

## Sequential matrices

```bash
python3 benchmarks/matrix.py --label candidate --temporary-user
```

This takes about 90 minutes: four core API cases at 1/5/10/25 VUs, three repetitions each; three one-VU runs of each secondary case; nine samples per browser workflow; three Lighthouse audits. Cases run sequentially. Keep application code, fixture data, server settings, and host workload unchanged.

For the higher-load continuation, create a separate working profile and run:

```bash
python3 benchmarks/run.py profile --label candidate-stress
python3 benchmarks/matrix.py --label candidate-stress --loads 50 100 --api-only --allow-threshold-failures --temporary-user
```

This takes about 35 minutes (24 runs). The explicit threshold-failure flag preserves k6 exit-code-99 measurements and continues diagnostics; setup/process errors stop the matrix. Interpret latency alongside failure rates because unsuccessful responses are included when present. VUs share one authenticated session per run and target hot fixture data, not distinct login identities. Flat throughput with rising latency suggests saturation under the tested configuration.

During collection, scripts write expanded per-run files under api/, browser/, and logs/, with manifests/resources beside each run and a matrix checkpoint. Existing files are never silently overwritten. These working files remain available for diagnosis until consolidation.

## Finish and consolidate

Capture query plans after timed runs, then inspect the generated report. Use `--eager` for the optimized category/inventory joins; omit it to reproduce original base-query shapes. These plans cover base queries, while the diagnostic profile counts all endpoint round trips:

```bash
docker compose exec -T backend python - --eager < benchmarks/profiling/query_plans.py > benchmarks/results/candidate/query-plans.json
python3 benchmarks/summarize.py --label candidate --output /tmp/merchantops-candidate.md
python3 benchmarks/compact_results.py --label candidate
```

Consolidation pools exact metadata and verifies retained metrics, browser payloads, resource samples, and reconstructed manifests against their originals. By default it accepts only a completed, cleaned-up, successful matrix. For a completed stress matrix with exit-99 threshold failures, explicitly add `--allow-threshold-failures`; those runs remain included and their console logs are retained in `failure-logs/` when pruning. Process errors and incomplete attempts remain in working format for diagnosis. Check the compacted report, then prune verified inputs:

```bash
python3 benchmarks/compact_results.py --label candidate --prune
```

For an identical stress profile, --profile-ref ../candidate/profile.json deduplicates it; the tool rejects a differing hash. Do not share profiles if optimized query counts or other profile evidence differ. Pruning intentionally removes successful logs, checkpoints, private Lighthouse dumps, and redundant working reports; threshold-failure logs are preserved. Archive those outside the repository beforehand if needed.

Once both optimized matrices are complete, cleaned up and consolidated, regenerate the shared comparison tables:

```bash
python3 benchmarks/compare_results.py
```

This verifies matching fixture/scenario/backend profiles, three API repetitions per case/load, nine browser samples per workflow, and three successful Lighthouse audits before replacing `results/comparison.md` and `results/stress-comparison.md`. Default labels are `baseline-full`, `baseline-stress`, `optimized-full`, and `optimized-stress`; command-line options select other complete datasets. It preserves all workflows, including measured regressions, and reports per-run p95 ranges rather than pooled percentiles.

Optimized manifests also preserve measured application hashes and the uncommitted patch. The original baseline did not record the exact frontend Node patch version; this comparison limitation is explicit in the reports.

## Fair interpretation

Preserve all measured repetitions. Report per-run percentiles/ranges, never an average p95 described as pooled. Small browser samples support medians/ranges, not strong p95/p99 claims. Keep fixtures, timing definitions, browser/server versions, serving mode, telemetry and load settings equivalent. Check manifests and primary workload fingerprints.

The retained runs use Django runserver and Vite dev. They demonstrate local improvements, not production capacity or field Core Web Vitals. A production-serving comparison must measure both revisions under the same configuration. Write-contention tests require the adjustment feature and isolated fixtures; Redis tests remain conditional on measured need after direct optimizations.

References: [k6 metrics](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/), [Playwright](https://playwright.dev/docs/intro), [Lighthouse](https://developer.chrome.com/docs/lighthouse/overview).
