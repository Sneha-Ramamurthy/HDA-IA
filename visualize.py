"""Folium map (OpenStreetMap base) and recovery-curve chart."""
import folium
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shapely
from shapely.geometry import Point

import config

PHASE_COLORS = {1: "#2a78d6", 2: "#eb6834", 3: "#1baf7a"}  # categorical slots 1-3
PHASE_NAMES = {1: "Phase 1: restore the first 50% of lost access", 2: "Phase 2: restore up to 80%", 3: "Phase 3: restore the rest"}
GROUP_STYLE = {"health": ("H", "#c2185b"), "emergency": ("E", "#6a1b9a"), "power": ("P", "#f9a825"), "water": ("W", "#0277bd"), "transport": ("T", "#455a64")}
GROUP_LABEL = {"health": "Health (hospitals)", "emergency": "Emergency (fire, police)", "power": "Power (substations)", "water": "Water and sanitation", "transport": "Rail, metro, bus stations"}
INK, GRID = "#6b6a66", "#c9c8c3"


def _ll(geom):
    return [(y, x) for x, y in geom.coords]


def _letter(letter, color, damaged, size=20):
    border = "3px solid #d7191c" if damaged else "2px solid #fff"
    return folium.DivIcon(html=f'<div style="background:{color};color:#fff;width:{size}px;height:{size}px;border-radius:4px;text-align:center;'
                                f'line-height:{size - 4}px;font:bold 11px sans-serif;border:{border}">{letter}</div>', icon_size=(size, size), icon_anchor=(size // 2, size // 2))


def _gdf(frame, cols):
    """Light GeoDataFrame for a GeoJSON layer: only the needed columns, coordinates rounded to ~1 m."""
    g = frame[cols + ["geometry"]].copy()
    g["geometry"] = shapely.set_precision(g.geometry.values, 1e-5)
    return g


def make_map(res, path=None):
    """OSM map of one assessed disaster: damaged roads and bridges, facilities, cut-off junctions, numbered repair priorities.

    Roads are drawn as a few GeoJSON layers (not one object per road) so a 10 km network stays light in the browser.
    """
    G, h = res.base.G, res.hazard
    e = res.edges.to_crs(4326)
    fac = res.fac.to_crs(4326)
    rank = {r.key: r for r in res.ranking.itertuples()} if hasattr(res, "ranking") else None
    metric = h.unit.split(" (")[0]
    m = folium.Map(location=config.CENTER, zoom_start=13, tiles="OpenStreetMap", prefer_canvas=True)

    ok = folium.FeatureGroup("Undamaged roads", show=True)
    folium.GeoJson(_gdf(e[~e.damaged], []), style_function=lambda f: {"color": "#7a7a7a", "weight": 1.2, "opacity": 0.65}).add_to(ok)
    ok.add_to(m)

    dm = e[e.damaged].copy()

    def tip(r):
        t = f"{r['name'] or r.highway} ({'bridge' if r.bridge else r.highway}) | {r.length:.0f} m | {metric} {r.metric:.2f} | repair ₹{r.cost_lakh:.1f} lakh"
        if rank is not None and (r.u, r.v) in rank:
            t += f" | priority #{rank[(r.u, r.v)].priority}, phase {rank[(r.u, r.v)].phase}"
        else:
            t += " | not needed to restore access"
        return t

    dm["tip"] = dm.apply(tip, axis=1)
    for name, sel, style in (("Damaged roads", ~dm.bridge, {"color": "#d7191c", "weight": 3.5}),
                             ("Damaged bridges", dm.bridge, {"color": "#d7191c", "weight": 6, "dashArray": "8 6"})):
        sub = dm[sel]
        if len(sub):
            fg = folium.FeatureGroup(name, show=True)
            folium.GeoJson(_gdf(sub, ["tip"]), style_function=lambda f, s=style: s,
                           tooltip=folium.GeoJsonTooltip(fields=["tip"], labels=False, sticky=True)).add_to(fg)
            fg.add_to(m)

    cut_nodes = getattr(res, "cut_nodes", [])
    if cut_nodes:
        pts = gpd.GeoDataFrame(geometry=[Point(G.nodes[n]["x"], G.nodes[n]["y"]) for n in cut_nodes], crs=config.CRS_PROJECTED).to_crs(4326)
        fg = folium.FeatureGroup("Junctions cut off from every hospital", show=True)
        folium.GeoJson(_gdf(pts, []), marker=folium.CircleMarker(radius=2.5, color="#7b3294", weight=0, fill=True, fill_opacity=0.75)).add_to(fg)
        fg.add_to(m)

    fg_ok, fg_bad = folium.FeatureGroup("Facilities (working)", show=True), folium.FeatureGroup("Facilities (damaged)", show=True)
    for i, r in fac.iterrows():
        letter, color = GROUP_STYLE[r.group]
        t = f"<b>{r['name'] or r.kind}</b><br>{GROUP_LABEL[r.group]} · {r.kind}<br>{metric} {r.metric:.2f}"
        if r.damaged:
            t += f"<br>repair estimate ₹{r.cost_lakh:.1f} lakh"
            if rank is not None and ("F", i) in rank:
                t += f"<br><b>priority #{rank[('F', i)].priority} · phase {rank[('F', i)].phase}</b>"
        folium.Marker((r.geometry.y, r.geometry.x), icon=_letter(letter, color, bool(r.damaged), 18), tooltip=t).add_to(fg_bad if r.damaged else fg_ok)
    fg_ok.add_to(m)
    fg_bad.add_to(m)

    if rank is not None:
        lookup = e.set_index(["u", "v"]).geometry
        for ph in (1, 2, 3):
            g = folium.FeatureGroup(PHASE_NAMES[ph], show=True)
            for p in res.ranking[(res.ranking.phase == ph) & (res.ranking.priority <= config.N_LABELS)].itertuples():
                key = p.key
                pt = fac.geometry.loc[key[1]] if key[0] == "F" else lookup[key].interpolate(0.5, normalized=True)
                dy = -16 if key[0] == "F" else 0
                folium.Marker((pt.y, pt.x), icon=folium.DivIcon(
                    html=f'<div style="background:{PHASE_COLORS[ph]};color:#fff;border-radius:50%;width:22px;height:22px;text-align:center;line-height:22px;'
                         f'font:bold 11px sans-serif;border:1px solid #fff;margin-top:{dy}px">{p.priority}</div>', icon_size=(22, 22), icon_anchor=(11, 11)),
                    tooltip=f"Priority {p.priority} · {p.asset} · ₹{p.repair_cost_lakh:.1f} lakh · {p.cum_access_recovered_pct:.0f}% of lost access back after this repair").add_to(g)
            g.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    if path:
        m.save(path)
    return m


def plot_curves(curves, grid, path=None, title="Recovery curve: prioritised vs. other repair orders"):
    fig, ax = plt.subplots(figsize=(8, 4.6))
    fig.patch.set_alpha(0)
    ax.patch.set_alpha(0)
    km, rec = curves["greedy"]
    ax.step(km, rec, where="post", color="#2a78d6", lw=2.5, label="Priority plan (access gained per rupee)")
    km, rec = curves["longest"]
    ax.step(km, rec, where="post", color="#eb6834", lw=1.8, label="Longest road first")
    r = np.array([np.interp(grid, k, v) for k, v in curves["random"]])
    ax.plot(grid, r.mean(0), color="#7f7f7f", lw=2, label=f"Random order (mean of {len(r)})")
    ax.fill_between(grid, np.percentile(r, 10, 0), np.percentile(r, 90, 0), color="#7f7f7f", alpha=0.2, label="Random 10-90%")
    ax.set_xlim(0, grid[-1])
    ax.set_ylim(0, 102)
    ax.set_xlabel("Cumulative repair spending (₹ crore)", color=INK)
    ax.set_ylabel("Service access recovered (%)", color=INK)
    ax.set_title(title, loc="left", color=INK, fontweight="bold")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK)
    ax.grid(alpha=0.3, color=GRID)
    ax.legend(loc="lower right", frameon=False, labelcolor=INK)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=150, transparent=True)
    return fig
