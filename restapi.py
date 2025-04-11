from flask import Flask, request, Response
from flask_restful import Resource, Api
from rekognition import analyze_image
from aws_s3 import upload_file, delete_bucket, s3_client
from notifications import send_security_alert
from database import (
    save_image, add_security_alert, save_temp_image_file,
    update_s3_url, cleanup_old_images, get_recent_images
)
import requests
from dotenv import load_dotenv
import os
import tempfile
import cv2
import numpy as np
import base64
import threading
import time
from datetime import datetime

# Load environment variables
load_dotenv()

# Initialize the Flask application
app = Flask(__name__)
# Create an API object from Flask-RESTful
api = Api(app)

# Global variables for camera control
camera = None
is_monitoring = False
monitor_thread = None
last_frame = None
frame_lock = threading.Lock()
last_save_time = 0
SAVE_INTERVAL = 20  # seconds between saves
last_email_time = 0
EMAIL_INTERVAL = 60  # seconds between emails

# Local REST API endpoints
REST_API_URL = "http://localhost:5000"
ANALYZE_ENDPOINT = f"{REST_API_URL}/analyze"
UPLOAD_ENDPOINT = f"{REST_API_URL}/upload"
NOTIFY_ENDPOINT = f"{REST_API_URL}/notify"
DB_IMAGE_ENDPOINT = f"{REST_API_URL}/db/image"
DB_ALERT_ENDPOINT = f"{REST_API_URL}/db/alert"
DB_CLEANUP_ENDPOINT = f"{REST_API_URL}/db/cleanup"
DB_S3URL_ENDPOINT = f"{REST_API_URL}/db/s3url"
S3_BUCKET_DELETE_ENDPOINT = f"{REST_API_URL}/s3/bucket/delete"
CAMERA_CONTROL_ENDPOINT = f"{REST_API_URL}/camera"

def monitor_camera():
    global camera, is_monitoring, last_frame, frame_lock, last_save_time, last_email_time
    backSub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=True)
    
    while is_monitoring:
        if camera is None or not camera.isOpened():
            time.sleep(0.1)
            continue
            
        ret, frame = camera.read()
        if not ret:
            continue
            
        # Process frame for motion detection
        frame = cv2.resize(frame, (500, 500))
        original_frame = frame.copy()
        fgMask = backSub.apply(frame)
        _, thresh = cv2.threshold(fgMask, 250, 255, cv2.THRESH_BINARY)
        thresh = cv2.erode(thresh, None, iterations=2)
        thresh = cv2.dilate(thresh, None, iterations=2)
        
        # Detect motion
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        motion_detected = False
        
        for c in contours:
            if cv2.contourArea(c) < 1500:
                continue
            motion_detected = True
            (x, y, w, h) = cv2.boundingRect(c)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, "Motion Detected", (10, 20),
                      cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        
        with frame_lock:
            last_frame = frame.copy()
        
        # Process motion detection
        if motion_detected:
            current_time = time.time()
            if current_time - last_save_time >= SAVE_INTERVAL:
                process_motion(original_frame)
                last_save_time = current_time
        
        time.sleep(0.1)

def process_motion(frame):
    """
    Process a frame with detected motion:
    1. Save to database
    2. Upload to S3
    3. Analyze with Rekognition
    4. Send email notification if needed
    """
    try:
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"motion_{timestamp}.jpg"
        
        # Save to temporary file
        temp_path = f"temp_{filename}"
        cv2.imwrite(temp_path, frame)
        
        try:
            # First save to database
            _, buffer = cv2.imencode('.jpg', frame)
            image_base64 = base64.b64encode(buffer).decode('utf-8')
            
            response = requests.post(DB_IMAGE_ENDPOINT, json={
                'image_data': image_base64,
                'filename': filename
            })
            response.raise_for_status()
            db_result = response.json()
            
            if not db_result.get('success'):
                print(f"Failed to save image to database: {db_result.get('error')}")
                return
                
            image_id = db_result.get('image_id')
            
            # Upload to S3
            success, error, s3_url = upload_file(temp_path, 'computer-vision-analysis', filename)
            if not success:
                print(f"Failed to upload to S3: {error}")
                return
            
            # Update S3 URL in database
            response = requests.post(DB_S3URL_ENDPOINT, json={
                'image_id': image_id,
                's3_url': s3_url
            })
            response.raise_for_status()
            
            # Analyze with Rekognition
            analysis = analyze_image(s3_url)
            if analysis.get('error'):
                print(f"Error analyzing image: {analysis['error']}")
                return
            
            # Process security alerts
            if analysis['security_alerts']:
                process_security_alerts(image_id, analysis['security_alerts'], frame, s3_url)
                
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
    except Exception as e:
        print(f"Error processing motion: {str(e)}")

