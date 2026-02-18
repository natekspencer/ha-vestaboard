"""Helpers for the Vestaboard integration."""

from __future__ import annotations

import base64
import io
import logging
from typing import TYPE_CHECKING, Any, cast

import httpx
from PIL import Image, ImageDraw, ImageOps
from vesta import Color, LocalClient, encode_text

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.util.ssl import get_default_context

from .const import (
    ALIGN_CENTER,
    ALIGN_JUSTIFIED,
    COLOR_BLACK,
    CONF_ALIGN,
    CONF_ENABLEMENT_TOKEN,
    CONF_JUSTIFY,
    DOMAIN,
)
from .fontloader import get_font_bytes, load_emoji_font, load_font
from .vestaboard_model import (
    BIT_HEIGHT,
    BIT_HEIGHT_SPACING,
    BIT_WIDTH,
    BIT_WIDTH_SPACING,
    VestaboardModel,
)

if TYPE_CHECKING:
    from .coordinator import VestaboardCoordinator

_LOGGER = logging.getLogger(__name__)

PRINTABLE = (
    " ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890!@#$() - +&=;: '\"%,.  /? °🟥🟧🟨🟩🟦🟪⬜⬛■"
)
EMOJI_MAP = {
    "🟥": "{63}",
    "🟧": "{64}",
    "🟨": "{65}",
    "🟩": "{66}",
    "🟦": "{67}",
    "🟪": "{68}",
    "⬜": "{69}",
    "⬛": "{70}",
    "■": "{71}",
    "❤️": "{62}",
}


def construct_message(message: str, **kwargs: Any) -> list[list[int]]:
    """Construct a message."""
    message = "".join(EMOJI_MAP.get(char, char) for char in message)
    align = kwargs.get(CONF_JUSTIFY, ALIGN_CENTER)
    if align in (ALIGN_JUSTIFIED):
        align = ALIGN_CENTER
    valign = kwargs.get(CONF_ALIGN, ALIGN_CENTER)
    if valign in (ALIGN_CENTER, ALIGN_JUSTIFIED):
        valign = "middle"
    return encode_text(message, align=align, valign=valign)


def create_client(data: dict[str, Any]) -> LocalClient:
    """Create a Vestaboard local client."""
    url = f"http://{data['host']}:7000"
    key = data["api_key"]
    http_client = httpx.Client(verify=get_default_context())
    if data.get(CONF_ENABLEMENT_TOKEN):
        client = LocalClient(base_url=url, http_client=http_client)
        client.enable(key)
        return client
    return LocalClient(local_api_key=key, base_url=url, http_client=http_client)


def draw_emoji(emoji: str, size: tuple[int, int] | list[int]) -> Image.Image:
    """Draw a scaled emoji image at the requested size.

    :param size: The requested size in pixels, as a tuple or array:
        (width, height).
    :returns: An :py:class:`~PIL.Image.Image` object.
    """
    # draw the emoji
    width, height = 76, 90
    emoji_font = load_emoji_font()
    img = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(img)
    draw.text((0, -44), emoji, font=emoji_font, embedded_color=True)

    # create the flap line
    mask = img.getchannel("A")
    draw = ImageDraw.Draw(mask)
    hinge_y = int(height * 0.45)
    draw.line([(0, hinge_y), (width, hinge_y)], fill=0, width=int(height * 0.035))
    img.putalpha(mask)

    # size appropriately and return
    return ImageOps.contain(img, size, Image.LANCZOS)


