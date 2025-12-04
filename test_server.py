#!/usr/bin/env python3
"""
Minimal test server with proxy for VENICE camera testing
"""

from flask import Flask, send_file, request, Response
import requests
from urllib.parse import urljoin, urlparse
import re

app = Flask(__name__)

# ============================================
# CONFIGURATION - EDIT THESE VALUES
# ============================================
CAMERA_IP = "https://en.wikipedia.org"
PORT = 443
# ============================================

@app.route('/')
def index():
    """Serve the test.html file"""
    return send_file('test.html')

@app.route('/proxy/camera')
def proxy_camera():
    """Proxy the camera's web interface"""
    try:
        # Build the camera URL - add http:// if not present
        if CAMERA_IP.startswith('http://') or CAMERA_IP.startswith('https://'):
            camera_url = CAMERA_IP
        else:
            camera_url = f"http://{CAMERA_IP}"
        
        print(f"Fetching: {camera_url}")
        
        # Set a proper User-Agent header
        headers = {
            'User-Agent': 'MultiVeniceTool/1.0 (Camera Control Proxy)'
        }
        response = requests.get(camera_url, timeout=10, headers=headers)
        
        # Get the content
        content = response.content
        content_type = response.headers.get('Content-Type', '')
        
        # If it's HTML, rewrite URLs to go through our proxy
        if 'text/html' in content_type:
            html = content.decode('utf-8', errors='ignore')
            
            # Rewrite relative URLs to absolute ones through our proxy
            html = rewrite_urls(html, camera_url)
            
            content = html.encode('utf-8')
        
        # Return the proxied content
        return Response(content, content_type=content_type)
    
    except requests.RequestException as e:
        return f"Error connecting to camera: {str(e)}", 500

@app.route('/proxy/asset')
def proxy_asset():
    """Proxy static assets (CSS, JS, images) from the camera"""
    asset_path = request.args.get('path', '')
    
    try:
        # Build the base camera URL
        if CAMERA_IP.startswith('http://') or CAMERA_IP.startswith('https://'):
            base_url = CAMERA_IP
        else:
            base_url = f"http://{CAMERA_IP}"
        
        # Construct the full URL to the asset
        asset_url = f"{base_url.rstrip('/')}/{asset_path.lstrip('/')}"
        print(f"Fetching asset: {asset_url}")
        
        # Set a proper User-Agent header
        headers = {
            'User-Agent': 'MultiVeniceTool/1.0 (Camera Control Proxy)'
        }
        response = requests.get(asset_url, timeout=10, headers=headers)
        
        # Return the asset with original content type
        return Response(
            response.content,
            content_type=response.headers.get('Content-Type', 'application/octet-stream')
        )
    
    except requests.RequestException as e:
        return f"Error fetching asset: {str(e)}", 404

def rewrite_urls(html, base_url):
    """Rewrite URLs in HTML to go through our proxy"""
    
    # Rewrite src attributes (images, scripts)
    html = re.sub(
        r'src=(["\'])(?!http|//|data:)([^"\']+)\1',
        lambda m: f'src={m.group(1)}/proxy/asset?path={m.group(2)}{m.group(1)}',
        html
    )
    
    # Rewrite href attributes (stylesheets, links)
    html = re.sub(
        r'href=(["\'])(?!http|//|#|javascript:)([^"\']+)\1',
        lambda m: f'href={m.group(1)}/proxy/asset?path={m.group(2)}{m.group(1)}',
        html
    )
    
    return html

if __name__ == '__main__':
    print("=" * 50)
    print("VENICE Camera Test Server")
    print("=" * 50)
    print(f"Camera IP: {CAMERA_IP}")
    print(f"Server running at: http://localhost:{PORT}")
    print(f"Press Ctrl+C to stop")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=PORT, debug=True)