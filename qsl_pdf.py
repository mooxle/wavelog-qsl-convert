"""
qsl_pdf.py
==========
Erzeugt aus den Zeilen von qsl_convert.py ein druckfertiges PDF mit einer QSL-Karte pro Seite
(140 × 90 mm). Zwei Vorlagen: "blanko" (komplette Rückseite, Layout von QSL_Blanko.docx) und
"vordruck" (nur die QSO-Daten als Überdruck auf vorgedruckte Karten, Positionen von QSL_Seriendruck.docx). Nur Standardbibliothek: eigener kleiner PDF-Writer,
TrueType-Schriften werden vollständig eingebettet, das Logo (PNG) wird selbst dekodiert.

Die Stationsdaten (Name, Anschrift, Heimat-Locator, DOK, Zonen) kommen aus einer INI-Datei,
siehe qsl_station.example.ini.
"""

import configparser
import os
import shlex
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

MM = 72 / 25.4                    # Punkt pro Millimeter
PAGE_W, PAGE_H = 140 * MM, 90 * MM
TW = 1 / 20                       # Twips → Punkt (Layout ist aus der Word-Vorlage übernommen)

GRAY_TEXT, GRAY_FILL, GRAY_LINE = 0.35, 0.25, 0.25
LINE_W = 0.75

LAYOUTS = ("blanko", "vordruck")

