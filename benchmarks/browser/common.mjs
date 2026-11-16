import fs from 'node:fs'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

export { chromium, expect }
export const base = (process.env.FRONTEND_URL || 'http://127.0.0.1:5173').replace(/\/$/, '')
export const config = JSON.parse(fs.readFileSync(process.env.BENCH_CONFIG, 'utf8'))
export const output = process.env.RESULT_PATH
if (!output || fs.existsSync(output)) throw new Error('Set RESULT_PATH to a new output filename')
if (!process.env.BENCH_USERNAME || !process.env.BENCH_PASSWORD) throw new Error('Set local benchmark credentials')

export async function login(context) {
  const response = await context.request.get(base + '/login/')
  const html = await response.text()
  const token = html.match(/name="csrfmiddlewaretoken" value="([^"]+)"/)?.[1]
  if (!token) throw new Error('Login CSRF token missing')
  const result = await context.request.post(base + '/login/', {
    form: { username: process.env.BENCH_USERNAME, password: process.env.BENCH_PASSWORD, csrfmiddlewaretoken: token },
    headers: { Referer: base + '/login/' }, maxRedirects: 0,
  })
  if (result.status() !== 302) throw new Error('Login failed')
  const probe = await context.request.get(`${base}/api/products/?merchant_id=${config.merchant_id}`)
  if (probe.status() !== 200) throw new Error('Authenticated merchant preflight failed')
}

export async function catalogueReady(page, ids) {
  await page.waitForFunction(expected => {
    const panel = document.querySelector('[aria-label="Product catalogue"]')
    if (!panel || panel.getAttribute('aria-busy') !== 'false') return false
    if (!expected.length) return panel.textContent.includes('No matching products')
    const actual = Array.from(panel.querySelectorAll('.catalogue-table .product-link'))
      .map(link => Number(link.getAttribute('href').split('/').pop()))
    return JSON.stringify(actual) === JSON.stringify(expected)
  }, ids, { polling: 'raf', timeout: 60000 })
}

export function save(value) {
  fs.mkdirSync(path.dirname(output), { recursive: true })
  fs.writeFileSync(output, JSON.stringify(value, null, 2) + '\n', { flag: 'wx' })
}
