# Pure helpers for scout_parcel.py: listing-URL parsing, APN and street matching, lon/lat geometry,
# grade statistics from a sampled elevation grid, flood and stream summaries, and triage flags.
# Plain Python 3 stdlib and no network, so tests/ covers all of it. Lon/lat rings are closed lists of
# (lon, lat); local meters come from a flat projection about a reference point, which is accurate to
# well under 1% over a few km.
import math, re, urllib.parse

from design_geom import inside, seg_dist, segs_cross

# --- listing URLs and addresses ----------------------------------------------------------------

SUFFIXES = {"AVE", "AVENUE", "BLVD", "BOULEVARD", "CIR", "CIRCLE", "CT", "COURT", "CV", "COVE", "DR", "DRIVE",
            "HWY", "HIGHWAY", "LN", "LANE", "LOOP", "PASS", "PATH", "PKWY", "PARKWAY", "PL", "PLACE", "PT", "POINT",
            "RD", "ROAD", "RUN", "SQ", "ST", "STREET", "TER", "TERRACE", "TRL", "TRAIL", "WAY", "XING", "ROW"}
DIRECTIONALS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "NORTH", "SOUTH", "EAST", "WEST"}
UNIT_WORDS = {"APT", "UNIT", "LOT", "SPC", "SPACE", "STE", "SUITE", "BLDG", "TRLR"}
STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
          "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
          "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
          "PR"}


def clean_url(url):
    """The URL without its query string and fragment (tracking parameters, share sources)."""
    p = urllib.parse.urlsplit(url.strip())
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _split_tokens(tokens):
    """Address tokens (number first, state and zip possibly last) -> dict of parts. Unit markers and
    their values are dropped; the city is whatever sits between the last street suffix and the state."""
    out = {"street_number": None, "street": "", "city": "", "state": "", "zip": "", "unit": ""}
    toks = [t for t in tokens if t]
    if toks and re.fullmatch(r"\d{5}(-\d{4})?", toks[-1]):
        out["zip"] = toks.pop()[:5]
    if toks and toks[-1].upper() in STATES:
        out["state"] = toks.pop().upper()
    clean = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.startswith("#"):
            out["unit"] = t[1:].strip("-")
        elif t.upper() in UNIT_WORDS and i + 1 < len(toks):
            out["unit"] = toks[i + 1]
            i += 1
        else:
            clean.append(t)
        i += 1
    if clean and re.fullmatch(r"\d+[A-Za-z]?(-\d+)?", clean[0]):
        out["street_number"] = clean.pop(0)
    # the first suffix after at least one name word ends the street: "Court St" and "St Andrews Dr" keep
    # their leading word, and a city like "Port St Lucie" is not mistaken for part of the street
    last = next((k for k, t in enumerate(clean) if k >= 1 and t.upper().rstrip(".") in SUFFIXES), None)
    if last is not None and last + 1 < len(clean) and clean[last + 1].upper() in DIRECTIONALS:
        last += 1  # "Main St N"
    if last is None:
        out["street"] = " ".join(clean)
    else:
        out["street"] = " ".join(clean[:last + 1])
        out["city"] = " ".join(clean[last + 1:])
    return out


