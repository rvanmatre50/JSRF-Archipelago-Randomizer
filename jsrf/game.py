"""Game-side access for Jet Set Radio Future (JSRF Unleashed). No Archipelago imports, so it can be tested alone.

Memory facts (all found from the user's default.xbe and live runs; see the project notes):
  * Xbox virtual addresses are read from the engine process (engine\\jsrf_recomp.exe) via ReadProcessMemory.
  * The story-flag manager is at 0x1EFFB0. At +0xD8 / +0xF8 / +0x118 it holds three 256-bit arrays,
    "Graffiti Soul Appear" / "Get" / "Possess". Bit N of an array is the soul with wiki number N+1.
  * Ids 0-3, 28-31, 56-59, 84-87 and 112-115 are the Test Run souls. The game sets them in every array at
    start-up; they are not locations, and seeing them all set tells us a game state is loaded.
"""
import ctypes
import struct
import sys
import time
from typing import Dict, Optional, Set, Tuple

from . import procmem
from .data import (AREAS, AREA_LOCATIONS, BASE_ID, GAME_AREA_INDEX, STAGE_AREAS, TAG_SPOTS, TAPE_FLAG, tag_id,
                   RIVAL_BATTLES, rival_location_id, TEST_RUNS, JET_RANK, JET_LOCATION_OF)

FLAG_MGR = 0x001EFFB0
SOUL_APPEAR = FLAG_MGR + 0xD8      # 0x1F0088
SOUL_GET = FLAG_MGR + 0xF8         # 0x1F00A8
SOUL_POSSESS = FLAG_MGR + 0x118    # 0x1F00C8
MISSION_FLAGS = FLAG_MGR + 0x6A14    # story flag bank 0 ("Mission"), 512 bits, LSB first
SOUL_ARRAY_BYTES = 32              # 256 bits

TEST_RUN_IDS = frozenset(b * 28 + k for b in range(5) for k in range(4))   # 0-3, 28-31, 56-59, 84-87, 112-115
_PRESET_MASK = sum(1 << i for i in TEST_RUN_IDS)
# Possess bits the client may set so the game's soul counter shows the Graffiti Soul items received: ids no soul uses
# (140-255), then the 20 default graffiti. All have area -1 in the soul -> area table 0x1F8C38, so no area count moves.
COUNTER_FILLER_IDS = tuple(range(140, 256)) + tuple(sorted(TEST_RUN_IDS))
_FILLER_MASK = sum(1 << i for i in COUNTER_FILLER_IDS)

GAME_MGR_PTR = 0x0022FCE0          # pointer to the game manager
LOADER_SLOT = 0x98 + 4 * 7         # manager sub-object #7 is the stage loader
STAGE_CODE = 0x1D4                 # last requested packed stage code (hi << 16 | lo), 0 in the Garage
XBOX_RAM = 64 * 1024 * 1024

# Mission objects (default.xbe constructor 0x4A910, vtable 0x1CAAB0). Writing hi, lo and then state 93 makes the engine build
# and fade into another mission: the same three writes its own F6 map selector does. Confirmed live with jsrf_flow.py.
MISSION_VTABLE = 0x001CAAB0
M_HI, M_NEXT_LO, M_ID, M_STATE = 0x4C, 0x54, 0x58, 0x5C
M_RECORD = 0x1040                  # pointer to the mission's loaded .bin; its first dword is the mission's own stage code
M_ANSWER = 0x2A0                   # answer of the mission's last Yes / No talk (state 0x1E passes &mission[+0x2A0] to the talk)
STATE_RUNNING = 15
STATE_START_NEXT = 0x5D            # handler 0x539B0: build mission (hi = [+0x4C], lo = [+0x54]) and fade out
STATE_COUNT = 0x77
HEAP = (0x00290000, XBOX_RAM)
GARAGE_LO = 97                     # mssn0N97 is the Garage of chapter N
FREE_SKATE_CHAPTER = 9             # its Garage has every door open (the story chapters 1-5 keep them shut)

# The manager's variable array: variable k is the dword at manager + VAR_BASE + 4 * k (setter 0x127C0, getter 0x127E0).
# Variable 0x198 is the start-point index the next spawn uses (read at 0x53D9A and 0x5692B, set to -1 or to a door's index
# by the player update at 0x810BA when a door trigger is left or entered).
VAR_BASE = 0x7868
START_VAR = 0x198
START_SANE = range(-1, 256)        # anything else read there means the address is wrong, and then nothing is written
START_HOLD = 1.0                   # seconds the index is re-asserted after the mission change is requested
START_HOLD_STEP = 0.02
# Variable 6 is where a Garage entry's character select goes when the player has picked: mssnN97's only exit is type 257
# (0x53FB0 -> state 0x67, handler 0x53C00: build mission (hi = [+0x4C], lo = variable 6)). A New Game leaves it 0, a Continue
# loads it from the save (0x7C59D, flag manager +8), the F6 selector sets it from its table (0x1378FD) and Roboy's Test Run
# menu sets it to the Test Run's stage (0x765D7, e.g. 12 for Dogenzaka). After a Test Run, 9:97 therefore went on to 9:12
# (mssn0912 does not exist: the loader retried forever, a freeze; 2026-11-19 19:38). Sending to a Garage entry now sets it
# to that chapter's hub (lo N00, mssnN00; the game's own value for the free-skate hub is 900).
SELECT_EXIT_VAR = 6
SELECT_EXIT_SANE = range(-1, 10000)  # anything else read there means the address is wrong, and then nothing is written

# Graffiti tag spots (default.xbe 0x3E690-0x3F4A0, see discovery-findings.md "Graffiti tag spots"). The graffiti manager keeps
# the loaded stage's spots in a list; the story flag manager keeps every area's saved record: 16 areas x 80 slots x 2 dwords
# (part state, aux). A spot's part state has 3 bits per part, 7 = that part is not sprayed yet. The game copies the live
# state into the record when it saves and at a mission change, so the live list gives a check at once and the record
# covers areas that are not loaded.
GRAFFITI_MGR = 0x002314B0
SPOT_LIST = 0x808                  # head of the list of loaded spots; next spot at spot + 0x10C
SPOT_PARTS, SPOT_STATE, SPOT_STAGE, SPOT_SLOT, SPOT_NEXT = 0x98, 0xA4, 0xB8, 0xBC, 0x10C
TAG_RECORD = FLAG_MGR + 4 * 0x5E   # 0x1F0128; slot (area, s) at + 8 * (area * 80 + s)
# Test Run top-5 tables (data.TEST_RUNS): 8 bytes per ((area index * 4 + type) * 5 + slot), slot 0 = best; rank byte +6, +5 for
# Jet Tech (type 1). 16 area indexes * 4 types * 5 slots.
JET_RECORDS = FLAG_MGR + 0x2A9C    # 0x1F2A4C
JET_RECORDS_SIZE = 16 * 4 * 5 * 8
JET_RANK_MAX = 15                  # a rank byte above this is not a rank (unloaded or foreign data)
TAG_SLOTS = 80
TAG_AREAS = 16
MAX_SPOTS = 1024


