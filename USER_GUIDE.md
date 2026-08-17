# Willhaben-Suchagent — Benutzeranleitung

Diese Anleitung richtet sich an normale Benutzer, die den Willhaben-Suchagenten
installieren und benutzen wollen — kein Programmier- oder Terminal-Wissen nötig.

Für Entwickler-/Quellcode-Informationen siehe [README.md](README.md).

## Was der Willhaben-Suchagent tut — und was er NICHT tut

- Er durchsucht **ausschließlich den öffentlichen Willhaben-Marktplatz** (Kleinanzeigen).
  Auto & Motor, Immobilien und Jobs sind noch nicht unterstützt.
- Er benötigt **keinen Willhaben-Login** und keine Cookies — er liest nur öffentlich
  sichtbare Seiten.
- Er sendet **niemals automatisch Nachrichten an Verkäufer**. Er bereitet höchstens
  Text vor, den du selbst kopierst und selbst versendest.
- ntfy, Discord und E-Mail sind **reine Benachrichtigungen** — "es gibt ein neues
  Inserat", nicht mehr.
- Firefox ist die **einzige Bedienoberfläche**. Ein zusätzliches, dauerhaft offenes
  Fenster (schwarzes Terminal- bzw. CMD-Fenster) ist der eigentliche Suchagent im
  Hintergrund — siehe unten.

## Installation — Windows

1. Das Release-Paket (`Willhaben-Suchagent-1.0.0-windows-x86_64.zip`) an einen
   beliebigen Ort entpacken, z. B. auf den Desktop oder in einen eigenen
   Programme-Ordner. Der Pfad darf Leerzeichen enthalten und auf einem beliebigen
   Laufwerk liegen.
2. `Einrichtung.bat` doppelklicken. Es öffnet sich ein Fenster, das die lokale
   Verbindung zu Firefox einrichtet. Es ist kein Python und keine
   Administratorrechte nötig.
3. Firefox öffnen, `about:addons` aufrufen, das Zahnrad-Symbol → "Add-on aus Datei
   installieren…" wählen und `extension\willhaben-suchagent.xpi` aus dem
   Programmordner auswählen. (Zum aktuellen Signierungsstatus siehe unten.)
4. `Willhaben-Suchagent starten.bat` doppelklicken. Es öffnet sich ein Fenster mit
   der Meldung, dass der Suchagent läuft — **dieses Fenster offen lassen**,
   solange du den Suchagenten benutzen willst.
5. Auf das Erweiterungssymbol in Firefox klicken und eine erste Suche einrichten.
6. Optional: Benachrichtigungsziele einrichten (siehe unten).

## Installation — Linux

1. Das Release-Paket (`Willhaben-Suchagent-1.0.0-linux-x86_64.tar.gz`) an einen
   beliebigen Ort entpacken, z. B. `~/Programme/Willhaben-Suchagent`.
2. `./Einrichtung.sh` ausführen. Es ist kein `sudo` nötig. Dabei wird — sofern
   verfügbar — automatisch ein `systemd --user`-Autostart eingerichtet, sodass der
   Suchagent auch nach einem Neustart automatisch im Hintergrund läuft.
3. Firefox öffnen, `about:addons` aufrufen, das Zahnrad-Symbol → "Add-on aus Datei
   installieren…" wählen und `extension/willhaben-suchagent.xpi` auswählen.
4. Falls kein Autostart eingerichtet wurde (oder der Agent gerade nicht läuft):
   `./"Willhaben-Suchagent starten.sh"` ausführen. Das Terminal-Fenster muss
   offen bleiben, solange kein Autostart aktiv ist.
5. Auf das Erweiterungssymbol in Firefox klicken und eine erste Suche einrichten.

## Programmordner verschieben

Der komplette Programmordner darf jederzeit an einen anderen Ort verschoben werden
(anderer Ordner, anderes Laufwerk, anderer Rechnerpfad). Danach einmal
`Einrichtung.bat`/`Einrichtung.sh` erneut ausführen — das aktualisiert die lokale
Verbindung zu Firefox (und unter Linux den Autostart-Dienst) auf den neuen Pfad.
Deine Suchen, Vorlagen, Ziele und Einstellungen bleiben dabei erhalten, da sie
**nicht** im Programmordner, sondern in einem Benutzer-Datenverzeichnis des
Betriebssystems liegen.

