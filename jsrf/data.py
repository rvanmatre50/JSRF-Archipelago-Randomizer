from typing import List, NamedTuple, Optional, Set, Tuple

BASE_ID = 7_450_000
GAME_NAME = "Jet Set Radio Future"

# Order matters: location IDs depend on the index. Only ever APPEND areas.
AREAS = [
    "Dogenzaka Hill",
    "Shibuya Terminal",
    "Chuo Street",
    "Hikage Street",
    "Kibogaoka Hill",
    "Rokkaku-dai Heights",
    "99th Street",
    "Skyscraper District and Pharaoh Park",
    "Tokyo Underground Sewage Facility",
    "Fortified Residential Zone",
    "Bottom Point of Sewage Facility",
    "Highway Zero",
    "Sky Dinosaurian Square",
]

# Areas connected to the Garage (sphere 1). Order must match StartingArea options.
STARTING_AREAS = [
    "Dogenzaka Hill",
    "Shibuya Terminal",
    "Rokkaku-dai Heights",
    "99th Street",
]

# Physical map connections (two-way). To enter an area you need its Unlock item
# AND a connected area you can already reach. Source: JetSetPedia.
GARAGE = "Garage"
CONNECTIONS: List[Tuple[str, str]] = [
    (GARAGE, "Dogenzaka Hill"),
    (GARAGE, "Shibuya Terminal"),
    (GARAGE, "Rokkaku-dai Heights"),
    (GARAGE, "99th Street"),
    ("Dogenzaka Hill", "Shibuya Terminal"),
    ("Shibuya Terminal", "Hikage Street"),
    ("Shibuya Terminal", "Chuo Street"),
    ("Rokkaku-dai Heights", "Tokyo Underground Sewage Facility"),
    ("Tokyo Underground Sewage Facility", "Kibogaoka Hill"),
    ("Tokyo Underground Sewage Facility", "Fortified Residential Zone"),
    ("Tokyo Underground Sewage Facility", "Bottom Point of Sewage Facility"),
    ("99th Street", "Skyscraper District and Pharaoh Park"),
    ("Skyscraper District and Pharaoh Park", "Highway Zero"),
    ("Skyscraper District and Pharaoh Park", "Sky Dinosaurian Square"),
]

# The packed stage code the engine is running (hi << 16 | lo; the stage file is Stg<hi><lo>_*) -> area.
# 0 is the Garage. Read live with `jsrf_watch.py stage`; F6 jumps and the Garage's own Dogenzaka door give the
# same code. Areas that are not listed here are reported once in the client log so they can be added.
GARAGE_STAGE = 0
# Mission-bank flag that rises when Corn's text box at the start of a New Game ends (101 clears, 103 sets) and stays set
# until the tutorial is over (user capture, discovery-findings.md "Passive capture"). The client uses it to send the
# player to the free-skate Garage on its own.
CORN_DONE_FLAG = 103
# Corn's talk lives in mission 1:1 (mssn0101, id 0x10001, stage 0 = the Garage). Its script sets Mission flags 100 and 101
# when the mission starts (needs Chapter flag 1), runs the talk file TE001 while 101 is set, then sets 103. Its first start
# record (spot 0) is the same spot as record 24 of the free-skate Garage (105, 34, 186.7).
CORN_MISSION = (1, 1)
CORN_MISSION_ID = 0x10001
CORN_FLAG_SETUP = 100
CORN_FLAG_TALK = 101
CORN_FLAG_TALKING = 102                         # set while TE001 is up (101 := 0, 102 := 1 when the talk starts)
CORN_FLAGS_RESET = tuple(range(100, 120))      # the chain this mission walks through after the talk; cleared before a replay
# After the talk (102 := 0, 103 := 1, 110 := 1) the script walks 110 -> 111 -> 112 -> 113 and then starts Gum's talk
# (TE002). Clearing these just before the client sends the player on keeps that talk from starting.
CORN_CHAIN = tuple(range(110, 120))
CORN_CHAIN_STOP = (110, 111, 112, 113)
# Seen in play (2026-11-16): the Mission bank is reset when mission 1:1 starts, so the game runs Corn's talk by itself on
# every visit; the client could not see the mission as running while the box was up, and the flags it then found
# (100-103 = 1001) meant "the talk is over", not "the talk never started".
STAGE_AREAS = {
    0x00010000: "Shibuya Terminal",
    0x00010001: "Chuo Street",
    0x00010002: "Dogenzaka Hill",
    0x00010003: "Hikage Street",
    0x00020000: "Rokkaku-dai Heights",
    0x00020001: "Tokyo Underground Sewage Facility",
    0x00020002: "Kibogaoka Hill",
    0x00020003: "Bottom Point of Sewage Facility",
    0x00020004: "Fortified Residential Zone",
    0x00030000: "99th Street",
    0x00030001: "Sky Dinosaurian Square",
    0x00030003: "Highway Zero",
    0x00030004: "Skyscraper District and Pharaoh Park",
}
# The Future Site of Rokkaku Expo Stadium (user, 2026-11-25): a stage of its own (0x30002; free-skate mission 9:165 =
# mssn0965, Jazz's race 9:166 = mssn0966), not one of the 13 areas (no Unlock item, never bounced). Its two checks, Jazz
# joining and its one graffiti spot (slot 0, the save point tag), carry its name but sit in the 99th Street region: they
# need the 99th Street Unlock and the client holds them until it arrives.
EXPO = "The Future Site of Rokkaku Expo Stadium"
EXPO_STAGE = 0x00030002
EXPO_REGION = "99th Street"
# Stages the F6 list offers that are not one of our areas (not locked, never bounced).
OTHER_STAGES = {
    EXPO_STAGE: EXPO,
}


def area_of_stage(code: int) -> Optional[str]:
    return STAGE_AREAS.get(code)


