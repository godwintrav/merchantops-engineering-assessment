# MerchantOps Benchmarks

Read [baseline findings](results/comparison.md) and [50/100-user findings](results/stress-comparison.md) first. The retained evidence preserves all 90 API runs, nine samples per browser workflow, three Lighthouse audits, and every resource sample.

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
```

- **manifest.json:** shared environment, matrix completion/cleanup, per-run options/timestamps/exit codes, and original result hashes. Each run references a pooled context containing its exact original commit, working-tree state, and script fingerprints. Distinct contexts are preserved rather than overwritten with the latest version.
- **api-runs.json:** measured request counts, min/median/p95/p99/max latency, throughput/window, HTTP/content failure rates, checks, and thresholds. Setup/warm-up and duplicate native metrics are omitted. Durations are milliseconds.
- **browser-runs.json / lighthouse-runs.json:** original measurement payloads grouped by batch ID. Repetition numbers are local to each browser batch; retain the batch ID when comparing samples.
- **resources.json:** all Docker samples grouped by API run ID, including timestamps and service CPU/memory/I/O data. Samples cover warm-up and measured phases, not continuous maxima or load-generator CPU.
- **profile.json / query-plans.json:** fixtures, diagnostic query counts, and ORM-generated optimizer estimates. Stress references the identical baseline profile by relative path and SHA-256 in its manifest.

Exploratory runs, successful console logs, checkpoints, duplicate summaries/manifests, and private Lighthouse dumps have been removed. Completed datasets are sealed: use a new label for future measurements. Measurements and historical script fingerprints are immutable; reporting/packaging helpers can evolve separately.

Generate detailed tables from either working files or consolidated evidence without adding files to the retained dataset:

```bash
python3 benchmarks/summarize.py --label baseline-full --output /tmp/merchantops-baseline.md
python3 benchmarks/summarize.py --label baseline-stress --include-threshold-failures --output /tmp/merchantops-stress.md
```

## Prepare a new run

Run from the repository root. Keep Compose services running with the catalogue and complex fixtures from setup.sh. Use an active merchant-member account. Host tools: Python 3, Node 22.19+, and Chromium; k6 can run through Docker.

```bash
cd benchmarks
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

## Catalogue regression checks

With the frontend running, use Node 22.19+ and the installed Chromium binary:

```bash
cd benchmarks
npm run test:catalogue
```

These Playwright tests mock the product API, so they require no credentials or database fixtures. They verify one list request per catalogue load/page/search, displayed fields and response ordering, loading and empty states, and error/retry behavior. They are correctness/request-budget checks, separate from the authenticated timing benchmarks below.

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

Capture query plans after timed runs, then inspect the generated report:

```bash
docker compose exec -T backend python - < benchmarks/profiling/query_plans.py > benchmarks/results/candidate/query-plans.json
python3 benchmarks/summarize.py --label candidate --output /tmp/merchantops-candidate.md
python3 benchmarks/compact_results.py --label candidate
```

Consolidation pools exact metadata and verifies retained metrics, browser payloads, resource samples, and reconstructed manifests against their originals. It accepts a completed, cleaned-up, successful matrix. Failed/incomplete attempts remain in working format for diagnosis. Check the compacted report, then prune verified inputs:

```bash
python3 benchmarks/compact_results.py --label candidate --prune
```

For an identical stress profile, --profile-ref ../candidate/profile.json deduplicates it; the tool rejects a differing hash. Do not share profiles if optimized query counts or other profile evidence differ. Pruning intentionally removes successful logs, checkpoints, private Lighthouse dumps, and redundant working reports. Archive those outside the repository beforehand if needed.

## Fair interpretation

Preserve all measured repetitions. Report per-run percentiles/ranges, never an average p95 described as pooled. Small browser samples support medians/ranges, not strong p95/p99 claims. Keep fixtures, timing definitions, browser/server versions, serving mode, telemetry and load settings equivalent. Check manifests and primary workload fingerprints.

The retained runs use Django runserver and Vite dev. They demonstrate local improvements, not production capacity or field Core Web Vitals. A production-serving comparison must measure both revisions under the same configuration. Write-contention tests require the adjustment feature and isolated fixtures; Redis tests remain conditional on measured need after direct optimizations.

References: [k6 metrics](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/), [Playwright](https://playwright.dev/docs/intro), [Lighthouse](https://developer.chrome.com/docs/lighthouse/overview).
