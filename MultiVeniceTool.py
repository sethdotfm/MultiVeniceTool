from dataclasses import dataclass
from typing import Optional, List

import yaml
from playwright.sync_api import (
    sync_playwright,
    Playwright,
    Browser,
    Page,
    Error,
)
import tkinter as tk
from tkinter import messagebox

CONFIG_PATH = "config.yaml"


@dataclass
class Camera:
    name: str
    ip: str
    username: str
    password: str
    context: Optional[object] = None  # Playwright BrowserContext
    page: Optional[Page] = None
    status_label: Optional[tk.Label] = None

    @property
    def url(self) -> str:
        return f"http://{self.ip}/rmt.html"


class MultiVeniceToolApp:
    def __init__(self, config_path: str = CONFIG_PATH):
        self.config_path = config_path
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.cameras: List[Camera] = []

        # Tkinter UI
        self.root = tk.Tk()
        self.root.title("MultiVeniceTool")
        self.root.resizable(False, False)

        self.cameras_frame = tk.Frame(self.root, padx=10, pady=10)
        self.cameras_frame.pack(fill="both", expand=True)

        self.buttons_frame = tk.Frame(self.root, padx=10, pady=10)
        self.buttons_frame.pack(fill="x", expand=False)

        self._build_buttons()

        # Start Playwright and load cameras
        self._start_playwright()
        self._load_cameras_from_config()
        self._build_camera_rows()
        self._connect_all_cameras()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- Playwright lifecycle ----------

    def _start_playwright(self):
        try:
            self.playwright = sync_playwright().start()
            # Set headless=False if you want to see the browser windows
            self.browser = self.playwright.chromium.launch(headless=True)
        except Exception as e:
            messagebox.showerror("Playwright Error", f"Failed to start Playwright: {e}")
            raise

    def _stop_playwright(self):
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            # We're shutting down anyway
            pass
        finally:
            self.browser = None
            self.playwright = None

    # ---------- Config & camera setup ----------

    def _load_cameras_from_config(self):
        try:
            with open(self.config_path, "r") as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            messagebox.showerror("Config Error", f"Config file not found: {self.config_path}")
            data = {}
        except Exception as e:
            messagebox.showerror("Config Error", f"Failed to read config file: {e}")
            data = {}

        cameras_cfg = data.get("cameras", [])
        self.cameras = []
        for idx, cam_cfg in enumerate(cameras_cfg, start=1):
            try:
                cam = Camera(
                    name=cam_cfg.get("name", f"Camera {idx}"),
                    ip=str(cam_cfg["ip"]),
                    username=str(cam_cfg["username"]),
                    password=str(cam_cfg["password"]),
                )
                self.cameras.append(cam)
            except KeyError as e:
                messagebox.showwarning(
                    "Config Warning",
                    f"Skipping camera entry #{idx} due to missing key: {e}",
                )

    # ---------- UI building ----------

    def _build_camera_rows(self):
        # Clear existing widgets
        for child in self.cameras_frame.winfo_children():
            child.destroy()

        # Header row
        tk.Label(self.cameras_frame, text="Status", width=10, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(self.cameras_frame, text="Name", width=20, anchor="w").grid(
            row=0, column=1, sticky="w"
        )
        tk.Label(self.cameras_frame, text="IP", width=20, anchor="w").grid(
            row=0, column=2, sticky="w"
        )

        # Camera rows
        for row_idx, cam in enumerate(self.cameras, start=1):
            status_label = tk.Label(
                self.cameras_frame, text="OFFLINE", bg="red", fg="white", width=10
            )
            status_label.grid(row=row_idx, column=0, padx=5, pady=2, sticky="w")

            name_label = tk.Label(self.cameras_frame, text=cam.name, width=20, anchor="w")
            name_label.grid(row=row_idx, column=1, padx=5, pady=2, sticky="w")

            ip_label = tk.Label(self.cameras_frame, text=cam.ip, width=20, anchor="w")
            ip_label.grid(row=row_idx, column=2, padx=5, pady=2, sticky="w")

            cam.status_label = status_label

    def _build_buttons(self):
        reload_btn = tk.Button(
            self.buttons_frame, text="Reload Cameras", command=self.reload_cameras
        )
        reload_btn.pack(side="left", padx=5)

        start_btn = tk.Button(
            self.buttons_frame, text="Start Recording", command=self.start_recording
        )
        start_btn.pack(side="left", padx=5)

        quit_btn = tk.Button(
            self.buttons_frame, text="End Application", command=self.on_close
        )
        quit_btn.pack(side="right", padx=5)

    # ---------- Camera connectivity ----------

    def _connect_camera(self, cam: Camera):
        # Close any existing context for this camera
        try:
            if cam.context:
                cam.context.close()
        except Exception:
            pass
        cam.context = None
        cam.page = None

        if not self.browser:
            return

        try:
            context = self.browser.new_context(
                http_credentials={
                    "username": cam.username,
                    "password": cam.password,
                }
            )
            page = context.new_page()
            page.goto(cam.url, wait_until="domcontentloaded", timeout=5000)
            cam.context = context
            cam.page = page
            self._set_camera_status(cam, online=True)
        except Error:
            self._set_camera_status(cam, online=False)
        except Exception:
            self._set_camera_status(cam, online=False)

    def _connect_all_cameras(self):
        for cam in self.cameras:
            self._connect_camera(cam)

    def _set_camera_status(self, cam: Camera, online: bool):
        if not cam.status_label:
            return
        if online:
            cam.status_label.config(text="ONLINE", bg="green")
        else:
            cam.status_label.config(text="OFFLINE", bg="red")

    # ---------- Button callbacks ----------

    def reload_cameras(self):
        """
        Reload cameras from config and reconnect.
        """
        self._load_cameras_from_config()
        self._build_camera_rows()
        self._connect_all_cameras()

    def start_recording(self):
        """
        For each online camera, run:
        document.getElementById("BUTTON_REC_BUTTON").click()
        """
        if not self.cameras:
            messagebox.showwarning("No Cameras", "No cameras configured.")
            return

        failures = []

        for cam in self.cameras:
            if not cam.page:
                failures.append(cam.name)
                self._set_camera_status(cam, online=False)
                continue

            try:
                cam.page.evaluate(
                    'document.getElementById("BUTTON_REC_BUTTON").click()'
                )
            except Error:
                failures.append(cam.name)
                self._set_camera_status(cam, online=False)
            except Exception:
                failures.append(cam.name)
                self._set_camera_status(cam, online=False)

        if failures:
            messagebox.showwarning(
                "Recording Issues",
                "Failed to trigger recording on: " + ", ".join(failures),
            )

    # ---------- Shutdown ----------

    def on_close(self):
        self._stop_playwright()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    app = MultiVeniceToolApp()
    app.run()


if __name__ == "__main__":
    main()
