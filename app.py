from flask import Flask, render_template, jsonify, request
import os
import threading
from backend_logic import DiscordManager

# ---------------------------------------------------------------------------
# Flask setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
manager = DiscordManager()

# ---------------------------------------------------------------------------
# Cross-platform file / folder dialogs (tkinter)
# ---------------------------------------------------------------------------

def _open_file_dialog() -> str:
    """Open a native file-picker dialog. Works on Linux, macOS, and Windows."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()           # hide the empty root window
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select a file",
            filetypes=[("All Files", "*.*")],
        )
        root.destroy()
        return path or ""
    except Exception as exc:
        print(f"File dialog error: {exc}")
        return ""


def _open_folder_dialog() -> str:
    """Open a native folder-picker dialog. Works on Linux, macOS, and Windows."""
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
        print(f"Folder dialog error: {exc}")
        return ""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/select_file", methods=["GET"])
def select_file():
    # Dialogs must run on the main thread on some platforms (macOS requires it).
    result: dict = {}
    event = threading.Event()

    def _run():
        result["path"] = _open_file_dialog()
        event.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    event.wait(timeout=30)          # 30-second timeout
    return jsonify({"path": result.get("path", "")})


@app.route("/api/select_folder", methods=["GET"])
def select_folder():
    result: dict = {}
    event = threading.Event()

    def _run():
        result["path"] = _open_folder_dialog()
        event.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    event.wait(timeout=30)
    return jsonify({"path": result.get("path", "")})


@app.route("/api/upload", methods=["POST"])
def upload():
    data = request.json or {}
    file_path = data.get("file_path", "").strip()
    if not file_path:
        return jsonify({"error": "No file path provided"}), 400

    success, msg = manager.split_and_upload(file_path)
    return jsonify({"success": success, "message": msg})


@app.route("/api/scan", methods=["POST"])
def scan():
    success, msg = manager.scan_server()
    return jsonify({"success": success, "message": msg})


@app.route("/api/channels", methods=["GET"])
def get_channels():
    return jsonify({"channels": manager.channels})


@app.route("/api/download", methods=["POST"])
def download():
    data = request.json or {}
    channel = data.get("channel", "").strip()
    save_dir = data.get("save_dir", "").strip()

    if not channel or not save_dir:
        return jsonify({"error": "Missing channel or save directory"}), 400

    success, msg = manager.download_and_merge(channel, save_dir)
    return jsonify({"success": success, "message": msg})


@app.route("/api/logs", methods=["GET"])
def get_logs():
    start_index = int(request.args.get("start", 0))
    new_logs = manager.get_logs(start_index)
    return jsonify({"logs": new_logs, "next_index": start_index + len(new_logs)})


@app.route("/api/status", methods=["GET"])
def get_status():
    return jsonify(manager.get_status())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
