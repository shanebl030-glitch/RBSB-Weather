# RBSB-Weather (formerly WeatherDesk) – Development Session Transcript

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

## Session 1v – 2026-11-17 – v1.13.1 and v1.14.0

**1.13.1:** Shane's screenshot of the provider list showed "MET Norway
(backup 1)…" cut to one line. Rows now get an explicit two-line height, and
a test checks every row.

**1.14.0:** "can you add weather underground I have a API key with them".
- The Weather Company's PWS-contributor API list includes PWS observations,
  Location Services and the Daily Forecast (5 Day), but no hourly forecast.
- Done: `providers/wunderground.py`, provider options (Station ID), the
  dialog's option field, and the chart's "doesn't provide an hourly forecast"
  message.
- After the first screenshot, current conditions showed "Rain" (from the
  forecast) while the station measured 0 mm/h. The station's rain gauge now
  corrects the forecast's condition.
- Not tested against the live API (no access from here); Shane's key and Test
  connection are the live check.


## Session 1w – 2026-11-18 – v1.15.0 (stability and production-readiness audit)

**Request:** a full production-readiness audit of the whole app and all seven
providers (architecture, bugs, obsolete code, crashes, security, logging,
memory/CPU, timers, UI, packaging, upgrades, Mint compatibility), fixes for
what was found without redesigning or removing features, more tests, and a
stable release build. Work stays on `claude/weatherdesk-1.12.0`: no merge to
`main`, no tag, no GitHub release, existing releases untouched, commits
unsigned. (Shane said the current version was 1.13.0; the branch held 1.14.0,
which added Weather Underground, so the audit started from 1.14.0.)

