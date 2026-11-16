"""Real MySQL transactions; worker connections never share the test connection."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import OperationalError, connection, connections, transaction
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import (
    AuditLog,
    Category,
    Inventory,
    Merchant,
    Product,
    ProductVariant,
)
from catalog.services.inventory import MAX_QUANTITY, adjust_inventory


class InventoryConcurrencyTests(TransactionTestCase):
    wait_seconds = 5

    def setUp(self):
        self.assertEqual(
            connection.vendor, "mysql", "Run these tests through Docker Compose/MySQL."
        )
        self.users = [
            get_user_model().objects.create_user(username=f"stock-worker-{i}")
            for i in range(2)
        ]
        merchant = Merchant.objects.create(
            name="Concurrent stock", slug="concurrent-stock"
        )
        merchant.members.add(*self.users)
        category = Category.objects.create(merchant=merchant, name="Stock")
        self.product = Product.objects.create(
            merchant=merchant, category=category, name="Stock", sku="P"
        )
        self.variant = ProductVariant.objects.create(
            product=self.product, name="First", sku="V1"
        )
        self.other_variant = ProductVariant.objects.create(
            product=self.product, name="Second", sku="V2"
        )
        self.inventory = Inventory.objects.create(
            variant=self.variant, quantity=10, reserved=4
        )
        Inventory.objects.create(variant=self.other_variant, quantity=20, reserved=2)
        with connection.cursor() as cursor:
            cursor.execute("SELECT CONNECTION_ID()")
            self.main_connection_id = cursor.fetchone()[0]
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.pool.shutdown, wait=True, cancel_futures=True)

    def worker(self, operation):
        # Django's connection handler is thread-local. Close even when a test fails.
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION innodb_lock_wait_timeout=3")
                cursor.execute("SELECT CONNECTION_ID()")
                connection_id = cursor.fetchone()[0]
            return connection_id, operation()
        finally:
            # This also discards the worker's test-only session timeout.
            connections.close_all()

    def post(self, user, delta, variant=None):
        client = APIClient()
        client.force_authenticate(user)
        url = reverse(
            "inventory-adjustment",
            kwargs={"pk": self.product.pk, "variant_id": (variant or self.variant).pk},
        )
        response = client.post(
            url + f"?merchant_id={self.product.merchant_id}",
            {"delta": delta, "reason": f"Correction by {user.username}"},
            format="json",
        )
        return response.status_code, response.json()

    def result(self, future):
        return future.result(timeout=self.wait_seconds * 3)

    def concurrent_posts(self, deltas):
        barrier = Barrier(2, timeout=self.wait_seconds)

        def request(user, delta):
            def synchronize(execute, sql, params, many, context):
                # Both actual requests reach the inventory read before either runs it.
                # Never put a barrier after acquiring the same exclusive row lock.
                if (
                    sql.lstrip().upper().startswith("SELECT")
                    and "`catalog_inventory`" in sql
                ):
                    barrier.wait()
                return execute(sql, params, many, context)

            with connection.execute_wrapper(synchronize):
                return self.post(user, delta)

        futures = [
            self.pool.submit(
                self.worker, lambda user=user, delta=delta: request(user, delta)
            )
            for user, delta in zip(self.users, deltas)
        ]
        results = [self.result(future) for future in futures]
        ids = [item[0] for item in results]
        self.assertEqual(len(set(ids)), 2)
        self.assertNotIn(self.main_connection_id, ids)
        return [item[1] for item in results]

    def assert_audit_chain(self, start, end, count):
        audits = list(AuditLog.objects.filter(product=self.product).order_by("id"))
        self.assertEqual(len(audits), count)
        current = start
        for audit in audits:
            details = audit.details
            self.assertEqual(audit.action, "inventory.adjusted")
            self.assertEqual(details["variant_id"], self.variant.pk)
            self.assertEqual(details["variant_sku"], self.variant.sku)
            self.assertEqual(details["operator_id"], audit.actor_id)
            self.assertEqual(details["operator_username"], audit.actor.username)
            self.assertEqual(details["reason"], f"Correction by {audit.actor.username}")
            self.assertEqual(details["quantity_before"], current)
            self.assertEqual(details["quantity_after"], current + details["delta"])
            self.assertEqual(details["reserved"], 4)
            self.assertIsNotNone(audit.created_at)
            current = details["quantity_after"]
        self.assertEqual(current, end)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, end)
        self.assertEqual(self.inventory.reserved, 4)

    def test_concurrent_increments_keep_both_changes_and_audit_chain(self):
        results = self.concurrent_posts([3, 5])
        self.assertEqual([status for status, _ in results], [201, 201])
        self.assert_audit_chain(10, 18, 2)
        self.assertEqual(
            set(AuditLog.objects.values_list("actor_id", flat=True)),
            {user.pk for user in self.users},
        )
        self.assertEqual({data["adjustment"]["delta"] for _, data in results}, {3, 5})

    def test_competing_decrements_reject_one_without_violating_reservations(self):
        results = self.concurrent_posts([-4, -4])
        self.assertEqual(sorted(status for status, _ in results), [201, 409])
        rejected = next(data for status, data in results if status == 409)
        self.assertEqual(rejected["code"], "insufficient_stock")
        self.assert_audit_chain(10, 6, 1)

    def test_competing_increments_cannot_overflow_quantity_limit(self):
        Inventory.objects.filter(pk=self.inventory.pk).update(quantity=MAX_QUANTITY - 2)
        results = self.concurrent_posts([2, 1])
        self.assertEqual(sorted(status for status, _ in results), [201, 409])
        accepted = next(data for status, data in results if status == 201)
        rejected = next(data for status, data in results if status == 409)
        self.assertEqual(rejected["code"], "quantity_out_of_range")
        self.assert_audit_chain(MAX_QUANTITY - 2, accepted["inventory"]["quantity"], 1)

    def test_same_inventory_lock_is_enforced_by_mysql(self):
        attempted = Event()

        def adjust():
            def signal(execute, sql, params, many, context):
                if (
                    sql.lstrip().upper().startswith("SELECT")
                    and "`catalog_inventory`" in sql
                ):
                    attempted.set()
                return execute(sql, params, many, context)

            with connection.execute_wrapper(signal):
                return adjust_inventory(
                    variant=self.variant,
                    actor=self.users[0],
                    delta=1,
                    reason="Blocked correction",
                )

        with transaction.atomic():
            Inventory.objects.select_for_update().get(pk=self.inventory.pk)
            future = self.pool.submit(self.worker, adjust)
            self.assertTrue(
                attempted.wait(self.wait_seconds),
                "Worker never attempted its inventory read",
            )
            # A real server lock wait must time out while this connection holds the row.
            with self.assertRaises(OperationalError) as raised:
                self.result(future)
            self.assertEqual(raised.exception.args[0], 1205)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 10)
        self.assertFalse(AuditLog.objects.exists())

    def test_waiting_adjustment_checks_latest_quantity_and_reservations(self):
        attempted = Event()

        def request():
            def signal(execute, sql, params, many, context):
                if (
                    sql.lstrip().upper().startswith("SELECT")
                    and "`catalog_inventory`" in sql
                ):
                    attempted.set()
                return execute(sql, params, many, context)

            with connection.execute_wrapper(signal):
                return self.post(self.users[0], -4)

        with transaction.atomic():
            inventory = Inventory.objects.select_for_update().get(pk=self.inventory.pk)
            future = self.pool.submit(self.worker, request)
            self.assertTrue(attempted.wait(self.wait_seconds))
            inventory.quantity, inventory.reserved = 15, 12
            inventory.save(update_fields=["quantity", "reserved"])
        _, (status, body) = self.result(future)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "insufficient_stock")
        self.inventory.refresh_from_db()
        self.assertEqual((self.inventory.quantity, self.inventory.reserved), (15, 12))
        self.assertFalse(AuditLog.objects.exists())

    def test_unrelated_variant_completes_while_first_inventory_is_locked(self):
        with transaction.atomic():
            Inventory.objects.select_for_update().get(pk=self.inventory.pk)
            future = self.pool.submit(
                self.worker, lambda: self.post(self.users[0], 2, self.other_variant)
            )
            worker_id, (status, body) = self.result(future)
            self.assertNotEqual(worker_id, self.main_connection_id)
            self.assertEqual(status, 201)
            self.assertEqual(body["inventory"]["quantity"], 22)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 10)
        self.assertEqual(AuditLog.objects.count(), 1)
        self.assertEqual(
            AuditLog.objects.get().details["variant_id"], self.other_variant.pk
        )

    def test_stock_and_audit_become_visible_only_after_commit(self):
        inserted, release = Event(), Event()
        create_audit = AuditLog.objects.create

        def pause_after_insert(**kwargs):
            audit = create_audit(**kwargs)
            inserted.set()
            if not release.wait(self.wait_seconds):
                raise TimeoutError("Test never released the pending transaction")
            return audit

        with patch(
            "catalog.services.inventory.AuditLog.objects.create",
            side_effect=pause_after_insert,
        ):
            future = self.pool.submit(self.worker, lambda: self.post(self.users[0], 3))
            try:
                self.assertTrue(
                    inserted.wait(self.wait_seconds), "Worker never inserted its audit"
                )
                # Both writes exist in the worker transaction but neither is committed.
                self.assertEqual(
                    Inventory.objects.get(pk=self.inventory.pk).quantity, 10
                )
                self.assertFalse(AuditLog.objects.exists())
            finally:
                release.set()
            worker_id, (status, _) = self.result(future)
        self.assertNotEqual(worker_id, self.main_connection_id)
        self.assertEqual(status, 201)
        self.assert_audit_chain(10, 13, 1)

    def test_exception_after_audit_insert_rolls_back_both_writes(self):
        create_audit = AuditLog.objects.create

        def fail_after_insert(**kwargs):
            create_audit(**kwargs)
            raise RuntimeError("Failure after actual audit insertion")

        with patch(
            "catalog.services.inventory.AuditLog.objects.create",
            side_effect=fail_after_insert,
        ):
            with self.assertRaisesMessage(RuntimeError, "after actual audit insertion"):
                adjust_inventory(
                    variant=self.variant,
                    actor=self.users[0],
                    delta=3,
                    reason="Rollback check",
                )

        def independently_read():
            return (
                Inventory.objects.get(pk=self.inventory.pk).quantity,
                AuditLog.objects.count(),
            )

        worker_id, state = self.result(
            self.pool.submit(self.worker, independently_read)
        )
        self.assertNotEqual(worker_id, self.main_connection_id)
        self.assertEqual(state, (10, 0))
