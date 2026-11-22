# Writes scout_cases.json next to this file: synthetic inputs with expectations computed by scout_geo.py.
# The file is shared with rural-scout (copy it to rural-scout/tests/fixtures/ unchanged after a rule change).
# Run: python tests/fixtures/make_scout_cases.py
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "templates"))
import scout_geo as g

PARSE = [
    "https://www.zillow.com/homedetails/000-QUIET-HAWK-Trl-%23--Anytown-CO-80000/123_zpid/?utm_campaign=share&utm_source=txt",
    "https://www.zillow.com/homedetails/0000-Quiet-Hawk-Rd-%2312B-Anytown-CO-80000/9_zpid/",
    "https://www.zillow.com/homedetails/42-Elm-St-APT-3-Port-St-Lucie-FL-34952/77_zpid/",
    "https://www.zillow.com/homedetails/5-St-Andrews-Dr-Anytown-CO-80000/1_zpid/",
    "https://www.zillow.com/homedetails/9-Main-St-N-Anytown-CO-80000/2_zpid/",
    "https://www.zillow.com/homedetails/Lot-7-Quiet-Hawk-Trl-Anytown-CO-80000/3_zpid/",
    "https://www.redfin.com/CO/Anytown/0-Quiet-Hawk-Trl-80000/home/555?share=1",
    "https://www.redfin.com/CO/Any-Town/12-Quiet-Hawk-Trl-80000/home/556",
    "https://www.realtor.com/realestateandhomes-detail/7-Quiet-Hawk-Trl_Any-Town_CO_80000_M1-2",
    "https://www.realtor.com/realestateandhomes-detail/0-Quiet-Hawk-Trl_Anytown_CO_80000_M3-4#photos",
    "https://listings.example.com/homes/123-Quiet-Hawk-Trl-Anytown-CO-80000",
    "000 Quiet Hawk Trl #-, Anytown, CO 80000",
    "12 Quiet Hawk Trl Anytown CO",
    "12 Quiet Hawk Trl Unit 4, Anytown, CO 80000-1234",
    "Quiet Hawk Trl, Anytown, CO",
    "  0 County Road 5, Anytown, CO 80000  ",
    "https://www.zillow.com/homedetails/0-County-Road-5-Anytown-CO-80000/4_zpid/",
    "https://www.zillow.com/homedetails/000-N-State-Route-260-Any-Town-AZ-85000/5_zpid/",
    "12 Highway 89A, Anytown, AZ 85000",
    "5 US Highway 191 Anytown AZ",
    "7 Rd 12 Anytown CO",
]
KEYS = ["street_number", "street", "city", "state", "zip", "unit", "vacant", "url", "source", "listing_id", "query"]

STREET = [
    ["1234 W QUIET HAWK TRAIL", "Quiet Hawk Trl"],
    ["1234 W QUIET HAWK RD", "Quiet Hawk Trl"],
    ["1234 QUIET HAWK", "Quiet Hawk Trl"],
    ["12 N QUIET HAWK DR.", "N Quiet Hawk Drive"],
    ["12 ELM ST", "Quiet Hawk Trl"],
    ["5 ST ANDREWS DR", "St Andrews Dr"],
]
CORE = ["N Quiet Hawk Drive", "QUIET HAWK DR", "Main St N", "St Andrews Dr", "N", "County Road 5"]
APN = [["123-45-067", "67"], ["12345067", "067"], ["123-45-067", "7"], ["123-45-067", "68"], ["12-34A", "34"],
       ["123-45-067", ""]]
APN_V = ["123-45-678a", " 12 345 678 ", "R0012.34"]