def parse_listing(text):
    """A listing URL (Zillow, Redfin, Realtor.com) or a typed address -> dict with street_number,
    street, city, state, zip, unit, vacant (no real street number: missing or all zeros), url (cleaned),
    source, listing_id, and query (a geocoder-ready one-line address without the fake number)."""
    text = text.strip()
    out = None
    if re.match(r"https?://", text):
        url = clean_url(text)
        p = urllib.parse.urlsplit(url)
        parts = [urllib.parse.unquote(s) for s in p.path.split("/") if s]
        host = p.netloc.lower()
        if "zillow." in host and "homedetails" in parts:
            k = parts.index("homedetails")
            slug = parts[k + 1] if k + 1 < len(parts) else ""
            out = _split_tokens(re.split(r"-+", re.sub(r"#[^-]*", lambda m: "-" + m.group(0) + "-", slug)))
            ids = [s for s in parts if s.endswith("_zpid")]
            out.update(source="zillow", listing_id=ids[0][:-5] if ids else "")
        elif "redfin." in host and len(parts) >= 3:
            # /ST/City/123-Main-St-12345/home/678
            out = _split_tokens(re.split(r"-+", parts[2]))
            out.update(state=out["state"] or parts[0].upper(), city=out["city"] or parts[1].replace("-", " "),
                       source="redfin", listing_id=parts[4] if len(parts) > 4 and parts[3] == "home" else "")
        elif "realtor." in host and "realestateandhomes-detail" in parts:
            # /realestateandhomes-detail/123-Main-St_City-Name_ST_12345_M123-45678
            seg = parts[parts.index("realestateandhomes-detail") + 1].split("_")
            out = _split_tokens(re.split(r"-+", seg[0]))
            if len(seg) >= 4:
                out.update(city=seg[1].replace("-", " "), state=seg[2].upper(), zip=seg[3][:5])
            out.update(source="realtor", listing_id=seg[4] if len(seg) > 4 else "")
        else:
            out = _split_tokens(re.split(r"-+", parts[-1] if parts else ""))
            out.update(source=host, listing_id="")
        out["url"] = url
    else:
        # "123 Main St, Springfield, ST 12345" or without commas
        bits = [b.strip() for b in text.split(",")]
        toks = []
        for b in bits:
            toks += b.split()
        out = _split_tokens(toks)
        if len(bits) >= 3:  # commas pin the city
            out["city"] = bits[1]
            first = _split_tokens(bits[0].split())
            out["street"], out["street_number"] = first["street"], first["street_number"]
            out["unit"] = out["unit"] or first["unit"]
        out.update(source="text", listing_id="", url="")
    num = out["street_number"]
    out["vacant"] = num is None or re.fullmatch(r"0+", num) is not None
    if out["vacant"]:
        out["street_number"] = None
    out["query"] = ", ".join(x for x in (" ".join(x for x in (out["street_number"] or "", out["street"]) if x),
                                         out["city"], " ".join(x for x in (out["state"], out["zip"]) if x)) if x)
    return out


def street_core(street):
    """The distinctive words of a street name, upper case, for LIKE matching across sources that
    disagree on suffixes and directionals ("N Quiet Hawk Drive" and "QUIET HAWK DR" -> "QUIET HAWK")."""
    toks = [t.upper().rstrip(".") for t in street.split()]
    while toks and (toks[-1] in SUFFIXES or toks[-1] in DIRECTIONALS):
        toks.pop()
    while toks and toks[0] in DIRECTIONALS and len(toks) > 1:
        toks.pop(0)
    return " ".join(toks)


SUFFIX_NORM = {"AVENUE": "AVE", "BOULEVARD": "BLVD", "CIRCLE": "CIR", "COURT": "CT", "COVE": "CV", "DRIVE": "DR",
               "HIGHWAY": "HWY", "LANE": "LN", "PARKWAY": "PKWY", "PLACE": "PL", "POINT": "PT", "ROAD": "RD",
               "STREET": "ST", "TERRACE": "TER", "TRAIL": "TRL"}


def street_suffix(street):
    """The street's normalized suffix (TRAIL -> TRL), or '' when it has none."""
    toks = [t.upper().rstrip(".") for t in street.split()]
    while toks and toks[-1] in DIRECTIONALS:
        toks.pop()
    if toks and toks[-1] in SUFFIXES:
        return SUFFIX_NORM.get(toks[-1], toks[-1])
    return ""


def same_street(addr, street):
    """True when a situs address names the same street, suffix included when both have one
    ('9417 W QUIET HAWK TRAIL' matches 'Quiet Hawk Trl' but not 'Quiet Hawk Rd')."""
    core, suf = street_core(street), street_suffix(street)
    a = " ".join(addr.upper().split())
    if core not in a:
        return False
    rest = a.split(core, 1)[1].split()
    have = SUFFIX_NORM.get(rest[0].rstrip("."), rest[0].rstrip(".")) if rest else ""
    return not suf or not have or have == suf


def apn_tail_match(parcel_id, number):
    """A listing's street number is sometimes the tail of the APN (vacant lots with no situs address
    get '79 Some Rd' from APN ...079). True when the ID's last digits equal the number."""
    n = (number or "").lstrip("0")
    if len(n) < 2 or not n.isdigit():
        return False
    return "".join(ch for ch in str(parcel_id) if ch.isdigit()).endswith(n)


def apn_variants(apn):
    """Spellings to try for a parcel number: as given, upper case, and without separators. Counties
    store the same APN as 123-45-678A, 12345678A or with a book/map prefix."""
    a = apn.strip()
    out = []
    for v in (a, a.upper(), re.sub(r"[\s\-\.]", "", a.upper())):
        if v and v not in out:
            out.append(v)
    return out


