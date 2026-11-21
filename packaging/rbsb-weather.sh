#!/bin/sh
# RBSB-Weather launcher. Created By Shane BlackbuRn
PYTHONPATH=/usr/lib/rbsb-weather
export PYTHONPATH
exec /usr/bin/python3 -m rbsb_weather "$@"
