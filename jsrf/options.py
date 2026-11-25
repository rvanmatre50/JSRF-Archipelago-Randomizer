import random
from dataclasses import dataclass
from typing import Dict

from Options import Choice, DefaultOnToggle, OptionGroup, PerGameCommonOptions, Range, Toggle

# Docstrings are what players read: the hover tooltip in the Launcher's Options Creator, the comments in the YAML
# template, and the options page on the website. Keep them player-facing, lines under ~76 characters (the tooltip does not
# wrap), and put a blank line between the descriptions of a choice's values.


class NamedChoice(Choice):
    """A Choice whose values have hand-written names in the Options Creator and the website (Archipelago's automatic
    names would read "99Th Street", "Rokkaku Dai Heights", "Nt 3000"). The YAML keys stay the option_ names."""
    display_names: Dict[str, str] = {}

    @classmethod
    def get_option_name(cls, value) -> str:
        key = value if isinstance(value, str) else cls.name_lookup.get(value, str(value))
        return cls.display_names.get(key, key.replace("_", " ").title())


class SoulsRequiredPercent(Range):
    """Gouji's Tower always needs the Gouji's Tower Unlock item. This option
    and the Tag Spots and Street Challenges ones below stack more on top
    of it: each one you turn on makes the road to the boss longer.

    This one: the percent of your Graffiti Soul items (below) you need.
    Rounded up: 70 items at 70% means 49.

    **0:** no souls needed, and no Graffiti Soul items are added."""
    display_name = "Tower: Graffiti Souls Needed (%)"
    range_start = 0
    range_end = 100
    default = 70


class SoulsInPool(Range):
    """How many Graffiti Soul items are shuffled into the multiworld (1-300).
    They are items, separate from the 105 souls you find in the levels, so
    with graffiti tags on you can add more than 105 in place of some filler.
    If there are not enough free slots, this is lowered (with a warning).
    Not used when Graffiti Souls Needed is 0."""
    display_name = "Graffiti Soul Items"
    range_start = 1
    range_end = 300
    default = 70


class TagsNeededPercent(Range):
    """Adds a requirement to Gouji's Tower: spray this percent of the city's
    573 graffiti tag spots (every piece of a spot). Any spot counts, check
    or not. Rounded up: 50% is 287 spots. Each area holds 26 to 65 (99th
    Street 66, with the Expo Stadium's spot), so a high share needs most
    of the Unlock items.

    **0** (the default): not needed."""
    display_name = "Tower: Tag Spots Needed (%)"
    range_start = 0
    range_end = 100
    default = 0


class ChallengesNeeded(Range):
    """Adds a requirement to Gouji's Tower: clear this many of the 65
    Street Challenges (5 per area). With Mystery Tapes on, an area's
    challenges open with its Mystery Tape item.

    **0** (the default): not needed."""
    display_name = "Tower: Street Challenges Needed"
    range_start = 0
    range_end = 65
    default = 0


class StartingArea(NamedChoice):
    """Which Garage area is unlocked when you start. Corn tells you which one
    when you start your New Game. The other areas arrive as Unlock items.
    Tick Random? to have one of the four picked for you."""
    display_name = "Starting Area"
    option_dogenzaka_hill = 0
    option_shibuya_terminal = 1
    option_rokkaku_dai_heights = 2
    option_99th_street = 3
    # A real default, not "random": with "random" the Options Creator kept writing random after Random? was unticked,
    # whatever the list showed (user, 2026-11-19 20:11). Its Random? button still writes "random".
    default = option_dogenzaka_hill
    display_names = {"dogenzaka_hill": "Dogenzaka Hill", "shibuya_terminal": "Shibuya Terminal",
                     "rokkaku_dai_heights": "Rokkaku-dai Heights", "99th_street": "99th Street"}


class StartingCharacter(NamedChoice):
    """Who you start as. Every other character arrives as an item.

    **Classic:** Corn, Gum and Yoyo, like a normal New Game.

    Or pick any character by name. Tick **Random?** to have one character
    picked at random (never Classic)."""
    display_name = "Starting Character"
    option_beat = 0
    option_corn = 1
    option_gum = 2
    option_combo = 3
    option_rhyth = 4
    option_soda = 5
    option_yoyo = 6
    option_nt_3000 = 7
    option_garam = 8
    option_boogie = 9
    option_cube = 10
    option_love_shockers = 11
    option_poison_jam = 12
    option_noise_tanks = 13
    option_immortals = 14
    option_doom_riders = 15
    option_rapid_99 = 16
    option_pots = 17
    option_gouji = 18
    option_roboy = 19
    option_clutch = 20
    option_jazz = 21
    option_a_ku_mu = 22
    option_zero_beat = 23
    option_classic = 24
    default = option_beat             # not "random" (see StartingArea)
    display_names = {"nt_3000": "NT-3000", "a_ku_mu": "A.KU.MU", "rapid_99": "Rapid 99",
                     "classic": "Classic (Corn, Gum, Yoyo)"}

    @classmethod
    def from_text(cls, text: str) -> "StartingCharacter":
        # "random" (the Options Creator's Random? button, or a YAML) means one random character, never Classic.
        # "random_character" is the old name of that choice (YAMLs from before 2026-11-17).
        if text.lower() in ("random", "random_character"):
            return cls(random.choice(range(cls.option_classic)))
        return super().from_text(text)


