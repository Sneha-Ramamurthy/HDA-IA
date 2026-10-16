# GIS + Graph-Based Post-Disaster Infrastructure Recovery Prioritization

Kurla / Vidyavihar, Mumbai (10 x 10 km: about 10,000 junctions, 13,600 road segments, 480 facilities; set by DIST_M in config.py). Roads, bridges, hospitals, emergency services, power, water and transport form one network.
For flood, storm and earthquake the app removes the damaged assets, recomputes every junction's access to each service, and ranks repairs by access gained per rupee.
The dashboard has no inputs: every scenario is chosen automatically from data.

## Run
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/streamlit run app.py     # dashboard; opens in seconds once data/results.pkl exists
    .venv/bin/python build.py          # (re)build all assessments: about 2 minutes once the data is cached, parallel on all cores
    .venv/bin/python main.py           # prints the tables and writes outputs/ (uses the saved results)
The first ever run also downloads OpenStreetMap (public servers can be slow, 15+ minutes for 10 km), elevation, tree cover and soil data into data/.
Results rebuild automatically when code, settings or the road data change. The earlier 5 x 5 km caches are in data_5km_backup/ (set DIST_M = 2500 and move them back to return to that box).

## Data (all downloaded automatically except the EM-DAT files you supplied in data/)
| Data | Source | Used for |
|---|---|---|
| Roads, lanes, bridges, facilities, rivers | OpenStreetMap | the network and assets |
| Elevation (30 m) | Copernicus GLO-30 via Microsoft Planetary Computer | flood depth |
| Tree cover (10 m) | ESA WorldCover via Planetary Computer | storm tree-fall |
| Cyclone tracks | NOAA IBTrACS | real storms, Holland wind profile |
| Earthquake catalogue | USGS | strongest recorded event (context) |
| Active faults | GEM Global Active Faults | earthquake source distance |
| Soil stiffness (Vs30, 1 km) | USGS global Vs30 grid | earthquake site amplification |
| Flood / storm / earthquake history | EM-DAT (three exports: world, India, world 2015-2026) | history tab, event matching |

## Method
1. Graph of OSM roads; facilities (health, emergency, power, water, transport) snapped to junctions.
2. Hazard per disaster gives each road, bridge and facility a class 0-4; class >= 3 = damaged.
   - Flood: height above the nearest river cell, water at 3 / 4 / 5 m, flooding only where low ground connects to the river and lies within 1 km of it.
   - Storm: three real cyclones (Holland wind from IBTrACS) x tree cover along roads; substations fail at a fixed wind speed.
   - Earthquake: Raghukanth & Iyengar (2007) peninsular-India ground motion on the nearest mapped fault, M6.5 / 7.0 / 7.5, amplified by Vs30.
3. Objective J = sum over junctions and services of min(travel time to the nearest working facility, 15 min).
4. Lazy greedy: repair the asset with the best J reduction per rupee until all lost access is restored; phases at 50% / 80% / 100%. Compared with longest-first and random.

## Limitations (stated in the app)
- Flood level, storm thresholds and earthquake magnitudes above the regional record are assumptions shown as three-level ladders; no dataset available here pins them down.
- Repair costs are placeholders (config.py); replace with BMC / Maharashtra PWD rates.
- Services are equally weighted, with no dependencies between facilities.
- OSM is incomplete for utilities (15 substations, 17 water facilities mapped); coarse elevation and soil grids; fixed study area; greedy is a heuristic.
- Baseline recovery curves are sampled at 120 points; the priority plan is evaluated exactly at every repair.
