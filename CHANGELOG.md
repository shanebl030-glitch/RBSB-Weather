# WeatherDesk Changelog

Created By Shane BlackbuRn

## 1.13.0 – 2026-11-17 (on branch claude/weatherdesk-1.12.0; not released)

### Added
- **Settings → Weather Providers** (Ctrl+,): a provider manager.
  - **Choose any integrated provider** as the primary, and any number of
    **backups** in order. If the primary can't supply the weather, the next
    backup is tried automatically.
  - **Recovery**: return to the primary at the next update, after
    15/30/60 minutes (30 is the default), or stay on the backup until it fails.
    There's also a *Use the primary now* button.
  - For each provider: status (working / not working / needs a key / not used
    yet / planned), coverage, forecast length, hourly data, free allowance
    and limits, the values it supplies, what WeatherDesk calculates for it,
    last successful update, last problem, usage it reports, and sign-up and
    documentation links.
  - **API keys**: add, change or remove; **Test connection** shows the result
    (and can test a typed key before saving it). It also shows which provider
    is **currently supplying the weather**; the status bar says "from …
    (backup)" and credits the provider in use.
- **New providers, each fully integrated and tested** (they need your own free
  API key):
  - **OpenWeather**: One Call 3.0 (8 days, 48 h hourly, UV). It falls back to
    the plain free key (current + 5-day/3-hour) automatically when the account
    has no One Call subscription.
  - **WeatherAPI.com**: 3 days on the free plan (14 on paid), hourly, UV.
  - **Visual Crossing**: 15 days (7 used), hourly; one forecast costs 1 of
    the 1,000 free daily records.
  - **Tomorrow.io**: 5 days and 120 hours. It shows the requests left today
    and this hour.
- **Planned, not yet integrated** (listed in the dialog with the reason):
  AccuWeather (paid-only after a 14-day trial, plus an extra location-key
  call per update) and Weatherbit (50 requests a day on the free plan, no
  hourly data).
- **Extensible design**: each provider is one module in
  `weatherdesk/providers/` registered with `@register`. The rest of the app
  only uses the `ProviderManager`. See "Adding a weather provider" in the
  README.

### Data compatibility
- Every provider is converted into WeatherDesk's existing forecast format:
  WMO weather codes, °C, km/h, mm, hPa, % and the location's local time.
  Code tables are included for OpenWeather, WeatherAPI.com, Visual Crossing
  and Tomorrow.io.
- A shared normaliser then:
  - calculates sunrise/sunset, day/night and "feels like" only where a
    provider leaves them out;
  - works out an unknown condition from cloud and rain;
  - fills a day's condition and rain chance from its hours;
  - clamps percentages, drops impossible values, and sorts and limits the
    days.

  Anything that can't be worked out exactly shows "–", never a guess.
  Calculated values are listed per provider in the dialog.
- The scene, icons, Sun and Moon, mini forecast, chart, 7-day list, tray and
  desktop widget work unchanged with every provider (tested for each one).
  Providers with fewer than 7 days show the days they have.

### Security
- Keys are stored in the **system keyring** (Secret Service: GNOME Keyring /
  KWallet) when `python3-keyring` is available (now a recommended package).
  Otherwise they go in `~/.config/weatherdesk/keys.json`: folder 0700, file
  0600, written atomically, and tightened again if the permissions are ever
  loosened.
- Keys are never stored in `settings.json`, the forecast cache or the
  provider status file, and never appear in the window. Once saved, a key
  shows only as "Saved ••••••••". The key field is masked, with an optional
  "Show while typing", and is never pre-filled.
- A logging filter removes saved keys, and any `key=`, `appid=`, `apikey=` or
  `token=` value, from every log line, tracebacks included. Error messages
  are cleaned too: Visual Crossing echoes the key back in its errors. The
  connection test report shows only "key saved (not shown)".
- `.gitignore` refuses `keys.json`, `*.key` and `.env` files; the source
  archive excludes them as well.

### Changed
- View → Weather source (1.12) is replaced by Settings → Weather Providers.
  A 1.12 choice of "MET Norway first" carries over as the provider order.
- Help → Test connection checks every provider in your order: the
  connection, the secure handshake and a real forecast.
- Messages for a rejected key (HTTP 401/403) and a reached usage limit
  (HTTP 429, or a "quota" reply) name the provider and say what to check.
- Quota guards: Tomorrow.io is asked at most every 10 minutes per location,
  and OpenWeather and Visual Crossing at most every 5. A refresh in between
  shows the forecast already downloaded.

### Tests
- New `test_providers.py` (54 tests). Each provider is served by the local
  fake server in its documented response shape (`provider_fixtures.py`).
  Covered: conversion and units, code tables, unknown codes, bad key and
  usage limit (with the key never echoed), garbled data, missing key,
  fallback order, all four recovery modes, quota guards, the status file,
  Test connection, the normaliser, key storage (file permissions, system
  keyring, insecure keyrings refused), log redaction, settings migration,
  diagnostics, the whole window driven by every provider, and the Settings
  dialog (key add/change/remove never shown, test results, order and
  recovery saved, warnings, primary now).
- The full suite has 379 tests. As before, `test_sky`'s zoom-glide test is
  timing-sensitive on a busy machine; it fails the same way on 1.11.1.
- **Not tested against the live services**: the build environment can't
  reach them. Each integration follows the provider's current
  documentation; Test connection with a real key is the live check.

Created By Shane BlackbuRn

## 1.12.0 – 2026-11-17

