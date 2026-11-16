"""Read-only fixture discovery and diagnostic query counts; never a latency test."""

import json
import platform
from collections import Counter
from urllib.parse import urlencode

import django
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Count, Q
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from catalog.models import AuditLog, Inventory, Merchant, Product, ProductVariant


class Command(BaseCommand):
    help = "Discover authorized benchmark fixtures and profile read API query counts."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--merchant-slug", default="assessment-merchant-01")

    def handle(self, *args, **options):
        try:
            user = get_user_model().objects.get(username=options["username"])
            merchant = Merchant.objects.get(slug=options["merchant_slug"], members=user)
        except (get_user_model().DoesNotExist, Merchant.DoesNotExist) as exc:
            raise CommandError(
                "Benchmark user or authorized merchant not found."
            ) from exc

        products = Product.objects.filter(merchant=merchant).annotate(
            variant_count=Count("variants")
        )
        ordinary = products.filter(variant_count=2).order_by("id").first()
        complex_products = [
            products.filter(variant_count=count).order_by("id").first()
            for count in (25, 50)
        ]
        if ordinary is None or any(p is None for p in complex_products):
            raise CommandError("Run seed_catalog and seed_complex_products first.")

        selected = [ordinary, *complex_products]
        total = products.count()
        last_page = (total + 24) // 25
        pages = sorted({1, (last_page + 1) // 2, last_page})
        scenarios = []

        def add(name, path, kind, **expected):
            scenarios.append({"name": name, "path": path, "kind": kind, **expected})

        for page in pages:
            expected_ids = list(
                products.order_by("id").values_list("id", flat=True)[
                    (page - 1) * 25 : page * 25
                ]
            )
            add(
                f"catalogue_page_{page}",
                f"/api/products/?page={page}",
                "list",
                ids=expected_ids,
                count=total,
                page=page,
            )
        for label, term in (
            ("common", "Assessment"),
            ("selective", ordinary.sku),
            ("none", "benchmark-no-such-product-938174"),
        ):
            # Same predicates as the existing API, including database collation.
            matches = products.filter(Q(name__icontains=term) | Q(sku__icontains=term))
            add(
                f"search_{label}",
                "/api/products/?" + urlencode({"search": term}),
                "list",
                ids=list(matches.order_by("id").values_list("id", flat=True)[:25]),
                count=matches.count(),
                search=term,
            )
        for product in selected:
            add(
                f"editor_{product.variant_count}_variants",
                f"/api/products/{product.pk}/editor/",
                "editor",
                id=product.pk,
                variants=product.variant_count,
            )
        activity_product = (
            products.annotate(log_count=Count("activity", distinct=True))
            .order_by("-log_count", "id")
            .first()
        )
        activity_count = AuditLog.objects.filter(product=activity_product).count()
        for page in sorted({1, max(1, (activity_count + 24) // 25)}):
            add(
                f"activity_page_{page}",
                f"/api/products/{activity_product.pk}/activity/?page={page}",
                "activity",
                count=activity_count,
                page=page,
            )

        # Force-authentication isolates endpoint SQL. k6/browser use real sessions.
        client = APIClient()
        client.force_authenticate(user)
        profiles = []
        for scenario in scenarios:
            separator = "&" if "?" in scenario["path"] else "?"
            path = scenario["path"] + separator + f"merchant_id={merchant.pk}"
            with CaptureQueriesContext(connection) as captured:
                response = client.get(path, HTTP_HOST="localhost")
                response.render()
            if response.status_code != 200:
                raise CommandError(
                    f"Preflight failed: {scenario['name']} ({response.status_code})"
                )
            # Record SQL shapes/counts, never SQL text that could contain user data.
            operations = Counter(q["sql"].split()[0].upper() for q in captured)
            profiles.append(
                {
                    "scenario": scenario["name"],
                    "queries": len(captured),
                    "operations": dict(operations),
                    "response_bytes": len(response.content),
                }
            )

        self.stdout.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "merchant_id": merchant.pk,
                    "fixtures": {
                        "products": total,
                        "variants": ProductVariant.objects.filter(
                            product__merchant=merchant
                        ).count(),
                        "inventory": Inventory.objects.filter(
                            variant__product__merchant=merchant
                        ).count(),
                        "activity_records": AuditLog.objects.filter(
                            product__merchant=merchant
                        ).count(),
                        "editor_products": [
                            {"id": p.pk, "variants": p.variant_count} for p in selected
                        ],
                    },
                    "environment": {
                        "python": platform.python_version(),
                        "django": django.get_version(),
                        "database_vendor": connection.vendor,
                        "database_version": list(connection.get_database_version()),
                        "debug": settings.DEBUG,
                    },
                    "scenarios": scenarios,
                    "query_profiles": profiles,
                    "notes": [
                        "Diagnostic ORM query capture; timings intentionally excluded.",
                        "Forced authentication excludes session/authentication SQL.",
                        "No fixtures modified. Sparse activity history is not a scale benchmark.",
                    ],
                },
                indent=2,
            )
        )