## Eine Suche einrichten

- **Stichwort-Suche**: Suchbegriff eingeben, optional Ort und Preisspanne.
- **Tiefe Kategorie**: über "Willhaben-Suchlink übernehmen" einen echten
  Willhaben-Such-Link einfügen (z. B. nachdem du auf willhaben.at selbst gefiltert
  hast) — der Suchagent übernimmt die genaue Kategorie, sodass die Treffer
  präziser sind als bei einer reinen Stichwortsuche.

## Benachrichtigungen einrichten

Unter Einstellungen → Benachrichtigungen legst du wiederverwendbare **Ziele** an:

- **Push (ntfy)**: eigener oder öffentlicher ntfy-Server + Thema.
- **Discord**: ein Server-Webhook.
- **E-Mail**: Empfängeradresse (der Versand selbst läuft über einen einmalig
  konfigurierten SMTP-Account, den du unter "SMTP-Absender" hinterlegst).

Jede Suche wählt anschließend selbst aus, welche dieser Ziele sie benutzen soll —
keines, eines oder mehrere gleichzeitig. Ein neues, gerade angelegtes Ziel ist bei
neuen Suchen bewusst noch nicht vorausgewählt.

## Backup

Unter Einstellungen → Daten kannst du ein Backup exportieren (Suchen, Vorlagen,
Ziel-Namen und Zuordnungen) und später wieder importieren. **Passwörter, Tokens
und Discord-Webhooks werden aus Sicherheitsgründen nie mit exportiert** — nach
einem Import müssen diese für importierte Ziele einmalig neu eingegeben werden.
Ein Import überschreibt nichts Vorhandenes; bereits existierende Einträge
(gleicher Name) werden übersprungen.

## Firefox-Erweiterung dauerhaft installieren

Firefox verlangt für eine **dauerhafte** Installation normalerweise eine
Signierung durch Mozilla (AMO). Die mitgelieferte `.xpi` ist für die Installation
über "Add-on aus Datei installieren…" vorbereitet; ob sie ohne weitere Schritte
dauerhaft bestehen bleibt, hängt vom Signierungsstatus des jeweiligen Release
ab — siehe die Release Notes der jeweiligen Version für den genauen Stand.
Es wird nicht empfohlen und nicht dokumentiert, Firefox-Sicherheitsfunktionen zu
deaktivieren, um eine unsignierte Erweiterung zu erzwingen.

## Das schwarze Fenster

Das Fenster, das sich beim Ausführen von "Willhaben-Suchagent starten" öffnet,
**ist** der laufende Suchagent — kein Fehler und keine Nebensache. Solange kein
Autostart eingerichtet ist, muss es geöffnet bleiben, damit der Suchagent im
Hintergrund weiterläuft und Firefox mit ihm sprechen kann.

## Wenn zweimal gestartet wird

Wird "Willhaben-Suchagent starten" ein zweites Mal ausgeführt, während der Agent
bereits läuft, erscheint die Meldung "Willhaben-Suchagent läuft bereits." — das
Fenster kann dann einfach geschlossen werden, die erste Instanz läuft normal
weiter.

## Wenn die Erweiterung "Lokale Verbindung veraltet" meldet

Das bedeutet, dass die installierte lokale Verbindung (Native-Messaging-Host)
älter ist als die installierte Erweiterung. Führe in diesem Fall die Einrichtung
(`Einrichtung.bat`/`Einrichtung.sh`) erneut aus.

## Bekannte Einschränkungen (Version 1.0.0)

- Nur der öffentliche Willhaben-Marktplatz; Auto & Motor, Immobilien und Jobs
  folgen erst nach V1.0.
- Kein Willhaben-Login.
- Keine automatische Kontaktaufnahme mit Verkäufern.
- Die öffentliche Seitenstruktur von willhaben.at kann sich jederzeit ändern.
- Schutzmaßnahmen von willhaben.at (z. B. HTTP 403/429 oder Challenge-Seiten)
  werden nicht umgangen — der Suchagent zeigt den Fehler an und versucht es beim
  nächsten Zyklus erneut.
