# RBSB-Weather Changelog (formerly WeatherDesk)

Created By Shane BlackbuRn

Entries before 2.0.0 use the app's old name, WeatherDesk, as they were written.

## 2.2.0 – 2026-11-21 (on branch claude/rbsb-weather-2.2.0; not released)

Requested by Shane: "I'd like to add new tab for wind etc... as attached as a
globe" (with a screenshot of a world wind map). He chose NOAA GFS as the data
source and "wind only" for this first version. Built on 2.1.2, which isn't
merged yet either.

### Added – the 🌬 Wind tab
- **The whole world's wind on a globe**, 10 m above the ground:
  - colours by speed (calm blue → green → yellow → red → purple);
  - about 2,200 moving streaks with fading trails that follow the wind;
  - coastlines;
  - your saved places.

  Drag to turn it, use the wheel or + / − to zoom, and **Centre on selected**
  turns to your place.
- **Hover readout:** hovering shows the wind at that point, in your wind unit
  with the direction it comes *from*. Over a saved place, it shows that
  place's wind.
- **Colour key** in your wind unit, which changes instantly with
  View → Units.
- **Moving streaks** checkbox:
  - The streaks also stop when View → Animations is off, and whenever
    another tab is showing (measured: 0 frames drawn).
  - Turning or zooming the globe clears them, so they never smear.
- **The line above the globe** says which time the map is for (your time),
  from which NOAA run.

### Wind data – NOAA Global Forecast System (GFS)
- **Grid and timing:** a 1° grid (360 × 181 points), with a forecast every 3
  hours. The forecast closest to now is shown, from the newest run
  published. Runs start every 6 hours and are out about 4 hours later; if
  the newest isn't there yet, the one before is used.
- **Download size:** only the 10 m U and V wind fields, about 200 KB.
  - First from **NOMADS** (NOAA's "grib filter", which cuts them out for us).
  - If that fails, from **NOAA's copy of GFS on AWS**: the run's .idx index
    gives the byte ranges, and only those bytes are fetched.
- **When it downloads:** only when the tab is opened, then when a newer
  forecast hour is due (every 3 hours) while it's open.
  - It's saved in `~/.cache/rbsb-weather/wind/`, so the tab shows the last
    map straight away, and offline.
  - A failed download keeps the saved map, says so, and retries after 20
    minutes.
  - A damaged download never replaces the saved map.
- Public domain; credited in the tab, Help → About, the User Guide, the
  README and the package's copyright file.

### Added – GRIB2 reader (`rbsb_weather/grib2.py`)
- GFS data comes in GRIB2, the WMO's binary weather format. RBSB-Weather now
  reads it itself, so there's no new dependency.
  - Grids: latitude/longitude grids (template 3.0), any row direction.
  - Products: template 4.0.
  - Packing: simple (5.0), complex (5.2), and complex with 1st/2nd order
    spatial differencing (5.3, what GFS uses).
  - Bitmaps of missing points are handled.
  - With or without numpy.
- Damaged or unexpected files raise a clear error. A file claiming an
  absurd grid size is refused rather than allocating memory.
- JPEG2000 and PNG packing aren't supported (GFS doesn't use them), and say
  so if met.

### How it was checked
- **Against ecCodes**, ECMWF's reference GRIB library (installed on the build
  machine only), on a real NOAA GFS file from the pygrib project's samples:
  - **All 343 fields decode identically**, including 45 with missing
    points, both with numpy and without.
  - The 10 m U and V winds from that file are now in `tests/data`.
- **Synthetic files** written by ecCodes with every supported packing, plus
  ecCodes' answers, are in `tests/data`, so the tests run on any machine
  without ecCodes. `tools/make_grib2_fixtures.py` rebuilds them.
- New `tests/test_grib2.py` (13 tests: every file in both modes, damaged
  files, huge grids, sign-magnitude integers).
- New `tests/test_wind.py` (26 tests). A fake NOAA answers like NOMADS and
  like the AWS copy (index plus byte ranges). They cover:
  - which run and hour to use, the URLs, and the index byte ranges;
  - the wind direction convention and interpolation, including the
    date-line wrap and the poles;
  - the numpy and pure-Python paths;
  - NOMADS down (falls back to AWS), the newest run missing (uses the older
    run), nothing reachable;
  - the cache, reuse without the network, refreshing after 3 hours, keeping
    the saved map on failure, a damaged download, and a damaged saved file;
  - the tab: nothing downloaded until it's opened, frames only while shown
    and on, the hover readout in knots, streaks cleared on turning, offline
    with nothing saved, and offline with a saved map;
  - the frame cost.