def create_png(
    data: list[list[int]],
    color: str = COLOR_BLACK,
    height: int = 1080,
    draw_bit: bool = True,
) -> bytes:
    model = VestaboardModel.from_color(color, data)

    #  Physical scale
    px_per_in = height / model.height
    width = int(model.width * px_per_in)

    img = Image.new("RGB", (width, height), color=model.frame_color)
    draw = ImageDraw.Draw(img)

    # Convert physical dimensions to pixels

    # Board background
    outer_border = model.frame_thickness * px_per_in
    draw.rectangle(
        [(0, 0), (width, height)],
        outline=model.bit_color,
        width=int(outer_border),
    )

    inner_border = model.frame_border * px_per_in

    bit_w = BIT_WIDTH * px_per_in
    bit_h = BIT_HEIGHT * px_per_in

    gap_x = BIT_WIDTH_SPACING * px_per_in
    gap_y = BIT_HEIGHT_SPACING * px_per_in

    # Starting position of first bit
    start_x = outer_border + inner_border
    start_y = outer_border + inner_border

    # Font
    font = load_font(int(bit_h * 0.8))

    # Calculate height of squares based on the letter O
    ascent, descent = font.getmetrics()
    font_height = ascent + descent
    text_bbox = draw.textbbox((0, 0), "O", font=font)
    _, top, _, bottom = text_bbox
    glyph_height = bottom - top

    # Draw bits
    for row, characters in enumerate(data):
        ypos = start_y + row * (bit_h + gap_y)
        for col, code in enumerate(characters):
            xpos = start_x + col * (bit_w + gap_x)

            if draw_bit:
                draw.rectangle(
                    [(xpos, ypos), (xpos + bit_w, ypos + bit_h)],
                    fill=model.bit_color,
                )

            if code in model.emoji_map:
                emoji = model.emoji_for_code(code)
                emoji_img = draw_emoji(emoji, (int(bit_w), int(bit_h)))
                vertical_padding = (font_height - glyph_height) / 2
                img.paste(
                    emoji_img,
                    (int(xpos), int(ypos + vertical_padding + top)),
                    emoji_img,
                )

            elif code in (c.value for c in Color):
                vertical_padding = (font_height - glyph_height) / 2
                bit_pad = bit_w * 0.02
                draw.rectangle(
                    [
                        (xpos + bit_pad, ypos + vertical_padding + top),
                        (
                            xpos + bit_w - bit_pad,
                            ypos + vertical_padding + top + glyph_height,
                        ),
                    ],
                    fill=model.color_map[code],
                )

                flap_top = ypos + bit_h * 0.1
                flap_bottom = ypos + bit_h * 0.78
                flap_h = flap_bottom - flap_top
                stripe_h = bit_h * 0.02
                stripe_center = flap_top + flap_h / 2
                draw.rectangle(
                    [
                        (xpos, stripe_center - stripe_h / 2),
                        (xpos + bit_w, stripe_center + stripe_h / 2),
                    ],
                    fill=model.frame_color,
                )

            else:
                emoji = symbol(code)
                draw.text(
                    (xpos + bit_w / 2, ypos + bit_h / 2),
                    emoji,
                    fill=model.text_color,
                    font=font,
                    anchor="mm",
                )

    # logo placement
    logo_text = "VESTABOARD"
    logo_font = load_font(int(bit_h * 0.3))

    text_bbox = draw.textbbox((0, 0), logo_text, font=logo_font)
    text_height = text_bbox[3] - text_bbox[1]

    bottom_inner_top = start_y + model.rows * (bit_h + gap_y)
    bottom_inner_height = inner_border

    # vertical center of inner border
    inner_center_y = bottom_inner_top + bottom_inner_height / 2

    # adjust y to place visual center of text at inner_center_y
    logo_y = inner_center_y - text_height

    draw.text(
        (width / 2, logo_y),
        logo_text,
        fill=model.logo_color,
        anchor="md",
        font=logo_font,
    )

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def create_svg(data: list[list[int]], color: str = COLOR_BLACK) -> str:
    """Create an svg for the message from the Vestaboard."""
    model = VestaboardModel.from_color(color, data)

    encoded_font = base64.b64encode(get_font_bytes()).decode("ascii")
    font_face = f"""@font-face {{
        font-family: "Vestaboard";
        src: url("data:font/otf;base64,{encoded_font}") format("opentype");
      }}"""

    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 1.77" version="1.1">'
    svg += f"<style> {font_face} </style>"
    svg += '<style> svg { font-family: "Vestaboard", "Regular", sans-serif; text-anchor: middle; }'
    svg += f".board {{ fill: {model.frame_color}; stroke: {model.bit_color}; stroke-width: 0.02; }}"
    svg += f".char {{ font-size: 0.14px; width: 0.09px; height: 0.11px; }} text.char {{ fill: {model.text_color}; transform: translateY(0.105px); }}"
    svg += " ".join(
        f".{Color(k).name.lower()} {{ fill: {v}; }}" for k, v in model.color_map.items()
    )
    svg += f".logo {{ font-size: 0.10px; fill: {model.bit_color}; }} </style>"
    svg += '<rect class="board" x="0.01" y="0.01" width="3.98" height="1.75" />'
    start = 0.2
    row_multiplier = 0.24
    column_multiplier = 0.166
    for row, characters in enumerate(data):
        for column, code in enumerate(characters):
            xpos = round(start + column * column_multiplier, 3)
            ypos = round(start + row * row_multiplier, 3)
            if code in (c.value for c in Color):
                svg += f'<rect class="char {Color(code).name.lower()}" x="{xpos}" y="{ypos}"/>'
            else:
                svg += f'<text class="char" x="{xpos + 0.045}" y="{ypos}">{symbol(code).replace("&", "&amp;")}</text>'
    svg += '<text class="logo" x="50%" y="1.68">VESTABOARD</text></svg>'
    return svg


def decode(data: list[int] | list[list[int]]) -> None:
    """Prints a console-formatted representation of encoded character data.

    ``data`` may be a single list or a two-dimensional array of character codes.
    """
    rows = cast(list[list[int]], data if data and isinstance(data[0], list) else [data])
    return "\n".join((f"{''.join(map(symbol, row))}" for row in rows))


def symbol(code: int) -> str:
    """Convert a character code to symbol."""
    return PRINTABLE[code] if 0 <= code < len(PRINTABLE) else " "


@callback
def async_get_coordinator_by_device_id(
    hass: HomeAssistant, device_id: str
) -> VestaboardCoordinator:
    """Get the Vestaboard coordinator for this device ID."""
    device_registry = dr.async_get(hass)

    if (device_entry := device_registry.async_get(device_id)) is None:
        raise ValueError(f"Unknown Vestaboard device ID: {device_id}")

    for entry_id in device_entry.config_entries:
        if (
            entry := hass.config_entries.async_get_entry(entry_id)
        ) and entry.domain == DOMAIN:
            return entry.runtime_data

    raise ValueError(f"No coordinator for device ID: {device_id}")
