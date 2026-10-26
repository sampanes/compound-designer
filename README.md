# compound-designer

Put a real land parcel into Blender -- its boundary, real lidar terrain, and aerial imagery -- and
try out building layouts on it: houses, courtyards, pads cut into the slope, views from where you
would actually stand.

A sketchbook for "what could fit on this lot?", not survey, engineering, or permit work.

Everything is plain scripts: a stdlib-Python downloader and two headless Blender scripts. The
downloader prints `[OK]`/`[SKIP]` per file and stops on a service error; the two Blender scripts
print `[CHECK] OK/FAIL` lines and exit non-zero if any check fails, so the pipeline is easy to
re-run after you edit a config.

## Docs
- [docs/vision.md](docs/vision.md) -- goals, motivating examples, design principles, non-goals.
- [docs/roadmap.md](docs/roadmap.md) -- the seven phases, milestone 1 status, parcel-analysis ideas.
- [docs/tool-stack.md](docs/tool-stack.md) -- which tool does what, and what's optional or planned.
- [docs/data-prep.md](docs/data-prep.md) -- preparing inputs in ArcGIS Pro or QGIS instead of `fetch_gis.py`.
- [docs/research-notes.md](docs/research-notes.md) -- BlenderGIS on Blender 5.1, public data
  sources, finding a parcel, steep-lot lessons.

## What you get per parcel
Everything lands in subfolders of the parcel folder. `<design>` is the `name` field of a design
JSON.

| path | contents |
| --- | --- |
| `gis/` | the downloaded inputs: DEM, aerial, parcel, neighbors, roads, and the optional context rasters. |
| `blender/site_master.blend` | 1 m lidar terrain with the aerial image draped on it, an optional ~8 km low-res context terrain (horizons and views), the parcel boundary, neighbor lines, road centerlines, a 1.8 m person for scale, and top/oblique/eye-level cameras. |
| `exports/site_stats.json` | area, elevation range, slope (at the DEM pixel size and 5 m smoothed), best-fit grade and which way the lot faces. |
| `renders/cam_top.png`, `cam_oblique.png`, `cam_eye.png` | the bare site from above, from an oblique, and from eye level downhill of the lot looking back up the slope. |
| `blender/<design>.blend` | one per layout `design_*.json`: the building masses on a graded copy of the terrain (pads cut to floor level). |
| `exports/<design>_stats.json` | per-element stats (floor elevation, uphill cut, exposed foundation downhill, clearance to the boundary, which `floor_mode` was used) and overall building coverage. |
| `renders/<design>_overview.png`, `_courtyard_eye.png`, `_from_road.png`, `_top.png` | the layout from downhill and off to one side, from the terrace looking out, from the road, and from above. |

