#!/usr/bin/env bash
# Build rbsb-weather_<version>_all.deb and a clean source archive into dist/.
# Created By Shane BlackbuRn
set -euo pipefail
cd "$(dirname "$0")"

VERSION=$(python3 -c "import re;print(re.search(r'__version__ = \"(.+?)\"', open('rbsb_weather/__init__.py').read()).group(1))")
PKG=rbsb-weather      # Debian package, command, desktop file and icon
MOD=rbsb_weather      # Python package folder
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/${PKG}_${VERSION}_all"
mkdir -p dist

# --- application files
install -d "$ROOT/usr/lib/$PKG/$MOD" "$ROOT/usr/bin" "$ROOT/usr/share/applications" \
           "$ROOT/usr/share/icons/hicolor/scalable/apps" "$ROOT/usr/share/doc/$PKG" "$ROOT/DEBIAN"
install -m 644 rbsb_weather/*.py rbsb_weather/USER_GUIDE.md "$ROOT/usr/lib/$PKG/$MOD/"
install -d "$ROOT/usr/lib/$PKG/$MOD/providers"
install -m 644 rbsb_weather/providers/*.py "$ROOT/usr/lib/$PKG/$MOD/providers/"
install -d "$ROOT/usr/lib/$PKG/$MOD/assets"
install -m 644 rbsb_weather/assets/*.jpg rbsb_weather/assets/*.json "$ROOT/usr/lib/$PKG/$MOD/assets/"
install -m 755 packaging/rbsb-weather.sh "$ROOT/usr/bin/$PKG"
# the old command keeps working for anyone used to it (or with it in scripts/shortcuts)
ln -s "$PKG" "$ROOT/usr/bin/weatherdesk"
install -m 644 packaging/rbsb-weather.desktop "$ROOT/usr/share/applications/$PKG.desktop"
install -m 644 packaging/rbsb-weather.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/$PKG.svg"
install -m 644 README.md "$ROOT/usr/share/doc/$PKG/README.md"
gzip -9n -c CHANGELOG.md > "$ROOT/usr/share/doc/$PKG/changelog.gz"
chmod 644 "$ROOT/usr/share/doc/$PKG/changelog.gz"
cat > "$ROOT/usr/share/doc/$PKG/copyright" <<EOF
RBSB-Weather $VERSION
Created By Shane BlackbuRn
Weather data: Open-Meteo.com, licensed CC BY 4.0 (https://open-meteo.com/), and
MET Norway (Norwegian Meteorological Institute), licensed CC BY 4.0 (https://api.met.no/).
Optional providers (used only with your own API key, under each provider's terms):
OpenWeather (https://openweathermap.org/, CC BY-SA 4.0), WeatherAPI.com
(https://www.weatherapi.com/), Visual Crossing (https://www.visualcrossing.com/)
Tomorrow.io (https://www.tomorrow.io/) and Weather Underground / The Weather
Company (https://www.wunderground.com/, PWS contributor API).
Moon textures: see /usr/lib/rbsb-weather/rbsb_weather/assets/moon_textures.json. When built
from NASA's CGI Moon Kit (https://svs.gsfc.nasa.gov/4720) they are public domain
imagery from NASA's Scientific Visualization Studio. Moon positions, phases and
rise/set times are calculated locally (Meeus, Astronomical Algorithms).
Earth maps (assets/earth_day.jpg, assets/earth_night.jpg): Solar System Scope,
https://www.solarsystemscope.com/textures/, licensed CC BY 4.0
(https://creativecommons.org/licenses/by/4.0/), based on NASA imagery.
Live clouds (downloaded at run time, not included in this package): Live Cloud
Maps by Matt Eason, https://github.com/matteason/live-cloud-maps, CC0 1.0.
Contains modified EUMETSAT data.
World wind (Wind tab; downloaded at run time, not included in this package): NOAA
Global Forecast System (GFS), via NOAA NOMADS or the NOAA Open Data Dissemination
copy on AWS; public domain (https://www.ncei.noaa.gov/).
EOF

SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pyqt6
Recommends: fonts-noto-color-emoji, python3-numpy, python3-keyring
Replaces: weatherdesk
Conflicts: weatherdesk
Installed-Size: $SIZE
Maintainer: Shane BlackbuRn <noreply@rbsb-weather.invalid>
Description: Desktop weather app, formerly WeatherDesk (Created By Shane BlackbuRn)
 RBSB-Weather shows current conditions, a 24-hour temperature and rain chart
 and a 7-day forecast for any number of saved locations, with a system-tray
 temperature readout, offline fallback to the last saved forecast, and
 unit choices. Uses the free Open-Meteo and MET Norway services with no
 account or key, and optionally OpenWeather, WeatherAPI.com, Visual Crossing,
 Tomorrow.io or Weather Underground with your own API key (stored in the
 system keyring).
 .
 This package replaces the weatherdesk package. Settings, saved locations and
 API keys are carried over automatically the first time it starts.
EOF

# remove compiled files from older byte-compilation on uninstall
cat > "$ROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
rm -rf /usr/lib/rbsb-weather/rbsb_weather/__pycache__ /usr/lib/rbsb-weather/rbsb_weather/providers/__pycache__
EOF
chmod 755 "$ROOT/DEBIAN/prerm"

find "$ROOT" -type d -exec chmod 755 {} +
DEB="dist/${PKG}_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$DEB" >/dev/null

# --- clean source archive (no caches, logs or build output)
SRC="dist/${PKG}-${VERSION}-source.tar.gz"
tar --exclude=keys.json --exclude="*.key" --exclude=".env*" --exclude="__pycache__" --exclude='*.pyc' --exclude='dist' --exclude='test-results.log' \
    --transform "s,^\.,${PKG}-${VERSION}," -czf "$SRC" \
    ./rbsb_weather ./tests ./tools ./packaging ./build_deb.sh ./run_tests.sh \
    ./README.md ./CHANGELOG.md ./TRANSCRIPT.md ./TEST_REPORT.md

(cd dist && sha256sum "$(basename "$DEB")" "$(basename "$SRC")" > SHA256SUMS)
echo "Built $DEB"
echo "Built $SRC"
cat dist/SHA256SUMS
