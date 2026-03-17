"""
Dateirolle:
Diese Datei enthaelt die Web-Views und Hilfsfunktionen fuer das Dashboard.
Sie verarbeitet Filter, Pagination, Dateiimporte, JSON-APIs und die
Anbindung separater Frontend-Seiten an das Backend.
"""
import json
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponseNotAllowed
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt

from .llm_service import (
    LLMIntegrationError,
    answer_supply_question,
    get_default_llm_provider,
    get_supported_llm_providers,
)
from .models import Delivery, Inventory, ProductionOrder
from .services import (
    InventoryImportError,
    get_dashboard_metrics,
    get_dashboard_order_data,
    get_upcoming_deliveries,
    import_inventory_from_file,
    import_production_orders_from_file,
    sync_deliveries_from_file,
)

TABLE_PAGE_SIZE = 5


def _store_uploaded_file(uploaded_file):
    """
    Zweck:
    Speichert eine hochgeladene Datei temporaer auf dem Dateisystem, damit sie
    von den Import-Services weiterverarbeitet werden kann.

    Parameter:
    `uploaded_file`: Ein Django-Uploadobjekt mit Dateiname und Chunk-Zugriff.

    Rueckgabewert:
    Ein `Path`-Objekt zur temporaer gespeicherten Datei.
    """
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        for chunk in uploaded_file.chunks():
            temp_file.write(chunk)
        return Path(temp_file.name)


def _build_dashboard_redirect(selected_location):
    """
    Zweck:
    Baut einen Redirect zur Dashboard-Route und haengt bei Bedarf den aktiven
    Standortfilter wieder an die URL an.

    Parameter:
    `selected_location`: Optionaler Standort als String.

    Rueckgabewert:
    Ein Django-Redirect-Response-Objekt.
    """
    dashboard_url = reverse("dashboard")
    if selected_location:
        return redirect(f"{dashboard_url}?location={selected_location}")
    return redirect(dashboard_url)


def _paginate_items(request, items, page_param):
    """
    Zweck:
    Kapselt die Paginierung fuer Listen im Dashboard, damit dieselbe Logik
    fuer mehrere Tabellen wiederverwendet werden kann.

    Parameter:
    `request`: Das aktuelle Django-Request-Objekt.
    `items`: Die zu paginierende Liste oder QuerySet-Struktur.
    `page_param`: Name des Query-Parameters fuer die gewuenschte Seite.

    Rueckgabewert:
    Ein Django-Page-Objekt mit den Datensaetzen der angeforderten Seite.
    """
    paginator = Paginator(items, TABLE_PAGE_SIZE)
    page_number = request.GET.get(page_param, 1)
    return paginator.get_page(page_number)


def _querystring_without(request, *keys_to_remove, **updates):
    """
    Zweck:
    Erzeugt einen Querystring auf Basis der aktuellen Request-Parameter, entfernt
    bestimmte Schluessel und aktualisiert optional einzelne Werte.

    Parameter:
    `request`: Das aktuelle Django-Request-Objekt.
    `keys_to_remove`: Beliebig viele Parameter, die entfernt werden sollen.
    `updates`: Schluessel-Wert-Paare, die gesetzt oder geloescht werden sollen.

    Rueckgabewert:
    Ein String mit Querystring-Anteil, der mit `&` beginnt oder leer ist.
    """
    query_data = request.GET.copy()
    for key in keys_to_remove:
        query_data.pop(key, None)
    for key, value in updates.items():
        if value in ("", None):
            query_data.pop(key, None)
        else:
            query_data[key] = value
    encoded = urlencode(query_data, doseq=True)
    return f"&{encoded}" if encoded else ""