def apn_like(apn):
    """A LIKE pattern that matches the APN's alphanumeric groups with any separators between them."""
    groups = re.findall(r"[A-Za-z0-9]+", apn.upper())
    return "%" + "%".join(groups) + "%" if groups else ""


def sql_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


# --- layer fields --------------------------------------------------------------------------------

ID_NAME = re.compile(r"^(APN|PARCEL.?NO|PARCEL.?NUM(BER)?|PARCEL.?ID|PARCELID|PARLABEL|PIN|PARCEL)$", re.I)
ADDR_NAME = re.compile(r"(SITUS|SITE.?ADD|PROP.?ADD|PHYS.?ADD|^ADDRESS$|FULL.?ADD)", re.I)
NOT_ADDR = re.compile(r"(MAIL|OWN|TAXPAYER|BILL)", re.I)


def guess_fields(fields, sample=None):
    """(id_field, address_field) from a layer's field list [{'name', 'type'}] and an optional sample
    attribute dict. Prefers the human-readable APN: a candidate whose sample value has separators
    (123-45-678) beats an internal key that only has digits."""
    names = [f["name"] for f in fields]
    ids = [n for n in names if ID_NAME.match(n)]

    def id_rank(n):
        v = str((sample or {}).get(n) or "")
        return (0 if re.search(r"\d[-\.]\d", v) else 1, 0 if "APN" in n.upper() else 1, names.index(n))
    id_field = sorted(ids, key=id_rank)[0] if ids else None
    addr = [f["name"] for f in fields if ADDR_NAME.search(f["name"]) and not NOT_ADDR.search(f["name"])
            and f.get("type", "esriFieldTypeString") == "esriFieldTypeString"]
    return id_field, (addr[0] if addr else None)


def rank_layer(title, owner, county, has_id, has_addr, kind="parcels"):
    """Score an ArcGIS Online search hit as the current parcel (or zoning) layer for a county. For
    zoning, has_id means the layer has a zoning field."""
    t = title.lower()
    c = county.lower().replace(" county", "").strip()
    s = 0
    s += 3 if ("parcel" if kind == "parcels" else "zon") in t else 0
    s += 2 if c and c in t else 0
    s += 1 if c and c[:4] in owner.lower() else 0
    s += 2 if has_id else -4
    s += 2 if has_addr else 0
    s -= 6 if re.search(r"histor|archive|\b(19|20)\d\d\b.*\bto\b|clipped|riparian|sold|sales", t) else 0
    return s


# --- lon/lat geometry ---------------------------------------------------------------------------

def m_per_deg(lat):
    """(meters per degree of longitude, of latitude) on WGS84 at this latitude."""
    p = math.radians(lat)
    return (111412.84 * math.cos(p) - 93.5 * math.cos(3 * p),
            111132.92 - 559.82 * math.cos(2 * p) + 1.175 * math.cos(4 * p))


class Local:
    """Flat lon/lat <-> meters about a reference point."""

    def __init__(self, lon0, lat0):
        self.lon0, self.lat0 = lon0, lat0
        self.kx, self.ky = m_per_deg(lat0)

    def xy(self, lon, lat):
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)

    def lonlat(self, x, y):
        return (self.lon0 + x / self.kx, self.lat0 + y / self.ky)

    def ring(self, ring):
        return [self.xy(*p) for p in ring]


def ring_area(ring_xy):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring_xy, ring_xy[1:]))) / 2


def outer_rings(rings_xy):
    """Esri polygon rings -> outer rings only. Esri outer rings run clockwise (negative shoelace
    sum), holes counterclockwise."""
    return [r for r in rings_xy if sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:])) < 0] or rings_xy


def parcel_shape(rings):
    """Facts about an Esri polygon in lon/lat: the largest outer ring, area (all outer rings minus
    holes), center, and the extent in meters. Returns (local projection, main ring in meters, dict)."""
    pts = [p for r in rings for p in r]
    lon0 = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
    lat0 = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
    loc = Local(lon0, lat0)
    xy = [loc.ring(r) for r in rings]
    outers = outer_rings(xy)
    holes = [r for r in xy if r not in outers]
    area = sum(ring_area(r) for r in outers) - sum(ring_area(r) for r in holes)
    main = max(outers, key=ring_area)
    xs, ys = [p[0] for p in main], [p[1] for p in main]
    info = {"acres": round(area / 4046.8564, 2), "area_m2": round(area), "parts": len(outers),
            "center_lat": round(lat0, 6), "center_lon": round(lon0, 6),
            "extent_ew_m": round(max(xs) - min(xs)), "extent_ns_m": round(max(ys) - min(ys))}
    return loc, main, info


