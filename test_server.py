#!/usr/bin/env python3
"""
VENICE Camera Test Server – root-level reverse proxy
"""

from flask import Flask, send_file, request, Response
import requests
from requests.auth import HTTPDigestAuth

app = Flask(__name__)

# ============================================
# CONFIGURATION - EDIT THESE VALUES
# ============================================
CAMERA_IP = "IP_ADDRESS"
CAMERA_PAGE = "rmt.html"       # main camera page
CAMERA_USERNAME = "admin"
CAMERA_PASSWORD = "PASSWORD"
PORT = 8080                    # 80 is fine too, 8080 avoids admin privileges
# ============================================

session = requests.Session()
session.auth = HTTPDigestAuth(CAMERA_USERNAME, CAMERA_PASSWORD)


@app.route("/ui")
def ui():
    """Serve the local test UI."""
    return send_file("test.html")


@app.route("/", defaults={"path": CAMERA_PAGE}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def proxy(path):
    """
    Reverse proxy everything except /ui to the camera.

    /               -> http://CAMERA_IP/CAMERA_PAGE
    /rmt.cgi?...    -> http://CAMERA_IP/rmt.cgi?...
    /foo/bar.js     -> http://CAMERA_IP/foo/bar.js
    """
    # Prevent accidental recursion if you ever host other stuff
    if path == "ui" or path == "test.html":
        return "Reserved path", 404

    # Build camera URL
    if CAMERA_IP.startswith("http://") or CAMERA_IP.startswith("https://"):
        base = CAMERA_IP.rstrip("/")
    else:
        base = f"http://{CAMERA_IP}"

    target_url = f"{base}/{path.lstrip('/')}"
    print(f"[proxy] {request.method} {request.path} -> {target_url}")

    # Copy headers except ones that must be controlled locally
    excluded = {"host", "content-length", "accept-encoding", "connection"}
    headers = {k: v for k, v in request.headers if k.lower() not in excluded}

    try:
        resp = session.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=request.args,
            data=request.get_data(),
            timeout=10,
            allow_redirects=False,
        )

        excluded_resp = {"content-encoding", "transfer-encoding", "content-length", "connection"}
        response_headers = [
            (k, v)
            for k, v in resp.headers.items()
            if k.lower() not in excluded_resp
        ]

        return Response(resp.content, status=resp.status_code, headers=response_headers)

    except requests.RequestException as e:
        print(f"[proxy error] {e}")
        return f"Error connecting to camera: {e}", 502


if __name__ == "__main__":
    print("=" * 50)
    print("VENICE Camera Test Server (root proxy)")
    print("=" * 50)
    print(f"Camera IP: {CAMERA_IP}")
    print(f"Username: {CAMERA_USERNAME}")
    print(f"Server running at: http://localhost:{PORT}/ui")
    print("Press Ctrl+C to stop")
    print("=" * 50)

    app.run(host="0.0.0.0", port=PORT, debug=True)
