# RBSB-Weather User Guide

RBSB-Weather shows current conditions, a 24-hour chart and a 7-day forecast for
any place in the world. It needs no account or API key.

RBSB-Weather was called **WeatherDesk** before version 2.0.0. Only the name
changed; see [Coming from WeatherDesk](#coming-from-weatherdesk).

## Getting started

1. Type a city or town into the search box at the top (or press **Ctrl+L**).
2. Matching places appear after a moment. Click one, or press **Enter** to pick
   the highlighted one.
3. The place is added to **Saved locations** on the left and its weather loads.

If several places share a name (for example *Hamilton*), check the region and
country shown next to each result.

## Reading the screen

* **Top card** – current temperature, conditions, "feels like", humidity, wind
  speed and direction, gusts, pressure, cloud cover, precipitation, today's
  maximum UV index, and sunrise/sunset in the location's local time.
* **Next 24 hours** – the orange line is temperature; the blue bars and
  percentages are the chance of precipitation for each hour.
* **7-day forecast** – high / low temperature, chance of rain with expected
  amount, and maximum wind for each day.
* **Status bar** – when the data was last downloaded. *saved copy* means you are
  looking at the last forecast saved on this computer (for example while
  offline). A warning appears if the data is more than 3 hours old.

## Animated weather

The top card shows a live sky for the selected place:

* The **sky colour** follows the local time there, including dawn and dusk.
* The **sun** and **moon** follow the same arc across the sky at their
  real times there:
  - each rises from just below the horizon at the bottom left;
  - it climbs to the top of the sky halfway between rising and setting;
  - it sinks and disappears below the bottom right when it sets.

  The sun is shown by day. The moon is shown whenever it's really above the
  horizon, day or night, in its real phase, so you'll often see both
  together. By day it's pale, like the real daytime moon. When it's below
  the horizon it isn't shown. **Stars** come out at night. Everything
  glides smoothly, minute by minute.
* **Clouds** drift with the current wind from the forecast:
  - **Speed:** the stronger the wind, the faster they move. In calm air
    they still drift gently, taking about 2½ minutes to cross the sky. At
    10 km/h it's about 70 seconds, at 40 km/h about 30 seconds, and from
    100 km/h it's capped at about 19 seconds, so a gale stays easy to watch.
    Distant clouds move more slowly than near ones.
  - **Direction:** they move the way the wind is blowing *towards*. Forecasts
    give the direction the wind comes *from*: a westerly blows from the west
    towards the east.
  - **East is to the right,** as on a weather map, so a westerly moves the
    clouds right and an easterly moves them left. The picture is a side view,
    so a wind blowing mostly north or south can't be shown head-on. Those
    clouds drift slowly towards whichever side the wind leans.
  - **When the forecast updates** with a different wind, the clouds ease
    into the new speed and direction over a few seconds instead of jumping.
    A change of direction slows them, turns them round, and speeds them up
    again.
  - **Main window and desktop widget:** the clouds take the same time to
    cross both, whatever their size.
* **Rain** is slanted by the wind, **snow** drifts down, **fog** rolls past,
  and **thunderstorms** flash with lightning. Rain, snow and fog turn round
  smoothly with the clouds when the wind changes direction.

### Forecast playback: the next 24 hours in the sky

The bar under the sky lets you see the coming hours as weather you can watch,
not just numbers:

* **▶ Play** runs the next 24 hours in the sky, an hour a second (about 24
  seconds in all). Press **⏸** to pause.
* **Drag the slider** to any time in the next 24 hours, in 15-minute steps.
* **Now** goes back to the weather now.

For the time shown, the sky has:
* **that hour's weather** from the hourly forecast: clear, cloudy, rain,
  showers, snow, fog or thunderstorms;
* **the Sun and Moon where they'll be,** with day, dusk and night at the
  right times (tomorrow's hours use tomorrow's sunrise and sunset);
* **the card text for that hour:** its temperature, its weather and its
  chance of rain, marked "▶ Forecast for …".

When the weather changes from hour to hour, the clouds, rain and sky colour
blend smoothly into the next. They do the same when a refresh brings new
weather.

**The clouds keep the wind of now,** because the hourly forecast doesn't
include wind. Hover over the time to see this note.

**The rest stays live:** the details beside the sky, the 7-day list, the tray
icon and the desktop widget keep showing the weather now. Choosing another
place returns to now.

Some providers don't give an hourly forecast. Weather Underground with a
weather-station key is one. While such a provider supplies the weather, the
bar says so instead.

### Mini forecast in the sky

The bottom-right corner of the top card (and of the desktop widget) shows a
short forecast. Each day has its name ("Today", "Tomorrow", "Wednesday" or
"Wed"), an **animated icon**, the **high and low**, and the **chance of
rain**. The icons move:
- the sun's rays turn;
- clouds drift;
- rain and snow fall, with more and faster drops in heavy rain;
- fog rolls past;
- thunderstorms flash now and then;
- windy days show sweeping gusts.

How many days you see depends on the space. A small widget shows 1–2 days,
a medium one 3–5, and a large card up to 7. It adjusts as you resize the
window or change the widget's size, and never shrinks the text to fit more.

The forecast keeps clear of the text on the card and stays fixed in the
bottom-right corner, with the same number of days all day. When the sun or
moon sets through that corner, it passes behind the forecast, whose soft
shade keeps the text readable. It updates with the weather, follows the
selected place, and uses your temperature unit.

The 7-day forecast below also has small animated icons.

To turn animation off, untick **View → Animated weather**. The scene stays
as a still picture. Animation pauses by itself whenever the window is
hidden or minimised, so it uses no CPU then.

## Moon

Open the **Moon** tab, next to **Forecast**, to see:

* a large, realistic picture of the moon, **turned exactly as it appears in
  that place's sky**. Near the equator a crescent can lie on its back (the
  "smiling moon"); from the southern hemisphere it's turned over compared
  with northern views; and the angle changes through the night. The **In the
  sky** line says whether it's up now (with its height and direction) or
  below the horizon, in which case it's shown as it will look at its highest
  point;
