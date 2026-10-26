# Tool stack

Each tool has one job. Data flows one way: GIS data -> 3D site -> buildings -> renders.

| Role | Tool | Status in this repo |
| --- | --- | --- |
| Geographic data | Public REST services via `templates/fetch_gis.py`, or a desktop GIS (ArcGIS Pro / QGIS) | **In use** (REST); desktop GIS optional |
| 3D site assembly | [Blender](https://www.blender.org/) + [BlenderGIS](https://github.com/domlysz/BlenderGIS) | **In use** (`build_site.py`) |
| Building massing | Blender, driven by a design JSON | **In use** (`place_masses.py`) |
| House layouts and interiors | [Sweet Home 3D](https://www.sweethome3d.com/) | Planned |
| Parametric architecture | [FreeCAD BIM](https://www.freecad.org/) or Bonsai (Blender) | Optional, later |
| Quick terrain viewer | [QGIS](https://qgis.org/) + [Qgis2threejs](https://github.com/minorua/Qgis2threejs) | Optional |
| Browser floor-plan sketching | [OpenPlan3D](https://github.com/laanlabs/openPlan3D) | Optional |
| First-person exploration | [Godot](https://godotengine.org/) | Optional, later |

## Geographic data -- the source of truth

Inputs that matter: parcel polygon and acreage, a DEM, aerial imagery, roads and access
corridors, streams and drainage, flood zones, and, where available, easements, setbacks,
existing structures, utilities, and vegetation.

Two ways to get them:

- **Scripted (current):** `fetch_gis.py` pulls the parcel, neighbors, roads, a 1 m DEM, and an
  aerial image straight from public REST services, already in the target projected CRS. No GIS
  application is needed. See [research-notes.md](research-notes.md#public-data-sources).
- **Desktop GIS (when you need analysis):** ArcGIS Pro or QGIS for slope and aspect, viewsheds,
  suitability analysis, setback buffers, flood-zone overlays, or data that has no REST service.
  Export to the same file formats `fetch_gis.py` produces, so the Blender steps don't change. See
  [data-prep.md](data-prep.md).

Blender does not try to reproduce GIS. Geographic accuracy is the GIS side's job.

## Blender + BlenderGIS -- the 3D site

Blender is where everything comes together: terrain, parcel lines, roads, building masses,
courtyards, landscaping, lighting, cameras, and renders. BlenderGIS handles georeferencing and
imports DEM GeoTIFFs as real meshes. It has been verified on Blender 5.1 without GDAL; see
[research-notes.md](research-notes.md#blendergis-on-blender-51).

Fallback if BlenderGIS breaks on a future Blender release: a plane sized to the raster's exact
extent in meters, plus a Displace modifier driven by the DEM. Or keep a portable older Blender
just for the import step.

## Sweet Home 3D -- houses (planned)

For dimensioned floor plans, walls, doors, windows, furniture, and multiple floors with a casual,
Sims-like editor. It exports OBJ with MTL and textures, which Blender imports. A community
[GLB exporter](https://github.com/lukevink/sweethome3d-glb-exporter) exists; evaluate it only if
GLB materially simplifies the round trip.

Rules:
- The `.sh3d` file is the editable source. Never edit only the exported mesh.
- Each house is placed on its site footprint using a documented convention (see
  [roadmap.md](roadmap.md#phase-5----design-individual-residences)).

## Optional tools

- **FreeCAD BIM** -- for buildings that need real parametric constraints: consistent wall
  thickness, parameter-driven dimensions, roofs, reusable components, IFC. Not required.
- **Bonsai (formerly BlenderBIM)** -- IFC modeling inside Blender. It could fill the FreeCAD
  role without leaving Blender. Not yet evaluated.
- **QGIS + Qgis2threejs** -- turns a DEM and vectors into an interactive web 3D scene or glTF
  in minutes. Handy for a quick look at a candidate parcel before committing to a Blender build.
  Check plugin and QGIS version compatibility first.
- **OpenPlan3D** -- browser-based floor-plan sketching with JSON project data and 2D exports.
  Don't assume its JSON or DXF is a usable 3D Blender scene. Pick it *or* Sweet Home 3D; don't
  maintain the same house in both.
- **Godot** -- first-person walkthroughs from a glTF/GLB exported from Blender, with collision and
  movement. Only if Blender's own navigation and cameras turn out to be insufficient.

## Candidate Blender add-ons and asset libraries (not yet evaluated)

- **CAD Sketcher** -- constraint-based 2D sketches in Blender; a possible fit for parametric
  building footprints.
- **Bonsai** -- see above.
- **Poly Haven** -- free (CC0) HDRIs, textures, and models.
- **BlenderKit** -- large library with a free tier; check each asset's license.
- Blender's own Geometry Nodes for scattering trees and vegetation before reaching for paid
  scatter add-ons.
