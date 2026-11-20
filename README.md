# Jet Set Radio Future for Archipelago

An [Archipelago](https://archipelago.gg) world and client for Jet Set Radio Future, played on JSRF Unleashed for Windows.

**Current release: v1.0a (alpha).**

**This project was developed along side AI**

## What it does

You skate Tokyo-to as it is after the story, with the Garage as your hub. Every area stays locked until its Unlock item
arrives, and what you find in the city is sent out to the multiworld.

**Checks**

| Check | How many |
| --- | --- |
| Graffiti Souls lying in the levels | 40 |
| Graffiti Souls from Street Challenges | 65 |
| Mystery Tapes | 13 |
| Rival gang battles (Doom Riders, Love Shockers, Immortals) | 3 |
| Recruited characters (Rhyth, Boogie, Cube, Jazz, Soda) | 5, or 17 with the Test Run characters |
| Jet ranks on Roboy's Test Runs | 39 |
| Graffiti tag spots (off by default) | 572 |

**Items:** an Unlock item for each area, every character, Mystery Tape items (an area's Street Challenges open with its
tape), Graffiti Soul items, Gouji's Tower Unlock, and Spray Can / Health refills as filler.

**Goals:** defeat Gouji in Gouji's Tower, or earn a set number of Jet ranks on Roboy's Test Runs.

The client runs beside the game. It sends your checks, hands you your items, turns you back from areas you haven't
unlocked, has Corn tell you what's going on, and shows the items you receive on the game screen.

## Requirements

- [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases/latest) 0.6.8 or newer
- JSRF Unleashed 0.6.10 on Windows, set up with your own copy of Jet Set Radio Future

## Installing

1. Download `jsrf.apworld` from this repository's **Releases** page.
2. Put it in the `custom_worlds` folder of your Archipelago install, or use **Install APWorld** in the Archipelago
   Launcher.
3. Follow the [setup guide](jsrf/docs/setup_en.md) to make your options file and connect.

The [game page](<jsrf/docs/en_Jet Set Radio Future.md>) explains the checks, items and goals in more detail.
[`Jet Set Radio Future.yaml`](<Jet Set Radio Future.yaml>) is an example options file with every option at its
default; the Options Creator in the Launcher makes the same file.

## Client commands

| Command | What it shows or does |
| --- | --- |
| `/goal` | Your goal and how far along you are |
| `/unlocks` | Which areas are open, and checks held for areas still locked |
| `/tapes` | Which Mystery Tape items you have |
| `/checks` | Whether the loaded save is tied to your seed, and how many checks of each kind are done |
| `/usesave` | Ties the loaded save to your seed |

## Building from source

With Python 3 installed, run:

```
python build_apworld.py
```

The finished world is written to `dist/jsrf.apworld`.

## Reporting a problem

Open an issue and attach two files: the newest `JSRFClient_*.txt` from Archipelago's `logs` folder, and `last-run.log`
from your JSRF Unleashed folder.

## Legal

This is a fan project, not affiliated with or endorsed by SEGA. Jet Set Radio Future and its characters belong to SEGA.
JSRF Unleashed is a separate project by its own authors. No game files are included: the client reads what it needs from
your own copy of the game while it runs.

The code is released under the MIT License (see [LICENSE](LICENSE)).
