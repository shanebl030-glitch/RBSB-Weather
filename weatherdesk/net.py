"""Fast network connections ("Happy Eyeballs", RFC 8305 style) for urllib.

Problem this solves: Python's standard socket.create_connection() tries each
address of a host one after another and waits the *full* timeout on each. On
networks where IPv6 is advertised but doesn't actually work (common on home
routers), every request stalls for the whole timeout (15 s) before falling
back to IPv4. Web browsers avoid this by racing connections.

fast_create_connection() does the same: it starts the first address, and if
that hasn't connected within STAGGER seconds it starts the next one in
parallel (alternating IPv6/IPv4). The first to connect wins; the others are
closed. A failed attempt immediately starts the next.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import errno
import http.client
import logging
import selectors
import socket
import threading
import time
import urllib.request
from typing import Optional

log = logging.getLogger(__name__)

STAGGER = 0.25          # seconds before starting the next address in parallel
HANDSHAKE_TIMEOUT = 6.0  # secure-connection setup limit (the full timeout still applies to reading)
BAD_FOR_S = 600.0       # how long a failing address / broken IPv6 is avoided
CLAMP_MSS = 1000        # max TCP segment size requested after a stalled handshake
CLAMP_MSS_MIN = 536     # ...and after a stall even at CLAMP_MSS (the IPv4 minimum, safe everywhere)
CLAMP_FOR_S = 7 * 24 * 3600.0   # remembered (on disk) for a week
HEALTH_FILE = None      # set by the app (cache dir) so the small-packet setting survives restarts

# ---- connection health ----------------------------------------------------
# A server can accept the TCP connection and then stall during the secure
# (TLS) handshake – typically IPv6 with a path-MTU problem: small packets get
# through, the server's certificate (large packets) never arrives. Racing TCP
# connects can't detect that, so after such a failure the address (and, for
# IPv6, the whole family) is avoided for a while and the request is retried.
_health_lock = threading.Lock()
_bad_addr: dict[tuple, float] = {}         # (address, port) -> monotonic time it's trusted again
_bad_family: dict[int, float] = {}         # family  -> monotonic time it's trusted again
# Addresses whose handshake stalled get small TCP segments from then on. A stall
# after a successful TCP connect is the classic sign of a path-MTU "black hole":
# the server's certificate is sent in full-size packets that something on the
# route silently drops. Asking for smaller segments (TCP_MAXSEG) gets around it.
_clamp: dict[tuple, tuple] = {}             # (address, port) -> (wall-clock expiry, mss)
_clamp_loaded = False
_tls = threading.local()


class handshake_limit:
    """Context manager: use a different secure-setup limit for connections opened on
    this thread (the last retry allows a slow-but-working link more time)."""
    def __init__(self, seconds: float):
        self.seconds = float(seconds)

    def __enter__(self):
        self._prev = getattr(_tls, "handshake", None)
        _tls.handshake = self.seconds
        return self

    def __exit__(self, *exc):
        _tls.handshake = self._prev
        return False


def last_connection() -> Optional[dict]:
    """Details of the connection most recently opened on this thread (or None)."""
    return getattr(_tls, "info", None)


def clear_last_connection() -> None:
    _tls.info = None


def mark_bad(address: str, port: int, family: int, clamp: bool = True) -> None:
    """Avoid an address (and IPv6, if that failed) for a while, and use small packets
    to it. A second stall while already on small packets steps down to the smallest
    size (CLAMP_MSS_MIN), in case the route's limit is lower than CLAMP_MSS allows."""
    until = time.monotonic() + BAD_FOR_S
    mss = None
    with _health_lock:
        _bad_addr[(address, int(port))] = until
        if family == socket.AF_INET6:
            _bad_family[socket.AF_INET6] = until
        if clamp:
            _load_clamp_locked()
            now = time.time()
            prev = _clamp.get((address, int(port)))
            mss = CLAMP_MSS_MIN if prev and prev[0] > now else CLAMP_MSS
            _clamp[(address, int(port))] = (now + CLAMP_FOR_S, mss)
            _save_clamp_locked()
    log.warning("avoiding %s %s for %d min after a failed connection%s",
                _family_name(family), address, BAD_FOR_S // 60,
                f"; using small packets (MSS {mss}) to it from now on" if clamp else "")