* the phase, % illuminated, age in days, and whether it's waxing or waning;
* **moonrise and moonset today**, in the selected place's local time;
* the dates of the next new, first quarter, full and last quarter moons;
* **the next 7 days**, each with its moon picture (as it looks at its highest
  that day; hover over it for the time), phase, % illuminated, rise (↑) and
  set (↓).

The phase itself, how much is lit, is the same everywhere on Earth at the
same moment. What changes from place to place is its tilt, rise and set
times, and which day a phase falls on in local time.

"no moonrise" or "no moonset" on a day is normal: the moon rises about 50
minutes later each day, so some days miss one. Near the poles it can stay
up or down all day.

**Save high-resolution image…** saves the current moon as a 2048 × 2048 PNG.

Moon data is calculated on your computer, so it also works offline.

## Earth Flat and Earth Globe

The **Earth Flat** tab shows a live world map with day and night as they are
right now. City lights shine on the night side, and the line between them is
the real sunrise/sunset line. The yellow dot marks where the Sun is directly
overhead; the pale dot marks the Moon.

Your saved locations appear on the map. The selected one pulses and shows a
card with:

* its **local time**;
* whether it's **Day**, **Twilight** or **Night** there, and the Sun's height
  above (+) or below (−) the horizon;
* its **temperature** with an animated weather icon.

Pick a place in **Saved locations**, or **click its marker on the map**, to
move the card there. The map refreshes every 5 minutes while the tab is open.

The **Earth Globe** tab shows the same live Earth as a globe, with the same
markers and card:

* **Drag** anywhere on the globe to spin it.
* **Select a place** (in Saved locations, or click its marker) and the globe
  turns to face it. **Centre on selected**, or a double-click, turns it back.
* Places round the far side are hidden until you spin them into view.
* Tick **Rotate slowly** to let it turn on its own. It pauses while you're
  on another tab.
* **Zoom** with the mouse wheel, the **−** / **+** buttons in the top-right
  corner, or the **+** and **−** keys (**0** resets). It goes from 60% to 300%,
  gliding smoothly and sharpening as soon as it settles.
