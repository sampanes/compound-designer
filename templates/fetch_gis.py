# Download a parcel's GIS inputs (parcel + neighbors + roads + DEM + aerial + context terrain) from public
# REST services, driven by PARCEL_DIR/parcel.json. Plain Python 3 stdlib, no Blender needed.
# Usage: python fetch_gis.py PARCEL_DIR [--force] [--out DIR]
#   --force  re-download files that already exist
#   --out    resolve the output paths in parcel.json under DIR instead of PARCEL_DIR (a side copy; the
#            Blender steps always read from PARCEL_DIR)
# parcel.json needs only parcel_layer_url, parcel_id_field and parcel_id. Whatever else is missing is derived
# from the parcel itself and written back into parcel.json, so the Blender steps read the same values:
#   epsg             NAD83 / UTM zone that contains the parcel (EPSG:269xx)
#   local_origin_xy  parcel center rounded to 100 m
#   raster_bbox      parcel plus raster_pad_m (default 150 m), grown to whole DEM and aerial pixels
#   context_bbox     local_origin_xy +/- context_half_m (default 4000 m), grown to whole context pixels
#   dem, aerial, parcel, context_parcels, roads, context_dem, context_aerial   output paths under gis/
# Set context_dem and context_aerial to null to skip the context terrain. Each file lands at the path
# parcel.json names for it, relative to PARCEL_DIR.
# Sources: any ArcGIS REST parcel layer (parcel_layer_url), Census TIGERweb local roads, USGS 3DEP elevation,
# USGS NAIPPlus imagery. All fetched in the parcel's projected CRS so nothing is reprojected later.
import json, math, os, sys, urllib.parse, urllib.request
from functools import reduce

TIGER_ROADS = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer/8/query"
DEM_SVC = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
NAIP_SVC = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer/exportImage"
USAGE = "usage: python fetch_gis.py PARCEL_DIR [--force] [--out DIR]"
PATH_DEFAULTS = {"dem": "gis/terrain_dem.tif", "aerial": "gis/aerial_naip.tif",
                 "context_dem": "gis/context_dem_10m.tif", "context_aerial": "gis/context_aerial_naip_4m.tif",
                 "parcel": "gis/parcel_boundary.geojson", "context_parcels": "gis/context_parcels.geojson",
                 "roads": "gis/roads.geojson"}
KEY_ORDER = ["name", "epsg", "local_origin_xy", "raster_bbox", "context_bbox",
             "parcel_layer_url", "parcel_id_field", "parcel_id"]

args = sys.argv[1:]
if not args or args[0].startswith("-"):  # no parcel dir, -h, --help, or flags before the parcel dir
    print(USAGE, file=sys.stderr)
    sys.exit(2)
PDIR = os.path.abspath(args[0])
FORCE = "--force" in args
OUT = os.path.abspath(args[args.index("--out") + 1]) if "--out" in args else PDIR
CFG_PATH = os.path.join(PDIR, "parcel.json")
with open(CFG_PATH) as f:
    cfg = json.load(f)
derived = {}


def fetch(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "CompoundDesigner-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if data[:1] == b"{" and b'"error"' in data[:200]:
        raise SystemExit("[X] service error from %s: %s" % (url, data[:300]))
    return data


def get(url, params, dest):
    path = os.path.normpath(os.path.join(OUT, dest))
    if os.path.exists(path) and not FORCE:
        print("[SKIP] %s (exists)" % path)
        return path
    data = fetch(url, params)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    print("[OK] %s (%d bytes)" % (path, len(data)))
    return path


def vector(url, where, bbox, fields, dest):
    params = {"where": where, "outFields": fields, "outSR": WKID, "f": "geojson"}
    if bbox:
        params.update(geometry="%f,%f,%f,%f" % tuple(bbox), geometryType="esriGeometryEnvelope",
                      inSR=WKID, spatialRel="esriSpatialRelIntersects")
    return get(url, params, dest)


def raster(url, bbox, px_m, dest, extra):
    w = (bbox[2] - bbox[0]) / px_m
    h = (bbox[3] - bbox[1]) / px_m
    if abs(w - round(w)) > 1e-6 or abs(h - round(h)) > 1e-6:
        # otherwise the service stretches pixels to fit and the grid no longer lands on whole pixels
        raise SystemExit("[X] %s: bbox %.2f x %.2f m is not a whole number of %g m pixels; widen the bbox"
                         % (dest, bbox[2] - bbox[0], bbox[3] - bbox[1], px_m))
    w, h = int(round(w)), int(round(h))
    params = {"bbox": "%.6f,%.6f,%.6f,%.6f" % tuple(bbox), "bboxSR": WKID, "imageSR": WKID,
              "size": "%d,%d" % (w, h), "format": "tiff", "f": "image"}
    params.update(extra)
    return get(url, params, dest)


def outer_ring(geom):
    # Outer ring of the largest polygon: a parcel split by a road arrives as a MultiPolygon.
    if geom["type"] == "Polygon":
        polys = [geom["coordinates"]]
    elif geom["type"] == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        raise SystemExit("[X] parcel geometry is %s, expected Polygon or MultiPolygon" % geom["type"])
    area = lambda ring: abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))) / 2
    return max((poly[0] for poly in polys), key=area)


