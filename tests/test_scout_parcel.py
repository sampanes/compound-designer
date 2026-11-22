# End-to-end tests for templates/scout_parcel.py against faked services: a synthetic county whose parcel
# layer has a street of addressed parcels and a vacant lot with no situs address, a creek across the
# lot, a road along its north edge, a flood zone over its southern half, and a zoning service whose
# first layer is empty. No network.
# Run: python -m unittest discover -s tests -v
import contextlib, csv, io, json, os, sys, tempfile, unittest, urllib.parse, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
import scout_geo as g
import scout_parcel as sp

LAT0, LON0 = 39.5, -105.5
LOC = g.Local(LON0, LAT0)
PARCELS = "https://gis.example.com/arcgis/rest/services/Example_Parcels/FeatureServer"
OLD = "https://gis.example.com/arcgis/rest/services/Example_Parcels_Copy/FeatureServer"
PARTIAL = "https://gis.example.com/arcgis/rest/services/Example_Parcels_Partial/FeatureServer"
ZONING = "https://gis.example.com/arcgis/rest/services/Example_Zoning/FeatureServer"
VACANT_URL = "https://www.zillow.com/homedetails/000-Quiet-Hawk-Trl-%23--Anytown-CO-80000/1_zpid/?utm_source=txt"


def square(cx, cy, w, h):
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    return [list(LOC.lonlat(x, y)) for x, y in ((x0, y0), (x0, y1), (x1, y1), (x1, y0), (x0, y0))]


def acres_side(ac):
    return (ac * 4046.8564) ** 0.5


# the street runs east-west at y = 0; the vacant target lot (3.0 ac) sits south of it
LOTS = [
    {"APN": "123-45-011", "SITUS_ADDR": "11 QUIET HAWK TRL", "ring": square(-300, 40, 60, 60)},
    {"APN": "123-45-012", "SITUS_ADDR": "12 QUIET HAWK TRL", "ring": square(-200, 40, 70, 70)},
    {"APN": "123-45-067", "SITUS_ADDR": " ", "ring": square(0, -acres_side(3.0) / 2, acres_side(3.0), acres_side(3.0))},
    {"APN": "123-45-090", "SITUS_ADDR": None, "ring": square(900, -900, acres_side(3.6), acres_side(3.6))},
    {"APN": "123-99-001", "SITUS_ADDR": "5 QUIET HAWK RD", "ring": square(5000, 5000, 50, 50)},
]
TARGET = LOTS[2]


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def feature(lot):
    return {"attributes": {"APN": lot["APN"], "SITUS_ADDR": lot["SITUS_ADDR"]}, "geometry": {"rings": [lot["ring"]]}}


