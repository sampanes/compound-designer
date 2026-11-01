# Tests for templates/scout_geo.py: listing parsing, street and APN matching, lon/lat geometry, terrain
# statistics, and triage flags. Pure functions, no network.
# Run: python -m unittest discover -s tests -v
import math, os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
import scout_geo as g

LAT0, LON0 = 39.5, -105.5


def square(cx, cy, w, h, loc):
    """A clockwise (Esri outer) lon/lat ring for a w x h m rectangle centered at (cx, cy) m."""
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    return [list(loc.lonlat(x, y)) for x, y in ((x0, y0), (x0, y1), (x1, y1), (x1, y0), (x0, y0))]


class ParseListing(unittest.TestCase):
    def test_zillow_vacant_with_encoded_unit_and_tracking(self):
        p = g.parse_listing("https://www.zillow.com/homedetails/000-QUIET-HAWK-Trl-%23--Anytown-CO-80000/123_zpid/"
                            "?utm_campaign=share&utm_source=txt")
        self.assertEqual(p["url"], "https://www.zillow.com/homedetails/000-QUIET-HAWK-Trl-%23--Anytown-CO-80000/123_zpid/")
        self.assertTrue(p["vacant"])
        self.assertIsNone(p["street_number"])
        self.assertEqual((p["street"], p["city"], p["state"], p["zip"]), ("QUIET HAWK Trl", "Anytown", "CO", "80000"))
        self.assertEqual(p["listing_id"], "123")
        self.assertEqual(p["query"], "QUIET HAWK Trl, Anytown, CO 80000")

    def test_zillow_unit_value_and_four_zeros(self):
        p = g.parse_listing("https://www.zillow.com/homedetails/0000-Quiet-Hawk-Rd-%2312B-Anytown-CO-80000/9_zpid/")
        self.assertTrue(p["vacant"])
        self.assertEqual(p["unit"], "12B")
        self.assertEqual(p["street"], "Quiet Hawk Rd")

    def test_zillow_regular_address_with_apt(self):
        p = g.parse_listing("https://www.zillow.com/homedetails/42-Elm-St-APT-3-Port-St-Lucie-FL-34952/77_zpid/")
        self.assertFalse(p["vacant"])
        self.assertEqual((p["street_number"], p["street"], p["unit"], p["city"]), ("42", "Elm St", "3", "Port St Lucie"))

    def test_street_starting_with_a_suffix_word(self):
        p = g.parse_listing("https://www.zillow.com/homedetails/5-St-Andrews-Dr-Anytown-CO-80000/1_zpid/")
        self.assertEqual((p["street"], p["city"]), ("St Andrews Dr", "Anytown"))

    def test_redfin_and_realtor(self):
        r = g.parse_listing("https://www.redfin.com/CO/Anytown/0-Quiet-Hawk-Trl-80000/home/555?share=1")
        self.assertEqual((r["source"], r["street"], r["city"], r["state"], r["zip"], r["listing_id"], r["vacant"]),
                         ("redfin", "Quiet Hawk Trl", "Anytown", "CO", "80000", "555", True))
        t = g.parse_listing("https://www.realtor.com/realestateandhomes-detail/7-Quiet-Hawk-Trl_Any-Town_CO_80000_M1-2")
        self.assertEqual((t["street_number"], t["street"], t["city"], t["state"], t["zip"]),
                         ("7", "Quiet Hawk Trl", "Any Town", "CO", "80000"))

    def test_typed_address(self):
        p = g.parse_listing("000 Quiet Hawk Trl #-, Anytown, CO 80000")
        self.assertEqual((p["street"], p["city"], p["state"], p["zip"], p["vacant"]),
                         ("Quiet Hawk Trl", "Anytown", "CO", "80000", True))
        q = g.parse_listing("12 Quiet Hawk Trl Anytown CO")
        self.assertEqual((q["street_number"], q["street"], q["city"], q["state"]), ("12", "Quiet Hawk Trl", "Anytown", "CO"))


