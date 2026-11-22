# Triage land listings before any Blender work: find the parcel behind a listing (including vacant lots
# with no street address), then report the facts that decide whether it is worth a closer look --
# size, terrain and grade, which way it faces, lidar coverage, flood zones, streams, road access, and
# zoning. Plain Python 3 stdlib (plus scout_geo.py and design_geom.py next to it). Every lookup is cached,
# so a batch of hundreds of listings re-runs cheaply and a county's parcel layer is discovered once.
#
#   python scout_parcel.py listing URL_OR_ADDRESS [--acres A] [--apn APN] [--json FILE]
#       Parse a listing link (Zillow, Redfin, Realtor.com; tracking parameters dropped) or a typed address,
#       find the county and its parcel layer, then the parcel: by APN when given, by street address when
#       the listing has a real number, otherwise among parcels near that street matching --acres.
#       One clear match is reported; several are listed as candidates.
#   python scout_parcel.py report --layer URL --id-field FIELD --id VALUE [--json FILE]
#   python scout_parcel.py init PARCEL_DIR --layer URL --id-field FIELD --id VALUE [--force]
#       Write the four-key parcel.json that fetch_gis.py needs, plus scout.json and notes.md.
#   python scout_parcel.py batch IN.csv OUT.csv [--reports DIR]
#       One row per listing. Columns (header required, any order, blanks allowed): name, listing
#       (URL or address), acres, apn, layer, id_field. Writes a summary row per listing.
#   Options for all: --cache FILE (default parcels/_scout_cache.json beside templates/),
#       --zoning-layer URL (else discovered per county), --no-discover (use only cached or given layers)
#
# Services: ArcGIS Online search (county parcel and zoning layers), Census geocoder (county from a
# point), OpenStreetMap Nominatim (city and street points, at most one request per second), USGS 3DEP
# getSamples (elevations), USGS NHD (streams), Census TIGERweb (roads), and FEMA flood zones via Esri's
# public mirror with FEMA's own NFHL service as the fallback. Parcel queries request only the ID and
# situs-address fields, never owner names.
import csv, json, os, sys, time, urllib.error, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scout_geo as G

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE = os.path.join(HERE, "..", "parcels", "_scout_cache.json")
UA = "compound-designer-scout/1.0 (+https://github.com/sampanes/compound-designer)"
AGOL_SEARCH = "https://www.arcgis.com/sharing/rest/search"
CENSUS_COUNTY = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
DEM_SAMPLES = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/getSamples"
DEM_IDENTIFY = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/identify"
NHD_FLOWLINES = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query"
TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer/%d/query"
TIGER_LAYERS = (2, 6, 8)  # primary, secondary, local roads
FLOOD_LAYERS = ("https://services5.arcgis.com/7weheFjxuNkGGiZi/arcgis/rest/services/USA_Flood_Hazard_Areas_view/FeatureServer/0/query",
                "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query")
USAGE = """usage:
  python scout_parcel.py listing URL_OR_ADDRESS [--acres A] [--apn APN] [--layer URL [--id-field F]] [--json FILE]
  python scout_parcel.py report --layer URL [--id-field F] --id VALUE [--json FILE]
  python scout_parcel.py init PARCEL_DIR --layer URL [--id-field F] --id VALUE [--force]
  python scout_parcel.py batch IN.csv OUT.csv [--reports DIR]
  options: --cache FILE  --zoning-layer URL  --no-discover   (details in the header of scout_parcel.py)"""


class ScoutError(Exception):
    pass


# --- HTTP and cache ------------------------------------------------------------------------------

_last_nominatim = [0.0]


