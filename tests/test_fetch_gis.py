# Network-free tests for templates/fetch_gis.py: urlopen is faked, the script runs for real, and the
# tests check where files land, what the requests asked for, and what gets derived into parcel.json.
# Run: python -m unittest discover -s tests -v
import contextlib, io, json, os, runpy, sys, tempfile, unittest, urllib.parse, urllib.request

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "fetch_gis.py")
LAYER = "https://gis.example.com/arcgis/rest/services/Parcels/MapServer/0"
BIG = [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]
SMALL = [[500, 500], [510, 500], [510, 510], [500, 510], [500, 500]]
# a parcel in UTM zone 13 with fractional corners, so bbox snapping has something to do
LOT = [[500100.3, 4000400.7], [500180.6, 4000400.7], [500180.6, 4000470.2], [500100.3, 4000470.2],
       [500100.3, 4000400.7]]
LONLAT = [[-105.5, 39.7], [-105.499, 39.7], [-105.499, 39.701], [-105.5, 39.701], [-105.5, 39.7]]
FULL_CFG = {"epsg": "EPSG:26913", "parcel_layer_url": LAYER, "parcel_id_field": "APN", "parcel_id": "1",
            "local_origin_xy": [0.0, 0.0], "raster_bbox": [0, 0, 100, 100],
            "context_bbox": [-1000, -1000, 1000, 1000],
            "dem": "gis/terrain_dem.tif", "aerial": "gis/aerial_naip.tif",
            "context_dem": "gis/context_dem_10m.tif", "context_aerial": "gis/context_aerial_naip_4m.tif",
            "parcel": "gis/parcel_boundary.geojson", "context_parcels": "gis/context_parcels.geojson",
            "roads": "gis/roads.geojson"}
MIN_CFG = {"name": "lot", "parcel_layer_url": LAYER, "parcel_id_field": "APN", "parcel_id": "1"}


def fc(geom):
    feats = [] if geom is None else [{"type": "Feature", "properties": {"APN": "1"}, "geometry": geom}]
    return json.dumps({"type": "FeatureCollection", "features": feats}).encode()


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class Run:
    """One scripted run: argv with {D} standing for the parcel dir, canned responses, captured output."""

    def __init__(self, argv, cfg, parcel_geom, lonlat_geom=None, keep_dir=None):
        self.dir = keep_dir or tempfile.mkdtemp(prefix="fetchgis_")
        if cfg is not None:
            with open(os.path.join(self.dir, "parcel.json"), "w") as f:
                json.dump(cfg, f)
        self.urls = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url
            self.urls.append(url)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if "/query" not in url:
                return Response(b"II*\x00fake-tiff")
            if q.get("outSR") == ["4326"]:
                return Response(fc(lonlat_geom))
            if "geometry" in q:  # neighbors or roads around the parcel
                return Response(fc({"type": "Polygon", "coordinates": [BIG]}))
            return Response(fc(parcel_geom))

        real, old_argv = urllib.request.urlopen, sys.argv
        urllib.request.urlopen = fake_urlopen
        sys.argv = [SCRIPT] + [a.replace("{D}", self.dir) for a in argv]
        self.out, self.err, self.code = io.StringIO(), io.StringIO(), None
        try:
            with contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.err):
                runpy.run_path(SCRIPT, run_name="__main__")
        except SystemExit as e:
            self.code = e.code
        finally:
            urllib.request.urlopen, sys.argv = real, old_argv

    def has(self, rel):
        return os.path.isfile(os.path.join(self.dir, rel))

    def params(self, i):
        return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.urls[i]).query).items()}

    def cfg(self):
        with open(os.path.join(self.dir, "parcel.json")) as f:
            return json.load(f)


