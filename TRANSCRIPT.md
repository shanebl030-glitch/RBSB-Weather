# WeatherDesk – Development Session Transcript

Created By Shane BlackbuRn

## Session 1 – 2026-11-15 – v1.0.0 (initial build)

**Request:** "I want to create my own desktop weather app."

### Decisions made (with reasons)
| Decision | Reason |
|---|---|
| Python 3 + PyQt6 using the distro packages (`python3-pyqt6`) | Matches SpeedCheck/NetMonitor; Mint 22 ships PyQt6 6.6.1 / Qt 6.4.2, which is the exact version used for testing |
| Open-Meteo for weather and geocoding | Free, no API key or account, worldwide coverage, CC BY 4.0 |
| Standard-library `urllib` for HTTP | No extra dependencies; honours the system proxy settings |
| Daemon threads plus Qt signals, with a token per request | The UI never blocks, quitting is instant even with a stalled socket, and stale responses are discarded |
| Metric data stored, converted only for display | Switching units is instant and needs no re-download |
| Atomic JSON writes; corrupt settings moved aside, not deleted | No data loss after a crash or bad file |
| Per-location forecast cache | Useful offline and instant at startup |
| .deb, `Architecture: all` | Consistent with your other Linux apps |

### Work completed
1. Core modules: `api.py`, `models.py`, `units.py`, `weather_codes.py`,
   `storage.py`, and `workers.py`.
2. GUI: `main_window.py` and `widgets.py` (painted 24-hour chart, tray icon
   showing the temperature), plus `app.py` (CLI, logging, single instance,
   signal handling).
3. In-app User Guide (`USER_GUIDE.md`, opened with F1) and an About box. The
   "Created By Shane BlackbuRn" credit appears in the status bar, About,
   guide, `--version`, .desktop file, and package metadata.
4. Test suite: 67 tests (core, GUI workflows, stress/leak) against a local
   fake Open-Meteo server.
5. Packaging: `build_deb.sh` produces the .deb, a source archive, and
   SHA256SUMS. Installed with apt, launched from `/usr/bin/weatherdesk`,
   tested the single-instance handover, and uninstalled cleanly.

### Problems found and fixed
- **"No weather data yet." shown while the first download was running.**
  The stalled-network stress test caught it. `refresh_selected()` now
  re-renders when there's no data yet, so the card shows "Loading weather…".
- **Apparent memory growth in the stress test** turned out to be the fake
  server's own unbounded request log, not the app. The fake server now keeps
  counters plus a bounded log. A 600-refresh probe confirmed the app's
  memory stays flat (about +120 KB, levelling off).
- **SIGTERM killed the app abruptly** (exit code 143, geometry not saved).
  Added SIGTERM/SIGINT handlers; it now exits with code 0 and saves.

### Environment notes
- The sandbox can't reach api.open-meteo.com (it's blocked by the network
  allowlist). The installed app did try the real URL and showed the friendly
  "Could not reach the weather service" error. **Live weather downloads have
  not yet been seen working and must be checked on your machine.**
- The sandbox has no system tray or colour emoji font, and runs Qt headless
  (offscreen). Tray behaviour and the visual appearance on Cinnamon need
  checking on your hardware.

### Follow-up within session 1
- Shane: "it doesn't retrieve any weather". I checked every requested field
  against Open-Meteo's docs (all valid) and sent a terminal diagnostic.
- Shane: "it is working just takes a bit of time".

## Session 1b – 2026-11-15 – v1.0.1 (slow loading fix)

**Diagnosis:** I couldn't time it on Shane's machine, so I reproduced the
most common cause locally: a "black-holed" first address, the way broken
IPv6 behaves. In v1.0.0, every request then waited the full timeout before
trying the next address (15 s in the app). That matches "it works but takes
a while".

**Fix:** new `weatherdesk/net.py` with a staggered parallel connect (Happy
Eyeballs). `api.py` now uses an opener built on it, which still honours
proxies and verifies HTTPS certificates.

**Bug found along the way:** the first attempt overrode
`_create_connection` on the class, but `http.client` sets it on each
connection object inside `__init__`, so the fix silently did nothing (still
5 s in the reproduction). It's now set after `__init__`. The
`test_fast_connect_used` test locks this in. Putting the old behaviour back
makes two tests fail (30 s for 2 requests), which confirms the tests catch
the bug.

**Test-harness fix:** `qapp()` now keeps the QApplication alive for the
whole run. A test that discarded it caused a Qt abort, which was a test bug,
not an app bug.

**Added:** Help → Test connection… and `weatherdesk --diagnose`; per-request
timing in the log.

**Not yet confirmed:** that broken IPv6 is the cause on Shane's network.
The Test connection report will show it. If IPv6 shows working and
downloads are still slow, the delay is elsewhere (DNS or the service) and
needs a separate look.

## Session 1c – 2026-11-15 – v1.1.0 (animated realistic weather)

**Request:** "I'd like it to have Realistic weather widget and have them
animate". I took this to mean an animated, realistic sky inside the app,
animated forecast icons, and a separate desktop widget (both readings of
"weather widget").

