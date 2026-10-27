# Preflight for the pipeline. Finds Blender and probes it once headless (version, numpy, BlenderGIS, EEVEE,
# FreeImage DLL), then validates a parcel folder (parcel.json, GIS inputs) and design JSONs, so every
# missing piece shows up in one run before the slow steps. Plain Python 3 stdlib; never imports bpy.
# Usage: python doctor.py [PARCEL_DIR] [DESIGN.json ...]
#   No arguments: environment only. With PARCEL_DIR and no designs, every design_*.json in it is checked.
# Blender is BLENDER if set, else the default 5.1 install, else the newest "Blender Foundation\Blender *"
# folder, else `blender` on PATH. Prints [CHECK] OK/FAIL lines and exits 1 if any check fails.
import glob, json, os, re, shutil, subprocess, sys

USAGE = "usage: python doctor.py [PARCEL_DIR] [DESIGN.json ...]"
failed = []

def check(name, ok, detail=""):
    print("[CHECK] %-4s %s %s" % ("OK" if ok else "FAIL", name, detail))
    if not ok:
        failed.append(name)

def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

args = sys.argv[1:]
if any(a in ("-h", "--help") for a in args):
    print(USAGE, file=sys.stderr)
    sys.exit(2)
PDIR, designs = None, []
for a in args:
    if a.lower().endswith(".json"):
        designs.append(a)
    elif PDIR is None:
        PDIR = a
    else:
        print(USAGE, file=sys.stderr)
        sys.exit(2)

# --- A. environment ---------------------------------------------------------------------------
check("python", sys.version_info >= (3, 8), "%d.%d.%d" % sys.version_info[:3])

def find_blender():
    exe = os.environ.get("BLENDER")
    if exe:
        return exe, "from BLENDER"
    if sys.platform == "win32":
        default = r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
        if os.path.isfile(default):
            return default, "default 5.1 install"
        found = glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe")
        if found:
            ver = lambda f: tuple(int(x) for x in re.findall(r"\d+", os.path.basename(os.path.dirname(f))))
            return max(found, key=ver), "newest install found"
        return None, "no Blender under C:\\Program Files\\Blender Foundation; set BLENDER=<path to blender.exe>"
    exe = shutil.which("blender")
    return exe, "on PATH" if exe else "no blender on PATH; set BLENDER=<path to blender>"

exe, how = find_blender()
if exe and not os.path.isfile(exe):
    check("blender executable", False, "%s (%s) does not exist" % (exe, how))
    exe = None
else:
    check("blender executable", bool(exe), "%s (%s)" % (exe, how) if exe else how)

# Runs inside Blender. Every probe guards itself, the text avoids characters cmd.exe treats specially, and
# exec(repr(...)) turns it into the single line Blender receives on its command line.
PROBE = '''
import json, os
r = {}
try:
    import bpy
    r["version"] = bpy.app.version_string
except Exception:
    r["version"] = None
try:
    import numpy
    r["numpy"] = True
except Exception:
    r["numpy"] = False
try:
    import addon_utils
    r["gis_addons"] = sorted(m.__name__ for m in addon_utils.modules() if "gis" in m.__name__.lower())
except Exception:
    r["gis_addons"] = []
try:
    import addon_utils
    r["blendergis"] = addon_utils.enable("BlenderGIS", default_set=True) is not None
except Exception:
    r["blendergis"] = False
try:
    r["engines"] = list(bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys())
except Exception:
    r["engines"] = []
try:
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "imageio") if os.name == "nt" else os.path.expanduser("~/.imageio")
    r["freeimage"] = any("freeimage" in f.lower() for _, _, fs in os.walk(base) for f in fs)
except Exception:
    r["freeimage"] = False
print("DOCTOR " + json.dumps(r))
'''
EXPR = "exec(%r)" % PROBE
compile(PROBE, "<probe>", "exec")
compile(EXPR, "<expr>", "exec")

