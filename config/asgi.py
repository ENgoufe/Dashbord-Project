"""
Dateirolle:
Diese Datei stellt den ASGI-Einstiegspunkt fuer das Projekt bereit.
Sie wird verwendet, wenn die Anwendung ueber einen ASGI-Server laeuft,
zum Beispiel fuer asynchrone Deployments oder WebSocket-faehige Setups.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
