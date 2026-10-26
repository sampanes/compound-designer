# Research notes

Findings from building the pipeline. Dated so you know how stale they might be.

## BlenderGIS on Blender 5.1

Checked 2026-10 against BlenderGIS commit `2add45f` on Blender 5.1.1, headless, with no GDAL,
PyProj, or Pillow installed.

- **Repository health:** last commit 2025-12-20. Open issues at the time included a Blender 5.0
  crash after installing GDAL, a general "5.0" compatibility issue, and a Map Viewer crash on
  4.2. Maintained, but slowly. Re-test after major Blender upgrades.
- **Do not install GDAL into Blender's Python** on 5.x. It isn't needed.
- **Both DEM import modes work:** `importgis.georaster` with `importMode="DEM_RAW"` (a real mesh,
  one vertex per pixel at `step=1`) and `importMode="DEM"` (a displaced plane). The scripts use
  `DEM_RAW`.
- **Accuracy:** against the GeoTIFF's own tags, the horizontal extent was exact (vertices sit at
  pixel centers, half a pixel in from the raster edge), and max elevation was within 3 mm.
  Blender units are real meters.
- **Local origin:** BlenderGIS stores a scene georef origin and keeps mesh coordinates small,
  which avoids float32 trouble with UTM-sized numbers. `build_site.py` sets that origin explicitly
  from `local_origin_xy`.
- **Set the scene CRS before importing** (GIS panel, or `GeoScene(scene).crs = "EPSG:xxxx"` in a
  script). With reprojection off, the raster is assumed to already be in the scene CRS.
- **First raster read downloads a DLL:** without GDAL or Pillow, imageio fetches a FreeImage DLL
  from `github.com/domlysz/freeimage_bin` into `%LOCALAPPDATA%\imageio\`. That download is what
  makes the no-GDAL path work.
- **Harmless noise:** Python `SyntaxWarning`s (old regex strings in the add-on) and libtiff
  "Unknown field with tag 33550 / 33922 / 347xx" (GeoTIFF tags that libtiff doesn't know).

## Public data sources

All of these are US-wide, free, and answer plain REST queries (no API key). `fetch_gis.py` uses
the first four.

| Data | Service | Notes |
| --- | --- | --- |
| Elevation | USGS 3DEP `3DEPElevation/ImageServer/exportImage` | 1 m lidar where flown; ask for `pixelType=F32`, `format=tiff`, bilinear resampling. NAVD88 meters. |
| Aerial imagery | USGS `USGSNAIPPlus/ImageServer/exportImage` | NAIP, public domain. Request the same bbox and CRS as the DEM. |
| Roads | Census TIGERweb `Transportation/MapServer/8` | Local road centerlines. Approximate. |
| Parcels | County or state ArcGIS REST parcel layers | Varies by county. Assessor lines, not surveys. |
| Flood zones | FEMA National Flood Hazard Layer (NFHL) | Not yet wired in. |
| Streams | USGS NHD / NHDPlus | Not yet wired in. |

The `exportImage` endpoint is the easy way to get a small clipped DEM without downloading
whole 1 m tiles: give it a bbox, an output CRS, and a pixel size. Example shape:

```
https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage
  ?bbox=XMIN,YMIN,XMAX,YMAX&bboxSR=<EPSG>&imageSR=<EPSG>&size=W,H
  &format=tiff&pixelType=F32&noData=-9999&interpolation=RSP_BilinearInterpolation&f=image
```

To see which lidar project (and year) covers a point, call `identify` on the same ImageServer
with `returnCatalogItems=true`.

## Finding the parcel

- A vacant lot often has **no situs address** in assessor data, and a geocoder won't find it. A
  listing's "address" number is sometimes the tail of the APN. Search the parcel layer for the
  listing's acreage near the street name.
- Some county GIS servers sit behind a bot challenge that blocks scripted REST queries. State
  agencies and statewide aggregators often republish county parcels on their own ArcGIS
  servers, and those usually answer plain queries.
- Request only the ID field from parcel layers. Owner names and mailing addresses are personal
  data and aren't needed for design.

## Steep-lot lessons

Rules of thumb from massing houses on a hillside lot (numbers below are illustrative):

- **Fall across a footprint = grade x footprint depth.** A 12 m deep house on a 30% slope has
  about 3.6 m of fall. With a "balanced" pad, roughly half becomes uphill cut and half becomes
  exposed foundation downhill. Turning the long side along the contour helps a lot.
- **Access is usually the real constraint, not the houses.** Driveway length is roughly the
  vertical drop divided by the maximum driveway grade: 15 m of drop at 15% is about 100 m of
  driveway, which on a narrow lot means switchbacks, or parking at road level with stairs or an
  inclined path down.
- **A lot that falls away from the road** hides everything below the road from the street.
  Good for privacy and views, hard for access and septic.
- **Camera gotcha:** on a steep downhill lot, an eye-level camera at the road aimed at the lot
  looks along the slope and shows only smeared ground. Put the eye-level camera below the
  buildings and look *up* the slope. `build_site.py` does this.
- **Context terrain matters for views.** A coarse DEM several km wide (10 m pixels is plenty)
  makes the far ridges visible from the courtyard camera. It is lowered slightly and cut out
  under the detail DEM so the two never z-fight.
- None of this checks local hillside, grading, septic, or setback rules. Those are
  jurisdiction-specific.

## Smaller notes

- Keep `site_master.blend` as a regenerated artifact. Do design work in separate `.blend` files
  that read from it, so a rebuild never destroys a design.
- Each mass is one object (walls + roof + a deep foundation that the terrain hides), with its
  origin at floor level. You can move it by hand, but the terrain grading follows the JSON, so
  copy positions back into the JSON and re-run to re-grade.
- `fetch_gis.py` re-downloads were byte-identical to the originals, so the GIS inputs are
  reproducible from `parcel.json` alone and don't need to be kept in version control.
