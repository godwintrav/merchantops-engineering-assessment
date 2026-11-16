from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import (
    AuditLog,
    Category,
    Merchant,
    Product,
)


class ProductActivityAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="activity-user",
            password="test-password",
        )

        cls.merchant = Merchant.objects.create(
            name="Activity Merchant",
            slug="activity-merchant",
        )
        cls.other_merchant = Merchant.objects.create(
            name="Private Merchant",
            slug="private-activity-merchant",
        )

        cls.merchant.members.add(cls.user)

        category = Category.objects.create(
            merchant=cls.merchant,
            name="Electronics",
        )
        private_category = Category.objects.create(
            merchant=cls.other_merchant,
            name="Electronics",
        )

        cls.product = Product.objects.create(
            merchant=cls.merchant,
            category=category,
            name="Workstation",
            sku="ACT-001",
        )
        cls.private_product = Product.objects.create(
            merchant=cls.other_merchant,
            category=private_category,
            name="Private Workstation",
            sku="ACT-PRIVATE",
        )

        cls.first_log = AuditLog.objects.create(
            product=cls.product,
            actor=cls.user,
            action="product.created",
            details={"name": "Workstation"},
        )
        cls.second_log = AuditLog.objects.create(
            product=cls.product,
            actor=cls.user,
            action="product.updated",
            details={"field": "name"},
        )

        now = timezone.now()

        AuditLog.objects.filter(pk=cls.first_log.pk).update(
            created_at=now - timedelta(days=1)
        )

        AuditLog.objects.filter(pk=cls.second_log.pk).update(created_at=now)

        AuditLog.objects.create(
            product=cls.private_product,
            action="product.created",
            details={"private": True},
        )

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, product):
        return reverse(
            "product-activity",
            kwargs={"pk": product.pk},
        )

    def test_member_can_read_activity(self):
        response = self.client.get(
            self.url(self.product),
            {"merchant_id": self.merchant.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

        records = response.data["results"]

        self.assertEqual(
            records[0]["action"],
            "product.updated",
        )
        self.assertEqual(
            records[1]["action"],
            "product.created",
        )
        self.assertEqual(
            records[0]["details"],
            {"field": "name"},
        )

    def test_other_merchant_activity_is_inaccessible(self):
        response = self.client.get(
            self.url(self.private_product),
            {"merchant_id": self.merchant.pk},
        )

        self.assertEqual(response.status_code, 404)

    def test_nonmember_merchant_is_inaccessible(self):
        response = self.client.get(
            self.url(self.private_product),
            {"merchant_id": self.other_merchant.pk},
        )

        self.assertEqual(response.status_code, 404)

    def test_missing_merchant_context_rejected(self):
        response = self.client.get(
            self.url(self.product),
        )

        self.assertEqual(response.status_code, 400)

    def test_unauthenticated_access_rejected(self):
        self.client.logout()

        response = self.client.get(
            self.url(self.product),
            {"merchant_id": self.merchant.pk},
        )

        self.assertIn(response.status_code, (401, 403))

    def test_activity_is_paginated(self):
        AuditLog.objects.bulk_create(
            [
                AuditLog(
                    product=self.product,
                    actor=self.user,
                    action="product.updated",
                    details={"number": number},
                )
                for number in range(30)
            ]
        )

        # Equal timestamps must retain a deterministic ID tiebreaker across pages.
        AuditLog.objects.filter(product=self.product).update(created_at=timezone.now())
        expected_ids = list(
            AuditLog.objects.filter(product=self.product)
            .order_by("-id")
            .values_list("id", flat=True)
        )

        response = self.client.get(
            self.url(self.product),
            {"merchant_id": self.merchant.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 32)
        self.assertEqual(
            len(response.data["results"]),
            25,
        )

        second = self.client.get(
            self.url(self.product),
            {
                "merchant_id": self.merchant.pk,
                "page": 2,
            },
        )

        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            len(second.data["results"]),
            7,
        )

        self.assertEqual(
            [record["id"] for record in response.data["results"]]
            + [record["id"] for record in second.data["results"]],
            expected_ids,
        )