def http_json(url, params, post=False, tries=3):
    """GET (or POST for long geometries) and parse JSON. Retries connection resets and 5xx with
    backoff; an ArcGIS {"error": ...} reply raises ScoutError."""
    data = urllib.parse.urlencode(params).encode()
    last = None
    for k in range(tries):
        try:
            if post:
                req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            else:
                req = urllib.request.Request(url + "?" + data.decode(), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read()
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last = e
            if isinstance(e, urllib.error.HTTPError) and e.code < 500:
                break
            if k + 1 < tries:
                time.sleep(2 ** k)
            continue
        try:
            out = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            raise ScoutError("%s: reply is not JSON (a bot challenge page?): %r" % (url, body[:80]))
        if isinstance(out, dict) and "error" in out:
            raise ScoutError("%s: %s" % (url, out["error"]))
        return out
    raise ScoutError("%s: %s" % (url, last))


class Cache:
    def __init__(self, path):
        self.path = path
        self.d = {}
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.d = json.load(f)

    def get(self, key):
        return self.d.get(key)

    def put(self, key, value):
        self.d[key] = value
        if self.path:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        return value


# --- where is it ---------------------------------------------------------------------------------

def geocode(cache, **q):
    """Nominatim structured search (street, city, state, postalcode) -> (lat, lon) or None. Cached,
    and spaced at least 1.1 s apart as its usage policy asks."""
    q = {k: v for k, v in q.items() if v}
    key = "geocode|" + json.dumps(q, sort_keys=True)
    hit = cache.get(key)
    if hit is not None:
        return tuple(hit) if hit else None
    wait = 1.1 - (time.time() - _last_nominatim[0])
    if wait > 0:
        time.sleep(wait)
    _last_nominatim[0] = time.time()
    res = http_json(NOMINATIM, dict(q, countrycodes="us", format="json", limit=1))
    val = [float(res[0]["lat"]), float(res[0]["lon"])] if res else []
    cache.put(key, val)
    return tuple(val) if val else None


def county_at(cache, lat, lon):
    """(county name, state FIPS, county GEOID) for a point, from the Census geocoder."""
    key = "county|%.3f,%.3f" % (lat, lon)
    hit = cache.get(key)
    if hit:
        return tuple(hit)
    res = http_json(CENSUS_COUNTY, {"x": lon, "y": lat, "benchmark": "Public_AR_Current",
                                    "vintage": "Current_Current", "layers": "Counties", "format": "json"})
    cs = res.get("result", {}).get("geographies", {}).get("Counties", [])
    if not cs:
        raise ScoutError("no county at %.5f, %.5f" % (lat, lon))
    return tuple(cache.put(key, [cs[0]["NAME"], cs[0]["STATE"], cs[0]["GEOID"]]))


def polygon_layers(url):
    """[(layer url, layer info)] for a layer URL, or for every polygon layer under a service root."""
    url = url.rstrip("/")
    info = http_json(url, {"f": "json"})
    if "fields" in info:
        return [(url, info)]
    out = []
    for l in info.get("layers", []):
        if l.get("geometryType") in (None, "esriGeometryPolygon"):
            sub = http_json("%s/%d" % (url, l["id"]), {"f": "json"})
            if sub.get("geometryType") == "esriGeometryPolygon":
                out.append(("%s/%d" % (url, l["id"]), sub))
    if not out:
        raise ScoutError("%s has no polygon layer" % url)
    return out


def layer_info(url):
    """The first polygon layer at a URL (a service root resolves to its first polygon layer)."""
    return polygon_layers(url)[0]


def sample_attrs(url, fields):
    try:
        res = http_json(url + "/query", {"where": "1=1", "outFields": ",".join(fields), "returnGeometry": "false",
                                         "resultRecordCount": 1, "f": "json"})
        feats = res.get("features") or []
        return feats[0]["attributes"] if feats else {}
    except ScoutError:
        return {}


def find_layer(cache, county, kind="parcels", discover=True):
    """The parcel (or zoning) layer for a county (name, state FIPS, GEOID): cached, else the best-ranked
    ArcGIS Online hit. Returns {url, id_field, addr_field} for parcels or {url, layers: [{url, fields}]}
    for zoning (every polygon layer of the service with a zoning field, tried in order), plus title,
    owner and score; None when nothing fits. To pin a layer by hand, put such a dict in the cache
    under 'layer|<kind>|<county GEOID>'."""
    name = county[0]
    key = "layer|%s|%s" % (kind, county[2])
    hit = cache.get(key)
    if hit is not None or not discover:
        return hit or None
    res = http_json(AGOL_SEARCH, {"q": '"%s" %s type:"Feature Service"' % (name.replace(" County", ""), kind),
                                  "num": 20, "f": "json"})
    found = []
    for item in res.get("results", [])[:12]:
        if not item.get("url"):
            continue
        try:
            subs = polygon_layers(item["url"])
        except ScoutError:
            continue
        if kind == "parcels":
            url, info = subs[0]
            fields = info.get("fields", [])
            names = [f["name"] for f in fields if G.ID_NAME.match(f["name"]) or G.ADDR_NAME.search(f["name"])]
            idf, addr = G.guess_fields(fields, sample_attrs(url, names) if names else {})
            score = G.rank_layer(item["title"], item.get("owner", ""), name, idf is not None, addr is not None)
            cand = {"url": url, "id_field": idf, "addr_field": addr}
        else:
            layers = [{"url": u, "fields": [f["name"] for f in i.get("fields", []) if "ZON" in f["name"].upper()]}
                      for u, i in subs]
            layers = [l for l in layers if l["fields"]]
            score = G.rank_layer(item["title"], item.get("owner", ""), name, bool(layers), True, kind)
            cand = {"url": layers[0]["url"] if layers else subs[0][0], "layers": layers}
        cand.update(title=item["title"], owner=item.get("owner", ""), score=score)
        found.append(cand)
    found = sorted([c for c in found if c["score"] >= 3], key=lambda c: -c["score"])
    if not found:
        cache.put(key, {})
        return None
    # copies of a county's parcels are often partial or stale, so keep the runners-up to fall back on
    best = dict(found[0], alternates=found[1:4])
    return cache.put(key, best)


# --- parcels -------------------------------------------------------------------------------------

def query_parcels(layer, where, extra=None, page=1000, max_pages=5):
    """Features (attributes + lon/lat rings) for a where clause, paging through big results."""
    out = []
    fields = ",".join(f for f in (layer["id_field"], layer.get("addr_field")) if f)
    for k in range(max_pages):
        params = {"where": where, "outFields": fields, "returnGeometry": "true", "outSR": 4326,
                  "geometryPrecision": 7, "resultOffset": k * page, "resultRecordCount": page, "f": "json"}
        params.update(extra or {})
        res = http_json(layer["url"] + "/query", params, post=True)
        feats = [f for f in res.get("features", []) if f.get("geometry", {}).get("rings")]
        out += feats
        if not res.get("exceededTransferLimit"):
            break
    return out


def by_apn(layer, apn):
    f = layer["id_field"]
    for v in G.apn_variants(apn):
        feats = query_parcels(layer, "%s = %s" % (f, G.sql_quote(v)))
        if feats:
            return feats
    pat = G.apn_like(apn)
    return query_parcels(layer, "UPPER(%s) LIKE %s" % (f, G.sql_quote(pat))) if pat else []


def candidate(feat, layer, ref=None):
    loc, main, shape = G.parcel_shape(feat["geometry"]["rings"])
    c = {"id": str(feat["attributes"].get(layer["id_field"])), "acres": shape["acres"],
         "address": (feat["attributes"].get(layer.get("addr_field")) or "").strip() if layer.get("addr_field") else "",
         "lat": shape["center_lat"], "lon": shape["center_lon"]}
    if ref:
        kx, ky = G.m_per_deg(ref[0])
        c["dist_m"] = round(((c["lon"] - ref[1]) ** 2 * kx * kx + (c["lat"] - ref[0]) ** 2 * ky * ky) ** 0.5)
    return c


def counties_near(cache, lat, lon, km=12):
    """Counties at the point and at eight points km away, the point's own county first."""
    kx, ky = G.m_per_deg(lat)
    pts = [(lat, lon)] + [(lat + km * 1000 * dy / ky, lon + km * 1000 * dx / kx)
                          for dx, dy in ((0, 1), (0.7, 0.7), (1, 0), (0.7, -0.7), (0, -1), (-0.7, -0.7), (-1, 0), (-0.7, 0.7))]
    out = []
    for p in pts:
        try:
            c = county_at(cache, *p)
        except ScoutError:
            continue
        if c not in out:
            out.append(c)
    return out


def street_hits(layer, street):
    """Parcels whose situs address names the street; the suffix narrows it when that leaves any
    (QUIET HAWK TRL, not QUIET HAWK RD)."""
    addr, core = layer.get("addr_field"), G.street_core(street)
    if not core or not addr:
        return []
    feats = query_parcels(layer, "UPPER(%s) LIKE %s" % (addr, G.sql_quote("%" + core + "%")))
    same = [f for f in feats if G.same_street(f["attributes"].get(addr) or "", street)]
    return same or feats


def exact_number(feats, layer, num):
    """The features whose situs address starts with the street number."""
    addr = layer.get("addr_field")
    return [f for f in feats if (f["attributes"].get(addr) or "").strip().upper().split(" ")[:1] == [num]]


def locate(cache, parsed, acres=None, apn=None, layer=None, discover=True, radius_m=1500):
    """Find the county, its parcel layer, and the parcel for a parsed listing. Returns a dict with
    county, layer, status ('found', 'ambiguous', 'not_found') and candidates (best first)."""
    out = {"listing": parsed, "candidates": []}
    pt = None
    if parsed.get("street"):
        pt = geocode(cache, street=" ".join(x for x in (parsed.get("street_number"), parsed["street"]) if x),
                     city=parsed.get("city"), state=parsed.get("state"))
    if pt is None and parsed.get("city"):
        pt = geocode(cache, city=parsed["city"], state=parsed.get("state"))
    if pt is None and parsed.get("zip"):
        pt = geocode(cache, postalcode=parsed["zip"], state=parsed.get("state"))
    if pt is None and layer is None:
        raise ScoutError("could not place %r (no street, city, or zip that geocodes)" % parsed.get("query"))
    core = G.street_core(parsed.get("street", ""))
    # Towns sit near county lines (and a city's center can be in a different county than the lot), so
    # look for the street in the parcel layer of every county near the point and keep the one that has it.
    tried = []
    street_feats = []
    num = (parsed.get("street_number") or "").upper()
    if layer is None:
        # A street name can repeat across counties, so with a street number, a county whose parcels have
        # the street but not the number is only a fallback.
        fallback = None
        for county in counties_near(cache, *pt):
            lay = find_layer(cache, county, discover=discover)
            tried.append(county[0] + ("" if lay and lay.get("id_field") else " (no parcel layer)"))
            if not lay or not lay.get("id_field"):
                continue
            if layer is None:
                layer, out["county"] = lay, list(county)
            if apn:
                if by_apn(lay, apn):
                    layer, out["county"] = lay, list(county)
                    break
                continue
            for alt in [lay] + [a for a in lay.get("alternates", []) if a.get("id_field")]:
                hits = street_hits(alt, parsed.get("street", ""))
                if hits and num and not exact_number(hits, alt, num):
                    fallback = fallback or (alt, list(county), hits)
                elif hits:
                    layer, out["county"], street_feats = alt, list(county), hits
                    break
            if street_feats:
                break
        if not street_feats and fallback:
            layer, out["county"], street_feats = fallback
        if layer is None:
            raise ScoutError("no parcel layer found for %s; pass --layer and --id-field, or pin one in the cache"
                             % ", ".join(tried))
    else:
        if pt:
            out["county"] = list(county_at(cache, *pt))
        street_feats = [] if apn else street_hits(layer, parsed.get("street", ""))
    out["layer"] = layer
    out["counties_tried"] = tried
    if apn:
        feats = by_apn(layer, apn)
        out["candidates"] = [candidate(f, layer, pt) for f in feats]
        out["status"] = "found" if len(feats) == 1 else ("ambiguous" if feats else "not_found")
        out["matched_by"] = "apn"
        return out
    if num and street_feats:
        exact = exact_number(street_feats, layer, num)
        if exact:
            out["candidates"] = [candidate(f, layer, pt) for f in exact]
            out["status"] = "found" if len(exact) == 1 else "ambiguous"
            out["matched_by"] = "address"
            return out
    # vacant land or no exact number: parcels near the street by acreage. Without the street in the
    # parcel data the search center is only a geocoded point, so nothing found that way is "found".
    if street_feats:
        cs = [candidate(f, layer) for f in street_feats]
        ref = (sum(c["lat"] for c in cs) / len(cs), sum(c["lon"] for c in cs) / len(cs))
        lats, lons = [c["lat"] for c in cs], [c["lon"] for c in cs]
    elif pt:
        ref, lats, lons = pt, [pt[0]], [pt[1]]
        out["note"] = "street %r not in the parcel data of %s; candidates are by acreage near a geocoded point" % (
            core, ", ".join(tried) or (out.get("county") or ["the given layer"])[0])
    else:
        out["status"] = "not_found"
        return out
    out["search_center"] = [round(ref[0], 6), round(ref[1], 6)]
    if not acres:
        out["candidates"] = G.rank_candidates([candidate(f, layer, ref) for f in street_feats],
                                              number=parsed.get("street_number"))
        out["status"] = "ambiguous" if out["candidates"] else "not_found"
        out["matched_by"] = "street (pass --acres or --apn to pick one)"
        return out
    kx, ky = G.m_per_deg(ref[0])
    box = (min(lons) - radius_m / kx, min(lats) - radius_m / ky, max(lons) + radius_m / kx, max(lats) + radius_m / ky)
    feats = query_parcels(layer, "1=1", {"geometry": "%f,%f,%f,%f" % box, "geometryType": "esriGeometryEnvelope",
                                         "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"})
    num = parsed.get("street_number")
    cands = G.rank_candidates([candidate(f, layer, ref) for f in feats], acres, number=num)
    out["candidates"] = cands
    out["matched_by"] = "acreage within %d m of %s" % (radius_m, "the street" if street_feats else "a geocoded point")
    if not cands:
        out["status"] = "not_found"
    elif street_feats and (len(cands) == 1 or G.apn_tail_match(cands[0]["id"], num) and not G.apn_tail_match(cands[1]["id"], num)
                           or abs(cands[1]["acres"] - acres) > 2 * abs(cands[0]["acres"] - acres) + 0.01 * acres):
        out["status"] = "found"
        if G.apn_tail_match(cands[0]["id"], num):
            out["matched_by"] += "; the listing number is the tail of the APN"
    else:
        out["status"] = "ambiguous"
    return out


# --- report --------------------------------------------------------------------------------------

def report(cache, layer, parcel_id, zoning_layer=None, discover=True):
    """Everything worth knowing before downloading a site: shape, terrain, lidar, flood, streams,
    roads, zoning, and triage flags. Each section has a status so one flaky service never sinks the rest."""
    feats = by_apn(layer, parcel_id)
    if not feats:
        raise ScoutError("no parcel %s = %r in %s" % (layer["id_field"], parcel_id, layer["url"]))
    rings = [r for f in feats for r in f["geometry"]["rings"]]
    loc, main, shape = G.parcel_shape(rings)
    rep = {"parcel_id": str(feats[0]["attributes"].get(layer["id_field"])), "layer": layer["url"],
           "id_field": layer["id_field"], "shape": shape,
           "address": (feats[0]["attributes"].get(layer.get("addr_field")) or "").strip() if layer.get("addr_field") else ""}
    poly = json.dumps({"rings": [[list(p) for p in r] for r in rings], "spatialReference": {"wkid": 4326}})
    try:
        rep["county"] = list(county_at(cache, shape["center_lat"], shape["center_lon"]))
    except ScoutError as e:
        rep["county"] = None
        print("[!] county: %s" % e)

    # terrain from a sampled grid
    step, nx, ny, x0, y0, pts = G.sample_grid(loc, main)
    grid = (step, nx, ny, x0, y0)
    try:
        res = http_json(DEM_SAMPLES, {"geometry": json.dumps({"points": [list(p) for p in pts], "spatialReference": {"wkid": 4326}}),
                                      "geometryType": "esriGeometryMultipoint", "returnFirstValueOnly": "true",
                                      "interpolation": "RSP_BilinearInterpolation", "f": "json"}, post=True)
        z = [None] * len(pts)
        for s in res.get("samples", []):
            try:
                v = float(s["value"])
                z[int(s["locationId"])] = v if v > -1000 else None
            except (KeyError, TypeError, ValueError):
                pass
        rep["terrain"] = G.terrain_stats(z, *grid, main)
    except ScoutError as e:
        rep["terrain"] = None
        print("[!] terrain: %s" % e)

    # 1 m lidar coverage at the center
    try:
        res = http_json(DEM_IDENTIFY, {"geometry": json.dumps({"x": shape["center_lon"], "y": shape["center_lat"], "spatialReference": {"wkid": 4326}}),
                                       "geometryType": "esriGeometryPoint", "returnCatalogItems": "true",
                                       "returnGeometry": "false", "f": "json"})
        items = res.get("catalogItems", {}).get("features", [])
        rep["lidar"] = sorted({i["attributes"].get("Name") for i in items
                               if (i["attributes"].get("LowPS") or 99) <= 1 and i["attributes"].get("Name")})
    except ScoutError as e:
        rep["lidar"] = None
        print("[!] lidar: %s" % e)

    # flood zones: share of the parcel in each
    flood = {"status": "unverified"}
    for url in FLOOD_LAYERS:
        try:
            res = http_json(url, {"geometry": poly, "geometryType": "esriGeometryPolygon", "inSR": 4326,
                                  "spatialRel": "esriSpatialRelIntersects", "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
                                  "returnGeometry": "true", "outSR": 4326, "maxAllowableOffset": 0.00002,
                                  "geometryPrecision": 6, "f": "json"}, post=True)
        except ScoutError as e:
            print("[!] flood (%s): %s" % (url.split("/")[2], e))
            continue
        feats_f = [f for f in res.get("features", []) if f.get("geometry", {}).get("rings")]
        shares = G.share_inside([f["geometry"]["rings"] for f in feats_f], loc, *grid, main)
        zones, sfha, fway = {}, 0.0, 0.0
        for f, s in zip(feats_f, shares):
            a = f["attributes"]
            name = a.get("FLD_ZONE") or "?"
            if a.get("ZONE_SUBTY"):
                name += " (%s)" % a["ZONE_SUBTY"].lower()
            zones[name] = zones.get(name, 0) + s
            sfha += s if a.get("SFHA_TF") == "T" else 0
            fway += s if "FLOODWAY" in (a.get("ZONE_SUBTY") or "").upper() else 0
        flood = {"status": "ok", "source": url.split("/")[2],
                 "zones_pct": {k: max(1, round(100 * v)) for k, v in sorted(zones.items()) if v > 0},
                 "pct_sfha": round(100 * min(sfha, 1)), "pct_floodway": round(100 * min(fway, 1)),
                 "note": "" if feats_f else "no mapped flood zone here (possibly unstudied; check the FIRM panel)"}
        break
    rep["flood"] = flood

    # streams and roads near the parcel
    box = G.bbox_lonlat(loc, main, 300)
    env = {"geometry": "%f,%f,%f,%f" % box, "geometryType": "esriGeometryEnvelope", "inSR": 4326,
           "spatialRel": "esriSpatialRelIntersects", "returnGeometry": "true", "outSR": 4326, "f": "json"}
    try:
        res = http_json(NHD_FLOWLINES, dict(env, outFields="gnis_name,fcode"))
        best = None
        named = None
        for f in res.get("features", []):
            for path in f["geometry"].get("paths", []):
                d = G.min_dist(loc.ring(path), main)
                a = f["attributes"]
                item = (d, a.get("gnis_name") or "", G.stream_kind(a.get("fcode")))
                best = item if best is None or d < best[0] else best
                if item[1] and (named is None or d < named[0]):
                    named = item
        rep["streams"] = {"status": "ok", "nearest_m": round(best[0]) if best else None,
                          "nearest_name": best[1] if best else "", "nearest_kind": best[2] if best else "",
                          "nearest_named": named[1] if named else "", "nearest_named_m": round(named[0]) if named else None}
    except ScoutError as e:
        rep["streams"] = {"status": "unverified"}
        print("[!] streams: %s" % e)
    try:
        best = None
        for lid in TIGER_LAYERS:
            res = http_json(TIGER % lid, dict(env, outFields="NAME,MTFCC"))
            for f in res.get("features", []):
                for path in f["geometry"].get("paths", []):
                    d = G.min_dist(loc.ring(path), main)
                    if best is None or d < best[0]:
                        best = (d, f["attributes"].get("NAME") or "(unnamed)", f["attributes"].get("MTFCC") or "")
        rep["roads"] = {"status": "ok", "nearest_m": round(best[0]) if best else None,
                        "nearest_name": best[1] if best else "", "mtfcc": best[2] if best else ""}
    except ScoutError as e:
        rep["roads"] = {"status": "unverified"}
        print("[!] roads: %s" % e)

    # zoning
    zl = zoning_layer
    if zl is None and rep.get("county"):
        zl = find_layer(cache, rep["county"], kind="zoning", discover=discover)
    if zl:
        try:
            vals, used = [], zl["url"]
            for lay in zl.get("layers") or [{"url": zl["url"], "fields": ["*"]}]:
                res = http_json(lay["url"] + "/query", {"geometry": poly, "geometryType": "esriGeometryPolygon",
                                                        "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                                                        "outFields": ",".join(lay["fields"] or ["*"]),
                                                        "returnGeometry": "false", "f": "json"}, post=True)
                vals = sorted({" ".join(str(v) for k, v in f["attributes"].items() if v not in (None, "", " "))
                               for f in res.get("features", [])})
                if vals:
                    used = lay["url"]
                    break
            rep["zoning"] = {"status": "ok", "values": vals, "layer": used}
        except ScoutError as e:
            rep["zoning"] = {"status": "unverified"}
            print("[!] zoning: %s" % e)
    else:
        rep["zoning"] = {"status": "no layer"}
    rep["flags"] = G.flags(rep)
    return rep


def print_report(rep):
    s, t = rep["shape"], rep.get("terrain") or {}
    print("[PARCEL] %s = %s  %.2f ac  %d x %d m  center %.6f, %.6f%s" % (
        rep["id_field"], rep["parcel_id"], s["acres"], s["extent_ew_m"], s["extent_ns_m"], s["center_lat"],
        s["center_lon"], "  (%d parts)" % s["parts"] if s["parts"] > 1 else ""))
    if rep.get("county"):
        print("[COUNTY] %s" % rep["county"][0])
    if t:
        print("[TERRAIN] %s-%s m, relief %s m; grade median %s%%, p90 %s%%; %s%% under 15%%; faces %s" % (
            t["elev_min_m"], t["elev_max_m"], t["relief_m"], t["grade_median_pct"], t["grade_p90_pct"],
            t["pct_area_grade_under_15"], t["faces"]))
    print("[LIDAR] %s" % (", ".join(rep["lidar"]) if rep.get("lidar") else "none at 1 m" if rep.get("lidar") == [] else "unverified"))
    fl = rep["flood"]
    zones = ", ".join("%s %d%%" % kv for kv in fl.get("zones_pct", {}).items()) or "none"
    print("[FLOOD] %s" % (("%s %s" % (zones, fl["note"])).strip() if fl["status"] == "ok" else "unverified"))
    st = rep.get("streams") or {}
    if st.get("status") == "ok" and st.get("nearest_m") is None:
        print("[STREAM] none within 300 m")
    elif st.get("status") == "ok":
        print("[STREAM] nearest %s m (%s); nearest named: %s" % (
            st["nearest_m"], " ".join(x for x in (st["nearest_name"], st["nearest_kind"]) if x),
            "%s at %s m" % (st["nearest_named"], st["nearest_named_m"]) if st["nearest_named"] else "none within 300 m"))
    rd = rep.get("roads") or {}
    if rd.get("status") == "ok":
        print("[ROAD] %s" % ("nearest %s m: %s" % (rd["nearest_m"], rd["nearest_name"]) if rd["nearest_m"] is not None
                             else "none within 300 m"))
    z = rep.get("zoning") or {}
    print("[ZONING] %s" % ("; ".join(z.get("values") or []) or
                          ("no zoning polygon here (a city may zone it)" if z.get("status") == "ok" else z.get("status"))))
    for f in rep["flags"]:
        print("[FLAG] %s" % f)


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# --- commands ------------------------------------------------------------------------------------

def opt(args, name, default=None):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def given_layer(args):
    url = opt(args, "--layer")
    if not url:
        return None
    url, info = layer_info(url)
    names = [f["name"] for f in info.get("fields", [])]
    idf = opt(args, "--id-field")
    cands = [n for n in names if G.ID_NAME.match(n) or G.ADDR_NAME.search(n)]
    gid, addr = G.guess_fields(info.get("fields", []), sample_attrs(url, cands) if cands else {})
    idf = idf or gid
    if idf not in names:
        raise ScoutError("--id-field %r is not a field of %s (fields: %s)" % (idf, url, ", ".join(names)))
    return {"url": url, "id_field": idf, "addr_field": addr}


def zoning_arg(args):
    url = opt(args, "--zoning-layer")
    if not url:
        return None
    layers = [{"url": u, "fields": [f["name"] for f in i.get("fields", []) if "ZON" in f["name"].upper()]}
              for u, i in polygon_layers(url)]
    return {"url": layers[0]["url"], "layers": layers}


def run_listing(cache, text, acres=None, apn=None, layer=None, zoning=None, discover=True):
    parsed = G.parse_listing(text)
    print("[LISTING] %s%s" % (parsed["query"], "  (vacant: no street number)" if parsed["vacant"] else ""))
    if parsed.get("url"):
        print("[URL] %s" % parsed["url"])
    loc = locate(cache, parsed, acres=acres, apn=apn, layer=layer, discover=discover)
    if loc.get("county"):
        print("[COUNTY] %s" % loc["county"][0])
    print("[LAYER] %s (id %s, address %s)" % (loc["layer"]["url"], loc["layer"]["id_field"], loc["layer"].get("addr_field")))
    for c in loc["candidates"][:8]:
        print("[CAND] %s  %.2f ac  %s  %s" % (c["id"], c["acres"], ("%d m away" % c["dist_m"]) if "dist_m" in c else "",
                                               c["address"] or "(no situs address)"))
    print("[MATCH] %s by %s" % (loc["status"], loc.get("matched_by", "-")))
    if loc.get("note"):
        print("[!] %s" % loc["note"])
    if loc["status"] == "found":
        loc["report"] = report(cache, loc["layer"], loc["candidates"][0]["id"], zoning, discover)
        print_report(loc["report"])
    return loc


CSV_COLS = ["name", "listing", "status", "county", "parcel_id", "acres", "elev_min_m", "elev_max_m", "relief_m",
            "grade_median_pct", "pct_area_grade_under_15", "faces", "pct_sfha", "pct_floodway", "nearest_stream",
            "stream_m", "nearest_road", "road_m", "lidar_1m", "zoning", "flags", "candidates", "layer", "id_field",
            "error"]


def summary_row(name, text, loc=None, err=""):
    row = dict.fromkeys(CSV_COLS, "")
    row.update(name=name, listing=text, error=err, status="error" if err else "")
    if not loc:
        return row
    rep = loc.get("report") or {}
    t, fl, st, rd = rep.get("terrain") or {}, rep.get("flood") or {}, rep.get("streams") or {}, rep.get("roads") or {}
    row.update(status=loc["status"], county=(loc.get("county") or [""])[0], layer=loc["layer"]["url"],
               id_field=loc["layer"]["id_field"],
               candidates="; ".join("%s %.2fac" % (c["id"], c["acres"]) for c in loc["candidates"][:5]))
    if rep:
        row.update(parcel_id=rep["parcel_id"], acres=rep["shape"]["acres"],
                   elev_min_m=t.get("elev_min_m", ""), elev_max_m=t.get("elev_max_m", ""), relief_m=t.get("relief_m", ""),
                   grade_median_pct=t.get("grade_median_pct", ""), pct_area_grade_under_15=t.get("pct_area_grade_under_15", ""),
                   faces=t.get("faces", ""), pct_sfha=fl.get("pct_sfha", "?"), pct_floodway=fl.get("pct_floodway", "?"),
                   nearest_stream=st.get("nearest_named") or st.get("nearest_name", ""), stream_m=st.get("nearest_named_m", ""),
                   nearest_road=rd.get("nearest_name", ""), road_m=rd.get("nearest_m", ""),
                   lidar_1m="; ".join(rep.get("lidar") or []), zoning="; ".join((rep.get("zoning") or {}).get("values") or []),
                   flags="; ".join(rep.get("flags") or []))
    return row


def main(argv):
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in ("listing", "report", "init", "batch"):
        print(USAGE, file=sys.stderr)
        return 2
    cmd, args = argv[0], argv[1:]
    cache = Cache(opt(args, "--cache", DEFAULT_CACHE))
    discover = "--no-discover" not in args
    try:
        zoning = zoning_arg(args)
        if cmd == "listing":
            if not args or args[0].startswith("--"):
                print(USAGE, file=sys.stderr)
                return 2
            acres = float(opt(args, "--acres")) if opt(args, "--acres") else None
            loc = run_listing(cache, args[0], acres, opt(args, "--apn"), given_layer(args), zoning, discover)
            if opt(args, "--json"):
                write_json(opt(args, "--json"), loc)
            return 0 if loc["status"] == "found" else 1
        if cmd == "report":
            layer = given_layer(args)
            if not layer or not opt(args, "--id"):
                raise ScoutError("report needs --layer and --id (and --id-field unless it can be guessed)")
            rep = report(cache, layer, opt(args, "--id"), zoning, discover)
            print_report(rep)
            if opt(args, "--json"):
                write_json(opt(args, "--json"), rep)
            return 0
        if cmd == "init":
            pdir = args[0] if args and not args[0].startswith("--") else None
            layer = given_layer(args)
            if not pdir or not layer or not opt(args, "--id"):
                raise ScoutError("init needs PARCEL_DIR, --layer and --id")
            cfg_path = os.path.join(pdir, "parcel.json")
            if os.path.exists(cfg_path) and "--force" not in args:
                raise ScoutError("%s exists; pass --force to replace it" % cfg_path)
            rep = report(cache, layer, opt(args, "--id"), zoning, discover)
            print_report(rep)
            write_json(cfg_path, {"name": os.path.basename(os.path.abspath(pdir)), "parcel_layer_url": layer["url"],
                                  "parcel_id_field": layer["id_field"], "parcel_id": rep["parcel_id"]})
            write_json(os.path.join(pdir, "scout.json"), rep)
            notes = os.path.join(pdir, "notes.md")
            tmpl = os.path.join(HERE, "..", "examples", "notes.example.md")
            if not os.path.exists(notes) and os.path.exists(tmpl):
                with open(tmpl, encoding="utf-8") as f, open(notes, "w", encoding="utf-8") as g:
                    g.write(f.read())
            print("[OK] %s" % cfg_path)
            return 0
        if cmd == "batch":
            if len(args) < 2:
                raise ScoutError("batch needs IN.csv OUT.csv")
            rdir = opt(args, "--reports")
            with open(args[0], newline="", encoding="utf-8-sig") as f:  # -sig: CSVs saved by Excel
                rows = list(csv.DictReader(f))
            out = []
            for k, r in enumerate(rows):
                name = (r.get("name") or "").strip() or "row%d" % (k + 1)
                text = (r.get("listing") or "").strip()
                print("==== %s" % name)
                try:
                    layer = None
                    if (r.get("layer") or "").strip():
                        layer = given_layer(["--layer", r["layer"].strip()] +
                                            (["--id-field", r["id_field"].strip()] if (r.get("id_field") or "").strip() else []))
                    acres = float(r["acres"]) if (r.get("acres") or "").strip() else None
                    loc = run_listing(cache, text, acres, (r.get("apn") or "").strip() or None, layer, zoning, discover)
                    out.append(summary_row(name, text, loc))
                    if rdir:
                        write_json(os.path.join(rdir, "%s.json" % name), loc)
                except ScoutError as e:
                    print("[X] %s" % e)
                    out.append(summary_row(name, text, err=str(e)))
            with open(args[1], "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, CSV_COLS)
                w.writeheader()
                w.writerows(out)
            print("[DONE] %d rows -> %s (%d found)" % (len(out), args[1], sum(1 for r in out if r["status"] == "found")))
            return 0
    except ScoutError as e:
        print("[X] %s" % e, file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
