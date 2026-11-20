"""Which requests the launcher answers: this computer's own page, and tools run on this computer.

The launcher listens on loopback only, so the one way in from outside is the browser: a page from anywhere, open in
the same browser, can send a request to `localhost:9000`. Before 20 Nov 2026 nothing checked. Such a page could POST
`/api/tasks/ibkr-paper-cycle/stop` in the middle of a window (the run's limits are cancelled and the cycle halts), or
`/start?take_over=true&allow_unsynced=true&force_take_over=true`, which skips the two-PC fence (review, 20 Nov 2026).

- Every request must name a loopback **Host**. A DNS-rebinding page reaches us under its own name.
- A request that changes something (anything but GET, HEAD, OPTIONS) must also come from the launcher's own page:
  its **Origin**, when the browser sends one, must be the address it is asking; **Sec-Fetch-Site**, when sent, must be
  `same-origin` or `none`. A browser sends Origin on every cross-site POST, so a request with neither header is a
  local tool (curl, a script), and is let through.
"""
from collections.abc import Mapping
from urllib.parse import urlsplit

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
READ_ONLY = frozenset({"GET", "HEAD", "OPTIONS"})
OWN_PAGE = frozenset({"same-origin", "none"})


def _split(host: str) -> tuple[str, str]:
    """`localhost:9000` -> (`localhost`, `9000`); `[::1]:9000` -> (`::1`, `9000`). Lower case; port "" when absent."""
    host = host.strip().lower()
    if host.startswith("["):
        name, _, rest = host[1:].partition("]")
        return name, rest.lstrip(":")
    name, _, port = host.partition(":")
    return name, port


def refusal(method: str, headers: Mapping[str, str]) -> str | None:
    """Why the request is refused, or None when it is answered. `headers` is looked up in lower case."""
    name, port = _split(headers.get("host", ""))
    if name not in LOOPBACK:
        return "The launcher answers only on this computer's own address (localhost)."
    if method.upper() in READ_ONLY:
        return None
    site = headers.get("sec-fetch-site")
    if site is not None and site.lower() not in OWN_PAGE:
        return "The launcher takes changes only from its own page."
    origin = headers.get("origin")
    if origin is not None:
        parts = urlsplit(origin)
        try:
            origin_port = str(parts.port or "")
        except ValueError:  # a port that is not a number
            origin_port = "?"
        if (parts.hostname or "").lower() not in LOOPBACK or origin_port != port:
            return "The launcher takes changes only from its own page."
    return None