class IncludeTags(Toggle):
    """Every graffiti tag spot in the 13 areas and The Future Site of Rokkaku
    Expo Stadium becomes a check: 573 in all, save point tags included. A spot counts once all of its pieces are
    sprayed. Makes the seed a lot longer."""
    display_name = "Include Graffiti Tags"


class IncludeMysteryTapes(DefaultOnToggle):
    """Each area's Mystery Tape becomes a check (13), and 13 Mystery Tape items
    are added. An area's Street Challenges only open once you receive its
    Mystery Tape item, your starting area's included."""
    display_name = "Include Mystery Tapes"


class IncludeStreetChallenges(DefaultOnToggle):
    """The 65 Graffiti Souls earned from Street Challenges become checks.
    Each one counts when you pick up its soul."""
    display_name = "Include Street Challenges"


class IncludeRivalBattles(DefaultOnToggle):
    """Beating the Doom Riders (Dogenzaka Hill), the Love Shockers
    (Hikage Street) and the Immortals (99th Street) become checks (3)."""
    display_name = "Include Rival Gang Battles"


class CharacterUnlocks(NamedChoice):
    """Which character unlocks are checks. Characters are always items.

    **Recruits:** beating Rhyth, Boogie, Cube, Jazz and Soda in their
    challenges (5 checks).

    **All:** also the characters the game gives for a Jet rank on all of an
    area's Test Runs (12 more; Poison Jam needs both sewage areas).

    **Off:** none."""
    display_name = "Character Unlock Checks"
    option_off = 0
    option_recruits = 1
    option_all = 2
    default = 1


class IncludeJetRanks(DefaultOnToggle):
    """Each Test Run you finish with a Jet rank becomes a check (39: Jet
    Graffiti and Jet Tech in every area, plus Jet Dash or Jet Flag). As in
    the normal game, Roboy in the Garage offers an area's Test Runs once you
    have every Graffiti Soul there, Street Challenges included."""
    display_name = "Include Jet Ranks"


class Goal(NamedChoice):
    """How you finish.

    **Defeat Gouji:** beat the final boss in Gouji's Tower. The Tower's
    requirements are the options below.

    **Jet Ranks:** earn a Jet rank on Test Runs (Jet Ranks Needed). As in
    the normal game, Roboy in the Garage offers an area's Test Runs once
    you have every Graffiti Soul there, Street Challenges included.
    Experimental: not play-tested yet."""
    display_name = "Goal"
    option_defeat_gouji = 0
    option_jet_ranks = 1
    default = 0


class JetRanksNeeded(Range):
    """Jet Ranks goal only: how many of the 39 Test Runs you need a Jet rank
    on (3 per area: Jet Graffiti, Jet Tech, and Jet Dash or Jet Flag).
    39 means every one."""
    display_name = "Jet Ranks Needed"
    range_start = 1
    range_end = 39
    default = 39


@dataclass
class JSRFOptions(PerGameCommonOptions):
    goal: Goal
    jet_ranks_needed: JetRanksNeeded
    souls_required_percent: SoulsRequiredPercent
    souls_in_pool: SoulsInPool
    tags_needed_percent: TagsNeededPercent
    challenges_needed: ChallengesNeeded
    starting_area: StartingArea
    starting_character: StartingCharacter
    include_tags: IncludeTags
    include_mystery_tapes: IncludeMysteryTapes
    include_street_challenges: IncludeStreetChallenges
    include_rival_battles: IncludeRivalBattles
    include_jet_ranks: IncludeJetRanks
    character_unlocks: CharacterUnlocks


# Panels in the Options Creator and sections on the website / YAML template (Archipelago's own "Game Options" with
# Progression Balancing and Accessibility comes first, "Item & Location Options" last).
OPTION_GROUPS = [
    OptionGroup("Goal", [Goal, JetRanksNeeded]),
    OptionGroup("Gouji's Tower", [SoulsRequiredPercent, SoulsInPool, TagsNeededPercent, ChallengesNeeded]),
    OptionGroup("Starting Out", [StartingArea, StartingCharacter]),
    OptionGroup("Checks", [IncludeTags, IncludeMysteryTapes, IncludeStreetChallenges, IncludeRivalBattles,
                           IncludeJetRanks, CharacterUnlocks]),
]
