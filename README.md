# Home Security Camera System

The Home Security Camera System is an open-source, self-hosted solution designed to provide monitoring and analysis of security threats using computer vision and cloud technologies. This system leverages a FastAPI web application, SQLite database, AWS Rekognition, and email notifications to deliver a robust and scalable home security experience.

## Introduction

The primary goal of this project is to offer users a convenient open source solution to home security. By running locally, users maintain a level of control over their data while benefiting from advanced computer vision capabilities powered by AWS Rekognition.

The system continuously monitors a video feed from a connected camera, capturing images when motion is detected. These images are then uploaded to an AWS S3 bucket and analyzed by AWS Rekognition for potential security threats such as people, vehicles, weapons, or packages. If any threats are detected, the system sends an email notification with relevant details and a link to the uploaded image.

Additionally, the system provides a RESTful API for managing the camera, analyzing images, sending notifications, and interacting with the SQLite database, which stores captured images, security alerts, and associated metadata.

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

### Prerequisites

- Python 3.7 or higher
- A webcam or IP camera connected to your system
- An AWS account with access keys (for AWS Rekognition and S3)
- An email account for sending notifications

### Setup Wizard

The Home Security Camera System includes a user-friendly setup wizard to simplify the installation and configuration process. Follow these steps to get started:
\
make sure python is installed on your operating system.

1. Clone the repository:

```bash
git clone https://github.com/Sbussiso/home-security-server.git
cd home-security-server
```

2. Run the setup wizard:

```bash
python setup_wizard.py
```

The setup wizard will guide you through the following steps:

- **Environment Setup**: The wizard will check your Python version and install the necessary dependencies. It will also create the required directories for the project.
- **Configuration**: The wizard will prompt you to enter your AWS credentials (access key and secret key), email configuration (email address, password, SMTP server, and port), and database configuration (database path, master username, and master password).

After completing the setup wizard, a `.env` file will be created with your configuration settings.

4. Initialize the database:

```bash
python database.py
```

This step will create the SQLite database file specified in the `DB_PATH` environment variable.

## Usage

1. Start the FastAPI server:

```bash
uvicorn app:app --reload
```

The server will be accessible at `http://localhost:5000`.

2. Use the provided API endpoints to control the camera, analyze images, send notifications, and manage the database. You can use tools like Postman or cURL to interact with the API.

Here are some example API requests:

- Start camera monitoring:

```bash
curl -X POST http://localhost:5000/camera -H "Content-Type: application/json" -d '{"action": "start"}'
```

- Stop camera monitoring:

```bash
curl -X POST http://localhost:5000/camera -H "Content-Type: application/json" -d '{"action": "stop"}'
```

- Analyze an image:

```bash
curl -X POST http://localhost:5000/analyze -H "Content-Type: application/json" -d '{"image_data": "base64-encoded-image-data", "filename": "image.jpg"}'
```

- Send a notification:

```bash
curl -X POST http://localhost:5000/notify -H "Content-Type: application/json" -d '{"recipient_email": "recipient@example.com", "subject": "Security Alert", "message": "Suspicious activity detected."}'
```

- Clean up old images from the database:

```bash
curl -X POST http://localhost:5000/db/cleanup?days