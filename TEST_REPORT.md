# RBSB-Weather Test Report (formerly WeatherDesk)

Created By Shane BlackbuRn

| Item | Result |
|---|---|
| Version | 2.2.0 (the Wind tab: world wind on a globe from NOAA GFS; built on 2.1.2) |
| Date | 2026-11-21 |
| Environment | Ubuntu 24.04.5 (Linux Mint 22 base), Python 3.12, PyQt6 6.6.1 / Qt 6.4.2, headless (offscreen), 2 CPUs, `python3-keyring` installed (no D-Bus, so keys use the private file) |
| Suites | as 1.18.0, plus **`test_migrate`** (new in 2.0.0) **`test_updates`** (new in 2.1.0) **`test_support`** (new in 2.1.1) **`test_widget_source`** (new in 2.1.2), **`test_grib2`** and **`test_wind`** (new in 2.2.0) |
| Tests run | 588 |
| Passed | 586 |
| Failed / errors | 0 / 0 |
| Skipped | 2: `test_readonly_dir_raises_oserror` (root ignores directory permissions; it passed as the `nobody` user in 1.11), and the NASA-converter test (needs build-time numpy + tifffile). Neither is an app fault. On a machine without the ecCodes Python package (normal on Mint), `test_grib2`'s ecCodes cross-check also skips |
| Run time | about 544 s (2 CPUs), including the 60 s soak |
| Command | `PYTHON=/usr/bin/python3.12 ./run_tests.sh` (full log in `test-results.log`) |

**Mocks and simulations.** Every provider test runs against a local fake
server sending replies in each service's documented format. That proves
WeatherDesk handles those formats, failures and recoveries. It does **not**
prove the live services still send them. None of the weather services could
be reached from the build machine (all blocked, HTTP 403 from its proxy).

## 2.2.0: the Wind tab

| Check | Result |
|---|---|
| GRIB2 reader vs ecCodes, real NOAA GFS file | All 343 fields identical (45 with missing points), numpy and pure Python |
| GRIB2 reader, shipped test files | Real GFS 10 m U/V and synthetic files of every supported packing match ecCodes' values (checksums of every value) in both modes; damaged, cut-short, GRIB1 and absurd-size files refused cleanly |
| Runs, hours and URLs | Newest published run and the closest 3-hourly forecast; local time converted; NOMADS and AWS addresses as NOAA documents them; .idx byte ranges, including shared-message entries |
| Wind maths | Direction "from" convention; interpolation within neighbours; date-line wrap; poles clamped; numpy and pure-Python agree |
| Download | NOMADS; the newest run missing → older run, same time; NOMADS down → AWS byte ranges give exactly the two fields; nothing reachable → clear error |
| Cache | Saved and reused without the network; refreshed 3 hours on; failure keeps the saved map and waits 20 min; a damaged download never replaces it; a damaged saved file is ignored |
| Tab | Nothing downloaded until opened; frames only while shown and on (0 frames otherwise); hover readout in knots; streaks cleared on turning; offline with nothing saved shows the reason; a saved map shows at once offline |
| Performance (build machine, 2 CPUs) | ~31 frames/s, ~9.5 ms CPU per frame with 2,200 streaks; whole app ~34% of one core with streaks, 9% without |
| Visual | Screenshots with the real NOAA wind: swirls, streaks, coastlines, colour key, saved place |

**Not tested here:** the live NOAA download (the build machine can't reach NOAA),
and today's 1° files (the real sample is an older 2.5° file with the same
packing). Both need Shane's Mint.

## 2.1.2: provider name on the desktop widget

| Check | Result |
|---|---|
| Shown | "Open-Meteo" under the place, smaller than the place name, with a tooltip; the mini forecast keeps clear of it |
| Wording | "MET Norway (backup)" when a backup supplied it; "Open-Meteo · saved copy" offline; hidden with no location |
| Fits | "Weather Underground (backup)" at small, medium and large, without overlapping the temperature or update time (tested, and seen in screenshots) |
| `test_net` leak check | Failed once (18 != 16) from unrelated file activity in the test process; now checks the leaked sockets themselves; still fails when the counter is deliberately broken; 36 clean runs |
| Update checker on Mint | Shane confirmed 2.1.0 found the published 2.1.1 |

## 2.1.1: buy me a coffee

