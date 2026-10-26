# Place building masses from a design JSON onto a parcel's site_master.blend, save as a separate design .blend.
# Usage:
#   blender -b --factory-startup -noaudio --python place_masses.py -- PARCEL_DIR DESIGN.json [--no-render]
# Reads blender/site_master.blend (never modifies it), writes blender/<design name>.blend,
# renders/<design name>_*.png and exports/<design name>_stats.json. Exits 1 if any [CHECK] fails.
# Each mass is ONE object (walls + roof + deep foundation) with its origin at floor level, so it can be
# moved/rotated in Blender; the foundation runs 20 m down and the terrain hides the buried part.
import sys, os, json, math
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
PDIR, DESIGN = os.path.abspath(argv[0]), os.path.abspath(argv[1])
RENDER = "--no-render" not in argv
FT = 0.3048
FOUNDATION_DEPTH = 20.0
cfg = json.load(open(os.path.join(PDIR, "parcel.json")))
design = json.load(open(DESIGN))
OX, OY = cfg["local_origin_xy"]
failed = []

def check(name, ok, detail=""):
    print("[CHECK] %-4s %s %s" % ("OK" if ok else "FAIL", name, detail))
    if not ok:
        failed.append(name)

def fatal(name, detail=""):
    # a failed check after which nothing further can be computed
    check(name, False, detail)
    print("[DONE] %d check(s) failed: %s" % (len(failed), failed))
    sys.exit(1)

def outer_ring(geom):
    # Outer ring of the largest polygon: a parcel split by a road arrives as a MultiPolygon.
    if geom["type"] == "Polygon":
        polys = [geom["coordinates"]]
    elif geom["type"] == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        fatal("parcel geometry", "%s, expected Polygon or MultiPolygon" % geom["type"])
    area = lambda ring: abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))) / 2
    return max((poly[0] for poly in polys), key=area)

def p(rel):
    return os.path.join(PDIR, rel)

for sub in ("exports", "renders"):
    os.makedirs(p(sub), exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=p("blender/site_master.blend"))
scn = bpy.context.scene
terrain = bpy.data.objects["terrain"]
bvh = BVHTree.FromObject(terrain, bpy.context.evaluated_depsgraph_get())

def ground(x, y):
    hit = bvh.ray_cast(Vector((x, y, 5000)), Vector((0, 0, -1)))
    return hit[0].z if hit[0] else None

# --- parcel frame: origin = front corner with the smallest u, u along the road, v into the lot ---
ring = outer_ring(json.load(open(p(cfg["parcel"])))["features"][0]["geometry"])
loc_ring = [(x - OX, y - OY) for x, y in ring]
ub = math.radians(design["frame"]["u_bearing_deg"])
U = Vector((math.sin(ub), math.cos(ub)))           # bearing -> (east, north)
V = Vector((math.sin(ub + math.pi / 2), math.cos(ub + math.pi / 2)))
# frame origin: the vertex with minimal u among the vertices with minimal v (front corner)
pts = [Vector(q) for q in loc_ring[:-1]]
vmin = min(q.dot(V) for q in pts)
front = [q for q in pts if q.dot(V) < vmin + 3.0]
F0 = min(front, key=lambda q: q.dot(U))
F0 = U * F0.dot(U) + V * vmin  # project so v=0 is the frontmost point

def uv_to_xy(u, v):
    q = F0 + U * u + V * v
    return q.x, q.y

def inside(px, py, poly):
    res = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        if (y1 > py) != (y2 > py) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
            res = not res
    return res

def seg_dist(pt, a, b):
    ax, ay = a; bx, by = b; px, py = pt
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)

def segs_cross(a, b, c, d):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return (orient(a, b, c) > 0) != (orient(a, b, d) > 0) and (orient(c, d, a) > 0) != (orient(c, d, b) > 0)

def footprint_vs_parcel(corners, ring):
    """(fully inside, min clearance m). Inside = every corner inside and no edge crosses the boundary,
    so concave lots are handled. Clearance = true distance between the two outlines."""
    fp = list(corners) + [corners[0]]
    fsegs, psegs = list(zip(fp, fp[1:])), list(zip(ring, ring[1:]))
    crosses = any(segs_cross(a, b, c, d) for a, b in fsegs for c, d in psegs)
    ins = not crosses and all(inside(x, y, ring) for x, y in corners)
    clear = 0.0 if crosses else min(min(seg_dist(c, a, b) for c in corners for a, b in psegs),
                                    min(seg_dist(q, a, b) for q in ring[:-1] for a, b in fsegs))
    return ins, clear