# Sandbox goal: with the Tower Unlock item and N Graffiti Soul items, the Zero Beat
# fight at Shibuya Terminal opens Gouji's Tower; defeating the final boss wins.
TOWER = "Gouji's Tower"
TOWER_PARENT = "Shibuya Terminal"
TOWER_UNLOCK = "Gouji's Tower Unlock"
# Confirmed in play (user, 21:13 and 21:45): the last chapter's finale runs, in order,
#   mssn0812 (id 8:12, Stg42 = 0x40002, the Zero Beat fight) -> mssn0811 (8:11, Stg43 = 0x40003, cutscene)
#   -> mssn0890 (8:890, Stg40 = 0x40000, Gouji's Tower and the final boss) -> mssn0813 (8:813, Stg43 again, a different
#   cutscene) -> mssn0899 (8:899, the credits, no stage) -> the Garage (2:96, 2:294).
# The game itself requests the Tower as lo 890 (file mssn0890, lo % 100), so /tower uses that id.
TOWER_STAGE = 0x00040000
TOWER_MISSION = (8, 890)
# Every spawn reads a start-point index from the manager variable 0x198 and places the player at that record of the new
# mission's start table (0x2C-byte records, position at +8). The F6 handler and our writes do not set it, so a teleport
# used whatever the last door trigger left: -1 (the table entry before the first, about (0, 0, 0)) or a stale door index
# that can run past the end of a short table. Out of bounds in the Tower (its floor is near y = -958) and the finale.
# The Garage files mssn0197 / 0297 / 0997 have 27 records: 0-23 stand in front of the doors, 24 is the middle of the room.
GARAGE_START_INDEX = 24
DEFAULT_START_INDEX = 0            # the Tower (8:890) has one record, index 0
FINALE_STAGES = {                      # the other two stages of the finale; gated together with the Tower
    0x00040002: "Shibuya Terminal (Zero Beat fight)",
    0x00040003: "Shibuya Terminal (finale cutscenes)",
}
# Goal: the player was in the Tower (with its items) and the stage then becomes this one = the final boss is beaten.
GOAL_STAGE = 0x00040003
# Backup (2026-11-19): the credits mission runs only after the final boss, so seeing it counts the goal too, for a client
# that was started after the Tower visit (the stage rule above needs to have seen the Tower).
CREDITS_MISSION_ID = (8 << 16) | 899

# Release label (user, 2026-11-19 20:40: "v1.0a for Alpha ... v1.0b for Beta ... then v1.0"). Archipelago's own world
# version (archipelago.json "world_version") must be plain numbers, so it stays 1.0.0 and this label is what players see.
# The seed carries it in slot data, and the client warns when the seed was made with another release.
RELEASE = "1.0a"
SOUL_ITEM = "Graffiti Soul"

# Filler (user, 2026-11-17: refills). The client fills the live player's spray cans / health to their max (game.py refill).
SPRAY_REFILL = "Spray Can Refill"
HEALTH_REFILL = "Health Refill"
FILLER_ITEMS = [SPRAY_REFILL, HEALTH_REFILL]


class LocData(NamedTuple):
    name: str                       # shown in the multiworld
    kind: str                       # "soul", "challenge_soul" or "tape"
    soul_no: Optional[int] = None   # in-game Graffiti Soul number (for the client)
    reach: Tuple[str, ...] = ()     # extra areas that must be reachable


def _soul(name, no=None, reach=()):
    return LocData(f"Soul - {name}", "soul", no, tuple(reach))


def _chal(name, no=None, reach=()):
    return LocData(f"Street Challenge - {name}", "challenge_soul", no, tuple(reach))


_TAPE = LocData("Mystery Tape", "tape")

# Mystery Tape flags (found 2026-11-16): picking up a tape (object vtable 0x1CA708, default.xbe 0x43974) sets Riddle Tape flag N
# (N = the tape object's +0xA4) and the area's five Street Challenge flags 32 + 5N .. 36 + 5N. Each area's chapter 9 mission
# tests exactly one such block (mssn0910: 32-36 ... mssn0975: 92-96), which gives N per area; Dogenzaka's 2 (with 42-46) was
# also seen live in two runs.
TAPE_FLAG = {
    "Shibuya Terminal": 0, "Chuo Street": 1, "Dogenzaka Hill": 2, "Hikage Street": 3, "Rokkaku-dai Heights": 4,
    "Tokyo Underground Sewage Facility": 5, "Kibogaoka Hill": 6, "Bottom Point of Sewage Facility": 7,
    "Fortified Residential Zone": 8, "99th Street": 9, "Sky Dinosaurian Square": 10, "Highway Zero": 11,
    "Skyscraper District and Pharaoh Park": 12,
}
# Mystery Tape items (user design 2026-11-16): picking a tape up is a location; the area's Street Challenges open with the
# area's Mystery Tape ITEM. The client keeps the challenge flags 32 + 5N .. 36 + 5N equal to the tape items received.
TAPE_ITEM_OFFSET = 3_000                         # item id = BASE_ID + 3_000 + N


def tape_item_name(area: str) -> str:
    return f"{area} Mystery Tape"


def tape_item_id(area: str) -> int:
    return BASE_ID + TAPE_ITEM_OFFSET + TAPE_FLAG[area]


def area_of_tape_item(item_id: int) -> "Optional[str]":
    n = item_id - BASE_ID - TAPE_ITEM_OFFSET
    return next((a for a, f in TAPE_FLAG.items() if f == n), None)


def challenge_flags(area: str) -> Tuple[int, ...]:
    """Riddle Tape flags that open the area's five Street Challenges (the game sets them when the tape is picked up)."""
    n = TAPE_FLAG[area]
    return tuple(range(32 + 5 * n, 37 + 5 * n))


def challenge_setup_flags(area: str) -> Tuple[int, ...]:
    """Riddle Tape flags 192 + 5N .. 196 + 5N: the "challenge cleared" marks. Each area's chapter 9 mission runs challenge i
    while its open flag is set and this mark is clear (mssn0920: op 0x22.. if T42 = 1 and T202 = 0; finishing sets T202 := 1 and
    M59 := 1, then op 0x8C makes the soul appear). A challenge that has started stays for the visit even if its open flag is
    cleared again. The client keeps a pickup without the tape item from opening them at all (claude/mystery-tapes.md) and
    holds these marks only for the rest of a visit in which it missed such a pickup."""
    n = TAPE_FLAG[area]
    return tuple(range(192 + 5 * n, 197 + 5 * n))

