from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile, status

from app.config import MAX_UPLOAD_SIZE_BYTES, STORAGE_DIR
from app.schemas import FileSummary, MeasurementsResponse
from app.services.geospatial import ALLOWED_EXTENSIONS, process_geodataframe, read_geospatial_file
from app.services.storage import load_result, save_result

app = FastAPI(
    title="Geospatial Measurement API",
    description="Upload KML or zipped Shapefiles and calculate CRS-safe feature measurements.",
    version="1.0.0",
)


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def load_or_404(file_id: str) -> dict:
    result = load_result(STORAGE_DIR, file_id)
    if result is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return result


@app.get("/", tags=["Health"])
def root() -> dict[str, str]:
    return {"service": "Geospatial Measurement API", "status": "ok"}


@app.get("/health", tags=["Health"])
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/api/files/", response_model=FileSummary, status_code=status.HTTP_201_CREATED, tags=["Files"])
async def upload_file(file: UploadFile = File(...)) -> FileSummary:
    filename = safe_filename(file.filename or "")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .kml or .zip files are supported.")

    file_id = uuid4().hex
    source_path = STORAGE_DIR / f"{file_id}_{filename}"

    try:
        size = 0
        with source_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit.")
                output.write(chunk)

        gdf = read_geospatial_file(source_path)
        processed = process_geodataframe(gdf)
        result = {
            "id": file_id,
            "filename": filename,
            "feature_count": processed["feature_count"],
            "crs": processed["crs"],
            "status": "COMPLETED",
            "features": processed["features"],
        }
        save_result(STORAGE_DIR, file_id, result)
        return FileSummary(**{k: result[k] for k in ("id", "filename", "feature_count", "crs", "status")})
    except HTTPException:
        raise
    except Exception as exc:
        save_result(
            STORAGE_DIR,
            file_id,
            {
                "id": file_id,
                "filename": filename,
                "feature_count": 0,
                "crs": None,
                "status": "FAILED",
                "features": [],
                "error": str(exc),
            },
        )
        raise HTTPException(status_code=422, detail=f"Could not process the geospatial file: {exc}") from exc
    finally:
        source_path.unlink(missing_ok=True)
        await file.close()


@app.get("/api/files/{file_id}/", response_model=FileSummary, tags=["Files"])
def get_file(file_id: str) -> FileSummary:
    result = load_or_404(file_id)
    return FileSummary(**{k: result[k] for k in ("id", "filename", "feature_count", "crs", "status")})


@app.get("/api/files/{file_id}/measurements/", response_model=MeasurementsResponse, tags=["Measurements"])
def get_measurements(file_id: str) -> MeasurementsResponse:
    result = load_or_404(file_id)
    return MeasurementsResponse(
        file_id=result["id"],
        filename=result["filename"],
        feature_count=result["feature_count"],
        measurements=result["features"],
    )
