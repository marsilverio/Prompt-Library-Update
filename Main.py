"""
Prompt Library Pro - desktop launcher.

Boots a local Waitress server hosting the Flask app, then opens it in a
pywebview window. All errors are written to error.log next to the .exe.
"""

import logging
import os
import socket
import sys
import threading
import time
import traceback

import webview

from app import app, get_data_dir, init_db, start_auto_backup


# ERROR LOGGING
# Writes to error.log next to the .exe (frozen) or Main.py (dev).
if getattr(sys, 'frozen', False):
    _log_dir = os.path.dirname(sys.executable)
else:
    _log_dir = os.path.dirname(os.path.abspath(__file__))

_LOG_LEVEL = logging.WARNING   # Capture WARNING + ERROR + CRITICAL
_LOG_FORMAT = '%(asctime)s %(levelname)s %(message)s'


def _init_logging(primary_dir):
    """Attach a file log, trying primary_dir then the data dir. Never raises."""
    candidates = [primary_dir]
    try:
        candidates.append(get_data_dir())
    except OSError:
        pass
    for candidate in candidates:
        if not candidate:
            continue
        try:
            os.makedirs(candidate, exist_ok=True)
            path = os.path.join(candidate, 'error.log')
            logging.basicConfig(filename=path, level=_LOG_LEVEL, format=_LOG_FORMAT)
            return path
        except OSError:
            continue
    # Last resort: run without a log file rather than refuse to start.
    logging.basicConfig(level=_LOG_LEVEL, format=_LOG_FORMAT)
    return None


_log_path = _init_logging(_log_dir)


class Api:
    """Bridge exposed to the frontend as window.pywebview.api.* -- native OS
    dialogs the browser sandbox can't open on its own."""

    def pick_folder(self):
        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            return result[0]
        return None


HOST = '127.0.0.1'
BIND_HOST = '0.0.0.0'  # LAN reachable; app.py gate blocks non-local unless Phone Share is on
PORT = 5757  # fixed so the webview origin (and its localStorage) is stable; 5000 is taken by AirPlay on macOS

_server_crashed = threading.Event()


def _find_free_port(preferred=PORT):
    """Return the preferred port if free, otherwise an OS-assigned free one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def start_server(port):
    """Run the Flask app under Waitress (production-grade WSGI)."""
    try:
        init_db()
        start_auto_backup()
        try:
            from waitress import serve
            serve(app, host=BIND_HOST, port=port, threads=8, _quiet=True)
        except ImportError:
            # Fallback to the dev server if waitress is missing for any reason
            app.run(host=BIND_HOST, port=port, debug=False, use_reloader=False)
    except Exception:
        logging.error(traceback.format_exc())
        _server_crashed.set()


def wait_for_server(host, port, timeout=30):
    """Block until the server accepts connections, or raise on timeout."""
    start = time.time()
    while time.time() - start < timeout:
        if _server_crashed.is_set():
            raise RuntimeError("Server thread crashed - see error.log")
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.1)
    raise RuntimeError(f"Server did not start within {timeout} seconds.")


if __name__ == '__main__':
    port = _find_free_port(PORT)

    # Check if a .plp file was passed as an argument (OS file association double-click)
    pending_plp = None
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith('.plp'):
        pending_plp = os.path.abspath(sys.argv[1])

    # Start server in background thread
    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()

    # Wait until it's actually accepting connections
    try:
        wait_for_server(HOST, port)
    except RuntimeError as e:
        logging.error(str(e))
        webview.create_window(
            'Prompt Library - Error',
            html=(
                '<h2 style="font-family:sans-serif;padding:40px;color:#ef4444">'
                'Failed to start the local server.<br>'
                'Check <code>error.log</code> next to the application.</h2>'
            ),
            width=600, height=240,
        )
        webview.start()  # Allow user to see the error message
        sys.exit(1)

    # If a .plp was passed, write the flag file so the frontend can pick it up
    if pending_plp and os.path.isfile(pending_plp):
        try:
            import urllib.request, urllib.error
            req = urllib.request.Request(
                f'http://{HOST}:{port}/api/pending-import',
                data=__import__('json').dumps({'path': pending_plp}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass  # Non-fatal — user can import manually

    # Open the desktop window
    webview.create_window(
        'Prompt Library Pro',
        f'http://{HOST}:{port}/',
        width=1400,
        height=900,
        resizable=True,
        maximized=True,
        min_size=(900, 600),
        js_api=Api(),
    )
    webview.start() # enables the devtools console with error logging

