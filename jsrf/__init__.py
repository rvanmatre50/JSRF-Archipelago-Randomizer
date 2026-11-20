import logging
from typing import Dict, Set

from Options import OptionError
from BaseClasses import Item, ItemClassification, Location, Region, Tutorial
from worlds.AutoWorld import World, WebWorld
from worlds.generic.Rules import add_rule
from worlds.LauncherComponents import Component, Type, components, icon_paths, launch_subprocess

from .data import (AREAS, AREA_LOCATIONS, BASE_ID, CHARACTER_ITEMS, CHARACTER_UNLOCKS, CHARACTERS, CONNECTIONS, FILLER_ITEMS,
                   START_CHARACTERS, RELEASE,
                   GAME_NAME, GARAGE, SOUL_ITEM, STARTING_AREAS, TAG_SPOTS, TOWER,
                   TOWER_PARENT, TOWER_UNLOCK, LocData,
                   location_name, tag_id, tag_name, unlock_name, SAVE_TAG_SLOTS,
                   character_item_id, character_item_name, character_location_id, character_location_name,
                   tape_item_id, tape_item_name, RIVAL_BATTLES, rival_location_id, rival_location_name,
                   CHALLENGE_TOTAL, CHALLENGES_EVENT, CHALLENGES_EVENT_ITEM, GOUJI_EVENT, GOUJI_EVENT_ITEM,
                   TAGS_EVENT, TAGS_EVENT_ITEM, TAG_COUNTS, tags_needed, JETS_EVENT, JETS_EVENT_ITEM, TEST_RUNS,
                   TEST_RUN_TOTAL, jet_location_id, jet_location_name, soul_reach)
from .options import JSRFOptions, OPTION_GROUPS


def _record_client_error():
    """Append the current traceback to <Archipelago data folder>/logs/JSRFClient_startup_error.txt.
    The client window runs in its own process, so a crash while it starts is otherwise invisible."""
    try:
        import os
        import time
        import traceback
        import Utils
        folder = Utils.user_path("logs")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "JSRFClient_startup_error.txt"), "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + traceback.format_exc() + "\n")
    except Exception:
        pass


def _run_client(*args: str):
    try:
        from .client import launch
        launch(*args)
    except Exception:
        _record_client_error()
        raise


def _launch_client(*args: str):
    try:
        launch_subprocess(_run_client, name="JSRFClient", args=args)
    except Exception:
        _record_client_error()
        raise


# The Launcher icon: client_icon.png, an original spray-can badge that ships with this world (user, 2026-11-19: its own
# file, nothing taken from the game).
icon_paths["jsrf_client"] = f"ap:{__name__}/client_icon.png"


components.append(Component("JSRF Client", func=_launch_client, component_type=Type.CLIENT, icon="jsrf_client"))


class JSRFItem(Item):
    game = GAME_NAME


class JSRFLocation(Location):
    game = GAME_NAME


class JSRFWebWorld(WebWorld):
    theme = "partyTime"
    # docs/en_Jet Set Radio Future.md is the game page; docs/setup_en.md the setup guide (both in the apworld).
    tutorials = [Tutorial(
        "Multiworld Setup Guide",
        "Install the world, make an options file and connect JSRF Unleashed to an Archipelago game.",
        "English",
        "setup_en.md",
        "setup/en",
        ["Robbie"],
    )]
    option_groups = OPTION_GROUPS     # panels in the Launcher's Options Creator, sections on the website and in the template
    rich_text_doc = True              # option docstrings render as reStructuredText on the website (**bold**, paragraphs)


ITEM_IDS = {unlock_name(a): BASE_ID + i for i, a in enumerate(AREAS)}
ITEM_IDS[TOWER_UNLOCK] = BASE_ID + 500
ITEM_IDS[SOUL_ITEM] = BASE_ID + 900
for _i, _n in enumerate(FILLER_ITEMS):
    ITEM_IDS[_n] = BASE_ID + 1000 + _i
for _c in CHARACTER_ITEMS:
    ITEM_IDS[character_item_name(_c)] = character_item_id(_c)
for _a in AREAS:
    ITEM_IDS[tape_item_name(_a)] = tape_item_id(_a)

