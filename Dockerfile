# Use Python 3.9 since it has better ARM compatibility
FROM python:3.9-slim-bullseye

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies needed for various Python packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        # For OpenCV
        libgl1-mesa-glx \
        libglib2.0-0 \
        # For tkinter GUI (needed by setup_wizard.py)
        python3-tk \
        tk-dev \
        # Build tools
        build-essential \
        # For AWS libraries
        git \
        # Database dependencies
        libsqlite3-dev \
    # Clean up to reduce image size
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt for initial processing
COPY requirements.txt .

# Create a filtered requirements file without numpy and opencv-python
RUN grep -v -E "^numpy==|^opencv-python==" requirements.txt > requirements_filtered.txt

# Install numpy and opencv-python separately with compatible versions for ARM 
# Note: Older versions selected specifically for Raspberry Pi compatibility
RUN pip install --no-cache-dir \
    numpy==1.23.5 \
    opencv-python==4.5.5.64

# Install all other dependencies
RUN pip install --no-cache-dir -r requirements_filtered.txt

# Copy the rest of the application code into the container
COPY . .

# Create necessary directories
RUN mkdir -p temp logs

# Create a non-root user and group
RUN groupadd -r appgroup && useradd --no-log-init -r -g appgroup appuser \
    && chown -R appuser:appgroup /app

# Switch to the non-root user
USER appuser

# Expose the port the app runs on
EXPOSE 5000

# Define the command to run the application
CMD ["python", "server.py"]