"""
qsl_convert.py
==============
Konvertiert den Wavelog-QSL-Export (CSV oder ADIF) in ein serienbrieftaugliches CSV.

Transformationen:
  - FREQ (Hz)  →  FREQUENZ (MHz, z. B. 21.230)
  - DATE_ON    →  DATUM_T / DATUM_M / DATUM_J
  - TIME_ON    →  UTC_ZEIT  (nur HH:MM)
  - RST_SENT bei FT8  →  RST_SENT_FT8  (z. B. "-12 dB") und RST_R / RST_S / RST_T
                       als Vorzeichen / Zehner / Einer ("-", "1", "2") für die drei RST-Kästchen
  - RST_SENT bei SSB  →  RST_R / RST_S / RST_T  (aus "59" oder "599")
  - MODE       →  BETRIEBSART (unverändert)
  - CALL       →  AN_RUFZEICHEN
  - COMMENT    →  BEMERKUNG
  - QSL_RCVD  →  TNX_QSL  ("X" wenn = "Y" oder "V", sonst leer)
  - PSE_QSL    immer "X"  (da alle Karten zum Bestätigen verschickt werden)
  - TX_PWR          →  LEISTUNG_W      (Sendeleistung in Watt)
  - MY_GRIDSQUARE   →  EIGENER_LOCATOR (eigener Locator des QSOs)
  - MY_POTA_REF     →  POTA_REF        (ggf. mehrere, kommagetrennt)
  - POTA_REF        →  POTA_NAME       (Parkname(n) über die POTA-API, " / "-getrennt)
  - POTA_ANZAHL, POTA_1 … POTA_4  (feste Slots "DE-0021 – Parkname", leer wenn unbelegt;
                       für Word-Serienbriefe, die keine Schleifen kennen)
  - COMMENT         →  ANTENNE / RIG / SETUP ("Rig · Antenne") / BEMERKUNG
                       ("[antenna] … [rig] …" wird aus dem Kommentar gelöst,
                        der Rest bleibt in BEMERKUNG)

Eingabe: Wavelog-QSL-Export als CSV oder ADIF (.adi/.adif).

Sortierung (nach QSL_SENT_VIA):
  1. Bureau (B): in der Reihenfolge des DARC-QSL-Büros, also nach Haupt-Prefix gebündelt
                 (Prefix-Liste des DARC, Stand 4/18), innerhalb davon nach Rufzeichen
  2. Direct (D): nach Datum und Uhrzeit
  3. alles andere (E, M, leer): nach Datum und Uhrzeit
  - VERSAND     →  "BUREAU" / "DIRECT" / "ELECTRONIC" / "MANAGER" (aus QSL_SENT_VIA)
  - DARC_GRUPPE →  Haupt-Prefix, unter dem die Karte beim DARC-QSL-Büro gebündelt wird

Umschläge für Direct-Karten:
  Für alle QSOs mit QSL_SENT_VIA = D wird zusätzlich <eingabe>_umschlaege.csv geschrieben:
  die Postanschrift je QSO aus der QRZ.com-XML-Datenbank (braucht ein QRZ-XML-Abo; Zugangsdaten
  über QRZ_USERNAME/QRZ_PASSWORD oder interaktive Abfrage). Steht in QSL_VIA ein anderes Rufzeichen
  (QSL-Manager), wird dessen Adresse abgefragt. Format wie bisher adressen.csv (Semikolon), passend
  zur Umschlag-Vorlage; die Zeilen liegen in derselben Reihenfolge wie die Karten.

Verwendung:
  python3 qsl_convert.py qsl_export.csv [ausgabe.csv]
  python3 qsl_convert.py export.adi [ausgabe.csv] [--no-pota] [--pota-slots N]
                                    [--no-qrz] [--umschlaege DATEI] [--qrz-delay SEK]
"""

import argparse
import csv
import getpass
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

POTA_API = "https://api.pota.app/park/{}"
POTA_SLOTS = 4      # Anzahl fester Spalten POTA_1 … POTA_n (muss zur Word-Vorlage passen)


def freq_mhz(hz_str: str) -> str:
    """21230000 → '21.230'"""
    try:
        hz = float(hz_str)
        mhz = hz / 1_000_000
        # 3 Nachkommastellen (kHz-Genauigkeit)
        return f"{mhz:.3f}"
    except ValueError:
        return hz_str


def split_date(date_str: str):
    """'2026-04-14' → ('14', '04', '2026')"""
    try:
        y, m, d = date_str.split("-")
        return d, m, y
    except Exception:
        return date_str, "", ""


def time_hhmm(time_str: str) -> str:
    """'18:00:45' → '1800'"""
    try:
        parts = time_str.split(":")
        return parts[0] + parts[1]
    except Exception:
        return time_str


def split_rst_ssb(rst: str):
    """
    '59'  → R='5', S='9', T='9'   (Telefonie: T immer 9)
    '599' → R='5', S='9', T='9'
    '56'  → R='5', S='6', T='9'
    """
    rst = rst.strip()
    if len(rst) >= 3:
        return rst[0], rst[1], rst[2]
    elif len(rst) == 2:
        return rst[0], rst[1], "9"   # T bei Phone per Konvention 9
    else:
        return rst, "", "9"


