"""In-memory caching for reports/availability.

Keys are tuples whose first element is the org id, so every write in an org
invalidates all of that org's cached read models (usage report, availability,
room stats) — reads always reflect current state immediately after a write.
"""

import threading


class Cache:
    def __init__(self):
        self._data: dict[tuple, object] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple):
        with self._lock:
            return self._data.get(key)

    def set(self, key: tuple, value) -> None:
        with self._lock:
            self._data[key] = value

    def invalidate_org(self, org_id: int) -> None:
        with self._lock:
            for key in [k for k in self._data if k and k[0] == org_id]:
                self._data.pop(key, None)


cache = Cache()
