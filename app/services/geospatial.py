from __future__ import annotations

import json
import math
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import LineString, Point, Polygon, mapping


ALLOWED_EXTENSIONS = {".kml", ".zip"}
SHAPEFILE_COMPONENTS = {".shp", ".shx", ".dbf"}


def safe_extract_zip(zip_path: Path, destination: Path) -> list[Path]:
    """Extract a ZIP while preventing path traversal and excessive nesting."""
    members = zipfile.ZipFile(zip_path).infolist()
    if not members:
        raise ValueError("The ZIP archive is empty.")

    total_uncompressed = sum(member.file_size for member in members)
    if total_uncompressed > 100 * 1024 * 1024:
        raise ValueError("The ZIP archive expands beyond the 100 MB safety limit.")

    extracted: list[Path] = []
    destination = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in members:
            target = (destination / member.filename).resolve()
            if not str(target).startswith(str(destination)):
                raise ValueError("The ZIP archive contains an unsafe path.")
            if member.is_dir():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                output.write(source.read())
            extracted.append(target)
    return extracted


def locate_shapefile(extracted_files: list[Path]) -> Path:
    shapefiles = [path for path in extracted_files if path.suffix.lower() == ".shp"]
    if len(shapefiles) != 1:
        raise ValueError("ZIP must contain exactly one Shapefile (.shp).")

    shp = shapefiles[0]
    stem = shp.stem.lower()
    siblings = {path.name.lower() for path in extracted_files if path.stem.lower() == stem}
    missing = [ext for ext in SHAPEFILE_COMPONENTS if f"{stem}{ext}" not in siblings]
    if missing:
        raise ValueError(f"Shapefile is missing required components: {', '.join(sorted(missing))}")
    return shp


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    return element.text.strip()


def _coordinates(text: str) -> list[tuple[float, float]]:
    coordinates: list[tuple[float, float]] = []
    for token in text.replace("\n", " ").split():
        values = token.split(",")
        if len(values) < 2:
            continue
        coordinates.append((float(values[0]), float(values[1])))
    if not coordinates:
        raise ValueError("KML geometry contains no valid coordinates.")
    return coordinates


def _parse_kml_geometry(placemark: ET.Element):
    for element in placemark.iter():
        if _local_name(element.tag) != "Point":
            continue
        coordinate_node = next((child for child in element.iter() if _local_name(child.tag) == "coordinates"), None)
        if coordinate_node is not None and _text(coordinate_node):
            return Point(_coordinates(_text(coordinate_node))[0])

    for element in placemark.iter():
        if _local_name(element.tag) != "LineString":
            continue
        coordinate_node = next((child for child in element.iter() if _local_name(child.tag) == "coordinates"), None)
        if coordinate_node is not None and _text(coordinate_node):
            return LineString(_coordinates(_text(coordinate_node)))

    polygons = []
    for element in placemark.iter():
        if _local_name(element.tag) != "Polygon":
            continue
        rings = []
        for child in element.iter():
            if _local_name(child.tag) != "coordinates":
                continue
            text = _text(child)
            if text:
                rings.append(_coordinates(text))
        if rings:
            polygons.append(Polygon(rings[0], rings[1:]))

    if polygons:
        return polygons[0] if len(polygons) == 1 else gpd.GeoSeries(polygons).union_all()
    return None