def tag_done(state: int, parts: int) -> bool:
    """True when none of the spot's first `parts` pieces is still 7 (unsprayed)."""
    return all((state >> (3 * i)) & 7 != 7 for i in range(min(parts, 10)))


TAG_PARTS = {(area, slot): parts for area in AREAS for slot, parts in TAG_SPOTS[area]}

# Character roster (default.xbe 0x39CB0 set / 0x39CF0 clear / 0x39D10 test): one bit per character id. The game's unlock also
# writes -1 to manager variable 0x151 + id; jsrf_roster.py does the same writes and was confirmed in play (Roboy, Beat).
ROSTER = FLAG_MGR + 0x14           # 0x1EFFC4
CHAPTER_NUMBER = FLAG_MGR + 0x4    # the Test Run character reward needs 9
CHAR_VAR = 0x151
CURRENT_CHAR_VAR = 0xD             # the character you play as (character select writes it; New Game sets 6 = Yoyo)
# Roboy's Test Run menu (static, default.xbe, 2026-11-17). Factory 0x75DE0 builds it (ctor 0x75A30, vtable 0x1CCCD8) and
# registers it in manager object slot 0x128A (0x12870: *(mgr + 0x98 + 4 * slot)); the slot is empty while the menu is shut.
# The builder 0x756E0 runs once at construction: nothing at all unless the chapter number is 9; then an area's Test Runs are
# enabled only when every Graffiti Soul of the area is possessed. Layout: +0xB4 -> the top menu (6 x 16-byte options, copied
# from 0x20D0D0; +0x58 = option 5's enabled flag, the Test Run entry), +0xCC -> 4 categories x 16 bytes (+8 enabled; type 0
# Graffiti, 1 Tech, 2 Dash, 3 Flag), +0xD4 / +0xD8 / +0xDC / +0xE0 -> the four lists (13 / 13 / 6 / 7 entries x 16 bytes:
# +0 index into the 14 stage codes of 0x21C098, +8 enabled). The client rewrites the enabled flags by Unlock item.
# The destructor (0x74D75) frees the lists and sets variable 0x1A2 := 1 (the constructor sets it to 0) but leaves the slot
# pointing at the freed object (the base destructor 0x11000 changes its vtable), so both are checked.
TEST_MENU_SLOT = 0x128A
TEST_MENU_VTABLE = 0x1CCCD8
TEST_MENU_CLOSED_VAR = 0x1A2

# The pause menu (the map screen): opening it builds an object (factory 0x78C19 -> constructor 0x78520, vtable 0x1CCD18)
# in manager slot 0x1167. The constructor copies the Graffiti Soul total (0x39FD0, the Possess bits) into +0x1B0 and the
# current area's count (0x3A130) into +0x1B4; the screen's draw code (0x112D21) prints +0x1B0 with "%d" every frame. So
# writing +0x1B0 while the menu is open changes only the number shown (user, 2026-11-19 22:21: the map screen should show
# the Graffiti Soul items received, not the souls picked up). +0x1BC / +0x1C0 ("%d(%d%%)") are graffiti progress.
PAUSE_MENU_SLOT = 0x1167
PAUSE_MENU_VTABLE = 0x1CCD18
PAUSE_MENU_SOULS = 0x1B0
TM_TOP, TM_TOP_TESTRUN, TM_CATEGORIES = 0xB4, 0x58, 0xCC
TM_LISTS = ((0xD4, 13), (0xD8, 13), (0xDC, 6), (0xE0, 7))          # by type: Graffiti, Tech, Dash, Flag
TEST_MENU_STAGES = (0x10000, 0x10001, 0x10002, 0x10003, 0x20000, 0x20001, 0x20002, 0x20003, 0x20004,
                    0x30000, 0x30001, 0x30002, 0x30003, 0x30004)
CHOSEN_CHAR_VAR = 0x1AC            # a chosen character the mission copies into 0xD when it is not -1 (0x53E81)

# The player object (static, 2026-11-17). Script op 0x22 (player stat test, 0x572B0) finds it as: controller =
# manager object slot 12 + player number (0x128C0: *(mgr + 0x98 + 4 * slot)); player = slot *(controller + 0x8D4). The HUD
# (0x735D9) reads the same fields. Spray cans: small can +1, big can +5, capped at the max (pickup 0x8E648 / 0x8E673);
# tagging subtracts (0x7FC60). Health: a health pickup adds a per-character amount up to the max (0x8E6A0). When the player
# object is destroyed (0x7E9AC) the game saves cans into game variable 0x172 and health into 0x151 + character, and the
# next area's player starts from them (0x843C4 / 0x843E4), so a write to the live object carries over.
PLAYER_CTRL_SLOT = 12              # manager object slot of player 1's controller (op 0x22: arg0 + 0xC)
CTRL_PLAYER_SLOT = 0x8D4           # controller field: manager object slot of the player character
P_HEALTH = 0xF98
P_HEALTH_MAX = 0xF9C
P_CANS = 0xFA0
P_CANS_MAX = 0xFA4
P_CHAR = 0xFBC                     # character id (health is saved in variable 0x151 + this)
P_FIELDS = 0x28                    # bytes read from P_HEALTH

XBE_VA = 0x10000                   # the XBE header "XBEH" sits here, so the view's start is Xbox address 0
ENGINE_EXE = "jsrf_recomp.exe"


def soul_location_ids() -> Dict[int, int]:
    """soul id (wiki number - 1) -> Archipelago location id, for every soul in the location list."""
    out: Dict[int, int] = {}
    for i, area in enumerate(AREAS):
        for j, loc in enumerate(AREA_LOCATIONS[area]):
            if loc.soul_no:
                out[loc.soul_no - 1] = BASE_ID + 100 * i + j
    return out


