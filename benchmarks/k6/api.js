import http from 'k6/http'
import { check, fail, sleep } from 'k6'
import { Trend, Rate, Counter } from 'k6/metrics'

const config = JSON.parse(open(__ENV.BENCH_CONFIG || '../results/baseline/profile.json'))
const base = (__ENV.BASE_URL || 'http://127.0.0.1:8002').replace(/\/$/, '')
const vus = Number(__ENV.VUS || 1)
const warmupSeconds = Number(__ENV.WARMUP_SECONDS || 15)
const selected = config.scenarios.filter(s => !__ENV.CASE || s.name === __ENV.CASE)
if (!selected.length) throw new Error('CASE does not match a discovered scenario')
const latency = new Trend('endpoint_duration', true)
const invalid = new Rate('endpoint_invalid')
const requests = new Counter('endpoint_requests')
const httpFailed = new Rate('endpoint_http_failed')
const measurementClock = new Trend('measurement_clock_ms')
const thresholds = { endpoint_invalid: ['rate==0'] }
for (const s of selected) {
  // Explicit submetrics make per-endpoint summaries available in exported JSON.
  thresholds[`endpoint_duration{endpoint:${s.name}}`] = ['p(95)>=0']
  thresholds[`endpoint_invalid{endpoint:${s.name}}`] = ['rate==0']
  thresholds[`endpoint_requests{endpoint:${s.name}}`] = ['count>0']
  thresholds[`endpoint_http_failed{endpoint:${s.name}}`] = ['rate==0']
}

export const options = {
  scenarios: {
    warmup: { executor: 'constant-vus', vus, duration: `${warmupSeconds}s`, exec: 'warmup', gracefulStop: '5s' },
    measured: {
      executor: 'constant-vus', vus, duration: __ENV.DURATION || '60s',
      startTime: `${warmupSeconds + 6}s`, exec: 'measured', gracefulStop: '10s',
    },
  },
  thresholds,
  summaryTrendStats: ['count', 'min', 'med', 'p(95)', 'p(99)', 'max'],
}

function url(s) {
  return base + s.path + (s.path.includes('?') ? '&' : '?') + 'merchant_id=' + config.merchant_id
}

function valid(s, response) {
  if (response.status !== 200) return false
  let data
  try { data = response.json() } catch (_) { return false }
  if (s.kind === 'editor') return data.id === s.id && Array.isArray(data.variants) && data.variants.length === s.variants
  if (!Array.isArray(data.results) || data.count !== s.count) return false
  if (s.kind === 'list') return JSON.stringify(data.results.map(p => p.id)) === JSON.stringify(s.ids)
  const expected = Math.min(25, Math.max(0, s.count - (s.page - 1) * 25))
  return data.results.length === expected
}

export function setup() {
  if (!__ENV.BENCH_USERNAME || !__ENV.BENCH_PASSWORD) fail('Set BENCH_USERNAME and BENCH_PASSWORD locally')
  const login = http.get(base + '/login/', { tags: { name: 'auth_setup' } })
  const token = login.html().find('input[name="csrfmiddlewaretoken"]').attr('value')
  if (!token) fail('CSRF token unavailable')
  const response = http.post(base + '/login/', {
    username: __ENV.BENCH_USERNAME, password: __ENV.BENCH_PASSWORD, csrfmiddlewaretoken: token,
  }, { redirects: 0, headers: { Referer: base + '/login/' }, tags: { name: 'auth_setup' } })
  if (response.status !== 302) fail('Login failed')
  const cookies = http.cookieJar().cookiesForURL(base)
  if (!cookies.sessionid) fail('Login did not establish a session')
  for (const s of selected) {
    if (!valid(s, http.get(url(s), { tags: { name: s.name, phase: 'preflight' } }))) fail('Preflight failed: ' + s.name)
  }
  return { cookies }
}

function run(data, record) {
  for (const [name, values] of Object.entries(data.cookies)) {
    for (const value of values) http.cookieJar().set(base, name, value)
  }
  for (const s of selected) {
    if (record) measurementClock.add(Date.now())
    const response = http.get(url(s), { tags: { name: s.name }, redirects: 0 })
    const ok = valid(s, response)
    if (record) {
      const tags = { endpoint: s.name }
      latency.add(response.timings.duration, tags)
      invalid.add(!ok, tags)
      requests.add(1, tags)
      httpFailed.add(response.status !== 200, tags)
      measurementClock.add(Date.now())
      check(response, { 'expected status and content': () => ok }, tags)
    }
    sleep(Number(__ENV.THINK_SECONDS || 0.2))
  }
}

export function warmup(data) { run(data, false) }
export function measured(data) { run(data, true) }

export function handleSummary(data) {
  // Setup data (session cookies) is deliberately not exported.
  const clock = data.metrics.measurement_clock_ms?.values
  const seconds = clock ? (clock.max - clock.min) / 1000 : 0
  data.benchmark = {
    measured_request_window_seconds: seconds,
    measured_requests_per_second: seconds > 0 ? data.metrics.endpoint_requests.values.count / seconds : null,
    base_url: base, vus, cases: selected.map(s => s.name),
    note: 'Throughput spans first measured request start to last completion, including think-time gaps and drain; excludes setup/warmup. Per-case throughput uses the same window.',
  }
  data.benchmark.per_endpoint_requests_per_second = Object.fromEntries(selected.map(s => [
    s.name, seconds > 0 ? data.metrics[`endpoint_requests{endpoint:${s.name}}`]?.values.count / seconds : null,
  ]))
  return { [__ENV.RESULT_PATH || 'k6-summary.json']: JSON.stringify(data, null, 2) }
}
