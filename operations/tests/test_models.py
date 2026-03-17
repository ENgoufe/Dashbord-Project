"""
Dateirolle:
Diese Datei testet die fachlichen Validierungsregeln der Produktmodelle.
Im Fokus steht die Beziehung zwischen Sicherheitsbestand und Meldebestand.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from operations.models import Product


class ProductModelTests(TestCase):
    def test_product_rejects_reorder_point_below_safety_stock(self):
        """
        Zweck:
        Prueft, dass eine Produktvalidierung fehlschlaegt, wenn der Meldebestand
        kleiner als der Sicherheitsbestand ist.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert das erwartete Ausnahmeverhalten.
        """
        product = Product(
            sku="MAT-500",
            name="Speziallager",
            category="Komponente",
            safety_stock=50,
            reorder_point=30,
        )

        with self.assertRaises(ValidationError) as exc_info:
            product.full_clean()

        self.assertIn("reorder_point", exc_info.exception.message_dict)

    def test_product_allows_reorder_point_equal_or_above_safety_stock(self):
        """
        Zweck:
        Prueft, dass Produktdaten gueltig sind, wenn der Meldebestand mindestens
        so hoch wie der Sicherheitsbestand gesetzt ist.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test schlaegt bei unerwarteter Exception fehl.
        """
        product = Product(
            sku="MAT-501",
            name="Dichtung",
            category="Komponente",
            safety_stock=20,
            reorder_point=20,
        )

        product.full_clean()
