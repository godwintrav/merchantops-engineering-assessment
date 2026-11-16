"""Apply a relative stock correction and its audit event as one operation."""

from contextlib import contextmanager

from django.conf import settings
from django.db import connection, transaction
from django.shortcuts import get_object_or_404

from catalog.models import AuditLog, Inventory, InventoryOperation

MAX_QUANTITY = 2147483647


class InventoryConflict(Exception):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(detail)


@contextmanager
def inventory_lock_timeout():
    """Bound MySQL waits on this connection only, restoring its previous policy."""
    seconds = getattr(settings, "INVENTORY_LOCK_WAIT_SECONDS", 5)
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@SESSION.innodb_lock_wait_timeout")
        previous = cursor.fetchone()[0]
        cursor.execute("SET SESSION innodb_lock_wait_timeout = %s", [seconds])
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION innodb_lock_wait_timeout = %s", [previous])


def adjust_inventory(*, variant, actor, delta, reason, operation_key=None):
    with inventory_lock_timeout(), transaction.atomic():
        operation = None
        if operation_key is not None:
            payload = {
                "product_id": variant.product_id,
                "variant_id": variant.pk,
                "delta": delta,
                "reason": reason,
            }
            # The unique insert serializes duplicate keys across processes. Django's
            # savepoint-backed get_or_create reads the winner after it commits.
            operation, created = InventoryOperation.objects.get_or_create(
                merchant_id=variant.product.merchant_id,
                key=operation_key,
                defaults={"actor_id": actor.pk, "request": payload},
            )
            if not created:
                if operation.actor_id != actor.pk or operation.request != payload:
                    raise InventoryConflict(
                        "idempotency_conflict",
                        "This operation key belongs to a different adjustment.",
                    )
                current = get_object_or_404(Inventory, variant_id=variant.pk)
                return {
                    **operation.response,
                    "replayed": True,
                    "inventory": {
                        "id": current.pk,
                        "quantity": current.quantity,
                        "reserved": current.reserved,
                        "available": current.quantity - current.reserved,
                    },
                }
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
            "replayed": False,
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
        if operation is not None:
            operation.response = result
            operation.save(update_fields=["response"])
    return result
