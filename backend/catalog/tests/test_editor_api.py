from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import (
    Availability,
    Category,
    Inventory,
    Merchant,
    PriceRule,
    Product,
    ProductVariant,
)


class ProductEditorAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="editor-user",
            password="test-password",
        )

        cls.merchant = Merchant.objects.create(
            name="Editor Merchant",
            slug="editor-merchant",
        )
        cls.other_merchant = Merchant.objects.create(
            name="Other Merchant",
            slug="other-editor-merchant",
        )
        cls.merchant.members.add(cls.user)

        category = Category.objects.create(
            merchant=cls.merchant,
            name="Electronics",
        )
        other_category = Category.objects.create(
            merchant=cls.other_merchant,
            name="Electronics",
        )

        cls.product = Product.objects.create(
            merchant=cls.merchant,
            category=category,
            name="Workstation",
            sku="WORK-001",
            description="Development workstation",
        )

        cls.other_product = Product.objects.create(
            merchant=cls.other_merchant,
            category=other_category,
            name="Private Product",
            sku="PRIVATE-001",
        )

        variant = ProductVariant.objects.create(
            product=cls.product,
            name="16GB RAM",
            sku="WORK-001-16",
        )
        PriceRule.objects.create(
            variant=variant,
            tier="retail",
            amount=Decimal("1299.00"),
        )
        Inventory.objects.create(
            variant=variant,
            quantity=20,
            reserved=3,
        )
        Availability.objects.create(
            product=cls.product,
            channel="online",
            enabled=True,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def editor_url(self, product):
        return reverse(
            "product-editor",
            kwargs={"pk": product.pk},
        )

    def test_editor_returns_related_data(self):
        response = self.client.get(
            self.editor_url(self.product),
            {"merchant_id": self.merchant.pk},
        )

        self.assertEqual(response.status_code, 200)

        data = response.data

        self.assertEqual(data["id"], self.product.pk)
        self.assertEqual(data["name"], "Workstation")
        self.assertEqual(
            data["description"],
            "Development workstation",
        )
        self.assertEqual(data["category"]["name"], "Electronics")

        self.assertEqual(len(data["variants"]), 1)
        variant = data["variants"][0]

        self.assertEqual(variant["sku"], "WORK-001-16")
        self.assertEqual(
            variant["prices"][0]["amount"],
            "1299.00",
        )
        self.assertEqual(variant["inventory"]["quantity"], 20)
        self.assertEqual(variant["inventory"]["reserved"], 3)

        self.assertEqual(len(data["availability"]), 1)
        self.assertEqual(
            data["availability"][0]["channel"],
            "online",
        )

    def test_other_merchant_product_is_inaccessible(self):
        response = self.client.get(
            self.editor_url(self.other_product),
            {"merchant_id": self.merchant.pk},
        )
        self.assertEqual(response.status_code, 404)

    def test_nonmember_merchant_is_inaccessible(self):
        response = self.client.get(
            self.editor_url(self.other_product),
            {"merchant_id": self.other_merchant.pk},
        )
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_user_is_rejected(self):
        self.client.logout()

        response = self.client.get(
            self.editor_url(self.product),
            {"merchant_id": self.merchant.pk},
        )
        self.assertIn(response.status_code, (401, 403))

    def test_missing_merchant_context_is_rejected(self):
        response = self.client.get(
            self.editor_url(self.product),
        )
        self.assertEqual(response.status_code, 400)

    def test_editor_query_budget_and_payload_across_variant_counts(self):
        client = APIClient()
        client.force_authenticate(self.user)
        category = self.product.category

        foreign_variant = ProductVariant.objects.create(
            product=self.other_product, name="Private variant", sku="PRIVATE-V1"
        )
        PriceRule.objects.create(
            variant=foreign_variant, tier="private", amount=Decimal("999.99")
        )
        Inventory.objects.create(variant=foreign_variant, quantity=999)

        for count in (0, 2, 25, 50):
            with self.subTest(variants=count):
                product = Product.objects.create(
                    merchant=self.merchant,
                    category=category,
                    name=f"Batch product {count}",
                    sku=f"BATCH-{count}",
                    description="Query budget fixture",
                )
                expected_variants = []
                for number in range(count):
                    # Names/SKUs run opposite to ID order.
                    variant = ProductVariant.objects.create(
                        product=product,
                        name=f"Variant {count - number:03d}",
                        sku=f"BATCH-{count}-V{count - number:03d}",
                    )
                    prices = []
                    if number != 1:
                        for tier, amount in (
                            ("wholesale", Decimal("12.34") + number),
                            ("retail", Decimal("56.78") + number),
                        ):
                            price = PriceRule.objects.create(
                                variant=variant, tier=tier, amount=amount
                            )
                            prices.append(
                                {
                                    "id": price.pk,
                                    "tier": tier,
                                    "amount": f"{amount:.2f}",
                                }
                            )
                    inventory_data = None
                    if number != 0:
                        inventory = Inventory.objects.create(
                            variant=variant, quantity=number + 10, reserved=number
                        )
                        inventory_data = {
                            "id": inventory.pk,
                            "quantity": inventory.quantity,
                            "reserved": inventory.reserved,
                        }
                    expected_variants.append(
                        {
                            "id": variant.pk,
                            "name": variant.name,
                            "sku": variant.sku,
                            "prices": prices,
                            "inventory": inventory_data,
                        }
                    )
                availability = []
                if count:
                    for channel, enabled in (("webstore", True), ("amazon", False)):
                        record = Availability.objects.create(
                            product=product, channel=channel, enabled=enabled
                        )
                        availability.append(
                            {"id": record.pk, "channel": channel, "enabled": enabled}
                        )

                # Fixtures/authentication are outside capture. No variants means
                # Django skips the price prefetch, reducing the budget to four.
                with self.assertNumQueries(5 if count else 4):
                    response = client.get(
                        self.editor_url(product), {"merchant_id": self.merchant.pk}
                    )
                    response.render()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.data,
                    {
                        "id": product.pk,
                        "name": product.name,
                        "sku": product.sku,
                        "description": product.description,
                        "status": product.status,
                        "category": {"id": category.pk, "name": category.name},
                        "variants": expected_variants,
                        "availability": availability,
                    },
                )
