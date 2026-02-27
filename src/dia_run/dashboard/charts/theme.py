"""Plotly chart theme configuration using the Dia-Run color palette."""

from typing import Any

# Palette colors
ASH_GREY = "#cad2c5"
MUTED_TEAL = "#84a98c"
DEEP_TEAL = "#52796f"
DARK_SLATE_GREY = "#354f52"
CHARCOAL_BLUE = "#2f3e46"

# Legacy aliases kept for compatibility across chart modules
NAVY = CHARCOAL_BLUE
CHIFFON = ASH_GREY
GOLD = MUTED_TEAL
SANDY = DEEP_TEAL
TOMATO = DARK_SLATE_GREY

# Primary chart color shades
MAIN_COLOR = NAVY
MAIN_COLOR_SHADE_500 = DEEP_TEAL
MAIN_COLOR_SHADE_300 = MUTED_TEAL
NO_ACTIVITY_COLOR = "#e5e7eb"

# Extended palette for charts
CHART_COLORS = [
    NAVY,
    GOLD,
    SANDY,
    TOMATO,
    ASH_GREY,
    CHARCOAL_BLUE,
    DEEP_TEAL,
    MUTED_TEAL,
]

# Semantic colors
COLOR_SUCCESS = MUTED_TEAL
COLOR_WARNING = SANDY
COLOR_ERROR = TOMATO
COLOR_MUTED = DEEP_TEAL

# Chart element colors
CHART_BG = "#ffffff"
CHART_GRID = "rgba(47, 62, 70, 0.12)"
CHART_PAPER_BG = "#ffffff"
TARGET_RANGE_FILL = "rgba(47, 62, 70, 0.1)"


def get_default_layout(
    *,
    title: str,
    xaxis_title: str = "",
    yaxis_title: str = "",
    height: int | None = None,
    showlegend: bool = False,
) -> dict[str, Any]:
    """Get a default Plotly layout dict with Dia-Run theming.

    Args:
        title: Chart title
        xaxis_title: X-axis label
        yaxis_title: Y-axis label
        height: Optional chart height in pixels
        showlegend: Whether to show the legend

    Returns:
        Plotly layout dictionary with theme applied

    """
    layout: dict[str, Any] = {
        "meta": {"card_title": title},
        "paper_bgcolor": CHART_PAPER_BG,
        "plot_bgcolor": CHART_BG,
        "font": {"color": NAVY, "family": "Work Sans, sans-serif"},
        "xaxis": {
            "title": {"text": xaxis_title, "font": {"color": NAVY}},
            "gridcolor": CHART_GRID,
            "linecolor": CHART_GRID,
            "tickfont": {"color": COLOR_MUTED},
        },
        "yaxis": {
            "title": {"text": yaxis_title, "font": {"color": NAVY}},
            "gridcolor": CHART_GRID,
            "linecolor": CHART_GRID,
            "tickfont": {"color": COLOR_MUTED},
        },
        "showlegend": showlegend,
        "margin": {"l": 60, "r": 30, "t": 30, "b": 60},
    }

    if height is not None:
        layout["height"] = height

    return layout


def get_empty_chart_layout(*, title: str, message: str = "No data available") -> dict[str, Any]:
    """Get layout for empty/placeholder charts.

    Args:
        title: Chart title
        message: Message to display in the center

    Returns:
        Plotly layout dictionary with empty state

    """
    return {
        "meta": {"card_title": title},
        "paper_bgcolor": CHART_PAPER_BG,
        "plot_bgcolor": CHART_BG,
        "annotations": [
            {
                "text": message,
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "font": {"color": COLOR_MUTED, "size": 14},
            }
        ],
        "xaxis": {"visible": False},
        "yaxis": {"visible": False},
    }


def get_color_for_index(index: int) -> str:
    """Get a chart color by index, cycling through the palette.

    Args:
        index: Index into the color palette

    Returns:
        Hex color string

    """
    return CHART_COLORS[index % len(CHART_COLORS)]
