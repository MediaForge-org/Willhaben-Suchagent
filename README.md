# Willhaben-Suchagent

Willhaben-Suchagent ist ein lokal betriebener Live-Suchagent für öffentlich sichtbare
Marktplatz-Inserate auf willhaben.at. Mehrere aktivierte Suchen teilen sich genau einen
globalen Scheduler. Er startet standardmäßig alle 60 Sekunden einen Cycle, begrenzt die
Provider-Abfragen zentral und sendet global deduplizierte neue Treffer per ntfy aufs Handy.

Der aktuelle Stand ist **Meilenstein M3.1 (Listing-Enrichment + informative ntfy-Pushes)**.
Es werden weder Willhaben-Login noch Accounts, Benutzer-Cookies, CAPTCHA-Umgehung,
Proxy-/IP-Rotation oder aggressive Retries verwendet. Auto & Motor, Immobilien, Jobs,
automatische Nachrichten und die Firefox-Extension gehören ausdrücklich nicht zu M3.1.

## Funktionsumfang

- FastAPI-Anwendung mit SQLite-Persistenz und automatischem Lifespan-Start
- ein globaler Scheduler für alle aktiven Suchen, standardmäßig alle 60 Sekunden
- Takt vom Start des vorherigen Cycles, nicht von dessen Ende
- kontrollierte Provider-Parallelität, standardmäßig höchstens zwei Requests
- echter `WillhabenMarketplaceProvider` für öffentliche Marktplatz-Suchergebnisse
- Baseline beim ersten erfolgreichen Lauf ohne Benachrichtigungen
- globale Listing-Deduplizierung und Search-Matches für alle passenden Suchen
- genau ein öffentlicher Detailseitenabruf für jedes danach wirklich neue Marketplace-Listing
- Detail-Enrichment mit Anbietername/-art, Zustand, genauerem öffentlichen Standort,
  Hauptbild, Titel, Preis, Kategorie, öffentlichen Artikelattributen und Zeitangaben, soweit
  diese auf der Seite vorhanden sind
- persistente Enrichment-Zustände `not_requested`, `enriched`, `partial` und `failed`
- persistente Notifications mit den Zuständen `pending`, `sent` und `failed`
- ein Zustellversuch pro ausstehender Notification und Cycle, auch nach Neustarts
- echter `NtfyNotificationService` mit Titel, Preis, Anbieter, Ort, Zustand und Click-Link
  zum echten Inserat; nicht vorhandene Zeilen entfallen vollständig
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
  -> Detailseite ausschließlich bei enrichment_status=not_requested
  -> angereichertes Listing (enriched/partial/failed)
  -> NtfyNotificationService
  -> sent oder failed
```

Beim ersten erfolgreichen Lauf einer Suche werden die aktuellen Listings und Matches als
Baseline gespeichert, ohne Push und ohne Detailseitenabrufe. Ab dem folgenden erfolgreichen
Lauf erzeugt nur ein global unbekanntes Listing eine Notification. Erst diese persistente
Notification macht das Listing zum einmaligen Enrichment-Kandidaten. Passt dasselbe Listing
gleichzeitig zu mehreren Suchen, werden alle Matches gespeichert, aber nur eine Notification
und ein Detailrequest angelegt. Bekannte, bereits angereicherte oder fehlgeschlagen
angereicherte Listings werden in späteren 60-Sekunden-Cycles nicht erneut geladen.

Ein erfolgreicher Detailabruf wird `enriched`, wenn alle häufig verwendeten Detailfelder
vorhanden sind, andernfalls `partial`. Ein Timeout, Parsefehler, HTTP 403/429 oder eine
Challenge wird `failed`. Das Listing bleibt dabei ein neuer Treffer und erhält trotzdem den
Basis-Push. Es gibt keinen unmittelbaren Detail-Retry. Die öffentliche Beschreibung wird
bewusst nicht persistiert; Logs enthalten nur die Listing-ID und den Ergebnis-/Fehlertyp,
nicht Anbietername, Standort oder Beschreibung.

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

Jeder Eintrag enthält neben den bisherigen Feldern `seller_name`, `seller_type`, `condition`,
`location`, `image_url` und `enrichment_status`. Fehlende öffentliche Werte werden als
`null` geliefert; es werden keine Ersatznamen oder abgeleiteten Privatadressen erfunden.

## Push-Format

Ein vollständig angereichertes gewerbliches Inserat erscheint beispielsweise so:

```text
Neues Willhaben-Inserat

