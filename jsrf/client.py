"""Archipelago client for Jet Set Radio Future (JSRF Unleashed).

Run the game first, then open "Jet Set Radio Future Client" from the Archipelago Launcher and connect.
The client reads the game's memory to find your Graffiti Souls and Street Challenges. It writes to the game in one
place only: when you stand in an area whose Unlock item you do not have, it starts the free-skate Garage, the same way
the game's own F6 map selector starts a mission (see game.py). Turn that off with /bounce off. The same primitive
powers /tower, which starts Gouji's Tower (the last chapter's Future Go Go mission) once its items have arrived.

Corn's text box (see talk.py): the client rewrites the English text of the game's TE001 talk file in the engine's cache
folder, so Corn's New Game box explains that the city is locked, and so that a locked-area bounce can go through Corn first
("you can't go to X yet") before the free-skate Garage. /corn off puts his own words back and bounces straight to the Garage.

Corn in the free-skate Garage (see garage.py): the client also writes its own copy of the Garage's mission file into the
cache folder, so Corn stands at his New Game spot there; talking to him asks about Gouji's Tower (or says what it still
needs). /corn garage off takes him out again.
"""
import asyncio
import os
import logging
import time
import zlib
from typing import Dict, List, Optional, Set, Tuple

import Utils
from NetUtils import ClientStatus
from CommonClient import ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, logger, server_loop

from . import game as jsrf_game
from . import talk as jsrf_talk
from . import garage as jsrf_garage
from .overlay import Overlay, format_notice

# Details for the log file only: the client window shows the "Client" logger, so these stay out of the player's way
# (user, 2026-11-17 19:32: at start the window only needs the starting area, the character and "Found the game.").
# The lines that came with every check (Checked N location(s), Received, Refilled, tape picked up, character joined,
# rival fights) are details too: the server's "JSRF found ..." line says it (user, 2026-11-19 20:21).
detail = logging.getLogger("JSRF")
from .data import (AREAS, CORN_CHAIN, CORN_CHAIN_STOP, CORN_DONE_FLAG, CORN_FLAG_SETUP, CORN_FLAG_TALK, CORN_FLAG_TALKING,
                   CORN_FLAGS_RESET, CORN_MISSION, CORN_MISSION_ID,
                   DEFAULT_START_INDEX, FINALE_STAGES, GAME_NAME, GARAGE_START_INDEX, GARAGE_STAGE,
                   GOAL_STAGE, OTHER_STAGES, SOUL_ITEM, STAGE_AREAS, TAG_SPOTS, TOWER,
                   CHARACTERS, CHARACTER_UNLOCKS, CHARACTER_UNLOCK_OF, START_CHARACTERS,
                   character_of_item, character_location_id, character_location_name,
                   AREA_LOCATIONS, BASE_ID, character_of_location, rival_of_location, tag_slot_of_id,
                   RIVAL_BATTLES, rival_location_id, rival_location_name,
                   area_of_tape_item, TAPE_FLAG, challenge_flags, challenge_setup_flags, tape_item_name, SPRAY_REFILL, HEALTH_REFILL,
                   TOWER_MISSION, TOWER_STAGE, TOWER_UNLOCK, area_of_stage, unlock_name, location_requirements,
                   CREDITS_MISSION_ID, RELEASE,
                   CHALLENGE_TOTAL, TAG_TOTAL, TEST_RUNS, TEST_RUN_KINDS, TEST_RUN_TOTAL, area_soul_ids, JET_LOCATION_OF)

TAPE_AREA = {n: area for area, n in TAPE_FLAG.items()}         # Riddle Tape flag N -> area
TOWER_STAGES = frozenset({TOWER_STAGE, *FINALE_STAGES})      # the Zero Beat fight, the Tower and the finale cutscenes
KNOWN_STAGES = frozenset({GARAGE_STAGE, *STAGE_AREAS, *OTHER_STAGES, *TOWER_STAGES})

POLL_SECONDS = 0.25
MENU_POLL = 0.05               # seconds between looks for the open pause menu (its soul total, menu_watcher)
RESTORE_EVERY = 2.0            # seconds between looks for progress the server has but the loaded save lacks
TAPE_SCAN_SECONDS = 0.5        # how often to look for a picked-up tape the level placed again
TAPE_EVENT_MAX = 20.0          # a defused tape sequence that is still there after this long: set the tape's flag anyway
ITEM_SETTLE_SECONDS = 3.0      # after connecting, wait for the item list before calling an area locked
BOUNCE_DELAY = 1.0             # seconds in a locked area before the player is sent back (ignores a stray reading)
BOUNCE_COOLDOWN = 15.0         # after sending the player back, leave the game alone this long while it loads
BOUNCE_RETRY = 4.0             # after a bounce that could not be done, wait this long before trying again
STAGE_SETTLE = 4.0             # the stage code must stay unchanged this long before the client writes anything to the game
                               # (the code changes when a load is requested, before the player is placed; /settle changes it)
CONFIRM_DELAY = 0.25           # just before a write the mission object is read a second time after this long
CORN_ARRIVE_TIMEOUT = 40.0     # Corn's mission must be running and settled this soon after the bounce, else a plain Garage bounce
CORN_TALK_TIMEOUT = 300.0      # the text box must be done this soon after it started (the player has to press buttons)
CORN_SCAN_EVERY = 2.0          # seconds between full memory scans for Corn's mission object
GOAL_POLL = 2.0                # seconds between counts of tag spots / Street Challenges for Gouji's Tower
SHUT_GARAGE_WAIT = 2.0         # a story-chapter Garage (doors shut) must have been running this long before the client moves on
                               # (6 s until 2026-11-19 20:40, user: "reduce the time ... to around 2 seconds")
MISSION_SCAN_EVERY = 2.0       # seconds between full scans for the running mission when the cached one is gone
TEST_RUN_HIS = range(30, 34)   # Test Run missions (Jet Graffiti, Tech, Dash, Flag)


TITLE_TEXT = "The game is on its title screen (the Shibuya demo). Start or load a game first."
BOUNCE_PROBLEMS = {
    "title": TITLE_TEXT,
    "nowrite": "The client has no write access to the game, so it cannot send you anywhere. Go back to the Garage yourself.",
    "nomission": "Could not find the running mission, so the client cannot send you back. Go back to the Garage yourself.",
    "failed": "Writing to the game failed, so the client cannot send you back. Go back to the Garage yourself.",
}
SEND_PROBLEMS = {
    "title": TITLE_TEXT,
    "nowrite": "The client has no write access to the game, so it cannot send you anywhere.",
    "nomission": "Could not find the running mission, so the client cannot send you there. Try again in a moment.",
    "failed": "Writing to the game failed, so the client cannot send you there.",
}


def is_garage_hub(mission: Optional[dict]) -> bool:
    """True for the free-skate Garage's own mission (hi 9, file mssn0900: the hub that runs while the player skates there)."""
    return (mission is not None and mission.get("hi") == jsrf_game.FREE_SKATE_CHAPTER
            and (mission.get("id", 0) & 0xFFFF) % 100 == 0)


# The commands players see (user, 2026-11-19 18:53): /goal, /tapes, /unlocks, /checks and /usesave, besides Archipelago's
# own. The others are developer tools: their methods are named _dev_<name>, so the window neither lists nor accepts them,
# unless the environment variable JSRF_DEV_COMMANDS is set when the client starts.
DEV_COMMANDS = bool(os.environ.get("JSRF_DEV_COMMANDS"))