def clamp_mss(address: str, port: int) -> Optional[int]:
    """The small segment size to request from this address, or None for normal packets."""
    with _health_lock:
        _load_clamp_locked()
        entry = _clamp.get((address, int(port)))
        return entry[1] if entry and entry[0] > time.time() else None


def clamped(address: str, port: int) -> bool:
    return clamp_mss(address, port) is not None


def _load_clamp_locked() -> None:
    global _clamp_loaded
    if _clamp_loaded or HEALTH_FILE is None:
        return
    _clamp_loaded = True
    try:
        import json
        with open(HEALTH_FILE, encoding="utf-8") as f:
            data = json.load(f)
        now = time.time()
        for item in data.get("small_packets", []):
            key = (str(item["address"]), int(item["port"]))
            mss = int(item.get("mss", CLAMP_MSS))
            if float(item["until"]) > now and CLAMP_MSS_MIN <= mss <= CLAMP_MSS:
                _clamp[key] = (float(item["until"]), mss)
    except (OSError, ValueError, KeyError, TypeError):
        pass


def _save_clamp_locked() -> None:
    if HEALTH_FILE is None:
        return
    try:
        from .storage import atomic_write_json
        from pathlib import Path
        now = time.time()
        atomic_write_json(Path(HEALTH_FILE), {"small_packets": [
            {"address": a, "port": p, "until": t, "mss": m}
            for (a, p), (t, m) in _clamp.items() if t > now]})
    except Exception as e:                    # best effort only
        log.debug("could not save network health: %s", e)


def reset_health() -> None:
    global _clamp_loaded
    with _health_lock:
        _bad_addr.clear()
        _bad_family.clear()
        _clamp.clear()
        _clamp_loaded = False


def health_snapshot() -> dict:
    now = time.monotonic()
    with _health_lock:
        wall = time.time()
        return {"addresses": sorted(f"{a}:{p}" for (a, p), t in _bad_addr.items() if t > now),
                "ipv6_avoided": _bad_family.get(socket.AF_INET6, 0) > now,
                "small_packets": sorted(f"{a}:{p}" for (a, p), (t, _m) in _clamp.items() if t > wall),
                "small_packet_sizes": {f"{a}:{p}": m for (a, p), (t, m) in _clamp.items() if t > wall}}


def order_addresses(infos: list) -> list:
    """Resolver order, interleaved by family, with known-bad addresses tried last and
    IPv4 first while IPv6 is being avoided."""
    now = time.monotonic()
    with _health_lock:
        bad_addr = {a for a, t in _bad_addr.items() if t > now}
        bad_fam = {f for f, t in _bad_family.items() if t > now}
    if bad_fam and any(i[0] not in bad_fam for i in infos):
        infos = sorted(infos, key=lambda i: i[0] in bad_fam)     # stable: good family first
    ordered = _interleave(infos)
    key = lambda i: (i[4][0], int(i[4][1]))
    return [i for i in ordered if key(i) not in bad_addr] + [i for i in ordered if key(i) in bad_addr]

_IN_PROGRESS = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY}


def _interleave(infos: list) -> list:
    """Alternate address families, keeping the resolver's preferred family first."""
    if not infos:
        return []
    first = infos[0][0]
    a = [i for i in infos if i[0] == first]
    b = [i for i in infos if i[0] != first]
    out = []
    for i in range(max(len(a), len(b))):
        if i < len(a):
            out.append(a[i])
        if i < len(b):
            out.append(b[i])
    return out


def _family_name(fam: int) -> str:
    return {socket.AF_INET: "IPv4", socket.AF_INET6: "IPv6"}.get(fam, str(fam))


