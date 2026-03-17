"""
Dateirolle:
Diese Datei testet die zentrale Service-Schicht fuer Dateiimporte,
Lieferabgleiche, Materialverfuegbarkeit und Bestandswarnungen.
"""
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from django.test import TestCase

from operations.models import (
    BillOfMaterialItem,
    Delivery,
    Inventory,
    Product,
    ProductionOrder,
)
from operations.services import (
    analyze_production_order_feasibility,
    get_inventory_alerts,
    InventoryImportError,
    import_inventory_from_file,
    import_production_orders_from_file,
    sync_deliveries_from_records,
)


def write_xlsx_file(path: Path, headers, rows):
    """
    Zweck:
    Erzeugt zur Testunterstuetzung eine minimale XLSX-Datei mit gegebenen
    Kopfzeilen und Datensaetzen.
    Parameter:
    `path`: Zielpfad der zu schreibenden XLSX-Datei.
    `headers`: Sequenz der Spaltennamen fuer die erste Zeile.
    `rows`: Zeilenliste mit den eigentlichen Nutzdaten.
    Rueckgabewert:
    Kein Rueckgabewert. Die Funktion schreibt die Datei an den angegebenen Pfad.
    """
    shared_strings = []
    shared_string_lookup = {}

    def shared_string_index(value):
        """
        Zweck:
        Verwaltet die Shared-String-Tabelle innerhalb der Test-XLSX-Datei, damit
        identische Texte nur einmal im XML abgelegt werden.
        Parameter:
        `value`: Der Zellwert als String.
        Rueckgabewert:
        Der numerische Index des Werts in der Shared-String-Tabelle.
        """
        if value not in shared_string_lookup:
            shared_string_lookup[value] = len(shared_strings)
            shared_strings.append(value)
        return shared_string_lookup[value]

    row_xml_parts = []
    all_rows = [headers, *rows]
    for row_index, row in enumerate(all_rows, start=1):
        cells_xml = []
        for column_index, cell_value in enumerate(row, start=1):
            column_letter = chr(64 + column_index)
            shared_index = shared_string_index(str(cell_value))
            cells_xml.append(
                f'<c r="{column_letter}{row_index}" t="s"><v>{shared_index}</v></c>'
            )
        row_xml_parts.append(f'<row r="{row_index}">{"".join(cells_xml)}</row>')

    shared_strings_xml = "".join(
        f"<si><t>{escape(value)}</t></si>" for value in shared_strings
    )
    worksheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml_parts)}</sheetData>'
        "</worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )
    shared_strings_file = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        f"{shared_strings_xml}</sst>"
    )

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", root_rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
        archive.writestr("xl/sharedStrings.xml", shared_strings_file)


class InventoryImportTests(TestCase):
    def test_import_inventory_from_csv_creates_products_and_inventory(self):
        """
        Zweck:
        Prueft, dass ein CSV-Import neue Produkte und neue Bestandsdatensaetze anlegt.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Importergebnis und Datenbankzustand.
        """
        csv_content = """sku,name,category,location,quantity
MAT-001,Stahlplatte,Rohmaterial,Frankfurt,120
MAT-002,Schraubensatz,Kleinteile,München,40
"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "inventory.csv"
            file_path.write_text(csv_content, encoding="utf-8")

            result = import_inventory_from_file(file_path)

        self.assertEqual(result["created_products"], 2)
        self.assertEqual(result["created_inventories"], 2)
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(Inventory.objects.count(), 2)

        inventory = Inventory.objects.get(product__sku="MAT-001", location="Frankfurt")
        self.assertEqual(inventory.quantity, 120)

    def test_import_inventory_from_csv_updates_existing_inventory(self):
        """
        Zweck:
        Prueft, dass ein CSV-Import bestehende Lagerdaten aktualisieren kann.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert den Update-Pfad des Imports.
        """
        product = Product.objects.create(
            sku="MAT-001",
            name="Stahlplatte",
            category="Rohmaterial",
        )
        Inventory.objects.create(
            product=product,
            location="Frankfurt",
            quantity=50,
        )

        csv_content = """sku,name,category,location,quantity
