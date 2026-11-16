import { test, expect } from '@playwright/test'

function product() {
  return {
    id: 42, name: 'Stock product', sku: 'STOCK-42', description: '', status: 'active', image_url: '',
    category: { id: 1, name: 'Stock' }, availability: [],
    variants: [
      { id: 7, name: 'Blue', sku: 'BLUE', prices: [], inventory: { id: 70, quantity: 10, reserved: 4 } },
      { id: 8, name: 'Red', sku: 'RED', prices: [], inventory: { id: 80, quantity: 20, reserved: 1 } },
      { id: 9, name: 'Missing', sku: 'MISSING', prices: [], inventory: null },
    ],
  }
}

async function editor(page, handlePost, inventory) {
  const fixture = product()
  if (inventory) fixture.variants[0].inventory = { ...fixture.variants[0].inventory, ...inventory }
  const requests = []
  await page.route('**/api/products/**', async route => {
    const req = route.request()
    requests.push({ method: req.method(), path: new URL(req.url()).pathname })
    if (req.method() === 'POST') return handlePost(route)
    await route.fulfill({ json: fixture })
  })
  await page.goto('/products/42')
  await expect(page.getByLabel('Product name', { exact: true })).toHaveValue('Stock product')
  return requests
}

async function open(page) {
  await page.getByRole('tab', { name: 'inventory', exact: true }).click()
  await page.getByRole('button', { name: 'Adjust stock for Blue', exact: true }).click()
  return page.getByRole('form', { name: 'Adjust stock for Blue' })
}

