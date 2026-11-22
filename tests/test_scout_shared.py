# The listing, matching, and triage cases in tests/fixtures/scout_cases.json are shared with rural-scout
# (js/listing.js and js/geo.js run the same file), so the web app and scout_parcel.py read listings and
# flag parcels the same way. When a rule changes, regenerate the expectations here and copy the file to
# rural-scout/tests/fixtures/ unchanged; its CI compares the two copies.
# Run: python -m unittest discover -s tests -v
import json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "templates"))
import scout_geo as g

with open(os.path.join(HERE, "fixtures", "scout_cases.json"), encoding="utf-8") as f:
    CASES = json.load(f)


class Shared(unittest.TestCase):
    def test_parse_listing(self):
        for c in CASES["parse_listing"]:
            p = g.parse_listing(c["input"])
            with self.subTest(c["input"]):
                self.assertEqual({k: p[k] for k in c["expect"]}, c["expect"])

    def test_street_matching(self):
        for c in CASES["same_street"]:
            with self.subTest(c["addr"]):
                self.assertEqual(g.same_street(c["addr"], c["street"]), c["expect"])
        for c in CASES["street_core"]:
            with self.subTest(c["street"]):
                self.assertEqual((g.street_core(c["street"]), g.street_suffix(c["street"])), (c["expect"], c["suffix"]))

    def test_apn(self):
        for c in CASES["apn_tail_match"]:
            with self.subTest(c):
                self.assertEqual(g.apn_tail_match(c["id"], c["number"]), c["expect"])
        for c in CASES["apn_variants"]:
            with self.subTest(c["apn"]):
                self.assertEqual((g.apn_variants(c["apn"]), g.apn_like(c["apn"])), (c["variants"], c["like"]))

    def test_flags_and_ranking(self):
        for c in CASES["flags"]:
            self.assertEqual(g.flags(c["report"]), c["expect"])
        for c in CASES["rank_candidates"]:
            got = [x["id"] for x in g.rank_candidates(c["cands"], c["acres"], number=c["number"])]
            self.assertEqual(got, c["expect"])

    def test_layer_fields(self):
        for c in CASES["guess_fields"]:
            self.assertEqual(list(g.guess_fields(c["fields"], c["sample"])), c["expect"])
        for c in CASES["rank_layer"]:
            self.assertEqual(g.rank_layer(*c["args"]), c["expect"])


if __name__ == "__main__":
    unittest.main()