FLOOD_OK = {"status": "ok", "pct_sfha": 0, "pct_floodway": 0}
FLAGS = [
    {"flood": FLOOD_OK, "terrain": {"pct_area_grade_under_15": 80, "grade_median_pct": 8},
     "roads": {"status": "ok", "nearest_m": 5}, "streams": {"status": "ok", "nearest_m": None}, "lidar": ["XX_Example_2020"]},
    {"flood": {"status": "ok", "pct_sfha": 40, "pct_floodway": 12}, "terrain": {"pct_area_grade_under_15": 60, "grade_median_pct": 11},
     "roads": {"status": "ok", "nearest_m": 220},
     "streams": {"status": "ok", "nearest_m": 0, "nearest_name": "Willow Creek", "nearest_kind": "perennial stream"},
     "lidar": ["XX_Example_2020"]},
    {"flood": {"status": "unverified"}, "terrain": {"pct_area_grade_under_15": 5, "grade_median_pct": 45},
     "roads": {"status": "unverified"}, "streams": {"status": "ok", "nearest_m": 20, "nearest_name": "", "nearest_kind": ""},
     "lidar": []},
    {"flood": FLOOD_OK, "terrain": {"pct_area_grade_under_15": 30, "grade_median_pct": 31},
     "roads": {"status": "ok", "nearest_m": None}, "streams": {"status": "unverified"}, "lidar": None},
    {"flood": FLOOD_OK, "terrain": None, "roads": {"status": "ok", "nearest_m": 30}, "streams": {"status": "ok", "nearest_m": 31}},
]
RANK = [
    {"cands": [{"id": "123-45-068", "acres": 2.2, "dist_m": 50}, {"id": "123-45-067", "acres": 2.3, "dist_m": 400},
               {"id": "123-45-069", "acres": 4.0, "dist_m": 10}], "acres": 2.3, "number": "67"},
    {"cands": [{"id": "A", "acres": 5.0, "dist_m": 300}, {"id": "B", "acres": 5.1, "dist_m": 100},
               {"id": "C", "acres": 4.9, "dist_m": 50}], "acres": 5.0, "number": None},
    {"cands": [{"id": "A", "acres": 5.0, "dist_m": 300}, {"id": "B", "acres": 9.0, "dist_m": 100}], "acres": None, "number": None},
]
FIELDS = [
    {"fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}, {"name": "PARCELID", "type": "esriFieldTypeString"},
                {"name": "APN", "type": "esriFieldTypeString"}, {"name": "SITUS_ADDR", "type": "esriFieldTypeString"},
                {"name": "OWNER_ADDR", "type": "esriFieldTypeString"}],
     "sample": {"PARCELID": "12345678", "APN": "123-45-678"}},
    {"fields": [{"name": "PIN", "type": "esriFieldTypeString"}, {"name": "MAIL_ADDRESS", "type": "esriFieldTypeString"},
                {"name": "ADDRESS", "type": "esriFieldTypeString"}], "sample": None},
    {"fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}, {"name": "NAME", "type": "esriFieldTypeString"}], "sample": None},
]
LAYERS = [
    ["Anytown County Parcels", "anytown_gis", "Anytown County", True, True, "parcels"],
    ["Parcels Historic 2005 to 2010", "anytown_gis", "Anytown County", True, True, "parcels"],
    ["Road Centerlines", "someone", "Anytown County", False, False, "parcels"],
    ["Anytown Zoning Districts", "anytown_gis", "Anytown County", True, True, "zoning"],
]

out = {
    "_about": "Shared test cases for compound-designer's templates/scout_geo.py and rural-scout's js/listing.js and "
              "js/geo.js. Inputs are synthetic. Expectations come from scout_geo.py; keep both repos' copies identical.",
    "parse_listing": [{"input": t, "expect": {k: g.parse_listing(t)[k] for k in KEYS}} for t in PARSE],
    "same_street": [{"addr": a, "street": s, "expect": g.same_street(a, s)} for a, s in STREET],
    "street_core": [{"street": s, "expect": g.street_core(s), "suffix": g.street_suffix(s)} for s in CORE],
    "apn_tail_match": [{"id": i, "number": n, "expect": g.apn_tail_match(i, n)} for i, n in APN],
    "apn_variants": [{"apn": a, "variants": g.apn_variants(a), "like": g.apn_like(a)} for a in APN_V],
    "flags": [{"report": r, "expect": g.flags(r)} for r in FLAGS],
    "rank_candidates": [dict(c, expect=[x["id"] for x in g.rank_candidates(c["cands"], c["acres"], number=c["number"])])
                        for c in RANK],
    "guess_fields": [dict(f, expect=list(g.guess_fields(f["fields"], f["sample"]))) for f in FIELDS],
    "rank_layer": [{"args": a, "expect": g.rank_layer(*a)} for a in LAYERS],
}
path = os.path.join(HERE, "scout_cases.json")
with open(path, "w", encoding="utf-8", newline="\n") as f:
    json.dump(out, f, indent=1, ensure_ascii=True)
    f.write("\n")
print("[OK] %s" % path)
