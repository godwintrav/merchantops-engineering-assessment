"""Persisted retry identity and safe, non-retrying database error responses."""

from unittest.mock import patch
from uuid import uuid4

from django.db import OperationalError, connection
from django.test import TestCase
from rest_framework.test import APIClient

from catalog.models import AuditLog, Inventory, InventoryOperation
from catalog.tests import test_inventory_adjustment_api as contract


class InventoryReliabilityTests(TestCase):
    url = contract.InventoryAdjustmentAPITests.url
    assert_unchanged = contract.InventoryAdjustmentAPITests.assert_unchanged

    @classmethod
    def setUpTestData(cls):
        contract.InventoryAdjustmentAPITests.setUpTestData.__func__(cls)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.key = str(uuid4())

    def keyed_post(self, body=None, key=None, **kwargs):
        return self.client.post(
            self.url(**kwargs),
            body or {"delta": 3, "reason": "Count"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=key or self.key,
        )

    def test_duplicate_returns_original_adjustment_and_latest_inventory(self):
        first = self.keyed_post()
        self.assertEqual(first.status_code, 201)
        Inventory.objects.filter(pk=self.inventory.pk).update(quantity=15)
        replay = self.keyed_post({"delta": 3, "reason": "  Count  "})
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.data["replayed"])
        self.assertEqual(replay.data["adjustment"], first.data["adjustment"])
        self.assertEqual(replay.data["inventory"]["quantity"], 15)
        self.assertEqual(AuditLog.objects.count(), 1)
        operation = InventoryOperation.objects.get()
        self.assertEqual(operation.response["inventory"]["quantity"], 13)

    def test_key_payload_target_and_actor_mismatch_rejected(self):
        self.assertEqual(self.keyed_post().status_code, 201)
        for body in [
            {"delta": 4, "reason": "Count"},
            {"delta": 3, "reason": "Other reason"},
        ]:
            self.assertEqual(self.keyed_post(body).data["code"], "idempotency_conflict")
        other_variant = self.foreign_variant
        # Reauthorization occurs before any stored result can be disclosed.
        self.assertEqual(self.keyed_post(variant=other_variant.pk).status_code, 404)
        self.merchant.members.add(self.outsider)
        self.client.force_authenticate(self.outsider)
        response = self.keyed_post()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "idempotency_conflict")
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_replay_rechecks_membership(self):
        self.assertEqual(self.keyed_post().status_code, 201)
        self.merchant.members.remove(self.user)
        self.assertEqual(self.keyed_post().status_code, 404)
        self.assertEqual(InventoryOperation.objects.count(), 1)

    def test_malformed_key_rejected(self):
        for key in ["", "not-a-uuid", "x" * 100]:
            response = self.client.post(
                self.url(),
                {"delta": 3, "reason": "Count"},
                format="json",
                HTTP_IDEMPOTENCY_KEY=key,
            )
            self.assertEqual(response.status_code, 400)
        self.assert_unchanged()
        self.assertFalse(InventoryOperation.objects.exists())

    def test_new_key_is_new_intended_operation(self):
        self.assertEqual(self.keyed_post().status_code, 201)
        self.assertEqual(self.keyed_post(key=str(uuid4())).status_code, 201)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 16)
        self.assertEqual(AuditLog.objects.count(), 2)
        self.assertEqual(InventoryOperation.objects.count(), 2)

    def test_rejected_adjustment_does_not_claim_key(self):
        self.assertEqual(
            self.keyed_post({"delta": -7, "reason": "Count"}).status_code, 409
        )
        self.assertFalse(InventoryOperation.objects.exists())
        self.assertEqual(self.keyed_post().status_code, 201)

    def test_audit_failure_rolls_back_operation_key_too(self):
        with patch(
            "catalog.services.inventory.AuditLog.objects.create",
            side_effect=RuntimeError("Audit failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.keyed_post()
        self.assert_unchanged()
        self.assertFalse(InventoryOperation.objects.exists())
        self.assertEqual(self.keyed_post().status_code, 201)

    def test_recognized_lock_errors_return_safe_503_without_retry(self):
        for code in [1205, 1213]:
            with patch(
                "catalog.views.adjust_inventory",
                side_effect=OperationalError(code, "private database details"),
            ) as adjust:
                response = self.keyed_post()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.data["code"], "inventory_busy")
                self.assertEqual(response["Retry-After"], "1")
                self.assertNotIn("private", str(response.data))
                adjust.assert_called_once()
        self.assert_unchanged()

    def test_unrecognized_database_error_is_not_misclassified(self):
        with patch(
            "catalog.views.adjust_inventory",
            side_effect=OperationalError(2002, "Connection unavailable"),
        ):
            with self.assertRaises(OperationalError):
                self.keyed_post()

    def test_connection_lock_timeout_restored_after_success_and_conflict(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@SESSION.innodb_lock_wait_timeout")
            original = cursor.fetchone()[0]
        self.keyed_post()
        self.keyed_post({"delta": -100, "reason": "Count"}, key=str(uuid4()))
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@SESSION.innodb_lock_wait_timeout")
            self.assertEqual(cursor.fetchone()[0], original)

    def test_key_cannot_be_reused_for_another_authorized_variant(self):
        from catalog.models import ProductVariant

        variant = ProductVariant.objects.create(
            product=self.product, sku="SECOND", name="Second"
        )
        inventory = Inventory.objects.create(variant=variant, quantity=20)
        self.assertEqual(self.keyed_post().status_code, 201)
        response = self.keyed_post(variant=variant.pk)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "idempotency_conflict")
        inventory.refresh_from_db()
        self.assertEqual(inventory.quantity, 20)
        self.assertEqual(AuditLog.objects.count(), 1)

    def test_same_key_is_scoped_to_merchant(self):
        self.foreign_merchant.members.add(self.user)
        self.assertEqual(self.keyed_post().status_code, 201)
        response = self.keyed_post(
            product=self.foreign_product.pk,
            variant=self.foreign_variant.pk,
            merchant=self.foreign_merchant.pk,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(InventoryOperation.objects.count(), 2)
        self.assertEqual(AuditLog.objects.count(), 2)

    def test_failure_saving_outcome_rolls_back_stock_audit_and_key(self):
        save = InventoryOperation.save

        def fail_on_outcome(instance, *args, **kwargs):
            if instance.response:
                raise OperationalError(1213, "Injected deadlock after stock and audit")
            return save(instance, *args, **kwargs)

        with patch.object(InventoryOperation, "save", new=fail_on_outcome):
            response = self.keyed_post()
        self.assertEqual(response.status_code, 503)
        self.assert_unchanged()
        self.assertFalse(InventoryOperation.objects.exists())
        self.assertEqual(self.keyed_post().status_code, 201)
