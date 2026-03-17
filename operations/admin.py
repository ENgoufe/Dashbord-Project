"""
Dateirolle:
Diese Datei registriert die Modelle der `operations`-App im Django-Admin
und konfiguriert, welche Felder dort angezeigt, gefiltert und durchsucht werden koennen.
"""
from django.contrib import admin

from .models import BillOfMaterialItem, Delivery, Inventory, Product, ProductionOrder


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Zweck:
    Konfiguriert die Admin-Ansicht fuer Produkte.
    Parameter:
    Keine Methodenparameter. Django verwendet die Attribute der Klasse zur Darstellung.
    Rueckgabewert:
    Kein direkter Rueckgabewert. Die Klasse steuert die Produktdarstellung im Admin.
    """
    list_display = ("sku", "name", "category", "safety_stock", "reorder_point")
    list_filter = ("category",)
    search_fields = ("sku", "name", "category")


@admin.register(BillOfMaterialItem)
class BillOfMaterialItemAdmin(admin.ModelAdmin):
    """
    Zweck:
    Konfiguriert die Admin-Ansicht fuer Stuecklistenpositionen.
    Parameter:
    Keine Methodenparameter. Django liest die Konfigurationsattribute beim Rendern.
    Rueckgabewert:
    Kein direkter Rueckgabewert. Die Klasse bestimmt Anzeige und Suche im Admin.
    """
    list_display = ("finished_product", "component", "quantity_per_unit")
    search_fields = (
        "finished_product__sku",
        "finished_product__name",
        "component__sku",
        "component__name",
    )


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    """
    Zweck:
    Konfiguriert die Admin-Ansicht fuer Bestandsdatensaetze je Produkt und Standort.
    Parameter:
    Keine Methodenparameter. Die Klasse wird von Django automatisch ausgewertet.
    Rueckgabewert:
    Kein direkter Rueckgabewert. Die Klasse beeinflusst die Admin-Oberflaeche.
    """
    list_display = ("product", "location", "quantity", "last_updated")
    list_filter = ("location",)
    search_fields = ("product__sku", "product__name", "location")


@admin.register(ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    """
    Zweck:
    Konfiguriert die Admin-Ansicht fuer Produktionsauftraege.
    Parameter:
    Keine Methodenparameter. Die Anzeige wird ueber Klassenattribute beschrieben.
    Rueckgabewert:
    Kein direkter Rueckgabewert. Die Klasse steuert Filter, Suche und Tabellenansicht.
    """
    list_display = ("order_number", "product", "quantity", "due_date", "status")
    list_filter = ("status", "due_date")
    search_fields = ("order_number", "product__sku", "product__name")


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    """
    Zweck:
    Konfiguriert die Admin-Ansicht fuer Lieferungen.
    Parameter:
    Keine Methodenparameter. Django verwendet ausschliesslich die gesetzten Attribute.
    Rueckgabewert:
    Kein direkter Rueckgabewert. Die Klasse bestimmt die Lieferungsdarstellung im Admin.
    """
    list_display = (
        "delivery_number",
        "product",
        "quantity",
        "expected_date",
        "supplier",
        "status",
    )
    list_filter = ("status", "expected_date", "supplier")
    search_fields = ("delivery_number", "product__sku", "product__name", "supplier")
