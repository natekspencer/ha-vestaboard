"""Fontloader."""

from __future__ import annotations

from importlib import resources
import io
from typing import Final

from PIL import ImageFont

FONT_NAME: Final = "Vestaboard.otf"
FONT_EMOJI: Final = "VestaEmojis.ttf"
FONT_EMOJI_SIZE: Final = 128

_font_cache: dict[str, bytes] = {}


def _load_font_bytes(name: str = FONT_NAME) -> bytes:
    """Load the raw font bytes from the font file."""
    if name not in _font_cache:
        _font_bytes = resources.read_binary(__package__, name)
        _font_cache[name] = _font_bytes
    return _font_cache[name]


def get_font_buffer(name: str = FONT_NAME) -> io.BytesIO:
    """Return the font as a BytesIO stream."""
    return io.BytesIO(_load_font_bytes(name))


def get_font_bytes(name: str = FONT_NAME) -> bytes:
    """Return raw font bytes."""
    return _load_font_bytes(name)


def load_font(size: float | None) -> ImageFont:
    """Load a font."""
    try:
        return ImageFont.truetype(get_font_buffer(), size=size)
    except OSError:
        return ImageFont.load_default(size)


def load_emoji_font() -> ImageFont:
    """Load an emoji font."""
    try:
        return ImageFont.truetype(get_font_buffer(FONT_EMOJI), size=FONT_EMOJI_SIZE)
    except OSError:
        return ImageFont.load_default()
