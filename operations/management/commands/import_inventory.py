"""
Dateirolle:
Dieses Management-Kommando importiert Lagerbestaende aus einer CSV- oder XLSX-Datei.
Es macht die Importlogik der Service-Schicht ueber die Django-Kommandozeile nutzbar
und schreibt die Ergebniszaehler in das Terminal.
"""
from django.core.management.base import BaseCommand, CommandError

from operations.services import InventoryImportError, import_inventory_from_file


class Command(BaseCommand):
    help = "Importiert Lagerbestaende aus einer CSV- oder Excel-Datei (.xlsx)"

    def add_arguments(self, parser):
        """
        Zweck:
        Registriert das verpflichtende Dateipfad-Argument fuer den Bestandsimport.
        Parameter:
        `self`: Die aktuelle Command-Instanz.
        `parser`: Der von Django bereitgestellte Argument-Parser.
        Rueckgabewert:
        Kein Rueckgabewert. Der Parser wird direkt um das Argument erweitert.
        """
        parser.add_argument(
            "file_path", type=str, help="Pfad zur CSV- oder Excel-Datei (.xlsx)"
        )

    def handle(self, *args, **options):
        """
        Zweck:
        Fuehrt den Bestandsimport aus, faengt fachliche Importfehler ab und gibt
        die Anzahl neuer und aktualisierter Datensaetze im Terminal aus.
        Parameter:
        `self`: Die aktuelle Command-Instanz.
        `*args`: Nicht verwendete Positionsargumente von Django.
        `**options`: Enthalten das Kommandozeilenargument `file_path`.
        Rueckgabewert:
        Kein Rueckgabewert. Bei Importproblemen wird `CommandError` ausgeloest.
        """
        file_path = options["file_path"]

        try:
            result = import_inventory_from_file(file_path)
        except InventoryImportError as e:
            raise CommandError(str(e))

        self.stdout.write(self.style.SUCCESS("Import erfolgreich."))
        self.stdout.write(f"Neue Produkte: {result['created_products']}")
        self.stdout.write(f"Aktualisierte Produkte: {result['updated_products']}")
        self.stdout.write(f"Neue Bestaende: {result['created_inventories']}")
        self.stdout.write(f"Aktualisierte Bestaende: {result['updated_inventories']}")
