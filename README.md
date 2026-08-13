# Willhaben-Suchagent

Willhaben-Suchagent ist ein lokal betriebener Live-Suchagent für öffentlich sichtbare
Marktplatz-Inserate auf willhaben.at. Mehrere aktivierte Suchen teilen sich genau einen
globalen Scheduler. Er startet standardmäßig alle 60 Sekunden einen Cycle, begrenzt die
Provider-Abfragen zentral und sendet global deduplizierte neue Treffer per ntfy aufs Handy.

Der aktuelle Stand ist **Meilenstein M3 (End-to-End Live-Monitoring + ntfy)**. Es werden
weder Willhaben-Login noch Accounts, Benutzer-Cookies, CAPTCHA-Umgehung, Proxy-/IP-Rotation
oder aggressive Retries verwendet. Auto & Motor, Immobilien, Jobs, automatische Nachrichten
und die Firefox-Extension gehören ausdrücklich nicht zu M3.

## Funktionsumfang

- FastAPI-Anwendung mit SQLite-Persistenz und automatischem Lifespan-Start
- ein globaler Scheduler für alle aktiven Suchen, standardmäßig alle 60 Sekunden
- Takt vom Start des vorherigen Cycles, nicht von dessen Ende
- kontrollierte Provider-Parallelität, standardmäßig höchstens zwei Requests
- echter `WillhabenMarketplaceProvider` für öffentliche Marktplatz-Suchergebnisse
- Baseline beim ersten erfolgreichen Lauf ohne Benachrichtigungen
- globale Listing-Deduplizierung und Search-Matches für alle passenden Suchen
- persistente Notifications mit den Zuständen `pending`, `sent` und `failed`
- ein Zustellversuch pro ausstehender Notification und Cycle, auch nach Neustarts
- echter `NtfyNotificationService` mit Titel, Preis, Standort und Click-Link zum Inserat
- Test-Push, Recent-Listings-API sowie erweiterter Health-/Status-Endpunkt
- vollständig offline laufende Tests mit Fake-Providern und HTTP-Mocks

## Voraussetzungen und Installation

Benötigt wird Python 3.12 oder neuer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
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
| ntfy aktiv | `false` | `NTFY_ENABLED` |
| ntfy-Basis-URL | `https://ntfy.sh` | `NTFY_BASE_URL` |
| ntfy-Topic | nicht gesetzt | `NTFY_TOPIC` |
| optionaler ntfy-Token | nicht gesetzt | `NTFY_TOKEN` |
| ntfy-Timeout | 10 Sekunden | `NTFY_TIMEOUT` |
| Provider-User-Agent | siehe `.env.example` | `WILLHABEN_MARKETPLACE_USER_AGENT` |
| Connect-Timeout | 10 Sekunden | `WILLHABEN_MARKETPLACE_CONNECT_TIMEOUT_SECONDS` |
| Read-Timeout | 20 Sekunden | `WILLHABEN_MARKETPLACE_READ_TIMEOUT_SECONDS` |
| maximale Redirects | 3 | `WILLHABEN_MARKETPLACE_MAX_REDIRECTS` |
| maximale Antwortgröße | 5.000.000 Bytes | `WILLHABEN_MARKETPLACE_MAX_RESPONSE_BYTES` |

Ohne `NTFY_ENABLED=true` und ein nicht leeres `NTFY_TOPIC` startet die Anwendung normal,
weist ntfy aber nachvollziehbar als deaktiviert aus. Tokens werden nur aus Konfiguration
beziehungsweise Environment gelesen und weder im Status noch in Logs ausgegeben. Für das
öffentliche `ntfy.sh` empfiehlt sich ein langer, schwer zu erratender Topic-Name. Ein Token
ist nur nötig, wenn der gewählte Server beziehungsweise das Topic Authentifizierung verlangt.

## Datenfluss und Zustellmodell

```text
SearchDefinition
  -> globaler Scheduler
  -> WillhabenMarketplaceProvider
  -> Listing[]
  -> Baseline + globale Deduplizierung + Search-Matches
  -> persistente Notification (pending)
  -> NtfyNotificationService
  -> sent oder failed
```

Beim ersten erfolgreichen Lauf einer Suche werden die aktuellen Listings und Matches als
Baseline gespeichert, ohne Push. Ab dem folgenden erfolgreichen Lauf erzeugt nur ein global
unbekanntes Listing eine Notification. Passt dasselbe Listing gleichzeitig zu mehreren
Suchen, werden alle Matches gespeichert, aber nur eine Notification angelegt.

