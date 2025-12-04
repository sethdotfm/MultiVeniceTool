#!/usr/bin/env python3
"""
MultiVenice Kiosk Controller (embedded-ish browser windows)

- Opens up to three Sony VENICE 2 web UIs with Playwright (Chromium).
- Creates a fullscreen Tkinter window with a 2×2 grid:
    [ VENICE A ] [ VENICE B ]
    [ VENICE C ] [ Control  ]
- Uses Win32 SetParent to reparent the Chromium windows into Tk frames,
  giving a "single window" kiosk-style UI.
- START RECORD button runs:
      document.getElementById("BUTTON_REC_BUTTON").click();
  in each camera browser.

Requirements:
    pip install playwright
    python -m playwright install chromium

Platform:
    Windows only (uses user32.dll).
"""

import ctypes
from ctypes import wintypes
import tkinter as tk

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --------------------------------------------------------------------
# CONFIG – EDIT THESE
# --------------------------------------------------------------------

# While testing, you can limit to only the camera that is actually on, e.g.:
# CAMERAS = [
#     {"label": "VENICE C", "url": "http://172.17.80.103/rmt.html"},
# ]
CAMERAS = [
    {"label": "VENICE A", "url": "http://172.17.80.101/rmt.html"},
    {"label": "VENICE B", "url": "http://172.17.80.102/rmt.html"},
    {"label": "VENICE C", "url": "http://172.17.80.103/rmt.html"},
]

# HTTP auth for the VENICE web UI (if used)
HTTP_USERNAME = "admin"
HTTP_PASSWORD = "PASSWORD"

# DOM element IDs inside the VENICE web UI
REC_BUTTON_ID = "BUTTON_REC_BUTTON"     # known working ID
STOP_BUTTON_ID = None                   # set once you know it, e.g. "BUTTON_REC_STOP"

# Title of the control window (used for embedding & identification)
CONTROL_WINDOW_TITLE = "MultiVenice Control"

# How long to wait after opening all windows before embedding (seconds)
EMBED_DELAY_SECONDS = 2.0

# --------------------------------------------------------------------
# Win32 helpers
# --------------------------------------------------------------------

user32 = ctypes.windll.user32
GetSystemMetrics = user32.GetSystemMetrics
MoveWindow = user32.MoveWindow
EnumWindows = user32.EnumWindows
IsWindowVisible = user32.IsWindowVisible
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
SetParent = user32.SetParent

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def find_windows_by_title_substrings(substrings):
    """
    Find top-level visible windows whose titles contain any of the given substrings.
    Returns a dict: {substring: hwnd or None}
    """
    result = {s: None for s in substrings}

    def _callback(hwnd, lparam):
        if not IsWindowVisible(hwnd):
            return True
        length = GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value
        for s in substrings:
            if s and s in title:
                result[s] = hwnd
        return True

    EnumWindows(EnumWindowsProc(_callback), 0)
    return result


# --------------------------------------------------------------------
# Playwright controller
# --------------------------------------------------------------------

class VeniceController:
    """
    Manages Chromium windows and JS execution for each camera.
    """

    def __init__(self):
        self.playwright = None
        self.browsers = []    # one browser per camera (for those that succeed)
        self.pages = []       # list of Page objects (matching cam_infos)
        self.cam_infos = []   # list of camera dicts that actually opened

    def start(self):
        """
        Start Playwright, open each camera UI, and set up per-camera window titles.
        Skips cameras that fail to load instead of crashing.
        """
        self.playwright = sync_playwright().start()

        for cam in CAMERAS:
            label = cam["label"]
            url = cam["url"]
            print(f"Opening {label} at {url}...")

            browser = self.playwright.chromium.launch(headless=False)
            context = browser.new_context(
                http_credentials={"username": HTTP_USERNAME, "password": HTTP_PASSWORD}
            )
            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"{label}: FAILED to open ({e}). Skipping this camera.")
                browser.close()
                continue

            # Force a unique window title for embedding
            try:
                page.evaluate(f"document.title = {label!r};")
            except Exception as e:
                print(f"{label}: Could not set title ({e}), continuing anyway.")

            # Optional: wait for REC button as sanity check
            try:
                page.wait_for_selector(f"#{REC_BUTTON_ID}", timeout=15000)
            except PlaywrightTimeoutError:
                print(f"{label}: REC button not found in time; JS click may still work.")

            self.browsers.append(browser)
            self.pages.append(page)
            self.cam_infos.append(cam)

        if not self.pages:
            print("No cameras could be opened. Exiting.")
            self.playwright.stop()
            self.playwright = None
            raise SystemExit(1)

        print(f"{len(self.pages)} camera UI(s) opened successfully.")

    def stop(self):
        """
        Close all browsers and stop Playwright.
        """
        if self.playwright is None:
            return
        for browser in self.browsers:
            try:
                browser.close()
            except Exception:
                pass
        self.browsers.clear()
        self.pages.clear()
        self.cam_infos.clear()
        self.playwright.stop()
        self.playwright = None

    def click_button_all(self, element_id: str):
        """
        Execute a document.getElementById(...).click() on all open camera pages.

        NOTE: must be called from the same thread that created Playwright
        (Tk main thread in this script).
        """
        if self.playwright is None:
            print("Playwright not running.")
            return

        js = f"""
            (function() {{
                var el = document.getElementById({element_id!r});
                if (!el) {{
                    return "Element not found: " + {element_id!r};
                }}
                el.click();
                return "Clicked " + {element_id!r};
            }})()
        """

        for cam, page in zip(self.cam_infos, self.pages):
            label = cam["label"]
            try:
                result = page.evaluate(js)
                print(f"{label}: {result}")
            except Exception as e:
                print(f"{label}: ERROR executing JS: {e}")


