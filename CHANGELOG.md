# Changelog

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/).

## [1.0.0] — Unreleased

Erster V1.0-Release: öffentlicher Willhaben-Marktplatz, Live-Suchen, präzise tiefe
Kategoriepfade, Willhaben-Suchlink-Import, Templates, Desktop-Sound, ntfy/Discord/
E-Mail mit wiederverwendbaren Benachrichtigungszielen, Firefox-Popup/-Dashboard,
Backup/Restore, portable Windows-/Linux-Release-Pakete ohne benötigtes Python/Node
beim Endbenutzer.

### Hinzugefügt

- Wiederverwendbare Benachrichtigungsziele (mehrere ntfy-/Discord-/E-Mail-Ziele,
  frei pro Suche wählbar, Union-Deduplizierung über mehrere passende Suchen).
- Willhaben-Suchlink-Import mit voller Tiefkategorie-Unterstützung; Keyword wird
  bei gesetzter Kategorie optional.
- Backup-Export/-Import für Suchen, Vorlagen und Ziel-Metadaten (ohne Secrets).
- Startschutz gegen versehentlichen doppelten Start ("Willhaben-Suchagent läuft
  bereits.").
- Protokollversionierung zwischen Firefox-Erweiterung und lokalem Native-
  Messaging-Host; ein veralteter Host meldet sich klar statt mit einem
  kryptischen Teilfehler.
- Portable, relocatable Windows-/Linux-Release-Pakete mit gebündelter
  Python-Laufzeit (PyInstaller) — kein Python, pip, venv oder Node beim
  Endbenutzer nötig.
- Zentrale Versionsnummer (`agent/app/_version.py`), verwendet von Backend,
  Firefox-Erweiterung und User-Agent.

### Bekannte Einschränkungen

- Nur Willhaben-Marktplatz. Auto & Motor, Immobilien, Jobs folgen nach V1.0.
- Kein Willhaben-Login, keine automatische Verkäuferkontaktaufnahme.
- Öffentliche Seitenstruktur von willhaben.at kann sich ändern; Schutzmaßnahmen
  (403/429/Challenge) werden nicht umgangen.
