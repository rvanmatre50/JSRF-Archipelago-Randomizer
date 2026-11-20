"""Corn's text box: rewrite the English text of the game's TE001 talk file. No Archipelago imports.

What was found (user's JSRF Unleashed install, see the project notes):
  * Corn's New Game talk is talk event 1. Its file is Media\\Event\\TalkEvent\\TE001.bin. The engine opens it from its
    cache mirror, save\\Cache\\Media\\Event\\TalkEvent\\TE001.bin (the original padded with zeros to a multiple of 512
    bytes), every time that talk starts, right after the portrait files.
  * The file is a header of 29 little-endian dwords (page counts and display times), the Japanese text, then the English
    text. Each text ends with "$r$e$r". Inside a text, pages are separated by "$r" and the two lines of a page by "$n".
    The English text of TE001 has four pages of two lines, and header dword 10 (value 5) counts them (+1).
  * So the header and the Japanese text stay as they are and only the English text after the first "$r$e$r" is replaced,
    with exactly four pages of two lines. The cache copy is padded with zeros back to its old size.
The original file in Media is never touched. It is the source for every rewrite and for put-back.
"""
import os
from typing import List, Optional, Sequence, Tuple

END = b"$r$e$r"
PAGES = 4                      # pages in the English text of TE001 (header dword 10 is PAGES + 1)
HEADER_DWORDS = 29
PAGE_COUNT_DWORD = 10
MAX_LINE = 37                  # the longest line in the original text; the text box is about this wide
Page = Tuple[str, str]

ORIGINAL_PAGES: List[Page] = [
    ("This is the GG's Garage.", "Hey, where's our pizza?"),
    ("Huh? You're not the pizza guy?", "Oh, you're here to join the GG's, eh?"),
    ("Heh... Tell you what. Find Gum.", "She's the one you wanna talk to."),
    ("Just get close to her and pull", "the “Right Trigger”. Got it?"),
]


class TalkError(Exception):
    """The file is not shaped the way this module expects, so nothing is written."""


def clean(text: str) -> str:
    """Plain ASCII without the engine's control character."""
    out = text.replace("$", "S").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in out)


def problems(pages: Sequence[Page]) -> List[str]:
    """Why these pages cannot go into the file (empty list = fine)."""
    out = []
    if len(pages) != PAGES:
        out.append("needs exactly %d pages, got %d" % (PAGES, len(pages)))
    for i, page in enumerate(pages, 1):
        if len(page) != 2:
            out.append("page %d must have two lines" % i)
            continue
        for line in page:
            if len(clean(line)) > MAX_LINE:
                out.append("page %d: line is %d characters (max %d): %s" % (i, len(clean(line)), MAX_LINE, line))
            if not line.strip():
                out.append("page %d has an empty line" % i)
    return out


def english_block(pages: Sequence[Page]) -> bytes:
    bad = problems(pages)
    if bad:
        raise TalkError("; ".join(bad))
    body = "$r".join("$n".join(clean(line) for line in page) for page in pages)
    return body.encode("ascii") + END


def split_file(data: bytes) -> Tuple[bytes, bytes]:
    """(everything up to and including the Japanese text, the English text without the zero padding)."""
    first = data.find(END)
    if first < 0:
        raise TalkError("no text found in the file")
    head_end = first + len(END)
    last = data.find(END, head_end)
    if last < 0:
        raise TalkError("no English text found in the file")
    return data[:head_end], data[head_end:last + len(END)]


def check_template(data: bytes):
    """Make sure `data` looks like the TE001 this module was written for."""
    if len(data) < HEADER_DWORDS * 4 + 2 * len(END):
        raise TalkError("the file is too short")
    head, english = split_file(data)
    dwords = [int.from_bytes(data[i * 4:i * 4 + 4], "little") for i in range(HEADER_DWORDS)]
    if dwords[PAGE_COUNT_DWORD] != PAGES + 1:
        raise TalkError("the file does not have %d English pages (header says %d)" % (PAGES, dwords[PAGE_COUNT_DWORD] - 1))
    if english.count(b"$r") != PAGES + 1:                  # one "$r" after each page, one more inside "$r$e$r"
        raise TalkError("the English text does not have %d pages" % PAGES)
    if data[len(head) + len(english):].strip(b"\0"):
        raise TalkError("there is more data after the English text")


def pages_of(data: bytes) -> List[Page]:
    """The English pages of a TE001 file."""
    _, english = split_file(data)
    body = english[:-len(END)].decode("latin-1")
    out = []
    for page in body.split("$r"):
        lines = page.split("$n")
        out.append((lines[0], lines[1] if len(lines) > 1 else ""))
    return out


