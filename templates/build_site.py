# Build a site_master.blend for one parcel folder (terrain + aerial + parcel lines + roads + cameras).
# Usage:
#   blender -b --factory-startup -noaudio --python build_site.py -- PARCEL_DIR [--no-render]
# PARCEL_DIR holds parcel.json (CRS, local origin, raster bbox, file paths). Everything in Blender is
# in real meters relative to local_origin_xy; Z is absolute elevation (NAVD88 m for 3DEP).
# Exits 1 if any [CHECK] fails.
import sys, os, json, math
import bpy, bmesh, addon_utils
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
PDIR = os.path.abspath(argv[0])
RENDER = "--no-render" not in argv
cfg = json.load(open(os.path.join(PDIR, "parcel.json")))
OX, OY = cfg["local_origin_xy"]
BX0, BY0, BX1, BY1 = cfg["raster_bbox"]
PX = float(cfg.get("dem_px_m", 1.0))  # DEM pixel size in meters (fetch_gis.py requests this size)
failed = []

def check(name, ok, detail=""):
    print("[CHECK] %-4s %s %s" % ("OK" if ok else "FAIL", name, detail))
    if not ok:
        failed.append(name)

def p(rel):
    return os.path.join(PDIR, rel)

for sub in ("blender", "exports", "renders"):
    os.makedirs(p(sub), exist_ok=True)

# --- fresh scene, BlenderGIS georef ---------------------------------------------------------
for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)
addon_utils.enable("BlenderGIS", default_set=True)
from BlenderGIS.geoscene import GeoScene
from BlenderGIS.core.georaster import GeoRaster
scn = bpy.context.scene
scn.unit_settings.system = "METRIC"
geoscn = GeoScene(scn)
geoscn.crs = cfg["epsg"]
geoscn.setOriginPrj(OX, OY, synch=False)
check("scene georef", geoscn.isGeoref, "%s origin=(%.1f, %.1f)" % (geoscn.crs, OX, OY))

# --- input rasters: georeferenced extent and pixel size must match parcel.json ----------------
def raster_matches(name, path, px):
    r = GeoRaster(path)
    bb = r.bbox
    tol = px / 2
    ok = (abs(bb.xmin - BX0) < tol and abs(bb.xmax - BX1) < tol and
          abs(bb.ymin - BY0) < tol and abs(bb.ymax - BY1) < tol and abs(abs(r.pxSize.x) - px) < 1e-3 * px)
    check(name + " georef matches raster_bbox", ok, "bbox %.2f %.2f %.2f %.2f px %.3f m, %dx%d" % (
        bb.xmin, bb.ymin, bb.xmax, bb.ymax, abs(r.pxSize.x), r.size.x, r.size.y))
    return r

dem_r = raster_matches("DEM", p(cfg["dem"]), PX)
raster_matches("aerial", p(cfg["aerial"]), float(cfg.get("aerial_px_m", 0.25)))

# --- terrain: DEM as real mesh (1 vertex per DEM pixel center) -----------------------------
bpy.ops.importgis.georaster(filepath=p(cfg["dem"]), importMode="DEM_RAW", step=1, buildFaces=True)
terrain = bpy.context.selected_objects[0]
terrain.name = "terrain"
me = terrain.data
co = np.empty(len(me.vertices) * 3)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
check("terrain origin offset", abs(geoscn.crsx - OX) < 1e-6 and abs(geoscn.crsy - OY) < 1e-6)
# vertices sit at pixel centers: half a pixel in from each edge of raster_bbox, one per DEM pixel
NX, NY = int(round((BX1 - BX0) / PX)), int(round((BY1 - BY0) / PX))
edges_ok = (abs(co[:, 0].min() + OX - (BX0 + PX / 2)) < 0.01 and abs(co[:, 0].max() + OX - (BX1 - PX / 2)) < 0.01 and
            abs(co[:, 1].min() + OY - (BY0 + PX / 2)) < 0.01 and abs(co[:, 1].max() + OY - (BY1 - PX / 2)) < 0.01)
check("terrain extent (4 edges, %dx%d verts)" % (NX, NY), edges_ok and len(co) == NX * NY,
      "x %.2f..%.2f y %.2f..%.2f z %.2f..%.2f (local)" % (co[:, 0].min(), co[:, 0].max(),
                                                         co[:, 1].min(), co[:, 1].max(),
                                                         co[:, 2].min(), co[:, 2].max()))
for poly in me.polygons:
    poly.use_smooth = True