### Fixed
- **"Couldn't update: The secure connection to the weather service timed out"
  and the weather stopping.** Shane's Waiuku connection still stalls on
  Open-Meteo's forecast server (`api.open-meteo.com`) even with the 1.2.2
  small-packet fix. WeatherDesk now keeps updating anyway:
  - **A second weather source: MET Norway** (the Norwegian Meteorological
    Institute, behind yr.no). It's free, with no account or key, and runs on
    different servers and a different network route. If Open-Meteo can't be
    reached (or returns a server error), the forecast comes from MET Norway
    with no error shown. For the next 30 minutes WeatherDesk goes straight to
    the working source, so updates don't wait out the failing one first.
  - **Two retries that try harder** instead of one: small packets (MSS 1000),
    then the smallest (MSS 536) with 2.5× longer (15 s) for the secure setup,
    for a link that is slow rather than blocked. What worked is remembered.
  - **Quicker retries after a failed update**: 30 s, then 1, 2 and every
    5 minutes (was a fixed 5 minutes), while auto refresh is on.
  - **A calmer message** while recent weather is still on screen: it says
    how old that weather is and that it's retrying, in normal text. The bold
    warning is kept for weather more than 3 hours old.

### Added
- **View → Weather source**: *Open-Meteo (MET Norway as backup)*, the
  default, or *MET Norway (Open-Meteo as backup)*. Saved with your settings.
- The status bar credit shows which service the weather on screen came from.
  About and the user guide credit MET Norway.
- **Help → Test connection** also tests MET Norway (connection, secure
  handshake and a real forecast download), and says when the backup is what
  keeps the weather updating.

### MET Norway details
- Times converted from UTC to the location's time zone; m/s to km/h; MET's
  weather symbols to the app's weather codes (sleet is shown as snow).