def process_security_alerts(image_id, alerts, frame, s3_url):
    """
    Process security alerts:
    1. Add alerts to database
    2. Send email notification if needed
    """
    global last_email_time
    
    try:
        current_time = time.time()
        
        # Add alerts to database
        for alert in alerts:
            try:
                response = requests.post(DB_ALERT_ENDPOINT, json={
                    'image_id': image_id,
                    'alert_type': alert['type'],
                    'confidence': alert['confidence']
                })
                response.raise_for_status()
            except Exception as e:
                print(f"Failed to save alert: {str(e)}")
        
        # Send email notification if needed
        if os.getenv('EMAIL_USER') and (current_time - last_email_time >= EMAIL_INTERVAL):
            subject = "🚨 Security Alert: Suspicious Activity Detected"
            alert_details = "\n".join([
                f"- {alert['type']} (Confidence: {alert['confidence']:.2f}%)" 
                for alert in alerts
            ])
            
            message = f"""Security Alert from your camera system!

Suspicious activity has been detected:

{alert_details}

The image has been saved to your S3 bucket.
Image URL: {s3_url}

This is an automated message from your security camera system.
"""
            try:
                # Convert frame to base64
                _, buffer = cv2.imencode('.jpg', frame)
                image_base64 = base64.b64encode(buffer).decode('utf-8')
                
                response = requests.post(NOTIFY_ENDPOINT, json={
                    'recipient_email': os.getenv('EMAIL_USER'),
                    'subject': subject,
                    'message': message,
                    'image_data': image_base64
                })
                response.raise_for_status()
                last_email_time = current_time
                
            except Exception as e:
                print(f"Error sending email: {str(e)}")
                
    except Exception as e:
        print(f"Error processing security alerts: {str(e)}")

# Define a resource
class HelloWorld(Resource):
    def get(self):
        # Returns a JSON response for GET requests
        return {'message': 'Hello, world!'}

    def post(self):
        # For a POST request, get the JSON payload sent by the client
        json_data = request.get_json(force=True)
        # You can process json_data here. For demonstration, we return it back.
        return {'you sent': json_data}, 201

class ImageAnalysis(Resource):
    def post(self):
        """
        Analyze an image using AWS Rekognition.
        Expects a JSON payload with 'image_url' field.
        """
        try:
            # Get the image URL from the request
            data = request.get_json(force=True)
            image_url = data.get('image_url')
            
            if not image_url:
                return {'error': 'No image URL provided'}, 400

            # Use the existing analyze_image function from rekognition.py
            result = analyze_image(image_url)
            return result, 200

        except Exception as e:
            return {'error': f'Unexpected error: {str(e)}'}, 500

