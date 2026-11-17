# WeatherDesk 1.13.0

A desktop weather app for Linux Mint (and other Ubuntu 24.04-based systems).
It shows current conditions, a 24-hour chart, a 7-day forecast, and the
temperature in your system tray. It uses the free Open-Meteo service, with
MET Norway (yr.no) as an automatic backup, so you don't need an account or an
API key. If you like, Settings → Weather Providers adds OpenWeather,
WeatherAPI.com, Visual Crossing or Tomorrow.io with your own API key, as the
primary provider or as backups.

**Created By Shane BlackbuRn**

*Shane's design and Claude's coding.* Every feature started as Shane's idea and
design; Claude (Anthropic's AI) wrote the code and the tests to his spec.

## Features

* Search for any city or town worldwide; save up to 50 locations and reorder them.
* Current conditions: temperature, feels-like, humidity, wind and direction,
  gusts, pressure, cloud cover, precipitation, UV index, and sunrise/sunset.
* An animated, realistic sky: the sky colour follows the local time of day,
  the sun and moon rise at the bottom left, arc across the sky and set at
  the bottom right at their real times, the moon shows its real phase (and is
  visible by day whenever it's really up), clouds drift
  with the wind, and there's rain, snow, fog and lightning.
* A mini forecast of 1–7 days, with animated icons, high/low and rain chance,
  in the bottom-right of the animated sky. It adapts to the space and stays
  put, with the setting sun or moon passing behind it.
* A floating desktop widget with the same animated sky, the temperature and
  when it was last updated.
* A Moon tab with a high-resolution picture of the current phase (correct
  for your hemisphere), moonrise and moonset, upcoming phases, and the next
  7 days. It's calculated on your computer, so it works offline, and you can
  save the moon as a 2048 px image.
* Earth Flat and Earth Globe tabs with the live day/night Earth, as a map or
  as a globe you can drag to spin. Each saved location shows its local time,
  whether it's day, twilight or night there, its temperature and an animated
  weather icon. Click a marker to select that place; the globe turns to face it.
  The globe zooms (wheel, +/−), and the real Sun, Moon (with its phase) and
  stars sit behind it, moving as it turns.
* Live satellite clouds on both Earth tabs, updated every 3 hours: white over
  the day side, hiding city lights at night.
* A 24-hour chart of temperature with the chance of precipitation.
* A 7-day forecast with high/low temperature, rain chance and amount, and wind.
* °C/°F, km/h · m/s · mph · knots, mm/inches, and a 12- or 24-hour clock.
  Switching is instant.
* Auto-refresh every 10–120 minutes, or turned off.
* A tray icon showing the live temperature, with optional close-to-tray and
  start at login.
* Offline fallback: the last forecast for each location is saved and shown,
  clearly labelled, when there's no internet.
* Single instance: launching it a second time brings the existing window forward.
* The in-app User Guide is under Help → User Guide (F1).

## Install

```bash
sudo apt install ./weatherdesk_1.11.1_all.deb
```

`apt` pulls in `python3-pyqt6` automatically. Launch **WeatherDesk** from the
menu (it's under Accessories), or run `weatherdesk` from a terminal.

To verify the download first:

```bash
sha256sum -c SHA256SUMS
```

## Update

Install the newer .deb the same way. Your settings and saved forecasts in
`~/.config/weatherdesk` and `~/.cache/weatherdesk` are kept. Then open
WeatherDesk: if an older copy is still running (for example in the tray), it
closes itself cleanly and the new version takes over. From 1.1.1 on this is
automatic; before that you had to quit the old copy first.

## Roll back / uninstall

```bash
sudo apt install ./weatherdesk_<older-version>_all.deb   # roll back
sudo apt remove weatherdesk                                # uninstall
rm -rf ~/.config/weatherdesk ~/.cache/weatherdesk          # optional: remove your data
rm -f ~/.config/autostart/weatherdesk.desktop              # if "Start at login" was on
```

## Run from source

```bash
sudo apt install python3-pyqt6
python3 -m weatherdesk            # from the project folder
```

Options: `--minimized` starts in the tray, `--verbose` turns on debug
logging, and `--version` prints the version.

## Tests

```bash
./run_tests.sh
```

The tests run fully offline against a local fake Open-Meteo server. They
cover parsing, network error paths, settings and cache safety, complete GUI
workflows, and stress/leak checks. The full log is written to
`test-results.log`. See `TEST_REPORT.md` for the latest results.

## Build the package

```bash
./build_deb.sh     # -> dist/weatherdesk_<ver>_all.deb, source tar.gz, SHA256SUMS
```

## Project layout

| Path | Purpose |
|---|---|
| `weatherdesk/api.py` | Open-Meteo client, response parsing, retries and the automatic backup (standard library only) |
| `weatherdesk/metno.py` | MET Norway client: the second weather source |
| `weatherdesk/providers/` | Weather providers: one module per service, the registry, the common-format normaliser and the ProviderManager (fallback chain, recovery, quota guards, status) |
| `weatherdesk/providers_dialog.py` | Settings → Weather Providers |
| `weatherdesk/keystore.py` | API key storage (system keyring or a 0600 file) and log redaction |
| `weatherdesk/sun.py` | Sunrise/sunset, day/night and "feels like" for providers that don't supply them |
| `weatherdesk/storage.py` | Settings and forecast cache (atomic JSON writes) |
| `weatherdesk/workers.py` | Background network threads |
| `weatherdesk/main_window.py` | The main window, tray, and menus |
| `weatherdesk/widgets.py` | 24-hour chart and tray icon drawing |
| `weatherdesk/scene.py` | Animated weather scenes, icons, and the shared animation clock |
| `weatherdesk/desktop_widget.py` | Floating desktop widget |
| `weatherdesk/moon.py` | Moon phase, illumination, rise/set (Meeus) |
| `weatherdesk/moon_render.py`, `moon_panel.py` | Moon images and the Moon tab |
| `tools/make_moon_texture_nasa.py` | Build moon images from NASA's CGI Moon Kit |
| `tools/make_moon_texture.py` | Generated fallback moon images |
| `weatherdesk/earth.py`, `earth_panel.py` | Sun position, day/night map blending, Earth Flat tab |
| `weatherdesk/clouds.py` | Live cloud map download, cache and blending |
| `weatherdesk/forecast_strip.py` | The mini forecast in the sky: adaptive layout, keeping clear of text and the Sun/Moon, drawing |
| `weatherdesk/sky.py` | Sun, Moon and stars behind the globe (positions, Moon orientation) |
| `weatherdesk/globe.py`, `globe_panel.py` | Globe projection and drawing (numpy or pure Python), Earth Globe tab |
| `weatherdesk/net.py` | Fast IPv4/IPv6 connection racing |
| `weatherdesk/diagnostics.py` | Help → Test connection |
| `weatherdesk/units.py`, `weather_codes.py` | Unit conversion and weather descriptions |
| `tests/` | Test suite and fake server |
| `packaging/` | Launcher, .desktop file, and icon |

## Adding a weather provider

1. Create `weatherdesk/providers/<name>.py` with a class derived from
   `Provider` and decorated with `@register`:
   * `info = ProviderInfo(...)`: id, name, whether it needs a key, website,
     credit, coverage, forecast days, hourly, limits, the features it supplies,
     sign-up and documentation links, and `min_interval_s` if its free
     allowance is small;
   * `default_base_url()`;
   * `_fetch(location, days)`: request the data (the key is `self.api_key`),
     convert it to a `Forecast`: WMO weather codes, °C, km/h, mm, hPa, %, and
     local times as `YYYY-MM-DDTHH:MM`. Leave anything the service doesn't
     supply as `None`;
   * optionally `_error_reason(body)` and `usage()`.
2. Import the module in `weatherdesk/providers/__init__.py`.
3. Add its documented response shape to `tests/provider_fixtures.py` and its
   tests to `tests/test_providers.py`.

The normaliser, fallback, key storage, Settings dialog, connection test and
the rest of the app need no changes.

## Data and privacy

The app sends only the search text and the coordinates of your saved
locations to Open-Meteo, and the coordinates to MET Norway or any other
provider when it's used (as the primary or a backup, chosen in Settings →
Weather Providers). API keys you add are sent only to their own provider and
are stored in the system keyring or a private file, never in the settings,
logs or reports. While an Earth tab is open with **Live clouds** on,
it also downloads the global cloud map from clouds.matteason.co.uk (at most
once an hour; nothing about you or your locations is sent). There's no
tracking or analytics. Weather data
comes from [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0) and
[MET Norway](https://api.met.no/) (CC BY 4.0). Earth maps
come from [Solar System Scope](https://www.solarsystemscope.com/textures/)
(CC BY 4.0). Moon imagery comes from NASA's Scientific Visualization Studio
(public domain). Live clouds come from [Live Cloud Maps](https://github.com/matteason/live-cloud-maps)
by Matt Eason (CC0) and contain modified EUMETSAT data.
