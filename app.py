from flask import Flask, render_template, jsonify, request, send_from_directory
import os
import threading
from backend_logic import DiscordManager
from werkzeug.utils import secure_filename
import logging
from functools import wraps

# ---------------------------------------------------------------------------
# Flask setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max for API requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Discord Manager (will raise ValueError if .env is missing)
try:
    manager = DiscordManager()
    logger.info("Discord Manager initialized successfully.")
except ValueError as e:
    logger.error(f"Failed to initialize Discord Manager: {e}")
    manager = None


# ---------------------------------------------------------------------------
# Security decorators
# ---------------------------------------------------------------------------

def check_env_imported:
    """Decorator to ensure required environment variables are set."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if manager is None:
                return jsonify({"error": "DISCORD_TOKEN or DISCORD_SERVER_ID not configured."}), 500
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ---------------------------------------------------------------------------
# Cross-platform file / folder dialogs (tkinter fallback)
# ---------------------------------------------------------------------------

def _open_file_dialog() -> str:
    """Open a native file-picker dialog."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()  # hide the empty root window
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select a file",
            filetypes=[("All Files", "*.*")],
        )
        root.destroy()
        return path or ""
    except Exception as exc:
        logger.error(f"File dialog error: {exc}")
        return ""


def _open_folder_dialog() -> str:
    """Open a native folder-picker dialog."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Select a folder")
        root.destroy()
        return path or ""
    except Exception as exc:
        logger.error(f"Folder dialog error: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _sanitize_path(path: str) -> tuple[bool, str]:
    """Sanitize and validate a file path."""
    if not path:
        return False, "Path cannot be empty."
    
    # Ensure path is absolute
    path = os.path.abspath(path)
    
    # Check if path exists (for uploads)
    if not os.path.exists(path):
        return False, f"Path does not exist: {path}"
    
    # Check if path is a file (for uploads)
    if not os.path.isfile(path):
        return False, f"Path is not a file: {path}"
    
    return True, path


def _sanitize_directory(path: str) -> tuple[bool, str]:
    """Sanitize and validate a directory path."""
    if not path:
        return False, "Directory cannot be empty."
    
    # Ensure path is absolute
    path = os.path.abspath(path)
    
    # Check if path exists
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            return False, f"Failed to create directory: {e}"
    elif not os.path.isdir(path):
        return False, f"Path is not a directory: {path}"
    
    return True, path


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/select_file", methods=["GET"])
def select_file():
    """Open a file picker dialog and return the selected path."""
    result: dict = {}
    event = threading.Event()
    
    def _run():
        result["path"] = _open_file_dialog()
        event.set()
    
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    event.wait(timeout=30)  # 30-second timeout
    
    return jsonify({"path": result.get("path", "")})


@app.route("/api/select_folder", methods=["GET"])
def select_folder():
    """Open a folder picker dialog and return the selected path."""
    result: dict = {}
    event = threading.Event()
    
    def _run():
        result["path"] = _open_folder_dialog()
        event.set()
    
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    event.wait(timeout=30)  # 30-second timeout
    
    return jsonify({"path": result.get("path", "")})


@app.route("/api/upload", methods=["POST"])
@check_env_imported
ndef upload():
    """Start a file upload to Discord."""
    data = request.json or {}
    file_path = data.get("file_path", "").strip()
    
    # Validate path
    is_valid, message = _sanitize_path(file_path)
    if not is_valid:
        return jsonify({"success": False, "message": message}), 400
    
    success, msg = manager.split_and_upload(file_path)
    return jsonify({"success": success, "message": msg})


@app.route("/api/scan", methods=["POST"])
@check_env_imported
def scan():
    """Scan Discord server for channels."""
    success, msg = manager.scan_server()
    return jsonify({"success": success, "message": msg})


@app.route("/api/channels", methods=["GET"])
@check_env_imported
def get_channels():
    """Get list of Discord channels."""
    return jsonify({"channels": manager.channels})


@app.route("/api/download", methods=["POST"])
@check_env_imported
def download():
    """Download and merge files from a Discord channel."""
    data = request.json or {}
    channel = data.get("channel", "").strip()
    save_dir = data.get("save_dir", "").strip()
    
    if not channel:
        return jsonify({"error": "Channel name is required"}), 400
    
    if not save_dir:
        return jsonify({"error": "Save directory is required"}), 400
    
    # Validate directory
    is_valid, message = _sanitize_directory(save_dir)
    if not is_valid:
        return jsonify({"success": False, "message": message}), 400
    
    success, msg = manager.download_and_merge(channel, save_dir)
    return jsonify({"success": success, "message": msg})


@app.route("/api/logs", methods=["GET"])
@check_env_imported
def get_logs():
    """Get logs from Discord operations."""
    start_index = int(request.args.get("start", 0))
    new_logs = manager.get_logs(start_index)
    return jsonify({"logs": new_logs, "next_index": start_index + len(new_logs)})


@app.route("/api/status", methods=["GET"])
@check_env_imported
def get_status():
    """Get current status (speed, progress, busy)."""
    return jsonify(manager.get_status())


@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "ok", "manager_initialized": manager is not None})


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad request", "message": str(error)}), 400


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"error": "Method not allowed"}), 405


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return jsonify({"error": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
        use_reloader=False,
        host="0.0.0.0",
        port=int(os.environ.get("FLASK_PORT", 5000))
    )
