"""Reading and writing another process's memory through /proc/<pid>/mem (Linux and Android). No Archipelago imports.

Android keeps apps apart: a terminal app (Termux and the like) can only see and read the game's process when it runs as
root (su), or when the game is a debuggable build. Without that, the game's process is hidden and /proc/<pid>/mem is
refused, and nothing in this module can change it.

The game's Xbox memory is one mapping whose first byte is Xbox address 0, so host address = mapping start + Xbox address.
The mapping is found by the XBE header the engine loads at Xbox address 0x10000: the signature "XBEH" sits 0x10000
bytes past the start of the mapping. (The engine maps the same RAM again at other addresses; any of those views works.)
"""
import errno
import os
import re
from typing import Callable, List, Optional, Tuple

XBE_VA = 0x10000
PACKAGE = "com.jumatt.jsrfunleashed"          # the Android app's package, which is also its process name
MATCH = (PACKAGE, "jsrf_recomp")               # process names looked for (Android app, Linux/Mac engine)
Region = Tuple[int, int, str, str]             # start, end, permissions, path

_MAPS_LINE = re.compile(r"^([0-9a-fA-F]+)-([0-9a-fA-F]+)\s+(\S+)\s+\S+\s+\S+\s+\S+\s*(.*)$")


def find_pids(match=None, proc: str = "/proc") -> List[Tuple[int, str]]:
    """(pid, process name) for every visible process whose name is one of `match`. On Android an app's process name is its
    package; other processes of the same app carry a ':suffix' and are not returned."""
    match = MATCH if match is None else match
    found = []
    try:
        names = os.listdir(proc)
    except OSError:
        return found
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open("%s/%s/cmdline" % (proc, name), "rb") as f:
                raw = f.read(4096)
        except OSError:
            continue
        first = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
        if first and any(first == m or os.path.basename(first) == m for m in match):
            found.append((int(name), first))
    return sorted(found)


def visible_process_count(proc: str = "/proc") -> int:
    """How many processes this user can see (Android hides everyone else's from an ordinary app)."""
    try:
        return sum(1 for n in os.listdir(proc) if n.isdigit())
    except OSError:
        return 0


def read_maps(pid: int, proc: str = "/proc") -> List[Region]:
    out = []
    with open("%s/%d/maps" % (proc, pid), "r", errors="replace") as f:
        for line in f:
            m = _MAPS_LINE.match(line)
            if m:
                out.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3), m.group(4).strip()))
    return out


def find_base(read_abs: Callable[[int, int], bytes], regions: List[Region]) -> Optional[int]:
    """Start of the mapping that holds the Xbox's memory: the first readable region with "XBEH" 0x10000 bytes in."""
    for start, end, perms, _ in sorted(regions):
        if "r" in perms and end - start >= XBE_VA + 4 and read_abs(start + XBE_VA, 4) == b"XBEH":
            return start
    return None


class ProcMem:
    """/proc/<pid>/mem opened for reading, or for reading and writing when `write` is asked for and allowed."""

    def __init__(self, pid: int, write: bool = False, proc: str = "/proc"):
        self.pid = pid
        self.can_write = False
        path = "%s/%d/mem" % (proc, pid)
        if write:
            try:
                self.fd = os.open(path, os.O_RDWR)
                self.can_write = True
                return
            except OSError:
                pass
        self.fd = os.open(path, os.O_RDONLY)

    def read(self, addr: int, n: int) -> bytes:
        try:
            return os.pread(self.fd, n, addr)
        except (OSError, OverflowError, ValueError):
            return b""

    def write(self, addr: int, data: bytes) -> bool:
        if not self.can_write:
            return False
        try:
            return os.pwrite(self.fd, data, addr) == len(data)
        except (OSError, OverflowError, ValueError):
            return False

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


def game_dirs(process_name: str) -> List[str]:
    """Folders the Android app keeps its files in, most likely first (only those that exist from where we stand)."""
    if "/" in process_name or "." not in process_name:
        return []
    candidates = [
        "/sdcard/Android/data/%s/files" % process_name,
        "/storage/emulated/0/Android/data/%s/files" % process_name,
        "/storage/self/primary/Android/data/%s/files" % process_name,
        "/data/media/0/Android/data/%s/files" % process_name,
        "/sdcard/Android/data/%s" % process_name,
        "/data/user/0/%s/files" % process_name,
        "/data/data/%s/files" % process_name,
    ]
    return [c for c in candidates if os.path.isdir(c)]


def is_android() -> bool:
    return os.path.exists("/system/build.prop") or "ANDROID_ROOT" in os.environ


def why_not(err: OSError) -> str:
    """A plain reason for a refused open of /proc/<pid>/mem."""
    if err.errno in (errno.EACCES, errno.EPERM):
        return "Android does not let this app read the game's memory. Run the client as root (su)."
    if err.errno in (errno.ESRCH, errno.ENOENT):
        return "The game process went away."
    return "Could not open the game's memory (%s)." % err.strerror
