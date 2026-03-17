#!/usr/bin/env python
"""
Dateirolle:
Diese Datei ist der Einstiegspunkt fuer Django-Management-Kommandos im Projekt.
Sie setzt das Standard-Settings-Modul und uebergibt die Kommandozeilenargumente
an Django, damit Befehle wie `runserver`, `migrate` oder `test` ausgefuehrt werden.
"""

import os
import sys


def main():
    """
    Zweck:
    Startet das Django-Kommandozeilenprogramm mit den uebergebenen Argumenten.

    Parameter:
    Keine direkten Parameter. Die Funktion liest die Kommandozeilenargumente aus `sys.argv`.

    Rueckgabewert:
    Kein Rueckgabewert. Bei Erfolg wird das passende Django-Kommando ausgefuehrt,
    bei Fehlern wird eine ImportError-Exception ausgeloest.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
