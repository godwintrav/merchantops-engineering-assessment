from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import Category, Merchant, Product


class ProductListAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="alice",
            password="test-password",
        )

        cls.merchant = Merchant.objects.create(
            name="Northstar Retail",
            slug="northstar",
        )
        cls.other_merchant = Merchant.objects.create(
            name="Summit Supplies",
            slug="summit",
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
            name="Laptop",
            sku="LAP-001",
            status=Product.Status.ACTIVE,
        )
        cls.other_product = Product.objects.create(
            merchant=cls.other_merchant,
            category=other_category,
            name="Other Laptop",
            sku="LAP-002",
        )

        cls.url = reverse("product-list")

    def setUp(self):
        self.client.force_login(self.user)

    def test_member_can_list_merchant_products(self):
        response = self.client.get(
            self.url,
            {"merchant_id": self.merchant.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        product = response.data["results"][0]

        self.assertEqual(product["id"], self.product.pk)
        self.assertEqual(product["sku"], "LAP-001")
        self.assertEqual(product["category"], "Electronics")

    def test_other_merchants_products_are_excluded(self):
        response = self.client.get(
            self.url,
            {"merchant_id": self.merchant.pk},
        )

        returned_ids = {item["id"] for item in response.data["results"]}

        self.assertNotIn(
            self.other_product.pk,
            returned_ids,
        )

    def test_nonmember_cannot_access_merchant(self):
        response = self.client.get(
            self.url,
            {"merchant_id": self.other_merchant.pk},
        )

        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_user_is_rejected(self):
        self.client.logout()

        response = self.client.get(
            self.url,
            {"merchant_id": self.merchant.pk},
        )

        self.assertIn(response.status_code, (401, 403))

    def test_missing_merchant_id_is_rejected(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 400)

    def test_invalid_merchant_id_is_rejected(self):
        response = self.client.get(
            self.url,
            {"merchant_id": "invalid"},
        )

        self.assertEqual(response.status_code, 400)

    def test_search_filters_products(self):
        response = self.client.get(
            self.url,
            {
                "merchant_id": self.merchant.pk,
                "search": "Laptop",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        response = self.client.get(
            self.url,
            {
                "merchant_id": self.merchant.pk,
                "search": "Nonexistent",
            },
        )

        self.assertEqual(response.data["count"], 0)

    def test_results_are_paginated(self):
        category = self.product.category

        Product.objects.bulk_create(
            [
                Product(
                    merchant=self.merchant,
                    category=category,
                    name=f"Additional Product {number}",
                    sku=f"ADD-{number:03d}",
                )
                for number in range(30)
            ]
        )

        response = self.client.get(
            self.url,
            {"merchant_id": self.merchant.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 31)
        self.assertEqual(len(response.data["results"]), 25)

        second = self.client.get(
            self.url,
            {
                "merchant_id": self.merchant.pk,
                "page": 2,
            },
        )

        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(second.data["results"]), 6)

    def test_query_budget_is_constant_across_page_sizes_and_search(self):
        client = APIClient()
        client.force_authenticate(self.user)
        params = {"merchant_id": self.merchant.pk}

        # Excludes authentication/fixture setup, matching benchmark_profile.
        with self.assertNumQueries(3):
            response = client.get(self.url, params)
            response.render()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["category"], "Electronics")

        additional = []
        for number in range(30):
            category = Category.objects.create(
                merchant=self.merchant, name=f"Category {number:02d}"
            )
            additional.append(
                Product.objects.create(
                    merchant=self.merchant,
                    category=category,
                    name=f"Additional Product {number:02d}",
                    sku=f"ADD-{number:03d}",
                    image_url="/product-images/laptop.webp",
                )
            )

        cases = [
            ({}, 31, [self.product, *additional[:24]], 3),
            ({"page": 2}, 31, additional[24:], 3),
            ({"search": "ADD-"}, 30, additional[:25], 3),
            ({"search": "no-such-product"}, 0, [], 2),
        ]
        for query, count, expected, budget in cases:
            with self.subTest(query=query):
                with self.assertNumQueries(budget):
                    response = client.get(self.url, {**params, **query})
                    response.render()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], count)
                self.assertEqual(
                    response.data["results"],
                    [
                        {
                            "id": product.pk,
                            "name": product.name,
                            "sku": product.sku,
                            "status": product.status,
                            "category": product.category.name,
                            "image_url": product.image_url,
                        }
                        for product in expected
                    ],
                )