* Behind the globe you'll see the **real Sun, Moon and stars** where they
  are right now. As the globe turns, the Sun sets behind the Earth just as
  the middle of the view goes into night. The Moon shows its real phase,
  lit on the side facing the Sun. When either is out of view, a small marker
  at the edge shows which way it is.
  The Sun and Moon are drawn larger than true scale so you can see them. The
  Moon uses the same high-resolution NASA images as the Moon tab. When the
  Sun is just behind the Earth, its light blazes round the edge, like a
  sunrise seen from orbit.

### Live clouds

With **Live clouds** ticked (on by default, in either Earth tab), real
satellite clouds are laid over the Earth. By day they're white; at night they
hide the city lights beneath them. The map is made from weather-satellite
images about every 3 hours, and the line above the map shows the time of the
one you're seeing.

RBSB-Weather checks for a newer cloud map at most once an hour, and only while
an Earth tab is open. Offline, it keeps showing the last one. Untick
**Live clouds** to turn them off; the setting is remembered.

Near the poles the satellites can't see, so the cloud map's edges there are
filled in, and now and then a missed patch shows as a square gap.

Both tabs share the same day/night picture, so the globe adds no extra
background work. Without python3-numpy the globe is a little less sharp,
and Rotate slowly is unavailable.

## Wind

The **🌬 Wind** tab shows the wind over the whole world on a globe, 10 m above
the ground:

* **Colours** show the wind speed, from calm blue through green and yellow to
  red and purple for storm-force winds. The key under the globe is in your
  wind unit (View → Units).
* **Moving streaks** follow the wind, so you can see where the air is going
  and spot the swirls of lows and highs. Untick **Moving streaks** to stop
  them (they also stop when View → Animations is off, or when another tab is
  showing).
* **Hover** anywhere on the globe to see the wind there: its speed and the
  direction it's coming **from**, as weather forecasts give it. Hovering over
  one of your saved places shows the wind at that place.
* **Drag** to turn the globe, use the **mouse wheel** or **+ / −** to zoom,
  and click **Centre on selected** to turn to your selected place.
* Coastlines are drawn so you can see where the land is.

The wind comes from NOAA's Global Forecast System (GFS), the US weather
service's free worldwide forecast. It has a value every 1° of latitude and
longitude (about 110 km apart), so small local effects like sea breezes and
gusts around hills don't show. The line above the globe says which time the
map is for. It's always the forecast closest to now (GFS has one every 3
hours), from the newest run that's been published.

The wind is only downloaded when you open the tab (about 200 KB), then again
every 3 hours while you use it. It's saved, so the tab works offline with the
last map. If NOAA can't be reached, the saved map stays up and the line above
the globe says so.

## Desktop widget

Tick **View → Desktop widget** to put a small animated weather card on your
desktop. It shows the selected location's sky, temperature, conditions, and
today's high and low.

The top-right corner shows when the weather was last updated, for example
**↻ 19:30**. Hover over it for details. It turns amber, with how long ago
(for example "(2 h ago)"), if the weather hasn't been updated for a while,
the last update failed, or it's showing a saved copy while offline.

Under the place name, in small text, is the weather provider the forecast came
from, for example **Open-Meteo**. It says **(backup)** when your main provider
couldn't be reached and a backup supplied the weather, and **· saved copy**
when it's showing the last saved forecast while offline. Hover over it for
details.

* **Drag** it to move it. Its position is remembered.
* **Double-click** it to open RBSB-Weather.
* **Right-click** it for Refresh, Size (small, medium or large), Keep on top
  of windows, Lock position, and Hide widget.
* **Lock position** (right-click) stops the widget being dragged by accident.
  It stays exactly where it is, even after a restart, and double-click and
  right-click still work. Untick it to move the widget again. If its spot is
  ever off-screen (for example, a monitor was unplugged), it still moves back
  onto your screen.

By default it sits underneath your windows like a desktop gadget. The
widget keeps working while the main window is closed to the tray.

## Saved locations

* Click a location to switch to it. Data newer than 10 minutes is shown
  straight away without re-downloading.
* **▲ / ▼** change the order. **Remove** deletes the selected location and its
  saved forecast.