**Built:**
- `scene.py`:
  - `WeatherScene`: sky gradients by time of day and weather, the sun along
    its arc, a moon with its real phase (mirrored in the southern
    hemisphere), stars, volumetric cloud sprites in three parallax layers
    plus a low deck when overcast, rain with wind slant and splashes,
    drizzle, snow, fog and lightning.
  - `WeatherIcon` and `paint_icon` for the forecast rows.
  - `AnimationClock`: one shared 30 fps timer that stops whenever nothing
    animated is visible, or when animation is turned off.
- `desktop_widget.py`: a frameless, draggable widget with a right-click
  menu, saved position, size and keep-on-top, and recovery when its saved
  position is off-screen.
- The main window's current-conditions card now sits on the scene (white
  text over a darkened area for readability), the forecast rows use
  animated icons, and the View menu has "Animated weather" and "Desktop
  widget".
- Settings: `animations`, `desktop_widget`, `widget_x`/`widget_y`,
  `widget_size`, `widget_on_top`. Invalid values are replaced individually.

**Checked visually** with contact sheets of every weather type at day, dusk
and night, every moon phase, and the icons. I fixed the issues they showed:
cloud puffs were clipped flat at the edge of their images, overcast skies
were too empty (added a low cloud deck), and night clouds were too bright.

**Performance:** rain cost about 3 ms per frame for antialiased lines. Drawing
them in one batched call without antialiasing brought heavy rain from about
6.2 ms to 4.4 ms per frame. Steady frames now take 1.3–5.3 ms at 640×240 in
the sandbox's software renderer.

**CPU, measured on the installed package:** animation used about 10% of one
core at 30 fps in the sandbox (software rendering) and 0% when turned off.
I reduced it to 24 fps (weather moves slowly) to save about 20%. More
precise in-process timing showed 30 fps cost 19.2% and 24 fps 15.9% for the
window plus widget, and 10.2% for the window alone. The coarse `/proc`
sampling had read 10% for both settings, which was misleading, so I
re-measured rather than trust it. Forecast icons now redraw every other
frame (12 fps). Also,
Test connection now lists only the HTTP/HTTPS proxy settings.

**Tests:** 28 new ones (`test_scene.py`). The full suite has 112 tests, all
passing (1 is skipped only because the sandbox runs as root).

**Not verifiable here:** smoothness on real hardware, how the widget's
see-through rounded corners look under Cinnamon's compositor, and how
"stay below other windows" behaves with Cinnamon's desktop. These need
checking on your laptop.

## Session 1d – 2026-11-15 – v1.1.1 (update hand-over)

**Report:** "I installed the .deb but it still looks exactly the same".
**Cause:** the single-instance guard. Launching 1.1.0 just brought the old,
still-running 1.0.x window to the front, still running the old code from
memory. I told Shane to quit the old copy first. Shane: "true. that looks
cool", which confirmed the cause and that 1.1.0 works.

**Fix (`instance.py`):** a version hand-over between launches. A newer
launch makes an older running copy save and quit; the same version is
brought to the front; a newer running copy stays. Pre-1.1.1 copies (which
never answer) are given SIGTERM, which they handle cleanly. Only the process
owning the instance socket (found via /proc/net/unix and file descriptors,
then checked to be WeatherDesk) is ever signalled.

**Bugs found by the new real-process tests:**
1. A segmentation fault when shutdown was triggered twice (hand-over quit
   plus SIGTERM). `quit_app` is now safe to call more than once, and signals
   are ignored once shutdown starts. Re-tested 30 times: all exit code 0.
2. A copy still building its window could miss the 1.5 s reply and be taken
   for a legacy copy and closed. The server now listens only after the
   window exists, and "legacy" needs 3 unanswered attempts (2 s each). A new
   test freezes a running copy with SIGSTOP and confirms it's never closed.
   Putting back the single-attempt logic makes that test fail.

**Real upgrade on the installed package:** 1.1.0 running → `apt install`
1.1.1 → launch. The old copy exited with code 0 after 6.2 s, and the new one
took over.

**Tests:** 121, all passing (1 is skipped only because the sandbox runs as
root). `test_instance` was run 6 times in a row, all green.

## Session 1e – 2026-11-15 – v1.2.0 (Moon tab)

**Request:** "add the current moon phase and when the moon rise and moon
sets and next 7 days. I want high res images".

**Data:** Open-Meteo has no moon data, so it's calculated locally in
`moon.py` using Meeus chapters 47, 25 and 15. Validated against PyEphem
across 4 cities and 30 days:
- rise/set: Auckland ≤ 23 s, London ≤ 36 s, Quito ≤ 16 s; Tromsø up to
  221 s (grazing geometry);
- illumination within 0.015 points;
- phase times within 30 s.
Also cross-checked against published tables: next full moon 25 Nov 03:53
NZDT matches sunrise-sunset.org; first quarter 18 Nov 00:47 NZDT matches
Hong Kong Observatory (17 Nov 19:48 HKT). PyEphem reference values are saved
in `tests/moon_reference.json`.

**Images:** a per-pixel renderer with Lommel–Seeliger reflectance, crater
relief from a height map, earthshine, the bright-limb angle from the
astronomy, and a 180° rotation for the southern hemisphere. numpy is used
when available, with a pure-Python fallback that matches it within 6/255.
The first generated near-side texture went through several rounds: blobby
maria, then over-merged maria, then coverage fixed at about one third; too
many bright crater rims; relief far too strong (large-scale slopes tilted
the lighting). The full moon also looked bumpy until the viewing angle used
the bumped surface too. Measured lit areas now match illumination.