| Check | Result |
|---|---|
| The link | https://www.paypal.com payment link, Merchant ID M4EDN77T6EEPJ, NZ$0.99, NZD, "Coffee for RBSB-Weather"; no email address |
| Where it shows | Help → About (clickable, checked in the real About box and a screenshot), the User Guide, the README, and Help → Buy Me a Coffee… (opens it) |
| No browser | The link is shown in a message so it can be copied |
| Personal details | No Gmail address anywhere in the app's files or the README |

**Not tested here:** PayPal refuses automated visits to its payment page, so
whether the link opens the right page must be checked in a browser on Mint.

## 2.1.0: check for updates

| Check | Result |
|---|---|
| Reading releases | Normal, `V1.15.0`-style tags, drafts, pre-releases and bad tags refused; only `rbsb-weather_<version>_all.deb` is used; long notes cut; a bad page address replaced |
| Versions | 2.1.0 > 2.0.0, 2.10.0 > 2.9.0; same or older is not an update |
| When due | Never checked: due. 1 h after a good check: not due. 25 h: due. Failed 1 h ago: not due. Failed 4 h ago: due. Clock went back: due |
| Addresses | GitHub, api.github.com and *.githubusercontent.com allowed; http, look-alike domains, file: and others refused; http only for a local test server |
| Check errors | 404, rate limit, HTTP 500, damaged and oversized replies, no network, all in plain English; one retry after a timeout (tested: 2 requests, then success) |
| Download | Verified through a redirect, saved 0644, no temporary files left, progress reported; a wrong checksum, a missing or unlisted checksum, an HTML page, an incomplete file, an oversized file and a redirect away from GitHub are all refused and leave no files; cancel leaves no files; an identical file is reused without downloading; another file with the name is kept and `-2` used |
| Window | Menu items present and on by default; a manual check shows the update, then installs (opener called with the verified file); a bad download is never opened; up to date; error and retry; automatic check once a day, never in the first minute, never when switched off; skip hides it, the menu still shows it; a known update shown at startup without the network; closing during a download cancels it and deletes the part file |
| Stability | The window tests ran 20 times in a row with no failure (after fixing a crash on closing, see CHANGELOG) |
| **Real GitHub** | Check found RBSB-Weather 2.0.0 (installable). The download (GitHub redirect to its download server) passed the checksum; SHA256 0eb8931c… is the same as the tested 2.0.0 package |
| **Real dpkg upgrade 2.0.0 → 2.1.0** | Installed 2.0.0 running; `apt install ./rbsb-weather_2.1.0_all.deb` ("Unpacking rbsb-weather (2.1.0) over (2.0.0)"); launching 2.1.0 made 2.0.0 quit cleanly (exit 0) and take over |
| **Installed 2.1.0, real automatic check** | 61 s after starting: "update check: latest release is 2.0.0 (this is 2.1.0)" from the real GitHub; nothing announced (correct); `updates.json` written |
| Installed 2.1.0, restart | `updates.json` and `providers.json` still there after a restart (2.0.0 deleted them at startup) |
| Cache clean-up regression | `providers.json`, `network.json`, `clouds.json`, `updates.json` and other files survive; only orphaned forecast files are removed |

**Not tested here:** opening the .deb in Mint's package installer, the tray
notice on a real panel, and a real update from 2.1.0 to a later release (none
exists yet).

## 2.0.0: renamed to RBSB-Weather

