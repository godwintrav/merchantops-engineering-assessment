# Review Demonstration

Start the app with `./setup.sh` and sign in at `http://127.0.0.1:5173/` using `demo_operator` and your chosen password.

1. **Catalogue:** open browser Network tools, filter `/api/products/`, and load/page/search the catalogue. Each action uses one list request; rows retain category, status and images.
2. **Complex editor:** open the seeded 50-variant product (standard fresh seed: product 1). One editor request supplies variants, ordered prices, inventory and image. Compare saved SQL/latency evidence in `benchmarks/results/comparison.md`.
3. **Adjustment:** open another product, edit its name without saving, switch to Inventory, and choose Adjust stock. Enter `+1` and reason `Review demonstration`. Inspect the preview and success result; return to General to confirm the unsaved name remains. Discard that name edit when navigating away.
4. **History:** view product activity. Confirm operator, variant, reason, signed delta, before/after stock and timestamp. A corrective `-1` adjustment can restore quantity; both intentional operations remain audited.
5. **Safe retry:** API clients can repeat the same authorized POST with the same UUID `Idempotency-Key` and payload. The first returns 201, a replay returns 200 with the same adjustment ID and current stock. Use a new key only for a new intended correction. The README documents session/CSRF requirements.
6. **Competing operations:** run the real MySQL concurrency and reliability tests:

```bash
docker compose exec backend python manage.py test catalog.tests.test_inventory_concurrency catalog.tests.test_inventory_idempotency_concurrency catalog.tests.test_inventory_reliability --keepdb
```

The automated suites cover competing increments/decrements, atomic rollback, independent row locks, concurrent duplicate keys and manual recovery after contention. No destructive database reset is needed. Run the complete backend and Playwright suites using the README commands.
