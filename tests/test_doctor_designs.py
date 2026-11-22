# Tests for the design-JSON validation in templates/doctor.py. --design-only makes the subprocess
# result describe design validation alone, without requiring or probing Blender.
# Run: python -m unittest discover -s tests -v
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DOCTOR = os.path.join(ROOT, "templates", "doctor.py")
EXAMPLE = os.path.join(ROOT, "examples", "design.example.json")


def run_doctor(*paths):
    env = dict(os.environ, BLENDER="__design_only_must_not_probe_blender__")
    return subprocess.run([sys.executable, DOCTOR, "--design-only", *paths],
                          capture_output=True, text=True, env=env)


def run_normal_doctor(*args):
    env = dict(os.environ, BLENDER=os.path.join(tempfile.gettempdir(), "no-such-blender"))
    return subprocess.run([sys.executable, DOCTOR, *args], capture_output=True, text=True, env=env)


def result_detail(result):
    return "returncode=%d\nstdout:\n%s\nstderr:\n%s" % (result.returncode, result.stdout, result.stderr)


def doctor_line(result, path):
    tag = "design " + os.path.basename(path)
    lines = [line for line in result.stdout.splitlines() if line.startswith("[CHECK]") and tag in line]
    if len(lines) != 1:
        raise AssertionError("expected one check line for %s\n%s" % (tag, result_detail(result)))
    return lines[0]


class DoctorDesignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="doctor_")
        self.addCleanup(self.tmp.cleanup)
        self.written = 0

    def example(self):
        with open(EXAMPLE) as f:
            return json.load(f)

    def write_design(self, design, filename=None):
        self.written += 1
        path = os.path.join(self.tmp.name, filename or "design_%d.json" % self.written)
        with open(path, "w") as f:
            json.dump(design, f)
        return path

    def assert_result(self, result, code):
        self.assertEqual(result.returncode, code, result_detail(result))
        self.assertEqual(result.stderr, "", result_detail(result))

    def test_example_design_passes_without_probing_blender(self):
        result = run_doctor(EXAMPLE)
        self.assert_result(result, 0)
        line = doctor_line(result, EXAMPLE)
        self.assertTrue(line.startswith("[CHECK] OK"), line)
        self.assertIn("8 element(s)", line)
        self.assertIn("[DONE] all checks OK", result.stdout)
        self.assertNotIn("blender executable", result.stdout.lower())
        self.assertNotIn("__design_only_must_not_probe_blender__", result.stdout + result.stderr)

    def test_drive_and_steps_problems_are_named(self):
        d = self.example()
        d["max_grade_pct"] = 0
        d["elements"] = [
            {"id": "h", "kind": "house", "u": 0, "v": 0, "w_ft": 30, "d_ft": 32, "steps": [16, 12], "wall_h": 3, "roof_pitch": 0.3},
            {"id": "h2", "kind": "house", "u": 0, "v": 0, "w_ft": 30, "d_ft": 32, "steps": 1, "wall_h": 3, "roof_pitch": 0.3},
            {"id": "d1", "kind": "drive", "width_m": 3},
            {"id": "d2", "kind": "drive", "width_m": 0, "points": [[0, 0], [0, 0], [5, 5]], "max_grade_pct": -1},
            {"id": "d3", "kind": "drive", "width_m": 2, "points": [[0, 0], [1]]},
            {"id": "x", "kind": "pool", "u": 0, "v": 0},
        ]
        path = self.write_design(d)
        result = run_doctor(path)
        self.assert_result(result, 1)
        line = doctor_line(result, path)
        self.assertTrue(line.startswith("[CHECK] FAIL"), line)
        for msg in ("max_grade_pct must be a positive number",
                    "h: steps must be an integer >= 2 or a list of pad depths in ft that sum to d_ft",
                    "h2: steps must be",
                    "d1: points must be a list of at least two [u, v] pairs",
                    "d2: consecutive points repeat", "d2: width_m must be positive",
                    "d2: max_grade_pct must be a positive number",
                    "d3: points must be",
                    "x: kind must be house, terrace or drive"):
            self.assertIn(msg, line)
        self.assertNotIn("d1: u must be", line)  # drives have points, not u/v

    def test_plain_house_integer_steps_and_switchback_pass(self):
        d = self.example()
        d["elements"] = [
            {"id": "a", "kind": "house", "u": -2, "v": -1, "w_ft": 30, "d_ft": 30,
             "wall_h": 3, "roof_pitch": 0.3, "rot_deg": -90},
            {"id": "b", "kind": "house", "u": 0, "v": 0, "w_ft": 30, "d_ft": 30,
             "steps": 3, "wall_h": 3, "roof_pitch": 0.3},
            {"id": "p", "kind": "drive", "width_m": 1.5,
             "points": [[0, 0], [10, 0], [10, 10], [20, 10]]},
        ]
        path = self.write_design(d)
        result = run_doctor(path)
        self.assert_result(result, 0)
        self.assertTrue(doctor_line(result, path).startswith("[CHECK] OK"))

    def test_vegetation_defaults_and_bounds(self):
        valid = [None, {}, {"min_h": 11}, {"max_h": 4}, {"min_h": 7, "max_h": 7}]
        for vegetation in valid:
            with self.subTest(valid=vegetation):
                d = self.example()
                d["name"] = "valid_vegetation_%d" % self.written
                d["vegetation"] = vegetation
                path = self.write_design(d)
                result = run_doctor(path)
                self.assert_result(result, 0)

        invalid = [
            {"per_ha": -1, "seed": 2.5, "min_h": 12, "max_h": 4},
            {"min_h": 12},       # runtime max_h defaults to 11
            {"max_h": 3},        # runtime min_h defaults to 4
            [40],
        ]
        for vegetation in invalid:
            with self.subTest(invalid=vegetation):
                d = self.example()
                d["name"] = "invalid_vegetation_%d" % self.written
                d["vegetation"] = vegetation
                path = self.write_design(d)
                result = run_doctor(path)
                self.assert_result(result, 1)
                self.assertTrue(doctor_line(result, path).startswith("[CHECK] FAIL"))

    def test_duplicate_output_names_are_rejected_case_insensitively(self):
        first, second = self.example(), self.example()
        first["name"], second["name"] = "Layout_A", "layout_b"
        p1 = self.write_design(first, "design_a.json")
        p2 = self.write_design(second, "design_b.json")
        result = run_doctor(p1, p2)
        self.assert_result(result, 0)
        self.assertTrue(doctor_line(result, p1).startswith("[CHECK] OK"))
        self.assertTrue(doctor_line(result, p2).startswith("[CHECK] OK"))

        second["name"] = "layout_a"
        p2 = self.write_design(second, "design_duplicate.json")
        result = run_doctor(p1, p2)
        self.assert_result(result, 1)
        self.assertIn("name duplicates design_a.json", doctor_line(result, p2))

    def test_mass_and_numeric_preconditions(self):
        drive_only = self.example()
        drive_only["elements"] = [{"id": "d", "kind": "drive", "width_m": 2,
                                    "points": [[0, 0], [5, 0]]}]
        path = self.write_design(drive_only)
        result = run_doctor(path)
        self.assert_result(result, 1)
        self.assertIn("elements must include at least one house or terrace", doctor_line(result, path))

        bad = self.example()
        bad["frame"]["u_bearing_deg"] = float("nan")
        bad["elements"] = [
            {"id": 7, "kind": "house", "u": float("inf"), "v": 0, "w_ft": 0, "d_ft": -1,
             "wall_h": 0, "roof_pitch": 0},
            {"id": "t", "kind": "terrace", "u": 0, "v": 0, "w_m": 0, "d_m": -2},
        ]
        path = self.write_design(bad)
        result = run_doctor(path)
        self.assert_result(result, 1)
        line = doctor_line(result, path)
        for msg in ("frame.u_bearing_deg must be a number", "id must be letters", "u must be a number",
                    "w_ft must be positive", "d_ft must be positive", "wall_h must be positive",
                    "roof_pitch must be positive", "w_m must be positive", "d_m must be positive"):
            self.assertIn(msg, line)

    def test_invalid_ribbon_geometry_is_rejected(self):
        routes = [
            [[0, 0], [1e-10, 0]],
            [[0, 0], [10, 0], [0, 0]],
            [[0, 0], [10, 0], [0, 0.01]],
            [[0, 0], [0.5, 0], [0.5, 5]],
            [[0, 0], [10, 10], [0, 10], [10, 0]],
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0.5]],
        ]
        for points in routes:
            with self.subTest(points=points):
                d = self.example()
                d["name"] = "bad_route_%d" % self.written
                d["elements"] = [
                    {"id": "h", "kind": "house", "u": 0, "v": 0, "w_ft": 20, "d_ft": 20,
                     "wall_h": 3, "roof_pitch": 0.2},
                    {"id": "d", "kind": "drive", "width_m": 2, "points": points},
                ]
                path = self.write_design(d)
                result = run_doctor(path)
                self.assert_result(result, 1)
                self.assertTrue(doctor_line(result, path).startswith("[CHECK] FAIL"))

    def test_all_explicit_designs_are_processed(self):
        good, bad = self.example(), self.example()
        good["name"] = "good"
        bad["name"] = "bad"
        bad["elements"] = []
        p1, p2 = self.write_design(good, "design_good.json"), self.write_design(bad, "design_bad.json")
        result = run_doctor(p1, p2)
        self.assert_result(result, 1)
        self.assertTrue(doctor_line(result, p1).startswith("[CHECK] OK"))
        self.assertTrue(doctor_line(result, p2).startswith("[CHECK] FAIL"))

    def test_design_only_requires_at_least_one_json(self):
        result = run_doctor()
        self.assertEqual(result.returncode, 2, result_detail(result))
        self.assertEqual(result.stdout, "", result_detail(result))
        self.assertIn("usage: python doctor.py", result.stderr)

    def test_normal_cli_still_discovers_folder_designs(self):
        first, second = self.example(), self.example()
        first["name"], second["name"] = "same_output", "SAME_OUTPUT"
        p1 = self.write_design(first, "design_a.json")
        p2 = self.write_design(second, "design_b.json")
        result = run_normal_doctor(self.tmp.name)
        self.assertEqual(result.returncode, 1, result_detail(result))
        self.assertTrue(doctor_line(result, p1).startswith("[CHECK] OK"))
        self.assertIn("name duplicates design_a.json", doctor_line(result, p2))


if __name__ == "__main__":
    unittest.main()
