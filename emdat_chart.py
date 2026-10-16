"""EM-DAT flood history from three exports: world (2000-2026), India only, world 2015-2026."""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import config

BLUE, GRAY, INK, GRID = "#2a78d6", "#a8a7a2", "#6b6a66", "#c9c8c3"
MUMBAI_WORDS = "Mumbai|Bombay|Thane|Raigad|Palghar"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def load_emdat():
    """Return {name: DataFrame} for each configured file that exists (empty dict if none)."""
    out = {}
    for name, path in config.EMDAT_FILES.items():
        if os.path.exists(path):
            out[name] = pd.read_excel(path, sheet_name="EM-DAT Data")
    return out


ALL_NATURAL, ALL = "All natural disasters", "All disasters"


def kinds_available(df):
    """Options for the disaster-type selector: the two 'all' choices, then each EM-DAT Disaster Type by frequency."""
    return [ALL_NATURAL, ALL] + list(df["Disaster Type"].value_counts().index)


def disasters(df, kind=ALL_NATURAL, country=None):
    """Filter an EM-DAT frame to one disaster type (or all natural / all) and optionally one country."""
    d = df
    if kind == ALL_NATURAL:
        d = d[d["Disaster Group"].eq("Natural")]
    elif kind != ALL:
        d = d[d["Disaster Type"].eq(kind)]
    if country:
        d = d[d["Country"].eq(country)]
    d = d.copy()
    for col in ("Total Affected", "Total Deaths"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    return d


def mumbai_events(d):
    return d[d["Location"].str.contains(MUMBAI_WORDS, na=False, case=False)]


def top_countries(df, kind=ALL_NATURAL, n=8):
    """People affected per country (events with a reported figure only)."""
    return disasters(df, kind).groupby("Country")["Total Affected"].sum().sort_values(ascending=False).head(n)


def _style(ax, title, ylabel=None, xlabel=None):
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold")
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK, length=0, labelsize=9)
    ax.grid(axis="y", color=GRID, alpha=0.5, lw=0.8)
    ax.set_axisbelow(True)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK, fontsize=9)
    if xlabel:
        ax.set_xlabel(xlabel, color=INK, fontsize=9)


def _fig(w=6.2, h=3.4):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_alpha(0)
    ax.patch.set_alpha(0)
    return fig, ax


def _bars(series, title, ylabel, label_fmt=None):
    fig, ax = _fig()
    ax.bar(series.index.astype(str), series.values, color=BLUE, width=0.62)
    _style(ax, title, ylabel)
    ax.tick_params(axis="x", labelrotation=90 if len(series) > 14 else 0)
    if label_fmt:
        for x, v in zip(range(len(series)), series.values):
            if v == series.max():
                ax.annotate(label_fmt(v), (x, v), ha="center", va="bottom", fontsize=8, color=INK)
    fig.tight_layout()
    return fig


def india_events_per_year(india, kind=ALL_NATURAL):
    s = disasters(india, kind, "India").groupby("Start Year").size()
    return _bars(s.reindex(range(2000, 2027), fill_value=0), "Events recorded per year", "events", lambda v: f"{int(v)}")


def india_affected_per_year(india, kind=ALL_NATURAL):
    s = disasters(india, kind, "India").groupby("Start Year")["Total Affected"].sum().reindex(range(2000, 2027), fill_value=0) / 1e6
    return _bars(s, "People affected per year (millions)", "millions", lambda v: f"{v:.0f} M")


def india_by_month(india, kind=ALL_NATURAL):
    s = disasters(india, kind, "India").groupby("Start Month").size().reindex(range(1, 13), fill_value=0)
    s.index = MONTHS
    return _bars(s, "Events by start month", "events", lambda v: f"{int(v)}")


def country_ranking(df, title, kind=ALL_NATURAL, n=8):
    """Horizontal bars, India highlighted, one hue plus neutral gray."""
    s = top_countries(df, kind, n)[::-1] / 1e6
    fig, ax = _fig(6.2, 3.6)
    ax.barh(s.index, s.values, color=[BLUE if c == "India" else GRAY for c in s.index], height=0.62)
    _style(ax, title)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, alpha=0.5, lw=0.8)
    for y, v in enumerate(s.values):
        ax.text(v, y, f" {v:,.0f} M", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, max(s.max() * 1.18, 1e-9))
    fig.tight_layout()
    return fig


def summary(world, india, recent, kind=ALL_NATURAL):
    """Headline numbers for the dashboard."""
    di = disasters(india, kind, "India")
    ranking = top_countries(world, kind, n=500)
    rank = list(ranking.index).index("India") + 1 if "India" in ranking.index else None
    return dict(
        events=len(di), affected=di["Total Affected"].sum(), deaths=di["Total Deaths"].sum(),
        reported=int(di["Total Affected"].notna().sum()), rank=rank,
        share=(ranking["India"] / ranking.sum()) if rank else 0.0,
        recent_events=len(disasters(recent, kind, "India")), mumbai=len(mumbai_events(di)),
    )


def make_emdat_charts(outdir="outputs", kind=ALL_NATURAL):
    data = load_emdat()
    if not {"world", "india", "recent"} <= data.keys():
        print("  (EM-DAT files missing from data/; skipping EM-DAT charts)")
        return
    figs = {
        "emdat_india_events": india_events_per_year(data["india"], kind),
        "emdat_india_affected": india_affected_per_year(data["india"], kind),
        "emdat_india_months": india_by_month(data["india"], kind),
        "emdat_world_2000_2026": country_ranking(data["world"], "People affected by country, 2000-2026", kind),
        "emdat_world_2015_2026": country_ranking(data["recent"], "People affected by country, 2015-2026", kind),
    }
    for name, fig in figs.items():
        fig.savefig(f"{outdir}/{name}.png", dpi=150, transparent=True)
        plt.close(fig)