LOCATION_IDS: Dict[str, int] = {}
LOCATION_GROUPS: Dict[str, Set[str]] = {
    "Street Challenges": set(), "Pre-spawned Souls": set(), "Mystery Tapes": set(),
    "Tags": set(), "Save Point Tags": set(), "Character Unlocks": set(), "Rival Gang Battles": set(), "Jet Ranks": set(),
}
for _i, _area in enumerate(AREAS):
    LOCATION_GROUPS[_area] = set()
    for _j, _loc in enumerate(AREA_LOCATIONS[_area]):
        _name = location_name(_area, _loc)
        LOCATION_IDS[_name] = BASE_ID + 100 * _i + _j
        LOCATION_GROUPS[_area].add(_name)
        _kind = {"soul": "Pre-spawned Souls", "challenge_soul": "Street Challenges",
                 "tape": "Mystery Tapes"}[_loc.kind]
        LOCATION_GROUPS[_kind].add(_name)
    for _slot, _ in TAG_SPOTS[_area]:
        _tname = tag_name(_area, _slot)
        LOCATION_IDS[_tname] = tag_id(_area, _slot)
        LOCATION_GROUPS[_area].add(_tname)
        LOCATION_GROUPS["Tags"].add(_tname)
        if _slot in SAVE_TAG_SLOTS:
            LOCATION_GROUPS["Save Point Tags"].add(_tname)


for _u in CHARACTER_UNLOCKS:
    _cname = character_location_name(_u.char)
    LOCATION_IDS[_cname] = character_location_id(_u.char)
    LOCATION_GROUPS[_u.area].add(_cname)
    LOCATION_GROUPS["Character Unlocks"].add(_cname)
for _r in RIVAL_BATTLES:
    _rname = rival_location_name(_r)
    LOCATION_IDS[_rname] = rival_location_id(_r)
    LOCATION_GROUPS[_r.area].add(_rname)
    LOCATION_GROUPS["Rival Gang Battles"].add(_rname)
for _t in TEST_RUNS:
    _jname = jet_location_name(_t)
    LOCATION_IDS[_jname] = jet_location_id(_t)
    LOCATION_GROUPS[_t.area].add(_jname)
    LOCATION_GROUPS["Jet Ranks"].add(_jname)


