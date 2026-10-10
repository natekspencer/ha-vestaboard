"""Vestaboard model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Self

from pyvbml import vbml
from pyvbml.types import IVBML, ComponentStyle

MODEL_FLAGSHIP = "flagship"
MODEL_NOTE = "note"
COLOR_BLACK = "black"
COLOR_WHITE = "white"

BIT_WIDTH = 1 + 6 / 32
BIT_HEIGHT = 2 + 1 / 32
BIT_WIDTH_SPACING = 29 / 64
BIT_HEIGHT_SPACING = 55 / 64

# Without a frame, the margin around the bits matches the spacing between them
FRAMELESS_MARGIN = BIT_WIDTH_SPACING


def frameless_width(columns: int) -> float:
    """Return the physical width of a grid of bits plus margin, in inches."""
    bits = columns * BIT_WIDTH + (columns - 1) * BIT_WIDTH_SPACING
    return bits + 2 * FRAMELESS_MARGIN


def frameless_height(rows: int) -> float:
    """Return the physical height of a grid of bits plus margin, in inches."""
    bits = rows * BIT_HEIGHT + (rows - 1) * BIT_HEIGHT_SPACING
    return bits + 2 * FRAMELESS_MARGIN


@dataclass(frozen=True)
class ColorTheme:
    frame: str
    bit: str
    text: str
    logo: str
    color_map: dict[int, str]


@dataclass(frozen=True)
class ModelSpec:
    rows: int
    columns: int
    width: float
    height: float
    frame_thickness: float
    frame_border: float
    emoji_map: dict[int, str] = field(default_factory=dict)


BLACK_COLOR_MAP: Final[dict[int, str]] = {
    0: "#141414",  # blank
    63: "#DA291C",  # red
    64: "#FA7400",  # orange
    65: "#FCB81B",  # yellow
    66: "#1F9A44",  # green
    67: "#2083D5",  # blue
    68: "#702F8A",  # violet
    69: "#FFFFFF",  # white
    70: "#141414",  # black
    71: "#FFFFFF",  # filled
}
WHITE_COLOR_MAP: Final[dict[int, str]] = BLACK_COLOR_MAP | {
    0: "#FFFFFF",  # blank
    69: "#000000",  # black
    70: "#FFFFFF",  # white
    71: "#000000",  # filled
}

COLOR_SCHEMES: Final[dict[str, ColorTheme]] = {
    COLOR_BLACK: ColorTheme(
        frame="#171818",
        bit="#141414",
        text="#FFFFFF",
        logo="#333333",
        color_map=BLACK_COLOR_MAP,
    ),
    COLOR_WHITE: ColorTheme(
        frame="#F5F5F7",
        bit="#FFFFFF",
        text="#000000",
        logo="#CCCCCC",
        color_map=WHITE_COLOR_MAP,
    ),
}
MODELS: Final[dict[str, ModelSpec]] = {
    MODEL_FLAGSHIP: ModelSpec(
        rows=6,
        columns=22,
        width=41.2,
        height=22,
        frame_thickness=5 / 32,
        frame_border=2 + 21 / 32,
    ),
    MODEL_NOTE: ModelSpec(
        rows=3,
        columns=15,
        width=28.4,
        height=12.2,
        frame_thickness=5 / 32,
        frame_border=2,
        emoji_map={62: "❤️"},
    ),
}
MODEL_BY_SIZE: Final[dict[tuple[int, int], str]] = {
    (spec.rows, spec.columns): model for model, spec in MODELS.items()
}


@dataclass(frozen=True, slots=True)
class VestaboardModel:
    """Encapsulates Vestaboard model specifics, colors, chars, layout, and board styling."""

    color: str
    model: str
    has_frame: bool = True
    """Whether the board is drawn with its frame and logo, or as bits only."""

    def __post_init__(self) -> None:
        """Validate color and model."""
        if self.color not in COLOR_SCHEMES:
            raise ValueError(f"Unknown color: {self.color!r}")
        if self.model not in MODELS:
            raise ValueError(f"Unknown model: {self.model!r}")

    @property
    def name(self) -> str:
        """Return the name."""
        return f"Vestaboard {self.model.capitalize()} {self.color.capitalize()}"

    @property
    def bit_color(self) -> str:
        """Return the bit color."""
        return COLOR_SCHEMES[self.color].bit

    @property
    def frame_color(self) -> str:
        """Return the frame color."""
        return COLOR_SCHEMES[self.color].frame

    @property
    def logo_color(self) -> str:
        """Return the logo color."""
        return COLOR_SCHEMES[self.color].logo

    @property
    def text_color(self) -> str:
        """Return the text color."""
        return COLOR_SCHEMES[self.color].text

    @property
    def color_map(self) -> dict[int, str]:
        """Return the color map."""
        return COLOR_SCHEMES[self.color].color_map

    @property
    def emoji_map(self) -> dict[int, str]:
        """Return the emoji map."""
        return MODELS[self.model].emoji_map

    @property
    def rows(self) -> int:
        """Return the number of rows."""
        return MODELS[self.model].rows

    @property
    def columns(self) -> int:
        """Return the number of columns."""
        return MODELS[self.model].columns

    @property
    def width(self) -> float:
        """Return the physical width of the board, in inches."""
        if not self.has_frame:
            return frameless_width(self.columns)
        return MODELS[self.model].width

    @property
    def height(self) -> float:
        """Return the physical height of the board, in inches."""
        if not self.has_frame:
            return frameless_height(self.rows)
        return MODELS[self.model].height

    @property
    def frame_border(self) -> float:
        """Return the physical frame border, or margin when frameless, in inches."""
        if not self.has_frame:
            return FRAMELESS_MARGIN
        return MODELS[self.model].frame_border

    @property
    def frame_thickness(self) -> float:
        """Return the physical frame thickness, in inches."""
        if not self.has_frame:
            return 0
        return MODELS[self.model].frame_thickness

    @property
    def aspect_ratio(self) -> float:
        """Return the aspect ratio."""
        return self.width / self.height

    def board_at(self, row: int, column: int) -> VestaboardModel:
        """Return the board that a bit belongs to, which is always this board."""
        return self

    @property
    def is_flagship(self) -> bool:
        """Return True if this is a flagship model (6 rows x 22 columns)."""
        return self.model == MODEL_FLAGSHIP

    def color_for_code(self, code: int) -> str | None:
        """Return the hex color for a numeric color code, if defined."""
        return self.color_map.get(code)

    def emoji_for_code(self, code: int) -> str | None:
        """Return the emoji override for a given code, if defined."""
        return self.emoji_map.get(code)

    def tile_size(
        self, target_width: float, target_height: float
    ) -> tuple[float, float]:
        """Calculate the tile size."""
        tile_width = target_width / self.columns
        tile_height = target_height / self.rows
        return tile_width, tile_height

    def tile_aspect_ratio(self, target_width: float, target_height: float) -> float:
        """Calculate the tile aspect ratio."""
        tile_width, tile_height = self.tile_size(target_width, target_height)
        return tile_width / tile_height

    @staticmethod
    def all_models() -> list[str]:
        """Return all known Vestaboard model names."""
        return list(MODELS.keys())

    @staticmethod
    def all_colors() -> list[str]:
        """Return all known Vestaboard color names."""
        return list(COLOR_SCHEMES.keys())

    @classmethod
    def from_color(
        cls, color: str, data: list[list[int]] | None = None, has_frame: bool = True
    ) -> Self:
        """Factory with validation to return Vestaboard model based on color and size."""
        if data is None:
            model = MODEL_FLAGSHIP
        else:
            size = (len(data), max((len(row) for row in data), default=0))
            model = MODEL_BY_SIZE.get(size)

        if model is None or color not in COLOR_SCHEMES:
            raise ValueError(
                f"Unknown Vestaboard model: {model or f'{size[0]}x{size[1]}'} {color!r}"
            )

        return cls(color, model, has_frame)

    def parse_template(
        self, template: str, style: ComponentStyle | None = None
    ) -> list[list[int]]:
        """Parse VBML template using the model's size."""
        return vbml.parse(
            {
                "style": {"height": self.rows, "width": self.columns},
                "components": [{"template": template, "style": style}],
            }
        )

    def parse_vbml(self, data: IVBML) -> list[list[int]]:
        """Parse VBML using the model's size."""
        # Force array size to match this model
        data["style"] = {"height": self.rows, "width": self.columns}
        return vbml.parse(data)