SOUL_LOCATIONS = soul_location_ids()
RIDDLE_TAPE_FLAGS = FLAG_MGR + 0x98    # story flag bank 3 ("Riddle Tape"), 512 bits, LSB first; Mystery Tape N = bit N
# Mystery Tape pickup (default.xbe, 2026-11-19): touching a tape (the player's pickup switch, 0x8E7C8) creates a short
# "tape got" sequence object (0x44840 -> constructor 0x44660; vtable 0x1CA708, 0xA8 bytes) as a child of manager object
# slot 9, with the tape number N at +0xA4. When the sequence ends its destructor (0x43950) sets Riddle Tape flag N and the
# five Street Challenge open flags 32 + 5N + i. The flag setter (0x39BE0) ignores an index of 0x200 or more, so writing
# 0x200 + N to +0xA4 while the sequence plays makes the destructor set nothing; the client then sets flag N itself.
# Object tree (0x12020): +0x24 parent, parent +0x28 first child, +0x30 next sibling.
# The tape lying in the level (2026-11-19): vtable 0x1CA6C8, made by 0x43B80 in a free manager slot from 0x15B4 to 0x19B4
# (0x128E0 searches that range), tape number N at +0x50. Its constructor sets +0x60 ("shown") only while flag N is clear;
# its update (0x438C0) clears +0x60 once flag N is set, and 0x43910 deletes the object once +0x60 is 0.
TAPE_OBJ_VTABLE = 0x001CA6C8
TAPE_OBJ_SLOTS = (0x15B4, 0x19B4)    # inclusive
TO_TAPE, TO_SHOWN = 0x50, 0x60
TAPE_EVENT_VTABLE = 0x001CA708
TAPE_EVENT_PARENT_SLOT = 9
TE_TAPE = 0xA4
TE_SIZE = 0xA8
TAPE_DEFUSED = 0x200
OBJ_FIRST_CHILD, OBJ_NEXT_SIBLING = 0x28, 0x30
# Riddle Tape flag N -> the area's Mystery Tape location id
TAPE_LOCATIONS = {TAPE_FLAG[area]: BASE_ID + 100 * i + j for i, area in enumerate(AREAS)
                  for j, loc in enumerate(AREA_LOCATIONS[area]) if loc.kind == "tape"}
# With Mystery Tape items (2026-11-19 evening): flag N follows the tape ITEM (the pause menu shows an area's tape and its
# challenges only while flag N is set, and the area mission's op 0x6A needs it for the fifth challenge), so the pickup is
# recorded in a flag of its own, Riddle Tape 13 + N. Flags 13-31 are used by no mission script (scan of 191 files) and by no
# native code (every bank 3 access with a fixed number comes from the area table at 0x21C270, Roboy's 384+/416+ or a
# tape's own number). The levels' tapes carry 0x200 + N in the client's copies of the area missions (garage.py), so they
# stay out whatever flag N says and their pickup sets nothing by itself.
TAPE_PICKED_BASE = 13
TAPE_PICKED = {n: TAPE_PICKED_BASE + n for n in TAPE_LOCATIONS}
GLOBAL_FLAGS = FLAG_MGR + 0x58         # story flag bank 2 ("Global"), 512 bits, LSB first
# Fresh-save handling (2026-11-17): the client ties a save to its seed by writing a 32-bit marker into Global flags 480-511
# (the bank's last dword). The flag record is part of the save; New Game (0x3AED0, and the three menu variants 0x3B420 /
# 0x3B5A0 / 0x3B640 that call it) zeroes the whole record, so a new game starts with no marker. The mission scripts only use
# Global flags 1, 10-17 and 20-28 (scan of 191 mission files) and no native code addresses this bank with a constant.
SAVE_MARKER = GLOBAL_FLAGS + 0x3C
# Global flag a rival gang battle's win sets -> its location id (Doom Riders 15, Love Shockers 16, Immortals 17)
RIVAL_LOCATIONS = {r.flag: rival_location_id(r) for r in RIVAL_BATTLES}
# Ids of the souls a Street Challenge awards (the other 40 are pre-spawned in the level).
CHALLENGE_IDS = frozenset(loc.soul_no - 1 for area in AREAS for loc in AREA_LOCATIONS[area]
                          if loc.kind == "challenge_soul")


