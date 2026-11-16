import { test, expect } from '@playwright/test'

for (const count of [2, 50]) {
  test(`editor loads ${count} variants in one request and saves image edits`, async ({ page }) => {
    const product = {
      id: 42, name: 'Editor product', sku: 'EDITOR-42', description: 'Product description',
      status: 'draft', image_url: count === 2 ? '/product-images/laptop.webp' : '',
      category: { id: 7, name: 'Computers' },
      variants: Array.from({ length: count }, (_, number) => ({
        id: number + 1, name: `Variant ${number + 1}`, sku: `V-${number + 1}`,
        prices: [{ id: number + 1, tier: 'retail', amount: '12.34' }],
        inventory: { id: number + 1, quantity: 10, reserved: 5 },
      })),
      availability: [{ id: 1, channel: 'online', enabled: true }],
    }
    const requests = []
    let patch
    await page.route('**/api/products/**', async route => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      requests.push({ method: request.method(), path })
      if (path === '/api/products/42/editor/' && request.method() === 'GET') {
        await route.fulfill({ json: product })
      } else if (path === '/api/products/42/' && request.method() === 'PATCH') {
        patch = request.postDataJSON()
        await route.fulfill({ json: {
          id: product.id, name: product.name, sku: product.sku,
          description: product.description, status: product.status,
          category: product.category.id, image_url: patch.image_url,
        } })
      } else {
        await route.fulfill({ status: 500, json: { detail: 'Unexpected editor detail fetch' } })
      }
    })

    await page.goto('/products/42')
    await expect(page.getByLabel('Product name', { exact: true })).toHaveValue(product.name)
    await expect(page.getByLabel(/^Image path/)).toHaveValue(product.image_url)
    await expect(page.locator('#panel-inventory tbody tr')).toHaveCount(count)
    await expect(page.locator('#panel-pricing tbody tr')).toHaveCount(count)
    await expect(page.getByRole('button', { name: 'Save changes', exact: true })).toBeDisabled()
    expect(requests).toEqual([{ method: 'GET', path: '/api/products/42/editor/' }])
    if (product.image_url) {
      await expect(page.locator('.editor-thumbnail img')).toHaveAttribute('src', product.image_url)
    } else {
      await expect(page.locator('.editor-thumbnail .package-icon')).toBeVisible()
    }

    await page.getByRole('tab', { name: 'inventory', exact: true }).click()
    await expect(page.locator('#panel-inventory tbody tr').first()).toContainText('V-1')
    await page.getByRole('tab', { name: 'general', exact: true }).click()
    await page.getByLabel(/^Image path/).fill('/product-images/camera.webp')
    await page.getByRole('button', { name: 'Save changes', exact: true }).click()
    await expect(page.getByText('Product saved.', { exact: true })).toBeVisible()
    expect(patch).toEqual({ image_url: '/product-images/camera.webp' })
    await expect(page.locator('.editor-thumbnail img')).toHaveAttribute('src', patch.image_url)
    await expect(page.getByRole('button', { name: 'Save changes', exact: true })).toBeDisabled()
    expect(requests).toEqual([
      { method: 'GET', path: '/api/products/42/editor/' },
      { method: 'PATCH', path: '/api/products/42/' },
    ])
  })
}