# aerial as UVs computed from world XY (aerial was exported over the same bbox as the DEM)
uv = me.uv_layers.new(name="aerial")
loop_v = np.empty(len(me.loops), dtype=np.int64)
me.loops.foreach_get("vertex_index", loop_v)
u = (co[loop_v, 0] + OX - BX0) / (BX1 - BX0)
v = (co[loop_v, 1] + OY - BY0) / (BY1 - BY0)
uv.data.foreach_set("uv", np.column_stack([u, v]).ravel())

def make_mat(name, color, image=None, emit=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.diffuse_color = color
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = 0.9
    if emit:
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = emit
    if image:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(image)
        tex.extension = "EXTEND"
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return m

terrain.data.materials.append(make_mat("aerial_naip", (0.4, 0.4, 0.35, 1), image=p(cfg["aerial"])))

# --- vector overlays draped on terrain -----------------------------------------------------
bvh = BVHTree.FromObject(terrain, bpy.context.evaluated_depsgraph_get())
ZTOP = co[:, 2].max() + 100

def drape(xy, lift):
    hit = bvh.ray_cast(Vector((xy[0], xy[1], ZTOP)), Vector((0, 0, -1)))
    return Vector((xy[0], xy[1], (hit[0].z if hit[0] else co[:, 2].min()) + lift))

def densify(pts, step=1.0):
    out = []
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(math.dist(a, b) / step))
        out += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]
    out.append(pts[-1])
    return out

def to_local(pts):
    return [(x - OX, y - OY) for x, y in pts]

def curve_obj(name, lines, width, mat, lift, closed=False, coll=None):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = width / 2
    cu.bevel_resolution = 1
    for pts in lines:
        pts = densify(to_local(pts))
        if closed and pts[0] == pts[-1]:
            pts = pts[:-1]
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for pt, xy in zip(sp.points, pts):
            pt.co = (*drape(xy, lift), 1)
        sp.use_cyclic_u = closed
    ob = bpy.data.objects.new(name, cu)
    (coll or scn.collection).objects.link(ob)
    ob.data.materials.append(mat)
    return ob

def rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [poly[0] for poly in geom["coordinates"]]
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return geom["coordinates"]
    return []

def new_coll(name):
    c = bpy.data.collections.new(name)
    scn.collection.children.link(c)
    return c

site = new_coll("site_gis")
for o in (terrain,):
    scn.collection.objects.unlink(o)
    site.objects.link(o)

target = json.load(open(p(cfg["parcel"])))["features"][0]
tring = rings(target["geometry"])[0]
parcel_ob = curve_obj("parcel_boundary", [tring], 0.30, make_mat("parcel_red", (0.9, 0.05, 0.02, 1), emit=2.0),
                      0.3, closed=True, coll=site)

# The boundary curve actually built in Blender vs the source GeoJSON: same area, and its centroid
# plus the local origin lands on the source centroid (catches origin/offset mistakes). Should match to mm.
def area_centroid(pts):
    pts = list(pts) + [pts[0]] if pts[0] != pts[-1] else list(pts)
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    return abs(a) / 2, cx / (3 * a), cy / (3 * a)

loc = to_local(tring)
curve_xy = [(pt.co.x, pt.co.y) for pt in parcel_ob.data.splines[0].points]
area_bl, ccx_bl, ccy_bl = area_centroid(curve_xy)
# source centroid computed near a vertex of the ring itself (raw UTM-sized products lose precision)
X0, Y0 = tring[0][0], tring[0][1]
area_src, ccx_src, ccy_src = area_centroid([(q[0] - X0, q[1] - Y0) for q in tring])
off = math.hypot(ccx_bl + OX - (ccx_src + X0), ccy_bl + OY - (ccy_src + Y0))
check("parcel area matches source", abs(area_bl - area_src) < 0.01,
      "%.1f m2 = %.4f acres" % (area_bl, area_bl / 4046.8564))
check("parcel position matches source", off < 0.01, "centroid offset %.4f m" % off)

ctx = json.load(open(p(cfg["context_parcels"])))
ID_FIELD = cfg.get("parcel_id_field", "APN")
others = [r for f in ctx["features"] if str(f["properties"].get(ID_FIELD)) != str(cfg["parcel_id"])
          for r in rings(f["geometry"])]
curve_obj("neighbor_parcels", others, 0.12, make_mat("neighbor_white", (0.85, 0.85, 0.8, 1), emit=0.5), 0.2, coll=site)

roads = json.load(open(p(cfg["roads"])))
road_lines = [r for f in roads["features"] for r in rings(f["geometry"])]
curve_obj("road_centerlines", road_lines, 0.4, make_mat("road_yellow", (0.95, 0.75, 0.1, 1), emit=1.0), 0.25, coll=site)

