"""A real uvicorn server plus Chromium page for browser tests."""

import socket
import threading
import time
from contextlib import contextmanager

import uvicorn
from playwright.sync_api import sync_playwright


@contextmanager
def live_browser(app, viewport=None):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport=viewport)
            try:
                yield page, f"http://127.0.0.1:{sock.getsockname()[1]}"
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
