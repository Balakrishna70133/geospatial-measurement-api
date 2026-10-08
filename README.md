# Geospatial Measurement API

A production-minded FastAPI service for uploading **KML** files or **ZIP archives containing a Shapefile**, extracting their features, and calculating geometry measurements without incorrectly measuring geographic coordinates in degrees.

## Why this implementation

The main engineering goal is correctness first: the API preserves the source CRS for reporting, but measurement calculations use a projected CRS. For geographic input such as `EPSG:4326`, the service estimates a local UTM CRS from the dataset extent before calculating polygon area or line length.

The service also treats unsupported geometries and missing CRS information as data conditions rather than application crashes.

## Features

- FastAPI REST API with automatic OpenAPI/Swagger documentation.
- Accepts `.kml` and `.zip` containing one Shapefile.
- Extracts feature ID/index, geometry type, geometry, CRS, and properties.
- Calculates:
  - Polygon / MultiPolygon area in square metres.
  - LineString / MultiLineString length in metres.
  - No measurement for Point / MultiPoint.
- Reprojects geographic coordinates before measurement.
- Handles missing CRS, empty geometry, and unsupported geometry types gracefully.
- Upload-size validation and ZIP path-traversal protection.
- Automated tests for CRS-aware measurement behavior.
- Docker support for reproducible local execution.

## Project structure

```text
geospatial-measurement-api/
├── app/
│   ├── main.py                 # HTTP routes and request handling
│   ├── config.py               # Runtime configuration
│   ├── schemas.py              # API response models
│   └── services/
│       ├── geospatial.py       # Reading, CRS handling, measurements
│       └── storage.py          # Lightweight JSON result persistence
├── tests/
│   ├── test_api.py
│   └── test_geospatial.py
├── data/                       # Place local sample data here if needed
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pytest.ini
├── requirements.txt
└── README.md
```

## Setup

### Option 1: Python virtual environment

Python 3.11+ is recommended.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the API:

```bash
uvicorn app.main:app --reload
```

Open Swagger UI:

```text
http://127.0.0.1:8000/docs
```

### Option 2: Docker

```bash
docker compose up --build
```

Then open `http://127.0.0.1:8000/docs`.

## API

### 1. Upload and process a file

`POST /api/files/`

Multipart form field:

```text
file=<survey.kml>
```

Example with curl:

```bash
curl -X POST "http://127.0.0.1:8000/api/files/" \
  -F "file=@./data/survey.kml"
```

For a Shapefile, upload a ZIP containing the `.shp`, `.shx`, and `.dbf` components. If a `.prj` file is available, include it so the source CRS can be identified correctly.

Example response:

```json
{
  "id": "6b5d0b1c2d5f4b8b9d8d8f8b8a8d7c6e",
  "filename": "survey.kml",
  "feature_count": 120,
  "crs": "EPSG:4326",
  "status": "COMPLETED"
}
```

### 2. Get file information

`GET /api/files/{id}/`

Example:

```bash
curl "http://127.0.0.1:8000/api/files/<id>/"
```

Response:

```json
{
  "id": "<id>",
  "filename": "survey.kml",
  "feature_count": 120,
  "crs": "EPSG:4326",
  "status": "COMPLETED"
}
```

### 3. Get measurements

`GET /api/files/{id}/measurements/`

Example:

```bash
curl "http://127.0.0.1:8000/api/files/<id>/measurements/"
```

A feature response contains the source CRS and, when a measurement is possible, the projected CRS used for the calculation:

```json
{
  "file_id": "<id>",
  "filename": "survey.kml",
  "feature_count": 2,
  "measurements": [
    {
      "feature_id": 0,
      "geometry_type": "Polygon",
      "geometry": {"type": "Polygon", "coordinates": []},
      "crs": "EPSG:4326",
      "properties": {"name": "Site A"},
      "measurement": 102345.67,
      "measurement_unit": "square_meters",
      "measurement_status": "CALCULATED",
      "measurement_crs": "EPSG:32644"
    },
    {
      "feature_id": 1,
      "geometry_type": "Point",
      "geometry": {"type": "Point", "coordinates": [78.1, 17.4]},
      "crs": "EPSG:4326",
      "properties": {"name": "Reference"},
      "measurement": null,
      "measurement_unit": null,
      "measurement_status": "NOT_REQUIRED",
      "measurement_crs": "EPSG:32644"
    }
  ]
}
```

## Measurement and CRS strategy

A geographic CRS such as `EPSG:4326` stores longitude/latitude in angular degrees. Directly using Shapely's planar `.area` or `.length` on those coordinates would therefore produce values in degree-based coordinate units rather than metres.

This service follows this flow:

```text
Input file
   │
   ├── KML ───────────────┐
   └── ZIP/Shapefile ─────┤
                          ▼
                 GeoPandas GeoDataFrame
                          │
                          ▼
                    Read source CRS
                          │
             ┌────────────┴────────────┐
             │                         │
      Projected CRS             Geographic CRS
             │                         │
             │                estimate local UTM
             │                         │
             └────────────┬────────────┘
                          ▼
                  Projected geometry
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
          Polygon     LineString      Point
             │            │            │
          Area m²      Length m       No measure
```

