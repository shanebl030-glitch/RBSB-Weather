#!/usr/bin/env bash
# WeatherDesk baseline test suite - run after every change.
# Fully offline: uses a local fake Open-Meteo server. Created By Shane BlackbuRn
set -euo pipefail
cd "$(dirname "$0")/tests"
PY="${PYTHON:-python3}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
"$PY" -m unittest -v test_core test_net test_tls test_metno test_providers test_scene test_moon test_earth test_globe test_clouds test_sky test_refresh test_timefmt test_arc test_forecast_strip test_instance test_gui test_stress test_robustness test_audit test_packaging test_soak 2>&1 | tee ../test-results.log | grep -E "^(Ran|OK|FAILED)|stress results|scene results|moon results|earth results|globe results|clouds results|sky results|refresh results|arc results|forecast strip results|providers results|robustness results|soak results|^  (refresh|render|stalled|close|window|animation|desktop|all |paint|rise/set|illumination|new/quarter|7-day|render 300|save 2048|subsolar|sun elevation|day/night|projection|numpy|pure-Python|200 px|cloud map|stalled cloud|city-light|day\/night + clouds|globe paint|zoom glide|widget line|Moon arc|moon_pass|resize sweep|days shown|fixed forecast|icon pixels|scene frame with|desktop widget days|top card days|close while|emit flood|Moon lit|soak |idle CPU|[^:]+: [0-9]+ damaged responses)"
exit "${PIPESTATUS[0]}"
