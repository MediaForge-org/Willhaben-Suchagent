# Willhaben-Suchagent

Willhaben-Suchagent ist ein lokal betriebener Live-Suchagent für öffentlich sichtbare
Inserate auf willhaben.at. Mehrere Suchen teilen sich einen globalen Scheduler, der alle
aktivierten Suchen standardmäßig alle 60 Sekunden prüft und neue Treffer systemweit
dedupliziert.

Der aktuelle Stand ist **Meilenstein M2 (echter Marktplatz-Provider)**. Der Provider ruft
ausschließlich öffentliche Willhaben-Marktplatz-Suchergebnisse ohne Anmeldung ab. Auto &
Motor, Immobilien und Jobs sind nicht Teil von M2.

## Was M2 enthält

- echter `WillhabenMarketplaceProvider` hinter der providerunabhängigen
  `ListingProvider`-Schnittstelle
- zentraler, deterministischer Search Builder für öffentliche Marktplatz-Seiten
- gekapselter HTTPX-Transport mit Timeouts, höchstens drei Redirects, konfigurierbarem
  User-Agent und einer Begrenzung der dekomprimierten Antwortgröße
- kein automatisches Retry-Verhalten
- Parser für die strukturierten `__NEXT_DATA__`-State-Daten der öffentlichen Webseite
- Mapping in das bestehende providerunabhängige `Listing`-Modell
- kontrollierte Klassifikation von HTTP-, Netzwerk-, Timeout-, Parser- und Challenge-Fehlern
- reale, auf die benötigte Struktur reduzierte und bereinigte Offline-Fixtures
- manueller CLI-Test für genau eine öffentliche Marktplatz-Suche
- unveränderte Baseline-, Deduplizierungs- und 60-Sekunden-Scheduler-Architektur aus M1

Der Provider extrahiert stabile Willhaben-Inserat-IDs, Titel, normalisierte Preise,
öffentliche Detail-URLs, das erste Inseratbild, Standort, die Hauptkategorie `marketplace`
und ausgewählte öffentliche Attribute wie Veröffentlichungszeit, Bundesland, Bezirk,
Postleitzahl, PayLivery-/Privatstatus sowie Marktplatz-Kategorie-IDs. Fehlt ein optionales
Feld, bleibt das restliche Inserat gültig. Einzelne defekte Inserate verwerfen nicht
automatisch die übrigen Treffer.

## Unterstützte Marktplatz-Filter

| `SearchDefinition`-Feld | Öffentlicher Willhaben-Parameter |
|---|---|
| `query` | `keyword` |
| `price_min` | `PRICE_FROM` |
| `price_max` | `PRICE_TO` |
| `location` | `areaId` |
| `category_filters.marketplace_category` | öffentlicher SEO-Kategoriepfad |

`location` unterstützt die acht österreichischen Flächenbundesländer und Wien sowie deren
bestätigte numerische `areaId`. Freie Umkreis-, Bezirks- oder Ortsnamensuchen werden
in M2 nicht geraten oder stillschweigend erweitert.

Als `marketplace_category` werden aktuell die im realen Fixture bestätigten Kategorien
akzeptiert: Bücher / Filme / Musik, Computer / Software, Dienstleistungen, Freizeit /
Instrumente / Kulinarik, KFZ-Zubehör / Motorradteile, Mode / Accessoires, Smartphones /
Telefonie und Wohnen / Haushalt / Gastronomie. Akzeptiert werden der Name, die numerische
Kategorie-ID oder ein vollständiges SEO-Segment wie `computer-software-5824`. Unbekannte
Filter lösen kontrolliert `ProviderInternalError` aus, statt eine breitere Suche auszuführen.

Jede Anfrage setzt explizit `sort=1`. Die reale öffentliche Antwort bezeichnet diese
Sortierung als `published.descending` beziehungsweise „Aktualität“. Damit werden die
aktuellsten Inserate zuerst angefordert; Relevanzranking (`sort=7`) wird nicht verwendet.

## Voraussetzungen und Installation

Benötigt wird Python 3.12 oder neuer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

## Konfiguration

| Einstellung | Standard | Umgebungsvariable |
|---|---:|---|
| Cycle-Intervall | 60 Sekunden | `WILLHABEN_CYCLE_INTERVAL_SECONDS` |
| parallele Provider-Abfragen | 2 | `WILLHABEN_MAX_CONCURRENT_REQUESTS` |
| SQLite-Datei | `data/willhaben_suchagent.db` | `WILLHABEN_DATABASE_PATH` |
| API-Host | `127.0.0.1` | `WILLHABEN_API_HOST` |
| API-Port | `8000` | `WILLHABEN_API_PORT` |
| Umgebung | `development` | `WILLHABEN_APP_ENVIRONMENT` |
| Scheduler aktiv | `true` | `WILLHABEN_SCHEDULER_ENABLED` |
| Provider-User-Agent | siehe `.env.example` | `WILLHABEN_MARKETPLACE_USER_AGENT` |
| Connect-Timeout | 10 Sekunden | `WILLHABEN_MARKETPLACE_CONNECT_TIMEOUT_SECONDS` |
| Read-Timeout | 20 Sekunden | `WILLHABEN_MARKETPLACE_READ_TIMEOUT_SECONDS` |
| maximale Redirects | 3 | `WILLHABEN_MARKETPLACE_MAX_REDIRECTS` |
| maximale Antwortgröße | 5.000.000 Bytes | `WILLHABEN_MARKETPLACE_MAX_RESPONSE_BYTES` |

