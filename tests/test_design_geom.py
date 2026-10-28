# Tests for templates/design_geom.py, the Blender-free geometry behind place_masses.py.
# Run: python -m unittest discover -s tests -v
import math, os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
import design_geom as g

SQUARE = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
# an L-shaped (concave) lot: a 20 x 20 square with its top-right 10 x 10 quadrant missing
ELL = [(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20), (0, 0)]


class PointsAndSegments(unittest.TestCase):
    def test_seg_dist_clamps_to_the_segment_ends(self):
        self.assertAlmostEqual(g.seg_dist((5, 3), (0, 0), (10, 0)), 3)
        self.assertAlmostEqual(g.seg_dist((13, 4), (0, 0), (10, 0)), 5)
        self.assertAlmostEqual(g.seg_dist((3, 4), (0, 0), (0, 0)), 5)  # degenerate segment

    def test_segs_cross(self):
        self.assertTrue(g.segs_cross((0, 0), (10, 10), (0, 10), (10, 0)))
        self.assertFalse(g.segs_cross((0, 0), (10, 0), (0, 1), (10, 1)))
        self.assertFalse(g.segs_cross((0, 0), (10, 0), (20, -1), (20, 1)))

    def test_inside_handles_concave_rings(self):
        self.assertTrue(g.inside(5, 5, SQUARE))
        self.assertFalse(g.inside(15, 5, SQUARE))
        self.assertTrue(g.inside(15, 5, ELL))
        self.assertFalse(g.inside(15, 15, ELL))  # the notch


class Footprints(unittest.TestCase):
    def test_footprint_inside_with_clearance(self):
        ins, clear = g.footprint_vs_parcel([(2, 2), (6, 2), (6, 5), (2, 5)], SQUARE)
        self.assertTrue(ins)
        self.assertAlmostEqual(clear, 2)

    def test_footprint_across_the_notch_of_a_concave_lot_is_outside(self):
        # every corner is inside the L, but one edge crosses the notch
        ins, clear = g.footprint_vs_parcel([(5, 15), (15, 5), (16, 6), (6, 16)], ELL)
        self.assertFalse(ins)
        self.assertEqual(clear, 0.0)

    def test_polyline_distance_zero_when_touching_crossing_or_entering(self):
        self.assertEqual(g.polyline_to_polygon_distance([(5, 5), (5, 20)], SQUARE), 0.0)   # starts inside
        self.assertEqual(g.polyline_to_polygon_distance([(-5, 5), (15, 5)], SQUARE), 0.0)  # crosses
        self.assertAlmostEqual(g.polyline_to_polygon_distance([(-5, 5), (-2, 5)], SQUARE), 2)
        self.assertAlmostEqual(g.polyline_to_polygon_distance([(-5, -5), (-3, -4)], SQUARE), 5)


class Ribbons(unittest.TestCase):
    def test_straight_ribbon_is_a_rectangle(self):
        (l0, r0), (l1, r1) = g.offsets([(0, 0), (10, 0)], 4)
        self.assertEqual((l0, r0), ((0, 2), (0, -2)))  # left of travel is +y
        self.assertEqual((l1, r1), ((10, 2), (10, -2)))

    def test_right_angle_join_is_mitered(self):
        pairs = g.offsets([(0, 0), (10, 0), (10, 10)], 4)
        l, r = pairs[1]
        self.assertAlmostEqual(l[0], 8)   # inner corner
        self.assertAlmostEqual(l[1], 2)
        self.assertAlmostEqual(r[0], 12)  # outer corner, 2 * sqrt(2) from the vertex
        self.assertAlmostEqual(r[1], -2)
        self.assertAlmostEqual(math.dist(r, (10, 0)), 2 * math.sqrt(2))

    def test_sharp_turn_miter_is_capped(self):
        pairs = g.offsets([(0, 0), (10, 0), (0, 1)], 2)
        l, r = pairs[1]
        self.assertLessEqual(math.dist(l, (10, 0)), 2.0 + 1e-9)
        self.assertLessEqual(math.dist(r, (10, 0)), 2.0 + 1e-9)

    def test_bad_ribbons_are_refused(self):
        with self.assertRaises(ValueError):
            g.offsets([(0, 0)], 2)
        with self.assertRaises(ValueError):
            g.offsets([(0, 0), (0, 0), (5, 0)], 2)


class Profiles(unittest.TestCase):
    def test_grades_lengths_and_flags(self):
        p = g.profile([(0, 0), (40, 0), (40, 30), (40, 40)], [100, 96, 93, 95], 15)
        self.assertEqual(p["length_m"], 80)
        self.assertEqual([s["grade_pct"] for s in p["segments"]], [-10, -10, 20])
        self.assertEqual([s["ok"] for s in p["segments"]], [True, True, False])
        self.assertEqual(p["too_steep_segments"], [2])
        self.assertEqual(p["max_grade_pct"], 20)
        self.assertEqual(p["mean_grade_pct"], round((4 + 3 + 2) / 80 * 100, 1))
        self.assertEqual((p["start_z"], p["end_z"], p["rise_m"]), (100, 95, -5))
        self.assertEqual(p["max_grade_pct_allowed"], 15)

    def test_limit_is_inclusive(self):
        p = g.profile([(0, 0), (100, 0)], [0, 15], 15)
        self.assertEqual(p["too_steep_segments"], [])

    def test_bad_profiles_are_refused(self):
        with self.assertRaises(ValueError):
            g.profile([(0, 0), (1, 0)], [0], 15)
        with self.assertRaises(ValueError):
            g.profile([(0, 0), (0, 0)], [0, 1], 15)


class Steps(unittest.TestCase):
    def test_integer_splits_evenly(self):
        self.assertEqual(g.split_depths(2, 32), [16, 16])
        self.assertEqual(g.split_depths(4, 30), [7.5] * 4)

    def test_list_must_sum_to_the_depth(self):
        self.assertEqual(g.split_depths([12, 20], 32), [12.0, 20.0])
        with self.assertRaises(ValueError):
            g.split_depths([12, 12], 32)

    def test_bad_steps_are_refused(self):
        for bad in (1, 0, True, [16], [16, -16], [16, "x"], "2", 2.5):
            with self.assertRaises(ValueError):
                g.split_depths(bad, 32)


if __name__ == "__main__":
    unittest.main()