def fast_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                           source_address=None, *, stagger: float = STAGGER,
                           stats: Optional[dict] = None):
    """Drop-in replacement for socket.create_connection with staggered racing.

    `stats`, if given, is filled with dns_ms, connect_ms, family and address.
    """
    host, port = address
    _tls.info = None
    t0 = time.monotonic()
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    t_dns = time.monotonic()
    ordered = order_addresses(infos)
    if not ordered:
        raise OSError(f"no addresses found for {host}")

    if timeout is socket._GLOBAL_DEFAULT_TIMEOUT or timeout is None:
        deadline = None
    else:
        deadline = t_dns + float(timeout)

    sel = selectors.DefaultSelector()
    pending: dict[socket.socket, tuple] = {}
    winner: Optional[socket.socket] = None
    winner_info = None
    last_err: Optional[BaseException] = None
    idx = 0
    next_start = t_dns
    try:
        while winner is None:
            now = time.monotonic()
            # start the next attempt if it's due (or nothing is in flight)
            if idx < len(ordered) and (not pending or now >= next_start):
                info = ordered[idx]
                idx += 1
                fam, typ, proto, _, sa = info
                s = None
                try:
                    s = socket.socket(fam, typ, proto)
                    mss = clamp_mss(sa[0], sa[1]) if clamped(sa[0], sa[1]) else None
                    if mss:
                        try:      # must be set before connect so it goes in the SYN
                            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, mss)
                        except (OSError, AttributeError):
                            pass
                    s.setblocking(False)
                    if source_address:
                        s.bind(source_address)
                    err = s.connect_ex(sa)
                except OSError as e:
                    if s is not None:
                        s.close()
                    last_err = e
                    continue
                if err == 0:
                    winner, winner_info = s, info
                    break
                if err in _IN_PROGRESS:
                    sel.register(s, selectors.EVENT_WRITE)
                    pending[s] = info
                    next_start = now + stagger
                else:
                    s.close()
                    last_err = OSError(err, f"{errno.errorcode.get(err, err)} connecting to {sa[0]}")
                    next_start = now          # try the next address straight away
                continue

            if not pending:
                raise last_err or OSError(f"could not connect to {host}")

            now = time.monotonic()
            if deadline is not None and now >= deadline:
                raise socket.timeout(f"timed out connecting to {host}")
            waits = []
            if idx < len(ordered):
                waits.append(next_start - now)
            if deadline is not None:
                waits.append(deadline - now)
            wait = max(0.0, min(waits)) if waits else None

            for key, _ in sel.select(wait):
                s = key.fileobj
                info = pending.pop(s)
                sel.unregister(s)
                err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err == 0 and winner is None:
                    winner, winner_info = s, info
                else:
                    s.close()
                    if err:
                        last_err = OSError(err, f"{errno.errorcode.get(err, err)} connecting to {info[4][0]}")
                        next_start = time.monotonic()
    finally:
        for s in list(pending):
            try:
                sel.unregister(s)
            except Exception:
                pass
            s.close()
        sel.close()

    winner.setblocking(True)
    if deadline is not None:
        winner.settimeout(float(timeout))
    t_conn = time.monotonic()
    info = {"dns_ms": round((t_dns - t0) * 1000), "connect_ms": round((t_conn - t_dns) * 1000),
            "family": _family_name(winner_info[0]), "address": winner_info[4][0],
            "family_num": winner_info[0], "port": winner_info[4][1], "attempts": idx}
    _tls.info = info
    if stats is not None:
        stats.update(info)
    log.debug("connected to %s via %s %s (dns %d ms, connect %d ms, %d attempt(s))",
              host, info["family"], info["address"], info["dns_ms"], info["connect_ms"], idx)
    return winner


# http.client assigns self._create_connection = socket.create_connection inside
# __init__, so it must be replaced on the instance *after* __init__ (a class
# attribute would be silently shadowed - verified by test_fast_connect_used).
class FastHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = fast_create_connection


class FastHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = fast_create_connection

    def connect(self):
        # Limit only the connect + TLS handshake, so a stalled handshake fails in
        # a few seconds (and gets retried elsewhere) rather than the full timeout.
        full = self.timeout
        limit = getattr(_tls, "handshake", None) or HANDSHAKE_TIMEOUT
        if isinstance(full, (int, float)) and full > limit:
            self.timeout = limit
        try:
            super().connect()
        finally:
            self.timeout = full
        if self.sock is not None and isinstance(full, (int, float)):
            self.sock.settimeout(full)


class _FastHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(FastHTTPConnection, req)


class _FastHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(FastHTTPSConnection, req, context=self._context)


def build_opener(ssl_context=None) -> urllib.request.OpenerDirector:
    """urllib opener using fast connections; still honours system proxy settings.
    `ssl_context` defaults to the system's normal certificate checks."""
    return urllib.request.build_opener(_FastHTTPHandler(), _FastHTTPSHandler(context=ssl_context))