def mat(name, color, rough=0.8):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    m.diffuse_color = color
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color
    b.inputs["Roughness"].default_value = rough
    return m

M_WALL = mat("mass_wall", (0.92, 0.89, 0.82, 1))
M_ROOF = mat("mass_roof", (0.32, 0.22, 0.18, 1))
M_FND = mat("mass_foundation", (0.55, 0.55, 0.53, 1))
M_TER = mat("mass_terrace", (0.78, 0.70, 0.58, 1), rough=0.95)

def add_box(bm, x0, x1, y0, y1, z0, z1, mi):
    vs = [bm.verts.new((x, y, z)) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        bm.faces.new([vs[i] for i in f]).material_index = mi

def add_gable(bm, w, d, z, rise, over, mi):
    # ridge along local X (the long side); eaves at y = +/- (d/2 + over)
    x0, x1, y = -w / 2 - over, w / 2 + over, d / 2 + over
    a = [bm.verts.new(c) for c in ((x0, -y, z), (x1, -y, z), (x1, y, z), (x0, y, z),
                                   (x0, 0, z + rise), (x1, 0, z + rise))]
    for f in ((0, 1, 5, 4), (3, 4, 5, 2), (0, 4, 3), (1, 2, 5), (0, 3, 2, 1)):
        bm.faces.new([a[i] for i in f]).material_index = mi

coll = bpy.data.collections["design_masses"]
for ob in list(coll.objects):
    bpy.data.objects.remove(ob, do_unlink=True)

stats = {"design": design["name"], "floor_mode": design["floor_mode"], "elements": {}}
ids = [e["id"] for e in design["elements"]]
dupes = sorted({i for i in ids if ids.count(i) > 1})
if dupes:  # objects, meshes and stats are all keyed by id
    fatal("element ids unique", "duplicates: %s" % dupes)
footprints = {}
for el in design["elements"]:
    if el["kind"] == "house":
        w, d = el["w_ft"] * FT, el["d_ft"] * FT
    else:
        w, d = el["w_m"], el["d_m"]
    cx, cy = uv_to_xy(el["u"], el["v"])
    rot = math.atan2(U.y, U.x) + math.radians(el.get("rot_deg", 0))
    R = Matrix.Rotation(rot, 2)
    corners = [tuple(Vector((cx, cy)) + R @ Vector((sx * w / 2, sy * d / 2)))
               for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    footprints[el["id"]] = corners
    # sample terrain under the footprint on a 1 m grid
    zs = [ground(*(Vector((cx, cy)) + R @ Vector((gx, gy))))
          for gx in np.arange(-w / 2, w / 2 + 0.01, 1.0) for gy in np.arange(-d / 2, d / 2 + 0.01, 1.0)]
    zs = [z for z in zs if z is not None]
    if not zs:
        fatal("%s footprint on terrain" % el["id"], "no DEM under the footprint; check u/v against raster_bbox")
    zmin, zmax = min(zs), max(zs)
    mode = el.get("floor_mode", design["floor_mode"])
    if mode not in ("balanced", "uphill"):
        fatal("%s floor_mode" % el["id"], "%r, expected balanced or uphill" % mode)
    floor = {"balanced": float(np.mean(zs)), "uphill": zmax}[mode]

    me = bpy.data.meshes.new(el["id"])
    bm = bmesh.new()
    if el["kind"] == "house":
        h = el["wall_h"]
        add_box(bm, -w / 2, w / 2, -d / 2, d / 2, 0, h, 0)
        add_gable(bm, w, d, h, (d / 2 + 0.5) * el["roof_pitch"], 0.5, 1)
        add_box(bm, -w / 2 + 0.05, w / 2 - 0.05, -d / 2 + 0.05, d / 2 - 0.05, -FOUNDATION_DEPTH, 0, 2)
        for m in (M_WALL, M_ROOF, M_FND):
            me.materials.append(m)
    else:
        add_box(bm, -w / 2, w / 2, -d / 2, d / 2, -0.3, 0, 0)
        add_box(bm, -w / 2 + 0.05, w / 2 - 0.05, -d / 2 + 0.05, d / 2 - 0.05, -FOUNDATION_DEPTH, -0.3, 1)
        for m in (M_TER, M_FND):
            me.materials.append(m)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(el["id"], me)
    coll.objects.link(ob)
    ob.location = (cx, cy, floor)
    ob.rotation_euler = (0, 0, rot)

    # measure the footprint of the mesh actually built (walls / terrace top = material 0), in world XY
    vids = {i for poly in me.polygons if poly.material_index == 0 for i in poly.vertices}
    local = [me.vertices[i].co for i in vids]
    w_built = max(q.x for q in local) - min(q.x for q in local)
    d_built = max(q.y for q in local) - min(q.y for q in local)
    built_corners = [tuple((ob.matrix_basis @ q).xy) for q in local]
    match = all(min(math.dist(c, q) for q in built_corners) < 0.001 for c in corners)
    check("%s built footprint %.2f x %.2f m (%d sq ft)" % (el["id"], w_built, d_built,
                                                           round(w_built * d_built / FT / FT)),
          abs(w_built - w) < 0.001 and abs(d_built - d) < 0.001 and match)

    ins, clear = footprint_vs_parcel(corners, loc_ring)
    info = dict(footprint_m2=round(w * d, 1), footprint_sqft=round(w * d / FT / FT), floor_mode=mode,
                floor_z=round(floor, 2), ground_z_range=[round(zmin, 2), round(zmax, 2)],
                cut_depth_uphill_m=round(zmax - floor, 2), exposed_foundation_downhill_m=round(floor - zmin, 2),
                min_clearance_to_boundary_m=round(clear, 1))
    stats["elements"][el["id"]] = info
    check("%s inside parcel" % el["id"], ins, json.dumps(info))

# --- graded terrain: copy of the terrain with each pad cut down to its floor (fill side untouched,
# so foundations show on the downhill side). Follows the design JSON, not hand-moved objects.
graded = terrain.copy()
graded.data = terrain.data.copy()
graded.name = graded.data.name = "terrain_graded"
for c in terrain.users_collection:
    c.objects.link(graded)
terrain.hide_render = True
terrain.hide_set(True)
gco = np.empty(len(graded.data.vertices) * 3)
graded.data.vertices.foreach_get("co", gco)
gco = gco.reshape(-1, 3)
CUT_MARGIN = 0.75
for el in design["elements"]:
    ob = bpy.data.objects[el["id"]]
    w, d = ((el["w_ft"] * FT, el["d_ft"] * FT) if el["kind"] == "house" else (el["w_m"], el["d_m"]))
    rel = gco[:, :2] - np.array(ob.location.xy)
    c, s = math.cos(-ob.rotation_euler.z), math.sin(-ob.rotation_euler.z)
    lx, ly = rel[:, 0] * c - rel[:, 1] * s, rel[:, 0] * s + rel[:, 1] * c
    sel = (np.abs(lx) <= w / 2 + CUT_MARGIN) & (np.abs(ly) <= d / 2 + CUT_MARGIN)
    top = ob.location.z - 0.05
    gco[sel, 2] = np.minimum(gco[sel, 2], top)
graded.data.vertices.foreach_set("co", gco.ravel())
graded.data.update()

# overlaps (separating axis on the rotated rectangles)
def overlap(a, b):
    for poly in (a, b):
        for i in range(4):
            e = Vector(poly[(i + 1) % 4]) - Vector(poly[i])
            n = Vector((-e.y, e.x))
            pa = [n.dot(Vector(q)) for q in a]
            pb = [n.dot(Vector(q)) for q in b]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True
clash = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:] if overlap(footprints[a], footprints[b])]
check("no footprint overlaps", not clash, str(clash))
parcel_area = 0.5 * abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(loc_ring, loc_ring[1:])))
houses = [k for k, e in zip(ids, design["elements"]) if e["kind"] == "house"]
cov = sum(stats["elements"][k]["footprint_m2"] for k in houses) / parcel_area * 100
stats["building_coverage_pct"] = round(cov, 1)
print("[INFO] building coverage %.1f%% of %.0f m2" % (cov, parcel_area))

