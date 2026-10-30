# Roadmap

Seven phases. Only the first four are needed for the first milestone; Phases 5-7 come later.

## Milestone 1 -- proof of concept

Goal: a few accurately sized hypothetical houses on a real parcel with real terrain, inspected in
3D.

| Criterion | State |
| --- | --- |
| One real parcel loaded | Done (`fetch_gis.py` + `build_site.py`) |
| Measured boundary visible | Done (draped boundary line; area checked against the source polygon) |
| Real elevation as terrain | Done (1 m 3DEP lidar as a real mesh) |
| At least three movable, dimensionally accurate masses | Done (`place_masses.py`, one object per mass) |
| A courtyard or shared outdoor area | Done (`terrace` element) |
| Navigable views, including eye level | Done (top, oblique, eye-level cameras; 1.8 m person for scale) |
| A saved, editable Blender project | Done (`site_master.blend` + one `.blend` per design) |
| At least one attractive overview render | Basic renders work; materials and vegetation pass not done |
| A documented, repeatable import workflow | Done (README; both Blender steps print `[CHECK]` lines) |

Not required for milestone 1: detailed interiors, automatic layouts, Godot.

**Next:** [Milestone 3](#milestone-3----access-that-works-on-a-steep-lot). Milestone 2 is done and
verified; its findings are what Milestone 3 fixes.

### Verified runs

| What | When | Versions |
| --- | --- | --- |
| `build_site.py` and `place_masses.py` on one real parcel, headless, no GDAL | 2026-10 | Blender 5.1.1, BlenderGIS commit `2add45f` (see [research-notes.md](research-notes.md#blendergis-on-blender-51)) |
| Fresh folder from the README Quick start (four-key `parcel.json`, `doctor.py`, `run_all.bat`), end to end | 2026-10 | Blender 5.1.1, BlenderGIS commit `2add45f`; derived bboxes matched a hand-made setup and every design stat came out identical |
| Milestone 2 checklist: `design_v1` regression (only `vegetation` added to the stats), example `design_v2` with a split-level house, a drive and paths, renders inspected | 2026-10 | Blender 5.1.1, BlenderGIS commit `2add45f` |

## Milestone 2 -- a steep-lot compound you could pitch

Goal: one layout on a real hillside parcel that looks good in a render and answers "how do you
get in?" Everything is still produced by `run_all.bat` from JSON; no hand edits in Blender.

| Criterion | Done when | State |
| --- | --- | --- |
| Attractive overview render | `place_masses.py` gives walls, roofs, and terrace paving distinct materials, adds sun and sky lighting, and scatters vegetation on the terrain outside the pads and drives. Free or procedural assets only. If an optional asset is missing, the run falls back to plain materials and still passes. | Verified (Blender 5.1.1). Procedural materials (noise and brick nodes), a physical sky, and two simple tree shapes. Three fixes from the Blender run: the sky type (5.0 replaced `NISHITA`), the sky azimuth (was 180 deg off the sun lamp; checked by rendering the sky in eight directions), and the tree filter (arid scrub is never greener than it is red, so dark yellow-green pixels count too). Colors are converted from sRGB to linear so they no longer render washed out |
| Driveway and path element | A design element (for example `drive`) takes a polyline in `u`/`v` and a width, and is graded into the terrain as a ribbon. Stats report the length plus the mean and maximum grade, and flag segments steeper than a configurable `max_grade_pct` (default 15). | Verified (Blender 5.1.1): ribbons graded into the terrain, per-segment grades, and `<id> grade within N% FAIL` on steep segments |
| Stepped houses | A `house` can sit on two or more pads at different floor levels (split-level), with per-pad stats, so a deep footprint on a steep slope does not need one tall foundation wall. | Verified (Blender 5.1.1): two pads at different floors, a roof per pad, per-pad stats |
| A `design_v2` that uses all three | On a lot that falls away from the road: every house is reachable by a drive or path within `max_grade_pct`, or the stats say which one is not. | The example runs on a real steep lot once `u_bearing_deg` is set to the lot's road; every path in it is too steep there, which the grade checks report. `unreached_houses` is geometric (no drive nearby), not grade-aware. A layout that actually solves access on a steep lot is design work, not code |
| Verified on a Blender machine | A row in Verified runs (see the workflow below). | Done (see Verified runs) |

Not in scope: real driveway engineering (drainage, turning radii, retaining walls), interiors,
and Godot.

### Develop anywhere, verify on a Blender machine

Code can be written on a machine without Blender or a parcel. `fetch_gis.py` changes go with
tests in `tests/`, which CI runs. The Blender scripts are verified on a machine that has Blender,
BlenderGIS, and at least one parcel folder:

```
git pull
python templates\doctor.py parcels\<parcel>
templates\run_all.bat parcels\<parcel>
```

`place_masses.py` keeps the previous run's stats beside the new ones as
`exports/<design>_stats.prev.json`. Diff the two for every design (`git diff --no-index` works on
any two files): the diff must show only the fields the change meant to add or change. Look at the
renders, then add a row to Verified runs.

#### Verifying Milestone 2

One run exercises all three code items. The existing `design_v1.json` (a copy of the
pre-Milestone-2 example: three houses and a terrace) shows whether anything regressed; a copy of
the current example as `design_v2.json` exercises the split-level house, the drive and the paths.

```
git pull
copy examples\design.example.json parcels\<parcel>\design_v2.json
python templates\doctor.py parcels\<parcel>
templates\run_all.bat parcels\<parcel>
```

Then, in order:

1. `git diff --no-index parcels\<parcel>\exports\design_v1_stats.prev.json parcels\<parcel>\exports\design_v1_stats.json`:
   the only new field should be `vegetation` (tree count, density, seed, whether the aerial filter
   was used). Every other number should be identical; anything else that moved is a regression.
2. `design_v2_stats.json`: `main_house` has a `pads` list of two at different floors; each drive
   has `length_m`, `mean_grade_pct`, `max_grade_pct`, `segments` and `reaches`; each house has
   `access` or is listed in `unreached_houses`. A `<id> grade within 15% FAIL` is a finding about
   the example's path on this lot, not a code failure: move the point or raise `max_grade_pct` in
   `design_v2.json` and rerun `place_masses.bat` for that design.
3. The log has no `render pass FAIL`. If it does, the traceback above it names the Blender call to
   fix; the stats and `.blend` were still written.
4. The renders (`renders\design_v2_*.png`), the guesses in order of likelihood: the sky is neither
   washed out nor dim (the last argument of the `physical_sky(...)` call in `place_masses.py`,
   0.25); the shadows fall away from the bright side of the sky (if not, the
   `sun_rotation` line in `physical_sky` has the azimuth convention backwards: change it until the
   sky agrees with the sun lamp, which is right); trees stand on the ground outside the pads and
   drives in a plausible number (`vegetation.per_ha`); the split-level house steps down the hill
   with a roof per pad; the drive reads as a ribbon that meets the house pad.
5. Add a Verified-runs row and update the Milestone 2 State cells.

## Milestone 3 -- access that works on a steep lot

Goal: on a lot that falls away from the road, the pipeline proposes a drive or path to each house
that stays within `max_grade_pct`, or says plainly that none fits. Milestone 2's verification
found that the hand-drawn example paths all ran straight downhill and were two to four times too
steep, and that the default frame bearing put a house across the parcel line.

| Criterion | Done when | Where it can be built |
| --- | --- | --- |
| Frame from the parcel | `"u_bearing_deg": "auto"` (and the default when the key is missing) derives the bearing from the parcel edge nearest the road centerlines, with the origin at that edge's end with the smaller u. `doctor.py` prints the derived bearing, and warns when any element's footprint falls outside the parcel in that frame. | Anywhere: pure geometry in `design_geom.py` with tests on synthetic parcels and roads. |
| Grade-aware access | Each house's `access` records whether the drive or path that reaches it stays within `max_grade_pct` along the whole route from the road. The stats add `steep_access_houses` next to `unreached_houses`, and the `[INFO] access` line names both. | Anywhere: logic and tests; the Blender run only supplies the elevations. |
| Switchback routing | A `drive` with `"to": "<house id>"` and no `points` is routed automatically: a least-cost path over the DEM grid (for example A* with grade-limited steps, preferring fewer turns) from the road frontage to that house's pad. It stays inside the parcel, off other pads, and within `max_grade_pct`. The chosen polyline goes into the stats in `u`/`v` so it can be copied into the JSON and edited. If no route fits, `<id> route FAIL` says why (for example, the steepest unavoidable step). | Anywhere: the router takes a 2-D elevation array, so the tests can use synthetic planes and ridges. Verify on a Blender machine with a real lot. |
| Example uses it | `examples/design.example.json` routes its drive and paths with `"to"` instead of fixed points, so it works on any lot the frame fits. | Anywhere. |
| Render helpers under test | The tree filter (pixel rule) and the compass-to-`sun_rotation` mapping move into `design_geom.py`, with tests that pin the arid-scrub case and the 90 - azimuth convention, so a refactor cannot quietly undo the Milestone 2 fixes. | Anywhere. |
| Verified on a Blender machine | A row in Verified runs: `design_v1` regression, the example routed on a real steep lot, renders inspected. | Blender machine. |

Not in scope: retaining walls, turning radii, drainage, and cut-and-fill volumes for the drive.
Courtyard-camera framing and tree species are render polish for a later pass.

## Phase 1 -- Identify a real parcel

Capture the listing URL, parcel ID (APN), jurisdiction, acreage, boundary, topography, access,
and notable features. Never invent parcel geometry. Listing boundaries and assessor lines are not
surveys. Keep all of this in your local `parcels/` folder, not in this repo.

## Phase 2 -- Prepare geographic data

One consistent set of site data in one projected CRS with meter units:

- Parcel boundary (GeoJSON).
- DEM as a float32 GeoTIFF, buffered well beyond the parcel line for context (about 150 m for
  the detail DEM, several km at low resolution for horizons).
- Aerial imagery over the same bbox as the DEM, where licensing permits.
- Roads, streams, and constraints as vectors.
- A notes file recording CRS, vertical datum, units, and sources with fetch dates. Start from
  [`examples/notes.example.md`](../examples/notes.example.md).

Pick a round local modeling origin near the parcel. Blender coordinates are CRS minus that
origin, so numbers stay small enough for float32. Never rescale the property. `fetch_gis.py`
derives the origin, the CRS, and both bboxes from the parcel on its first run and writes them into
`parcel.json`; `doctor.py` validates them.

## Phase 3 -- Build the 3D site

`build_site.py` makes `site_master.blend` from the Phase 2 files: terrain, aerial texture,
boundary, neighbor lines, roads, optional context terrain, a scale figure, and cameras. It checks
the rasters' georeference against `raster_bbox`, all four terrain edges, and the area and position
of the boundary curve against the source polygon (details in
[data-prep.md](data-prep.md#checking-the-result)).

Validate a few key distances in Blender against the GIS (for example, frontage length or the
distance from a corner to the road).

## Phase 4 -- Experiment with building massing

Simple editable masses before any detailed houses. Things to vary: building widths, depths, and
heights; rotations and spacing; courtyard size; paths and driveways; shared versus private
outdoor space; separation, privacy, and orientation.

`place_masses.py` reads a design JSON, places each mass on a pad graded into the terrain, renders,
and writes per-element stats (floor elevation, uphill cut, exposed downhill foundation, true
clearance to the boundary, which `floor_mode` was used) plus overall building coverage. It also checks that each built mass has
the requested footprint and lies fully inside the parcel, including on irregular (concave) lots. Each design is its own `.blend`; the site file is never modified.

Possible next steps here (use existing Blender features before writing code):
- Driveway and path curves with length and grade readouts.
- Geometry Nodes for parametric massing, if hand-editing the JSON gets tedious.
- Step or split-level masses for steep lots.

## Phase 5 -- Design individual residences

Once a site arrangement looks promising, design individual houses in Sweet Home 3D and bring them
into Blender.

Placement convention (proposed): in Sweet Home 3D, model each house with its footprint's
reference corner at the plan origin and the front of the house facing the plan's -Y. In Blender,
the matching mass from Phase 4 supplies position, rotation, and floor elevation, and the imported
house is parented to it. Moving the mass then moves the house.

Keep the `.sh3d` files as the editable source and re-export after changes.

## Phase 6 -- Attractive renderings

Better architectural materials, vegetation and landscaping, realistic lighting and shadows,
outdoor furniture, paths, surrounding context, and human-scale references. Aim for aerial,
courtyard, exterior, and interior views. Prefer free, openly licensed assets (see
[tool-stack.md](tool-stack.md#candidate-blender-add-ons-and-asset-libraries-not-yet-evaluated)).

## Phase 7 -- Game-style exploration (optional)

If Blender's navigation is not enough, export an optimized glTF/GLB scene to Godot and add
first-person movement and collision. This is an enhancement, not a prerequisite.

## Parcel analysis -- useful, not automatic

Computational help is welcome, but the goal is not to generate dozens of layouts. Useful
questions:

- Usable area after setbacks and exclusion zones.
- Where the relatively level areas are.
- Distance from candidate home sites to roads, utilities, and water.
- Viewsheds from candidate sites.
- Privacy and line of sight between residences.
- Road and path lengths.
- Building footprint coverage.
- Rough cut-and-fill comparisons between site alternatives.

Use a desktop GIS's existing geoprocessing and suitability tools first. Small scripts are fine
for repetitive or missing steps.

Keep two separations explicit in any output:
- **Exploratory scores versus engineering findings.** A slope score is a sketch, not a geotech
  report.
- **Legal or environmental limits versus preferences.** Flood zones, stream setbacks, and
  easements are constraints. Views and sun are preferences.
