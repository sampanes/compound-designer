# Pure 2D geometry for the design side of place_masses.py: everything about footprints, ribbons and
# grade lines that does not need Blender. Plain Python 3 stdlib, so tests/ runs it anywhere;
# place_masses.py imports it inside Blender. Points are (x, y) tuples in meters; a ring is closed
# (its last point repeats its first).
import math


def seg_dist(pt, a, b):
    """Distance from pt to the segment ab."""
    ax, ay = a
    bx, by = b
    px, py = pt
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def segs_cross(a, b, c, d):
    """True when segments ab and cd properly cross."""
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return (orient(a, b, c) > 0) != (orient(a, b, d) > 0) and (orient(c, d, a) > 0) != (orient(c, d, b) > 0)


def inside(px, py, ring):
    """Point in polygon (even-odd rule) for a closed ring."""
    res = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > py) != (y2 > py) and px < (x2 - x1) * (py - y1) / (y2 - y1) + x1:
            res = not res
    return res


def footprint_vs_parcel(corners, ring):
    """(fully inside, min clearance m) of a footprint (open list of corners) against a parcel ring.
    Inside = every corner inside and no edge crosses the boundary, so concave lots are handled.
    Clearance = true distance between the two outlines."""
    fp = list(corners) + [corners[0]]
    fsegs, psegs = list(zip(fp, fp[1:])), list(zip(ring, ring[1:]))
    crosses = any(segs_cross(a, b, c, d) for a, b in fsegs for c, d in psegs)
    ins = not crosses and all(inside(x, y, ring) for x, y in corners)
    clear = 0.0 if crosses else min(min(seg_dist(c, a, b) for c in corners for a, b in psegs),
                                    min(seg_dist(q, a, b) for q in ring[:-1] for a, b in fsegs))
    return ins, clear


def polyline_to_polygon_distance(pts, ring):
    """Distance between an open polyline and a closed ring: 0 when the line touches, crosses or
    enters the polygon."""
    psegs, rsegs = list(zip(pts, pts[1:])), list(zip(ring, ring[1:]))
    if any(inside(x, y, ring) for x, y in pts):
        return 0.0
    if any(segs_cross(a, b, c, d) for a, b in psegs for c, d in rsegs):
        return 0.0
    return min(min(seg_dist(q, c, d) for q in pts for c, d in rsegs),
               min(seg_dist(r, a, b) for r in ring[:-1] for a, b in psegs))


def offsets(pts, width):
    """Left and right edge points of a ribbon of the given width along the polyline pts, one
    (left, right) pair per vertex, joins mitered. A miter is capped at twice the half width, so a
    very sharp turn gets a blunt corner instead of a spike."""
    if len(pts) < 2:
        raise ValueError("a ribbon needs at least two points")
    hw = width / 2
    dirs = []
    for a, b in zip(pts, pts[1:]):
        L = math.dist(a, b)
        if L < 1e-9:
            raise ValueError("points %s and %s coincide" % (a, b))
        dirs.append(((b[0] - a[0]) / L, (b[1] - a[1]) / L))
    out = []
    for i, (x, y) in enumerate(pts):
        d0, d1 = dirs[max(i - 1, 0)], dirs[min(i, len(dirs) - 1)]
        n0, n1 = (-d0[1], d0[0]), (-d1[1], d1[0])  # left-hand normals of the segments in and out
        mx, my = n0[0] + n1[0], n0[1] + n1[1]
        m = math.hypot(mx, my)
        if m < 1e-9:  # a hairpin: use the incoming normal
            mx, my, m = n0[0], n0[1], 1.0
        mx, my = mx / m, my / m
        k = hw / max(mx * n0[0] + my * n0[1], 0.5)  # hw / cos(half the turn), capped at 2 hw
        out.append(((x + mx * k, y + my * k), (x - mx * k, y - my * k)))
    return out


def _segments_meet(a, b, c, d):
    """True when closed segments ab and cd cross, touch or overlap."""
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    def on_segment(p, q, r):
        return (min(p[0], r[0]) <= q[0] <= max(p[0], r[0])
                and min(p[1], r[1]) <= q[1] <= max(p[1], r[1]))
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0):
        return True
    return ((o1 == 0 and on_segment(a, c, b)) or (o2 == 0 and on_segment(a, d, b))
            or (o3 == 0 and on_segment(c, a, d)) or (o4 == 0 and on_segment(c, b, d)))