class Services:
    """Routes a request URL (+ POST body) to a canned JSON reply and records what was asked."""

    def __init__(self, street_geocodes=False):
        self.calls = []
        self.street_geocodes = street_geocodes

    def __call__(self, req, timeout=None):
        url = req.full_url
        base, _, qs = url.partition("?")
        q = {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}
        if req.data:
            q.update({k: v[0] for k, v in urllib.parse.parse_qs(req.data.decode()).items()})
        self.calls.append((base, q))
        return Response(json.dumps(self.reply(base, q)).encode())

    def reply(self, base, q):
        if "nominatim" in base:
            if "street" in q and not self.street_geocodes:
                return []
            if q.get("city") == "Nowhere":
                return []
            return [{"lat": str(LAT0), "lon": str(LON0)}]
        if "geocoding.geo.census.gov" in base:
            return {"result": {"geographies": {"Counties": [{"NAME": "Example County", "STATE": "08", "GEOID": "08999"}]}}}
        if "sharing/rest/search" in base:
            if "zoning" in q["q"]:
                return {"results": [{"title": "Zoning - Example County", "owner": "examplegis", "url": ZONING}]}
            return {"results": [{"title": "Example County Parcels", "owner": "examplegis", "url": PARCELS},
                                {"title": "Parcels copy", "owner": "someone", "url": OLD}]}
        for svc in (PARCELS, OLD, PARTIAL):
            if base == svc:
                return {"layers": [{"id": 0, "geometryType": "esriGeometryPolygon"}]}
            if base == svc + "/0":
                return {"geometryType": "esriGeometryPolygon",
                        "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"},
                                   {"name": "APN", "type": "esriFieldTypeString"},
                                   {"name": "SITUS_ADDR", "type": "esriFieldTypeString"},
                                   {"name": "OWNER_NAME", "type": "esriFieldTypeString"}]}
            if base == svc + "/0/query":
                return self.parcels(q, svc)
        if base == ZONING:
            return {"layers": [{"id": 0, "geometryType": "esriGeometryPolygon"}, {"id": 1, "geometryType": "esriGeometryPolygon"}]}
        if base in (ZONING + "/0", ZONING + "/1"):
            return {"geometryType": "esriGeometryPolygon", "fields": [{"name": "ZONING", "type": "esriFieldTypeString"}]}
        if base == ZONING + "/0/query":
            return {"features": []}
        if base == ZONING + "/1/query":
            return {"features": [{"attributes": {"ZONING": "R-2A"}}]}
        if base.endswith("getSamples"):
            pts = json.loads(q["geometry"])["points"]
            return {"samples": [{"locationId": i, "value": str(2000 + 0.1 * LOC.xy(*p)[1])} for i, p in enumerate(pts)]}
        if base.endswith("ImageServer/identify"):
            return {"catalogItems": {"features": [{"attributes": {"Name": "EX_Lidar_2020", "LowPS": 1}},
                                                  {"attributes": {"Name": "overview", "LowPS": 75}}]}}
        if "USA_Flood_Hazard" in base:
            south = square(0, -acres_side(3.0) * 0.75, 400, acres_side(3.0) / 2)
            return {"features": [{"attributes": {"FLD_ZONE": "AE", "ZONE_SUBTY": None, "SFHA_TF": "T"},
                                  "geometry": {"rings": [south]}}]}
        if "nhd/MapServer" in base:
            creek = [list(LOC.lonlat(x, -acres_side(3.0) / 2)) for x in (-400, 0, 400)]
            return {"features": [{"attributes": {"gnis_name": "Example Creek", "fcode": 46006}, "geometry": {"paths": [creek]}}]}
        if "TIGERweb" in base:
            if "/8/" not in base:
                return {"features": []}
            road = [list(LOC.lonlat(x, 3)) for x in (-500, 500)]
            return {"features": [{"attributes": {"NAME": "Quiet Hawk Trl", "MTFCC": "S1400"}, "geometry": {"paths": [road]}}]}
        raise AssertionError("unexpected request " + base)

    def parcels(self, q, svc):
        where = q.get("where", "")
        # the copy is empty; the partial copy has the street but is missing number 12
        lots = [] if svc == OLD else [l for l in LOTS if l["APN"] != "123-45-012"] if svc == PARTIAL else LOTS
        if q.get("resultRecordCount") == "1" and where == "1=1":
            return {"features": [{"attributes": {"APN": "123-45-011", "SITUS_ADDR": "11 QUIET HAWK TRL"}}]}
        if "LIKE '%QUIET HAWK%'" in where:
            return {"features": [feature(l) for l in lots if "QUIET HAWK" in (l["SITUS_ADDR"] or "")]}
        if where.startswith("APN = "):
            v = where.split("'")[1]
            return {"features": [feature(l) for l in lots if l["APN"] == v]}
        if "LIKE" in where and "APN" in where:
            return {"features": []}
        if "geometry" in q:
            return {"features": [feature(l) for l in lots]}
        return {"features": []}