# Source: JetSetPedia. Each area: pre-spawned souls, Street Challenge souls
# (unlocked after the Mystery Tape), and the tape itself.
# soul_no None = number not found yet. Test Run souls are excluded for now.
# Rokkaku-dai's "second half" opens after the Poison Jam race in Chuo Street.
AREA_LOCATIONS = {
    "Dogenzaka Hill": [
        _soul("Rooftop after the first two tags", 5),
        _soul("Roadside on the way to Shibuya Terminal", 34),
        _soul("Ledge past the statue", 61),
        _chal("Grind Combo x10", 92),
        _chal("Air Combo x3", 117),
        _chal("20 Tricks", 6),
        _chal("50,000 Point Combo", 35),
        _chal("Avenue Long Grind", 62),
        _TAPE,
    ],
    "Shibuya Terminal": [
        _soul("On top of a bus", 7),
        _soul("Corridor behind some boxes", 93),
        _soul("On one of the 13 platforms", 119),
        _chal("Grind Combo x10", 36),
        _chal("Air Combo x3", 63),
        _chal("25 Tricks", 94),
        _chal("100,000 Point Combo", 121),
        _chal("Platforms x13 Without Falling", 8),
        _TAPE,
    ],
    "Chuo Street": [
        _soul("Canal opening past the telephone poles", 37),
        _soul("Crevice across the water area", 64),
        _soul("Green platform near the Shibuya Terminal exit", 95),
        _chal("Grind Combo x10", 122),
        _chal("Air Combo x4", 9),
        _chal("30 Tricks", 38),
        _chal("60,000 Point Combo", 65),
        _chal("G-W-G-W Reach the Sewer", 96),
        _TAPE,
    ],
    "Hikage Street": [
        _soul("Crevice on the path to the eastern overpass", 45),
        _soul("Crane in the eastern overpass", 73),
        _soul("In the air on the way to the northern overpass", 103),
        _chal("Grind Combo x20", 131),
        _chal("Air Combo x4", 18),
        _chal("55 Tricks", 46),
        _chal("300,000 Point Combo", 74),
        _chal("Special Challenge", 104),
        _TAPE,
    ],
    "Kibogaoka Hill": [
        _soul("Under a tower before the tunnel", 19),
        _soul("Ledge past where Boogie spawns", 47),
        _soul("Platform past the special challenge gate", 132),
        _chal("Grind Combo x20", 76),
        _chal("Air Combo x4", 105),
        _chal("50 Tricks", 133),
        _chal("250,000 Point Combo", 21),
        _chal("Gate of Kanji", 49),
        _TAPE,
    ],
    "Rokkaku-dai Heights": [
        # Rokkaku-dai is fully open in chapter 9 (user, 2026-11-17): no Chuo Street rule for the warehouse spots.
        _soul("Warehouse roof", 10),
        _soul("Near the stairs behind the warehouse", 39),
        _soul("Inside the jacuzzi", 123),
        _chal("Grind Combo x10", 67),
        _chal("Air Combo x4", 97),
        _chal("35 Tricks", 124),
        _chal("40,000 Point Combo", 11),
        _chal("Chimney #1 Grind", 40),
        _TAPE,
    ],
    "99th Street": [
        _soul("Rooftop in the dark district", 68),
        _soul("Billboard in the light district", 98),
        _soul("Above the tunnel to the dark district", 126),
        _chal("Grind Combo x15", 12),
        _chal("Air Combo x4", 41),
        _chal("40 Tricks", 69),
        _chal("100,000 Point Combo", 99),
        _chal("Cardinal Gates Grind", 127),
        _TAPE,
    ],
    "Skyscraper District and Pharaoh Park": [
        _soul("Top of the observatory", 77),
        _soul("Between the quarter pipes", 106),
        _soul("On a pillar in Pharaoh Park", 134),
        _chal("Grind Combo x20", 22),
        _chal("Air Combo x4", 50),
        _chal("55 Tricks", 79),
        _chal("70,000 Point Combo", 107),
        _chal("Circle Around the Pharaoh", 135),
        _TAPE,
    ],
    "Tokyo Underground Sewage Facility": [
        _soul("Halfpipe air on the way to the first switch", 13),
        _soul("Top of the processor tank around the final switch", 42),
        _soul("Pipe toward the first switch", 70),
        _chal("Grind Combo x10", 100),
        _chal("Air Combo x4", 128),
        _chal("45 Tricks", 15),
        _chal("100,000 Point Combo", 43),
        _chal("150,000 Point Combo", 71),
        _TAPE,
    ],
    "Fortified Residential Zone": [
        _soul("Up the red pipe", 83),
        _soul("In a tube reached via the giant metal piece", 111),
        _soul("Awning in the third area", 139),
        _chal("Grind Combo x10", 28),
        _chal("Air Combo x8", 56),
        _chal("100 Tricks", 84),
        _chal("50,000 Point Combo", 112),
        _chal("Giant of Metal Grind Up", 140),
        _TAPE,
    ],
    "Bottom Point of Sewage Facility": [
        _soul("Platform in the third large room", 16),
        # Numbers 16/101/129 confirmed by the user.
        _soul("Platform right before the race start line", 101),
        _soul("Catwalk above the halfpipe after the swirling rails", 129),
        _chal("Grind Combo x10", 44),
        _chal("Air Combo x4", 72),
        _chal("50 Tricks", 102),
        _chal("50,000 Point Combo", 130),
        _chal("70,000 Point Combo", 17),
        _TAPE,
    ],
    "Highway Zero": [
        _soul("Under the Skyscraper District exit", 23),
        _soul("Behind boxes in the vendor district", 51),
        _soul("In the pit after the six billboards", 80),
        _chal("Grind Combo x15", 108),
        _chal("Air Combo x5", 136),
        _chal("70 Tricks", 24),
        _chal("90,000 Point Combo", 52),
        _chal("Six Billboard Wallrides", 81),
        _TAPE,
    ],
    "Sky Dinosaurian Square": [
        _soul("Top of the T-Rex's head", 26),
        _soul("Under the brontosaurus", 54),
        _soul("Yellow structure before the end of the red-track lap", 109),
        _soul("Building after the T-Rex on the orange tracks", 137),
        _chal("Grind Combo x50", 82),
        _chal("Air Combo x6", 110),
        _chal("100 Tricks", 138),
        _chal("10,000 Point Combo", 27),
        _chal("Rail, Swinging Ride, Rail", 55),
        _TAPE,
    ],
}

