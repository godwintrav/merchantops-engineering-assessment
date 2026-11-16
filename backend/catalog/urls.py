from django.urls import path

from catalog.views import (
    InventoryAdjustmentView,
    ProductActivityView,
    ProductDetailView,
    ProductEditorView,
    ProductListView,
)

urlpatterns = [
    path(
        "products/<int:pk>/variants/<int:variant_id>/adjustments/",
        InventoryAdjustmentView.as_view(),
        name="inventory-adjustment",
    ),
    path(
        "products/",
        ProductListView.as_view(),
        name="product-list",
    ),
    path(
        "products/<int:pk>/editor/",
        ProductEditorView.as_view(),
        name="product-editor",
    ),
    path(
        "products/<int:pk>/",
        ProductDetailView.as_view(),
        name="product-detail",
    ),
    path(
        "products/<int:pk>/activity/",
        ProductActivityView.as_view(),
        name="product-activity",
    ),
]
