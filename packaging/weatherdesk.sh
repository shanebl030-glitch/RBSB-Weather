#!/bin/sh
# WeatherDesk launcher. Created By Shane BlackbuRn
PYTHONPATH=/usr/lib/weatherdesk
export PYTHONPATH
exec /usr/bin/python3 -m weatherdesk "$@"