- **Measured** on the build machine (2 CPUs, no GPU):
  - about 31 frames a second with 2,200 streaks;
  - about 9.5 ms of CPU per frame (budget 33 ms);
  - the whole app uses about 34% of one core with streaks moving, and 9%
    with them off or another tab showing.
- **Visual:** screenshots of the tab with the real NOAA wind (zoomed in and
  out), during which the streak density, trail length and the land's
  visibility were tuned, and coastlines added.
- **Not tested here:** the build machine can't reach NOAA, so the live
  download, and whether today's 1° files use the same packing as the sample,
  can only be checked on Shane's Mint.

## 2.1.2 – 2026-11-21 (on branch claude/rbsb-weather-2.1.2; not released)

Requested by Shane: "one more update for the widget, under the city location
list the weather provider in small font".

### Added – provider name on the desktop widget
- Under the place name, in small, slightly dimmer text, the widget shows the
  weather provider that supplied what's on screen. For example:
  - `Open-Meteo`;
  - `MET Norway (backup)` when the main provider couldn't be reached;
  - `Open-Meteo · saved copy` when offline.

  Hovering over it explains which case it is.
- The text scales with the widget size, but is never below 7 pt. It fits
  "Weather Underground (backup)" on the small widget, and the mini forecast
  keeps clear of it.
- The line is hidden when no location is selected.

### Tests
- New `tests/test_widget_source.py` (4 tests). It checks:
  - the provider is shown under the place, smaller than the place name;
  - the backup and saved-copy wording;
  - the line is cleared when there's no location;
  - the longest name fits every widget size without overlapping the
    temperature or the update time.
- Also checked visually at all three sizes.

### Test fix – `test_net` "catches a real leak" check
- It failed once in a full run ("18 != 16"). It compared every file open in
  the whole test process before and after opening 5 deliberately "leaked"
  connections, so anything else opening 2 files at that moment failed it.
  It didn't happen again in 36 more runs.
- It now checks that each of the 5 leaked connections is counted, which is
  what it's meant to prove. A failure message names any other new files.
- Confirmed it still has teeth: with the leak counter deliberately broken to
  ignore connections, the test fails.

### Confirmed by Shane on Linux Mint
- The update checker (2.1.0) found the published 2.1.1 on the real GitHub.

## 2.1.1 – 2026-11-21 (released as v2.1.1)

Requested by Shane: "add to the about and user guide 'If you enjoy this app
considering buying me a coffee for a $ 0.99' and add my paypal account".

### Added – buy me a coffee
- "☕ If you enjoy this app, consider buying me a coffee for NZ$0.99" with a
  **Buy me a coffee with PayPal** link appears in three places:
  - **Help → About** (the link is clickable);
  - the **User Guide** (new "Support RBSB-Weather" section);
  - the **README** (new "Support" section).
- New **Help → Buy Me a Coffee…** opens the PayPal page in the browser. If no
  browser can be opened, the link is shown so it can be copied.
- **The link:** a PayPal payment link for NZ$0.99 ("Coffee for RBSB-Weather"),
  paid to Shane's account and identified by its PayPal Merchant ID. That ID is
  public by design, and no email address or other personal details are in
  the app or on GitHub.
  - PayPal.Me isn't available for this account (the page bounces back to the
    Summary).
  - PayPal's Donate button needs a registered charity.
- Wording tidied from "considering ... for a $ 0.99" to "consider ... for
  NZ$0.99" (Shane: "I'll go with your recommendation"). The currency is shown
  because PayPal charges in the account's currency.

### Tests
- New `tests/test_support.py` (6 tests). It checks:
  - the exact link (https, paypal.com, Merchant ID, NZ$0.99, no email);
  - the text and link in the User Guide and README;
  - no Gmail address anywhere in the app or README;
  - the Help menu opening the link;
  - the real About box showing a clickable link;
  - the fallback when no browser opens.
- **Not tested here:** PayPal refuses automated visits to its payment page,
  so whether the link opens the right PayPal page can only be checked in a
  browser.

## 2.1.0 – 2026-11-21 (released as v2.1.0)

Requested by Shane: "Is it possible to add a check for updates", with the
daily check "turned on by default".

### Added – check for updates
- **Once a day**, RBSB-Weather asks GitHub for the latest published release
  of shanebl030-glitch/RBSB-Weather. It's on by default, and off with
  **Settings → Check for updates automatically**.
  - Never in the first minute after starting, so startup isn't slowed.
  - Driven by the existing once-a-minute timer and the wall clock, so it
    still happens after the computer sleeps.
  - A failed check is retried 3 hours later. A clock that jumped backwards
    counts as due.