- "Feels like" uses the same formula as Open-Meteo. Sunrise and sunset are
  calculated on your computer (within a minute of the Sun's true position).
- Today's high and low cover the rest of today only, and the UV index is the
  clear-sky value. Requests follow MET's terms: an identifying User-Agent,
  at most 4 decimals in coordinates, and no more often than every 30 s.

### Tests
- New `test_metno.py` (30 tests): symbol mapping, sunrise/sunset (checked
  against the Sun's computed position, plus polar day and night), parsing
  with MET's real response shape, the cache round trip, the automatic
  backup in both directions, both sources down, diagnostics, smaller
  packets and the health file (old format still read), the retry back-off,
  the calmer message, and the source menu.
- The "only route stalls" test now expects three attempts.
- The fake server also serves a MET Norway endpoint.
- The full suite has 325 tests. `test_sky`'s zoom-glide test is
  timing-sensitive on a busy machine; it fails the same way on 1.11.1.

Created By Shane BlackbuRn

## 1.11.1 – 2026-11-16

### Changed
- **The mini forecast stays fixed in the bottom-right corner**, as
  requested. It no longer moves left or drops days when the Sun or Moon
  reaches that corner. The Sun and Moon now **pass behind it** as they set:
  it's drawn on top of them, over its existing soft translucent shade.
- The number of days still adapts to the scene's size, as in 1.11.0. It
  only changes when you resize, never because of the Sun or Moon.
- The Sun and Moon arcs, timings and drawing are unchanged. Everything else
  in 1.11.0 is unchanged.

### Tests
- New: over a full simulated day (51 frames), the forecast keeps one
  position and one day count. The Sun and Moon are in identical places, with
  identical progress, with and without the forecast. Every pixel outside the
  forecast's shaded area is identical too. The Sun and Moon passed behind it
  in 32 frames.
- New: when the Sun is behind the forecast, the forecast's icons are drawn
  on top.
- The "steps aside" test was replaced, because that behaviour was removed
  on request. A small test keeps `plan()`'s optional circle-avoidance
  working, although the scene no longer uses it.
- A test helper now clears its image before painting. Without that, unset
  corner pixels made identical frames compare as different.

Created By Shane BlackbuRn

## 1.11.0 – 2026-11-16

### Added
- **A mini forecast inside the weather scene**, in the bottom-right corner of
  both the top card and the desktop widget. The Sun and Moon stay the
  centrepiece. For each day it shows:
  - the day's name ("Today", "Tomorrow", then "Wednesday" or "Wed" depending
    on space);
  - an **animated weather icon**;
  - the **high** (bold) and **low**;
  - the **chance of rain**, with a small drop symbol, when the forecast
    includes it.

  It's drawn straight onto the sky with a soft, feathered shade for
  readability (not a separate panel), using the same animation clock as the
  sky.
- **Adaptive, 1–7 days:**
  - The number of days is worked out from the scene's real size. Small
    scenes are capped at 2 days, medium at 5, and large at 7.
  - A day is shown only if it fits at a readable size: text is at least
    9.5 px and icons at least 18 px. Text is never squeezed to fit more.
  - Long day names are used when there's room, otherwise short ones.
  - Fonts, icons, spacing and the day count are recalculated whenever the
    scene is resized: the window, or the widget's small/medium/large size.
- **Never overlaps:**
  - It stays to the right of the scene's own text, measuring where the
    words actually are: place, temperature, description and local time in
    the card; place, temperature, conditions, high/low and the ↻ time in
    the widget.
  - The Sun and Moon rise and set through the bottom corners. When one
    passes through the forecast's corner, the forecast steps to its left
    (with fewer days if needed) and moves back once it has set. It's hidden
    only if not even one day fits.
- **Data:** it uses the forecast WeatherDesk already downloads from
  Open-Meteo, with no extra requests. Days run from "today" at the location.
  It updates with each refresh, when you change location, and with the
  temperature unit.
- **Animated icons:**
  - sunny: rotating rays;
  - partly cloudy: the sun with a drifting cloud;
  - cloudy: drifting clouds;
  - drizzle and rain: falling drops;
  - **heavy rain** (new): more, faster drops;
  - thunderstorms: occasional lightning;
  - snow: falling flakes;
  - fog: drifting bands;
  - **windy** (new): sweeping gusts, for dry days with a maximum wind of
    40 km/h or more.

  Each day's icon is offset in time so they don't move in lockstep. The
  heavy-rain change also shows in the 7-day list's icons.

### Unchanged
- The Sun and Moon arcs, their real rise/set times, daytime Moon
  visibility, the scene's weather effects, the card's text, the desktop
  widget's features, and all other tabs. A test confirms the Sun and Moon
  are drawn in exactly the same place with and without the forecast.

### Tests
- `test_forecast_strip.py` (17 tests):
  - day names, values taken from the downloaded data in order, past days
    skipped, temperature text and units, and when the windy icon applies;
  - size classes (small 2, medium 4, large 7 days), and 1–7 days with
    never more than are available;
  - a 224-size resize sweep: inside the scene, never over text, readable,
    never fewer days with more room, cells side by side, names not clipped;
  - bottom-right placement;
  - Sun and Moon sweeps along the whole arc: the forecast never overlaps
    the disc and steps aside when needed;
  - every icon kind drawing and animating, with heavy rain, windy and
    thunder variants;
  - the top card and the desktop widget showing the forecast and following
    the location and unit;
  - window-resize adaptation (3/5/7/7 days at 900/1100/1400/1800 px);
  - the Sun and Moon unchanged with the forecast on, and the frame cost
    (about 4–6 ms);
  - hidden with no data.
- The full suite has 293 tests, all passing (2 skipped, as before).

Created By Shane BlackbuRn

## 1.10.1 – 2026-11-16

### Changed
- **The Moon is visible in daytime when it's really above the horizon.**
  - Before, it was only drawn at night (it faded out as daylight rose), even
    when it was up.
  - Now it's shown whenever its real position says it's up, by day or night,
    so the Sun and Moon often appear together, each on its own arc with its
    own rise and set times. It's hidden when it's below the horizon.
  - By day it's drawn like the real daytime Moon: paler (70%), with no night
    glow. Its unlit side isn't drawn as a dark disc against the blue sky,
    because "screen" blending lets the dark part vanish. This cross-fades
    smoothly through twilight. The night-time Moon is unchanged.

### Tests
- `test_arc.py`: the old "Moon only at night" test was replaced (that
  behaviour was intentionally removed) by 5 tests:
  - the daytime Moon visible on its arc, brighter than the sky on its lit
    side, with no dark blob on its unlit side;
  - the Sun and Moon together, each exactly on its own arc and moving at
    its own speed;
  - the Moon disappearing below the horizon by day, at dusk and at night
    (just after setting, before rising, and when down);
  - the night Moon unchanged;
  - visibility taken from the Moon's real altitude rather than the time of
    day: up at noon is shown, down at night is hidden.

Created By Shane BlackbuRn

## 1.10.0 – 2026-11-16

### Changed
- **Sun and Moon arc in the weather scene** (the top card and the desktop
  widget), following Shane's sketch. Both follow one path:
  - they rise from just below the horizon at the bottom left, so they
    emerge gradually;
  - they climb to the top middle halfway through their time in the sky;
  - they sink and disappear below the bottom right as they set.
- The **Sun's** place comes from the real sunrise and sunset times for the
  location. The **Moon's** comes from its real moonrise and moonset for its
  current trip across the sky. That's a new `moon.moon_pass()`, which agrees
  with the Moon tab's times to the second.
- Positions are worked out from the clock at every frame, so they glide
  instead of stepping each minute. By day the Sun is shown, and at night the
  Moon (only while it's really up).
- Before this, the Sun's arc started part-way up the left side and the Moon
  sat at a fixed spot on the right, with only its height changing.

### Tests
- `test_arc.py` (9 tests):
  - the path shape: starts and ends fully below the horizon, left and
    right, highest in the middle with the disc inside the scene,
    symmetrical, left to right, smooth, and gradual emergence;
  - Sun progress from the real sunrise and sunset;
  - `moon_pass` matching the Moon tab's rise and set times (worst 0 s over
    20 passes in 3 cities), and returning nothing while the Moon is down;
  - the Sun drawn exactly on the arc at 5 times of day, moving under 1 px a
    minute, and gone after sunset;
  - the Moon on the same arc, and gone after moonset;
  - only the Sun by day and only the Moon by night;
  - real times taken from the forecast.
- The full suite has 272 tests (2 skipped, as before).

Created By Shane BlackbuRn

## 1.9.0 – 2026-11-16

### Added
- **12/24-hour clock option**: **View → Time format** → 24-hour (19:30) or
  12-hour (7:30 pm). Every clock time follows it:
  - local time at the location, sunrise and sunset;
  - the 24-hour chart's hour labels ("7 pm");
  - the status bar ("Updated 5:27 pm");
  - the Moon tab: rise and set, upcoming phases, "shown at its highest", and
    the 7-day strip;
  - both Earth tabs: the location card, the info line and the cloud time;
  - the desktop widget's ↻ time.

  It switches instantly, with no download, and is saved. 24-hour stays the
  default, so nothing changes until you pick 12-hour.
- All clock formatting now goes through one place (`units.fmt_clock`,
  `fmt_iso_clock` and `fmt_hour_label`), so no time can be missed.

### Tests
- `test_timefmt.py` (6 tests):
  - both formats at midnight, noon, morning, afternoon and 23:59, with and
    without the day;
  - ISO strings, including bad ones, and chart labels;
  - the global switch ignoring bad values;
  - saving and validating the setting (a non-string or unknown value falls
    back to 24);
  - switching updating every view: hero, details, status bar, Earth card
    and info line, the widget, every Moon tab time, and chart labels, all
    without re-downloading, then back again;
  - the choice remembered after a restart.
- The full suite has 263 tests (2 skipped, as before).

Created By Shane BlackbuRn

## 1.8.1 – 2026-11-16

### Changed
- The desktop widget's last-updated time (↻ HH:MM) moved to the **top-right
  corner**, beside the place name, as requested. It keeps its dark pill
  background, so it stays readable over clouds.

### Fixed
- **A rare crash when a window closes while a background download finishes.**
  The full test suite segfaulted once in the window open/close stress test.
  The crash trace showed a background thread emitting a forecast result
  through the window's signal "bridge" while that window was being destroyed.
  Deleting a Qt object while another thread uses it is undefined behaviour.
  - The bridge no longer belongs to the window. When the window closes, the
    bridge is "retired": its signals are blocked, so nothing reaches the
    closed window. It's deleted only once its worker threads have all
    finished.
  - On your desktop this mainly mattered when quitting during an update.
- **Launches that gave up waiting could crash or close the running
  WeatherDesk.** If the running copy was busy or suspended and you launched
  it again, the new launch gave up after 3 tries, but its request stayed
  queued. When the running copy caught up:
  - it could crash: a socket was deleted inside its own signal. This was
    found by the "busy copy" test, about 1 run in 25;
  - a queued "newer version" request made it quit for a launch that had
    already moved on.

  Now each socket is deleted only from the event loop, and actions run after
  its signal returns. A request whose sender has already hung up is ignored:
  the app checks with a non-blocking peek at the socket.

### Tests
- New `TestCloseRace` stress tests:
  - 40 windows closed while forecast and Earth results are arriving at
    varied moments;
  - 15 windows destroyed while a thread floods signals through their
    bridges;
  - all retired bridges are released afterwards.
- The window-cycle stress test was run repeatedly after the fix (results in
  TEST_REPORT.md).
- New `test_abandoned_requests_while_busy_are_harmless`: 25 abandoned
  requests (half claiming a newer version) are queued while the running copy
  is paused. It must survive, keep answering normal launches, log that it
  ignored them, and exit cleanly. 1.8.0 fails this test 3 times out of 3;
  1.8.1 passes it.
- Two timing-sensitive tests were tightened: the globe-turn test now waits
  for the turn animation to end, and the Moon "in the sky" wording check is
  now an exact pattern.
- The widget-line test now also checks that the time sits in the top
  quarter against the right edge, and doesn't overlap the place name, at all
  3 sizes.
- Fixed a time-dependent test bug found in this run. One Moon tab test
  accepted only two of the three "In the sky" wordings, so it failed whenever
  the Moon was below the horizon when the tests ran. The app was correct. The
  test now checks all three exact formats with a pattern, which is stricter
  than before.

Created By Shane BlackbuRn

## 1.8.0 – 2026-11-15

### Added
- **The desktop widget shows when it was last updated**, as **↻ 19:30** in
  the bottom-right corner (moved to the top right in 1.8.1).
  - It sits on a soft dark pill, so it's readable over clouds or a sunny sky.
  - It says "updating…" during an update.
  - It turns amber with how long ago (for example "(2 h ago)") when the data
    is older than two update intervals, the last update failed, or it's a
    saved copy while offline.
  - Hover over it for the full time, the interval and any problem.

### Fixed
- **Reliable updates every 30 minutes** (or whatever you choose).
  - Before, updates relied only on Qt's interval timer, which doesn't count
    time while the computer is asleep. After waking, the widget could show
    hours-old weather for up to another 30 minutes, and a failed update
    waited a whole interval to try again.
  - Now a once-a-minute check goes by the wall clock: when the weather is
    older than the interval, it updates. It catches up within a minute of
    waking, and works while the window is closed to the tray.
  - A failed update is retried after 5 minutes, without hammering the
    server. The interval timer restarts after each catch-up, so there are
    no double updates.

### Tests
- `test_refresh.py` (10 tests):
  - 30-minute default and both timers running;
  - nothing at 28 minutes, an update at 30, then nothing until the next one;
  - catching up after 3 hours asleep, with the interval timer restarted;
  - a failed update not repeated within 5 minutes, then retried, with the
    widget warning cleared;
  - "never" means never;
  - a 60-minute interval;
  - the widget line's time, tooltip, and placement at all 3 sizes;
  - "updating…" and the old-data warning;
  - a saved copy and an empty widget;
  - the line appearing straight away when the widget is opened later.
- The full suite has 254 tests, all passing (2 skipped, as before).

Created By Shane BlackbuRn

## 1.7.1 – 2026-11-15

### Fixed
- **Choppy zooming on the Earth Globe.** Each zoom step used to redraw the
  whole globe, at up to about 120 ms a step. Zooming now glides smoothly
  over 0.18 s:
  - each frame just scales the current picture (about 10 ms);
  - the globe is redrawn sharp once, when the zoom settles;
  - the Sun and Moon pictures are reused while it moves.

  Touchpad scrolling zooms in small, gradual amounts.

### Changed
- **Bigger Moon** behind the globe: twice the previous size (about 0.64 of
  the globe's radius across, up to 360 px). It's drawn from the NASA CGI
  Moon Kit images (2048 px) at screen resolution, so the craters and maria
  are sharp. It's turned with the view rather than redrawn, so turning the
  globe stays smooth.
- **A larger, more realistic Sun:**
  - a limb-darkened disc (whiter in the middle, warmer at the edge);
  - a bright corona and a wide warm glow;
  - a soft camera-style starburst.

  When the Sun is just behind the Earth, its light now blazes round that
  edge, like a sunrise seen from orbit. The Sun picture is built once per
  size step and reused.

### Tests
- `test_sky.py` gained 2 tests and has updated zoom tests:
  - zoom glides with no globe redraws mid-glide and one redraw at the end;
    the worst frame was 11 ms over 11 frames, and the Sun picture wasn't
    rebuilt;
  - the Moon is drawn at screen resolution, twice the old size, with no
    re-render mid-zoom and one sharp re-render afterwards;
  - touchpad fractional steps;
  - zooming several steps in a row.
- The full suite has 244 tests, all passing (2 skipped, as before).

Created By Shane BlackbuRn

## 1.7.0 – 2026-11-15

### Added
- **The real Sun, Moon and stars behind the Earth Globe**, where they
  actually are right now.
  - As the globe turns, the Sun slides across the background and sets
    behind the Earth exactly as the middle of the view goes into night. Just
    behind the edge, its glow spills round the globe like a sunrise seen
    from orbit.
  - The **Moon** shows its real phase, from the same NASA-based Moon images
    as the Moon tab. Its lit side faces the Sun, and its north is turned to
    match the view.
  - **Stars** are fixed in space and wheel past as the globe turns.
  - When the Sun or Moon is out of view, a small marker at the window edge
    shows which way it is. Hover over it to see whether it's off-screen or
    "behind you".
- **Zoom on the Earth Globe**, from 60% to 300%:
  - the mouse wheel;
  - **−** / **+** buttons with a percentage in the top-right corner;
  - the **+** and **−** keys, and **0** to reset.

  Zooming draws a quick preview, then sharpens after a quarter of a second.
  The location card hides when its place is zoomed off-screen.

### Changed
- The globe can now be drawn up to 1300 px across. The Earth maps hold no
  finer detail, so larger zooms are scaled up from that.
- The globe's cached drawing grids use about half the memory (32-bit) and
  are limited to 3 sizes.

### Tests
- `test_sky.py` (11 tests):
  - projection: straight behind, behind the camera, the edge exactly at the
    view angle, and which side east and north fall;
  - the Sun reaching the globe's edge exactly in step with day and night;
  - the Moon's lit side facing the Sun on screen (worst 0.00°), checked in
    the rendered pixels too;
  - stars turning with sidereal time, with numpy and pure Python agreeing;
  - the Sun drawn at the computed spot and hidden (with an edge hint) when
    facing the day side;
  - the Moon's phase matching the Moon tab, and hidden when straight behind
    the Earth;
  - the sky moving as the globe turns, and paint time;
  - zoom with the wheel, buttons and keys, its limits and the sharpening;
  - the render size cap and the memory limit;
  - the card hiding off-screen, and marker clicks while zoomed.
- The full suite has 242 tests, all passing (2 skipped, as before).

Created By Shane BlackbuRn

## 1.6.0 – 2026-11-15

### Added
- **Live clouds** on Earth Flat and Earth Globe: a near real-time global
  cloud map from weather-satellite images, updated every 3 hours.
  - Clouds are white on the day side. On the night side they hide the city
    lights underneath (with a faint glow, so they're still visible).
  - The line above the map gives the time of the satellite map being shown.
  - A **Live clouds** tick box in both Earth tabs. It's on by default, the
    two boxes stay in step, the choice is saved, and the Earth redraws
    straight away.
- The cloud map is downloaded in the background through the same connection
  code as the weather:
  - It's checked at most once an hour, and only while an Earth tab is open.
    A check uses a conditional request, so an unchanged map isn't
    downloaded again.
  - It's cached in `~/.cache/weatherdesk/`, so the last map is used offline.
  - After a failure, the next attempt waits 15 minutes. Downloads are capped
    at 8 MB, with a 30 s timeout and one retry.
  - A download that isn't a valid 2:1 image never replaces the cached one.
  - If the clouds can't be drawn, the Earth is still drawn without them.
- Credits: Live Cloud Maps by Matt Eason (CC0), "Contains modified EUMETSAT
  data". They're shown in both Earth tabs, the About box, the User Guide,
  the README and the package copyright file.

### Tests
- `test_clouds.py` (17 tests):
  - downloading, a 304 not-modified re-check, and a newer map;
  - the 1-hour and 15-minute schedules;
  - garbage, HTTP 404 and oversize downloads keeping the cached map;
  - a wrong-shaped image;
  - an unreachable server, and a stalled server (gives up in 1 s at a
    0.5 s timeout);
  - a corrupt cache;
  - the haze/thick-cloud curve;
  - white cloud by day, with the map unchanged outside the cloud;
  - city-light contrast under cloud at night (208 → 21);
  - both tick boxes in step, saved, redrawing, and no re-download from cache;
  - offline with no cache (the Earth is still drawn);
  - only one download across repeated redraws;
  - closing the window during a stalled download (2 ms);
  - setting validation.
- Tests never contact the real cloud service; it's redirected to the local
  fake server.

Created By Shane BlackbuRn

## 1.5.0 – 2026-11-15

### Added
- **Earth Globe tab:** the same live day/night Earth on a 3D globe, with
  everything the flat map has:
  - saved locations as labelled markers (hidden when they're round the back);
  - the pulsing selected marker and its card (local time, Day/Twilight/Night
    with the sun's height, temperature and an animated weather icon);
  - Sun and Moon overhead markers when they're on the side facing you.
- **Drag to spin** the globe in any direction. Grabbing a marker and dragging
  spins the globe; a plain click on a marker selects that place.
- The globe **turns smoothly** (0.7 s, the shortest way round) to face a
  place when you select it in Saved locations or click its marker.
  **Centre on selected** and double-click turn it back.
- Optional **Rotate slowly** (off by default). It stops while the tab is
  hidden, so it uses no CPU then.
- A soft atmosphere glow, limb darkening and a starry background.

### Changed
- The Earth tab is now called **Earth Flat**.
- Both Earth tabs share one day/night image, drawn in the background every
  5 minutes, so the globe adds no extra background work.
- The card placement, labels and info line are shared code between the two
  Earth tabs.

### Performance
- Globe drawing with numpy (installed with the .deb): about 30 ms for a
  600 px globe. While dragging, turning or spinning it draws at 60%
  resolution, then sharpens when you let go.
- Without numpy it draws at up to 320 px (about 75 ms) and scales up.
  Selecting a place jumps straight there, and Rotate slowly is disabled.

### Tests
- `test_globe.py` (17 tests):
  - projection: the centre, far side, limb and poles, plus a 3000-point
    round trip (worst error 2e-13°);
  - the renderers: the centre pixel matches the map, the outside of the disc
    is transparent, the edge is darker, numpy and pure Python are
    pixel-identical at 4 centres, the size cap and scaling, and speed;
  - the tab: names; facing the selected place with its card; smooth turning
    on selection; marker click versus marker drag; drag rotation; the card
    hiding on the far side; one shared image for both tabs; slow rotation
    stopping when hidden and resuming when shown; Centre and the no-numpy
    jump; a missing map; the credit.
- The full suite has 214 tests, all passing (2 skipped, as before).

Created By Shane BlackbuRn

## 1.4.0 – 2026-11-15

### Added
- **Earth tab:** a live world map, blending your day and night Earth maps
  along the real day/night line (terminator).
  - City lights glow on the night side, with a soft twilight band and
    slightly darker daylight near sunrise and sunset.
  - The map is redrawn in the background every 5 minutes while the tab is
    open.
  - **Sun and moon markers** show where each is directly overhead. A line
    above the map gives the time and the sun's overhead point.
  - **Saved locations** appear as labelled markers. The selected one has a
    pulsing marker and a card showing:
    - its **local time** (in its own timezone, updating every 15 s);
    - **Day, Twilight or Night** there, with the sun's height above or
      below the horizon;
    - its **temperature** (in your units) with an **animated weather icon**
      and a description.
  - Selecting a place in **Saved locations** moves the card to it, and
    **clicking a marker on the map** selects that place.
  - The card places itself so it doesn't cover other locations, and stays
    inside the map at any window size. Labels near the right edge go on the
    left of their dot so they're never cut off.
- Earth maps: Solar System Scope (https://www.solarsystemscope.com/textures/),
  CC BY 4.0, based on NASA imagery. They're credited in the Earth tab, the
  About box and the package copyright file.

### Tests
- `test_earth.py` (18 tests):
  - the sun's overhead point against 150 PyEphem samples (within 0.8
    arcminutes), and the sun's height against 384 samples (within 0.006°);
  - equinox and solstice latitudes;
  - day/twilight/night thresholds;
  - map projection there and back;
  - day/night masks;
  - the blended map using the day map under the sun and the night map
    opposite it;
  - a missing map file giving a clear error;
  - markers and card contents, and the card following the Saved locations
    selection;
  - clicking markers;
  - fixed-time day, twilight and night for London;
  - units and a location with no weather yet;
  - the card avoiding other markers at two window sizes;
  - redrawing only when stale, and the clock stopping when the tab is
    hidden;
  - labels near the map's right edge staying fully visible;
  - credits.
  The suite now has 197 tests.

## 1.3.0 – 2026-11-15

### Added
- **The moon is shown as it looks in each place's sky.** Pictures are turned
  by the moon's parallactic angle (Meeus ch. 14). The tilt now depends on
  latitude and the time of night, not just the hemisphere:
  - near the equator, an evening crescent lies on its back (the "smiling
    moon", bright edge pointing down);
  - northern locations at the moon's highest point see it "north up";
  - southern locations see it turned over, as before;
  - everything in between is shown at its true angle.
  Checked against PyEphem: within 1.6° over 283 samples in 6 cities.
  - If the moon is **up now**, it's shown as it looks right now. The new "In
    the sky" line gives its height and compass direction, for example "Up now
    · 29° high in the E".
  - If it's **below the horizon**, it's shown as it will look at its highest
    point, with the time ("Below horizon · shown at its highest, Sun 21:14").
  - Each of the **7 days** shows the moon as it looks at its highest that
    day; hover over a picture for the time and height.
- The night sky in the animated weather scene now shows the moon only when
  it's actually above the horizon, at the right tilt, and higher in the scene
  the higher it is in the sky.

### Performance
- Moon calculations are 3.5× faster: the 7-day view went from 77 ms to 21
  ms, with identical results. Times of the moon's highest point, phase times
  and rise/set times now use a few refining steps (Newton or secant) instead
  of a fine time scan. Found by the UI-responsiveness stress test: the extra
  orientation calculations had cut screen updates during a stalled download
  from about 45 to 16–26 per half second. They're back to 43–45.

### Tests
- 9 new tests:
  - parallactic angle against 283 PyEphem samples;
  - the equatorial "smile";
  - north up and turned over at the highest point;
  - "now" versus "at its highest" views, and the time of a day's highest
    point;
  - rotation by any angle (and 180° matches the old southern view
    pixel-for-pixel);
  - different orientations for Auckland, Singapore and London at the same
    moment;
  - the scene's moon hidden below the horizon and rotated correctly when up.
  The suite now has 179 tests.

## 1.2.2 – 2026-11-15

### Fixed
- **"Couldn't update: Could not reach the weather service (_ssl.c:983: The
  handshake operation timed out)".** Shane's connection test showed that
  `api.open-meteo.com` has a single IPv4 address. The connection to it opens
  (320 ms), but the secure (TLS) setup then stalls, while the location-search
  server works fine. That's the signature of a path-MTU "black hole":
  something on the route silently drops the server's full-size packets,
  which carry its certificate. I reproduced the exact error in a simulated
  network (a separate network namespace and virtual cable, with packets over
  1200 bytes dropped and no ICMP "too big" reply). The fixes:
  - The secure setup now has its own 6 s limit (reading still gets the full
    15 s), so a stall is detected quickly.
  - One automatic retry. The address that stalled is avoided for 10 minutes
    if another exists, and so is IPv6 as a whole if that's what failed.
  - The retry, and every later connection to that server, uses **small TCP
    segments (MSS 1000)**, which gets past the black hole. In the simulation:
    the first request recovers once the stall limit is reached, and every
    request after that takes about 4 ms instead of failing.
  - The small-packet setting is remembered for 7 days, including across
    restarts (`~/.cache/weatherdesk/network.json`), so only the very first
    request ever stalls.
  - Clearer messages ("The secure connection to the weather service timed
    out…"). Certificate errors are never retried or bypassed, and server
    errors (HTTP 5xx) are not retried.

### Changed
- **Help → Test connection / `--diagnose`** now completes the secure
  handshake over IPv4 and IPv6 separately, instead of only testing the basic
  connection. That earlier check couldn't detect this fault. When a handshake
  stalls, it automatically re-tests with small packets and says whether
  that's a packet-size problem. It also lists any addresses currently being
  avoided or using small packets.

### Added
- `test_tls.py` (21 tests):
  - a real HTTPS fake server with certificate checks on, plus a silent
    server, covering retry-elsewhere, a bounded fail time, the full read
    timeout, no retry for certificate or server errors, and address ordering
    (IPv4 first after an IPv6 stall);
  - avoidance that expires, a corrupt health file, and small segments
    actually applied to the socket;
  - a path-MTU black-hole simulation with a network namespace and veth,
    covering: fails without the fix, recovers with it, remembered across
    restarts, and diagnostics that explain the problem;
  - the main window showing weather, not an error.
  The suite now has 170 tests.

## 1.2.1 – 2026-11-15

### Changed
- **Real NASA moon surface:** the moon pictures are built from NASA's
  public-domain CGI Moon Kit, using the colour map
  (`lroc_color_poles_4k.tif`, from the Lunar Reconnaissance Orbiter's camera)
  and the height map (`ldem_16_uint.tif`, from its laser altimeter). The
  converter is `tools/make_moon_texture_nasa.py`. The result is a 2048 px
  near side with every real mare and crater in place, and real terrain
  shadows along the day/night line. The NASA credit appears in the Moon tab
  and the About box. The earlier generated textures are kept in
  `tools/generated_textures/` as a fallback and rollback.

### Fixed
- The Moon tab scrolls instead of squashing its rows when the window is short (found by a new layout test at the smallest window size).
- The credit line no longer squeezes the moonrise/moonset rows; it now sits
  at the bottom of the Moon tab.
- Released as 1.2.1, so it installs over, and takes over from, the 1.2.0
  preview.

## 1.2.0 – 2026-11-15 (preview, generated moon)

### Added
- **Moon tab** (next to Forecast):
  - A large, high-resolution picture of the moon in its current phase.
  - Phase name, % illuminated, age in days, and waxing or waning.
  - Today's moonrise and moonset, and the moon's distance.
  - The dates and times of the next new, first quarter, full and last
    quarter moons.
  - **The next 7 days**: a moon picture for each day, with its phase, %
    illuminated, rise and set.
- **Moon calculations run on this computer** (`moon.py`), with no web
  service, so they work offline. They use the main terms of Meeus,
  *Astronomical Algorithms*. Checked against PyEphem:
  - Moonrise/moonset within 23 s for Auckland, 36 s for London and 16 s for
    Quito.
  - Up to about 3.7 minutes in the Arctic (Tromsø), where the moon skims the
    horizon.
  - Illumination within 0.02 percentage points.
  - New, quarter and full moon times within 82 s.
  - Days when the moon never rises or never sets (for example in polar
    regions) are handled. Times are in the location's own timezone.
- **Realistic moon images** (`moon_render.py`):
  - Lit for the exact phase, using the lunar-surface reflectance model
    (Lommel–Seeliger).
  - Crater relief casts shadows along the day/night line.
  - Faint earthshine on the dark side.
  - The crescent's tilt matches the real sky.
  - Shown upside down in the southern hemisphere, as it looks from New
    Zealand.
  - Sharp on high-resolution screens.
  - **Save high-resolution image…** saves a 2048 × 2048 PNG.
- Moon pictures from a detailed generated near-side texture (`tools/make_moon_texture.py`).
- The animated weather scene's night sky now shows the same realistic moon.
- Recommends `python3-numpy`. Moon pictures render about 7× faster with it,
  but everything works without it.
- `test_moon.py` (28 tests), checked against 120 PyEphem rise/set days in 4
  cities, 167 illumination samples and 48 phase times, plus rendering,
  orientation, the NASA converter, and the Moon tab. The suite now has 149
  tests.

### Fixed
- Test-only: the fake weather server now returns the requested location's
  timezone, as the real service does.

## 1.1.1 – 2026-11-15

### Fixed
- **Installing an update didn't take effect while the app was running.**
  Only one copy runs at a time, so launching the newly installed version
  just brought the old, still-running copy to the front. Now a new launch
  asks the running copy for its version:
  - If the running copy is older, it saves its settings and quits, and the
    new version takes over.
  - If it's the same version, it comes to the front.
  - If it's newer, it stays and the older launch exits.
  - Copies from before this change (1.0.0–1.1.0) can't answer. They're
    recognised after three unanswered requests (about 6 seconds), then
    closed cleanly and replaced.
  The new window confirms "Updated to WeatherDesk 1.1.1…". Only the process
  that holds WeatherDesk's single-instance lock is ever closed, and only
  after checking that it really is WeatherDesk.
- **Crash (segmentation fault) when shutdown was triggered twice at once**,
  for example a stop signal arriving during an update hand-over or two
  quick stop signals. Quitting can now safely be triggered more than once,
  and further stop signals are ignored once shutdown has started. Tested
  with 30 runs of two or three overlapping stop signals: all exited cleanly.
- The app now starts listening for new launches only after its window is
  built, so it always answers promptly. Found by a new test: a slow-starting
  copy could miss the 1.5 s reply window and be mistaken for an old one.

### Added
- `test_instance.py` (9 tests) runs real WeatherDesk processes:
  same-version launch, upgrade hand-over, older launch versus a newer running
  copy, a pre-1.1.1 copy that can't answer, a busy copy that must never be
  closed, a decoy process that must never be touched, and a stale socket
  left by a crash. Tests use their own instance name
  (`WEATHERDESK_INSTANCE`), so running them never affects a WeatherDesk you
  have open. The suite now has 121 tests.

## 1.1.0 – 2026-11-15

### Added
- **Animated, realistic weather scene** behind the current conditions:
  - The sky colour follows the real time of day at the location, with dawn
    and dusk glows worked out from its sunrise and sunset times.
  - The sun travels along its daily arc, with a soft glow and slowly
    turning rays.
  - At night there's a moon in its actual phase (mirrored in the southern
    hemisphere, as it looks from New Zealand) and twinkling stars.
  - Layered clouds drift at the speed and in the direction of the wind.
    Clouds get heavier and greyer for rain and storms, and overcast skies
    get a lower cloud deck.
  - Rain falls slanted by the wind and splashes; drizzle is finer; snow
    sways as it falls; fog banks drift; storms have lightning bolts and
    flashes.
  - The sky keeps changing between downloads as the local time moves on.
- **Animated icons** in the 7-day forecast.
- **Desktop widget** (View → Desktop widget): a floating, frameless window
  with the animated scene, temperature, conditions and the day's high and
  low. Drag it anywhere, double-click to open the app, and right-click for
  Refresh, Size (small/medium/large), Keep on top, and Hide. Its position and
  size are remembered, and it's moved back onto the screen if a saved spot
  is no longer visible.
- **View → Animated weather** turns animation on or off. Animation runs at
  24 fps from one shared timer (forecast icons redraw at 12 fps), and only
  while something animated is on screen. Measured in the test sandbox's
  software renderer: about 10% of one core for the window, about 16% with the
  desktop widget too, and about 0% when animation is off or nothing animated
  is visible. Down from 20% at the first-draft 30 fps.
- 28 new tests (`test_scene.py`): every weather code at day, dusk and night,
  steady paint time under 15 ms (measured 1.3–5.3 ms), particles staying
  bounded over 10 simulated minutes, lightning only in storms, rain slanting
  with the wind, the clock pausing when hidden or disabled, and desktop
  widget persistence, off-screen recovery and leak checks. The suite now has
  112 tests.

### Changed
- Help → Test connection now lists only the HTTP/HTTPS proxy settings, not
  every proxy-related environment variable.

### Performance
- Rain streaks are drawn in one batched call without antialiasing, which
  cuts heavy-rain frames from about 6.2 ms to 4.4 ms.

## 1.0.1 – 2026-11-15 (not released separately; included in 1.1.0)

### Fixed
- **Slow weather loading.** Python's standard connection code tries a
  server's addresses one at a time and waits the full 15-second timeout on
  each. On networks where IPv6 is offered but doesn't work, every search and
  forecast stalled for about 15 s before falling back to IPv4. WeatherDesk now
  races the addresses the way web browsers do ("Happy Eyeballs", RFC 8305):
  if the first hasn't answered in 0.25 s, the next is tried in parallel and
  the first to connect wins. In a reproduction, a stalled request went from
  15 s to 0.25 s. Proxy settings and HTTPS certificate checks are unchanged.

### Added
- **Help → Test connection…** shows DNS lookup time, whether IPv4 and IPv6
  each work, and how long a real search and forecast download take, with a
  plain-English summary and a Copy report button. You can also run it from
  the terminal with `weatherdesk --diagnose`.
- Each download's size and time is written to the log
  (`~/.cache/weatherdesk/weatherdesk.log`).
- 17 new tests (`test_net.py`), including a simulated "black-holed" address
  that reproduces the stall. The suite now has 84 tests.

## 1.0.0 – 2026-11-15

First release.

### Added
- Location search (Open-Meteo geocoding) with a 450 ms debounce; Enter or click
  adds the result.
- Saved locations sidebar showing each place's current temperature; reorder,
  remove, and a maximum of 50.
- Current conditions card, a 24-hour temperature and precipitation-chance
  chart, and a 7-day forecast.
- Unit choices for temperature, wind, and precipitation, applied instantly
  with no re-download.
- Auto-refresh (off, or every 10, 15, 30, 60, or 120 minutes; default 30).
- A system tray icon that shows the live temperature, with Show/Hide,
  Refresh, and Quit; close-to-tray; and start at login (minimised).
- Offline fallback to the last saved forecast for each location, with clear
  "saved copy", "Couldn't update", and "data may be out of date" indicators.
- A single-instance guard: a second launch brings the running window forward.
- Help → User Guide (F1), Help → About, and the "Created By Shane BlackbuRn"
  credit in the status bar, About box, guide, and package metadata.
- Atomic settings and cache writes. A corrupt settings file is moved aside to
  `settings.json.corrupt-<time>` instead of being deleted.
- A rotating log at `~/.cache/weatherdesk/weatherdesk.log`.
- An offline test suite (67 tests) with a fake Open-Meteo server, GUI
  workflow tests, and stress/leak tests.
- A .deb package, a source archive, and SHA256 checksums.

- Clean shutdown on SIGTERM and Ctrl+C (logout or `kill`): settings and
  window size are saved, and the exit code is 0.

### Fixed during development
- SIGTERM previously killed the app abruptly (exit code 143) without saving
  the window geometry.
- Adding a location showed "No weather data yet." instead of "Loading
  weather…" while the first download was running. The stalled-network stress
  test caught this.