| Check | Result |
|---|---|
| Copy of settings, cache and `keys.json` | Byte-identical; `keys.json` stays 0600 and the folder 0700; old logs not copied; old folders unchanged |
| Never overwrites | An existing RBSB-Weather settings file is kept; runs only once (marker); a failed copy is retried next start |
| Interrupted copy | No half-filled folder left behind; the next attempt succeeds |
| Keyring | Copied from "WeatherDesk" to "RBSB-Weather" (fake keyring); an existing key isn't overwritten; a locked entry doesn't stop the rest |
| Start at login | `rbsb-weather.desktop` written, the old file renamed `.migrated`; an existing new entry is kept |
| Real app, temporary home with a WeatherDesk profile | Carried over on the first start; nothing on the second |
| Real WeatherDesk 1.18.0 process (from git tag v1.18.0) running | Asked to hand over via its old socket, exited 0, RBSB-Weather owns the new socket and has its settings |
| Package | `Package: rbsb-weather`, `Replaces`/`Conflicts: weatherdesk`, `/usr/bin/weatherdesk` → `rbsb-weather`, menu keyword `weatherdesk` |
| **Real dpkg upgrade** | Installed `weatherdesk` 1.18.0 running (pid 3672, profile with 2 locations, °F, 12-hour, Weather Underground first with a Station ID, 2 keys in `keys.json`, login entry). `apt install ./rbsb-weather_2.0.0_all.deb`: "REMOVED: weatherdesk, NEW: rbsb-weather". `rbsb-weather` then: "WeatherDesk is running (yield); replacing it", old copy "exited (0)", "carried over from WeatherDesk: settings and saved locations, saved forecasts, Start at login". The installed app reads Auckland + London, F, 12, the provider chain, Station ID IAUCKL123, and both keys. `weatherdesk --version` prints RBSB-Weather 2.0.0; a second launch brings the running copy forward |
| Rollback and upgrade again | `apt install ./weatherdesk_1.18.0_all.deb` removed rbsb-weather and restored 1.18.0 with its settings unchanged; a second one-step upgrade was clean |

**Not tested here:** a real GNOME Keyring (no D-Bus in the sandbox; covered
by the fake-keyring tests only), the menu, icon and login entry on a real
desktop, and a real reboot.

## 1.18.0: forecast playback