Eine neue Notification beginnt als `pending`. Nach erfolgreicher ntfy-Antwort wird sie
`sent`; bei Timeout, Netzwerk- oder HTTP-Fehler wird sie `failed`, der Fehler und die
Versuchsanzahl werden gespeichert. `pending` und `failed` werden in einem späteren globalen
Cycle erneut versucht, ohne schnelle Retry-Schleife. Ein Neustart verliert sie nicht.
Bereits als `sent` gespeicherte Notifications werden nicht erneut ausgewählt.

Deaktivieren und späteres Reaktivieren behält eine bereits initialisierte Baseline und alle
bekannten Listings bei. Dadurch werden nach der Reaktivierung nur wirklich global unbekannte
Listings gemeldet. Eine Änderung der eigentlichen Filter setzt die Baseline der Suche zurück;
eine reine Umbenennung oder Aktivierung/Deaktivierung tut das nicht.

## Search API

Eine echte Marketplace-Suche kann direkt aktiviert angelegt werden:

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
    "category_filters": {"marketplace_category": "computer-software-5824"},
    "enabled": true
  }'
```

Aktivieren und deaktivieren erfolgt ohne neuen Timer über den bestehenden PATCH-Endpunkt:

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/searches/1 \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false}'

curl -X PATCH http://127.0.0.1:8000/api/v1/searches/1 \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true}'
```

Zuletzt gefundene Listings, optional gefiltert nach Search-ID und immer neueste zuerst:

```bash
curl 'http://127.0.0.1:8000/api/v1/listings/recent?limit=20'
curl 'http://127.0.0.1:8000/api/v1/listings/recent?limit=20&search_id=1'
```

## Unterstützte Marktplatz-Filter

| `SearchDefinition`-Feld | Öffentlicher Willhaben-Parameter |
|---|---|
| `query` | `keyword` |
| `price_min` | `PRICE_FROM` |
| `price_max` | `PRICE_TO` |
| `location` | `areaId` |
| `category_filters.marketplace_category` | öffentlicher SEO-Kategoriepfad |

`location` unterstützt die österreichischen Bundesländer und Wien sowie deren bestätigte
numerische `areaId`. Freie Umkreis-, Bezirks- oder Ortsnamensuchen werden nicht geraten.

Als `marketplace_category` werden aktuell die anhand der öffentlichen Antwortstruktur
bestätigten Kategorien akzeptiert: Bücher / Filme / Musik, Computer / Software,
Dienstleistungen, Freizeit / Instrumente / Kulinarik, KFZ-Zubehör / Motorradteile, Mode /
Accessoires, Smartphones / Telefonie und Wohnen / Haushalt / Gastronomie. Akzeptiert werden
Name, numerische Kategorie-ID oder SEO-Segment wie `computer-software-5824`. Unbekannte
Filter führen kontrolliert zu einem Providerfehler, statt still breiter zu suchen.

Jede Anfrage setzt `sort=1`, in der öffentlichen Antwort als `published.descending` /
„Aktualität“ bezeichnet. Es wird höchstens die erste öffentliche Ergebnisseite verarbeitet;
M3 implementiert kein aggressives Paging oder Crawling.

## Konkreter lokaler End-to-End-Test

Diese Schritte sind für einen echten Test außerhalb einer eventuell netzwerkbeschränkten
Entwicklungs-Sandbox gedacht.

1. `.env` aus der Vorlage erstellen und mindestens diese Werte eintragen:

   ```dotenv
   NTFY_ENABLED=true
   NTFY_BASE_URL=https://ntfy.sh
   NTFY_TOPIC=ein-langer-eindeutiger-privater-topic-name
   NTFY_TOKEN=
   NTFY_TIMEOUT=10
   WILLHABEN_CYCLE_INTERVAL_SECONDS=60
   WILLHABEN_MAX_CONCURRENT_REQUESTS=2
   ```

2. In der ntfy-App auf dem Handy denselben Topic-Namen abonnieren.

3. Anwendung starten:

   ```bash
   source .venv/bin/activate
   willhaben-suchagent
   ```

4. In einem zweiten Terminal den klar getrennten Test-Push senden. Dieser erzeugt kein
   Fake-Listing und keine Listing-Notification in SQLite:

   ```bash
   curl -X POST http://127.0.0.1:8000/api/v1/notifications/test
   ```

   Erwartete Nachricht: `Willhaben-Suchagent – Test erfolgreich`.

