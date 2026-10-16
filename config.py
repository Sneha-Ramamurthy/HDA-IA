"""Settings for the flood recovery prioritization prototype."""

# Study area: Kurla / Vidyavihar (Mithi River), Mumbai. 5 km x 5 km box.
CENTER = (19.075, 72.883)  # (lat, lon)
DIST_M = 5000

# Hazard: "simulated" (distance to river) or "raster" (GeoTIFF of hazard classes 0-4)
HAZARD_MODE = "dem"  # "dem" = terrain-based flood from Copernicus DEM (automatic); "simulated" = distance bands; "raster" = your GeoTIFF
RASTER_PATH = "data/flood_hazard.tif"
DAMAGE_THRESHOLD = 3  # hazard class >= this means the road is damaged

# Scenario hazards: (distance in metres from the hazard source, hazard class 1-4), nearest band wins.
# Distance-decay rules are simplifications, not engineering models. Any disaster can instead use a real raster.
HAZARD_TYPES = ["Flood", "Earthquake", "Cyclone / storm"]
SIM_BANDS_M = [(200, 4), (400, 3), (600, 2), (900, 1)]  # flood: distance to river/canal/stream
QUAKE_BANDS_M = [(700, 4), (1200, 3), (2000, 2), (3000, 1)]  # earthquake: distance to epicentre (at magnitude 6.5)
STORM_BANDS_M = [(150, 4), (300, 3), (600, 2), (1000, 1)]  # cyclone: distance to the storm-track corridor

# Travel model
SPEED_KMH = 25
T_CAP_MIN = 15  # a node farther than this from any hospital counts as "cut off"

# Prioritization
MAX_STEPS = 600  # upper limit on planned repairs (planning also stops once all lost access is restored)
COST_AWARE = True  # rank by gain per metre of road repaired
N_RANDOM = 5
CURVE_POINTS = 120  # baseline recovery curves are evaluated at this many points (the priority plan is exact at every repair)
N_LABELS = 30  # numbered markers on the map
SEED = 42

CRS_PROJECTED = "EPSG:32643"  # UTM 43N
EMDAT_FILES = {  # all three are EM-DAT exports; india and recent are subsets of world
    "world": "data/public_emdat_2026-10-12.xlsx",  # every country, 2000-2026
    "india": "data/public_emdat_custom_request_2026-10-15_5307893b-1de5-48c4-8781-1fde55f0b2c5.xlsx",  # India only
    "recent": "data/public_emdat_custom_request_2026-10-15_7ad26aed-6e85-4145-bc62-1e8313ec887d.xlsx",  # every country, 2015-2026
}

# Terrain-based flood (Copernicus GLO-30 DEM). Fixed design assumptions, not user inputs.
DEM_PATH = "data/dem_utm.tif"
FLOOD_STAGE_M = 5.0  # primary scenario: water stands this high above the nearest river cell (assumption; see STAGE_LADDER_M)
STAGE_LADDER_M = [3.0, 4.0, 5.0]  # moderate / severe / extreme, always shown side by side; no data source pins the true stage
DEPTH_CLASSES_M = [(1.0, 4), (0.5, 3), (0.2, 2), (0.0, 1)]  # flood depth on a road (m) -> hazard class
SAMPLE_STEP_M = 15  # spacing of elevation samples along each road

# Repair cost model: lanes come from OpenStreetMap (default by road class when untagged).
# PLACEHOLDER RATES (rupee lakh per lane-km): replace with BMC / Maharashtra PWD Schedule of Rates.
RUPEE_LAKH_PER_LANE_KM = {"motorway": 20, "trunk": 20, "primary": 20, "secondary": 20, "tertiary": 18,
                          "residential": 15, "unclassified": 15, "living_street": 10, "service": 10}
DEFAULT_RATE_LAKH_PER_LANE_KM = 15
DEFAULT_LANES = {"motorway": 4, "trunk": 4, "primary": 4, "secondary": 2, "tertiary": 2}  # anything else: 1 (narrow street)
DAMAGE_FRACTION = {3: 0.25, 4: 0.5}  # share of the road needing reconstruction at each hazard class

# Infrastructure (OpenStreetMap). Each group is a service whose access is measured over the road network.
ASSET_GROUPS = {
    "health": {"amenity": ["hospital"]},
    "emergency": {"amenity": ["fire_station", "police"]},
    "power": {"power": ["substation"]},
    "water": {"man_made": ["water_works", "pumping_station", "water_tower", "wastewater_plant"]},
    "transport": {"railway": ["station", "halt"], "station": ["subway", "light_rail"], "amenity": ["bus_station"]},
}
GROUP_WEIGHT = 1.0  # every service group counts equally in the access objective
# PLACEHOLDER repair/rebuild costs per facility, rupee lakh (replace with real estimates)
FACILITY_COST_LAKH = {"hospital": 500, "fire_station": 150, "police": 100, "substation": 800, "water_works": 600,
                      "pumping_station": 200, "water_tower": 100, "wastewater_plant": 800, "station": 600,
                      "halt": 200, "subway": 800, "light_rail": 800, "bus_station": 100}
DEFAULT_FACILITY_COST_LAKH = 300
BRIDGE_COST_FACTOR = 5  # placeholder: a bridge costs this many times a plain road of the same length and lanes
IBTRACS_CSV = "data/ibtracs_NI.csv"
IBTRACS_URL = "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.NI.list.v04r01.csv"
GEM_FAULTS = "data/gem_faults.geojson"
GEM_FAULTS_URL = "https://raw.githubusercontent.com/GEMScienceTools/gem-global-active-faults/master/geojson/gem_active_faults_harmonized.geojson"
VS30_GRID_URL = "https://apps.usgs.gov/shakemap_geodata/vs30/global_vs30.grd"
QUAKE_LADDER_MAG = [6.5, 7.0, 7.5]  # 6.5 = strongest earthquake of record within 500 km (USGS); 7.0 and 7.5 are hypothetical
STORM_LADDER_N = 3  # the three real cyclones with the strongest estimated wind at the study area
STORM_WIND_DAMAGE_MS = 17.5  # tropical-storm-force wind: trees start to fall onto roads
POWER_WIND_FAIL_MS = 30.0  # assumed wind speed at which substations/overhead supply fail

# Flood extent: water spreads at most this far from the nearest river/canal/stream (floodplain width assumption).
FLOODPLAIN_MAX_M = 1000
RESULT_CACHE = "data/results.pkl"  # finished assessments, so the dashboard opens instantly
