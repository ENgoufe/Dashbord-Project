"""
Dateirolle:
Diese Datei enthaelt die zentrale Fachlogik der `operations`-App.
Dazu gehoeren Dateiimporte, Bestands- und Auftragsanalysen, Lieferabgleiche
sowie die Aufbereitung von Kennzahlen fuer Dashboard und LLM-Kontext.
"""
import csv
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import requests
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import BillOfMaterialItem, Delivery, Inventory, Product, ProductionOrder


class InventoryImportError(Exception):
    pass


SPREADSHEET_NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}

EXCEL_DATE_EPOCH = datetime(1899, 12, 30)


def _normalize_tabular_value(value):
    """
    Zweck:
    Vereinheitlicht eingelesene Tabellenwerte, damit CSV- und Excel-Daten in einer
    konsistenten Textdarstellung weiterverarbeitet werden koennen.
    Parameter:
    `value`: Ein beliebiger Zellwert, zum Beispiel `None`, Float, Integer oder String.
    Rueckgabewert:
    Ein String ohne Typunterschiede aus der Quelldatei. `None` wird zu einem leeren String.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _excel_serial_to_date_string(value):
    """
    Zweck:
    Wandelt ein numerisches Excel-Seriendatum in ein Datum im ISO-Format um.
    Parameter:
    `value`: Ein numerischer oder numerisch lesbarer Wert aus einer Excel-Zelle.
    Rueckgabewert:
    Ein String im Format `YYYY-MM-DD`.
    """
    numeric_value = float(value)
    converted = EXCEL_DATE_EPOCH + timedelta(days=numeric_value)
    return converted.date().isoformat()


def _looks_like_excel_serial(value):
    """
    Zweck:
    Prueft, ob ein Eingabewert numerisch genug ist, um als Excel-Seriendatum
    interpretiert werden zu koennen.
    Parameter:
    `value`: Ein beliebiger Tabellenwert.
    Rueckgabewert:
    `True`, wenn der Wert in eine Zahl konvertiert werden kann, sonst `False`.
    """
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _parse_xlsx_rows(file_path):
    """
    Zweck:
    Liest die erste Tabelle einer XLSX-Datei direkt aus dem ZIP/XML-Format aus,
    ohne externe Excel-Bibliotheken zu verwenden.
    Parameter:
    `file_path`: Pfad zur XLSX-Datei als String oder `Path`.
    Rueckgabewert:
    Ein Tupel aus `header` und `records`, wobei `header` eine Spaltenliste und
    `records` eine Liste von Dictionary-Zeilen ist.
    Bei defekten oder unlesbaren Dateien wird `InventoryImportError` ausgeloest.
    """
    try:
        archive = zipfile.ZipFile(file_path)
    except zipfile.BadZipFile as exc:
        raise InventoryImportError(f"Ungültige Excel-Datei: {file_path}") from exc

    with archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for string_item in shared_root.findall("main:si", SPREADSHEET_NS):
                text_parts = [
                    node.text or ""
                    for node in string_item.findall(".//main:t", SPREADSHEET_NS)
                ]
                shared_strings.append("".join(text_parts))

        workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = workbook_root.find("main:sheets/main:sheet", SPREADSHEET_NS)
        if first_sheet is None:
            raise InventoryImportError("Excel-Datei enthält kein Tabellenblatt.")

        sheet_rel_id = first_sheet.attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        if not sheet_rel_id:
            raise InventoryImportError("Excel-Datei enthält ein ungültiges Tabellenblatt.")

        rels_root = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        worksheet_target = None
        for relation in rels_root.findall("pkg:Relationship", SPREADSHEET_NS):
            if relation.attrib.get("Id") == sheet_rel_id:
                worksheet_target = relation.attrib.get("Target")
                break

        if not worksheet_target:
            raise InventoryImportError("Excel-Datei enthält kein lesbares Tabellenblatt.")

        worksheet_path = worksheet_target.lstrip("/")
        if not worksheet_path.startswith("xl/"):
            worksheet_path = f"xl/{worksheet_path}"

        sheet_root = ElementTree.fromstring(archive.read(worksheet_path))
        rows = []

        for row in sheet_root.findall(".//main:sheetData/main:row", SPREADSHEET_NS):
            values = []
            for cell in row.findall("main:c", SPREADSHEET_NS):
                cell_type = cell.attrib.get("t")
                value_node = cell.find("main:v", SPREADSHEET_NS)
                inline_node = cell.find("main:is/main:t", SPREADSHEET_NS)
                raw_value = ""
                if inline_node is not None:
                    raw_value = inline_node.text or ""
                elif value_node is not None and value_node.text is not None:
                    raw_value = value_node.text

                if cell_type == "s" and raw_value != "":
                    values.append(shared_strings[int(raw_value)])
                    continue
                if cell_type == "inlineStr":
                    values.append(raw_value)
                    continue

                values.append(raw_value)

            rows.append(values)

    if not rows:
        raise InventoryImportError("Excel-Datei ist leer oder hat keine Kopfzeile.")

    header = [_normalize_tabular_value(value).strip() for value in rows[0]]
    records = []

    for row in rows[1:]:
        padded_row = list(row) + [""] * (len(header) - len(row))
        records.append(
            {
                column_name: _normalize_tabular_value(padded_row[index]).strip()
                for index, column_name in enumerate(header)
            }
        )

    return header, records


def _load_tabular_records(file_path):
    """
    Zweck:
    Laedt tabellarische Datensaetze aus CSV- oder XLSX-Dateien und bringt sie
    in ein gemeinsames Format fuer die Importlogik.
    Parameter:
    `file_path`: Pfad zur Quelldatei als String oder `Path`.
    Rueckgabewert:
    Ein Tupel aus Feldnamenliste und Datensatzliste.
    Bei fehlender Datei, leerem Inhalt oder ungueltigem Format wird `InventoryImportError` geworfen.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise InventoryImportError(f"Datei nicht gefunden: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        with file_path.open(mode="r", encoding="utf-8-sig", newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            if not reader.fieldnames:
                raise InventoryImportError("Datei ist leer oder hat keine Kopfzeile.")

            rows = []
            for row in reader:
                rows.append(
                    {
                        key: _normalize_tabular_value(value).strip()
                        for key, value in row.items()
                    }
                )
            return [field.strip() for field in reader.fieldnames], rows

    if suffix == ".xlsx":
        return _parse_xlsx_rows(file_path)

    raise InventoryImportError(
        f"Nicht unterstütztes Dateiformat '{suffix}'. Erlaubt sind .csv und .xlsx."
    )


@transaction.atomic
def import_inventory_from_file(file_path):
    """
    Zweck:
    Importiert Produkt- und Bestandsdaten aus einer CSV- oder XLSX-Datei,
    legt neue Produkte an und aktualisiert bestehende Produkte und Lagerbestaende.
    Parameter:
    `file_path`: Pfad zur Importdatei.
    Rueckgabewert:
    Ein Dictionary mit Zaehlern fuer neu angelegte und aktualisierte Produkte
    sowie Bestandsdatensaetze.
    Bei fachlich oder technisch ungueltigen Daten wird `InventoryImportError` ausgeloest.
    """
    created_products = 0
    updated_products = 0
    created_inventories = 0
    updated_inventories = 0

    fieldnames, records = _load_tabular_records(file_path)
    required_columns = {"sku", "name", "category", "location", "quantity"}
    optional_columns = {"safety_stock", "reorder_point"}
    missing_columns = required_columns - set(fieldnames)
    if missing_columns:
        raise InventoryImportError(
            f"Fehlende Spalten in Datei: {', '.join(sorted(missing_columns))}"
        )

    for row_number, row in enumerate(records, start=2):
        sku = row["sku"].strip()
        name = row["name"].strip()
        category = row["category"].strip()
        location = row["location"].strip()
        quantity_raw = row["quantity"].strip()
        safety_stock_raw = row.get("safety_stock", "").strip()
        reorder_point_raw = row.get("reorder_point", "").strip()

        if not sku:
            raise InventoryImportError(f"Zeile {row_number}: SKU fehlt.")
        if not name:
            raise InventoryImportError(f"Zeile {row_number}: Name fehlt.")
        if not location:
            raise InventoryImportError(f"Zeile {row_number}: Standort fehlt.")

        try:
            quantity = int(quantity_raw)
        except ValueError:
            raise InventoryImportError(
                f"Zeile {row_number}: quantity ist keine ganze Zahl: '{quantity_raw}'"
            )

        try:
            safety_stock = (
                int(safety_stock_raw) if "safety_stock" in fieldnames and safety_stock_raw else 0
            )
        except ValueError:
            raise InventoryImportError(
                f"Zeile {row_number}: safety_stock ist keine ganze Zahl: '{safety_stock_raw}'"
            )

        try:
            reorder_point = (
                int(reorder_point_raw)
                if "reorder_point" in fieldnames and reorder_point_raw
                else 0
            )
        except ValueError:
            raise InventoryImportError(
                f"Zeile {row_number}: reorder_point ist keine ganze Zahl: '{reorder_point_raw}'"
            )

        product, product_created = Product.objects.get_or_create(
            sku=sku,
            defaults={
                "name": name,
                "category": category,
                "safety_stock": safety_stock,
                "reorder_point": reorder_point,
            },
        )

        if product_created:
            created_products += 1
        else:
            changed = False
            if product.name != name:
                product.name = name
                changed = True
            if product.category != category:
                product.category = category
                changed = True
            if "safety_stock" in fieldnames and product.safety_stock != safety_stock:
                product.safety_stock = safety_stock
                changed = True
            if "reorder_point" in fieldnames and product.reorder_point != reorder_point:
                product.reorder_point = reorder_point
                changed = True
            if changed:
                try:
                    product.full_clean()
                except ValidationError as exc:
                    raise InventoryImportError(
                        f"Zeile {row_number}: Ungültige Produktdaten: {exc}"
                    )
                product.save()
                updated_products += 1

        if product_created:
            try:
                product.full_clean()
            except ValidationError as exc:
                raise InventoryImportError(
                    f"Zeile {row_number}: Ungültige Produktdaten: {exc}"
                )
            product.save()

        inventory, inventory_created = Inventory.objects.update_or_create(
            product=product,
            location=location,
            defaults={
                "quantity": quantity,
            },
        )

        if inventory_created:
            created_inventories += 1
        else:
            updated_inventories += 1

    return {
        "created_products": created_products,
        "updated_products": updated_products,
        "created_inventories": created_inventories,
        "updated_inventories": updated_inventories,
    }


def get_order_material_requirements(order: ProductionOrder):
    """
    Zweck:
    Ermittelt den Materialbedarf eines Produktionsauftrags auf Basis der
    hinterlegten Stuecklistenpositionen des Fertigprodukts.
    Parameter:
    `order`: Eine `ProductionOrder`-Instanz, fuer die der Bedarf berechnet wird.
    Rueckgabewert:
    Eine Liste von Dictionaries mit Komponente, Menge pro Einheit und Gesamtbedarf.
    """
    requirements = []

    bom_items = BillOfMaterialItem.objects.filter(
        finished_product=order.product
    ).select_related("component")

    for item in bom_items:
        required_quantity = item.quantity_per_unit * order.quantity
        requirements.append(
            {
                "component": item.component,
                "quantity_per_unit": item.quantity_per_unit,
                "required_quantity": required_quantity,
            }
        )

    return requirements


def get_total_inventory_for_product(product: Product, location=None):
    """
    Zweck:
    Summiert den aktuellen Lagerbestand eines Produkts ueber alle oder nur ueber
    einen bestimmten Standort.
    Parameter:
    `product`: Die Produktinstanz, deren Bestand summiert werden soll.
    `location`: Optionaler Standortfilter als String.
    Rueckgabewert:
    Eine Ganzzahl mit der verfuegbaren Gesamtmenge.
    """
    inventories = Inventory.objects.filter(product=product)
    if location:
        inventories = inventories.filter(location=location)
    return sum(inv.quantity for inv in inventories)


def get_inventory_alerts(location=None):
    """
    Zweck:
    Erstellt Warnmeldungen fuer Produkte, deren Bestand unter Sicherheitsbestand
    oder Meldebestand liegt.
    Parameter:
    `location`: Optionaler Standortfilter fuer die Bestandsbewertung.
    Rueckgabewert:
    Eine Liste von Dictionaries mit Produkt, Bestand, Grenzwerten und Warnstufe.
    """
    alerts = []

    for product in Product.objects.order_by("sku"):
        current_stock = get_total_inventory_for_product(product, location=location)
        has_safety_stock = product.safety_stock > 0
        has_reorder_point = product.reorder_point > 0
        is_below_safety_stock = has_safety_stock and current_stock < product.safety_stock
        is_below_reorder_point = (
            has_reorder_point and current_stock <= product.reorder_point
        )

        if not is_below_safety_stock and not is_below_reorder_point:
            continue

        if is_below_safety_stock:
            alert_level = "critical"
        else:
            alert_level = "warning"

        alerts.append(
            {
                "product": product,
                "current_stock": current_stock,
                "safety_stock": product.safety_stock,
                "reorder_point": product.reorder_point,
                "alert_level": alert_level,
                "is_below_safety_stock": is_below_safety_stock,
                "is_below_reorder_point": is_below_reorder_point,
            }
        )

    return alerts


def get_dashboard_metrics(location=None):
    """
    Zweck:
    Aggregiert die wichtigsten Dashboard-Kennzahlen fuer Produkte, Bestandsdaten,
    Warnungen, offene Auftraege und verspaetete Lieferungen.
    Parameter:
    `location`: Optionaler Standortfilter fuer bestandsbezogene Kennzahlen.
    Rueckgabewert:
    Ein Dictionary mit Summenwerten und der Liste relevanter Bestandswarnungen.
    """
    inventory_queryset = Inventory.objects.all()
    if location:
        inventory_queryset = inventory_queryset.filter(location=location)

    inventory_alerts = get_inventory_alerts(location=location)

    return {
        "total_products": Product.objects.count(),
        "total_inventory_records": inventory_queryset.count(),
        "below_safety_stock_count": sum(
            1 for alert in inventory_alerts if alert["is_below_safety_stock"]
        ),
        "below_reorder_point_count": sum(
            1 for alert in inventory_alerts if alert["is_below_reorder_point"]
        ),
        "open_orders_count": ProductionOrder.objects.exclude(status="completed").count(),
        "delayed_deliveries_count": Delivery.objects.filter(status="delayed").count(),
        "inventory_alerts": inventory_alerts,
    }


def get_dashboard_order_data(location=None):
    """
    Zweck:
    Bereitet offene Produktionsauftraege samt kritischer Komponenten und einer
    verdichteten Engpassliste fuer das Dashboard auf.
    Parameter:
    `location`: Optionaler Standortfilter fuer die Materialverfuegbarkeitsanalyse.
    Rueckgabewert:
    Ein Dictionary mit aufbereiteten Auftraegen, kritischen Auftraegen und
    einer nach Fehlmenge sortierten Engpasszusammenfassung.
    """
    open_orders = (
        ProductionOrder.objects.exclude(status="completed")
        .select_related("product")
        .order_by("due_date")
    )

    enriched_orders = []
    shortage_summary = {}

    for order in open_orders:
        analysis = analyze_production_order_feasibility(order, location=location)
        has_shortage = any(item["shortage"] > 0 for item in analysis)

        critical_components = []
        for item in analysis:
            if item["shortage"] <= 0:
                continue

            critical_components.append(
                {
                    "component_sku": item["component"].sku,
                    "component_name": item["component"].name,
                    "required_quantity": item["required_quantity"],
                    "available_quantity": item["available_quantity"],
                    "incoming_quantity": item["incoming_quantity"],
                    "shortage": item["shortage"],
                }
            )

            key = item["component"].sku
            if key not in shortage_summary:
                shortage_summary[key] = {
                    "component_sku": item["component"].sku,
                    "component_name": item["component"].name,
                    "total_shortage": 0,
                }
            shortage_summary[key]["total_shortage"] += item["shortage"]

        enriched_orders.append(
            {
                "order_number": order.order_number,
                "product_sku": order.product.sku,
                "product_name": order.product.name,
                "quantity": order.quantity,
                "due_date": order.due_date,
                "status": order.status,
                "has_shortage": has_shortage,
                "critical_components": critical_components,
            }
        )

    return {
        "orders": enriched_orders,
        "critical_orders": [order for order in enriched_orders if order["has_shortage"]],
        "shortage_summary": sorted(
            shortage_summary.values(),
            key=lambda item: item["total_shortage"],
            reverse=True,
        ),
    }


def get_upcoming_deliveries(next_days=7):
    """
    Zweck:
    Liefert Lieferungen, die innerhalb eines Zeitfensters erwartet werden und noch
    nicht als zugestellt markiert sind.
    Parameter:
    `next_days`: Anzahl der Tage ab heute, die betrachtet werden sollen.
    Rueckgabewert:
    Ein QuerySet von `Delivery`-Objekten, sortiert nach erwartetem Lieferdatum.
    """
    target_date = datetime.today().date() + timedelta(days=next_days)
    return (
        Delivery.objects.filter(expected_date__lte=target_date)
        .exclude(status="delivered")
        .select_related("product")
        .order_by("expected_date")
    )


def build_llm_dashboard_context(location=None, next_days=7, max_items=5):
    """
    Zweck:
    Baut einen kompakten, serialisierbaren Kontext aus Dashboard-Kennzahlen,
    Warnungen, kritischen Materialien, Auftraegen und Lieferungen fuer LLM-Abfragen.
    Parameter:
    `location`: Optionaler Standortfilter.
    `next_days`: Zeitraum fuer anstehende Lieferungen.
    `max_items`: Maximale Anzahl von Eintraegen pro Kontextbereich.
    Rueckgabewert:
    Ein Dictionary mit kompakten Kennzahlen und Listen fuer die Modellanfrage.
    """
    metrics = get_dashboard_metrics(location=location)
    order_data = get_dashboard_order_data(location=location)
    deliveries = list(get_upcoming_deliveries(next_days=next_days)[:max_items])

    return {
        "location": location or "all",
        "metrics": {
            "total_products": metrics["total_products"],
            "total_inventory_records": metrics["total_inventory_records"],
            "below_safety_stock_count": metrics["below_safety_stock_count"],
            "below_reorder_point_count": metrics["below_reorder_point_count"],
            "open_orders_count": metrics["open_orders_count"],
            "delayed_deliveries_count": metrics["delayed_deliveries_count"],
        },
        "stock_alerts": [
            {
                "sku": alert["product"].sku,
                "name": alert["product"].name,
                "current_stock": alert["current_stock"],
                "safety_stock": alert["safety_stock"],
                "reorder_point": alert["reorder_point"],
                "alert_level": alert["alert_level"],
            }
            for alert in metrics["inventory_alerts"][:max_items]
        ],
        "critical_materials": order_data["shortage_summary"][:max_items],
        "open_orders": order_data["orders"][:max_items],
        "upcoming_deliveries": [
            {
                "delivery_number": delivery.delivery_number,
                "product_sku": delivery.product.sku,
                "product_name": delivery.product.name,
                "quantity": delivery.quantity,
                "expected_date": delivery.expected_date.isoformat(),
                "supplier": delivery.supplier,
                "status": delivery.status,
            }
            for delivery in deliveries
        ],
    }


def analyze_production_order_feasibility(order: ProductionOrder, location=None):
    """
    Zweck:
    Prueft fuer jede benoetigte Komponente eines Produktionsauftrags, ob aktueller
    Bestand plus erwartete Lieferungen bis zum Faelligkeitsdatum ausreichen.
    Parameter:
    `order`: Die zu analysierende `ProductionOrder`-Instanz.
    `location`: Optionaler Standortfilter fuer die Bestandssicht.
    Rueckgabewert:
    Eine Liste von Dictionaries mit Bedarfen, Verfuegbarkeit, Lieferungen und Engpassstatus.
    """
    requirements = get_order_material_requirements(order)
    analysis = []

    for req in requirements:
        component = req["component"]
        required_quantity = req["required_quantity"]

        available_quantity = get_total_inventory_for_product(component, location=location)
        incoming_quantity = get_expected_deliveries_for_product_until(
            component, order.due_date
        )
        total_expected_quantity = available_quantity + incoming_quantity
        shortage = max(required_quantity - total_expected_quantity, 0)

        analysis.append(
            {
                "component": component,
                "required_quantity": required_quantity,
                "available_quantity": available_quantity,
                "incoming_quantity": incoming_quantity,
                "total_expected_quantity": total_expected_quantity,
                "shortage": shortage,
                "is_sufficient": shortage == 0,
            }
        )

    return analysis


@transaction.atomic
def import_production_orders_from_file(file_path):
    """
    Zweck:
    Importiert Produktionsauftraege aus einer CSV- oder XLSX-Datei und aktualisiert
    vorhandene Auftraege anhand der Auftragsnummer.
    Parameter:
    `file_path`: Pfad zur Quelldatei mit Produktionsauftraegen.
    Rueckgabewert:
    Ein Dictionary mit Anzahlen neu angelegter und aktualisierter Auftraege.
    Bei fehlenden Spalten oder ungueltigen Daten wird `InventoryImportError` ausgelost.
    """
    created_orders = 0
    updated_orders = 0

    fieldnames, records = _load_tabular_records(file_path)
    required_columns = {
        "order_number",
        "product_sku",
        "quantity",
        "due_date",
        "status",
    }
    missing_columns = required_columns - set(fieldnames)
    if missing_columns:
        raise InventoryImportError(
            f"Fehlende Spalten in Datei: {', '.join(sorted(missing_columns))}"
        )

    for row_number, row in enumerate(records, start=2):
        order_number = row["order_number"].strip()
        product_sku = row["product_sku"].strip()
        quantity_raw = row["quantity"].strip()
        due_date_raw = row["due_date"].strip()
        status = row["status"].strip()

        if not order_number:
            raise InventoryImportError(f"Zeile {row_number}: order_number fehlt.")
        if not product_sku:
            raise InventoryImportError(f"Zeile {row_number}: product_sku fehlt.")

        try:
            quantity = int(quantity_raw)
        except ValueError:
            raise InventoryImportError(
                f"Zeile {row_number}: quantity ist keine ganze Zahl."
            )

        try:
            if _looks_like_excel_serial(due_date_raw):
                due_date_raw = _excel_serial_to_date_string(due_date_raw)
            due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date()
        except ValueError:
            raise InventoryImportError(
                f"Zeile {row_number}: due_date muss Format YYYY-MM-DD haben."
            )

        try:
            product = Product.objects.get(sku=product_sku)
        except Product.DoesNotExist:
            raise InventoryImportError(
                f"Zeile {row_number}: Produkt mit SKU '{product_sku}' nicht gefunden."
            )

        order, created = ProductionOrder.objects.update_or_create(
            order_number=order_number,
            defaults={
                "product": product,
                "quantity": quantity,
                "due_date": due_date,
                "status": status,
            },
        )

        if created:
            created_orders += 1
        else:
            updated_orders += 1

    return {
        "created_orders": created_orders,
        "updated_orders": updated_orders,
    }


def import_inventory_from_csv(file_path):
    """
    Zweck:
    Stellt einen Kompatibilitaetsaufruf fuer bestehenden Code bereit, der
    explizit einen CSV-Import fuer Bestandsdaten erwartet.
    Parameter:
    `file_path`: Pfad zur Bestandsdatei.
    Rueckgabewert:
    Das gleiche Ergebnis wie `import_inventory_from_file`.
    """
    return import_inventory_from_file(file_path)


def import_production_orders_from_csv(file_path):
    """
    Zweck:
    Stellt einen Kompatibilitaetsaufruf fuer bestehenden Code bereit, der
    explizit einen CSV-Import fuer Produktionsauftraege erwartet.
    Parameter:
    `file_path`: Pfad zur Auftragsdatei.
    Rueckgabewert:
    Das gleiche Ergebnis wie `import_production_orders_from_file`.
    """
    return import_production_orders_from_file(file_path)


@transaction.atomic
def sync_deliveries_from_records(records):
    """
    Zweck:
    Synchronisiert Lieferungen auf Basis bereits geladener Datensaetze und legt
    Eintraege neu an oder aktualisiert sie ueber die Liefernummer.
    Parameter:
    `records`: Liste von Dictionaries mit Lieferdaten.
    Rueckgabewert:
    Ein Dictionary mit Anzahlen fuer neue und aktualisierte Lieferungen.
    Bei ungueltigen Daten wird `InventoryImportError` ausgelost.
    """
    created_deliveries = 0
    updated_deliveries = 0

    valid_statuses = {"expected", "delivered", "delayed"}

    for index, record in enumerate(records, start=1):
        delivery_number = str(record.get("delivery_number", "")).strip()
        product_sku = str(record.get("product_sku", "")).strip()
        supplier = str(record.get("supplier", "")).strip()
        status = str(record.get("status", "expected")).strip()
        quantity_raw = record.get("quantity")
        expected_date_raw = str(record.get("expected_date", "")).strip()

        if not delivery_number:
            raise InventoryImportError(f"Eintrag {index}: delivery_number fehlt.")
        if not product_sku:
            raise InventoryImportError(f"Eintrag {index}: product_sku fehlt.")
        if expected_date_raw == "":
            raise InventoryImportError(f"Eintrag {index}: expected_date fehlt.")

        if status not in valid_statuses:
            raise InventoryImportError(
                f"Eintrag {index}: ungültiger status '{status}'. Erlaubt sind: expected, delivered, delayed."
            )

        try:
            quantity = int(quantity_raw)
        except (TypeError, ValueError):
            raise InventoryImportError(
                f"Eintrag {index}: quantity muss eine ganze Zahl sein."
            )

        if quantity < 0:
            raise InventoryImportError(
                f"Eintrag {index}: quantity darf nicht negativ sein."
            )

        try:
            expected_date = datetime.strptime(expected_date_raw, "%Y-%m-%d").date()
        except ValueError:
            raise InventoryImportError(
                f"Eintrag {index}: expected_date muss Format YYYY-MM-DD haben."
            )

        try:
            product = Product.objects.get(sku=product_sku)
        except Product.DoesNotExist:
            raise InventoryImportError(
                f"Eintrag {index}: Produkt mit SKU '{product_sku}' nicht gefunden."
            )

        delivery, created = Delivery.objects.update_or_create(
            delivery_number=delivery_number,
            defaults={
                "product": product,
                "quantity": quantity,
                "expected_date": expected_date,
                "supplier": supplier,
                "status": status,
            },
        )

        if created:
            created_deliveries += 1
        else:
            updated_deliveries += 1

    return {
        "created_deliveries": created_deliveries,
        "updated_deliveries": updated_deliveries,
    }


def sync_deliveries_from_json(file_path):
    """
    Zweck:
    Laedt Lieferdaten aus einer JSON-Datei, prueft die Struktur und uebergibt
    die Datensaetze an die eigentliche Synchronisationslogik.
    Parameter:
    `file_path`: Pfad zur JSON-Datei.
    Rueckgabewert:
    Das Ergebnis von `sync_deliveries_from_records` als Dictionary mit Zaehlern.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise InventoryImportError(f"Datei nicht gefunden: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        try:
            records = json.load(f)
        except json.JSONDecodeError as e:
            raise InventoryImportError(f"Ungültige JSON-Datei: {e}")

    if not isinstance(records, list):
        raise InventoryImportError(
            "Die JSON-Datei muss eine Liste von Lieferobjekten enthalten."
        )

    return sync_deliveries_from_records(records)


def sync_deliveries_from_file(file_path):
    """
    Zweck:
    Waehlt anhand der Dateiendung den passenden Importpfad fuer Lieferdaten
    und validiert die erforderlichen Spalten bei tabellarischen Dateien.
    Parameter:
    `file_path`: Pfad zur Lieferdatei.
    Rueckgabewert:
    Ein Dictionary mit den Ergebnissen der Liefersynchronisation.
    """
    file_path = Path(file_path)

    suffix = file_path.suffix.lower()
    if suffix == ".json":
        return sync_deliveries_from_json(file_path)

    fieldnames, records = _load_tabular_records(file_path)
    required_columns = {
        "delivery_number",
        "product_sku",
        "quantity",
        "expected_date",
        "supplier",
        "status",
    }
    missing_columns = required_columns - set(fieldnames)
    if missing_columns:
        raise InventoryImportError(
            f"Fehlende Spalten in Datei: {', '.join(sorted(missing_columns))}"
        )

    return sync_deliveries_from_records(records)


def sync_deliveries_from_api(url):
    """
    Zweck:
    Ruft Lieferdaten von einer externen API ab, validiert die Antwort und gibt
    die Datensaetze an die Synchronisationslogik weiter.
    Parameter:
    `url`: Die URL der JSON-API fuer Lieferdaten.
    Rueckgabewert:
    Ein Dictionary mit Anzahlen neuer und aktualisierter Lieferungen.
    Bei Netz- oder Formatfehlern wird `InventoryImportError` ausgelost.
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        raise InventoryImportError(f"Fehler beim API-Aufruf: {e}")

    try:
        records = response.json()
    except ValueError:
        raise InventoryImportError("API-Antwort ist kein valides JSON.")

    if not isinstance(records, list):
        raise InventoryImportError(
            "Die API muss eine Liste von Lieferobjekten zurückgeben."
        )

    return sync_deliveries_from_records(records)


def get_expected_deliveries_for_product_until(product: Product, target_date):
    """
    Zweck:
    Summiert alle erwarteten, noch nicht gelieferten Mengen eines Produkts bis zu
    einem gegebenen Stichtag.
    Parameter:
    `product`: Die Produktinstanz, fuer die Liefermengen berechnet werden.
    `target_date`: Das letzte beruecksichtigte Lieferdatum.
    Rueckgabewert:
    Eine Ganzzahl mit der erwarteten Liefermenge bis einschliesslich des Stichtags.
    """
    deliveries = Delivery.objects.filter(
        product=product,
        status="expected",
        expected_date__lte=target_date,
    )
    return sum(delivery.quantity for delivery in deliveries)
