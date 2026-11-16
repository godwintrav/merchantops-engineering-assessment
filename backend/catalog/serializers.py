import re

from rest_framework import serializers

from catalog.models import AuditLog, Category, Product


class ProductListSerializer(serializers.ModelSerializer):
    category = serializers.CharField(
        source="category.name",
        read_only=True,
    )

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "sku",
            "status",
            "category",
            "image_url",
        ]


class ProductUpdateSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(),
    )

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "sku",
            "description",
            "status",
            "category",
            "image_url",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        allowed = set(self.fields)
        unexpected = set(self.initial_data) - allowed

        # Read-only fields must not be submitted either.
        unexpected |= set(self.initial_data) & {"id"}

        if unexpected:
            raise serializers.ValidationError(
                {
                    field: "This field cannot be modified."
                    for field in sorted(unexpected)
                }
            )

        return attrs

    def validate_sku(self, value):
        product = self.instance

        duplicates = Product.objects.filter(
            merchant_id=product.merchant_id,
            sku=value,
        ).exclude(pk=product.pk)

        if duplicates.exists():
            raise serializers.ValidationError(
                "A product with this SKU already exists " "for this merchant."
            )

        return value

    def validate_category(self, category):
        if category.merchant_id != self.instance.merchant_id:
            raise serializers.ValidationError(
                "Category does not belong to this merchant."
            )

        return category

    def validate_image_url(self, value):
        if value and not re.fullmatch(
            r"/product-images/[a-z0-9][a-z0-9_-]*\.webp",
            value,
        ):
            raise serializers.ValidationError(
                "Expected a local /product-images/*.webp path."
            )

        return value


class ProductActivitySerializer(serializers.ModelSerializer):
    actor = serializers.CharField(
        source="actor.username",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor",
            "action",
            "details",
            "created_at",
        ]


class StrictAdjustmentDeltaField(serializers.Field):
    def to_internal_value(self, value):
        if type(value) is not int or value == 0:
            raise serializers.ValidationError("Must be a nonzero JSON integer.")
        if not -2147483647 <= value <= 2147483647:
            raise serializers.ValidationError("Amount is outside the supported range.")
        return value


class StrictAdjustmentReasonField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("Must be a string.")
        return super().to_internal_value(data)


class InventoryAdjustmentSerializer(serializers.Serializer):
    delta = StrictAdjustmentDeltaField()
    reason = StrictAdjustmentReasonField(max_length=500, trim_whitespace=True)

    def validate(self, attrs):
        unexpected = set(self.initial_data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(
                {field: "This field is not accepted." for field in sorted(unexpected)}
            )
        return attrs
