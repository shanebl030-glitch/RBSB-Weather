# WeatherDesk Test Report

Created By Shane BlackbuRn

| Item | Result |
|---|---|
| Version | 1.11.1 |
| Date | 2026-11-16 |
| Environment | Ubuntu 24.04.5 (Linux Mint 22 base), Python 3.12, PyQt6 6.6.1 / Qt 6.4.2, headless (offscreen) |
| Suites | `test_core`, `test_net`, `test_tls`, `test_scene`, `test_moon`, `test_earth`, `test_globe`, `test_clouds`, `test_sky`, `test_refresh`, `test_timefmt`, `test_arc`, `test_forecast_strip`, `test_instance`, `test_gui`, `test_stress` |
| Tests run | 295 |
| Passed | 293 |
| Failed / errors | 0 / 0 |
| Skipped | 2: `test_readonly_dir_raises_oserror` is skipped when run as root (it passed as the `nobody` user), and the NASA-converter test needs build-time tools (numpy and tifffile). It passed in a run with those installed, where all 28 Moon tests passed. |
| Run time | about 216 s (2 CPUs) |
| Command | `./run_tests.sh` (full log in `test-results.log`) |

## What's covered

| Suite | Tests | Covers |
|---|---|---|
| `test_core` | 39 | Units, weather codes, parsing robustness, HTTP error paths, settings, atomic writes, cache |
| `test_net` | 17 | Fast connections with a dead first address; refused, all-dead and no-address cases; no socket leaks; the regression for the slow-loading bug; the connection test report, dialog and `--diagnose` flag |
| `test_tls` | 21 | Secure-connection faults: the reported handshake stall reproduced and recovered; bounded failure time; full read timeout kept; no retry for certificate or HTTP errors; address ordering and expiry; small segments applied; corrupt health file; a **path-MTU black hole simulated with a network namespace and veth** (fails without the fix, recovers in about one stall limit, then about 4 ms per request; remembered across restarts; diagnostics explain it); GUI shows weather, not an error |
| `test_scene` | 28 | Every weather code at day, dusk and night; day/dusk/night maths; sun position; clock moving on since download; wind direction; hemisphere; moon phase against known dates; paint-time limit; 10 simulated minutes of animation; lightning only in storms; rain slant; sprite cache limit; icons; animation clock pausing; desktop widget behaviour and persistence; off-screen recovery; toggle leak check |
| `test_moon` | 37 | Moon rise/set against 120 PyEphem reference days in 4 cities; illumination (167 samples); new/quarter/full times (48); phase names; the 7-day view; polar always-up/down; timezones; rendering (lit area matches illumination, hemisphere orientation, earthshine, numpy and pure Python agree, cache, missing texture, bad metadata, size limits); NASA converter landmark placement; Moon tab (data, location switch, 10-minute refresh limit, rows never overlap at 3 window sizes, NASA credit, 2048 px save, save failure); night-scene moon |
| `test_earth` | 18 | The sun's overhead point and height vs PyEphem; equinox and solstices; day/twilight/night; projection; masks; blended map pixels (day map under the sun, night map opposite); missing map; markers, card and clicks; fixed-time states; units and no-weather; card placement; redraw and clock behaviour; credits |
| `test_globe` | 17 | Projection (centre, far side, limb, poles, 3000-point round trip); renderers (centre pixel, transparent outside, limb darkening, numpy vs pure Python identical, size cap, speed); tab names; facing the selected place; smooth turn on selection; marker click vs drag; drag rotation; far-side card hidden; one shared image for both Earth tabs; slow rotation only while visible; Centre button; no-numpy jump; missing map; credit |
| `test_clouds` | 17 | Cloud map download, 304 re-check, newer map; hourly / 15-minute schedules; garbage, 404, oversize and wrong-shape downloads never replace the cache; unreachable and stalled servers; corrupt cache; haze curve; day clouds white; night clouds hide city lights; tick boxes in step, saved, redraw; offline without cache; no repeated downloads; closing mid-download; setting validation |
| `test_sky` | 13 | Sky projection; zoom glide without per-frame redraws; high-res Moon reuse while moving; the Sun at the globe edge in step with day/night; the Moon's lit side towards the Sun (geometry and rendered pixels); stars with sidereal time (numpy = pure Python); Sun drawn/hidden plus edge hints; Moon phase; the sky moving with the globe; zoom by wheel, buttons and keys, limits, sharpening; render cap and memory; card off-screen; clicks while zoomed |
| `test_refresh` | 10 | Updates every interval by the wall clock (none at 28 min, one at 30), catching up after sleep, 5-minute retry after failure without hammering, off/60-minute settings; the widget's "↻ HH:MM" line: text, tooltip, placement at all sizes, "updating…", old-data/saved-copy warnings, shown at once |
| `test_timefmt` | 6 | 12/24-hour formatting (edge times, day names, ISO and bad input, chart labels), the setting and its validation, every view switching without re-downloading, remembered after restart |
| `test_arc` | 13 | Sun/Moon arc shape (hidden at rise and set, top middle, symmetrical, smooth, gradual emergence), progress from real rise/set times, `moon_pass` vs Moon tab times, scene drawing on the arc and gliding with the clock; daytime Moon when up (pale, no dark blob), Sun and Moon together on their own arcs, Moon hidden below the horizon by day/dusk/night, visibility from real altitude |
| `test_forecast_strip` | 19 | Mini forecast: daily data and names, size classes, 1–7 days, 224-size resize sweep (no overlap/clipping, readable, monotonic), bottom-right placement, fixed position and day count all day with Sun/Moon passing behind (positions and pixels outside the forecast identical with/without it), forecast drawn over the Sun, animated icons (10 kinds incl. heavy rain and windy), top card + desktop widget (location, units, sizes), window resize, Sun/Moon unchanged, frame cost, hidden without data |
| `test_instance` | 10 | Real-process single-instance hand-over: same version, upgrade, older launch versus newer, legacy (pre-1.1.1) copy, a busy copy never closed, abandoned requests while paused ignored, a decoy never signalled, a stale socket after a crash |
| `test_gui` | 23 | Complete user workflows (search, add, units, remove, reorder, restart, offline, stale responses, autostart, settings failure, credit) |
| `test_stress` | 7 | Repeated refreshes ×1/10/25/50, render ×200, stalled socket, closing mid-request, window open/close cycles, closing while results arrive ×40, signal flood during window destruction ×15 |