class JSRFCommandProcessor(ClientCommandProcessor):
    def _cmd_help(self):
        """Returns the help listing"""
        # The window runs /help once by itself when it opens; that long list stays out of the start-up text (user,
        # 2026-11-17 19:32). Typing /help shows it as usual.
        if getattr(self.ctx, "startup_help_pending", False):
            self.ctx.startup_help_pending = False
            return
        super()._cmd_help()

    def _dev_game(self):
        """Show whether the game is found and how many souls it reports."""
        ctx: "JSRFContext" = self.ctx
        if ctx.game_reader is None:
            logger.info("Game not found. Start JSRF Unleashed.")
            return
        souls = ctx.state().collected_souls()
        logger.info("Game found. %s" % ("No game state loaded yet." if souls is None
                                         else "%d souls collected." % len(souls)))

    def _cmd_unlocks(self):
        """Show which areas are unlocked and how many collected checks are being held back."""
        ctx: "JSRFContext" = self.ctx
        open_areas = ctx.unlocked_areas()
        logger.info("Unlocked areas: %s" % (", ".join(a for a in AREAS if a in open_areas) or "none yet"))
        logger.info("Locked areas: %s" % (", ".join(a for a in AREAS if a not in open_areas) or "none"))
        if ctx.goal != "jet_ranks":                    # with the Jet Ranks goal the Tower is not part of the game (user, 18:53)
            missing = ctx.tower_missing()
            logger.info("%s: %s" % (TOWER, "open (talk to Corn in the Garage)" if not missing else
                                    "closed, you still need " + ", ".join(missing)))
        if ctx.game_reader is not None:
            found = ctx.state().collected_locations(ctx.challenge_on_clear, ctx.include_tags) or set()
            _, held = ctx.split_by_unlock(found)
            held = held & set(ctx.missing_locations)
            logger.info("%d collected check(s) held back until their area unlocks." % len(held))

    def _cmd_tapes(self):
        """List the areas whose Mystery Tape item you have (that item opens the area's Street Challenges)."""
        ctx: "JSRFContext" = self.ctx
        if ctx.slot is None:
            logger.info("Connect to the server first.")
            return
        if not ctx.manage_tapes:
            logger.info("This seed has no Mystery Tape items.")
            return
        have = ctx.received_tapes()
        logger.info("Tapes Acquired: %s" % (", ".join(a for a in AREAS if a in have) or "none"))

    def _dev_tags(self):
        """Show how many tag spots are sprayed in each area (when tags are checks in this seed)."""
        ctx: "JSRFContext" = self.ctx
        if not ctx.include_tags:
            logger.info("Tag spots are not checks in this seed (include_tags is off).")
            return
        if ctx.game_reader is None:
            logger.info("Game not found. Start JSRF Unleashed.")
            return
        done = ctx.state().sprayed_tags()
        open_areas = ctx.unlocked_areas()
        for area in AREAS:
            n = sum(1 for slot, _ in TAG_SPOTS[area] if (area, slot) in done)
            logger.info("%s: %d of %d tags%s" % (area, n, len(TAG_SPOTS[area]), "" if area in open_areas else " (locked, held)"))

    def _dev_characters(self):
        """Show your characters and which character unlock checks are still open."""
        ctx: "JSRFContext" = self.ctx
        if not ctx.manage_roster:
            logger.info("Characters are not items in this seed.")
            return
        got = ctx.start_chars | ctx.received_characters()
        logger.info("Your characters: %s" % ", ".join(CHARACTERS[c] for c in sorted(got)))
        logger.info("Still to receive: %s" % (", ".join(CHARACTERS[c] for c in sorted(set(CHARACTERS) - got)) or "none"))
        open_ = [character_location_name(u.char) for u in CHARACTER_UNLOCKS
                 if character_location_id(u.char) in ctx.missing_locations
                 and character_location_id(u.char) not in ctx.sent_locations]
        logger.info("Character unlock checks still open: %s" % (", ".join(open_) or "none"))
        if ctx.game_reader is not None:
            ch = ctx.state().chapter_number()
            if ch is not None and ch != 9 and any(u.kind == "test_run" for u in CHARACTER_UNLOCKS
                                                  if character_location_id(u.char) in ctx.missing_locations):
                logger.info("Note: the game's chapter number is %d; it only gives Test Run characters at 9." % ch)

    def _dev_overlay(self, mode: str = ""):
        """On-screen "Item received" notices over the game window: /overlay on, /overlay off, /overlay test."""
        ctx: "JSRFContext" = self.ctx
        mode = mode.lower()
        if mode in ("on", "off"):
            ctx.overlay.enabled = mode == "on"
        elif mode == "test":
            ctx.overlay.enabled = True
            for item, sender, own in (("Graffiti Soul", "Someone", False), ("Health Refill", None, True),
                                      ("Chuo Street Unlock", "Someone", False)):
                ctx.overlay.notify(format_notice(item, sender, own))
            logger.info("Showing three test notices over the game window.")
            return
        logger.info("On-screen item notices are %s." % ("on" if ctx.overlay.enabled else "off")
                    + (" (stopped after an error)" if ctx.overlay.failed else ""))

    def _dev_soulcounter(self, mode: str = ""):
        """What the game's Graffiti Soul counter shows: /soulcounter items (Graffiti Soul items received, the default),
        pickups (souls picked up in your game only), game (the game's own count, with 20 default graffiti)."""
        ctx: "JSRFContext" = self.ctx
        mode = mode.lower()
        if mode in ("items", "pickups", "game"):
            ctx.soul_counter_mode = mode
            ctx.soul_counter_restore = mode == "game"
            ctx.soul_counter_ahead_told = ctx.soul_counter_cap_told = False
            if ctx.game_reader is not None:
                ctx.sync_soul_counter()
        elif mode:
            logger.info("Use /soulcounter items, /soulcounter pickups or /soulcounter game.")
            return
        logger.info("The game's soul counter shows %s." % {
            "items": "the Graffiti Soul items you have received (what Gouji's Tower counts)",
            "pickups": "only the souls you pick up in your game",
            "game": "the game's own count, with 20 default graffiti"}[ctx.soul_counter_mode])

    def _dev_chapter(self, number: str = ""):
        """Show the save's story chapter number, or set it. The client keeps it at 9 in the free-skate chapter (Roboy's Test
        Run menu and the Test Run characters need it); /chapter 1 sets a New Game's value and stops that."""
        ctx: "JSRFContext" = self.ctx
        if ctx.game_reader is None:
            logger.info("Game not found. Start JSRF Unleashed.")
            return
        state = ctx.state()
        cur = state.chapter_number()
        if not number:
            logger.info("Chapter number: %s. Roboy's Test Run menu and the Test Run characters need 9; a New Game sets 1. "
                        "/chapter 9 to try it, /chapter 1 to go back." % cur)
            return
        try:
            n = int(number)
        except ValueError:
            n = -1
        if not 0 <= n <= 9:
            logger.info("Give a chapter number from 0 to 9, e.g. /chapter 9.")
            return
        if not getattr(ctx.game_reader, "can_write", False):
            logger.info("The client has no write access to the game.")
            return
        if state.set_chapter_number(n):
            ctx.chapter_auto = n == 9
            logger.info("Chapter number: %s -> %d. It is saved with your game; /chapter %s puts it back.%s" % (
                cur, n, cur, "" if n == 9 else " The client no longer sets 9 by itself (/chapter 9 turns that back on)."))
        else:
            logger.info("Could not set the chapter number (it reads %s). Load a save first." % cur)

    def _dev_player(self):
        """Show your health and spray cans as the client reads them (what refill items fill up)."""
        ctx: JSRFContext = self.ctx
        if ctx.game_reader is None:
            logger.info("The game is not running.")
            return
        p = ctx.state().player()
        if p is None:
            logger.info("No player right now (menu or loading). Try again while skating.")
            return
        done = "?" if ctx.refills_done is None else str(ctx.refills_done)
        logger.info("Health %d/%d, spray cans %d/%d (character %s). Refill items received: %d, applied: %s."
                    % (p["health"], p["health_max"], p["cans"], p["cans_max"], CHARACTERS.get(p["char"], p["char"]),
                       len(ctx.refill_names()), done))

    def _cmd_goal(self):
        """Show what Gouji's Tower still needs (your goal is beating Gouji there)."""
        ctx: JSRFContext = self.ctx
        if ctx.slot is None:
            logger.info("Connect to the server first.")
            return
        if ctx.goal == "jet_ranks":
            if ctx.goal_sent:
                logger.info("Your goal is complete: %d Jet ranks." % ctx.jets_needed)
                return
            jets = ctx.tower_counts(fresh=True).get("jets")
            logger.info("Your goal: a Jet rank on %d of the %d Test Runs. %s" % (
                ctx.jets_needed, TEST_RUN_TOTAL, "Load your save so the client can count them." if jets is None else
                "You have %d. Roboy offers an area's Test Runs once you have all of its Graffiti Souls." % jets))
            return
        if ctx.goal_sent:
            logger.info("Your goal is complete: Gouji is beaten.")
            return
        logger.info("Your goal: beat Gouji at the top of Gouji's Tower. The Tower needs:")
        for what, have, need in ctx.tower_requirements(fresh=True):
            if what.startswith("the "):
                logger.info("- %s: %s" % (what[4:], "received" if have else "not yet"))
            elif have is None:
                logger.info("- %d %s: load your save so the client can count them" % (need, what))
            else:
                total = {"sprayed tag spots": " (%d in the city)" % TAG_TOTAL,
                         "cleared Street Challenges": " (%d in all)" % CHALLENGE_TOTAL,
                         }.get(what, "")
                logger.info("- %s: %d of %d%s%s" % (what[0].upper() + what[1:], have, need, total, ", done" if have >= need else ""))
        missing = ctx.tower_missing()
        logger.info("Gouji's Tower is open: talk to Corn in the Garage." if not missing else
                    "Still missing: %s." % ", ".join(missing))

    def _cmd_usesave(self):
        """Tie the loaded save to this seed anyway, so the checks it already has are sent (for a save the client refused:
        progress from before the randomizer or from another seed, or a New Game for this seed played with the client closed)."""
        ctx: JSRFContext = self.ctx
        mine = ctx.save_marker_value()
        if ctx.game_reader is None or mine is None:
            logger.info("Connect to the server and start the game first.")
            return
        if ctx.state().collected_locations(ctx.challenge_on_clear, ctx.include_tags) is None:
            logger.info("Load the save first (it is not loaded yet).")
            return
        if not ctx.state().write_save_marker(mine):
            logger.info("Could not write to the game (was it started as another user?).")
            return
        ctx.save_status = "ok"
        logger.info("This save is now tied to this seed. The checks it already has will be sent.")

    def _cmd_checks(self):
        """Count this seed's checks by kind: how many are still open, and how many the game shows as done right now."""
        ctx: "JSRFContext" = self.ctx
        logger.info({"ok": "This save is tied to this seed.",
                     "old": "This save has progress from before this seed: nothing is sent (New Game, or /usesave).",
                     "foreign": "This save belongs to another seed: nothing is sent (New Game, or /usesave).",
                     "waiting": "Waiting to read the save or the room information before using the save."}.get(
                        ctx.save_status, "Save not checked yet (load a save while connected)."))
        kinds = {"Graffiti Souls": set(), "Street Challenge souls": set(), "Mystery Tapes": set(), "Tags": set(),
                 "Character unlocks": set(), "Rival gang battles": set(), "Jet ranks": set(JET_LOCATION_OF.values())}
        label = {"soul": "Graffiti Souls", "challenge_soul": "Street Challenge souls", "tape": "Mystery Tapes"}
        for i, area in enumerate(AREAS):
            for j, loc in enumerate(AREA_LOCATIONS[area]):
                kinds[label[loc.kind]].add(BASE_ID + 100 * i + j)
        missing = set(ctx.missing_locations)
        checked = set(getattr(ctx, "checked_locations", set()) or set())
        for loc in missing | checked:
            if tag_slot_of_id(loc):
                kinds["Tags"].add(loc)
            elif character_of_location(loc) is not None:
                kinds["Character unlocks"].add(loc)
            elif rival_of_location(loc) is not None:
                kinds["Rival gang battles"].add(loc)
        found = set()
        if ctx.game_reader is not None:
            found = (ctx.state().collected_locations(ctx.challenge_on_clear, ctx.include_tags) or set()) | ctx.char_found
        for name, ids in kinds.items():
            in_seed = ids & (missing | checked)
            if not in_seed:
                logger.info("%s: not checks in this seed." % name)
                continue
            logger.info("%s: %d in this seed, %d still open; the game shows %d done%s." % (
                name, len(in_seed), len(ids & missing), len(ids & found),
                (", %d of them waiting (area locked or not sent yet)" % len(ids & found & missing)) if ids & found & missing else ""))

    def _dev_where(self):
        """Show the stage the game is in and whether its area is unlocked."""
        ctx: "JSRFContext" = self.ctx
        if ctx.game_reader is None:
            logger.info("Game not found. Start JSRF Unleashed.")
            return
        code = ctx.state().current_stage()
        if code is None:
            logger.info("The game has not set up a stage yet.")
        elif code == GARAGE_STAGE:
            logger.info("You are in the Garage.")
        elif code in TOWER_STAGES:
            missing = ctx.tower_missing()
            where = TOWER if code == TOWER_STAGE else FINALE_STAGES[code]
            logger.info("You are in %s (%s)." % (where, "open" if not missing else "LOCKED: you still need " + ", ".join(missing)))
        elif code in OTHER_STAGES:
            logger.info("You are in %s, which has no checks." % OTHER_STAGES[code])
        else:
            area = area_of_stage(code)
            if area is None:
                logger.info("Stage 0x%08X (Stg%d%d) is not mapped to an area yet." % (code, code >> 16, code & 0xFFFF))
            else:
                logger.info("You are in %s (%s)." % (area, "unlocked" if area in ctx.unlocked_areas() else "LOCKED"))

    def _dev_bounce(self, mode: str = ""):
        """Send you back to the Garage when you enter a locked area: /bounce on or /bounce off."""
        ctx: "JSRFContext" = self.ctx
        if mode in ("on", "off"):
            ctx.bounce_enabled = mode == "on"
            ctx.bounce_told = False
        logger.info("Bouncing out of locked areas is %s. Use /bounce on or /bounce off." % ("on" if ctx.bounce_enabled else "off"))

    def _dev_garage(self):
        """Go to the free-skate Garage now, where every door is open (locked areas still send you back)."""
        ctx: "JSRFContext" = self.ctx
        if ctx.game_reader is None:
            logger.info("Game not found. Start JSRF Unleashed.")
            return
        if ctx.still_loading():
            return
        result = ctx.try_bounce()
        if result == "sent":
            logger.info("Sending you to the free-skate Garage.")
            ctx.bounce_until = time.monotonic() + BOUNCE_COOLDOWN
        else:
            logger.info(BOUNCE_PROBLEMS.get(result, "The mission is still loading. Try again in a moment."))

    def _dev_autogarage(self, mode: str = ""):
        """Send you to the free-skate Garage when Corn's text box at the start of a New Game ends: /autogarage on or off."""
        ctx: "JSRFContext" = self.ctx
        if mode in ("on", "off"):
            ctx.auto_garage = mode == "on"
            ctx.auto_garage_done = False
        logger.info("Going to the free-skate Garage by itself after Corn's text box is %s. Use /autogarage on or /autogarage off."
                    % ("on" if ctx.auto_garage else "off"))

    def _dev_settle(self, seconds: str = ""):
        """Show or set how long the client waits after a level change before it moves you, e.g. /settle 6."""
        ctx: "JSRFContext" = self.ctx
        if seconds:
            try:
                ctx.stage_settle = min(30.0, max(0.5, float(seconds)))
            except ValueError:
                logger.info("Give a number of seconds, for example /settle 6.")
                return
        logger.info("The client waits %.1f s after a level change before it moves you (and %d s after it has moved you). "
                    "Raise this with /settle <seconds> if you ever land out of bounds." % (ctx.stage_settle, BOUNCE_COOLDOWN))

    def _dev_startpoint(self, index: str = ""):
        """Show or set which spot of the Garage you are sent to, e.g. /startpoint 24 (0-26, or -1 for the game's own default)."""
        ctx: "JSRFContext" = self.ctx
        if index:
            try:
                value = int(index)
            except ValueError:
                value = 99
            if not -1 <= value <= 26:
                logger.info("Give a number from 0 to 26, or -1 for the game's own default, for example /startpoint 24.")
                return
            ctx.garage_start = value
        current = ctx.state().start_index() if ctx.game_reader is not None else None
        logger.info("You are sent to Garage spot %d (0-23 are in front of the doors, 24 is the middle of the room, -1 the game's own "
                    "default). The game's spawn spot reads %s right now." % (ctx.garage_start, "unknown" if current is None else current))

    def _dev_corn(self, *words: str):
        """Corn's text box: /corn, /corn on|off, /corn bounce on|off, /corn garage on|off (Corn waits in the free-skate
        Garage with the Gouji's Tower question), /corn test, /corn folder <game folder>."""
        ctx: "JSRFContext" = self.ctx
        args = [w.lower() for w in words]
        if args[:1] == ["folder"]:
            path = " ".join(words[1:]).strip().strip('"')
            if not path:
                logger.info("Give the folder that holds engine and save, for example /corn folder C:\\Games\\JSRF Unleashed")
                return
            ctx.corn_root, ctx.corn_patch = path, None
            ctx.overlay.game_root = path
            ctx.corn_told.clear()
            if ctx.garage_corn and ctx.game_reader is not None:
                ctx.garage_setup()                     # (says so itself when the folder lacks the Garage's files)
            logger.info("Game folder set to %s. %s" % (path, "Corn's text is ready." if ctx.corn_show_idle() else "That folder did not work."))
            return
        if args[:1] == ["garage"] and args[1:2] in (["on"], ["off"]):
            ctx.garage_corn = args[1] == "on"
            ctx.corn_told = {t for t in ctx.corn_told if not t.startswith("garage: ")}
            if ctx.garage_corn:
                if ctx.game_reader is None:
                    logger.info("Corn will wait in the free-skate Garage once the game is found.")
                elif ctx.garage_setup():
                    logger.info("Corn waits in the free-skate Garage from the next time it loads. Talk to him about %s." % TOWER)
            else:
                ctx.garage_restore()
                logger.info("Corn leaves the free-skate Garage the next time it loads. /tower takes you to %s." % TOWER)
            return
        if args[:1] == ["test"]:
            if ctx.game_reader is None:
                logger.info("Game not found. Start JSRF Unleashed.")
                return
            if ctx.still_loading():
                return
            locked = [a for a in AREAS if a not in ctx.unlocked_areas()]
            area = locked[0] if locked else TOWER
            result = ctx.try_corn(area)
            if result == "sent":
                logger.info("Sending you to Corn, who talks about %s, then to the free-skate Garage." % area)
                ctx.bounce_until = time.monotonic() + BOUNCE_COOLDOWN
            elif result == "plain":
                logger.info("Corn's text could not be set, so nothing was started. See the message above.")
            else:
                logger.info(SEND_PROBLEMS.get(result, "The mission is still loading. Try again in a moment."))
            return
        if args[:1] in (["on"], ["off"]):
            ctx.corn_text = ctx.corn_bounce = args[0] == "on"
            ctx.corn_told.clear()
            ctx.corn_show_idle()
        elif args[:1] == ["bounce"] and args[1:2] in (["on"], ["off"]):
            ctx.corn_bounce = args[1] == "on"
        patch = ctx.corn_patch
        logger.info("Corn's New Game text is %s. Locked-area bounces %s. Corn %s in the free-skate Garage. Game folder: %s. "
                    "Text file: %s. Use /corn on, /corn off, /corn bounce on|off, /corn garage on|off, /corn test or "
                    "/corn folder <path>." % (
                        "ours" if ctx.corn_text else "his own", "go through Corn first" if ctx.corn_bounce else "go straight to the Garage",
                        "waits" if ctx.garage_active() else "does not wait" if not ctx.garage_corn else "could not be put",
                        (patch.root if patch is not None else ctx.corn_root) or "not looked for yet",
                        patch.cache if patch is not None and patch.ok else "not found yet"))

    def _dev_tower(self, *args):
        """Go to Gouji's Tower now (needs the Gouji's Tower Unlock item and enough Graffiti Soul items).
        /tower ask: have Corn ask you in the Garage now. /tower prompt on|off: Corn asks by himself the first time you come
        to the Garage with the Tower open (default on; once per seed)."""
        ctx: "JSRFContext" = self.ctx
        if args[:1] == ("prompt",) and args[1:2] in (("on",), ("off",)):
            ctx.tower_prompt = args[1] == "on"
            logger.info("Corn %s ask about %s the first time you come to the Garage with it open."
                        % ("will" if ctx.tower_prompt else "won't", TOWER))
            return
        if ctx.game_reader is None:
            logger.info("Game not found. Start JSRF Unleashed.")
            return
        if args[:1] == ("ask",):
            missing = ctx.tower_missing()
            if missing:
                logger.info("%s is still closed. You need %s." % (TOWER, ", ".join(missing)))
            elif ctx.stage != GARAGE_STAGE or ctx.corn_phase is not None:
                logger.info("Go to the Garage first (and wait for any talk to end).")
            elif not ctx.still_loading():
                result = ctx.try_tower_ask()
                if result not in ("sent",):
                    logger.info(SEND_PROBLEMS.get(result, "Corn could not be asked right now. Try again in a moment."))
            return
        missing = ctx.tower_missing()
        if missing:
            logger.info("%s is still closed. You need %s." % (TOWER, ", ".join(missing)))
            return
        if ctx.still_loading():
            return
        result = ctx.try_send(*TOWER_MISSION)
        if result == "sent":
            logger.info("Sending you to %s." % TOWER)
            ctx.bounce_until = time.monotonic() + BOUNCE_COOLDOWN
        else:
            logger.info(SEND_PROBLEMS.get(result, "The mission is still loading. Try again in a moment."))

    def _dev_testrun(self, *words):
        """List the Test Runs (with your Jet ranks), or start one from the Garage: /testrun <area> <graffiti|tech|dash|flag>,
        e.g. /testrun dogenzaka tech. An area's Test Runs need its Unlock item. Experimental."""
        ctx: "JSRFContext" = self.ctx
        if ctx.game_reader is None:
            logger.info("Game not found. Start JSRF Unleashed.")
            return
        jets = ctx.state().jet_ranks() or set()
        open_areas = ctx.unlocked_areas()
        words = [w.lower() for w in words]
        if not words:
            logger.info("Test Runs (%d of %d with a Jet rank). Start one from the Garage with /testrun <area> <type>:"
                        % (len(jets), TEST_RUN_TOTAL))
            for area in AREAS:
                runs = [t for t in TEST_RUNS if t.area == area]
                logger.info("- %s%s: %s" % (area, "" if area in open_areas else " (locked)", ", ".join(
                    "%s%s" % (t.kind[4:], " (Jet)" if (t.area, t.hi) in jets else "") for t in runs)))
            return
        kind_words = {"graffiti": 30, "tech": 31, "dash": 32, "flag": 33}
        hi = next((kind_words[w] for w in words if w in kind_words), None)
        area_words = [w for w in words if w not in kind_words and w != "jet"]
        areas = [a for a in AREAS if area_words and all(w in a.lower() for w in area_words)]
        if hi is None or len(areas) != 1:
            logger.info("Say which area and which Test Run, e.g. /testrun dogenzaka tech (types: graffiti, tech, dash, flag)."
                        + (" That matches %s." % ", ".join(areas) if len(areas) > 1 else ""))
            return
        run = next((t for t in TEST_RUNS if t.area == areas[0] and t.hi == hi), None)
        if run is None:
            logger.info("%s has no %s Test Run. It has: %s." % (areas[0], TEST_RUN_KINDS[hi], ", ".join(
                t.kind for t in TEST_RUNS if t.area == areas[0])))
            return
        if run.area not in open_areas:
            logger.info("%s is locked: you need the %s item first." % (run.area, unlock_name(run.area)))
            return
        souls = ctx.state().collected_souls() or set()
        need = area_soul_ids(run.area)
        if not need <= souls:
            logger.info("%s's Test Runs open once you have all of its Graffiti Souls (%d of %d), Street Challenges "
                        "included, the same rule as Roboy's menu." % (run.area, len(need & souls), len(need)))
            return
        if ctx.stage != GARAGE_STAGE or ctx.corn_phase is not None:
            logger.info("Go to the Garage first (and wait for any talk to end).")
            return
        if ctx.still_loading():
            return
        result = ctx.try_send(run.hi, run.lo)
        if result == "sent":
            logger.info("Sending you to %s's %s Test Run. When it is over, /garage brings you back if the game does not."
                        % (run.area, run.kind))
            ctx.bounce_until = time.monotonic() + BOUNCE_COOLDOWN
        else:
            logger.info(SEND_PROBLEMS.get(result, "The mission is still loading. Try again in a moment."))

    def _dev_challenges(self, mode: str = ""):
        """Choose when Street Challenge checks are sent: /challenges pickup (default, when you pick up the soul) or /challenges clear."""
        ctx: "JSRFContext" = self.ctx
        if mode in ("pickup", "clear"):
            ctx.challenge_on_clear = mode == "clear"
            logger.info("Street Challenge checks now count on %s." % mode)
        else:
            logger.info("Street Challenge checks count on %s. Use /challenges clear or /challenges pickup."
                        % ("clear" if ctx.challenge_on_clear else "pickup"))


