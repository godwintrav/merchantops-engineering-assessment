from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
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


class InventoryAdjustmentAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="stock-operator")
        cls.outsider = get_user_model().objects.create_user(username="outsider")
        cls.merchant = Merchant.objects.create(name="Stock Merchant", slug="stock")
        cls.merchant.members.add(cls.user)
        category = Category.objects.create(merchant=cls.merchant, name="Stock")
        cls.product = Product.objects.create(
            merchant=cls.merchant, category=category, name="Product", sku="P"
        )
        cls.variant = ProductVariant.objects.create(
            product=cls.product, name="Variant", sku="V"
        )
        cls.inventory = Inventory.objects.create(
            variant=cls.variant, quantity=10, reserved=4
        )
        cls.other_product = Product.objects.create(
            merchant=cls.merchant, category=category, name="Other", sku="O"
        )
        cls.foreign_merchant = Merchant.objects.create(name="Other", slug="other-stock")
        foreign_category = Category.objects.create(
            merchant=cls.foreign_merchant, name="Other"
        )
        cls.foreign_product = Product.objects.create(
            merchant=cls.foreign_merchant,
            category=foreign_category,
            name="Foreign",
            sku="F",
        )
        cls.foreign_variant = ProductVariant.objects.create(
            product=cls.foreign_product, name="Foreign", sku="F"
        )
        cls.foreign_inventory = Inventory.objects.create(
            variant=cls.foreign_variant, quantity=20
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def url(self, product=None, variant=None, merchant=None):
        return (
            reverse(
                "inventory-adjustment",
                kwargs={
                    "pk": product or self.product.pk,
                    "variant_id": variant or self.variant.pk,
                },
            )
            + f"?merchant_id={merchant or self.merchant.pk}"
        )

    def post(self, body=None, **kwargs):
        return self.client.post(
            self.url(**kwargs),
            body if body is not None else {"delta": -3, "reason": "  Physical count  "},
            format="json",
        )

    def assert_unchanged(self):
        self.inventory.refresh_from_db()
        self.foreign_inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 10)
        self.assertEqual(self.foreign_inventory.quantity, 20)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_success_returns_authoritative_inventory_and_accurate_audit(self):
        response = self.post()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data["inventory"],
            {"id": self.inventory.pk, "quantity": 7, "reserved": 4, "available": 3},
        )
        event = AuditLog.objects.get()
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 7)
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.product, self.product)
        self.assertEqual(event.action, "inventory.adjusted")
        self.assertEqual(
            event.details,
            {
                "schema_version": 1,
                "variant_id": self.variant.pk,
                "variant_sku": "V",
                "variant_name": "Variant",
                "operator_id": self.user.pk,
                "operator_username": "stock-operator",
                "delta": -3,
                "reason": "Physical count",
                "quantity_before": 10,
                "quantity_after": 7,
                "reserved": 4,
            },
        )
        self.assertEqual(
            response.data["adjustment"],
            {
                "id": event.pk,
                "variant_id": self.variant.pk,
                "delta": -3,
                "reason": "Physical count",
                "quantity_before": 10,
                "quantity_after": 7,
                "actor": {"id": self.user.pk, "username": "stock-operator"},
                "created_at": event.created_at.isoformat(),
            },
        )

    def test_increment_and_exact_reserved_boundary(self):
        self.assertEqual(self.post({"delta": 2, "reason": "Delivery"}).status_code, 201)
        self.assertEqual(self.post({"delta": -8, "reason": "Count"}).status_code, 201)
        self.inventory.refresh_from_db()
        self.assertEqual((self.inventory.quantity, self.inventory.reserved), (4, 4))
        self.assertEqual(AuditLog.objects.count(), 2)

    def test_strict_delta_validation(self):
        for delta in [
            0,
            True,
            False,
            1.0,
            1.5,
            "2",
            None,
            [],
            {},
            2147483648,
            -2147483648,
        ]:
            with self.subTest(delta=delta):
                self.assertEqual(
                    self.post({"delta": delta, "reason": "Count"}).status_code, 400
                )
                self.assert_unchanged()
        self.assertEqual(self.post({"reason": "Count"}).status_code, 400)

    def test_strict_reason_validation(self):
        for reason in ["", " \t\n", None, 12, True, [], {}, "x" * 501]:
            with self.subTest(reason=reason):
                self.assertEqual(
                    self.post({"delta": 1, "reason": reason}).status_code, 400
                )
                self.assert_unchanged()
        self.assertEqual(self.post({"delta": 1}).status_code, 400)
        self.assertEqual(
            self.post({"delta": 1, "reason": " " + "x" * 500 + " "}).status_code, 201
        )

    def test_rejects_unknown_and_client_controlled_fields(self):
        for field in ["actor", "quantity", "reserved", "variant_id", "unexpected"]:
            with self.subTest(field=field):
                self.assertEqual(
                    self.post({"delta": 1, "reason": "Count", field: 1}).status_code,
                    400,
                )
                self.assert_unchanged()

    def test_stock_and_overflow_conflicts(self):
        for delta, code in [
            (-7, "insufficient_stock"),
            (2147483647, "quantity_out_of_range"),
        ]:
            with self.subTest(delta=delta):
                response = self.post({"delta": delta, "reason": "Count"})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.data["code"], code)
                self.assert_unchanged()

    def test_anonymous_and_nonmember_rejected(self):
        for user in [None, self.outsider]:
            self.client.force_authenticate(user)
            self.assertEqual(self.post().status_code, 403 if user is None else 404)
            self.assert_unchanged()

    def test_scoped_target_resolution(self):
        for kwargs in [
            {"merchant": self.foreign_merchant.pk},
            {"product": self.foreign_product.pk, "variant": self.foreign_variant.pk},
            {"variant": self.foreign_variant.pk},
            {"product": self.other_product.pk},
            {"variant": 999999},
        ]:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.post(**kwargs).status_code, 404)
                self.assert_unchanged()

    def test_missing_inventory_is_not_created(self):
        self.inventory.delete()
        self.assertEqual(self.post().status_code, 404)
        self.assertFalse(Inventory.objects.filter(variant=self.variant).exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_merchant_parameter_validation(self):
        base = self.url().split("?")[0]
        for suffix in [
            "",
            "?merchant_id=",
            "?merchant_id=abc",
            "?merchant_id=0",
            "?merchant_id=-1",
        ]:
            self.assertEqual(
                self.client.post(
                    base + suffix, {"delta": 1, "reason": "Count"}, format="json"
                ).status_code,
                400,
            )
        self.assert_unchanged()

    def test_malformed_body_and_method(self):
        for body in [[], "invalid", None]:
            self.assertEqual(
                self.client.post(self.url(), body, format="json").status_code, 400
            )
        self.assertEqual(self.client.get(self.url()).status_code, 405)
        self.assert_unchanged()

    def test_audit_error_rolls_back_stock(self):
        with patch(
            "catalog.services.inventory.AuditLog.objects.create",
            side_effect=RuntimeError("Audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.post()
        self.assert_unchanged()

    def test_real_session_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/login/")
        client.force_login(self.user)
        body = {"delta": 1, "reason": "Count"}
        self.assertEqual(client.post(self.url(), body, format="json").status_code, 403)
        self.assert_unchanged()
        token = client.cookies["csrftoken"].value
        self.assertEqual(
            client.post(
                self.url(), body, format="json", HTTP_X_CSRFTOKEN="incorrect"
            ).status_code,
            403,
        )
        self.assert_unchanged()
        self.assertEqual(
            client.post(
                self.url(), body, format="json", HTTP_X_CSRFTOKEN=token
            ).status_code,
            201,
        )
