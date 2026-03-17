"""
Dateirolle:
Diese Datei definiert die Django-App-Konfiguration fuer die `operations`-App.
Darin werden Metadaten der App hinterlegt, die Django beim Laden der Anwendung nutzt.
"""
from django.apps import AppConfig


class OperationsConfig(AppConfig):
    """
    Zweck:
    Beschreibt die Grundkonfiguration der `operations`-App fuer Django.
    Parameter:
    Keine Methodenparameter in dieser Klasse. Django liest die Klassenattribute beim Start.
    Rueckgabewert:
    Kein direkter Rueckgabewert. Die Klasse liefert Konfigurationsinformationen fuer Django.
    """
    name = "operations"
