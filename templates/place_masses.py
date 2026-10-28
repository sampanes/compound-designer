# Place building masses from a design JSON onto a parcel's site_master.blend, save as a separate design .blend.
# Usage:
#   blender -b --factory-startup -noaudio --python place_masses.py -- PARCEL_DIR DESIGN.json [--no-render]
# Reads blender/site_master.blend (never modifies it), writes blender/<design name>.blend,
# renders/<design name>_*.png and exports/<design name>_stats.json. Exits 1 if any [CHECK] fails.
# Elements: house (w_ft x d_ft; "steps" splits it onto several pads at their own floor levels), terrace
# (w_m x d_m) and drive (a u/v polyline with a width: a driveway or path graded into the terrain as a
# ribbon, with length and grade stats and a check against max_grade_pct).
# Each mass is ONE object (walls + roof + deep foundation) with its origin at floor level, so it can be
# moved/rotated in Blender; the foundation runs 20 m down and the terrain hides the buried part.
import sys, os, json, math
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # design_geom.py sits next to this script
from design_geom import footprint_vs_parcel, polyline_to_polygon_distance, offsets, profile, split_depths

argv = sys.argv[sys.argv.index("--") + 1:]
PDIR, DESIGN = os.path.abspath(argv[0]), os.path.abspath(argv[1])
RENDER = "--no-render" not in argv
FT = 0.3048
FOUNDATION_DEPTH = 20.0
CUT_MARGIN = 0.75   # a pad is cut this far beyond its footprint
DRIVE_BLEND = 1.0   # a drive's cut or fill tapers back to the terrain over this distance beyond its edge
DRIVE_LIFT = 0.03   # the drive surface sits this far above the graded terrain
cfg = json.load(open(os.path.join(PDIR, "parcel.json")))
design = json.load(open(DESIGN))
OX, OY = cfg["local_origin_xy"]
MAX_GRADE = design.get("max_grade_pct", 15)
REACH = design.get("reach_m", 3.0)
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
M_DRIVE = mat("mass_drive", (0.30, 0.29, 0.28, 1), rough=0.95)