# --- cameras ---------------------------------------------------------------------------------
def add_cam(name, loc3, look_at, lens=35):
    cd = bpy.data.cameras.new(name)
    cd.clip_start, cd.clip_end, cd.lens = 0.1, 20000, lens
    ob = bpy.data.objects.get(name)
    if ob:
        bpy.data.objects.remove(ob, do_unlink=True)
    ob = bpy.data.objects.new(name, cd)
    scn.collection.objects.link(ob)
    ob.location = loc3
    ob.rotation_euler = (Vector(look_at) - Vector(loc3)).to_track_quat("-Z", "Y").to_euler()
    return ob

def use_eevee(scn):
    # Blender 5.0 renamed the engine identifier from BLENDER_EEVEE_NEXT back to BLENDER_EEVEE.
    for eng in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scn.render.engine = eng
            return eng
        except TypeError:
            pass
    fatal("render engine", "no EEVEE engine in this Blender")

els = design["elements"]
mid = Vector(uv_to_xy(sum(e["u"] for e in els) / len(els), sum(e["v"] for e in els) / len(els)))
mz = ground(*mid)
if mz is None:  # layout center off the DEM: use the mean floor elevation instead
    mz = sum(bpy.data.objects[e["id"]].location.z for e in els) / len(els)
cams = {
    # from downhill and off to one side, elevated, looking back up at the whole layout
    "overview": add_cam("cam_overview", (*(mid + V * 85 - U * 45), mz + 35), (*mid, mz + 2), lens=35),
}
court = next((e for e in els if e["kind"] == "terrace"), None)
if court:
    # standing near the terrace's uphill edge looking out over it (downhill) to the horizon
    ccx, ccy = uv_to_xy(court["u"], court["v"])
    cz = bpy.data.objects[court["id"]].location.z
    cams["courtyard_eye"] = add_cam("cam_courtyard_eye", (*(Vector((ccx, ccy)) - V * 2), cz + 1.7),
                                    (*(Vector((ccx, ccy)) + V * 300), cz - 25), lens=24)
