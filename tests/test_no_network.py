"""DocRepo makes no network connections, so no networking module may appear in its code."""
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "docrepo"

BANNED_MODULES = (
    "socket", "ssl", "http", "urllib.request", "ftplib", "smtplib", "poplib", "imaplib", "nntplib",
    "telnetlib", "xmlrpc", "socketserver", "webbrowser", "requests", "httpx", "aiohttp", "urllib3",
    "websocket", "websockets", "paramiko", "win32inet", "PySide6.QtNetwork", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
)
# Windows network libraries and COM objects that could be reached through ctypes or win32com.
BANNED_TEXT = ("wininet", "winhttp", "ws2_32", "xmlhttp")


def banned_uses(source: str) -> list[str]:
    """The networking modules and libraries that ``source`` uses."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        else:
            continue
        found += [n for n in names if any(n == b or n.startswith(b + ".") for b in BANNED_MODULES)]
    lowered = source.lower()
    return found + [t for t in BANNED_TEXT if t in lowered]


def test_docrepo_uses_no_networking_modules():
    files = sorted(PACKAGE.rglob("*.py"))
    assert files, "found no source files to scan"
    problems = {str(f.relative_to(PACKAGE.parent)): banned_uses(f.read_text(encoding="utf-8")) for f in files}
    assert {name: uses for name, uses in problems.items() if uses} == {}


def test_the_scan_catches_network_code():
    sample = (
        "import socket\n"
        "from urllib import request\n"
        "from PySide6 import QtNetwork\n"
        "import requests.adapters\n"
        "x = 'WinHttp.WinHttpRequest.5.1'\n"
    )
    assert {"socket", "urllib.request", "PySide6.QtNetwork", "requests.adapters", "winhttp"} <= set(banned_uses(sample))


def test_the_scan_allows_harmless_neighbours():
    assert banned_uses("import urllib.parse\nfrom PySide6 import QtWidgets\n") == []
