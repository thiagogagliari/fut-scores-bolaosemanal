from __future__ import annotations

import traceback
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from app import FutScoresHandler, init_database


_init_lock = Lock()
_initialized = False


class handler(FutScoresHandler):
    def parse_request(self) -> bool:
        global _initialized

        if not _initialized:
            with _init_lock:
                if not _initialized:
                    try:
                        init_database()
                    except Exception:
                        traceback.print_exc()
                        raise
                    _initialized = True

        if not super().parse_request():
            return False
        original_path = parse_qs(urlsplit(self.path).query).get("_route", [])
        if original_path:
            self.path = original_path[0]
        return True
