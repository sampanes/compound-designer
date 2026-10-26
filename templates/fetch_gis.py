# Download a parcel's GIS inputs (parcel + neighbors + roads + DEM + aerial + context terrain) from public
# REST services, driven by PARCEL_DIR/parcel.json. Plain Python 3 stdlib, no Blender needed.
# Usage: python fetch_gis.py PARCEL_DIR [--force] [--out DIR]
#   --force  re-download files that already exist     --out  write into DIR instead of PARCEL_DIR/gis
# Sources: any ArcGIS REST parcel layer (parcel_layer_url), Census TIGERweb local roads, USGS 3DEP elevation,
# USGS NAIPPlus imagery. All fetched in the parcel's projected CRS so nothing is reprojected later.
import json, os, sys, urllib.parse, urllib.request

TIGER_ROADS = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer/8/query"
DEM_SVC = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
NAIP_SVC = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer/exportImage"

args = sys.argv[1:]
PDIR = os.path.abspath(args[0])
FORCE = "--force" in args
OUT = os.path.abspath(args[args.index("--out") + 1]) if "--out" in args else os.path.join(PDIR, "gis")
cfg = json.load(open(os.path.join(PDIR, "parcel.json")))
WKID = cfg["epsg"].split(":")[1]
os.makedirs(OUT, exist_ok=True)


def get(url, params, dest):
    path = os.path.join(OUT, os.path.basename(dest))
    if os.path.exists(path) and not FORCE:
        print("[SKIP] %s (exists)" % path)
        return path
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "CompoundDesigner-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if data[:1] == b"{" and b'"error"' in data[:200]:
        raise SystemExit("[X] service error for %s: %s" % (dest, data[:300]))
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
    w = int(round((bbox[2] - bbox[0]) / px_m))
    h = int(round((bbox[3] - bbox[1]) / px_m))
    params = {"bbox": "%.6f,%.6f,%.6f,%.6f" % tuple(bbox), "bboxSR": WKID, "imageSR": WKID,
              "size": "%d,%d" % (w, h), "format": "tiff", "f": "image"}
    params.update(extra)
    return get(url, params, dest)


# 1) target parcel, by its ID field. Attribute lists default to the ID field only, so owner names and
#    other personal fields are never downloaded unless you list them explicitly.
ID_FIELD = cfg.get("parcel_id_field", "APN")
ppath = vector(cfg["parcel_layer_url"] + "/query", "%s='%s'" % (ID_FIELD, cfg["parcel_id"]), None,
               cfg.get("parcel_out_fields", ID_FIELD), cfg["parcel"])
ring = json.load(open(ppath))["features"][0]["geometry"]["coordinates"][0]
xs, ys = [q[0] for q in ring], [q[1] for q in ring]
pad = cfg.get("context_vector_buffer_m", 200)
vbox = (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)

# 2) neighbors + roads around it
vector(cfg["parcel_layer_url"] + "/query", "1=1", vbox, cfg.get("context_out_fields", ID_FIELD),
       cfg["context_parcels"])
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
