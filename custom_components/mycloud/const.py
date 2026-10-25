"""Constants for the My Cloud integration."""

from homeassistant.const import Platform

DOMAIN = "mycloud"

HOST = "Host"
USERNAME = "Username"
PASSWORD = "Password"
VERSION = "Version"

PLATFORMS = (Platform.SENSOR, Platform.BINARY_SENSOR)

DEFAULT_UPDATE_INTERVAL = 600
MIN_UPDATE_INTERVAL = 30
CONFIG_FLOW_TIMEOUT = 15
UPDATE_TIMEOUT = 60
