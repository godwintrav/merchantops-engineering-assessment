import { performance } from 'node:perf_hooks'
import { chromium, expect, base, config, login, catalogueReady, save } from './common.mjs'

const browser = await chromium.launch()
const results = []
const repetitions = Number(process.env.REPETITIONS || 3)
if (!Number.isInteger(repetitions) || repetitions < 1) throw new Error('Invalid REPETITIONS')
const first = config.scenarios.find(s => s.name === 'catalogue_page_1')
const search = config.scenarios.find(s => s.name === 'search_selective')

try {
  for (let repetition = 1; repetition <= repetitions; repetition++) {
    // Fresh context isolates browser caches; API preflight warms server caches.
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    try {
      await login(context)
      const page = await context.newPage()
      page.setDefaultTimeout(60000)
      let active
      page.on('request', request => {
        if (active && new URL(request.url()).pathname.startsWith('/api/')) active.requests++
      })
      page.on('response', response => {
        if (active && new URL(response.url()).pathname.startsWith('/api/') && response.status() >= 400) active.errors++
      })
      page.on('requestfailed', request => {
        if (active && new URL(request.url()).pathname.startsWith('/api/')) active.errors++
      })

      async function measure(name, action, ready, hard = false) {
        // Node's monotonic clock spans document replacement; includes automation overhead.
        active = { name, repetition, requests: 0, errors: 0 }
        if (!hard) await page.evaluate(() => performance.clearResourceTimings())
        const start = performance.now()
        await action()
        await ready()
        const elapsed = performance.now() - start
        const row = active
        active = null
        const resources = await page.evaluate(() => performance.getEntriesByType('resource').map(r => ({
          api: new URL(r.name).pathname.startsWith('/api/'),
          transfer: r.transferSize, encoded: r.encodedBodySize,
        })))
        expect(row.errors, name + ': API errors').toBe(0)
        results.push({ ...row, duration_ms: elapsed,
          resource_transfer_bytes: resources.reduce((sum, r) => sum + r.transfer, 0),
          api_encoded_body_bytes: resources.filter(r => r.api).reduce((sum, r) => sum + r.encoded, 0),
        })
      }

      await measure('catalogue_hard_navigation', () => page.goto(base + '/'),
        () => catalogueReady(page, first.ids), true)
      // Read expected page IDs outside the timed interval.
      const nextResponse = await context.request.get(`${base}/api/products/?merchant_id=${config.merchant_id}&page=2`)
      expect(nextResponse.status()).toBe(200)
      const next = await nextResponse.json()
      await measure('catalogue_next_page', () => page.getByRole('button', { name: /Next/ }).click(), async () => {
        await page.waitForFunction(() => new URL(location.href).searchParams.get('page') === '2', null, { polling: 'raf' })
        await catalogueReady(page, next.results.map(p => p.id))
      })
      await measure('catalogue_search', () => page.getByRole('searchbox').fill(search.search), async () => {
        await page.waitForFunction(term => new URL(location.href).searchParams.get('search') === term, search.search, { polling: 'raf' })
        await catalogueReady(page, search.ids)
      })

      for (const product of config.fixtures.editor_products) {
        // Prepare via UI, outside timing; each editor starts from the catalogue.
        await page.goto(base + '/')
        await catalogueReady(page, first.ids)
        await measure(`editor_${product.variants}_variants`,
          () => page.locator(`.product-link[href="/products/${product.id}"]`).click(), async () => {
            await page.waitForFunction(expected => {
              const field = document.querySelector('#panel-general input')
              return location.pathname === `/products/${expected.id}` && field &&
                !field.disabled && !field.readOnly && field.getClientRects().length > 0 &&
                document.querySelectorAll('#panel-inventory tbody tr').length === expected.variants &&
                document.querySelectorAll('#panel-pricing tbody tr').length === expected.variants
            }, product, { polling: 'raf' })
          })
      }
    } finally { await context.close() }
  }
  save({ schema_version: 2, readiness_polling: 'requestAnimationFrame; excludes assertion retry backoff', browser: browser.version(), base_url: base,
    viewport: { width: 1440, height: 900 }, repetitions,
    timing: 'Node monotonic action-to-DOM-ready; includes automation overhead, not paint timing',
    profile: 'desktop, unthrottled; fresh context per repetition, then warm navigation',
    bytes: 'Resource Timing transferSize (headers + encoded body; cached may be zero), excluding document; API encodedBodySize separately',
    results })
} finally { await browser.close() }
