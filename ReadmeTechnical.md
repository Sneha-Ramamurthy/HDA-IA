# Technical Reference: Methods, Models and Evaluation

> **README 2 of 2.** Covers datasets, module internals, algorithms, hazard models, the cost model, performance engineering, testing, assumptions and viva preparation. For the overview, quick start, dashboard and results, see [`README.md`](README.md).

---

## Contents

1. [Datasets](#1-datasets)
2. [Module reference](#2-module-reference)
3. [Network and evaluator internals](#3-network-and-evaluator-internals)
4. [Core algorithms](#4-core-algorithms)
5. [Hazard models](#5-hazard-models)
6. [Repair cost model](#6-repair-cost-model)
7. [Performance engineering](#7-performance-engineering)
8. [Testing and validation](#8-testing-and-validation)
9. [Assumptions register](#9-assumptions-register)
10. [Development history](#10-development-history)
11. [Viva preparation Q&A](#11-viva-preparation-qa)

---

## 1. Datasets

Eight open sources feed the model. All except the EM-DAT files are downloaded automatically and cached under `data/`.

| Dataset | Source | Acquisition | Resolution / size | Used for |
|---------|--------|-------------|-------------------|----------|
| Road network, lanes, bridge tags | OpenStreetMap | OSMnx `graph_from_point`, 5,000 m, drive network; retries across 3 Overpass mirrors | 10,011 nodes, 13,599 edges | Graph, travel times, bridges |
| Facilities | OpenStreetMap | `features_from_point` per service group; polygons → centroids | 480 points | Service access, facility damage |
| Rivers and canals | OpenStreetMap | `waterway` = river, canal, stream | 16 KB | Flood source, event matching |
| Elevation | Copernicus GLO-30 DEM | STAC search on Planetary Computer; COG window read, reprojected to EPSG:32643 | 30 m | Flood depth |
| Tree cover | ESA WorldCover 2021 | STAC window read | 10 m, class 10 = trees | Storm tree fall |
| Cyclone tracks | NOAA IBTrACS v04r01 (N. Indian Ocean) | CSV download, 28 MB | 3-hourly fixes | Real storms, wind at site |
| Earthquake catalogue | USGS FDSN event API | CSV, 500 km radius, M ≥ 4.5, since 1900 | 85 events | Strongest recorded quake |
| Active faults | GEM Global Active Faults | GeoJSON, 10 MB | 13,696 traces | Distance to nearest fault |
| Soil stiffness (Vs30) | USGS global Vs30 grid | HTTP range reads of HDF5 via fsspec + h5py (window only) | 30 arc-sec (~1 km) | Local shaking amplification |
| Disaster history | EM-DAT (3 Excel exports) | pandas + openpyxl | 17,082 world rows; 866 India rows; 6,593 world rows (2015–2026) | History tab; event matching |

**Notes**

- The India and 2015–2026 EM-DAT files are subsets of the world file; they add detail, not new events.
- EM-DAT has **no spatial damage data**, so it never decides which roads are damaged.
- **Cross-dataset links in code:** OSM river name "Mithi" ↔ EM-DAT River Basin field → reference flood `2005-0409-IND` (1,200 deaths). IBTrACS storm names ↔ EM-DAT event names (e.g. Nisarga, 2020).

**Datasets tried and rejected**

- **Sentinel-1 radar** (06:33 IST pass, 2 July 2019): showed almost no new open water in the dense city; matched no modelled flood level.
- **ERA5 reanalysis rainfall** (Open-Meteo): understated the 2005 extreme (~125 mm).

Flood level therefore stays an explicit assumption.

---

## 2. Module reference

| Module | Responsibility | Key objects / functions |
|--------|----------------|-------------------------|
| `config.py` | Every setting and assumption | `CENTER`, `DIST_M`, `T_CAP_MIN`, `DAMAGE_FRACTION`, `STAGE_LADDER_M` |
| `data_loader.py` | OSM road graph and rivers; Overpass retry across mirrors | `load_data()`, `overpass_retry()` |
| `assets.py` | Facilities by service group from OSM tags | `load_assets()` |
| `graph_model.py` | Graph construction, snapping, service access evaluator | `build_graph()`, `snap_points()`, `Evaluator` |
| `dem_hazard.py` | DEM download/reprojection; flood depth grid | `ensure_dem()`, `flood_depth_grid()` |
| `hazards.py` | Flood, Storm, Quake classes; severity ladders | `Flood`, `Storm`, `Quake`, `ladders()` |
| `prioritize.py` | Lazy greedy, baselines, recovery curves | `greedy_ranking()`, `recovery_curve()`, `auc()` |
| `pipeline.py` | Orchestration: damage, costs, evaluation, ranking table, parallel runs | `prepare()`, `run()`, `assess_all()` |
| `build.py`, `cache.py` | Build all results once; cache with code signature | `signature()`, `load_or_build()` |
| `visualize.py`, `emdat_chart.py` | Folium map, matplotlib curves, EM-DAT charts | `make_map()`, `plot_curves()` |
| `app.py`, `main.py` | Streamlit dashboard and CLI runner | tabs, KPIs, tables |

### Orchestration (`pipeline.run`) for one hazard

1. `hazard.assess()` returns class and metric arrays for edges and facilities
2. `damaged = class >= 3`
3. Repair costs computed per asset
4. `Evaluator` built with the damaged units
5. `greedy_ranking` returns the repair order
6. `recovery_curve` evaluates access after each repair; phases cut at 50% and 80%
7. Ranking DataFrame assembled for the dashboard

---

## 3. Network and evaluator internals

### Network construction (`graph_model.build_graph`)

- Keep the largest weakly connected component of the OSM multigraph.
- Collapse parallel edges (shortest kept) → simple undirected `nx.Graph`.
- Edge attributes: `length` (m); `travel_time = length / (25 / 3.6)` s; `geometry`; `name`; `highway` (first value if list); `lanes` (OSM tag, else default by road class); boolean `bridge`.
- Coordinates projected to EPSG:32643 so lengths are in metres.

### Facilities (`assets.load_assets`, `graph_model.snap_points`)

| Service group | OSM tags |
|---------------|----------|
| Health | `amenity=hospital` |
| Emergency | `fire_station`, `police` |
| Power | `power=substation` |
| Water | `water_works`, `pumping_station`, `water_tower`, `wastewater_plant` |
| Transport | `railway=station/halt`, `station=subway/light_rail`, `amenity=bus_station` |

Polygons → centroids; duplicates dropped; each point snapped to its nearest graph node (argmin over squared distances). Result: **480 facilities** (322 health, 90 transport, 36 emergency, 17 water, 15 power).

### The Evaluator (`graph_model.Evaluator`)

The performance-critical core; the planner calls it tens of thousands of times.

- **CSR matrix:** graph stored once as a SciPy CSR matrix with both edge directions; array `pos` maps each undirected edge to its two CSR positions.
- **Damage toggling:** a damaged road gets weight `BIG = 1e9` in O(1); repair restores travel time. Because Dijkstra runs with `limit = 900 s`, a BIG edge can never be used.
- **Facilities as sources:** per group, a dictionary counts working facilities per node; a damaged facility is removed.
- **Evaluation:** `evaluate()` runs one multi-source `dijkstra(..., min_only=True, limit=cap)` per group; returns cost **J** and a mask of junctions served by ≥ 1 group.
- **Units:** every repairable asset is a unit: road key `(u, v)` or facility key `("F", i)`, with cost, length, name and node indices.

---

## 4. Core algorithms

### 4.1 Access objective J

For service group *g* (health, emergency, power, water, transport), let *t_g(n)* be the shortest travel time from junction *n* to the nearest working facility of that group. With *T* = 900 s and equal weights *w_g* = 1:

```
J = Σ_g  w_g · Σ_{n ∈ N}  min( t_g(n), T )
```

A junction with *t_g(n) > T* is "cut off" and contributes the full cap *T*. *J_pre* is the floor; *J_post* is the starting point after the disaster.

Recovery after *k* repairs:

```
R_k = 100 · (J_post − J_k) / (J_post − J_pre)
```

The cap keeps J bounded: being 10 hours from a hospital is not scored worse than 15 minutes, so a few extreme junctions cannot dominate.

### 4.2 Shortest paths

`csgraph.dijkstra` runs from all working facilities of a group at once (`min_only=True`) and stops at the limit, exploring only the 15-minute reach. One evaluation of all five groups on the 10 × 10 km network takes **~7 ms**.

### 4.3 Lazy greedy ranking (`prioritize.greedy_ranking`)

At each step pick the damaged unit *u* with the best score:

```
score(u) = ( J − J_after_repairing_u ) / cost(u)
```

Three ideas avoid O(units × steps) evaluations:

1. **Lazy evaluation:** scores sit in a max-heap as stale upper bounds. The top entry is re-scored; if it still beats the next stale score it is accepted, otherwise pushed back. Typically **~2.4 evaluations per step**.
2. **Exact pruning:** a damaged road can only help if one of its ends is already served (`reached` mask). Others enter the heap later when a repair newly reaches them. Damaged facilities are always candidates.
3. **Zero-gain fallback:** if the best gain is 0 (a corridor needs several segments), take the cheapest road crossing the boundary of the served region.

The loop stops when J returns to J_pre or no candidate remains. Because gains can *increase* as the network heals, this is a **heuristic**, not exact greedy.

### 4.4 Baselines and comparison

- **Longest road first:** damaged roads sorted by length, descending.
- **Random order:** five seeded shuffles, averaged.
- **Metric:** each recovery curve R(cost) is interpolated onto a common spending grid and averaged (area under curve ÷ grid length) = "average access recovered over the plan's spending".
- Baseline curves use 120 evenly spaced points; the priority plan is evaluated after every repair.

### 4.5 Phases

Cumulative recovery *R_k* assigns each repair to phase 1 (R < 50%), phase 2 (R < 80%) or phase 3 (the rest), giving crews and budgets clear milestones.

---

## 5. Hazard models

Each disaster is a class in `hazards.py` with an `assess(base)` method returning, for every road and facility, a physical metric and a damage class 0–4. Class ≥ 3 is damaged, so **adding a new disaster means adding one class**.

### 5.1 Flood (`Flood`, `dem_hazard.py`)

Terrain model of the Mithi River at three water levels (3, 4, 5 m above the river).

1. **HAND:** rasterise river/canal/stream ways onto the 30 m DEM grid; Euclidean distance transform with indices gives each cell's nearest river cell; `HAND = DEM(cell) − DEM(nearest river cell)`.
2. **Candidate cells:** HAND ≤ stage **and** within 1,000 m of the river (floodplain width assumption).
3. **Connectivity:** `scipy.ndimage.label` (8-connectivity); only regions touching a river cell flood. `Depth = stage − HAND`.
4. **Depth along roads:** sample every 15 m; road depth = 75th percentile. Bridges judged by max depth at their two ends (deck stands above water). Facilities take the depth of their cell.
5. **Classes:** depth > 0 → class 1; 0.2 m → 2; **0.5 m → 3 (damaged)**; 1.0 m → 4.

### 5.2 Storm (`Storm`)

Three real cyclones, ranked by the wind they would cause at the study area.

- **Catalogue:** IBTrACS 3-hourly fixes; wind = `USA_WIND` else `WMO_WIND` (→ m/s); radius of max wind = `USA_RMW` (default 40 km).
- **Wind at site:** Holland (1980) profile, B = 1.5, maximum over all fixes:

  ```
  V(r) = Vmax · sqrt( x · e^(1−x) ),   x = (Rmax / r)^B
  ```

- **Selected storms:** Nisarga 2020 (33.4 m/s), Tauktae 2021 (25.6 m/s), Phyan 2009 (23.1 m/s).
- **Road blockage:** tree share from WorldCover (class 10), sampled every 10 m on and one pixel either side of the road. `score = tree_share × (V / 17.5)²` when V ≥ 17.5 m/s (tropical storm force), else 0. Cut points 1.0, 2.0, 3.0 → classes 2, 3, 4.
- **Other assets:** bridges exempt (tree fall is a road effect); substations fail at V ≥ 30 m/s.

### 5.3 Earthquake (`Quake`)

Ground-motion equation + local soil on the nearest mapped fault.

- **Source:** nearest GEM trace is an offshore spreading ridge **77 km** away. Strongest recorded quake within 500 km (USGS) is **1967 M6.5 Koyna**, ~210 km away, barely felt in Kurla. Ladder: M6.5 (regional record), M7.0 and M7.5 (hypothetical), at hypocentral distance `R = sqrt(d² + 10²)` km.
- **Bedrock PGA** (Raghukanth & Iyengar 2007, Southern India; coefficients from OpenQuake source):

  ```
  ln y_br = 1.7816 + 0.9205(M−6) − 0.0673(M−6)² − ln R − 0.0035 R
  ```

- **Site amplification:** USGS Vs30 → NEHRP class; `ln F_s = a1·y_br + a2`:

  | Class | Vs30 (m/s) | a1 | a2 |
  |-------|-----------|----:|----:|
  | A | ≥ 1,500 | 0 | 0.36 |
  | B | 760–1,500 | 0 | 0.49 |
  | C | 360–760 | −0.89 | 0.66 |
  | D | < 360 | −2.61 | 0.80 |

- **Damage classes:** site PGA (g) × vulnerability factor (roads 0.7, bridges 1.3, facilities 1.0), cut at 0.1, 0.2, 0.3, 0.4 g → classes 1–4.

### 5.4 Severity ladders

| Disaster | Rung 1 | Rung 2 | Rung 3 (full plan) |
|----------|--------|--------|--------------------|
| Flood | 3 m above river | 4 m | 5 m |
| Storm | Phyan 2009 (23.1 m/s) | Tauktae 2021 (25.6 m/s) | Nisarga 2020 (33.4 m/s) |
| Earthquake | M6.5 | M7.0 | M7.5 |

No dataset fixes the true flood level, and Mumbai has no recorded damaging earthquake, so a ladder is more honest than a single number.

---

## 6. Repair cost model

Costs form the ranking's denominator. The structure is data-driven; **every rate is a placeholder** meant to be replaced by BMC / Maharashtra PWD Schedule of Rates. Units: rupee lakh (1 lakh = 100,000; 1 crore = 100 lakh).

```
cost = (L / 1000) · lanes · rate_class · f(class) · b
```

*L* = length (m); *lanes* = OSM tag or class default; *f* = damage fraction; *b* = 5 for bridges, 1 otherwise.

| Parameter | Placeholder value |
|-----------|-------------------|
| Rate per lane-km (lakh) | motorway/trunk/primary/secondary 20; tertiary 18; residential/unclassified 15; living street/service 10 |
| Default lanes (untagged) | motorway/trunk/primary 4; secondary/tertiary 2; others 1 |
| Damage fraction *f* | 25% at class 3; 50% at class 4 |
| Bridge factor *b* | 5 |
| Facility base cost (lakh) | hospital 500; fire station 150; police 100; substation 800; water works 600; pumping station 200; water tower 100; wastewater plant 800; station 600 (halt 200; subway/light rail 800); bus station 100 |

A facility's repair cost = base cost × the same damage fraction. The same numbers produce the budget and plan cost on the dashboard. Rupee totals are illustrative; ordering, phases and curves depend more on cost **ratios** than absolute scale.

---

## 7. Performance engineering

Scaling from 5 × 5 km to 10 × 10 km cut the full assessment from 37 min to ~2 min by attacking the *measured* bottleneck.

**Profiling:** for the 3 m flood, 9,761 `evaluate()` calls took 71 of 76 s (~7 ms each).

| Change | Effect |
|--------|--------|
| SciPy CSR Dijkstra instead of NetworkX | ~1.2 ms for five services (5 km network) vs ~10 ms for one service before |
| Lazy greedy with exact pruning | ~2.4 evaluations per step instead of re-scoring everything |
| Parallel severity levels (8 processes, fork) | All 9 runs at once; heaviest starts first |
| Reuse the severe run | Severe level run once with baselines, not twice |
| Sampled baselines (120 points, 5 random runs) | A few hundred evaluations, not thousands |
| Floodplain cap (1 km) | More realistic extent; fewer damaged units |
| Result cache (pickle + SHA-1 of code + road-data timestamp) | Dashboard opens without recomputing |
| Subprocess build | `load_or_build()` runs `build.py` in a fresh interpreter, so forking never happens inside Streamlit's threads |
| GeoJSON map layers | A few layers instead of 13,000 polylines; maps 9–12 MB → 4–4.5 MB |
| Overpass retries and mirrors | A 502 no longer ends the run |

The first-ever run still spends ~14 min downloading OSM data from public servers (one-off, then cached).

---

## 8. Testing and validation

The model is validated by invariants, baselines and sanity checks, **not** against recorded damage (no public road-damage dataset exists for this area).

### Built-in invariants (every build)

- **Round trip:** repairing every damaged unit reproduces J_pre (`abs(J − J_pre) < 1e-6`), asserted in `main.py` for all three disasters.
- **Monotonicity:** J_post can never be below J_pre.
- **Reset semantics:** after `reset()` the evaluator returns exactly to the damaged state.
- **Termination:** greedy ends when J = J_pre (checked on severe flood: recovery ends at 100%).

### Comparative checks

- Priority plan beats longest-first and random at equal spending (flood: 91.5% vs 37.5% and 24.9%).
- Severity ladders are monotone (flood 11.4 / 16.8 / 22.7% of roads; storms 0 / 278 / 1,239; earthquakes 0 / 38 / 291).
- Spatial sanity: flood damage lies near the river (median ~400 m); earthquake damage tracks soil class, not distance alone.
- **Application tests:** dashboard run headlessly with Streamlit `AppTest`: no exceptions, zero input widgets, KPI values rendered.

### Defects found and fixed

| Defect | How it showed | Fix |
|--------|---------------|-----|
| Recovery sign error | Every strategy ~99% recovery | Denominator corrected to `(J_post − J_pre)` |
| False Mumbai match | Odisha flood matched "Raigarh" | Removed that name, kept "Raigad" |
| Edge key mismatch | `KeyError` toggling edges in CSR evaluator | Normalised keys with sorted-pair function |
| Over-damaging storm rule | 36% of roads blocked at Nisarga | Re-scaled tree-fall cut points |
| Earthquake cliff | M7.5 damaged every bridge and facility | Removed extra facility multiplier so soil classes differentiate |
| Plan stopped early | 600-repair cap ended plans before full recovery | Cap removed; planning ends at J_pre |
| Flood blow-up at 10 km | 33% of roads flooded on tidal lowland | Added 1 km floodplain cap |
| Download failures | 502 and SSL errors on macOS | Retry across mirrors; certifi SSL context |

**Cannot be validated:** flood level, storm tree-fall rule, quake magnitudes beyond the regional record, and all repair rates. Proper validation needs recorded flood-prone spots, past inundation maps and municipal cost data.

---

## 9. Assumptions register

All live in `config.py` or `hazards.py` and are stated in the dashboard's Method tab.

| Assumption | Value | Why it is an assumption |
|------------|-------|-------------------------|
| Flood stage above river | 3, 4, 5 m | No dataset fixes true level; Sentinel-1 and ERA5 failed |
| Floodplain width | 1,000 m | Stops unrealistic spread across coastal lowland |
| Flood damage depth | 0.5 m | Vehicle/building damage threshold |
| Storm tree-fall rule | `tree share × (V/17.5)²`, damaged at 2.0 | Shape assumed; cut points by judgement |
| Substation failure wind | 30 m/s | Assumed equipment limit |
| Quake source & magnitudes | Nearest GEM fault (77 km); M6.5, 7.0, 7.5 | No recorded damaging quake; 7.0/7.5 hypothetical |
| PGA cut points & vulnerability | 0.1/0.2/0.3/0.4 g; roads 0.7, bridges 1.3, facilities 1.0 | Fragility functions unavailable |
| Travel speed and cap | 25 km/h; 15 min | Simplified access model |
| Service weights | Equal | No evidence for other weights |
| Repair costs | Placeholder rates | No machine-readable public rate schedule |

---

## 10. Development history

| Stage | What was built | Reason |
|-------|----------------|--------|
| 1 | OSM roads + hospitals, simulated flood, greedy vs random | Prove the core idea on 5 × 5 km |
| 2 | Removed all sliders; fully automatic | Results must not depend on the user |
| 3 | Terrain-based flood from Copernicus DEM; EM-DAT linked by river name | Replace simulated flood with data |
| 4 | Facilities and bridges as repairable assets, multi-service objective | Scope is infrastructure, not only roads |
| 5 | Storm (IBTrACS, WorldCover) and earthquake (GMPE, Vs30, GEM faults) | Cover three disasters with real data |
| 6 | Scaled to 10 × 10 km; parallel runs, sampled curves, saved results, light maps | First full run 37 min → ~2 min |

---
