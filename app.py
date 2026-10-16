"""Streamlit dashboard: automatic multi-hazard infrastructure recovery plan (no user inputs)."""
import pandas as pd
import streamlit as st

import config
from emdat_chart import (country_ranking, disasters, india_affected_per_year, india_by_month, india_events_per_year, load_emdat,
                         mumbai_events, summary)
from events import reference_event
from hazards import strongest_recorded
from cache import load_or_build
from visualize import GROUP_LABEL, PHASE_NAMES, make_map, plot_curves

st.set_page_config(page_title="Infrastructure Recovery Planner", page_icon="🛠️", layout="wide")


@st.cache_resource(show_spinner="Building the assessments for flood, storm and earthquake (a couple of minutes, only when data or code changed)...")
def assess():
    return load_or_build()


@st.cache_data(show_spinner="Drawing the map...")
def map_html(key):
    return make_map(results[key].res).get_root().render()


@st.cache_data(show_spinner="Reading the EM-DAT files...")
def get_emdat():
    return load_emdat()


@st.cache_data(show_spinner=False)
def get_quake_record():
    return strongest_recorded()


base, results = assess()
emdat = get_emdat()
n_fac = len(base.facilities)
n_edges = len(base.edges)
AREA = f"{2 * config.DIST_M / 1000:g}×{2 * config.DIST_M / 1000:g} km"

st.title("🛠️ Post-Disaster Infrastructure Recovery Plan")
st.caption("Kurla / Vidyavihar, Mumbai · roads, bridges, hospitals, emergency services, power, water and transport as one network · "
           "flood, storm and earthquake · repairs ranked by service-access gain per rupee · every input is chosen automatically from data")

KEYS = ["flood", "storm", "quake"]
LABEL = {k: results[k].res.hazard.label for k in KEYS}


def event_card(key):
    res = results[key].res
    h = res.hazard
    india = emdat.get("india")
    if key == "flood":
        ev = reference_event(base.water, india) if india is not None else None
        if ev is not None:
            st.info(f"**Reference event (matched automatically):** OpenStreetMap shows the {ev['matched_river']} River here, and EM-DAT's flood on that river is "
                    f"**{ev['DisNo.']}**, {int(ev['Start Day'])}/{int(ev['Start Month'])}/{int(ev['Start Year'])} to {int(ev['End Day'])}/{int(ev['End Month'])}/{int(ev['End Year'])}: "
                    f"{int(ev['Total Deaths']):,} deaths, {ev['Total Affected'] / 1e6:.0f} M people affected. The scenarios below are terrain-based floods on this river "
                    f"(water {', '.join(f'{s:g}' for s in config.STAGE_LADDER_M)} m above it), not a reconstruction of that event.")
    elif key == "storm":
        txt = h.event_text(base)
        m = india[india["Event Name"].str.contains(h.name, case=False, na=False)] if india is not None else None
        if m is not None and len(m):
            e = m.iloc[0]
            txt += f" EM-DAT lists the same storm as **{e['DisNo.']}**: {int(e['Total Deaths']) if pd.notna(e['Total Deaths']) else 'n/a'} deaths, location: {str(e['Location'])[:90]}."
        st.info("**Reference event (strongest real cyclone at this site, matched to EM-DAT by name):** " + txt)
    else:
        q = get_quake_record()
        st.info(f"**Scenario:** {h.event_text(base)} For comparison, the strongest earthquake on record within 500 km (USGS) is **M{q['mag']:.1f}**, {q['time'][:4]}, "
                f"'{q['place']}', about 210 km away, which would be barely felt here. "
                f"The magnitudes {', '.join(f'M{m:g}' for m in config.QUAKE_LADDER_MAG)} are a ladder: M6.5 is the regional record, M7.0 and M7.5 are hypothetical.")


