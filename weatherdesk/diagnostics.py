"""Connection test (Help → Test connection): shows where any delay comes from.

Checks DNS, IPv4 and IPv6 connection times separately, then times a real
location search and forecast download. Plain text so it can be copied.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import platform
import socket
import ssl
import sys
import time
import urllib.parse
import urllib.request
from typing import Callable, Optional

from . import APP_NAME, AUTHOR_CREDIT, __version__
from . import net
from .api import OpenMeteoClient, WeatherError
from .keystore import redact
from .models import Location

PROBE_TIMEOUT = 5.0
SLOW_MS = 1500


def _ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


def _probe_family(host: str, port: int, family: int, tls_ctx=None) -> tuple[str, bool]:
    """Connect over one address family; for HTTPS also complete the secure (TLS)
    handshake, because a network can pass the connection but stall the handshake.
    Returns (text, tls_failed_after_connect)."""
    try:
        infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    except socket.gaierror:
        return "no address (not offered by DNS)", False
    addr = infos[0][4]
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(PROBE_TIMEOUT)
    t1 = time.monotonic()
    try:
        s.connect(addr)
    except socket.timeout:
        s.close()
        return f"NOT WORKING – no reply after {PROBE_TIMEOUT:.0f} s ({addr[0]})", False
    except OSError as e:
        s.close()
        return f"NOT WORKING – {e.strerror or e} ({addr[0]})", False
    connect_ms = _ms(t1)
    if tls_ctx is None:
        s.close()
        return f"OK – connected in {connect_ms} ms ({addr[0]})", False
    t2 = time.monotonic()
    try:
        with tls_ctx.wrap_socket(s, server_hostname=host) as ts:
            ts.settimeout(PROBE_TIMEOUT)
            return (f"OK – connected in {connect_ms} ms, secure handshake {_ms(t2)} ms "
                    f"({addr[0]})"), False
    except socket.timeout:
        small = _small_packet_handshake(host, addr, family, tls_ctx)
        return (f"CONNECTS ({connect_ms} ms) but the secure handshake STALLS – no reply after "
                f"{PROBE_TIMEOUT:.0f} s ({addr[0]}).\n"
                f"         With small packets (MSS {net.CLAMP_MSS}): {small}"), True
    except (ssl.SSLError, OSError) as e:
        return f"CONNECTS ({connect_ms} ms) but the secure handshake FAILS – {e} ({addr[0]})", True
    finally:
        s.close()


def _small_packet_handshake(host, addr, family, tls_ctx) -> str:
    s = socket.socket(family, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, net.CLAMP_MSS)
    except (OSError, AttributeError):
        s.close()
        return "not supported on this system"
    s.settimeout(PROBE_TIMEOUT)
    t = time.monotonic()
    try:
        s.connect(addr)
        with tls_ctx.wrap_socket(s, server_hostname=host):
            return (f"WORKS (secure handshake {_ms(t)} ms) – a path-MTU / packet-size problem "
                    f"on the network route; WeatherDesk uses small packets for this server automatically")
    except socket.timeout:
        return f"still stalls after {PROBE_TIMEOUT:.0f} s – not a packet-size problem"
    except (ssl.SSLError, OSError) as e:
        return f"fails – {e}"
    finally:
        s.close()


def run_diagnostics(client: Optional[OpenMeteoClient] = None,
                    sample: Optional[Location] = None,
                    progress: Optional[Callable[[str], None]] = None) -> str:
    client = client or _default_manager()
    lines: list[str] = []

    def out(line: str = "") -> None:
        line = redact(line)                 # no API key ever reaches the report
        lines.append(line)
        if progress:
            progress(line)

    out(f"{APP_NAME} {__version__} connection test – {AUTHOR_CREDIT}")
    out(f"Python {platform.python_version()} on {platform.platform()}")
    proxies = {k: v for k, v in urllib.request.getproxies().items() if k in ("http", "https")}
    out("Proxy: " + (", ".join(f"{k}={v}" for k, v in proxies.items()) if proxies else "none"))
    out()

    slow_v6 = False
    tls_stall = {"IPv4": False, "IPv6": False}
    hosts = []
    backup = getattr(client, "backup", None)
    chain = _chain(client)               # [(label, provider)] when it's a ProviderManager
    urls = [client.geocode_url, client.forecast_url] + ([backup.forecast_url] if backup is not None else [])
    urls += [getattr(getattr(p, "client", p), "forecast_url", p.base_url) for _l, p in chain]
    for url in urls:
        u = urllib.parse.urlsplit(url)
        port = u.port or (443 if u.scheme == "https" else 80)
        if (u.hostname, port) not in hosts:
            hosts.append((u.hostname, port))
    for host, port in hosts:
        out(f"[{host}]")
        t0 = time.monotonic()
        try:
            infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
            fams = sorted({_fam(i[0]) for i in infos})
            out(f"  DNS lookup: {_ms(t0)} ms – {', '.join(fams)} addresses")
        except socket.gaierror as e:
            out(f"  DNS lookup FAILED after {_ms(t0)} ms: {e}")
            out()
            continue
        scheme_https = any(urllib.parse.urlsplit(u).scheme == "https" and urllib.parse.urlsplit(u).hostname == host
                           for u in urls)
        tls_ctx = (client.ssl_context or ssl.create_default_context()) if scheme_https else None
        for fam, name in ((socket.AF_INET, "IPv4"), (socket.AF_INET6, "IPv6")):
            res, stalled = _probe_family(host, port, fam, tls_ctx)
            if name == "IPv6" and (res.startswith("NOT WORKING") or stalled):
                slow_v6 = True
            tls_stall[name] = tls_stall[name] or stalled
            out(f"  {name}: {res}")
        out()

    sample = sample or Location("Auckland", -36.8485, 174.7635, "New Zealand", timezone="auto")
    results = {}
    main_fetch = getattr(client, "fetch_open_meteo", client.fetch_forecast)
    checks = [("Location search", lambda: client.search_locations(sample.name))]
    if chain:
        for label, p in chain:
            if p.info.needs_key and not p.api_key:
                out(f"{label}: skipped – no API key saved (Settings → Weather Providers)")
                continue
            checks.append((label, lambda p=p: p.fetch_forecast(sample)))
    else:
        checks.append(("Forecast download", lambda: main_fetch(sample)))
    if backup is not None:
        checks.append((f"Backup forecast ({backup.source_name})", lambda: backup.fetch_forecast(sample)))
    for label, fn in checks:
        t0 = time.monotonic()
        try:
            fn()
            ms = _ms(t0)
            results[label] = ms
            out(f"{label}: OK in {ms} ms" + ("  ← slow" if ms > SLOW_MS else ""))
        except WeatherError as e:
            results[label] = None
            out(f"{label}: FAILED after {_ms(t0)} ms – {e}")

    out()
    out("Summary:")
    if chain:
        _summary_chain(out, chain, results)
    backup_label = next((k for k in results if k.startswith("Backup forecast")), None)
    if backup_label and results.get("Forecast download") is None and results.get(backup_label) is not None:
        out("  Open-Meteo's forecast server couldn't be reached, but the backup source")
        out(f"  ({backup.source_name}) works, so WeatherDesk keeps updating from it automatically.")
        out("  You can also choose it as the main source: Settings → Weather Providers.")
    elif backup_label and results.get(backup_label) is None and \
            all(v is not None for k, v in results.items() if k != backup_label):
        out(f"  Open-Meteo works. The backup source ({backup.source_name}) couldn't be reached,")
        out("  which only matters if Open-Meteo fails.")
    elif chain:
        pass
    elif any(v is None for v in results.values()):
        out("  The weather service could not be reached. Check your internet connection,")
        out("  firewall or proxy settings, then try again.")
    elif any(v > SLOW_MS for v in results.values()):
        out("  The service works but responded slowly. If IPv6 shows NOT WORKING above,")
        out("  WeatherDesk already works around it; the remaining delay is the network")
        out("  or the weather service itself.")
    else:
        out("  Everything looks good.")
    if slow_v6:
        out("  Note: IPv6 is offered but not working properly on this network.")
        out("  WeatherDesk automatically switches to IPv4 when that happens.")
    if tls_stall["IPv4"] or tls_stall["IPv6"]:
        which = " and ".join(k for k, v in tls_stall.items() if v)
        out(f"  Secure connections over {which} connect but then stall. This is usually")
        out("  the router or ISP (often an MTU/'packet size' problem), a VPN, or a")
        out("  firewall/antivirus inspecting HTTPS. WeatherDesk gives up on a stalled")
        out(f"  handshake after {net.HANDSHAKE_TIMEOUT:.0f} s and retries another way automatically.")
    h = net.health_snapshot()
    if h["addresses"] or h["ipv6_avoided"]:
        out("  Currently avoiding after recent failures: "
            + ", ".join(h["addresses"] + (["IPv6"] if h["ipv6_avoided"] else [])))
    if h["small_packets"]:
        out("  Using small packets (MSS %d) for: %s" % (net.CLAMP_MSS, ", ".join(h["small_packets"])))
    return "\n".join(lines)


def _default_manager():
    from .providers.manager import ProviderManager
    from .storage import SettingsStore
    s = SettingsStore().load()
    return ProviderManager(chain=s.provider_chain, recovery=s.provider_recovery)


def _chain(client) -> list:
    if not hasattr(client, "chain") or not hasattr(client, "provider"):
        return []
    out = []
    for i, pid in enumerate(client.chain):
        p = client.provider(pid)
        role = "primary" if i == 0 else f"backup {i}"
        key = (", key saved (not shown)" if p.api_key else "") if p.info.needs_key else ""
        out.append((f"Forecast – {p.info.name} ({role}{key})", p))
    return out


def _summary_chain(out, chain, results) -> None:
    ok = [lab for lab, _p in chain if results.get(lab) is not None]
    names = {lab: p.info.name for lab, p in chain}
    primary = chain[0][0]
    if results.get("Location search") is None:
        out("  Location search (Open-Meteo) couldn't be reached; saved locations still update.")
    if results.get(primary) is not None:
        slow = results[primary] > SLOW_MS
        out(f"  {names[primary]} (primary) works{' but responded slowly' if slow else ''}.")
        failed = [names[lab] for lab, _p in chain[1:] if lab in results and results[lab] is None]
        if failed:
            out(f"  Backup{'s' if len(failed) > 1 else ''} not working: {', '.join(failed)} – this only "
                f"matters if the primary fails.")
    elif ok:
        out(f"  {names[primary]} (primary) couldn't supply the weather, but {names[ok[0]]} works,")
        out("  so WeatherDesk keeps updating from it automatically (Settings → Weather Providers).")
    else:
        out("  No weather provider could be reached. Check your internet connection,")
        out("  firewall or proxy settings, and any API keys, then try again.")


def _fam(f: int) -> str:
    return {socket.AF_INET: "IPv4", socket.AF_INET6: "IPv6"}.get(f, str(f))


if __name__ == "__main__":     # python3 -m weatherdesk.diagnostics
    print(run_diagnostics())
    sys.exit(0)