def add_box(bm, x0, x1, y0, y1, z0, z1, mi):
    vs = [bm.verts.new((x, y, z)) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        bm.faces.new([vs[i] for i in f]).material_index = mi

def add_gable(bm, w, y0, y1, z, rise, over, mi):
    # ridge along local X (the long side) halfway between y0 and y1; eaves at y0 - over and y1 + over
    x0, x1, ya, yb, ym = -w / 2 - over, w / 2 + over, y0 - over, y1 + over, (y0 + y1) / 2
    a = [bm.verts.new(c) for c in ((x0, ya, z), (x1, ya, z), (x1, yb, z), (x0, yb, z),
                                   (x0, ym, z + rise), (x1, ym, z + rise))]
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
KINDS = ("house", "terrace", "drive")
for el in design["elements"]:
    if el.get("kind") not in KINDS:
        fatal("%s kind" % el["id"], "%r, expected one of %s" % (el.get("kind"), ", ".join(KINDS)))
masses = [e for e in design["elements"] if e["kind"] != "drive"]
drives = [e for e in design["elements"] if e["kind"] == "drive"]
houses = [e["id"] for e in masses if e["kind"] == "house"]
if not masses:
    fatal("elements", "a design needs at least one house or terrace")

# --- houses and terraces: one object each, on one pad or (a stepped house) several -----------------
footprints, pad_table = {}, {}
for el in masses:
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
    mode = el.get("floor_mode", design["floor_mode"])
    if mode not in ("balanced", "uphill"):
        fatal("%s floor_mode" % el["id"], "%r, expected balanced or uphill" % mode)
    # pads across the depth, front first: local +y faces the road (smaller v). A plain mass is one pad.
    if el["kind"] == "house" and "steps" in el:
        try:
            depths = [s * FT for s in split_depths(el["steps"], el["d_ft"])]
        except ValueError as e:
            fatal("%s steps" % el["id"], str(e))
    else:
        depths = [d]
    pads, y1 = [], d / 2  # (y0, y1, floor, ground min, ground max) per pad
    for pd in depths:
        y0 = y1 - pd
        # sample terrain under the pad on a 1 m grid
        zs = [ground(*(Vector((cx, cy)) + R @ Vector((gx, gy))))
              for gx in np.arange(-w / 2, w / 2 + 0.01, 1.0) for gy in np.arange(y0, y1 + 0.01, 1.0)]
        zs = [z for z in zs if z is not None]
        if not zs:
            fatal("%s footprint on terrain" % el["id"], "no DEM under the footprint; check u/v against raster_bbox")
        pads.append((y0, y1, {"balanced": float(np.mean(zs)), "uphill": max(zs)}[mode], min(zs), max(zs)))
        y1 = y0
    floor = pads[0][2]
    pad_table[el["id"]] = (cx, cy, rot, w, d, pads)

    me = bpy.data.meshes.new(el["id"])
    bm = bmesh.new()
    if el["kind"] == "house":
        h = el["wall_h"]
        for y0, y1, fz, _, _ in pads:
            z = fz - floor  # this pad's floor relative to the object origin, the front pad's floor
            add_box(bm, -w / 2, w / 2, y0, y1, z, z + h, 0)
            add_gable(bm, w, y0, y1, z + h, ((y1 - y0) / 2 + 0.5) * el["roof_pitch"], 0.5, 1)
            add_box(bm, -w / 2 + 0.05, w / 2 - 0.05, y0 + 0.05, y1 - 0.05, -FOUNDATION_DEPTH, z, 2)
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
                floor_z=round(floor, 2),
                ground_z_range=[round(min(q[3] for q in pads), 2), round(max(q[4] for q in pads), 2)],
                cut_depth_uphill_m=round(max(q[4] - q[2] for q in pads), 2),
                exposed_foundation_downhill_m=round(max(q[2] - q[3] for q in pads), 2),
                min_clearance_to_boundary_m=round(clear, 1))
    if len(pads) > 1:  # per-pad figures for a stepped house, front first
        info["pads"] = [dict(depth_ft=round((y1 - y0) / FT, 1), floor_z=round(fz, 2),
                             step_from_front_pad_m=round(fz - floor, 2), ground_z_range=[round(zl, 2), round(zh, 2)],
                             cut_depth_uphill_m=round(zh - fz, 2), exposed_foundation_downhill_m=round(fz - zl, 2))
                        for y0, y1, fz, zl, zh in pads]
    stats["elements"][el["id"]] = info
    check("%s inside parcel" % el["id"], ins, json.dumps(info))

# --- drives and paths: a ribbon along a u/v polyline, level across, straight between its points ------
def pad_floor_at(x, y):
    # floor of the pad under world (x, y) when a mass sits there (within CUT_MARGIN), else None
    for cx, cy, rot, w, d, pads in pad_table.values():
        q = Matrix.Rotation(-rot, 2) @ Vector((x - cx, y - cy))
        if abs(q.x) <= w / 2 + CUT_MARGIN:
            for y0, y1, fz, _, _ in pads:
                if y0 - CUT_MARGIN <= q.y <= y1 + CUT_MARGIN:
                    return fz
    return None

drive_lines = {}
for el in drives:
    pts = [uv_to_xy(u, v) for u, v in el["points"]]
    width, limit = el["width_m"], el.get("max_grade_pct", MAX_GRADE)
    zs = []
    for (x, y), uv in zip(pts, el["points"]):
        z = pad_floor_at(x, y)  # a point on a pad takes the pad's floor, so a drive meets its house at floor level
        z = ground(x, y) if z is None else z
        if z is None:
            fatal("%s on terrain" % el["id"], "point (u %g, v %g) is off the DEM; check it against raster_bbox" % tuple(uv))
        zs.append(z)
    try:
        edges = offsets(pts, width)
        prof = profile(pts, zs, limit)
    except ValueError as e:
        fatal("%s points" % el["id"], str(e))
    # one quad per segment between the left and right edges, just above the graded terrain
    me = bpy.data.meshes.new(el["id"])
    bm = bmesh.new()
    x0, y0, z0 = pts[0][0], pts[0][1], zs[0]
    left = [bm.verts.new((l[0] - x0, l[1] - y0, z - z0 + DRIVE_LIFT)) for (l, _), z in zip(edges, zs)]
    right = [bm.verts.new((r[0] - x0, r[1] - y0, z - z0 + DRIVE_LIFT)) for (_, r), z in zip(edges, zs)]
    for i in range(len(pts) - 1):
        bm.faces.new((left[i], right[i], right[i + 1], left[i + 1]))
    me.materials.append(M_DRIVE)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(el["id"], me)
    coll.objects.link(ob)
    ob.location = (x0, y0, z0)
    drive_lines[el["id"]] = (pts, zs, width)
    reach = [h for h in houses
             if polyline_to_polygon_distance(pts, footprints[h] + [footprints[h][0]]) <= width / 2 + REACH]
    stats["elements"][el["id"]] = dict(kind="drive", width_m=width, **prof, reaches=reach)
    steep = ["segment %d (%.0f m) at %.1f%%" % (s["from"], s["length_m"], s["grade_pct"])
             for s in prof["segments"] if not s["ok"]]
    check("%s grade within %g%%" % (el["id"], limit), not steep, "; ".join(steep) if steep else
          "%.0f m, max %.1f%%, reaches %s" % (prof["length_m"], prof["max_grade_pct"], ", ".join(reach) or "no house"))

