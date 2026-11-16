from uuid import UUID

from django.db import OperationalError, transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import (
    AuditLog,
    Availability,
    Inventory,
    Merchant,
    PriceRule,
    Product,
    ProductVariant,
)
from catalog.serializers import (
    InventoryAdjustmentSerializer,
    ProductActivitySerializer,
    ProductListSerializer,
    ProductUpdateSerializer,
)
from catalog.services.inventory import InventoryConflict, adjust_inventory


class ProductPagination(PageNumberPagination):
    page_size = 25


class ProductListView(generics.ListAPIView):
    serializer_class = ProductListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProductPagination

    def get_queryset(self):
        merchant_id = self.request.query_params.get("merchant_id")

        if not merchant_id:
            raise ValidationError({"merchant_id": "This parameter is required."})

        try:
            merchant_id = int(merchant_id)
        except (TypeError, ValueError):
            raise ValidationError({"merchant_id": "Must be a valid integer."})

        if merchant_id <= 0:
            raise ValidationError({"merchant_id": "Must be a positive integer."})

        get_object_or_404(
            Merchant.objects.filter(members=self.request.user),
            pk=merchant_id,
        )

        queryset = (
            Product.objects.filter(merchant_id=merchant_id)
            .select_related("category")
            .order_by("id")
        )

        search = self.request.query_params.get("search", "").strip()

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(sku__icontains=search)
            )

        return queryset


class ProductEditorView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        merchant_id = request.query_params.get("merchant_id")

        if not merchant_id:
            raise ValidationError({"merchant_id": "This parameter is required."})

        try:
            merchant_id = int(merchant_id)
        except (TypeError, ValueError):
            raise ValidationError({"merchant_id": "Must be a valid integer."})

        if merchant_id <= 0:
            raise ValidationError({"merchant_id": "Must be a positive integer."})

        get_object_or_404(
            Merchant.objects.filter(members=request.user),
            pk=merchant_id,
        )

        product = get_object_or_404(
            Product.objects.select_related("category"),
            pk=pk,
            merchant_id=merchant_id,
        )

        variants = list(
            ProductVariant.objects.filter(product_id=product.pk)
            .select_related("inventory")
            .prefetch_related(
                Prefetch(
                    "price_rules",
                    queryset=PriceRule.objects.order_by("id"),
                    to_attr="ordered_prices",
                )
            )
            .order_by("id")
        )

        prices_by_variant = {}
        inventory_by_variant = {}

        for variant in variants:
            prices_by_variant[variant.pk] = [
                {
                    "id": price.pk,
                    "tier": price.tier,
                    "amount": f"{price.amount:.2f}",
                }
                for price in variant.ordered_prices
            ]

            try:
                inventory = variant.inventory
            except Inventory.DoesNotExist:
                inventory = None

            inventory_by_variant[variant.pk] = (
                {
                    "id": inventory.pk,
                    "quantity": inventory.quantity,
                    "reserved": inventory.reserved,
                }
                if inventory
                else None
            )

        availability = list(
            Availability.objects.filter(product_id=product.pk)
            .order_by("id")
            .values(
                "id",
                "channel",
                "enabled",
            )
        )

        return Response(
            {
                "id": product.pk,
                "name": product.name,
                "sku": product.sku,
                "description": product.description,
                "status": product.status,
                "image_url": product.image_url,
                "category": {
                    "id": product.category_id,
                    "name": product.category.name,
                },
                "variants": [
                    {
                        "id": variant.pk,
                        "name": variant.name,
                        "sku": variant.sku,
                        "prices": prices_by_variant[variant.pk],
                        "inventory": inventory_by_variant.get(variant.pk),
                    }
                    for variant in variants
                ],
                "availability": availability,
            }
        )


class ProductDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = ProductUpdateSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = [
        "get",
        "patch",
        "head",
        "options",
    ]

    def get_queryset(self):
        merchant_id = self.request.query_params.get("merchant_id")

        if not merchant_id:
            raise ValidationError({"merchant_id": "This parameter is required."})

        try:
            merchant_id = int(merchant_id)
        except (TypeError, ValueError):
            raise ValidationError({"merchant_id": "Must be a valid integer."})

        if merchant_id <= 0:
            raise ValidationError({"merchant_id": "Must be a positive integer."})

        get_object_or_404(
            Merchant.objects.filter(members=self.request.user),
            pk=merchant_id,
        )

        return Product.objects.filter(merchant_id=merchant_id).select_related(
            "category"
        )

    def perform_update(self, serializer):
        tracked_fields = (
            "name",
            "sku",
            "description",
            "status",
            "category_id",
            "image_url",
        )

        with transaction.atomic():
            product = serializer.instance

            # Lock the row before comparing old and new values.
            locked_product = Product.objects.select_for_update().get(pk=product.pk)

            before = {field: getattr(locked_product, field) for field in tracked_fields}

            # Use the locked instance for the actual update.
            serializer.instance = locked_product
            updated_product = serializer.save()

            changes = {}

            for field in tracked_fields:
                old_value = before[field]
                new_value = getattr(updated_product, field)

                if old_value != new_value:
                    changes[field] = {
                        "from": old_value,
                        "to": new_value,
                    }

            if changes:
                AuditLog.objects.create(
                    product=updated_product,
                    actor=self.request.user,
                    action="product.updated",
                    details={"changes": changes},
                )


class ProductActivityView(generics.ListAPIView):
    serializer_class = ProductActivitySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = ProductPagination

    def get_queryset(self):
        merchant_id = self.request.query_params.get("merchant_id")

        if not merchant_id:
            raise ValidationError({"merchant_id": "This parameter is required."})

        try:
            merchant_id = int(merchant_id)
        except (TypeError, ValueError):
            raise ValidationError({"merchant_id": "Must be a valid integer."})

        if merchant_id <= 0:
            raise ValidationError({"merchant_id": "Must be a positive integer."})

        get_object_or_404(
            Merchant.objects.filter(members=self.request.user),
            pk=merchant_id,
        )

        product = get_object_or_404(
            Product.objects.filter(merchant_id=merchant_id),
            pk=self.kwargs["pk"],
        )

        return (
            AuditLog.objects.filter(product_id=product.pk)
            .select_related("actor")
            .order_by("-created_at", "-id")
        )


class InventoryAdjustmentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk, variant_id):
        merchant_id = request.query_params.get("merchant_id")
        if merchant_id is None:
            raise ValidationError({"merchant_id": "This parameter is required."})
        try:
            merchant_id = int(merchant_id)
        except (TypeError, ValueError):
            raise ValidationError({"merchant_id": "Must be a valid integer."})
        if merchant_id <= 0:
            raise ValidationError({"merchant_id": "Must be a positive integer."})
        get_object_or_404(Merchant.objects.filter(members=request.user), pk=merchant_id)
        product = get_object_or_404(
            Product.objects.filter(merchant_id=merchant_id), pk=pk
        )
        variant = get_object_or_404(
            ProductVariant.objects.filter(product_id=product.pk), pk=variant_id
        )
        operation_key = request.headers.get("Idempotency-Key")
        if operation_key is not None:
            try:
                operation_key = UUID(operation_key)
            except (ValueError, AttributeError):
                raise ValidationError({"idempotency_key": "Must be a valid UUID."})
        serializer = InventoryAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = adjust_inventory(
                variant=variant,
                actor=request.user,
                operation_key=operation_key,
                **serializer.validated_data,
            )
        except OperationalError as error:
            if not error.args or error.args[0] not in (1205, 1213):
                raise
            return Response(
                {
                    "code": "inventory_busy",
                    "detail": "Inventory is busy. Retry the same adjustment with the same operation key.",
                },
                status=503,
                headers={"Retry-After": "1"},
            )
        except InventoryConflict as conflict:
            return Response(
                {"code": conflict.code, "detail": conflict.detail}, status=409
            )
        return Response(result, status=200 if result["replayed"] else 201)