def render(key):
    o = results[key]
    res, tab = o.res, o.table
    pre_h, post_h = res.pre_groups["health"], res.post_groups["health"]
    n_dmg_road, n_br = int(res.edges.damaged.sum()), int((res.edges.damaged & res.edges.bridge).sum())
    n_dmg_fac = int(res.fac.damaged.sum())
    event_card(key)
    c = st.columns(5)
    c[0].metric("Damaged roads", n_dmg_road, f"{n_br} of them bridges · {100 * n_dmg_road / n_edges:.1f}% of network", delta_color="off")
    c[1].metric("Damaged facilities", n_dmg_fac, f"of {n_fac} mapped", delta_color="off")
    c[2].metric("Junctions cut off from hospitals", post_h["cut_off"], f"{post_h['cut_off'] - pre_h['cut_off']:+d} vs. before", delta_color="inverse")
    c[3].metric("Repair budget, everything damaged", f"₹{res.total_cost_crore:.1f} crore", "placeholder rates", delta_color="off")
    c[4].metric("Plan to restore all service access", f"₹{res.plan_cost_crore:.1f} crore", f"{len(res.order)} repairs", delta_color="off")

    t_map, t_plan, t_curve, t_serv = st.tabs(["🗺️ Damage map", "📋 Repair plan", "📈 Recovery curve", "🔌 Services & severity"])
    with t_map:
        st.iframe(map_html(key), height=680)
        st.caption(f"OpenStreetMap · red lines = damaged roads (dashed = bridges; hover for {res.hazard.unit} and cost) · lettered squares = facilities (H health, E emergency, "
                   "P power, W water, T transport; red border = damaged) · purple dots = junctions cut off from every hospital · numbered circles = repair priority by phase. "
                   "Use the layer list on the map to show or hide layers.")
    with t_plan:
        rk = res.ranking
        ph = rk.groupby("phase").agg(roads=("kind", lambda s: int((s == "road").sum())), facilities=("kind", lambda s: int((s == "facility").sum())),
                                     cost=("repair_cost_lakh", lambda s: s.sum() / 100), access=("cum_access_recovered_pct", "max")).reset_index()
        ph["Phase"] = ph["phase"].map(PHASE_NAMES)
        ph = ph.rename(columns={"roads": "Roads and bridges", "facilities": "Facilities", "cost": "Cost (₹ crore)", "access": "Lost access restored by end (%)"})
        st.subheader("Repair phases")
        st.dataframe(ph[["Phase", "Roads and bridges", "Facilities", "Cost (₹ crore)", "Lost access restored by end (%)"]].round(2), hide_index=True, width="stretch")
        left = res.n_units - len(rk)
        st.write(f"The plan restores all lost service access with **{len(rk)} repairs costing ₹{res.plan_cost_crore:.1f} crore**. "
                 f"The other {left} damaged assets (₹{res.total_cost_crore - res.plan_cost_crore:.1f} crore) don't change any service's access and can follow later.")
        st.subheader("Priority order")
        show = rk.drop(columns=["key"]).rename(columns={"priority": "Priority", "phase": "Phase", "kind": "Kind", "asset": "Asset", "type": "Type", "group": "Service",
                                                        "length_m": "Length (m)", "hazard_metric": res.hazard.unit.capitalize(), "repair_cost_lakh": "Repair cost (₹ lakh)",
                                                        "cum_cost_crore": "Cumulative cost (₹ crore)", "cum_access_recovered_pct": "Access restored (%)"})
        st.dataframe(show, hide_index=True, width="stretch", height=520)
        st.download_button("Download repair plan (CSV)", show.to_csv(index=False), f"repair_plan_{key}.csv", "text/csv", key=f"dl_{key}")
    with t_curve:
        st.pyplot(plot_curves(res.curves, res.grid, title=f"Recovery curve, {res.hazard.label.lower()} ({res.hazard.rung})"), width="content")
        s = res.scores
        cc = st.columns(3)
        for col, (name, v) in zip(cc, s.items()):
            col.metric(f"{name}: average access recovered over ₹{res.grid[-1]:.1f} crore", f"{v:.1f}%")
        st.info(f"For the same spending, the prioritised order restores about {s['Greedy'] / max(s['Random (mean)'], 0.1):.1f}× more service access than a random order.")
    with t_serv:
        st.subheader("Access to each service, before and after")
        rows = []
        for g in res.pre_groups:
            a, b = res.pre_groups[g], res.post_groups[g]
            rows.append({"Service": GROUP_LABEL[g], "Facilities mapped": a["facilities"], "Facilities damaged": int(((res.fac.group == g) & res.fac.damaged).sum()),
                         "Junctions cut off, before": a["cut_off"], "Junctions cut off, after": b["cut_off"],
                         "Mean minutes to nearest, before": round(a["mean_min"], 1), "Mean minutes to nearest, after": round(b["mean_min"], 1)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("A junction is 'cut off' from a service when no working facility of that kind is reachable within "
                   f"{config.T_CAP_MIN} minutes by road ({config.SPEED_KMH} km/h assumed). The plan optimises all services together, equally weighted.")
        st.subheader("How much does the answer depend on severity?")
        st.write("The same assessment at three severity levels. The plan above uses the most severe one.")
        st.dataframe(tab, hide_index=True, width="stretch")


def history(kind):
    if not {"world", "india", "recent"} <= emdat.keys():
        st.info("EM-DAT files not found. Check config.EMDAT_FILES.")
        return
    s = summary(emdat["world"], emdat["india"], emdat["recent"], kind)
    m = st.columns(5)
    m[0].metric(f"{kind} events in India", s["events"], "2000-2026", delta_color="off")
    m[1].metric("People affected", f"{s['affected'] / 1e6:.1f} M", f"{s['reported']} events with a figure", delta_color="off")
    m[2].metric("Lives lost", f"{int(s['deaths']):,}")
    m[3].metric("World rank (people affected)", f"#{s['rank']}" if s["rank"] else "n/a", f"{100 * s['share']:.0f}% of the global total" if s["rank"] else "", delta_color="off")
    m[4].metric("Mumbai-region events", s["mumbai"], f"{s['recent_events']} in India since 2015", delta_color="off")
    c1, c2, c3 = st.columns(3)
    c1.pyplot(india_events_per_year(emdat["india"], kind), width="stretch")
    c2.pyplot(india_affected_per_year(emdat["india"], kind), width="stretch")
    c3.pyplot(india_by_month(emdat["india"], kind), width="stretch")
    w1, w2 = st.columns(2)
    w1.pyplot(country_ranking(emdat["world"], "People affected by country, 2000-2026", kind), width="stretch")
    w2.pyplot(country_ranking(emdat["recent"], "People affected by country, 2015-2026", kind), width="stretch")
    st.caption("Totals use only events where EM-DAT reports people affected, so they are lower bounds.")
    mf = mumbai_events(disasters(emdat["india"], kind, "India"))
    if len(mf):
        st.subheader(f"Mumbai-region {kind.lower()} events")
        st.dataframe(mf[["Start Year", "Start Month", "Location", "Total Deaths", "Total Affected"]].sort_values(["Start Year", "Start Month"], ascending=False),
                     hide_index=True, width="stretch")


tabs = st.tabs(["🏠 Overview", "🌊 Flood", "🌀 Storm", "🌍 Earthquake", "📚 Disaster history", "ℹ️ Method & limits"])

with tabs[0]:
    st.subheader("Three disasters, one network")
    rows = []
    for k in KEYS:
        r = results[k].res
        h = r.post_groups["health"]
        rows.append({"Disaster (severe case)": f"{LABEL[k]}: {r.hazard.rung}", "Damaged roads": int(r.edges.damaged.sum()), "of which bridges": int((r.edges.damaged & r.edges.bridge).sum()),
                     "Damaged facilities": int(r.fac.damaged.sum()), "Junctions cut off from hospitals": h["cut_off"],
                     "Repair budget, all damaged (₹ crore)": round(r.total_cost_crore, 1), "Plan to restore access (₹ crore)": round(r.plan_cost_crore, 1),
                     "Repairs in plan": len(r.order)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.write(f"Study area: a {AREA} box around Kurla and Vidyavihar with **{base.G.number_of_nodes():,} junctions, {n_edges:,} road segments and {n_fac} mapped facilities** "
             f"({', '.join(f'{v} {GROUP_LABEL[g].split(' (')[0].lower()}' for g, v in base.facilities.group.value_counts().items())}).")
    st.markdown("""
- **Flood** hits the low ground along the Mithi River and the bridges' approaches.
- **Storm** blocks tree-lined roads and can switch off power; it spares bridges and most buildings.
- **Earthquake** barely touches roads but damages bridges and facilities, so it cuts the network at its weak points.

Open each disaster's tab for its map, repair plan, budget and recovery curve. The same method runs for all three: damage is removed from the network,
service access (travel time to the nearest working hospital, fire or police station, substation, water facility and station) is recomputed, and repairs are ranked by access gained per rupee.
""")

for key, tab in zip(KEYS, tabs[1:4]):
    with tab:
        render(key)

with tabs[4]:
    sub = st.tabs(["Floods", "Storms", "Earthquakes"])
    for kind, t in zip(["Flood", "Storm", "Earthquake"], sub):
        with t:
            history(kind)

with tabs[5]:
    st.markdown(f"""
**What this does, automatically** OpenStreetMap roads, lanes, bridges and facilities → network → each disaster's hazard from data → damaged assets removed →
service access recomputed for five services (health, emergency, power, water, transport) → repairs ranked greedily by access gained per rupee until all lost access is restored.

**Where each input comes from**
- Roads, lanes, bridges, facilities, rivers: OpenStreetMap. Terrain: Copernicus GLO-30 elevation. Tree cover: ESA WorldCover. Soil stiffness (Vs30): USGS global Vs30 grid.
- Real cyclone tracks: NOAA IBTrACS. Earthquake catalogue: USGS. Active faults: GEM Global Active Faults. Flood, storm and earthquake history: the three EM-DAT files.

**Flood** Height above the nearest river cell; water stands at 3, 4 or 5 m above the river and floods low ground only where it connects to the river and lies within {config.FLOODPLAIN_MAX_M} m of it. A road is damaged at ≥ 0.5 m depth
(75th percentile along it; bridges are judged at their approaches). Facilities are damaged at ≥ 0.5 m at their location.

**Storm** The three real cyclones with the strongest estimated wind at the site (Holland wind profile from IBTrACS track, intensity and radius). Wind force grows with the square of speed;
a road is blocked where tree cover is high enough for that wind (score = tree share × (wind/17.5 m/s)²). Substations fail at ≥ {config.POWER_WIND_FAIL_MS:.0f} m/s.

**Earthquake** Ground motion from the published peninsular-India equation (Raghukanth & Iyengar 2007, Southern region; coefficients read from OpenQuake's source), site amplification from USGS Vs30 soil classes,
on the nearest mapped fault. Damage classes use fixed PGA cut points (0.3 g for class 3) with bridges 1.3× and roads 0.7× as vulnerable as buildings.

**What could not be taken from data (assumptions)**
- Flood level, storm tree-fall thresholds and earthquake magnitudes beyond the regional record are assumptions, shown as three-level ladders. No available dataset pins them down:
  Sentinel-1 radar saw almost no flooding in the dense city on 2 July 2019, reanalysis rainfall misses extreme storms, and the nearest mapped fault is an offshore ridge (the regional record, M6.5 in 1967 at about 210 km, barely affects Kurla).
- Repair costs: no public machine-readable rate schedule exists. Road cost = length × lanes × placeholder rate per lane-km × share needing reconstruction (25% or 50%); bridges ×{config.BRIDGE_COST_FACTOR};
  facility costs are placeholders. Replace them in `config.py` with BMC / Maharashtra PWD figures.
- Services are equally weighted; reach is by road within {config.T_CAP_MIN} minutes at {config.SPEED_KMH} km/h; there are no dependencies between facilities (for example, hospitals losing power).

**Limitations** 30 m elevation and 1 km soil grids are coarse · not a forecast · greedy ranking is a heuristic · repair unit is an OSM segment, not a whole named road · OpenStreetMap is incomplete for utilities
(only {int((base.facilities.group == 'power').sum())} substations and {int((base.facilities.group == 'water').sum())} water facilities are mapped here) · "hospital" is anything tagged `amenity=hospital` · fixed {AREA} area.
""")