def split_ft8(rst: str):
    """
    '-12' → ('-', '1', '2'),  '+6' → ('+', '0', '6'),  '-7' → ('-', '0', '7')
    Ein FT8-Report hat Vorzeichen + zwei Ziffern = genau drei Zeichen für die RST-Kästchen.
    Nicht passende Werte ergeben leere Kästchen (die Textzeile bleibt als Fallback).
    """
    m = re.fullmatch(r"([+-]?)(\d{1,2})", rst.strip())
    if not m:
        return "", "", ""
    digits = m.group(2).zfill(2)
    return m.group(1) or "+", digits[0], digits[1]


def rst_ft8(rst: str) -> str:
    """'-12' → '-12 dB',  '+06' → '+06 dB'"""
    rst = rst.strip()
    # Sicherstellen, dass + oder - vorhanden
    if rst and rst[0] not in ("+", "-"):
        rst = "+" + rst
    return f"{rst} dB"


# --- DARC-Sortierung ---------------------------------------------------------

# Quelle: DARC e. V., "Prefix-Liste" für QSL-Manager, Stand 4/18, Spalte "Zusammenfassen mit".
# Format: Prefix[-Prefix]:Haupt-Prefix. "*" = USA (nach Zahl, siehe darc_group).
DARC_PREFIXLISTE = """
0T:TI 1A:I 1B:1B 1C:UA 1K:1K 1P:1P 1S:9M 1X:UA 1Z:XZ 2A-2Z:G 3A:3A
3B6-3B7:3B 3B8:3B 3B9:3B 3C:3C 3D0:3D0 3D2:3D0 3D2C:3D0 3D2R:3D0 3D6:3D6
3DA:3D6 3E-3F:HP 3G:CE 3H-3U:BY 3V:3V fasst:gibt! 3W:XV 3X:3C 3Y:LA 3Z:SP
4A-4C:XE 4D-4I:DU 4J-4K:4J 4L:4L 4M:YV 4P-4S:4S 4T:OA 4U:HB9 4U1SCO:F
4U1U:W2 4U1VIC:OE 4U1WB:W2 4U1YK:YK 4U48:W2 4U49:W2 4U5U:W2 4V:HH 4W:4W
4X-4Z:4X 5A:5A 5B:5B 5C-5G:CN 5H-5I:5H 5J-5K:HK 5L-5M:EL 5N-5O:5N 5P-5Q:OZ
5R-5S:5R 5T:5T 5U:5U 5V:5V 5W:5W 5X:5X 5Y-5Z:5Z 6A-6B:SU 6C:YK 6D-6J:XE
6K-6N:HL 6O:T5 6P-6S:AP 6T-6U:ST 6V-6W:6W 6X:5R 6Y:6Y 6Z:EL 7A-7I:YB
7J-7N:JA 7O:7O 7P:7P 7Q:7Q 7R:7X 7S:SM 7T-7Y:7X 7Z:HZ 8A-8I:YB 8J-8N:JA
8O:A2 8P:8P 8Q:8Q 8R:8R 8S:SM 8T-8Y:VU 8Z:HZ 9A:9A 9B-9D:EP 9E-9F:ET 9G:9G
9H:9H 9I-9J:9J 9K:9K 9L:9L 9M:9M 9N:9N 9O-9T:9Q 9U:9U 9V:9V 9W:9M 9X:9X
9Y-9Z:9Y A1:A1 A2:A2 A3:A3 A4:A4 A5:A5 A6:A6 A7:A7 A8:EL A9:A9 AA-AL:*
AH0:W0 AH1:W1 AH2:KH2 AH3:W3 AH4:WA4 AH5:W5 AH6:KH6 AH7:KH6 AH8:W8 AH9:W9
AL7:KL7 AM:EA AM6:EA AM8:EA AM9:EA AN:EA AN6:EA AN8:EA AN9:EA AO:EA AO6:EA
AO8:EA AO9:EA AP-AS:AP AT-AW:VU AX:VK AY-AZ:LU B0-B9:BY BA-BL:BY BM-BQ:BV
BR-BT:BY BU-BX:BV BY-BZ:BY C2:C2 C3:C3 C4:5B C5:C5 C6:C6 C8-C9:C9 CA-CE:CE
CF-CK:VE CL-CM:CO CN:CN CO:CO CP:CP CQ-CT:CT CU:CT CV-CX:CX CY-CZ:VE
D2-D3:D2 D4:D4 D5:EL D6:D6 D7-D9:HL DA-DR:DL DS-DT:HL DU-DZ:DU E2:HS E3:E3
E4:E4 E51:E5 EA-EH:EA EI-EJ:EI EK:EK EL:EL EM-EO:UR EP-EQ:EP ER:ER ES:ES
ET:ET EU-EW:EU EX:EX EY:EY EZ:EZ F-FJ:F FK:FK FL-FN:F FO:FO FP-FX:F FY:FY
FZ:F G:G H2:5B H3:HP H4:H4 H5:ZS H6-H7:YN H8-H9:HP HA:HA HB0:HB HB:HB9
HC-HD:HC HE:HB9 HE0:HB HF:SP HG:HA HH:HH HI:HI HJ-HK:HK HL:HL HM:HM HN:YI
HO-HP:HP HQ-HR:HR HS:HS HT:YN HU:YS HV:HV HW-HY:F HZ:HZ I:I IS:I IT:I J2:J2
J3:J3 J4:SV J5:3C J6:J6 J7:J7 J8:J8 JA-JS:JA JT-JV:JT JW:LA JX:LA JY:JY
JZ:YB K:* KC6:W6 KG4:KG4 KG6:KH2 KH0:W0 KH1:W1 KH2:KH2 KH3:W3 KH4:WA4 KH5:W5
KH6:KH6 KH7:KH6 KH8:W8 KH9:W9 KL7-KL8:KL7 KP1:W1 KP2:NP2 KP3-KP4:KP4 KP5:W5
KV4:WA4 LA-LN:LA LO-LW:LU LX:LX LY:LY LZ:LZ M:G N:* NH0:W0 NH1:W1 NH2:KH2
NH3:W3 NH4:WA4 NH5:W5 NH6:KH6 NH7:KH6 NH8:W8 NH9:W9 NL7-NL8:KL7 NP1:W1
NP2:NP2 NP3-NP4:KP4 NP5:W5 OA-OC:OA OD:OD OE:OE OF-OJ:OH OK-OL:OK OM:OM
ON-OT:ON OU-OW:OZ OX:OZ OY:OY OZ:OZ P2:P2 P3:5B P4:P4 P5-P9:HM PA-PI:PA
PJ:PJ PK-PO:YB PP-PY:PY PZ:PZ S0:EA S2-S3:S2 S4:ZS S5:S5 S6:9V S7:S7 S8:ZS
S9:S9 SA-SM:SM SN-SR:SP SS:SU ST:ST SU:SU SV-SZ:SV T0:T0 T2:T2 T3:T3 T4:CO
T5:T5 T6:YA T7:T7 T8:W6 T9:E7 TA-TC:TA TD:TG TE:TI TF:TF TG:TG TH:F TI:TI
TJ:TJ TK:F TL:TL TM:F TN:TN TO-TQ:F TR:TR TS:3V TT:TT TU:TU TV-TX:F TY:TY
TZ:TZ UA-UI:UA UJ-UM:UK UN-UQ:UN UR-UZ:UR V2:V2 V3:V3 V4:V4 V5:V5 V6:V6
V7:V7 V8:V8 VA-VG:VE VH-VN:VK VO:VE VP2E:VP2 VP2M:VP2 VP2V:VP2 VP3:VP3
VP5:VP5 VP6D:VP6 VP8:VP8 VP9:VP9 VQ9:VQ9 VR2:VS6 VR6:VR6 VS6:VS6 VT-VW:VU
VX-VY:VE VZ:VK W:* WH0:W0 WH1:W1 WH2:KH2 WH3:W3 WH4:WA4 WH5:W5 WH6:KH6
WH7:KH6 WH8:W8 WH9:W9 WL7-WL8:KL7 WP1:W1 WP2:NP2 WP3-WP4:KP4 WP5:W5 XA-XI:XE
XJ-XO:VE XP:OZ XQ-XR:CE XT:XT XU:XU XV:XV XW:XW XX:CT XX9:XX9 XY-XZ:XZ YA:YA
YB-YH:YB YI:YI YJ:YJ YK:YK YL:YL YM:TA YN:YN YO-YR:YO YS:YS YV-YY:YV YZ:YU
Z2:Z2 Z3:Z3 Z8:Z8 ZA:ZA ZB:ZB ZC4:ZC4 ZD7:ZD7 ZD8:ZD8 ZD9:ZD9 ZF:ZF ZG:ZB
ZK1:ZK1 ZK2:ZK2 ZK3:ZK3 ZK-ZM:ZL ZP:ZP ZR-ZU:ZS ZV-ZZ:PY 4N:YU 4O:4O E7:E7
R:UA YT:YU YU:YU Z6:Z6
"""


