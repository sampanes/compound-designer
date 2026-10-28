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
| `blender/<design>.blend` | one per layout `design_*.json`: the building masses and drives on a graded copy of the terrain (pads cut to floor level, drives cut and filled to their grade line), with procedural materials, a physical sky, and simple trees scattered where the aerial is green. |
| `exports/<design>_stats.json` | per-element stats (floor elevation, uphill cut, exposed foundation downhill, clearance to the boundary, which `floor_mode` was used, per pad for a stepped house; length and grades for a drive, and which drive reaches each house) and overall building coverage. |
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
rem edit parcel.json: the parcel layer URL, the ID field, and your parcel's ID (see below)
python templates\doctor.py parcels\my_parcel
templates\run_all.bat parcels\my_parcel
```
`doctor.py` finds Blender, probes it once headless (version, numpy, BlenderGIS, EEVEE, the
FreeImage DLL), and validates `parcel.json` and every `design_*.json`, so anything missing shows
up before the slow steps. `run_all.bat` then runs the three steps in order and stops at the first
failure. They are the same three commands you can run by hand:
```
python templates\fetch_gis.py parcels\my_parcel
templates\build_site.bat parcels\my_parcel
templates\place_masses.bat parcels\my_parcel parcels\my_parcel\design_v1.json
```
Add `--no-render` to `run_all.bat` or either Blender wrapper to skip the renders. The wrappers use
`BLENDER` if it is set, else the default 5.1 install, else the newest Blender under Program Files.

`fetch_gis.py` needs only the four keys in the example. It derives the CRS (the NAD83 / UTM zone
that contains the parcel), the local origin, and both bboxes from the parcel itself, writes them
back into `parcel.json`, and writes each file to the path `parcel.json` names (`gis/...` by
default). Files that already exist are skipped, so re-running after an edit is cheap. Flags:
`--force` re-downloads existing files; `--out DIR` resolves those same relative paths under `DIR`
instead of the parcel folder, for a one-off download elsewhere (the Blender steps always read from
the parcel folder). No arguments or `--help` prints usage. A query that matches no parcel stops
with a message naming the where clause it sent, so a wrong `parcel_id_field` or `parcel_id` is
obvious.

`parcels/` is git-ignored. Your parcels, downloads, and designs stay on your machine. If you
want history for them, make `parcels/` its own local repo.

## parcel.json
`examples/parcel.example.json` is the minimal form; `examples/parcel.full.example.json` shows
every key.

You set:

| key | meaning |
| --- | --- |
| `parcel_layer_url` | ArcGIS REST layer URL ending in `/MapServer/<n>` or `/FeatureServer/<n>`. County GIS sites or state aggregators usually have one. |
| `parcel_id_field`, `parcel_id` | field name and value that select your parcel (often an APN). |

Derived by `fetch_gis.py` on the first run and written back into the file; set any of them
yourself to override:

| key | meaning |
| --- | --- |
| `epsg` | projected CRS in meters. Everything is fetched in this CRS. Derived: the NAD83 / UTM zone that contains the parcel (`EPSG:269xx`). |
| `local_origin_xy` | a round point near the parcel. Blender X/Y = CRS minus this origin, so coordinates stay small (float32 precision). Derived: the parcel center rounded to 100 m. |
| `raster_bbox` | `[xmin, ymin, xmax, ymax]` for the detailed DEM and aerial. Derived: the parcel plus `raster_pad_m` (default 150 m), grown to whole pixels. |
| `context_bbox` | wider bbox for the low-res context terrain. Derived: the origin plus and minus `context_half_m` (default 4000 m), grown to whole pixels. |
| `dem`, `aerial`, `parcel`, `context_parcels`, `roads`, `context_dem`, `context_aerial` | output file paths, relative to the parcel folder (default `gis/...`). Set `context_dem` and `context_aerial` to `null` to skip the context terrain. |

Optional:

| key | meaning |
| --- | --- |
| `parcel_out_fields`, `context_out_fields` | attributes to download. **Defaults to the ID field only**, so owner names never land on disk unless you ask for them. |
| `dem_px_m`, `aerial_px_m`, `context_*_px_m` | resolutions (defaults: 1, 0.25, 10, 4 m). Each bbox's width and height must be a whole number of its pixel size, or `fetch_gis.py` stops; derived bboxes always are. |
| `raster_pad_m`, `context_half_m`, `context_vector_buffer_m` | the paddings above, and the buffer around the parcel for neighbor lines and roads (default 200 m). |

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
- `house`: `w_ft` x `d_ft` footprint, `wall_h`, `roof_pitch`. Add `steps` to split the depth into
  pads at different floor levels (a split-level): `2` for two equal pads, or a list of pad depths in
  feet that sum to `d_ft`, front (road side) first. Each pad takes its floor from the ground under
  it, so a deep house on a steep slope steps down the hill instead of standing on one tall
  foundation wall. The stats then carry a `pads` list.
- `terrace`: `w_m` x `d_m`.
- `drive`: a driveway or path. `points` is a polyline of `[u, v]` pairs and `width_m` its width. It
  is graded into the terrain as a ribbon, level across and straight between points, so every point
  is a change of grade. A point that lands on a house or terrace pad takes that pad's floor, which
  is how a drive meets its house. Stats: length, the grade of each segment, the mean and maximum,
  and the segments steeper than `max_grade_pct` (top-level, default 15; a drive can carry its own).
  A segment over the limit is a `[CHECK] FAIL`. When a design has drives, each house's stats also
  say which drive or path reaches it (comes within `reach_m`, default 3 m, of its walls) and the
  design lists `unreached_houses`.

A top-level `vegetation` object controls the trees that `place_masses.py` scatters for the renders:
`per_ha` (default 40), `seed`, `min_h` and `max_h` in meters (4 and 11), and `clear_m`, the gap
kept around every pad and drive (2). Trees go where the aerial image is green, and only on the
terrain, so a bare lot gets few and a wooded one gets many. `"vegetation": null` turns them off.
They are simple shapes in a `vegetation` collection, hidden in the top render.

Houses and terraces have `u`, `v`, and `rot_deg`. The top-level `floor_mode` is the default for
every pad: `balanced` (mean ground under the footprint) or `uphill` (highest ground, no cut). An
element can override it with its own `floor_mode` key, and the per-element stats record which was
used. Duplicate element ids, an invalid `floor_mode`, bad `steps`, or a footprint or drive point
with no DEM under it stop the run with a `[CHECK] FAIL`.

Every mass is one object (walls + roof + a deep foundation that the terrain hides), so you can
move it by hand in Blender. The terrain grading, however, follows the JSON. Copy positions back
into the JSON and re-run to re-grade. Drives are objects too, but their cut and fill lives in the
terrain copy, so move them in the JSON.

## Troubleshooting
| Symptom | Cause and fix |
| --- | --- |
| `[X] no Blender found`, or `blender executable FAIL` | set `BLENDER` to your `blender.exe`; the wrappers and `doctor.py` look there first. |
| `BlenderGIS add-on FAIL` | install BlenderGIS as a legacy add-on with the folder named `BlenderGIS`; the detail lists the GIS-like module names Blender saw. |
| `[X] no parcel matched ...` | the where clause in the message is what the layer was asked. Fix the ID field name or value, then re-run with `--force` (the empty reply was cached). |
| `[X] ... is not a whole number of ... pixels` | a bbox set by hand: widen it to whole pixels, or delete it from `parcel.json` and let `fetch_gis.py` derive one. |
| `DEM georef matches raster_bbox FAIL` | the GeoTIFF's own extent disagrees with `parcel.json`, usually after a bbox edit. Delete the `gis/` rasters and re-run `fetch_gis.py`. |
| `parcel geojson FAIL ... look like lon/lat` | the parcel file is not in the projected CRS. Delete it and re-run `fetch_gis.py`, or re-export it from your GIS in that CRS. |
| `<id> footprint on terrain FAIL` | the mass is off the DEM. `u` and `v` are meters from the lot's front corner; compare the design with `exports/site_stats.json`. |
| `<id> on terrain FAIL` | a drive point is off the DEM; same cause as the footprint case. |
| `<id> grade within 15% FAIL` | a segment of that drive is steeper than `max_grade_pct`; the detail names it. Add a point so the route runs across the slope, lengthen it, or raise the limit. |
| `render pass FAIL` | the materials, sky or tree scatter hit a Blender API problem; the traceback is just above in the log, and the stats and `.blend` were still written. `"vegetation": null` skips the scatter. |
| the first raster read is slow, or fails offline | BlenderGIS downloads the FreeImage DLL for imageio once, and needs internet that one time. |

## Tests
`python -m unittest discover -s tests -v` runs the network-free tests: `fetch_gis.py` against a
faked `urlopen`, the footprint, ribbon and grade-line geometry in `design_geom.py` that
`place_masses.py` uses, and `doctor.py`'s design validation. CI runs the same command on every
push. The Blender scripts themselves have no automated tests; `doctor.py` and their `[CHECK]` lines
are the safety net there, and
[docs/roadmap.md](docs/roadmap.md#develop-anywhere-verify-on-a-blender-machine) says how a change
gets verified on a Blender machine.

## Conventions and caveats
- Real meters, no rescaling. Z is absolute elevation (NAVD88 meters for 3DEP).
- `site_master.blend` is regenerated by `build_site`. Designs never modify it.
- Assessor boundaries and TIGER centerlines are approximate.
- Neighbor lines and roads that run past the detail DEM are draped on the context terrain when
  one is configured, and dropped otherwise.
- Fitting on the lot is not the same as being allowed: zoning, setbacks, septic, access, and
  slope rules are local and not checked here.