if DEV_COMMANDS:
    JSRFCommandProcessor.commands.update({name[5:]: method for name, method in vars(JSRFCommandProcessor).items()
                                          if name.startswith("_dev_")})


class JSRFContext(CommonContext):
    game = GAME_NAME
    items_handling = 0b111            # receive our own items and starting inventory as well
    command_processor = JSRFCommandProcessor

    def __init__(self, server_address: Optional[str], password: Optional[str]):
        super().__init__(server_address, password)
        self.game_reader = None
        self.sent_locations = set()
        self.last_error = ""
        self.challenge_on_clear = False       # user choice 2026-11-16: a challenge's check comes with its soul's pickup
                                              # (a clear sets only the soul's 'appear' bit; /challenges clear counts that)
        self.include_tags = False             # from slot data: tag spots are locations
        self.manage_roster = False            # from slot data: characters are items, so the client owns the roster
        self.char_found: Set[int] = set()     # character unlock locations the game ran (detected by a roster bit we did not set)
        self.roster_said = ""                 # last roster change reported
        self.roster_last: Optional[int] = None  # the roster as the client last left it (None: not looked at yet)
        self.start_chars = set(START_CHARACTERS)  # from slot data: the character(s) the seed starts with
        self.manage_tapes = False             # from slot data: Mystery Tape items open the Street Challenges
        self.tapes_told: Set[str] = set()     # areas whose closed challenges were already explained
        self.tape_pending: Dict[int, Tuple[int, float]] = {}   # defused tape sequence -> (tape number, when it was defused)
        self.rival_now = None                 # the rival gang fight running now (data.RivalBattle), for the log
        self.tape_hold: Set[str] = set()      # areas whose challenge marks are held for this visit (a pickup the client missed)
        self.tape_hidden_told: Set[str] = set()  # areas whose tape flag the client keeps off (said once in the log file)
        self.tape_scan_at = 0.0               # next look for a tape lying in the level
        self.spots_told: Set[tuple] = set()   # loaded tag spots without a location, already reported
        self.save_status: Optional[str] = None  # "ok" (tied to this seed), "old" / "foreign" (refused), None: not checked
        self.tower_prompt = True              # Corn asks in the Garage when Gouji's Tower is open (/tower prompt on|off)
        self.tower_asked = False              # already asked during this stay in the Garage
        self.tower_asks: Optional[int] = None # how often Corn has asked by himself in this seed (server data storage)
        self.tower_asks_read = False          # the Get for tower_asks has been sent
        self.corn_purpose: Optional[str] = None  # "tower" while Corn's visit is the Gouji's Tower question
        self.refills_done: Optional[int] = None  # refill items already applied (server data storage); None: not read yet
        self.refill_asked = False             # the Get for refills_done has been sent
        self.refill_waiting_told = False      # said once that refills wait for a playable moment
        self.requirements = location_requirements()
        self.start_area: Optional[str] = None
        self.held_notice: Set[str] = set()    # areas we already told the player about
        self.stage: Optional[int] = None      # last stage code the watcher looked at
        self.stage_told: Set[int] = set()     # unmapped stage codes already reported
        self.connected_at = time.monotonic()
        self.bounce_enabled = True            # send the player out of locked areas (needs write access to the game)
        self.bounce_told = False              # said once that a bounce could not be done
        self.bounce_until = 0.0               # no bounce before this monotonic time (cooldown / retry)
        self.locked_since: Optional[float] = None
        self.mission_addr: Optional[int] = None   # cached address of the running mission object
        self.souls_required: Optional[int] = None  # from slot data; None until connected
        self.tower_seen = False                    # the player stood in the open Tower
        self.goal_reached = False                  # ...and the stage then became the finale cutscene stage
        self.goal_sent = False
        self.tags_needed = 0                       # from slot data: sprayed tag spots Gouji's Tower needs (0 = none)
        self.challenges_needed = 0                 # from slot data: cleared Street Challenges Gouji's Tower needs (0 = none)
        self.goal = "defeat_gouji"                 # from slot data: "defeat_gouji" or "jet_ranks"
        self.jets_needed = 0                       # from slot data: Test Runs with a Jet rank the Jet Ranks goal needs
        self.counts_at = -GOAL_POLL                # when tower_counts last read the game
        self.watch_errors: Set[str] = set()        # watcher errors already logged
        self.overlay = Overlay(on_error=lambda msg: logger.info(msg), on_note=lambda msg: detail.info(msg))   # "Item received" notices over the game window
        self.notice_count: Optional[int] = None    # items already accounted for notices (None: next batch is the connect sync)
        self.between_told = None                   # (mission id, stage) last reported as "between levels"
        self.soul_counter_mode = "items"           # the game's soul counter: "items" received, "pickups", "game" (/soulcounter)
        self.menu_souls_told = False               # logged once: the pause menu's soul total follows the items
        self.restore_at = 0.0                      # next look for progress to put back (restore_progress)
        self.restore_told = False                  # a failed restore was reported
        self.own_done: Optional[Set[int]] = None   # restorable checks seen done in this seed's game (server data storage;
                                                   # None until read)
        self.own_asked = False                     # the read of own_done has been sent
        self.soul_counter_restore = False         # "game" chosen: put the game's own count back once
        self.soul_counter_told = self.soul_counter_ahead_told = self.soul_counter_cap_told = False
        self.chapter_auto = True                   # set the save's chapter number to 9 in the free-skate chapter (/chapter turns it off)
        self.chapter_told = False
        self.test_menu_seen = None                 # address of the Roboy menu last opened (to speak once per opening)
        self.counts_last: Dict[str, int] = {}      # last counts read: "tags", "challenges", "jets" (kept while no save is readable)
        self.requirements_told: Set[str] = set()   # Tower requirements already announced as met
        self.auto_garage = True                    # send the player to the free-skate Garage once Corn's text box is done
        self.auto_garage_done = False
        self.stage_settle = STAGE_SETTLE           # seconds of an unchanged stage code before any write
        self.stage_seen = object()                 # last stage code the watcher saw (a sentinel until the first look)
        self.stage_since = 0.0                     # monotonic time that code first appeared
        self.garage_start = GARAGE_START_INDEX     # start-point record used for the Garage (-1 = the game's own default)
        self.corn_text = True                      # rewrite Corn's New Game text box (explains the locked city)
        self.corn_bounce = True                    # a locked-area bounce goes through Corn's text box before the Garage
        self.corn_root: Optional[str] = None       # game folder (holds engine\\ and save\\); found from the engine's path
        self.corn_patch: Optional[jsrf_talk.TalkPatch] = None
        self.corn_told: Set[str] = set()           # problems already reported
        self.corn_phase: Optional[str] = None      # None, 'arrive' (waiting for Corn's mission) or 'talk' (waiting for its end)
        self.garage_corn = True                    # Corn waits in the free-skate Garage with the Tower question (/corn garage)
        self.garage_patch: Optional[jsrf_garage.GaragePatch] = None
        self.tape_missions: Optional[jsrf_garage.TapeMissions] = None   # area missions whose tapes the client re-numbers
        self.test_run_seen = False                 # a Test Run (hi 30-33) ran since the last free-skate Garage
        self.shut_garage = None                    # (mission id, since) of a story-chapter Garage the player stands in
        self.corn_since = 0.0
        self.corn_scan_at = 0.0
        self.mission_scan_at = 0.0

    def received_names(self) -> list:
        names = []
        for item in self.items_received:
            try:
                names.append(self._item_name(item.item))
            except Exception:
                pass
        return names

    def note_stage(self, code: Optional[int], now: float):
        """Remember when the stage code last changed (None, e.g. while a load is under way, counts as a change)."""
        if code != self.stage_seen:
            self.stage_seen = code
            self.stage_since = now

    def settle_left(self, now: float) -> float:
        """Seconds until the stage code has been stable long enough for the client to write to the game."""
        return max(0.0, self.stage_since + self.stage_settle - now)

    def still_loading(self) -> bool:
        """For the commands: tell the player to wait when the level has only just changed. True when they must wait."""
        left = self.settle_left(time.monotonic())
        if left > 0:
            logger.info("The level is still loading. Try again in %d s." % (int(left) + 1))
            return True
        return False

    def tower_missing(self) -> list:
        """What Gouji's Tower still needs, as readable phrases (empty when it is open)."""
        names = self.received_names()
        missing = []
        if TOWER_UNLOCK not in names:
            missing.append("the %s item" % TOWER_UNLOCK)
        need = self.souls_required or 0
        have = names.count(SOUL_ITEM)
        if have < need:
            missing.append("%d more %s item(s) (%d of %d)" % (need - have, SOUL_ITEM, have, need))
        counts = self.tower_counts() if (self.tags_needed or self.challenges_needed) else {}
        for key, need, what in (("tags", self.tags_needed, "sprayed tag spot(s)"),
                                ("challenges", self.challenges_needed, "cleared Street Challenge(s)")):
            if need:
                have = counts.get(key)
                if have is None:
                    missing.append("%d %s (load your save so the client can count them)" % (need, what))
                elif have < need:
                    missing.append("%d more %s (%d of %d)" % (need - have, what, have, need))
        return missing

    def lock_text(self, area: str) -> str:
        """Why `area` is locked, for the log."""
        if area == TOWER:
            return "%s is locked. You still need %s." % (TOWER, ", ".join(self.tower_missing()))
        return "%s is locked. Checks you collect there stay held until the %s item arrives." % (area, unlock_name(area))

    def locked_stage_area(self, code: Optional[int]) -> Optional[str]:
        """The locked area this stage code is in, or None (Garage, unmapped stage, unlocked area, or items still arriving)."""
        if code in TOWER_STAGES:
            if time.monotonic() - self.connected_at < ITEM_SETTLE_SECONDS:
                return None
            return TOWER if self.tower_missing() else None
        if code is None or code == GARAGE_STAGE or code in OTHER_STAGES:
            return None
        area = area_of_stage(code)
        if area is None or area in self.unlocked_areas():
            return None
        if time.monotonic() - self.connected_at < ITEM_SETTLE_SECONDS:
            return None
        return area

    def bounce_due(self, code: Optional[int], now: float) -> Optional[str]:
        """The locked area to send the player out of right now, or None."""
        area = self.locked_stage_area(code) if self.bounce_enabled else None
        if area is None:
            self.locked_since = None
            return None
        if self.locked_since is None:
            self.locked_since = now
        if now < self.bounce_until or now - self.locked_since < BOUNCE_DELAY or self.settle_left(now) > 0:
            return None
        return area

    def start_for(self, hi: int, lo: int) -> int:
        """The start-point record to spawn at in mission (hi, lo): the Garage's chosen spot, else record 0."""
        return self.garage_start if lo == jsrf_game.GARAGE_LO else DEFAULT_START_INDEX

    def try_send(self, hi: int, lo: int, skip_hi: Optional[int] = None) -> str:
        """Start mission (hi, lo). Returns 'sent', 'wait' (the mission is still loading), 'nowrite',
        'nomission' (not found, or more than one candidate), 'failed', or 'already' (the running mission's hi is
        skip_hi, so nothing was written)."""
        if not getattr(self.game_reader, "can_write", False):
            return "nowrite"
        state = self.state()
        mission = state.running_mission(self.mission_addr)
        if mission is None:
            return "nomission"
        self.mission_addr = mission["addr"]
        if mission["id"] >> 16 == 0:
            return "title"                             # hi 0 = the title screen's attract demo (mssn0090, in the Shibuya stage)
        if mission["state"] != jsrf_game.STATE_RUNNING:
            return "wait"
        # Between levels the game already reports the next level while the old mission still runs (a talk, a cutscene,
        # the end of the tutorial). Moving the player then froze the game twice (2026-11-17 18:42-18:43: a bounce "out of
        # Dogenzaka" while the tutorial mission, a Garage mission, was still running). Only write when the running
        # mission's own level is the level the game reports.
        own = state.mission_stage(mission["addr"])
        now_stage = state.current_stage()
        if own in KNOWN_STAGES and now_stage is not None and own != now_stage:
            if self.between_told != (mission["id"], now_stage):
                self.between_told = (mission["id"], now_stage)
                logger.info("Waiting: the game is between levels (mission %d:%d is in stage 0x%X, the game reports 0x%X)."
                            % (mission["id"] >> 16, mission["id"] & 0xFFFF, own, now_stage))
            return "wait"
        if skip_hi is not None and mission["hi"] == skip_hi:
            return "already"
        if CONFIRM_DELAY > 0:                          # still the same mission, still running a moment later?
            time.sleep(CONFIRM_DELAY)
            again = state._mission_at(mission["addr"])
            if again is None or again["id"] != mission["id"] or again["state"] != jsrf_game.STATE_RUNNING:
                return "wait"
        self.ensure_playable(state)
        sent = state.send_to_mission(mission, hi, lo, self.start_for(hi, lo))
        note = state.start_note
        if note:
            if note["written"]:
                detail.info("Spawn point: was %s, set to %s%s." % (note["before"], note["wanted"],
                                                                   " (put back %d times)" % note["fixed"] if note["fixed"] else ""))
            else:
                detail.info("Spawn point could not be set (reads %s), so the game picks it."
                            % note["before"])
        pick = getattr(state, "select_note", None)
        if pick:
            if pick["written"]:
                detail.info("After the character select: was lo %s, set to %s." % (pick["before"], pick["wanted"]))
            else:
                detail.info("After the character select: could not be set (reads %s); the game goes to lo %s."
                            % (pick["before"], pick["before"]))
        if sent and self.corn_phase is not None and (hi, lo) != CORN_MISSION:
            self.corn_finish()                         # something else was started: the Corn flow is over
        return "sent" if sent else "failed"

    def garage_return_due(self, code: Optional[int], now: float) -> bool:
        """True when the player stands in a story-chapter Garage (hi 1-8, doors shut) that the game put them in: after
        Test Runs, leaving Roboy's menu loads the chapter-1 Garage (engine log 2026-11-19: mssn3212 -> mssn0100 ->
        mssn01195), where no area can be entered (user, 18:53). Not during Corn's mission or a New Game (Corn's flow
        handles those), not while Roboy's menu is open, and only once that Garage has run for a moment."""
        if self.game_reader is None or not getattr(self.game_reader, "can_write", False):
            return False
        state = self.state()
        mission = state._mission_at(self.mission_addr) if self.mission_addr else None
        if mission is None and now >= self.mission_scan_at:
            self.mission_scan_at = now + MISSION_SCAN_EVERY
            mission = state.running_mission(None)
        if mission is None:
            return False
        self.mission_addr = mission["addr"]
        hi = mission["hi"]
        if hi in TEST_RUN_HIS:
            self.test_run_seen = True
        if hi == jsrf_game.FREE_SKATE_CHAPTER:
            self.test_run_seen = False
        if (code != GARAGE_STAGE or not 1 <= hi <= 8 or mission["id"] == CORN_MISSION_ID or self.corn_phase is not None
                or mission["state"] != jsrf_game.STATE_RUNNING or not (self.test_run_seen or self.auto_garage_done)
                or state.test_menu() is not None):
            self.shut_garage = None
            return False
        if self.shut_garage is None or self.shut_garage[0] != mission["id"]:
            self.shut_garage = (mission["id"], now)
            return False
        # The wait on a running mission in the Garage stage is the settle time here: the general STAGE_SETTLE (counted
        # from the load request) would stretch the 2 s the user asked for.
        return now - self.shut_garage[1] >= SHUT_GARAGE_WAIT and now >= self.bounce_until

    def try_bounce(self) -> str:
        """Start the free-skate Garage (same results as try_send)."""
        return self.try_send(jsrf_game.FREE_SKATE_CHAPTER, jsrf_game.GARAGE_LO)

    # ---- Corn's text box (talk.py) ----

    def corn_report(self, problem: str):
        """Say once that Corn's text could not be changed. Nothing else depends on it."""
        if problem and problem not in self.corn_told:
            self.corn_told.add(problem)
            logger.info("Corn's text box could not be changed (%s). Everything else still works." % problem)

    def game_folder(self) -> Optional[str]:
        """The game folder (the one that holds engine and save): /corn folder, else from the running game."""
        reader = self.game_reader
        return (self.corn_root or getattr(reader, "game_dir", None)
                or jsrf_talk.game_root(getattr(reader, "exe_path", None)))

    def corn_files(self) -> Optional[jsrf_talk.TalkPatch]:
        """The talk-file helper for the game folder, or None (reported once) when it cannot be used."""
        root = self.game_folder()
        if not root:
            self.corn_report("the game folder is unknown")
            return None
        if self.corn_patch is None or self.corn_patch.root != root:
            self.corn_patch = jsrf_talk.TalkPatch(root)
            if self.corn_patch.ok:
                detail.info("Corn's text file: %s" % self.corn_patch.cache)
        if not self.corn_patch.ok:
            self.corn_report(self.corn_patch.error)
            return None
        return self.corn_patch

    def corn_show_idle(self) -> bool:
        """Corn's resting text: the New Game explanation, or his own words when /corn off."""
        patch = self.corn_files()
        if patch is None:
            return False
        ok = patch.write(jsrf_talk.intro_pages(self.start_area)) if self.corn_text else patch.restore()
        if not ok:
            self.corn_report(patch.error)
        return ok

    def corn_restore(self):
        """Put Corn's own text back (when the client closes, or /corn off)."""
        if self.corn_patch is not None and self.corn_patch.ok:
            self.corn_patch.restore()

    def corn_finish(self):
        """The Corn flow is over (finished, replaced by another mission, or given up): back to the resting text."""
        self.corn_phase = None
        self.corn_purpose = None
        self.corn_show_idle()

    def try_corn(self, area: str) -> str:
        """Send the player to Corn (mission 1:1) with a text about `area`. Same results as try_send, plus 'plain' when
        the text could not be set (the caller then bounces to the Garage directly)."""
        patch = self.corn_files()
        if patch is None:
            return "plain"
        if not patch.write(jsrf_talk.bounce_pages(area, area == TOWER)):
            self.corn_report(patch.error)
            return "plain"
        result = self.try_send(*CORN_MISSION)
        if result == "sent":
            self.corn_phase, self.corn_since, self.corn_scan_at = "arrive", time.monotonic(), 0.0
        elif result != "wait":
            self.corn_show_idle()
        return result

    def tower_ask_due(self, code: Optional[int], now: float) -> bool:
        """True when Corn should ask about Gouji's Tower: the player is in the free-skate Garage, the Tower is open, and
        Corn has not asked yet during this stay in the Garage (leaving the Garage resets that)."""
        if code != GARAGE_STAGE:
            self.tower_asked = False
            return False
        # Corn asks by himself once per seed while he waits in the Garage (talking to him asks again); without him there he
        # asks on every Garage visit, the only way to the Tower then. Never with the Jet Ranks goal (user, 18:42).
        once = self.garage_active()
        if (not self.tower_prompt or not self.corn_text or not self.corn_bounce or self.tower_asked
                or (once and self.tower_asks != 0) or self.goal == "jet_ranks"
                or self.corn_phase is not None or self.goal_reached or (self.auto_garage and not self.auto_garage_done)
                or not getattr(self.game_reader, "can_write", False) or now < self.bounce_until or self.settle_left(now) > 0
                or now - self.connected_at < ITEM_SETTLE_SECONDS or self.tower_missing()):
            return False
        mission = self.state().running_mission(self.mission_addr)
        return (mission is not None and mission["hi"] == jsrf_game.FREE_SKATE_CHAPTER
                and mission["state"] == jsrf_game.STATE_RUNNING)

    def try_tower_ask(self) -> str:
        """Send the player to Corn (mission 1:1) with the Yes / No question about Gouji's Tower. Same results as
        try_send, plus 'plain' when the question could not be written (then nobody asks again during this stay)."""
        patch = self.corn_files()
        if patch is None or not patch.write_question(*jsrf_talk.tower_question("first" if self.garage_active() else "plain")):
            if patch is not None:
                self.corn_report(patch.error)
            self.tower_asked = True
            self.corn_show_idle()
            return "plain"
        result = self.try_send(*CORN_MISSION)
        if result == "sent":
            self.tower_asked = True
            self.corn_purpose = "tower"
            self.corn_phase, self.corn_since, self.corn_scan_at = "arrive", time.monotonic(), 0.0
            logger.info("Gouji's Tower is open. Corn has something to ask you.")
        elif result != "wait":
            self.tower_asked = True
            self.corn_show_idle()
        return result

    def finish_tower_ask(self) -> str:
        """Corn's question is over: Yes -> Gouji's Tower, anything else -> the free-skate Garage. Same results as try_send."""
        state = self.state()
        answer = state.talk_answer(self.mission_addr)
        self.corn_purpose = None
        if answer == 1 and not self.tower_missing():
            state.set_mission_flags({n: False for n in CORN_CHAIN_STOP})     # no walk towards Gum's talk meanwhile
            result = self.try_send(*TOWER_MISSION)
            if result == "sent":
                logger.info("You said yes. Sending you to %s. Good luck!" % TOWER)
                return result
        elif self.garage_active():
            logger.info("You said no%s. Talk to Corn in the Garage when you are ready for %s."
                        % ("" if answer == 0 else " (answer %s)" % answer, TOWER))
        else:
            logger.info("You said no%s. Corn asks again the next time you come to the Garage while %s is open."
                        % ("" if answer == 0 else " (answer %s)" % answer, TOWER))
        return self.try_auto_garage()

    # ---- Corn in the free-skate Garage (garage.py) ----

    def garage_active(self) -> bool:
        """True while the client's Garage files (Corn standing there, his two talks) are in the cache folder."""
        return bool(self.garage_corn and self.garage_patch is not None and self.garage_patch.applied)

    def garage_report(self, problem: str):
        """Say once that Corn could not be put into the Garage. He then asks about the Tower on every Garage visit."""
        key = "garage: " + (problem or "unknown")
        if key not in self.corn_told:
            self.corn_told.add(key)
            logger.info("Corn could not be put into the free-skate Garage (%s). Once %s is open he asks you about it each "
                        "time you come to the Garage instead." % (problem or "unknown problem", TOWER))

    def tower_missing_lines(self) -> List[str]:
        """What Gouji's Tower still needs, one short line each (for Corn's talk in the Garage)."""
        names = self.received_names()
        lines = []
        if TOWER_UNLOCK not in names:
            lines.append("Item: %s" % TOWER_UNLOCK)
        need = self.souls_required or 0
        have = names.count(SOUL_ITEM)
        if have < need:
            lines.append("%ss: %d of %d" % (SOUL_ITEM, have, need))
        counts = self.tower_counts() if (self.tags_needed or self.challenges_needed) else {}
        for key, need, what in (("tags", self.tags_needed, "Tag spots"), ("challenges", self.challenges_needed,
                                                                           "Street Challenges")):
            if need:
                have = counts.get(key)
                if have is None:
                    lines.append("%s: %d needed" % (what, need))
                elif have < need:
                    lines.append("%s: %d of %d" % (what, have, need))
        return lines

    def garage_status_pages(self) -> List[jsrf_talk.Page]:
        """What Corn says in the Garage when he does not ask about the Tower: what the Tower still needs, or with the Jet
        Ranks goal how the Jet ranks stand (user, 2026-11-19 18:42)."""
        if self.goal == "jet_ranks":
            return jsrf_talk.jet_status_pages(self.tower_counts().get("jets"), self.jets_needed, self.test_run_areas_ready())
        return jsrf_talk.tower_status_pages(self.tower_missing_lines())

    def test_run_areas_ready(self) -> Optional[int]:
        """Unlocked areas whose Graffiti Souls are all collected, Street Challenge souls included (Roboy's rule), or None
        when the game cannot be read."""
        if self.game_reader is None:
            return None
        souls = self.state().collected_souls()
        if souls is None:
            return None
        open_areas = self.unlocked_areas()
        return sum(1 for a in AREAS if a in open_areas and area_soul_ids(a) <= souls)

    def garage_setup(self) -> bool:
        """Write Corn's Garage files into the cache folder. The game reads them the next time the Garage loads."""
        if not self.garage_corn:
            return False
        root = self.game_folder()
        if not root:
            self.garage_report("the game folder is unknown")
            return False
        if self.garage_patch is None or self.garage_patch.root != root:
            self.garage_restore()
            self.garage_patch = jsrf_garage.GaragePatch(root)
        patch = self.garage_patch
        if not patch.ok or not patch.apply(jsrf_talk.tower_question("garage"), self.garage_status_pages()):
            self.garage_report(patch.error)
            return False
        detail.info("Corn waits in the free-skate Garage from its next load (%s)." % patch.mission_cache)
        return True

    def tapes_setup(self) -> int:
        """With Mystery Tape items: write the client's copies of the free-skate area missions, whose tapes carry 0x200 + N
        (see sync_tapes). The game reads them the next time an area loads. Returns how many were written."""
        if not self.manage_tapes:
            return 0
        root = self.game_folder()
        if not root:
            return 0
        if self.tape_missions is None or self.tape_missions.root != root:
            self.tapes_restore()
            self.tape_missions = jsrf_garage.TapeMissions(root)
        done = self.tape_missions.apply() if self.tape_missions.ok else 0
        if done:
            detail.info("Mystery Tapes: %d area missions copied with re-numbered tapes." % done)
        elif "tapes" not in self.corn_told:
            self.corn_told.add("tapes")
            logger.info("The area missions could not be prepared for Mystery Tapes (%s): a tape whose item you already have "
                        "stays hidden in its level." % (self.tape_missions.error or "none found"))
        return done

    def tapes_restore(self):
        """Put the game's own area missions back (when the client closes)."""
        if self.tape_missions is not None and self.tape_missions.applied:
            self.tape_missions.restore()

    def garage_restore(self):
        """Put the game's own Garage files back (when the client closes, or /corn garage off)."""
        if self.garage_patch is not None and self.garage_patch.applied:
            self.garage_patch.restore()

    def garage_poll(self, code: Optional[int], now: float) -> Optional[str]:
        """Once per poll: keep Corn's "still shut" talk up to date, tell the Garage whether the Tower is open (Mission flag
        143 picks his question or his list), and act on his question (flag 144: the talk is over). Returns try_send's
        result when the player said yes, else None."""
        if not self.garage_active():
            return None
        patch = self.garage_patch
        if self.settle_left(now) > 0:
            return None
        if not patch.write_status(self.garage_status_pages()):
            self.garage_report(patch.error)
        if code != GARAGE_STAGE or not getattr(self.game_reader, "can_write", False):
            return None
        state = self.state()
        mission = state.running_mission(self.mission_addr)
        if not is_garage_hub(mission) or mission["state"] != jsrf_game.STATE_RUNNING:
            return None
        self.mission_addr = mission["addr"]
        is_open = (self.goal != "jet_ranks" and now - self.connected_at >= ITEM_SETTLE_SECONDS
                   and not self.tower_missing())           # the Jet Ranks goal: always his Jet talk, never the Tower
        if state.mission_flag(jsrf_garage.F_TOWER_OPEN) not in (None, is_open):
            state.set_mission_flags({jsrf_garage.F_TOWER_OPEN: is_open})
        if not state.mission_flag(jsrf_garage.F_ASKED):
            return None
        answer = state.talk_answer(mission["addr"])
        if answer == 1 and is_open:
            result = self.try_send(*TOWER_MISSION)
            if result == "wait":
                return None                            # the answer stays: try again next poll
            state.set_mission_flags({jsrf_garage.F_ASKED: False})
            if result == "sent":
                logger.info("You said yes. Sending you to %s. Good luck!" % TOWER)
            else:
                logger.info(SEND_PROBLEMS.get(result, "Could not send you to %s. Talk to Corn again." % TOWER))
            return result
        state.set_mission_flags({jsrf_garage.F_ASKED: False})
        if answer == 1:
            logger.info(self.lock_text(TOWER))
        else:
            logger.info("You said no%s. Talk to Corn again when you are ready for %s."
                        % ("" if answer == 0 else " (answer %s)" % answer, TOWER))
        return None

    def corn_gave_up(self):
        """Corn's mission never showed up: the Garage is the way out from now on."""
        logger.info("Corn's mission did not start. Sending you to the free-skate Garage. Locked areas will send you "
                    "straight there from now on.")
        self.corn_bounce = False
        self.corn_finish()

    def bounce_for(self, area: str) -> str:
        """Send the player out of a locked area: through Corn's text box when that is on, else straight to the Garage."""
        if self.corn_phase == "arrive":                # still in a locked area although Corn's mission was started
            self.corn_gave_up()
        if self.corn_bounce and self.corn_phase is None and getattr(self.game_reader, "can_write", False):
            result = self.try_corn(area)
            if result != "plain":
                return result
        return self.try_bounce()

    def corn_poll(self, code: Optional[int], now: float) -> Optional[str]:
        """Follow the Corn flow once per poll. Returns 'fallback' when it ran out of time and the player should be sent
        to the Garage directly."""
        phase = self.corn_phase
        if phase is None:
            return None
        elapsed = now - self.corn_since
        if phase == "arrive":
            state = self.state()
            mission = state._mission_at(self.mission_addr) if self.mission_addr else None
            if (mission is None or mission["id"] != CORN_MISSION_ID) and now >= self.corn_scan_at:
                self.corn_scan_at = now + CORN_SCAN_EVERY
                mission = state.running_mission(None)
            if (mission is not None and mission["id"] == CORN_MISSION_ID and mission["state"] != jsrf_game.STATE_START_NEXT
                    and code == GARAGE_STAGE and self.settle_left(now) <= 0):
                # The Mission bank is reset when 1:1 starts, so whatever is set now is this visit's own progress. While
                # the box is up the mission may not read as running, so this can first be seen after the talk has ended.
                flags = {n: state.mission_flag(n) for n in CORN_FLAGS_RESET}
                if any(v is None for v in flags.values()):
                    return None
                seen = "".join("1" if flags[n] else "0" for n in range(CORN_FLAG_SETUP, CORN_DONE_FLAG + 1))
                if flags[CORN_FLAG_TALK] or flags[CORN_FLAG_TALKING]:
                    if flags[CORN_DONE_FLAG]:
                        state.set_mission_flags({CORN_DONE_FLAG: False})     # 103 next to a talk that has not ended is left over
                    logger.info("Corn is talking.")
                elif flags[CORN_DONE_FLAG] or any(flags[n] for n in CORN_CHAIN):
                    logger.info("Corn has had his say (flags %d-%d: %s)." % (CORN_FLAG_SETUP, CORN_DONE_FLAG, seen))
                elif mission["state"] == jsrf_game.STATE_RUNNING:
                    # nothing of the talk has happened and the mission is running: its own setup did not run (it needs
                    # Chapter flag 1), so raise what the setup raises
                    state.set_mission_flags({CORN_FLAG_SETUP: True, CORN_FLAG_TALK: True})
                    logger.info("Corn is talking (his talk did not start by itself, so the client started it; flags %d-%d were %s)."
                                % (CORN_FLAG_SETUP, CORN_DONE_FLAG, seen))
                else:
                    return None                        # the mission is not running yet: look again next time
                self.mission_addr = mission["addr"]
                self.corn_phase, self.corn_since = "talk", now
                return None
            if elapsed > CORN_ARRIVE_TIMEOUT:
                self.corn_gave_up()
                return "fallback"
        elif elapsed > CORN_TALK_TIMEOUT:
            logger.info("Corn's text box did not finish. Sending you to the free-skate Garage.")
            self.corn_finish()
            return "fallback"
        return None

    def auto_garage_due(self, code: Optional[int], now: float) -> bool:
        """True when the player stands in the (story) Garage and Corn's New Game text box has ended."""
        if self.corn_phase == "arrive":                # Corn's mission is not up yet: flag 103 may be left over from an old run
            return False
        if code != GARAGE_STAGE or not (self.corn_phase == "talk" or (self.auto_garage and not self.auto_garage_done)):
            return False
        # the cooldown after a bounce does not hold up the way out of Corn's talk: the settle time already covers the load,
        # and a player who clicks through quickly would otherwise get Gum's talk (TE002) before the cooldown ran out
        if (now < self.bounce_until and self.corn_phase != "talk") or self.settle_left(now) > 0:
            return False
        return self.state().mission_flag(CORN_DONE_FLAG) is True

    def try_auto_garage(self) -> str:
        """The free-skate Garage, unless the player is already in that chapter. When the player is in Corn's mission, the
        script's walk towards Gum's talk is stopped first, so that talk does not start while the Garage loads."""
        state = self.state()
        mission = state.running_mission(self.mission_addr)
        if mission is not None and mission["id"] == CORN_MISSION_ID:
            state.set_mission_flags({n: False for n in CORN_CHAIN_STOP})
        return self.try_send(jsrf_game.FREE_SKATE_CHAPTER, jsrf_game.GARAGE_LO, skip_hi=jsrf_game.FREE_SKATE_CHAPTER)

    def after_auto_garage(self, result: str, now: float, message: str = "Corn is done talking. Sending you to the free-skate Garage."):
        if result == "sent":
            self.auto_garage_done = True
            self.bounce_until = now + BOUNCE_COOLDOWN
            if message:
                logger.info(message)
        elif result == "already":
            self.auto_garage_done = True
        elif result != "wait":
            self.bounce_until = now + BOUNCE_RETRY
            if result == "nowrite":
                self.auto_garage = False
            if not self.bounce_told:
                self.bounce_told = True
                logger.info(BOUNCE_PROBLEMS.get(result, "Could not send you to the Garage."))

    def after_bounce(self, area: str, result: str, now: float):
        """Report what try_bounce did and set the cooldown."""
        if result == "title":                          # the title demo plays in the Shibuya stage: not a real visit
            self.bounce_until = now + BOUNCE_RETRY
            return
        if result == "sent":
            where = "Corn, then back to the Garage" if self.corn_phase == "arrive" else "back to the Garage"
            if area == TOWER:
                logger.info("%s is locked. You still need %s. Sending you %s." % (TOWER, ", ".join(self.tower_missing()), where))
            else:
                logger.info("%s is locked. Sending you %s until the %s item arrives." % (area, where, unlock_name(area)))
            self.bounce_until = now + BOUNCE_COOLDOWN
            self.locked_since = None
        elif result != "wait":
            self.bounce_until = now + BOUNCE_RETRY
            if result == "nowrite":
                self.bounce_enabled = False
            if not self.bounce_told:
                self.bounce_told = True
                logger.info(BOUNCE_PROBLEMS.get(result, "Could not send you back to the Garage."))

    def save_marker_value(self) -> Optional[int]:
        """This seed and slot's 32-bit save marker (never 0), or None before the room info is known."""
        # Archipelago 0.6.8 keeps the room's seed in server_seed_name; seed_name is only filled from a patch file, so it
        # stays None for this client (reading it alone kept every save waiting: nothing ran, 2026-11-17 18:38).
        seed = getattr(self, "server_seed_name", None) or getattr(self, "seed_name", None)
        if not seed or self.slot is None:
            return None
        return zlib.crc32(("%s|%s|%s" % (seed, getattr(self, "team", None), self.slot)).encode()) or 1

    def save_ok(self, found: Set[int]) -> bool:
        """Fresh-save handling: True when the loaded save may be used with this seed (checks sent, game changed).
        A save carrying this seed's marker is fine. A save with no marker is tied to the seed (marker written) when it has
        nothing done yet (a New Game) or only checks the server already has (this seed's save from before the marker);
        otherwise, and for another seed's marker, the client refuses it until a New Game or /usesave."""
        mine = self.save_marker_value()
        marker = None if mine is None else self.state().save_marker()
        if marker is None:
            if self.save_status != "waiting":
                self.save_status = "waiting"
                logger.info("Waiting for %s before using the loaded save." % (
                    "the server's room information" if mine is None else "the save's data to be readable"))
            return False                                       # seed or save not known yet: wait
        if marker == mine:
            status = "ok"
        elif marker == 0:
            checked = set(getattr(self, "checked_locations", set()) or set())
            seed_locs = set(self.missing_locations) | checked
            new = ((found | self.char_found) & seed_locs) - checked
            if new:
                status = "old"
            else:
                status = "ok"
                tied = self.state().write_save_marker(mine)
                if tied:
                    self.on_new_save()
                if self.save_status != "ok":
                    (detail if tied else logger).info(("This save is now tied to this seed." if not found else
                                 "This save's progress matches this seed; it is now tied to this seed.")
                                if tied else "Could not mark this save for this seed (no write access).")
        else:
            status = "foreign"
        if status != self.save_status:
            self.save_status = status
            if status == "old":
                logger.info("This save already has checks done that this seed has not seen (progress from before this seed, "
                            "or a save from another seed). The client sends nothing and leaves this save alone. Start a "
                            "New Game for this seed; or, if this really is this seed's save (e.g. played with the client "
                            "closed), type /usesave.")
            elif status == "foreign":
                logger.info("This save belongs to another seed. The client sends nothing and leaves this save alone. Start "
                            "a New Game for this seed, or type /usesave to use this save anyway.")
        return status == "ok"

    def own_key(self) -> str:
        """Server data storage key: the restorable checks this seed's game has shown done (a list of location ids).
        restore_progress puts back only these: the server's checked locations also hold the ones another world's
        !collect or a !release marked (user, 2026-11-21 17:26: OOT's goal collected its items from JSRF, the client then
        "put back" 21 Street Challenges it had never seen cleared, and Gouji's Tower opened)."""
        return "jsrf_done_%s_%s" % (getattr(self, "team", None), self.slot)

    def note_own_progress(self, found: Set[int]) -> Set[int]:
        """The restorable checks this seed's save shows done that own_done does not have yet; they are added to own_done
        and the caller stores them on the server. Nothing while own_done is unread or the loaded save is not this
        seed's (save_status ok). The game only shows a check done when the player did it or restore_progress put it
        back from own_done, so the list stays the player's own."""
        if self.own_done is None or self.save_status != "ok" or self.on_title_screen():
            return set()
        new = (set(found) & jsrf_game.RESTORABLE) - self.own_done
        self.own_done |= new
        return new

    def restore_progress(self, found: Set[int], now: float) -> int:
        """Put back what the player did in this seed's game but the loaded save lacks (user, 2026-11-21: a game over or a
        lost rival fight sends the player to the main menu, and the save, or a New Game, no longer has the progress since
        the last save). The record is own_done (what the game showed done, kept on the server) within the server's
        checked locations; a check only !collect or !release marked is never put back (user, 17:26). Souls, Street
        Challenges (cleared mark + soul), rival wins, Jet ranks and tags (user, 09:34; the loaded area's once the player
        has left it) are written back; Mystery Tapes come back through sync_tapes. Looks every RESTORE_EVERY
        seconds, only with this seed's save in the free-skate chapter (chapter 9) and outside Corn's talks. Returns the
        number of checks put back."""
        if now < self.restore_at:
            return 0
        self.restore_at = now + RESTORE_EVERY
        if not getattr(self.game_reader, "can_write", False) or self.save_status != "ok" or self.corn_phase:
            return 0
        if now - self.connected_at < ITEM_SETTLE_SECONDS or self.own_done is None:
            return 0
        checked = set(getattr(self, "checked_locations", set()) or set())
        missing = (checked & jsrf_game.RESTORABLE & self.own_done) - found
        if not missing:
            return 0
        state = self.state()
        if state.chapter_number() != 9:                     # New Game: wait for the free-skate Garage
            return 0
        plan = jsrf_game.restore_plan(missing)
        tags = plan.pop("tags")
        if any(plan.values()) and not state.restore_progress(plan):
            if not self.restore_told:
                self.restore_told = True
                logger.info("Could not put back this save's missing progress (the game did not take the change).")
            return 0
        tags_done: Set[tuple] = set()
        if tags:
            # Tags of the area the player is in come back once they have left it (see JSRFGame.restore_tags).
            code = state.current_stage()
            tags_done = state.restore_tags(tags, area_of_stage(code) if code is not None else None)
        souls = len(plan["souls"]) - len(plan["marks"])
        parts = [(souls, "Graffiti Soul"), (len(plan["marks"]), "Street Challenge"), (len(plan["rivals"]), "rival gang win"),
                 (len(plan["jets"]), "Jet rank"), (len(tags_done), "tag")]
        said = ", ".join("%d %s%s" % (n, what, "" if n == 1 else "s") for n, what in parts if n)
        if said:
            logger.info("Put back progress this save was missing (you had done it in this seed's game): %s." % said)
        return sum(n for n, _ in parts)

    def on_new_save(self):
        """A save was just tied to this seed: a New Game (it zeroes the flag record that holds the marker) or this seed's
        save from before the marker. What the client did for the previous save no longer applies, so the New Game steps
        are armed again (user, 2026-11-21: after a lost rival fight sent him to the main menu and he started a New Game,
        Corn's talk no longer led to the free-skate Garage, as that ran once per game start)."""
        self.auto_garage_done = False
        self.corn_phase = None
        self.roster_last = None
        self.test_run_seen, self.shut_garage = False, None
        self.restore_told, self.restore_at = False, 0.0
        detail.info("A new save for this seed: Corn's New Game talk will lead to the free-skate Garage again.")

    def tower_ask_key(self) -> str:
        """Server data storage key: how often Corn has asked about Gouji's Tower by himself (he does that once per seed;
        user, 2026-11-19 16:04: after the first time it should not interrupt the player)."""
        return "jsrf_tower_asks_%s_%s" % (getattr(self, "team", None), self.slot)

    def refill_key(self) -> str:
        """Server data storage key holding how many refill items this slot has already applied (survives restarts)."""
        return "jsrf_refills_%s_%s" % (getattr(self, "team", None), self.slot)

    def refill_names(self) -> List[str]:
        out = []
        for item in self.items_received:
            try:
                name = self._item_name(item.item)
            except Exception:
                continue
            if name in (SPRAY_REFILL, HEALTH_REFILL):
                out.append(name)
        return out

    def apply_refills(self) -> Optional[int]:
        """Apply refill items received since the last applied one: fill spray cans and/or health to the max on the live
        player. Several waiting refills collapse into one fill. Returns the new applied count (to store on the server), or
        None when nothing was done (nothing new, count not read yet, no player right now, title screen, no write access)."""
        if self.refills_done is None or self.game_reader is None or not getattr(self.game_reader, "can_write", False):
            return None
        names = self.refill_names()
        pending = names[self.refills_done:]
        if not pending or self.on_title_screen():
            return None
        cans, health = SPRAY_REFILL in pending, HEALTH_REFILL in pending
        p = self.state().refill(cans, health)
        if p is None:
            if not self.refill_waiting_told:
                self.refill_waiting_told = True
                detail.info("Refill items wait until you are skating (not in menus or loading).")
            return None
        self.refill_waiting_told = False
        done = []
        if cans:
            done.append("spray cans %d -> %d" % (p["cans"], p["cans_max"]))
        if health:
            done.append("health %d -> %d" % (p["health"], p["health_max"]))
        detail.info("Refilled %s." % " and ".join(done))
        self.refills_done = len(names)
        return self.refills_done

    def on_title_screen(self) -> bool:
        """True when the last mission the client looked at is the title screen's demo (hi 0)."""
        if not self.mission_addr or self.game_reader is None:
            return False
        mission = self.state()._mission_at(self.mission_addr)
        return mission is not None and mission["id"] >> 16 == 0

    def check_stage(self, code: Optional[int]):
        """Tell the player once per visit when they are standing in a locked area (honor system: the game's
        own Garage doors and the F6 map list are not blocked), and report stage codes we cannot name yet."""
        if code is None or code == self.stage:
            return
        if code == GARAGE_STAGE or code in OTHER_STAGES:
            self.stage = code
            return
        if code in TOWER_STAGES:
            if time.monotonic() - self.connected_at < ITEM_SETTLE_SECONDS:
                return                                   # items may still be arriving; look again next poll
            if self.tower_missing():
                auto = self.bounce_enabled and getattr(self.game_reader, "can_write", False)
                logger.info(self.lock_text(TOWER) + ("" if auto else " Please go back to the Garage."))
            elif code == TOWER_STAGE:
                logger.info("You are in %s." % TOWER)
            self.stage = code
            return
        area = area_of_stage(code)
        if area is None:
            self.stage = code
            if code not in self.stage_told:
                self.stage_told.add(code)
                logger.info("Stage 0x%08X (Stg%d%d) is not mapped to an area yet. Tell the developer which area this is."
                            % (code, code >> 16, code & 0xFFFF))
            return
        if area not in self.unlocked_areas():
            if time.monotonic() - self.connected_at < ITEM_SETTLE_SECONDS:
                return                                   # items may still be arriving; look again next poll
            auto = self.bounce_enabled and getattr(self.game_reader, "can_write", False)
            # with the bounce on, its own message says it (and the title screen's Shibuya demo, which is no visit,
            # is only recognised when the bounce looks at the mission)
            if not auto and not self.on_title_screen():
                logger.info(self.lock_text(area) + " Please go back to the Garage.")
        self.stage = code

    def track_goal(self, code: Optional[int]) -> bool:
        """Follow the finale by stage code: the Tower, then the finale cutscene stage = the final boss is beaten. As a
        backup, the credits mission (8:899) counts too. True once, when the goal should be sent."""
        if self.goal_sent:
            return False
        if self.goal == "jet_ranks":
            if code is None:
                return False
            jets = self.tower_counts().get("jets")
            return jets is not None and jets >= self.jets_needed
        now = time.monotonic()
        settled = now - self.connected_at >= ITEM_SETTLE_SECONDS
        if code == TOWER_STAGE and settled and not self.tower_missing():
            self.tower_seen = True
        elif code == GOAL_STAGE and self.tower_seen:
            self.goal_reached = True
        if not self.goal_reached and settled and self.credits_running(now):
            self.goal_reached = True
            detail.info("The credits are rolling (mission 8:899): the final boss is beaten.")
        return self.goal_reached and not self.tower_missing()

    def sync_menu_souls(self) -> Optional[bool]:
        """While the pause menu (the map screen) is open, its Graffiti Soul total shows the Graffiti Soul items received
        (user, 2026-11-19 22:21). Only that number changes: the soul flags, the per-area counts and Roboy's rule stay as
        they are. True when written, False when it already showed it, None when there is nothing to do."""
        if self.game_reader is None or self.slot is None or self.save_status in ("old", "foreign"):
            return None
        if not getattr(self.game_reader, "can_write", False):
            return None
        target = self.soul_counter_target()
        if target is None:                                       # /soulcounter game: the game's own count
            return None
        result = self.state().set_menu_souls(target)
        if result and not self.menu_souls_told:
            self.menu_souls_told = True
            detail.info("The pause menu's Graffiti Soul total now shows the Graffiti Soul items received (%d)." % target)
        return result

    def check_release(self, seed_release: Optional[str]) -> bool:
        """Compare the release the seed was made with (slot data "release") with this client's. Says so in the window
        when they differ; True when they match."""
        if seed_release == RELEASE:
            detail.info("Seed and client are both JSRF v%s." % RELEASE)
            return True
        made = "JSRF v%s" % seed_release if seed_release else "an older JSRF build (before v1.0a)"
        logger.info("This seed was made with %s, but this client is v%s. Some things may not work as expected: "
                    "generate a new seed, or play this one with the jsrf.apworld it was made with." % (made, RELEASE))
        return False

    def credits_running(self, now: float) -> bool:
        """Whether the running mission is the credits (8:899). Reads the known mission object; looks for another at most
        every MISSION_SCAN_EVERY seconds when that one is gone."""
        if self.game_reader is None:
            return False
        state = self.state()
        mission = state._mission_at(self.mission_addr) if self.mission_addr else None
        if mission is None and now >= self.mission_scan_at:
            self.mission_scan_at = now + MISSION_SCAN_EVERY
            mission = state.running_mission(None)
            if mission is not None:
                self.mission_addr = mission["addr"]
        return mission is not None and mission["id"] == CREDITS_MISSION_ID

    def tower_counts(self, fresh: bool = False) -> Dict[str, int]:
        """The game's counts for the Tower's tag spot / Street Challenge / Jet Rank requirements that are on: "tags" (fully
        sprayed tag spots, check or not), "challenges" (cleared: the soul appeared or was picked up) and "jets" (Test Runs
        whose best result is a Jet rank). Read at most every
        GOAL_POLL seconds unless fresh; while no save can be read (loading, title screen) the last counts are kept."""
        if not (self.tags_needed or self.challenges_needed or self.jets_needed) or self.game_reader is None:
            return dict(self.counts_last)
        now = time.monotonic()
        if not fresh and now - self.counts_at < GOAL_POLL:
            return dict(self.counts_last)
        self.counts_at = now
        state = self.state()
        souls = state.collected_souls()
        if souls is None or self.on_title_screen():
            return dict(self.counts_last)
        if self.tags_needed:
            self.counts_last["tags"] = len(state.sprayed_tags())
        if self.challenges_needed:
            self.counts_last["challenges"] = len((souls | state.cleared_challenges()) & jsrf_game.CHALLENGE_IDS)
        if self.jets_needed:
            jets = state.jet_ranks()
            if jets is not None:
                self.counts_last["jets"] = len(jets)
        return dict(self.counts_last)

    def tower_requirements(self, fresh: bool = False) -> list:
        """(what, have, need) for each requirement of Gouji's Tower that is on; have is None when it cannot be read."""
        names = self.received_names()
        counts = self.tower_counts(fresh)
        out = [("the %s item" % TOWER_UNLOCK, int(TOWER_UNLOCK in names), 1)]
        if self.souls_required:
            out.append(("%s items" % SOUL_ITEM, names.count(SOUL_ITEM), self.souls_required))
        if self.tags_needed:
            out.append(("sprayed tag spots", counts.get("tags"), self.tags_needed))
        if self.challenges_needed:
            out.append(("cleared Street Challenges", counts.get("challenges"), self.challenges_needed))
        return out

    def tower_text(self) -> str:
        """Everything Gouji's Tower needs, in one phrase."""
        parts = [("the %s item" % TOWER_UNLOCK)]
        if self.souls_required:
            parts.append("%d %s items" % (self.souls_required, SOUL_ITEM))
        if self.tags_needed:
            parts.append("%d sprayed tag spots (of %d in the city)" % (self.tags_needed, TAG_TOTAL))
        if self.challenges_needed:
            parts.append("%d cleared Street Challenges (of %d)" % (self.challenges_needed, CHALLENGE_TOTAL))
        return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]

    def goal_text(self) -> str:
        """The goal in a sentence, for the connect message."""
        if self.goal == "jet_ranks":
            return ("Your goal: a Jet rank on %d of the %d Test Runs. Roboy in the Garage offers an area's Test Runs once you "
                    "have every Graffiti Soul there, Street Challenges included. /goal shows how far you are."
                    % (self.jets_needed, TEST_RUN_TOTAL))
        return ("Gouji's Tower opens with %s; the first time you come to the Garage with it open, Corn asks you (after that, "
                "talk to Corn in the Garage). Beating the final boss there completes your goal. /goal shows what is left."
                % self.tower_text())

    def announce_requirements(self):
        """Say once when the tag spot / Street Challenge requirement of Gouji's Tower is met."""
        counts = self.tower_counts()
        for key, need, label in (("tags", self.tags_needed, "Tag spots"), ("challenges", self.challenges_needed,
                                 "Street Challenges")):
            if need and key not in self.requirements_told and (counts.get(key) or 0) >= need:
                self.requirements_told.add(key)
                missing = self.tower_missing()
                logger.info("%s for Gouji's Tower: %d of %d, done! %s" % (
                    label, counts[key], need, "The Tower is open: talk to Corn in the Garage." if not missing else
                    "The Tower still needs %s." % ", ".join(missing)))

    def state(self) -> jsrf_game.JSRFGame:
        return jsrf_game.JSRFGame(self.game_reader)

    def unlocked_areas(self) -> Set[str]:
        """Areas whose Unlock item has been received (plus the chosen starting area)."""
        names = set()
        for item in self.items_received:
            try:
                names.add(self._item_name(item.item))
            except Exception:
                pass
        out = {a for a in AREAS if unlock_name(a) in names}
        if self.start_area:
            out.add(self.start_area)
        return out

    def split_by_unlock(self, found: Set[int]):
        """Split collected location ids into (reportable now, held until an area unlock arrives)."""
        open_areas = self.unlocked_areas()
        now, held = set(), set()
        for loc in found:
            needed = self.requirements.get(loc, ())
            (now if all(a in open_areas for a in needed) else held).add(loc)
        return now, held

    # ---- characters (data.CHARACTER_UNLOCKS) ----

    def received_characters(self) -> Set[int]:
        return {c for c in (character_of_item(i.item) for i in self.items_received) if c is not None}

    def roster_wanted(self, code: Optional[int]) -> int:
        """The roster the player should have: the New Game three plus every character item received. A received character
        whose own unlock check is still open is left out while the player is where that unlock happens (the game only runs
        it for a character that is not unlocked), and a character whose unlock was just found keeps its bit until the
        check has gone out (so a restart finds it again)."""
        mask = 0
        for c in self.start_chars | self.received_characters():
            u = CHARACTER_UNLOCK_OF.get(c)
            loc = character_location_id(c) if u else None
            if u and code in u.stages and loc in self.missing_locations and loc not in self.sent_locations \
                    and loc not in self.char_found:
                continue
            mask |= 1 << c
        for loc in self.char_found - self.sent_locations:
            mask |= 1 << (loc - character_location_id(0))
        if not mask & sum(1 << c for c in self.start_chars):
            # never leave the game without its starting character: with an empty roster the Garage's character lookup
            # (default.xbe 0x4D682) would search forever
            mask |= sum(1 << c for c in self.start_chars)
        return mask

    def ensure_playable(self, state) -> None:
        """Before a level load: if you are playing as a character you do not have, switch to the starting character."""
        if not self.manage_roster or not getattr(self.game_reader, "can_write", False):
            return
        cur = state.current_character()
        have = self.start_chars | self.received_characters()
        if cur is None or cur in have:
            return
        target = min(self.start_chars) if len(self.start_chars) == 1 else (6 if 6 in self.start_chars else min(self.start_chars))
        if state.set_current_character(target):
            detail.info("You were playing as %s, who is not in your crew yet; switching you to %s." % (CHARACTERS[cur], CHARACTERS[target]))

    def open_test_stages(self) -> Set[int]:
        """Stage codes whose Test Runs Roboy may offer: the unlocked areas."""
        open_areas = self.unlocked_areas()
        return {code for code, area in STAGE_AREAS.items() if area in open_areas}

    def sync_test_runs(self, code: Optional[int]) -> bool:
        """In the free-skate chapter keep the save's chapter number at 9, as after the story: Roboy's Test Run menu and the
        Test Run character rewards need it. Roboy then offers an area's Test Runs the game's own way, once every Graffiti
        Soul of the area is possessed (user decision 2026-11-17 19:23; game.open_test_menu is kept but not used).
        True when something was written."""
        if not getattr(self.game_reader, "can_write", False) or time.monotonic() - self.connected_at < ITEM_SETTLE_SECONDS:
            return False
        state = self.state()
        wrote = False
        chapter = state.chapter_number() if self.chapter_auto and code == GARAGE_STAGE else None
        if chapter is not None and chapter != 9 and 0 <= chapter <= 9:
            # the running mission (found again when the cached one is gone, e.g. after Continue on the title screen)
            mission = state.running_mission(self.mission_addr)
            if mission is not None and mission["hi"] == jsrf_game.FREE_SKATE_CHAPTER and mission["state"] == jsrf_game.STATE_RUNNING:
                self.mission_addr = mission["addr"]
                if state.set_chapter_number(9):
                    wrote = True
                    detail.info("Story chapter number set to 9 (was %d)." % chapter)
                    if not self.chapter_told:
                        self.chapter_told = True
                        logger.info("Story chapter set to 9, as after the story, so Roboy's Test Runs and the Test Run "
                                    "characters work.")
        return wrote

    def soul_counter_target(self) -> Optional[int]:
        """What the game's soul counter should show: the Graffiti Soul items received (mode "items", the default), the
        souls picked up in this game only ("pickups"), or the game's own count with the 20 default graffiti (None)."""
        if self.soul_counter_mode == "items":
            return self.received_names().count(SOUL_ITEM)
        return 0 if self.soul_counter_mode == "pickups" else None

    def sync_soul_counter(self) -> bool:
        """Keep the game's Graffiti Soul counter equal to the Graffiti Soul items received (user requests 2026-11-17
        20:06 and 2026-11-18 15:00), so it matches the souls Gouji's Tower counts. True when something was written."""
        if self.soul_counter_mode == "game" and not self.soul_counter_restore:
            return False
        if not getattr(self.game_reader, "can_write", False) or time.monotonic() - self.connected_at < ITEM_SETTLE_SECONDS:
            return False
        state = self.state()
        changed = state.set_soul_counter(self.soul_counter_target())
        if changed is None:
            return False
        self.soul_counter_restore = False
        if self.soul_counter_mode == "items":
            target = self.soul_counter_target()
            real = (state.soul_counter() or (0, 0))[0]
            if real > target and not self.soul_counter_ahead_told:
                self.soul_counter_ahead_told = True
                detail.info("The game's soul counter shows %d: you have picked up more souls (%d) than Graffiti Soul "
                            "items have arrived (%d), and picked-up souls stay counted (Roboy's Test Runs need them)."
                            % (real, real, target))
            if target > real + len(jsrf_game.COUNTER_FILLER_IDS) and not self.soul_counter_cap_told:
                self.soul_counter_cap_told = True
                detail.info("The game's soul counter tops out at %d here; /goal has the full count."
                            % (real + len(jsrf_game.COUNTER_FILLER_IDS)))
        if changed and not self.soul_counter_told:
            self.soul_counter_told = True
            detail.info("The game's soul counter now follows the Graffiti Soul items you have received.")
        return bool(changed)

    def received_tapes(self) -> Set[str]:
        return {a for a in (area_of_tape_item(i.item) for i in self.items_received) if a is not None}

    def sync_tapes(self, code: Optional[int] = None) -> bool:
        """Mystery Tapes and Street Challenges with tape items (user design 2026-11-16, reworked 2026-11-19 evening): an
        area's tape flag N and its five challenge open flags follow the area's Mystery Tape ITEM, so the item alone shows
        the tape and the challenges in the pause menu and opens them (user, 18:42). Picking the tape up is only the tape
        check, recorded in flag 13 + N (game.TAPE_PICKED). The levels' tapes carry 0x200 + N in the client's copies of the
        area missions (garage.TapeMissions), so they are there whatever flag N says and their pickup sets nothing; after
        the pickup the client takes the tape away on every visit. A tape that still carries N (its mission was loaded
        before the copies were written) is defused when the item is missing, as before. True when something was written."""
        if not self.manage_tapes or not getattr(self.game_reader, "can_write", False):
            return False
        now = time.monotonic()
        if now - self.connected_at < ITEM_SETTLE_SECONDS:
            return False
        state = self.state()
        have = self.received_tapes()
        bits = state.riddle_bits()
        if bits is None:
            return False
        here = STAGE_AREAS.get(code) if code is not None else None
        checked = set(getattr(self, "checked_locations", None) or ()) | set(self.sent_locations)
        change: Dict[int, bool] = {}
        picked = {n for n, flag in jsrf_game.TAPE_PICKED.items() if bits >> flag & 1}
        for n, loc in jsrf_game.TAPE_LOCATIONS.items():
            if loc in checked and n not in picked:     # the server knows the pickup (an earlier session or client)
                change[jsrf_game.TAPE_PICKED[n]] = True
                picked.add(n)
        # Pickups: look for the tape's "got" sequence only where it can matter (or while one is still playing).
        armed = here is not None and TAPE_FLAG[here] not in picked
        events = state.tape_events() if armed or self.tape_pending else []
        alive = {addr for addr, _ in events}
        for addr, value in events:
            n = value - jsrf_game.TAPE_DEFUSED if value >= jsrf_game.TAPE_DEFUSED else value
            area = TAPE_AREA.get(n)
            if area is None or addr in self.tape_pending:
                continue
            if value < jsrf_game.TAPE_DEFUSED and area not in have:
                state.defuse_tape_event(addr, value)   # an old-numbered tape: its pickup must not open the challenges
            self.tape_pending[addr] = (n, now)
            detail.info("Mystery Tape %d (%s) picked up." % (n, area))
            # The tape lying in the level stays until it is taken away; the player, still standing on it, would pick it
            # up a second time when the sequence ends (user, 2026-11-19 15:48).
            for obj, num, shown in state.world_tapes():
                if num in (n, jsrf_game.TAPE_DEFUSED + n) and shown:
                    state.remove_world_tape(obj, num)
        for addr, (n, since) in list(self.tape_pending.items()):
            if addr in alive and now - since < TAPE_EVENT_MAX:
                continue
            del self.tape_pending[addr]
            change[jsrf_game.TAPE_PICKED[n]] = True
            picked.add(n)
            area = TAPE_AREA[n]
            if area not in self.tapes_told:
                self.tapes_told.add(area)
                detail.info("Picked up the %s Mystery Tape.%s" % (area, "" if area in have else
                            " Its Street Challenges open when the %s item arrives." % tape_item_name(area)))
        for area in AREAS:
            opens, marks = challenge_flags(area), challenge_setup_flags(area)
            opened = [bool(bits >> f & 1) for f in opens]
            n = TAPE_FLAG[area]
            tape_on = bool(bits >> n & 1)
            if area in have:
                if area in self.tape_hold:                 # the item came during a held visit: let go of the held marks
                    self.tape_hold.discard(area)
                    change.update({f: False for f in marks})
                if not all(opened):
                    change.update({f: True for f in opens})
                if not tape_on:                            # the pause menu shows the tape and its challenges
                    change[n] = True
            else:
                if tape_on:
                    change[n] = False
                if any(opened):
                    # Opened without the item: a pickup of an old-numbered tape the client did not see (it was closed).
                    # Shut them, and since a challenge that has started stays for the visit, hold their "cleared" marks
                    # until the player leaves the area.
                    change.update({f: False for f, on in zip(opens, opened) if on})
                    if here == area:
                        self.tape_hold.add(area)
                    if area not in self.tapes_told:
                        self.tapes_told.add(area)
                        logger.info("%s's Street Challenges stay closed until the %s item arrives."
                                    % (area, tape_item_name(area)))
                if area in self.tape_hold:
                    if here == area:
                        change.update({f: True for f in marks if not bits >> f & 1})
                    else:
                        self.tape_hold.discard(area)
                        change.update({f: False for f in marks if bits >> f & 1})
                elif all(bits >> f & 1 for f in marks):
                    # all five marks set without the item: held by an older version of the client. Release them.
                    change.update({f: False for f in marks})
            if n in picked and here == area:
                self.remove_level_tape(area, n, now)
        if change:
            return state.set_riddle_flags(change)
        return False

    def remove_level_tape(self, area: str, tape: int, now: float) -> bool:
        """In an area whose tape was picked up: take away the tape the level placed again (the client's mission copies
        place it on every visit)."""
        if now < self.tape_scan_at:
            return False
        self.tape_scan_at = now + TAPE_SCAN_SECONDS
        removed = False
        state = self.state()
        for addr, n, shown in state.world_tapes():
            if n in (tape, jsrf_game.TAPE_DEFUSED + tape) and shown and state.remove_world_tape(addr, n):
                removed = True
                detail.info("%s: took away the tape the level placed again (already picked up)." % area)
        return removed

    def note_rival_fight(self) -> Optional[str]:
        """Say when a rival gang fight (missions 9:921, 9:926, 9:956) starts and how it ended, so a fight that should have
        been a check can be traced in the log (user report 2026-11-19). Returns what was said, if anything."""
        if not self.mission_addr or self.game_reader is None:
            return None
        state = self.state()
        mission = state._mission_at(self.mission_addr)
        lo = mission["id"] & 0xFFFF if mission is not None and mission["id"] >> 16 == 9 else None
        fight = next((r for r in RIVAL_BATTLES if r.mission == lo), None)
        if fight == self.rival_now:
            return None
        said = []
        if self.rival_now is not None:
            r = self.rival_now
            won = rival_location_id(r) in state.won_rival_battles()
            if won:
                said.append("You beat the %s (\"%s\")." % (r.gang, rival_location_name(r)))
            else:
                said.append("The %s fight ended without a win (Global flag %d is clear)." % (r.gang, r.flag))
        if fight is not None:
            said.append("The %s fight started (mission 9:%d)." % (fight.gang, fight.mission))
        self.rival_now = fight
        for line in said:
            detail.info(line)
        return " ".join(said) or None

    def sync_roster(self, code: Optional[int]) -> bool:
        """Find the game's own character unlocks and keep the roster as roster_wanted says. True when a write was made."""
        if not self.manage_roster or not getattr(self.game_reader, "can_write", False):
            return False
        if time.monotonic() - self.connected_at < ITEM_SETTLE_SECONDS:
            return False
        state = self.state()
        current = state.roster()
        if current is None:
            return False
        wanted = self.roster_wanted(code)
        # A bit the client did not leave there is the game's own unlock. Before the first look, the received characters
        # count as the client's (a received character that is being held clear must not look like an unlock).
        received = sum(1 << c for c in self.start_chars | self.received_characters())
        baseline = self.roster_last if self.roster_last is not None else received
        for c in range(24):
            if current >> c & 1 and not wanted >> c & 1 and not baseline >> c & 1 and c in CHARACTER_UNLOCK_OF:
                loc = character_location_id(c)
                if loc in self.missing_locations and loc not in self.char_found:
                    self.char_found.add(loc)
                    detail.info("%s joined the crew in the game: that is the check \"%s\"." % (CHARACTERS[c], character_location_name(c)))
                    wanted |= 1 << c
        if wanted == current:
            self.roster_last = current
            return False
        added = [c for c in range(24) if wanted >> c & 1 and not current >> c & 1]
        removed = [c for c in range(24) if current >> c & 1 and not wanted >> c & 1]
        if not state.set_roster(wanted, added):
            return False
        self.roster_last = wanted
        said = "%s|%s" % (added, removed)
        if said != self.roster_said:
            self.roster_said = said
            parts = []
            if added:
                parts.append("added " + ", ".join(CHARACTERS[c] for c in added))
            if removed:
                parts.append("took out " + ", ".join(CHARACTERS[c] for c in removed))
            detail.info("Roster: %s." % "; ".join(parts))
        return True

    def report_unknown_spots(self):
        """Say once per spot when the loaded area has a tag spot that is not in the tag table (no location for it)."""
        if self.settle_left(time.monotonic()) > 0:
            return
        new = [s for s in self.state().unknown_spots() if (s["area"], s["slot"]) not in self.spots_told]
        if new:
            self.spots_told |= {(s["area"], s["slot"]) for s in new}
            # log file only (user, 2026-11-19 18:55: no tag messages in the window)
            detail.info("Tag spots in %s that have no check yet: slot %s." % (new[0]["area"], ", ".join(str(s["slot"]) for s in new)))

    async def server_auth(self, password_requested: bool = False):
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_package(self, cmd: str, args: dict):
        if cmd == "Connected":
            self.sent_locations.clear()                      # re-report everything after (re)connecting
            self.held_notice.clear()
            self.stage = None                                # look at the current area again
            self.connected_at = time.monotonic()
            slot_data = args.get("slot_data") or {}
            self.start_area = slot_data.get("starting_area")
            self.souls_required = slot_data.get("souls_required")
            self.tags_needed = int(slot_data.get("tags_needed") or 0)
            self.challenges_needed = int(slot_data.get("challenges_needed") or 0)
            self.goal = slot_data.get("goal", "defeat_gouji")
            self.jets_needed = int(slot_data.get("jets_needed") or 0) if self.goal == "jet_ranks" else 0
            self.counts_at = -GOAL_POLL
            self.check_release(slot_data.get("release"))
            detail.info(self.goal_text())
            self.include_tags = bool(slot_data.get("include_tags"))
            self.manage_roster = "character_unlocks" in slot_data       # seeds made before characters were items: hands off
            self.char_found.clear()
            self.roster_last = None
            self.start_chars = set(slot_data.get("start_characters") or START_CHARACTERS)
            chars = [CHARACTERS[c] for c in sorted(self.start_chars) if c in CHARACTERS]
            logger.info("Starting area: %s. Starting character%s: %s." % (
                self.start_area or "unknown", "s" if len(chars) > 1 else "",
                ", ".join(chars[:-1]) + " and " + chars[-1] if len(chars) > 1 else (chars[0] if chars else "unknown")))
            self.manage_tapes = bool(slot_data.get("tape_items"))
            self.goal_sent = False                           # a reconnect sends the goal again if it was reached
            self.notice_count = None                         # the item list that follows is the connect sync: no notices
            self.refills_done = None                         # read the applied-refill count again (watcher asks)
            self.save_status = None                          # look at the loaded save again for this seed
            self.refill_asked = False
            self.tower_asks = None                           # read again (watcher asks)
            self.tower_asks_read = False
            self.own_done, self.own_asked = None, False      # read again (watcher asks)
            self.corn_phase = None
            self.corn_told.clear()
            if self.game_reader is not None:
                self.corn_show_idle()                        # the start area is known now, so Corn can name it
        elif cmd == "ReceivedItems":
            names = [self._item_name(i.item) for i in self.items_received[args["index"]:]]
            if names:
                # the first list after connecting is the items you already have (incl. the starting area's): file only
                # (and since 2026-11-19 20:21 every later one too: the server's "JSRF found ..." line already says it)
                detail.info("Received: %s" % ", ".join(names))
            self.show_item_notices()
        elif cmd == "Retrieved":
            keys = args.get("keys") or {}
            if self.slot is not None and self.refill_key() in keys:
                try:
                    self.refills_done = max(int(keys[self.refill_key()] or 0), 0)
                except (TypeError, ValueError):
                    self.refills_done = 0
            if self.slot is not None and self.tower_ask_key() in keys:
                try:
                    self.tower_asks = max(int(keys[self.tower_ask_key()] or 0), 0)
                except (TypeError, ValueError):
                    self.tower_asks = 0
            if self.slot is not None and self.own_key() in keys:
                value = keys[self.own_key()]
                own: Set[int] = set()
                for loc in value if isinstance(value, list) else ():
                    try:
                        own.add(int(loc))
                    except (TypeError, ValueError):
                        pass
                self.own_done = own | (self.own_done or set())

    def show_item_notices(self):
        """Put an "Item received" notice over the game window for every item that arrived since the last call. The first
        batch after connecting is the server's full list of items already received: it only sets the count."""
        total = len(self.items_received)
        if self.notice_count is None or total < self.notice_count:
            self.notice_count = total
            return
        for item in self.items_received[self.notice_count:]:
            try:
                name = self._item_name(item.item)
            except Exception:
                name = "an item"
            sender = getattr(self, "player_names", {}).get(item.player) if hasattr(self, "player_names") else None
            self.overlay.notify(format_notice(name, sender, item.player == self.slot))
        self.notice_count = total

    def _item_name(self, item_id: int) -> str:
        try:
            return self.item_names.lookup_in_game(item_id)         # newer Archipelago
        except AttributeError:
            return self.item_names[item_id]                        # older Archipelago

    def run_gui(self):
        from kvui import GameManager
        self.startup_help_pending = True            # the window's own /help at start is skipped (JSRFCommandProcessor)

        class JSRFManager(GameManager):
            logging_pairs = [("Client", "Archipelago")]
            base_title = "JSRF v%s - Archipelago Client" % RELEASE   # the window adds the Archipelago version

            def __init__(self, ctx):
                super().__init__(ctx)
                path = window_icon()                     # the window icon needs a real file: client_icon.png, copied out
                if path:
                    self.icon = path

        self.ui = JSRFManager(self)
        self.ui_task = asyncio.create_task(self.ui.async_run(), name="UI")


