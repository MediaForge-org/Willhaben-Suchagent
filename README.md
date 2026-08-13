# Willhaben-Suchagent

Willhaben-Suchagent wird ein lokal betriebener Live-Suchagent für öffentlich sichtbare
Inserate auf willhaben.at. Benutzer sollen mehrere Suchen verwalten können; ein gemeinsamer
Scheduler prüft alle aktivierten Suchen standardmäßig alle 60 Sekunden und meldet neue,
systemweit deduplizierte Treffer.

Der aktuelle Stand ist **Meilenstein M1 (Projektfundament)**. Es gibt bewusst noch keinen
echten Zugriff auf willhaben.at.

## Was M1 enthält

- ausschließlich lokal gebundene FastAPI-Anwendung (`127.0.0.1:8000`)
- zentrale, typisierte und per Umgebungsvariablen änderbare Konfiguration
- asynchrone SQLite-Persistenz mit Suchen, Inseraten, Zuordnungen und Notification-Ereignissen
- providerunabhängige `SearchDefinition`- und `Listing`-Modelle
- klare `ListingProvider`-Schnittstelle und deterministischer Fake-Provider
- genau einen globalen Scheduler für alle aktivierten Suchen
- konfigurierbare Parallelitätsgrenze für Provider-Abfragen (Standard: 2)
- transaktionale Baseline- und systemweite Deduplizierungslogik
- Notification-Abstraktion mit Fake-Implementation
- Health-, Status- und Search-CRUD-API
- explizite Provider-Fehlerklassen und kontrollierte Fehlerbehandlung
- strukturierte, gut lesbare Cycle-Logs
- automatisierte Tests ohne Netzwerkzugriff auf willhaben.at

## Voraussetzungen und Installation

Benötigt wird Python 3.12 oder neuer. Im Projektverzeichnis eine virtuelle Umgebung anlegen
und die Anwendung einschließlich Entwicklungswerkzeugen installieren:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Die Laufzeitabhängigkeiten sind FastAPI, Uvicorn, HTTPX, aiosqlite, Pydantic und
pydantic-settings. pytest, pytest-asyncio und Ruff werden nur für Entwicklung und Tests
benötigt. Alle Abhängigkeiten und Versionsbereiche stehen in `pyproject.toml`.

## Konfiguration

Standardwerte:

| Einstellung | Standard | Umgebungsvariable |
|---|---:|---|
| Cycle-Intervall | 60 Sekunden | `WILLHABEN_CYCLE_INTERVAL_SECONDS` |
| parallele Provider-Abfragen | 2 | `WILLHABEN_MAX_CONCURRENT_REQUESTS` |
| SQLite-Datei | `data/willhaben_suchagent.db` | `WILLHABEN_DATABASE_PATH` |
| API-Host | `127.0.0.1` | `WILLHABEN_API_HOST` |
| API-Port | `8000` | `WILLHABEN_API_PORT` |
| Umgebung | `development` | `WILLHABEN_APP_ENVIRONMENT` |
| Scheduler aktiv | `true` | `WILLHABEN_SCHEDULER_ENABLED` |

`.env.example` kann als Vorlage für eine lokale, nicht versionierte `.env` dienen. Die
lokale Bindung sollte nur bewusst geändert werden. Laufzeitdaten, Datenbanken, Secrets,
Logs und virtuelle Umgebungen werden durch `.gitignore` ausgeschlossen.

## Anwendung starten

```bash
source .venv/bin/activate
willhaben-suchagent
```

Alternativ:

```bash
python -m uvicorn agent.app.main:app --host 127.0.0.1 --port 8000
```

Die lokale API ist anschließend unter `http://127.0.0.1:8000` erreichbar. Beispiele:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/status
curl http://127.0.0.1:8000/api/v1/searches
```

FastAPIs lokale interaktive Dokumentation liegt unter `http://127.0.0.1:8000/docs`.

Eine Suche kann beispielsweise so erstellt werden:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/searches \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "BMW 340i",
    "category": "auto_motor",
    "query": "BMW 340i",
    "location": "Wien",
    "price_max": 50000,
    "category_filters": {"fuel": "petrol"}
  }'
```

Beim ersten erfolgreichen Lauf wird diese Suche initialisiert: vorhandene Treffer werden
gespeichert, lösen aber keine Notification aus. Erst global unbekannte Treffer eines späteren
erfolgreichen Cycles erzeugen ein Notification-Ereignis. Eine Filteränderung oder erneute
Aktivierung setzt die Baseline der betroffenen Suche kontrolliert zurück.

## Tests und Qualität

Die Tests greifen ausschließlich auf temporäre SQLite-Dateien und den Fake-Provider zu:

```bash
source .venv/bin/activate
pytest
ruff check .
ruff format --check .
```

## Architektur

- `agent/app/api`: lokale HTTP-Schnittstelle und API-Schemas
- `agent/app/core`: Konfiguration, Domain-Modelle, Provider-Vertrag, Scheduler und Health-State
- `agent/app/storage`: SQLite-Schema und Repository-/Transaktionslogik
- `agent/app/notifications`: providerunabhängiger Notification-Vertrag
- `agent/app/willhaben`: gekapselte Provider-Seite; in M1 nur Fake-Provider
- `agent/tests`: Integrations- und Unit-Tests des M1-Fundaments

`extension/` und `deployment/` werden erst angelegt, sobald ein Meilenstein dort echte Inhalte
benötigt. Der Scheduler kennt keine Willhaben-spezifischen Datenstrukturen und arbeitet nur
gegen die Provider-Schnittstelle.

## Bekannte Einschränkungen von M1

- kein echtes Scraping und keine HTTP-Anfragen an willhaben.at
- keine Willhaben-Parser oder kategoriespezifischen Such-Builder
- keine Firefox-Extension
- keine ntfy- oder sonstige echte Push-Zustellung
- kein automatisches Anschreiben und keine Nachrichten-Templates
- noch keine NAS-/Service-Paketierung in `deployment/`
- Notification-Ereignisse werden bereits persistent angelegt, aber nur an den Fake-Service
  übergeben

## Nächste Meilensteine

Spätere Meilensteine können den gekapselten Willhaben-Client, Search-Builder und Parser für
Marktplatz, Auto & Motor, Immobilien und Jobs ergänzen. Danach folgen echte Push-Zustellung,
Firefox-Oberfläche, erweitertes Health Monitoring und portable Deployment-Varianten. Dabei
bleiben die verbindlichen Grenzen bestehen: keine Accounts oder Benutzer-Cookies, keine
CAPTCHA-Umgehung, keine Proxy-/IP-Rotation und kontrolliertes Verhalten bei 429, 403 oder
Challenges.
