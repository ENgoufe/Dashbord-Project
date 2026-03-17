"""
Dateirolle:
Diese Datei definiert die zentralen Datenmodelle der `operations`-App.
Sie beschreibt Produkte, Stuecklisten, Lagerbestaende, Produktionsauftraege
und Lieferungen inklusive fachlicher Validierungsregeln.
"""
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    safety_stock = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    reorder_point = models.IntegerField(default=0, validators=[MinValueValidator(0)])

    def __str__(self):
        """
        Zweck:
        Liefert eine lesbare Textdarstellung eines Produkts fuer Admin, Logs und Debugging.
        Parameter:
        `self`: Die aktuelle Produktinstanz mit SKU und Name.
        Rueckgabewert:
        Ein String im Format `SKU - Name`.
        """
        return f"{self.sku} - {self.name}"

    def clean(self):
        """
        Zweck:
        Prueft die fachliche Regel, dass der Meldebestand nicht unter dem
        Sicherheitsbestand liegen darf.
        Parameter:
        `self`: Die aktuelle Produktinstanz mit den Feldern `safety_stock` und `reorder_point`.
        Rueckgabewert:
        Kein Rueckgabewert. Bei ungueltigen Daten wird eine `ValidationError` ausgelost.
        """
        if self.reorder_point < self.safety_stock:
            raise ValidationError(
                {
                    "reorder_point": (
                        "Der Meldebestand darf nicht kleiner als der "
                        "Sicherheitsbestand sein."
                    )
                }
            )


class BillOfMaterialItem(models.Model):
    finished_product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="bom_items"
    )
    component = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="used_in_boms"
    )
    quantity_per_unit = models.FloatField(validators=[MinValueValidator(0.01)])

    class Meta:
        unique_together = ("finished_product", "component")

    def __str__(self):
        """
        Zweck:
        Erstellt eine kompakte Textdarstellung der Stuecklistenposition.
        Parameter:
        `self`: Die aktuelle Stuecklisteninstanz mit Fertigprodukt, Komponente und Menge.
        Rueckgabewert:
        Ein String, der Abhaengigkeit und benoetigte Menge beschreibt.
        """
        return (
            f"{self.finished_product.sku} needs "
            f"{self.quantity_per_unit} x {self.component.sku}"
        )

    def clean(self):
        """
        Zweck:
        Verhindert fachlich ungueltige Stuecklisten, in denen ein Produkt sich
        selbst als Komponente referenziert.
        Parameter:
        `self`: Die aktuelle Stuecklisteninstanz mit Produkt- und Komponentenreferenz.
        Rueckgabewert:
        Kein Rueckgabewert. Bei ungueltiger Konstellation wird `ValidationError` geworfen.
        """
        if self.finished_product_id == self.component_id:
            raise ValidationError(
                "Ein Produkt kann nicht sich selbst als Komponente haben."
            )


class Inventory(models.Model):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="inventories"
    )
    location = models.CharField(max_length=100)
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("product", "location")

    def __str__(self):
        """
        Zweck:
        Liefert eine kompakte Textdarstellung eines Lagerbestands.
        Parameter:
        `self`: Die aktuelle Bestandsinstanz mit Produkt, Standort und Menge.
        Rueckgabewert:
        Ein String mit SKU, Standort und verfuegbarer Menge.
        """
        return f"{self.product.sku} @ {self.location}: {self.quantity}"


class ProductionOrder(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"

    order_number = models.CharField(max_length=50, unique=True)
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="production_orders"
    )
    quantity = models.IntegerField(validators=[MinValueValidator(0)])
    due_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PLANNED
    )

    def __str__(self):
        """
        Zweck:
        Liefert eine kurze Kennzeichnung eines Produktionsauftrags.
        Parameter:
        `self`: Die aktuelle Produktionsauftragsinstanz mit Auftragsnummer und Produkt.
        Rueckgabewert:
        Ein String mit Auftragsnummer und Produkt-SKU.
        """
        return f"{self.order_number} - {self.product.sku}"


class Delivery(models.Model):
    class Status(models.TextChoices):
        EXPECTED = "expected", "Expected"
        DELIVERED = "delivered", "Delivered"
        DELAYED = "delayed", "Delayed"

    delivery_number = models.CharField(max_length=50, unique=True)
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="deliveries"
    )
    quantity = models.IntegerField(validators=[MinValueValidator(0)])
    expected_date = models.DateField()
    supplier = models.CharField(max_length=150, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.EXPECTED
    )

    def __str__(self):
        """
        Zweck:
        Liefert eine kurze Kennzeichnung einer Lieferung.
        Parameter:
        `self`: Die aktuelle Lieferinstanz mit Liefernummer und Produkt.
        Rueckgabewert:
        Ein String mit Liefernummer und Produkt-SKU.
        """
        return f"{self.delivery_number} - {self.product.sku}"


class DataImportError(Exception):
    pass


ProductionOrder.Status.COMPLETED
Delivery.Status.EXPECTED