def min_dist(line_xy, ring_xy):
    """Shortest distance between a polyline and a closed ring, 0 if they cross or the line starts inside."""
    if any(inside(x, y, ring_xy) for x, y in line_xy):
        return 0.0
    rsegs = list(zip(ring_xy, ring_xy[1:]))
    best = float("inf")
    for a, b in zip(line_xy, line_xy[1:]):
        for c, d in rsegs:
            if segs_cross(a, b, c, d):
                return 0.0
    for p in line_xy:
        for c, d in rsegs:
            best = min(best, seg_dist(p, c, d))
    for p in ring_xy:
        for a, b in zip(line_xy, line_xy[1:]):
            best = min(best, seg_dist(p, a, b))
    return best


def bbox_lonlat(loc, ring_xy, pad_m):
    xs, ys = [p[0] for p in ring_xy], [p[1] for p in ring_xy]
    lo = loc.lonlat(min(xs) - pad_m, min(ys) - pad_m)
    hi = loc.lonlat(max(xs) + pad_m, max(ys) + pad_m)
    return (lo[0], lo[1], hi[0], hi[1])


# --- terrain from a sampled grid ----------------------------------------------------------------

def sample_grid(loc, ring_xy, max_points=900, min_step=5.0):
    """A regular grid over the ring's bbox plus one cell, spaced so it stays under max_points.
    Returns (step m, nx, ny, x0, y0, [(lon, lat)] row-major from the south-west corner)."""
    xs, ys = [p[0] for p in ring_xy], [p[1] for p in ring_xy]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    step = max(min_step, math.sqrt(max(w * h, 1.0) / max_points))
    while (int(w / step) + 3) * (int(h / step) + 3) > max_points:
        step *= 1.1
    nx, ny = int(w / step) + 3, int(h / step) + 3
    x0, y0 = min(xs) - step, min(ys) - step
    pts = [loc.lonlat(x0 + i * step, y0 + j * step) for j in range(ny) for i in range(nx)]
    return step, nx, ny, x0, y0, pts


