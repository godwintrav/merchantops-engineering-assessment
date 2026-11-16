# 50- and 100-User Stress Comparison

Recorded November 15, 2026: **24 runs, 230,446 measured requests, zero HTTP/content failures, and zero interrupted iterations**. Each of the eight case/load combinations has three repetitions. Business fixtures and query profiles were unchanged afterward; the temporary account was removed.

## Latency

Ranges below are individual-run p95 values in milliseconds, not pooled percentiles.

| Endpoint | 25 VUs | 50 VUs | 100 VUs |
| --- | ---: | ---: | ---: |
| Catalogue | 77.61–88.01 | 151.76–173.74 | 470.05–474.17 |
| Editor: 2 variants | 23.92–25.00 | 25.92–28.80 | 99.90–104.98 |
| Editor: 25 variants | 101.33–134.47 | 397.53–404.53 | 1015.04–1026.90 |
| Editor: 50 variants | 348.76–380.09 | 829.39–837.74 | 1932.24–1965.33 |

## Throughput

Median of per-run measured-window request rates. Includes the 200ms think time; not maximum capacity.

| Endpoint | 25 VUs, req/s | 50 VUs, req/s | 100 VUs, req/s |
| --- | ---: | ---: | ---: |
| Catalogue | 106.56 | 172.46 | 173.25 |
| Editor: 2 variants | 117.73 | 235.70 | 394.44 |
| Editor: 25 variants | 95.28 | 98.70 | 95.14 |
| Editor: 50 variants | 54.76 | 54.40 | 52.34 |

## Interpretation

- The catalogue is near 173 req/s at both 50 and 100 VUs, while p95 increases from 152–174ms to 470–474ms.
- The 25-variant editor remains near 95–99 req/s as p95 rises from 398–405ms at 50 VUs to 1.015–1.027 seconds at 100 VUs.
- The 50-variant editor remains near 52–55 req/s across 25/50/100 VUs. Its p95 rises from 349–380ms to 829–838ms to 1.932–1.965 seconds.
- The ordinary editor still gains throughput at 100 VUs, although its tail latency increases. Larger responses therefore reach a throughput plateau earlier under this workload.
- These patterns suggest saturation and increased waiting under the tested configuration. They do not isolate an internal bottleneck by themselves. The separately measured query counts (8/54/104 for the editor) and source loops provide direct evidence of avoidable query amplification.
- Prioritize batching editor inventory/prices, joining catalogue categories, and removing redundant frontend requests. Re-run the same matrix after those changes before deciding whether Redis is warranted.

## Conditions and Evidence

Same application and primary API measurement scripts as the completed baseline, with the supplied Django runserver/Vite configuration and existing fixtures. Fixed-user closed workload: 15s warm-up, 6s drain gap, 60s measured interval, 200ms think time, sequential runs. VUs share one authenticated merchant-member session per run and target hot fixture data. This is a local development stress comparison, not a production capacity claim.

No latency SLO was enforced: passing here means valid measured responses and completed tests, not that two-second latency is acceptable. No write/adjustment contention was tested.

See [per-run stress evidence](baseline-stress/api-runs.json), [run metadata and environment](baseline-stress/manifest.json), [resource samples](baseline-stress/resources.json), and [original baseline findings](comparison.md). The stress manifest references the identical shared fixture profile by path and hash.