class S3Upload(Resource):
    def post(self):
        """
        Upload an image to S3 and return the URL.
        Expects a JSON payload with 'image_data' (base64 encoded) and 'filename' fields.
        """
        try:
            data = request.get_json(force=True)
            image_data = data.get('image_data')
            filename = data.get('filename')
            
            if not image_data or not filename:
                return {'error': 'Missing image_data or filename'}, 400

            try:
                # Decode base64 image data
                image_bytes = base64.b64decode(image_data)
                nparr = np.frombuffer(image_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if img is None:
                    return {'error': 'Invalid image data'}, 400

                # Save image to temporary file
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                    cv2.imwrite(temp_file.name, img)
                    temp_path = temp_file.name

                try:
                    # Use the existing upload_file function from aws_s3.py
                    success, error, s3_url = upload_file(
                        temp_path,
                        'computer-vision-analysis',
                        filename
                    )

                    if success:
                        return {
                            'success': True,
                            's3_url': s3_url
                        }, 200
                    else:
                        return {'error': error}, 500

                finally:
                    # Clean up temporary file
                    if os.path.exists(temp_path):
                        os.remove(temp_path)

            except base64.binascii.Error:
                return {'error': 'Invalid base64 image data'}, 400
            except Exception as e:
                return {'error': f'Error processing image: {str(e)}'}, 400

        except Exception as e:
            return {'error': f'Error uploading to S3: {str(e)}'}, 500

class Notification(Resource):
    def post(self):
        """
        Send a security alert notification.
        Expects a JSON payload with 'recipient_email', 'subject', 'message', and 'image_data' (base64 encoded) fields.
        """
        try:
            data = request.get_json(force=True)
            recipient_email = data.get('recipient_email')
            subject = data.get('subject')
            message = data.get('message')
            image_data = data.get('image_data')
            
            if not all([recipient_email, subject, message]):
                return {'error': 'Missing required fields'}, 400

            temp_path = None
            try:
                # If image data is provided, save it to a temporary file
                if image_data:
                    image_bytes = base64.b64decode(image_data)
                    nparr = np.frombuffer(image_bytes, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    
                    if img is None:
                        return {'error': 'Invalid image data'}, 400

                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                        cv2.imwrite(temp_file.name, img)
                        temp_path = temp_file.name

                # Use the existing send_security_alert function
                success, error = send_security_alert(
                    recipient_email,
                    subject,
                    message,
                    temp_path
                )

                if success:
                    return {'success': True}, 200
                else:
                    return {'error': error}, 500

            finally:
                # Clean up temporary file
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

        except base64.binascii.Error:
            return {'error': 'Invalid base64 image data'}, 400
        except Exception as e:
            return {'error': f'Error sending notification: {str(e)}'}, 500

class DatabaseImage(Resource):
    def post(self):
        """
        Save an image to the database.
        Expects a JSON payload with 'image_data' (base64 encoded) and 'filename' fields.
        """
        try:
            data = request.get_json(force=True)
            image_data = data.get('image_data')
            filename = data.get('filename')
            
            if not image_data or not filename:
                return {'error': 'Missing image_data or filename'}, 400

            # Decode base64 image data
            image_bytes = base64.b64decode(image_data)
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                return {'error': 'Invalid image data'}, 400

            # Save to database
            image_id = save_image(img, filename)
            return {'success': True, 'image_id': image_id}, 200

        except Exception as e:
            return {'error': f'Error saving image to database: {str(e)}'}, 500

    def get(self):
        """
        Get recent images from the database.
        Optional query parameter 'limit' to specify number of images to return.
        """
        try:
            limit = request.args.get('limit', default=10, type=int)
            images = get_recent_images(limit)
            
            # Convert datetime objects to strings
            serialized_images = []
            for image in images:
                serialized_image = {
                    'id': image['id'],
                    'timestamp': image['timestamp'].strftime("%Y-%m-%d %H:%M:%S"),
                    'filename': image['filename'],
                    's3_url': image['s3_url'],
                    'width': image['width'],
                    'height': image['height'],
                    'alert_count': image['alert_count']
                }
                serialized_images.append(serialized_image)
            
            return {'images': serialized_images}, 200
        except Exception as e:
            return {'error': f'Error retrieving images: {str(e)}'}, 500

class SecurityAlert(Resource):
    def post(self):
        """
        Add a security alert to the database.
        Expects a JSON payload with 'image_id', 'alert_type', and 'confidence' fields.
        """
        try:
            data = request.get_json(force=True)
            image_id = data.get('image_id')
            alert_type = data.get('alert_type')
            confidence = data.get('confidence')
            
            if not all([image_id, alert_type, confidence]):
                return {'error': 'Missing required fields'}, 400

            # Add alert to database
            alert_id = add_security_alert(image_id, alert_type, confidence)
            return {'success': True, 'alert_id': alert_id}, 200

        except Exception as e:
            return {'error': f'Error adding security alert: {str(e)}'}, 500

class DatabaseCleanup(Resource):
    def post(self):
        """
        Clean up old images from the database.
        Optional query parameter 'days' to specify how many days of images to keep.
        """
        try:
            days = request.args.get('days', default=30, type=int)
            deleted_count = cleanup_old_images(days)
            return {'success': True, 'deleted_count': deleted_count}, 200
        except Exception as e:
            return {'error': f'Error cleaning up database: {str(e)}'}, 500

class S3UrlUpdate(Resource):
    def post(self):
        """
        Update the S3 URL for an image in the database.
        Expects a JSON payload with 'image_id' and 's3_url' fields.
        """
        try:
            data = request.get_json(force=True)
            image_id = data.get('image_id')
            s3_url = data.get('s3_url')
            
            if not all([image_id, s3_url]):
                return {'error': 'Missing required fields'}, 400

            # Update S3 URL
            success = update_s3_url(image_id, s3_url)
            if success:
                return {'success': True}, 200
            else:
                return {'error': 'Failed to update S3 URL'}, 500

        except Exception as e:
            return {'error': f'Error updating S3 URL: {str(e)}'}, 500

class S3BucketDelete(Resource):
    def post(self):
        """
        Emergency protocol to delete the entire S3 bucket and all its contents.
        This is a destructive operation that cannot be undone.
        
        Expects a JSON payload with 'bucket_name' and 'confirmation' fields.
        The confirmation field must be set to "CONFIRM_DELETE" to proceed.
        """
        try:
            data = request.get_json(force=True)
            bucket_name = data.get('bucket_name')
            confirmation = data.get('confirmation')
            
            if not bucket_name or not confirmation:
                return {'error': 'Missing bucket_name or confirmation'}, 400
                
            if confirmation != "CONFIRM_DELETE":
                return {'error': 'Invalid confirmation code. This operation requires explicit confirmation.'}, 400

            # Use the delete_bucket function with the imported s3_client
            success, error = delete_bucket(bucket_name, s3_client)
            
            if success:
                return {
                    'success': True,
                    'message': f'Bucket {bucket_name} and all its contents have been deleted'
                }, 200
            else:
                return {'error': error}, 500

        except Exception as e:
            return {'error': f'Error deleting bucket: {str(e)}'}, 500

class CameraControl(Resource):
    def post(self):
        """
        Control the camera (start/stop monitoring).
        Expects a JSON payload with 'action' field ('start' or 'stop').
        """
        try:
            data = request.get_json(force=True)
            action = data.get('action')
            
            if not action:
                return {'error': 'Missing action parameter'}, 400
                
            global camera, is_monitoring, monitor_thread
            
            if action == 'start':
                if is_monitoring:
                    return {'error': 'Camera is already monitoring'}, 400
                    
                camera = cv2.VideoCapture(0)
                if not camera.isOpened():
                    return {'error': 'Could not open video device'}, 500
                    
                is_monitoring = True
                monitor_thread = threading.Thread(target=monitor_camera)
                monitor_thread.daemon = True
                monitor_thread.start()
                return {'success': True, 'message': 'Camera monitoring started'}, 200
                
            elif action == 'stop':
                if not is_monitoring:
                    return {'error': 'Camera is not monitoring'}, 400
                    
                is_monitoring = False
                if monitor_thread:
                    monitor_thread.join(timeout=1.0)
                if camera:
                    camera.release()
                    camera = None
                return {'success': True, 'message': 'Camera monitoring stopped'}, 200
                
            else:
                return {'error': 'Invalid action. Use "start" or "stop"'}, 400
                
        except Exception as e:
            return {'error': f'Error controlling camera: {str(e)}'}, 500

    def get(self):
        """
        Get the current camera frame.
        Returns the frame as a base64 encoded image.
        """
        try:
            global last_frame, frame_lock
            
            with frame_lock:
                if last_frame is None:
                    return {'error': 'No frame available'}, 404
                    
                # Convert frame to JPEG
                _, buffer = cv2.imencode('.jpg', last_frame)
                frame_base64 = base64.b64encode(buffer).decode('utf-8')
                
                return {
                    'success': True,
                    'frame': frame_base64
                }, 200
                
        except Exception as e:
            return {'error': f'Error getting camera frame: {str(e)}'}, 500

# Add the resources to the API
api.add_resource(HelloWorld, '/')
api.add_resource(ImageAnalysis, '/analyze')
api.add_resource(S3Upload, '/upload')
api.add_resource(Notification, '/notify')
api.add_resource(DatabaseImage, '/db/image')
api.add_resource(SecurityAlert, '/db/alert')
api.add_resource(DatabaseCleanup, '/db/cleanup')
api.add_resource(S3UrlUpdate, '/db/s3url')
api.add_resource(S3BucketDelete, '/s3/bucket/delete')
api.add_resource(CameraControl, '/camera')

if __name__ == '__main__':
    # Run the Flask app in debug mode for development purposes
    app.run(debug=True)
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import asyncio
import aiofiles
import aiobotocore.session
from aiohttp import ClientSession
from contextlib import asynccontextmanager
from rekognition import analyze_image
from notifications import send_security_alert
from database import (
    save_image, add_security_alert, save_temp_image_file,
    update_s3_url, cleanup_old_images, get_recent_images
)
import requests
from dotenv import load_dotenv
import os
import tempfile
import cv2
import numpy as np
import base64
import threading
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.exceptions import ClientError

# Load environment variables
load_dotenv()

# Global variables for camera control
camera = None
is_monitoring = False
monitor_thread = None
last_frame = None
frame_lock = threading.Lock()
last_save_time = 0
SAVE_INTERVAL = 20  # seconds between saves
last_email_time = 0
EMAIL_INTERVAL = 60  # seconds between emails

# Thread pool for CPU-bound operations
thread_pool = ThreadPoolExecutor(max_workers=4)

# Async session for HTTP requests
async_session = None

# Initialize synchronous S3 client for camera operations
s3_client_sync = boto3.client(
    's3',
    region_name=os.getenv('AWS_REGION'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('AWS_SECRET_KEY')
)

async def init_async_clients():
    global async_session
    try:
        async_session = ClientSession()
    except Exception as e:
        print(f"Error initializing async clients: {str(e)}")
        raise

async def cleanup_async_clients():
    global async_session
    try:
        if async_session:
            await async_session.close()
    except Exception as e:
        print(f"Error cleaning up async clients: {str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await init_async_clients()
        yield
    finally:
        # Shutdown
        await cleanup_async_clients()

# Initialize the FastAPI application
app = FastAPI(
    title="Security Camera API",
    description="API for security camera monitoring and analysis",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for request/response validation
class CameraAction(BaseModel):
    action: str

class ImageData(BaseModel):
    image_data: str
    filename: str

class AlertData(BaseModel):
    image_id: int
    alert_type: str
    confidence: float

class S3UrlData(BaseModel):
    image_id: int
    s3_url: str

class NotificationData(BaseModel):
    recipient_email: str
    subject: str
    message: str
    image_data: Optional[str] = None

class S3BucketDelete(BaseModel):
    bucket_name: str
    confirmation: str

def sync_upload_to_s3(file_path: str, bucket_name: str, filename: str):
    """Synchronously upload a file to S3"""
    try:
        # Upload the file
        s3_client_sync.upload_file(file_path, bucket_name, filename)
        
        # Generate a pre-signed URL that expires in 1 hour
        presigned_url = s3_client_sync.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket_name,
                'Key': filename
            },
            ExpiresIn=3600  # URL expires in 1 hour
        )
        
        return True, None, presigned_url
    except Exception as e:
        print(f"Error uploading to S3: {str(e)}")
        return False, str(e), None

async def async_save_image_to_db(image_data: np.ndarray, filename: str):
    """Asynchronously save image to database"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        thread_pool,
        save_image,
        image_data,
        filename
    )

async def async_analyze_image(image_url: str):
    """Asynchronously analyze image with Rekognition"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        thread_pool,
        analyze_image,
        image_url
    )

async def async_send_notification(recipient_email: str, subject: str, message: str, image_path: Optional[str] = None):
    """Asynchronously send notification"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        thread_pool,
        send_security_alert,
        recipient_email,
        subject,
        message,
        image_path
    )

async def async_update_s3_url(image_id: int, s3_url: str):
    """Asynchronously update S3 URL in database"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        thread_pool,
        update_s3_url,
        image_id,
        s3_url
    )

def process_motion_sync(frame: np.ndarray):
    """Synchronously process motion detection"""
    try:
        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"motion_{timestamp}.jpg"
        
        # Save to temporary file
        temp_path = f"temp_{filename}"
        cv2.imwrite(temp_path, frame)
        
        try:
            # Save to database
            image_id = save_image(frame, filename)
            
            # Upload to S3
            success, error, s3_url = sync_upload_to_s3(
                temp_path,
                'computer-vision-analysis',
                filename
            )
            
            if not success:
                print(f"Failed to upload to S3: {error}")
                return
            
            # Update S3 URL in database
            update_s3_url(image_id, s3_url)
            
            # Analyze with Rekognition
            analysis = analyze_image(s3_url)
            if analysis.get('error'):
                print(f"Error analyzing image: {analysis['error']}")
                return
            
            # Process security alerts
            if analysis['security_alerts']:
                process_security_alerts_sync(
                    image_id,
                    analysis['security_alerts'],
                    frame,
                    s3_url
                )
                
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
    except Exception as e:
        print(f"Error processing motion: {str(e)}")

def process_security_alerts_sync(image_id: int, alerts: List[dict], frame: np.ndarray, s3_url: str):
    """Synchronously process security alerts"""
    global last_email_time
    
    try:
        current_time = time.time()
        
        # Add alerts to database
        for alert in alerts:
            try:
                add_security_alert(
                    image_id,
                    alert['type'],
                    alert['confidence']
                )
            except Exception as e:
                print(f"Failed to save alert: {str(e)}")
        
        # Send email notification if needed
        if os.getenv('EMAIL_USER') and (current_time - last_email_time >= EMAIL_INTERVAL):
            subject = "🚨 Security Alert: Suspicious Activity Detected"
            alert_details = "\n".join([
                f"- {alert['type']} (Confidence: {alert['confidence']:.2f}%)" 
                for alert in alerts
            ])
            
            message = f"""Security Alert from your camera system!

Suspicious activity has been detected:

{alert_details}

The image has been saved to your S3 bucket.
Image URL: {s3_url}

This is an automated message from your security camera system.
"""
            try:
                # Save frame to temporary file for email
                temp_path = f"temp_alert_{image_id}.jpg"
                cv2.imwrite(temp_path, frame)
                
                send_security_alert(
                    os.getenv('EMAIL_USER'),
                    subject,
                    message,
                    temp_path
                )
                
                last_email_time = current_time
                
                # Clean up temporary file
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    
            except Exception as e:
                print(f"Error sending email: {str(e)}")
                
    except Exception as e:
        print(f"Error processing security alerts: {str(e)}")

async def monitor_camera_async():
    """Asynchronous camera monitoring"""
    global camera, is_monitoring, last_frame, frame_lock, last_save_time, last_email_time
    backSub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=True)
    
    while is_monitoring:
        if camera is None or not camera.isOpened():
            await asyncio.sleep(0.1)
            continue
            
        ret, frame = camera.read()
        if not ret:
            continue
            
        # Process frame for motion detection
        frame = cv2.resize(frame, (500, 500))
        original_frame = frame.copy()
        fgMask = backSub.apply(frame)
        _, thresh = cv2.threshold(fgMask, 250, 255, cv2.THRESH_BINARY)
        thresh = cv2.erode(thresh, None, iterations=2)
        thresh = cv2.dilate(thresh, None, iterations=2)
        
        # Detect motion
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        motion_detected = False
        
        for c in contours:
            if cv2.contourArea(c) < 1500:
                continue
            motion_detected = True
            (x, y, w, h) = cv2.boundingRect(c)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, "Motion Detected", (10, 20),
                      cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        
        with frame_lock:
            last_frame = frame.copy()
        
        # Process motion detection synchronously
        if motion_detected:
            current_time = time.time()
            if current_time - last_save_time >= SAVE_INTERVAL:
                process_motion_sync(original_frame)
                last_save_time = current_time
        
        await asyncio.sleep(0.1)

