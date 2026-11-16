"""Run inside the backend container via stdin, after timed tests have finished."""

import argparse
import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.db.models import Q

from catalog.models import AuditLog, Merchant, Product, ProductVariant

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("merchant_slug", nargs="?", default="assessment-merchant-01")
parser.add_argument("--eager", action="store_true", help="Explain optimized joins")
args = parser.parse_args()
merchant = Merchant.objects.get(slug=args.merchant_slug)
products = Product.objects.filter(merchant=merchant).order_by("id")
if args.eager:
    products = products.select_related("category")
product = products.first()
if product is None:
    raise SystemExit("Seed the catalogue before capturing query plans")

variants = ProductVariant.objects.filter(product=product).order_by("id")
if args.eager:
    variants = variants.select_related("inventory")

cases = {
    "catalogue_first_page": products[:25],
    "catalogue_last_page": products[((products.count() - 1) // 25) * 25 :],
    "search_common": products.filter(
        Q(name__icontains="Assessment") | Q(sku__icontains="Assessment")
    )[:25],
    "search_selective": products.filter(
        Q(name__icontains="ASSESS-000005") | Q(sku__icontains="ASSESS-000005")
    )[:25],
    "search_none": products.filter(
        Q(name__icontains="benchmark-no-such-product-938174")
        | Q(sku__icontains="benchmark-no-such-product-938174")
    )[:25],
    "editor_variants": variants,
    "activity": AuditLog.objects.filter(product=product)
    .select_related("actor")
    .order_by("-created_at", "-id")[:25],
}


def explain(queryset):
    plan = queryset.explain(format="JSON")
    # Django/MySQL versions may wrap the server JSON in a JSON string.
    while isinstance(plan, str):
        plan = json.loads(plan)
    return plan


print(
    json.dumps(
        {
            "merchant_id": merchant.pk,
            "query_mode": "optimized_joins" if args.eager else "original_base_queries",
            "notes": [
                "Read-only ORM EXPLAIN JSON, captured outside timing runs.",
                "Optimizer estimates, not measured execution durations or EXPLAIN ANALYZE.",
                "Base-query shapes only; all round trips are counted by benchmark_profile.",
                "--eager includes category/inventory joins; price prefetch is a separate query.",
                "Fixed fixture search terms mirror this benchmark suite.",
            ],
            "plans": {name: explain(queryset) for name, queryset in cases.items()},
        },
        indent=2,
    )
)
