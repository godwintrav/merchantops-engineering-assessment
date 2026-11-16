import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import net from 'node:net'
import lighthouse from 'lighthouse'
import { chromium, base, login, catalogueReady, config, output, save } from './common.mjs'

// Temporary persistent context lets Lighthouse use the authenticated default profile.
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'merchantops-lighthouse-'))
const server = net.createServer()
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const port = server.address().port
await new Promise(resolve => server.close(resolve))
let context
try {
  context = await chromium.launchPersistentContext(directory, {
    headless: true, args: [`--remote-debugging-port=${port}`],
  })
  await login(context)
  const page = context.pages()[0]
  await page.goto(base + '/')
  await catalogueReady(page, config.scenarios.find(s => s.name === 'catalogue_page_1').ids)
  const result = await lighthouse(base + '/', {
    port, output: ['json', 'html'], onlyCategories: ['performance'],
    disableStorageReset: true, formFactor: 'desktop',
    screenEmulation: { mobile: false, width: 1440, height: 900, deviceScaleFactor: 1, disabled: false },
    throttlingMethod: 'provided',
  })
  if (result.lhr.runtimeError || new URL(result.lhr.finalDisplayedUrl).pathname !== '/') {
    throw new Error('Lighthouse failed or measured the login page')
  }
  // Full reports may include DOM/URLs: keep ignored until manually reviewed.
  const raw = output + '.private'
  fs.mkdirSync(raw, { recursive: true })
  fs.writeFileSync(path.join(raw, 'report.json'), result.report[0])
  fs.writeFileSync(path.join(raw, 'report.html'), result.report[1])
  const ids = ['largest-contentful-paint', 'cumulative-layout-shift', 'total-blocking-time', 'first-contentful-paint']
  save({ schema_version: 1, lighthouse_version: result.lhr.lighthouseVersion,
    final_url: result.lhr.finalDisplayedUrl,
    profile: 'desktop, unthrottled; existing authenticated session; browser cache not reset',
    metrics: Object.fromEntries(ids.map(id => [id, {
      value: result.lhr.audits[id].numericValue, unit: result.lhr.audits[id].numericUnit,
    }])),
    note: 'Supplementary initial-load diagnostics; does not establish catalogue readiness. Raw reports require manual sanitization.' })
} finally {
  if (context) await context.close()
  fs.rmSync(directory, { recursive: true, force: true })
}