def probe_blender(exe):
    try:
        out = subprocess.run([exe, "-b", "--factory-startup", "-noaudio", "--python-expr", EXPR],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        text = out.stdout + out.stderr
    except subprocess.TimeoutExpired:
        return None, "Blender did not finish within 120 s"
    except OSError as e:
        return None, "could not run %s: %s" % (exe, e)
    for line in text.splitlines():
        if line.startswith("DOCTOR "):
            try:
                return json.loads(line[7:]), ""
            except ValueError:
                break
    tail = [l for l in text.splitlines() if l.strip()][-5:]
    return None, "no DOCTOR line in Blender's output; last lines: " + " | ".join(tail)

if exe:
    info, err = probe_blender(exe)
    if info is None:
        check("blender probe", False, err)
    else:
        check("blender version", bool(info.get("version")), info.get("version") or "bpy did not import")
        check("numpy in blender", bool(info.get("numpy")), "" if info.get("numpy") else "Blender's bundled numpy is missing")
        gis = info.get("gis_addons") or []
        check("BlenderGIS add-on", bool(info.get("blendergis")), "enabled" if info.get("blendergis") else
              "not enabled; the add-on folder must be named BlenderGIS (GIS-like add-ons seen: %s)" % (gis or "none"))
        eng = info.get("engines") or []
        ee = next((e for e in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT") if e in eng), None)
        check("EEVEE render engine", ee is not None, ee or "neither BLENDER_EEVEE nor BLENDER_EEVEE_NEXT in %s" % eng)
        check("FreeImage DLL", True, "present under imageio" if info.get("freeimage") else
              "not downloaded yet: BlenderGIS fetches it on the first raster read, which needs internet")

# --- B. parcel folder -------------------------------------------------------------------------
cfg = None
if PDIR and not os.path.isdir(PDIR):
    check("parcel folder", False, "%s is not a directory" % PDIR)
    PDIR = None
if PDIR:
    pj = os.path.join(PDIR, "parcel.json")
    try:
        cfg = json.load(open(pj, encoding="utf-8"))
        check("parcel.json", isinstance(cfg, dict), pj if isinstance(cfg, dict) else "%s is not a JSON object" % pj)
        cfg = cfg if isinstance(cfg, dict) else None
    except (OSError, ValueError) as e:
        check("parcel.json", False, "%s: %s" % (pj, e))

def is_bbox(b):
    return isinstance(b, list) and len(b) == 4 and all(num(x) for x in b) and b[0] < b[2] and b[1] < b[3]

def whole_px(b, px):
    w, h = (b[2] - b[0]) / px, (b[3] - b[1]) / px
    return abs(w - round(w)) < 1e-6 and abs(h - round(h)) < 1e-6

if cfg is not None:
    bad = []
    if not re.search(r"/(MapServer|FeatureServer)/\d+", str(cfg.get("parcel_layer_url", ""))):
        bad.append("parcel_layer_url must contain /MapServer/<n> or /FeatureServer/<n>")
    if not str(cfg.get("parcel_id", "")).strip():
        bad.append("parcel_id is empty")
    if "parcel_id_field" in cfg and not str(cfg["parcel_id_field"]).strip():
        bad.append("parcel_id_field is empty")
    if "epsg" in cfg and not re.fullmatch(r"EPSG:\d+", str(cfg["epsg"])):
        bad.append("epsg must look like EPSG:26913")
    origin = cfg.get("local_origin_xy")
    if origin is not None and not (isinstance(origin, list) and len(origin) == 2 and all(num(x) for x in origin)):
        bad.append("local_origin_xy must be [x, y]")
        origin = None
    boxes = {}
    for key, pxs in (("raster_bbox", (("dem_px_m", 1.0), ("aerial_px_m", 0.25))),
                     ("context_bbox", (("context_dem_px_m", 10.0), ("context_aerial_px_m", 4.0)))):
        b = cfg.get(key)
        if b is None:
            continue
        if not is_bbox(b):
            bad.append("%s must be [xmin, ymin, xmax, ymax] with min < max" % key)
            continue
        boxes[key] = b
        for pk, default in pxs:
            px = cfg.get(pk, default)
            if not (num(px) and px > 0):
                bad.append("%s must be a positive number" % pk)
            elif not whole_px(b, px):
                bad.append("%s (%.3f x %.3f m) is not a whole number of %s=%g m pixels" % (key, b[2] - b[0], b[3] - b[1], pk, px))
    if "raster_bbox" in boxes and "context_bbox" in boxes:
        r, c = boxes["raster_bbox"], boxes["context_bbox"]
        if not (c[0] <= r[0] and c[1] <= r[1] and c[2] >= r[2] and c[3] >= r[3]):
            bad.append("context_bbox does not contain raster_bbox")
    if origin and "raster_bbox" in boxes:
        r = boxes["raster_bbox"]
        dx, dy = max(r[0] - origin[0], 0, origin[0] - r[2]), max(r[1] - origin[1], 0, origin[1] - r[3])
        if (dx * dx + dy * dy) ** 0.5 > 5000:
            bad.append("local_origin_xy is more than 5 km from raster_bbox")
    missing = [k for k in ("epsg", "local_origin_xy", "raster_bbox", "context_bbox") if k not in cfg]
    check("parcel.json values", not bad, "; ".join(bad) or ("fetch_gis.py will derive %s" % ", ".join(missing) if missing else "complete"))

    DEFAULTS = {"dem": "gis/terrain_dem.tif", "aerial": "gis/aerial_naip.tif", "parcel": "gis/parcel_boundary.geojson",
                "context_parcels": "gis/context_parcels.geojson", "roads": "gis/roads.geojson"}
    paths = {k: cfg.get(k, d) for k, d in DEFAULTS.items()}
    paths.update({k: cfg[k] for k in ("context_dem", "context_aerial") if cfg.get(k)})
    missing = [k for k, rel in paths.items() if not os.path.isfile(os.path.join(PDIR, str(rel)))]
    check("gis inputs", True, "all %d present" % len(paths) if not missing else "missing %s: run fetch_gis.py" % ", ".join(missing))
    ppath = os.path.join(PDIR, str(paths["parcel"]))
    if os.path.isfile(ppath):
        try:
            feats = json.load(open(ppath, encoding="utf-8")).get("features") or []
            geom = (feats[0].get("geometry") or {}) if feats else {}
            gtype, coords = geom.get("type"), geom.get("coordinates") or []
            ring = coords[0] if gtype == "Polygon" and coords else coords[0][0] if gtype == "MultiPolygon" and coords and coords[0] else []
            x, y = (ring[0][0], ring[0][1]) if ring else (0, 0)
            prob = ("no features" if not feats else
                    "geometry is %s, expected Polygon or MultiPolygon" % gtype if gtype not in ("Polygon", "MultiPolygon") else
                    "coordinates look like lon/lat (%s, %s): fetch with outSR set to the projected CRS" % (x, y) if max(abs(x), abs(y)) <= 1000 else "")
            check("parcel geojson", not prob, prob or "%s, %d feature(s), projected coordinates" % (gtype, len(feats)))
        except (OSError, ValueError, AttributeError, IndexError, KeyError, TypeError) as e:
            check("parcel geojson", False, "%s: %r" % (ppath, e))
    blend = os.path.join(PDIR, "blender", "site_master.blend")
    check("site_master.blend", True, "present" if os.path.isfile(blend) else "not built yet: run build_site")

# --- C. design JSONs --------------------------------------------------------------------------
if PDIR and not designs:
    designs = sorted(glob.glob(os.path.join(PDIR, "design_*.json")))
    if not designs:
        check("designs", True, "no design_*.json in %s" % PDIR)
SAFE = re.compile(r"[A-Za-z0-9_-]+")
MODES = ("balanced", "uphill")
NEED = {"house": ("w_ft", "d_ft", "wall_h", "roof_pitch"), "terrace": ("w_m", "d_m")}
for dpath in designs:
    name = "design %s" % os.path.basename(dpath)
    try:
        d = json.load(open(dpath, encoding="utf-8"))
    except (OSError, ValueError) as e:
        check(name, False, str(e))
        continue
    bad = []
    if not isinstance(d, dict):
        bad.append("not a JSON object")
        d = {}
    if not SAFE.fullmatch(str(d.get("name", ""))):
        bad.append("name must be letters, digits, _ or - (it names the output files)")
    frame = d.get("frame")
    if not (isinstance(frame, dict) and num(frame.get("u_bearing_deg"))):
        bad.append("frame.u_bearing_deg must be a number")
    if d.get("floor_mode") not in MODES:
        bad.append("floor_mode must be balanced or uphill")
    els = d.get("elements")
    if not (isinstance(els, list) and els):
        bad.append("elements must be a non-empty list")
        els = []
    seen = set()
    for i, el in enumerate(els):
        if not isinstance(el, dict):
            bad.append("element %d is not an object" % i)
            continue
        eid = str(el.get("id", ""))
        tag = eid or "element %d" % i
        if not SAFE.fullmatch(eid):
            bad.append("%s: id must be letters, digits, _ or -" % tag)
        elif eid in seen:
            bad.append("%s: duplicate id" % tag)
        seen.add(eid)
        kind = el.get("kind")
        if kind not in NEED:
            bad.append("%s: kind must be house or terrace" % tag)
        for k in ("u", "v") + NEED.get(kind, ()):
            if not num(el.get(k)):
                bad.append("%s: %s must be a number" % (tag, k))
        if "rot_deg" in el and not num(el["rot_deg"]):
            bad.append("%s: rot_deg must be a number" % tag)
        if "floor_mode" in el and el["floor_mode"] not in MODES:
            bad.append("%s: floor_mode must be balanced or uphill" % tag)
    check(name, not bad, "; ".join(bad) if bad else "%s, %d element(s)" % (d.get("name"), len(els)))

print("[DONE] %d check(s) failed: %s" % (len(failed), failed) if failed else "[DONE] all checks OK")
sys.exit(1 if failed else 0)