for _area in AREAS:
    assert _area in AREA_LOCATIONS, _area

# IDs are BASE_ID + area_index*100 + position in the list.
# Only ever APPEND to a list, or existing IDs shift.
MAX_LOCATIONS_PER_AREA = 100


def unlock_name(area: str) -> str:
    return f"{area} Unlock"


def location_name(area: str, loc: LocData) -> str:
    return f"{area} - {loc.name}"


# --- Graffiti tag spots ------------------------------------------------------------
# Found 2026-11-16 (default.xbe + the user's jsrf_tags.py tour, see discovery-findings.md "Graffiti tag spots"):
# the game keeps each tag spot's state per AREA SLOT (0-79) in a saved record inside the story flag manager, not per
# mission, so a slot sprayed in one chapter's version of an area stays sprayed in every other version that uses it.
# Each entry is (slot, parts): parts = how many pieces the spot has (3 bits of state each; 7 = not sprayed yet).
# Slots 0-2 are the save point tags; the game leaves them out of its own "x / y" count, but they are checks here.
# The lists are the free-skate (chapter 9) versions (missions 9:9xx / F6's hi 9 ones) the Garage doors lead to; other
# chapters load other sets (F6's Dogenzaka 6:120 has only the 17 spots of chapter 1, its 99th Street 6:155 has 35 of 65).
TAG_SPOTS = {
    'Dogenzaka Hill': (  # 43 spots, mission 9:920
        (0, 3), (4, 6), (7, 3), (9, 6), (10, 3), (11, 6), (12, 6), (20, 3), (21, 1), (22, 1), (23, 1), (24, 3),
        (25, 10), (26, 1), (27, 1), (28, 1), (29, 1), (32, 3), (33, 1), (34, 3), (37, 6), (44, 6), (45, 3), (47, 3),
        (51, 3), (52, 3), (53, 1), (54, 1), (55, 1), (56, 1), (57, 1), (58, 1), (59, 3), (60, 6), (62, 6), (64, 1),
        (65, 1), (66, 1), (67, 1), (68, 1), (69, 3), (70, 6), (71, 6),
    ),
    'Shibuya Terminal': (  # 49 spots, mission 9:910
        (0, 3), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 1), (10, 1), (11, 1), (12, 3), (13, 1), (14, 3),
        (15, 3), (16, 3), (21, 1), (22, 1), (23, 1), (24, 1), (25, 1), (26, 1), (27, 1), (28, 1), (29, 1), (30, 1),
        (31, 1), (32, 1), (33, 1), (34, 1), (35, 1), (36, 3), (37, 3), (38, 6), (39, 3), (40, 3), (41, 6), (42, 10),
        (45, 1), (46, 1), (47, 1), (51, 1), (52, 1), (53, 1), (58, 10), (63, 6), (67, 3), (69, 10), (71, 6), (72, 3),
    ),
    'Chuo Street': (  # 51 spots, mission 9:115
        (0, 3), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 6), (9, 6), (10, 3), (11, 1), (12, 1), (13, 10), (14, 6),
        (15, 10), (16, 3), (17, 6), (18, 3), (19, 1), (20, 1), (21, 3), (22, 3), (23, 6), (24, 10), (25, 3), (26, 6),
        (27, 6), (28, 3), (30, 1), (31, 1), (32, 1), (36, 10), (39, 1), (42, 1), (43, 1), (44, 1), (45, 1), (47, 1),
        (48, 3), (49, 1), (50, 1), (51, 1), (52, 1), (53, 1), (54, 1), (57, 1), (59, 1), (60, 1), (61, 1), (62, 1),
        (64, 6), (71, 6),
    ),
    'Hikage Street': (  # 51 spots, mission 9:925
        (0, 3), (4, 1), (6, 1), (7, 3), (11, 1), (12, 3), (13, 1), (14, 1), (15, 1), (16, 1), (17, 6), (18, 1),
        (19, 3), (20, 1), (21, 3), (22, 1), (23, 1), (24, 1), (25, 1), (26, 1), (27, 3), (28, 3), (30, 3), (31, 3),
        (32, 6), (33, 6), (34, 6), (35, 10), (36, 1), (37, 3), (38, 6), (39, 1), (40, 3), (41, 6), (42, 3), (43, 1),
        (45, 6), (46, 1), (47, 1), (48, 10), (49, 1), (50, 1), (51, 3), (52, 10), (53, 10), (54, 10), (55, 6), (57, 3),
        (58, 3), (59, 10), (60, 3),
    ),
    'Kibogaoka Hill': (  # 54 spots, mission 9:140
        (0, 3), (1, 3), (3, 1), (4, 1), (5, 10), (6, 1), (7, 1), (8, 1), (9, 1), (10, 1), (11, 10), (12, 1), (13, 10),
        (14, 1), (15, 3), (16, 1), (17, 6), (19, 6), (21, 1), (22, 6), (24, 10), (25, 3), (26, 6), (27, 3), (29, 3),
        (30, 3), (31, 1), (32, 1), (33, 10), (34, 3), (35, 1), (36, 1), (37, 1), (38, 3), (40, 1), (41, 1), (43, 1),
        (44, 3), (46, 1), (47, 3), (51, 10), (52, 1), (53, 3), (55, 6), (60, 6), (61, 3), (65, 1), (68, 3), (71, 3),
        (72, 1), (73, 1), (74, 6), (75, 6), (78, 6),
    ),
    'Rokkaku-dai Heights': (  # 55 spots, mission 9:130
        (0, 3), (1, 3), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 1), (10, 1), (11, 10), (12, 6), (13, 10),
        (14, 3), (15, 1), (16, 1), (17, 1), (18, 1), (19, 1), (20, 3), (21, 1), (22, 1), (23, 6), (24, 1), (25, 1),
        (26, 3), (27, 1), (28, 1), (29, 6), (30, 6), (31, 6), (32, 10), (33, 6), (34, 1), (45, 6), (47, 1), (48, 1),
        (49, 1), (50, 1), (51, 1), (52, 1), (53, 3), (54, 1), (55, 1), (56, 1), (57, 1), (58, 6), (60, 6), (64, 6),
        (71, 1), (73, 1), (74, 1), (76, 6), (77, 10), (78, 1),
    ),
    '99th Street': (  # 65 spots, mission 9:955
        (0, 3), (3, 3), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 3), (12, 1), (13, 1), (14, 1), (16, 1), (17, 1),
        (18, 1), (19, 1), (20, 1), (21, 1), (22, 1), (23, 3), (24, 1), (25, 1), (26, 1), (27, 1), (28, 3), (29, 3),
        (30, 6), (31, 3), (32, 6), (33, 10), (34, 6), (35, 3), (36, 1), (37, 1), (38, 1), (39, 6), (40, 6), (41, 3),
        (42, 6), (43, 1), (44, 1), (47, 6), (48, 10), (49, 1), (50, 1), (51, 3), (52, 10), (53, 1), (54, 6), (55, 10),
        (56, 3), (57, 3), (58, 1), (60, 3), (61, 6), (62, 1), (63, 1), (64, 1), (65, 1), (66, 3), (67, 3), (68, 6),
        (69, 1), (70, 3), (71, 1), (72, 1),
    ),
    'Skyscraper District and Pharaoh Park': (  # 42 spots, mission 9:175
        (0, 3), (1, 3), (5, 6), (6, 1), (7, 1), (8, 1), (9, 1), (10, 10), (11, 3), (12, 3), (13, 3), (14, 10), (15, 3),
        (16, 6), (17, 6), (18, 6), (19, 6), (20, 6), (22, 1), (23, 3), (25, 6), (26, 6), (27, 6), (28, 6), (29, 6),
        (30, 1), (31, 1), (33, 3), (34, 6), (35, 6), (36, 6), (37, 6), (38, 6), (39, 3), (40, 6), (41, 6), (42, 6),
        (44, 10), (45, 3), (46, 3), (47, 6), (48, 10),
    ),
    'Tokyo Underground Sewage Facility': (  # 27 spots, mission 9:135
        (0, 3), (1, 3), (2, 3), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 1), (10, 1), (13, 1), (16, 6),
        (17, 1), (18, 1), (20, 1), (22, 3), (23, 3), (24, 3), (25, 6), (26, 3), (27, 1), (28, 1), (29, 1), (30, 1),
        (31, 3), (32, 1),
    ),
    'Fortified Residential Zone': (  # 50 spots, mission 9:150
        (0, 3), (1, 3), (2, 3), (3, 3), (4, 6), (7, 3), (9, 1), (10, 1), (11, 1), (12, 3), (13, 3), (14, 3), (16, 3),
        (17, 1), (29, 6), (31, 3), (32, 10), (33, 3), (34, 6), (35, 1), (36, 10), (37, 3), (38, 1), (39, 1), (40, 3),
        (41, 3), (42, 1), (43, 10), (44, 3), (45, 1), (46, 1), (47, 1), (48, 6), (49, 6), (50, 1), (51, 6), (52, 3),
        (53, 6), (57, 6), (58, 1), (59, 3), (60, 1), (61, 1), (62, 1), (63, 1), (64, 1), (65, 3), (66, 1), (67, 1),
        (68, 1),
    ),
    'Bottom Point of Sewage Facility': (  # 29 spots, mission 9:145
        (0, 3), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 6), (10, 3), (11, 3), (12, 3), (13, 3), (14, 1),
        (15, 1), (16, 1), (17, 1), (18, 3), (19, 6), (20, 6), (21, 1), (22, 1), (23, 1), (24, 1), (25, 1), (28, 10),
        (29, 10), (30, 6), (31, 1), (32, 1),
    ),
    'Highway Zero': (  # 26 spots, mission 9:170
        (0, 3), (3, 1), (4, 3), (5, 10), (7, 3), (9, 1), (10, 1), (12, 1), (13, 1), (14, 1), (15, 1), (16, 3), (17, 1),
        (18, 1), (19, 1), (20, 1), (21, 6), (22, 10), (23, 1), (24, 1), (25, 1), (26, 1), (27, 1), (28, 1), (29, 1),
        (31, 6),
    ),
    'Sky Dinosaurian Square': (  # 30 spots, mission 9:160
        (0, 3), (3, 1), (4, 3), (5, 10), (6, 10), (7, 1), (8, 3), (9, 1), (10, 1), (11, 1), (12, 3), (13, 1), (14, 1),
        (15, 6), (16, 1), (17, 10), (18, 10), (19, 1), (20, 6), (21, 1), (22, 1), (23, 10), (24, 1), (25, 3), (27, 1),
        (28, 3), (29, 1), (30, 1), (31, 3), (32, 6),
    ),
    # added 2026-11-25 (user): the stadium's missions (mssn0965, 0966) list one spot, slot 0, with 3 parts (the spot
    # record's +0xA0, which matches the parts of all 65 99th Street spots in mssn0955)
    EXPO: (
        (0, 3),
    ),
}
# Tag areas: the 13 areas plus the stadium. A tag area's spots are checks of its region.
TAG_AREAS = tuple(AREAS) + (EXPO,)
TAG_REGION = {area: area for area in AREAS}
TAG_REGION[EXPO] = EXPO_REGION
TAG_STAGE_AREAS = dict(STAGE_AREAS)              # stage code -> tag area (the loaded spots carry their stage's code)
TAG_STAGE_AREAS[EXPO_STAGE] = EXPO