5. Eine echte Marketplace-Suche mit dem oben gezeigten `POST /api/v1/searches` anlegen.
   Die Antwort enthält die Search-ID und `baseline_initialized: false`.

6. Den unmittelbar gestarteten beziehungsweise nächsten globalen Cycle im Log beobachten.
   `baseline_initialized` wird nach dem ersten erfolgreichen Abruf `true`; vorhandene
   Inserate lösen dabei absichtlich keinen Push aus:

   ```bash
   curl http://127.0.0.1:8000/api/v1/searches/1
   ```

7. Die Suche aktiviert lassen. Der Scheduler startet Folge-Cycles jeweils 60 Sekunden nach
   dem vorherigen Cycle-Start. Ein danach erstmals sichtbares Inserat erzeugt einen ntfy-Push;
   Antippen öffnet dessen echte Willhaben-URL.

8. Live-Status und gefundene Listings prüfen:

   ```bash
   curl http://127.0.0.1:8000/health
   curl http://127.0.0.1:8000/api/v1/status
   curl 'http://127.0.0.1:8000/api/v1/listings/recent?limit=20&search_id=1'
   ```

9. Den Agenten im ersten Terminal mit `Ctrl-C` kontrolliert stoppen. FastAPI beendet den
   Scheduler, bricht dessen offene Task ab und schließt den ntfy-HTTP-Client. SQLite verwendet
   pro Operation kontrolliert geschlossene Verbindungen.

## Einzelne öffentliche Suche diagnostisch testen

Der bestehende Development-Befehl führt genau einen öffentlichen Request aus und zeigt die
ersten Treffer. Er ist nicht für das dauerhafte Monitoring nötig:

```bash
source .venv/bin/activate
willhaben-marketplace-search 'ThinkPad' \
  --price-from 100 \
  --price-to 1200 \
  --location Wien \
  --category computer-software-5824 \
  --limit 5
```

## Fehler- und Schutzverhalten

- HTTP 429 wird `RateLimitedError`, HTTP 403 wird `AccessDeniedError`.
- Erkannte CAPTCHA-/Challenge-Seiten werden `ChallengeDetectedError`.
- Netzwerkfehler werden `NetworkError`, Timeouts `RequestTimeoutError`.
- Einzelne Search-Fehler werden gespeichert und verhindern andere Suchen desselben Cycles
  möglichst nicht.
- Es gibt keine unmittelbare Provider-Retry-Schleife, keinen Neustart-Loop, keine Header-,
  Proxy- oder IP-Rotation und keinen Versuch, Schutzmechanismen zu umgehen.
- ntfy-Ausfälle erzeugen keinen Prozesscrash; Zustellungen bleiben persistent wiederholbar.
- Logs enthalten Cycle-/Search-/Listing-/Notification-Ergebnisse und Dauer, aber keine
  Cookies, Tokens oder vollständigen Environment-Werte.

## Tests und Qualität

Alle automatisierten Tests nutzen Mock-Transporte, temporäre SQLite-Datenbanken und lokale
Fixtures. Sie greifen nicht auf willhaben.at oder ntfy.sh zu:

```bash
source .venv/bin/activate
pytest
ruff check .
ruff format --check .
git diff --check
pytest
```

## Architektur und bekannte Grenzen

- `agent/app/api`: lokale CRUD-, Listings-, Notification- und Status-API
- `agent/app/core`: Konfiguration, Domain-Modelle, Scheduler und Health-State
- `agent/app/storage`: SQLite-Schema, Migration und transaktionale Deduplizierung
- `agent/app/notifications`: providerunabhängiger Vertrag und ntfy-Transport
- `agent/app/willhaben`: Search Builder, HTTP-Transport, Parser und echter Provider

Der Scheduler kennt keine Willhaben-spezifischen HTML-/JSON-Strukturen. Öffentliche
Seitenstrukturen können sich ändern; Abweichungen enden kontrolliert mit `ParseError`. ntfy
und Willhaben müssen für den echten Alltagstest vom lokalen Rechner erreichbar sein.

Die M3-API ist zunächst für Entwickler bedienbar. Eine spätere Firefox-Extension kann über
dieselben Search-, Status- und Recent-Listings-Endpunkte Suchen verwalten, ohne die Scheduler-
oder Persistenzarchitektur umzubauen. Ein normaler Endbenutzer soll langfristig keine
Terminalbefehle benötigen. **M4 ist nicht Bestandteil dieses Stands.**
