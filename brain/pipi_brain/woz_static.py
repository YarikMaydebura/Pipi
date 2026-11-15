"""Static files for the WoZ server: the built web app in ``web/dist`` (``npm run build``).

The WoZ server answers plain HTTP GET requests with these files, so on study/demo day only the
brain has to run: the panel (``/woz/``) and the fake robot (``/fake-robot/``) come from here.

Safety:
- Only files inside ``web/dist`` are served (no ``..`` tricks, no symlinks out of the folder).
- The pages contain no secrets; the WebSocket behind them is what needs the token.
- ``Referrer-Policy: no-referrer`` keeps the ``?token=`` in the page URL from leaking to any
  other site; a Content-Security-Policy only allows our own scripts.
"""

from __future__ import annotations

import email.utils
import http
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from websockets.datastructures import Headers
from websockets.http11 import Response

# Explicit types: Windows sometimes maps .js to text/plain in its registry, which breaks
# module scripts, so we do not rely on the ``mimetypes`` module.
CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".wasm": "application/wasm",
}
DEFAULT_CONTENT_TYPE = "application/octet-stream"

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' data: https://fonts.gstatic.com",
        "img-src 'self' data: blob:",
        "media-src 'self' data: blob:",
        "worker-src 'self' blob:",
        "connect-src 'self' ws: wss:",  # panel -> WoZ socket, fake robot -> body socket
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
    ]
)
SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy", CONTENT_SECURITY_POLICY),
)
HASHED_ASSET_PREFIX = "/assets/"  # Vite puts content-hashed files here: safe to cache long

MISSING_DIST_TEXT = (
    "The web app is not built yet, so there is no WoZ panel to show.\n\n"
    "Fix: in the repo root run\n\n"
    "    npm install\n"
    "    npm run build\n\n"
    "then reload this page (the brain does not need a restart).\n"
    "Expected folder: {dist}\n"
)
PANEL_INDEX = Path("woz") / "index.html"


def make_response(
    status: http.HTTPStatus,
    body: bytes,
    content_type: str,
    extra_headers: tuple[tuple[str, str], ...] = (),
) -> Response:
    """An HTTP response for ``process_request`` (the connection is closed after it)."""
    headers = Headers(
        [
            ("Date", email.utils.formatdate(usegmt=True)),
            ("Connection", "close"),
            ("Content-Length", str(len(body))),
            ("Content-Type", content_type),
            *SECURITY_HEADERS,
            *extra_headers,
        ]
    )
    return Response(status.value, status.phrase, headers, body)


def text_response(status: http.HTTPStatus, text: str) -> Response:
    return make_response(
        status, text.encode("utf-8"), "text/plain; charset=utf-8", (("Cache-Control", "no-store"),)
    )


def redirect(location: str) -> Response:
    return make_response(
        http.HTTPStatus.FOUND,
        b"",
        "text/plain; charset=utf-8",
        (("Location", location), ("Cache-Control", "no-store")),
    )


@dataclass(frozen=True)
class StaticSite:
    """Serves files from one folder (``web/dist``)."""

    root: Path

    @property
    def available(self) -> bool:
        """True when the panel has been built (``web/dist/woz/index.html`` exists)."""
        return (self.root / PANEL_INDEX).is_file()

    def missing_text(self) -> str:
        return MISSING_DIST_TEXT.format(dist=self.root)

    def respond(self, path: str, query: str) -> Response:
        """Answer ``GET path?query``. ``query`` is kept on redirects (it carries the token)."""
        suffix = f"?{query}" if query else ""
        if path in ("", "/"):
            return redirect(f"/woz/{suffix}")
        if not self.available:
            return text_response(http.HTTPStatus.SERVICE_UNAVAILABLE, self.missing_text())
        target = self._resolve(path)
        if target is None:
            return text_response(http.HTTPStatus.NOT_FOUND, "Not found.\n")
        if target.is_dir():
            if not path.endswith("/") and (target / "index.html").is_file():
                return redirect(f"{path}/{suffix}")
            target = target / "index.html"
        if not target.is_file():
            return text_response(http.HTTPStatus.NOT_FOUND, "Not found.\n")
        return self._file_response(path, target)

    def _resolve(self, path: str) -> Path | None:
        """Map a URL path to a file inside ``root``; None if it points anywhere else."""
        relative = unquote(path).lstrip("/")
        if "\x00" in relative or "\\" in relative:
            return None
        root = self.root.resolve()
        try:
            candidate = (root / relative).resolve()
        except (OSError, RuntimeError):
            return None
        if candidate != root and not candidate.is_relative_to(root):
            return None
        return candidate if candidate.exists() else None

    @staticmethod
    def _file_response(path: str, target: Path) -> Response:
        try:
            body = target.read_bytes()
        except OSError:
            return text_response(http.HTTPStatus.INTERNAL_SERVER_ERROR, "Cannot read file.\n")
        content_type = CONTENT_TYPES.get(target.suffix.lower(), DEFAULT_CONTENT_TYPE)
        cache = (
            "public, max-age=31536000, immutable"
            if path.startswith(HASHED_ASSET_PREFIX)
            else "no-cache"
        )
        return make_response(http.HTTPStatus.OK, body, content_type, (("Cache-Control", cache),))