# --- optional wide context terrain (low-res, for horizons/views) ----------------------------
# Lowered 1.5 m and holed under the detailed DEM (minus a 15 m overlap) so the two never z-fight.
if cfg.get("context_dem"):
    bpy.ops.importgis.georaster(filepath=p(cfg["context_dem"]), importMode="DEM_RAW", step=1, buildFaces=True)
    ctx_t = bpy.context.selected_objects[0]
    ctx_t.name = "terrain_context"
    bm = bmesh.new()
    bm.from_mesh(ctx_t.data)
    m = 15.0
    hole = [vv for vv in bm.verts
            if BX0 - OX + m < vv.co.x < BX1 - OX - m and BY0 - OY + m < vv.co.y < BY1 - OY - m]
    bmesh.ops.delete(bm, geom=hole, context="VERTS")
    for vv in bm.verts:
        vv.co.z -= 1.5
    bm.to_mesh(ctx_t.data)
    bm.free()
    for poly in ctx_t.data.polygons:
        poly.use_smooth = True
    if cfg.get("context_aerial"):
        cb = cfg["context_bbox"]
        cme = ctx_t.data
        cco = np.empty(len(cme.vertices) * 3)
        cme.vertices.foreach_get("co", cco)
        cco = cco.reshape(-1, 3)
        cuv = cme.uv_layers.new(name="aerial")
        lv = np.empty(len(cme.loops), dtype=np.int64)
        cme.loops.foreach_get("vertex_index", lv)
        cuv.data.foreach_set("uv", np.column_stack([(cco[lv, 0] + OX - cb[0]) / (cb[2] - cb[0]),
                                                    (cco[lv, 1] + OY - cb[1]) / (cb[3] - cb[1])]).ravel())
        cme.materials.append(make_mat("aerial_context", (0.4, 0.4, 0.35, 1), image=p(cfg["context_aerial"])))
    for c in ctx_t.users_collection:
        c.objects.unlink(ctx_t)
    site.objects.link(ctx_t)
    check("context terrain", len(ctx_t.data.vertices) > 1000, "%d verts" % len(ctx_t.data.vertices))

# --- parcel stats on the terrain: elevation range and slope inside the boundary --------------
def inside(px, py, poly):
    # even-odd ray test, vectorized over points
    res = np.zeros(len(px), dtype=bool)
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        cross = ((y1 > py) != (y2 > py)) & (px < (x2 - x1) * (py - y1) / ((y2 - y1) or 1e-12) + x1)
        res ^= cross
    return res

mask = inside(co[:, 0], co[:, 1], loc)
zin = co[mask, 2]
# DEM grid slope from the raw vertex grid (PX m pixels)
grid = co[:, 2].reshape(-1, NX) if len(co) == NX * NY else None
stats = {"dem_pixels_in_parcel": int(mask.sum())}
if len(zin):
    stats.update(z_min=round(float(zin.min()), 2), z_max=round(float(zin.max()), 2),
                 relief_m=round(float(zin.max() - zin.min()), 2))