MAT-001,Stahlplatte,Rohmaterial,Frankfurt,150
"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "inventory.csv"
            file_path.write_text(csv_content, encoding="utf-8")

            result = import_inventory_from_file(file_path)

        self.assertEqual(result["updated_inventories"], 1)

        inventory = Inventory.objects.get(product__sku="MAT-001", location="Frankfurt")
        self.assertEqual(inventory.quantity, 150)

    def test_import_inventory_from_xlsx_creates_products_and_inventory(self):
        """
        Zweck:
        Prueft, dass auch XLSX-Dateien fuer den Bestandsimport korrekt verarbeitet werden.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert den Excel-Importpfad.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "inventory.xlsx"
            write_xlsx_file(
                file_path,
                ["sku", "name", "category", "location", "quantity"],
                [["MAT-003", "Aluprofil", "Rohmaterial", "Berlin", "75"]],
            )

            result = import_inventory_from_file(file_path)

        self.assertEqual(result["created_products"], 1)
        self.assertEqual(result["created_inventories"], 1)
        inventory = Inventory.objects.get(product__sku="MAT-003", location="Berlin")
        self.assertEqual(inventory.quantity, 75)

    def test_import_inventory_from_csv_can_set_safety_stock_and_reorder_point(self):
        """
        Zweck:
        Prueft, dass Sicherheitsbestand und Meldebestand beim CSV-Import gesetzt werden koennen.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die Uebernahme optionaler Spalten.
        """
        csv_content = """sku,name,category,location,quantity,safety_stock,reorder_point
MAT-004,Kabelsatz,Komponente,Hamburg,35,20,50
"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "inventory.csv"
            file_path.write_text(csv_content, encoding="utf-8")

            result = import_inventory_from_file(file_path)

        self.assertEqual(result["created_products"], 1)
        product = Product.objects.get(sku="MAT-004")
        self.assertEqual(product.safety_stock, 20)
        self.assertEqual(product.reorder_point, 50)

    def test_import_inventory_from_csv_rejects_invalid_stock_thresholds(self):
        """
        Zweck:
        Prueft, dass fachlich ungueltige Schwellwerte beim Import zu einem Fehler fuehren.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die Fehlerbehandlung des Imports.
        """
        csv_content = """sku,name,category,location,quantity,safety_stock,reorder_point
MAT-005,Dichtung,Komponente,Hamburg,35,50,20
"""

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "inventory.csv"
            file_path.write_text(csv_content, encoding="utf-8")

            with self.assertRaises(InventoryImportError):
                import_inventory_from_file(file_path)


class DeliverySyncTests(TestCase):
    def setUp(self):
        """
        Zweck:
        Legt ein Produkt als Voraussetzung fuer Liefer-Synchronisationstests an.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Die Methode bereitet die Testdatenbank vor.
        """
        self.product = Product.objects.create(
            sku="MAT-002",
            name="Schraubensatz",
            category="Kleinteile",
        )

    def test_sync_deliveries_from_records_creates_delivery(self):
        """
        Zweck:
        Prueft, dass Lieferdatensaetze in eine neue Lieferung ueberfuehrt werden koennen.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Anlage und Feldwerte der Lieferung.
        """
        records = [
            {
                "delivery_number": "DEL-5001",
                "product_sku": "MAT-002",
                "quantity": 100,
                "expected_date": "2026-03-15",
                "supplier": "FastParts GmbH",
                "status": "expected",
            }
        ]

        result = sync_deliveries_from_records(records)

        self.assertEqual(result["created_deliveries"], 1)
        self.assertEqual(Delivery.objects.count(), 1)

        delivery = Delivery.objects.get(delivery_number="DEL-5001")
        self.assertEqual(delivery.product.sku, "MAT-002")
        self.assertEqual(delivery.quantity, 100)
        self.assertEqual(delivery.status, "expected")


