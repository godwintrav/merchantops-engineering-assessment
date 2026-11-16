import { test, expect } from '@playwright/test'

test('inventory helper uses POST with CSRF and exposes structured conflicts', async ({ page, context, baseURL }) => {
  await context.addCookies([{ name: 'csrftoken', value: 'test-csrf-token', url: baseURL }])
  const calls = []
  await page.route('**/api/products/**', async route => {
    const req = route.request()
    if (new URL(req.url()).pathname.endsWith('/adjustments/')) {
      calls.push({ method: req.method(), headers: req.headers(), body: req.postDataJSON() })
      await route.fulfill({ status: 409, json: { code: 'insufficient_stock', detail: 'Quantity cannot fall below reserved stock.' } })
    } else {
      await route.fulfill({ json: { count: 0, next: null, previous: null, results: [] } })
    }
  })
  await page.goto('/')
  const error = await page.evaluate(async () => {
    const { products } = await import('/src/api.js')
    try {
      await products.adjustInventory(42, 7, { delta: -3, reason: 'Physical count' })
    } catch (failure) {
      return { status: failure.status, code: failure.code, fields: failure.fields, message: failure.message }
    }
  })
  expect(calls).toHaveLength(1)
  expect(calls[0].method).toBe('POST')
  expect(calls[0].headers['x-csrftoken']).toBe('test-csrf-token')
  expect(calls[0].body).toEqual({ delta: -3, reason: 'Physical count' })
  expect(error).toEqual({ status: 409, code: 'insufficient_stock', fields: { code: 'insufficient_stock', detail: 'Quantity cannot fall below reserved stock.' }, message: 'Quantity cannot fall below reserved stock.' })
})