- **When there's a newer version:**
  - **⬆ Update available: x.y.z** appears in the status bar and opens the
    update window.
  - The tray shows a notice once per version, not every day.
  - An automatic check never pops up a window.
  - A newer version found earlier is shown again at the next start, without
    using the network.
- **Help → Check for Updates…** checks now and shows the answer: up to date,
  a new version with its release notes, or why it couldn't check.
- **Download and Install:**
  - The .deb goes to the Downloads folder and is checked against the
    release's SHA256SUMS. A file that doesn't match, isn't a Debian package,
    is incomplete or is too large is deleted.
  - Then it opens in the desktop's package installer, which asks for the
    password. The app never runs anything as root.
  - If the installer can't be opened, the window shows the `apt` command
    with a Copy button.
  - A file already downloaded and verified is reused. A different file with
    the same name is never overwritten (`-2` is added to the new name).
  - Closing the window cancels the download and deletes the partial file.
- **Skip This Version** stops reminders for that version only.
  **Help → Check for Updates** still offers it.
- **Safety:** https only, and only GitHub's own addresses (including after
  redirects). There are size limits on every reply, the release's file name
  must be `rbsb-weather_<version>_all.deb`, and only finished releases count
  (not drafts or pre-releases).
- **Errors in plain English:** no release found, GitHub's rate limit
  reached, GitHub errors, no network, timeouts (one retry), a damaged reply.
- Settings: `update_check` (default on) and `update_skip`. The check times
  are kept in `~/.cache/rbsb-weather/updates.json`.
- New modules `rbsb_weather/updates.py` (no Qt: check, download, verify) and
  `rbsb_weather/update_dialog.py` (the window).
  `net.build_opener` accepts extra handlers, for the GitHub-only redirect
  check.

### Fixed – startup deleted files from the cache folder (present since at least 1.11.1)
- At every start, the app's clean-up of forecasts for removed locations
  deleted *every* `.json` file in `~/.cache/rbsb-weather`, not just forecast
  files. That included:
  - `providers.json` (provider status and usage);
  - `network.json` (remembering a slow or broken network route);
  - `clouds.json` (when the cloud map was last downloaded, so it was fetched
    again after each start);
  - the new `updates.json`.
- It now removes only forecast files (named like `m36.8500_174.7600.json`).
  Found by a new update test. A regression test was added to `test_core`.

### Fixed during development (never released)
- **A crash (segmentation fault) when a window closed with the update window
  open.** The update window deleted itself on close, and its "deleted" signal
  called back into a main window that was itself being destroyed. The
  update window is now kept and reused instead. The window tests then ran
  20 times in a row without a failure.

### Tests
- New `tests/test_updates.py` (35 tests) against a local fake GitHub that
  answers in GitHub's format and redirects downloads to a second host. It
  covers:
  - reading releases and comparing versions;
  - when a check is due;
  - only allowing GitHub's addresses;
  - errors and the retry;
  - a verified download, a wrong checksum, a missing checksum, a file that
    isn't a package, an incomplete download, a too-large download, a
    redirect away from GitHub, cancelling, and reuse without overwriting;
  - the window: the menu items, a manual check, install, a bad download
    never being opened, up to date and errors, the daily automatic check and
    turning it off, nothing in the first minute, skipping a version, an
    update shown again at startup without the network, and closing during
    a download.
- The test suite's update checks go to a closed local port, so tests never
  contact GitHub.
- **Against the real GitHub** (from the build machine): the check found
  RBSB-Weather 2.0.0, and the download followed GitHub's redirect, passed the
  checksum, and is byte-identical to the tested 2.0.0 package.

### Docs
- User Guide: new "Updates" section, and `updates.json` under Files.
- README: feature line, Update section and module table.

## 2.0.0 – 2026-11-21 (released as v2.0.0)

Requested by Shane: "WeatherDesk is too common". The app is now
**RBSB-Weather**. There are no feature changes; existing users' data comes with
them automatically.

### Changed – the name
- **RBSB-Weather** everywhere you see it: the window, menu entry, About box
  ("formerly WeatherDesk"), tray tooltip, User Guide and README.
- **`rbsb-weather`** for the command, Debian package, menu entry file, icon,
  and the folders `~/.config/rbsb-weather` and `~/.cache/rbsb-weather`.
- The Python package folder is `rbsb_weather` (Python names can't contain
  `-`). Environment variables are now `RBSB_WEATHER_*`; the keyring service
  is "RBSB-Weather"; the log is `rbsb-weather.log`.