@app.post("/camera")
async def camera_control(action: CameraAction):
    """Control the camera (start/stop monitoring)"""
    try:
        global camera, is_monitoring, monitor_thread
        
        if action.action == 'start':
            if is_monitoring:
                raise HTTPException(status_code=400, detail="Camera is already monitoring")
                
            camera = cv2.VideoCapture(0)
            if not camera.isOpened():
                raise HTTPException(status_code=500, detail="Could not open video device")
                
            is_monitoring = True
            # Create a new event loop for the monitoring thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            monitor_thread = threading.Thread(
                target=lambda: loop.run_until_complete(monitor_camera_async())
            )
            monitor_thread.daemon = True
            monitor_thread.start()
            return {"success": True, "message": "Camera monitoring started"}
            
        elif action.action == 'stop':
            if not is_monitoring:
                raise HTTPException(status_code=400, detail="Camera is not monitoring")
                
            is_monitoring = False
            if monitor_thread:
                monitor_thread.join(timeout=1.0)
            if camera:
                camera.release()
                camera = None
            return {"success": True, "message": "Camera monitoring stopped"}
            
        else:
            raise HTTPException(status_code=400, detail="Invalid action. Use 'start' or 'stop'")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error controlling camera: {str(e)}")

@app.get("/camera")
async def get_camera_frame():
    """Get the current camera frame"""
    try:
        global last_frame, frame_lock
        
        with frame_lock:
            if last_frame is None:
                raise HTTPException(status_code=404, detail="No frame available")
                
            # Convert frame to JPEG
            _, buffer = cv2.imencode('.jpg', last_frame)
            frame_base64 = base64.b64encode(buffer).decode('utf-8')
            
            return {
                "success": True,
                "frame": frame_base64
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting camera frame: {str(e)}")

@app.post("/analyze")
async def analyze_image_endpoint(image_data: ImageData):
    """Analyze an image using AWS Rekognition"""
    try:
        # Decode base64 image data
        image_bytes = base64.b64decode(image_data.image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image data")
            
        # Save to temporary file
        temp_path = f"temp_{image_data.filename}"
        cv2.imwrite(temp_path, img)
        
        try:
            # Upload to S3
            success, error, s3_url = sync_upload_to_s3(
                temp_path,
                'computer-vision-analysis',
                image_data.filename
            )
            
            if not success:
                raise HTTPException(status_code=500, detail=f"Failed to upload to S3: {error}")
                
            # Analyze with Rekognition
            analysis = await async_analyze_image(s3_url)
            return analysis
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing image: {str(e)}")

@app.post("/notify")
async def send_notification(notification: NotificationData):
    """Send a security alert notification"""
    try:
        temp_path = None
        try:
            # If image data is provided, save it to a temporary file
            if notification.image_data:
                image_bytes = base64.b64decode(notification.image_data)
                nparr = np.frombuffer(image_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if img is None:
                    raise HTTPException(status_code=400, detail="Invalid image data")
                    
                temp_path = f"temp_notification_{int(time.time())}.jpg"
                cv2.imwrite(temp_path, img)
                
            # Send notification
            success, error = await async_send_notification(
                notification.recipient_email,
                notification.subject,
                notification.message,
                temp_path
            )
            
            if success:
                return {"success": True}
            else:
                raise HTTPException(status_code=500, detail=error)
                
        finally:
            # Clean up temporary file
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending notification: {str(e)}")

@app.post("/db/cleanup")
async def cleanup_database(days: int = 30):
    """Clean up old images from the database"""
    try:
        loop = asyncio.get_event_loop()
        deleted_count = await loop.run_in_executor(
            thread_pool,
            cleanup_old_images,
            days
        )
        return {"success": True, "deleted_count": deleted_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cleaning up database: {str(e)}")

@app.get("/db/image")
async def get_images(limit: int = 10):
    """Get recent images from the database"""
    try:
        loop = asyncio.get_event_loop()
        images = await loop.run_in_executor(
            thread_pool,
            get_recent_images,
            limit
        )
        
        # Convert datetime objects to strings
        serialized_images = []
        for image in images:
            serialized_image = {
                'id': image['id'],
                'timestamp': image['timestamp'].strftime("%Y-%m-%d %H:%M:%S"),
                'filename': image['filename'],
                's3_url': image['s3_url'],
                'width': image['width'],
                'height': image['height'],
                'alert_count': image['alert_count']
            }
            serialized_images.append(serialized_image)
        
        return {"images": serialized_images}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving images: {str(e)}")

@app.post("/s3/bucket/delete")
async def delete_s3_bucket(data: S3BucketDelete):
    """Delete an S3 bucket and all its contents"""
    try:
        if data.confirmation != "CONFIRM_DELETE":
            raise HTTPException(status_code=400, detail="Invalid confirmation code")
            
        # Delete all objects in the bucket
        paginator = s3_client_sync.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=data.bucket_name):
            if 'Contents' in page:
                delete_keys = {'Objects': [{'Key': obj['Key']} for obj in page['Contents']]}
                s3_client_sync.delete_objects(Bucket=data.bucket_name, Delete=delete_keys)
        
        # Delete the bucket itself
        s3_client_sync.delete_bucket(Bucket=data.bucket_name)
        return {"success": True, "message": f"Bucket {data.bucket_name} and all contents deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting bucket: {str(e)}")

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=5000) 