class Scout(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="scout_")
        self.cache = os.path.join(self.dir, "cache.json")
        self.svc = Services()
        self._urlopen, self._sleep = urllib.request.urlopen, sp.time.sleep
        urllib.request.urlopen = self.svc
        sp.time.sleep = lambda s: None

    def tearDown(self):
        urllib.request.urlopen, sp.time.sleep = self._urlopen, self._sleep

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sp.main(list(argv) + ["--cache", self.cache])
        return rc, out.getvalue(), err.getvalue()

    def test_vacant_listing_found_by_street_and_acreage(self):
        js = os.path.join(self.dir, "loc.json")
        rc, out, err = self.run_main("listing", VACANT_URL, "--acres", "3", "--json", js)
        self.assertEqual(rc, 0, out + err)
        with open(js, encoding="utf-8") as f:
            loc = json.load(f)
        self.assertEqual(loc["status"], "found")
        self.assertEqual(loc["candidates"][0]["id"], TARGET["APN"])
        self.assertNotIn("123-45-090", [c["id"] for c in loc["candidates"]])  # 3.6 ac is outside 5%
        rep = loc["report"]
        self.assertEqual(rep["county"][0], "Example County")
        self.assertAlmostEqual(rep["shape"]["acres"], 3.0, delta=0.03)
        self.assertAlmostEqual(rep["terrain"]["grade_median_pct"], 10.0, delta=0.3)
        self.assertEqual(rep["terrain"]["faces"], "S")
        self.assertEqual(rep["lidar"], ["EX_Lidar_2020"])
        self.assertAlmostEqual(rep["flood"]["pct_sfha"], 50, delta=8)
        self.assertEqual(rep["streams"]["nearest_name"], "Example Creek")
        self.assertEqual(rep["streams"]["nearest_m"], 0)
        self.assertEqual(rep["roads"]["nearest_name"], "Quiet Hawk Trl")
        self.assertLessEqual(rep["roads"]["nearest_m"], 5)
        self.assertEqual(rep["zoning"]["values"], ["R-2A"])  # the empty first zoning layer is skipped
        self.assertIn("Example Creek perennial stream crosses the parcel", rep["flags"])
        self.assertIn("[MATCH] found", out)
        # parcel queries never ask for owner fields
        for base, q in self.svc.calls:
            if base.endswith("/0/query") and "outFields" in q:
                self.assertNotIn("OWNER", q["outFields"].upper())

    def test_street_missing_from_the_top_layer_falls_back_to_the_next(self):
        cache = {"layer|parcels|08999": {"url": OLD + "/0", "id_field": "APN", "addr_field": "SITUS_ADDR", "score": 9,
                                          "alternates": [{"url": PARCELS + "/0", "id_field": "APN", "addr_field": "SITUS_ADDR", "score": 8}]}}
        with open(self.cache, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        rc, out, _ = self.run_main("listing", VACANT_URL, "--acres", "3")
        self.assertEqual(rc, 0)
        self.assertIn("[LAYER] %s/0" % PARCELS, out)

    def test_street_number_missing_from_the_top_layer_falls_back_to_one_that_has_it(self):
        cache = {"layer|parcels|08999": {"url": PARTIAL + "/0", "id_field": "APN", "addr_field": "SITUS_ADDR", "score": 9,
                                          "alternates": [{"url": PARCELS + "/0", "id_field": "APN", "addr_field": "SITUS_ADDR", "score": 8}]}}
        with open(self.cache, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        rc, out, _ = self.run_main("listing", "12 Quiet Hawk Trl, Anytown, CO 80000")
        self.assertEqual(rc, 0, out)
        self.assertIn("[LAYER] %s/0" % PARCELS, out)
        self.assertIn("[MATCH] found by address", out)

    def test_no_acres_lists_street_candidates(self):
        rc, out, _ = self.run_main("listing", VACANT_URL)
        self.assertEqual(rc, 1)
        self.assertIn("[MATCH] ambiguous", out)
        self.assertIn("123-45-011", out)

    def test_exact_address_and_apn(self):
        rc, out, _ = self.run_main("listing", "12 Quiet Hawk Trl, Anytown, CO 80000")
        self.assertEqual(rc, 0)
        self.assertIn("[MATCH] found by address", out)
        self.assertIn("[PARCEL] APN = 123-45-012", out)
        rc, out, _ = self.run_main("listing", VACANT_URL, "--apn", "123-45-067")
        self.assertEqual(rc, 0)
        self.assertIn("[MATCH] found by apn", out)

    def test_geocoded_point_only_is_never_found(self):
        # the street is not in any parcel data: candidates by acreage near the city are only "ambiguous"
        rc, out, _ = self.run_main("listing", "000 Unknown Way, Anytown, CO 80000", "--acres", "3")
        self.assertEqual(rc, 1)
        self.assertIn("[MATCH] ambiguous", out)
        self.assertIn("not in the parcel data", out)

    def test_cache_skips_discovery_on_the_second_run(self):
        self.run_main("listing", VACANT_URL, "--acres", "3")
        n = len(self.svc.calls)
        self.svc.calls.clear()
        self.run_main("listing", VACANT_URL, "--acres", "3")
        bases = [b for b, _ in self.svc.calls]
        self.assertFalse(any("sharing/rest/search" in b or "nominatim" in b or "geocoding.geo.census" in b for b in bases))
        self.assertLess(len(bases), n)

    def test_init_writes_the_four_keys(self):
        pdir = os.path.join(self.dir, "lot")
        rc, out, err = self.run_main("init", pdir, "--layer", PARCELS, "--id", "123-45-067")
        self.assertEqual(rc, 0, out + err)
        with open(os.path.join(pdir, "parcel.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg, {"name": "lot", "parcel_layer_url": PARCELS + "/0", "parcel_id_field": "APN",
                               "parcel_id": "123-45-067"})
        self.assertTrue(os.path.exists(os.path.join(pdir, "scout.json")))
        rc, _, err = self.run_main("init", pdir, "--layer", PARCELS, "--id", "123-45-067")
        self.assertEqual(rc, 1)
        self.assertIn("--force", err)

    def test_batch(self):
        src, dst = os.path.join(self.dir, "in.csv"), os.path.join(self.dir, "out.csv")
        with open(src, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["name", "listing", "acres", "apn", "layer", "id_field"])
            w.writerow(["vacant", VACANT_URL, "3", "", "", ""])
            w.writerow(["lost", "1 Main St, Nowhere, ZZ", "", "", "", ""])
        rc, out, _ = self.run_main("batch", src, dst, "--reports", os.path.join(self.dir, "reports"))
        self.assertEqual(rc, 0)
        with open(dst, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r["status"] for r in rows], ["found", "error"])
        self.assertEqual(rows[0]["parcel_id"], TARGET["APN"])
        self.assertIn("floodplain", rows[0]["flags"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "reports", "vacant.json")))

    def test_usage(self):
        rc, _, err = self.run_main("nonsense")
        self.assertEqual(rc, 2)
        self.assertIn("usage", err)


if __name__ == "__main__":
    unittest.main()