class Matching(unittest.TestCase):
    def test_street_core_and_suffix(self):
        self.assertEqual(g.street_core("N Quiet Hawk Drive"), "QUIET HAWK")
        self.assertEqual(g.street_suffix("Quiet Hawk Trail"), "TRL")
        self.assertEqual(g.street_suffix("Quiet Hawk"), "")

    def test_same_street(self):
        self.assertTrue(g.same_street("9417 W QUIET HAWK TRAIL ", "Quiet Hawk Trl"))
        self.assertFalse(g.same_street("12 QUIET HAWK RD", "Quiet Hawk Trl"))
        self.assertTrue(g.same_street("12 QUIET HAWK", "Quiet Hawk Trl"))  # no suffix on file: keep it
        self.assertFalse(g.same_street("12 OTHER RD", "Quiet Hawk Trl"))

    def test_apn_spellings(self):
        self.assertEqual(g.apn_variants("123-45-067a"), ["123-45-067a", "123-45-067A", "12345067A"])
        self.assertEqual(g.apn_like("123-45-067A"), "%123%45%067A%")
        self.assertEqual(g.sql_quote("O'Hare"), "'O''Hare'")

    def test_apn_tail(self):
        self.assertTrue(g.apn_tail_match("12345067", "67"))
        self.assertTrue(g.apn_tail_match("123-45-067", "067"))
        self.assertFalse(g.apn_tail_match("12345067", "7"))  # one digit says nothing
        self.assertFalse(g.apn_tail_match("12345068", "67"))
        self.assertFalse(g.apn_tail_match("12345067", None))

    def test_guess_fields_prefers_the_readable_apn(self):
        fields = [{"name": "PARCEL_ID", "type": "esriFieldTypeString"}, {"name": "PARLABEL", "type": "esriFieldTypeString"},
                  {"name": "OWNER_ADDR", "type": "esriFieldTypeString"}, {"name": "SITUS_ADD", "type": "esriFieldTypeString"}]
        self.assertEqual(g.guess_fields(fields, {"PARCEL_ID": "1012345067001", "PARLABEL": "123-45-067"}),
                         ("PARLABEL", "SITUS_ADD"))

    def test_rank_layer(self):
        cur = g.rank_layer("Example County Parcels", "examplegis", "Example County", True, True)
        old = g.rank_layer("Historical Parcels 2001 to 2005", "examplegis", "Example County", True, True)
        none = g.rank_layer("Example County Parcels", "x", "Example County", False, True)
        self.assertGreater(cur, old)
        self.assertGreater(cur, none)
        self.assertGreater(g.rank_layer("Zoning - Example County", "x", "Example County", True, True, "zoning"),
                           g.rank_layer("Example roads", "x", "Example County", False, True, "zoning"))

    def test_rank_candidates(self):
        cands = [{"id": "1", "acres": 3.0, "dist_m": 900}, {"id": "2", "acres": 3.05, "dist_m": 100},
                 {"id": "3", "acres": 4.0, "dist_m": 50}, {"id": "10067", "acres": 3.1, "dist_m": 800}]
        self.assertEqual([c["id"] for c in g.rank_candidates(cands, 3.0)], ["1", "2", "10067"])
        self.assertEqual(g.rank_candidates(cands, 3.0, number="67")[0]["id"], "10067")
        self.assertEqual([c["id"] for c in g.rank_candidates(cands)], ["3", "2", "10067", "1"])