if drives:  # access: which drive or path comes within REACH of each house's walls
    stats.update(max_grade_pct=MAX_GRADE, reach_m=REACH)
    unreached = []
    for h in houses:
        ring_h = footprints[h] + [footprints[h][0]]
        gap, via = min((polyline_to_polygon_distance(pts, ring_h) - width / 2, did)
                       for did, (pts, _, width) in drive_lines.items())
        ok = gap <= REACH
        stats["elements"][h]["access"] = {"via": via if ok else None, "gap_m": round(max(gap, 0.0), 1)}
        if not ok:
            unreached.append(h)
    stats["unreached_houses"] = unreached
    print("[INFO] access: " + ("every house is reached by a drive or path" if not unreached else
                               "no drive or path within %g m of %s" % (REACH, ", ".join(unreached))))

# --- graded terrain: a copy of the terrain with each drive cut and filled to its grade line, then each
# pad cut down to its floor (fill side untouched, so foundations show on the downhill side; a pad wins
# over a drive that crosses it). Follows the design JSON, not hand-moved objects.
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
for pts, zs, width in drive_lines.values():
    hw = width / 2
    for (a, b), (za, zb) in zip(zip(pts, pts[1:]), zip(zs, zs[1:])):
        a, dv = np.array(a), np.array(b) - np.array(a)
        t = np.clip(((gco[:, :2] - a) @ dv) / (dv @ dv), 0, 1)
        dist = np.linalg.norm(gco[:, :2] - (a + t[:, None] * dv), axis=1)
        zp = za + t * (zb - za)  # the grade line, straight between the two points
        on = dist <= hw
        gco[on, 2] = zp[on]
        edge = (dist > hw) & (dist <= hw + DRIVE_BLEND)
        wgt = (dist[edge] - hw) / DRIVE_BLEND
        gco[edge, 2] = zp[edge] * (1 - wgt) + gco[edge, 2] * wgt
for cx, cy, rot, w, d, pads in pad_table.values():
    rel = gco[:, :2] - np.array((cx, cy))
    c, s = math.cos(-rot), math.sin(-rot)
    lx, ly = rel[:, 0] * c - rel[:, 1] * s, rel[:, 0] * s + rel[:, 1] * c
    for y0, y1, fz, _, _ in pads:
        # the margin applies at the mass's own edges, not at the step between two pads
        lo = y0 - (CUT_MARGIN if abs(y0 + d / 2) < 1e-6 else 0)
        hi = y1 + (CUT_MARGIN if abs(y1 - d / 2) < 1e-6 else 0)
        sel = (np.abs(lx) <= w / 2 + CUT_MARGIN) & (ly >= lo) & (ly <= hi)
        gco[sel, 2] = np.minimum(gco[sel, 2], fz - 0.05)
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
mass_ids = [e["id"] for e in masses]
clash = [(a, b) for i, a in enumerate(mass_ids) for b in mass_ids[i + 1:] if overlap(footprints[a], footprints[b])]
check("no footprint overlaps", not clash, str(clash))
parcel_area = 0.5 * abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(loc_ring, loc_ring[1:])))
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

els = masses
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