def _handle_dashboard_upload(request, selected_location):
    """
    Zweck:
    Verarbeitet Import-Uploads aus dem Dashboard, ruft den passenden Import-Service auf
    und schreibt Erfolgs- oder Fehlermeldungen in das Django-Messages-Framework.

    Parameter:
    `request`: Das aktuelle POST-Request-Objekt mit Formular- und Dateidaten.
    `selected_location`: Aktiver Standortfilter, der nach dem Redirect erhalten bleiben soll.

    Rueckgabewert:
    Ein Redirect-Response zurueck auf das Dashboard.
    """
    import_target = request.POST.get("import_target", "").strip()
    uploaded_file = request.FILES.get("data_file")

    if not import_target:
        messages.error(request, "Importziel fehlt.")
        return _build_dashboard_redirect(selected_location)

    if uploaded_file is None:
        messages.error(request, "Bitte eine Datei auswaehlen.")
        return _build_dashboard_redirect(selected_location)

    temp_path = _store_uploaded_file(uploaded_file)
    try:
        if import_target == "inventory":
            result = import_inventory_from_file(temp_path)
            messages.success(
                request,
                "Bestaende importiert. "
                f"Produkte neu: {result['created_products']}, "
                f"Produkte aktualisiert: {result['updated_products']}, "
                f"Bestaende neu: {result['created_inventories']}, "
                f"Bestaende aktualisiert: {result['updated_inventories']}.",
            )
        elif import_target == "orders":
            result = import_production_orders_from_file(temp_path)
            messages.success(
                request,
                "Produktionsauftraege importiert. "
                f"Neu: {result['created_orders']}, "
                f"Aktualisiert: {result['updated_orders']}.",
            )
        elif import_target == "deliveries":
            result = sync_deliveries_from_file(temp_path)
            messages.success(
                request,
                "Lieferungen importiert. "
                f"Neu: {result['created_deliveries']}, "
                f"Aktualisiert: {result['updated_deliveries']}.",
            )
        else:
            messages.error(request, "Unbekanntes Importziel.")
    except InventoryImportError as exc:
        messages.error(request, str(exc))
    finally:
        temp_path.unlink(missing_ok=True)

    return _build_dashboard_redirect(selected_location)


def _serialize_inventory(inventory):
    """
    Zweck:
    Wandelt einen Bestandsdatensatz in ein JSON-kompatibles Dictionary fuer die API um.

    Parameter:
    `inventory`: Eine `Inventory`-Instanz inklusive verknuepftem Produkt.

    Rueckgabewert:
    Ein Dictionary mit Produkt-, Standort- und Bestandsinformationen.
    """
    return {
        "sku": inventory.product.sku,
        "product_name": inventory.product.name,
        "category": inventory.product.category,
        "location": inventory.location,
        "quantity": inventory.quantity,
        "safety_stock": inventory.product.safety_stock,
        "reorder_point": inventory.product.reorder_point,
        "last_updated": inventory.last_updated.isoformat(),
    }


def _serialize_order(order):
    """
    Zweck:
    Wandelt einen Produktionsauftrag in ein JSON-kompatibles Dictionary fuer die API um.

    Parameter:
    `order`: Eine `ProductionOrder`-Instanz inklusive verknuepftem Produkt.

    Rueckgabewert:
    Ein Dictionary mit Auftrags-, Produkt- und Termininformationen.
    """
    return {
        "order_number": order.order_number,
        "product_sku": order.product.sku,
        "product_name": order.product.name,
        "quantity": order.quantity,
        "due_date": order.due_date.isoformat(),
        "status": order.status,
    }


def _serialize_delivery(delivery):
    """
    Zweck:
    Wandelt eine Lieferung in ein JSON-kompatibles Dictionary fuer die API um.

    Parameter:
    `delivery`: Eine `Delivery`-Instanz inklusive verknuepftem Produkt.

    Rueckgabewert:
    Ein Dictionary mit Liefer-, Produkt- und Statusinformationen.
    """
    return {
        "delivery_number": delivery.delivery_number,
        "product_sku": delivery.product.sku,
        "product_name": delivery.product.name,
        "quantity": delivery.quantity,
        "expected_date": delivery.expected_date.isoformat(),
        "supplier": delivery.supplier,
        "status": delivery.status,
    }


@require_GET
def inventory_api_view(request):
    """
    Zweck:
    Liefert alle Lagerbestaende als JSON-API und erlaubt optional die Filterung
    nach Standort ueber den Query-Parameter `location`.

    Parameter:
    `request`: Das aktuelle Django-Request-Objekt fuer einen GET-Aufruf.

    Rueckgabewert:
    Eine `JsonResponse` mit einer Liste serialisierter Bestandsdatensaetze.
    """
    location = request.GET.get("location", "").strip()
    inventories = Inventory.objects.select_related("product").order_by(
        "location", "product__sku"
    )
    if location:
        inventories = inventories.filter(location=location)

    data = [_serialize_inventory(inventory) for inventory in inventories]
    return JsonResponse({"count": len(data), "results": data})


