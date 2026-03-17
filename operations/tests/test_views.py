"""
Dateirolle:
Diese Datei testet die Dashboard-View inklusive Rendering, Filtern, Pagination,
Dateiimporten und der Integration des Supply-Copiloten im UI.
"""
import json
from datetime import date, timedelta
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from operations.llm_service import LLMIntegrationError
from operations.models import (
    BillOfMaterialItem,
    Delivery,
    Inventory,
    Product,
    ProductionOrder,
)


class DashboardViewTests(TestCase):
    def setUp(self):
        """
        Zweck:
        Baut einen realistischen Datenbestand fuer Dashboard-Tests auf, inklusive
        Produkten, Stueckliste, Bestandsdaten, Produktionsauftrag und Lieferung.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Die Methode bereitet die Testdatenbank vor.
        """
        mat_1 = Product.objects.create(
            sku="MAT-001",
            name="Stahlplatte",
            category="Rohmaterial",
        )
        mat_2 = Product.objects.create(
            sku="MAT-002",
            name="Schraubensatz",
            category="Kleinteile",
        )
        finished_product = Product.objects.create(
            sku="FERTIG-001",
            name="Montageset",
            category="Fertigprodukt",
        )

        BillOfMaterialItem.objects.create(
            finished_product=finished_product,
            component=mat_1,
            quantity_per_unit=2,
        )
        BillOfMaterialItem.objects.create(
            finished_product=finished_product,
            component=mat_2,
            quantity_per_unit=4,
        )

        Inventory.objects.create(product=mat_1, location="Frankfurt", quantity=120)
        Inventory.objects.create(product=mat_2, location="Frankfurt", quantity=50)
        mat_1.safety_stock = 140
        mat_1.reorder_point = 160
        mat_1.save()
        mat_2.safety_stock = 40
        mat_2.reorder_point = 70
        mat_2.save()

        ProductionOrder.objects.create(
            order_number="PO-2001",
            product=finished_product,
            quantity=20,
            due_date=date.today() + timedelta(days=2),
            status="planned",
        )

        Delivery.objects.create(
            delivery_number="DEL-5001",
            product=mat_2,
            quantity=100,
            expected_date=date.today() + timedelta(days=1),
            supplier="FastParts GmbH",
            status="expected",
        )

    def test_dashboard_view_returns_200(self):
        """
        Zweck:
        Prueft, dass das Dashboard erfolgreich erreichbar ist.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert den HTTP-Statuscode.
        """
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_contains_api_explorer_section(self):
        """
        Zweck:
        Prueft, dass der API-Explorer als neuer Frontend-Bereich im Dashboard gerendert wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die Sichtbarkeit der API-Oberflaeche.
        """
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "API Explorer")
        self.assertContains(response, "Inventory API")
        self.assertContains(response, "Orders API")
        self.assertContains(response, "Deliveries API")

    def test_dashboard_uses_correct_template(self):
        """
        Zweck:
        Prueft, dass die erwartete Template-Datei fuer das Dashboard verwendet wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert das gerenderte Template.
        """
        response = self.client.get(reverse("dashboard"))
        self.assertTemplateUsed(response, "operations/dashboard.html")

    def test_dashboard_contains_expected_content(self):
        """
        Zweck:
        Prueft, dass zentrale Inhalte und UI-Elemente im Dashboard-HTML vorhanden sind.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert den Seiteninhalt.
        """
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Supply Platform Dashboard")
        self.assertContains(response, "PO-2001")
        self.assertContains(response, "DEL-5001")
        self.assertContains(response, "Bestandswarnungen")
        self.assertContains(response, "Unter Sicherheitsbestand")
        self.assertContains(response, "data-interactive-table", html=False)
        self.assertContains(response, "Auftrag filtern")
        self.assertContains(response, "Filter zurücksetzen")
        self.assertContains(response, "Seite 1 von 1")

    def test_dashboard_can_filter_by_location(self):
        """
        Zweck:
        Prueft, dass ein Standortfilter korrekt auf Kennzahlen und Inhalte angewendet wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Filterung und Kontextdaten.
        """
        response = self.client.get(reverse("dashboard"), {"location": "Berlin"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_location"], "Berlin")
        self.assertEqual(response.context["total_inventory_records"], 0)
        self.assertEqual(response.context["below_safety_stock_count"], 2)
        self.assertEqual(response.context["below_reorder_point_count"], 2)
        self.assertContains(response, "Aktiver Standortfilter: Berlin")
        self.assertContains(response, "MAT-001")
        self.assertContains(response, "Fehlmenge 40")

    def test_dashboard_paginates_orders_and_preserves_filters_in_links(self):
        """
        Zweck:
        Prueft, dass Auftragslisten paginiert werden und aktive Filter in den Links erhalten bleiben.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Pagination und Querystrings.
        """
        product = Product.objects.get(sku="FERTIG-001")
        for index in range(2, 14):
            ProductionOrder.objects.create(
                order_number=f"PO-{2000 + index}",
                product=product,
                quantity=index,
                due_date=date.today() + timedelta(days=index),
                status="planned",
            )

        response = self.client.get(
            reverse("dashboard"), {"orders_page": 2, "location": "Frankfurt"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["orders"].number, 2)
        self.assertEqual(response.context["orders"].paginator.num_pages, 2)
        self.assertContains(response, "?orders_page=1&amp;location=Frankfurt")
        self.assertContains(response, "Seite 2 von 2")

    def test_dashboard_paginates_deliveries(self):
        """
        Zweck:
        Prueft, dass auch die Liste kommender Lieferungen korrekt paginiert wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test verifiziert die Liefer-Pagination.
        """
        product = Product.objects.get(sku="MAT-001")
        for index in range(2, 14):
            Delivery.objects.create(
                delivery_number=f"DEL-{5000 + index}",
                product=product,
                quantity=index * 10,
                expected_date=date.today() + timedelta(days=1),
                supplier="NordParts GmbH",
                status="expected",
            )

        response = self.client.get(reverse("dashboard"), {"deliveries_page": 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["upcoming_deliveries"].number, 2)
        self.assertEqual(response.context["upcoming_deliveries"].paginator.num_pages, 2)
        self.assertContains(response, "Seite 2 von 2")

    def test_dashboard_can_import_inventory_file(self):
        """
        Zweck:
        Prueft, dass ein Inventar-Upload aus dem Dashboard heraus verarbeitet
        und in Datenbankeintraege ueberfuehrt wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Import und Erfolgsmeldung.
        """
        upload = SimpleUploadedFile(
            "inventory.csv",
            (
                "sku,name,category,location,quantity\n"
                "MAT-010,Kupferdraht,Rohmaterial,Hamburg,25\n"
            ).encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(
            reverse("dashboard"),
            {"import_target": "inventory", "selected_location": "", "data_file": upload},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Product.objects.filter(sku="MAT-010").exists())
        self.assertTrue(
            Inventory.objects.filter(product__sku="MAT-010", location="Hamburg").exists()
        )
        self.assertContains(response, "Bestände importiert")

    def test_dashboard_can_import_production_orders_file(self):
        """
        Zweck:
        Prueft, dass Produktionsauftraege per Dashboard-Upload importiert werden koennen.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert den Importpfad fuer Auftragsdaten.
        """
        upload = SimpleUploadedFile(
            "orders.csv",
            (
                "order_number,product_sku,quantity,due_date,status\n"
                "PO-3001,FERTIG-001,5,2026-03-20,planned\n"
            ).encode("utf-8"),
            content_type="text/csv",
        )

        response = self.client.post(
            reverse("dashboard"),
            {"import_target": "orders", "selected_location": "", "data_file": upload},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ProductionOrder.objects.filter(order_number="PO-3001").exists())
        self.assertContains(response, "Produktionsaufträge importiert")

    def test_dashboard_can_import_deliveries_file(self):
        """
        Zweck:
        Prueft, dass Lieferdaten per Dashboard-Upload aus JSON verarbeitet werden koennen.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert den Lieferimport und die Rueckmeldung.
        """
        upload = SimpleUploadedFile(
            "deliveries.json",
            (
                '[{"delivery_number":"DEL-7001","product_sku":"MAT-001",'
                '"quantity":30,"expected_date":"2026-03-18",'
                '"supplier":"NordParts","status":"expected"}]'
            ).encode("utf-8"),
            content_type="application/json",
        )

        response = self.client.post(
            reverse("dashboard"),
            {"import_target": "deliveries", "selected_location": "", "data_file": upload},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Delivery.objects.filter(delivery_number="DEL-7001").exists())
        self.assertContains(response, "Lieferungen importiert")

    def test_dashboard_can_answer_llm_question(self):
        """
        Zweck:
        Prueft, dass eine LLM-Anfrage aus dem Dashboard an die Service-Schicht
        uebergeben und die Antwort im Frontend angezeigt wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die UI-Integration des Copiloten.
        """
        with patch("operations.views.answer_supply_question") as ask_llm:
            ask_llm.return_value = {
                "answer": "Das groesste Risiko ist MAT-001 in Frankfurt.",
                "model": "gpt-4.1-mini",
                "provider": "openai",
            }
            response = self.client.post(
                reverse("dashboard"),
                {
                    "action": "ask_llm",
                    "selected_location": "Frankfurt",
                    "llm_provider": "openai",
                    "llm_question": "Was ist das groesste Risiko?",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Supply Copilot")
        self.assertContains(response, "Das groesste Risiko ist MAT-001 in Frankfurt.")
        self.assertContains(response, "gpt-4.1-mini")
        self.assertContains(response, "Provider: openai")

    def test_inventory_api_returns_filtered_inventory_as_json(self):
        """
        Zweck:
        Prueft, dass die Inventory-API Bestandsdaten als JSON zurueckgibt
        und Standortfilter ueber Query-Parameter unterstuetzt.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Statuscode, JSON-Struktur und Filterung.
        """
        Product.objects.create(
            sku="MAT-003",
            name="Kupferdraht",
            category="Rohmaterial",
        )

        response = self.client.get(reverse("api_inventory"), {"location": "Frankfurt"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["results"][0]["location"], "Frankfurt")
        self.assertEqual(payload["results"][0]["sku"], "MAT-001")
        self.assertIn("safety_stock", payload["results"][0])

    def test_orders_api_returns_filtered_orders_as_json(self):
        """
        Zweck:
        Prueft, dass die Orders-API Produktionsauftraege als JSON ausliefert
        und nach Status gefiltert werden kann.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die JSON-Daten des Endpunkts.
        """
        product = Product.objects.get(sku="FERTIG-001")
        ProductionOrder.objects.create(
            order_number="PO-2002",
            product=product,
            quantity=5,
            due_date=date.today() + timedelta(days=4),
            status="completed",
        )

        response = self.client.get(reverse("api_orders"), {"status": "planned"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["order_number"], "PO-2001")
        self.assertEqual(payload["results"][0]["status"], "planned")

    def test_deliveries_api_returns_filtered_deliveries_as_json(self):
        """
        Zweck:
        Prueft, dass die Deliveries-API Lieferungen als JSON ausliefert
        und nach Lieferstatus gefiltert werden kann.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die JSON-Struktur des Endpunkts.
        """
        product = Product.objects.get(sku="MAT-001")
        Delivery.objects.create(
            delivery_number="DEL-5002",
            product=product,
            quantity=20,
            expected_date=date.today() + timedelta(days=3),
            supplier="NordParts GmbH",
            status="delivered",
        )

        response = self.client.get(reverse("api_deliveries"), {"status": "expected"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["delivery_number"], "DEL-5001")
        self.assertEqual(payload["results"][0]["status"], "expected")

    def test_ask_llm_api_returns_contextual_response_as_json(self):
        """
        Zweck:
        Prueft, dass die neue LLM-API JSON akzeptiert, die Service-Schicht aufruft
        und Antwortdaten inklusive Kontext als JSON zurueckliefert.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Statuscode und JSON-Struktur.
        """
        with patch("operations.views.answer_supply_question") as ask_llm:
            ask_llm.return_value = {
                "answer": "MAT-001 ist das groesste Risiko.",
                "model": "llama3.1",
                "provider": "ollama",
                "context": {"location": "Frankfurt", "metrics": {"open_orders_count": 1}},
            }
            response = self.client.post(
                reverse("api_ask_llm"),
                data=json.dumps(
                    {
                        "question": "Welche Risiken sind in den naechsten 7 Tagen am wichtigsten?",
                        "location": "Frankfurt",
                        "provider": "ollama",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["answer"], "MAT-001 ist das groesste Risiko.")
        self.assertEqual(payload["model"], "llama3.1")
        self.assertEqual(payload["provider"], "ollama")
        self.assertEqual(payload["location"], "Frankfurt")
        self.assertEqual(payload["context"]["location"], "Frankfurt")

    def test_ask_llm_api_returns_error_for_invalid_json(self):
        """
        Zweck:
        Prueft, dass die LLM-API ungueltiges JSON sauber mit HTTP 400 ablehnt.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die Fehlerbehandlung des Endpunkts.
        """
        response = self.client.post(
            reverse("api_ask_llm"),
            data="{invalid json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Ungueltiger JSON-Body.")

    def test_ask_llm_api_returns_error_from_llm_service(self):
        """
        Zweck:
        Prueft, dass Integrationsfehler aus der LLM-Service-Schicht als HTTP 400
        an API-Clients zurueckgegeben werden.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die API-Fehlerantwort.
        """
        with patch("operations.views.answer_supply_question") as ask_llm:
            ask_llm.side_effect = LLMIntegrationError("Bitte eine Frage eingeben.")
            response = self.client.post(
                reverse("api_ask_llm"),
                data=json.dumps({"question": ""}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Bitte eine Frage eingeben.")

    def test_ask_llm_api_accepts_get_with_query_params(self):
        """
        Zweck:
        Prueft, dass die LLM-API auch GET mit Query-Parametern fuer einfache
        Browser- und Testaufrufe akzeptiert.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die GET-Unterstuetzung.
        """
        with patch("operations.views.answer_supply_question") as ask_llm:
            ask_llm.return_value = {
                "answer": "MAT-001 ist das groesste Risiko.",
                "model": "llama3.1",
                "provider": "ollama",
                "context": {"location": "Frankfurt"},
            }
            response = self.client.get(
                reverse("api_ask_llm"),
                {
                    "question": "Welche Risiken sind in den naechsten 7 Tagen am wichtigsten?",
                    "location": "Frankfurt",
                    "provider": "ollama",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider"], "ollama")

    def test_inventory_frontend_page_renders(self):
        """
        Zweck:
        Prueft, dass die separate Inventory-Frontend-Seite erfolgreich gerendert wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Route und Grundinhalt der Seite.
        """
        response = self.client.get(reverse("inventory_frontend"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inventory API")
        self.assertContains(response, reverse("api_inventory"))

    def test_orders_frontend_page_renders(self):
        """
        Zweck:
        Prueft, dass die separate Orders-Frontend-Seite erfolgreich gerendert wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Route und Grundinhalt der Seite.
        """
        response = self.client.get(reverse("orders_frontend"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Orders API")
        self.assertContains(response, reverse("api_orders"))

    def test_deliveries_frontend_page_renders(self):
        """
        Zweck:
        Prueft, dass die separate Deliveries-Frontend-Seite erfolgreich gerendert wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert Route und Grundinhalt der Seite.
        """
        response = self.client.get(reverse("deliveries_frontend"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Deliveries API")
        self.assertContains(response, reverse("api_deliveries"))
