import { test, expect } from '@playwright/test'

const products = Array.from({ length: 50 }, (_, index) => ({
  id: 1000 - index,
  name: `Catalogue product ${index + 1}`,
  sku: `SKU-${index + 1}`,
  category: index % 2 ? 'Accessories' : 'Computers',
  status: index % 2 ? 'draft' : 'active',
  image_url: '/product-images/laptop.webp',
}))

async function expectProducts(page, expected) {
  await expect(page.locator('[aria-label="Product catalogue"]')).toHaveAttribute('aria-busy', 'false')
  const rows = page.locator('.catalogue-table tbody tr')
  await expect(rows).toHaveCount(expected.length)
  await expect(rows.locator('.product-link')).toHaveText(expected.map(product => product.name))
  await expect(rows.locator('td:nth-child(2)')).toHaveText(expected.map(product => product.sku))
  await expect(rows.locator('td:nth-child(3)')).toHaveText(expected.map(product => product.category))
  await expect(rows.locator('.status-badge')).toHaveText(expected.map(product => product.status))
  expect(await rows.locator('.product-link').evaluateAll(links => links.map(link => link.getAttribute('href'))))
    .toEqual(expected.map(product => `/products/${product.id}`))
  await expect(rows.first().locator('img')).toHaveAttribute('src', expected[0].image_url)
}

test('catalogue renders list fields with one request per load, page and search', async ({ page }) => {
  const requests = []
  let releaseFirstResponse
  const firstResponse = new Promise(resolve => { releaseFirstResponse = resolve })
  await page.route('**/api/products/**', async route => {
    const url = new URL(route.request().url())
    requests.push(url)
    if (url.pathname !== '/api/products/') {
      await route.fulfill({ status: 500, json: { detail: 'Unexpected detail hydration request' } })
      return
    }
    if (requests.length === 1) await firstResponse
    const term = url.searchParams.get('search') || ''
    const matches = products.filter(product => product.sku === term || !term)
    const number = Number(url.searchParams.get('page') || 1)
    await route.fulfill({ json: {
      count: matches.length,
      previous: number > 1 ? '/api/products/?page=1' : null,
      next: !term && number === 1 ? '/api/products/?page=2' : null,
      results: matches.slice((number - 1) * 25, number * 25),
    } })
  })

  await page.goto('/')
  await expect(page.getByRole('status')).toContainText('Loading products')
  releaseFirstResponse()
  await expectProducts(page, products.slice(0, 25))
  expect(requests).toHaveLength(1)

  await page.getByRole('button', { name: /Next/ }).click()
  await expectProducts(page, products.slice(25))
  expect(requests).toHaveLength(2)
  expect(requests[1].searchParams.get('page')).toBe('2')

  await page.getByRole('searchbox').fill('SKU-7')
  await expectProducts(page, [products[6]])
  expect(requests).toHaveLength(3)
  expect(requests[2].searchParams.get('page')).toBe('1')

  await page.getByRole('searchbox').fill('no-matches')
  await expect(page.getByText('No matching products', { exact: true })).toBeVisible()
  await expect(page.locator('.catalogue-table tbody tr')).toHaveCount(0)
  expect(requests).toHaveLength(4)
  expect(requests.every(url => Number(url.searchParams.get('merchant_id')) > 0)).toBe(true)
})

test('catalogue keeps error feedback and retries the list without fetching details', async ({ page }) => {
  const requests = []
  await page.route('**/api/products/**', async route => {
    requests.push(new URL(route.request().url()).pathname)
    if (requests.length === 1) {
      await route.fulfill({ status: 503, json: { detail: 'Catalogue temporarily unavailable' } })
      return
    }
    await route.fulfill({ json: { count: 25, next: null, previous: null, results: products.slice(0, 25) } })
  })
  await page.goto('/')
  await expect(page.getByRole('alert')).toHaveText('Catalogue temporarily unavailable')
  expect(requests).toEqual(['/api/products/'])
  await page.getByRole('button', { name: 'Try again' }).click()
  await expectProducts(page, products.slice(0, 25))
  expect(requests).toEqual(['/api/products/', '/api/products/'])
})
