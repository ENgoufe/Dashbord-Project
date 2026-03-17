"""
Dateirolle:
Diese Datei definiert die URL-Muster der `operations`-App.
Sie verbindet Dashboard, separate Frontend-Seiten und JSON-API-Endpunkte.
"""
from django.urls import path

from .views import (
    ask_llm_api_view,
    dashboard_view,
    deliveries_api_view,
    deliveries_frontend_view,
    inventory_api_view,
    inventory_frontend_view,
    orders_api_view,
    orders_frontend_view,
)

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("inventory/", inventory_frontend_view, name="inventory_frontend"),
    path("orders/", orders_frontend_view, name="orders_frontend"),
    path("deliveries/", deliveries_frontend_view, name="deliveries_frontend"),
    path("api/inventory/", inventory_api_view, name="api_inventory"),
    path("api/orders/", orders_api_view, name="api_orders"),
    path("api/deliveries/", deliveries_api_view, name="api_deliveries"),
    path("api/ask-llm/", ask_llm_api_view, name="api_ask_llm"),
]