class ProductionFeasibilityTests(TestCase):
    def setUp(self):
        """
        Zweck:
        Erstellt Produkte, Stueckliste, Bestandsdaten und einen Produktionsauftrag
        fuer Materialverfuegbarkeitsanalysen.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Die Methode baut die Ausgangsdaten fuer mehrere Tests auf.
        """
        self.mat_1 = Product.objects.create(
            sku="MAT-001",
            name="Stahlplatte",
            category="Rohmaterial",
        )
        self.mat_2 = Product.objects.create(
            sku="MAT-002",
            name="Schraubensatz",
            category="Kleinteile",
        )
        self.finished_product = Product.objects.create(
            sku="FERTIG-001",
            name="Montageset",
            category="Fertigprodukt",
        )

        BillOfMaterialItem.objects.create(
            finished_product=self.finished_product,
            component=self.mat_1,
            quantity_per_unit=2,
        )
        BillOfMaterialItem.objects.create(
            finished_product=self.finished_product,
            component=self.mat_2,
            quantity_per_unit=4,
        )

        Inventory.objects.create(product=self.mat_1, location="Frankfurt", quantity=120)
        Inventory.objects.create(product=self.mat_2, location="Frankfurt", quantity=50)

        self.order = ProductionOrder.objects.create(
            order_number="PO-2001",
            product=self.finished_product,
            quantity=20,
            due_date=date.today() + timedelta(days=3),
            status="planned",
        )

    def test_analyze_production_order_feasibility_detects_shortage(self):
        """
        Zweck:
        Prueft, dass Fehlmengen korrekt erkannt werden, wenn vorhandener Bestand nicht ausreicht.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die Engpassanalyse pro Komponente.
        """
        result = analyze_production_order_feasibility(self.order)

        result_by_sku = {item["component"].sku: item for item in result}

        self.assertEqual(result_by_sku["MAT-001"]["required_quantity"], 40)
        self.assertEqual(result_by_sku["MAT-001"]["available_quantity"], 120)
        self.assertTrue(result_by_sku["MAT-001"]["is_sufficient"])

        self.assertEqual(result_by_sku["MAT-002"]["required_quantity"], 80)
        self.assertEqual(result_by_sku["MAT-002"]["available_quantity"], 50)
        self.assertEqual(result_by_sku["MAT-002"]["shortage"], 30)
        self.assertFalse(result_by_sku["MAT-002"]["is_sufficient"])

    def test_analyze_production_order_feasibility_includes_expected_deliveries(self):
        """
        Zweck:
        Prueft, dass erwartete Lieferungen in die Verfuegbarkeitsanalyse einbezogen werden.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die Beruecksichtigung offener Lieferungen.
        """
        Delivery.objects.create(
            delivery_number="DEL-5001",
            product=self.mat_2,
            quantity=100,
            expected_date=self.order.due_date,
            supplier="FastParts GmbH",
            status="expected",
        )

        result = analyze_production_order_feasibility(self.order)
        result_by_sku = {item["component"].sku: item for item in result}

        self.assertEqual(result_by_sku["MAT-002"]["incoming_quantity"], 100)
        self.assertEqual(result_by_sku["MAT-002"]["total_expected_quantity"], 150)
        self.assertEqual(result_by_sku["MAT-002"]["shortage"], 0)
        self.assertTrue(result_by_sku["MAT-002"]["is_sufficient"])

    def test_analyze_production_order_feasibility_can_filter_inventory_by_location(self):
        """
        Zweck:
        Prueft, dass die Verfuegbarkeitsanalyse optional auf einen einzelnen Standort
        eingeschraenkt werden kann.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert den Standortfilter.
        """
        Inventory.objects.create(product=self.mat_2, location="Berlin", quantity=100)

        result = analyze_production_order_feasibility(self.order, location="Berlin")
        result_by_sku = {item["component"].sku: item for item in result}

        self.assertEqual(result_by_sku["MAT-001"]["available_quantity"], 0)
        self.assertEqual(result_by_sku["MAT-001"]["shortage"], 40)
        self.assertEqual(result_by_sku["MAT-002"]["available_quantity"], 100)
        self.assertEqual(result_by_sku["MAT-002"]["shortage"], 0)