# Tag ids live in their own range so changing a list never shifts soul/tape ids:
# BASE_ID + 10_000 + tag_area_index * 100 + slot + 1   (slot 0-79; the stadium is tag area 13, after the 13 areas)
TAG_ID_OFFSET = 10_000
SAVE_TAG_SLOTS = frozenset({0, 1, 2})
TAG_COUNTS = {area: len(TAG_SPOTS[area]) for area in TAG_AREAS}
TAG_TOTAL = sum(TAG_COUNTS.values())             # 573

# Gouji's Tower requirements (user, 2026-11-17): the Tower Unlock item always, plus any of Graffiti Soul items, sprayed tag
# spots and cleared Street Challenges, stacked. Beating Gouji in the Tower is the goal. The tag / challenge requirements are
# events in the Garage (their rules count what the reachable areas offer), so the Tower's entrance needs only items.
GOUJI_EVENT = "Defeat Gouji"                     # event location in the Tower
GOUJI_EVENT_ITEM = "Gouji Defeated"
TAGS_EVENT = "Tower Requirement: Tag Spots"
TAGS_EVENT_ITEM = "Tag Spots Sprayed"
CHALLENGES_EVENT = "Tower Requirement: Street Challenges"
CHALLENGES_EVENT_ITEM = "Street Challenges Cleared"
CHALLENGE_TOTAL = sum(1 for a in AREAS for loc in AREA_LOCATIONS[a] if loc.kind == "challenge_soul")   # 65
JETS_EVENT = "Goal: Jet Ranks"                # event location in the Garage when the goal is Jet Ranks