## Key results

| Check | Result |
|---|---|
| Request with a dead first address (broken-IPv6 simulation), 15 s timeout | v1.0.0: **15 s** per request → v1.1.0: **0.25 s** |
| Regression test with the old behaviour put back | Fails (30 s for 2 requests), confirming it catches the bug |
| Simulated path-MTU black hole (1 address, packets over 1200 B dropped) | v1.2.1: fails with `_ssl.c:983: The handshake operation timed out`. v1.2.2: first request recovers after the stall limit, then about 4 ms per request |
| Sun overhead point / sun height vs PyEphem | within 0.23′ lat and 0.80′ lon / within 0.006° (384 samples) |
| Day/night map blend (2576×1288) | about 0.2 s, background thread, pure Qt |
| Globe projection round trip | worst 2.1e-13° over 3000 points |
| Globe render: numpy 600 px / pure Python 240 px | 29 ms per frame / 72 ms |
| Globe numpy vs pure-Python renders | identical (worst channel difference 0) at 4 centres |
| Day/night + clouds blend (2576×1288) | about 0.2 s, background thread |
| City-light contrast at Lagos at night, clear vs under cloud | 208 → 21 |
| Stalled cloud server (0.5 s timeout, one retry) | gave up after 1.0 s; cached map kept |
| Window closed during a stalled cloud download | 2 ms |
| Moon lit side vs direction to the Sun on screen | worst 0.00° (4 geometries), confirmed in rendered pixels |
| Globe paint with stars, Sun and Moon | about 7–9 ms |
| Zoom glide (1.7.0 redrew the globe every step, up to about 120 ms) | 11 frames, worst 11 ms; 0 redraws mid-glide, 1 sharp redraw after |
| Zoomed globe render | capped at 1300 px; at most 3 cached grids (about 30 MB at the largest) |
| Window open/close stress after the Bridge fix | 12 of 12 `test_stress` runs clean (before: the window-cycle test segfaulted about 1 run in 6) |
| Abandoned launch requests while paused (25, half "newer version") | 1.8.0: running copy quits (3/3 runs); 1.8.1: ignored, survives, exits cleanly |
| `test_instance` repeated after the fix | 5 of 5 runs clean; the "busy copy" repro was clean in 25 of 25 (before: 1 crash in 25) |
| Full suite, two consecutive runs (1.8.1) | both 257 run, 255 passed, 2 skipped |
| Moon arc rise/set vs Moon tab times | worst 0 s over 20 passes (Auckland, London, Quito) |
| Mini forecast days shown | widget small 2 · medium 4 · large 4; card 3/5/7/7 at 900/1100/1400/1800 px windows |
| Mini forecast over a full simulated day (51 frames) | 1 position, 1 day count; Sun/Moon identical with and without it; they pass behind it in 32 frames |
| Scene frame with mini forecast (7 animated icons) | about 4–6 ms |
| Both Earth tabs opened | 1 background day/night drawing (shared) |
| Moon orientation (parallactic angle) vs PyEphem | within 1.57° over 283 samples, 6 cities |
| 7-day moon calculation | 21 ms (77 ms before the Newton/secant rewrite) |
| UI responsiveness during a stalled download, with the moon calculation running | 43–45 updates per 0.5 s (16–26 before the speed-up; 49 with the moon calculation off) |
| Moonrise/moonset vs PyEphem | Auckland 23 s, London 36 s, Quito 16 s, Tromsø 219 s (Arctic grazing geometry) |
| Illumination / phase times vs PyEphem | 0.017 percentage points / 82 s |
| Moon tab (installed package, NASA textures) | Waxing Crescent 27%, rise 10:13, set 00:33 for Auckland on 15 Nov 2026 |
| Moon image render, 300 px | 66 ms with numpy (installed automatically with the .deb); about 250 ms pure Python |
| Save 2048 px PNG | 0.3–0.6 s |
| Real upgrade: installed 1.1.0 running → install 1.1.1 → launch | Old copy exited with code 0 after 6.2 s; 1.1.1 took over; the next launch brought it to the front |
| Overlapping stop signals (2 or 3), 30 runs | All exit code 0 (the earlier version could crash) |
| `test_instance` repeated | 6 runs in a row, all passing |
| Animation frame rate | 25 frames per second (target 24) |
| Paint time, 640×240, steady state (median) | Clear 1.8 ms, overcast 1.4, fog 4.4, drizzle 6.0, rain 4.3, snow 4.0, storm 3.2 |
| First frame after the weather changes | Up to about 56 ms, a one-off while cloud images are generated, then cached |
| Animation while hidden or turned off | The timer stops and scene time freezes (tested) |
| Desktop widget on/off ×20 | Top-level widgets 9 → 9 (no leak) |
| Refresh ×50 with animation running | Threads, file descriptors and QObjects unchanged; memory +24 KB |
| Steady CPU with animation (sandbox software rendering, in-process timing) | Window + desktop widget: 19.2% at 30 fps → **15.9% at 24 fps** (shipped). Window only: **10.2%**. Hidden or off: **0.4%** |

