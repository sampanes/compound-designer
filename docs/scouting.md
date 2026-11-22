# Scouting listings

Before anything goes into Blender, `templates/scout_parcel.py` answers two questions for each
listing in seconds: *which parcel is it?* and *is it worth a closer look?* It is built for going
through hundreds of listings: everything is cached, every service failure is contained to its own
section of the report, and a batch writes one CSV row per listing.

## Commands

```
python templates\scout_parcel.py listing "<listing URL or address>" [--acres 7.5] [--apn 123-45-678]
python templates\scout_parcel.py report --layer <parcel layer URL> --id 123-45-678 [--id-field APN]
python templates\scout_parcel.py init parcels\my_parcel --layer <parcel layer URL> --id 123-45-678
python templates\scout_parcel.py batch listings.csv results.csv [--reports parcels\_scout_reports]
```

- `listing` accepts a Zillow, Redfin, or Realtor.com link (share links with tracking parameters are
  fine) or a typed address. Pass `--acres` from the listing for vacant land; pass `--apn` when the
  listing or a broker page shows one.
- `init` writes the four-key `parcel.json` that `fetch_gis.py` needs, plus `scout.json` (the
  report) and `notes.md` from the template, so a scouted parcel goes straight into `run_all.bat`.
- `batch` reads a CSV with a header row and the columns `name, listing, acres, apn, layer,
  id_field` (any order, blanks allowed). See [`examples/listings.example.csv`](../examples/listings.example.csv).
  Exit codes: `listing` returns 0 only when one parcel was found, 1 otherwise.

The cache (`parcels/_scout_cache.json` by default, `--cache` to move it) holds geocodes, county
lookups, and the parcel and zoning layer chosen for each county. A second run over the same area
makes no discovery calls. To pin a layer by hand, add an entry keyed
`layer|parcels|<county GEOID>` with `url`, `id_field`, and `addr_field` (zoning:
`layer|zoning|<GEOID>` with `url` and `layers: [{url, fields}]`).

## How a listing becomes a parcel

1. **Parse the listing.** Tracking parameters are dropped. Unit markers (`#`, `%23`, `#-`,
   `APT 3`) are removed. A street number that is missing or all zeros (`0`, `000`, `0000`) means
   vacant land with no assigned address: the number is dropped rather than geocoded. A route word
   followed by a number keeps the number (`County Road 5`, `Highway 89A`, `State Route 260`).
2. **Place it.** OpenStreetMap Nominatim geocodes the street, falling back to the city, then the
   ZIP. Rural streets are often missing from OSM, so the city fallback is common.
3. **Find the county, plural.** The Census geocoder gives the county at the point and at eight
   points 12 km around it. A town's center can sit in a different county than the lot, so every
   nearby county is a candidate.
4. **Find each county's parcel layer.** An ArcGIS Online search for `"<county>" parcels` finds
   county-published hosted layers, and the best-ranked hit is kept with up to three runners-up.
   Ranking favors titles with "parcel" and the county name, a readable ID field, and a situs-address
   field. It penalizes historical, clipped, and sales layers.
5. **Find the street in the parcel data.** The parcel layer's situs-address field is the most
   reliable map of rural streets. The search is `LIKE '%<street core>%'`: suffixes and directionals
   are stripped because sources disagree ("Drive" vs "Rd"), then the suffix narrows the hits again
   when it can. The first county and layer whose data has the street wins. If the top layer lacks it,
   the runners-up are tried, because copies of county parcels are often partial or stale. With a real
   street number, a county or layer that has the street but not the number is only a fallback: street
   names repeat across a county line, so the search keeps going for one that has the number.
6. **Pick the parcel.**
   - A real street number matches the situs address exactly.
   - Vacant land is matched by acreage (within 5%) among parcels within 1.5 km of that street's
     parcels.
   - A listing number that equals the tail of a candidate's APN wins ties. Vacant lots are often
     listed as "79 Some Rd" when the APN ends in 079.
   - Results are `found`, `ambiguous` (candidates listed), or `not_found`. A match made only near
     a geocoded point (street not in any parcel data) is never `found`.

