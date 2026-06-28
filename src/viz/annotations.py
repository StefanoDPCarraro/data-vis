"""Historical annotations for Plotly figures."""

from __future__ import annotations


def add_historical_markers(fig):
    markers = [
        ("2020-03-01", "2020 — pandemia de COVID-19"),
        ("2021-07-01", "2021 — crise hídrica"),
    ]
    for date_value, label in markers:
        fig.add_vline(x=date_value, line_width=1, line_dash="dash", line_color="#555")
        fig.add_annotation(x=date_value, y=1, yref="paper", text=label, showarrow=False, yanchor="bottom")
    return fig