* Up to 50 locations can be saved.

## Refreshing

* Press **F5**, click **⟳ Refresh**, or use the tray menu.
* **View → Auto refresh** updates the selected location every 10–120 minutes
  (default 30), or never. The main window and the desktop widget both update,
  even while the window is closed to the tray.
* The timing goes by the clock: if your computer has been asleep, the weather
  updates within a minute of waking. If an update fails (for example, no
  internet), it tries again after 5 minutes rather than waiting a whole
  interval.
* **At startup every saved location updates**, not just the one on screen.
  The one you're looking at updates first, then the others one at a time,
  1½ seconds apart, so a small free allowance isn't used up in a burst. This
  includes RBSB-Weather starting at login. If the internet isn't ready yet, as
  often happens straight after the computer boots, each location is tried
  again after 30 seconds, then 1, 2 and 5 minutes; until then its last saved
  forecast stays on screen. A location updated in the last 2 minutes (for
  example, if you've just restarted RBSB-Weather) is skipped. To update only
  the location on screen at startup, untick **View → Auto refresh → Update
  all locations at startup**.

## Units

**View → Temperature / Wind speed / Precipitation**. Changing units is instant
and does not re-download anything.

**View → Time format** switches every clock in the app between **24-hour**
(19:30) and **12-hour** (7:30 pm). That covers the forecast, sunrise and
sunset, the 24-hour chart, the Moon tab, both Earth tabs, the desktop widget
and the status bar. It changes straight away without downloading anything,
and is remembered.

## System tray

* **View → Show tray icon** puts the current temperature in your panel. Click it
  to show or hide the window; right-click for Refresh and Quit.
* **View → Close to tray** keeps RBSB-Weather running in the tray when you close
  the window. Use **File → Quit** (Ctrl+Q) or the tray menu to exit fully.
* **View → Start at login** starts RBSB-Weather minimised to the tray when you
  log in.

Only one copy of RBSB-Weather runs at a time; launching it again brings the
existing window to the front.

**Updating:** after installing a new version, just open RBSB-Weather again.
If an older version is still running (for example in the tray), it saves its
settings and closes, and the new version opens in its place. The status bar
confirms the update. Copies older than 1.1.1 take about 6 seconds to be
recognised and replaced.

## Updates

RBSB-Weather checks GitHub once a day for a newer version. The first check is
a minute after it starts, so opening the app is never slowed down. If there's
a newer version:

* **⬆ Update available** appears at the bottom right of the window. Click it
  to see what's new.
* The tray shows a notice once (not every day).

Nothing is installed without you. In the update window:

* **Download and Install** downloads the new package to your Downloads
  folder and checks it against the release's checksum. A download that doesn't
  match is deleted, never installed. Then your package installer opens: click
  **Install** and enter your password. Start RBSB-Weather again afterwards and
  the new version takes over.
* **View on GitHub** opens the release page.
* **Skip This Version** stops reminders about that version. A later version is
  still announced, and **Help → Check for Updates…** still shows it.

**Help → Check for Updates…** checks straight away. To turn the daily check
off, untick **Settings → Check for updates automatically**.

The check only contacts GitHub (github.com and its download servers). It sends
nothing about you except the app's version, which every web request includes.
If GitHub can't be reached, the app tries again 3 hours later.

## Working offline

The last successful forecast for each location is saved. If the internet is
unavailable, RBSB-Weather shows that saved copy, marks it as such in the status
bar, and shows *Couldn't update* with the reason in the top card, plus how
old the weather on screen is. While auto refresh is on, a failed update is
retried after 30 seconds, then 1, 2 and every 5 minutes until it works.

## Weather providers

Open **Settings → Weather Providers…** (Ctrl+,). The list on the left shows
every weather service RBSB-Weather knows and its status:

| Symbol | Meaning |
|---|---|
| ✓ Working | its last update or test succeeded |
| ⚠ Not working | its last update or test failed (the reason is shown) |
| 🔑 Needs an API key | add a key before it can be used |
| ○ Not used yet | ready, but hasn't supplied the weather yet |
| … Planned | researched, not integrated yet |

Select a provider to see its coverage, how many days and hours it forecasts,
its free allowance and limits, which values it supplies, which values
RBSB-Weather calculates for it, its last successful update, the usage it
reports (for example Tomorrow.io's requests left today), and links to sign up
and to its documentation.

**Available now**

| Provider | Key | Free allowance | Forecast |
|---|---|---|---|
| Open-Meteo | none | fair use | 7 days, hourly |
| MET Norway | none | fair use | 7 days, hourly for about 2½ days |
| OpenWeather | free key | 1,000 One Call calls a day (separate subscription), or 5-day/3-hour with a plain free key | 8 or 5 days |
| WeatherAPI.com | free key | 100,000 calls a month | 3 days (free), 14 (paid) |
| Visual Crossing | free key | 1,000 records a day (a forecast = 1) | 7 of 15 days, hourly |
| Tomorrow.io | free key | 500 a day, 25 an hour | 5 days, 120 hours hourly |
| Weather Underground | weather-station (PWS) owner's key | about 1,500 a day | today + 5 days; no hourly |

AccuWeather and Weatherbit are listed as planned; the dialog says why.

**Weather Underground** keys are given to members who send data from a
personal weather station (wunderground.com → My Profile → API Keys). The
forecast comes from The Weather Company; current conditions come from a
weather station: enter your station's ID under *Settings for this provider*,
or leave it empty to use the nearest station that's reporting (stations that
are offline, failing quality checks or more than 2 hours old are skipped).
Stations don't report a condition, so it comes from the forecast for this
part of the day, corrected by the station's rain gauge (no rain falling
shows the cloud instead; rain falling shows rain). A PWS key has no hourly
forecast, so the 24-hour chart says so while Weather Underground supplies
the weather.