def compass8(bearing):
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int(((bearing % 360) + 22.5) // 45) % 8]


def terrain_stats(z, step, nx, ny, x0, y0, ring_xy):
    """Elevation and grade statistics for the grid nodes inside the ring. z is row-major (None where
    the service had no data). Grade at a node uses central differences; the best-fit plane over the
    inside nodes gives the overall grade and which way the lot faces (downhill compass direction)."""
    def Z(i, j):
        return z[j * nx + i] if 0 <= i < nx and 0 <= j < ny else None
    ins = [(i, j) for j in range(ny) for i in range(nx)
           if inside(x0 + i * step, y0 + j * step, ring_xy) and Z(i, j) is not None]
    if len(ins) < 3:
        return None
    vals = [Z(i, j) for i, j in ins]
    grades = []
    for i, j in ins:
        l, r, d, u = Z(i - 1, j), Z(i + 1, j), Z(i, j - 1), Z(i, j + 1)
        if None in (l, r, d, u):
            continue
        grades.append(100 * math.hypot((r - l) / (2 * step), (u - d) / (2 * step)))
    # least squares z = a x + b y + c over the inside nodes
    n = len(ins)
    X = [x0 + i * step for i, _ in ins]
    Y = [y0 + j * step for _, j in ins]
    mx, my, mz = sum(X) / n, sum(Y) / n, sum(vals) / n
    sxx = sum((x - mx) ** 2 for x in X)
    syy = sum((y - my) ** 2 for y in Y)
    sxy = sum((x - mx) * (y - my) for x, y in zip(X, Y))
    sxz = sum((x - mx) * (v - mz) for x, v in zip(X, vals))
    syz = sum((y - my) * (v - mz) for y, v in zip(Y, vals))
    det = sxx * syy - sxy * sxy
    a = (sxz * syy - syz * sxy) / det if det else 0.0
    b = (syz * sxx - sxz * sxy) / det if det else 0.0
    downhill = math.degrees(math.atan2(-a, -b)) % 360
    g = sorted(grades)

    def pct(p):
        return round(g[min(len(g) - 1, int(p / 100 * len(g)))], 1) if g else None
    return {"elev_min_m": round(min(vals), 1), "elev_max_m": round(max(vals), 1),
            "elev_mean_m": round(mz, 1), "relief_m": round(max(vals) - min(vals), 1),
            "grade_median_pct": pct(50), "grade_p90_pct": pct(90),
            "pct_area_grade_under_15": round(100 * sum(1 for v in g if v < 15) / len(g)) if g else None,
            "pct_area_grade_under_25": round(100 * sum(1 for v in g if v < 25) / len(g)) if g else None,
            "fit_grade_pct": round(100 * math.hypot(a, b), 1),
            "faces": compass8(downhill) if math.hypot(a, b) > 0.02 else "flat",
            "faces_deg": round(downhill), "sample_step_m": round(step, 1), "samples_inside": n}


def share_inside(rings_by_feature, loc, step, nx, ny, x0, y0, ring_xy):
    """For each feature (a list of lon/lat rings, holes included, even-odd), the share of the parcel's
    grid nodes that fall inside it. Returns a list of fractions in feature order."""
    nodes = [(x0 + i * step, y0 + j * step) for j in range(ny) for i in range(nx)]
    nodes = [p for p in nodes if inside(p[0], p[1], ring_xy)]
    if not nodes:
        return [0.0 for _ in rings_by_feature]
    out = []
    for rings in rings_by_feature:
        xy = [loc.ring(r) for r in rings]
        hit = sum(1 for x, y in nodes if sum(inside(x, y, r) for r in xy) % 2 == 1)
        out.append(hit / len(nodes))
    return out


FCODE = {46000: "stream", 46003: "intermittent stream", 46006: "perennial stream", 46007: "ephemeral stream",
         55800: "river centerline", 33600: "canal", 33400: "connector", 42800: "pipeline"}


def stream_kind(fcode):
    try:
        return FCODE.get(int(fcode), "flowline")
    except (TypeError, ValueError):
        return "flowline"


# --- triage --------------------------------------------------------------------------------------

def flags(rep):
    """Short warnings for a report dict, most important first."""
    out = []
    fl = rep.get("flood") or {}
    if fl.get("status") != "ok":
        out.append("flood zone unverified")
    else:
        if fl.get("pct_floodway", 0) > 0:
            out.append("%d%% in a regulatory floodway" % fl["pct_floodway"])
        if fl.get("pct_sfha", 0) > 0:
            out.append("%d%% in the 1%% annual chance floodplain (SFHA)" % fl["pct_sfha"])
    t = rep.get("terrain") or {}
    if t:
        if t.get("pct_area_grade_under_15") is not None and t["pct_area_grade_under_15"] < 10:
            out.append("under 10% of the lot is below a 15% grade")
        elif t.get("grade_median_pct") is not None and t["grade_median_pct"] >= 30:
            out.append("steep: median grade %s%%" % t["grade_median_pct"])
    else:
        out.append("no elevation samples")
    r = rep.get("roads") or {}
    if r.get("status") == "ok" and (r.get("nearest_m") is None or r["nearest_m"] > 30):
        out.append("no mapped road within 30 m (access may be by easement or unmapped road)")
    s = rep.get("streams") or {}
    if s.get("status") == "ok" and s.get("nearest_m") is not None and s["nearest_m"] <= 30:
        what = " ".join(x for x in (s.get("nearest_name"), s.get("nearest_kind")) if x) or "a stream"
        out.append("%s crosses the parcel" % what if s["nearest_m"] == 0 else "%s within %d m" % (what, s["nearest_m"]))
    if rep.get("lidar") is not None and not rep["lidar"]:
        out.append("no 1 m lidar")
    return out


def rank_candidates(cands, acres=None, tol=0.05, number=None):
    """Sort parcel candidates (dicts with id, acres and dist_m): an ID whose tail is the listing's
    street number first, then acreage match, then distance. With acres given, drop those more than
    tol (fraction) off."""
    if acres:
        cands = [c for c in cands if abs(c["acres"] - acres) <= tol * acres]
    return sorted(cands, key=lambda c: (0 if apn_tail_match(c["id"], number) else 1,
                                        abs(c["acres"] - acres) / acres if acres else 0, c.get("dist_m") or 0))
