"""Helpers for the Vestaboard integration."""

from __future__ import annotations

import base64
import io
import logging
from typing import TYPE_CHECKING, Any, cast

from PIL import Image, ImageDraw, ImageOps
from pyvbml.character_codes import COLOR_CODES, CharacterCode

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import DEFAULT_PORT, VestaboardLocalClient
from .const import (
    COLOR_BLACK,
    CONF_ENABLEMENT_TOKEN,
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_ARRAY,
    ENTRY_TYPE_DEVICE,
)
from .fontloader import get_font_bytes, load_emoji_font, load_font
from .vestaboard_model import (
    BIT_HEIGHT,
    BIT_HEIGHT_SPACING,
    BIT_WIDTH,
    BIT_WIDTH_SPACING,
    VestaboardArrayModel,
    VestaboardModel,
)

if TYPE_CHECKING:
    from .coordinator import VestaboardArrayCoordinator, VestaboardCoordinator

_LOGGER = logging.getLogger(__name__)

PRINTABLE = (
    " ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890!@#$() - +&=;: '\"%,.  /? °🟥🟧🟨🟩🟦🟪⬜⬛■"
)


def get_entry_type(entry: ConfigEntry) -> str:
    """Return the config entry type: a physical device, a virtual board or an array."""
    return entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_DEVICE)


def is_array_entry(entry: ConfigEntry) -> bool:
    """Return True if the config entry is a Vestaboard array."""
    return get_entry_type(entry) == ENTRY_TYPE_ARRAY


async def create_client(
    hass: HomeAssistant, data: dict[str, Any]
) -> VestaboardLocalClient:
    """Create a Vestaboard local client."""
    api_key = data.get("api_key")
    url = f"http://{data['host']}:{DEFAULT_PORT}"
    session = async_get_clientsession(hass)
    client = VestaboardLocalClient(base_url=url, session=session)
    if data.get(CONF_ENABLEMENT_TOKEN):
        await client.enable(api_key)
    elif api_key:
        client.api_key = api_key
    return client


def draw_emoji(emoji: str, size: tuple[int, int]) -> Image.Image:
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
    model: VestaboardModel | VestaboardArrayModel | None = None,
) -> bytes:
    """Create a png of the message on a Vestaboard.

    Pass an array model to render a whole array as one frameless board.
    """
    return _to_png(render_board(data, color, height, draw_bit, model))


def create_framed_array_png(
    tiles: list[list[list[list[int]]]],
    colors: tuple[tuple[str, ...], ...],
    height: int = 1080,
    draw_bit: bool = True,
) -> bytes:
    """Create a png of the message on a grid of separately framed Vestaboards."""
    grid_rows = len(tiles)
    tile_height = height // grid_rows
    images = [
        [
            render_board(tile, color, tile_height, draw_bit)
            for tile, color in zip(tile_row, color_row)
        ]
        for tile_row, color_row in zip(tiles, colors)
    ]
    tile_width = images[0][0].width
    gap = max(1, tile_height // 100)

    img = Image.new(
        "RGBA",
        (
            tile_width * len(images[0]) + gap * (len(images[0]) - 1),
            tile_height * grid_rows + gap * (grid_rows - 1),
        ),
    )
    for grid_row, tile_row in enumerate(images):
        for grid_column, tile_img in enumerate(tile_row):
            img.paste(
                tile_img,
                (grid_column * (tile_width + gap), grid_row * (tile_height + gap)),
            )
    return _to_png(img)


def _to_png(img: Image.Image) -> bytes:
    """Encode an image as png."""
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def render_board(
    data: list[list[int]],
    color: str = COLOR_BLACK,
    height: int = 1080,
    draw_bit: bool = True,
    model: VestaboardModel | VestaboardArrayModel | None = None,
) -> Image.Image:
    """Render the message on a Vestaboard as an image."""
    if model is None:
        model = VestaboardModel.from_color(color, data)

    #  Physical scale
    px_per_in = height / model.height
    width = int(model.width * px_per_in)

    img = Image.new("RGB", (width, height), color=model.frame_color)
    draw = ImageDraw.Draw(img)

    # Convert physical dimensions to pixels

    # Board background
    outer_border = model.frame_thickness * px_per_in
    if outer_border:
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

    if isinstance(model, VestaboardArrayModel):
        _fill_array_backgrounds(
            draw,
            model,
            (width, height),
            (start_x, start_y),
            (bit_w, bit_h),
            (gap_x, gap_y),
        )

    # Draw bits
    for row, characters in enumerate(data):
        ypos = start_y + row * (bit_h + gap_y)
        for col, code in enumerate(characters):
            xpos = start_x + col * (bit_w + gap_x)
            board = model.board_at(row, col)

            if draw_bit:
                draw.rectangle(
                    [(xpos, ypos), (xpos + bit_w, ypos + bit_h)],
                    fill=board.bit_color,
                )

            if code in board.emoji_map:
                emoji = board.emoji_for_code(code)
                emoji_img = draw_emoji(emoji, (int(bit_w), int(bit_h)))
                vertical_padding = (font_height - glyph_height) / 2
                img.paste(
                    emoji_img,
                    (int(xpos), int(ypos + vertical_padding + top)),
                    emoji_img,
                )

            elif code in COLOR_CODES:
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
                    fill=board.color_map[code],
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
                    fill=board.frame_color,
                )

            else:
                char = symbol(code)
                draw.text(
                    (xpos + bit_w / 2, ypos + bit_h / 2),
                    char,
                    fill=board.text_color,
                    font=font,
                    anchor="mm",
                )

    if model.has_frame:
        _draw_logo(draw, model, start_y, bit_h, gap_y, inner_border, width)

    return img