`.env.example` dient als Vorlage. Laufzeitdaten, Datenbanken, Secrets, Logs und virtuelle
Umgebungen sind durch `.gitignore` ausgeschlossen.

## Anwendung und SearchDefinition

```bash
source .venv/bin/activate
willhaben-suchagent
```

Alternativ:

```bash
python -m uvicorn agent.app.main:app --host 127.0.0.1 --port 8000
```

Eine Marktplatz-Suche lässt sich über die lokale API anlegen:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/searches \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "ThinkPad in Wien",
    "category": "marketplace",
    "query": "ThinkPad",
    "location": "Wien",
    "price_min": 100,
    "price_max": 1200,
    "category_filters": {"marketplace_category": "computer-software-5824"}
  }'
```

Beim ersten erfolgreichen Lauf wird die Baseline initialisiert: bereits vorhandene Treffer
werden gespeichert, lösen aber keine Notification aus. Erst global unbekannte Treffer eines
späteren erfolgreichen Cycles erzeugen ein Notification-Ereignis. Filteränderungen und eine
erneute Aktivierung setzen die Baseline der betroffenen Suche zurück.

## Einzelne Suche manuell testen

Der Development-Befehl führt genau einen öffentlichen Request aus und zeigt Trefferzahl,
die ersten IDs, Titel, Preise und Detail-URLs:

```bash
source .venv/bin/activate
willhaben-marketplace-search 'ThinkPad' \
  --price-from 100 \
  --price-to 1200 \
  --location Wien \
  --category computer-software-5824 \
  --limit 5
```

Ohne erneute Installation kann derselbe Test so gestartet werden:

```bash
python -m agent.app.willhaben.cli 'ThinkPad' --location Wien --limit 5
```

Der manuelle Test ist absichtlich kein Crawl und enthält keine Retry- oder Parallel-Schleife.

## Fehler- und Schutzverhalten

- Netzwerkfehler werden `NetworkError`, Timeouts `RequestTimeoutError`.
- HTTP 429 wird unmittelbar `RateLimitedError`.
- HTTP 403 wird unmittelbar `AccessDeniedError`.
- erkannte CAPTCHA-, Bot- oder Challenge-Seiten werden `ChallengeDetectedError`.
- unerwartete oder nicht parsebare Seiten werden `ParseError`.
- andere HTTP- und Providerfehler werden `ProviderInternalError`.

Bei 403, 429 oder Challenges wird kontrolliert abgebrochen. Es gibt keine Header-Rotation,
Proxy-/IP-Rotation, CAPTCHA-Umgehung oder andere Mechanismen zur Umgehung von Sperren. Der
Provider verwendet keinen Willhaben-Account, kein Login, keine Benutzer-Cookies und keine
authentifizierte Session. Geloggt werden Request-Beginn, Search-ID, HTTP-Status, Trefferzahl
und Fehlerklasse, jedoch weder komplette Seiten noch Cookies oder Secrets.

## Tests und Qualität

Alle automatisierten Tests arbeiten mit Mock-Transporten, temporären SQLite-Datenbanken und
bereinigten Fixtures. Sie greifen niemals live auf willhaben.at zu:

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
- `agent/app/willhaben/marketplace_search.py`: zentraler Marktplatz-Search-Builder
- `agent/app/willhaben/http_client.py`: begrenzter öffentlicher HTTPX-Transport
- `agent/app/willhaben/marketplace_parser.py`: State-Parser und Listing-Mapping
- `agent/app/willhaben/marketplace_provider.py`: Provider-Orchestrierung und Fehlerklassifikation
- `agent/tests/fixtures/willhaben`: bereinigte reale Antwortstruktur für Offline-Tests

Der Scheduler kennt weiterhin keine Willhaben-spezifischen URLs, HTML- oder JSON-Strukturen.
Sein Ablauf bleibt `SearchDefinition → ListingProvider → Listing → Baseline/Deduplizierung`.

## Bekannte Einschränkungen und M3

- Öffentliche Seitenstrukturen können sich ändern; strukturelle Abweichungen brechen
  kontrolliert mit `ParseError` ab.
- M2 unterstützt nur nachweisbar abgebildete Bundesländer und Marktplatz-Kategorien.
- Die maximal erste öffentliche Ergebnisseite mit standardmäßig 30 Treffern wird verarbeitet;
  es gibt kein aggressives Paging oder Crawling.
- Bei Netzwerksperren, 403, 429 und Challenges wird nicht versucht, die Sperre zu umgehen.
- Firefox-Extension, ntfy, Nachrichten-Templates, automatisches Anschreiben, Account/Login,
  Auto & Motor, Immobilien und Jobs sind nicht implementiert.

M3 wurde ausdrücklich nicht begonnen. Ein späterer Meilenstein muss die jeweils vorgesehenen
weiteren Funktionen separat ergänzen, ohne Willhaben-spezifische Logik in den Scheduler zu
verschieben.
