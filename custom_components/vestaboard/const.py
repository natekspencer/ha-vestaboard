"""Constants for the Vestaboard integration."""

from typing import Final

DOMAIN: Final = "vestaboard"

# justify (horizontal) and align (vertical) values
ALIGN_BOTTOM: Final = "bottom"
ALIGN_CENTER: Final = "center"
ALIGN_JUSTIFIED: Final = "justified"
ALIGN_LEFT: Final = "left"
ALIGN_RIGHT: Final = "right"
ALIGN_TOP: Final = "top"
ALIGN_HORIZONTAL: Final = [ALIGN_LEFT, ALIGN_RIGHT, ALIGN_CENTER, ALIGN_JUSTIFIED]
ALIGN_VERTICAL: Final = [ALIGN_TOP, ALIGN_BOTTOM, ALIGN_CENTER, ALIGN_JUSTIFIED]

CONF_ALIGN: Final = "align"
CONF_DURATION: Final = "duration"
CONF_ENABLEMENT_TOKEN: Final = "enablement_token"
CONF_JUSTIFY: Final = "justify"
CONF_MESSAGE: Final = "message"
CONF_MODEL: Final = "model"
CONF_QUIET_END: Final = "quiet_end"
CONF_QUIET_START: Final = "quiet_start"
CONF_VBML: Final = "vbml"

DATA_HASS_CONFIG: Final = "hass_config"

COLOR_BLACK: Final = "black"
COLOR_WHITE: Final = "white"

SERVICE_MESSAGE: Final = "message"
VBML_URL: Final = "https://vbml.vestaboard.com/compose"