def window_icon() -> Optional[str]:
    """client_icon.png (shipped with this world, inside the .apworld) as a file in Archipelago's cache folder, for the
    window icon, which cannot be read from inside a zip. None if that fails (the window keeps Archipelago's icon)."""
    try:
        import pkgutil
        import Utils
        data = pkgutil.get_data(__package__, "client_icon.png")
        if not data:
            return None
        folder = Utils.cache_path("jsrf")
        os.makedirs(folder, exist_ok=True)
        old = os.path.join(folder, "client_icon.png")       # made from the game's files by the 2026-11-19 16:16 build
        if os.path.isfile(old):
            os.remove(old)
        path = os.path.join(folder, "jsrf_client_icon.png")
        if not os.path.isfile(path) or open(path, "rb").read() != data:
            with open(path, "wb") as f:
                f.write(data)
        return path
    except Exception:
        return None


def _connect_game(ctx: JSRFContext) -> bool:
    """(Re)attach to the engine process when needed. Returns True when a live reader exists."""
    if ctx.game_reader is not None:
        try:
            if ctx.game_reader.alive():
                return True
        except Exception:
            pass
        ctx.game_reader = None
        logger.info("Lost the game. Waiting for it to start again...")
    try:
        ctx.game_reader = jsrf_game.attach(write=True)
        ctx.overlay.pid = getattr(ctx.game_reader, "pid", None)
        ctx.overlay.game_root = ctx.game_folder()                # the notices use the game's own font
        ctx.auto_garage_done = False                          # a restarted game gets a new New Game
        ctx.roster_last = None
        ctx.corn_phase = None
        ctx.last_error = ""
        ctx.corn_show_idle()
        ctx.garage_setup()
        ctx.tapes_setup()
        logger.info("Found the game." if getattr(ctx.game_reader, "can_write", False) else
                    "Found the game, but without write access: locked areas cannot send you back.")
        return True
    except RuntimeError as e:
        if str(e) != ctx.last_error:                          # say each problem once
            ctx.last_error = str(e)
            (logger if "not running" not in ctx.last_error else detail).info(ctx.last_error)
        return False