- Web requests identify as `RBSB-Weather/2.0.0`, and MET Norway's contact
  address is github.com/shanebl030-glitch/RBSB-Weather (the GitHub repository
  needs renaming to match).
- Version 2.0.0, because the package, command and folders changed.

### Added – carrying WeatherDesk users over (`rbsb_weather/migrate.py`)
- **On the first start**, before the window loads its settings, it copies:
  - `~/.config/weatherdesk` (settings, saved locations, `keys.json`, which
    stays readable only by you) to `~/.config/rbsb-weather`;
  - `~/.cache/weatherdesk` (saved forecasts, cloud map, provider status;
    not the old logs) to `~/.cache/rbsb-weather`;
  - API keys in the keyring, from the "WeatherDesk" service to
    "RBSB-Weather", without overwriting a key already there;
  - "Start at login": `weatherdesk.desktop` is replaced by
    `rbsb-weather.desktop`, and the old file renamed to
    `weatherdesk.desktop.migrated` (not deleted), so it doesn't start twice.
- **Copied, never moved or deleted**, so a WeatherDesk package still finds
  its data. A folder is only copied when RBSB-Weather has no data of its own
  there, so nothing is ever overwritten. A new folder is built under a
  temporary name and renamed into place, so an interrupted copy can't leave a
  half-filled folder. A marker file stops it running twice; if the copy
  fails, it tries again next start. A failure never stops the app starting.
- The status bar says what was carried over.
- **A WeatherDesk still running** (in the tray, after the upgrade) is asked
  to hand over through its old single-instance socket, saves its settings
  and quits, and *then* its data is copied. The process check accepts both
  names, and still only touches the process that owns the socket.
- Skipped when the test suite's folder overrides are set (so tests never
  touch a real profile), or with `RBSB_WEATHER_MIGRATE=0`.

### Packaging
- `Replaces: weatherdesk` and `Conflicts: weatherdesk`: `apt install
  ./rbsb-weather_2.0.0_all.deb` removes the old package and installs the new
  one in one step. Installing a WeatherDesk .deb later does the reverse.
- `/usr/bin/weatherdesk` is kept as a link to `rbsb-weather`, so old
  shortcuts and habits still work. The menu entry has "weatherdesk" as a
  search keyword.
- Files renamed: `packaging/rbsb-weather.{desktop,sh,svg}`,
  `docs/media/rbsb-weather-playback.gif`.
- "Start at login" helpers (`autostart_path`, `AUTOSTART_ENTRY`) moved from
  `main_window.py` to `storage.py`, so the migration can use them without
  loading the window code. `main_window` still exports them.

### Tests
- New `tests/test_migrate.py` (15 tests): copying, never overwriting, only
  once, retry after a failure, an interrupted copy, keyring copy with a fake
  keyring (including a locked one), the login entry, the process check, the
  real app started with a WeatherDesk profile in a temporary home, and a
  **real WeatherDesk 1.18.0 process** (taken from git tag v1.18.0) handing
  over to RBSB-Weather. That last test skips in the source archive, which
  has no git history.
- `test_packaging` checks the new names, `Replaces`/`Conflicts` and the
  `weatherdesk` link.

