"""Short-lived request_id -> reply_text map for the streaming speech endpoint.

The <audio> element fetches speech by opaque id, so no conversation text ever
appears in a URL (query strings get logged; opaque ids don't leak anything).
Single-process in-memory store is correct here: the app runs as one instance,
and entries are only needed for the seconds between reply and playback.
"""

import time

TTL_SECONDS = 300
MAX_ENTRIES = 500

_store: dict[str, tuple[str, float]] = {}


def put(request_id: str, text: str) -> None:
    now = time.monotonic()
    if len(_store) >= MAX_ENTRIES:
        for key, (_, ts) in list(_store.items()):
            if now - ts > TTL_SECONDS:
                del _store[key]
    if len(_store) >= MAX_ENTRIES:  # still full: drop oldest
        del _store[min(_store, key=lambda k: _store[k][1])]
    _store[request_id] = (text, now)


def get(request_id: str) -> str | None:
    entry = _store.get(request_id)
    if entry is None:
        return None
    text, ts = entry
    if time.monotonic() - ts > TTL_SECONDS:
        del _store[request_id]
        return None
    return text