def _expand_prefix(spec: str) -> list[str]:
    """'3H-3U' → ['3H', …, '3U'],  'F-FJ' → ['F', 'FA', …, 'FJ'],  'JA' → ['JA']"""
    if "-" not in spec:
        return [spec]
    lo, hi = spec.split("-")
    if len(lo) == len(hi) and lo[:-1] == hi[:-1]:
        return [lo[:-1] + chr(c) for c in range(ord(lo[-1]), ord(hi[-1]) + 1)]
    if len(hi) == len(lo) + 1 and hi.startswith(lo):
        return [lo] + [lo + chr(c) for c in range(ord("A"), ord(hi[-1]) + 1)]
    return [lo, hi]


DARC_PREFIXE: dict[str, str] = {}
for _tok in DARC_PREFIXLISTE.split():
    _spec, _main = _tok.split(":")
    for _prefix in _expand_prefix(_spec):
        DARC_PREFIXE[_prefix] = _main

# Zusätze hinter/vor dem Rufzeichen, die nicht zum Heimatrufzeichen gehören
CALL_SUFFIXES = {"P", "M", "MM", "AM", "QRP", "QRPP", "A", "LH", "LGT", "T", "R"}


def home_call(call: str) -> str:
    """'LA/DA6MAX/P' → 'DA6MAX' (QSL-Büros vermitteln nach dem Heimatrufzeichen)."""
    parts = [p for p in call.upper().strip().split("/")
             if p and p not in CALL_SUFFIXES and not p.isdigit()]
    return max(parts, key=len) if parts else call.upper().strip()