**Shane asked about NASA SVS Dial-A-Moon.** I researched it: 730 px images,
hourly, data only to 31 Dec of the current year, and no rise/set times.
Shane then asked about other sources, and I recommended the **NASA CGI Moon
Kit** maps (public domain) rendered by our own engine: any date, offline,
any size. Shane agreed. Wrote `tools/make_moon_texture_nasa.py` and
validated it with fake NASA-format TIFFs: landmarks land on the right
pixels, and nothing from the far side shows through. **Waiting for Shane to
attach** `lroc_color_poles_4k.tif` and `ldem_16_uint.tif`; the first links
I gave were http and didn't work, and corrected https links were sent.

**NASA maps received** (`lroc_color_poles_4k.tif`, 4096×2048 RGB with LZW
compression; `ldem_16_uint.tif`, 5760×2880 uint16). I backed up the
generated textures to `tools/generated_textures/` and converted the maps in
2.8 s: albedo 850 KB, relief 915 KB, relief span 2215 m (99.5th percentile),
3× exaggeration. Visual checks: Crisium on the east limb, Tycho's rays in
the south, Copernicus west of centre; the 2048 px close-up shows the
Apennines and Imbrium shoreline with real terrain shadows. All 148 tests
pass with the NASA textures. The screenshot showed the new credit line
squashing the moonrise and moonset rows; the credit now sits at the bottom
of the tab, and a test checks the rows never overlap. That test then caught
that a short window still squashed the rows (the window's minimum size, 560
px, was smaller than the content's, 882 px), so the Moon tab now sits in a
scroll area. The test checks 3 window sizes, including the smallest allowed. Installing the .deb
pulled in `python3-numpy` automatically, because apt installs recommended
packages, so the fast rendering path is the default on Mint.

**Moon tab:** all work runs on a background thread, results are refreshed
every 10 minutes or when the location changes, and saving a 2048 px PNG
also runs in the background.

**Released as 1.2.1:** the earlier preview was also numbered 1.2.0, and apt
won't reinstall the same version (nor would the single-instance hand-over
replace a running copy of the same version), so the NASA build is 1.2.1.
The upgrade from a running 1.2.0 was tested on the installed package.

## Session 1f – 2026-11-15 – v1.2.2 (TLS handshake stall)

**Report:** "couldn't update: Could not reach the weather service (_ssl.c:983:
The handshake operation timed out)".

**Reproduced first** with a silent server (it accepts TCP, then never
replies): exactly the same message. v1.2.1's TCP racing can't help, because
the stalled address "wins" the race every time.

**Shane's connection test** narrowed it down. Geocoding (202.61.206.6) is
fine. `api.open-meteo.com` has only 51.81.167.44: TCP connects in 320 ms,
then the TLS handshake times out. The old diagnostics only tested TCP, so
they couldn't show this. Diagnosis: a path-MTU black hole on that route.

**Simulation:** a first attempt with iptables on loopback was not faithful:
Linux builds 64 KB offload "super-packets" internally, so the length rule
dropped them even with small MSS. I moved to a network namespace and veth
with offloads off on both ends and the drop on the receive path, which gives
real wire-size packets. Results: default MSS fails with the exact error; MSS
1000 completes the TLS handshake in 2.1 ms and the response in 1.6 ms.

**Fix:** a 6 s handshake limit; one retry; bad-address and IPv6 avoidance
for 10 minutes; MSS clamp (TCP_MAXSEG 1000) for that server, remembered for
7 days in `network.json`; clearer messages; no retry for certificate or HTTP
errors. Diagnostics: per-family TLS handshake, an automatic small-packet
re-test, and a health summary.

**Tests:** `test_tls.py` (21). The netns class passed 3 runs in a row and
cleans up its namespace, veth and iptables rule even when setup fails. Full
suite: 170 tests, all passing (2 skipped for environment reasons).

**Waiting on Shane:** the curl/MTU output, to confirm the black-hole
diagnosis on his network.

## Session 1g – 2026-11-15 – v1.3.0 (moon as seen in each sky)

**Question:** "does the moon look the same and have the same phases around
the world?" Answer: the phase is global; the orientation, rise/set times and
local date of a phase differ. Shane: "do it", meaning show the true
orientation for each location.

**Built:** `sky_geometry` (parallactic angle, altitude, azimuth),
`next_transit`, `sky_view` (now if up, otherwise at its next highest point)
and `day_view`, all in `moon.py`. `render_moon(rotation=…)` takes any angle
(re-cropped after rotation; 90° multiples are lossless). The Moon tab has an
"In the sky" row and 7-day thumbnails at each day's highest point. The scene
shows the moon only when it's up, at the correct tilt and height.

**Validation:** parallactic angle within 1.57° of PyEphem over 283 samples;
an equatorial evening crescent has its bright limb about 192° from the
zenith (pointing down: the "smile"); London's highest point is 0° (north
up), Auckland's 180°. A visual comparison at 21:00 NZDT: Auckland crescent
lit lower-left, Suva lit along the bottom, Singapore daytime moon lit
upper-right towards the sun, London below the horizon and shown at its
16:47 highest point.

