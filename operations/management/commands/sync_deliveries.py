"""
Dateirolle:
Dieses Management-Kommando synchronisiert Lieferdaten aus einer JSON-Datei
oder aus einer externen API ueber die Django-Kommandozeile.
"""
from django.core.management.base import BaseCommand, CommandError

from operations.services import (
    InventoryImportError,
    sync_deliveries_from_api,
    sync_deliveries_from_json,
)


class Command(BaseCommand):
    help = "Synchronisiert Lieferdaten aus JSON-Datei oder API"

    def add_arguments(self, parser):
        """
        Zweck:
        Registriert die optionalen Parameter fuer Dateiquelle oder API-URL.
        Parameter:
        `self`: Die aktuelle Command-Instanz.
        `parser`: Der von Django uebergebene Argument-Parser.
        Rueckgabewert:
        Kein Rueckgabewert. Die Argumente werden direkt am Parser angelegt.
        """
        parser.add_argument(
            "--file", type=str, help="Pfad zu einer JSON-Datei mit Lieferdaten"
        )
        parser.add_argument("--url", type=str, help="URL einer API mit Lieferdaten")

    def handle(self, *args, **options):
        """
        Zweck:
        Validiert die gewaehlte Datenquelle, fuehrt die Liefersynchronisation aus
        und schreibt das Ergebnis in die Konsole.
        Parameter:
        `self`: Die aktuelle Command-Instanz.
        `*args`: Nicht verwendete Positionsargumente.
        `**options`: Enthalten optional `file` oder `url` als Datenquelle.
        Rueckgabewert:
        Kein Rueckgabewert. Bei Bedien- oder Importfehlern wird `CommandError` ausgeloest.
        """
        file_path = options.get("file")
        url = options.get("url")

        if not file_path and not url:
            raise CommandError("Bitte entweder --file oder --url angeben.")

        if file_path and url:
            raise CommandError("Bitte nur eine Quelle verwenden: --file oder --url.")

        try:
            if file_path:
                result = sync_deliveries_from_json(file_path)
            else:
                result = sync_deliveries_from_api(url)
        except InventoryImportError as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS("Liefersynchronisation erfolgreich."))
        self.stdout.write(f"Neue Lieferungen: {result['created_deliveries']}")
        self.stdout.write(f"Aktualisierte Lieferungen: {result['updated_deliveries']}")