def _fill_array_backgrounds(
    draw: ImageDraw.ImageDraw,
    model: VestaboardArrayModel,
    size: tuple[int, int],
    start: tuple[float, float],
    bit: tuple[float, float],
    gap: tuple[float, float],
) -> None:
    """Fill the area behind each board of an array with that board's color.

    Each board's area runs to the midpoint of the gap between it and its
    neighbors, and to the image edge on the outside of the array.
    """
    width, height = size
    start_x, start_y = start
    gap_x, gap_y = gap
    pitch_x, pitch_y = bit[0] + gap_x, bit[1] + gap_y
    board_rows, board_columns = model.board.rows, model.board.columns
    for grid_row in range(model.grid_rows):
        top = start_y + grid_row * board_rows * pitch_y - gap_y / 2
        bottom = top + board_rows * pitch_y
        for grid_column in range(model.grid_columns):
            left = start_x + grid_column * board_columns * pitch_x - gap_x / 2
            right = left + board_columns * pitch_x
            board = model.board_at(grid_row * board_rows, grid_column * board_columns)
            draw.rectangle(
                [
                    (0 if grid_column == 0 else left, 0 if grid_row == 0 else top),
                    (
                        width if grid_column == model.grid_columns - 1 else right,
                        height if grid_row == model.grid_rows - 1 else bottom,
                    ),
                ],
                fill=board.frame_color,
            )


def _draw_logo(
    draw: ImageDraw.ImageDraw,
    model: VestaboardModel,
    start_y: float,
    bit_h: float,
    gap_y: float,
    inner_border: float,
    width: int,
) -> None:
    """Draw the logo centered in the frame below the bits."""
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


def create_svg(data: list[list[int]], color: str = COLOR_BLACK) -> str:
    """Create an svg for the message from the Vestaboard.

    This currently only works for the original Vestaboard Flagship model (6 x 22).
    """
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
        f".{CharacterCode(k).name.lower()} {{ fill: {v}; }}"
        for k, v in model.color_map.items()
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
            if code in COLOR_CODES:
                svg += f'<rect class="char {CharacterCode(code).name.lower()}" x="{xpos}" y="{ypos}"/>'
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
) -> VestaboardCoordinator | VestaboardArrayCoordinator:
    """Get the Vestaboard (or Vestaboard array) coordinator for this device ID."""
    device_registry = dr.async_get(hass)

    if (device_entry := device_registry.async_get(device_id)) is None:
        raise ValueError(f"Unknown Vestaboard device ID: {device_id}")

    for entry_id in device_entry.config_entries:
        if (
            entry := hass.config_entries.async_get_entry(entry_id)
        ) and entry.domain == DOMAIN:
            return entry.runtime_data

    raise ValueError(f"No coordinator for device ID: {device_id}")
