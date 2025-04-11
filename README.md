# Home Security Camera System

This project is an open-source, local home security camera system that leverages computer vision and cloud technologies to monitor, analyze, and notify users of potential security threats. It combines a FastAPI web application, SQLite database, AWS Rekognition, and email notifications to provide a robust and scalable solution for home security.

## Introduction

The home security camera system is designed to continuously monitor a video feed from a connected camera. When motion is detected, it captures images, uploads them to an AWS S3 bucket, and analyzes them using AWS Rekognition for potential security threats such as people, vehicles, weapons, or packages. If any threats are detected, the system sends an email notification with the relevant details and a link to the uploaded image.

The system also provides a RESTful API for managing the camera, analyzing images, sending notifications, and interacting with the database. The database stores captured images, detected security alerts, and other metadata for future reference and analysis.

This project aims to provide an open-source, self-hosted solution for home security, allowing users to monitor their premises without relying on third-party services or cloud-based solutions. By leveraging AWS services and running locally, users can maintain control over their data while benefiting from advanced computer vision capabilities.

## Features

- Real-time motion detection and image capture
- Image analysis using AWS Rekognition for detecting security threats
- Email notifications for detected security alerts
- RESTful API for camera control, image analysis, and database management
- SQLite database for storing captured images, security alerts, and metadata
- AWS S3 integration for storing and retrieving captured images
- Background tasks for asynchronous processing
- Modular and extensible design
- Open-source and self-hosted for privacy and control

## Installation

1. Clone the repository:

```bash
git clone https://github.com/your-username/home-security-camera.git
cd home-security-camera
```

2. Create a virtual environment and install dependencies:

```bash
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
pip install -r requirements.txt
```

3. Set up environment variables:

Create a `.env` file in the project root directory with the following variables:

```
EMAIL_USER=your-email@example.com
EMAIL_PASSWORD=your-email-password
SMTP_SERVER=your-smtp-server
SMTP_PORT=your-smtp-port
AWS_ACCESS_KEY=your-aws-access-key
AWS_SECRET_KEY=your-aws-secret-key
AWS_REGION=your-aws-region
DB_PATH=path/to/your/database.db
```

Replace the placeholders with your actual values.

4. Initialize the database:

```bash
python database.py
```

This will create the SQLite database file specified in the `DB_PATH` environment variable.

## Usage

1. Start the FastAPI server:

```bash
uvicorn app:app --reload
```

The server will be accessible at `http://localhost:8000`.

2. Use the provided API endpoints to control the camera, analyze images, send notifications, and manage the database. You can use tools like Postman or cURL to interact with the API.

Here are some example API requests:

- Start camera monitoring:

```bash
curl -X POST http://localhost:8000/camera -H "Content-Type: application/json" -d '{"action": "start"}'
```

- Stop camera monitoring:

```bash
curl -X POST http://localhost:8000/camera -H "Content-Type: application/json" -d '{"action": "stop"}'
```

- Analyze an image:

```bash
curl -X POST http://localhost:8000/analyze -H "Content-Type: application/json" -d '{"image_data": "base64-encoded-image-data", "filename": "image.jpg"}'
```

- Send a notification:

```bash
curl -X POST http://localhost:8000/notify -H "Content-Type: application/json" -d '{"recipient_email": "recipient@example.com", "subject": "Security Alert", "message": "Suspicious activity detected."}'
```

- Clean up old images from the database:

```bash
curl -X POST http://localhost:8000/db/cleanup?days=30
```

- Get recent images from the database:

```bash
curl -X GET http://localhost:8000/db/