def _finite_number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def checked_offsets(pts, width):
    """Validated ribbon offsets for an open polyline.

    Rejects non-finite inputs, crossing centerlines and any segment whose mitered quad folds or
    crosses itself. It intentionally imposes no turning-radius policy: separated switchbacks are
    valid, while geometry that cannot make the quad faces used by Blender is not.
    """
    if not (_finite_number(width) and width > 0):
        raise ValueError("width must be a finite positive number")
    if not (isinstance(pts, (list, tuple)) and all(
            isinstance(q, (list, tuple)) and len(q) == 2
            and all(_finite_number(v) for v in q)
            for q in pts)):
        raise ValueError("points must be finite [x, y] pairs")
    try:
        edges = offsets(pts, width)  # also enforces the existing 1e-9 m segment threshold
    except (OverflowError, ZeroDivisionError) as e:
        raise ValueError("ribbon geometry overflowed") from e
    if not all(_finite_number(v) for pair in edges for point in pair for v in point):
        raise ValueError("ribbon geometry overflowed")
    segments = list(zip(pts, pts[1:]))
    for i, (a, b) in enumerate(segments):
        for j in range(i + 2, len(segments)):
            c, d = segments[j]
            if _segments_meet(a, b, c, d):
                raise ValueError("centerline segments %d and %d cross, touch or overlap" % (i, j))
    for i, ((l0, r0), (l1, r1)) in enumerate(zip(edges, edges[1:])):
        face = (l0, r0, r1, l1)
        area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(face, face[1:] + face[:1]))
        if area2 <= 0 or _segments_meet(l0, r0, r1, l1) or _segments_meet(r0, r1, l1, l0):
            raise ValueError("segment %d creates a folded ribbon face" % i)
    # The individual quads can all be valid while a later one loops back over an earlier one.
    # A valid open ribbon has one simple outer boundary: left side forward, end cap, right side
    # backward, start cap. Non-neighboring boundary edges may not cross, touch or overlap.
    left, right = [pair[0] for pair in edges], [pair[1] for pair in edges]
    boundary = left + list(reversed(right)) + [left[0]]
    boundary_segments = list(zip(boundary, boundary[1:]))
    for i, (a, b) in enumerate(boundary_segments):
        for j in range(i + 1, len(boundary_segments)):
            if j == i + 1 or (i == 0 and j == len(boundary_segments) - 1):
                continue
            if _segments_meet(a, b, *boundary_segments[j]):
                raise ValueError("ribbon boundary crosses, touches or overlaps itself")
    return edges


def profile(pts, zs, max_grade_pct):
    """Grade line of a polyline whose vertices sit at elevations zs: per-segment length, rise and
    grade (signed, positive climbs in the direction of travel), plus totals and which segments are
    steeper than max_grade_pct."""
    if len(pts) < 2 or len(zs) != len(pts):
        raise ValueError("need one elevation per point and at least two points")
    segs, raw = [], []
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        L = math.dist(a, b)
        if L < 1e-9:
            raise ValueError("points %s and %s coincide" % (a, b))
        rise = zs[i + 1] - zs[i]
        g = rise / L * 100
        raw.append((L, rise, g))
        segs.append({"from": i, "to": i + 1, "length_m": round(L, 1), "rise_m": round(rise, 2),
                     "grade_pct": round(g, 1), "ok": abs(g) <= max_grade_pct + 1e-9})
    total = sum(L for L, _, _ in raw)
    climb = sum(abs(rise) for _, rise, _ in raw)
    return {"length_m": round(total, 1), "start_z": round(zs[0], 2), "end_z": round(zs[-1], 2),
            "rise_m": round(zs[-1] - zs[0], 2), "mean_grade_pct": round(climb / total * 100, 1),
            "max_grade_pct": round(max(abs(g) for _, _, g in raw), 1), "max_grade_pct_allowed": max_grade_pct,
            "too_steep_segments": [s["from"] for s in segs if not s["ok"]], "segments": segs}


def split_depths(steps, depth):
    """Pad depths of a stepped house, front first. An integer splits the depth into that many equal
    pads; a list is used as given and must sum to the depth."""
    if isinstance(steps, int) and not isinstance(steps, bool):
        if steps < 2:
            raise ValueError("steps must be 2 or more")
        return [depth / steps] * steps
    if (isinstance(steps, list) and len(steps) >= 2
            and all(isinstance(s, (int, float)) and not isinstance(s, bool) and s > 0 for s in steps)):
        if abs(sum(steps) - depth) > 1e-6:
            raise ValueError("steps %s sum to %g, not the depth %g" % (steps, sum(steps), depth))
        return [float(s) for s in steps]
    raise ValueError("steps must be an integer >= 2 or a list of pad depths")