def area_soul_ids(area: str) -> "Set[int]":
    """Soul ids (wiki number - 1) of every Graffiti Soul of an area, Street Challenge souls included. Roboy offers an
    area's Test Runs (at chapter 9) only once all of them are possessed (0x756E0)."""
    return {loc.soul_no - 1 for loc in AREA_LOCATIONS[area] if loc.soul_no}
JETS_EVENT_ITEM = "Jet Ranks Earned"


# Test Runs (Jet Ranks), static 2026-11-17, not yet played. 39 missions, files Media/Mission/mssnHHAA: HH = hi (30 Jet
# Graffiti in all 13 areas, 31 Jet Tech in all 13, 32 Jet Dash in the 6 linear areas, 33 Jet Flag in the 7 open ones), AA =
# the stage (group * 10 + index, stage code 0x000G000I); requested as lo HH * 100 + AA, as the game does for the Tower (890).
# Finishing one stores the result in the area's top-5 table (0x73440 -> 0x3B7E0): flag manager + 0x2A9C + 8 * ((area index
# * 4 + type) * 5 + slot), type = hi - 30, slot 0 = best, area index as for tags (table 0x1EFC88 = GAME_AREA_INDEX below).
# The rank is byte +6 (byte +5 for Jet Tech); the game's all-Jet test (0x11A6F0) takes >= 5 as Jet. New Game's default
# tables (0x77400) top out below Jet, so a fresh save has none.
class TestRun(NamedTuple):
    area: str
    kind: str          # "Jet Graffiti" / "Jet Tech" / "Jet Dash" / "Jet Flag"
    hi: int
    lo: int
    record_type: int   # 0-3, the type index in the record table


TEST_RUN_KINDS = {30: "Jet Graffiti", 31: "Jet Tech", 32: "Jet Dash", 33: "Jet Flag"}
_TEST_RUN_STAGES = {30: (10, 11, 12, 13, 20, 21, 22, 23, 24, 30, 31, 33, 34),
                    31: (10, 11, 12, 13, 20, 21, 22, 23, 24, 30, 31, 33, 34),
                    32: (11, 12, 22, 23, 31, 33),
                    33: (10, 13, 20, 21, 24, 30, 34)}
