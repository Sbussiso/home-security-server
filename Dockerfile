# Use Python 3.9 since it has better ARM compatibility
FROM python:3.9-slim-bullseye

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
# Add system packages directory to PYTHONPATH
ENV PYTHONPATH=/app:/usr/lib/python3/dist-packages

# Set the working directory in the container
WORKDIR /app

# Install system dependencies needed for Python packages and the application
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        # Runtime dependencies for OpenCV & Numpy from apt
        libgl1-mesa-glx \
        libglib2.0-0 \
        libatlas-base-dev \
        # For tkinter GUI (needed by setup_wizard.py)
        python3-tk \
        tk-dev \
        # Install Numpy and OpenCV from apt
        python3-numpy \
        python3-opencv \
        # Build tools (some packages might still need them)
        build-essential \
        # For AWS libraries
        git \
        # Database dependencies
        libsqlite3-dev \
    # Clean up to reduce image size
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt for processing
COPY requirements.txt .

# Create a filtered requirements file without numpy and opencv-python
# These are now installed via apt
RUN grep -v -E "^numpy==|^opencv-python==" requirements.txt > requirements_filtered.txt

# Install remaining Python dependencies via pip
RUN pip install --no-cache-dir -r requirements_filtered.txt

# Copy the rest of the application code into the container
COPY . .

# Create necessary directories
RUN mkdir -p temp logs

# Create a non-root user and group, add user to video group
RUN groupadd -r appgroup && useradd --no-log-init -r -g appgroup appuser \
    && usermod -a -G video appuser \
    && chown -R appuser:appgroup /app

# Switch to the non-root user
USER appuser

# Expose the port the app runs on
EXPOSE 5000

# Define the command to run the application
CMD ["python", "server.py"]