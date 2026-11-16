# High-Load Before/After Comparison

Each cell is a range of three run p95 values in milliseconds. The 25-user control is included alongside 50/100 VUs.

| API | Before 25 | After 25 | Before 50 | After 50 | Before 100 | After 100 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Catalogue | 77.61–88.01 | 21.14–24.13 | 151.76–173.74 | 17.17–21.60 | 470.05–474.17 | 133.68–180.41 |
| Editor: 2 variants | 23.92–25.00 | 20.95–25.27 | 25.92–28.80 | 24.01–25.43 | 99.90–104.98 | 113.51–116.88 |
| Editor: 25 variants | 101.33–134.47 | 21.08–24.66 | 397.53–404.53 | 22.44–25.23 | 1015.04–1026.90 | 188.72–192.07 |
| Editor: 50 variants | 348.76–380.09 | 25.83–27.83 | 829.39–837.74 | 21.26–22.13 | 1932.24–1965.33 | 282.33–283.05 |

## Throughput

Median measured-window requests/sec. Includes think time; not maximum capacity.

| API | Before 25 | After 25 | Before 50 | After 50 | Before 100 | After 100 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Catalogue | 106.56 | 118.81 | 172.46 | 241.00 | 173.25 | 334.89 |
| Editor: 2 variants | 117.73 | 118.79 | 235.70 | 237.37 | 394.44 | 354.45 |
| Editor: 25 variants | 95.28 | 118.95 | 98.70 | 237.96 | 95.14 | 278.32 |
| Editor: 50 variants | 54.76 | 117.32 | 54.40 | 238.10 | 52.34 | 226.04 |

Maximum per-run invalid-response rate: 0.00% baseline, 0.00% optimized. All selected runs passed zero-error thresholds. Passing validation is not a latency SLO. See [full comparison](comparison.md) for all load levels, browser/SQL evidence, raw-data links, methodology and limitations.