def read_kml(file_path: Path) -> gpd.GeoDataFrame:
    """Read common KML Placemark geometries without relying on a GDAL KML driver."""
    try:
        root = ET.parse(file_path).getroot()
    except ET.ParseError as exc:
        raise ValueError("The KML document is not valid XML.") from exc

    rows = []
    for placemark in (element for element in root.iter() if _local_name(element.tag) == "Placemark"):
        geometry = _parse_kml_geometry(placemark)
        if geometry is None:
            continue

        properties: dict[str, Any] = {}
        name_node = next((child for child in placemark if _local_name(child.tag) == "name"), None)
        if _text(name_node):
            properties["name"] = _text(name_node)

        for data in placemark.iter():
            if _local_name(data.tag) != "Data":
                continue
            key = data.attrib.get("name")
            value_node = next((child for child in data if _local_name(child.tag) == "value"), None)
            if key and _text(value_node) is not None:
                properties[key] = _text(value_node)

        rows.append({**properties, "geometry": geometry})

    if not rows:
        raise ValueError("The KML file contains no supported Point, LineString, or Polygon Placemarks.")

    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def read_geospatial_file(file_path: Path) -> gpd.GeoDataFrame:
    suffix = file_path.suffix.lower()
    if suffix == ".kml":
        return read_kml(file_path)
    if suffix == ".zip":
        with tempfile.TemporaryDirectory(prefix="geospatial_zip_") as temp_dir:
            extracted = safe_extract_zip(file_path, Path(temp_dir))
            shp = locate_shapefile(extracted)
            return gpd.read_file(shp).copy()
    raise ValueError("Unsupported file type. Upload a .kml file or a .zip containing a Shapefile.")


def crs_label(crs: Any) -> str | None:
    if crs is None:
        return None
    try:
        return CRS.from_user_input(crs).to_string()
    except Exception:
        return str(crs)


def select_measurement_crs(gdf: gpd.GeoDataFrame) -> CRS | None:
    """Return a projected CRS suitable for metric calculations."""
    if gdf.crs is None:
        return None

    source_crs = CRS.from_user_input(gdf.crs)
    if not source_crs.is_geographic:
        return source_crs

    # GeoPandas estimates a local UTM CRS from the dataset's geographic extent.
    estimated = gdf.estimate_utm_crs()
    return CRS.from_user_input(estimated) if estimated else None


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return str(value)


def process_geodataframe(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    # Normalize the index so every feature has a stable zero-based API ID.
    gdf = gdf.reset_index(drop=True)
    source_crs = crs_label(gdf.crs)
    measurement_crs = select_measurement_crs(gdf)

    transformed = gdf
    if measurement_crs is not None and gdf.crs is not None:
        source = CRS.from_user_input(gdf.crs)
        if source != measurement_crs:
            transformed = gdf.to_crs(measurement_crs)

    features: list[dict[str, Any]] = []
    for index, row in gdf.iterrows():
        geometry = row.geometry
        geometry_type = geometry.geom_type if geometry is not None else "Unknown"
        measurement_geometry = transformed.loc[index].geometry

        measurement = None
        unit = None
        status = "NOT_REQUIRED"

        if geometry is None or geometry.is_empty:
            status = "UNAVAILABLE_EMPTY_GEOMETRY"
        elif geometry_type == "Polygon" or geometry_type == "MultiPolygon":
            if measurement_crs is None:
                status = "UNAVAILABLE_CRS"
            else:
                measurement = float(measurement_geometry.area)
                unit = "square_meters"
                status = "CALCULATED"
        elif geometry_type == "LineString" or geometry_type == "MultiLineString":
            if measurement_crs is None:
                status = "UNAVAILABLE_CRS"
            else:
                measurement = float(measurement_geometry.length)
                unit = "meters"
                status = "CALCULATED"
        elif geometry_type in {"Point", "MultiPoint"}:
            status = "NOT_REQUIRED"
        else:
            status = "UNSUPPORTED_GEOMETRY"

        features.append(
            {
                "feature_id": int(index),
                "geometry_type": geometry_type,
                "geometry": json_safe(mapping(geometry)) if geometry is not None else None,
                "crs": source_crs,
                "properties": json_safe(row.drop(labels=["geometry"]).to_dict()),
                "measurement": measurement,
                "measurement_unit": unit,
                "measurement_status": status,
                "measurement_crs": crs_label(measurement_crs),
            }
        )

    return {
        "feature_count": len(features),
        "crs": source_crs,
        "features": features,
    }
