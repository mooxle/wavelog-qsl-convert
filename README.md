# 📮 wavelog-qsl-convert

> Vom Wavelog-Export zur druckfertigen QSL-Karte — fürs Büro sortiert, mit POTA-Parks, FT8-Rapporten und Umschlägen für Direktkarten.

QSL-Karten von Hand auszufüllen dauert, und ein roher Log-Export passt nicht auf eine Karte: Frequenz in Hz, Datum als `2026-04-14`, FT8-Rapporte, die in kein RST-Kästchen passen, POTA-Referenzen ohne Parknamen. Dieses Tool macht aus einem [Wavelog](https://www.wavelog.org/)-Export (ADIF oder CSV) eine saubere Seriendruck-Datei und bringt Word-Vorlagen mit, die die Karten für dich drucken.

![QSL-Karte, gedruckt auf Blanko-Karton](docs/card-blank.png)

## ✨ Was du bekommst

- **Druckfertige Karten mit einem Befehl.** Eine CSV speist drei Word-Vorlagen: eine komplette Kartenrückseite für Blanko-Karten, einen Überdruck für vorgedruckte Karten und Umschläge.
- **Karten in Büro-Reihenfolge.** Bureau-Karten sind nach Haupt-Prefix gebündelt, so wie das DARC-QSL-Büro sie haben will (USA nach Rufzeichengebiet, inklusive der Trennung W4/WA4). Der Stapel ist sortiert, wenn er aus dem Drucker kommt.
- **Bureau und Direct in einem Export.** Erst kommen die Bureau-Karten, dann die Direktkarten, und jede Karte trägt den Marker `via BUREAU` bzw. `via DIRECT`.
- **Umschläge für Direktkarten.** Die Postanschriften kommen von QRZ.com, auch die von QSL-Managern, die im Feld `QSL_VIA` genannt sind. Umschlag Nr. *n* gehört zu Karte Nr. *n*.
- **POTA inklusive.** Die Parknamen kommen aus der POTA-API und stehen neben der Referenz, bis zu vier Parks pro QSO (n-fer). Die Karte wird automatisch als *Portable* markiert.
- **FT8 richtig dargestellt.** Der SNR steht als `-07 dB` auf der Karte oder verteilt sich auf die drei R/S/T-Kästchen einer vorgedruckten Karte.
- **Dein tatsächlicher Standort.** Die Karte zeigt den Locator, von dem aus du gefunkt hast, nicht nur dein Heimat-QTH.
- **Rig und Antenne auf der Karte**, über zwei einfache Tags im Wavelog-Kommentar.
- **Keine Abhängigkeiten.** Eine Python-Datei, nur Standardbibliothek.

---

## 🚀 Quick Start

### 1. Voraussetzungen

- Python 3.9 oder neuer (keine Zusatzpakete)
- Microsoft Word für die Vorlagen (getestet mit Word für Mac)
- Optional: ein QRZ.com-Konto mit XML-Datenzugriff, für die Umschlag-Adressen

### 2. QSOs aus Wavelog exportieren

Exportiere die QSOs, für die du Karten willst, als **ADIF** (empfohlen) oder CSV, zum Beispiel aus der QSL-Druckwarteschlange von Wavelog. ADIF enthält alles, was die Karten brauchen (Leistung, eigener Locator, POTA-Referenzen, Bureau/Direct).

### 3. Konvertieren

```bash
python3 qsl_convert.py mein-export.adi
```

```
✓ 5 Einträge konvertiert → mein-export_seriendruck.csv
  Versand: BUREAU 4, DIRECT 1
```

Das Ergebnis `mein-export_seriendruck.csv` liegt im aktuellen Verzeichnis. Zum Ausprobieren liegt ein Beispiel-Log bei:

```bash
python3 qsl_convert.py examples/sample.adi --no-qrz
```

### 4. Mit Word drucken

1. Eine der Vorlagen öffnen (siehe Abschnitt „Vorlagen“).
2. *Sendungen → Empfänger auswählen → Vorhandene Liste verwenden…* und die `_seriendruck.csv` auswählen.
3. Mit *Vorschau Ergebnisse* durch die Karten blättern, dann *Fertig stellen und zusammenführen → Dokumente drucken*.

Word fragt einmal, ob es die Datendatei lesen darf. Mit *Ja* bestätigen.

---

## 🖨️ Vorlagen

Alle Vorlagen haben das Format 5,5 × 3,5 Zoll (140 × 89 mm) und nutzen dieselbe CSV.

| Vorlage | Wofür |
|---|---|
| `QSL_Blanko.docx` | **Blanko-Karten.** Druckt die komplette Rückseite in einem Durchgang, nur Schwarz und Grau (gemacht für einen Monochrom-Laserdrucker). |
| `QSL_Seriendruck.docx` | **Vorgedruckte Karten.** Druckt nur die QSO-Daten in die Kästchen einer vorhandenen Karte. |
| `umschlaege.docx` | **Umschläge** für Direktkarten, gespeist aus der Datei `_umschlaege.csv`. |

### Blanko-Karte: `QSL_Blanko.docx`

- **Oben links:** dein Rufzeichen (aus dem Log, damit auch `S5/DL9XX` stimmt), Name, Anschrift und die Daten des Heimat-QTH.
- **Oben rechts:** Platz für einen `VIA`-Manager und die Box `TO RADIO` mit dem Rufzeichen der Gegenstation, dem größten Element der Karte.
- **QSO-Tabelle:** Datum (`JJJJ-MM-TT`), UTC, MHz, Band, Mode und Rapport. Der Rapport zeigt bei FT8 `-07 dB`, bei SSB `57` und sonst den Rohwert.
- **Standort-Block:** der Locator, von dem aus du gefunkt hast, darunter `PORTABLE - PARKS ON THE AIR` mit den Parks. Ohne POTA steht dort `PORTABLE`, wenn der Locator vom Heimat-Locator abweicht, und nichts, wenn du zu Hause warst.
- **Stations-Block:** Rig, Leistung und Antenne.
- **Unten rechts:** `PSE QSL` (plus `TNX QSL`, wenn du schon eine Karte bekommen hast), dein Gruß und der Marker `QSL via BUREAU` / `DIRECT`.
- **POTA-Logo:** wird nur bei QSOs mit Park-Referenz gedruckt.

### Vorgedruckte Karte: `QSL_Seriendruck.docx`

![QSO-Daten als Überdruck auf einer vorgedruckten Karte](docs/card-preprinted.png)

Druckt Rufzeichen, Datum, Zeit, Frequenz, Mode und Rapport an feste Positionen, dazu ein `X` im Kästchen *Portable* bei POTA-QSOs und einen Block mit Parks, Setup, Leistung und Locator. Die Positionen passen zu einem bestimmten Kartenlayout. Für deine eigenen Karten verschiebst du die Tabellen in Word, bis sie auf deinen Kästchen sitzen.

### Vorlagen anpassen

Die Vorlagen enthalten Musterdaten (`DL9XX`, `Max Mustermann`, `JO40XX`, `DOK X00`). Vor dem ersten Druck:

1. Name, Anschrift, Heimat-Locator, DOK und Zonen durch deine eigenen ersetzen.
2. In `QSL_Blanko.docx` mit <kbd>Alt</kbd>+<kbd>F9</kbd> die Feldfunktionen einblenden und `JO40XX*` in der *Portable*-Bedingung (unten links) durch deinen Heimat-Locator ersetzen.
3. `QSL_Blanko.docx` nutzt die Schrift *Avenir Next Condensed* (bei macOS dabei). Auf anderen Systemen eine schmale Schrift wählen, sonst können die Spalten knapp werden.

---

## 🧩 Wie die Details funktionieren

### Rig und Antenne

Zwei Tags im Wavelog-Kommentar eines QSOs:

```
[antenna] Vertical Dipole - 4m high [rig] Yaesu FT-891
```

Sie landen in den Spalten `ANTENNE`, `RIG` und `SETUP` (`Yaesu FT-891 · Vertical Dipole - 4m high`). Text vor dem ersten Tag bleibt als normale Bemerkung in `BEMERKUNG`.

### POTA

- Mehrere Referenzen (`DE-0021,DE-0200`) sind möglich, Duplikate entfallen.
- Die Namen kommen von `https://api.pota.app/park/<REF>`, ergänzt um den Parktyp wie auf pota.app (`Wetterau Bird Sanctuary`). Jede Referenz wird pro Lauf nur einmal abgefragt.
- Der Word-Seriendruck kennt keine Schleifen, deshalb stehen die Parks in festen Spalten `POTA_1` … `POTA_4` (`DE-0021 – Bergstrasse-Odenwald Nature Park`); unbenutzte bleiben leer. `--pota-slots N` ändert die Anzahl.
- Ist eine Referenz unbekannt oder die API nicht erreichbar, gibt es eine Warnung und der Name bleibt leer. Die Konvertierung läuft trotzdem durch.

### Sortierung

Die Reihenfolge richtet sich nach `QSL_SENT_VIA` aus deinem Log:

1. **Bureau (`B`)** zuerst, nach Haupt-Prefix gebündelt, dann nach Rufzeichen.
2. **Direct (`D`)**, nach Datum und Uhrzeit.
3. **Alles andere**, nach Datum und Uhrzeit.

Die Bündelung für das Büro folgt der [Prefix-Liste des DARC-QSL-Büros](https://www.darc.de/geschaeftsstelle/qsl-buero/) (Stand 4/18), die im Script hinterlegt ist:

- Alle deutschen Prefixe (`DA`–`DR`) bilden die Gruppe `DL`.
- USA wird nach der Zahl im Rufzeichen gruppiert (`W0` … `W9`). Zwei Buchstaben vor einer 4 (`AA4`, `KA4`, `WA4`) gehen an `WA4`, der Rest an `W4`.
- Portable-Rufzeichen zählen nach dem Heimatrufzeichen: `LA/DL9XX/P` → `DL`.
- Die Gruppe steht in der Spalte `DARC_GRUPPE`, praktisch für die Banderole um jedes Bündel.
- Unbekannte Prefixe landen mit einer Warnung am Ende der Bureau-Karten.

Die Liste stammt von 2018. Neuere Prefixe lassen sich im Script in `DARC_PREFIXLISTE` nachtragen.

### Umschläge für Direktkarten

Für jedes QSO mit `QSL_SENT_VIA` = `D` schreibt das Script zusätzlich `<export>_umschlaege.csv` mit der Postanschrift aus der QRZ.com-XML-Datenbank.

- **Zugangsdaten:** `QRZ_USERNAME` und `QRZ_PASSWORD` setzen oder das Script im Terminal fragen lassen. Das Passwort wird nicht angezeigt und nie gespeichert. Ein leeres Passwort überspringt den Schritt.
- **QSL-Manager:** Nennt `QSL_VIA` ein anderes Rufzeichen (`QSL VIA ONLY KU9C`), wird die Adresse des Managers verwendet. Reine Hinweise wie `NO BURO, DIRECT only!` werden ignoriert.
- **Portable-Rufzeichen** werden über das Heimatrufzeichen abgefragt (`OE1RDU/3` → `OE1RDU`).
- **Eine Zeile pro QSO**, in derselben Reihenfolge wie die Direktkarten. Jedes Rufzeichen wird nur einmal abgefragt.
- **Fehlende Adressen** listet das Script am Ende auf und markiert sie in der Spalte `Status`.

### FT8 und RST

- **FT8:** `RST_SENT_FT8` enthält `-07 dB`. Für vorgedruckte Karten werden die drei Zeichen zusätzlich auf `RST_R` / `RST_S` / `RST_T` verteilt (`-`, `0`, `7`).
- **SSB:** `59` wird zu R `5`, S `9`.
- **Andere Betriebsarten** (CW, …): werden genauso zerlegt, der Rohwert bleibt erhalten.

### Wo welche Logik steckt

Faustregel: **Das Script entscheidet, was die Daten sind, Word entscheidet, was angezeigt wird.** Die CSV dazwischen ist reiner Text, den du öffnen und prüfen kannst.

| Macht das Python-Script | Macht Word (Wenn-Felder in den Vorlagen) |
|---|---|
| ADIF/CSV lesen, Einheiten und Formate umrechnen (MHz, Datumsteile, `HHMM`) | Eine Zeile ausblenden, wenn ihr Feld leer ist (Rig, Antenne, Leistung, Bemerkung, Parks) |
| RST zerlegen und den FT8-Rapport formatieren | Auswählen, welcher Rapport gedruckt wird: FT8-Wert oder R/S (Blanko-Karte); drittes RST-Kästchen und FT8-Hinweis nur bei FT8 (vorgedruckte Karte) |
| `[antenna]` / `[rig]` aus dem Kommentar lösen | — |
| POTA-Parknamen abfragen und `POTA_1` … `POTA_4` füllen | Überschrift `PORTABLE - PARKS ON THE AIR`, das POTA-Logo und das `X` im Kästchen *Portable*, jeweils ausgelöst durch ein gefülltes `POTA_1` |
| — | `PORTABLE` ohne POTA: Vergleich des QSO-Locators mit deinem Heimat-Locator |
| Sortierung (Bureau nach DARC-Gruppe, dann Direct) | — |
| `QSL_SENT_VIA` in `BUREAU` / `DIRECT` übersetzen | Den Marker `via …` drucken; `TNX QSL` nur, wenn `TNX_QSL` = `X` |
| Umschlag-Adressen von QRZ.com, QSL-Manager erkennen | — |

Was das praktisch heißt:

- **Wie etwas aussieht oder wann es erscheint**, änderst du in Word. <kbd>Alt</kbd>+<kbd>F9</kbd> zeigt die Bedingungen.
- **Dein Heimat-Locator** steht nur in der Word-Vorlage (in der *Portable*-Bedingung). Das Script kennt ihn nicht.
- **Mehr als vier Parks** brauchen beide Seiten: `--pota-slots N` im Script und passende Zeilen in der Vorlage.
- **Die Sortierung** lässt sich in Word nicht ändern; die Karten werden in der Reihenfolge der CSV gedruckt.
- **Eine eigene Vorlage** braucht nur die Seriendruckfelder aus der Spaltenreferenz unten. Keine der Bedingungen ist Pflicht.

---

## ⚙️ Optionen

```bash
python3 qsl_convert.py <export.adi|export.csv> [ausgabe.csv] [optionen]
```

| Option | Wirkung |
|---|---|
| `--no-pota` | Keine Parknamen bei der POTA-API abfragen |
| `--pota-slots N` | Anzahl der Spalten `POTA_n` (Standard 4; die Vorlage muss dazu passen) |
| `--no-qrz` | Keine Umschlag-Adressen abfragen |
| `--umschlaege DATEI` | Ausgabename für die Umschlag-CSV |
| `--qrz-delay SEK` | Pause zwischen QRZ-Abfragen (Standard 1.0) |

<details>
<summary><b>📋 Spaltenreferenz</b></summary>

Die Seriendruck-CSV ist UTF-8 mit BOM, alle Felder stehen in Anführungszeichen.

| Quellfeld | Spalte | Beispiel |
|---|---|---|
| `CALL` | `AN_RUFZEICHEN` | `W1AW` |
| `STATION_CALLSIGN` | `EIGENES_CALL` | `DL9XX/P` |
| `QSO_DATE` / `DATE_ON` | `DATUM_T`, `DATUM_M`, `DATUM_J` | `12`, `09`, `2026` |
| `TIME_ON` | `UTC_ZEIT` | `1015` |
| `FREQ` | `FREQUENZ` (MHz) | `14.244` |
| `BAND` | `BAND` | `20m` |
| `MODE` | `BETRIEBSART` | `SSB` |
| `RST_SENT` | `RST_SENT_FT8`, `RST_R`, `RST_S`, `RST_T` | `-07 dB`, `-`, `0`, `7` |
| `QSL_RCVD` | `TNX_QSL` | `X`, wenn empfangen |
| — | `PSE_QSL` | immer `X` |
| `TX_PWR` | `LEISTUNG_W` | `100` |
| `MY_GRIDSQUARE` | `EIGENER_LOCATOR` | `JN49EP` |
| `MY_POTA_REF` | `POTA_REF`, `POTA_NAME`, `POTA_ANZAHL`, `POTA_1` … `POTA_4` | `DE-0021 – Bergstrasse-Odenwald Nature Park` |
| `COMMENT` | `ANTENNE`, `RIG`, `SETUP`, `BEMERKUNG` | `Yaesu FT-891 · Vertical Dipole - 4m high` |
| `QSL_SENT_VIA` | `VERSAND` | `BUREAU`, `DIRECT`, `ELECTRONIC`, `MANAGER` |
| `CALL` | `DARC_GRUPPE` | `DL`, `JA`, `W1` |
| `QSL_VIA`, `GRIDSQUARE`, `COUNTRY` | `QSL_VIA`, `GRIDSQUARE`, `ENTITY` | unverändert |

Umschlag-CSV (Trennzeichen `;`): `Rufzeichen`, `Via_Rufzeichen`, `QRZ_Rufzeichen`, `Datum`, `Band`, `Vorname`, `Nachname`, `Adresse`, `Ort`, `Bundesland`, `PLZ`, `Land`, `Status`.

Ein CSV-Export aus Wavelog funktioniert auch, enthält Leistung, Locator, POTA und Bureau/Direct aber nur, wenn diese Spalten Teil des Exports sind. Fehlende Felder brechen den Lauf nie ab; die Spalte bleibt dann leer.

</details>

---

## 🔒 Datenschutz und fremde Dienste

- Log-Exporte und die erzeugten CSV-Dateien enthalten Rufzeichen, Bemerkungen und Postanschriften anderer Personen. Sie sind per `.gitignore` von Git ausgeschlossen. Lege sie nicht an öffentlichen Orten ab.
- Das Script kontaktiert `api.pota.app` (Parknamen) und, nur wenn du Zugangsdaten angibst, `xmldata.qrz.com` (Adressen). Sonst verlässt nichts deinen Rechner.
- Kein offizielles Projekt von Wavelog, DARC, Parks on the Air oder QRZ.com.

## 📄 Lizenz

[MIT](LICENSE) für das Script und die Vorlagen.

Das Parks-on-the-Air-Logo in `QSL_Blanko.docx`, `umschlaege.docx` und im Screenshot gehört [Parks on the Air](https://parksontheair.com/) und fällt nicht unter die MIT-Lizenz. Entferne oder ersetze es, wenn du nicht am Programm teilnimmst. Die Prefix-Bündelung für das Büro basiert auf der Prefix-Liste des DARC-QSL-Büros.

73!
