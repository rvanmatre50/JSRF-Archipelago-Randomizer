"""JSRF's own lettering for the on-screen notices, read at run time from the player's game files (nothing of the game is
shipped with the client).

Media\\Font\\jetfont.dat holds the game's font textures one after another, each behind a 0x30-byte header whose second
dword is the file offset of the next header and whose third is the data size + 0x20. The last two are the Latin sheets:
256x256 DXT3, white glyphs on a 12-column grid with rows 256/7.5 pixels apart (there is no backslash):

    sheet 1:  ! " # $ % & ' ( ) * + ,  /  - . / 0 1 2 3 4 5 6 7 8  /  9 : ; < = > ? @ A B C D  /  E ... P
              Q ... Z [ ]  /  ^ _ ` a ... i  /  j ... u
    sheet 2:  v w x y z ¡ §  (row 1: signs, unused)  then accented letters, rows 2-5 (LATIN2 below)

Only the alpha is used (the glyphs are pure white). Everything here is plain Python so it runs on any system and can be
tested away from Windows."""
import os
import struct
import unicodedata
from typing import Dict, List, Optional, Tuple

FONT_FILE = ("Media", "Font", "jetfont.dat")
SHEET = 256                    # both Latin sheets are SHEET x SHEET
SHEET_DATA = SHEET * SHEET     # DXT3: one byte per pixel
COLUMNS = 12
ROW_PITCH = SHEET / 7.5
LATIN1 = ("!\"#$%&'()*+,", "-./012345678", "9:;<=>?@ABCD", "EFGHIJKLMNOP", "QRSTUVWXYZ[]", "^_`abcdefghi",
          "jklmnopqrstu")
LATIN2 = ("vwxyz\u00a1\u00a7", "",
          "\u00bd\u00be\u00bf\u00c0\u00c2\u00c4\u00c6\u00c7\u00c8\u00c9\u00cb\u00cc",     # ½ ¾ ¿ À Â Ä Æ Ç È É Ë Ì
          "\u00cd\u00ce\u00cf\u00d1\u00d2\u00d3\u00d4\u00d6\u00d7\u00d8\u00d9\u00da",     # Í Î Ï Ñ Ò Ó Ô Ö × Ø Ù Ú
          "\u00db\u00dc\u00df\u00e0\u00e2\u00e4\u00e6\u00e7\u00e8\u00e9\u00ea\u00eb",     # Û Ü ß à â ä æ ç è é ê ë
          "\u00ee\u00ef\u00f1\u00f2\u00f3\u00f4\u00f6\u00f8\u00f9\u00fa\u00fb\u00fc")     # î ï ñ ò ó ô ö ø ù ú û ü
DESCENDERS = set("gjpqyQ,;_\u00c7\u00e7\u00bf")
TRACKING = 2          # pixels between letters (sheet scale)
SPACE = 12            # width of a space (sheet scale)
INK = 24              # alpha (0-255) that counts as ink when measuring a glyph


class FontError(Exception):
    pass


def _texture_headers(data: bytes) -> List[int]:
    """Offsets of the texture headers, following each header's link to the next."""
    if data[:4] != b"NORM":
        raise FontError("not a JSRF font file")
    out, at = [], 0x10
    while 0 <= at and at + 0x30 <= len(data) and at not in out and len(out) < 64:
        out.append(at)
        nxt = struct.unpack_from("<I", data, at + 4)[0]
        if nxt <= at:
            break
        at = nxt
    if len(out) < 2:
        raise FontError("no textures found")
    return out


