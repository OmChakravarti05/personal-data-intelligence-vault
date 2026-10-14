FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf-cache

RUN useradd --create-home --uid 1000 vault

WORKDIR /app

# CPU-only PyTorch: the default Linux wheel pulls ~2 GB of GPU libraries we never use.
# The next step's requirements.txt pin (torch==2.14.1) is satisfied by this build.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image so first start needs no download.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

# Encrypted uploads live here; compose mounts a named volume on it.
RUN mkdir -p /data/storage && chown -R vault:vault /data /opt/hf-cache /app
ENV STORAGE_DIR=/data/storage

USER vault
EXPOSE 8000

# Apply migrations, then start the API.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]