# Preparing data in a desktop GIS

`fetch_gis.py` covers most US parcels using public services. Use ArcGIS Pro or QGIS instead (or in
addition) when you need analysis layers, a parcel that has no REST service, or a constraint layer
(flood zones, easements, setbacks) the script doesn't fetch.

The goal is to produce **the same files `fetch_gis.py` would**, so `build_site.py` and
`place_masses.py` don't change.

> Status: the target formats below are what the Blender scripts read and are verified. The
> desktop-GIS steps are a recipe, not yet tested end to end in this repo.

## Target files

| File | Format | Notes |
| --- | --- | --- |
| `gis/terrain_dem.tif` | GeoTIFF, **float32**, single band, NoData -9999 | Projected CRS in **meters**; parcel bbox plus about 150 m |
| `gis/aerial_naip.tif` | GeoTIFF, RGB | **Exactly the same bbox** as the DEM (UVs are a linear map from XY) |
| `gis/parcel_boundary.geojson` | GeoJSON polygon | Same CRS as the DEM; ID field only |
| `gis/context_parcels.geojson` | GeoJSON polygons | Neighbors within about 200 m |
| `gis/roads.geojson` | GeoJSON lines | Same CRS |
| `gis/context_dem_10m.tif` (optional) | GeoTIFF, float32 | Several km wide, coarse, for horizons and views |

Then fill in `parcel.json` (`epsg`, `local_origin_xy`, `raster_bbox`, and file paths) to match.
`fetch_gis.py` only derives those values when it fetches, so on this path set them by hand, and
run `doctor.py` on the folder: it checks the bboxes against the pixel sizes and the parcel file's
CRS before Blender starts.

## Rules that keep everything aligned

- **One projected CRS with meter units** for every layer -- usually the local UTM zone
  (`EPSG:269xx` for NAD83 / UTM). Don't use a state plane zone in US feet unless you also
  convert, because the Blender side assumes meters.
- **Record the vertical datum and units.** 3DEP DEMs are NAVD88 meters. If your DEM is in feet,
  convert it to meters before export.
- **Don't clip the DEM to the parcel line.** Buffer it; the surroundings are what make the site
  readable.
- **Export the DEM and aerial over an identical extent.** Snap both to the same bbox (and
  ideally to a whole-meter grid).
- **Uncompressed or simple-compressed GeoTIFF.** BlenderGIS reads GeoTIFFs without GDAL, but
  keep the format plain: single-band float32 for elevation, no pyramids or exotic compression.
- **Strip attributes.** Export only the parcel ID field. Owner names and mailing addresses
  have no business being in a design folder.

## ArcGIS Pro outline

1. Set the map's coordinate system to the projected CRS you chose.
2. Parcel: select it, then **Project** if needed, and export with **Features To JSON** using
   the GeoJSON option. Do the same for neighbors and roads.
3. DEM: **Clip Raster** to the buffered bbox (use *Maintain Clipping Extent* and the bbox as the
   output extent), then **Copy Raster** to TIFF with pixel type 32-bit float and NoData -9999.
4. Aerial: Clip Raster with the *same* extent as the DEM and export to TIFF.
5. Analysis (needs Spatial Analyst or 3D Analyst): **Slope**, **Aspect**, **Viewshed** or
   **Visibility**, **Buffer** for setbacks, and suitability modeling. Export any result you want
   in Blender as a GeoTIFF or GeoJSON in the same CRS.

Tool names and options vary between ArcGIS Pro releases; check the documentation for the version
you have.

## QGIS outline

1. Set the project CRS.
2. Vectors: right-click the layer, **Export > Save Features As**, format GeoJSON, CRS = project
   CRS, and keep only the ID field.
3. DEM: **Raster > Extraction > Clip Raster by Extent**, output data type Float32, NoData -9999.
4. Aerial: the same tool with the same extent.
5. For a quick 3D look before building in Blender, Qgis2threejs can export the DEM and layers to
   a web viewer or glTF.

## Checking the result

`build_site.py` prints `[CHECK]` lines and exits 1 if anything is off. It checks that:
- the DEM's and the aerial's own georeference (GeoTIFF tags) match `raster_bbox` and the
  configured pixel sizes;
- the terrain mesh has one vertex per DEM pixel and its four edges sit where `raster_bbox` says;
- the parcel boundary curve built in Blender has the source polygon's area and sits at the
  source polygon's position.

It does not check that the parcel, roads, and rasters really share a CRS beyond those extents,
so keep the CRS rule above. If a check fails, the usual causes
are a CRS mismatch between layers, a DEM in feet, or a DEM and aerial exported over different
extents.