async def watch_step(ctx: JSRFContext):
    """One poll of the game: everything the client does on its own. Returns early when there is nothing to do."""
    if ctx.server is None or not ctx.server.socket.open or ctx.slot is None:
        return
    if not _connect_game(ctx):
        return
    code = ctx.state().current_stage()
    ctx.note_stage(code, time.monotonic())
    # Fresh-save handling: with a save loaded, do nothing (no checks, no changes to the game) unless it may be used
    # with this seed. With no save loaded (title screen) the rest runs as before; it has nothing to send.
    loaded = ctx.state().collected_locations(ctx.challenge_on_clear, ctx.include_tags)
    if loaded is not None and not ctx.on_title_screen() and not ctx.save_ok(loaded):
        return
    if ctx.track_goal(code):
        ctx.goal_sent = True
        await ctx.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
        logger.info("Jet ranks: %d. Goal complete!" % ctx.jets_needed if ctx.goal == "jet_ranks" else
                    "The final boss is down. Goal complete!")
    ctx.check_stage(code)
    if ctx.auto_garage_due(code, time.monotonic()):
        if ctx.corn_purpose == "tower":
            result = await asyncio.get_running_loop().run_in_executor(None, ctx.finish_tower_ask)
            ctx.after_auto_garage(result, time.monotonic(), "")
        else:
            result = await asyncio.get_running_loop().run_in_executor(None, ctx.try_auto_garage)
            ctx.after_auto_garage(result, time.monotonic())
    elif ctx.tower_ask_due(code, time.monotonic()):
        result = await asyncio.get_running_loop().run_in_executor(None, ctx.try_tower_ask)
        if result == "sent":
            ctx.tower_asks = (ctx.tower_asks or 0) + 1      # Corn asks by himself once per seed
            await ctx.send_msgs([{"cmd": "Set", "key": ctx.tower_ask_key(), "default": 0, "want_reply": False,
                                  "operations": [{"operation": "add", "value": 1}]}])
        elif result not in ("wait", "plain"):
            ctx.bounce_until = time.monotonic() + BOUNCE_RETRY
    if ctx.corn_poll(code, time.monotonic()) == "fallback":
        result = await asyncio.get_running_loop().run_in_executor(None, ctx.try_auto_garage)
        ctx.after_auto_garage(result, time.monotonic(), "Sending you to the free-skate Garage.")
    if ctx.garage_active():
        result = await asyncio.get_running_loop().run_in_executor(None, ctx.garage_poll, code, time.monotonic())
        if result == "sent":
            ctx.bounce_until = time.monotonic() + BOUNCE_COOLDOWN
    if await asyncio.get_running_loop().run_in_executor(None, ctx.garage_return_due, code, time.monotonic()):
        after_runs = ctx.test_run_seen
        result = await asyncio.get_running_loop().run_in_executor(None, ctx.try_bounce)
        if result == "sent":
            ctx.test_run_seen, ctx.shut_garage = False, None
            ctx.bounce_until = time.monotonic() + BOUNCE_COOLDOWN
            logger.info("Sending you back to the free-skate Garage%s." % (" after the Test Runs" if after_runs else ""))
        elif result != "wait":
            ctx.bounce_until = time.monotonic() + BOUNCE_RETRY
    area = ctx.bounce_due(code, time.monotonic())
    if area:
        result = await asyncio.get_running_loop().run_in_executor(None, ctx.bounce_for, area)
        ctx.after_bounce(area, result, time.monotonic())
    found = ctx.state().collected_locations(ctx.challenge_on_clear, ctx.include_tags)
    if found is None:                                     # title screen / no game state yet
        return
    ctx.sync_roster(code)
    ctx.sync_tapes(code)
    ctx.note_rival_fight()
    ctx.sync_test_runs(code)
    if ctx.own_done is None and not ctx.own_asked:
        ctx.own_asked = True
        await ctx.send_msgs([{"cmd": "Get", "keys": [ctx.own_key()]}])
    own_new = ctx.note_own_progress(found)
    if own_new:
        await ctx.send_msgs([{"cmd": "Set", "key": ctx.own_key(), "default": [], "want_reply": False,
                              "operations": [{"operation": "update", "value": sorted(own_new)}]}])
    ctx.restore_progress(found, time.monotonic())
    ctx.sync_soul_counter()
    if ctx.tower_asks is None and not ctx.tower_asks_read:
        ctx.tower_asks_read = True
        await ctx.send_msgs([{"cmd": "Get", "keys": [ctx.tower_ask_key()]}])
    if ctx.refills_done is None and not ctx.refill_asked:
        ctx.refill_asked = True
        await ctx.send_msgs([{"cmd": "Get", "keys": [ctx.refill_key()]}])
    ctx.announce_requirements()
    applied = ctx.apply_refills()
    if applied is not None:
        await ctx.send_msgs([{"cmd": "Set", "key": ctx.refill_key(), "default": 0, "want_reply": False,
                              "operations": [{"operation": "max", "value": applied}]}])
    found |= ctx.char_found
    if ctx.include_tags:
        ctx.report_unknown_spots()
    reportable, held = ctx.split_by_unlock(found)
    held = (held & set(ctx.missing_locations)) - ctx.sent_locations
    for area in sorted({a for loc in held for a in ctx.requirements.get(loc, ()) if a not in ctx.unlocked_areas()}):
        if area not in ctx.held_notice:
            ctx.held_notice.add(area)
            logger.info("Holding checks from %s until the %s item arrives." % (area, unlock_name(area)))
    new = (reportable & set(ctx.missing_locations)) - ctx.sent_locations
    if new:
        ctx.sent_locations |= new
        await ctx.send_msgs([{"cmd": "LocationChecks", "locations": sorted(new)}])
        detail.info("Checked %d location(s)." % len(new))