TEST_RUNS = [TestRun(STAGE_AREAS[(aa // 10) << 16 | aa % 10], TEST_RUN_KINDS[hi], hi, hi * 100 + aa, hi - 30)
             for hi, stages in _TEST_RUN_STAGES.items() for aa in stages]
TEST_RUN_TOTAL = len(TEST_RUNS)                  # 39
JET_RANK = 5                                     # rank byte value of a Jet (and above)
assert TEST_RUN_TOTAL == 39 and all(sum(1 for t in TEST_RUNS if t.area == a) == 3 for a in AREAS)

# Jet rank checks (user, 2026-11-19 18:10): a Jet rank on a Test Run is a location. The game keeps the best result per Test
# Run in the save (see above), so the client reads it the same way as for the Jet Ranks goal.
JET_LOCATION_OFFSET = 40_000                     # location id = BASE_ID + 40_000 + the Test Run's lo (hi * 100 + stage)


def jet_location_name(run: TestRun) -> str:
    return f"{run.area} - Jet Rank: {run.kind}"


def jet_location_id(run: TestRun) -> int:
    return BASE_ID + JET_LOCATION_OFFSET + run.lo


JET_LOCATION_OF = {(t.area, t.hi): jet_location_id(t) for t in TEST_RUNS}     # (area, hi) -> location id


def soul_reach(area: str) -> "Tuple[str, ...]":
    """Other areas the Graffiti Souls of `area` need (every soul's extra reach): Roboy offers the area's Test Runs only once
    all of its souls are possessed."""
    return tuple(sorted({r for loc in AREA_LOCATIONS[area] if loc.soul_no for r in loc.reach}))


def tags_needed(percent: int) -> int:
    """Tag spots the Tower needs: percent of all of them, rounded up (0 = not needed)."""
    return 0 if percent <= 0 else max(1, min(TAG_TOTAL, -(-TAG_TOTAL * percent // 100)))
# The game's own area numbers (table at 0x1EFC88, indexed by the stage code's digits), used for the saved tag record.
GAME_AREA_INDEX = {
    "Shibuya Terminal": 2, "Chuo Street": 3, "Dogenzaka Hill": 4, "Hikage Street": 5, "Rokkaku-dai Heights": 6,
    "Tokyo Underground Sewage Facility": 7, "Kibogaoka Hill": 8, "Bottom Point of Sewage Facility": 9,
    "Fortified Residential Zone": 10, "99th Street": 11, "Sky Dinosaurian Square": 12, "Highway Zero": 14,
    "Skyscraper District and Pharaoh Park": 15,
    EXPO: 13,                                     # 0x1EFC88[32] (stage 0x30002) = 13
}

assert set(TAG_SPOTS) == set(TAG_AREAS) and all(TAG_REGION[a] in AREAS for a in TAG_AREAS)
for _area in TAG_AREAS:
    assert _area in TAG_SPOTS and _area in GAME_AREA_INDEX, _area
    assert all(0 <= _slot < 80 and 0 <= _parts <= 10 for _slot, _parts in TAG_SPOTS[_area]), _area
    assert len({_slot for _slot, _ in TAG_SPOTS[_area]}) == len(TAG_SPOTS[_area]), _area


def tag_name(area: str, slot: int) -> str:
    if slot in SAVE_TAG_SLOTS:
        return f"{area} - Save Point Tag" + ("" if slot == 0 else f" {slot + 1}")
    return f"{area} - Tag {slot:02d}"


def tag_id(area: str, slot: int) -> int:
    assert 0 <= slot < 80
    return BASE_ID + TAG_ID_OFFSET + TAG_AREAS.index(area) * 100 + slot + 1


def tag_slot_of_id(location_id: int) -> "Optional[Tuple[str, int]]":
    """(tag area, slot) for a tag location id, or None."""
    rel = location_id - BASE_ID - TAG_ID_OFFSET
    idx, n = divmod(rel, 100)
    if rel < 0 or not 0 <= idx < len(TAG_AREAS) or not 1 <= n <= 80:
        return None
    return TAG_AREAS[idx], n - 1


def tag_areas_of_region(region: str) -> "List[str]":
    """The tag areas whose spots are checks of this region (the area itself, and the stadium for 99th Street)."""
    return [a for a in TAG_AREAS if TAG_REGION[a] == region]


# --- Characters ---------------------------------------------------------------------
# Found 2026-11-16 (default.xbe, characters.md): the roster is a 32-bit mask at story flag manager + 0x14 (0x1EFFC4), one bit
# per character id; New Game sets Corn, Gum and Yoyo. The game's own unlock (script op 0xD6 -> 0x39CB0) sets the bit and writes
# -1 to game variable 0x151 + id. Characters are Archipelago items; the game's unlock events are locations.
CHARACTERS = {
    0: "Beat", 1: "Corn", 2: "Gum", 3: "Combo", 4: "Rhyth", 5: "Soda", 6: "Yoyo", 7: "NT-3000", 8: "Garam", 9: "Boogie",
    10: "Cube", 11: "Love Shockers", 12: "Poison Jam", 13: "Noise Tanks", 14: "Immortals", 15: "Doom Riders", 16: "Rapid 99",
    17: "Pots", 18: "Gouji", 19: "Roboy", 20: "Clutch", 21: "Jazz", 22: "A.KU.MU", 23: "Zero Beat",
}
START_CHARACTERS = frozenset({1, 2, 6})          # Corn, Gum, Yoyo: what a New Game starts with (the "classic" start)
CHARACTER_ITEMS = tuple(sorted(CHARACTERS))      # every character has an item; the starting one(s) are left out of the pool
NEW_GAME_CHARACTER = 6                           # New Game puts you in as Yoyo (default.xbe 0x7C3EF writes 6 to variable 0xD)
CHARACTER_ITEM_OFFSET = 2_000                    # item id = BASE_ID + 2_000 + character id
CHARACTER_LOCATION_OFFSET = 20_000               # location id = BASE_ID + 20_000 + character id
ROKKAKU_EXPO_STAGE = EXPO_STAGE


class CharacterUnlock(NamedTuple):
    char: int
    area: str                     # region the location sits in
    reach: Tuple[str, ...]        # other areas it needs
    stages: Tuple[int, ...]       # stage codes where the game can run this unlock (the client keeps the bit clear there)
    kind: str                     # "recruit" (free-skate challenge) or "test_run" (Jet on all of the area's Test Runs)


def _stage_of(area: str) -> int:
    return next(code for code, a in STAGE_AREAS.items() if a == area)


# Recruits: the challenge missions with script op 0xD6 (mssn0930 Rhyth if M433, 0941 Boogie if M407, 0946 Cube, 0966 Jazz and
# 0971 Soda if M402). Test Run characters: default.xbe 0x11AB11 gives them when all three Test Runs of the area are Jet, the
# chapter number (flag manager + 4) is 9 and the character is not unlocked yet; Poison Jam needs both sewage areas.
CHARACTER_UNLOCKS = [
    CharacterUnlock(4, "Rokkaku-dai Heights", (), (_stage_of("Rokkaku-dai Heights"),), "recruit"),
    CharacterUnlock(9, "Kibogaoka Hill", (), (_stage_of("Kibogaoka Hill"),), "recruit"),
    CharacterUnlock(10, "Bottom Point of Sewage Facility", (), (_stage_of("Bottom Point of Sewage Facility"),), "recruit"),
    CharacterUnlock(21, EXPO_REGION, (), (EXPO_STAGE,), "recruit"),          # the race is in the Expo Stadium
    CharacterUnlock(5, "Highway Zero", (), (_stage_of("Highway Zero"),), "recruit"),
    CharacterUnlock(15, "Dogenzaka Hill", (), (_stage_of("Dogenzaka Hill"),), "test_run"),
    CharacterUnlock(23, "Shibuya Terminal", (), (_stage_of("Shibuya Terminal"),), "test_run"),
    CharacterUnlock(19, "Chuo Street", (), (_stage_of("Chuo Street"),), "test_run"),
    CharacterUnlock(11, "Hikage Street", (), (_stage_of("Hikage Street"),), "test_run"),
    CharacterUnlock(18, "Rokkaku-dai Heights", (), (_stage_of("Rokkaku-dai Heights"),), "test_run"),
    CharacterUnlock(12, "Tokyo Underground Sewage Facility", ("Bottom Point of Sewage Facility",),
                    (_stage_of("Tokyo Underground Sewage Facility"), _stage_of("Bottom Point of Sewage Facility")), "test_run"),
    CharacterUnlock(17, "Kibogaoka Hill", (), (_stage_of("Kibogaoka Hill"),), "test_run"),
    CharacterUnlock(22, "Fortified Residential Zone", (), (_stage_of("Fortified Residential Zone"),), "test_run"),
    CharacterUnlock(16, "99th Street", (), (_stage_of("99th Street"),), "test_run"),
    CharacterUnlock(7, "Sky Dinosaurian Square", (), (_stage_of("Sky Dinosaurian Square"),), "test_run"),
    CharacterUnlock(13, "Highway Zero", (), (_stage_of("Highway Zero"),), "test_run"),
    CharacterUnlock(14, "Skyscraper District and Pharaoh Park", (), (_stage_of("Skyscraper District and Pharaoh Park"),), "test_run"),
]
CHARACTER_UNLOCK_OF = {u.char: u for u in CHARACTER_UNLOCKS}
assert len(CHARACTER_UNLOCK_OF) == 17 and all(u.area in AREAS and all(r in AREAS for r in u.reach) for u in CHARACTER_UNLOCKS)


def character_item_name(char: int) -> str:
    return CHARACTERS[char]


def character_item_id(char: int) -> int:
    return BASE_ID + CHARACTER_ITEM_OFFSET + char


def character_of_item(item_id: int) -> "Optional[int]":
    char = item_id - BASE_ID - CHARACTER_ITEM_OFFSET
    return char if char in CHARACTERS else None


# Where a character's unlock happens when that is not its region's own stage (the name the location carries).
CHARACTER_PLACE = {21: EXPO}                     # Jazz's race (user, 2026-11-25)


def character_location_name(char: int) -> str:
    u = CHARACTER_UNLOCK_OF[char]
    return f"{CHARACTER_PLACE.get(char, u.area)} - {CHARACTERS[char]} Joins"


def character_location_id(char: int) -> int:
    return BASE_ID + CHARACTER_LOCATION_OFFSET + char


def character_of_location(location_id: int) -> "Optional[int]":
    char = location_id - BASE_ID - CHARACTER_LOCATION_OFFSET
    return char if char in CHARACTER_UNLOCK_OF else None


# --- Rival gang battles (chapter 9) ------------------------------------------------------------------------------
# Found 2026-11-17 (mission files): three chapter 9 area missions hand over to a battle mission through their exit table
# (op 0xFB): 9:920 Dogenzaka Hill -> 9:921, 9:925 Hikage Street -> 9:926, 9:955 99th Street -> 9:956. Each battle places the
# gang (spawn table type 2: character 15 Doom Riders, 11 Love Shockers, 14 Immortals; op 0x49 riders of the same id) and on a
# win sets one Global flag (op 0xE5: 921 sets G15, 926 G16, 956 G17). The parent missions only offer the battle while that
# flag is clear (op 0x70 / 0x18 if Gn = 0), so each battle is won once. No other script or native code sets G15-G17.
class RivalBattle(NamedTuple):
    gang: str
    char: int          # the gang's character id (spawn table / op 0x49)
    area: str
    flag: int          # Global flag the win sets
    mission: int       # lo of the battle mission (hi 9)


RIVAL_BATTLES = [
    RivalBattle("Doom Riders", 15, "Dogenzaka Hill", 15, 921),
    RivalBattle("Love Shockers", 11, "Hikage Street", 16, 926),
    RivalBattle("Immortals", 14, "99th Street", 17, 956),
]
RIVAL_LOCATION_OFFSET = 30_000                   # location id = BASE_ID + 30_000 + the Global flag
assert all(r.area in AREAS and CHARACTERS[r.char] == r.gang for r in RIVAL_BATTLES)


def rival_location_name(r: RivalBattle) -> str:
    return f"{r.area} - Beat the {r.gang}"


def rival_location_id(r: RivalBattle) -> int:
    return BASE_ID + RIVAL_LOCATION_OFFSET + r.flag


def rival_of_location(location_id: int) -> "Optional[RivalBattle]":
    return next((r for r in RIVAL_BATTLES if rival_location_id(r) == location_id), None)


def location_requirements() -> "dict[int, Tuple[str, ...]]":
    """Archipelago location id -> areas whose Unlock item must have arrived before the client reports the check.
    Souls, challenges and tapes need their own area plus any `reach` areas. Tags (when enabled) need their area."""
    out = {}
    for i, area in enumerate(AREAS):
        for j, loc in enumerate(AREA_LOCATIONS[area]):
            out[BASE_ID + 100 * i + j] = (area,) + tuple(loc.reach)
    for area in TAG_AREAS:
        for slot, _ in TAG_SPOTS[area]:
            out[tag_id(area, slot)] = (TAG_REGION[area],)
    for u in CHARACTER_UNLOCKS:
        out[character_location_id(u.char)] = (u.area,) + u.reach
    for r in RIVAL_BATTLES:
        out[rival_location_id(r)] = (r.area,)
    for t in TEST_RUNS:
        out[jet_location_id(t)] = (t.area,) + soul_reach(t.area)
    return out


def area_of_location(location_id: int) -> "Optional[str]":
    """The area a (soul/challenge/tape) location id belongs to, or None."""
    idx = (location_id - BASE_ID) // 100
    return AREAS[idx] if 0 <= idx < len(AREAS) else None
