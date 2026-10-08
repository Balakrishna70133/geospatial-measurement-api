import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

from app.services.geospatial import process_geodataframe


def test_wgs84_polygon_is_reprojected_before_area_calculation():
    polygon = Polygon([(78.0, 17.0), (78.01, 17.0), (78.01, 17.01), (78.0, 17.01)])
    gdf = gpd.GeoDataFrame({"name": ["test"]}, geometry=[polygon], crs="EPSG:4326")

    result = process_geodataframe(gdf)
    feature = result["features"][0]

    assert result["crs"] == "EPSG:4326"
    assert feature["measurement_status"] == "CALCULATED"
    assert feature["measurement_unit"] == "square_meters"
    assert feature["measurement_crs"].startswith("EPSG:")
    assert 900_000 < feature["measurement"] < 1_500_000


def test_line_length_is_returned_in_meters():
    line = LineString([(78.0, 17.0), (78.01, 17.0)])
    gdf = gpd.GeoDataFrame({}, geometry=[line], crs="EPSG:4326")

    feature = process_geodataframe(gdf)["features"][0]
    assert feature["measurement_status"] == "CALCULATED"
    assert feature["measurement_unit"] == "meters"
    assert feature["measurement"] > 900


def test_point_does_not_require_measurement():
    gdf = gpd.GeoDataFrame({"label": ["A"]}, geometry=[Point(78, 17)], crs="EPSG:4326")

    feature = process_geodataframe(gdf)["features"][0]
    assert feature["measurement_status"] == "NOT_REQUIRED"
    assert feature["measurement"] is None


def test_missing_crs_is_handled_without_crashing():
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    gdf = gpd.GeoDataFrame({}, geometry=[polygon])

    feature = process_geodataframe(gdf)["features"][0]
    assert feature["measurement_status"] == "UNAVAILABLE_CRS"
    assert feature["measurement"] is None


def test_unsupported_geometry_is_reported_without_crashing():
    from shapely.geometry import GeometryCollection

    geometry = GeometryCollection([Point(78, 17)])
    gdf = gpd.GeoDataFrame({}, geometry=[geometry], crs="EPSG:4326")

    feature = process_geodataframe(gdf)["features"][0]
    assert feature["measurement_status"] == "UNSUPPORTED_GEOMETRY"
    assert feature["measurement"] is None


def test_kml_reader_extracts_common_placemarks(tmp_path):
    from app.services.geospatial import read_kml

    kml = tmp_path / "sample.kml"
    kml.write_text("""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<kml xmlns=\"http://www.opengis.net/kml/2.2\">
  <Document>
    <Placemark><name>Site</name><Point><coordinates>78.0,17.0,0</coordinates></Point></Placemark>
    <Placemark><name>Road</name><LineString><coordinates>78.0,17.0,0 78.01,17.0,0</coordinates></LineString></Placemark>
  </Document>
</kml>
""", encoding="utf-8")

    gdf = read_kml(kml)
    assert len(gdf) == 2
    assert gdf.crs.to_epsg() == 4326
    assert list(gdf.geometry.geom_type) == ["Point", "LineString"]