async def menu_watcher(ctx: JSRFContext):
    """Looks for the open pause menu often (MENU_POLL), so its Graffiti Soul total shows the items received from the
    first frames on (the main watcher polls every POLL_SECONDS)."""
    while not ctx.exit_event.is_set():
        await asyncio.sleep(MENU_POLL)
        try:
            ctx.sync_menu_souls()
        except Exception as e:                                 # the game closing mid-read and the like: note once
            key = "menu: %s: %s" % (type(e).__name__, e)
            if key not in ctx.watch_errors:
                ctx.watch_errors.add(key)
                detail.info("Pause menu soul total: %s" % key)


async def game_watcher(ctx: JSRFContext):
    while not ctx.exit_event.is_set():
        await asyncio.sleep(POLL_SECONDS)
        try:
            await watch_step(ctx)
        except Exception as e:                                 # never die silently: say what broke, keep watching
            key = "%s: %s" % (type(e).__name__, e)
            if key not in ctx.watch_errors:
                ctx.watch_errors.add(key)
                logger.exception("The client hit an error while watching the game (it keeps going; please send this "
                                 "log to the developer): %s" % key)

def launch(*launch_args: str):
    async def main(args):
        ctx = JSRFContext(args.connect, args.password)
        ctx.auth = args.name
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")
        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()
        ctx.watcher_task = asyncio.create_task(game_watcher(ctx), name="JSRFWatcher")
        ctx.menu_task = asyncio.create_task(menu_watcher(ctx), name="JSRFMenuWatcher")
        await ctx.exit_event.wait()
        ctx.corn_restore()                                         # Corn gets his own words back
        ctx.garage_restore()                                       # ...and the Garage its own files
        ctx.tapes_restore()                                        # ...and the areas their own missions
        ctx.server_address = None
        # The window is closed (or closing): a connection error that arrives now must go to the log, not to a popup,
        # which would need the window's App and crashed the client on exit (JSRFClient_startup_error.txt, 2026-11-16).
        ctx.ui = None
        await ctx.shutdown()

    Utils.init_logging("JSRFClient", exception_logger="Client")
    parser = get_base_parser(description="Jet Set Radio Future Archipelago client.")
    parser.add_argument("--name", default=None, help="Slot name to connect as.")
    parser.add_argument("url", nargs="?", help="Archipelago connection url")
    args = parser.parse_args(launch_args)

    if args.url:                                               # archipelago://name:password@host:port
        import urllib.parse
        url = urllib.parse.urlparse(args.url)
        if url.scheme == "archipelago":
            args.connect = "%s:%d" % (url.hostname, url.port) if url.port else (url.hostname or "")
            if url.username:
                args.name = urllib.parse.unquote(url.username)
            if url.password:
                args.password = urllib.parse.unquote(url.password)
        else:
            parser.error("Unsupported url scheme: %s" % url.scheme)

    import colorama
    colorama.just_fix_windows_console()
    asyncio.run(main(args))
    colorama.deinit()


if __name__ == "__main__":
    launch()