## Requirements
- Blender 5.1+ with the [BlenderGIS](https://github.com/domlysz/BlenderGIS) add-on installed and
  named `BlenderGIS`. GDAL is not needed. The first raster read makes BlenderGIS download a
  FreeImage DLL for imageio. The scripts try the `BLENDER_EEVEE` render engine and then
  `BLENDER_EEVEE_NEXT` (Blender 5.0 renamed it back), so 4.2 and later may work but are untested.
- Python 3 (stdlib only) for `fetch_gis.py`.
- US parcels for the bundled data sources: USGS 3DEP elevation, USGS NAIP imagery, and Census
  TIGERweb roads. The parcel layer can be any ArcGIS REST layer that has an ID field.
- The `.bat` wrappers are for Windows cmd. On other platforms, run the same `blender -b ...`
  command they contain.

## Quick start
```
mkdir parcels\my_parcel
copy examples\parcel.example.json parcels\my_parcel\parcel.json
copy examples\design.example.json parcels\my_parcel\design_v1.json
copy examples\notes.example.md parcels\my_parcel\notes.md
rem edit parcel.json: parcel layer URL, parcel ID, CRS, origin, bboxes (see below)
python templates\fetch_gis.py parcels\my_parcel
templates\build_site.bat parcels\my_parcel
templates\place_masses.bat parcels\my_parcel parcels\my_parcel\design_v1.json
```
Set `BLENDER` to a different `blender.exe` if you're not using the default 5.1 install path.

`fetch_gis.py` writes each file to the path `parcel.json` names, under the parcel folder
(`gis/...` by default), and skips files that already exist. Flags: `--force` re-downloads existing
files; `--out DIR` resolves those same relative paths under `DIR` instead of the parcel folder,
for a one-off download elsewhere (the Blender steps always read from the parcel folder). No
arguments or `--help` prints usage. A query that matches no parcel stops with a message naming the
where clause it sent, so a wrong `parcel_id_field` or `parcel_id` is obvious.

`parcels/` is git-ignored. Your parcels, downloads, and designs stay on your machine. If you
want history for them, make `parcels/` its own local repo.

## parcel.json
| key | meaning |
| --- | --- |
| `epsg` | projected CRS in meters, for example a UTM zone (`EPSG:269xx` for NAD83 / UTM). Everything is fetched in this CRS. |
| `local_origin_xy` | a round point near the parcel. Blender X/Y = CRS minus this origin, so coordinates stay small (float32 precision). |
| `raster_bbox` | `[xmin, ymin, xmax, ymax]` for the detailed DEM and aerial: the parcel plus about 150 m. |
| `context_bbox` | optional wider bbox (several km) for the low-res context terrain. |
| `parcel_layer_url` | ArcGIS REST layer URL ending in `/MapServer/<n>` or `/FeatureServer/<n>`. County GIS sites or state aggregators usually have one. |
| `parcel_id_field`, `parcel_id` | field name and value that select your parcel (often an APN). |
| `parcel_out_fields`, `context_out_fields` | attributes to download. **Defaults to the ID field only**, so owner names never land on disk unless you ask for them. |
| `dem_px_m`, `aerial_px_m`, `context_*_px_m` | resolutions (defaults: 1, 0.25, 10, 4 m). Each bbox's width and height must be a whole number of its pixel size, or `fetch_gis.py` stops. |
| `dem`, `aerial`, `parcel`, ... | output file paths, relative to the parcel folder. |

Tips:
- To find which lidar project covers a point, call `identify` on the 3DEP ImageServer with
  `returnCatalogItems=true`.
- A vacant lot often has no street address in assessor data. A listing's "address" may really be
  the end of the APN. Search the parcel layer by acreage near the street.
- A parcel split by a road comes back as a MultiPolygon. All three scripts treat the outer ring of
  its largest polygon as the parcel for the frame, stats, and inside checks; `build_site.py` draws
  every outer ring.

## design JSON
A layout lives in a frame aligned with the lot: **u** runs along the road (`u_bearing_deg`, a
compass bearing) and **v** runs perpendicular to it, into the lot (downhill on a lot that falls
away from the road). The frame origin is the front corner with the smallest u.
Elements:
- `house`: `w_ft` x `d_ft` footprint, `wall_h`, `roof_pitch`.
- `terrace`: `w_m` x `d_m`.

Each has `u`, `v`, and `rot_deg`. The top-level `floor_mode` is the default for every element:
`balanced` (mean ground under the footprint) or `uphill` (highest ground, no cut). An element can
override it with its own `floor_mode` key, and the per-element stats record which was used.
Duplicate element ids, an invalid `floor_mode`, or a footprint with no DEM under it stop the run
with a `[CHECK] FAIL`.

Every mass is one object (walls + roof + a deep foundation that the terrain hides), so you can
move it by hand in Blender. The terrain grading, however, follows the JSON. Copy positions back
into the JSON and re-run to re-grade.

## Conventions and caveats
- Real meters, no rescaling. Z is absolute elevation (NAVD88 meters for 3DEP).
- `site_master.blend` is regenerated by `build_site`. Designs never modify it.
- Assessor boundaries and TIGER centerlines are approximate.
- Neighbor lines and roads that run past the detail DEM are draped on the context terrain when
  one is configured, and dropped otherwise.
- Fitting on the lot is not the same as being allowed: zoning, setbacks, septic, access, and
  slope rules are local and not checked here.