class JSRFGame:
    """Reads game state through any object with .read(xbox_va, n) -> bytes."""

    def __init__(self, reader):
        self.reader = reader
        self.start_note: Optional[Dict[str, object]] = None
        self.select_note: Optional[Dict[str, object]] = None

    def _soul_bits(self, va: int) -> Optional[int]:
        raw = self.reader.read(va, SOUL_ARRAY_BYTES)
        return int.from_bytes(raw, "little") if len(raw) == SOUL_ARRAY_BYTES else None

    def _u32(self, va: int) -> Optional[int]:
        raw = self.reader.read(va, 4)
        return struct.unpack("<I", raw)[0] if len(raw) == 4 else None

    def current_stage(self) -> Optional[int]:
        """Packed code of the stage the engine last loaded (0 = Garage), or None while the manager is not set up.
        Confirmed live: F6 jumps to Dogenzaka Hill, Shibuya, Chuo St, Hikage St, Rokkaku-dai and the Sewage
        Facility gave 0x10002, 0x10000, 0x10001, 0x10003, 0x20000 and 0x20001."""
        gm = self._u32(GAME_MGR_PTR)
        if not gm or gm >= XBOX_RAM - 0x400:
            return None
        loader = self._u32(gm + LOADER_SLOT)
        if not loader or loader >= XBOX_RAM - 0x400:
            return None
        return self._u32(loader + STAGE_CODE)

    # ---- mission object and the bounce (the only place the client writes to the game) ----

    def mission_stage(self, addr: int) -> Optional[int]:
        """The stage code of the mission object at addr, from its loaded mission file (first dword: 0 Garage, 0x10002
        Dogenzaka, 0x40000 the Tower, ...), or None when the pointer or the value cannot be read."""
        ptr = self._u32(addr + M_RECORD)
        if not ptr or ptr >= XBOX_RAM - 4:
            return None
        return self._u32(ptr)

    def _mission_at(self, addr: int) -> Optional[Dict[str, int]]:
        """The mission object at addr, or None when it is not (or no longer) one."""
        raw = self.reader.read(addr, 0x60)
        if len(raw) != 0x60:
            return None
        f = struct.unpack("<24I", raw)
        mid, state = f[M_ID // 4], f[M_STATE // 4]
        if f[0] == MISSION_VTABLE and state < STATE_COUNT and (mid >> 16) < 0x100 and (mid & 0xFFFF) < 0x1000:
            return {"addr": addr, "id": mid, "state": state, "hi": f[M_HI // 4]}
        return None

    def find_missions(self) -> list:
        """Every live mission object, found by its vtable. Reads the Xbox heap (about 64 MB); under a second."""
        needle = struct.pack("<I", MISSION_VTABLE)
        out, step, page = [], 0x10000, 0x1000
        addr = HEAP[0]
        while addr < HEAP[1]:
            n = min(step, HEAP[1] - addr)
            data = self.reader.read(addr, n)
            pieces = [(addr, data)] if len(data) == n else [
                (a, self.reader.read(a, min(page, HEAP[1] - a))) for a in range(addr, addr + n, page)]
            for base, blob in pieces:
                pos = blob.find(needle)
                while pos != -1:
                    if pos % 4 == 0:
                        m = self._mission_at(base + pos)
                        if m:
                            out.append(m)
                    pos = blob.find(needle, pos + 1)
            addr += n
        return out

    def running_mission(self, cached: Optional[int] = None) -> Optional[Dict[str, int]]:
        """The mission object that is running now (the only one in state 15, else the only one there is). Tries the
        cached address first, then scans. None when there is none or it is ambiguous."""
        if cached:
            m = self._mission_at(cached)
            if m:
                return m
        found = self.find_missions()
        running = [m for m in found if m["state"] == STATE_RUNNING]
        if len(running) == 1:
            return running[0]
        return found[0] if len(found) == 1 else None      # none, or ambiguous: do not guess which one to write to

    def start_index_addr(self) -> Optional[int]:
        gm = self._u32(GAME_MGR_PTR)
        if not gm or gm >= XBOX_RAM - VAR_BASE - 4 * (START_VAR + 1):
            return None
        return gm + VAR_BASE + 4 * START_VAR

    def start_index(self) -> Optional[int]:
        """The start-point index the next spawn will use (-1 = none), or None when it cannot be read."""
        addr = self.start_index_addr()
        raw = self.reader.read(addr, 4) if addr else b""
        return struct.unpack("<i", raw)[0] if len(raw) == 4 else None

    def set_start_index(self, value: int) -> bool:
        """Write the start-point index. Refuses (False) when the value read there is not a plausible index, which would
        mean the address is wrong."""
        write = getattr(self.reader, "write", None)
        addr = self.start_index_addr()
        if write is None or addr is None or self.start_index() not in START_SANE:
            return False
        return bool(write(addr, struct.pack("<i", value))) and self.start_index() == value

    def hold_start_index(self, value: int, seconds: Optional[float] = None, step: Optional[float] = None) -> int:
        """Keep the index at `value` for a moment (the old player object can still reset it to -1 for a frame or two
        after the mission change is requested). Returns how many times it had to be put back."""
        seconds = START_HOLD if seconds is None else seconds
        step = START_HOLD_STEP if step is None else step
        fixed, end = 0, time.monotonic() + seconds
        while time.monotonic() < end:
            if self.start_index() != value and self.set_start_index(value):
                fixed += 1
            time.sleep(step)
        return fixed

    def var_addr(self, k: int) -> Optional[int]:
        gm = self._u32(GAME_MGR_PTR)
        if not gm or gm >= XBOX_RAM - VAR_BASE - 4 * (k + 1):
            return None
        return gm + VAR_BASE + 4 * k

    def select_exit(self) -> Optional[int]:
        """Variable 6: the lo a Garage entry's character select goes to (signed), or None when it cannot be read."""
        addr = self.var_addr(SELECT_EXIT_VAR)
        raw = self.reader.read(addr, 4) if addr else b""
        return struct.unpack("<i", raw)[0] if len(raw) == 4 else None

    def set_select_exit(self, lo: int) -> bool:
        """Write variable 6. Refuses (False) when the value read there is implausible (wrong address)."""
        write = getattr(self.reader, "write", None)
        addr = self.var_addr(SELECT_EXIT_VAR)
        if write is None or addr is None or self.select_exit() not in SELECT_EXIT_SANE:
            return False
        return bool(write(addr, struct.pack("<i", lo))) and self.select_exit() == lo

    def send_to_mission(self, mission: Dict[str, int], hi: int, lo: int, start: Optional[int] = None) -> bool:
        """Start mission (hi, lo) by writing hi, lo, then state last (what F6 does). True when the writes took.
        With `start` the start-point index is written first, so the new mission places the player at that record of its
        start table instead of wherever the last door trigger left the variable. self.start_note says what happened.
        For a Garage entry (lo 97) variable 6 is set to the chapter's hub first, so its character select goes there
        (self.select_note)."""
        write = getattr(self.reader, "write", None)
        if write is None:
            return False
        a = mission["addr"]
        self.start_note = None
        self.select_note = None
        if start is not None:
            before = self.start_index()
            done = self.set_start_index(start)
            self.start_note = {"before": before, "wanted": start, "written": done, "fixed": 0}
        if lo == GARAGE_LO:
            hub = hi * 100
            before = self.select_exit()
            self.select_note = {"before": before, "wanted": hub,
                                "written": before == hub or self.set_select_exit(hub)}
        ok = write(a + M_HI, struct.pack("<I", hi))
        ok = write(a + M_NEXT_LO, struct.pack("<I", lo)) and ok
        ok = write(a + M_STATE, struct.pack("<I", STATE_START_NEXT)) and ok
        back = self.reader.read(a + M_HI, 4) + self.reader.read(a + M_NEXT_LO, 4)
        good = bool(ok) and back == struct.pack("<II", hi, lo)
        if good and self.start_note and self.start_note["written"] and START_HOLD > 0:
            self.start_note["fixed"] = self.hold_start_index(start)
        return good

    def send_to_garage(self, mission: Dict[str, int], chapter: int = FREE_SKATE_CHAPTER, start: Optional[int] = None) -> bool:
        """Start the Garage of `chapter`."""
        return self.send_to_mission(mission, chapter, GARAGE_LO, start)

    def mission_flag(self, n: int) -> Optional[bool]:
        """Mission-bank story flag n, or None when it cannot be read."""
        raw = self.reader.read(MISSION_FLAGS + n // 8, 1)
        if len(raw) != 1:
            return None
        return bool(raw[0] >> (n % 8) & 1)

    def set_mission_flags(self, values: Dict[int, bool]) -> bool:
        """Set or clear Mission-bank story flags ({flag number: wanted value}), one byte at a time, touching only the bits
        asked for. True when every byte reads back as written."""
        return self._set_flags(MISSION_FLAGS, values)

    def set_riddle_flags(self, values: Dict[int, bool]) -> bool:
        """The same for the Riddle Tape bank (Mystery Tapes and the Street Challenge flags they open)."""
        return self._set_flags(RIDDLE_TAPE_FLAGS, values)

    def world_tapes(self) -> list:
        """The tapes lying in the current level, as (object address, tape number, shown)."""
        gm = self._u32(GAME_MGR_PTR)
        if not gm or gm >= XBOX_RAM - 0x8000:
            return []
        lo, hi = TAPE_OBJ_SLOTS
        raw = self.reader.read(gm + 0x98 + 4 * lo, 4 * (hi - lo + 1))
        if len(raw) != 4 * (hi - lo + 1):
            return []
        out = []
        for (ptr,) in struct.iter_unpack("<I", raw):
            if not ptr or ptr >= XBOX_RAM - 0x64:
                continue
            obj = self.reader.read(ptr, 0x64)
            if len(obj) == 0x64 and struct.unpack_from("<I", obj, 0)[0] == TAPE_OBJ_VTABLE:
                out.append((ptr, struct.unpack_from("<I", obj, TO_TAPE)[0], struct.unpack_from("<I", obj, TO_SHOWN)[0] != 0))
        return out

    def remove_world_tape(self, addr: int, tape: int) -> bool:
        """Make a tape lying in the level go away (it deletes itself once not shown), as if its flag had been seen set."""
        write = getattr(self.reader, "write", None)
        if write is None or self._u32(addr) != TAPE_OBJ_VTABLE or self._u32(addr + TO_TAPE) != tape:
            return False
        return bool(write(addr + TO_SHOWN, struct.pack("<I", 0))) and self._u32(addr + TO_SHOWN) == 0

    def tape_events(self) -> list:
        """The Mystery Tape sequences playing now, as (object address, value at +0xA4): the tape number N, or
        TAPE_DEFUSED + N once the client has defused it. Usually empty; one right after a tape is touched."""
        gm = self._u32(GAME_MGR_PTR)
        if not gm or gm >= XBOX_RAM - 0x400:
            return []
        parent = self._u32(gm + 0x98 + 4 * TAPE_EVENT_PARENT_SLOT)
        if not parent or parent >= XBOX_RAM - 0x40:
            return []
        node, seen, out = self._u32(parent + OBJ_FIRST_CHILD), set(), []
        while node and node < XBOX_RAM - TE_SIZE and node not in seen and len(seen) < 256:
            seen.add(node)
            raw = self.reader.read(node, TE_SIZE)
            if len(raw) != TE_SIZE:
                break
            if struct.unpack_from("<I", raw, 0)[0] == TAPE_EVENT_VTABLE:
                out.append((node, struct.unpack_from("<I", raw, TE_TAPE)[0]))
            node = struct.unpack_from("<I", raw, OBJ_NEXT_SIBLING)[0]
        return out

    def defuse_tape_event(self, addr: int, tape: int) -> bool:
        """Make a playing tape sequence set no flags when it ends (see TAPE_EVENT_VTABLE). True when it holds."""
        write = getattr(self.reader, "write", None)
        if write is None or self._u32(addr) != TAPE_EVENT_VTABLE or self._u32(addr + TE_TAPE) != tape:
            return False
        if not write(addr + TE_TAPE, struct.pack("<I", TAPE_DEFUSED + tape)):
            return False
        return self._u32(addr + TE_TAPE) == TAPE_DEFUSED + tape

    def riddle_bits(self) -> Optional[int]:
        """The first 320 Riddle Tape flags as one number (bit N = flag N; the challenge setup flags go up to 256), or None
        when unreadable."""
        raw = self.reader.read(RIDDLE_TAPE_FLAGS, 40)
        return int.from_bytes(raw, "little") if len(raw) == 40 else None

    def _set_flags(self, base: int, values: Dict[int, bool]) -> bool:
        write = getattr(self.reader, "write", None)
        if write is None:
            return False
        by_byte: Dict[int, Dict[int, bool]] = {}
        for n, value in values.items():
            by_byte.setdefault(n // 8, {})[n % 8] = bool(value)
        good = True
        for index, bits in sorted(by_byte.items()):
            raw = self.reader.read(base + index, 1)
            if len(raw) != 1:
                return False
            byte = raw[0]
            for bit, value in bits.items():
                byte = byte | (1 << bit) if value else byte & ~(1 << bit) & 0xFF
            if byte != raw[0]:
                good = bool(write(base + index, bytes([byte]))) and good
            back = self.reader.read(base + index, 1)
            good = good and len(back) == 1 and all(bool(back[0] >> bit & 1) == value for bit, value in bits.items())
        return good

    def ready(self) -> bool:
        """True once a game state is loaded (the Test Run souls are marked collected)."""
        bits = self._soul_bits(SOUL_GET)
        return bits is not None and bits & _PRESET_MASK == _PRESET_MASK

    def soul_counter(self) -> Optional[Tuple[int, int]]:
        """The game's Graffiti Soul counter (the number of Possess bits, 0x39FD0) split in two: (real, filler). Real =
        souls the game itself marked possessed (picked up, Test Run rewards); filler = bits the client set on
        COUNTER_FILLER_IDS. None when unreadable."""
        bits = self._soul_bits(SOUL_POSSESS)
        if bits is None:
            return None
        return bin(bits & ~_FILLER_MASK).count("1"), bin(bits & _FILLER_MASK).count("1")

    def set_soul_counter(self, target: Optional[int]) -> Optional[int]:
        """Make the counter show `target` by setting filler bits on top of the real souls (it cannot go below the real
        ones: their Possess bits decide when Roboy opens an area's Test Runs). None = the game's own count: no filler,
        the 20 default graffiti back. Returns the number of bits changed (0 = already right), or None when no game
        state is loaded or the write failed.
        Safe by the code: the spray-can design list tests Get (0x3A2B0), not Possess; the per-area soul count (0x3A130,
        Roboy's menu) skips every filler id (area -1 in the table at 0x1F8C38); only the script condition 'souls
        possessed >= N' (0x571F8) and the game's 'N more souls needed' texts see the different total. A mission
        script can copy Get into Possess (0x39F60) and undo the filler; the client sets it again on its next poll."""
        get = self._soul_bits(SOUL_GET)
        bits = self._soul_bits(SOUL_POSSESS)
        if get is None or bits is None or get & _PRESET_MASK != _PRESET_MASK:
            return None                                   # no game state loaded
        if target is None:
            want = {i: False for i in COUNTER_FILLER_IDS}
            want.update({i: True for i in TEST_RUN_IDS})
        else:
            real = bin(bits & ~_FILLER_MASK).count("1")
            n = max(0, min(len(COUNTER_FILLER_IDS), target - real))
            want = {i: k < n for k, i in enumerate(COUNTER_FILLER_IDS)}
        change = {i: v for i, v in want.items() if bool(bits >> i & 1) != v}
        if not change:
            return 0
        return len(change) if self._set_flags(SOUL_POSSESS, change) else None

    def collected_souls(self) -> Optional[Set[int]]:
        """Soul ids (wiki number - 1) the player has collected, or None while no game state is loaded."""
        bits = self._soul_bits(SOUL_GET)
        if bits is None or bits & _PRESET_MASK != _PRESET_MASK:
            return None
        return {i for i in range(256) if bits >> i & 1 and i not in TEST_RUN_IDS}

    def cleared_challenges(self) -> Set[int]:
        """Challenge soul ids whose 'Appear' bit is set. Confirmed in play (Dogenzaka Hill, all five challenges):
        clearing a Street Challenge sets only this bit; picking the soul up later sets Get and Possess."""
        bits = self._soul_bits(SOUL_APPEAR)
        if bits is None:
            return set()
        return {i for i in CHALLENGE_IDS if bits >> i & 1}

    def collected_tapes(self) -> Set[int]:
        """Location ids of the Mystery Tapes picked up (their pickup flag 13 + N is set; see TAPE_PICKED)."""
        raw = self.reader.read(RIDDLE_TAPE_FLAGS, 4)
        if len(raw) != 4:
            return set()
        bits = int.from_bytes(raw, "little")
        return {TAPE_LOCATIONS[n] for n, flag in TAPE_PICKED.items() if bits >> flag & 1}

    def talk_answer(self, mission_addr: Optional[int]) -> Optional[int]:
        """The answer of the last Yes / No talk in the mission object at `mission_addr` (+0x2A0: 1 = Yes / accept,
        0 = No / decline, -1 = none yet; written by the talk system, read by script ops 0x16 / 0x17), or None."""
        if not mission_addr:
            return None
        v = self._u32(mission_addr + M_ANSWER)
        return None if v is None else (v - (1 << 32) if v & 0x80000000 else v)

    def save_marker(self) -> Optional[int]:
        """The seed marker in the loaded save's flag record (0 = none), or None when it cannot be read."""
        return self._u32(SAVE_MARKER)

    def write_save_marker(self, value: int) -> bool:
        write = getattr(self.reader, "write", None)
        return bool(write and write(SAVE_MARKER, struct.pack("<I", value & 0xFFFFFFFF)))

    def won_rival_battles(self) -> Set[int]:
        """Location ids of the rival gang battles won (their Global flag is set)."""
        raw = self.reader.read(GLOBAL_FLAGS, 4)
        if len(raw) != 4:
            return set()
        bits = int.from_bytes(raw, "little")
        return {loc for flag, loc in RIVAL_LOCATIONS.items() if bits >> flag & 1}

    def collected_locations(self, challenge_on_clear: bool = False, tags: bool = False) -> Optional[Set[int]]:
        """Archipelago location ids for the souls collected so far (None while not ready).
        With challenge_on_clear, a Street Challenge also counts as soon as its soul appears; with tags, every fully
        sprayed tag spot of the tag table counts too."""
        souls = self.collected_souls()
        if souls is None:
            return None
        if challenge_on_clear:
            souls = souls | self.cleared_challenges()
        found = {SOUL_LOCATIONS[s] for s in souls if s in SOUL_LOCATIONS}
        found |= self.collected_tapes()
        found |= self.won_rival_battles()
        found |= {JET_LOCATION_OF[run] for run in (self.jet_ranks() or ())}     # Jet rank checks (the seed decides)
        if tags:
            found |= {tag_id(area, slot) for area, slot in self.sprayed_tags()}
        return found


    # ---- character roster ----

    def roster(self) -> Optional[int]:
        """The roster mask, or None when it cannot be read or does not look like a loaded game (bits above 23, or empty)."""
        mask = self._u32(ROSTER)
        if mask is None or mask & ~0xFFFFFF or not mask:
            return None
        return mask

    def chapter_number(self) -> Optional[int]:
        return self._u32(CHAPTER_NUMBER)

    def pause_menu(self) -> Optional[int]:
        """The pause menu object's address while it is open, else None (the slot can keep a destroyed object: its
        vtable is checked)."""
        gm = self._u32(GAME_MGR_PTR)
        if not gm or gm >= XBOX_RAM - 0x8000:
            return None
        obj = self._u32(gm + 0x98 + 4 * PAUSE_MENU_SLOT)
        if not obj or obj >= XBOX_RAM - 0x200 or self._u32(obj) != PAUSE_MENU_VTABLE:
            return None
        return obj

    def set_menu_souls(self, value: int) -> Optional[bool]:
        """Make the open pause menu show `value` as its Graffiti Soul total. True when written, False when it already
        showed it, None when no menu is open (or no write access)."""
        write = getattr(self.reader, "write", None)
        obj = self.pause_menu()
        if obj is None or write is None:
            return None
        shown = self._u32(obj + PAUSE_MENU_SOULS)
        if shown is None or shown > 0xFFFF:              # a soul total; anything else means it is not the menu we know
            return None
        if shown == value:
            return False
        return bool(write(obj + PAUSE_MENU_SOULS, struct.pack("<I", value)))

    def test_menu(self) -> Optional[dict]:
        """Roboy's Test Run menu while it is open and its lists are built (chapter 9): its address and, per type, the list
        entries as (entry address, stage code, enabled). None when it is shut, not built, or does not look right."""
        gm = self._u32(GAME_MGR_PTR)
        if not gm or gm >= XBOX_RAM - 0x8000:
            return None
        obj = self._u32(gm + 0x98 + 4 * TEST_MENU_SLOT)
        if not obj or obj >= XBOX_RAM - 0x200 or self._u32(obj) != TEST_MENU_VTABLE or self._var(TEST_MENU_CLOSED_VAR) != 0:
            return None
        top, cats = self._u32(obj + TM_TOP), self._u32(obj + TM_CATEGORIES)
        if not top or top >= XBOX_RAM - 0x60 or not cats or cats >= XBOX_RAM - 0x40:
            return None
        lists = []
        for off, count in TM_LISTS:
            ptr = self._u32(obj + off)
            if not ptr or ptr >= XBOX_RAM - 16 * count:
                return None
            raw = self.reader.read(ptr, 16 * count)
            if len(raw) != 16 * count:
                return None
            entries = []
            for i in range(count):
                idx, _, enabled = struct.unpack_from("<iII", raw, 16 * i)
                if not 0 <= idx < len(TEST_MENU_STAGES) or enabled > 1:
                    return None                      # not built (chapter number not 9) or not the menu we know
                entries.append((ptr + 16 * i, TEST_MENU_STAGES[idx], enabled))
            lists.append(entries)
        return {"addr": obj, "top": top, "cats": cats, "lists": lists}

    def open_test_menu(self, open_stages: Set[int]) -> Optional[int]:
        """Make Roboy's open Test Run menu offer exactly the Test Runs of the given stages (enabled flags of the entries,
        their categories and the top menu's Test Run option). Returns how many flags were changed (0 = already right), or
        None when the menu is not open / not built or the game cannot be written."""
        write = getattr(self.reader, "write", None)
        menu = self.test_menu()
        if menu is None or write is None:
            return None
        changed, any_open = 0, False
        for t, entries in enumerate(menu["lists"]):
            type_open = False
            for addr, stage, enabled in entries:
                want = 1 if stage in open_stages else 0
                type_open |= bool(want)
                if enabled != want:
                    if not write(addr + 8, struct.pack("<I", want)):
                        return None
                    changed += 1
            any_open |= type_open
            cat = menu["cats"] + 16 * t + 8
            if self._u32(cat) != int(type_open):
                write(cat, struct.pack("<I", int(type_open)))
                changed += 1
        top = menu["top"] + TM_TOP_TESTRUN
        if self._u32(top) != int(any_open):
            write(top, struct.pack("<I", int(any_open)))
            changed += 1
        return changed

    def set_chapter_number(self, n: int) -> bool:
        """Write the story chapter number (flag manager + 4; New Game sets 1, Roboy's Test Run menu and the Test Run
        character reward need 9). Refuses unless the current value reads as a chapter (0-9). True when it reads back."""
        write = getattr(self.reader, "write", None)
        cur = self.chapter_number()
        if write is None or cur is None or not 0 <= cur <= 9 or not 0 <= n <= 9:
            return False
        return bool(write(CHAPTER_NUMBER, struct.pack("<I", n))) and self.chapter_number() == n

    def set_roster(self, mask: int, added=()) -> bool:
        """Write the roster mask; for each id in `added` also write -1 to manager variable 0x151 + id (as the game's own
        unlock does). True when the mask reads back as written."""
        write = getattr(self.reader, "write", None)
        if write is None or mask & ~0xFFFFFF:
            return False
        ok = bool(write(ROSTER, struct.pack("<I", mask)))
        gm = self._u32(GAME_MGR_PTR)
        if ok and added and gm and gm < XBOX_RAM - 0x8000:
            for c in added:
                write(gm + VAR_BASE + 4 * (CHAR_VAR + c), struct.pack("<i", -1))
        return ok and self._u32(ROSTER) == mask

    def _var(self, k: int) -> Optional[int]:
        gm = self._u32(GAME_MGR_PTR)
        if not gm or gm >= XBOX_RAM - 0x8000:
            return None
        v = self._u32(gm + VAR_BASE + 4 * k)
        return None if v is None else (v - (1 << 32) if v & 0x80000000 else v)

    def player(self) -> Optional[Dict[str, int]]:
        """The live player object and its health and spray cans, or None when there is none (loading, menus) or the
        values do not look like a player's."""
        gm = self._u32(GAME_MGR_PTR)
        if not gm or gm >= XBOX_RAM - 0x400:
            return None
        ctrl = self._u32(gm + 0x98 + 4 * PLAYER_CTRL_SLOT)
        if not ctrl or ctrl >= XBOX_RAM - 0x1000:
            return None
        slot = self._u32(ctrl + CTRL_PLAYER_SLOT)
        if slot is None or not 0 <= slot < 0x100:
            return None
        addr = self._u32(gm + 0x98 + 4 * slot)
        if not addr or addr >= XBOX_RAM - 0x1000:
            return None
        raw = self.reader.read(addr + P_HEALTH, P_FIELDS)
        if len(raw) != P_FIELDS:
            return None
        f = lambda off: struct.unpack_from("<i", raw, off - P_HEALTH)[0]
        p = {"addr": addr, "health": f(P_HEALTH), "health_max": f(P_HEALTH_MAX), "cans": f(P_CANS),
             "cans_max": f(P_CANS_MAX), "char": f(P_CHAR)}
        if not (0 <= p["char"] < 24 and 0 < p["cans_max"] <= 999 and 0 <= p["cans"] <= p["cans_max"]
                and 0 < p["health_max"] <= 1_000_000 and 0 <= p["health"] <= p["health_max"]):
            return None
        return p

    def refill(self, cans: bool, health: bool) -> Optional[Dict[str, int]]:
        """Fill the live player's spray cans and/or health to their max. Returns the player values written, or None."""
        write = getattr(self.reader, "write", None)
        p = self.player()
        if write is None or p is None:
            return None
        ok = True
        if cans:
            ok &= bool(write(p["addr"] + P_CANS, struct.pack("<i", p["cans_max"])))
        if health:
            ok &= bool(write(p["addr"] + P_HEALTH, struct.pack("<i", p["health_max"])))
        return p if ok else None

    def current_character(self) -> Optional[int]:
        """The character you play as (game variable 0xD), or None when it cannot be read or is not a character id."""
        v = self._var(CURRENT_CHAR_VAR)
        return v if v is not None and 0 <= v < 24 else None

    def set_current_character(self, char: int) -> bool:
        """Play as `char` from the next level load on: variable 0xD, and 0x1AC too when it holds a choice."""
        write = getattr(self.reader, "write", None)
        gm = self._u32(GAME_MGR_PTR)
        if write is None or not gm or gm >= XBOX_RAM - 0x8000 or not 0 <= char < 24:
            return False
        if self._var(CURRENT_CHAR_VAR) is None or not -1 <= self._var(CURRENT_CHAR_VAR) < 24:
            return False                                     # not a character id: wrong address or no game loaded
        ok = bool(write(gm + VAR_BASE + 4 * CURRENT_CHAR_VAR, struct.pack("<i", char)))
        if self._var(CHOSEN_CHAR_VAR) not in (None, -1):
            ok = bool(write(gm + VAR_BASE + 4 * CHOSEN_CHAR_VAR, struct.pack("<i", char))) and ok
        return ok and self._var(CURRENT_CHAR_VAR) == char

    # ---- graffiti tags ----

    def loaded_spots(self) -> list:
        """The spots of the loaded stage: dicts with area (None if the stage is not one of ours), slot, parts, state."""
        out, seen = [], set()
        p = self._u32(GRAFFITI_MGR + SPOT_LIST)
        while p and p < XBOX_RAM - 0x200 and p not in seen and len(out) < MAX_SPOTS:
            seen.add(p)
            raw = self.reader.read(p + SPOT_PARTS, SPOT_NEXT + 4 - SPOT_PARTS)
            if len(raw) != SPOT_NEXT + 4 - SPOT_PARTS:
                break
            f = lambda off: struct.unpack_from("<I", raw, off - SPOT_PARTS)[0]
            out.append({"area": STAGE_AREAS.get(f(SPOT_STAGE)), "slot": f(SPOT_SLOT), "parts": f(SPOT_PARTS),
                        "state": f(SPOT_STATE)})
            p = f(SPOT_NEXT)
        return out

    def jet_ranks(self) -> Optional[Set[tuple]]:
        """(area, hi) of each Test Run whose best result is a Jet rank, from the save's top-5 tables. None when unreadable."""
        raw = self.reader.read(JET_RECORDS, JET_RECORDS_SIZE)
        if len(raw) != JET_RECORDS_SIZE:
            return None
        out = set()
        for run in TEST_RUNS:
            off = 8 * ((GAME_AREA_INDEX[run.area] * 4 + run.record_type) * 5)
            rank = raw[off + (5 if run.record_type == 1 else 6)]
            if JET_RANK <= rank <= JET_RANK_MAX:
                out.add((run.area, run.hi))
        return out

    def sprayed_tags(self) -> Set[tuple]:
        """(area, slot) of every listed tag spot that is fully sprayed: from the saved record of all areas, plus the
        spots of the loaded stage (which show a spray at once, before the game saves it)."""
        done: Set[tuple] = set()
        raw = self.reader.read(TAG_RECORD, TAG_AREAS * TAG_SLOTS * 8)
        if len(raw) == TAG_AREAS * TAG_SLOTS * 8:
            for area in AREAS:
                block = raw[GAME_AREA_INDEX[area] * TAG_SLOTS * 8:(GAME_AREA_INDEX[area] + 1) * TAG_SLOTS * 8]
                if not any(block):                    # an area record that was never written: nothing to read there
                    continue
                for slot, parts in TAG_SPOTS[area]:
                    if tag_done(struct.unpack_from("<I", block, 8 * slot)[0], parts):
                        done.add((area, slot))
        for spot in self.loaded_spots():
            key = (spot["area"], spot["slot"])
            if key in TAG_PARTS and tag_done(spot["state"], spot["parts"]):
                done.add(key)
        return done

    def unknown_spots(self) -> list:
        """Loaded spots of one of our areas whose slot is not in the tag table (so it has no location yet). Spots with no
        slot number (the Test Runs' own graffiti, slot -1) are not tag spots and are left out."""
        return [s for s in self.loaded_spots()
                if s["area"] and 0 <= s["slot"] < TAG_SLOTS and (s["area"], s["slot"]) not in TAG_PARTS]


class _WinReader:
    """ReadProcessMemory against the engine process. Windows only."""

    def __init__(self, handle, offset, k32, can_write=False, exe_path=None):
        self.h, self.off, self.k32 = handle, offset, k32
        self.can_write = can_write
        self.exe_path = exe_path          # full path of jsrf_recomp.exe, to find the game folder (None if Windows would not say)

    def read(self, va: int, n: int) -> bytes:
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t(0)
        ok = self.k32.ReadProcessMemory(self.h, ctypes.c_void_p(va + self.off), buf, n, ctypes.byref(got))
        return buf.raw[:got.value] if ok else b""

    def write(self, va: int, data: bytes) -> bool:
        if not self.can_write:
            return False
        put = ctypes.c_size_t(0)
        ok = self.k32.WriteProcessMemory(self.h, ctypes.c_void_p(va + self.off), data, len(data), ctypes.byref(put))
        return bool(ok) and put.value == len(data)

    def alive(self) -> bool:
        return len(self.read(XBE_VA, 4)) == 4


class _ProcReader:
    """The same reader interface as _WinReader, over /proc/<pid>/mem (Linux, and Android when run as root)."""

    def __init__(self, mem, offset, pid=None, name="", exe_path=None, game_dir=None):
        self.mem, self.off = mem, offset
        self.can_write = mem.can_write
        self.pid, self.name = pid, name
        self.exe_path = exe_path          # the engine's own path on Linux/Mac (None on Android, where the process is the app)
        self.game_dir = game_dir          # the Android app's files folder, when it can be seen

    def read(self, va: int, n: int) -> bytes:
        return self.mem.read(va + self.off, n)

    def write(self, va: int, data: bytes) -> bool:
        return self.can_write and self.mem.write(va + self.off, data)

    def alive(self) -> bool:
        return len(self.read(XBE_VA, 4)) == 4


def _attach_proc(write: bool = False) -> _ProcReader:
    """attach() for Linux and Android: find the process by name, open its memory, find the Xbox RAM by its XBE header."""
    import os
    found = procmem.find_pids()
    if not found:
        hint = (" If it is running, Android is hiding it from this app: start the client as root (su)."
                if procmem.is_android() else "")
        raise RuntimeError("The game is not running (no process named %s). Start the game first.%s"
                           % (" or ".join(procmem.MATCH), hint))
    pid, name = found[0]
    try:
        mem = procmem.ProcMem(pid, write)
    except OSError as e:
        raise RuntimeError(procmem.why_not(e))
    try:
        base = procmem.find_base(mem.read, procmem.read_maps(pid))
    except OSError as e:
        mem.close()
        raise RuntimeError(procmem.why_not(e))
    if base is None:
        mem.close()
        raise RuntimeError("Found the game process but not its Xbox memory.")
    exe, folders = None, procmem.game_dirs(name)
    if "/" in name or "." not in name:                       # a desktop engine: its path says where the game folder is
        try:
            exe = os.readlink("/proc/%d/exe" % pid)
        except OSError:
            exe = None
    return _ProcReader(mem, base, pid, name, exe, folders[0] if folders else None)


def _exe_path(k32, handle) -> Optional[str]:
    """Full path of the process behind `handle` (the handle needs PROCESS_QUERY_INFORMATION, which attach() asks for)."""
    try:
        from ctypes import wintypes as wt
        k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value or None
    except Exception:
        pass
    return None


def attach(write: bool = False) -> _WinReader:
    """Find the running engine and its Xbox memory. Raises RuntimeError with a plain message on failure.
    With write=True the handle also gets write rights; if Windows refuses those, the reader is read-only (can_write False).
    On Linux and Android the process is read through /proc/<pid>/mem (see procmem.py)."""
    if sys.platform != "win32":
        return _attach_proc(write)
    from ctypes import wintypes as wt
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k32.OpenProcess.restype = wt.HANDLE
    k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_char_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("pid", wt.DWORD), ("heap", ctypes.c_void_p),
                    ("module", wt.DWORD), ("threads", wt.DWORD), ("ppid", wt.DWORD), ("pri", wt.LONG),
                    ("flags", wt.DWORD), ("exe", wt.WCHAR * 260)]

    snap = k32.CreateToolhelp32Snapshot(2, 0)
    pe = PE()
    pe.dwSize = ctypes.sizeof(PE)
    pids, ok = [], k32.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        if pe.exe.lower() == ENGINE_EXE:
            pids.append(pe.pid)
        ok = k32.Process32NextW(snap, ctypes.byref(pe))
    k32.CloseHandle(snap)
    if not pids:
        raise RuntimeError("%s is not running. Start the game first." % ENGINE_EXE)
    can_write = False
    h = k32.OpenProcess(0x0410 | 0x0028, False, pids[0]) if write else None     # + VM_WRITE | VM_OPERATION
    if h:
        can_write = True
    else:
        h = k32.OpenProcess(0x0410, False, pids[0])        # VM_READ | QUERY_INFORMATION
    if not h:
        raise RuntimeError("Could not open the game process (error %d)." % ctypes.get_last_error())

    class MBI(ctypes.Structure):
        _fields_ = [("base", ctypes.c_void_p), ("abase", ctypes.c_void_p), ("aprot", wt.DWORD),
                    ("part", wt.WORD), ("size", ctypes.c_size_t), ("state", wt.DWORD),
                    ("prot", wt.DWORD), ("type", wt.DWORD)]

    k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
    probe = _WinReader(h, 0, k32)
    mbi, addr = MBI(), 0
    while addr < 0x7FFFFFFF0000:
        if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        base = mbi.base or 0
        if mbi.state == 0x1000 and mbi.type == 0x40000 and probe.read(base + XBE_VA, 4) == b"XBEH":
            reader = _WinReader(h, base, k32, can_write, _exe_path(k32, h))
            reader.pid = pids[0]              # the overlay (overlay.py) finds the game window by its process id
            return reader
        addr = base + mbi.size
    raise RuntimeError("Found the game process but not its Xbox memory.")