### Docs
- README: "formerly WeatherDesk" note and a "Coming from WeatherDesk" section
  (what's carried over, the old command, going back).
- User Guide: the same, in a short section.

## 1.18.0 – 2026-11-21 (released as v1.18.0)

Requested by Shane (idea 2 from the "what could no other app have" list):
forecast playback in the animated sky. Built on 1.17.0, which isn't released
yet either.

### Added – forecast playback
- **A bar under the sky:**
  - **▶ Play** runs the next 24 hours, an hour a second (about 24 s).
  - **The slider** picks any time in the next 24 hours, in 15-minute steps.
  - **Now** goes back to the live weather.
- **The sky for that time:**
  - **Weather** from the hourly forecast: clear, cloudy, rain, showers,
    drizzle, snow, fog or thunder.
  - **Sun and Moon** where they'll be, with day, dusk and night at the right
    times. Tomorrow's hours use tomorrow's sunrise and sunset.
  - **Card text** for that hour: temperature, weather and chance of rain,
    marked "▶ Forecast for …". The line is kept short so the mini forecast
    keeps all its days.
- **The rest stays live:** the details beside the sky, the 7-day list, the
  tray and the desktop widget. Choosing another place returns to now. A
  refresh, a unit change or the minute tick during playback keeps the chosen
  hour, without a flicker of the live sky.
- **The clouds keep the wind of now.** WeatherDesk's hourly forecast has no
  wind, and inventing one would be wrong. The time's tooltip and the User
  Guide say so.
- **Providers without an hourly forecast** (Weather Underground with a PWS
  key) show "… doesn't provide an hourly forecast" instead of the bar's
  controls.

### Changed – smooth weather changes (live too)
- **A change of weather type now cross-fades over 0.8 s** instead of
  jumping. That covers the clouds, rain, drizzle, snow and fog (which keep
  moving while they fade out), the sky's tint, and how much the clouds veil
  the Sun, Moon and stars. Before, the whole picture changed in one frame,
  and an "overcast" Sun vanished at once.
  - It matters most during playback, where the weather can change every
    hour, but a refresh with new weather fades the same way.
  - Changes faster than the fade (fast playback) never pop: each outgoing
    weather fades from however visible it was, with at most 3 cloud
    layouts and 2 rain/snow/fog sets at once.
  - With animations turned off, a change is still instant, as before. A
    window resize ends any fade.
  - The rain, snow and fog code was moved into its own methods, unchanged,
    so the same code also moves and paints the weather that's fading out.

### Docs and demo
- **README demo:** an animated GIF of forecast playback at the top of the
  README (`docs/media/weatherdesk-playback.gif`, 25 frames a second, 7.1 MB,
  28.7 s). It was recorded from the real main window, but with a sample day
  of forecast data (the build machine can't reach any weather service), and
  says so.
  - The animation clock was stepped exactly 1/30 s per frame, so the motion
    is even however long each frame took to draw. A first, real-time
    capture managed only about 8 frames a second and looked jerky.
  - Measured: none of the 720 playback frames repeats the one before.
- **Play/pause button:** now uses the desktop theme's own play and pause
  icons. While playing, the text "⏸" had shown as a tiny square in fonts
  without that symbol (seen in the recording).

### Fixed
- **The Moon was always calculated for the real now,** even when the scene
  was asked for another moment. Live use wasn't affected; playback needed
  the fix.
- **A cached forecast from yesterday** now takes sunrise and sunset from the
  day that matches the location's date, not simply the first day in the
  forecast.
- **Two Earth Globe tests could fail depending on the time of day:**
  - The Moon-image test counted every Moon drawing in the app, including the
    weather sky's when the real Moon was up. It now checks the globe's own
    Moon picture, with the same strictness.
  - The zoom test measured before a status line above the globe had wrapped,
    which made the globe 15 px shorter. The tests now wait for the layout to
    settle first.

  Both failed on the unchanged 1.17.0 code too. The cause was found and
  measured, not guessed.

### Tests
- New `test_playback` (28 tests). Highlights:
  - **The sky ahead:** each hour's weather matches the hourly data;
    tomorrow uses tomorrow's sunrise; the Moon is calculated for that moment;
    the wind stays as now; how far ahead playback can go.
  - **Cross-fades,** measured in rendered pixels: at the change itself the
    picture is identical, and the largest change in any one frame is
    2.6–2.8, against 26.6–36.6 when the same changes jump.
  - **The bar:** an hour a second (3 hours took 3.03 s), 15-minute steps,
    Now, a disabled state, and clamping to a shorter forecast.
  - **In the app:** card and sky versus the details, tray and widget;
    changing location; no flicker on refresh or unit change; 12-hour clock;
    a provider without hourly data.
  - **Real play for 3 s:** 74 steps, median 0.8 ms each.
- **Proving the tests work:** each of three deliberate mistakes made tests
  fail. With the Moon at the real now, 2 failed; without the cross-fade, 6;
  with a live-sky flicker on redraw, 1.
- **CPU, idle and animating** (window and widget, 4 runs each): 1.17.0
  averaged 30.1%, 1.18.0 31.2%. The runs within each version spread
  further than that, so there's no measurable increase, at most about
  1 point.
- **Full suite:** 488 run, 486 passed, 0 failed, 2 skipped
  (environment-only, as before).

Created By Shane BlackbuRn

## 1.17.0 – 2026-11-20 (on branch claude/weatherdesk-1.17.0; not released)

Requested by Shane: clouds in the weather scene should move at a speed and in a
direction that reflect the forecast's current wind. Built on 1.16.0, which isn't
released yet either.

### Changed – clouds follow the real wind
- **Speed now follows the wind speed** in the forecast (km/h; every provider
  is already converted to km/h).
  - The front clouds cross the scene in 150 s in calm air, 70 s at 10 km/h,
    50 s at 20, 32 s at 40, 25 s at 60 and 21 s at 80.
  - Strong wind is capped at 19 s (100 km/h and above), so the clouds never
    turn into a blur (at most about 1.4 px per frame in the main window).
  - Speeds in between are interpolated, so any change in the wind shows.
  - Before, clouds moved a fixed number of pixels per second (8 + 0.9 ×
    km/h, capped at 80 km/h). That crossed the main window in about 7 s at
    80 km/h.
- **The same speed in the main window and the desktop widget.** Speed is now
  measured in scene widths, so the clouds take the same time to cross both.
  Before, the small widget's sky raced at about 3 times the main window's
  pace for the same wind.
- **Direction follows the wind direction, converted correctly.** The
  forecast gives the direction the wind comes FROM, and the clouds move the
  way it blows TO. With east to the right, as before and as on a weather map:
  - a westerly (from 270°) moves the clouds right, and an easterly (90°) left;
  - a north-westerly (315°) moves them right at 80% of full speed.

  Before, only left or right was used, so a north-easterly and an easterly
  looked the same.
- **Mostly north or south winds** can't be shown head-on in a side view.
  They still drift towards the side they lean, at 30% of full speed for a
  wind from due north or south and more the further it leans east or west,
  rather than freezing.
- **No jumps after a refresh.** When the wind changes, speed and direction
  ease to the new values with a 3-second time constant: 95% of the way in
  9 s. A reversal slows, turns after about 2 s, and speeds up again. Before,
  a change of direction flipped every cloud at once.
  - A change of wind alone never rebuilds or moves the clouds. A change of
    weather type still rebuilds them, as before.
  - The first real forecast is shown at once. It doesn't ease in from the
    placeholder wind the sky uses before any forecast has loaded.
- **Rain slant, snowflake drift and fog** turn round smoothly with the
  clouds. With a steady wind they're exactly as before.
- **Unchanged:** the Sun and Moon, the mini forecast, the weather icons, the
  desktop widget and the speed of rain and snow. A missing or unusable wind
  speed counts as calm; a missing direction drifts right, as before.

### Tests
- New `test_wind_clouds` (24 tests). Highlights:
  - **From/to conversion,** checked for all 360 whole degrees.
  - **Measured on the real animated scene:** speed and direction for six
    winds, each within 1% of the design.
  - **Main window and widget sizes** match within 1%.
  - **Calm air** visibly drifts; **strong wind** is capped.
  - **Refresh from 10 km/h west to 60 km/h east:** no rebuild, every frame
    matches the easing formula exactly, and the largest single step of any
    cloud is 1.05 px.
  - **Nothing else moves:** the Sun, Moon and mini forecast are identical
    with any wind.
  - **The real app:** a refresh with new wind reaches the main window and
    the widget, and both ease together.
- **Proving the tests work:** each of three deliberate mistakes made tests
  fail. With from/to backwards, 11 failed; without easing, 4; with fixed
  pixel speeds, 1.
- **CPU:** the easing costs 0.0015 ms per frame. With the main window and
  the widget animating, 1.16.0 and 1.17.0 measured 31.3% and 28.8% (average
  of 3 runs each), which is the same within run-to-run variation.
- Full suite: 460 run, 458 passed, 0 failed, 2 skipped (environment-only, as
  before).

Created By Shane BlackbuRn

## 1.16.0 – 2026-11-20 (on branch claude/weatherdesk-1.16.0; not released)

Requested by Shane: "On startup/boot update all saved locations" and "Add a
lock position to the wedge" (the desktop widget).

### Added
- **Every saved location updates at startup**, including when WeatherDesk
  starts at login. Before, only the selected location updated; the others
  showed their last saved forecast until you clicked them.
  - The selected location updates first, as before. The others follow one
    at a time, 1.5 s apart, in the order they're saved, so services with
    small allowances (Tomorrow.io: 25 an hour) aren't hit by a burst.
  - **At boot the network often isn't up yet.** A location that fails is
    tried again after 30 s, then 1, 2 and 5 minutes (the same steps as the
    selected location), and then left until you select it or restart. Its
    saved forecast stays on screen meanwhile.
  - A location updated in the last 2 minutes (a quick restart) is skipped.
  - A location removed before its turn isn't fetched. Closing WeatherDesk
    stops the round.
  - **View → Auto refresh → Update all locations at startup** turns it off
    (it's on by default). Unticking it stops a round that's still running.
    The setting is saved; older settings files get the default.

- **Lock position for the desktop widget** (requested by Shane: "Add a lock
  position to the wedge"). Right-click the widget → **Lock position**.
  - While locked, dragging does nothing. Double-click (open WeatherDesk) and
    right-click (Refresh, Size, Keep on top, Hide) still work, and the
    tooltip says it's locked.
  - Locking also saves the widget's current position. The lock is saved and
    survives turning the widget off and on, and restarts.
  - Locking during a drag ends the drag where it is.
  - A locked position that's off-screen (monitor unplugged) is still brought
    back onto the screen.

### Changed
- Closing the window now also stops the retry timer (as it already stopped
  the other timers), so nothing fires on a closed window.

### Tests
- New `test_startup_all` (10 tests): every location updated once, selected
  first, the rest in saved order and spaced (measured 1.47–1.59 s apart); a
  quick restart skips just-updated places; the setting off; turning it off
  mid-round; a location removed mid-round; closing mid-round; boot without
  network (retried, then recovers when the network comes up); network never
  up (each tried 5 times, then left, with the saved copy shown); setting
  default and validation.
- New `test_widget_lock` (8 tests), driven by real mouse press/move/release
  events:
  - unlocked drags as before, and locked doesn't move;
  - unlocking lets it move again, and locking mid-drag stops the drag;
  - the menu item, with double-click, size and on-top still working when
    locked;
  - the lock survives widget off/on and a restart;
  - an off-screen locked position is recovered;
  - setting default and validation.

  A check with the lock deliberately removed from the code made 2 of these
  tests fail, so they do catch it.
- **Fixed a rare false failure in `test_net`'s socket-leak test**, seen about
  2 times in 300 runs, and during a full suite run on 2026-11-20. It isn't
  new: the test was last changed in 1.13.0, and 1.16.0 doesn't touch the code
  it tests.
  - **Investigated:** the extra open descriptor was a socket that closed
    itself about 50 ms after the test's 2-second wait, while no WeatherDesk
    code was running. WeatherDesk's connection code runs on one thread and
    closes every socket it doesn't return before returning.
  - **Cause:** the in-process fake server closing its own end of the last
    connection late on a busy machine.
  - **Fix:** the test now counts only WeatherDesk's side of the connections.
    The wait wasn't lengthened, so a real leak still fails it.
  - **Proof:** a new test leaks 5 connections on purpose and checks they're
    counted. The leak test then passed 150 runs out of 150.
- Full suite: see TEST_REPORT.md.

Created By Shane BlackbuRn

## 1.15.0 – 2026-11-18 (stable release candidate; on branch claude/weatherdesk-1.12.0, not released)

A full stability, security and production-readiness audit of 1.14.0. No
features were removed or redesigned; every fix below has a regression test in
`tests/test_audit.py` unless another test is named.

### Fixed – crashes and fallback
- **A bad value could stop the backups being tried.** JSON allows
  `Infinity`, and converting it to a whole number raised `OverflowError`. That
  wasn't one of the errors a provider turned into a clean failure, so the
  manager stopped instead of moving on to the backups. Non-finite numbers are
  now dropped as missing values, the provider wrapper also catches arithmetic,
  recursion and text-encoding errors, and the manager treats *any*
  unexpected error from a provider as that provider failing ("… sent data
  WeatherDesk couldn't use (OverflowError)"), logs it, and tries the next one.
  Found by the new fuzz test (`tests/test_robustness.py`).
- **Test connection** could raise on the same kind of error, or when a reply
  had no current temperature. It now always shows a result.

### Fixed – data quality
- **Impossible values are dropped instead of shown.** Every provider's data
  now goes through plausibility limits (temperature −100…+70 °C, wind
  0–600 km/h, pressure 800–1100 hPa, rain 0–1000 mm, UV 0–25). A current
  temperature outside the limits makes the reply unusable (backups take
  over); other values show "–". Before, an absurd temperature from a damaged
  reply produced an infinite "feels like".
- **Unknown weather condition codes** are no longer passed to the scene.
  They're worked out from the cloud and rain readings, as for a missing code.
- **MET Norway:** a new or unknown symbol was shown as clear sky. It's now
  treated as unknown and worked out from the measurements.
- **OpenWeather (plain free key):** the 5-day/3-hour list ends part-way
  through the last day, and that day's high and low came from just a few
  hours. Days (other than today) with fewer than four 3-hour steps are left
  out.
- **Tomorrow.io:** the request sent two `timesteps` values in a format the
  API documentation doesn't describe. The parameter is now left out; the
  documented default returns both the hourly and the daily forecast.
  *This needs confirming with a real Tomorrow.io key.*

### Fixed – security and privacy
- **Unexpected errors are redacted before they reach the window.** The
  worker's "Unexpected error: …" message now goes through the key filter, as
  the log already did.
- **`weatherdesk --diagnose`** now applies the key filter to warnings printed
  while it runs.
- **Weather Providers dialog:** an error message or usage text from a
  weather service was displayed as rich text, so a service (or something
  pretending to be one) could add formatting or a clickable link to the
  dialog. It's now always shown as plain text.
- **Keyring lookups are cached.** The dialog asked the keyring for every
  provider's key on every refresh, each a D-Bus call on the window's thread
  (a visible pause if the keyring is slow or locked). A key is now read once;
  saving or removing a key updates the cache. A keyring that fails is not
  cached, so unlocking it later still works.

### Fixed – upgrades and rollbacks
- **Settings from a newer version are kept.** The real rollback test (1.15.0
  → 1.11.1 → 1.15.0 with dpkg) showed that the older version, once run,
  silently dropped the provider chain and Weather Underground Station ID,
  because it didn't know those settings (API keys were kept). 1.11.1 can't be
  changed, but from 1.15.0 on, settings written by a newer version are kept
  and written back unchanged, so later rollbacks lose nothing. Invalid values
  for known settings are still reset to defaults.

### Removed – obsolete code
- The 1.12 two-source logic left inside the Open-Meteo client
  (`default_client`, its backup and retry timing), the matching branch in
  diagnostics and the unused `ProviderManager.backup` property. The provider
  manager has done this since 1.13. Old settings still migrate as before.
- Unused imports, a `render_for_phase` helper nothing called, and a
  leftover `MOON_CLEARANCE` constant.

### Tests
- New: `test_robustness` (2,400 damaged replies across all eight parsers,
  plus non-JSON shapes: 0 crashes), `test_audit` (20 regression tests for
  the fixes above), `test_packaging` (builds the .deb and source archive and
  checks contents, dependencies, secrets, checksums, and runs the packaged
  copy), `test_soak` (60 s of tab cycling, globe zoom, refreshes, unit and
  widget switching, with memory, thread, file and idle-CPU checks), and a
  check of the Moon's transit time against its slow reference method, which
  had never been used by a test.
- The two keyring tests now skip, with a reason, when `python3-keyring`
  isn't installed instead of erroring.
- Full suite: 417 tests, 0 failures, 2 skips (see TEST_REPORT.md).

### Not verified (needs real accounts and your desktop)
- None of the six key-based or keyless services could be reached from the
  build machine, so every provider was tested against recorded documentation
  formats only. See TEST_REPORT.md → "Not tested".

Created By Shane BlackbuRn

## 1.14.0 – 2026-11-17 (on branch claude/weatherdesk-1.12.0; not released)

### Added
- **Weather Underground** as a provider (requested by Shane, who has a key).
  It uses the API The Weather Company gives personal weather station (PWS)
  contributors:
  - **Daily Forecast (5 Day)**: today plus 5 days, with day and night parts
    (condition, chance of rain, rain amount, wind, UV, sunrise/sunset). After
    3 pm, when The Weather Company blanks today's day part, tonight's is used.
  - **Current conditions from a weather station**: your own, if you enter its
    Station ID, or else the nearest one that's reporting, found with Location
    Services "near" (the list is kept for a day). Stations that fail quality
    checks, are offline (HTTP 204) or haven't reported for 2 hours are
    skipped. If your own station is offline, the backups take over, and the
    message names the station.
  - Stations don't report a weather condition. It comes from the forecast for
    this part of the day, corrected by the station's rain gauge (a wet
    forecast with no rain falling shows the cloud cover; rain falling shows
    rain). This is listed under "Calculated by WeatherDesk".
  - A PWS key has no hourly forecast. The 24-hour chart now says "Weather
    Underground doesn't provide an hourly forecast" instead of a bare
    "No hourly data".
- **Provider settings** in Settings → Weather Providers. Providers can now
  declare non-secret options (here, the Station ID), validated and saved in
  settings.json. API keys stay in the keyring or private key file.

### Tests
- 6 new Weather Underground tests (the fake server serves the 5-day
  forecast, PWS observations including 204 "offline", and nearby stations),
  plus option validation and saving, the dialog's option field, and the
  chart's message. The other provider tests (bad key never echoed, usage
  limit, garbled data, the whole window) now cover Weather Underground too.

Created By Shane BlackbuRn

## 1.13.1 – 2026-11-17 (on branch claude/weatherdesk-1.12.0; not released)

### Fixed
- **Settings → Weather Providers: a provider's status line could be cut off**
  (Shane's screenshot showed "MET Norway (backup 1)…" on one line, without
  "Not used yet"). Each row now has an explicit two-line height. A new test
  checks every row before and after a status change. Nothing else changed.

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