class ProductionOrderImportTests(TestCase):
    def test_import_production_orders_from_xlsx_creates_order(self):
        """
        Zweck:
        Prueft, dass Produktionsauftraege aus einer XLSX-Datei importiert werden koennen.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Anlage und Feldwerte des Auftrags.
        """
        product = Product.objects.create(
            sku="FERTIG-010",
            name="Baugruppe",
            category="Fertigprodukt",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "orders.xlsx"
            write_xlsx_file(
                file_path,
                ["order_number", "product_sku", "quantity", "due_date", "status"],
                [["PO-9001", product.sku, "12", "2026-03-20", "planned"]],
            )

            result = import_production_orders_from_file(file_path)

        self.assertEqual(result["created_orders"], 1)
        order = ProductionOrder.objects.get(order_number="PO-9001")
        self.assertEqual(order.product, product)
        self.assertEqual(order.quantity, 12)
        self.assertEqual(order.status, "planned")


class InventoryAlertTests(TestCase):
    def test_get_inventory_alerts_detects_reorder_and_safety_stock_breaches(self):
        """
        Zweck:
        Prueft, dass Warnungen fuer Sicherheitsbestand und Meldebestand mit der
        korrekten Schwere berechnet werden.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Warnlogik und Kennzeichnungen.
        """
        critical_product = Product.objects.create(
            sku="MAT-100",
            name="Kupferdraht",
            category="Rohmaterial",
            safety_stock=50,
            reorder_point=80,
        )
        warning_product = Product.objects.create(
            sku="MAT-101",
            name="Schmierstoff",
            category="Hilfsstoff",
            safety_stock=10,
            reorder_point=25,
        )
        healthy_product = Product.objects.create(
            sku="MAT-102",
            name="Aluprofil",
            category="Rohmaterial",
            safety_stock=20,
            reorder_point=40,
        )

        Inventory.objects.create(product=critical_product, location="Frankfurt", quantity=30)
        Inventory.objects.create(product=warning_product, location="Frankfurt", quantity=20)
        Inventory.objects.create(product=healthy_product, location="Frankfurt", quantity=60)

        alerts = get_inventory_alerts()
        alerts_by_sku = {alert["product"].sku: alert for alert in alerts}

        self.assertEqual(set(alerts_by_sku.keys()), {"MAT-100", "MAT-101"})
        self.assertTrue(alerts_by_sku["MAT-100"]["is_below_safety_stock"])
        self.assertTrue(alerts_by_sku["MAT-100"]["is_below_reorder_point"])
        self.assertEqual(alerts_by_sku["MAT-100"]["alert_level"], "critical")
        self.assertFalse(alerts_by_sku["MAT-101"]["is_below_safety_stock"])
        self.assertTrue(alerts_by_sku["MAT-101"]["is_below_reorder_point"])
        self.assertEqual(alerts_by_sku["MAT-101"]["alert_level"], "warning")

    def test_get_inventory_alerts_can_filter_by_location(self):
        """
        Zweck:
        Prueft, dass Bestandswarnungen optional nur fuer einen bestimmten Standort
        berechnet werden.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert den Standortfilter der Warnlogik.
        """
        product = Product.objects.create(
            sku="MAT-200",
            name="Lagerring",
            category="Komponente",
            safety_stock=15,
            reorder_point=25,
        )
        Inventory.objects.create(product=product, location="Berlin", quantity=10)
        Inventory.objects.create(product=product, location="Frankfurt", quantity=40)

        alerts = get_inventory_alerts(location="Berlin")

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["current_stock"], 10)
        self.assertEqual(alerts[0]["alert_level"], "critical")