def build(original: bytes, pages: Sequence[Page], size: Optional[int] = None) -> bytes:
    """The talk file with `pages` as its English text, padded with zeros to `size` bytes (default: the original's size
    rounded up to 512, which is what the cache mirror holds)."""
    check_template(original)
    head, _ = split_file(original)
    data = head + english_block(pages)
    size = size or -(-len(original) // 512) * 512
    if len(data) > size:
        raise TalkError("the new text is %d bytes, the file has room for %d" % (len(data), size))
    return data + b"\0" * (size - len(data))


# ---- the pages the client writes

def intro_pages(start_area: Optional[str]) -> List[Page]:
    """Corn's New Game text: the city is locked, and which door is open."""
    if start_area:
        return [
            ("Welcome to the GG's Garage. Heads up,", "the rest of Tokyo-to is locked down."),
            ("Areas open when their Unlock items", "show up. The one open right now is"),
            (start_area + ".", "Skate into a locked one and I'll"),
            ("send you right back here. Got it?", "Good luck, kid!"),
        ]
    return [
        ("Welcome to the GG's Garage. Heads up,", "the rest of Tokyo-to is locked down."),
        ("Areas open when their Unlock items", "show up out there in the city."),
        ("Skate into a locked one and I'll", "send you right back here."),
        ("Got it? Good luck, kid!", "Now go tag something."),
    ]


def bounce_pages(area: str, tower: bool = False) -> List[Page]:
    """Corn's text when the player skated into a locked area."""
    place = area + " yet." if len(area) + 5 <= MAX_LINE else area + "." if len(area) + 1 <= MAX_LINE else area
    if tower:
        why = ("Gouji's Tower is sealed until you've", "got its Unlock item and enough Souls.")
    else:
        why = ("That place stays locked until its", "Unlock item turns up somewhere.")
    return [
        ("Yo, hold up! You can't go to", place),
        why,
        ("Keep skating, find it, and I'll let", "you right on through."),
        ("For now the whole Garage is yours.", "Go tag something!"),
    ]


# ---- Corn's question before Gouji's Tower (a talk with a Yes / No choice)
# The game asks two-option questions inside talk files: an English block "question$r$s<a><b>$raccepted line" plus a
# second English block that is said when the player declines (TE124, Cube's challenge: "...I'll leave you alone.$r$s\x02\x04
# $rI won't hold back." / "Suit yourself."). The two bytes after $s are page numbers, counting the pages of the first
# block, then its end, then the second block: <a> = the last page said on Yes, <b> = the first page said on No. So TE124's
# \x02\x04 = Yes says page 2 ("I won't hold back."), No jumps to page 4 ("Suit yourself."). TE190 (Roboy's "Are you
# sure??") has no second block and \x02\x03: No jumps to the end and nothing is said. The same rule holds in TE019,
# TE031 and TE042 (longer talks: <a> = last page of the first block, <b> = that + 2). An earlier build used \x02\x03
# with TE124's layout, so Corn said nothing on No (user, 2026-11-19 17:23). After such a talk the mission object holds
# the answer at +0x2A0 (1 = the first choice / accept, 0 = decline; -1 while unanswered), which the mission script's ops
# 0x16 / 0x17 test. The client builds Corn's question from TE124's layout (header, Japanese blocks, page counts and the
# $s page numbers kept, so the header and the jumps stay valid), with TE001's speaker fields (header dwords 11 and 12) so
# it is still Corn who talks.
CHOICE_TEMPLATE = ("Media", "Event", "TalkEvent", "TE124.bin")
SPEAKER_DWORDS = (11, 12)
CHOICE_PAGES = (2, 4)          # <a>, <b> for question / choice / Yes line / end / No line


DECLINES = {
    # Corn's own question the first time (his mission 1:1); he then waits in the free-skate Garage (garage.py)
    "first": ("No sweat. I'll be here in the Garage.", "Talk to me again to hit the Tower."),
    # asked when the player talks to him in the free-skate Garage
    "garage": ("No sweat. Whenever you're ready,", "talk to me again to hit the Tower."),
    # no Corn in the Garage (his patch is off or could not be written): the client's /tower is the way
    "plain": ("No sweat. Take your time.", "Gouji's Tower isn't going anywhere."),
}


def tower_question(where: str = "first") -> Tuple[Page, Page, Page]:
    """(question, said on Yes, said on No) for Corn's Gouji's Tower question. `where` picks the No line (DECLINES)."""
    return (("Yo! Gouji's Tower is open for you.", "You ready to take him down?"),
            ("Then get up there and take Gouji", "down! Tokyo-to is counting on you!"),
            DECLINES.get(where, DECLINES["plain"]))


def tower_status_pages(missing: Sequence[str]) -> List[Page]:
    """Corn's four pages in the Garage while Gouji's Tower is still shut: what is missing, one short line each (at most
    four lines are shown; each is cut to the box width)."""
    lines = [clean(line)[:MAX_LINE] for line in missing if line and line.strip()][:4]
    if not lines:                                          # the Tower opened since this file was written
        return [("Hold up, Gouji's Tower just opened!", "Talk to me again in a second."),
                ("I've got something to ask you,", "so don't go too far."),
                ("Keep it moving out there.", "Tokyo-to is counting on you."),
                ("Catch you in a sec.", "Now go tag something!")]
    middle = lines + ["That's everything on the list."] if len(lines) % 2 else lines
    if len(middle) == 2:
        middle += ["Keep skating and tagging,", "it'll all come together."]
    return [("Gouji's Tower is still sealed.", "Here's what you're still missing:"),
            (middle[0], middle[1]), (middle[2], middle[3]),
            ("Come talk to me again once", "you've got it all. Good luck!")]


def jet_status_pages(jets: Optional[int], needed: int, ready: Optional[int]) -> List[Page]:
    """Corn's four pages in the Garage when the goal is Jet ranks (user, 2026-11-19 18:42: the Tower talk makes no sense
    then): how many Jet ranks there are, Roboy's rule, and in how many areas the Test Runs are ready (None = unknown)."""
    if jets is not None and needed and jets >= needed:
        return [("%d Jet ranks! You did it, kid." % jets, "That's the whole goal, done."),
                ("Tokyo-to's never seen skating", "like that. Respect."),
                ("Keep skating if you want.", "The city's all yours now."),
                ("Catch you around!", "Now go tag something!")]
    count = ("You've got %d of %d." % (jets, needed)) if jets is not None else ("You need %d of them." % needed)
    ready_page = (("Test Runs are ready in %d area%s." % (ready, "" if ready == 1 else "s"), "Go talk to Roboy about 'em!")
                  if ready else ("No area is ready for them yet.", "Grab every Soul in one first."))
    return [("Your goal: Jet ranks on Roboy's", "Test Runs. " + count),
            ("Roboy opens an area's Test Runs", "once you've got all its Souls."),
            ready_page,
            ("Get Jet on enough of them and", "you're done. Good luck, kid!")]


def _page_bytes(page: Page) -> bytes:
    if len(page) != 2 or any(not line.strip() or len(clean(line)) > MAX_LINE for line in page):
        raise TalkError("a page needs two lines of 1-%d characters: %r" % (MAX_LINE, page))
    return "$n".join(clean(line) for line in page).encode("ascii")


def check_choice_template(data: bytes):
    """Make sure `data` looks like TE124: Japanese question + decline, English question + decline, the question with one
    two-option choice between a page before and a page after it."""
    blocks = data.split(END)
    if len(blocks) != 5 or blocks[4].strip(b"\0"):
        raise TalkError("the choice template does not have four text blocks")
    en_main, en_decline = blocks[2], blocks[3]
    if en_main.count(b"$s") != 1 or len(en_main.split(b"$r")) != 3 or len(en_decline.split(b"$r")) != 1:
        raise TalkError("the choice template's English text is not question / choice / answer + decline")
    if en_main.split(b"$r")[1] != b"$s" + bytes(CHOICE_PAGES):
        raise TalkError("the choice template's Yes / No jumps are not pages %d / %d" % CHOICE_PAGES)
    if len(data) < HEADER_DWORDS * 4:
        raise TalkError("the choice template is too short")


def build_choice(template: bytes, speaker_from: bytes, question: Page, accept: Page, decline: Page,
                 size: Optional[int] = None) -> bytes:
    """A talk file with Corn asking `question` (Yes / No), saying `accept` on Yes and `decline` on No."""
    check_choice_template(template)
    blocks = template.split(END)
    head = END.join(blocks[:2]) + END                         # header + both Japanese blocks, as they are
    head = bytearray(head)
    for d in SPEAKER_DWORDS:                                   # whose face and voice: Corn's, from TE001
        head[d * 4:d * 4 + 4] = speaker_from[d * 4:d * 4 + 4]
    en = (_page_bytes(question) + b"$r$s" + bytes(CHOICE_PAGES) + b"$r" + _page_bytes(accept) + END
          + _page_bytes(decline) + END)
    data = bytes(head) + en
    size = size or -(-len(data) // 512) * 512
    if len(data) > size:
        raise TalkError("the question is %d bytes, the file has room for %d" % (len(data), size))
    return data + b"\0" * (size - len(data))


# ---- the files on disk

def game_root(exe_path: Optional[str]) -> Optional[str]:
    """The folder that holds engine\\ and save\\, from the engine's own path."""
    if not exe_path:
        return None
    folder = os.path.dirname(exe_path)
    if os.path.basename(folder).lower() == "engine":
        return os.path.dirname(folder)
    return folder


TALK = ("Media", "Event", "TalkEvent", "TE001.bin")


def _folders(root: str, depth: int = 3, skip_cache: bool = False):
    """`root` and the folders below it down to `depth` levels, shallow ones first (the names differ between installs)."""
    level = [root]
    for n in range(depth + 1):
        yield from level
        if n == depth:
            return
        nxt = []
        for folder in level:
            try:
                names = sorted(os.listdir(folder))[:500]
            except OSError:
                continue
            for name in names:
                path = os.path.join(folder, name)
                if skip_cache and name.lower() == "cache":
                    continue
                if os.path.isdir(path):
                    nxt.append(path)
        level = nxt


def media_file(root: str, parts=TALK) -> Optional[str]:
    """The untouched talk file (TE001.bin unless `parts` says otherwise) under the game folder. Cache folders are
    skipped: their copy may be one of ours."""
    for folder in _folders(root, 3, skip_cache=True):
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
    return None


def cache_file(root: str, parts=TALK) -> str:
    """The engine's cache copy of TE001.bin (or of `parts`): the one that exists, else where one would go in the folder
    named Cache that has a Media folder in it, else save\\Cache under the game folder (where JSRF Unleashed puts it on
    Windows)."""
    spare = None
    for folder in _folders(root, 3):
        if os.path.basename(folder).lower() != "cache":
            continue
        path = os.path.join(folder, *parts)
        if os.path.isfile(path):
            return path
        if spare is None and os.path.isdir(os.path.join(folder, "Media")):
            spare = path
    return spare or os.path.join(root, "save", "Cache", *parts)


class TalkPatch:
    """Reads the original TE001.bin once and writes versions of it into the engine's cache mirror."""

    def __init__(self, root: str):
        self.root = root
        self.media = media_file(root)
        self.cache = cache_file(root)
        self.original: Optional[bytes] = None
        self.error = ""
        self.shown: Optional[List[Page]] = None      # the pages last written (None = the original, or unknown)
        if not self.media:
            self.error = "could not find Media\\Event\\TalkEvent\\TE001.bin under " + root
            return
        try:
            with open(self.media, "rb") as f:
                self.original = f.read()
            check_template(self.original)
        except (OSError, TalkError) as e:
            self.original = None
            self.error = "cannot use %s: %s" % (self.media, e)

    @property
    def ok(self) -> bool:
        return self.original is not None

    def cache_size(self) -> int:
        try:
            return os.path.getsize(self.cache)
        except OSError:
            return -(-len(self.original) // 512) * 512

    def write(self, pages: Sequence[Page]) -> bool:
        """Put `pages` into the cache copy. False (with self.error set) when that did not work."""
        if not self.ok:
            return False
        try:
            data = build(self.original, pages, self.cache_size())
            os.makedirs(os.path.dirname(self.cache), exist_ok=True)
            if os.path.isfile(self.cache):
                with open(self.cache, "rb") as f:
                    if f.read() == data:
                        self.shown = list(pages)
                        return True
            with open(self.cache, "r+b" if os.path.isfile(self.cache) else "wb") as f:
                f.write(data)
                f.truncate(len(data))
        except (OSError, TalkError) as e:
            self.error = "could not write %s: %s" % (self.cache, e)
            return False
        self.error = ""
        self.shown = list(pages)
        return True

    def restore(self) -> bool:
        """Put Corn's own text back (the original, padded like the cache mirror pads it)."""
        if not self.ok:
            return False
        try:
            data = self.original + b"\0" * (self.cache_size() - len(self.original))
            if os.path.isfile(self.cache):
                with open(self.cache, "rb") as f:
                    if f.read() == data:
                        self.shown = None
                        return True
            with open(self.cache, "r+b" if os.path.isfile(self.cache) else "wb") as f:
                f.write(data)
                f.truncate(len(data))
        except OSError as e:
            self.error = "could not write %s: %s" % (self.cache, e)
            return False
        self.error = ""
        self.shown = None
        return True

    def write_question(self, question: Page, accept: Page, decline: Page) -> bool:
        """Put Corn's Yes / No question into the cache copy of TE001 (built from TE124's layout)."""
        if not self.ok:
            return False
        try:
            path = media_file(self.root, CHOICE_TEMPLATE)
            if not path:
                raise TalkError("could not find Media\\Event\\TalkEvent\\TE124.bin (the question layout)")
            with open(path, "rb") as f:
                template = f.read()
            data = build_choice(template, self.original, question, accept, decline, max(self.cache_size(), 512))
            os.makedirs(os.path.dirname(self.cache), exist_ok=True)
            with open(self.cache, "r+b" if os.path.isfile(self.cache) else "wb") as f:
                f.write(data)
                f.truncate(len(data))
        except (OSError, TalkError) as e:
            self.error = "could not write the question: %s" % e
            return False
        self.error = ""
        self.shown = [question]
        return True
