FROM python:3.12-slim

WORKDIR /app

# GDAL/PROJ are used underneath GeoPandas/Fiona/PyProj.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gdal-bin libgdal-dev libproj-dev proj-data \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY pytest.ini .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
