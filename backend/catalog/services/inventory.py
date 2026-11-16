"""Apply a relative stock correction and its audit event as one operation."""

from django.db import transaction
from django.shortcuts import get_object_or_404

from catalog.models import AuditLog, Inventory

MAX_QUANTITY = 2147483647


class InventoryConflict(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def adjust_inventory(*, variant, actor, delta, reason):
    with transaction.atomic():
        inventory = get_object_or_404(
            Inventory.objects.select_for_update(), variant_id=variant.pk
        )
        before = inventory.quantity
        after = before + delta
        if after < inventory.reserved:
            raise InventoryConflict(
                "insufficient_stock", "Quantity cannot fall below reserved stock."
            )
        if after > MAX_QUANTITY:
            raise InventoryConflict(
                "quantity_out_of_range", "Quantity exceeds the supported limit."
            )
        inventory.quantity = after
        inventory.save(update_fields=["quantity"])
        audit = AuditLog.objects.create(
            product_id=variant.product_id,
            actor=actor,
            action="inventory.adjusted",
            details={
                "schema_version": 1,
                "variant_id": variant.pk,
                "variant_sku": variant.sku,
                "variant_name": variant.name,
                "operator_id": actor.pk,
                "operator_username": actor.get_username(),
                "reason": reason,
                "delta": delta,
                "quantity_before": before,
                "quantity_after": after,
                "reserved": inventory.reserved,
            },
        )
        result = {
            "inventory": {
                "id": inventory.pk,
                "quantity": after,
                "reserved": inventory.reserved,
                "available": after - inventory.reserved,
            },
            "adjustment": {
                "id": audit.pk,
                "variant_id": variant.pk,
                "delta": delta,
                "reason": reason,
                "quantity_before": before,
                "quantity_after": after,
                "actor": {"id": actor.pk, "username": actor.get_username()},
                "created_at": audit.created_at.isoformat(),
            },
        }
    return result
