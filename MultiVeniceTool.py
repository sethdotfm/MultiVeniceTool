# main.py - Entry point
"""
MultiVeniceTool - Camera Control Center
"""

from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime
import yaml
from playwright.sync_api import (
    sync_playwright,
    Playwright,
    Browser,
    Page,
    Error,
)
import tkinter as tk
from tkinter import messagebox, scrolledtext

CONFIG_PATH = "config.yaml"


# ============================================================================
# Camera data model
# ============================================================================

@dataclass
class Camera:
    """Represents a Venice camera"""
    name: str
    ip: str
    username: str
    password: str
    zoom: float = 1.0  # Default 100% zoom
    context: Optional[object] = None
    page: Optional[Page] = None
    status_label: Optional[tk.Label] = None

    @property
    def url(self):
        return f"http://{self.ip}/rmt.html"


# ============================================================================
# Configuration handling
# ============================================================================

class ConfigManager:
    """Handles loading and parsing camera configuration"""
    
    @staticmethod
    def load_cameras(config_path):
        """Load cameras from config file. Returns (cameras, errors)"""
        errors = []
        cameras = []
        
        try:
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            errors.append(f"Config file not found: {config_path}")
            return cameras, errors
        except Exception as e:
            errors.append(f"Failed to read config: {e}")
            return cameras, errors

        cameras_cfg = data.get("cameras", [])
        
        for idx, cam_cfg in enumerate(cameras_cfg, start=1):
            try:
                cam = Camera(
                    name=cam_cfg.get("name", f"Camera {idx}"),
                    ip=str(cam_cfg["ip"]),
                    username=str(cam_cfg["username"]),
                    password=str(cam_cfg["password"]),
                    zoom=float(cam_cfg.get("zoom", 1.0)),  # Default 100%
                )
                cameras.append(cam)
            except KeyError as e:
                errors.append(f"Skipping camera #{idx}: missing {e}")
        
        return cameras, errors


# ============================================================================
# Playwright browser control
# ============================================================================

class BrowserManager:
    """Manages Playwright browser lifecycle and camera connections"""
    
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.screen_width = 1920
        self.screen_height = 1080
        self.main_window_positioned = False
    
    def start(self):
        """Start the browser. Returns True on success."""
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=False)
            return True
        except Exception as e:
            messagebox.showerror("Browser Error", f"Failed to start browser: {e}")
            return False
    
    def stop(self):
        """Stop the browser"""
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        finally:
            self.browser = None
            self.playwright = None
    
    def _calculate_window_position(self, camera_index, total_cameras):
        """Calculate window position for a camera in a grid layout"""
        # Calculate grid dimensions - add 1 for main window
        total_windows = total_cameras + 1
        grid_cols = max(2, int(total_windows ** 0.5))
        grid_rows = (total_windows + grid_cols - 1) // grid_cols
        
        # Calculate window dimensions
        window_width = self.screen_width // grid_cols
        window_height = self.screen_height // grid_rows
        
        # Camera windows start after position 0 (main app is at 0,0)
        position = camera_index + 1
        row = position // grid_cols
        col = position % grid_cols
        
        x = col * window_width
        y = row * window_height
        
        return {
            'x': x,
            'y': y,
            'width': window_width,
            'height': window_height
        }
    
    def connect_camera(self, cam, camera_index, total_cameras, refresh=False):
        """Connect to a camera. Returns (success, message)"""
        if not self.browser:
            return False, "Browser not started"
        
        try:
            # Try refresh first if requested and page exists
            if refresh and cam.page and cam.context:
                try:
                    cam.page.reload(wait_until="domcontentloaded", timeout=10000)
                    cam.page.evaluate(f"document.body.style.zoom = '{cam.zoom}'")
                    return True, f"Refreshed {cam.name}"
                except:
                    pass
            
            # Full reconnect
            if cam.context:
                try:
                    cam.context.close()
                except Exception:
                    pass
            
            cam.context = None
            cam.page = None
            
            # Create context - don't set viewport, let it be natural size
            context = self.browser.new_context(
                http_credentials={
                    "username": cam.username,
                    "password": cam.password,
                }
            )
            
            page = context.new_page()
            
            # Calculate and set window position BEFORE loading page
            pos = self._calculate_window_position(camera_index, total_cameras)
            
            # Set window size and position using CDP
            try:
                cdp = page.context.new_cdp_session(page)
                
                # Get window ID first
                windows = cdp.send('Browser.getWindowForTarget')
                window_id = windows.get('windowId', 1)
                
                # Set bounds
                cdp.send('Browser.setWindowBounds', {
                    'windowId': window_id,
                    'bounds': {
                        'left': pos['x'],
                        'top': pos['y'],
                        'width': pos['width'],
                        'height': pos['height'],
                        'windowState': 'normal'
                    }
                })
            except Exception as e:
                # CDP positioning failed, just log it
                pass
            
            page.goto(cam.url, wait_until="domcontentloaded", timeout=10000)
            page.evaluate(f"document.body.style.zoom = '{cam.zoom}'")
            
            cam.context = context
            cam.page = page
            
            # Update screen size from first window
            if not self.main_window_positioned:
                try:
                    screen_info = page.evaluate("""() => ({
                        width: window.screen.availWidth,
                        height: window.screen.availHeight
                    })""")
                    self.screen_width = screen_info['width']
                    self.screen_height = screen_info['height']
                except:
                    pass
            
            return True, f"Connected to {cam.name}"
            
        except Error as e:
            return False, f"Failed to connect to {cam.name}: {str(e)[:80]}"
        except Exception as e:
            return False, f"Error connecting to {cam.name}: {str(e)[:80]}"
    
    def toggle_recording(self, cam):
        """Toggle recording on a camera. Returns (success, message)"""
        if not cam.page:
            return False, f"{cam.name} not connected"
        
        try:
            cam.page.evaluate('document.getElementById("BUTTON_REC_BUTTON").click()')
            return True, f"Toggled recording on {cam.name}"
        except Error as e:
            return False, f"Failed on {cam.name}: {str(e)[:80]}"
        except Exception as e:
            return False, f"Error on {cam.name}: {str(e)[:80]}"
    
    def check_alive(self, cam):
        """Check if camera connection is still alive"""
        if not cam.page:
            return False
        try:
            cam.page.evaluate("1")
            return True
        except:
            return False


