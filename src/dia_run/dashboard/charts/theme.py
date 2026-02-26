"""Plotly chart theme configuration using the Dia-Run color palette."""

from typing import Any

# Palette colors
NAVY = "#0d3b66"
CHIFFON = "#faf0ca"
GOLD = "#f4d35e"
SANDY = "#ee964b"
TOMATO = "#f95738"

# Primary chart color shades
MAIN_COLOR = NAVY
MAIN_COLOR_SHADE_500 = "#4b79a7"
MAIN_COLOR_SHADE_300 = "#c6d8ea"
NO_ACTIVITY_COLOR = "#e5e7eb"

# Extended palette for charts
CHART_COLORS = [
    NAVY,
    GOLD,
    SANDY,
    TOMATO,
    "#5a8a9a",  # Muted teal for variety
    "#8a6a5a",  # Muted brown
    "#4a7a6a",  # Muted green
    "#7a5a8a",  # Muted purple
]

# Semantic colors
COLOR_SUCCESS = "#2d8a5e"
COLOR_WARNING = SANDY
COLOR_ERROR = TOMATO
COLOR_MUTED = "#6a7a8a"

# Chart element colors
CHART_BG = "#ffffff"
CHART_GRID = "rgba(13, 59, 102, 0.1)"
CHART_PAPER_BG = "#ffffff"
TARGET_RANGE_FILL = "rgba(13, 59, 102, 0.1)"


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