# --------------------------------------------------------------------
# Tkinter kiosk UI with embedded browser windows
# --------------------------------------------------------------------

class ControlApp:
    """
    Fullscreen Tk window with:
      - 3 frames for cameras (top-left, top-right, bottom-left)
      - 1 frame for control buttons (bottom-right)
    and embedded Chromium windows via SetParent.
    """

    def __init__(self, controller: VeniceController):
        self.controller = controller
        self.root = tk.Tk()
        self.root.title(CONTROL_WINDOW_TITLE)

        # Fullscreen / kiosk-ish
        # For a maximized window instead, use: self.root.state("zoomed")
        self.root.attributes("-fullscreen", True)

        self.cam_frames = {}    # label -> frame
        self.cam_child_hwnds = {}  # label -> browser window HWND

        self.control_frame = None

        self.build_layout()

        # After a short delay, embed all browser windows into the frames
        self.root.after(int(EMBED_DELAY_SECONDS * 1000), self.embed_all_browsers)

        # Ensure browsers are closed when UI exits
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_layout(self):
        # 2×2 grid layout
        self.root.rowconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)

        # Camera frames (we'll only create as many as we have CAMERAS)
        # Top-left, top-right, bottom-left
        positions = [(0, 0), (0, 1), (1, 0)]

        for idx, cam in enumerate(CAMERAS):
            if idx >= 3:
                break
            r, c = positions[idx]
            f = tk.Frame(self.root, bg="#000000")
            f.grid(row=r, column=c, sticky="nsew")
            self.cam_frames[cam["label"]] = f

            # When the frame resizes, resize the embedded browser window
            f.bind("<Configure>", self.make_resize_handler(cam["label"]))

        # Control frame: bottom-right
        self.control_frame = tk.Frame(self.root, bg="#222222")
        self.control_frame.grid(row=1, column=1, sticky="nsew")

        self.build_control_ui(self.control_frame)

    def build_control_ui(self, frame):
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        inner = tk.Frame(frame, bg="#222222")
        inner.place(relx=0.5, rely=0.5, anchor="center")

        label = tk.Label(
            inner,
            text="MultiVenice Control",
            fg="#ffffff",
            bg="#222222",
            font=("Segoe UI", 18, "bold"),
        )
        label.pack(pady=(0, 20))

        btn_start = tk.Button(
            inner,
            text="START RECORD",
            command=self.on_start,
            bg="#cc3333",
            fg="white",
            activebackground="#ff4444",
            activeforeground="white",
            font=("Segoe UI", 16, "bold"),
            width=18,
            height=2,
        )
        btn_start.pack(pady=10)

        if STOP_BUTTON_ID:
            btn_stop = tk.Button(
                inner,
                text="STOP RECORD",
                command=self.on_stop,
                bg="#339933",
                fg="white",
                activebackground="#44cc44",
                activeforeground="white",
                font=("Segoe UI", 14, "bold"),
                width=18,
                height=1,
            )
            btn_stop.pack(pady=10)
        else:
            info = tk.Label(
                inner,
                text="(Set STOP_BUTTON_ID in script to enable STOP)",
                fg="#aaaaaa",
                bg="#222222",
                font=("Segoe UI", 10),
            )
            info.pack(pady=8)

        # Escape to exit fullscreen quickly
        self.root.bind("<Escape>", lambda e: self.on_close())

    # --- embedding ---

    def embed_all_browsers(self):
        """
        Find each Chromium window by title, then SetParent it into the
        corresponding Tk frame, and size it to fill the frame.
        """
        substrings = [cam["label"] for cam in CAMERAS]
        handles = find_windows_by_title_substrings(substrings)

        for cam in CAMERAS:
            label = cam["label"]
            hwnd = handles.get(label)
            frame = self.cam_frames.get(label)

            if not frame:
                continue
            if not hwnd:
                print(f"{label}: No window handle found to embed.")
                continue

            parent_hwnd = frame.winfo_id()
            print(f"{label}: Embedding window {hwnd} into frame {parent_hwnd}...")
            SetParent(hwnd, parent_hwnd)
            self.cam_child_hwnds[label] = hwnd

            # Initial resize to frame
            self.resize_child_to_frame(label)

    def make_resize_handler(self, label):
        def handler(event):
            self.resize_child_to_frame(label)
        return handler

    def resize_child_to_frame(self, label):
        hwnd = self.cam_child_hwnds.get(label)
        frame = self.cam_frames.get(label)
        if not hwnd or not frame:
            return
        frame.update_idletasks()
        w = frame.winfo_width()
        h = frame.winfo_height()
        if w <= 0 or h <= 0:
            return
        MoveWindow(hwnd, 0, 0, w, h, True)

    # --- controls ---

    def on_start(self):
        self.controller.click_button_all(REC_BUTTON_ID)

    def on_stop(self):
        if not STOP_BUTTON_ID:
            return
        self.controller.click_button_all(STOP_BUTTON_ID)

    def on_close(self):
        self.controller.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# --------------------------------------------------------------------
# main
# --------------------------------------------------------------------

def main():
    controller = VeniceController()
    controller.start()

    app = ControlApp(controller)
    app.run()


if __name__ == "__main__":
    main()
