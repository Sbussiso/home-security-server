# 1. Base image (multi-arch manifest)
FROM python:3.10-bullseye

# 2. Environment settings
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app:/usr/lib/python3/dist-packages

WORKDIR /app

# 3. System dependencies (numeric libs via APT)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential gfortran \
      libopenblas-dev liblapack-dev libatlas-base-dev \
      libssl-dev cmake git curl sqlite3 libsqlite3-dev \
      libglib2.0-0 libgl1-mesa-glx \
      python3-tk tk-dev \
      libopencv-dev python3-opencv \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# 4. Python deps (w/ piwheels)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt \
    --extra-index-url https://www.piwheels.org/simple \
 && pip install --no-cache-dir awsiotsdk

# 5. App source
COPY . .

# 6. Prepare runtime dirs & user
RUN mkdir -p temp logs \
 && groupadd -r appgroup \
 && useradd --no-log-init -r -g appgroup appuser \
 && usermod -a -G video appuser \
 && chown -R appuser:appgroup /app

USER appuser
EXPOSE 5000

# 7. Launch command
CMD ["python", "server.py"]