if grid is not None:
    gy, gx = np.gradient(grid, PX)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).ravel()
    s_in = slope[mask]
    stats.update(dem_px_m=PX, slope_deg_median=round(float(np.median(s_in)), 1),
                 slope_deg_p90=round(float(np.percentile(s_in, 90)), 1))
    # ~5 m box-smoothed surface: closer to what a building pad / driveway "feels"
    k = max(1, int(round(5.0 / PX))) | 1  # odd kernel width in pixels
    pad = np.pad(grid, k // 2, mode="edge")
    cs = pad.cumsum(0).cumsum(1)
    cs = np.pad(cs, ((1, 0), (1, 0)))
    sm = (cs[k:, k:] - cs[:-k, k:] - cs[k:, :-k] + cs[:-k, :-k]) / (k * k)
    gy5, gx5 = np.gradient(sm, PX)
    s5 = np.degrees(np.arctan(np.hypot(gx5, gy5))).ravel()[mask]
    grade5 = np.tan(np.radians(s5)) * 100
    stats.update(slope5m_deg_median=round(float(np.median(s5)), 1),
                 grade5m_pct_median=round(float(np.median(grade5)), 1),
                 pct_area_grade5m_under_15=round(float((grade5 < 15).mean() * 100), 1),
                 pct_area_grade5m_under_25=round(float((grade5 < 25).mean() * 100), 1))
    # best-fit plane over the parcel: overall grade and downhill direction (aspect)
    A = np.column_stack([co[mask, 0], co[mask, 1], np.ones(mask.sum())])
    (a, b, _), *_ = np.linalg.lstsq(A, zin, rcond=None)
    aspect = (math.degrees(math.atan2(-a, -b)) + 360) % 360  # compass bearing of downhill
    stats.update(plane_grade_pct=round(math.hypot(a, b) * 100, 1),
                 downhill_faces_deg=round(aspect, 0),
                 downhill_faces=["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((aspect + 22.5) // 45) % 8])
check("parcel terrain stats", len(zin) > 1000, json.dumps(stats))

# --- human-scale reference + design collection -----------------------------------------------
cx, cy = (sum(x for x, _ in loc[:-1]) / (len(loc) - 1), sum(y for _, y in loc[:-1]) / (len(loc) - 1))
design = new_coll("design_masses")  # building masses go here
ref = new_coll("scale_refs")
bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=1.8, location=drape((cx, cy), 0.9))
person = bpy.context.active_object
person.name = "person_1.8m"
for c in person.users_collection:
    c.objects.unlink(person)
ref.objects.link(person)
person.data.materials.append(make_mat("person_blue", (0.1, 0.3, 0.9, 1), emit=0.5))

# --- cameras + light --------------------------------------------------------------------------
def add_cam(name, loc3, look_at, lens=35, ortho=None):
    cd = bpy.data.cameras.new(name)
    cd.clip_start, cd.clip_end = 0.1, 5000
    cd.lens = lens
    if ortho:
        cd.type, cd.ortho_scale = "ORTHO", ortho
    ob = bpy.data.objects.new(name, cd)
    scn.collection.objects.link(ob)
    ob.location = loc3
    ob.rotation_euler = (Vector(look_at) - Vector(loc3)).to_track_quat("-Z", "Y").to_euler()
    return ob

zc = drape((cx, cy), 0).z
# road frontage: the road centerline point nearest the parcel centroid (elevation + distance stats)
road_pts = [pt for L in road_lines for pt in densify(to_local(L))]
rx, ry = min(road_pts, key=lambda q: math.dist(q, (cx, cy))) if road_pts else (cx - 40, cy - 40)
stats["road_frontage_z"] = round(drape((rx, ry), 0).z, 2)
stats["road_to_centroid_m"] = round(math.dist((rx, ry), (cx, cy)), 1)
cams = {
    "cam_top": add_cam("cam_top", (cx, cy, zc + 400), (cx, cy, zc), ortho=150),
    "cam_oblique": add_cam("cam_oblique", (cx - 110, cy - 130, zc + 90), (cx, cy, zc), lens=30),
}
# eye level: 50 m downhill of the centroid (along the fitted aspect), looking back up the slope
b = math.radians(stats.get("downhill_faces_deg", 180))
ex, ey = cx + 50 * math.sin(b), cy + 50 * math.cos(b)
cams["cam_eye"] = add_cam("cam_eye", drape((ex, ey), 1.7), drape((cx, cy), 1.7), lens=28)
cams["cam_top"].rotation_euler = (0, 0, 0)  # straight down, north up
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 4
sun.rotation_euler = (math.radians(40), 0, math.radians(200))
scn.collection.objects.link(sun)
world = bpy.data.worlds.new("sky")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.55, 0.7, 0.9, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
scn.world = world
scn.camera = cams["cam_oblique"]

# --- render + save ----------------------------------------------------------------------------
if RENDER:
    scn.render.engine = "BLENDER_EEVEE"
    scn.render.resolution_x, scn.render.resolution_y = 1600, 1000
    scn.view_settings.view_transform = "AgX"
    for name, cam in cams.items():
        scn.camera = cam
        scn.render.filepath = p(os.path.join("renders", name + ".png"))
        bpy.ops.render.render(write_still=True)
        check("render " + name, os.path.exists(scn.render.filepath))
    scn.camera = cams["cam_oblique"]

with open(p("exports/site_stats.json"), "w") as f:
    json.dump(dict(stats, parcel_area_m2=round(area_bl, 1), parcel_acres=round(area_bl / 4046.8564, 4),
                   local_origin_xy=[OX, OY], crs=cfg["epsg"]), f, indent=2)

blend = p("blender/site_master.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend, relative_remap=True)
bpy.ops.file.make_paths_relative()
bpy.ops.wm.save_mainfile()
check("saved site_master.blend", os.path.exists(blend), blend)

print("[DONE] %d check(s) failed: %s" % (len(failed), failed) if failed else "[DONE] all checks OK")
sys.exit(1 if failed else 0)
