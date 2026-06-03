"""
HARRecorder — Python-side HAR 1.2 capture.

Playwright's native ``record_har_path`` is buffered driver-side and only flushed on a
client-initiated ``context.close()`` while the browser is alive. In interactive mode the
user closes the window first, so the browser dies and the HAR is lost (the webm survives
because the browser finalizes it itself). This recorder buffers entries in the Python
process — which outlives the browser — so the HAR is always written on close().

Captures one entry per response (request metadata is read from ``response.request``).
Response bodies are captured live for textual content types; binary/media keep metadata only.
"""

import asyncio
import base64
import json
import time
from datetime import datetime, timezone

# Content types whose body is worth keeping (the point is API/data rétro, not media bytes).
_TEXTUAL = ("application/json", "text/", "application/javascript", "application/xml",
            "application/x-www-form-urlencoded", "application/x-component",
            "application/graphql", "image/svg")
_MAX_BODY = 8 * 1024 * 1024  # skip bodies larger than 8 MB


def _headers_list(headers: dict) -> list:
    return [{"name": k, "value": v} for k, v in (headers or {}).items()]


class HARRecorder:
    """Buffers network entries in Python memory and writes a HAR 1.2 file on demand."""

    def __init__(self):
        self._entries: list = []
        self._context = None

    def attach(self, context):
        """Wire response capture on all current pages and any page opened later."""
        self._context = context
        for page in context.pages:
            self._attach_page(page)
        context.on("page", self._attach_page)

    def _attach_page(self, page):
        page.on("response", self._on_response)

    async def _on_response(self, response):
        try:
            req = response.request
            started = datetime.now(timezone.utc).isoformat()

            req_headers = await _safe(req.all_headers())
            res_headers = await _safe(response.all_headers())
            ct = (res_headers or {}).get("content-type", "")

            post_data = None
            try:
                if req.post_data:
                    post_data = {"mimeType": (req_headers or {}).get("content-type", "text/plain"),
                                 "text": req.post_data}
            except Exception:
                pass

            content = {"size": -1, "mimeType": ct}
            if any(t in ct for t in _TEXTUAL):
                body = await _safe(response.body())
                if body is not None and len(body) <= _MAX_BODY:
                    content["size"] = len(body)
                    try:
                        content["text"] = body.decode("utf-8")
                    except UnicodeDecodeError:
                        content["text"] = base64.b64encode(body).decode("ascii")
                        content["encoding"] = "base64"

            self._entries.append({
                "startedDateTime": started,
                "time": 0,
                "request": {
                    "method": req.method,
                    "url": response.url,
                    "httpVersion": "HTTP/1.1",
                    "headers": _headers_list(req_headers),
                    "queryString": [],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": -1,
                    **({"postData": post_data} if post_data else {}),
                },
                "response": {
                    "status": response.status,
                    "statusText": response.status_text or "",
                    "httpVersion": "HTTP/1.1",
                    "headers": _headers_list(res_headers),
                    "cookies": [],
                    "content": content,
                    "redirectURL": (res_headers or {}).get("location", ""),
                    "headersSize": -1,
                    "bodySize": content.get("size", -1),
                },
                "cache": {},
                "timings": {"send": 0, "wait": 0, "receive": 0},
                "_resourceType": req.resource_type,
            })
        except Exception:
            # Never let capture break the page.
            pass

    def write(self, path: str) -> int:
        """Write the buffered entries to a HAR 1.2 file. Returns entry count."""
        har = {
            "log": {
                "version": "1.2",
                "creator": {"name": "o-browser", "version": "1"},
                "pages": [],
                "entries": self._entries,
            }
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(har, f, ensure_ascii=False)
        return len(self._entries)


async def _safe(awaitable):
    """Await best-effort; return None if the browser is gone or the call fails."""
    try:
        return await awaitable
    except Exception:
        return None
