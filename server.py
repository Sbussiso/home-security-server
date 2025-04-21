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
import logging
import json
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
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess

# Import camera functions
import camera as cam
from iot_logging import AWSIoTHandlerV2

def show_setup_wizard_prompt():
    """Show a GUI prompt to run the setup wizard"""
    root = tk.Tk()
    root.title("Security System Setup Required")
    root.geometry("500x300")
    root.resizable(False, False)
    
    # Create main frame
    main_frame = ttk.Frame(root, padding="20")
    main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    
    # Welcome message
    welcome_label = ttk.Label(
        main_frame,
        text="Welcome to the Security System!",
        font=("Arial", 14, "bold")
    )
    welcome_label.grid(row=0, column=0, pady=10)
    
    # Message
    message = """
    No configuration file (.env) found.
    Please run the setup wizard to configure your security system.
    """
    message_label = ttk.Label(main_frame, text=message, wraplength=450, justify=tk.LEFT)
    message_label.grid(row=1, column=0, pady=10)
    
    # Buttons
    button_frame = ttk.Frame(main_frame)
    button_frame.grid(row=2, column=0, pady=20)
    
    def run_setup_wizard():
        try:
            subprocess.Popen(["python", "setup_wizard.py"])
            root.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start setup wizard: {str(e)}")
    
    def exit_app():
        root.destroy()
        sys.exit(1)
    
    setup_button = ttk.Button(button_frame, text="Run Setup Wizard", command=run_setup_wizard)
    setup_button.grid(row=0, column=0, padx=10)
    
    exit_button = ttk.Button(button_frame, text="Exit", command=exit_app)
    exit_button.grid(row=0, column=1, padx=10)
    
    root.mainloop()

# Check if .env file exists
if not os.path.exists('.env'):
    show_setup_wizard_prompt()
    sys.exit(1)

# Load environment variables
load_dotenv()

# Global variables for camera control
# camera = None # Removed - managed in camera.py
# is_monitoring = False # Removed - managed in camera.py
# monitor_thread = None # Removed - managed in camera.py
# last_frame = None # Removed - managed in camera.py
# frame_lock = threading.Lock() # Removed - managed in camera.py
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

# Configure root logger
log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)

