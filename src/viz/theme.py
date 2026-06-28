"""Plotly theme and class colors."""

CLASS_ORDER = [
    "Residencial",
    "Comercial",
    "Industrial",
    "Rural",
    "Poder público",
    "Iluminação pública",
    "Serviço público",
    "Consumo próprio",
    "Rural Aquicultor",
    "Outras",
]

CLASS_COLORS = {
    "Residencial": "#2E86AB",
    "Comercial": "#F18F01",
    "Industrial": "#5B8E7D",
    "Rural": "#8E6C8A",
    "Poder público": "#C73E1D",
    "Iluminação pública": "#F4D35E",
    "Serviço público": "#33658A",
    "Consumo próprio": "#6A4C93",
    "Rural Aquicultor": "#7CB518",
    "Outras": "#8D99AE",
}

FALLBACK_COLOR = "#7A7A7A"
PLOTLY_TEMPLATE = "plotly_white"


def color_map(classes: list[str]) -> dict[str, str]:
    return {value: CLASS_COLORS.get(value, FALLBACK_COLOR) for value in classes}


def apply_default_layout(fig):
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        legend_title_text="Classe",
        margin=dict(l=20, r=20, t=60, b=40),
        hovermode="x unified",
    )
    return fig
