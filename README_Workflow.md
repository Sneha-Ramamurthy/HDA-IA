# Post-Disaster Infrastructure Recovery Prioritization

> Ranks post-disaster repairs on a road-and-facility network so that access to hospitals, emergency services, power, water and transport returns fastest **per rupee spent**.

**Headline result (severe flood):** the priority order restores on average **91.5%** of lost service access over the plan's spending, versus **37.5%** for longest-road-first and **24.9%** for random order.

> 📘 This is **README 1 of 2** (overview, usage, results). For methods, algorithms, hazard models, cost model, testing and viva prep, see [`README_TECHNICAL.md`](README_TECHNICAL.md).

---

## Contents

1. [Overview](#1-overview)
2. [Objectives and scope](#2-objectives-and-scope)
3. [Workflow](#3-workflow)
4. [Architecture](#4-architecture)
5. [Technology stack](#5-technology-stack)
6. [Quick start](#6-quick-start)
7. [Dashboard](#7-dashboard)
8. [Results](#8-results)
9. [Project layout](#9-project-layout)
10. [Configuration](#10-configuration)
11. [Limitations and future work](#11-limitations-and-future-work)

---

## 1. Overview

**Problem.** After a flood, cyclone or earthquake, budgets and crews are limited. Fixing roads in the wrong order leaves people cut off from hospitals and utilities longer than necessary. A damage map alone does not say what to fix first.

**Approach.**

- **Study area:** 10 × 10 km around Kurla and Vidyavihar, Mumbai (centre 19.075 N, 72.883 E), crossed by the Mithi River.
- **Data:** 10,011 junctions, 13,599 road segments and 480 facilities from OpenStreetMap, modelled as a graph.
- **Hazards:** a data-driven hazard model per disaster decides which roads, bridges and facilities are damaged.
- **Impact:** the system recomputes every junction's travel time to the nearest *working* facility of each service.
- **Ranking:** a lazy greedy algorithm orders repairs by access regained per rupee.

**Outputs.**

- A numbered priority order and three repair phases
- A rupee budget and a recovery curve
- An interactive OpenStreetMap damage map
- A Streamlit dashboard with **no user inputs**; every scenario is chosen automatically from data

The method is not specific to Mumbai, but some inputs (cyclone archive, earthquake equation, map projection) are set for western India.

---

## 2. Objectives and scope

### Objectives

- Model the road network, bridges and critical facilities of a real urban area as one graph.
- Derive flood, cyclone and earthquake damage from datasets (terrain, tree cover, real storm tracks, soil stiffness, faults), not from sliders.
- Measure harm as loss of access to five services: health, emergency, power, water, transport.
- Rank roads, bridges and facilities together by access regained per rupee; report phases, budget and recovery curve.
- Compare against naive strategies (longest road first, random order).
- Deliver an automatic dashboard that opens in seconds.

### In scope

- One 10 × 10 km study area, three disasters, three severity levels each
- Roads, bridges, hospitals, fire and police stations, substations, water facilities, rail, metro and bus stations
- Placeholder repair costs with a structure real rate schedules can replace

### Out of scope

- Forecasting (every result is a scenario, not a prediction)
- Population weighting, facility capacity, and facility dependencies (e.g. hospital losing power)
- Validation against recorded road damage (no public dataset exists for this area)
- Exact optimisation (the ranking is a heuristic)

---

## 3. Workflow

The same six stages run for every disaster and every severity level.

| # | Stage | What happens |
|---|-------|--------------|
| 1 | **Acquire data** | OSM roads, lanes, bridges, rivers, facilities; Copernicus elevation; ESA WorldCover; NOAA IBTrACS; USGS catalogue + Vs30; GEM faults; EM-DAT. Downloaded once, cached in `data/`. |
| 2 | **Build network** | OSM graph → simple undirected NetworkX graph (edge weight = travel time at 25 km/h). Facilities snapped to nearest junction, tagged by service group. |
| 3 | **Run hazard model** | A `Flood`, `Storm` or `Quake` object assigns each road, bridge and facility a physical metric and a damage class 0–4. Class ≥ 3 = damaged. |
| 4 | **Measure impact** | Damaged roads become impassable; damaged facilities stop being sources. One multi-source Dijkstra per service gives travel time to nearest working facility (capped at 15 min). Summed into one cost, **J**. |
| 5 | **Prioritise repairs** | Lazy greedy loop repairs the asset with best drop in J per rupee until J returns to its pre-disaster value. Split into 3 phases at 50%, 80%, 100% of lost access. |
| 6 | **Present** | Results pickled once; Streamlit loads them and draws Folium maps, KPIs, plans, charts. |

Severity levels run in parallel on all CPU cores. The most severe level of each disaster also gets full baseline comparisons. A sanity assertion closes every run: **repairing every damaged asset must reproduce the pre-disaster cost exactly.**

---

## 4. Architecture

A one-way pipeline in six layers:

```
Data sources      OpenStreetMap | DEM + land cover | Hazard datasets | EM-DAT (3 files)
      ↓
Ingestion/cache   data_loader, assets, dem_hazard, hazards  → cached in data/
      ↓
Core modules      Graph model  |  Hazard models  |  Prioritizer (lazy greedy)
      ↓
Orchestration     pipeline.py + build.py  (9 severity levels in parallel)
      ↓
Result cache      data/results.pkl  (SHA-1 signature of code + data)
      ↓
Presentation      Streamlit dashboard | Folium maps + charts | CLI (main.py)
```

The dashboard and CLI only *read* saved results. The prioritizer is the key component because it produces the main output, the ranked plan.

---

## 5. Technology stack

Pure **Python 3.13**; each library has one job.

| Layer | Tools | Role |
|-------|-------|------|
| Data download | OSMnx, pystac-client, planetary-computer, fsspec, h5py, requests, certifi | OSM data; DEM and WorldCover windows; windowed Vs30 read via HTTP range requests |
| Graph | NetworkX | Undirected road graph |
| Fast paths | SciPy `sparse.csgraph.dijkstra` | Multi-source shortest paths on CSR matrix (~8× faster than NetworkX) |
| Vector GIS | GeoPandas, Shapely, PyProj | Geometry, sampling, projection to EPSG:32643 (UTM 43N) |
| Raster GIS | Rasterio, `scipy.ndimage` | DEM read, HAND, connected-component labelling |
| Numerics | NumPy, pandas, openpyxl | Vectorised hazard maths, tables, EM-DAT Excel |
| Parallelism | `concurrent.futures.ProcessPoolExecutor` (fork) | Severity levels in parallel on 8 cores |
| Persistence | pickle + SHA-1 code signature | Rebuild only when code/settings/data change |
| Mapping | Folium (Leaflet), OSM tiles | Interactive damage maps |
| Charts | Matplotlib | Recovery curves, EM-DAT charts |
| Dashboard | Streamlit 1.66 | Tabs, metrics, tables, caching |

Dependencies are in `requirements.txt`; the virtual environment lives in `.venv/`.

---

## 6. Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/streamlit run app.py   # dashboard; opens in seconds once data/results.pkl exists
.venv/bin/python build.py        # rebuild all assessments (~2 min, parallel on all cores)
.venv/bin/python main.py         # prints tables; writes maps, plan CSVs, charts to outputs/
```

- The **first-ever run** downloads OSM, elevation, tree cover and soil data (~14 min for 10 × 10 km, limited by public servers) and caches it in `data/`.
- Results rebuild automatically when code, settings or road data change.

### Run-time summary

| Quantity | Before | After |
|----------|--------|-------|
| Full assessment, 10 × 10 km | 37 min | 2 min 9 s |
| CLI run with saved results | ~20 min | 16 s |
| Dashboard load | not usable | ~18 s |
| Largest map file | 12 MB | 4.5 MB |

### Using another city

Change `CENTER` and `DIST_M` in `config.py` and clear the cached files. OSM, DEM, WorldCover, USGS and GEM are global. The cyclone file, ground-motion equation and projection are set for western India and must be swapped for other regions.

---

## 7. Dashboard

Six top-level tabs, no sidebar, no inputs (the headless test counts zero sliders, select boxes, radios and uploaders).

| Tab | Contents |
|-----|----------|
| **Overview** | Severe-case comparison of the three disasters, network size, facility counts, one-line character of each disaster |
| **Flood / Storm / Earthquake** | Event card, five KPIs, four sub-tabs (below) |
| **Disaster history** | EM-DAT charts: events per year, people affected, events by month, world ranking, Mumbai-region events |
| **Method and limits** | Data sources, hazard rules, assumptions, limitations |

### Each disaster tab

- **Event card:** Flood → matched EM-DAT reference flood. Storm → IBTrACS cyclone matched to EM-DAT. Earthquake → scenario source, bedrock PGA, strongest recorded quake.
- **Five KPIs:** damaged roads (and bridges); damaged facilities; junctions cut off from hospitals; repair budget for everything damaged; cost and number of repairs to restore all access.
- **Damage map (Folium):** layers for undamaged/damaged roads, damaged bridges (dashed), cut-off junctions, working/damaged facilities (lettered squares H, E, P, W, T) and numbered priority markers coloured by phase. Hover shows metric (depth, wind or PGA), cost, priority.
- **Repair plan:** phase table, full priority table (asset, type, service, metric, cost, cumulative cost, access restored) and CSV download.
- **Recovery curve:** priority plan vs longest-first vs random (10th–90th percentile band) plus average access recovered by each.
- **Services and severity:** per-service facilities, cut-off junctions and mean minutes to nearest (before/after); three-level severity table.

---

## 8. Results

Study area: 10,011 junctions, 13,599 road segments, 480 facilities (322 health, 90 transport, 36 emergency, 17 water, 15 power).

| Scenario | Damaged roads | Of which bridges | Damaged facilities | Junctions cut off from hospitals | Budget, all damaged (₹ crore) | Plan to restore access (₹ crore) | Repairs in plan |
|----------|---:|---:|---:|---:|---:|---:|---:|
| Flood 3 m | 1,548 (11.4%) | 79 | 22 | 1,258 | 111.1 | 101.2 | 1,556 |
| Flood 4 m | 2,284 (16.8%) | 109 | 36 | 1,817 | 165.8 | 150.6 | 2,299 |
| **Flood 5 m** | **3,088 (22.7%)** | 133 | 51 | 2,475 | 220.3 | **198.8** | 3,114 |
| Storm: Phyan 2009 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Storm: Tauktae 2021 | 278 (2.0%) | 0 | 0 | 209 | 0.8 | 0.8 | 272 |
| Storm: Nisarga 2020 | 1,239 (9.1%) | 0 | 15 | 881 | 37.9 | 29.7 | 1,232 |
| Earthquake M6.5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Earthquake M7.0 | 38 (0.3%) | 38 | 0 | 10 | 6.2 | 3.6 | 35 |
| Earthquake M7.5 | 291 (2.1%) | 291 | 151 | 361 | 262.9 | 199.8 | 380 |

### Why prioritising pays (severe flood)

| Strategy | Avg. access recovered over plan's spending |
|----------|---:|
| **Priority (gain per rupee)** | **91.5%** |
| Longest road first | 37.5% |
| Random order (5 seeded runs) | 24.9% |

Repairing every damaged asset reproduces the pre-disaster cost exactly in all three disasters.

### Character of each disaster

- **Flood:** damages the most roads, following the Mithi corridor (median damaged road ~400 m from the river, none beyond ~1 km) and bridge approaches.
- **Storm:** blocks tree-lined roads; Nisarga takes out all 15 mapped substations (fail above 30 m/s) and spares bridges.
- **Earthquake:** barely touches ordinary roads but damages bridges and facilities on amplifying soils. At M7.5, 151 facilities are damaged and 361 junctions lose access to every working hospital.

### Sensitivity

Moving from the 3 m to the 5 m flood roughly doubles damaged roads and cost, which is why the dashboard always shows a severity ladder rather than a single number.

---

## 9. Project layout

| Path | Contents |
|------|----------|
| `config.py` | Study area, speeds, caps, thresholds, cost rates, dataset URLs |
| `data_loader.py`, `assets.py` | OSM roads, rivers, facilities |
| `graph_model.py` | Graph construction and the `Evaluator` |
| `dem_hazard.py`, `hazards.py` | Flood depth grid; `Flood`, `Storm`, `Quake` classes; severity ladders |
| `prioritize.py` | Lazy greedy, baselines, recovery curves |
| `pipeline.py`, `build.py`, `cache.py` | Orchestration, parallel runs, result cache |
| `visualize.py`, `emdat_chart.py` | Maps and charts |
| `app.py`, `main.py` | Streamlit dashboard and CLI runner |
| `data/` | Cached downloads, the three EM-DAT files, `results.pkl` |
| `outputs/` | `map_<disaster>.html`, plan CSVs, recovery curves, EM-DAT charts |
| `data_5km_backup/` | Earlier 5 × 5 km caches (set `DIST_M = 2500` to return to that box) |
| `EVALUATION_GUIDE.md` | Short talking-points guide for evaluation |

---

## 10. Configuration

All tunable numbers live in `config.py`.

| Setting | Meaning | Value |
|---------|---------|-------|
| `CENTER`, `DIST_M` | Study-area centre and half-width | (19.075, 72.883), 5,000 m |
| `SPEED_KMH`, `T_CAP_MIN` | Travel speed and cut-off time | 25 km/h, 15 min |
| `DAMAGE_THRESHOLD` | Hazard class at which an asset is damaged | 3 |
| `STAGE_LADDER_M`, `FLOODPLAIN_MAX_M` | Flood stages and floodplain width | 3, 4, 5 m; 1,000 m |
| `QUAKE_LADDER_MAG`, `STORM_LADDER_N` | Earthquake magnitudes; number of real storms | 6.5, 7.0, 7.5; 3 |
| `N_RANDOM`, `CURVE_POINTS` | Random baseline runs; sampled curve points | 5; 120 |

---

## 11. Limitations and future work

### Limitations

- Results are **scenarios, not forecasts**.
- The repair unit is an OSM segment, not a whole named road, so plans contain thousands of small repairs.
- No facility dependencies, capacity or population weighting.
- OSM is incomplete for utilities; inputs are coarse (30 m elevation, 1 km soil grid).
- Lazy greedy is a heuristic with no optimality guarantee.
- One study area; cyclone archive, ground-motion equation and projection are set for western India.
- Flood level, storm tree-fall rule, quake magnitudes beyond the regional record and all repair rates are assumptions.

### Future work

- Real flood-extent data and BMC / Maharashtra PWD repair rates
- Population weighting (e.g. WorldPop)
- Facility dependencies (power → hospitals) and capacity-aware access
- Exact optimisation (integer programming) to bound the heuristic's gap
- Merging adjacent damaged segments into whole-road repair units
- Validation against flood-prone spot records and past inundation maps; other cities

---

➡️ **Next:** [`README_TECHNICAL.md`](README_TECHNICAL.md) for data sources, module internals, algorithms, hazard models, cost model, testing and viva Q&A.