For geographic datasets, `GeoDataFrame.estimate_utm_crs()` is used to select a local UTM CRS. For already projected data, the source projected CRS is retained. If there is no CRS, the service does not invent one; measurements are returned with `UNAVAILABLE_CRS`.

## Architecture

### Application layer

`app/main.py` owns HTTP concerns: validation, status codes, upload handling, and response serialization.

### Geospatial service layer

`app/services/geospatial.py` contains file reading, safe ZIP extraction, CRS selection, reprojection, feature extraction, and measurement logic. Keeping these operations outside the route makes the core behavior easier to test and extend.

### Persistence

For this assignment, processed results are stored as JSON files under `runtime_storage/`. This deliberately avoids introducing a database that is not required by the problem statement. The storage interface can later be replaced with PostgreSQL/PostGIS or object storage without changing the API contract.

## Error handling

The API handles common invalid-input cases explicitly:

- Unsupported extension → `400 Bad Request`.
- Upload larger than configured limit → `413 Payload Too Large`.
- Invalid or unreadable geospatial data → `422 Unprocessable Entity`.
- Unknown file ID → `404 Not Found`.
- Missing CRS → feature measurement status `UNAVAILABLE_CRS`.
- Empty geometry → `UNAVAILABLE_EMPTY_GEOMETRY`.
- Unsupported geometry → `UNSUPPORTED_GEOMETRY`.

## Testing

Run:

```bash
pytest -q
```

The tests cover:

- Geographic polygon reprojection before area calculation.
- Geographic LineString length in metres.
- Point behavior.
- Missing CRS handling.
- Unsupported upload extension handling.

## Design decisions

### Why FastAPI?

FastAPI provides a lightweight API layer, typed request/response models, automatic OpenAPI documentation, and a clean separation between routing and business logic. Django REST Framework would also satisfy the requirements, but FastAPI keeps this assignment focused on geospatial processing rather than framework infrastructure.

### Why GeoPandas/Shapely/pyproj?

They provide a well-established Python geospatial stack: GeoPandas manages tabular geospatial data and CRS transformations, Shapely provides geometry operations, pyproj supplies CRS definitions and transformations, and the KML reader uses Python's standard XML parser so KML support does not depend on whether a machine-specific GDAL build exposes a KML driver.

### Why a custom KML reader?

KML coordinates are longitude/latitude and therefore are treated as `EPSG:4326`. The implementation parses common KML `Placemark` geometries (Point, LineString, Polygon) directly with Python XML parsing. This makes the KML endpoint more portable across environments where Fiona/GDAL may not have KML driver support enabled.

### Why local JSON storage?

The assignment asks for file processing and measurement APIs, not a persistence architecture. JSON result files keep the implementation simple and transparent. In a production deployment, I would replace this with durable object storage plus PostgreSQL/PostGIS metadata and job state.

### Why estimate UTM?

A single global projected CRS is not appropriate for every geographic dataset. Estimating a local UTM CRS is a practical strategy for datasets covering a relatively local area. For very large datasets spanning multiple UTM zones, a production implementation could use a configured equal-area/equidistant CRS strategy or calculate measurements per zone depending on the business requirement.

## Learning

This project reinforced several practical concepts:

- Designing a REST API around a clear processing workflow.
- Handling multipart file uploads safely.
- Reading KML and Shapefile data with GeoPandas.
- Understanding the difference between geographic and projected CRS.
- Reprojecting geometries before planar measurements.
- Separating API, domain logic, and persistence concerns.
- Writing tests around correctness-sensitive geospatial calculations.
- Treating invalid input and unsupported geometry as expected application states.

## Future scope

If this service were taken beyond the assignment, I would consider:

1. PostgreSQL/PostGIS for durable metadata and spatial querying.
2. Object storage such as S3-compatible storage for original uploads.
3. Background processing with Celery/RQ for very large files.
4. Authentication, authorization, rate limiting, and audit logging.
5. Streaming/size-aware processing for large datasets.
6. More geometry types and configurable measurement strategies.
7. Better handling for datasets crossing UTM zones.
8. Automated CI/CD with linting, tests, security checks, and container scanning.
9. Observability with structured logs and metrics.
10. API pagination for very large feature collections.

## Submission checklist

Before submitting the GitHub repository:

- [ ] Run `pytest -q` successfully.
- [ ] Start the API and verify `/docs`.
- [ ] Upload one real KML file.
- [ ] Upload one ZIP containing a Shapefile.
- [ ] Verify the returned CRS and measurement CRS.
- [ ] Verify polygon area and line length values are in metric units.
- [ ] Confirm invalid file types return a controlled error.
- [ ] Review the repository for credentials or local runtime files.
- [ ] Push the complete repository to a public GitHub repository.


## Contact

**Bala Krishna**  
GitHub: https://github.com/Balakrishna70133

After extracting/opening the project folder:
## GitHub commands

```bash
git init
git add .
git commit -m "Build geospatial measurement API"
git branch -M main
git clone https://github.com/Balakrishna70133/geospatial-measurement-api.git
cd geospatial-measurement-api
git push -u origin main
```

Replace the repository URL with your actual public GitHub repository URL before running the final command.
