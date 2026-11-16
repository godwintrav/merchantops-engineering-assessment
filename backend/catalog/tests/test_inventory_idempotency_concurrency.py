from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import AuditLog, Inventory, InventoryOperation
from catalog.tests import test_inventory_concurrency as concurrency


class InventoryIdempotencyConcurrencyTests(TransactionTestCase):
    setUp = concurrency.InventoryConcurrencyTests.setUp
    worker = concurrency.InventoryConcurrencyTests.worker
    result = concurrency.InventoryConcurrencyTests.result
    wait_seconds = 5

    def post(self, user, key, delta=3):
        client = APIClient()
        client.force_authenticate(user)
        response = client.post(
            reverse(
                "inventory-adjustment",
                kwargs={"pk": self.product.pk, "variant_id": self.variant.pk},
            )
            + f"?merchant_id={self.product.merchant_id}",
            {"delta": delta, "reason": "Physical count"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(key),
        )
        return response.status_code, response.json(), response.get("Retry-After")

    def concurrent(self, users, deltas):
        key = uuid4()
        barrier = Barrier(2, timeout=self.wait_seconds)

        def request(user, delta):
            synchronized = False

            def synchronize(execute, sql, params, many, context):
                nonlocal synchronized
                if (
                    not synchronized
                    and sql.lstrip().upper().startswith("SELECT")
                    and "`catalog_inventoryoperation`" in sql
                ):
                    synchronized = True
                    barrier.wait()
                return execute(sql, params, many, context)

            with connection.execute_wrapper(synchronize):
                return self.post(user, key, delta)

        futures = [
            self.pool.submit(
                self.worker, lambda user=user, delta=delta: request(user, delta)
            )
            for user, delta in zip(users, deltas)
        ]
        results = [self.result(future) for future in futures]
        self.assertEqual(len({item[0] for item in results}), 2)
        self.assertNotIn(self.main_connection_id, [item[0] for item in results])
        return [item[1] for item in results]

    def assert_single_operation(self, delta):
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 10 + delta)
        self.assertEqual(self.inventory.reserved, 4)
        self.assertEqual(InventoryOperation.objects.count(), 1)
        self.assertEqual(AuditLog.objects.count(), 1)
        audit = AuditLog.objects.get()
        operation = InventoryOperation.objects.get()
        self.assertEqual(audit.details["delta"], delta)
        self.assertEqual(operation.response["adjustment"]["id"], audit.pk)

    def test_concurrent_identical_requests_commit_once(self):
        results = self.concurrent([self.users[0], self.users[0]], [3, 3])
        self.assertEqual(sorted(status for status, _, _ in results), [200, 201])
        self.assertEqual(results[0][1]["adjustment"], results[1][1]["adjustment"])
        self.assert_single_operation(3)

    def test_concurrent_payload_mismatch_commits_only_winner(self):
        results = self.concurrent([self.users[0], self.users[0]], [3, 5])
        self.assertEqual(sorted(status for status, _, _ in results), [201, 409])
        accepted = next(body for status, body, _ in results if status == 201)
        rejected = next(body for status, body, _ in results if status == 409)
        self.assertEqual(rejected["code"], "idempotency_conflict")
        self.assert_single_operation(accepted["adjustment"]["delta"])

    def test_concurrent_other_actor_cannot_replay_result(self):
        results = self.concurrent(self.users, [3, 3])
        self.assertEqual(sorted(status for status, _, _ in results), [201, 409])
        self.assert_single_operation(3)

    @override_settings(INVENTORY_LOCK_WAIT_SECONDS=1)
    def test_inflight_duplicate_times_out_safely_then_replays_committed_outcome(self):
        inserted, release = Event(), Event()
        create_audit = AuditLog.objects.create
        key = uuid4()

        def pause(**kwargs):
            audit = create_audit(**kwargs)
            inserted.set()
            if not release.wait(self.wait_seconds):
                raise TimeoutError("Test did not release original operation")
            return audit

        with patch(
            "catalog.services.inventory.AuditLog.objects.create", side_effect=pause
        ):
            first = self.pool.submit(self.worker, lambda: self.post(self.users[0], key))
            try:
                self.assertTrue(inserted.wait(self.wait_seconds))
                second = self.pool.submit(
                    self.worker, lambda: self.post(self.users[0], key)
                )
                _, (status, body, retry_after) = self.result(second)
                self.assertEqual(status, 503)
                self.assertEqual(body["code"], "inventory_busy")
                self.assertEqual(retry_after, "1")
            finally:
                release.set()
            self.assertEqual(self.result(first)[1][0], 201)
        # A new request/connection after an uncertain attempt sees the stored result.
        _, (status, body, _) = self.result(
            self.pool.submit(self.worker, lambda: self.post(self.users[0], key))
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["replayed"])
        self.assert_single_operation(3)

    @override_settings(INVENTORY_LOCK_WAIT_SECONDS=1)
    def test_inventory_contention_rolls_back_claim_and_allows_same_key_retry(self):
        from django.db import transaction

        key = uuid4()

        def attempt():
            result = self.post(self.users[0], key)
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1, @@SESSION.innodb_lock_wait_timeout")
                self.assertEqual(cursor.fetchone(), (1, 3))
            return result

        with transaction.atomic():
            Inventory.objects.select_for_update().get(pk=self.inventory.pk)
            future = self.pool.submit(self.worker, attempt)
            _, (status, body, _) = self.result(future)
            self.assertEqual(status, 503)
            self.assertEqual(body["code"], "inventory_busy")
            self.assertFalse(InventoryOperation.objects.exists())
            self.assertFalse(AuditLog.objects.exists())
        _, (status, _, _) = self.result(
            self.pool.submit(self.worker, lambda: self.post(self.users[0], key))
        )
        self.assertEqual(status, 201)
        self.assert_single_operation(3)