# Standard-Schriften, in dieser Reihenfolge gesucht: (regulär, fett), jeweils "Pfad" oder "Pfad#Schnitt"
FONT_CANDIDATES_VORDRUCK = [
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
FONT_CANDIDATES = [
    ("/System/Library/Fonts/Avenir Next Condensed.ttc#Avenir Next Condensed Regular",
     "/System/Library/Fonts/Avenir Next Condensed.ttc#Avenir Next Condensed Bold"),
    ("/System/Library/Fonts/Supplemental/Arial Narrow.ttf",
     "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf"),
    ("C:/Windows/Fonts/ARIALN.TTF", "C:/Windows/Fonts/ARIALNB.TTF"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"),
]


class QslPdfError(Exception):
    pass


# --- Stationsdaten ---------------------------------------------------------------------------

def load_station(path: str) -> dict:
    """Liest die Stationsdaten. Pfade (Logo, Schriften) dürfen relativ zur INI-Datei sein."""
    p = Path(path).expanduser()
    if not p.is_file():
        example = Path(__file__).resolve().parent / "qsl_station.example.ini"
        if example.is_file() and p.parent.is_dir():
            shutil.copyfile(example, p)
            raise QslPdfError(f"Stationsdatei angelegt: {p} – bitte Name, Anschrift und Heimat-QTH "
                              f"eintragen und erneut starten.")
        raise QslPdfError(f"Stationsdatei nicht gefunden: {p} – Vorlage: qsl_station.example.ini")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(p, encoding="utf-8")
    st = dict(cp["station"]) if cp.has_section("station") else {}
    pdf = dict(cp["pdf"]) if cp.has_section("pdf") else {}

    def rel(value):
        if not value:
            return ""
        path_part, _, face = value.partition("#")
        q = Path(path_part).expanduser()
        if not q.is_absolute():
            q = p.parent / q
        return str(q) + (f"#{face}" if face else "")

    name = st.get("name", "").strip()
    return {
        "name": name,
        "address": [line.strip() for line in st.get("address", "").splitlines() if line.strip()],
        "home_locator": st.get("home_locator", "").strip().upper(),
        "dok": st.get("dok", "").strip(),
        "cq_zone": st.get("cq_zone", "").strip(),
        "itu_zone": st.get("itu_zone", "").strip(),
        "greeting": st.get("greeting", "").strip() or (name.split()[0] if name else ""),
        "font": rel(pdf.get("font", "").strip()),
        "font_bold": rel(pdf.get("font_bold", "").strip()),
        "logo": rel(pdf.get("logo", "").strip()),
        "rotate": int(pdf.get("rotate", "0").strip() or 0) % 360,
        "print_command": pdf.get("drucken", "").strip(),
        "layout": pdf.get("vorlage", "blanko").strip().lower() or "blanko",
    }


# --- TrueType ----------------------------------------------------------------------------------

class TTFont:
    """Minimaler TrueType-Leser: Glyphen-IDs, Breiten und Metriken; TTC-Schnitte werden extrahiert."""

    def __init__(self, spec: str):
        path, _, face = spec.partition("#")
        data = Path(path).read_bytes()
        offset = 0
        if data[:4] == b"ttcf":
            n = struct.unpack(">I", data[8:12])[0]
            offsets = struct.unpack(f">{n}I", data[12:12 + 4 * n])
            matches = [o for o in offsets if not face or self._full_name(data, o) == face]
            if not matches:
                raise QslPdfError(f"Schnitt '{face}' nicht in {path}")
            offset = matches[0]
        self.data = self._standalone(data, offset) if offset or data[:4] == b"ttcf" else data
        self.tables = self._tables(self.data, 0)

        head = self._t("head")
        self.upem = struct.unpack(">H", head[18:20])[0]
        self.bbox = struct.unpack(">hhhh", head[36:44])
        hhea = self._t("hhea")
        self.ascent, self.descent = struct.unpack(">hh", hhea[4:8])
        n_hmetrics = struct.unpack(">H", hhea[34:36])[0]
        hmtx = self._t("hmtx")
        self.advances = [struct.unpack(">H", hmtx[4 * i:4 * i + 2])[0] for i in range(n_hmetrics)]
        os2 = self._t("OS/2")
        self.cap_height = (struct.unpack(">h", os2[88:90])[0]
                           if os2 and len(os2) >= 90 and struct.unpack(">H", os2[0:2])[0] >= 2
                           else int(self.ascent * 0.7))
        self.ps_name = self._name(self.data, 0, 6).replace(" ", "") or "Font"
        self.cmap = self._cmap()

    # -- Tabellen
    @staticmethod
    def _tables(data, offset):
        num = struct.unpack(">H", data[offset + 4:offset + 6])[0]
        out = {}
        for i in range(num):
            tag, _, off, length = struct.unpack(">4sIII", data[offset + 12 + 16 * i:offset + 28 + 16 * i])
            out[tag.decode("latin-1")] = (off, length)
        return out

    def _t(self, tag):
        if tag not in self.tables:
            return b""
        off, length = self.tables[tag]
        return self.data[off:off + length]

    @classmethod
    def _standalone(cls, data, offset):
        """Macht aus einem Schnitt einer TTC-Datei eine eigenständige TTF-Datei."""
        num = struct.unpack(">H", data[offset + 4:offset + 6])[0]
        header = bytearray(data[offset:offset + 12])
        records = []
        for i in range(num):
            tag, csum, off, length = struct.unpack(">4sIII", data[offset + 12 + 16 * i:offset + 28 + 16 * i])
            records.append((tag, csum, data[off:off + length]))
        pos = 12 + 16 * num
        directory, body = bytearray(), bytearray()
        for tag, csum, blob in records:
            directory += struct.pack(">4sIII", tag, csum, pos + len(body), len(blob))
            body += blob + b"\0" * (-len(blob) % 4)
        return bytes(header + directory + body)

    @classmethod
    def _full_name(cls, data, offset):
        return cls._name(data, offset, 4)

    @classmethod
    def _name(cls, data, offset, name_id):
        tables = cls._tables(data, offset)
        if "name" not in tables:
            return ""
        off, _ = tables["name"]
        _, count, string_off = struct.unpack(">HHH", data[off:off + 6])
        fallback = ""
        for i in range(count):
            pid, _, _, nid, length, noff = struct.unpack(">HHHHHH", data[off + 6 + 12 * i:off + 18 + 12 * i])
            if nid != name_id:
                continue
            raw = data[off + string_off + noff:off + string_off + noff + length]
            if pid in (0, 3):
                return raw.decode("utf-16-be", errors="replace")
            fallback = fallback or raw.decode("latin-1")
        return fallback

    def _cmap(self):
        cmap = self._t("cmap")
        _, num = struct.unpack(">HH", cmap[0:4])
        subtables = {}
        for i in range(num):
            pid, eid, off = struct.unpack(">HHI", cmap[4 + 8 * i:12 + 8 * i])
            subtables[(pid, eid)] = off
        for key in ((3, 10), (0, 4), (3, 1), (0, 3)):
            if key in subtables:
                off = subtables[key]
                fmt = struct.unpack(">H", cmap[off:off + 2])[0]
                if fmt == 12:
                    return self._cmap12(cmap, off)
                if fmt == 4:
                    return self._cmap4(cmap, off)
        raise QslPdfError("Schrift ohne Unicode-cmap")

    @staticmethod
    def _cmap4(cmap, off):
        seg2 = struct.unpack(">H", cmap[off + 6:off + 8])[0]
        n = seg2 // 2
        ends = struct.unpack(f">{n}H", cmap[off + 14:off + 14 + seg2])
        starts = struct.unpack(f">{n}H", cmap[off + 16 + seg2:off + 16 + 2 * seg2])
        deltas = struct.unpack(f">{n}h", cmap[off + 16 + 2 * seg2:off + 16 + 3 * seg2])
        ro_pos = off + 16 + 3 * seg2
        range_offs = struct.unpack(f">{n}H", cmap[ro_pos:ro_pos + seg2])
        out = {}
        for i in range(n):
            for c in range(starts[i], ends[i] + 1):
                if c == 0xFFFF:
                    continue
                if range_offs[i] == 0:
                    g = (c + deltas[i]) & 0xFFFF
                else:
                    p = ro_pos + 2 * i + range_offs[i] + 2 * (c - starts[i])
                    g = struct.unpack(">H", cmap[p:p + 2])[0]
                    g = (g + deltas[i]) & 0xFFFF if g else 0
                if g:
                    out[c] = g
        return out

    @staticmethod
    def _cmap12(cmap, off):
        n = struct.unpack(">I", cmap[off + 12:off + 16])[0]
        out = {}
        for i in range(n):
            start, end, gid = struct.unpack(">III", cmap[off + 16 + 12 * i:off + 28 + 12 * i])
            for c in range(start, end + 1):
                out[c] = gid + c - start
        return out

    # -- Nutzung
    def gid(self, ch):
        return self.cmap.get(ord(ch)) or self.cmap.get(ord("?"), 0)

    def advance(self, gid):
        return self.advances[gid] if gid < len(self.advances) else self.advances[-1]

    def width(self, text, size):
        return sum(self.advance(self.gid(c)) for c in text) * size / self.upem


# --- PNG ---------------------------------------------------------------------------------------

def read_png(path):
    """→ (Breite, Höhe, Farbraum, Farbdaten, Alphadaten|None) für 8-Bit-PNGs ohne Interlacing."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise QslPdfError(f"Kein PNG: {path}")
    pos, idat, ihdr = 8, bytearray(), None
    while pos < len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", chunk)
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length
    w, h, depth, ctype, _, _, interlace = ihdr
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(ctype)
    if depth != 8 or channels is None or interlace:
        raise QslPdfError(f"Logo bitte als 8-Bit-PNG ohne Palette/Interlacing speichern: {path}")
    raw, stride, bpp = zlib.decompress(bytes(idat)), w * channels, channels
    out, prev, i = bytearray(), bytearray(stride), 0
    for _ in range(h):
        ft, line = raw[i], bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            if ft == 1:
                line[x] = (line[x] + a) & 255
            elif ft == 2:
                line[x] = (line[x] + b) & 255
            elif ft == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif ft == 4:
                c = prev[x - bpp] if x >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += line
        prev = line
    color_ch = 3 if ctype in (2, 6) else 1
    if ctype in (4, 6):
        color = bytearray()
        for px in range(w * h):
            color += out[px * channels:px * channels + color_ch]
        alpha = bytes(out[color_ch::channels])
        return w, h, ("DeviceRGB" if color_ch == 3 else "DeviceGray"), bytes(color), alpha
    return w, h, ("DeviceRGB" if color_ch == 3 else "DeviceGray"), bytes(out), None


# --- PDF-Writer --------------------------------------------------------------------------------

class PdfWriter:
    def __init__(self, rotate=0):
        self.rotate = rotate       # 0 = Querformat 140 × 90; 90/270 = Hochformat 90 × 140 (Inhalt gedreht)
        self.objects = []          # Index = Objektnummer - 1
        self.pages = []
        self.fonts = {}            # Name → (TTFont, {Glyph-ID: Zeichen})
        self.images = {}

    def reserve(self):
        self.objects.append(None)
        return len(self.objects)

    def put(self, num, body):
        self.objects[num - 1] = body

    def add(self, body):
        num = self.reserve()
        self.put(num, body)
        return num

    @staticmethod
    def stream(dict_body, data, compress=True):
        if compress:
            data = zlib.compress(data, 9)
            dict_body += " /Filter /FlateDecode"
        return f"<< {dict_body} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"

    def register_font(self, name, font):
        self.fonts[name] = (font, {})

    def register_image(self, name, path):
        w, h, cs, color, alpha = read_png(path)
        smask = ""
        if alpha:
            snum = self.add(self.stream(f"/Type /XObject /Subtype /Image /Width {w} /Height {h} "
                                        f"/ColorSpace /DeviceGray /BitsPerComponent 8", alpha))
            smask = f" /SMask {snum} 0 R"
        self.images[name] = self.add(self.stream(
            f"/Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /{cs} "
            f"/BitsPerComponent 8{smask}", color))

    def _write_font(self, font, used):
        scale = 1000 / font.upem
        ff = self.add(self.stream(f"/Length1 {len(font.data)}", font.data))
        bbox = " ".join(str(round(v * scale)) for v in font.bbox)
        desc = self.add(f"<< /Type /FontDescriptor /FontName /{font.ps_name} /Flags 32 /FontBBox [{bbox}] "
                        f"/ItalicAngle 0 /Ascent {round(font.ascent * scale)} "
                        f"/Descent {round(font.descent * scale)} /CapHeight {round(font.cap_height * scale)} "
                        f"/StemV 80 /FontFile2 {ff} 0 R >>".encode())
        widths = " ".join(f"{g} [{round(font.advance(g) * scale)}]" for g in sorted(used))
        cid = self.add(f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{font.ps_name} "
                       f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
                       f"/FontDescriptor {desc} 0 R /W [{widths}] /CIDToGIDMap /Identity >>".encode())
        # ToUnicode: macht den Text im PDF durchsuch- und kopierbar
        pairs = [f"<{g:04X}> <{ch.encode('utf-16-be').hex().upper()}>" for g, ch in sorted(used.items())]
        blocks = "".join(f"{len(chunk)} beginbfchar\n" + "\n".join(chunk) + "\nendbfchar\n"
                         for chunk in (pairs[i:i + 100] for i in range(0, len(pairs), 100)))
        cmap = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
                "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
                "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
                "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n" + blocks +
                "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n")
        tu = self.add(self.stream("", cmap.encode("ascii")))
        return self.add(f"<< /Type /Font /Subtype /Type0 /BaseFont /{font.ps_name} /Encoding /Identity-H "
                        f"/DescendantFonts [{cid} 0 R] /ToUnicode {tu} 0 R >>".encode())

    def save(self, path):
        font_refs = {name: self._write_font(f, used) for name, (f, used) in self.fonts.items()}
        resources = ("<< /Font << " + " ".join(f"/{n} {r} 0 R" for n, r in font_refs.items()) + " >> "
                     "/XObject << " + " ".join(f"/{n} {r} 0 R" for n, r in self.images.items()) + " >> >>")
        pages_num = self.reserve()
        kids = []
        if self.rotate == 90:
            box, prefix = (PAGE_H, PAGE_W), f"0 1 -1 0 {PAGE_H:.2f} 0 cm\n"
        elif self.rotate == 270:
            box, prefix = (PAGE_H, PAGE_W), f"0 -1 1 0 0 {PAGE_W:.2f} cm\n"
        else:
            box, prefix = (PAGE_W, PAGE_H), ""
        for content in self.pages:
            c = self.add(self.stream("", (prefix + content).encode("latin-1")))
            kids.append(self.add(f"<< /Type /Page /Parent {pages_num} 0 R "
                                 f"/MediaBox [0 0 {box[0]:.2f} {box[1]:.2f}] "
                                 f"/Resources {resources} /Contents {c} 0 R >>".encode()))
        self.put(pages_num, f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                            f"/Count {len(kids)} >>".encode())
        catalog = self.add(f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode())

        out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
        xref = []
        for i, body in enumerate(self.objects, start=1):
            xref.append(len(out))
            out += f"{i} 0 obj\n".encode() + (body if isinstance(body, bytes) else body.encode()) + b"\nendobj\n"
        start = len(out)
        out += f"xref\n0 {len(self.objects) + 1}\n0000000000 65535 f \n".encode()
        out += b"".join(f"{x:010d} 00000 n \n".encode() for x in xref)
        out += (f"trailer\n<< /Size {len(self.objects) + 1} /Root {catalog} 0 R >>\n"
                f"startxref\n{start}\n%%EOF\n").encode()
        Path(path).write_bytes(bytes(out))


class Page:
    """Zeichenfläche einer Karte. Koordinaten in Twips, Ursprung oben links (wie in Word)."""

    def __init__(self, pdf: PdfWriter):
        self.pdf, self.ops = pdf, []

    @staticmethod
    def _xy(x, y):
        return x * TW, PAGE_H - y * TW

    def rect(self, x, y, w, h, fill=None, stroke=None):
        px, py = self._xy(x, y + h)
        if fill is not None:
            self.ops.append(f"{fill:.3f} g {px:.2f} {py:.2f} {w * TW:.2f} {h * TW:.2f} re f")
        if stroke is not None:
            self.ops.append(f"{stroke:.3f} G {LINE_W} w {px:.2f} {py:.2f} {w * TW:.2f} {h * TW:.2f} re S")

    def image(self, name, x, y, w, h):
        px, py = self._xy(x, y + h)
        self.ops.append(f"q {w * TW:.2f} 0 0 {h * TW:.2f} {px:.2f} {py:.2f} cm /{name} Do Q")

    def width(self, runs):
        return sum(self.pdf.fonts[f][0].width(t, s) for t, f, s, _ in runs)

    def line(self, runs, x, top, height, w=None, align="left"):
        """
        Eine Textzeile aus Läufen (text, font, size, gray). Die Zeile wird in der Höhe 'height'
        um die Versalhöhe zentriert. Ist sie breiter als w, wird sie verkleinert (bis 65 %)
        und notfalls mit „…“ gekürzt.
        """
        runs = [r for r in runs if r[0]]
        if not runs:
            return
        if w is not None:
            natural = self.width(runs)
            if natural > w * TW:
                factor = max(0.65, w * TW / natural)
                runs = [(t, f, s * factor, g) for t, f, s, g in runs]
                while self.width(runs) > w * TW and len(runs[-1][0]) > 1:
                    t, f, s, g = runs[-1]
                    runs[-1] = (t[:-2].rstrip() + "…", f, s, g)
        total = self.width(runs) / TW
        if align == "center" and w is not None:
            x += (w - total) / 2
        elif align == "right" and w is not None:
            x += w - total
        main_font, main_size = runs[0][1], max(r[2] for r in runs)
        cap = self.pdf.fonts[main_font][0].cap_height / self.pdf.fonts[main_font][0].upem * main_size
        px, py = self._xy(x, top + height / 2)
        py -= cap / 2
        self.ops.append(f"BT {px:.2f} {py:.2f} Td")
        for text, font_name, size, gray in runs:
            font, used = self.pdf.fonts[font_name]
            gids = [font.gid(c) for c in text]
            used.update(zip(gids, text))
            hexs = "".join(f"{g:04X}" for g in gids)
            self.ops.append(f"{gray:.3f} g /{font_name} {size:.2f} Tf <{hexs}> Tj")
        self.ops.append("ET")

    def finish(self):
        self.pdf.pages.append("\n".join(self.ops))


# --- Kartenlayout (übernommen aus QSL_Blanko.docx, Maße in Twips) ------------------------------

X0, Y0 = 300, 300
COL_ADDR, COL_LOGO, GAP, COL_R = 2850, 1550, 150, 2770
X_LOGO = X0 + COL_ADDR
X_R = X0 + COL_ADDR + COL_LOGO + GAP
QSO_COLS = [("Date (Y-M-D)", 1900), ("UTC", 950), ("MHz", 1300), ("Band", 870), ("Mode", 1000),
            ("RST / SNR", 1300)]


def draw_card(page: Page, r: dict, st: dict, logo: bool):
    R, B = "R", "B"
    lab = lambda t: (t, R, 7, GRAY_TEXT)          # graue Beschriftung wie in der Word-Vorlage
    lab_b = lambda t: (t, B, 7, GRAY_TEXT)

    # Oben links: eigenes Rufzeichen, Anschrift, Heimat-QTH
    y = Y0
    page.line([(r["EIGENES_CALL"], B, 15, 0)], X0, y, 370, COL_ADDR)
    y += 370
    for addr in [st["name"]] + st["address"][:3]:
        page.line([(addr, R, 8, 0)], X0, y, 195, COL_ADDR)
        y += 195
    y += 70
    home = "  -  ".join(p for p in (st["home_locator"],
                                     f"DOK {st['dok']}" if st["dok"] else "",
                                     f"CQ {st['cq_zone']}" if st["cq_zone"] else "",
                                     f"ITU {st['itu_zone']}" if st["itu_zone"] else "") if p)
    if home:
        page.line([lab_b("Home QTH:  "), (home, R, 7, 0)], X0, y, 180, COL_ADDR)

    # Logo nur bei POTA
    if logo and r.get("POTA_1"):
        page.image("Logo", X_LOGO + 75, Y0 + 25, 1400, 1400)

    # Oben rechts: VIA und TO RADIO
    page.line([lab("VIA")], X_R + 60, Y0, 320)
    page.rect(X_R, Y0 + 430, COL_R, 1020, stroke=GRAY_LINE)
    page.line([lab("TO RADIO")], X_R + 60, Y0 + 430, 190)
    page.line([(r["AN_RUFZEICHEN"], B, 26, 0)], X_R + 60, Y0 + 430 + 190 + 60, 600, COL_R - 120, "center")

    # QSO-Tabelle
    y = Y0 + 1450 + 20
    page.line([lab_b("CONFIRMING OUR 2-WAY QSO")], X0, y, 230)
    y += 230
    report = r["RST_SENT_FT8"] or (r["RST_R"] + r["RST_S"])
    values = [f"{r['DATUM_J']}-{r['DATUM_M']}-{r['DATUM_T']}", r["UTC_ZEIT"], r["FREQUENZ"], r["BAND"],
              r["BETRIEBSART"], report]
    x = X0
    for (head, w), value in zip(QSO_COLS, values):
        page.rect(x, y, w, 250, fill=GRAY_FILL, stroke=GRAY_LINE)
        page.line([(head.upper(), B, 7, 1)], x + 40, y, 250, w - 80, "center")
        page.rect(x, y + 250, w, 640, stroke=GRAY_LINE)
        page.line([(value, B, 16, 0)], x + 60, y + 250, 640, w - 120, "center")
        x += w

    # Unten links: Standort-Block
    y = Y0 + 1450 + 20 + 230 + 250 + 640 + 140
    w_left = COL_ADDR + COL_LOGO
    if r["EIGENER_LOCATOR"]:
        page.line([("Locator:  ", B, 8, 0), (r["EIGENER_LOCATOR"], B, 11, 0)], X0, y, 280, w_left)
    if r.get("POTA_1"):
        heading = "PORTABLE  -  PARKS ON THE AIR"
    elif r["EIGENER_LOCATOR"] and st["home_locator"] and \
            not r["EIGENER_LOCATOR"].upper().startswith(st["home_locator"]):
        heading = "PORTABLE"
    else:
        heading = ""
    page.line([(heading, B, 7, 0)], X0, y + 280, 220, w_left)
    for i in range(1, 5):
        page.line([(r.get(f"POTA_{i}", ""), R, 7, 0)], X0, y + 500 + 170 * (i - 1), 170, w_left)

    # Unten links: Stations-Block am unteren Rand
    y_bottom = y + 260 + 940 + 480
    rig_line = []
    if r["RIG"]:
        rig_line += [("Rig:  ", B, 7, 0), (r["RIG"], R, 7, 0), ("      ", R, 7, 0)]
    if r["LEISTUNG_W"]:
        rig_line += [("Power:  ", B, 7, 0), (f"{r['LEISTUNG_W']} W", R, 7, 0)]
    page.line(rig_line, X0, y_bottom - 350, 175, w_left)
    if r["ANTENNE"]:
        page.line([("Antenna:  ", B, 7, 0), (r["ANTENNE"], R, 7, 0)], X0, y_bottom - 175, 175, w_left)

    # Unten rechts: PSE/TNX, Gruß, Versandweg
    page.rect(X_R, y, COL_R, 260, fill=GRAY_FILL, stroke=GRAY_LINE)
    pse = "PSE QSL" + ("   ·   TNX QSL" if r["TNX_QSL"] == "X" else "")
    page.line([(pse, B, 8, 1)], X_R + 80, y, 260, COL_R - 160)
    page.rect(X_R, y + 260, COL_R, 940, stroke=GRAY_LINE)
    inner = COL_R - 160
    page.line([("VY 73!", R, 9, 0)], X_R + 80, y + 260 + 40, 240, inner)
    page.line([(r["BEMERKUNG"], R, 7, 0)], X_R + 80, y + 260 + 280, 180, inner)
    sign = [((st["greeting"] + ", ") if st["greeting"] else "", R, 9, 0), (r["EIGENES_CALL"], B, 9, 0)]
    page.line(sign, X_R + 80, y + 260 + 940 - 280, 240, inner, "right")
    if r["VERSAND"]:
        page.line([("QSL via ", R, 7, GRAY_TEXT), (r["VERSAND"], B, 7, 0)], X_R + 80, y + 1200 + 60, 180, inner)


# --- Überdruck auf vorgedruckte Karten (Positionen aus QSL_Seriendruck.docx, Twips) -----------

OV_CALL = (5558, 1135, 1985, 567)                    # TO RADIO
OV_PORTABLE = (1815, 228, 227, 227)                  # Kästchen „/p“: X bei POTA
OV_X_FIXED = [(1419, 1532, 227, 227),                # Kästchen „Our QSO“ (immer X)
              (4764, 2949, 227, 227)]                # Kästchen „PSE QSL“ (immer X)
OV_TNX = (5784, 2949, 227, 227)                      # Kästchen „TNX QSL“: X, wenn Karte empfangen
OV_ROW = (285, 2326, 454)                            # QSO-Zeile: x, y, Höhe
OV_COLS = [479, 479, 479, 1498, 1498, 1498, 480, 480, 480]
OV_INFO = (285, 3233, 4253, 1418)                    # Block links unten


def draw_overlay(page: Page, r: dict):
    R, B = "R", "B"
    box = lambda b, runs: page.line(runs, b[0], b[1], b[3], b[2], "center")

    if r.get("POTA_1"):
        box(OV_PORTABLE, [("X", B, 10, 0)])
    for b in OV_X_FIXED:
        box(b, [("X", B, 10, 0)])
    if r.get("TNX_QSL") == "X":
        box(OV_TNX, [("X", B, 10, 0)])
    box(OV_CALL, [(r["AN_RUFZEICHEN"], B, 18, 0)])

    # QSO-Zeile: Tag/Monat/Jahr, UTC, MHz, Mode, R/S/T (bei FT8: Vorzeichen/Zehner/Einer)
    x, y, h = OV_ROW
    ft8 = r["BETRIEBSART"] == "FT8"
    values = [(r["DATUM_T"], 10.5), (r["DATUM_M"], 10.5), (r["DATUM_J"], 10.5),
              (r["UTC_ZEIT"], 18), (r["FREQUENZ"], 18), (r["BETRIEBSART"], 18),
              (r["RST_R"], 18), (r["RST_S"], 18), (r["RST_T"] if ft8 else "", 18)]
    for w, (value, size) in zip(OV_COLS, values):
        page.line([(value, B, size, 0)], x, y, h, w, "center")
        x += w

    # Block links unten: wie in Word bleiben leere Zeilen weg, der Rest steht senkrecht mittig
    lines = []
    hint = [("FT-8 · Report = SNR in dB", R, 6.5, GRAY_TEXT)] if ft8 else []
    via = [("via ", B, 7, 0), (r["VERSAND"], B, 7, 0)] if r["VERSAND"] else []
    if hint or via:
        lines.append((hint, via, 180, 40))
    for i in range(1, 5):
        if r.get(f"POTA_{i}"):
            lines.append(([(r[f"POTA_{i}"], B, 7, 0)], [], 180, 0))
    if r["SETUP"]:
        lines.append(([("Setup: ", B, 7, 0), (r["SETUP"], R, 6.5, 0)], [], 180, 0))
    pwr_loc = []
    if r["LEISTUNG_W"]:
        pwr_loc += [("Power (W): ", B, 7, 0), (r["LEISTUNG_W"], R, 6.5, 0), ("    ", R, 6.5, 0)]
    if r["EIGENER_LOCATOR"]:
        pwr_loc += [("Loc: ", B, 7, 0), (r["EIGENER_LOCATOR"], R, 6.5, 0)]
    if pwr_loc:
        lines.append((pwr_loc, [], 180, 0))

    bx, by, bw, bh = OV_INFO
    y = by + (bh - sum(lh + after for _, _, lh, after in lines)) / 2
    for left, right, lh, after in lines:
        right_w = page.width(right) / TW if right else 0
        if left:
            page.line(left, bx, y, lh, bw - right_w - 100)
        if right:
            page.line(right, bx, y, lh, bw, "right")
        y += lh + after


def find_fonts(st: dict, layout: str = "blanko"):
    if st["font"]:
        candidates = [(st["font"], st["font_bold"] or st["font"])]
    else:
        candidates = FONT_CANDIDATES_VORDRUCK if layout == "vordruck" else FONT_CANDIDATES
    for regular, bold in candidates:
        if all(os.path.isfile(spec.partition("#")[0]) for spec in (regular, bold)):
            try:
                return TTFont(regular), TTFont(bold)
            except QslPdfError:
                if st["font"]:
                    raise
    raise QslPdfError("Keine passende Schrift gefunden – bitte 'font' und 'font_bold' in der Stationsdatei setzen.")


def write_cards(rows: list, path: str, station_path: str, layout: str | None = None) -> int:
    """Schreibt eine Karte pro Zeile (Reihenfolge wie im CSV). Liefert die Anzahl der Seiten."""
    st = load_station(station_path)
    layout = (layout or st["layout"]).lower()
    if layout not in LAYOUTS:
        raise QslPdfError(f"Unbekannte Vorlage '{layout}' – erlaubt: {', '.join(LAYOUTS)}")
    regular, bold = find_fonts(st, layout)
    pdf = PdfWriter(st["rotate"])
    pdf.register_font("R", regular)
    pdf.register_font("B", bold)
    logo = bool(st["logo"]) and os.path.isfile(st["logo"])
    if logo:
        pdf.register_image("Logo", st["logo"])
    for r in rows:
        page = Page(pdf)
        if layout == "vordruck":
            draw_overlay(page, r)
        else:
            draw_card(page, r, st, logo)
        page.finish()
    pdf.save(path)
    return len(rows)


def run_print_command(pdf_path: str, station_path: str) -> str:
    """
    Führt den in der Stationsdatei unter [pdf] drucken eingetragenen Befehl aus ({pdf} = Datei).
    Das Script kennt keinen Drucker; ohne Eintrag passiert nichts. Liefert die Ausgabe des Befehls.
    """
    command = load_station(station_path)["print_command"]
    if not command:
        raise QslPdfError("Kein Druckbefehl konfiguriert – in der Stationsdatei unter [pdf] 'drucken' eintragen.")
    args = [a.replace("{pdf}", pdf_path) for a in shlex.split(command)]
    if not any("{pdf}" in a for a in shlex.split(command)):
        args.append(pdf_path)
    try:
        result = subprocess.run(args, capture_output=True, text=True)
    except FileNotFoundError:
        raise QslPdfError(f"Druckbefehl nicht gefunden: {args[0]}")
    if result.returncode != 0:
        raise QslPdfError(f"Druckbefehl fehlgeschlagen: {(result.stderr or result.stdout).strip()}")
    return (result.stdout or result.stderr).strip()