# Basic console logging first
logging.basicConfig(level=log_level,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add AWS IoT Handler if configured
aws_iot_handler = AWSIoTHandlerV2(level=log_level)
if aws_iot_handler.endpoint: # Check if handler is configured
    # Note: The handler itself now does JSON formatting, simple formatter is fine here or none
    logging.getLogger().addHandler(aws_iot_handler)
    logging.info("AWS IoT Logging Handler V2 configured.")
else:
    logging.warning("AWS IoT Logging Handler V2 not configured (check environment variables).")

# --- S3 Helper Functions (adapted from aws_s3.py) ---
def bucket_exists(bucket_name, s3_client):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        logging.info(f"Bucket '{bucket_name}' exists.")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            logging.info(f"Bucket '{bucket_name}' does not exist.")
            return False
        else:
            logging.error(f"Error checking bucket '{bucket_name}': {e}", exc_info=True)
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
        logging.info(f'Bucket "{bucket_name}" created successfully in region {region}.')
    except ClientError as e:
        logging.error(f"Error creating bucket '{bucket_name}': {e}", exc_info=True)
        return False
    return True

# --- End S3 Helper Functions ---

async def init_async_clients():
    global async_session
    try:
        async_session = ClientSession()
        logging.info("Async HTTP client session initialized.")
    except Exception as e:
        logging.error(f"Error initializing async clients: {str(e)}", exc_info=True)
        raise

async def cleanup_async_clients():
    global async_session
    try:
        if async_session:
            await async_session.close()
            logging.info("Async HTTP client session closed.")
    except Exception as e:
        logging.error(f"Error cleaning up async clients: {str(e)}", exc_info=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logging.info("Application startup...")
    try:
        await init_async_clients()
        yield
    finally:
        # Shutdown
        logging.info("Application shutdown...")
        await cleanup_async_clients()
        # Ensure IoT handler is closed properly
        if aws_iot_handler:
            aws_iot_handler.close()
        logging.info("Application shutdown complete.")

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
            logging.info(f"Attempting to create bucket '{bucket_name}'...")
            if not create_bucket(bucket_name, s3_client_sync):
                error_msg = f"Failed to create bucket '{bucket_name}'. Cannot upload."
                logging.error(error_msg)
                return False, error_msg, None
    except Exception as check_create_e:
        # Catch errors during bucket check/creation
        error_msg = f"Error checking/creating bucket '{bucket_name}': {str(check_create_e)}"
        logging.error(error_msg, exc_info=True)
        return False, error_msg, None

    try:
        # Upload the file
        logging.info(f"Uploading {filename} to S3 bucket {bucket_name}...")
        s3_client_sync.upload_file(file_path, bucket_name, filename)
        logging.info(f"Successfully uploaded {filename} to S3.")
        
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
        logging.error(f"Error uploading {filename} to S3: {str(e)}", exc_info=True)
        
        # Add specific check for NoSuchBucket during upload itself (redundant but safe)
        if isinstance(e, ClientError) and e.response['Error']['Code'] == 'NoSuchBucket':
             error_msg = f"Failed to upload {filename} to S3: Bucket '{bucket_name}' does not exist (check permissions or region)."
             logging.error(error_msg)
             return False, error_msg, None
        else:
            error_msg = f"Error uploading {filename} to S3: {str(e)}"
            logging.error(error_msg)
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
        logging.info(f"Processing motion detection for {filename}")
        
        # Save to temporary file
        temp_path = f"temp_{filename}"
        cv2.imwrite(temp_path, frame)
        
        try:
            # Save to database
            image_id = save_image(frame, filename)
            logging.info(f"Saved image {filename} to database (ID: {image_id})")
            
            # Upload to S3
            success, error, s3_url = sync_upload_to_s3(
                temp_path,
                'computer-vision-analysis',
                filename
            )
            
            if not success:
                logging.error(f"Failed to upload {filename} to S3: {error}")
                return
            
            # Update S3 URL in database
            update_s3_url(image_id, s3_url)
            logging.info(f"Updated S3 URL for image ID {image_id}")
            
            # Analyze with Rekognition
            logging.info(f"Analyzing image {filename} with Rekognition...")
            analysis = analyze_image(s3_url)
            if analysis.get('error'):
                logging.error(f"Error analyzing image {filename}: {analysis['error']}")
                return
            
            # Process security alerts
            if analysis['security_alerts']:
                logging.info(f"Security alerts found for {filename}. Processing...")
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
        logging.error(f"Error processing motion: {str(e)}", exc_info=True)

def process_security_alerts_sync(image_id: int, alerts: List[dict], frame: np.ndarray, s3_url: str):
    """Synchronously process security alerts"""
    global last_email_time
    
    try:
        current_time = time.time()
        
        # Add alerts to database
        for alert in alerts:
            try:
                alert_id = add_security_alert(
                    image_id,
                    alert['type'],
                    alert['confidence']
                )
                logging.info(f"Saved alert ID {alert_id} ({alert['type']}) for image ID {image_id}")
            except Exception as e:
                logging.error(f"Failed to save alert for image ID {image_id}: {str(e)}", exc_info=True)
        
        # Send email notification if needed
        recipient = os.getenv('EMAIL_USER')
        if recipient and (current_time - last_email_time >= EMAIL_INTERVAL):
            subject = "🚨 Security Alert: Suspicious Activity Detected"
            alert_details = "\n".join([
                f"- {alert['type']}) (Confidence: {alert['confidence']:.2f}%)" 
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
                
                logging.info(f"Sending security alert email to {recipient} for image ID {image_id}")
                success, error = send_security_alert(
                    recipient,
                    subject,
                    message,
                    temp_path
                )
                if success:
                     logging.info("Security alert email sent successfully.")
                     last_email_time = current_time
                else:
                    logging.error(f"Failed to send security alert email: {error}")
                
                # Clean up temporary file
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    
            except Exception as e:
                logging.error(f"Error sending email: {str(e)}", exc_info=True)
                
    except Exception as e:
        logging.error(f"Error processing security alerts: {str(e)}", exc_info=True)

@app.post("/camera")
async def camera_control(action: CameraAction):
    """Control the camera (start/stop monitoring) using functions from camera.py"""
    logging.info(f"Received camera action request: {action.action}")
    try:
        if action.action == 'start':
            # Pass the synchronous motion processing function to the camera module
            success, message = cam.start_monitoring(process_motion_sync, SAVE_INTERVAL)
            if not success:
                 logging.error(f"Failed to start camera monitoring: {message}")
                 raise HTTPException(status_code=500, detail=message)
            logging.info("Camera monitoring started successfully.")
            return {"success": True, "message": message}
            
        elif action.action == 'stop':
            success, message = cam.stop_monitoring()
            if not success:
                 logging.warning(f"Attempted to stop monitoring but failed: {message}")
                 raise HTTPException(status_code=400, detail=message)
            logging.info("Camera monitoring stopped successfully.")
            return {"success": True, "message": message}
            
        else:
            logging.warning(f"Received invalid camera action: {action.action}")
            raise HTTPException(status_code=400, detail="Invalid action. Use 'start' or 'stop'")
            
    except Exception as e:
        # Catch potential exceptions from camera module or HTTP exceptions
        error_detail = str(e.detail) if isinstance(e, HTTPException) else str(e)
        status_code = e.status_code if isinstance(e, HTTPException) else 500
        logging.error(f"Error controlling camera (Status {status_code}): {error_detail}", exc_info=True)
        raise HTTPException(status_code=status_code, detail=f"Error controlling camera: {error_detail}")

@app.get("/camera")
async def get_camera_frame():
    """Get the current camera frame using function from camera.py"""
    try:
        frame_base64, message = cam.get_current_frame()
        
        if frame_base64 is None:
            # Handle cases like camera not monitoring or frame not ready
            status_code = 404 if "not monitoring" in message or "No frame" in message else 500
            raise HTTPException(status_code=status_code, detail=message)
            
        return {
            "success": True,
            "frame": frame_base64
        }
            
    except Exception as e:
        # Catch potential exceptions from camera module or HTTP exceptions
        error_detail = str(e.detail) if isinstance(e, HTTPException) else str(e)
        status_code = e.status_code if isinstance(e, HTTPException) else 500
        raise HTTPException(status_code=status_code, detail=f"Error getting camera frame: {error_detail}")

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
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", 5000))
    logging.info(f"Starting Uvicorn server on {host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port
    ) 