Lenovo ThinkPad T14 G3
465 €
Anbieter: Beispiel Technik GmbH
Ort: Wien, 22. Bezirk, Donaustadt
Zustand: Sehr gut
```

Bei einem eindeutig privaten Profil lautet die Zeile `Verkäufer: Max M.`. Jede optionale
Zeile wird nur bei vorhandenem Wert erzeugt; Darstellungen wie `null`, `None` oder
`unbekannt` gibt es nicht. Der vorhandene ntfy-`Click`-Link zeigt weiterhin direkt auf die
echte öffentliche Willhaben-Detailseite.

Ein zusätzlicher ntfy-Action-Button und ein Bild-Attachment werden in M3.1 bewusst nicht
gesendet. Der Click-Link ist für den zentralen iOS-Ablauf ausreichend und robuster; ein
extern geladenes Attachment würde die Push-Zustellung und iOS-Darstellung unnötig von der
Bild-URL abhängig machen. Ein noch funktionsloser „Anschreiben“-Button wird nicht simuliert.

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
M3.1 implementiert kein aggressives Paging oder Crawling.

## Konkreter lokaler End-to-End-Test für M3.1

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

4. Den Test-Push aus M3 muss nicht wiederholt werden. Die vorhandene Suche weiterverwenden.
   Falls noch keine Suche existiert, einmalig mit dem oben gezeigten
   `POST /api/v1/searches` anlegen.

5. Den unmittelbar gestarteten beziehungsweise nächsten globalen Cycle im Log beobachten.
   `baseline_initialized` wird nach dem ersten erfolgreichen Abruf `true`; vorhandene
   Inserate lösen dabei absichtlich weder Push noch Detailrequests aus:

   ```bash
   curl http://127.0.0.1:8000/api/v1/searches/1
   ```

6. Die Suche aktiviert lassen. Der Scheduler startet Folge-Cycles jeweils 60 Sekunden nach
   dem vorherigen Cycle-Start. Ein danach erstmals sichtbares Inserat erzeugt genau einen
   Detailrequest und danach einen ntfy-Push. Im Log erscheinen
   `listing_enrichment_started` und anschließend `listing_enrichment_completed`,
   `listing_enrichment_partial` oder `listing_enrichment_failed`. Antippen öffnet die echte
   Willhaben-URL.

7. Ohne auf ein echtes neues Inserat zu warten, lässt sich derselbe New-Listing-Ablauf
   kontrolliert und vollständig offline mit Fake-Provider, temporärer SQLite-Datenbank,
   anonymisiertem Detail-Fixture und ntfy-Mock simulieren. Die lokale M3-Datenbank und das
   echte Topic bleiben dabei unberührt:

   ```bash
   pytest -q agent/tests/test_scheduler.py -k 'one_new_listing or detail_failure'
   pytest -q agent/tests/test_notifications.py -k 'listing_payload or omits_all'
   ```

8. Recent Listings prüfen; für das neue Listing insbesondere die sechs Enrichment-Felder
   kontrollieren:

   ```bash
   curl http://127.0.0.1:8000/health
   curl http://127.0.0.1:8000/api/v1/status
   curl 'http://127.0.0.1:8000/api/v1/listings/recent?limit=20&search_id=1'
   ```

9. Auf dem iPhone Titel, Preis und – soweit öffentlich vorhanden – Anbieter, Ort und Zustand
   prüfen. Die Benachrichtigung antippen und sicherstellen, dass das konkrete Inserat geöffnet
   wird. Bei `failed` ist ein reduzierter Basis-Push korrekt.

10. Den Agenten im ersten Terminal mit `Ctrl-C` kontrolliert stoppen. FastAPI beendet den
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
- Detailfehler verhindern weder Persistenz noch Push; Detailabrufe selbst werden nicht
  aggressiv wiederholt.
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
- `agent/app/core`: Konfiguration, Domain-/Enrichment-Modelle, Scheduler und Health-State
- `agent/app/storage`: SQLite-Schema, Migration und transaktionale Deduplizierung
- `agent/app/notifications`: providerunabhängiger Vertrag und ntfy-Transport
- `agent/app/willhaben`: Search Builder, gemeinsamer HTTP-Transport, getrennte Such- und
  Detailparser, Detailclient, Listing-Enricher und echter Provider

Der Scheduler kennt keine Willhaben-spezifischen HTML-/JSON-Strukturen. Öffentliche
Seitenstrukturen können sich ändern; Abweichungen enden kontrolliert mit `ParseError`. ntfy
und Willhaben müssen für den echten Alltagstest vom lokalen Rechner erreichbar sein.

Beim Start erweitert eine additive SQLite-Migration bestehende M3-Listings um die vier neuen
Spalten `seller_name`, `seller_type`, `condition` und `enrichment_status`. Bestehende
Listings, Baselines, Matches und Notifications bleiben erhalten; Altbestände beginnen mit
`not_requested`, lösen aber ohne neue Notification keinen nachträglichen Detailabruf aus.

Die M3.1-API ist zunächst für Entwickler bedienbar. Eine spätere Firefox-Extension kann über
dieselben Search-, Status- und Recent-Listings-Endpunkte Suchen verwalten, ohne die Scheduler-
oder Persistenzarchitektur umzubauen. Die gespeicherte echte Listing-URL bleibt die Basis für
einen späteren, ausdrücklich benutzergesteuerten Kontakt-Workflow; Login oder automatisches
Anschreiben sind nicht implementiert. Ein normaler Endbenutzer soll langfristig keine
Terminalbefehle benötigen. **M4 wurde nicht begonnen und ist nicht Bestandteil dieses
Stands.**
