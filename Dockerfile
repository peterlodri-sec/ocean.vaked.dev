FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn[standard] \
    pydantic \
    aiohttp \
    requests

COPY . /app

EXPOSE 8000 8080

CMD ["python", "server/model_ocean.py"]