**Regression found by the stress test:** UI ticks during a stalled download
fell to 16–26 (threshold 20) because the 7-day transit scans (about 1,400
position calculations) competed for the GIL on this 2-core sandbox. The
threshold was kept and the work made cheaper: Newton iteration for transits
(identical results in 300 random cases, about 28× faster), and
Newton/secant for phase times and rise/set (identical PyEphem error
figures). The 7-day calculation went from 77 to 21 ms, and ticks recovered
to 43–45.

## Session 1h – 2026-11-15 – v1.4.0 (Earth tab)

**Request:** an Earth tab using two attached maps (`8k_earth_daymap.jpg`,
`8k_earth_nightmap.jpg`). Clicking a saved location should show its actual
local time, day or night, temperature, and a small animated weather icon.
The images arrived at 2576×1288 (downscaled by the chat); that's sharp
enough for the tab. Their source is Solar System Scope, CC BY 4.0, which
Shane confirmed (https://www.solarsystemscope.com/textures/); credited in
the tab, About, guide, README and package copyright file.

**Built:**
- `earth.py`: subsolar and sublunar points; sun elevation; day/twilight/
  night; day/night blending with Qt only (a 512×256 Python mask, smoothly
  scaled, used as an alpha mask; no numpy), about 0.2 s in the background.
- `earth_panel.py`: a 2:1 map with sun and moon markers, location markers
  with labels, a pulsing selected marker, and a card with local time (zoneinfo
  in the place's timezone), state, sun height, temperature in the user's
  units, an animated `WeatherIcon` and a description. Clicking a marker
  selects it via the Saved locations list. A 15 s clock runs only while the
  tab is visible; the map is redrawn when older than 5 minutes.

**Checks:** a screenshot at 13:12 NZDT showed the sun overhead at 18.4°S
173°E (local noon in NZ, southern summer), Antarctica in daylight, the
Arctic dark, New York and London at night with city lights, and Auckland's
card reading Sun 13:12 NZDT, Day, sun +72°, 17°C. The first screenshot
showed the card covering Singapore's marker, so the card now chooses the
corner covering the fewest other markers; a test checks this at two window
sizes. A noisy "earth map failed" log line when a window closed mid-drawing
was fixed.

The London screenshot showed "Auckland" cut off at the map's right edge, so
labels there now go on the left of their dot (with a test).

**Tests:** 18 new (`test_earth.py`); the full suite has 197, all passing.

## Session 1i – 2026-11-15 – v1.5.0 (Earth Globe tab)

**Shane:** "looks good to me. I was expecting a globe but flat is good or you
could add another tab called Earth Globe which has what Earth Flat has"

**Done:**
- The Earth tab was renamed **Earth Flat**, and a new **Earth Globe** tab was added.
- `globe.py`: orthographic projection and its inverse, and a globe renderer
  that maps every pixel of the disc back to the day/night map.
  - numpy path: cached per-size grids, limb darkening and an anti-aliased
    rim.
  - pure-Python fallback: up to 320 px, then scaled up.
  - The two paths are pixel-identical. That was fixed after the first
    comparison showed rim pixels differing by up to 120/255, because numpy
    dropped the anti-aliased edge.
- `globe_panel.py` has everything the flat map has:
  - markers, hidden on the far side;
  - the pulsing selected marker and card;
  - Sun and Moon overhead markers.
- New on the globe:
  - drag to spin;
  - a smooth 0.7 s shortest-way turn to the selected place;
  - Centre on selected, and double-click to re-centre;
  - optional Rotate slowly, which stops while the tab is hidden;
  - stars and an atmosphere glow.
  - Frames are drawn at lower resolution while moving, then sharpened.
- The card placement, labels and info line moved into shared helpers in
  `earth_panel.py`. Both tabs use one shared day/night image.

**Checks:**
- Screenshots: Auckland selected showed Australia, New Zealand and a sunlit
  Antarctica, with the card reading Sun 13:34 NZDT, Day, sun +71°.
  Selecting London turned the globe to Europe at night with city lights, and
  New York visible.
- The legend was cut off at the window's right edge, so the credit moved to
  its own line.
- The first drag test failed: pressing on the selected marker (at the centre
  of the globe) counted as a click, so the globe couldn't be grabbed there.
  A marker now selects on release only if the mouse didn't move, and a
  test covers dragging from a marker.

**Tests:** 17 new (`test_globe.py`); the full suite has 214, all passing.

## Session 1j – 2026-11-15 – v1.6.0 (live clouds)

**Shane:** "real live cloud texture would be amazing"

**Research:**
- Source chosen: Live Cloud Maps by Matt Eason (github.com/matteason/live-cloud-maps).
  - A global equirectangular cloud map built from EUMETSAT geostationary
    satellites, updated every 3 hours.
  - Available at 1024–8192 px; this release uses the 2048×1024 greyscale JPEG.
  - CC0. Required attribution: "Contains modified EUMETSAT data."
- NASA GIBS was considered. Its true-colour layers are daily with orbit
  gaps, so they're not a clean live cloud layer.

**Done:**
- `clouds.py`:
  - CloudStore (cached image plus metadata) and conditional-GET updates
    (If-Modified-Since / ETag), checked at most hourly, with a 15-minute
    back-off after a failure.
  - Validation: an 8 MB cap, decodes as an image, 2:1 shape. The connection
    code is shared with the weather (Happy Eyeballs, handshake timeout, one
    retry, bad-address memory).
  - A haze-trimming alpha curve, and a freshness note.
- `earth.compose_day_night(clouds=...)` puts white cloud on the day side; at
  night the cloud dims city lights by 88% with a 16% faint glow.
- Both Earth tabs have a **Live clouds** tick box. It's saved as the
  `earth_clouds` setting and both tabs share it. The worker refreshes the
  clouds only when due, and falls back to drawing the Earth without clouds.
- Credits were added to the tabs, About, the guide, the README and the
  package copyright file.

**Checks:**
- The real host can't be reached from the sandbox (proxy 403), so it was
  tested against the local fake server. The screenshots use a simulated
  cloud map and are labelled as such.
- The first night test measured only peak brightness (53 → 41), which was
  too weak a check. It now measures city-light contrast at Lagos
  (208 → 21), and the night glow was reduced from 22% to 16%.

**Tests:** 17 new (`test_clouds.py`); the full suite has 231, all passing.

## Session 1k – 2026-11-15 – v1.7.0 (Sun, Moon and stars behind the globe; zoom)

**Shane:** "on the Earth Globe tab it would good to have a real moon and sun in
the background so when the earth slowly rotates you get a visual idea also I
option either mouse wheel or +/- on the screen to have a zoom in/out"

**Done:**
- `sky.py`: far-away objects are drawn with a perspective (gnomonic)
  projection from the camera above the view centre. The camera sees 40°
  around the Earth's edge.
  - The Sun is placed at the subsolar direction, the Moon at the sublunar
    direction, and the stars by right ascension and declination with
    sidereal time.
  - The Moon is drawn with the existing renderer, using the geocentric phase.
    Its bright limb and rotation come from the screen directions to the Sun
    and to celestial north (which are straight lines in this projection).
- `globe_panel.py`:
  - The sky is painted behind the globe: stars, the Sun with a large glow,
    and the Moon (not to scale).
  - Edge hints show which way an off-screen Sun or Moon is.
  - Zoom (60–300%) with the wheel, the −/+ buttons and the keys, with a
    low-resolution preview that sharpens after 250 ms.
- `globe.py`: 32-bit grids, at most 3 cached sizes, and a 1300 px cap.

**Checks:**
- Screenshots showed:
  - the Sun just off the Earth's edge on the sunlit side, with the
    terminator facing it;
  - a 28% crescent Moon lit towards the Sun hidden behind the Earth (the
    Moon tab also says 27–28% for today);
  - zooming to 220% and 60%.
- Two tests first failed because the tests themselves were wrong:
  - one expected east on the left (it's on the right, matching the globe);
  - the other put the Sun exactly behind the camera, where no edge direction
    exists.

**Tests:** 11 new (`test_sky.py`); the full suite has 242, all passing.

## Session 1l – 2026-11-15 – v1.7.1 (smooth zoom, bigger Moon, realistic Sun)

**Shane:** "It's a bit choppy zooming in and out and it would be good the the
moon is using the high revs images if it's not already and possibly make the
biger. it doesn't to be scale size to the earth. Also the could be a little bit
bigger and more realistic."
(I took "the could be a little bit bigger" to mean the Sun.)

**Cause of the choppiness:** every zoom step re-rendered the globe. That was a
low-resolution pass plus a full one at up to 1300 px (about 120 ms). The Moon
was also re-rendered at each new size.

**Done:**
- Zoom is animated over 180 ms (ease-out). Frames only scale the last globe
  picture, and one full-resolution render happens when the zoom settles.
  Wheel steps re-target the glide, and touchpad fractions work.
- Moon: the 1.7.0 images were already NASA's 2048 px CGI Moon Kit, just drawn
  small (0.32 globe radii across). It's now 0.64 radii, up to 360 px, at
  device resolution.
  - It's rendered north-up and rotated by the painter, so turning the globe
    doesn't trigger a re-render.
  - While the globe moves, a near-enough picture is reused.
- Sun: a sprite cached per 10% size step, with:
  - a limb-darkened disc;
  - a corona and a wide glow;
  - a subtle 4-ray starburst (toned down after the first screenshot looked
    too "cross"-like).
- An additive glow on the Earth's edge when the Sun is just behind it.

**Checks:**
- Screenshots at 100% and 160%, and of the crescent Moon.
- The first versions of two tests counted the settle-time redraw as
  "mid-glide". They were corrected to record counts at the moment the glide
  ends.

**Tests:** the full suite has 244, all passing.

## Session 1m – 2026-11-15 – v1.8.0 (widget last-updated time; reliable 30-minute updates)

**Shane:** "the widget I have on the desktop add when it was last update and
ensure it updates every 30mins"

**Findings:**
- Auto refresh already defaulted to 30 minutes, but it relied only on a
  QTimer. That timer runs on a monotonic clock that stops during suspend, so
  after a laptop wakes, the next update could be up to 30 minutes away while
  showing old data.
- A failure also waited a full interval before trying again.

**Done:**
- `_check_refresh_due()` runs on the existing one-minute timer. It updates
  when the wall-clock age is at least the interval, retries 5 minutes after a
  failure, and restarts the interval timer after a catch-up.
- Desktop widget: a "↻ HH:MM" line at the bottom right, on a dark pill. It
  shows "updating…" during an update and turns amber with the age when old,
  failed or a saved copy, and has a full tooltip. It refreshes every minute
  with the status bar.

**Checks:**
- The first screenshot put the time at the top right, where it was hard to
  read over white clouds (and the amber unreadable). It moved to the bottom
  line on a translucent dark pill, checked at all 3 sizes and in the amber
  state.
- One test first expected a second request after an HTTP 500, but HTTP
  errors aren't retried immediately (by design), so the test was corrected.

**Tests:** 10 new (`test_refresh.py`); the full suite has 254, all passing.

## Session 1n – 2026-11-16 – v1.8.1 (widget time to the top right)

**Shane:** "Should be top right not bottom right"

**Done:**
- The ↻ HH:MM label moved into the top row of the widget, right-aligned
  beside the place name. The dark pill was kept for readability over clouds.
- The test checks it's in the top quarter at the right edge and doesn't
  overlap the place name, at all 3 sizes.
- Screenshots were checked at all sizes, plus the amber state.
- The full suite caught a time-dependent failure in `test_moon` this morning:
  "Below horizon · shown at its highest, Mon 18:30". The test only allowed
  "Up now…" or "Below the horizon…", and missed the app's middle wording.
  It's a test bug that is exposed only when the Moon is down at run time.
  The test now matches all three exact formats with a regex.
- **Stability (found while re-running the full suite for this release):**
  1. A segfault in the window open/close stress test. Faulthandler showed a
     worker thread emitting `forecast_ok` on a Bridge owned by a window that
     was being destroyed, which is undefined behaviour in Qt.
     - The Bridge now has no parent and is "retired" on close (signals
       blocked), then deleted only after its worker threads finish.
     - New stress tests (close while results arrive x40, emit flood x15)
       pass.
     - test_stress passed 12 out of 12 runs after the fix. Before the fix,
       the window-cycle test crashed 1 time in 6.
     - The new race tests couldn't force the crash on the old code; it's
       too rare to trigger on demand.
  2. A hang/crash in the "busy copy" hand-over test, about 1 in 25.
     - The running copy segfaulted in `on_ready` while answering
       connections from launches that had already given up. A queued
       "newer version" request also made it quit wrongly.
     - Now sockets are deleted only from the event loop, actions are
       deferred, and requests from senders that hung up are ignored
       (MSG_PEEK check).
     - A new deterministic test fails on 1.8.0 three times out of three and
       passes on 1.8.1.
  3. `test_globe` (selecting turns the globe) could check before the
     animation's final sharp frame. It now waits for the animation to stop.
- **Tests:** the full suite has 257.

## Session 1o – 2026-11-16 – v1.9.0 (12/24-hour clock)

**Shane:** "add a option for time 12/24 hours"

**Done:**
- Every clock time found by searching for `%H` and the ISO `[11:16]` slices:
  - the hero, sunrise and sunset, and the chart labels;
  - the status bar and the widget;
  - the Moon tab (rise/set, phases, sky line, 7-day strip);
  - the Earth info line and card;
  - the cloud note.
  These now use `units.fmt_clock`, `fmt_iso_clock` and `fmt_hour_label`.
  An app-wide format is set from settings at start-up and when changed.
- A `time_format` setting ("24" by default, or "12"), validated, plus a
  **View → Time format** menu built alongside the unit menus.
- Switching re-shows the Moon report, re-times both Earth tabs, redraws the
  Earth (for the cloud line) and repaints the chart. It doesn't download
  anything.

**Checks:**
- A screenshot in 12-hour mode: chart labels "10 am … 8 pm", sunrise
  6:00 am, sunset 8:10 pm, "Updated 5:27 pm".
- Two first attempts at the in-app test were wrong, not the app:
  - a regex treated "11:13 am" as a 24-hour time;
  - the chart was hidden behind another tab when repainted.
  The Moon check now requires every time to carry am/pm, and the chart is
  painted with `grab()`.
- A search afterwards found no remaining `%H` or `[11:16]` in the app code.

**Tests:** 6 new (`test_timefmt.py`).

## Session 1p – 2026-11-16 – v1.10.0 (Sun and Moon arc)

**Shane** sent a sketch: an arc from the bottom-left corner, up over the top
middle, down to the bottom-right corner. "When the sun or moon rises, the
animation should start on the left side of the horizon … gradually moving
upwards and across the sky towards the right side. When the sun or moon sets,
it should disappear over the horizon on the right-hand side … The sun and moon
should follow the same animation path."

**Before:** the Sun went from 18% to 88% across, starting at 78% height (it
never came from below the horizon). The Moon sat fixed at 80% across, with only
its height following its altitude.

**Done:**
- `scene.arc_point(progress, rect, radius)`: x runs from 5% to 95% of the
  width; y is a sine arc from just below the bottom edge (the disc is fully
  hidden at progress 0 and 1) to the top middle. Below the horizon it
  returns None.
- Sun progress uses the real sunrise and sunset (as epoch times). Moon
  progress uses the current pass's moonrise and moonset from the new
  `moon.moon_pass()`: 20-minute steps backwards and forwards plus secant
  refinement, cached per place while inside the pass.
- Progress is computed from the clock at paint time, so both glide. The
  Sun shows by day and the Moon at night (only while it's really up).

**Checks:**
- A strip of 9 frames: sunrise, morning, noon, afternoon and sunset, then
  moonrise, two mid-sky moons and moonset. Both follow the sketch's path.
- `moon_pass` matches the Moon tab's `rise_set` exactly (worst 0 s, 20
  passes).

**Tests:** 9 new (`test_arc.py`); the full suite has 272, all passing.

## Session 1q – 2026-11-16 – v1.10.1 (Moon visible by day)

**Shane:** the Moon should also be visible during daylight when it's actually
above the horizon. Both the Sun and Moon should be able to show together on
their own arcs, the Moon should be hidden below the horizon, and visibility
should come from astronomy, not day or night. Add tests and keep everything
else unchanged.

**Cause:** `paint_scene` only painted the Moon when `daylight < 0.6`, with its
alpha fading to zero as daylight rose.

**Done (scene.py only):**
- The Moon is painted whenever it's up (its arc point exists). Visibility
  was already astronomical: `moon_up` comes from its altitude, and its arc
  progress comes from its real rise and set times.
- Daytime strength is 1 − 0.3 × daylight. The glow fades out by day, and
  the rendered Moon is cross-faded from normal drawing (night) to "screen"
  blending (day), so the unlit side vanishes against the sky.
- Nothing else changed: the Sun, the arcs, the timing and the night Moon
  are all as before.

**Checks:** 6 frames: a day Sun with a first-quarter Moon, a rising day Moon
with the Sun, dusk with both, night, day with the Moon below the horizon,
and morning twilight.

**Tests:** the "Moon only at night" test was replaced (its behaviour was
deliberately changed) by 5 new tests; the full suite has 276.

## Session 1r – 2026-11-16 – v1.11.0 (mini forecast in the weather scene)

**Shane:** add a 1–7 day forecast to the bottom-right of the weather "wedge",
keeping the Sun and Moon as the centrepiece. It should adapt to size (small
1–2, medium 3–5, large up to 7), use animated icons (sunny, partly, cloudy,
rain, heavy rain, thunder, snow, windy, fog), and show the day name, high,
low and rain chance. It must resize smartly, never overlap the Sun, Moon,
local time or other elements, work in both the top card and the widget, and
use the existing data. Add tests and avoid unrelated changes.

**Inspection:**
- Both the top card and the desktop widget are a `WeatherScene` with QLabel
  overlays. The scene paints the sky at 24 fps from the shared
  AnimationClock.
- `paint_icon(p, rect, code, is_day, t)` already animates every weather
  kind (except windy and heavy rain).
- `Forecast.daily` already has the code, high/low, rain probability and
  maximum wind.

**Design decision:** the forecast is painted by the scene itself, after the
sky and Sun/Moon. This means:
- no extra widgets or timers, and the same smooth clock;
- both places get it automatically;
- the Sun and Moon positions from the same frame are known, so it can avoid
  them.

**Conflict noted:** the Sun and Moon set through the bottom-right corner (the
arc Shane asked for in 1.10.0), so a fixed bottom-right forecast would
sometimes overlap them. Resolution: the forecast steps to the left of the
setting body (with fewer days if needed) and moves back after it sets.

**Done:**
- `forecast_strip.py`: `Day` and `days_from_forecast` (today onwards at the
  location), day names, `size_cap`, and `plan()`.
  - `plan()` measures real fonts. Its minimums are 9.5 px text and 18 px
    icons.
  - It tries long names first, then short ones, and takes whichever fits
    more days.
  - Its left limit is to the right of any text in its band, measured from
    the actual text width rather than the label width.
  - It tries the rightmost spot, then just left of each Sun/Moon disc
    (allowing for clearance).
  - Painting uses a feathered shade, shadowed text, `paint_icon` per day
    (each phase-offset), and a drop symbol plus percentage.
- `scene.py`: `paint_icon(windy=...)` adds a gust animation; heavy rain has
  5 faster drops; `set_forecast()`, `avoid_widgets` and `_paint_forecast()`.
- `main_window.py` and `desktop_widget.py`: pass the days, today and unit,
  and register the text labels to avoid. It's cleared when there's no data.

**Checks:**
- Screenshots of the card at 1100 and 1600 px windows (5 and 7 days), the
  widget at small, medium and large (2, 4 and 4 days), and a sunset sequence
  (5 days at midday, 3 days left of the low Sun, 3 while it sets, 5 after).
- First tuning:
  - The temperature column was sized for "-88° -88°", which halved the day
    count. It's now sized from the real values.
  - Text minimums were raised for the small widget.
- A rounding bug: placing the strip exactly at the Sun's clearance edge
  counted as touching, which hid the forecast near sunset. A 3 px gap fixes
  it, and the sweep test now covers it.

**Tests:** 17 new (`test_forecast_strip.py`); the full suite has 293, all
passing.

## Session 1s – 2026-11-16 – v1.11.1 (forecast fixed; Sun and Moon pass behind)

**Shane:** keep the forecast fixed in the bottom-right with its normal number
of days and its translucent background, and let the Sun and Moon pass behind
it. Their paths and timings must not change, and everything else stays the
same.

**Done:**
- `_paint_forecast` no longer passes the Sun and Moon as obstacles to
  `plan()`. The forecast was already painted after them, so they pass behind
  it.
- `plan()` keeps its optional circle-avoidance, which the scene doesn't use.

**Tests:**
- New: a full simulated day of 51 frames. The forecast has 1 position and 1
  day count. The Sun and Moon are identical with and without the forecast,
  and every pixel outside its shade is identical. They pass behind it in 32
  frames.
- New: the forecast is drawn on top of the Sun.
- The "steps aside" test was replaced.
- The pixel comparison first failed because the test's QImage wasn't
  cleared (the rounded corners are never painted). The helper now fills it
  with transparent first.
- The full suite has 295.

### Next steps
1. Install the .deb on your Mint laptop and add your town. Check that live
   data appears and matches a trusted forecast.
2. Check the tray icon on the Cinnamon panel, close-to-tray, and start at login.
3. Optional ideas for 1.1: weather alerts and notifications (for example,
   rain within the hour), a dark/light theme toggle, and hourly detail on
   hover.

## Session 1t – 2026-11-17 – v1.12.0 (a second weather source)

**Shane:** a screenshot of "Couldn't update: The secure connection to the
weather service timed out (the network may be blocking or slowing it)", with
the weather not updating. Then: "I'd like to try a more reliable weather host,
free with no API key or with an API key."

**Diagnosis:** that message comes only from a stalled TLS handshake, after
1.2.2's retry with small packets has also stalled. So the route to
`api.open-meteo.com` still fails from Waiuku. It couldn't be tested from
here: this sandbox can't reach weather services.

**Choice of host:** MET Norway's Locationforecast 2.0: free, no key, global,
government-run, on separate infrastructure. Keyed services (OpenWeatherMap,
WeatherAPI.com, Tomorrow.io) would need Shane to sign up and store a key, so
they are left as a possible later option.

**Done:**
- `metno.py`: client and parser into the existing Forecast model, symbol to
  WMO mapping, apparent temperature, local sunrise/sunset.
- `api.py`: shared `JsonHttpClient`; three escalating attempts; the
  OpenMeteoClient takes a `backup` and `prefer_backup`, with a 30-minute
  "go straight to the working source" memory; `default_client()`.
- `net.py`: MSS 1000 then 536 (saved per address), and a per-thread
  handshake limit for the last attempt.
- `main_window.py`: View → Weather source, retries at 30 s/1/2/5 min, the
  calmer message, source-aware credit. `diagnostics.py`: tests MET Norway.

**Tests:** 30 new; the full suite has 325. Screenshots checked: the window
running on MET Norway, and both sources down.

## Session 1u – 2026-11-17 – v1.13.0 (Weather Provider Manager)

**Shane:** a configurable, extensible provider manager. Keep Open-Meteo and
MET Norway; research OpenWeather, WeatherAPI.com, Visual Crossing,
Tomorrow.io, AccuWeather and Weatherbit. Keys must be stored securely, never
shown or logged. Primary plus ordered backups with configurable recovery. One
common data format with graceful gaps. Status and limits per provider. Stay
on the claude/weatherdesk-1.12.0 branch, with no merge or release.

**Research (current docs):**
- OpenWeather: One Call 3.0 is a separate subscription (1,000 calls a day
  free); a free key gets current weather plus 5-day/3-hour.
- WeatherAPI.com: 100,000 calls a month free, with 3 forecast days.
- Visual Crossing: 1,000 records a day, and a forecast costs 1 record.
- Tomorrow.io: 500 a day, 25 an hour, 5 days plus 120 h.
- AccuWeather: free access ended in 2025 (a 14-day trial, then paid), and it
  needs a location-key lookup.
- Weatherbit: 50 a day non-commercial, no hourly data.

Plan agreed: integrate four keyed providers now; list AccuWeather and
Weatherbit as planned.

**Done:**
- `providers/` package: base, registry, normaliser, and modules for
  openmeteo, metno, openweather, weatherapi, visualcrossing, tomorrow and
  planned, plus `manager.py`.
- `keystore.py`: keyring or a 0600 file, and redaction. `sun.py`: shared
  astronomy.
- `providers_dialog.py`; main window: Settings menu, credit and backup
  status, `apply_provider_settings`. `diagnostics.py`: per-provider checks.
- Settings migration; packaging of the subpackage; `Recommends:
  python3-keyring`.

**Found while testing:**
- Keyed providers didn't stamp `fetched_at`, so the status bar lost
  "Updated …" and auto-refresh would have run every minute. Fixed in the
  base class, and a test now checks it for every provider.
- Visual Crossing's error text contains the key. It's redacted, with a test.
- `build_deb.sh` only copied `weatherdesk/*.py`, so the package would have
  shipped without the providers. It now installs the subpackage.

**Tests:** 54 new; the full suite has 379 (one known timing-sensitive globe
test aside). Screenshots checked: the window on a backup, the dialog with
key entry (masked) and a successful test with usage.