house = next((e for e in els if e["kind"] == "house"), None)
if house:
    # standing at the road frontage (v = 1 m) in line with the first house, looking down at it
    eye = Vector(uv_to_xy(house["u"], 1))
    ez, hz = ground(*eye), bpy.data.objects[house["id"]].location.z
    cams["from_road"] = add_cam("cam_from_road", (*eye, (hz if ez is None else ez) + 1.7),
                                (*Vector(uv_to_xy(house["u"], house["v"])), hz + 3), lens=24)
EYE_SHOTS = {"courtyard_eye", "from_road"}
OVERLAYS = [bpy.data.objects[n] for n in ("parcel_boundary", "neighbor_parcels", "road_centerlines")
            if n in bpy.data.objects]
top = bpy.data.objects.get("cam_top")

sun = bpy.data.objects.get("sun")
if sun:  # low sun from the SW for long shadows
    # X tilt 58 deg = 32 deg elevation; Z -45 deg makes the light travel toward the NE (sun in the SW)
    sun.rotation_euler = (math.radians(58), 0, math.radians(-45))
    sun.data.energy = 4.5
    sun.data.angle = math.radians(1.5)

name = design["name"]
if RENDER:
    use_eevee(scn)
    scn.render.resolution_x, scn.render.resolution_y = 1600, 1000
    scn.view_settings.view_transform = "AgX"
    shots = dict(cams)
    if top:
        shots["top"] = top
    for k, cam in shots.items():
        scn.camera = cam
        for o in OVERLAYS:  # GIS line tubes read well from above but fill the frame at eye level
            o.hide_render = k in EYE_SHOTS
        scn.render.filepath = p(os.path.join("renders", "%s_%s.png" % (name, k)))
        bpy.ops.render.render(write_still=True)
        check("render " + k, os.path.exists(scn.render.filepath))
scn.camera = cams["overview"]

with open(p("exports/%s_stats.json" % name), "w") as f:
    json.dump(stats, f, indent=2)
out = p("blender/%s.blend" % name)
bpy.ops.wm.save_as_mainfile(filepath=out, relative_remap=True)
check("saved %s.blend" % name, os.path.exists(out), out)
print("[DONE] %d check(s) failed: %s" % (len(failed), failed) if failed else "[DONE] all checks OK")
sys.exit(1 if failed else 0)