**API keys.** Select the provider, click **Add key…**, paste the key and
click **Save key**. RBSB-Weather tests it straight away. Once saved, a key is
never shown again (only "Saved ••••••••"); use **Change key…** or **Remove
key**. **Test connection** makes one real request and shows the result; if the
key field is open it tests the key you typed without saving it.

Keys are kept in your desktop's keyring (GNOME Keyring / KWallet, unlocked
with your login) when the `python3-keyring` package is installed, otherwise in
`~/.config/rbsb-weather/keys.json`, which only you can read. They are never
written to the settings file, the log, the connection-test report or the
screen.

**Primary and backups.** Choose the **primary provider**, then tick the
**backups** to use and put them in order (▲/▼). If the primary can't supply
the weather, the backups are tried in order, and the status bar shows
"from … (backup)". A provider that needs a key and has none is skipped.

**When the primary fails**, RBSB-Weather can:

* return to the primary at the next update;
* try the primary again after 15 minutes, 30 minutes (the default) or 1 hour;
* stay on the backup until the backup fails.

**Use the primary now** asks the primary first at the next update.

To protect small free allowances, RBSB-Weather asks Tomorrow.io at most every
10 minutes per location, and OpenWeather and Visual Crossing at most every
5 minutes; a refresh in between shows the forecast it already has.

**Different services, same display.** Every provider's data is converted to
the same format: °C, km/h, mm, local time, and the same weather conditions,
so the scene, icons, Sun and Moon, mini forecast and desktop widget look the
same whichever service supplies them. When a service doesn't supply
something, RBSB-Weather calculates it only if it can do so exactly (sunrise and
sunset, day or night, "feels like"); otherwise the value shows "–" rather than
a guess. Some services forecast fewer than 7 days (WeatherAPI.com's free plan
gives 3, Tomorrow.io 5); RBSB-Weather shows the days it has.

**Bad data is caught.** Values that can't be real (a temperature of 500 °C,
negative wind, a pressure of 50 hPa) are shown as "–" instead, and an unknown
weather condition is worked out from the cloud and rain readings rather than
shown as clear sky. If a service's whole reply can't be used, that counts as
a failure and the backups take over, exactly as if it were offline.

## If weather is slow or won't load

Open **Help → Test connection…**. It checks, step by step:

* how long the name lookup (DNS) takes,
* whether IPv4 and IPv6 connections work,
* how long a real location search and forecast download take, from
  Open-Meteo and from the backup (MET Norway),

then gives a short summary. **Copy report** puts the results on the clipboard
so you can share them. You can also run the same test from a terminal with
`rbsb-weather --diagnose`.

RBSB-Weather automatically works around two common network faults:

* **IPv6 offered but broken.** It switches to IPv4.
* **Secure connections that stall** ("handshake operation timed out"). Some
  routes silently drop large packets. RBSB-Weather notices the stall within 6
  seconds, retries using smaller packets, then retries once more with the
  smallest packets and a longer wait, and remembers what worked for that
  server for a week, so only the first update is slow. If all of that
  fails, the backup providers are used.

If Test connection says a handshake **STALLS** but **works with small
packets**, it's this second fault. RBSB-Weather is already handling it, but
the cause is on the network route. A router's MTU setting, a VPN, or
antivirus that inspects HTTPS are the usual suspects.

## Files

* Settings: `~/.config/rbsb-weather/settings.json`
* API keys (only if your desktop has no keyring): `~/.config/rbsb-weather/keys.json`, readable only by you
* Provider status (last success, last error, usage; never keys): `~/.cache/rbsb-weather/providers.json`
* Saved forecasts, the cloud map and log: `~/.cache/rbsb-weather/`
* When updates were last checked: `~/.cache/rbsb-weather/updates.json`
* The world wind map (Wind tab): `~/.cache/rbsb-weather/wind/`

Installing a newer RBSB-Weather never touches these files, so your locations,
settings and API keys carry over. Removing the package leaves them too.

Deleting these files resets RBSB-Weather. If the settings file is ever
damaged, it is moved aside to `settings.json.corrupt-<time>` and defaults are
used, so nothing is silently lost.

## Coming from WeatherDesk

The first time RBSB-Weather starts, it copies everything over from WeatherDesk:
your saved locations and settings, saved forecasts, API keys (from the keyring
or `keys.json`) and "Start at login". The status bar says what was carried over.
If WeatherDesk was still running in the tray, it closes itself first so nothing
it was about to save is lost.

The old folders (`~/.config/weatherdesk` and `~/.cache/weatherdesk`) are left
untouched, so you can switch back to a WeatherDesk package if you need to.
Once you're happy, you can delete them. The `weatherdesk` command still starts
RBSB-Weather, and the menu still finds it if you search for "weatherdesk".

## Keyboard shortcuts

| Key | Action |
|---|---|
| Ctrl+L | Find a location |
| F5 | Refresh |
| F1 | This guide |
| Ctrl+Q | Quit |

## Support RBSB-Weather

☕ If you enjoy this app, consider buying me a coffee for NZ$0.99: [Buy me a coffee with PayPal](https://www.paypal.com/cgi-bin/webscr?cmd=_xclick&business=M4EDN77T6EEPJ&item_name=Coffee+for+RBSB-Weather&amount=0.99&currency_code=NZD)

You'll find the same link under **Help → Buy Me a Coffee…** and in **Help → About**.
It opens PayPal in your browser, where you can pay with your PayPal account or a card.
RBSB-Weather stays free either way.

## Credits

Weather data by [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0) and
[MET Norway](https://api.met.no/) (CC BY 4.0), or, if you add their keys,
[OpenWeather](https://openweathermap.org/), [WeatherAPI.com](https://www.weatherapi.com/),
[Visual Crossing](https://www.visualcrossing.com/), [Tomorrow.io](https://www.tomorrow.io/) and
[Weather Underground](https://www.wunderground.com/).
The status bar always credits the service supplying the weather on screen.

Earth maps by [Solar System Scope](https://www.solarsystemscope.com/textures/)
(CC BY 4.0), based on NASA imagery. Moon imagery from NASA's Scientific
Visualization Studio (CGI Moon Kit). World wind from NOAA's Global Forecast
System (GFS), public domain. Live clouds by
[Live Cloud Maps](https://github.com/matteason/live-cloud-maps) (Matt Eason,
CC0); contains modified EUMETSAT data.

**Created By Shane BlackbuRn**