def darc_group(call: str) -> str:
    """
    Haupt-Prefix, unter dem das DARC-QSL-Büro die Karte gebündelt haben will, z. B.
    'DO5PY' → 'DL', 'JA2HYD' → 'JA', 'W1OW' → 'W1'. Unbekannte Prefixe ergeben ''.
    USA: nach Zahl im Rufzeichen (W0 … W9); die 4 wird geteilt: zwei Buchstaben vor der 4
    (z. B. AA4, KA4, WA4) → 'WA4', sonst 'W4'.
    """
    c = home_call(call)
    main = None
    for k in range(min(5, len(c)), 0, -1):
        main = DARC_PREFIXE.get(c[:k])
        if main is not None:
            break
    if main is None:
        return ""
    if main != "*":
        return main
    m = re.match(r"([A-Z]+)(\d)", c)
    if not m:
        return "W"
    letters, digit = m.groups()
    return "WA4" if digit == "4" and len(letters) == 2 else f"W{digit}"


ROUTES = {"B": "BUREAU", "D": "DIRECT", "E": "ELECTRONIC", "M": "MANAGER"}


def sort_key(r: dict):
    """Bureau zuerst (DARC-Reihenfolge), dann Direct, dann Rest; jeweils Datum/Uhrzeit als Abschluss."""
    route = r.get("QSL_SENT_VIA", "").strip().upper()
    when = (r.get("DATE_ON", ""), r.get("TIME_ON", ""))
    if route == "B":
        call = home_call(r.get("CALL", ""))
        return (0, darc_group(call) or "~", call) + when
    return (1 if route == "D" else 2, "", "") + when


# --- ADIF-Eingabe -----------------------------------------------------------

ADIF_TAG = re.compile(rb"<([A-Za-z0-9_]+)(?::(\d+)(?::[^>]*)?)?>")


def parse_adif(path: str) -> list[dict]:
    """
    Liest eine ADIF-Datei (.adi) und liefert pro QSO ein Dict {FELDNAME: Wert}.
    Die Feldlänge in <FELD:n> zählt Bytes (so schreibt Wavelog sie), daher wird
    binär geparst und erst der einzelne Wert als UTF-8 dekodiert.
    """
    data = Path(path).read_bytes()
    eoh = re.search(rb"<eoh>", data, re.I)
    pos = eoh.end() if eoh else 0

    records, rec = [], {}
    while True:
        m = ADIF_TAG.search(data, pos)
        if not m:
            break
        name = m.group(1).decode("ascii").upper()
        if name == "EOR":
            if rec:
                records.append(rec)
            rec = {}
            pos = m.end()
        elif m.group(2) is not None:
            end = m.end() + int(m.group(2))
            rec[name] = data[m.end():end].decode("utf-8", errors="replace")
            pos = end
        else:
            pos = m.end()
    if rec:
        records.append(rec)
    return records


def adif_to_row(rec: dict) -> dict:
    """ADIF-Record auf das Schema des CSV-Exports abbilden (ISO-Datum, Hz, ENTITY)."""
    row = dict(rec)

    d = rec.get("QSO_DATE", "").strip()
    row["DATE_ON"] = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d

    t = rec.get("TIME_ON", "").strip()
    if len(t) == 4:                      # HHMM → HHMMSS
        t += "00"
    row["TIME_ON"] = f"{t[:2]}:{t[2:4]}:{t[4:6]}" if len(t) == 6 else t

    # ADIF-FREQ ist in MHz, der CSV-Export liefert Hz
    try:
        row["FREQ"] = str(round(float(rec.get("FREQ", "")) * 1_000_000))
    except ValueError:
        row["FREQ"] = rec.get("FREQ", "")

    row["ENTITY"] = rec.get("COUNTRY", "")
    return row


def is_adif(path: str) -> bool:
    if Path(path).suffix.lower() in (".adi", ".adif"):
        return True
    with open(path, "rb") as f:
        head = f.read(65536).lower()
    return b"<eoh>" in head or b"<eor>" in head


def read_rows(path: str) -> list[dict]:
    if is_adif(path):
        return [adif_to_row(r) for r in parse_adif(path)]
    with open(path, newline="", encoding="utf-8") as fin:
        return list(csv.DictReader(fin))


# --- Zusatzfelder -----------------------------------------------------------

