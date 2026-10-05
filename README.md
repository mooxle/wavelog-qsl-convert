# wavelog-qsl-convert

Konvertiert den QSL-Export aus [Wavelog](https://www.wavelog.org/) (CSV oder ADIF) in ein serienbrieftaugliches CSV — zum Beispiel für den Seriendruck von QSL-Karten in Word.

## Warum?

Der Wavelog-Export liefert Frequenz in Hz, Datum als `2026-04-14`, RST als Rohwert und weitere Felder, die sich so nicht direkt in eine Karten-Vorlage übernehmen lassen. Das Script bereitet die Daten so auf, dass sie als Serienbrief-Datenquelle direkt passen (Datum in Tag/Monat/Jahr getrennt, Frequenz in MHz, RST je Betriebsart aufgeteilt usw.).

## Voraussetzungen

- Python 3.9+ (nur Standardbibliothek, keine externen Abhängigkeiten)
- Ein QSL-Export aus Wavelog als CSV oder ADIF (`.adi` / `.adif`)
- Internetzugang für die POTA-Parknamen (optional, siehe `--no-pota`)
- Für die Umschlag-Adressen der Direct-Karten: ein QRZ.com-Konto mit XML-Datenzugriff (optional, siehe `--no-qrz`)

## Quick Start

```bash
python3 qsl_convert.py qsl_export.csv
```

Die Ausgabe landet als `qsl_export_seriendruck.csv` im aktuellen Verzeichnis. Ein anderer Ausgabename lässt sich als zweites Argument angeben:

```bash
python3 qsl_convert.py qsl_export.csv karten.csv
```

ADIF-Dateien werden an der Endung `.adi`/`.adif` (oder am Inhalt) erkannt und genauso übergeben:

```bash
python3 qsl_convert.py DA6MAX-20260919-1443.adi
```

Ohne Netzwerk oder wenn die POTA-API nicht abgefragt werden soll:

```bash
python3 qsl_convert.py export.adi --no-pota
```

Anzahl der POTA-Slots ändern (Standard 4, siehe [POTA](#pota)):

```bash
python3 qsl_convert.py export.adi --pota-slots 6
```

## Erwartete Eingabefelder

**CSV:** `CALL`, `STATION_CALLSIGN`, `QSL_VIA`, `DATE_ON`, `TIME_ON`, `FREQ` (Hz), `BAND`, `MODE`, `RST_SENT`, `QSL_RCVD`, `COMMENT`, `GRIDSQUARE`, `ENTITY`

**ADIF:** `CALL`, `STATION_CALLSIGN`, `QSL_VIA`, `QSO_DATE`, `TIME_ON`, `FREQ` (MHz), `BAND`, `MODE`, `RST_SENT`, `QSL_RCVD`, `COMMENT`, `GRIDSQUARE`, `COUNTRY` (→ `ENTITY`)

Für die Felder zur eigenen Station (`TX_PWR`, `MY_GRIDSQUARE`, `MY_POTA_REF`) und den Versandweg (`QSL_SENT_VIA`) gilt in beiden Formaten derselbe Feldname. Ein CSV-Export enthält sie nur, wenn Wavelog die Spalten mit ausgibt.

Fehlende Felder führen nicht zum Abbruch, das jeweilige Feld bleibt dann leer.

## Transformationen

| Eingabe | Ausgabe | Beispiel |
|---|---|---|
| `FREQ` (Hz) | `FREQUENZ` (MHz, 3 Nachkommastellen) | `21230000` → `21.230` |
| `DATE_ON` | `DATUM_T` / `DATUM_M` / `DATUM_J` | `2026-04-14` → `14` / `04` / `2026` |
| `TIME_ON` | `UTC_ZEIT` (HHMM) | `18:00:45` → `1800` |
| `RST_SENT` bei FT8 | `RST_SENT_FT8` | `-12` → `-12 dB` |
| `RST_SENT` bei FT8 | `RST_R` / `RST_S` / `RST_T` | `-12` → `-` / `1` / `2` (Vorzeichen, Zehner, Einer) |
| `RST_SENT` bei SSB | `RST_R` / `RST_S` / `RST_T` | `59` → `5` / `9` / `9` |
| `MODE` | `BETRIEBSART` | unverändert (Großbuchstaben) |
| `CALL` | `AN_RUFZEICHEN` | |
| `STATION_CALLSIGN` | `EIGENES_CALL` | |
| `COMMENT` | `BEMERKUNG` | |
| `QSL_RCVD` | `TNX_QSL` | `X` bei `Y` oder `V`, sonst leer |
| — | `PSE_QSL` | immer `X` (alle Karten werden zum Bestätigen verschickt) |
| `TX_PWR` | `LEISTUNG_W` | `100` (`5.0` → `5`) |
| `MY_GRIDSQUARE` | `EIGENER_LOCATOR` | Locator des eigenen Standorts beim QSO, z. B. `JN49EP` |
| `MY_POTA_REF` | `POTA_REF` | `DE-0021, DE-0200` |
| `POTA_REF` → POTA-API | `POTA_NAME` | `Bergstrasse-Odenwald Nature Park / Maulbeeraue Natura 2000` |
| `POTA_REF` + Namen | `POTA_ANZAHL`, `POTA_1` … `POTA_4` | feste Slots für Word, siehe [POTA](#pota) |
| `COMMENT` | `ANTENNE`, `RIG`, `SETUP` | siehe unten |
| `QSL_SENT_VIA` | `VERSAND` | `B` → `BUREAU`, `D` → `DIRECT`, `E` → `ELECTRONIC`, `M` → `MANAGER` |
| `CALL` | `DARC_GRUPPE` | Haupt-Prefix für das DARC-QSL-Büro, z. B. `DL`, `JA`, `W1` |

`QSL_VIA`, `BAND`, `GRIDSQUARE` und `ENTITY` werden unverändert übernommen.

### Antenne und Rig im Kommentar

Im Wavelog-Kommentar können `[antenna]` und `[rig]` als versteckte Felder stehen:

```
[antenna] Vertical Dipole - 4m high [rig] Yaesu FT-891
```

Daraus werden `ANTENNE` = `Vertical Dipole - 4m high` und `RIG` = `Yaesu FT-891`. `SETUP` fasst beides zu `Yaesu FT-891 · Vertical Dipole - 4m high` zusammen (fehlt eines, steht nur das andere da). Die Reihenfolge der Tags ist egal. `BEMERKUNG` enthält nur den Text vor dem ersten Tag, ist also leer, wenn der Kommentar nur aus diesen beiden Tags besteht.

### POTA

- Mehrere Referenzen (`DE-0021,DE-0200`) werden in `POTA_REF` kommagetrennt ausgegeben, Duplikate entfallen.
- `POTA_NAME` enthält die Parknamen in derselben Reihenfolge, getrennt mit ` / `, weil Parknamen selbst Kommas enthalten können.
- Die Namen kommen von `https://api.pota.app/park/<REF>`, ergänzt um den Parktyp wie auf pota.app angezeigt (`Wetterau` + `Bird Sanctuary` → `Wetterau Bird Sanctuary`), und werden pro Lauf zwischengespeichert. Jede Referenz wird nur einmal abgefragt.
- **Feste Slots für Serienbriefe:** Word kennt keine Schleifen, ein Feld muss immer existieren. Deshalb gibt es `POTA_ANZAHL` (`0`, `1`, `2` …) und `POTA_1` bis `POTA_4` im Format `DE-0021 – Bergstrasse-Odenwald Nature Park`. Unbelegte Slots sind leer, bei 0 Parks sind alle leer. Die Spaltenzahl ist bewusst konstant, damit die Word-Vorlage über alle Läufe passt. Hat ein QSO mehr Parks als Slots, warnt das Script auf stderr; mit `--pota-slots N` lassen sich mehr Slots erzeugen (die Vorlage muss dann entsprechend erweitert werden).
- Ist eine Referenz unbekannt oder die API nicht erreichbar, erscheint eine Warnung auf stderr und `POTA_NAME` bleibt leer. Die Konvertierung läuft trotzdem durch.

### RST-Sonderfälle

- **FT8:** Der Report ist der SNR in dB, immer Vorzeichen plus zwei Ziffern, also genau drei Zeichen. Sie werden auf `RST_R`, `RST_S` und `RST_T` verteilt (`-07` → `-` / `0` / `7`), damit sie in die drei RST-Kästchen der Karte passen. Einstellige Werte werden aufgefüllt (`-7` → `-07`), ein fehlendes Vorzeichen wird zu `+`. Passt ein Wert nicht in dieses Schema, bleiben die drei Felder leer.
- **SSB:** Bei zweistelligem RST (`59`) wird T mit `9` ergänzt (Telefonie-Konvention).
- **Andere Betriebsarten** (z. B. CW): `RST_SENT_FT8` enthält den unveränderten Rohwert, zusätzlich wird er wie bei SSB in R/S/T zerlegt.

## Umschläge für Direct-Karten

Für alle QSOs mit `QSL_SENT_VIA` = `D` schreibt das Script zusätzlich `<eingabe>_umschlaege.csv` mit der Postanschrift je QSO, abgefragt bei der QRZ.com-XML-Datenbank. Gibt es keine Direct-Karten, entfällt der Schritt.

```bash
python3 qsl_convert.py export.adi
```

- **Zugangsdaten:** Die Umgebungsvariablen `QRZ_USERNAME` und `QRZ_PASSWORD` werden verwendet. Fehlen sie und läuft das Script in einem Terminal, fragt es nach Benutzername (Vorschlag: dein Rufzeichen) und Passwort; das Passwort wird nicht angezeigt und nie gespeichert. Ein leeres Passwort überspringt den Schritt. Ohne Terminal und ohne Variablen wird der Schritt übersprungen, die Karten-CSV entsteht trotzdem.
- **QSL-Manager:** Steht in `QSL_VIA` ein anderes Rufzeichen als das der Gegenstation (z. B. `LY2QT` oder `QSL VIA ONLY KU9C - …`), wird die Adresse dieses Rufzeichens abgefragt. Reine Hinweise wie `NO BURO, DIRECT only!` werden ignoriert.
- **Portable-Zusätze:** Für die Abfrage zählt das Heimatrufzeichen (`OE1RDU/3` → `OE1RDU`, `LA/DA6MAX/P` → `DA6MAX`). In der Spalte `Rufzeichen` steht weiterhin das Rufzeichen aus dem Log.
- **Eine Zeile pro QSO:** Zeilen werden nicht zusammengefasst, auch wenn mehrere QSOs denselben Manager haben. Jedes Ziel-Rufzeichen wird aber nur einmal bei QRZ abgefragt. Die Reihenfolge entspricht der der Karten (Direct nach Datum), so passt Umschlag Nr. n zu Karte Nr. n.
- **Fehlende Adressen:** Die Spalte `Status` zeigt `OK`, `OHNE ADRESSE BEI QRZ` oder `NICHT GEFUNDEN (…)`. Am Ende listet das Script die Rufzeichen ohne Adresse.
- **Format:** Spalten `Rufzeichen`, `Via_Rufzeichen`, `QRZ_Rufzeichen`, `Datum`, `Band`, `Vorname`, `Nachname`, `Adresse`, `Ort`, `Bundesland`, `PLZ`, `Land`, `Status`, Trennzeichen `;`, UTF-8 mit BOM. Das entspricht der bisherigen `adressen.csv` und passt zur Umschlag-Vorlage.
- **Optionen:** `--no-qrz` (überspringen), `--umschlaege DATEI` (anderer Ausgabename), `--qrz-delay SEK` (Pause zwischen Abfragen, Standard 1 s).

`umschlaege.docx` ist die passende Serienbrief-Vorlage für den Umschlagdruck (Felder `Vorname`, `Nachname`, `Rufzeichen`, `Adresse`, `Ort`, `Bundesland`, `PLZ`, `Land`). Der in der Datei hinterlegte Datenquellen-Pfad muss beim ersten Öffnen auf die eigene Umschlag-CSV zeigen.

Die Adress-CSV enthält personenbezogene Daten und ist wie alle CSV-Dateien von der Versionierung ausgeschlossen.

## Word-Vorlage

`QSL_Seriendruck.docx` ist die Serienbrief-Vorlage für die Kartenrückseite (5,5" × 3,5", Überdruck auf vorgedruckte Karten). Sie erwartet das CSV aus diesem Script als Datenquelle; der in der Datei hinterlegte Pfad muss beim ersten Öffnen auf die eigene CSV zeigen.

Die Kachel oben links (Markierung „Portable“) bekommt ein `X`, sobald `POTA_1` befüllt ist, also mindestens eine POTA-Referenz vorhanden ist.

Die Box links unten enthält, in dieser Reihenfolge (die erste Zeile trägt rechts außen zusätzlich den Versandweg `via BUREAU` bzw. `via DIRECT`, damit sich die gedruckten Karten auf einen Blick trennen lassen):

1. Hinweis `FT-8 · Report = SNR in dB` (klein, kursiv, grau, mit Abstand zu den übrigen Zeilen), nur wenn `BETRIEBSART` = `FT8`; bei allen anderen Betriebsarten bleibt die Zeile leer
2. `POTA_1` … `POTA_4` (leere Slots bleiben leer)
3. `Setup: «SETUP»`, nur wenn vorhanden
4. `Power (W): «LEISTUNG_W»` und `Loc: «EIGENER_LOCATOR»`, je nur wenn vorhanden

Bei FT8 zeigen die drei RST-Kästchen den SNR zeichenweise (`-` / `0` / `7`); das dritte Kästchen (`RST_T`) hat dafür ein Feld, das nur bei FT8 etwas ausgibt.

Alle Zeilen haben eine feste Höhe, damit Position und Raster über alle Karten gleich bleiben. Ändert sich `--pota-slots`, muss die Vorlage um entsprechende Zeilen erweitert werden.

## Word-Vorlage für Blanko-Karten

`QSL_Blanko.docx` druckt die komplette Rückseite auf eine unbedruckte Karte (5,5" × 3,5"), also Gestaltung und QSO-Daten in einem Durchgang. Sie nutzt dieselbe CSV wie `QSL_Seriendruck.docx` und ist rein schwarz/grau gehalten (Monochrom-Laserdrucker).

- **Oben links:** eigenes Rufzeichen (`EIGENES_CALL`, damit auch `S5/DA6MAX` stimmt), bewusst klein gehalten, damit beim Sortieren das Rufzeichen der Gegenstation ins Auge fällt. Darunter Name, Anschrift und die Daten des Heimat-QTH (Locator, DOK, CQ/ITU); diese stehen fest in der Vorlage.
- **Oben rechts:** `VIA` mit freiem Platz zum Eintragen eines QSL-Managers, darunter die Box `TO RADIO` mit `AN_RUFZEICHEN`.
- **QSO-Tabelle:** Datum als `JJJJ-MM-TT`, UTC, MHz, Band, Mode und Report. Der Report zeigt bei FT8 `-07 dB`, bei SSB `57`, sonst den Rohwert (z. B. `599`).
- **Unten links, Standort-Block (oben):** groß der `Locator` des Standorts, von dem das QSO gefahren wurde (`EIGENER_LOCATOR`, bei Portable-Betrieb also nicht das Heimat-QTH). Direkt darunter die Überschrift und `POTA_1` … `POTA_4`. Die Überschrift lautet „Portable - Parks on the Air“, wenn mindestens ein Park vorhanden ist; ohne POTA nur „Portable“, sofern der Locator nicht mit dem Heimat-Locator `JO40XX` beginnt; vom Heimat-QTH aus entfällt sie.
- **Unten links, Stations-Block (am unteren Rand):** Rig und Leistung in einer Zeile, darunter die Antenne, jeweils nur wenn vorhanden. Der freie Raum zwischen beiden Blöcken fängt die wechselnde Zahl der Parks auf.
- **Logo:** Das POTA-Logo steht oben in einer eigenen Spalte zwischen Adressblock und `VIA` und wird nur gedruckt, wenn `POTA_1` befüllt ist (Bild in einem Wenn-Feld, deshalb „mit Text in Zeile“ und nicht frei positioniert).
- **Unten rechts:** Box mit `PSE QSL` (bei `TNX_QSL` = `X` zusätzlich `TNX QSL`), „VY 73!“, `BEMERKUNG` und Unterschrift; darunter `QSL via «VERSAND»`.

Schrift ist „Avenir Next Condensed“ (auf dem Mac vorhanden); fehlt sie, ersetzt Word sie und die Spalten können knapp werden. Der Rand beträgt rundum etwa 5 mm, die Vorlage braucht also keinen randlosen Druck.

## Hinweis zu den Vorlagen

Die Word-Vorlagen in diesem Repo enthalten Musterdaten (`Max Mustermann`, `DL9XX`, `JO40XX`, `DOK X00`).
Vor dem ersten Druck die eigenen Stationsdaten eintragen und die Vorlage über
*Sendungen → Empfänger auswählen* mit der eigenen CSV verbinden. In `QSL_Blanko.docx` steckt der
Heimat-Locator zusätzlich in der Bedingung für die Überschrift „Portable“ (Wenn-Feld unten links,
mit Alt+F9 sichtbar); dort ebenfalls `JO40XX` durch den eigenen Locator ersetzen.

## Sortierung

Die Reihenfolge richtet sich nach dem Versandweg `QSL_SENT_VIA`, sodass Bureau- und Direct-Karten im selben ADIF bleiben können:

1. **Bureau (`B`)** zuerst, in der Reihenfolge, die das DARC-QSL-Büro verlangt: nach Haupt-Prefix gebündelt, innerhalb einer Gruppe nach Rufzeichen (dann Datum/Uhrzeit).
2. **Direct (`D`)**, nach Datum und Uhrzeit.
3. **Alles andere** (`E`, `M`, leer), ebenfalls nach Datum und Uhrzeit. Fehlt `QSL_SENT_VIA` komplett (z. B. bei manchen CSV-Exporten), gilt also weiterhin die reine Zeitsortierung.

### DARC-Reihenfolge für Bureau-Karten

Grundlage ist die [Prefix-Liste des DARC-QSL-Büros](https://www.darc.de/geschaeftsstelle/qsl-buero/) (Stand 4/18, Spalte „Zusammenfassen mit“). Sie ist als Tabelle im Script (`DARC_PREFIXLISTE`) hinterlegt.

- Die Gruppen sind nach Haupt-Prefix sortiert (Ziffern vor Buchstaben), z. B. `DL`, `F`, `JA`, `OE`, `SP`, `W1` … `W9`.
- **Deutschland** (`DA` bis `DR`) gehört zur Gruppe `DL` und wird nach Rufzeichen und damit nach Prefix sortiert.
- **USA** werden nach der Zahl im Rufzeichen gruppiert (`W0` … `W9`). Die 4 ist geteilt: zwei Buchstaben vor der 4 (`AA4`, `KA4`, `WA4`) ergeben `WA4`, sonst `W4`.
- **Portable-Rufzeichen** zählen nach dem Heimatrufzeichen: `LA/DA6MAX/P` → `DL`.
- Ist ein Prefix nicht in der Liste, steht die Karte am Ende der Bureau-Karten und das Script warnt.

Die Liste ist von 2018 und laut DARC ohne Gewähr. Neue oder geänderte Prefixe müssen bei Bedarf in `DARC_PREFIXLISTE` nachgetragen werden.

## Ausgabeformat

- Alle Felder in Anführungszeichen
- UTF-8 mit BOM, damit Word und Excel Umlaute korrekt öffnen

## Hinweis zu Daten

CSV-Dateien sind per `.gitignore` von der Versionierung ausgeschlossen, da Exporte Rufzeichen und Kommentare Dritter enthalten.