# ============================================================================
# UI construction helpers
# ============================================================================

class UIBuilder:
    """Builds UI components"""
    
    COLORS = {
        'bg': '#2b2b2b',
        'fg': '#ffffff',
        'online': '#4CAF50',
        'offline': '#f44336',
        'button_bg': '#3d3d3d',
    }
    
    @staticmethod
    def create_camera_card(parent, cam, on_open_browser):
        """Create a camera status card"""
        card = tk.Frame(parent, bg='#3d3d3d', relief=tk.RAISED, borderwidth=1)
        card.pack(fill="x", padx=5, pady=5)
        
        # Status indicator
        left_frame = tk.Frame(card, bg='#3d3d3d')
        left_frame.pack(side="left", padx=10, pady=10)
        
        status_label = tk.Label(
            left_frame, text="●", font=("Helvetica", 20),
            bg='#3d3d3d', fg=UIBuilder.COLORS['offline']
        )
        status_label.pack()
        cam.status_label = status_label
        
        # Camera info
        info_frame = tk.Frame(card, bg='#3d3d3d')
        info_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        tk.Label(
            info_frame, text=cam.name, font=("Helvetica", 12, "bold"),
            bg='#3d3d3d', fg=UIBuilder.COLORS['fg'], anchor="w"
        ).pack(fill="x")
        
        tk.Label(
            info_frame, text=f"IP: {cam.ip} • Zoom: {int(cam.zoom * 100)}%",
            font=("Helvetica", 9), bg='#3d3d3d', fg='#999999', anchor="w"
        ).pack(fill="x")
        
        # Actions
        actions_frame = tk.Frame(card, bg='#3d3d3d')
        actions_frame.pack(side="right", padx=10, pady=10)
        
        tk.Button(
            actions_frame, text="Open in Browser",
            command=lambda: on_open_browser(cam),
            bg=UIBuilder.COLORS['button_bg'], fg=UIBuilder.COLORS['fg'],
            relief=tk.FLAT, padx=10, pady=5
        ).pack(side="left", padx=2)
        
        return card


# ============================================================================
# Main application
# ============================================================================

