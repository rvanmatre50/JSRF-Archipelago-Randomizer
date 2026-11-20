"""Build jsrf.apworld from the jsrf folder.

    python build_apworld.py

writes dist/jsrf.apworld. Put it in Archipelago's custom_worlds folder, or attach it to a GitHub release.
Only the Python standard library is needed.
"""
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "jsrf")
OUTPUT = os.path.join(HERE, "dist", "jsrf.apworld")
SKIP_FOLDERS = {"__pycache__"}
CONTAINER_VERSION = 7          # the .apworld container format Archipelago 0.6.8 writes


def main() -> None:
    with open(os.path.join(SOURCE, "archipelago.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    # The source manifest leaves out the container fields (Archipelago's own world test asks for that);
    # the packed copy gets them, as Archipelago's packer does.
    manifest.update(version=CONTAINER_VERSION, compatible_version=CONTAINER_VERSION)
    text = json.dumps(manifest, indent=4)

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    temporary = OUTPUT + ".new"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("archipelago.json", text)
        z.writestr("jsrf/archipelago.json", text)
        for folder, subfolders, files in os.walk(SOURCE):
            subfolders[:] = sorted(s for s in subfolders if s not in SKIP_FOLDERS)
            for name in sorted(files):
                path = os.path.join(folder, name)
                inside = os.path.relpath(path, SOURCE).replace(os.sep, "/")
                if inside == "archipelago.json" or name.endswith(".pyc"):
                    continue
                z.write(path, "jsrf/" + inside)
    os.replace(temporary, OUTPUT)
    print("Wrote %s (JSRF world %s)" % (OUTPUT, manifest.get("world_version")))


if __name__ == "__main__":
    main()
