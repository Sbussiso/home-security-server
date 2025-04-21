# Use the full Python image instead of slim variant
FROM python:3.11

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies for OpenCV and other required libraries
# Also install build dependencies for scientific Python packages on ARM
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1-mesa-glx \
        libglib2.0-0 \
        # Build dependencies
        build-essential \
        libopenblas-dev \
        liblapack-dev \
        gfortran \
        cmake \
        pkg-config \
    # Clean up to reduce image size
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt first to leverage Docker cache
COPY requirements.txt .

# Install numpy separately first (using a version known to work on ARM)
RUN pip install --no-cache-dir numpy==1.26.3

# Install remaining Python dependencies, ignoring numpy in requirements.txt
RUN grep -v "^numpy==" requirements.txt > requirements_without_numpy.txt \
    && pip install --no-cache-dir -r requirements_without_numpy.txt

# Copy the rest of the application code into the container
COPY . .

# Create a non-root user and group
RUN groupadd -r appgroup && useradd --no-log-init -r -g appgroup appuser

# Change ownership of the app directory
# Ensure the app user can write to temp and logs if needed
RUN mkdir -p temp logs \
    && chown -R appuser:appgroup /app

# Switch to the non-root user
USER appuser

# Expose the port the app runs on
EXPOSE 5000

# Define the command to run the application
CMD ["python", "server.py"]