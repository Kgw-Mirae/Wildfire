import geopandas as gpd
from shapely.ops import unary_union
from pathlib import Path
import sys

# ===============================
# 0. Find GeoJSON file in ../data/Geojson
#    -> use the last fireline inside the configured forecast window
# ===============================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from data.Domain.domain_utils import load_domain_config
from fireline_schedule import build_fireline_schedule

geojson_dir = PROJECT_DIR / "data" / "Geojson"

cfg = load_domain_config(PROJECT_DIR)
schedule = build_fireline_schedule(geojson_dir, cfg)
geojson_path = schedule.entries[-1].path
print(f"Using GeoJSON file: {geojson_path}")
print(
    "[INFO] Forecast window: "
    f"base={schedule.forecast_base_time:%Y-%m-%d %H:%M}, "
    f"end={schedule.forecast_end_time:%Y-%m-%d %H:%M}, "
    f"domain_fireline={schedule.last_used_fireline_time:%Y-%m-%d %H:%M}"
)

# ===============================
# 0-1. Extract all event hours from fireline times
#    example:
#    202305031400_202305031450.geojson
# -> 2023.05.03.14
# ===============================
event_hours = sorted(
    {entry.fireline_time.replace(minute=0, second=0, microsecond=0) for entry in schedule.entries}
)
date_lines = [event_hour.strftime("%Y.%m.%d.%H") for event_hour in event_hours]

date_out_path = PROJECT_DIR / "data" / "Event" / "date.txt"
date_out_path.parent.mkdir(parents=True, exist_ok=True)

with open(date_out_path, "w", encoding="utf-8") as f:
    for date_line in date_lines:
        f.write(date_line + "\n")

# ===============================
# 1. Read GeoJSON
# ===============================
gdf = gpd.read_file(geojson_path)

if gdf.crs is None:
    raise ValueError("CRS is missing (EPSG:5179 expected).")

if gdf.empty:
    raise ValueError("GeoJSON contains no geometries.")

# ===============================
# 2. Fireline -> Enclosing polygon
# ===============================
merged_lines = unary_union(gdf.geometry)

fire_polygon = merged_lines.buffer(1.0)   # unit: meter (UTM-K)

# ===============================
# 3. Polygon centroid
# ===============================
centroid_utm = fire_polygon.centroid
x_utm, y_utm = centroid_utm.x, centroid_utm.y

# ===============================
# 4. Save UTM-K location
#    format:
#    953421.23
#    1945321.87
# ===============================
out_path = PROJECT_DIR / "data" / "Event" / "location.txt"
out_path.parent.mkdir(parents=True, exist_ok=True)

with open(out_path, "w", encoding="utf-8") as f:
    f.write(f"{x_utm:.2f}\n")
    f.write(f"{y_utm:.2f}\n")

# ===============================
# 5. Console output
# ===============================
print("===============================================")
print("Event information")
print("===============================================")
print(f"GeoJSON file : {geojson_path.name}")
print("Date saved   :")
for date_line in date_lines:
    print(f"  - {date_line}")
print(f"UTM-K X      : {x_utm:.2f} m")
print(f"UTM-K Y      : {y_utm:.2f} m")
print(f"Saved date   : {date_out_path}")
print(f"Saved coord  : {out_path}")
print("===============================================")