class Geometry(unittest.TestCase):
    def setUp(self):
        self.loc = g.Local(LON0, LAT0)

    def test_shape_of_a_square(self):
        ring = square(0, 0, 100, 100, self.loc)
        loc, main, info = g.parcel_shape([ring])
        self.assertAlmostEqual(info["area_m2"], 10000, delta=50)
        self.assertAlmostEqual(info["acres"], 2.47, delta=0.02)
        self.assertEqual((info["extent_ew_m"], info["extent_ns_m"], info["parts"]), (100, 100, 1))

    def test_hole_and_two_parts(self):
        outer = square(0, 0, 100, 100, self.loc)
        hole = list(reversed(square(0, 0, 20, 20, self.loc)))  # counterclockwise = hole
        other = square(300, 0, 50, 50, self.loc)
        _, main, info = g.parcel_shape([outer, hole, other])
        self.assertEqual(info["parts"], 2)
        self.assertAlmostEqual(info["area_m2"], 10000 - 400 + 2500, delta=80)
        self.assertAlmostEqual(g.ring_area(main), 10000, delta=50)

    def test_min_dist(self):
        ring = [(0, 0), (0, 100), (100, 100), (100, 0), (0, 0)]
        self.assertEqual(g.min_dist([(-50, 50), (150, 50)], ring), 0.0)
        self.assertAlmostEqual(g.min_dist([(-50, 150), (150, 150)], ring), 50.0)
        self.assertEqual(g.min_dist([(10, 10), (20, 20)], ring), 0.0)

    def test_terrain_on_a_south_facing_plane(self):
        ring = [self.loc.xy(*p) for p in square(0, 0, 120, 80, self.loc)]
        step, nx, ny, x0, y0, pts = g.sample_grid(self.loc, ring, max_points=400)
        self.assertLessEqual(len(pts), 400)
        z = [1000 + 0.2 * self.loc.xy(*p)[1] for p in pts]  # rises 20% to the north
        t = g.terrain_stats(z, step, nx, ny, x0, y0, ring)
        self.assertAlmostEqual(t["grade_median_pct"], 20.0, delta=0.3)
        self.assertAlmostEqual(t["fit_grade_pct"], 20.0, delta=0.3)
        self.assertEqual(t["faces"], "S")
        self.assertEqual(t["pct_area_grade_under_15"], 0)
        self.assertAlmostEqual(t["relief_m"], 16, delta=2 * 0.2 * step)

    def test_flat_and_missing_samples(self):
        ring = [self.loc.xy(*p) for p in square(0, 0, 60, 60, self.loc)]
        step, nx, ny, x0, y0, pts = g.sample_grid(self.loc, ring, max_points=200)
        t = g.terrain_stats([500.0] * len(pts), step, nx, ny, x0, y0, ring)
        self.assertEqual((t["faces"], t["pct_area_grade_under_15"]), ("flat", 100))
        self.assertIsNone(g.terrain_stats([None] * len(pts), step, nx, ny, x0, y0, ring))

    def test_share_inside(self):
        main = [self.loc.xy(*p) for p in square(0, 0, 100, 100, self.loc)]
        grid = g.sample_grid(self.loc, main, max_points=900)[:5]
        south = square(0, -50, 200, 100, self.loc)  # covers the southern half
        with_hole = [square(0, 0, 200, 200, self.loc), list(reversed(square(0, 0, 100, 100, self.loc)))]
        a, b = g.share_inside([[south], with_hole], self.loc, *grid, main)
        self.assertAlmostEqual(a, 0.5, delta=0.08)
        self.assertLess(b, 0.1)

    def test_compass(self):
        self.assertEqual([g.compass8(b) for b in (0, 44, 46, 180, 359)], ["N", "NE", "NE", "S", "N"])


class Flags(unittest.TestCase):
    def test_order_and_wording(self):
        rep = {"flood": {"status": "ok", "pct_sfha": 54, "pct_floodway": 51},
               "terrain": {"pct_area_grade_under_15": 66, "grade_median_pct": 10},
               "roads": {"status": "ok", "nearest_m": 177},
               "streams": {"status": "ok", "nearest_m": 0, "nearest_name": "Example Creek", "nearest_kind": "perennial stream"},
               "lidar": []}
        self.assertEqual(g.flags(rep), ["51% in a regulatory floodway", "54% in the 1% annual chance floodplain (SFHA)",
                                        "no mapped road within 30 m (access may be by easement or unmapped road)",
                                        "Example Creek perennial stream crosses the parcel", "no 1 m lidar"])

    def test_unverified_and_steep(self):
        f = g.flags({"flood": {"status": "unverified"}, "terrain": {"pct_area_grade_under_15": 0, "grade_median_pct": 45},
                     "roads": {"status": "unverified"}, "streams": {"status": "ok", "nearest_m": None}, "lidar": None})
        self.assertEqual(f, ["flood zone unverified", "under 10% of the lot is below a 15% grade"])


if __name__ == "__main__":
    unittest.main()