@require_GET
def orders_api_view(request):
    """
    Zweck:
    Liefert Produktionsauftraege als JSON-API und erlaubt optional die Filterung
    nach Status ueber den Query-Parameter `status`.

    Parameter:
    `request`: Das aktuelle Django-Request-Objekt fuer einen GET-Aufruf.

    Rueckgabewert:
    Eine `JsonResponse` mit einer Liste serialisierter Produktionsauftraege.
    """
    status = request.GET.get("status", "").strip()
    orders = ProductionOrder.objects.select_related("product").order_by("due_date")
    if status:
        orders = orders.filter(status=status)

    data = [_serialize_order(order) for order in orders]
    return JsonResponse({"count": len(data), "results": data})


@require_GET
def deliveries_api_view(request):
    """
    Zweck:
    Liefert Lieferungen als JSON-API und erlaubt optional die Filterung
    nach Lieferstatus ueber den Query-Parameter `status`.

    Parameter:
    `request`: Das aktuelle Django-Request-Objekt fuer einen GET-Aufruf.

    Rueckgabewert:
    Eine `JsonResponse` mit einer Liste serialisierter Lieferungen.
    """
    status = request.GET.get("status", "").strip()
    deliveries = Delivery.objects.select_related("product").order_by("expected_date")
    if status:
        deliveries = deliveries.filter(status=status)

    data = [_serialize_delivery(delivery) for delivery in deliveries]
    return JsonResponse({"count": len(data), "results": data})


@csrf_exempt
def ask_llm_api_view(request):
    """
    Zweck:
    Nimmt LLM-Fragen als JSON-API entgegen, baut automatisch den fachlichen
    Kontext aus der Datenbank auf und liefert die Modellantwort als JSON zurueck.

    Parameter:
    `request`: Das aktuelle Django-Request-Objekt. Erwartet POST mit JSON-Body
    oder Formdaten.

    Rueckgabewert:
    Eine `JsonResponse` mit Frage, Antwort, Provider, Modell und verwendetem Kontext
    oder eine Fehlermeldung mit passendem HTTP-Status.
    """
    if request.method == "GET":
        payload = request.GET
    elif request.method == "POST":
        payload = request.POST
    else:
        return HttpResponseNotAllowed(["GET", "POST"])

    if (
        request.method == "POST"
        and request.content_type
        and "application/json" in request.content_type
    ):
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JsonResponse(
                {"error": "Ungueltiger JSON-Body."},
                status=400,
            )

    question = str(payload.get("question", "")).strip()
    location = str(payload.get("location", "")).strip() or None
    provider = str(payload.get("provider", "")).strip() or None

    try:
        llm_result = answer_supply_question(
            question,
            location=location,
            provider=provider,
        )
    except LLMIntegrationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(
        {
            "question": question,
            "answer": llm_result["answer"],
            "model": llm_result["model"],
            "provider": llm_result["provider"],
            "location": location or "all",
            "context": llm_result["context"],
        }
    )


def inventory_frontend_view(request):
    """
    Zweck:
    Rendert eine eigenstaendige Frontend-Seite fuer die Bestands-API,
    damit Bestandsdaten ausserhalb des Dashboards betrachtet werden koennen.

    Parameter:
    `request`: Das aktuelle Django-Request-Objekt.

    Rueckgabewert:
    Ein gerendertes HTML-Response-Objekt fuer die Inventory-Frontend-Seite.
    """
    return render(
        request,
        "operations/api_inventory.html",
        {
            "page_title": "Bestände ",
            "api_url": reverse("api_inventory"),
            "filter_label": "Standort",
            "filter_name": "location",
            "filter_placeholder": "z. B. Frankfurt",
        },
    )


def orders_frontend_view(request):
    """
    Zweck:
    Rendert eine eigenstaendige Frontend-Seite fuer die Auftrags-API,
    damit Produktionsauftraege ausserhalb des Dashboards betrachtet werden koennen.

    Parameter:
    `request`: Das aktuelle Django-Request-Objekt.

    Rueckgabewert:
    Ein gerendertes HTML-Response-Objekt fuer die Orders-Frontend-Seite.
    """
    return render(
        request,
        "operations/api_orders.html",
        {
            "page_title": "Aufträge ",
            "api_url": reverse("api_orders"),
            "filter_label": "Status",
            "filter_name": "status",
            "filter_placeholder": "z. B. planned",
        },
    )