class JSRFWorld(World):
    """Jet Set Radio Future: area unlock randomizer."""
    game = GAME_NAME
    web = JSRFWebWorld()
    options_dataclass = JSRFOptions
    options: JSRFOptions
    item_name_to_id = ITEM_IDS
    location_name_to_id = LOCATION_IDS
    location_name_groups = LOCATION_GROUPS
    item_name_groups = {"Area Unlocks": {unlock_name(a) for a in AREAS},
                        "Characters": {character_item_name(c) for c in CHARACTER_ITEMS},
                        "Mystery Tapes": {tape_item_name(a) for a in AREAS}}

    def _included(self, loc: LocData) -> bool:
        if loc.kind == "tape":
            return bool(self.options.include_mystery_tapes)
        if loc.kind == "challenge_soul":
            return bool(self.options.include_street_challenges)
        return True

    def generate_early(self) -> None:
        # Gouji's Tower requirements stacked on the Tower Unlock item (0 = not needed); souls are worked out in create_items.
        self.tags_needed = tags_needed(self.options.tags_needed_percent.value)
        self.challenges_needed = min(self.options.challenges_needed.value, CHALLENGE_TOTAL)
        # Goal: beat Gouji, or Jet ranks on that many Test Runs (user, 2026-11-17 19:25: one or the other, not both).
        self.goal = "jet_ranks" if self.options.goal.value == 1 else "defeat_gouji"
        self.jets_needed = min(self.options.jet_ranks_needed.value, TEST_RUN_TOTAL) if self.goal == "jet_ranks" else 0
        choice = self.options.starting_character.value
        if choice == 24:
            self.start_characters = sorted(START_CHARACTERS)
        elif choice in CHARACTERS:
            self.start_characters = [choice]
        else:
            self.start_characters = [self.random.choice(sorted(CHARACTERS))]

    def _character_included(self, u) -> bool:
        """A character's unlock is a location when the option asks for its kind, except for a character you start with
        (the game would never place that challenge or give that reward while the character is already in the roster)."""
        mode = self.options.character_unlocks.value
        if u.char in getattr(self, "start_characters", ()):
            return False
        return mode == 2 or (mode == 1 and u.kind == "recruit")

    def create_item(self, name: str) -> JSRFItem:
        # Graffiti Souls are a collect-N item: progression, but kept out of progression balancing (seed testing 2026-11-17).
        if name == SOUL_ITEM:
            return JSRFItem(name, ItemClassification.progression_skip_balancing, self.item_name_to_id[name], self.player)
        cls = (ItemClassification.progression if name.endswith(" Unlock")
               or name in self.item_name_groups["Mystery Tapes"]
               else ItemClassification.useful if name in self.item_name_groups["Characters"]
               else ItemClassification.filler)
        return JSRFItem(name, cls, self.item_name_to_id[name], self.player)

    def get_filler_item_name(self) -> str:
        return self.random.choice(FILLER_ITEMS)

    def create_regions(self) -> None:
        self.created: Set[str] = set()
        menu = Region("Menu", self.player, self.multiworld)
        regions = {GARAGE: Region(GARAGE, self.player, self.multiworld)}
        menu.connect(regions[GARAGE])
        self.multiworld.regions += [menu, regions[GARAGE]]

        for area in AREAS:
            region = Region(area, self.player, self.multiworld)
            for loc in AREA_LOCATIONS[area]:
                if not self._included(loc):
                    continue
                name = location_name(area, loc)
                region.locations.append(
                    JSRFLocation(self.player, name, self.location_name_to_id[name], region))
                self.created.add(name)
            if self.options.include_tags:
                for slot, _ in TAG_SPOTS[area]:
                    tname = tag_name(area, slot)
                    region.locations.append(
                        JSRFLocation(self.player, tname, self.location_name_to_id[tname], region))
                    self.created.add(tname)
            for u in CHARACTER_UNLOCKS:
                if u.area == area and self._character_included(u):
                    cname = character_location_name(u.char)
                    # (Test Run characters held filler only until the chapter number was set to 9 automatically;
                    # since 2026-11-19 they are ordinary checks, user 18:10.)
                    region.locations.append(JSRFLocation(self.player, cname, self.location_name_to_id[cname], region))
                    self.created.add(cname)
            if self.options.include_rival_battles:
                for r in RIVAL_BATTLES:
                    if r.area == area:
                        rname = rival_location_name(r)
                        region.locations.append(
                            JSRFLocation(self.player, rname, self.location_name_to_id[rname], region))
                        self.created.add(rname)
            if self.options.include_jet_ranks:
                for t in TEST_RUNS:
                    if t.area == area:
                        jname = jet_location_name(t)
                        region.locations.append(
                            JSRFLocation(self.player, jname, self.location_name_to_id[jname], region))
                        self.created.add(jname)
            regions[area] = region
            self.multiworld.regions.append(region)

        # Two-way map connections; entering an area requires its Unlock item.
        for a, b in CONNECTIONS:
            for src, dst in ((a, b), (b, a)):
                if dst == GARAGE:
                    continue
                regions[src].connect(
                    regions[dst],
                    rule=lambda state, d=dst: state.has(unlock_name(d), self.player))

        tower = Region(TOWER, self.player, self.multiworld)
        self.multiworld.regions.append(tower)
        player = self.player
        # The tag spot / Street Challenge requirements are events in the Garage (rules in set_rules).
        needs = []
        for wanted, event, item in ((self.tags_needed, TAGS_EVENT, TAGS_EVENT_ITEM),
                                    (self.challenges_needed, CHALLENGES_EVENT, CHALLENGES_EVENT_ITEM)):
            if wanted:
                loc = JSRFLocation(player, event, None, regions[GARAGE])
                loc.place_locked_item(JSRFItem(item, ItemClassification.progression, None, player))
                regions[GARAGE].locations.append(loc)
                needs.append(item)
        if self.jets_needed:                       # the Jet Ranks goal: an event in the Garage (rule in set_rules)
            loc = JSRFLocation(player, JETS_EVENT, None, regions[GARAGE])
            loc.place_locked_item(JSRFItem(JETS_EVENT_ITEM, ItemClassification.progression, None, player))
            regions[GARAGE].locations.append(loc)
        regions[TOWER_PARENT].connect(
            tower,
            # Entering = winning the Zero Beat fight: the Tower Unlock item plus whatever requirements are on.
            rule=lambda state: (state.has(TOWER_UNLOCK, player)
                                and (not self.souls_required or state.has(SOUL_ITEM, player, self.souls_required))
                                and state.has_all(needs, player)))
        gouji = JSRFLocation(self.player, GOUJI_EVENT, None, tower)
        gouji.place_locked_item(JSRFItem(GOUJI_EVENT_ITEM, ItemClassification.progression, None, self.player))
        tower.locations.append(gouji)

    def create_items(self) -> None:
        start = STARTING_AREAS[self.options.starting_area.value]
        self.multiworld.push_precollected(self.create_item(unlock_name(start)))
        pool = [self.create_item(unlock_name(a)) for a in AREAS if a != start]
        pool.append(self.create_item(TOWER_UNLOCK))
        if self.options.include_mystery_tapes:
            # All 13 tape items go in the pool, the starting area's too (user, 2026-11-19: the start gives the area only).
            pool += [self.create_item(tape_item_name(a)) for a in AREAS]

        # Slots for characters and souls.
        room = len(self.created) - len(pool)
        if room < 1:
            raise OptionError(f"JSRF ({self.player_name}): no location is left for Graffiti Souls with these options.")
        if not hasattr(self, "start_characters"):
            self.generate_early()
        chars = [c for c in CHARACTER_ITEMS if c not in self.start_characters]
        self.random.shuffle(chars)
        # Characters keep their slots first, then Graffiti Souls up to the requested number (at least one), then filler.
        # Characters that do not fit (very small pools only) are given at the start instead.
        wanted = self.options.souls_in_pool.value if self.options.souls_required_percent.value else 0
        souls = max(1, min(wanted, room - len(chars))) if wanted else 0
        if souls < wanted:
            logging.warning(f"JSRF ({self.player_name}): Graffiti Souls In Pool lowered from {wanted} to {souls}, the "
                            f"slots left with the enabled locations after the character items.")
        in_pool, at_start = chars[:room - souls], chars[room - souls:]
        # Souls Required is a percent of the souls actually in the pool (rounded up, at least 1).
        self.souls_in_pool = souls
        self.souls_required = max(1, min(souls, -(-souls * self.options.souls_required_percent.value // 100))) if souls else 0
        for c in at_start:
            self.multiworld.push_precollected(self.create_item(character_item_name(c)))
        pool += [self.create_item(character_item_name(c)) for c in in_pool]
        pool += [self.create_item(SOUL_ITEM) for _ in range(souls)]
        while len(pool) < len(self.created):
            pool.append(self.create_item(self.get_filler_item_name()))
        self.multiworld.itempool += pool

    def set_rules(self) -> None:
        # Extra reachability requirements on individual locations.
        for area in AREAS:
            for loc in AREA_LOCATIONS[area]:
                name = location_name(area, loc)
                if name not in self.created or not loc.reach:
                    continue
                for needed in loc.reach:
                    add_rule(self.multiworld.get_location(name, self.player),
                             lambda state, n=needed: state.can_reach(n, "Region", self.player))

        # With Mystery Tape items, an area's Street Challenges open only when its tape item has arrived.
        if self.options.include_mystery_tapes:
            for area in AREAS:
                for loc in AREA_LOCATIONS[area]:
                    name = location_name(area, loc)
                    if loc.kind == "challenge_soul" and name in self.created:
                        add_rule(self.multiworld.get_location(name, self.player),
                                 lambda state, t=tape_item_name(area): state.has(t, self.player))

        player = self.player
        tapes = bool(self.options.include_mystery_tapes)

        def test_runs_open(state, area: str) -> bool:
            """Roboy offers the area's Test Runs: every Graffiti Soul of the area can be possessed (the area, each soul's
            extra reach and, with tape items, the area's tape item for its Street Challenges)."""
            return (state.can_reach_region(area, player) and all(state.can_reach_region(r, player) for r in soul_reach(area))
                    and (not tapes or state.has(tape_item_name(area), player)))

        for u in CHARACTER_UNLOCKS:
            cname = character_location_name(u.char)
            if cname in self.created:
                for needed in u.reach:
                    add_rule(self.multiworld.get_location(cname, self.player),
                             lambda state, n=needed: state.can_reach(n, "Region", self.player))
                if u.kind == "test_run":           # a Jet rank on all of the area's Test Runs (Poison Jam: both sewage areas)
                    add_rule(self.multiworld.get_location(cname, player),
                             lambda state, areas=(u.area,) + u.reach: all(test_runs_open(state, a) for a in areas))
        for t in TEST_RUNS:
            jname = jet_location_name(t)
            if jname in self.created:
                add_rule(self.multiworld.get_location(jname, player), lambda state, a=t.area: test_runs_open(state, a))

        if self.tags_needed:
            # Any tag spot counts, check or not, so an area adds all of its spots once it can be reached.
            need_tags = self.tags_needed
            add_rule(self.multiworld.get_location(TAGS_EVENT, player),
                     lambda state: sum(TAG_COUNTS[a] for a in AREAS if state.can_reach_region(a, player)) >= need_tags)
        if self.challenges_needed:
            # A Street Challenge can be cleared once its area (and anything its soul's spot needs) can be reached and,
            # with Mystery Tape items, the area's tape item is in (whether the challenge souls are checks or not).
            tapes = bool(self.options.include_mystery_tapes)
            per_area = {a: [loc.reach for loc in AREA_LOCATIONS[a] if loc.kind == "challenge_soul"] for a in AREAS}
            need = self.challenges_needed

            def challenges_open(state) -> bool:
                n = 0
                for a, reaches in per_area.items():
                    if not state.can_reach_region(a, player) or (tapes and not state.has(tape_item_name(a), player)):
                        continue
                    n += sum(1 for r in reaches if all(state.can_reach_region(x, player) for x in r))
                    if n >= need:
                        return True
                return False
            add_rule(self.multiworld.get_location(CHALLENGES_EVENT, player), challenges_open)
        if self.jets_needed:
            # Roboy offers an area's Test Runs (3 per area) once every Graffiti Soul of the area is possessed, Street
            # Challenge souls included: the area, each soul's extra reach and, with tape items, the area's tape item.
            runs_per_area = {a: sum(1 for t in TEST_RUNS if t.area == a) for a in AREAS}
            need_jets = self.jets_needed

            def runs_open(state) -> bool:
                n = 0
                for a, runs in runs_per_area.items():
                    if test_runs_open(state, a):
                        n += runs
                        if n >= need_jets:
                            return True
                return False
            add_rule(self.multiworld.get_location(JETS_EVENT, player), runs_open)

        goal_item = JETS_EVENT_ITEM if self.goal == "jet_ranks" else GOUJI_EVENT_ITEM
        self.multiworld.completion_condition[player] = lambda state: state.has(goal_item, player)

    def fill_slot_data(self) -> Dict[str, object]:
        return {
            "tags_needed": self.tags_needed,
            "challenges_needed": self.challenges_needed,
            "goal": self.goal,
            "jets_needed": self.jets_needed,
            "souls_required": self.souls_required,
            "souls_in_pool": self.souls_in_pool,
            "starting_area": STARTING_AREAS[self.options.starting_area.value],
            "include_tags": bool(self.options.include_tags),
            "include_mystery_tapes": bool(self.options.include_mystery_tapes),
            "include_street_challenges": bool(self.options.include_street_challenges),
            "include_rival_battles": bool(self.options.include_rival_battles),
            "include_jet_ranks": bool(self.options.include_jet_ranks),
            "character_unlocks": self.options.character_unlocks.value,
            "start_characters": list(self.start_characters),
            "tape_items": bool(self.options.include_mystery_tapes),
            "release": RELEASE,                                  # the client warns when its own release differs
        }