def dxt3_alpha(block_data: bytes, width: int, height: int) -> bytearray:
    """The alpha channel (0-255, one byte per pixel, rows top to bottom) of a DXT3 texture."""
    out = bytearray(width * height)
    bw = width // 4
    for b in range(min(len(block_data) // 16, bw * (height // 4))):
        by, bx = divmod(b, bw)
        bits = int.from_bytes(block_data[16 * b:16 * b + 8], "little")
        if not bits:
            continue
        base = by * 4 * width + bx * 4
        for p in range(16):
            a = (bits >> (4 * p)) & 15
            if a:
                y, x = divmod(p, 4)
                out[base + y * width + x] = a * 17
    return out


def _main_ink(alpha: bytes, x0: int, x1: int, y0: int, y1: int):
    """The x range of a cell's own glyph. The letters lean, so a cell can catch the tip of its neighbour: runs of inked
    columns that touch the cell's edge and hold little ink are dropped."""
    weight = [sum(1 for y in range(y0, y1) if alpha[y * SHEET + x] >= INK) for x in range(x0, x1)]
    runs, start = [], None
    for i, w in enumerate(weight + [0]):
        if w and start is None:
            start = i
        elif not w and start is not None:
            runs.append((start, i, sum(weight[start:i])))
            start = None
    if not runs:
        return None, None
    biggest = max(r[2] for r in runs)
    keep = [r for r in runs if r[2] >= biggest * 0.35 or not (r[0] == 0 or r[1] == len(weight))]
    return x0 + keep[0][0], x0 + keep[-1][1]


class Glyph:
    __slots__ = ("width", "height", "top", "alpha")

    def __init__(self, width: int, height: int, top: int, alpha: bytes):
        self.width, self.height, self.top, self.alpha = width, height, top, alpha   # top: rows above the baseline


class JetFont:
    """The game's Latin glyphs, measured from the sheet."""

    def __init__(self, data: bytes):
        heads = [h for h in _texture_headers(data) if struct.unpack_from("<I", data, h + 8)[0] == SHEET_DATA + 0x20]
        if len(heads) < 2 or heads[-1] + 0x30 + SHEET_DATA > len(data):
            raise FontError("the Latin sheets were not found")
        self.glyphs: Dict[str, Glyph] = {}
        cell = SHEET / COLUMNS
        ink = {}                                                     # char -> (x0, x1, y0, y1, row key, sheet)
        sheets = []
        for n, (head, rows) in enumerate(zip(heads[-2:], (LATIN1, LATIN2))):
            alpha = dxt3_alpha(data[head + 0x30:head + 0x30 + SHEET_DATA], SHEET, SHEET)
            sheets.append(alpha)
            for r, chars in enumerate(rows):
                y0, y1 = int(round(r * ROW_PITCH)), min(SHEET, int(round((r + 1) * ROW_PITCH)))
                for c, ch in enumerate(chars):
                    x0, x1 = int(round(c * cell)), int(round((c + 1) * cell))
                    xa, xb = _main_ink(alpha, x0, x1, y0, y1)
                    if xa is None:
                        raise FontError("no ink for %r" % ch)
                    ys = [y for y in range(y0, y1) if max(alpha[y * SHEET + xa:y * SHEET + xb]) >= INK]
                    ink[ch] = (xa, xb, ys[0], ys[-1] + 1, (n, r), n)
        # each row's baseline: the lowest ink of its letters that do not hang below the line
        base: Dict[Tuple[int, int], int] = {}
        for ch, (_, _, _, yb, r, _) in ink.items():
            if ch not in DESCENDERS and ch.isalnum():
                base[r] = max(base.get(r, 0), yb)
        for ch, (_, _, _, yb, r, _) in ink.items():                  # a row of signs only: its tallest-reaching sign
            if r not in base or (ch in "!#$%&?" and not any(c.isalnum() and ink[c][4] == r for c in ink)):
                if ch not in DESCENDERS and ch in "!#$%&?@<>=+*()/[]":
                    base[r] = max(base.get(r, 0) if r in base else 0, yb)
        for ch, (xa, xb, ya, yb, r, n) in ink.items():
            w, h = xb - xa, yb - ya
            buf = bytearray(w * h)
            for y in range(h):
                src = (ya + y) * SHEET + xa
                buf[y * w:(y + 1) * w] = sheets[n][src:src + w]
            self.glyphs[ch] = Glyph(w, h, base[r] - ya, bytes(buf))
        self.ascent = max(g.top for g in self.glyphs.values())
        self.descent = max(g.height - g.top for g in self.glyphs.values())
        self.line_height = self.ascent + self.descent

    @classmethod
    def from_file(cls, path: str) -> "JetFont":
        with open(path, "rb") as f:
            return cls(f.read())

    def glyph_for(self, ch: str) -> Optional[Glyph]:
        """The glyph for a character; letters the sheet lacks (accents, other scripts) fall back to their plain form,
        then to the other case. None means a space-sized gap."""
        g = self.glyphs.get(ch)
        if g is None:
            plain = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            for alt in (plain[:1], ch.upper(), ch.lower(), plain[:1].upper(), plain[:1].lower(),
                        {"\\": "/", "{": "(", "}": ")", "|": "!", "~": "-"}.get(ch, "")):
                if alt and alt in self.glyphs:
                    return self.glyphs[alt]
        return g

    def render(self, text: str) -> Tuple[int, int, bytearray]:
        """One line of text as an alpha mask at the sheet's size: (width, height, one byte per pixel)."""
        parts, x = [], 0
        for ch in text:
            g = None if ch.isspace() else self.glyph_for(ch)
            if g is None:
                x += SPACE
                continue
            parts.append((x, g))
            x += g.width + TRACKING
        width, height = max(1, x - TRACKING if parts else x), self.line_height
        out = bytearray(width * height)
        for gx, g in parts:
            oy = self.ascent - g.top
            for y in range(g.height):
                row = (oy + y) * width + gx
                src = g.alpha[y * g.width:(y + 1) * g.width]
                dst = out[row:row + g.width]
                out[row:row + g.width] = bytes(max(a, b) for a, b in zip(src, dst))
        return width, height, out


def scale_mask(width: int, height: int, mask: bytes, factor: float) -> Tuple[int, int, bytearray]:
    """Resize an alpha mask (area-weighted when shrinking, bilinear when growing)."""
    if abs(factor - 1.0) < 0.01:
        return width, height, bytearray(mask)
    nw, nh = max(1, int(round(width * factor))), max(1, int(round(height * factor)))
    out = bytearray(nw * nh)
    sx, sy = width / nw, height / nh
    if factor < 1.0:
        for y in range(nh):
            y0, y1 = y * sy, (y + 1) * sy
            for x in range(nw):
                x0, x1 = x * sx, (x + 1) * sx
                total = 0.0
                for yy in range(int(y0), min(height, int(-(-y1 // 1)))):
                    wy = min(y1, yy + 1) - max(y0, yy)
                    row = yy * width
                    for xx in range(int(x0), min(width, int(-(-x1 // 1)))):
                        total += mask[row + xx] * wy * (min(x1, xx + 1) - max(x0, xx))
                out[y * nw + x] = min(255, int(total / (sx * sy) + 0.5))
        return nw, nh, out
    for y in range(nh):
        fy = min(height - 1.0, max(0.0, (y + 0.5) * sy - 0.5))
        y0 = int(fy); y1 = min(height - 1, y0 + 1); ty = fy - y0
        for x in range(nw):
            fx = min(width - 1.0, max(0.0, (x + 0.5) * sx - 0.5))
            x0 = int(fx); x1 = min(width - 1, x0 + 1); tx = fx - x0
            a = mask[y0 * width + x0] * (1 - tx) + mask[y0 * width + x1] * tx
            b = mask[y1 * width + x0] * (1 - tx) + mask[y1 * width + x1] * tx
            out[y * nw + x] = int(a * (1 - ty) + b * ty + 0.5)
    return nw, nh, out


def compose(lines: List[Tuple[int, int, bytes]], pad_x: int, pad_y: int, gap: int, box_alpha: int) -> Tuple[int, int, bytearray]:
    """Stack text masks into one premultiplied BGRA image (top-down rows): each line on its own black box, boxes
    left-aligned with `gap` clear pixels between them. Returns (width, height, pixels)."""
    boxes = [(w + 2 * pad_x, h + 2 * pad_y) for w, h, _ in lines]
    width = max(b[0] for b in boxes)
    height = sum(b[1] for b in boxes) + gap * (len(boxes) - 1)
    out = bytearray(width * height * 4)
    top = 0
    bg = bytes((0, 0, 0, box_alpha))
    lut = [bytes((v, v, v, v + box_alpha * (255 - v) // 255)) for v in range(256)]   # white text over the box
    for (w, h, mask), (bw, bh) in zip(lines, boxes):
        for y in range(bh):
            row = ((top + y) * width) * 4
            out[row:row + bw * 4] = bg * bw
            ty = y - pad_y
            if 0 <= ty < h:
                start = row + pad_x * 4
                out[start:start + w * 4] = b"".join(lut[a] for a in mask[ty * w:(ty + 1) * w])
        top += bh + gap
    return width, height, out


def find_font(root: Optional[str]) -> Optional[str]:
    """jetfont.dat under the game folder (searched the same way as Corn's text file), or None."""
    if not root:
        return None
    from .talk import media_file
    return media_file(root, FONT_FILE)


def load(root: Optional[str]) -> Tuple[Optional[JetFont], str]:
    """(font, '') or (None, why not)."""
    path = find_font(root)
    if not path:
        return None, "Media\\Font\\jetfont.dat was not found"
    try:
        return JetFont.from_file(path), ""
    except (OSError, FontError, struct.error) as e:
        return None, "%s: %s" % (os.path.basename(path), e)
