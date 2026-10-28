# Tests for the design-JSON validation in templates/doctor.py (run as a subprocess with no Blender, so
# only the design checks matter here). Also keeps examples/design.example.json valid.
# Run: python -m unittest discover -s tests -v
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DOCTOR = os.path.join(ROOT, "templates", "doctor.py")
EXAMPLE = os.path.join(ROOT, "examples", "design.example.json")


def doctor_line(path):
    """The [CHECK] line doctor.py prints for one design file."""
    env = dict(os.environ, BLENDER=os.path.join(tempfile.gettempdir(), "no-such-blender"))
    out = subprocess.run([sys.executable, DOCTOR, path], capture_output=True, text=True, env=env).stdout
    tag = "design " + os.path.basename(path)
    return next(l for l in out.splitlines() if l.startswith("[CHECK]") and tag in l)


def write_design(d):
    path = os.path.join(tempfile.mkdtemp(prefix="doctor_"), "design_t.json")
    with open(path, "w") as f:
        json.dump(d, f)
    return path


class DoctorDesignTests(unittest.TestCase):
    def test_example_design_passes(self):
        line = doctor_line(EXAMPLE)
        self.assertTrue(line.startswith("[CHECK] OK"), line)
        self.assertIn("8 element(s)", line)

    def test_drive_and_steps_problems_are_named(self):
        with open(EXAMPLE) as f:
            d = json.load(f)
        d["max_grade_pct"] = 0
        d["elements"] = [
            {"id": "h", "kind": "house", "u": 0, "v": 0, "w_ft": 30, "d_ft": 32, "steps": [16, 12], "wall_h": 3, "roof_pitch": 0.3},
            {"id": "h2", "kind": "house", "u": 0, "v": 0, "w_ft": 30, "d_ft": 32, "steps": 1, "wall_h": 3, "roof_pitch": 0.3},
            {"id": "d1", "kind": "drive", "width_m": 3},
            {"id": "d2", "kind": "drive", "width_m": 0, "points": [[0, 0], [0, 0], [5, 5]], "max_grade_pct": -1},
            {"id": "d3", "kind": "drive", "width_m": 2, "points": [[0, 0], [1]]},
            {"id": "x", "kind": "pool", "u": 0, "v": 0},
        ]
        line = doctor_line(write_design(d))
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

    def test_plain_house_and_integer_steps_pass(self):
        with open(EXAMPLE) as f:
            d = json.load(f)
        d["elements"] = [
            {"id": "a", "kind": "house", "u": 0, "v": 0, "w_ft": 30, "d_ft": 30, "wall_h": 3, "roof_pitch": 0.3},
            {"id": "b", "kind": "house", "u": 0, "v": 0, "w_ft": 30, "d_ft": 30, "steps": 3, "wall_h": 3, "roof_pitch": 0.3},
            {"id": "p", "kind": "drive", "width_m": 1.5, "points": [[0, 0], [3, 4]]},
        ]
        self.assertTrue(doctor_line(write_design(d)).startswith("[CHECK] OK"))

    def test_vegetation_key(self):
        with open(EXAMPLE) as f:
            d = json.load(f)
        d["vegetation"] = None
        self.assertTrue(doctor_line(write_design(d)).startswith("[CHECK] OK"))
        d["vegetation"] = {"per_ha": -1, "seed": 2.5, "min_h": 12, "max_h": 4}
        line = doctor_line(write_design(d))
        for msg in ("vegetation.per_ha must be a number >= 0", "vegetation.seed must be a whole number >= 0",
                    "vegetation.min_h is larger than max_h"):
            self.assertIn(msg, line)
        d["vegetation"] = [40]
        self.assertIn("vegetation must be an object or null", doctor_line(write_design(d)))


if __name__ == "__main__":
    unittest.main()