## What the report checks

| Section | Source | Notes |
| --- | --- | --- |
| Shape | the parcel polygon | acres from the geometry (all parts, holes removed), extent, center |
| Terrain | USGS 3DEP `getSamples` | about 900 points on a grid over the lot. Min, max, relief, median and p90 grade, % of the lot under 15% and 25% grade, overall grade and the direction the lot faces from a best-fit plane |
| Lidar | 3DEP `identify` | 1 m projects covering the center |
| Flood | FEMA flood zones via Esri's public `USA_Flood_Hazard_Areas` mirror, FEMA NFHL as fallback | % of the lot in each zone, in the SFHA (1% annual chance), and in a regulatory floodway |
| Streams | USGS NHD large-scale flowlines | nearest flowline and nearest named stream, distance to the boundary (0 = crosses) |
| Roads | Census TIGERweb primary, secondary, local | nearest centerline to the boundary |
| Zoning | county zoning layer from the same ArcGIS Online search | every polygon layer of the service is tried, since the first is often empty |
| Flags | all of the above | floodway, SFHA, little land under 15%, no mapped road within 30 m, stream crossing or within 30 m, no 1 m lidar |

Owner names never leave the parcel service: parcel queries request only the ID and situs-address
fields.

## Lessons behind the design

- **Zillow and many county GIS servers block scripts** (HTTP 403, or a bot-challenge page). Broker
  sites often show the APN as "Property ID". ArcGIS Online usually has a county-published copy of
  the parcels that answers plain queries.
- **Listing ZIPs disagree.** The same lot can appear with two or three ZIP codes across sites and
  within one Zillow page. Treat the ZIP as a hint, not a key.
- **FEMA's own NFHL service resets connections** from some networks. Esri's public mirror has the
  same fields (`FLD_ZONE`, `ZONE_SUBTY`, `SFHA_TF`). City flood layers usually cover city limits only,
  so an empty result there says nothing about an unincorporated lot.
- **No mapped flood zone is not the same as no flood risk.** Many rural areas were never studied.
  The report says "possibly unstudied" instead of "none".
- **APN formats differ by county and by field.** A layer can carry both an internal key
  (`1012345067001`) and the printed label (`123-45-067`). The ID guess prefers a field whose sample
  value has separators. Lookups try the APN as given, upper case, without separators, and as a
  `LIKE` pattern.
- **Census TIGER and OSM both miss rural and private roads.** "No mapped road within 30 m" means
  check for an access easement, not that the lot is landlocked.
- **Grade from a sampled grid agrees with the full pipeline.** On a steep test lot, the scout's
  median grade matched `build_site.py`'s 5 m smoothed grade to the tenth of a percent.

## The web version and the shared cases

[rural-scout](https://github.com/sampanes/rural-scout) runs the same lookup in the browser (its
`js/listing.js`, `js/geo.js`, and `js/scout.js` port `scout_geo.py` and `scout_parcel.py`; the county
comes from the FCC area API, which allows browser calls), with a satellite map, a batch table, and the
drive time to town. A found parcel's card shows the `init` command for this repo.

`tests/fixtures/scout_cases.json` holds synthetic cases for parsing, street and APN matching, flags,
and candidate ranking, with expectations computed by `scout_geo.py`. Both repos test against the same
file, and rural-scout's CI fails when its copy differs from this one. After changing a rule here:

```
python tests\fixtures\make_scout_cases.py
python -m unittest discover -s tests
```

then copy the regenerated file to rural-scout's `tests\fixtures\` and port the rule to its `js/`.

## Triage, then design

The scout's job is to drop most listings cheaply. A listing worth more than a glance goes through
`init`, then `run_all.bat` for the full site and massing work. Its `scout.json` sits beside
`parcel.json` as the record of why it made the cut.