def grid_step(*px):
    # Smallest length that is a whole number of every pixel size: 1 and 0.25 m -> 1 m, 10 and 4 m -> 20 m.
    ints = [int(round(p * 1000)) for p in px]  # pixel sizes are whole millimeters
    return reduce(lambda a, b: a * b // math.gcd(a, b), ints) / 1000.0


def snap_out(bbox, step):
    # Grow a bbox outward to multiples of step, so every raster edge lands on a whole pixel.
    lo = lambda v: math.floor(v / step + 1e-9) * step
    hi = lambda v: math.ceil(v / step - 1e-9) * step
    return [lo(bbox[0]), lo(bbox[1]), hi(bbox[2]), hi(bbox[3])]


def derive(key, value):
    cfg[key] = derived[key] = value
    print("[DERIVED] %s = %s" % (key, json.dumps(value)))


def no_match():
    return SystemExit("[X] no parcel matched %s on %s; check parcel_id_field / parcel_id, then re-run with --force"
                      % (where, cfg["parcel_layer_url"]))


# 0) complete parcel.json: output paths, then the CRS from the parcel's own longitude
ID_FIELD = cfg.get("parcel_id_field", "APN")
where = "%s='%s'" % (ID_FIELD, cfg["parcel_id"])
QUERY = cfg["parcel_layer_url"] + "/query"
for k, v in PATH_DEFAULTS.items():
    if k not in cfg:  # an explicit null keeps the optional context rasters off
        derive(k, v)
if "epsg" not in cfg:
    ll = json.loads(fetch(QUERY, {"where": where, "outFields": ID_FIELD, "outSR": 4326, "f": "geojson"}))
    if not ll["features"]:
        raise no_match()
    r = outer_ring(ll["features"][0]["geometry"])
    lon = (min(q[0] for q in r) + max(q[0] for q in r)) / 2
    lat = (min(q[1] for q in r) + max(q[1] for q in r)) / 2
    zone = int((lon + 180) // 6) + 1
    if not (lat > 0 and 1 <= zone <= 23):
        raise SystemExit("[X] parcel at lon %.4f lat %.4f is outside NAD83 / UTM zones 1N-23N; set epsg by hand"
                         % (lon, lat))
    derive("epsg", "EPSG:%d" % (26900 + zone))
WKID = cfg["epsg"].split(":")[1]

# 1) target parcel, by its ID field. Attribute lists default to the ID field only, so owner names and
#    other personal fields are never downloaded unless you list them explicitly.
ppath = vector(QUERY, where, None, cfg.get("parcel_out_fields", ID_FIELD), cfg["parcel"])
with open(ppath) as f:
    feats = json.load(f)["features"]
if not feats:
    raise no_match()
ring = outer_ring(feats[0]["geometry"])
xs, ys = [q[0] for q in ring], [q[1] for q in ring]
pad = cfg.get("context_vector_buffer_m", 200)
vbox = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)

# origin and bboxes from the parcel outline, then write the completed config back for the Blender steps
if "local_origin_xy" not in cfg:
    derive("local_origin_xy", [round((min(xs) + max(xs)) / 200) * 100.0, round((min(ys) + max(ys)) / 200) * 100.0])
if "raster_bbox" not in cfg:
    rp = cfg.get("raster_pad_m", 150)
    derive("raster_bbox", snap_out([min(xs) - rp, min(ys) - rp, max(xs) + rp, max(ys) + rp],
                                   grid_step(cfg.get("dem_px_m", 1.0), cfg.get("aerial_px_m", 0.25))))
if "context_bbox" not in cfg and (cfg.get("context_dem") or cfg.get("context_aerial")):
    (ox, oy), half = cfg["local_origin_xy"], cfg.get("context_half_m", 4000)
    derive("context_bbox", snap_out([ox - half, oy - half, ox + half, oy + half],
                                    grid_step(cfg.get("context_dem_px_m", 10.0), cfg.get("context_aerial_px_m", 4.0))))
if derived:
    ordered = {k: cfg[k] for k in KEY_ORDER if k in cfg}
    ordered.update((k, v) for k, v in cfg.items() if k not in ordered)
    with open(CFG_PATH, "w") as f:
        json.dump(ordered, f, indent=2)
        f.write("\n")
    print("[WRITE] %s (%d derived key(s))" % (CFG_PATH, len(derived)))

# 2) neighbors + roads around it
vector(QUERY, "1=1", vbox, cfg.get("context_out_fields", ID_FIELD), cfg["context_parcels"])
vector(TIGER_ROADS, "1=1", vbox, "NAME,MTFCC", cfg["roads"])

# 3) rasters: detail DEM (1 m) + aerial (0.25 m) over raster_bbox; context DEM (10 m) + aerial (4 m)
dem = {"pixelType": "F32", "noData": "-9999", "interpolation": "RSP_BilinearInterpolation"}
raster(DEM_SVC, cfg["raster_bbox"], cfg.get("dem_px_m", 1.0), cfg["dem"], dem)
raster(NAIP_SVC, cfg["raster_bbox"], cfg.get("aerial_px_m", 0.25), cfg["aerial"], {})
if cfg.get("context_dem"):
    raster(DEM_SVC, cfg["context_bbox"], cfg.get("context_dem_px_m", 10.0), cfg["context_dem"], dem)
if cfg.get("context_aerial"):
    raster(NAIP_SVC, cfg["context_bbox"], cfg.get("context_aerial_px_m", 4.0), cfg["context_aerial"], {})
print("[DONE] %s" % OUT)