| Check | Result |
|---|---|
| The sky ahead (test data starts at 10:15) | Each hour's weather is that hour's forecast (checked at 7 offsets): +0 h day, +9 h day, +10 h dusk, +13 h night, +19.75 h dawn, +23 h day |
| Tomorrow's hours | Use tomorrow's sunrise (06:01, not today's 06:00) |
| The Moon at the chosen moment | Every Moon value equals the live calculation at that moment (3 offsets). Regression: a past moment is no longer the real now |
| Wind during playback | Stays as now (the hourly data has none); said in the tooltip and the guide |
| How far ahead | 24 h; a shorter forecast ends at its last hour; nothing ahead, or no codes: 0 (bar disabled) |
| Cross-fade at the moment of change | Picture identical to the frame before |
| Cross-fade, partly → overcast | Largest change in one frame 2.64 (mean pixel), against 26.55 if it jumped; done in 0.8 s |
| 8 weather types 0.2 s apart (rain, snow, fog, clear…) | Largest change in one frame 2.83, against 36.59 when jumping; at most 2 cloud layouts fading |
| Rain/snow/fog fading out | Keep falling and drifting while they fade |
| Animations off / turned off mid-fade / resize mid-fade | Instant / finishes at the next paint / starts clean |
| Thunder | Fades in, still flashes |
| Bar | 3 forecast hours took 3.03 s (76 steps of 144 s); 15-minute slider steps; Now; quiet reset; disabled without hourly data; clamps to a shorter forecast |
| In the app | Card and sky show the hour; details, desktop widget sky and text, and tray stay live; Now restores everything; a new place starts at now; refresh, °F and the minute tick keep the hour with no live-sky flicker; 12-hour clock ("3:15 pm"); a provider without hourly data |
| Real play for 3 s in the app | 74 steps, 3 weather types, median 0.8 ms per step (worst 1.7 ms) |
| Deliberate mistakes in the code | Moon at the real now: 2 tests failed · no cross-fade: 6 · live-sky flicker on redraw: 1 |
| CPU (window and widget animating, 4 runs each) | 1.17.0 averaged 30.1%, 1.18.0 31.2%; the spread within each version is larger, so no measurable increase, at most about 1 point |
| Earth Globe tests made reliable | Both failed on unchanged 1.17.0 at today's time. The Moon test counted the weather sky's Moon (the real Moon was up); it now checks the globe's own picture, and still fails if the globe re-renders. The zoom test measured before a status line wrapped (836×392 → 836×377 within 0.1 s); it now waits for the layout to settle. 3 runs out of 3 pass |
| Screenshots | Real main window at now, +3, +6, +9 and +13 h, checked by eye |
| Needs your desktop | How it looks and feels; the emoji drop with your colour emoji font; whether an hour a second is right |

## 1.17.0: clouds follow the real wind

Measured on the real animated scene by advancing its clock in 1/24 s frames.

| Check | Result |
|---|---|
| Measured speed and direction (front clouds) | 0 km/h from W: right, crosses in 150 s · 10 km/h from W: right, 70 s · 20 km/h from E: left, 50 s · 40 km/h from NW: right, 40 s (80% of full) · 80 km/h from W: right, 21 s · 150 km/h from E: left, 19 s (capped). Each within 1% of the design |
| From/to conversion | Checked for every whole degree from 0 to 359; Open-Meteo (from 225 → right) and MET Norway (from 90 → left, m/s → km/h) taken through to the scene |
| Main window (640 px) vs widget (300 and 220 px) | Same crossing time, within 1% |
| Calm and north/south winds | Still drifting (visible movement in 5 s) |
| Strong wind | Capped at 19 s per crossing, 1.4 px per frame |
| Refresh: 10 km/h W → 60 km/h E | No rebuild and no movement at the moment of the refresh; every frame matched the easing formula; largest single cloud step 1.05 px; turned round after 2.0 s; 95% of the new direction and speed after 9 s |
| Rain, snow and fog when the wind reverses | Turn smoothly (largest change per frame under 0.1); with a steady wind, exactly as before |
| Sun, Moon and mini forecast | Identical with 0 km/h from W and 90 km/h from E |
| Real app (fake server) | The forecast's 18.7 km/h from 225° reaches both the main window and the widget; a refresh to 55 km/h from 80° eases in on both together |
| Bug found and fixed | The first real forecast eased in from the placeholder wind for about 10 s (the window and the widget disagreed); now shown at once, with a regression test |
| Deliberate mistakes in the code | From/to backwards: 11 tests failed · no easing: 4 · fixed pixel speeds: 1 |
| CPU | Easing 0.0015 ms per frame. Window and widget animating: 1.16.0 31.3%, 1.17.0 28.8% (average of 3 runs each), the same within run-to-run variation |
| Rendered frames | Checked by eye: slow drift right at 5 km/h from W, faster movement left at 60 km/h from E; Sun and Moon unchanged |
| Needs your desktop | How the speeds feel on your screen, and a real refresh where the wind changes |

## 1.16.0: lock position for the desktop widget

All widget checks use real mouse press, move and release events.

| Check | Result |
|---|---|
| Unlocked widget dragged 80 × 40 px | Moved exactly 80 × 40; new position saved |
| Locked widget dragged 120 × 60 px | Didn't move; the lock and its position were saved; the tooltip says it's locked |
| Unlock, then drag | Moves again |
| Lock during a drag | The drag stops where it is |
| Locked: double-click, Size, Keep on top | All still work |
| Widget off and on / restart | Still locked, at the same spot; dragging still ignored |
| Locked at an off-screen position | Brought back onto the screen, still locked |
| Lock removed from the code on purpose | 2 tests failed, so the tests do catch it |
| Needs your desktop | Cinnamon's Alt + drag moves windows through the window manager, which WeatherDesk can't block. A locked widget moved that way isn't saved, so it returns to its spot at the next start |

## Test fix: `test_net` socket-leak check

This test was last changed in 1.13.0, and the code it covers is unchanged.

| Check | Result |
|---|---|
| What failed | Once in a full suite run: 14 open descriptors against a baseline of 13. Also 1 time in 5 when run on its own, and about 2 times in 300 in a recording loop |
| What the extra descriptor was | A socket that closed by itself about 50 ms after the 2-second wait, with no WeatherDesk code running |
| Why it isn't a WeatherDesk leak | The connection function runs on one thread and closes every socket except the one it returns, before returning |
| Cause | The test's fake server, in the same process, closing its own end late |
| Fix | Count only WeatherDesk's side of the connections; the wait wasn't lengthened |
| Proof | A new test leaks 5 connections on purpose and checks they're counted; the leak test then passed 150 runs out of 150 |

## 1.16.0: every location updates at startup

| Check | Result |
|---|---|
| Restart with 4 saved locations | All 4 updated once. The selected one came first; the others followed in saved order, 1.47–1.59 s apart (3 runs). The whole round took about 4.6 s |
| Restart within 2 minutes | Only the selected location updated (the others were already fresh) |
| Setting off | Only the selected location updated. The menu tick and the saved setting agree |
| Turned off mid-round / location removed mid-round / window closed mid-round | Round stops / that location is not fetched / no further requests and no crash |
| Boot without network (server failing), then the network comes up | Each other location retried; all updated once the network was back; no errors left |
| Network never comes up | Each other location tried 5 times (first try + 4 retries), then left with its saved forecast on screen |
| Test failure during development | One test saw 4 tries instead of 5. The cause was a race in the test (it checked "finished" before the round had started), not in the feature. Fixed in the test; the test then passed 3 runs out of 3 and the full suite passed |
| Needs your desktop | A real boot with "Start at login" on, especially with Wi-Fi joining late |

## 1.15.0 audit results

| Check | Result |
|---|---|
| Damaged replies, 300 per parser × 8 parsers (wrong types, missing parts, `Infinity`, huge numbers, deep nesting) | **0 crashes.** Open-Meteo 283 usable / 17 clean errors · MET Norway 278/22 · OpenWeather One Call 295/5 · OpenWeather free 266/34 · WeatherAPI 287/13 · Visual Crossing 298/2 · Tomorrow.io 288/12 · Weather Underground 285/15. Before the fixes: `OverflowError` escaped (stopping the backups) and "feels like" could be infinite. Seeds 2–6 also run by hand: 0 crashes |
| Non-JSON replies (`null`, `[]`, `""`, `42`, unexpected object) to every parser | All clean errors |
| Any unexpected exception in a provider (RuntimeError, OverflowError, ZeroDivisionError, RecursionError) | Logged, shown as "sent data WeatherDesk couldn't use (…)", next backup used |
| API key in an unexpected error, `--diagnose` warnings, providers dialog | Masked / masked / shown as plain text (HTML-escaped) |
| Keyring lookups for 20 dialog refreshes × 2 providers | 1 lookup (cached); a failing keyring is asked again each time, so unlocking it later works |
| Secrets in the package and source archive (a planted `keys.json`, `.key` and `.env` in the build copy) | None shipped |
| Git history | No real keys (only the obvious fake test keys in `tests/provider_fixtures.py`); `.gitignore` covers `keys.json`, `*.key`, `.env*`, `providers.json`, `dist/` |
| Soak: 60 s, 233 steps of tab cycling, globe zoom, forced refreshes, unit switching, desktop widget on/off | Memory flat (802 MB at start, at ⅓ and at end; the figure is high because the whole suite shares one process and its image caches). Threads 2 (base 5), open files 8 (base 8). A 40 s run on its own: 336 MB flat |
| Idle CPU, window open (sandbox, software rendering) | Animations on: 15–17% of one core on the Forecast tab, 17–20% on the rotating globe. **Animations off: 0.5%**, so all of it is the animated scene, which already pauses when hidden or minimised. No change made |
| Fast Moon transit vs its slow reference scan, 40 dates and longitudes | Within 5 s (the reference had never been used by a test) |
| Dead-code scan (`pyflakes`, `vulture`) | Removed: the 1.12 two-source client logic, `ProviderManager.backup`, `render_for_phase`, `MOON_CLEARANCE`, unused imports. Remaining hits checked: Qt event methods and test-only helpers |

### Real install, upgrade and rollback (dpkg on the build machine)

| Step | Result |
|---|---|
| Profile created by the **installed 1.11.1** code (2 locations, °F, 12-hour, 60-minute refresh), then 1.14.0 code added a provider chain (Weather Underground → Open-Meteo → MET Norway), a Station ID and two API keys (private-file store) | — |
| `dpkg -i weatherdesk_1.15.0_all.deb` over installed 1.11.1 | Upgraded cleanly; `apt-get check` clean; the profile's files byte-for-byte unchanged by the upgrade |
| Installed 1.15.0 reads the profile | Locations, units, time format, refresh, provider chain, Station ID and both keys all intact; key file still 0600 |
| Launch the installed app (offscreen, 15 s) | Started; tried Weather Underground, then both backups (all blocked here), showed the error; no traceback; no key in the log, settings or status file; settings still intact after it saved on exit |
| `dpkg --purge` | Program files and launcher removed; user profile untouched |
| Clean install with `apt-get install ./weatherdesk_1.15.0_all.deb`, empty profile | Installed with dependencies satisfied; app started and exited with code 0 on a stop signal; no traceback |
| `weatherdesk --version` / `--diagnose` | "WeatherDesk 1.15.0 – Created By Shane BlackbuRn" / ran every check and gave a clear "no provider could be reached" summary |
| Rollback: `dpkg -i weatherdesk_1.11.1_all.deb` over 1.15.0, run it | Runs; locations, units and keys kept, but **1.11.1 dropped the provider chain and Station ID** when it saved. That can't be fixed in 1.11.1; it's documented in the README. **1.15.0 now keeps settings it doesn't know**, so rolling back from a future version won't lose them (regression test added) |
| Final .deb: upgrade again from 1.11.1, profile with provider chain, Station ID, keys and a made-up "future version" setting; run the app | Upgraded cleanly; app ran with no traceback; after it saved on exit, every setting including the unknown one was still there; both keys intact; no key in the log or status file |

## What's covered

| Suite | Tests | Covers |
|---|---|---|
| `test_core` | 39 | Units, weather codes, parsing robustness, HTTP error paths, settings, atomic writes, cache |
| `test_net` | 17 | Fast connections with a dead first address; refused, all-dead and no-address cases; no socket leaks; the regression for the slow-loading bug; the connection test report, dialog and `--diagnose` flag |
| `test_tls` | 21 | Secure-connection faults: the reported handshake stall reproduced and recovered; bounded failure time; full read timeout kept; no retry for certificate or HTTP errors; address ordering and expiry; small segments applied; corrupt health file; a **path-MTU black hole simulated with a network namespace and veth** (fails without the fix, recovers in about one stall limit, then about 4 ms per request; remembered across restarts; diagnostics explain it); GUI shows weather, not an error |
| `test_scene` | 28 | Every weather code at day, dusk and night; day/dusk/night maths; sun position; clock moving on since download; wind direction; hemisphere; moon phase against known dates; paint-time limit; 10 simulated minutes of animation; lightning only in storms; rain slant; sprite cache limit; icons; animation clock pausing; desktop widget behaviour and persistence; off-screen recovery; toggle leak check |
| `test_moon` | 38 | Moon rise/set against 120 PyEphem reference days in 4 cities; illumination (167 samples); new/quarter/full times (48); phase names; the 7-day view; polar always-up/down; timezones; rendering (lit area matches illumination, hemisphere orientation, earthshine, numpy and pure Python agree, cache, missing texture, bad metadata, size limits); NASA converter landmark placement; Moon tab (data, location switch, 10-minute refresh limit, rows never overlap at 3 window sizes, NASA credit, 2048 px save, save failure); night-scene moon |
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
| `test_metno` | 29 | MET Norway parsing, the provider chain with Open-Meteo, fallback messages, diagnostics for each provider |
| `test_providers` | 60 | All seven providers: parsing, units, time zones, keys (keyring and private file, redaction), fallback, recovery modes, quota guard, usage, the dialog, Weather Underground stations |
| `test_robustness` | 3 | 2,400 damaged replies across 8 parsers; undamaged samples still parse; non-JSON replies |
| `test_audit` | 20 | A regression test for every 1.15.0 fix (see CHANGELOG) |
| `test_packaging` | 8 | Builds the .deb and source archive from a copy; control fields and dependencies; every module and asset packaged and identical; launcher, menu entry, icon, docs; no caches or secrets; nothing touches `~/.config`; checksums; the packaged copy imports and reports its version |
| `test_soak` | 1 | 60 s of mixed use: memory levels off, threads and files don't grow, idle CPU (length set with `WD_SOAK_SECONDS`) |

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

**Live weather services. These are the most important checks.** Each needs
your key, then **Test connection** in Settings → Weather Providers, then one
update with that provider as primary:

* **Tomorrow.io**: now asked *without* the `timesteps` parameter. Check that
  the forecast still has both hourly and daily data (the chart and 5 days).
* **OpenWeather**: with a One Call 3.0 subscription (8 days, hourly) and
  with a plain free key (5 days from the 3-hour list, partial last day left
  out).
* **WeatherAPI.com** and **Visual Crossing**: field names and units against
  the live reply.
* **Weather Underground**: your own station by ID, the nearest-station
  search with no ID, an offline station, and the after-3 pm day/night switch.
* **Open-Meteo and MET Norway** live: confirmed by you on earlier versions;
  re-check that 1.15 loads them.
* **Rate limits and 429 handling** with real quotas, and the usage figures
  the dialog shows (for example Tomorrow.io's requests left).

**Your desktop:**

* **GNOME Keyring**: saving, reading after a restart, and a locked keyring
  at login. Here there was no D-Bus, so only the private-file store and a
  fake keyring were tested.
* Idle CPU with animations on, on your hardware (about 15% of one core here,
  software rendering).

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