@dataclass(frozen=True, slots=True)
class VestaboardArrayModel:
    """A grid of same-model Vestaboards acting as one larger virtual board.

    Each board keeps its own color, so an array can mix black and white boards.
    """

    model: str
    colors: tuple[tuple[str, ...], ...]
    """The color of each board in the grid, by grid row then grid column."""

    def __post_init__(self) -> None:
        """Validate grid size."""
        if not self.colors or not self.colors[0]:
            raise ValueError("An array needs at least one board")
        if any(len(row) != len(self.colors[0]) for row in self.colors):
            raise ValueError("Every row of an array needs the same number of boards")

    @property
    def board(self) -> VestaboardModel:
        """Return the top left board, which sets the size of every board."""
        return VestaboardModel(self.colors[0][0], self.model)

    @property
    def grid_rows(self) -> int:
        """Return the number of rows of boards."""
        return len(self.colors)

    @property
    def grid_columns(self) -> int:
        """Return the number of columns of boards."""
        return len(self.colors[0])

    @property
    def name(self) -> str:
        """Return the name."""
        return (
            f"Vestaboard {self.model.capitalize()} Array "
            f"({self.grid_rows}x{self.grid_columns})"
        )

    def board_at(self, row: int, column: int) -> VestaboardModel:
        """Return the board that a bit at this array row and column belongs to."""
        board = self.board
        color = self.colors[row // board.rows][column // board.columns]
        return VestaboardModel(color, self.model)

    @property
    def is_flagship(self) -> bool:
        """Return True if the array is made of flagship boards."""
        return self.board.is_flagship

    @property
    def rows(self) -> int:
        """Return the number of rows across the whole array."""
        return self.board.rows * self.grid_rows

    @property
    def columns(self) -> int:
        """Return the number of columns across the whole array."""
        return self.board.columns * self.grid_columns

    @property
    def has_frame(self) -> bool:
        """Return False, as arrays are drawn as bits only, edge to edge."""
        return False

    @property
    def width(self) -> float:
        """Return the physical width of the array's bits plus margin, in inches."""
        return frameless_width(self.columns)

    @property
    def height(self) -> float:
        """Return the physical height of the array's bits plus margin, in inches."""
        return frameless_height(self.rows)

    @property
    def frame_border(self) -> float:
        """Return the margin around the bits, matching the spacing between them."""
        return FRAMELESS_MARGIN

    @property
    def frame_thickness(self) -> float:
        """Return the frame thickness, which is zero as arrays have no frame."""
        return 0

    @property
    def bit_color(self) -> str:
        """Return the bit color."""
        return self.board.bit_color

    @property
    def frame_color(self) -> str:
        """Return the frame color."""
        return self.board.frame_color

    @property
    def logo_color(self) -> str:
        """Return the logo color."""
        return self.board.logo_color

    @property
    def text_color(self) -> str:
        """Return the text color."""
        return self.board.text_color

    @property
    def color_map(self) -> dict[int, str]:
        """Return the color map."""
        return self.board.color_map

    @property
    def emoji_map(self) -> dict[int, str]:
        """Return the emoji map."""
        return self.board.emoji_map

    def emoji_for_code(self, code: int) -> str | None:
        """Return the emoji override for a given code, if defined."""
        return self.board.emoji_for_code(code)

    def parse_template(
        self, template: str, style: ComponentStyle | None = None
    ) -> list[list[int]]:
        """Parse VBML template using the array's size."""
        return vbml.parse(
            {
                "style": {"height": self.rows, "width": self.columns},
                "components": [{"template": template, "style": style}],
            }
        )

    def parse_vbml(self, data: IVBML) -> list[list[int]]:
        """Parse VBML using the array's size."""
        data["style"] = {"height": self.rows, "width": self.columns}
        return vbml.parse(data)

    def split(self, data: list[list[int]]) -> list[list[list[list[int]]]]:
        """Split array-sized data into a grid of board-sized tiles."""
        rows, columns = self.board.rows, self.board.columns
        return [
            [
                [
                    row[grid_column * columns : (grid_column + 1) * columns]
                    for row in data[grid_row * rows : (grid_row + 1) * rows]
                ]
                for grid_column in range(self.grid_columns)
            ]
            for grid_row in range(self.grid_rows)
        ]

    def join(self, tiles: list[list[list[list[int] | None]]]) -> list[list[int]]:
        """Join a grid of board-sized tiles into array-sized data.

        Missing tiles (``None``) are rendered as blank.
        """
        blank = [[0] * self.board.columns for _ in range(self.board.rows)]
        data: list[list[int]] = []
        for tile_row in tiles:
            tile_row = [tile or blank for tile in tile_row]
            for row in range(self.board.rows):
                data.append([code for tile in tile_row for code in tile[row]])
        return data