class FetchGisTests(unittest.TestCase):
    def test_usage_without_arguments_and_with_help(self):
        for argv in ([], ["--help"], ["-h"]):
            r = Run(argv, None, None)
            self.assertEqual(r.code, 2)
            self.assertIn("usage:", r.err.getvalue())
            self.assertEqual(r.urls, [])

    def test_full_config_writes_every_file_at_its_configured_path(self):
        r = Run(["{D}"], FULL_CFG, {"type": "Polygon", "coordinates": [BIG]})
        self.assertIsNone(r.code, r.code)
        for rel in FULL_CFG.values():
            if isinstance(rel, str) and rel.startswith("gis/"):
                self.assertTrue(r.has(rel), rel)
        self.assertEqual(len(r.urls), 7)
        self.assertNotIn("[DERIVED]", r.out.getvalue())
        self.assertNotIn("4326", "".join(r.urls))

    def test_out_dir_resolves_the_same_relative_paths_elsewhere(self):
        r = Run(["{D}", "--out", "{D}_side"], FULL_CFG, {"type": "Polygon", "coordinates": [BIG]})
        self.assertIsNone(r.code)
        self.assertTrue(os.path.isfile(os.path.join(r.dir + "_side", "gis", "terrain_dem.tif")))
        self.assertFalse(os.path.exists(os.path.join(r.dir, "gis")))

    def test_custom_subfolder_is_honored_not_flattened(self):
        r = Run(["{D}"], dict(FULL_CFG, dem="data/dem/elev.tif"), {"type": "Polygon", "coordinates": [BIG]})
        self.assertTrue(r.has("data/dem/elev.tif"))
        self.assertFalse(r.has("gis/elev.tif"))

    def test_multipolygon_uses_the_largest_polygon(self):
        r = Run(["{D}"], FULL_CFG, {"type": "MultiPolygon", "coordinates": [[SMALL], [BIG]]})
        self.assertIsNone(r.code)
        self.assertEqual(r.params(1)["geometry"], "-200.000000,-200.000000,300.000000,300.000000")

    def test_no_match_and_bad_geometry_exit_readably(self):
        r = Run(["{D}"], FULL_CFG, None)
        self.assertTrue(str(r.code).startswith("[X] no parcel matched APN='1' on"), r.code)
        r = Run(["{D}"], FULL_CFG, {"type": "Point", "coordinates": [1, 2]})
        self.assertIn("expected Polygon or MultiPolygon", str(r.code))

    def test_bbox_that_is_not_whole_pixels_is_refused(self):
        r = Run(["{D}"], dict(FULL_CFG, raster_bbox=[0, 0, 100.5, 100]), {"type": "Polygon", "coordinates": [BIG]})
        self.assertIn("not a whole number", str(r.code))

    def test_minimal_config_is_completed_and_written_back(self):
        r = Run(["{D}"], MIN_CFG, {"type": "Polygon", "coordinates": [LOT]}, {"type": "Polygon", "coordinates": [LONLAT]})
        self.assertIsNone(r.code, r.code)
        c = r.cfg()
        self.assertEqual(c["epsg"], "EPSG:26913")  # lon -105.5 -> UTM zone 13
        self.assertEqual(c["local_origin_xy"], [500100.0, 4000400.0])
        self.assertEqual(c["raster_bbox"], [499950.0, 4000250.0, 500331.0, 4000621.0])
        self.assertEqual(c["context_bbox"], [496100.0, 3996400.0, 504100.0, 4004400.0])
        self.assertEqual(c["dem"], "gis/terrain_dem.tif")
        self.assertEqual(list(c)[:5], ["name", "epsg", "local_origin_xy", "raster_bbox", "context_bbox"])
        # the parcel outline sits inside the derived raster bbox with the pad around it
        self.assertLessEqual(c["raster_bbox"][0], 500100.3 - 150)
        self.assertGreaterEqual(c["raster_bbox"][2], 500180.6 + 150)
        # one lon/lat probe, then everything in the derived CRS with whole-pixel raster sizes
        self.assertEqual(sum("outSR=4326" in u for u in r.urls), 1)
        self.assertEqual(r.params(1)["outSR"], "26913")
        self.assertEqual(r.params(4)["size"], "381,371")     # DEM at 1 m
        self.assertEqual(r.params(5)["size"], "1524,1484")   # aerial at 0.25 m
        self.assertEqual(r.params(6)["size"], "800,800")     # context DEM at 10 m
        self.assertEqual(r.params(7)["size"], "2000,2000")   # context aerial at 4 m
        self.assertIn("[WRITE]", r.out.getvalue())
        # a second run reads the completed config: no probe, nothing derived, every file skipped
        again = Run(["{D}"], None, {"type": "Polygon", "coordinates": [LOT]}, keep_dir=r.dir)
        self.assertIsNone(again.code, again.code)
        self.assertEqual(again.urls, [])
        self.assertNotIn("[DERIVED]", again.out.getvalue())
        self.assertEqual(again.cfg(), c)

    def test_null_context_rasters_switch_the_context_off(self):
        cfg = dict(MIN_CFG, context_dem=None, context_aerial=None)
        r = Run(["{D}"], cfg, {"type": "Polygon", "coordinates": [LOT]}, {"type": "Polygon", "coordinates": [LONLAT]})
        self.assertIsNone(r.code, r.code)
        self.assertNotIn("context_bbox", r.cfg())
        self.assertEqual(len(r.urls), 6)  # probe + parcel + neighbors + roads + DEM + aerial

    def test_parcels_outside_nad83_utm_need_epsg_by_hand(self):
        south = [[-70.0, -33.4], [-69.999, -33.4], [-69.999, -33.399], [-70.0, -33.399], [-70.0, -33.4]]
        r = Run(["{D}"], MIN_CFG, {"type": "Polygon", "coordinates": [LOT]}, {"type": "Polygon", "coordinates": [south]})
        self.assertIn("set epsg by hand", str(r.code))
        east = [[10.0, 50.0], [10.001, 50.0], [10.001, 50.001], [10.0, 50.001], [10.0, 50.0]]
        r = Run(["{D}"], MIN_CFG, {"type": "Polygon", "coordinates": [LOT]}, {"type": "Polygon", "coordinates": [east]})
        self.assertIn("set epsg by hand", str(r.code))


if __name__ == "__main__":
    unittest.main()