## Not tested (needs your machine)

* How the mini forecast looks with your fonts and display scaling. The
  layout measures the real fonts, so it adapts, but check the widget at
  your chosen size.

* A real suspend and resume on your laptop. Sleep was simulated by ageing the
  data while Qt's interval timer still had about 30 minutes left. After
  waking, the widget should show a new ↻ time within a minute or so (once
  the network is back).

* How smooth zooming feels with your mouse wheel or touchpad (touchpads send
  small steps, which zoom gradually).

* **The real cloud service (clouds.matteason.co.uk).** The sandbox's network
  blocks it (HTTP 403 from the proxy), so downloads were tested only against
  a local server sending maps in the documented format (2048×1024 greyscale
  JPEG). The screenshots use a simulated cloud map. On your laptop, open an
  Earth tab and check that the line above the map says "Clouds: satellite
  map from …".

* How smooth the globe feels when you drag it and while Rotate slowly is
  on, and its CPU use, on your display and graphics. In the sandbox the
  numpy path draws a 600 px globe in about 30 ms.

* Whether the packet-size workaround fixes the stall on **your** route to api.open-meteo.com. The simulation matches the symptoms in your connection test, and your curl output will confirm the cause.

* How the Moon tab looks and how fast it is on your display, including whether the 7-day strip fits without scrolling on your screen height.

* **Live Open-Meteo responses.** The sandbox blocks the domain. You've
  confirmed that v1.0.0 loads weather on your machine.
* Whether broken IPv6 was the cause of the slow loading on your network.
  **Help → Test connection** will show this.
* Animation smoothness and CPU use on real hardware with your display
  scaling.
* The desktop widget's see-through rounded corners and "stay below other
  windows" behaviour on Cinnamon. These depend on the window manager and
  compositor.
* The tray icon on the Cinnamon panel, and colour emoji rendering.
