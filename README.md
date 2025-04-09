# Security Camera System

This project is a security camera system that uses computer vision and machine learning to detect and analyze potential security threats. It captures images from a connected camera, uploads them to Amazon S3, and uses AWS Rekognition to analyze the images for suspicious objects or activities. If any security alerts are detected, the system can send email notifications with the relevant details and images.

## Introduction

The security camera system is designed to provide an automated solution for monitoring and detecting potential security threats. It combines various components, including image capture, database storage, cloud storage, computer vision analysis, and email notifications.

Key features:

- **Motion Detection**: The system continuously monitors the camera feed and captures images when motion is detected.
- **Image Storage**: Captured images are stored locally in a SQLite database, along with metadata and any detected security alerts.
- **Cloud Storage**: Images are uploaded to an Amazon S3 bucket for secure storage and analysis.
- **Computer Vision Analysis**: AWS Rekognition is used to analyze the uploaded images, detecting labels and potential security threats such as people, vehicles, weapons, or packages.
- **Security Alerts**: If any security-relevant objects or activities are detected, the system generates alerts with confidence levels.
- **Email Notifications**: When security alerts are triggered, the system can send email notifications with details and the relevant image attached.
- **Analytics**: The system provides a command-line interface to view recent images, security alerts, and statistics.

## Installation

To run the security camera system, you'll need to have Python 3.6 or later installed on your system. Additionally, you'll need to set up an AWS account and configure the necessary credentials and services.

1. Clone the repository:

```bash
git clone https://github.com/your-username/security-camera-system.git
cd security-camera-system
```

2. Create a virtual environment and install the required dependencies:

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
pip install -r requirements.txt
```

3. Set up the required AWS services:

   - Create an S3 bucket for storing the captured images.
   - Configure AWS Rekognition for image analysis.
   - Set up an SMTP server or email service for sending notifications (e.g., Gmail, Amazon SES).

4. Create a `.env` file in the project root directory and add the following environment variables:

```
EMAIL_USER=your-email@example.com
EMAIL_PASSWORD=your-email-password
SMTP_SERVER=your-smtp-server
SMTP_PORT=your-smtp-port
AWS_ACCESS_KEY=your-aws-access-key
AWS_SECRET_KEY=your-aws-secret-key
AWS_REGION=your-aws-region
DB_PATH=security_camera.db
```

Replace the placeholders with your actual credentials and settings.

5. Run the initial database setup:

```bash
python database.py
```

This will create the SQLite database file and initialize the necessary tables.

## Usage

To start the security camera system, run the following command:

```bash
python app.py
```

The application will prompt you with a menu:

1. **ACTIVATE SECURITY SYSTEM**: This option will start the main security camera monitoring process. It will capture images when motion is detected, upload them to S3, analyze them with Rekognition, and send email notifications if security alerts are triggered.

2. **ANALYZE ACTIVITY**: This option will display recent images, security alerts, and statistics from the database.

3. **DEACTIVATE SECURITY SYSTEM**: This option will exit the application.

While the security system is active, you can press the `q` key to quit the monitoring process.

## Contributing

Contributions to this project are welcome! If you find any issues or have suggestions for improvements, please open an issue or submit a pull request on the GitHub repository.

When contributing, please follow these guidelines:

1. Fork the repository and create a new branch for your feature or bug fix.
2. Make your changes and ensure that the code follows the project's coding style and conventions.
3. Write tests for your changes, if applicable.
4. Update the documentation (README.md, docstrings, etc.) if necessary.
5. Submit a pull request with a clear description of your changes.

## License

This project is licensed under the [MIT License](LICENSE).

## Acknowledgments

This project utilizes the following third-party libraries and services:

- OpenCV
- SQLAlchemy
- Amazon S