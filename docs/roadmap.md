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

**Next:** the materials and vegetation pass for one attractive overview render (the only open row
above), then Phase 4's driveway and path curves with length and grade readouts.

### Verified runs

| What | When | Versions |
| --- | --- | --- |
| `build_site.py` and `place_masses.py` on one real parcel, headless, no GDAL | 2026-10 | Blender 5.1.1, BlenderGIS commit `2add45f` (see [research-notes.md](research-notes.md#blendergis-on-blender-51)) |
| Fresh folder from the README Quick start, end to end | not yet recorded | add the date, Blender and BlenderGIS versions after the first clean run |

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
