# Supply Platform

Kleine Django-Anwendung zur Verwaltung von Bestands-, Produktions- und Lieferdaten.

## Funktionsumfang

- Verwaltung von Produkten und Stücklisten
- Import von Lagerbeständen aus CSV- und Excel-Dateien (`.csv`, `.xlsx`)
- Import von Produktionsaufträgen aus CSV- und Excel-Dateien (`.csv`, `.xlsx`)
- Import von Lieferdaten aus JSON-, CSV- und Excel-Dateien (`.json`, `.csv`, `.xlsx`)
- Synchronisation von Lieferdaten aus einer API
- Analyse der Materialverfügbarkeit für Produktionsaufträge
- Sicherheitsbestände und Meldebestände pro Produkt
- Dashboard mit Kennzahlen, Engpässen, Bestandswarnungen, anstehenden Lieferungen und Direkt-Uploads
- Dashboard mit Kennzahlen, Engpässen, Bestandswarnungen, anstehenden Lieferungen, Direkt-Uploads und einem LLM-Copilot
- Pflege aller Kernobjekte über das Django-Admin

## Technischer Aufbau

Die Anwendung besteht aus einer einzelnen Django-App `operations`.

Wichtige Module:

- `operations/models.py`: Domänenmodelle für Produkte, Stücklisten, Bestand, Aufträge und Lieferungen
- `operations/services.py`: Importlogik, Liefer-Synchronisation, Dashboard-Aggregation und Machbarkeitsanalyse
- `operations/views.py`: Dashboard-Ansicht mit Filtern, Pagination und Datei-Uploads
- `operations/management/commands/`: CLI-Commands für Datenimporte
- `operations/tests/`: Tests für Modelle, Services und Views

## Datenmodell

Die wichtigsten Entitäten sind:

- `Product`: Artikelstammdaten mit SKU, Name, Kategorie, Sicherheitsbestand und Meldebestand
- `BillOfMaterialItem`: Verknüpfung zwischen Endprodukt und Komponente inklusive Mengenbedarf
- `Inventory`: Lagerbestand eines Produkts pro Standort
- `ProductionOrder`: Produktionsauftrag mit Produkt, Menge, Fälligkeit und Status
- `Delivery`: Erwartete oder erfolgte Lieferung eines Produkts

## Voraussetzungen

- Python 3.12
- Virtuelle Umgebung empfohlen

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Danach ist das Dashboard unter `http://127.0.0.1:8000/` erreichbar.

## Dashboard-Importe

Im Dashboard können Dateien direkt hochgeladen und in die passenden Tabellen übernommen werden:

- Bestände: `.csv`, `.xlsx`
- Produktionsaufträge: `.csv`, `.xlsx`
- Lieferungen: `.json`, `.csv`, `.xlsx`

Die Seite zeigt nach jedem Import eine Erfolgs- oder Fehlermeldung an.

## LLM-Copilot

Im Dashboard gibt es einen einfachen Supply-Copilot fuer Fragen zu Risiken, Engpaessen und Lieferungen.

Der Provider kann direkt im Dashboard ausgewaehlt werden.

Unterstuetzte Provider:

- `openai`
- `ollama`

Optionale Umgebungsvariablen:

- `LLM_PROVIDER`: Standard-Provider fuer den Copilot, z. B. `openai` oder `ollama`
- `OPENAI_API_KEY`: API-Key fuer OpenAI
- `OPENAI_MODEL`: optional, Standard `gpt-4.1-mini`
- `OPENAI_RESPONSES_URL`: optional, Standard `https://api.openai.com/v1/responses`
- `OLLAMA_MODEL`: optional, Standard `llama3.1`
- `OLLAMA_URL`: optional, Standard `http://localhost:11434/api/generate`
- `OLLAMA_TIMEOUT_SECONDS`: optional, Standard `180`

Fuer externe Aufrufe steht zusaetzlich ein API-Endpunkt unter `POST /api/ask-llm/` zur Verfuegung.
Er nimmt `question`, optional `location` und optional `provider` entgegen, baut den DB-Kontext
automatisch ueber die Dashboard-Daten auf und gibt Antwort, Modell, Provider und Kontext als JSON zurueck.

PowerShell-Beispiel mit lokalem Ollama-Provider:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/ask-llm/ `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"question":"Welche Risiken sind in den naechsten 7 Tagen am wichtigsten?","location":"Frankfurt","provider":"ollama"}'
```

Wenn lokale Modelle auf schwacher Hardware laenger brauchen, kann das Timeout erhoeht werden:

```powershell
$env:OLLAMA_TIMEOUT_SECONDS="240"
python manage.py runserver
```

### Unterstützte Spalten für Bestandsimporte

Pflichtspalten:

- `sku`
- `name`
- `category`
- `location`
- `quantity`

Optionale Spalten:

- `safety_stock`
- `reorder_point`

Wenn die optionalen Spalten gesetzt sind, werden sie direkt am Produkt gepflegt. Dabei gilt die Fachregel: `reorder_point` darf nicht kleiner als `safety_stock` sein.

## Download-Vorlagen

Vorlagen für Dashboard-Uploads liegen unter `operations/download_templates/`:

- `inventory_template.csv`
- `inventory_template.xlsx`
- `production_orders_template.csv`
- `production_orders_template.xlsx`
- `deliveries_template.json`
- `deliveries_template.csv`
- `deliveries_template.xlsx`

Die Bestandsvorlagen enthalten bereits die optionalen Spalten `safety_stock` und `reorder_point`.

## Beispiel-Datenquellen

Im Projekt liegen zusätzlich Beispieldateien im Verzeichnis `data/`:

- `data/inventory.csv`
- `data/order.csv`
- `data/deliveries.json`

Für Excel-Importe werden aktuell `.xlsx`-Dateien unterstützt.

## Management-Commands

### Lagerbestände importieren

```bash
python manage.py import_inventory data/inventory.csv
```

```bash
python manage.py import_inventory data/inventory.xlsx
```

### Lieferdaten aus JSON importieren

```bash
python manage.py sync_deliveries --file data/deliveries.json
```

### Lieferdaten aus einer API synchronisieren

```bash
python manage.py sync_deliveries --url https://example.com/api/deliveries
```

## Tests

Gezielt ausführbare Tests:

```bash
python manage.py test operations.tests.test_models operations.tests.test_services operations.tests.test_views
```

Hinweis: Der generische Aufruf `python manage.py test` funktioniert aktuell nur dann sauber, wenn keine Namenskollision zwischen `operations/tests.py` und dem Paket `operations/tests/` besteht.

## Hinweise zum aktuellen Stand

- Standardmäßig wird SQLite verwendet.
- Die Anwendung ist aktuell auf lokale Entwicklung ausgelegt.
- Für produktiven Betrieb müssten insbesondere `DEBUG`, `ALLOWED_HOSTS` und `SECRET_KEY` sauber über Umgebungsvariablen konfiguriert werden.
