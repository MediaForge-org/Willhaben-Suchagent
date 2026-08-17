# Release-Test-Checkliste — Willhaben-Suchagent 1.0.0

Manuelle Abnahme vor Tag/Release. Automatisierte Prüfungen (pytest, Ruff,
npm typecheck/test/build, Packaging-/Protokoll-/Backup-Tests, Security-Audit)
sind bereits Teil der CI-Sequenz und hier nicht wiederholt.

## Installation

- [ ] Windows: frisches System, Release-ZIP entpackt, `Einrichtung.bat` läuft ohne Python durch
- [ ] Linux: frisches System, Release-Tarball entpackt, `Einrichtung.sh` läuft ohne `sudo` durch
- [ ] Installationspfad mit Leerzeichen (z. B. `Eigene Programme\Willhaben Suchagent`)
- [ ] Windows: anderes Laufwerk als `C:` (z. B. `D:\Programme\...`)
- [ ] Programmordner nach Einrichtung verschoben → Einrichtung erneut ausgeführt → Native
      Messaging zeigt auf neuen Pfad, Daten bleiben erhalten
- [ ] Native Messaging: Firefox erkennt den Host nach Einrichtung ohne Neuinstallation der
      Erweiterung

## Agent

- [ ] Start per Doppelklick auf "Willhaben-Suchagent starten"
- [ ] Zweiter Start bei bereits laufendem Agent zeigt "Willhaben-Suchagent läuft bereits."
      und startet keine zweite Instanz
- [ ] Firefox komplett geschlossen: Agent läuft weiter (bei aktivem Autostart)
- [ ] Firefox geöffnet: Dashboard verbindet sich automatisch
- [ ] Rechner-/Agent-Neustart mit aktivem Autostart (Linux systemd --user): Agent läuft
      danach automatisch wieder
- [ ] Alter Native-Messaging-Host + neue Erweiterung: klare Meldung "Lokale Verbindung
      veraltet", kein kryptischer Teilfehler

## Suche

- [ ] Reine Stichwortsuche liefert Treffer
- [ ] Tiefe Kategorie (Willhaben-Suchlink übernehmen, z. B. iPhone 13 Mini) liefert präzisere
      Treffer als die Stichwortsuche
- [ ] Baseline: erster Lauf einer neuen Suche löst keine Benachrichtigung aus
- [ ] Neues Inserat nach Baseline löst genau eine Benachrichtigung je gewähltem Ziel aus
- [ ] Enrichment (Anbieter, Zustand, Ort, Bild) erscheint im Dashboard, sobald verfügbar

## Benachrichtigungen

- [ ] Desktop-Sound spielt bei neuem Inserat, höchstens einmal pro Zyklus
- [ ] ntfy-Ziel: Test-Button liefert Push aufs Gerät
- [ ] Discord-Ziel: Test-Button liefert Nachricht im Kanal
- [ ] E-Mail-Ziel (z. B. Gmail als SMTP-Absender): Test-Button liefert Mail
- [ ] Zwei Suchen mit demselben Ziel (z. B. Discord): ein passendes Inserat löst dieses Ziel
      nur einmal aus
- [ ] Zwei Suchen mit unterschiedlichen Zielen: ein Inserat, das beide trifft, benachrichtigt
      beide Ziele unabhängig voneinander

## Templates

- [ ] Vorlage mit Namen im Text
- [ ] Vorlage ohne Namen im Text
- [ ] `article_phrase` wird korrekt eingesetzt
- [ ] Fallback auf `article_label`, wenn keine genauere Phrase vorliegt
- [ ] "Kopieren" legt den fertigen Text in die Zwischenablage
- [ ] "Inserat öffnen" öffnet die echte Willhaben-Seite in einem neuen Tab

## Backup

- [ ] Export lädt eine JSON-Datei herunter
- [ ] Import derselben Datei erkennt alles als bereits vorhanden (keine Duplikate)
- [ ] Import in eine leere Installation legt Suchen/Vorlagen/Ziele neu an
- [ ] Passwörter/Tokens/Webhooks fehlen nach Import erwartungsgemäß und müssen neu
      eingerichtet werden — das Dashboard weist klar darauf hin

## Robustheit

- [ ] Internetverbindung kurz trennen: Agent bleibt stabil, versucht es im nächsten Zyklus
      erneut
- [ ] Rechner in den Suspend-Modus versetzen und wieder aufwecken: kein Absturz, keine
      Flut nachgeholter Zyklen
- [ ] Firefox neu starten, während der Agent läuft: Dashboard verbindet sich automatisch neu
- [ ] Agent-Fenster schließen und über "Willhaben-Suchagent starten" neu starten: Daten
      (Suchen, Vorlagen, Ziele) bleiben erhalten