class MultiVeniceToolApp:
    """Main application class"""
    
    def __init__(self, config_path=CONFIG_PATH):
        self.config_path = config_path
        self.config_manager = ConfigManager()
        self.browser_manager = BrowserManager()
        self.cameras = []
        
        self._setup_ui()
        self._initialize()
    
    def _setup_ui(self):
        """Create the UI"""
        self.root = tk.Tk()
        self.root.title("MultiVeniceTool")
        self.root.geometry("900x600")
        self.root.resizable(True, True)
        self.root.configure(bg=UIBuilder.COLORS['bg'])
        
        main_container = tk.Frame(self.root, bg=UIBuilder.COLORS['bg'])
        main_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Title bar
        self._create_title_bar(main_container)
        
        # Camera list
        self.cameras_frame = self._create_camera_list(main_container)
        
        # Control buttons
        self._create_buttons(main_container)
        
        # Activity log
        self.log_text = self._create_log(main_container)
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def _create_title_bar(self, parent):
        """Create title bar with status"""
        title_frame = tk.Frame(parent, bg=UIBuilder.COLORS['bg'])
        title_frame.pack(fill="x", pady=(0, 10))
        
        tk.Label(
            title_frame, text="Camera Control Center",
            font=("Helvetica", 18, "bold"),
            bg=UIBuilder.COLORS['bg'], fg=UIBuilder.COLORS['fg']
        ).pack(side="left")
        
        self.status_summary = tk.Label(
            title_frame, text="", font=("Helvetica", 10),
            bg=UIBuilder.COLORS['bg'], fg='#999999'
        )
        self.status_summary.pack(side="right")
    
    def _create_camera_list(self, parent):
        """Create scrollable camera list"""
        list_frame = tk.Frame(parent, bg=UIBuilder.COLORS['bg'])
        list_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        canvas = tk.Canvas(list_frame, bg=UIBuilder.COLORS['bg'], highlightthickness=0)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        cameras_frame = tk.Frame(canvas, bg=UIBuilder.COLORS['bg'])
        
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        canvas_frame = canvas.create_window((0, 0), window=cameras_frame, anchor="nw")
        
        cameras_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_frame, width=e.width))
        
        return cameras_frame
    
    def _create_buttons(self, parent):
        """Create control buttons"""
        buttons_frame = tk.Frame(parent, bg=UIBuilder.COLORS['bg'])
        buttons_frame.pack(fill="x", pady=(0, 10))
        
        # Left buttons
        left = tk.Frame(buttons_frame, bg=UIBuilder.COLORS['bg'])
        left.pack(side="left")
        
        for text, cmd in [("Reload Config", self.reload_cameras),
                          ("Reconnect All", self.reconnect_all)]:
            tk.Button(
                left, text=text, command=cmd,
                bg=UIBuilder.COLORS['button_bg'], fg=UIBuilder.COLORS['fg'],
                relief=tk.FLAT, padx=15, pady=8, font=("Helvetica", 10)
            ).pack(side="left", padx=5)
        
        # Center button
        center = tk.Frame(buttons_frame, bg=UIBuilder.COLORS['bg'])
        center.pack(side="left", expand=True)
        
        tk.Button(
            center, text="Toggle Recording (All)", command=self.toggle_recording,
            bg='#ff9800', fg='white', relief=tk.FLAT,
            padx=20, pady=10, font=("Helvetica", 11, "bold")
        ).pack(padx=5)
        
        # Right button
        right = tk.Frame(buttons_frame, bg=UIBuilder.COLORS['bg'])
        right.pack(side="right")
        
        tk.Button(
            right, text="Exit", command=self.on_close,
            bg='#d32f2f', fg='white', relief=tk.FLAT,
            padx=15, pady=8, font=("Helvetica", 10)
        ).pack(side="right", padx=5)
    
    def _create_log(self, parent):
        """Create activity log"""
        log_frame = tk.LabelFrame(
            parent, text="Activity Log",
            bg=UIBuilder.COLORS['bg'], fg=UIBuilder.COLORS['fg'],
            font=("Helvetica", 10, "bold")
        )
        log_frame.pack(fill="both", expand=False, pady=(10, 0))
        
        log_text = scrolledtext.ScrolledText(
            log_frame, height=8, bg='#1e1e1e', fg='#cccccc',
            font=("Consolas", 9), wrap=tk.WORD
        )
        log_text.pack(fill="both", expand=True, padx=5, pady=5)
        return log_text
    
    def _initialize(self):
        """Initialize the application"""
        self.log("Starting application...")
        
        if not self.browser_manager.start():
            return
        self.log("✓ Browser engine started")
        
        self._load_cameras()
        
        # Position main window at top-left
        self.root.after(100, self._position_main_window)
        self.root.after(200, self._connect_all_cameras)
        self.root.after(30000, self._periodic_status_check)
    
    def _position_main_window(self):
        """Position the main application window at top-left"""
        try:
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            
            # Update browser manager's screen dimensions
            self.browser_manager.screen_width = screen_width
            self.browser_manager.screen_height = screen_height
            
            total_cameras = len(self.cameras)
            total_windows = total_cameras + 1
            grid_cols = max(2, int(total_windows ** 0.5))
            grid_rows = (total_windows + grid_cols - 1) // grid_cols
            
            window_width = screen_width // grid_cols
            window_height = screen_height // grid_rows
            
            self.root.geometry(f"{window_width}x{window_height}+0+0")
            self.browser_manager.main_window_positioned = True
            
            self.log(f"Window grid: {grid_cols}x{grid_rows} ({window_width}x{window_height} each)")
        except Exception as e:
            self.log(f"⚠ Could not position main window: {e}")
    
    def _load_cameras(self):
        """Load cameras from config"""
        cameras, errors = self.config_manager.load_cameras(self.config_path)
        
        if errors:
            for error in errors:
                self.log(f"⚠ {error}")
                messagebox.showwarning("Config Warning", error)
        
        self.cameras = cameras
        self.log(f"✓ Loaded {len(self.cameras)} camera(s)")
        self._rebuild_camera_list()
        self._update_status_summary()
    
    def _rebuild_camera_list(self):
        """Rebuild the camera list UI"""
        for child in self.cameras_frame.winfo_children():
            child.destroy()
        
        for cam in self.cameras:
            UIBuilder.create_camera_card(
                self.cameras_frame, cam, self._open_camera_in_browser
            )
    
    def _connect_all_cameras(self, refresh=False):
        """Connect to all cameras"""
        action = "Refreshing" if refresh else "Connecting to"
        self.log(f"{action} all cameras...")
        
        total_cameras = len(self.cameras)
        
        for idx, cam in enumerate(self.cameras):
            success, message = self.browser_manager.connect_camera(
                cam, idx, total_cameras, refresh
            )
            self.log(f"{'✓' if success else '✗'} {message}")
            self._set_camera_status(cam, success)
            self.root.update()
        
        self._update_status_summary()
        self.log("Connection complete")
    
    def _set_camera_status(self, cam, online):
        """Update camera status indicator"""
        if cam.status_label:
            color = UIBuilder.COLORS['online'] if online else UIBuilder.COLORS['offline']
            cam.status_label.config(fg=color)
    
    def _update_status_summary(self):
        """Update the status summary label"""
        online = sum(1 for c in self.cameras if c.page is not None)
        self.status_summary.config(text=f"{online}/{len(self.cameras)} online")
    
    def _open_camera_in_browser(self, cam):
        """Open camera interface in system browser"""
        import webbrowser
        webbrowser.open(cam.url)
        self.log(f"Opened {cam.name} in browser")
    
    def _periodic_status_check(self):
        """Background status check"""
        for cam in self.cameras:
            if not self.browser_manager.check_alive(cam):
                self._set_camera_status(cam, False)
        self._update_status_summary()
        self.root.after(30000, self._periodic_status_check)
    
    def reload_cameras(self):
        """Reload config and refresh connections"""
        self.log("Reloading configuration...")
        
        old_cameras = {cam.ip: cam for cam in self.cameras}
        self._load_cameras()
        
        for cam in self.cameras:
            if cam.ip in old_cameras:
                old_cam = old_cameras[cam.ip]
                cam.context = old_cam.context
                cam.page = old_cam.page
                if cam.page:
                    self._set_camera_status(cam, True)
        
        for ip, old_cam in old_cameras.items():
            if not any(c.ip == ip for c in self.cameras):
                if old_cam.context:
                    try:
                        old_cam.context.close()
                        self.log(f"Closed {old_cam.name} (removed from config)")
                    except:
                        pass
        
        self._connect_all_cameras(refresh=True)
    
    def reconnect_all(self):
        """Reconnect all cameras"""
        self._connect_all_cameras(refresh=True)
    
    def toggle_recording(self):
        """Toggle recording on all cameras"""
        if not self.cameras:
            messagebox.showwarning("No Cameras", "No cameras configured.")
            return
        
        self.log("Toggling recording on all cameras...")
        failures = []
        
        for cam in self.cameras:
            success, message = self.browser_manager.toggle_recording(cam)
            self.log(f"{'✓' if success else '✗'} {message}")
            
            if not success:
                failures.append(cam.name)
                self._set_camera_status(cam, False)
        
        if failures:
            messagebox.showwarning(
                "Recording Toggle Issues",
                f"Failed to toggle recording on:\n" + "\n".join(failures)
            )
        else:
            messagebox.showinfo("Success", "Recording toggled on all online cameras")
    
    def on_close(self):
        """Shutdown handler"""
        self.log("Shutting down...")
        self.browser_manager.stop()
        self.root.destroy()
    
    def log(self, message):
        """Add message to activity log"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def run(self):
        """Start the application"""
        self.root.mainloop()


# ============================================================================
# Entry point
# ============================================================================

def main():
    app = MultiVeniceToolApp()
    app.run()


if __name__ == "__main__":
    main()