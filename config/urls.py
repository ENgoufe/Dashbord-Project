"""
Dateirolle:
Diese Datei verbindet die oberste URL-Konfiguration des Projekts mit den
einzelnen App-Routen. Sie leitet den Admin-Bereich an Django weiter und bindet
die URL-Muster der `operations`-App als Standardroute ein.
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("operations.urls")),
]
