"""Constants for the independent Rostov Vodokanal integration."""

DOMAIN = "rostov_vodokanal"
BASE_URL = "https://lkfl.vodokanalrnd.ru"
CONF_ACCOUNT = "account"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 360  # Minutes; actions always fetch fresh data first.
TIMEZONE = "Europe/Moscow"
