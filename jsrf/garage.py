"""Corn in the free-skate Garage: the client's copy of the Garage's mission file, with Corn standing at his New Game spot
and a talk point for him. No Archipelago imports.

What was found (static reading of default.xbe and the mission files; project note corn-tower-talk.md):
  * The free-skate Garage's own mission is the hub 9:900, file Media\\Mission\\mssn0900.bin. The engine reads it from its
    cache mirror (save\\Cache\\Media\\Mission\\mssn0900.bin) every time the Garage loads, like the talk files, and turns
    every file offset in its tables into an address with 0x4DB30, table by table, starting from the header. So a table can
    move to the end of the file as long as the header points at it (offset, count).
  * Header +0x34/+0x38: the load list (0x20-byte entries: kind, argument, two list offsets). Kind 2 loads a character; an
    argument with bit 31 set loads it only while that character is in the crew (0x51861). Corn's entry is
    (2, 0x80000101); Roboy's (2, 0x113) has no such bit.
  * Header +0xA4/+0xA8: the talk points (0x170 bytes each): a placement, two trigger boxes, +0x04 = 0 for a talk the
    script handles (-1: the Garage's own crew talk, 0x6C6E0), +0x168/+0x16C = who stands there (72 bytes each: character
    id, pose, 4x4 placement). The mission keeps one slot per talk point (+0x1044, sized from +0xA8 at 0x51DD6).
  * Header +0x174/+0x178 (run once at the start), +0x17C/+0x180 (tested every frame), +0x184/+0x188 (loads),
    +0x18C/+0x190 (talks and exits): the script records, 0x54 bytes each: condition list offset and count, set list
    offset and count, op, 16 arguments. Flag words: bank | index << 3 | value << 19 (bank 0 = Mission, which the game
    clears when a mission starts).
  * Roboy's talk in the same file is the model: op 0x64 [24] puts him there (talk point 24), op 0x04 [0, 24] notices the
    player talking to him, op 0x31 [14] loads his talk file TE014, op 0xE7 [14, 24] plays it.
  * mssn0101.bin (Corn's New Game mission, same Garage stage) has talk point 8: Corn at his New Game spot
    (243.4, -0.4, 539.6), handled by the script (+0x04 = 0), with a 100 x 55 x 100 trigger box around him. Its bytes are
    read from the player's own file and appended as the Garage's talk point 25.
What this module adds to the Garage (Mission flags 140-144 are unused there; the game clears them on every visit):
  load list:  Corn's character always (2, 0x101)
  start:      op 0x64 [25]                                    Corn stands at talk point 25
  loads:      op 0x31 [QUESTION_TALK]   if M140=0 -> M140=1   his Yes / No question (TE005 in the cache)
              op 0x31 [STATUS_TALK]     if M141=0 -> M141=1   what the Tower still needs (TE006 in the cache)
  tests:      op 0x04 [0, 25]           if M140 M141 -> M142  the player talked to him
  talks:      op 0xE7 [QUESTION_TALK, 25] if M142 M143 -> M142=0 M144=1   (M143: the client says the Tower is open)
              op 0xE7 [STATUS_TALK, 25]   if M142 M143=0 -> M142=0
The client sets M143 while the player is in the Garage, and acts on M144 (reads the answer, clears M144).
TE005 and TE006 are tutorial talks (Gum and Roboy) that only the late part of mission 1:1 loads, which the client never
lets run; the client writes Corn's two talks over their cache copies and puts the originals back when it closes.
"""
import os
import struct
from typing import Dict, List, Optional, Sequence, Tuple

from . import talk as jsrf_talk

GARAGE_FILE = ("Media", "Mission", "mssn0900.bin")
CORN_FILE = ("Media", "Mission", "mssn0101.bin")
CORN_TALK_POINT = 8                    # in mssn0101: Corn at his New Game spot, a script talk
CORN_ID = 1
CORN_LOAD = (2, 0x80000101)            # Corn's character, only while he is in the crew
CORN_LOAD_ALWAYS = 0x101
QUESTION_TALK = 5                      # talk numbers whose cache copies hold Corn's talks
STATUS_TALK = 6

