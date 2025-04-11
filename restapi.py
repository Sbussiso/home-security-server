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
    update_s3_url, cleanup_old_images, get_recent_images,
    DB_PATH
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

# --- S3 Helper Functions (adapted from aws_s3.py) ---
def bucket_exists(bucket_name, s3_client):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        print(f"Bucket '{bucket_name}' exists.") # Added print
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            print(f"Bucket '{bucket_name}' does not exist.") # Added print
            return False
        else:
            print(f"Error checking bucket '{bucket_name}': {e}") # Added print
            raise

def create_bucket(bucket_name, s3_client, region=None):
    try:
        if region is None:
             region = os.getenv('AWS_REGION', 'us-east-1') # Default if not provided

        if region == 'us-east-1':
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        print(f'Bucket "{bucket_name}" created successfully in region {region}.')
    except ClientError as e:
        print(f"Error creating bucket '{bucket_name}': {e}")
        return False
    return True

# --- End S3 Helper Functions ---

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
    # Ensure the bucket exists before uploading
    try:
        if not bucket_exists(bucket_name, s3_client_sync):
            print(f"Attempting to create bucket '{bucket_name}'...")
            if not create_bucket(bucket_name, s3_client_sync):
                error_msg = f"Failed to create bucket '{bucket_name}'. Cannot upload."
                print(error_msg)
                return False, error_msg, None
    except Exception as check_create_e:
        # Catch errors during bucket check/creation
        error_msg = f"Error checking/creating bucket '{bucket_name}': {str(check_create_e)}"
        print(error_msg)
        return False, error_msg, None

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
        
        # Add specific check for NoSuchBucket during upload itself (redundant but safe)
        if isinstance(e, ClientError) and e.response['Error']['Code'] == 'NoSuchBucket':
             error_msg = f"Failed to upload {filename} to S3: Bucket '{bucket_name}' does not exist (check permissions or region)."
             print(error_msg)
             return False, error_msg, None
        else:
            error_msg = f"Error uploading {filename} to S3: {str(e)}"
            print(error_msg)
            return False, error_msg, None

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

# New endpoint to delete the database file
@app.post("/db/delete-file")
async def delete_database_file():
    """Deletes the entire SQLite database file."""
    try:
        if os.path.exists(DB_PATH):
            print(f"Attempting to delete database file: {DB_PATH}")
            os.remove(DB_PATH)
            # Wait a moment to ensure file handle is released if needed
            await asyncio.sleep(0.5)
            if not os.path.exists(DB_PATH):
                print(f"Successfully deleted database file: {DB_PATH}")
                return {"success": True, "message": "Database file deleted successfully."}
            else:
                # This might happen if permissions are wrong or file is locked
                print(f"Error: Database file {DB_PATH} still exists after removal attempt.")
                raise HTTPException(status_code=500, detail="Failed to delete database file (still exists).")
        else:
            print(f"Database file {DB_PATH} not found, nothing to delete.")
            return {"success": True, "message": "Database file not found, considered success."}
    except PermissionError as pe:
         print(f"PermissionError deleting database file {DB_PATH}: {pe}")
         raise HTTPException(status_code=500, detail=f"Permission error deleting database file: {str(pe)}")
    except Exception as e:
        print(f"Error deleting database file {DB_PATH}: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting database file: {str(e)}")

if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=5000) 