FROM python:3.10-bullseye

# 1. Prevent .pyc files, enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONPATH=/app:/usr/lib/python3/dist-packages

WORKDIR /app

# 2. Install system deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libgl1-mesa-glx \
      libglib2.0-0 \
      libatlas-base-dev \
      python3-tk \
      tk-dev \
      python3-numpy \
      python3-opencv \
      build-essential \
      cmake \
      libssl-dev \
      git \
      curl \
      libsqlite3-dev \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# 3. Copy & install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir awsiotsdk

# 4. Copy your app code
COPY . .

# 5. Prepare directories
RUN mkdir -p temp logs

# 6. Create non‑root user for camera access
RUN groupadd -r appgroup \
 && useradd --no-log-init -r -g appgroup appuser \
 && usermod -a -G video appuser \
 && chown -R appuser:appgroup /app

# 7. **THIS IS CRITICAL** – switch and set the launch command
USER appuser
EXPOSE 5000

# 10) Launch your FastAPI server
CMD ["python", "server.py"]

# --- TEMPORARY RUNTIME DIAGNOSTIC ---
# CMD ["python", "-c", 'import sys; print("--- Runtime Check ---"); print(sys.path); print("--- Importing awsiot.mqtt ---"); import awsiot.mqtt; print("--- Import SUCCESS ---')']
