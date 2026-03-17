"""
Dateirolle:
Diese Datei testet die LLM-Integrationsschicht fuer Provider-Auswahl,
API-Schluessel-Pruefung und Antwortverarbeitung.
"""
from unittest.mock import Mock, patch

from django.test import TestCase

from operations.llm_service import LLMIntegrationError, answer_supply_question
from operations.models import Delivery, Inventory, Product


class LLMServiceTests(TestCase):
    def setUp(self):
        """
        Zweck:
        Baut einen kleinen fachlichen Datenbestand fuer LLM-bezogene Tests auf,
        damit die Kontexterstellung realistische Daten enthaelt.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Die Methode legt Testdaten in der Testdatenbank an.
        """
        self.product = Product.objects.create(
            sku="MAT-001",
            name="Stahlplatte",
            category="Rohmaterial",
            safety_stock=50,
            reorder_point=80,
        )
        Inventory.objects.create(product=self.product, location="Frankfurt", quantity=30)
        Delivery.objects.create(
            delivery_number="DEL-9001",
            product=self.product,
            quantity=25,
            expected_date="2026-03-20",
            supplier="NordParts GmbH",
            status="expected",
        )

    def test_answer_supply_question_requires_api_key(self):
        """
        Zweck:
        Prueft, dass ohne OpenAI-API-Key ein Integrationsfehler ausgelost wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die Fehlerbehandlung.
        """
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(LLMIntegrationError):
                answer_supply_question("Welche Risiken gibt es?")

    def test_answer_supply_question_returns_text_from_openai_response(self):
        """
        Zweck:
        Prueft, dass eine simulierte OpenAI-Antwort korrekt in Text, Modellname
        und Kontextdaten ueberfuehrt wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die Struktur des Rueckgabewerts.
        """
        response = Mock()
        response.json.return_value = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": "MAT-001 ist kritisch wegen zu niedrigem Bestand.",
                        }
                    ]
                }
            ]
        }
        response.raise_for_status.return_value = None

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch("operations.llm_service.requests.post", return_value=response) as post:
                result = answer_supply_question(
                    "Welche Risiken gibt es?", location="Frankfurt"
                )

        self.assertIn("kritisch", result["answer"])
        self.assertEqual(result["model"], "gpt-4.1-mini")
        self.assertEqual(result["context"]["location"], "Frankfurt")
        post.assert_called_once()

    def test_answer_supply_question_can_use_ollama_provider(self):
        """
        Zweck:
        Prueft, dass alternativ ein lokaler Ollama-Provider genutzt werden kann
        und dessen Antwort korrekt zurueckgegeben wird.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test prueft Provider-spezifisches Verhalten.
        """
        response = Mock()
        response.json.return_value = {
            "response": "Lokales Modell: MAT-001 ist unter Sicherheitsbestand."
        }
        response.raise_for_status.return_value = None

        with patch.dict("os.environ", {"OLLAMA_MODEL": "llama3.1"}, clear=True):
            with patch("operations.llm_service.requests.post", return_value=response) as post:
                result = answer_supply_question(
                    "Welche Risiken gibt es?",
                    location="Frankfurt",
                    provider="ollama",
                )

        self.assertIn("Lokales Modell", result["answer"])
        self.assertEqual(result["model"], "llama3.1")
        self.assertEqual(result["provider"], "ollama")
        post.assert_called_once()

    def test_answer_supply_question_uses_configurable_ollama_timeout(self):
        """
        Zweck:
        Prueft, dass der Ollama-Aufruf ein ueber Umgebungsvariablen gesetztes
        Timeout verwendet.
        Parameter:
        `self`: Die aktuelle TestCase-Instanz.
        Rueckgabewert:
        Kein Rueckgabewert. Der Test validiert die Timeout-Konfiguration.
        """
        response = Mock()
        response.json.return_value = {
            "response": "Lokales Modell: MAT-001 ist unter Sicherheitsbestand."
        }
        response.raise_for_status.return_value = None

        with patch.dict(
            "os.environ",
            {"OLLAMA_MODEL": "llama3.1", "OLLAMA_TIMEOUT_SECONDS": "240"},
            clear=True,
        ):
            with patch("operations.llm_service.requests.post", return_value=response) as post:
                answer_supply_question(
                    "Welche Risiken gibt es?",
                    location="Frankfurt",
                    provider="ollama",
                )

        self.assertEqual(post.call_args.kwargs["timeout"], 240)