F_QUESTION_LOADED = 140
F_STATUS_LOADED = 141
F_TALKED = 142
F_TOWER_OPEN = 143                     # set by the client
F_ASKED = 144                          # the question talk is over: the client reads the answer

H_LOADS, H_TALKS = 0x34, 0xA4
H_START, H_TESTS, H_LOADING, H_EVENTS = 0x174, 0x17C, 0x184, 0x18C
TALK_SIZE, PERSON_SIZE, RECORD_SIZE, LOAD_SIZE = 0x170, 72, 0x54, 0x20
SECTOR = 512

OP_PLACE, OP_TALKED, OP_LOAD_TALK, OP_TALK = 0x64, 0x04, 0x31, 0xE7


def talk_parts(n: int) -> Tuple[str, ...]:
    return ("Media", "Event", "TalkEvent", "TE%03d.bin" % n)


def flag(n: int, value: int = 1) -> int:
    """A Mission-bank flag word."""
    return (n << 3) | (value << 19)


def _u32(data, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def padded(data: bytes, size: int = 0) -> bytes:
    """`data` with zeros up to a multiple of 512 bytes (what the engine's cache mirror holds), at least `size` bytes."""
    n = max(-(-len(data) // SECTOR) * SECTOR, size)
    return data + b"\0" * (n - len(data))


class GarageError(Exception):
    """A file is not shaped the way this module expects, so nothing is written."""


def corn_talk_point(corn: bytes) -> Tuple[bytes, bytes]:
    """(talk point bytes, its one person's bytes) of Corn's New Game spot in mssn0101.bin."""
    if len(corn) < 0x1A0:
        raise GarageError("mssn0101.bin is too short")
    table, count = _u32(corn, H_TALKS), _u32(corn, H_TALKS + 4)
    if count <= CORN_TALK_POINT or table + count * TALK_SIZE > len(corn):
        raise GarageError("mssn0101.bin has no talk point %d" % CORN_TALK_POINT)
    entry = corn[table + CORN_TALK_POINT * TALK_SIZE:table + (CORN_TALK_POINT + 1) * TALK_SIZE]
    people, n = _u32(entry, 0x168), _u32(entry, 0x16C)
    if n != 1 or people + PERSON_SIZE > len(corn):
        raise GarageError("talk point %d of mssn0101.bin is not one person" % CORN_TALK_POINT)
    person = corn[people:people + PERSON_SIZE]
    if _u32(person, 0) != CORN_ID or _u32(entry, 4) != 0:
        raise GarageError("talk point %d of mssn0101.bin is not Corn's script talk" % CORN_TALK_POINT)
    return entry, person


class _Builder:
    """The original file plus data appended at its end (offsets are file offsets, 16-byte aligned)."""

    def __init__(self, original: bytes):
        self.data = bytearray(original)

    def add(self, blob: bytes) -> int:
        self.data += b"\0" * (-len(self.data) % 16)
        at = len(self.data)
        self.data += blob
        return at

    def flags(self, words: Sequence[int]) -> int:
        """A flag list; an empty one still gets a valid offset (as the game's own records have)."""
        return self.add(struct.pack("<%dI" % max(len(words), 1), *(list(words) or [0])))


def _record(b: _Builder, op: int, args: Sequence[int], conds: Sequence[int] = (), sets: Sequence[int] = ()) -> bytes:
    words = [b.flags(conds), len(conds), b.flags(sets), len(sets), op] + list(args) + [0] * (16 - len(args))
    return struct.pack("<21I", *words)


def _grow(b: _Builder, header: int, extra: Sequence[bytes], size: int) -> int:
    """Move the table at `header` (offset, count) to the end of the file with `extra` entries after it. Returns the
    index of the first new entry."""
    at, n = _u32(b.data, header), _u32(b.data, header + 4)
    if n and (at <= 0 or at + n * size > len(b.data)):
        raise GarageError("the table at header +0x%X is out of the file" % header)
    old = bytes(b.data[at:at + n * size]) if n else b""
    new = b.add(old + b"".join(extra))
    struct.pack_into("<II", b.data, header, new, n + len(extra))
    return n


def build_garage(garage: bytes, corn: bytes) -> bytes:
    """mssn0900.bin with Corn always loaded, standing at his New Game spot, and his talk records (see the module text)."""
    if len(garage) < 0x1A0:
        raise GarageError("mssn0900.bin is too short")
    entry, person = corn_talk_point(corn)
    b = _Builder(garage)
    loads, n = _u32(garage, H_LOADS), _u32(garage, H_LOADS + 4)
    for i in range(n):
        at = loads + i * LOAD_SIZE
        if at + LOAD_SIZE > len(garage):
            break
        if struct.unpack_from("<2I", garage, at) in (CORN_LOAD, (2, CORN_LOAD_ALWAYS)):
            struct.pack_into("<I", b.data, at + 4, CORN_LOAD_ALWAYS)
            break
    else:
        raise GarageError("mssn0900.bin does not load Corn's character")
    if _u32(garage, H_TALKS + 4) == 0:
        raise GarageError("mssn0900.bin has no talk points")
    point = bytearray(entry)
    struct.pack_into("<II", point, 0x168, b.add(person), 1)
    k = _grow(b, H_TALKS, [bytes(point)], TALK_SIZE)
    _grow(b, H_START, [_record(b, OP_PLACE, [k, 0])], RECORD_SIZE)
    _grow(b, H_TESTS, [_record(b, OP_TALKED, [0, k], [flag(F_QUESTION_LOADED), flag(F_STATUS_LOADED)],
                               [flag(F_TALKED)])], RECORD_SIZE)
    _grow(b, H_LOADING, [
        _record(b, OP_LOAD_TALK, [QUESTION_TALK], [flag(F_QUESTION_LOADED, 0)], [flag(F_QUESTION_LOADED)]),
        _record(b, OP_LOAD_TALK, [STATUS_TALK], [flag(F_STATUS_LOADED, 0)], [flag(F_STATUS_LOADED)]),
    ], RECORD_SIZE)
    _grow(b, H_EVENTS, [
        _record(b, OP_TALK, [QUESTION_TALK, k], [flag(F_TALKED), flag(F_TOWER_OPEN)], [flag(F_TALKED, 0), flag(F_ASKED)]),
        _record(b, OP_TALK, [STATUS_TALK, k], [flag(F_TALKED), flag(F_TOWER_OPEN, 0)], [flag(F_TALKED, 0)]),
    ], RECORD_SIZE)
    return padded(bytes(b.data))


def corn_point(data: bytes) -> Optional[int]:
    """The index of the talk point build_garage added (None when `data` is not such a file)."""
    n = _u32(data, H_TALKS + 4)
    if n < 2:
        return None
    entry = data[_u32(data, H_TALKS) + (n - 1) * TALK_SIZE:][:TALK_SIZE]
    people = _u32(entry, 0x168)
    return n - 1 if _u32(entry, 0x16C) == 1 and _u32(data, people) == CORN_ID and _u32(entry, 4) == 0 else None


class GaragePatch:
    """Reads the original Garage mission and talk files once and writes Corn's versions into the engine's cache mirror."""

    def __init__(self, root: str):
        self.root = root
        self.error = ""
        self.applied = False
        self.status_shown: Optional[List[jsrf_talk.Page]] = None
        self.originals: Dict[str, bytes] = {}          # cache path -> the original bytes (Media copy)
        self.mission_cache = jsrf_talk.cache_file(root, GARAGE_FILE)
        self.question_cache = jsrf_talk.cache_file(root, talk_parts(QUESTION_TALK))
        self.status_cache = jsrf_talk.cache_file(root, talk_parts(STATUS_TALK))
        self.mission: Optional[bytes] = None
        self.speaker: Optional[bytes] = None           # TE001 (Corn's face and voice, the four-page layout)
        self.template: Optional[bytes] = None          # TE124 (the Yes / No layout)
        try:
            files = {}
            for name, parts in (("garage", GARAGE_FILE), ("corn", CORN_FILE), ("question", talk_parts(QUESTION_TALK)),
                                ("status", talk_parts(STATUS_TALK)), ("te001", jsrf_talk.TALK),
                                ("te124", jsrf_talk.CHOICE_TEMPLATE)):
                path = jsrf_talk.media_file(root, parts)
                if not path:
                    raise GarageError("could not find %s under %s" % ("\\".join(parts), root))
                with open(path, "rb") as f:
                    files[name] = f.read()
            self.mission = build_garage(files["garage"], files["corn"])
            jsrf_talk.check_template(files["te001"])
            jsrf_talk.check_choice_template(files["te124"])
            self.speaker, self.template = files["te001"], files["te124"]
            self.originals = {self.mission_cache: files["garage"], self.question_cache: files["question"],
                              self.status_cache: files["status"]}
        except (OSError, GarageError, jsrf_talk.TalkError) as e:
            self.mission = None
            self.error = str(e)

    @property
    def ok(self) -> bool:
        return self.mission is not None

    @staticmethod
    def _write(path: str, data: bytes):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                if f.read() == data:
                    return
        with open(path, "r+b" if os.path.isfile(path) else "wb") as f:
            f.write(data)
            f.truncate(len(data))

    def question_file(self, question: Tuple[jsrf_talk.Page, jsrf_talk.Page, jsrf_talk.Page]) -> bytes:
        return padded(jsrf_talk.build_choice(self.template, self.speaker, *question))

    def status_file(self, pages: Sequence[jsrf_talk.Page]) -> bytes:
        return padded(jsrf_talk.build(self.speaker, pages, 1 << 16).rstrip(b"\0"))

    def apply(self, question, status_pages) -> bool:
        """Write the Garage mission and both of Corn's talks. False (with self.error set) when that did not work; the
        files already written are put back then."""
        if not self.ok:
            return False
        try:
            q, s = self.question_file(question), self.status_file(status_pages)
            self._write(self.question_cache, q)
            self._write(self.status_cache, s)
            self._write(self.mission_cache, self.mission)     # last: Corn stands there only once his talks are ready
        except (OSError, jsrf_talk.TalkError) as e:
            self.error = "could not write Corn's Garage files: %s" % e
            self.restore()
            return False
        self.error = ""
        self.applied = True
        self.status_shown = list(status_pages)
        return True

    def write_status(self, pages: Sequence[jsrf_talk.Page]) -> bool:
        """Rewrite what Corn says while the Tower is shut (read by the game at the next Garage load)."""
        if not self.applied:
            return False
        if self.status_shown == list(pages):
            return True
        try:
            self._write(self.status_cache, self.status_file(pages))
        except (OSError, jsrf_talk.TalkError) as e:
            self.error = "could not write Corn's Garage talk: %s" % e
            return False
        self.status_shown = list(pages)
        return True

    def restore(self) -> bool:
        """Put the game's own files back (the mission first, so Corn's talk point never points at a missing talk)."""
        good = True
        for path in (self.mission_cache, self.question_cache, self.status_cache):
            original = self.originals.get(path)
            if original is None:
                continue
            try:
                self._write(path, padded(original))
            except OSError as e:
                self.error = "could not put back %s: %s" % (path, e)
                good = False
        self.applied = False
        self.status_shown = None
        return good


# ---- Mystery Tapes in the free-skate area missions (2026-11-19 evening) ----------------------------------------------
# An area mission places its tape from the table at header +0x10C / +0x110 (16 bytes per tape: position, then the tape
# number N), with op 0x76 at the start (0x5A351 -> 0x43B80). The tape object keeps N at +0x50 and hands it to its pickup
# (collision entry +0x20 -> 0x44840(N)); it shows itself only while Riddle Tape flag N is clear and its pickup sequence sets
# flag N and the five challenge open flags when it ends. The client's copies of the free-skate missions (mssn09xx) number
# the tape 13 + N instead, its pickup record flag (game.TAPE_PICKED): the tape shows itself until it is picked up, and the
# pickup sequence's destructor sets 13 + N (and 97 + 5N .. 101 + 5N in place of the open flags; no script or native code
# uses 97-161), so the game records the pickup and the tape removes itself the vanilla way. Flag N can then follow the
# tape ITEM (the pause menu's tape and challenges, the fifth challenge's op 0x6A).
# Until 2026-11-25 the copies carried 0x200 + N, whose flag the game can neither test nor set: the pickup set nothing and
# the tape stayed until the client took it away. Whenever the client was not watching (connection to the server down, the
# client closed with the copies still in place, ...), the player, still standing on the tape when its sequence ended,
# picked it up again at once, without end (user report 2026-11-25: stuck in the pickup animation, the tape impossible to
# pick up).
H_TAPES = 0x10C
TAPE_ENTRY = 16
TAPE_NUMBERED = 13                     # the number the client's copies give a tape: 13 + N (= game.TAPE_PICKED[N])
TAPE_MISSION_PREFIX = "mssn09"         # the free-skate chapter's missions (file = mssn + hi + lo % 100)


def tape_entries(data: bytes) -> List[Tuple[int, int]]:
    """(file offset of the number, tape number) of each tape the mission places; [] when it has none."""
    if len(data) < 0x1A0:
        return []
    at, n = _u32(data, H_TAPES), _u32(data, H_TAPES + 4)
    if not n or n > 16 or at <= 0 or at + n * TAPE_ENTRY > len(data):
        return []
    return [(at + k * TAPE_ENTRY + 12, _u32(data, at + k * TAPE_ENTRY + 12)) for k in range(n)]


def build_tape_mission(data: bytes) -> Optional[bytes]:
    """The mission with each of its tapes numbered 13 + N (None when it places no Mystery Tape)."""
    entries = [(off, n) for off, n in tape_entries(data) if 0 <= n < 13]
    if not entries:
        return None
    out = bytearray(data)
    for off, n in entries:
        struct.pack_into("<I", out, off, TAPE_NUMBERED + n)
    return padded(bytes(out))


class TapeMissions:
    """The client's copies of the free-skate area missions with re-numbered tapes, in the engine's cache mirror."""

    def __init__(self, root: str):
        self.root = root
        self.error = ""
        self.applied = False
        self.files: List[Tuple[str, str]] = []         # (original in Media, cache copy) of each mission with a tape
        media = jsrf_talk.media_file(root, GARAGE_FILE)
        if not media:
            self.error = "could not find Media\\Mission under %s" % root
            return
        folder, cache = os.path.dirname(media), os.path.dirname(jsrf_talk.cache_file(root, GARAGE_FILE))
        try:
            names = sorted(n for n in os.listdir(folder)
                           if n.lower().startswith(TAPE_MISSION_PREFIX) and n.lower().endswith(".bin"))
            for name in names:
                with open(os.path.join(folder, name), "rb") as f:
                    head = f.read(0x1A0)
                if len(head) == 0x1A0 and 0 < _u32(head, H_TAPES + 4) <= 16:
                    self.files.append((os.path.join(folder, name), os.path.join(cache, name)))
        except OSError as e:
            self.error = "could not read the missions in %s: %s" % (folder, e)
            self.files = []

    @property
    def ok(self) -> bool:
        return bool(self.files)

    def apply(self) -> int:
        """Write the re-numbered copies. Returns how many missions carry a tape that way (0 with self.error set when none
        could be written)."""
        done = 0
        for media, cache in self.files:
            try:
                with open(media, "rb") as f:
                    data = build_tape_mission(f.read())
                if data is not None:
                    GaragePatch._write(cache, data)
                    done += 1
            except OSError as e:
                self.error = "could not write %s: %s" % (cache, e)
        self.applied = done > 0
        return done

    def restore(self) -> bool:
        """Put the game's own missions back."""
        good = True
        for media, cache in self.files:
            try:
                with open(media, "rb") as f:
                    original = f.read()
                if build_tape_mission(original) is not None:
                    GaragePatch._write(cache, padded(original))
            except OSError as e:
                self.error = "could not put back %s: %s" % (cache, e)
                good = False
        self.applied = False
        return good
