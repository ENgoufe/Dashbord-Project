"""
Dateirolle:
Diese Datei kapselt die Anbindung an verschiedene LLM-Provider fuer das Dashboard.
Sie waehlt den aktiven Anbieter, baut Prompts mit Dashboard-Kontext und
vereinheitlicht die Rueckgabe fuer OpenAI und lokale Ollama-Modelle.
"""
import os

import requests

from .services import build_llm_dashboard_context


class LLMIntegrationError(Exception):
    pass


OPENAI_PROVIDER = "openai"
OLLAMA_PROVIDER = "ollama"
SUPPORTED_PROVIDERS = (OPENAI_PROVIDER, OLLAMA_PROVIDER)

DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OLLAMA_MODEL = "llama3.1"
DEFAULT_OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 180


def get_default_llm_provider():
    """
    Zweck:
    Liest den konfigurierten Standard-LLM-Provider aus den Umgebungsvariablen
    und faellt bei ungueltigen Werten auf OpenAI zurueck.
    Parameter:
    Keine direkten Parameter. Die Funktion liest `LLM_PROVIDER` aus der Umgebung.
    Rueckgabewert:
    Ein String mit dem Provider-Namen, zum Beispiel `openai` oder `ollama`.
    """
    provider = os.getenv("LLM_PROVIDER", OPENAI_PROVIDER).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        return OPENAI_PROVIDER
    return provider


def get_supported_llm_providers():
    """
    Zweck:
    Liefert die vom Frontend nutzbaren LLM-Provider mit technischen Werten und Anzeigenamen.
    Parameter:
    Keine.
    Rueckgabewert:
    Eine Liste von Dictionaries mit den Schluesseln `value` und `label`.
    """
    return [
        {"value": OPENAI_PROVIDER, "label": "OpenAI"},
        {"value": OLLAMA_PROVIDER, "label": "Ollama (lokal)"},
    ]


def _extract_openai_response_text(payload):
    """
    Zweck:
    Extrahiert den eigentlichen Antworttext aus dem JSON-Payload der OpenAI-Responses-API.
    Parameter:
    `payload`: Dictionary mit der API-Antwort von OpenAI.
    Rueckgabewert:
    Ein String mit dem zusammengefuehrten Antworttext. Wenn kein Text vorhanden ist,
    wird ein leerer String zurueckgegeben.
    """
    output_text = payload.get("output_text")
    if output_text:
        return output_text.strip()

    text_chunks = []
    for item in payload.get("output", []):
        for content_item in item.get("content", []):
            if content_item.get("type") == "output_text" and content_item.get("text"):
                text_chunks.append(content_item["text"].strip())

    return "\n".join(chunk for chunk in text_chunks if chunk)


def _call_openai(question, context):
    """
    Zweck:
    Baut eine Anfrage fuer die OpenAI-Responses-API auf und liefert die Modellantwort zurueck.
    Parameter:
    `question`: Die vom Benutzer gestellte Fachfrage als String.
    `context`: Der vorbereitete Dashboard-Kontext mit Kennzahlen, Warnungen und Lieferdaten.
    Rueckgabewert:
    Ein Dictionary mit mindestens `answer` fuer den Antworttext und `model` fuer den Modellnamen.
    Bei Konfigurations- oder Netzwerkfehlern wird `LLMIntegrationError` ausgeloest.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise LLMIntegrationError(
            "OPENAI_API_KEY ist nicht gesetzt. Lege den API-Key als Umgebungsvariable an."
        )

    model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
    responses_url = os.getenv(
        "OPENAI_RESPONSES_URL", DEFAULT_OPENAI_RESPONSES_URL
    ).strip()
    instructions = (
        "Du bist ein Assistent fuer Supply-Operations. "
        "Antworte kurz, fachlich und nur auf Basis des bereitgestellten Kontexts. "
        "Wenn Informationen fehlen, sage das klar."
    )
    prompt = f"Frage des Nutzers:\n{question}\n\nKontextdaten:\n{context}"

    try:
        response = requests.post(
            responses_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "instructions": instructions,
                "input": prompt,
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LLMIntegrationError(f"Fehler beim LLM-Aufruf: {exc}") from exc

    answer = _extract_openai_response_text(response.json())
    if not answer:
        raise LLMIntegrationError("Das LLM hat keine auswertbare Antwort geliefert.")

    return {"answer": answer, "model": model}


def _call_ollama(question, context):
    """
    Zweck:
    Baut eine Anfrage fuer eine lokale Ollama-Instanz auf und gibt die Antwort strukturiert zurueck.
    Parameter:
    `question`: Die vom Benutzer gestellte Fachfrage.
    `context`: Der vorbereitete fachliche Kontext aus den Dashboard-Daten.
    Rueckgabewert:
    Ein Dictionary mit `answer` und `model`.
    Bei Netzwerk- oder Antwortfehlern wird `LLMIntegrationError` ausgeloest.
    """
    model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip()
    generate_url = os.getenv(
        "OLLAMA_URL", DEFAULT_OLLAMA_GENERATE_URL
    ).strip()
    timeout_seconds = int(
        os.getenv("OLLAMA_TIMEOUT_SECONDS", str(DEFAULT_OLLAMA_TIMEOUT_SECONDS)).strip()
    )
    prompt = (
        "Du bist ein Assistent fuer Supply-Operations. "
        "Antworte kurz, fachlich und nur auf Basis des bereitgestellten Kontexts. "
        "Wenn Informationen fehlen, sage das klar.\n\n"
        f"Frage des Nutzers:\n{question}\n\n"
        f"Kontextdaten:\n{context}"
    )

    try:
        response = requests.post(
            generate_url,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise LLMIntegrationError(
            f"Fehler beim LLM-Aufruf: {exc}. "
            "Falls das lokale Modell langsam antwortet, erhoehe OLLAMA_TIMEOUT_SECONDS."
        ) from exc

    payload = response.json()
    answer = str(payload.get("response", "")).strip()
    if not answer:
        raise LLMIntegrationError("Das lokale LLM hat keine auswertbare Antwort geliefert.")

    return {"answer": answer, "model": model}


def answer_supply_question(question, location=None, provider=None):
    """
    Zweck:
    Validiert die Benutzerfrage, baut den Dashboard-Kontext auf und delegiert den Aufruf
    an den gewaehlten LLM-Provider.
    Parameter:
    `question`: Die Benutzerfrage als String.
    `location`: Optionaler Standortfilter fuer den Datenkontext.
    `provider`: Optionaler Providername. Wenn leer, wird der Standard-Provider verwendet.
    Rueckgabewert:
    Ein Dictionary mit Antworttext, Modellname, Provider und verwendetem Kontext.
    Bei ungueltigen Eingaben oder Integrationsfehlern wird `LLMIntegrationError` ausgeloest.
    """
    question = question.strip()
    if not question:
        raise LLMIntegrationError("Bitte eine Frage eingeben.")

    provider = (provider or get_default_llm_provider()).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise LLMIntegrationError(f"Nicht unterstuetzter LLM-Provider: {provider}")

    context = build_llm_dashboard_context(location=location)

    if provider == OPENAI_PROVIDER:
        result = _call_openai(question, context)
    else:
        result = _call_ollama(question, context)

    result["provider"] = provider
    result["context"] = context
    return result
