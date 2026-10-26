# Parcel notes -- <parcel name>

Copy this file to `parcels/<name>/notes.md` and fill it in as you go. Everything here stays
local (`parcels/` is git-ignored). Mark anything you have not confirmed as **unverified**.

## Listing
- URL: <listing url>
- Seen: YYYY-MM-DD
- Asking price / status: <optional>
- Acreage per listing: 0.0 ac
- Acreage computed from the parcel polygon (`exports/site_stats.json`): 0.0 ac

## Parcel
- Parcel ID (APN): 000-00-000
- Jurisdiction (county, city, zoning district): <county>, <zone> (unverified)
- Parcel layer URL: https://gis.example.com/arcgis/rest/services/Parcels/MapServer/0
- ID field: APN
- Boundary source: assessor lines, not a survey

## Coordinates
- CRS: EPSG:269xx (NAD83 / UTM zone xx, meters) -- chosen because <reason>
- Vertical datum and units: NAVD88 meters (3DEP)
- Local origin (`local_origin_xy`): [500000.0, 4000000.0]
- `raster_bbox`: [499800.0, 3999800.0, 500200.0, 4000200.0] (parcel plus about 150 m)
- `context_bbox`: [496000.0, 3996000.0, 504000.0, 4004000.0]

## Data sources
| Layer | Service | Fetched | Notes |
| --- | --- | --- | --- |
| Parcel + neighbors | <parcel layer url> | YYYY-MM-DD | ID field only |
| Roads | Census TIGERweb Transportation/8 | YYYY-MM-DD | centerlines, approximate |
| DEM | USGS 3DEP exportImage, 1 m | YYYY-MM-DD | lidar project / year from `identify`: <project> (<year>) |
| Aerial | USGS NAIPPlus exportImage, 0.25 m | YYYY-MM-DD | NAIP year: <year> |
| Context DEM / aerial | same services, 10 m / 4 m | YYYY-MM-DD | |

## Access and surroundings
- Road frontage, driveway options, grade to the road: <notes>
- Utilities (power, water, sewer or septic, internet): unverified
- Neighbors, noise, views: <notes>

## Constraints to check (all unverified until confirmed with the jurisdiction)
- Zoning and allowed uses, number of dwellings
- Setbacks and lot coverage
- Septic or sewer, water rights or well
- Flood zone, stream setbacks, wetlands
- Easements, access rights, HOA or covenants
- Hillside and grading rules

## Design log
| Date | Design file | What changed | Verdict |
| --- | --- | --- | --- |
| YYYY-MM-DD | `design_v1.json` | first layout from the example | <notes> |