test('adjustment saves once, updates authoritative stock, and preserves unsaved general edits', async ({ page }) => {
  let release
  const wait = new Promise(resolve => { release = resolve })
  let payload
  const requests = await editor(page, async route => {
    payload = route.request().postDataJSON()
    await wait
    await route.fulfill({ status: 201, json: {
      inventory: { id: 70, quantity: 12, reserved: 5, available: 7 },
      adjustment: { id: 100, variant_id: 7, quantity_before: 9, quantity_after: 12 },
    } })
  })
  await page.getByLabel('Product name', { exact: true }).fill('Unsaved product name')
  const form = await open(page)
  await expect(form.getByLabel('Adjustment amount')).toBeFocused()
  await form.getByLabel('Adjustment amount').fill('+3')
  await form.getByLabel('Reason', { exact: true }).fill('  Physical count  ')
  await expect(form).toContainText('Proposed quantity: 13')
  await form.getByRole('button', { name: 'Apply adjustment' }).click()
  await expect(form.getByRole('button', { name: 'Saving adjustment…' })).toBeDisabled()
  // A second submit event must not issue another mutation.
  await form.evaluate(element => element.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Dismiss stock dialog' })).toBeDisabled()
  release()
  await expect(form.getByRole('status')).toContainText('Stock adjusted: 9 → 12. Adjustment #100.')
  expect(payload).toEqual({ delta: 3, reason: 'Physical count' })
  const rows = page.locator('#panel-inventory tbody tr')
  await expect(rows.nth(0).locator('td').nth(1)).toHaveText('12')
  await expect(rows.nth(0).locator('td').nth(2)).toHaveText('5')
  await expect(rows.nth(0).locator('td').nth(3)).toHaveText('7')
  await expect(rows.nth(1).locator('td').nth(1)).toHaveText('20')
  await expect(rows.nth(2)).toContainText('Inventory unavailable')
  await expect(rows.nth(2).getByRole('button')).toHaveCount(0)
  await form.getByRole('button', { name: 'Close adjustment', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('tab', { name: 'general', exact: true }).click()
  await expect(page.getByLabel('Product name', { exact: true })).toHaveValue('Unsaved product name')
  await expect(page.getByRole('button', { name: 'Save changes', exact: true })).toBeEnabled()
  expect(requests).toEqual([
    { method: 'GET', path: '/api/products/42/editor/' },
    { method: 'POST', path: '/api/products/42/variants/7/adjustments/' },
  ])
})

test('local validation and server errors preserve adjustment inputs without changing inventory', async ({ page }) => {
  let attempts = 0
  const requests = await editor(page, async route => {
    attempts++
    if (attempts === 1) return route.fulfill({ status: 400, json: { reason: ['Please provide a specific reason.'] } })
    if (attempts === 2) return route.fulfill({ status: 409, json: { code: 'insufficient_stock', detail: 'Quantity cannot fall below reserved stock.' } })
    return route.abort('failed')
  })
  const form = await open(page)
  await form.getByLabel('Adjustment amount').fill('0')
  await form.getByLabel('Reason', { exact: true }).fill('Count')
  await form.getByRole('button', { name: 'Apply adjustment' }).click()
  await expect(form.getByRole('alert')).toContainText('Correct the highlighted fields.')
  expect(requests.filter(r => r.method === 'POST')).toHaveLength(0)
  await form.getByLabel('Adjustment amount').fill('-7')
  await expect(form).toContainText('Cannot go below 4 reserved units. You can remove at most 6 units.')
  await form.getByRole('button', { name: 'Apply adjustment' }).click()
  await expect(form).toContainText('Please provide a specific reason.')
  await expect(form.getByLabel('Reason', { exact: true })).toHaveValue('Count')
  await form.getByRole('button', { name: 'Apply adjustment' }).click()
  await expect(form.getByRole('alert')).toContainText('Quantity cannot fall below reserved stock.')
  await expect(form.getByLabel('Adjustment amount')).toHaveValue('-7')
  await form.getByRole('button', { name: 'Apply adjustment' }).click()
  await expect(form.getByRole('alert')).toContainText('The outcome could not be confirmed.')
  await expect(form.getByLabel('Reason', { exact: true })).toHaveValue('Count')
  await expect(page.locator('#panel-inventory tbody tr').first().locator('td').nth(1)).toHaveText('10')
  expect(requests.filter(r => r.method === 'POST')).toHaveLength(3)
})

test('modal contains focus and confirms unfinished input before Escape or backdrop dismissal', async ({ page }) => {
  await editor(page, () => { throw new Error('Unexpected mutation') })
  const form = await open(page)
  await form.getByLabel('Adjustment amount').fill('2')
  page.once('dialog', dialog => dialog.dismiss())
  await page.keyboard.press('Escape')
  await expect(form.getByLabel('Adjustment amount')).toHaveValue('2')
  await form.getByRole('button', { name: 'Close adjustment' }).focus()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Dismiss stock dialog' })).toBeFocused()
  page.once('dialog', dialog => dialog.dismiss())
  await page.mouse.click(2, 2)
  await expect(form).toBeVisible()
  page.once('dialog', dialog => dialog.accept())
  await form.getByRole('button', { name: 'Close adjustment' }).click()
  await expect(form).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Adjust stock for Blue', exact: true })).toBeFocused()
})

test('activity renders inventory audit snapshots and retains product changes', async ({ page }) => {
  await page.route('**/api/products/**', route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith('/activity/') ? {
    count: 2, next: null, previous: null, results: [
      { id: 2, action: 'inventory.adjusted', actor: null, created_at: '2026-11-16T12:00:00Z', details: { variant_id: 7, variant_name: 'Blue', variant_sku: 'BLUE', operator_username: 'original_operator', delta: -3, quantity_before: 10, quantity_after: 7, reason: '<script>unsafe()</script> Physical count' } },
      { id: 1, action: 'product.updated', actor: 'editor', created_at: '2026-11-15T12:00:00Z', details: { changes: { name: { from: 'Old name', to: 'Stock product' } } } },
    ],
  } : product() }))
  await page.goto('/products/42/activity')
  const rows = page.locator('.activity-table tbody tr')
  await expect(rows).toHaveCount(2)
  await expect(rows.first()).toContainText('Inventory adjusted')
  await expect(rows.first()).toContainText('original_operator')
  await expect(rows.first()).toContainText('Blue BLUE (ID 7)')
  await expect(rows.first()).toContainText('-3')
  await expect(rows.first()).toContainText('10 → 7')
  await expect(rows.first()).toContainText('<script>unsafe()</script> Physical count')
  await expect(rows.first().locator('script')).toHaveCount(0)
  await expect(rows.first().locator('time')).toHaveAttribute('datetime', '2026-11-16T12:00:00Z')
  await expect(rows.nth(1)).toContainText('Product updated')
  await expect(rows.nth(1)).toContainText('Old name')
  await expect(rows.nth(1)).toContainText('Stock product')
})


test('preview explains the actual reservation boundary for a large reduction', async ({ page }) => {
  const requests = await editor(page, () => { throw new Error('Preview must not submit an adjustment') }, { quantity: 352, reserved: 86 })
  const form = await open(page)
  await form.getByLabel('Adjustment amount').fill('-296')
  await expect(form).toContainText('Proposed quantity: 56')
  await expect(form).toContainText('Cannot go below 86 reserved units. You can remove at most 266 units.')
  await form.getByLabel('Adjustment amount').fill('-266')
  await expect(form).toContainText('Proposed quantity: 86')
  await expect(form.locator('.inventory-preview')).not.toHaveClass(/error-text/)
  await expect(form).not.toContainText('Cannot go below')
  await form.getByLabel('Adjustment amount').fill('2147483647')
  await expect(form).toContainText('Cannot exceed the maximum quantity of 2,147,483,647 units.')
  expect(requests.filter(request => request.method === 'POST')).toHaveLength(0)
})
