"""On-screen item notices over the game window (Windows only, pure ctypes; no Archipelago imports).

The game is a separate program we do not change, so the notices are a small window of our own laid over the game
window's bottom left corner: up to three notices at once, each white text on its own semi-transparent black box, newest
at the bottom, each leaving after a few seconds. The text uses JSRF's own lettering, read from the player's
Media\\Font\\jetfont.dat (jetfont.py); if that file cannot be used, Segoe UI stands in. The window is topmost, ignores
the mouse (clicks go through to the game), never takes focus and has no taskbar button. Everything runs on one
background thread with its own Win32 message loop; any failure turns the overlay off and is reported once through the
`on_error` callback instead of reaching the client."""
import collections
import sys
import threading
import time
from typing import Callable, Deque, Dict, List, Optional, Tuple

from . import jetfont

SHOW_SECONDS = 4.0           # how long one notice stays up
GAP_SECONDS = 0.3            # at least this long between two notices appearing (a batch comes in one by one)
MAX_VISIBLE = 3              # notices on screen at once (user request, 2026-11-17)
MAX_QUEUE = 30               # older waiting notices are dropped beyond this (e.g. a big batch of items at once)
BOX_ALPHA = 170              # 0-255 opacity of the black box behind the text
LINE_SHARE = 0.032           # height of one line of text, as a share of the game window's height
PAD_X, PAD_Y, STACK_GAP = 0.45, 0.25, 0.18   # box padding and the clear gap between boxes, in line heights
MARGIN = 0.04                # distance from the game window's left and bottom edges, as a share of its height
FALLBACK_FONT = "Segoe UI"
TICK_MS = 50


def format_notice(item: str, sender: Optional[str], own: bool) -> str:
    """The notice for one item (user wording, 2026-11-17): 'You found your own X' for one found in your own world,
    'Alice found your X' for one another player found."""
    return "You found your own %s" % item if own or not sender else "%s found your %s" % (sender, item)


class NoticeQueue:
    """The part that decides what is on screen when (no Windows calls, so it can be tested anywhere)."""

    def __init__(self, show_seconds: float = SHOW_SECONDS, gap_seconds: float = GAP_SECONDS, max_queue: int = MAX_QUEUE,
                 max_visible: int = MAX_VISIBLE):
        self.show_seconds, self.gap_seconds, self.max_visible = show_seconds, gap_seconds, max_visible
        self.pending: Deque[str] = collections.deque(maxlen=max_queue)
        self.visible: List[Tuple[str, float]] = []           # (text, leaves at), oldest first
        self.next_at = 0.0
        self.lock = threading.Lock()

    def push(self, text: str):
        with self.lock:
            self.pending.append(text)

    def tick(self, now: float) -> Optional[List[str]]:
        """Advance the clock. Returns the notices to show now, oldest first ([] to hide), or None when nothing changes."""
        with self.lock:
            kept = [v for v in self.visible if now < v[1]]
            changed = len(kept) != len(self.visible)
            self.visible = kept
            if self.pending and len(self.visible) < self.max_visible and now >= self.next_at:
                self.visible.append((self.pending.popleft(), now + self.show_seconds))
                self.next_at = now + self.gap_seconds
                changed = True
            return [t for t, _ in self.visible] if changed else None


class Painter:
    """Turns notices into one premultiplied BGRA picture. `measure_gdi(text, px)` is the Segoe UI stand-in, given by
    the Windows side; everything else here is plain Python."""

    def __init__(self, measure_gdi: Optional[Callable[[str, int], Tuple[int, int, bytes]]] = None,
                 on_note: Callable[[str], None] = lambda msg: None):
        self.measure_gdi = measure_gdi
        self.on_note = on_note
        self.root: Optional[str] = None
        self.loaded_root: Optional[str] = "<none>"
        self.font: Optional[jetfont.JetFont] = None
        self.cache: Dict[Tuple[str, int], Tuple[int, int, bytes]] = {}

    def load(self, root: Optional[str]):
        if root == self.loaded_root:
            return
        self.loaded_root, self.cache = root, {}
        self.font, why = jetfont.load(root)
        if self.font is not None:
            self.on_note("On-screen notices use the game's own font.")
        elif root:
            self.on_note("On-screen notices use %s: the game's font could not be read (%s)." % (FALLBACK_FONT, why))

    def line(self, text: str, line_px: int, max_width: int) -> Tuple[int, int, bytes]:
        key = (text, line_px)
        if key not in self.cache:
            if self.font is not None:
                w, h, mask = self.font.render(text)
                factor = line_px / self.font.line_height
            elif self.measure_gdi is not None:
                w, h, mask = self.measure_gdi(text, line_px)
                factor = 1.0
            else:
                raise RuntimeError("no font")
            if w * factor > max_width:
                factor = max_width / w
            if len(self.cache) > 40:
                self.cache.clear()
            self.cache[key] = jetfont.scale_mask(w, h, mask, factor)
        return self.cache[key]

    def paint(self, texts: List[str], game_height: int, max_width: int) -> Tuple[int, int, bytearray]:
        self.load(self.root)
        line_px = max(14, int(game_height * LINE_SHARE))
        pad_x, pad_y, gap = int(line_px * PAD_X), int(line_px * PAD_Y), max(2, int(line_px * STACK_GAP))
        lines = [self.line(t, line_px, max(50, max_width - 2 * pad_x)) for t in texts]
        return jetfont.compose(lines, pad_x, pad_y, gap, BOX_ALPHA)


