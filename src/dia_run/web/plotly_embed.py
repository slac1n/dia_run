from typing import Any

from markupsafe import Markup
from plotly.graph_objects import Figure
from plotly.io import to_html

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.30.0.min.js"
DEFAULT_PLOTLY_CONFIG = {
    "displayModeBar": False,
    "displaylogo": False,
    "responsive": True,
}


def render_plotly_figure(*, figure: Figure, config: dict[str, Any] | None = None) -> Markup:
    html = to_html(
        figure,
        include_plotlyjs=False,
        full_html=False,
        config=config or DEFAULT_PLOTLY_CONFIG,
    )
    return Markup(html)