COMMENT_TAG = re.compile(r"\[(antenna|rig)\]", re.I)


def split_comment(comment: str):
    """
    '[antenna] Vertical Dipole [rig] Yaesu FT-891' → ('', 'Vertical Dipole', 'Yaesu FT-891')
    Text vor dem ersten Tag bleibt als Bemerkung übrig.
    """
    parts = COMMENT_TAG.split(comment)   # [text, tag, wert, tag, wert, ...]
    rest = parts[0].strip()
    found = {tag.lower(): val.strip() for tag, val in zip(parts[1::2], parts[2::2])}
    return rest, found.get("antenna", ""), found.get("rig", "")


def fmt_power(pwr: str) -> str:
    """'100' → '100',  '5.0' → '5',  '0.5' → '0.5'"""
    pwr = pwr.strip()
    try:
        val = float(pwr)
    except ValueError:
        return pwr
    return str(int(val)) if val == int(val) else str(val)


def split_pota_refs(refs: str) -> list[str]:
    """'DE-0021, DE-0200' → ['DE-0021', 'DE-0200']  (ohne Duplikate, Reihenfolge bleibt)"""
    seen = []
    for ref in re.split(r"[,;\s]+", refs.strip().upper()):
        if ref and ref not in seen:
            seen.append(ref)
    return seen


_pota_cache: dict[str, str] = {}


