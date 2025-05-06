# Use an official ARMv7 Python runtime as a parent image (for 32-bit Raspbian OS)
FROM arm32v7/python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt /app/
RUN apt-get update && \
    apt-get install -y gcc g++ make libffi-dev libssl-dev && \
    pip install --upgrade pip && \
    pip install -r requirements.txt && \
    apt-get remove -y gcc g++ make libffi-dev libssl-dev && \
    apt-get autoremove -y && \
    apt-get clean

# Copy project files
COPY . /app/

# Expose port (change if your app uses a different port)
EXPOSE 8000

# Run the application (change app.py to your main script)
CMD ["python", "app.py"]
