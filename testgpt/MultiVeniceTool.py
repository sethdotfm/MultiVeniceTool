#!/usr/bin/env python3
"""
MultiVeniceTool – simple multi-camera control without DOM-clicking

- Shows each camera GUI in an iframe (monitoring only)
- Sends HTTP requests directly to camera CGI/API for control
"""

import os
import re
import time
import logging

from flask import Flask, jsonify, request, send_from_directory
import yaml
import requests
from requests.auth import HTTPDigestAuth, HTTPBasicAuth

# -----------------------------------------------------------------------------
# Flask app
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder="static")

log = logging.getLogger("MultiVeniceTool")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
CONFIG = {}
CAMERAS_BY_ID = {}
BUTTONS_BY_ID = {}
PORT = 8080


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item"


# -----------------------------------------------------------------------------
# Config loading / parsing
# -----------------------------------------------------------------------------
def load_config():
    global CONFIG, CAMERAS_BY_ID, BUTTONS_BY_ID, PORT

    if not os.path.exists(CONFIG_PATH):
        raise RuntimeError(f"config.yaml not found at {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    settings = raw.get("settings", {}) or {}
    PORT = int(settings.get("port", 8080))
    command_delay_ms = int(settings.get("command_delay_ms", 0))

    global_auth = (settings.get("auth") or {})
    global_auth_type = (global_auth.get("type") or "digest").lower()
    global_user = global_auth.get("username")
    global_pass = global_auth.get("password")

    # Cameras
    cameras = []
    CAMERAS_BY_ID = {}

    for cam in raw.get("cameras", []):
        name = cam.get("name")
        if not name:
            continue

        cid = cam.get("id") or slugify(name)
        url = (cam.get("url") or "").rstrip("/")
        if not url:
            continue

        gui_path = cam.get("gui_path") or "/"
        if not gui_path.startswith("/"):
            gui_path = "/" + gui_path

        cam_auth = cam.get("auth") or {}
        auth_type = (cam_auth.get("type") or global_auth_type).lower()
        username = cam_auth.get("username", global_user)
        password = cam_auth.get("password", global_pass)

        cameras.append(
            {
                "id": cid,
                "name": name,
                "url": url,
                "gui_path": gui_path,
                "auth_type": auth_type,
                "username": username,
                "password": password,
            }
        )
        CAMERAS_BY_ID[cid] = cameras[-1]

    # Buttons
    buttons = []
    BUTTONS_BY_ID = {}

    for btn in raw.get("buttons", []):
        label = btn.get("label")
        if not label:
            continue

        bid = btn.get("id") or slugify(label)
        color = btn.get("color")
        targets = btn.get("targets", "all")
        req_cfg = btn.get("request") or {}

        # Normalize targets
        if isinstance(targets, str):
            if targets.lower() == "all":
                targets_normalized = "all"
            else:
                targets_normalized = [targets]
        else:
            targets_normalized = list(targets)

        button = {
            "id": bid,
            "label": label,
            "color": color,
            "targets": targets_normalized,
            "request": {
                "method": (req_cfg.get("method") or "GET").upper(),
                "path": req_cfg.get("path") or "/",
                "params": req_cfg.get("params") or {},
                "data": req_cfg.get("data") or req_cfg.get("body") or None,
            },
        }

        buttons.append(button)
        BUTTONS_BY_ID[bid] = button

    CONFIG = {
        "settings": {
            "port": PORT,
            "command_delay_ms": command_delay_ms,
        },
        "cameras": cameras,
        "buttons": buttons,
    }

    log.info("Config loaded: %d cameras, %d buttons", len(cameras), len(buttons))


def build_auth(cam):
    user = cam.get("username")
    password = cam.get("password")
    if not user or not password:
        return None

    auth_type = (cam.get("auth_type") or "digest").lower()
    if auth_type == "basic":
        return HTTPBasicAuth(user, password)
    return HTTPDigestAuth(user, password)


def send_camera_request(cam, req_cfg, timeout=3.0):
    """
    Send the configured request to a single camera.
    Returns a dict with status.
    """
    base_url = cam["url"]
    path = req_cfg.get("path") or "/"
    if not path.startswith("/"):
        path = "/" + path
    url = base_url + path

    method = req_cfg.get("method", "GET").upper()
    params = req_cfg.get("params") or {}
    data = req_cfg.get("data")
    auth = build_auth(cam)

    try:
        resp = requests.request(
            method=method,
            url=url,
            params=params,
            data=data,
            auth=auth,
            timeout=timeout,
        )
        return {
            "camera_id": cam["id"],
            "camera_name": cam["name"],
            "ok": resp.ok,
            "status_code": resp.status_code,
            "error": None if resp.ok else resp.text[:200],
        }
    except Exception as e:
        return {
            "camera_id": cam["id"],
            "camera_name": cam["name"],
            "ok": False,
            "status_code": None,
            "error": str(e),
        }


def resolve_button_targets(button, requested_ids):
    """
    Determine which cameras this button should hit, based on config + caller request.
    """
    if button["targets"] == "all":
        allowed_ids = set(CAMERAS_BY_ID.keys())
    else:
        allowed_ids = set()
        # Targets specified as camera names or IDs
        for t in button["targets"]:
            t_lower = str(t).lower()
            for cam in CONFIG["cameras"]:
                if cam["id"].lower() == t_lower or cam["name"].lower() == t_lower:
                    allowed_ids.add(cam["id"])

    if requested_ids:
        requested_ids = set(requested_ids)
        target_ids = list(allowed_ids & requested_ids)
    else:
        target_ids = list(allowed_ids)

    return [CAMERAS_BY_ID[cid] for cid in target_ids]


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    # Serve front-end
    return send_from_directory(app.static_folder, "index.html")


@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory(app.static_folder, path)


@app.route("/api/config")
def api_config():
    """
    Return a trimmed config for the front-end (no passwords).
    """
    cameras_public = []
    for cam in CONFIG["cameras"]:
        gui_url = cam["url"] + cam["gui_path"]
        cameras_public.append(
            {
                "id": cam["id"],
                "name": cam["name"],
                "gui_url": gui_url,
            }
        )

    buttons_public = []
    for btn in CONFIG["buttons"]:
        buttons_public.append(
            {
                "id": btn["id"],
                "label": btn["label"],
                "color": btn.get("color"),
                "targets": btn["targets"],
            }
        )

    return jsonify(
        {
            "settings": CONFIG["settings"],
            "cameras": cameras_public,
            "buttons": buttons_public,
        }
    )


@app.route("/api/run_button", methods=["POST"])
def api_run_button():
    """
    Execute a button's configured request against target cameras.
    Body JSON:
    {
      "button_id": "rec_start",
      "target_ids": ["camera-a-id", "camera-b-id"]   # from enabled checkboxes
    }
    """
    data = request.get_json(force=True, silent=True) or {}
    button_id = data.get("button_id")
    target_ids = data.get("target_ids") or []

    if not button_id or button_id not in BUTTONS_BY_ID:
        return jsonify({"ok": False, "error": "Unknown button_id"}), 400

    button = BUTTONS_BY_ID[button_id]
    cmd_cfg = button["request"]
    command_delay_ms = CONFIG["settings"].get("command_delay_ms", 0) or 0

    targets = resolve_button_targets(button, target_ids)
    if not targets:
        return jsonify({"ok": False, "error": "No target cameras for this button"}), 400

    results = []
    for idx, cam in enumerate(targets):
        if idx > 0 and command_delay_ms > 0:
            time.sleep(command_delay_ms / 1000.0)

        log.info("Running %s on %s (%s)", button_id, cam["name"], cam["url"])
        res = send_camera_request(cam, cmd_cfg)
        results.append(res)

    all_ok = all(r["ok"] for r in results)
    return jsonify({"ok": all_ok, "button_id": button_id, "results": results})


@app.route("/api/reload_config", methods=["POST"])
def api_reload_config():
    """
    Hot-reload config.yaml without restarting.
    """
    try:
        load_config()
        return jsonify({"ok": True})
    except Exception as e:
        log.exception("Error reloading config")
        return jsonify({"ok": False, "error": str(e)}), 500


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    load_config()
    log.info("Starting MultiVeniceTool on port %d", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=True)