def pota_name(ref: str) -> str:
    """
    Parkname zu einer POTA-Referenz über api.pota.app (pro Lauf gecacht).
    Wie auf pota.app wird der Parktyp angehängt: 'Wetterau' → 'Wetterau Bird Sanctuary'.
    """
    if ref in _pota_cache:
        return _pota_cache[ref]
    name = ""
    try:
        req = urllib.request.Request(POTA_API.format(ref), headers={"User-Agent": "qsl_convert"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            park = json.load(resp)
        if park:
            name = park.get("name", "") or ""
            ptype = park.get("parktypeDesc", "") or ""
            if name and ptype and not name.lower().endswith(ptype.lower()):
                name = f"{name} {ptype}"
        else:
            print(f"  ! POTA-Referenz {ref} nicht gefunden", file=sys.stderr)
    except (OSError, ValueError) as e:      # Netzwerk, HTTP-Fehler, Timeout, ungültiges JSON
        print(f"  ! POTA-Abfrage für {ref} fehlgeschlagen: {e}", file=sys.stderr)
    _pota_cache[ref] = name
    return name


# --- Umschlag-Adressen (QRZ.com) --------------------------------------------

QRZ_API_URL = "https://xmldata.qrz.com/xml/current/"
QRZ_NS = "{http://xmldata.qrz.com}"
QRZ_AGENT = "qsl-convert/1.0"

# Manche macOS-Python-Installationen (python.org-Installer) haben keine Root-Zertifikate.
# Ist certifi installiert, nutzen wir dessen Liste, sonst den System-Standard.
try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

SSL_HELP_TEXT = (
    "SSL-Zertifikatsproblem - das liegt an der lokalen Python-Installation (typisch bei macOS), "
    "nicht an QRZ oder den Zugangsdaten. Abhilfe: 'pip3 install --upgrade certifi' bzw. bei einer "
    "python.org-Installation 'Install Certificates.command' unter Programme > Python 3.x ausführen."
)

# Spaltenformat wie bisher adressen.csv (passt zur Umschlag-Vorlage umschlaege.docx)
UMSCHLAG_FELDER = [
    "Rufzeichen", "Via_Rufzeichen", "QRZ_Rufzeichen", "Datum", "Band",
    "Vorname", "Nachname", "Adresse", "Ort", "Bundesland", "PLZ", "Land", "Status",
]

# Ein Token, das wie ein Rufzeichen aussieht: 3-8 Zeichen, mindestens eine Ziffer, mindestens zwei Buchstaben
CALL_TOKEN_RE = re.compile(r"^(?=[A-Z0-9]{3,8}$)(?=.*[0-9])(?=(?:.*[A-Z]){2,})[A-Z0-9]+$")
VIA_STOPWORDS = {
    "QSL", "EQSL", "LOTW", "BURO", "QRZ", "HRDLOG", "WWW", "COM", "NET", "ORG", "CARD", "ONLY",
    "DIRECT", "PAPER", "MGR", "MANAGER", "SVP", "VIA", "CC", "NO", "NOT", "100W", "50W",
}


def extract_via_callsign(via_text: str):
    """
    Sucht im QSL_VIA-Freitext ein eingebettetes Rufzeichen, z. B. 'LY2QT' oder
    'QSL VIA ONLY KU9C - I WILL NOT ACCEPT …' → 'KU9C'. Reine Hinweise wie
    'NO BURO, DIRECT only!' ergeben None. Ein Token direkt hinter 'VIA' hat Vorrang.
    """
    if not via_text:
        return None
    tokens = re.findall(r"[A-Z0-9]+(?:/[A-Z0-9]+)?", via_text.upper())
    candidates = []
    for i, tok in enumerate(tokens):
        base = tok.split("/")[0]
        if CALL_TOKEN_RE.match(base) and base not in VIA_STOPWORDS:
            candidates.append((i > 0 and tokens[i - 1] == "VIA", tok))
    if not candidates:
        return None
    candidates.sort(key=lambda c: not c[0])
    return candidates[0][1]


def determine_lookup(row: dict):
    """
    Rufzeichen für die QRZ-Abfrage: steht in QSL_VIA ein ANDERES Rufzeichen als das des
    Funkpartners, hat es Vorrang (QSL-Manager). Rückgabe: (lookup_call, original_call, via_call|None)
    """
    call = row.get("CALL", "").strip().upper()
    via_call = extract_via_callsign(row.get("QSL_VIA", ""))
    if via_call and home_call(via_call) == home_call(call):
        via_call = None
    return home_call(via_call or call), call, via_call


class QRZError(Exception):
    pass


class QRZClient:
    """Minimaler Client für die QRZ.com-XML-Datenbank (Login + Callsign-Abfrage)."""

    def __init__(self, username: str, password: str):
        self.username, self.password = username, password
        self.session_key = None

    def _request(self, params: dict):
        url = QRZ_API_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": QRZ_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15, context=_SSL_CONTEXT) as resp:
                data = resp.read()
        except OSError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                raise QRZError(SSL_HELP_TEXT)
            raise QRZError(f"Netzwerkfehler bei der QRZ-Anfrage: {e}")
        try:
            return ET.fromstring(data)
        except ET.ParseError as e:
            raise QRZError(f"Antwort von QRZ konnte nicht gelesen werden: {e}")

    def _login(self):
        root = self._request({"username": self.username, "password": self.password,
                              "agent": QRZ_AGENT})
        session = root.find(f"{QRZ_NS}Session")
        if session is None:
            raise QRZError("Unerwartete QRZ-Antwort beim Login.")
        err = session.findtext(f"{QRZ_NS}Error")
        if err:
            raise QRZError(f"QRZ-Login fehlgeschlagen: {err}")
        self.session_key = session.findtext(f"{QRZ_NS}Key")
        if not self.session_key:
            raise QRZError("Kein Session-Key von QRZ erhalten (Abo aktiv?).")

    def lookup(self, callsign: str, _retry: bool = True):
        """→ (daten_dict, None) oder (None, fehlertext); 'nicht gefunden' ist kein Programmfehler."""
        if not self.session_key:
            self._login()
        root = self._request({"s": self.session_key, "callsign": callsign})
        session = root.find(f"{QRZ_NS}Session")
        err = session.findtext(f"{QRZ_NS}Error") if session is not None else None
        if err:
            if _retry and any(w in err.lower() for w in ("session", "timeout", "invalid")):
                self.session_key = None
                return self.lookup(callsign, _retry=False)
            return None, err
        cs = root.find(f"{QRZ_NS}Callsign")
        if cs is None:
            return None, "Keine Daten gefunden"
        return {c.tag.replace(QRZ_NS, ""): (c.text or "").strip() for c in cs}, None


def address_row(lookup_call, call, via_call, datum, band, data, error) -> dict:
    row = {"Rufzeichen": call, "Via_Rufzeichen": via_call or "", "QRZ_Rufzeichen": lookup_call,
           "Datum": datum, "Band": band}
    if data is None:
        row.update({k: "" for k in ("Vorname", "Nachname", "Adresse", "Ort", "Bundesland", "PLZ", "Land")})
        row["Status"] = f"NICHT GEFUNDEN ({error})" if error else "NICHT GEFUNDEN"
        return row
    row.update({"Vorname": data.get("fname", ""), "Nachname": data.get("name", ""),
                "Adresse": data.get("addr1", ""), "Ort": data.get("addr2", ""),
                "Bundesland": data.get("state", ""), "PLZ": data.get("zip", ""),
                "Land": data.get("country", "")})
    row["Status"] = "OK" if data.get("addr1") or data.get("addr2") else "OHNE ADRESSE BEI QRZ"
    return row


def build_address_rows(direct_rows: list, client, delay: float = 1.0) -> list[dict]:
    """
    Pro Direct-QSO genau eine Zeile (Reihenfolge wie die Karten, nichts wird zusammengefasst).
    Jedes Ziel-Rufzeichen wird nur einmal bei QRZ abgefragt.
    """
    targets = [(*determine_lookup(r), r.get("DATE_ON", "").replace("-", ""), r.get("BAND", "").strip())
               for r in direct_rows]
    unique = list(dict.fromkeys(t[0] for t in targets))
    print(f"  {len(unique)} eindeutige Rufzeichen werden bei QRZ abgefragt")

    cache, aborted, failures = {}, False, 0
    for idx, call in enumerate(unique, start=1):
        print(f"  [{idx}/{len(unique)}] QRZ: {call} ...", end=" ", flush=True)
        try:
            data, err = client.lookup(call)
        except QRZError as e:
            print(f"FEHLER: {e}")
            cache[call] = (None, str(e))
            failures += 1
            if "login" in str(e).lower() or "abo" in str(e).lower() or failures >= 2:
                print("  ! Abbruch der Abfragen (Login-/Abo- oder Verbindungsproblem)")
                aborted = True
                break
            time.sleep(delay)
            continue
        failures = 0
        print("keine Adresse (" + str(err) + ")" if data is None
              else "OK" if data.get("addr1") or data.get("addr2") else "ohne Adresse")
        cache[call] = (data, err)
        time.sleep(delay)

    fallback = (None, "nicht abgefragt (Abbruch)" if aborted else "unbekannter Fehler")
    return [address_row(lc, call, via, datum, band, *cache.get(lc, fallback))
            for lc, call, via, datum, band in targets]


def write_umschlaege(rows: list[dict], path: str):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=UMSCHLAG_FELDER, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def qrz_credentials(rows: list):
    """Zugangsdaten aus QRZ_USERNAME/QRZ_PASSWORD, sonst interaktiv (nur im Terminal). Nie gespeichert."""
    user, pw = os.environ.get("QRZ_USERNAME"), os.environ.get("QRZ_PASSWORD")
    if not (user and pw) and sys.stdin.isatty():
        default = next((r.get("STATION_CALLSIGN", "").strip().upper()
                        for r in rows if r.get("STATION_CALLSIGN")), "")
        user = user or input(f"  QRZ.com Benutzername [{default}]: ").strip() or default
        pw = pw or getpass.getpass("  QRZ.com Passwort (leer = überspringen): ")
    return (user, pw) if user and pw else None


def make_umschlaege(rows: list, path: str, delay: float = 1.0):
    direct = [r for r in rows if r.get("QSL_SENT_VIA", "").strip().upper() == "D"
              and r.get("CALL", "").strip()]
    if not direct:
        return
    print(f"\n{len(direct)} Direct-Karten → Umschlag-Adressen")
    creds = qrz_credentials(rows)
    if not creds:
        print("  ! Keine QRZ-Zugangsdaten (QRZ_USERNAME/QRZ_PASSWORD oder interaktiv im Terminal) "
              "– Umschlag-CSV übersprungen")
        return
    out = build_address_rows(direct, QRZClient(*creds), delay)
    write_umschlaege(out, path)
    n_ok = sum(1 for r in out if r["Status"] == "OK")
    print(f"✓ {n_ok} von {len(out)} Direct-Karten mit Adresse → {path}")
    if n_ok < len(out):
        print("  ! Ohne Adresse (Spalte Status prüfen): "
              + ", ".join(r["Rufzeichen"] for r in out if r["Status"] != "OK"))


# --- Konvertierung ----------------------------------------------------------

def convert(input_path: str, output_path: str, lookup_pota: bool = True,
            pota_slots: int = POTA_SLOTS, umschlaege_path: str | None = None,
            qrz_delay: float = 1.0):
    rows = read_rows(input_path)

    # Bureau (DARC-Reihenfolge) → Direct → Rest, siehe sort_key
    rows.sort(key=sort_key)

    out_rows = []
    for r in rows:
        mode = r.get("MODE", "").strip().upper()
        rst  = r.get("RST_SENT", "").strip()

        # Datum / Zeit
        d, m, y = split_date(r.get("DATE_ON", ""))
        utc = time_hhmm(r.get("TIME_ON", ""))

        # RST aufbereiten
        if mode == "FT8":
            rst_out = rst_ft8(rst)
            rst_r, rst_s, rst_t = split_ft8(rst)   # Vorzeichen / Zehner / Einer
        elif mode == "SSB":
            rst_r, rst_s, rst_t = split_rst_ssb(rst)
            rst_out = ""                         # Gesamtfeld leer bei SSB
        else:
            # Andere Moden: RST unverändert
            rst_r, rst_s, rst_t = split_rst_ssb(rst)
            rst_out = rst

        # QSL-Felder
        qsl_rcvd = r.get("QSL_RCVD", "").strip().upper()
        tnx_qsl  = "X" if qsl_rcvd in ("Y", "V") else ""

        # Kommentar → Bemerkung / Antenne / Rig
        bemerkung, antenne, rig = split_comment(r.get("COMMENT", "").strip())

        # POTA
        pota_refs = split_pota_refs(r.get("MY_POTA_REF", ""))
        pota_names = [pota_name(ref) if lookup_pota else "" for ref in pota_refs]
        pota_lines = [f"{ref} – {name}" if name else ref
                      for ref, name in zip(pota_refs, pota_names)]
        if len(pota_lines) > pota_slots:
            print(f"  ! {r.get('CALL', '?')} {r.get('DATE_ON', '')}: {len(pota_lines)} POTA-Referenzen, "
                  f"nur {pota_slots} Slots – überzählige entfallen in POTA_1…POTA_{pota_slots}",
                  file=sys.stderr)

        out_rows.append({
            # Rufzeichen
            "AN_RUFZEICHEN": r.get("CALL", "").strip(),
            # Eigenes Rufzeichen (für eventuelle spätere Nutzung)
            "EIGENES_CALL":  r.get("STATION_CALLSIGN", "").strip(),
            # QSL-Route
            "QSL_VIA":       r.get("QSL_VIA", "").strip(),
            # Datum
            "DATUM_T": d,
            "DATUM_M": m,
            "DATUM_J": y,
            # Zeit
            "UTC_ZEIT": utc,
            # Frequenz
            "FREQUENZ": freq_mhz(r.get("FREQ", "")),
            # Band
            "BAND": r.get("BAND", "").strip(),
            # Betriebsart
            "BETRIEBSART": mode,
            # RST – FT8 kombiniert
            "RST_SENT_FT8": rst_out,
            # RST – SSB getrennt
            "RST_R": rst_r,
            "RST_S": rst_s,
            "RST_T": rst_t,
            # QSL
            "PSE_QSL":  "X",           # immer, da wir Karten verschicken
            "TNX_QSL":  tnx_qsl,
            # Bemerkung (ohne [antenna]/[rig])
            "BEMERKUNG": bemerkung,
            # Locator Gegenstation
            "GRIDSQUARE": r.get("GRIDSQUARE", "").strip(),
            # DXCC-Entity
            "ENTITY": r.get("ENTITY", "").strip(),
            # Eigene Station
            "EIGENER_LOCATOR": r.get("MY_GRIDSQUARE", "").strip(),
            "LEISTUNG_W": fmt_power(r.get("TX_PWR", "")),
            "ANTENNE": antenne,
            "RIG": rig,
            "SETUP": " · ".join(x for x in (rig, antenne) if x),
            # POTA (mehrere Referenzen kommagetrennt, Namen in gleicher Reihenfolge)
            "POTA_REF": ", ".join(pota_refs),
            "POTA_NAME": " / ".join(n for n in pota_names if n),
            "POTA_ANZAHL": str(len(pota_refs)),
            # Versandweg und DARC-Bündelung
            "VERSAND": ROUTES.get(r.get("QSL_SENT_VIA", "").strip().upper(),
                                  r.get("QSL_SENT_VIA", "").strip()),
            "DARC_GRUPPE": darc_group(r.get("CALL", "")),
            # Feste Slots für den Serienbrief (leer, wenn nicht belegt)
            **{f"POTA_{i + 1}": pota_lines[i] if i < len(pota_lines) else ""
               for i in range(pota_slots)},
        })

    fieldnames = list(out_rows[0].keys()) if out_rows else []

    with open(output_path, "w", newline="", encoding="utf-8-sig") as fout:
        # utf-8-sig = UTF-8 mit BOM → Word/Excel öffnet Umlaute korrekt
        writer = csv.DictWriter(fout, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(out_rows)

    counts = {}
    for o in out_rows:
        counts[o["VERSAND"] or "ohne QSL_SENT_VIA"] = counts.get(o["VERSAND"] or "ohne QSL_SENT_VIA", 0) + 1
    for o in out_rows:
        if o["VERSAND"] == "BUREAU" and not o["DARC_GRUPPE"]:
            print(f"  ! {o['AN_RUFZEICHEN']}: Prefix nicht in der DARC-Liste – steht am Ende der Bureau-Karten",
                  file=sys.stderr)

    print(f"✓ {len(out_rows)} Einträge konvertiert → {output_path}")
    print("  Versand: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print(f"  Felder: {', '.join(fieldnames)}")

    if umschlaege_path:
        make_umschlaege(rows, umschlaege_path, qrz_delay)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Wavelog-QSL-Export (CSV/ADIF) → Seriendruck-CSV")
    ap.add_argument("input", nargs="?", default="qsl_export.csv", help="CSV- oder ADIF-Datei")
    ap.add_argument("output", nargs="?", help="Ausgabe-CSV (Standard: <eingabe>_seriendruck.csv)")
    ap.add_argument("--no-pota", action="store_true", help="POTA-Parknamen nicht über die API abfragen")
    ap.add_argument("--pota-slots", type=int, default=POTA_SLOTS, metavar="N",
                    help=f"Anzahl der Spalten POTA_1…POTA_N (Standard: {POTA_SLOTS})")
    ap.add_argument("--no-qrz", action="store_true",
                    help="keine Umschlag-Adressen für Direct-Karten bei QRZ.com abfragen")
    ap.add_argument("--umschlaege", metavar="DATEI",
                    help="Ausgabe für die Umschlag-CSV (Standard: <eingabe>_umschlaege.csv)")
    ap.add_argument("--qrz-delay", type=float, default=1.0, metavar="SEK",
                    help="Wartezeit zwischen QRZ-Abfragen (Standard: 1.0)")
    args = ap.parse_args()
    out = args.output or str(Path(args.input).stem + "_seriendruck.csv")
    umschlaege = None if args.no_qrz else (args.umschlaege or str(Path(args.input).stem + "_umschlaege.csv"))
    convert(args.input, out, lookup_pota=not args.no_pota, pota_slots=args.pota_slots,
            umschlaege_path=umschlaege, qrz_delay=args.qrz_delay)
