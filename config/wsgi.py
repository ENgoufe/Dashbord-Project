"""
Dateirolle:
Diese Datei stellt den WSGI-Einstiegspunkt fuer das Projekt bereit.
Sie wird von klassischen Python-Webservern genutzt, um die Django-Anwendung
in einer synchronen Produktionsumgebung bereitzustellen.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