def deliveries_frontend_view(request):
    """
    Zweck:
    Rendert eine eigenstaendige Frontend-Seite fuer die Liefer-API,
    damit Lieferdaten ausserhalb des Dashboards betrachtet werden koennen.

    Parameter:
    `request`: Das aktuelle Django-Request-Objekt.

    Rueckgabewert:
    Ein gerendertes HTML-Response-Objekt fuer die Deliveries-Frontend-Seite.
    """
    return render(
        request,
        "operations/api_deliveries.html",
        {
            "page_title": "Lieferungen",
            "api_url": reverse("api_deliveries"),
            "filter_label": "Status",
            "filter_name": "status",
            "filter_placeholder": "z. B. expected",
        },
    )


def dashboard_view(request):
    """
    Zweck:
    Rendert das Dashboard, verarbeitet Standortfilter, fuehrt Dateiimporte aus
    und beantwortet bei Bedarf LLM-Anfragen aus dem Dashboard-Formular.

    Parameter:
    `request`: Das aktuelle Django-Request-Objekt fuer GET- und POST-Zugriffe.

    Rueckgabewert:
    Ein gerendertes HTML-Response-Objekt fuer das Dashboard oder ein Redirect nach Uploads.
    """
    today = timezone.localdate()
    selected_location = request.GET.get("location", "").strip()
    llm_question = ""
    llm_answer = ""
    llm_error = ""
    llm_model = ""
    llm_provider = request.GET.get("llm_provider", "").strip() or get_default_llm_provider()

    if request.method == "POST":
        selected_location = request.POST.get("selected_location", "").strip()
        if request.POST.get("action") == "ask_llm":
            llm_question = request.POST.get("llm_question", "").strip()
            llm_provider = (
                request.POST.get("llm_provider", "").strip()
                or get_default_llm_provider()
            )
            try:
                llm_result = answer_supply_question(
                    llm_question,
                    location=selected_location or None,
                    provider=llm_provider,
                )
                llm_answer = llm_result["answer"]
                llm_model = llm_result["model"]
            except LLMIntegrationError as exc:
                llm_error = str(exc)
        else:
            return _handle_dashboard_upload(request, selected_location)

    available_locations = list(
        Inventory.objects.order_by("location")
        .values_list("location", flat=True)
        .distinct()
    )
    metrics = get_dashboard_metrics(location=selected_location or None)
    order_data = get_dashboard_order_data(location=selected_location or None)

    orders_page = _paginate_items(request, order_data["orders"], "orders_page")
    shortages_page = _paginate_items(
        request, order_data["shortage_summary"], "shortages_page"
    )
    deliveries_page = _paginate_items(
        request, get_upcoming_deliveries(next_days=7), "deliveries_page"
    )
    stock_alerts_page = _paginate_items(
        request, metrics["inventory_alerts"], "stock_alerts_page"
    )

    context = {
        "today": today,
        "available_locations": available_locations,
        "selected_location": selected_location,
        "total_products": metrics["total_products"],
        "total_inventory_records": metrics["total_inventory_records"],
        "below_safety_stock_count": metrics["below_safety_stock_count"],
        "below_reorder_point_count": metrics["below_reorder_point_count"],
        "open_orders_count": metrics["open_orders_count"],
        "delayed_deliveries_count": metrics["delayed_deliveries_count"],
        "stock_alerts": stock_alerts_page,
        "stock_alerts_page_query": _querystring_without(request, "stock_alerts_page"),
        "orders": orders_page,
        "orders_page_query": _querystring_without(request, "orders_page"),
        "critical_orders": order_data["critical_orders"],
        "shortage_summary": shortages_page,
        "shortages_page_query": _querystring_without(request, "shortages_page"),
        "upcoming_deliveries": deliveries_page,
        "deliveries_page_query": _querystring_without(request, "deliveries_page"),
        "llm_question": llm_question,
        "llm_answer": llm_answer,
        "llm_error": llm_error,
        "llm_model": llm_model,
        "llm_provider": llm_provider,
        "llm_providers": get_supported_llm_providers(),
    }

    return render(request, "operations/dashboard.html", context)