class Overlay:
    """The notice window. `start()` is safe to call on any system; off Windows it does nothing."""

    def __init__(self, on_error: Callable[[str], None] = lambda msg: None, on_note: Callable[[str], None] = lambda msg: None):
        self.queue = NoticeQueue()
        self.on_error = on_error
        self.on_note = on_note
        self.enabled = True
        self.pid: Optional[int] = None           # the game's process id (its window is looked up by it)
        self.game_root: Optional[str] = None     # the game folder, for its font (set by the client)
        self.thread: Optional[threading.Thread] = None
        self.failed = False

    def notify(self, text: str):
        if self.enabled and not self.failed:
            self.queue.push(text)
            self.start()

    def start(self):
        if self.thread is not None or self.failed or sys.platform != "win32":
            return
        self.thread = threading.Thread(target=self._run, name="JSRFOverlay", daemon=True)
        self.thread.start()

    # ---- Windows ----
    def _run(self):
        try:
            self._loop()
        except Exception as e:                   # never take the client down: switch off and say so once
            self.failed = True
            self.on_error("The on-screen item notices stopped working (%s: %s); items still show in this window."
                          % (type(e).__name__, e))

    def _loop(self):
        import ctypes
        from ctypes import wintypes as wt
        user32, gdi32, k32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                        ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
        PBMI = ctypes.POINTER(BITMAPINFOHEADER)
        # 64-bit Windows: every handle must be declared, or ctypes passes it as a 32-bit int
        sig = {
            (user32, "DefWindowProcW"): (ctypes.c_ssize_t, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]),
            (user32, "CreateWindowExW"): (wt.HWND, [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                                    ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]),
            (user32, "GetWindowRect"): (wt.BOOL, [wt.HWND, ctypes.POINTER(wt.RECT)]),
            (user32, "GetDC"): (wt.HDC, [wt.HWND]),
            (user32, "ReleaseDC"): (ctypes.c_int, [wt.HWND, wt.HDC]),
            (user32, "ShowWindow"): (wt.BOOL, [wt.HWND, ctypes.c_int]),
            (user32, "SetWindowPos"): (wt.BOOL, [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]),
            (user32, "UpdateLayeredWindow"): (wt.BOOL, [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE),
                                                        wt.HDC, ctypes.POINTER(wt.POINT), wt.DWORD,
                                                        ctypes.POINTER(BLENDFUNCTION), wt.DWORD]),
            (user32, "SetTimer"): (ctypes.c_size_t, [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]),
            (user32, "GetWindowThreadProcessId"): (wt.DWORD, [wt.HWND, ctypes.POINTER(wt.DWORD)]),
            (user32, "IsWindowVisible"): (wt.BOOL, [wt.HWND]),
            (user32, "GetWindow"): (wt.HWND, [wt.HWND, wt.UINT]),
            (user32, "GetMessageW"): (wt.BOOL, [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]),
            (user32, "TranslateMessage"): (wt.BOOL, [ctypes.POINTER(wt.MSG)]),
            (user32, "DispatchMessageW"): (ctypes.c_ssize_t, [ctypes.POINTER(wt.MSG)]),
            (gdi32, "CreateCompatibleDC"): (wt.HDC, [wt.HDC]),
            (gdi32, "DeleteDC"): (wt.BOOL, [wt.HDC]),
            (gdi32, "CreateDIBSection"): (wt.HBITMAP, [wt.HDC, PBMI, wt.UINT, ctypes.POINTER(ctypes.c_void_p),
                                                      wt.HANDLE, wt.DWORD]),
            (gdi32, "DeleteObject"): (wt.BOOL, [wt.HGDIOBJ]),
            (gdi32, "SelectObject"): (wt.HGDIOBJ, [wt.HDC, wt.HGDIOBJ]),
            (gdi32, "SetBkMode"): (ctypes.c_int, [wt.HDC, ctypes.c_int]),
            (gdi32, "SetTextColor"): (wt.DWORD, [wt.HDC, wt.DWORD]),
            (gdi32, "TextOutW"): (wt.BOOL, [wt.HDC, ctypes.c_int, ctypes.c_int, wt.LPCWSTR, ctypes.c_int]),
            (gdi32, "GetTextExtentPoint32W"): (wt.BOOL, [wt.HDC, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.SIZE)]),
            (gdi32, "CreateFontW"): (wt.HFONT, [ctypes.c_int] * 5 + [wt.DWORD] * 8 + [wt.LPCWSTR]),
            (k32, "GetModuleHandleW"): (wt.HMODULE, [wt.LPCWSTR]),
        }
        for (lib, name), (res, args) in sig.items():
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = res, args

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                        ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                        ("lpszClassName", wt.LPCWSTR)]

        WM_TIMER, WM_DESTROY = 0x0113, 0x0002
        WS_POPUP = 0x80000000
        WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_LAYERED = 0x8, 0x80, 0x80000
        WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x20, 0x08000000
        SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
        HWND_TOPMOST = wt.HWND(-1)
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x2, 0x1, 0x10
        ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 0x2, 0x0, 0x1
        TRANSPARENT_BK = 1

        def dib(width: int, height: int):
            """A top-down 32-bit bitmap in a memory DC: (dc, bitmap, old object, pointer to its pixels)."""
            bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
            bits = ctypes.c_void_p()
            mem = gdi32.CreateCompatibleDC(None)
            bmp = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            if not mem or not bmp or not bits.value:
                if bmp:
                    gdi32.DeleteObject(bmp)
                if mem:
                    gdi32.DeleteDC(mem)
                raise OSError("CreateDIBSection failed (%d)" % k32.GetLastError())
            return mem, bmp, gdi32.SelectObject(mem, bmp), bits.value

        def free(mem, bmp, old):
            gdi32.SelectObject(mem, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem)

        gdi_fonts: Dict[int, int] = {}

        def measure_gdi(text: str, px: int) -> Tuple[int, int, bytes]:
            """The Segoe UI stand-in: white text drawn on black, its brightness used as the mask."""
            if px not in gdi_fonts:
                gdi_fonts[px] = gdi32.CreateFontW(-int(px * 0.8), 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 4, 0, FALLBACK_FONT)
            probe = gdi32.CreateCompatibleDC(None)
            gdi32.SelectObject(probe, gdi_fonts[px])
            size = wt.SIZE()
            gdi32.GetTextExtentPoint32W(probe, text, len(text), ctypes.byref(size))
            gdi32.DeleteDC(probe)
            w, h = max(1, size.cx), max(1, size.cy)
            mem, bmp, old, bits = dib(w, h)
            try:
                gdi32.SelectObject(mem, gdi_fonts[px])
                gdi32.SetBkMode(mem, TRANSPARENT_BK)
                gdi32.SetTextColor(mem, 0xFFFFFF)
                gdi32.TextOutW(mem, 0, 0, text, len(text))
                raw = ctypes.string_at(bits, w * h * 4)
            finally:
                free(mem, bmp, old)
            return w, h, raw[1::4]

        painter = Painter(measure_gdi, self.on_note)

        def find_game_window() -> Optional[wt.RECT]:
            if not self.pid:
                return None
            found = []

            @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
            def each(hwnd, _):
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == self.pid and user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4):  # no owner
                    r = wt.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(r)) and r.right - r.left > 200:
                        found.append(((r.right - r.left) * (r.bottom - r.top), r))
                return True
            user32.EnumWindows(each, 0)
            return max(found, key=lambda f: f[0])[1] if found else None

        def show(hwnd, texts: List[str]):
            game = find_game_window()
            if game is None:                    # no game window found: the main screen
                game = wt.RECT(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
            game_w, game_h = game.right - game.left, game.bottom - game.top
            margin = int(game_h * MARGIN)
            painter.root = self.game_root
            width, height, pixels = painter.paint(texts, game_h, max(200, game_w - 2 * margin))
            mem, bmp, old, bits = dib(width, height)
            try:
                ctypes.memmove(bits, bytes(pixels), len(pixels))
                screen = user32.GetDC(None)
                where = wt.POINT(game.left + margin, game.bottom - margin - height)     # bottom left of the game window
                ok = user32.UpdateLayeredWindow(hwnd, screen, ctypes.byref(where), ctypes.byref(wt.SIZE(width, height)),
                                                mem, ctypes.byref(wt.POINT(0, 0)), 0,
                                                ctypes.byref(BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)), ULW_ALPHA)
                user32.ReleaseDC(None, screen)
                if not ok:
                    raise OSError("UpdateLayeredWindow failed (%d)" % k32.GetLastError())
            finally:
                free(mem, bmp, old)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_TIMER:
                try:
                    texts = self.queue.tick(time.monotonic())
                    if texts == []:
                        user32.ShowWindow(hwnd, SW_HIDE)
                    elif texts:
                        show(hwnd, texts)
                except Exception as e:           # report once and stop the loop; _run turns the overlay off
                    state["error"] = e
                    user32.PostQuitMessage(0)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        state: Dict[str, Exception] = {}
        proc = WNDPROC(wndproc)                 # kept alive for the life of the loop
        hinst = k32.GetModuleHandleW(None)
        wc = WNDCLASSW(0, proc, 0, 0, hinst, None, None, None, None, "JSRFArchipelagoNotice")
        if not user32.RegisterClassW(ctypes.byref(wc)):
            raise OSError("RegisterClassW failed (%d)" % k32.GetLastError())
        hwnd = user32.CreateWindowExW(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE,
                                      "JSRFArchipelagoNotice", "JSRF item notice", WS_POPUP, 0, 0, 10, 10,
                                      None, None, hinst, None)
        if not hwnd:
            raise OSError("CreateWindowExW failed (%d)" % k32.GetLastError())
        user32.SetTimer(hwnd, 1, TICK_MS, None)
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if "error" in state:
            raise state["error"]