### How the audit was done
| Area | Method |
|---|---|
| Baseline | Full suite on the untouched 1.14.0: 2 errors, both `ModuleNotFoundError: keyring` (the package wasn't installed in this fresh build machine), so an environment gap, not a code fault. Installed `python3-keyring`; the tests now skip with a reason when it's missing |
| Crashes | A new fuzz test sends 300 randomly damaged replies (wrong types, missing parts, `Infinity`, huge numbers, deep nesting) to each of the 8 parsers. The first run found two real bugs (below) |
| Security | Read every path a key can travel: request URLs, logs, the status file, the worker's error signal, `--diagnose`, the providers dialog, git history, the source archive |
| Providers | Re-read each provider's documentation for units, time zones, limits and request format |
| Dead code | `pyflakes` and `vulture`, each hit checked by hand (most were Qt event methods) |
| Memory and CPU | New soak test: tab cycling, globe zoom, refreshes, unit and widget switching, with memory, thread, file and idle-CPU checks |
| Packaging | New package test, then real `dpkg` installs: upgrade 1.11.1 → 1.15.0 with a profile made by 1.11.1 and 1.14.0 code, clean install with apt, purge, and rollback to 1.11.1 and back |

### Problems found and fixed
1. **`Infinity` in a reply raised `OverflowError`.** It escaped the
   provider, so the backups were never tried. Fixed in three layers: number
   conversion, the provider wrapper and the manager, which now treats any
   unexpected error as that provider failing.
2. **An absurd temperature gave an infinite "feels like".** Plausibility
   limits now apply to every provider's data.
3. **Test connection could raise**, and it also failed when a reply had no
   current temperature.
4. **Unknown condition codes reached the scene.** MET Norway's unknown
   symbols were also shown as clear sky.
5. **OpenWeather (free key):** a partial last day's high and low were shown.
6. **Tomorrow.io:** the request used an undocumented `timesteps` format. The
   parameter is now left out, so the documented default is used.
7. **Unexpected worker errors reached the window unredacted.**
8. **`--diagnose` printed warnings without the key filter.**
9. **The providers dialog showed service text as rich text** (formatting
   or links could be injected).
10. **Keyring D-Bus lookups on every dialog refresh.** Keys are now cached.
11. **The rollback test showed 1.11.1 dropping provider settings.** 1.15 now
    keeps settings it doesn't know, so future rollbacks are safe.
12. **Obsolete code removed:** the 1.12 two-source client logic, an unused
    manager property, a dead helper and constant, and unused imports.
13. **A reference method was never used by a test.** The slow Moon-transit
    scan is now a test that checks the fast method against it.

### Looked at and deliberately left alone
- **Idle CPU of about 15% of one core with animations on.** Measured at 0.5%
  with animations off, so it is all the animated scene (software-rendered at
  24 fps). This is the designed feature, it has a setting, and it already
  pauses when hidden or minimised.
- **Provider objects are shared between the worker threads.** At worst, the
  usage counter display could be briefly out of date. No crash path was
  found in the fuzz, stress or soak tests.
- **The quota guard holds back an immediate retry of a failed paid
  provider.** This is by design: the backups cover it.
- **The `weather_source` setting.** Kept so 1.12 profiles still migrate.

### What couldn't be checked here
Every weather service is blocked from the build machine, so all provider work
is against documented formats and recorded samples. It is not a live check.
See TEST_REPORT.md → "Not tested".

Created By Shane BlackbuRn

## Session 1x – 2026-11-20 – v1.16.0 (update every location at startup)

**Context:** Shane tested 1.15.0 on his Mint Cinnamon desktop and approved it.
`main` was fast-forwarded to the tested commit `d9f8555`. The `v1.15.0` tag
couldn't be pushed from the build machine (the git proxy returned 403), so
Shane is publishing the release from the GitHub website. On 2026-11-19 he
spotted that the Moon's lit side doesn't face the drawn Sun in the weather
scene (diagnosed, not yet changed; waiting for his decision).

**Request:** "On startup/boot update all saved locations".

**Done on a new branch, `claude/weatherdesk-1.16.0`, from `d9f8555`**, so
the approved 1.15.0 stays exactly as tested.
- **Before:** only the selected location updated at startup.
- **After:**
  - All saved locations update: the selected one first, the rest spaced
    1.5 s apart.
  - Boot-time failures are retried on the usual 30 s / 1 / 2 / 5 min steps,
    then left.
  - Locations updated in the last 2 minutes are skipped.
  - There's a menu option to turn it off.

| Decision | Reason |
|---|---|
| Space the requests out instead of sending them all at once | Free plans have small hourly limits (Tomorrow.io allows 25 an hour), and some services rate-limit bursts |
| Retry a few times, then stop | At boot the network often comes up after WeatherDesk starts. Retrying for ever, for places you aren't looking at, would waste quota. The selected location still has its normal retries |
| Skip places updated in the last 2 minutes | Restarting twice shouldn't use the allowance twice |
| On by default, with a menu option | It's what was asked; the option is there for anyone saving quota |

**A test failure I investigated:** one new test saw 4 tries where 5 were
expected. Tracing it showed a race in the test itself, not the feature: it
checked "round finished" before the round had started. The test now waits
for the round to begin. It then passed 3 runs out of 3, and the full suite
passed.

**Needs your desktop:** a real boot with WeatherDesk starting at login, and
especially a slow network at boot (Wi-Fi joining late).

Created By Shane BlackbuRn

### Same session: lock position for the desktop widget

**Request:** "Add a lock position to the wedge" ("wedge" is the desktop
widget).

- **Done:** a "Lock position" tick in the widget's right-click menu. While
  locked, dragging is ignored; double-click and right-click still work.
  Locking saves the current position, and the lock is saved too.
- **Decision:** the off-screen safety move still applies when locked, so a
  widget on an unplugged monitor isn't lost.
- **A test failure I investigated:** the first unlocked-drag test moved the
  widget 3 times too far. The cause was the test's simulated mouse, which
  followed the widget as it moved. A real pointer stays fixed on the screen.
  The helper now uses fixed screen positions.
- **Proving the tests work:** with the lock deliberately removed from the
  code, 2 tests failed; with it restored, all passed (3 runs out of 3).
- **Not testable here:** Cinnamon lets you move any window with Alt + drag.
  That goes through the window manager, which WeatherDesk can't block. A
  locked widget moved that way isn't saved there, so it returns to its locked
  spot at the next start. Check this on your desktop.

**A failure in a test I didn't change:** the full suite then failed one
existing test, `test_net`'s socket-leak check (14 descriptors against 13).
It also failed once when run completely on its own, so it wasn't caused by
today's changes.

- **Evidence:** I recorded each extra descriptor over many runs. It happened
  twice in about 300, and both times it was a socket that closed by itself
  about 50 ms after the 2-second wait. No WeatherDesk code was running, and
  WeatherDesk's connection function closes everything except the socket it
  returns, on one thread.
- **Conclusion:** it's the fake server, which runs in the same process,
  closing its own end late.
- **Fix:** count only WeatherDesk's side, not a longer wait, plus a test that
  a deliberate leak is still caught.
- **My own mistake, caught by measuring:** my first version waited 10
  seconds on every run, because the fake server normally holds 2 sockets, not
  the 1 I'd assumed. That's corrected.
- **Result:** 150 runs out of 150 passed.

Created By Shane BlackbuRn

## Session 1y – 2026-11-20 – v1.17.0 (clouds follow the real wind)

**Request:** make the clouds move at the speed, and in the direction, of the
forecast's current wind:
- convert "from" to "to" correctly;
- no jumps after a refresh;
- calm air still drifts, and strong wind stays readable;
- the same in the main window and the desktop widget;
- efficient, and nothing else broken.

Work was on a separate branch, `claude/weatherdesk-1.17.0`, built on 1.16.0.
Nothing is merged or released.

### What I found first
| Before | Problem |
|---|---|
| Speed of 8 + 0.9 × km/h pixels per second, capped at 80 km/h | Small scenes raced (the widget at about 3 times the main window's pace); at 80 km/h the main window was crossed in about 7 s |
| Direction as a left/right sign of -sin(from) | The from-to conversion was already right, but only the sign was used: a north-easterly looked like an easterly |
| The new wind applied at once | A refresh with a new direction flipped every cloud instantly; rain, snow and fog too |
| Wind data | Real: the forecast's current speed (km/h) and direction (degrees FROM) from all seven providers, so nothing to invent |

### Decisions (with reasons)
| Decision | Reason |
|---|---|
| Speed in scene widths per second, from a table of crossing times (150 s calm to 19 s at 100 km/h and above) | The same wind looks the same at any size; a table is easy to read, test and tune; the cap keeps a gale under 1.5 px per frame |
| East to the right, as on a weather map | It's how the scene already worked, so existing behaviour is kept |
| The east-west part of the wind, with a 30% floor | A side view can't show north/south; the floor keeps the sky moving |
| Easing with a 3-second time constant, speed and direction separately | Smooth: 95% in 9 s, and a reversal slows, turns and speeds up |
| The first real forecast is shown at once | Easing from the placeholder would show an invented wind for about 10 s |
| Rain, snow and fog use the eased direction | They turn with the clouds; with a steady wind they're exactly as before |
| An unusable speed counts as calm; a missing direction drifts right | Never invent a wind; the direction default is unchanged from before |

### Problems found while testing
1. **A real bug.** The app test showed the main window and the widget
   disagreeing for about 10 s after start. The main window had eased from
   the placeholder wind (10 km/h) to the real one, while the widget started
   with the real one. Fixed: the first real forecast replaces the
   placeholder at once. A regression test was added.
2. **A compatibility gap.** An existing rain test built conditions with only
   the old left/right flag, and the new field ignored it. Fixed in the code:
   the new field now defaults to that flag.
3. **Three mistakes in my own tests:**
   - a wrong direction expectation for 350°;
   - an "infinite speed = capped" expectation, now treated as bad data;
   - wrong easing arithmetic: 15 s is 5 time constants, which leaves 1.8%
     of a full reversal still to go.

   The easing test now checks every frame against the exact formula.
4. **CPU.** The soak reading looked higher (17.7%). A direct comparison of
   1.16.0 and 1.17.0 (3 runs each) showed no increase, so it was run-to-run
   variation.

### Still needs your desktop
- How the speeds feel on your screen: the table is easy to tune.
- Watching a real refresh where the wind changes.

Created By Shane BlackbuRn

## Session 1z – 2026-11-21 – v1.18.0 (forecast playback)

**Context:** Shane asked whether The Weather Channel could be added. Its
forecasts come from The Weather Company, which WeatherDesk's Weather
Underground provider already uses with his PWS key. The full service is
enterprise-only, with a 30-day trial. I recommended not adding it unless he
gets a key. He then asked what WeatherDesk could have that other apps
probably don't, and chose idea 2: **forecast playback in the animated sky.**

Work was on a separate branch, `claude/weatherdesk-1.18.0`, built on 1.17.0.
Nothing is merged or released.

### What I checked first
- **Hourly data:** time, temperature, chance of rain, rain amount and
  weather code. No wind, no cloud cover.
- **The Sun** was placed from a clock plus today's sunrise and sunset.
- **The Moon was always calculated for the real "now"** (a bug for any other
  moment).
- **A change of weather type rebuilt the clouds:** a visible jump.

### Decisions (with reasons)
| Decision | Reason |
|---|---|
| A bar under the sky: ▶/⏸, a 24-hour slider in 15-minute steps, and Now | Simple; plays the day in about 24 s at an hour a second |
| The sky and the card's text follow the hour; details, 7-day list, tray and desktop widget stay live | Clear what's a forecast; the widget is a glance at now |
| The wind stays as now during playback, said in the tooltip and the guide | The hourly data has none, and inventing one would mislead |
| Cross-fade every weather change over 0.8 s (clouds, rain/snow/fog, sky tint, the veil over Sun, Moon and stars); live too | Playback changes the weather every hour; a refresh benefits the same way |
| Several outgoing layers, each fading from its own visibility (bounded at 3 cloud layouts and 2 particle sets) | Fast playback changes the weather mid-fade; this never pops |
| Rain, snow and fog code moved into methods unchanged, not rewritten | The outgoing weather keeps moving while it fades, with the same physics; less risk |
| No fade with animations off | The fade would never move on, and the new clouds would never appear |
| The status line kept short ("▶ Forecast for Sun 13:15") | A longer line pushed the mini forecast from 6 days to 4 (seen in the first screenshot) |

### Problems found while building and testing
1. **The Moon bug,** fixed and covered by a regression test.
2. **Things that still switched instantly.** Pixel tests showed that the
   sky's tint, rain/snow/fog and the Sun/Moon/stars veil all jumped. A
   clear-to-cloudy change also skipped the fade. All of these now fade too.
3. **A behaviour change I nearly made.** `sky_colors()` briefly returned
   the mid-fade colours. An existing test showed that callers expect the
   colours for the conditions, so the fade got its own method instead.
4. **A flicker risk.** A redraw during playback would set the live sky and
   then the hour's sky. It now goes straight to the hour (covered by a
   test).
5. **Two Earth Globe tests failed on unchanged 1.17.0 code at today's time:**
   - one counted the weather sky's Moon drawings (the real Moon was up);
   - the other measured before a status line wrapped, 15 px shorter
     (measured).

   Both tests are fixed without weakening them. I also confirmed the Moon
   test still fails when the globe really re-renders.
6. **My own test bugs:**
   - comparing images as huge lists made a failing check look like a
     hang;
   - a resize test used a hidden widget, which gets its resize later;
   - one test wrongly treated lightning as a pop.

   All are corrected.
7. **CPU, compared directly:** 1.17.0 averaged 30.1%, 1.18.0 31.2%
   (4 runs each). The spread within each version is larger than that, so
   there's no measurable increase, at most about 1 point.

### Still needs your desktop
- How playback looks and feels on your screen.
- The emoji drop before the rain chance: the build machine lacks the colour
  emoji font.
- Whether an hour a second is a good speed.

Created By Shane BlackbuRn

### Same session: demo recording

**Request:** "lets do it": record forecast playback for the README and for
forum posts.

- **Recording:** made from the real main window via the normal data path,
  with a believable sample day for Auckland (the build machine can't reach
  any weather service, so no real forecast). Captured at about 8 frames a
  second and encoded at real speed: a GIF for the README (760 px, 3.2 MB)
  and an MP4 for posts (920 px, 0.6 MB). The README caption says it's
  sample data.
- **Found in the recording:** the pause button's "⏸" text showed as a tiny
  square, because not every font has that symbol. The button now uses the
  desktop theme's play and pause icons; the two tests that read its text
  check the tooltip and icon instead.
- **To do on your desktop:** for an advert with real weather, record your
  own screen while playback runs (Cinnamon: Ctrl+Shift+Alt+R starts and
  stops a screen recording).

- **"could be a lot smoother":** the first recording grabbed the window in
  real time and only managed about 8 frames a second. It was re-recorded by
  taking over the animation clock: exactly 1/30 s of animation per frame,
  with every frame captured.
  - Measured: none of the 720 playback frames repeats the one before; the
    median change between frames is 0.45 (mean pixel) and the largest 5.0.
  - Encoded as an MP4 at 30 frames a second (0.95 MB), and a GIF at 25
    (exact GIF timing, 7.1 MB, 760 px).
  - The bar shows the pause icon throughout (the first re-take showed ▶,
    because the script drove the slider itself).

Created By Shane BlackbuRn

## Session 2a – 2026-11-21 – v2.0.0 (renamed to RBSB-Weather)

**Request:** "I need to change the name of my app. WeatherDesk is too common."
Shane first chose Weatherglass from my suggestions, then found that common too:
"I'd like to change the name to RBSB-Weather". The Weatherglass work was
discarded before anything was committed, and the branch reset to the released
1.18.0 and renamed `claude/rbsb-weather-2.0.0`. Nothing is merged or released.

### Decisions (with reasons)
| Decision | Reason |
|---|---|
| "RBSB-Weather" for everything shown; `rbsb-weather` for the command, package, folders, menu file and icon; `rbsb_weather` only for the Python package folder | Debian package names and Linux commands are lower case; Python module names can't contain `-` |
| Version 2.0.0 | The package, command and folders changed: a big step for users even with no new features |
| Copy WeatherDesk's settings, cache, keyring keys and login entry on first start; never move or delete | Nobody loses anything; going back to WeatherDesk still works |
| Only copy into a folder with no data of its own; marker file; retry on failure | Can never overwrite RBSB-Weather data; can't run twice; a full disk doesn't lose the chance |
| Rename the old login entry to `.migrated` instead of deleting it | It would otherwise start a second time (the `weatherdesk` link starts RBSB-Weather), and nothing of Shane's is deleted |
| Ask a running WeatherDesk to hand over through its old socket, then copy | It saves its settings as it quits, so the copy includes its latest state |
| Debian `Replaces`/`Conflicts: weatherdesk` plus a `/usr/bin/weatherdesk` link | One `apt install` swaps the packages; old shortcuts and habits keep working |
| Historical CHANGELOG, TRANSCRIPT and TEST_REPORT entries keep the old name | They record what happened under that name |

### Problems found while building and testing
1. **My blanket rename made every lower-case "weatherdesk" the module name.**
   Command, folders, menu file and icon names were then corrected one by one
   to `rbsb-weather`, and `build_deb.sh` got separate package and module
   variables. A grep afterwards found no leftovers.
2. **The log is created in the cache folder before the copy,** so the new
   cache folder is never empty. The copy treats a folder holding only logs as
   empty and merges into it without replacing anything (tested).
3. **A test of the "interrupted copy" did nothing at first:** `shutil.copytree`
   binds its copy function when Python starts, so patching it had no effect.
   The migration now calls its own copy function, and the test really breaks
   the copy part-way.
4. **apt error during the real upgrade test:** "Pathname to install is not
   absolute". It came from the `--no-download` flag I added, not the package
   (apt had already removed weatherdesk). Re-run as Shane would type it, it
   installed cleanly; the whole upgrade was then repeated from scratch.

### Tested for real (in this sandbox)
- Full suite: 503 run, 501 passed, 2 skipped (environment-only), 0 failed.
- Real dpkg: installed WeatherDesk 1.18.0 running in the tray →
  `apt install ./rbsb-weather_2.0.0_all.deb` removed weatherdesk and installed
  rbsb-weather → launching `rbsb-weather` made the running WeatherDesk quit
  cleanly (exit 0) and took over; settings, both locations, °F, 12-hour,
  provider order, Station ID and both keys came across byte-identical; the
  login entry was swapped; the old folders are unchanged.
- Rollback to WeatherDesk 1.18.0 with apt, and a second one-step upgrade.

### Still needs your desktop (Linux Mint)
- The upgrade on your real profile, including keys in GNOME Keyring (the
  sandbox has no keyring, so that path was tested with a fake keyring only).
- The menu entry and icon under the new name, and the panel grouping.
- "Start at login" after a real reboot.

### For you to do on GitHub
- Rename the repository to `RBSB-Weather` (Settings → General → Repository
  name). GitHub redirects the old address.

Created By Shane BlackbuRn

## Session 2b – 2026-11-21 – v2.1.0 (check for updates)

**Context:** Shane tested 2.0.0 on Mint ("Working perfectly"), merged PR #3,
renamed the GitHub repository to RBSB-Weather and published the v2.0.0
release himself (this session isn't allowed to create releases; GitHub refused
with "not permitted for this session type"). He then asked "Is it possible to
add a check for updates", and chose "daily check turned on by default".

Work is on branch `claude/rbsb-weather-2.1.0`. Nothing is merged or released.

### Decisions (with reasons)
| Decision | Reason |
|---|---|
| Ask GitHub's "latest release" address; compare versions | The releases are already published there; no server of our own to run |
| Once a day, not in the first minute, using the existing minute timer and wall clock | Startup stays quick; works across sleep; no extra timers |
| Retry 3 hours after a failed check; a clock that went backwards counts as due | A short outage doesn't mean a day's wait; a bad clock can't block checks forever |
| Status-bar button, plus a tray notice once per version; never a pop-up window for an automatic check | Noticeable without nagging |
| Download to Downloads, verify against the release's SHA256SUMS, then open in the package installer | The user sees and approves the install; the app never runs as root; a damaged or tampered file is never offered |
| No checksum file, or the file not listed: refuse to download | An unverifiable package shouldn't be installed through the app |
| https and GitHub's own addresses only, also after redirects; size limits; strict file name | Nothing else can be fetched or written even if a reply is wrong |
| Never overwrite a file in Downloads; reuse an identical one | Shane's rule about user files |
| Last-check times in the cache folder, not settings.json | Settings shouldn't be rewritten every day just for a time stamp |
| Tests point the check at a closed local port | The test suite must never contact GitHub |

### Problems found while building and testing
1. **An older bug, found by the new tests:** at every start, the clean-up of
   forecasts for removed locations deleted every `.json` in the cache folder.
   That included provider status, the network-route memory, the cloud map's
   download record (so the cloud map was downloaded again each start) and the
   new update record. Present since at least 1.11.1. It now only removes
   forecast files, with a regression test.
2. **A segmentation fault in the update window tests** (intermittent). The
   update window deleted itself on close, and its "deleted" callback ran into
   a main window that was being destroyed. The window is now kept and reused.
   The window tests then ran 20 times in a row with no failure, plus 3 full
   runs of the update and core tests.
3. **Layout:** with no release notes to show, the text was spread down the
   window (seen in a screenshot). Fixed with a filler.

### Tested
- Full suite: 539 run, 537 passed, 2 skipped (environment-only), 0 failed.
- Against the **real GitHub**: the check found RBSB-Weather 2.0.0 (so 2.0.0
  users will be told about 2.1.0 once it's published). The download followed
  GitHub's redirect, passed the checksum, and is byte-identical to the
  2.0.0 package Shane tested.
- Screenshots of the update window: available, downloaded, up to date, error;
  and the status-bar button.
- Real package: installed 2.0.0 running → `apt install` 2.1.0 → 2.0.0 handed
  over cleanly. The installed 2.1.0 made its first automatic check 61 s after
  starting, against the real GitHub ("latest release is 2.0.0 (this is
  2.1.0)", nothing announced). After a restart, `updates.json` and
  `providers.json` were still there.

### Still needs your desktop (Linux Mint)
- Opening the downloaded .deb in Mint's package installer (the build machine
  has no desktop to open it in).
- The tray notice on your panel.
- The full path 2.1.0 → a later version can only be seen once a newer
  release than 2.1.0 is published. 2.0.0 has no update checker, so going
  from 2.0.0 to 2.1.0 is a normal manual install.

Created By Shane BlackbuRn

## Session 2c – 2026-11-21 – v2.1.1 (buy me a coffee)

**Context:** Shane published 2.1.0 (with help to attach its files), filled in
the repository's About box and topics, and set up a daily scheduled task that
checks whether RBSB-Weather shows in web searches. He mentioned a possible
trial version later, "but not at the moment". He then asked for a "buy me a
coffee for $0.99" line with his PayPal account in the About box and User Guide.

### Finding a PayPal link that works for his account
1. **PayPal.Me:** `paypal.me/my/settings` bounced back to his Summary page.
   That's the known sign PayPal.Me isn't offered for his account or country.
2. **Ko-fi** (pays into PayPal): Shane didn't want it. He wants a direct
   PayPal link.
3. **PayPal Donate button:** needs a confirmed charity.
4. **PayPal payment link with his Merchant ID:** this works without PayPal.Me,
   a charity or an email address. The Merchant ID is meant to be public.

When Shane pasted his account page it also showed his address, phone and ID
details. Only the Merchant ID is used. Nothing else was stored, and a test
makes sure no Gmail address is ever shipped.

### Fees, as told to Shane
PayPal takes a fixed fee per payment (NZ$0.45 for NZD donations, per PayPal's
fee page) plus a percentage. So on NZ$0.99 he keeps only about half. I
suggested $3 or "any amount"; he kept NZ$0.99.

### Tested
- Full suite: 545 run, 543 passed, 2 skipped (environment-only), 0 failed.
- 6 new tests. The About box and menu item were checked visually in a
  screenshot.
- PayPal refuses automated visits to its payment page, so Shane needs to
  check the link opens the right page in his browser. It should show "RBSB
  Brothers" and NZ$0.99. He shouldn't complete the payment, since PayPal won't
  let him pay himself.

Created By Shane BlackbuRn
