import cv2 
import os
import time
import requests
import base64
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Email to receive security alerts
ALERT_EMAIL = os.getenv('EMAIL_USER')
# Local REST API endpoints
REST_API_URL = "http://localhost:5000"
ANALYZE_ENDPOINT = f"{REST_API_URL}/analyze"
UPLOAD_ENDPOINT = f"{REST_API_URL}/upload"
NOTIFY_ENDPOINT = f"{REST_API_URL}/notify"
DB_IMAGE_ENDPOINT = f"{REST_API_URL}/db/image"
DB_ALERT_ENDPOINT = f"{REST_API_URL}/db/alert"
DB_CLEANUP_ENDPOINT = f"{REST_API_URL}/db/cleanup"
DB_S3URL_ENDPOINT = f"{REST_API_URL}/db/s3url"

def analyze_image(image_url):
    """
    Analyze an image using the local REST API endpoint.
    """
    try:
        response = requests.post(ANALYZE_ENDPOINT, json={'image_url': image_url})
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'error': str(e), 'labels': [], 'security_alerts': []}

def upload_to_s3(image_data, filename):
    """
    Upload an image to S3 using the local REST API endpoint.
    """
    try:
        # Convert image to base64
        _, buffer = cv2.imencode('.jpg', image_data)
        image_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # Send to REST API
        response = requests.post(UPLOAD_ENDPOINT, json={
            'image_data': image_base64,
            'filename': filename
        })
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'error': str(e), 'success': False, 's3_url': None}

def send_notification(recipient_email, subject, message, image_data=None):
    """
    Send a notification using the local REST API endpoint.
    """
    try:
        # Convert image to base64 if provided
        image_base64 = None
        if image_data is not None:
            _, buffer = cv2.imencode('.jpg', image_data)
            image_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # Send to REST API
        response = requests.post(NOTIFY_ENDPOINT, json={
            'recipient_email': recipient_email,
            'subject': subject,
            'message': message,
            'image_data': image_base64
        })
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'error': str(e), 'success': False}

def save_image_to_db(image_data, filename):
    """
    Save an image to the database using the REST API.
    """
    try:
        # Convert image to base64
        _, buffer = cv2.imencode('.jpg', image_data)
        image_base64 = base64.b64encode(buffer).decode('utf-8')
        
        # Send to REST API
        response = requests.post(DB_IMAGE_ENDPOINT, json={
            'image_data': image_base64,
            'filename': filename
        })
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'error': str(e), 'success': False}

def add_alert_to_db(image_id, alert_type, confidence):
    """
    Add a security alert to the database using the REST API.
    """
    try:
        response = requests.post(DB_ALERT_ENDPOINT, json={
            'image_id': image_id,
            'alert_type': alert_type,
            'confidence': confidence
        })
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'error': str(e), 'success': False}

def update_s3_url_in_db(image_id, s3_url):
    """
    Update the S3 URL for an image in the database using the REST API.
    """
    try:
        response = requests.post(DB_S3URL_ENDPOINT, json={
            'image_id': image_id,
            's3_url': s3_url
        })
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'error': str(e), 'success': False}

def cleanup_db(days=30):
    """
    Clean up old images from the database using the REST API.
    """
    try:
        response = requests.post(DB_CLEANUP_ENDPOINT, params={'days': days})
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'error': str(e), 'success': False}

def analytics():
    """List all images and security alerts in the database"""
    print("\n===== SECURITY CAMERA ANALYTICS =====")
    
    try:
        # Get recent images from the database
        response = requests.get(DB_IMAGE_ENDPOINT, params={'limit': 1000})
        response.raise_for_status()
        result = response.json()
        
        if 'error' in result:
            print(f"Error retrieving images: {result['error']}")
            return
        
        images = result.get('images', [])
        
        if not images:
            print("No images found in the database.")
            return
        
        # Display summary statistics
        print(f"\nTotal Images: {len(images)}")
        
        # Count images with alerts
        images_with_alerts = sum(1 for img in images if img['alert_count'] > 0)
        print(f"Images with Security Alerts: {images_with_alerts}")
        print(f"Alert Rate: {(images_with_alerts/len(images))*100:.2f}%")
        
        # Get most recent images
        print("\n----- 10 Most Recent Images -----")
        for i, img in enumerate(images[:10]):
            # Timestamp is already a string from the REST API
            timestamp_str = img['timestamp']
            alert_status = f"🚨 {img['alert_count']} alerts" if img['alert_count'] > 0 else "No alerts"
            print(f"{i+1}. [{timestamp_str}] {img['filename']} - {alert_status}")
        
        # Get images with alerts
        if images_with_alerts > 0:
            print("\n----- Recent Security Alerts -----")
            alert_count = 0
            for img in images:
                if img['alert_count'] > 0:
                    # Timestamp is already a string from the REST API
                    timestamp_str = img['timestamp']
                    print(f"Image: {img['filename']} - {timestamp_str}")
                    if img['s3_url']:
                        print(f"S3 URL: {img['s3_url']}")
                    print(f"Total Alerts: {img['alert_count']}")
                    print("-" * 40)
                    
                    alert_count += 1
                    if alert_count >= 10:  # Show only 10 most recent alerts
                        break
        
        print("\n====================================")
        print("For more detailed analysis, export the database to a data analysis tool.")
        
    except requests.exceptions.RequestException as e:
        print(f"Error accessing database: {str(e)}")

def main():
    # Ensure email settings are configured
    if not ALERT_EMAIL:
        print("Warning: EMAIL_USER not set in .env file. Email notifications will not work.")
    
    # Periodically clean up old images from database (older than 30 days)
    cleanup_result = cleanup_db(days=30)
    if cleanup_result.get('success'):
        deleted_count = cleanup_result.get('deleted_count', 0)
        if deleted_count > 0:
            print(f"Cleaned up {deleted_count} old images from database")
    
    # Initialize camera
    print("Arming security system...")
    countdown = 30
    for i in range(countdown, 0, -1):
        print(f"System will be armed in {i} seconds...", end="\r")
        time.sleep(1)
    print("\nSystem armed! Monitoring activated.")
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise Exception("Could not open video device")

    cv2.namedWindow("Motion Detection", cv2.WINDOW_NORMAL)
    # Create the background subtractor
    backSub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=True)

    # Initialize last save time
    last_save_time = 0
    SAVE_INTERVAL = 20  # seconds between saves
    # Initialize last email time to prevent email flooding
    last_email_time = 0
    EMAIL_INTERVAL = 60  # seconds between emails

    print("Press 'q' to quit")
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame")
            break

        frame = cv2.resize(frame, (500, 500))
        # Create a copy of the original frame for saving
        original_frame = frame.copy()
        
        fgMask = backSub.apply(frame)
        # Further threshold to reduce shadow effects (if needed)
        _, thresh = cv2.threshold(fgMask, 250, 255, cv2.THRESH_BINARY)
        thresh = cv2.erode(thresh, None, iterations=2)
        thresh = cv2.dilate(thresh, None, iterations=2)

        # Detect contours and track if any motion is detected
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        motionDetected = False  # Flag to mark motion detection

        for c in contours:
            if cv2.contourArea(c) < 1500:
                continue
            # If we find a contour that meets our area threshold,
            # set the flag to True.
            motionDetected = True

            # Draw a bounding box and label on the frame.
            (x, y, w, h) = cv2.boundingRect(c)
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, "Motion Detected", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        # If motion is detected in this frame, save the original frame
        if motionDetected:
            print("Motion Detected!")
            current_time = time.time()
            
            # Check if enough time has passed since last save
            if current_time - last_save_time >= SAVE_INTERVAL:
                # Generate timestamp for unique filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"motion_{timestamp}.jpg"
                
                try:
                    # Save the image to the database
                    print(f"Saving image {filename} to database...")
                    save_result = save_image_to_db(original_frame, filename)
                    if not save_result.get('success'):
                        print(f"Failed to save image to database: {save_result.get('error')}")
                        continue
                    
                    image_id = save_result.get('image_id')
                    print(f"Image saved with ID: {image_id}")
                    last_save_time = current_time
                    
                    # Upload to S3 using REST API
                    print(f"Uploading image to S3...")
                    upload_result = upload_to_s3(original_frame, filename)
                    
                    if upload_result.get('success'):
                        s3_url = upload_result['s3_url']
                        print(f"Image uploaded to S3. URL: {s3_url}")
                        
                        # Update the S3 URL in the database
                        update_result = update_s3_url_in_db(image_id, s3_url)
                        if not update_result.get('success'):
                            print(f"Failed to update S3 URL: {update_result.get('error')}")
                        
                        # Analyze the image using the local REST API
                        print("Analyzing image with local REST API...")
                        analysis = analyze_image(s3_url)
                        
                        if analysis.get('error'):
                            print(f"Analysis error: {analysis['error']}")
                        else:
                            # Print all detected labels
                            print("\nDetected labels:")
                            for label in analysis['labels']:
                                print(f"  {label['name']} (Confidence: {label['confidence']:.2f}%)")
                            
                            # Process and save security alerts
                            alerts_found = False
                            
                            if analysis['security_alerts']:
                                alerts_found = True
                                print("\n🚨 SECURITY ALERTS 🚨")
                                
                                # Save each alert to the database
                                for alert in analysis['security_alerts']:
                                    print(f"  {alert['type']} (Confidence: {alert['confidence']:.2f}%)")
                                    # Add alert to database
                                    alert_result = add_alert_to_db(
                                        image_id=image_id,
                                        alert_type=alert['type'],
                                        confidence=alert['confidence']
                                    )
                                    if not alert_result.get('success'):
                                        print(f"Failed to save alert: {alert_result.get('error')}")
                                
                                # Check if enough time has passed since last email
                                if ALERT_EMAIL and (current_time - last_email_time >= EMAIL_INTERVAL):
                                    # Send email notification with the image attached
                                    subject = "🚨 Security Alert: Suspicious Activity Detected"
                                    
                                    # Create email message with all detected alerts
                                    alert_details = "\n".join([
                                        f"- {alert['type']} (Confidence: {alert['confidence']:.2f}%)" 
                                        for alert in analysis['security_alerts']
                                    ])
                                    
                                    message = f"""Security Alert from your camera system!

Suspicious activity has been detected:

{alert_details}

The image has been saved to your S3 bucket.
Image URL: {s3_url}

This is an automated message from your security camera system.
"""
                                    try:
                                        # Send the notification using the REST API
                                        notification_result = send_notification(
                                            ALERT_EMAIL,
                                            subject,
                                            message,
                                            original_frame
                                        )
                                        
                                        if notification_result.get('success'):
                                            print(f"Security alert email sent to {ALERT_EMAIL}")
                                            last_email_time = current_time
                                        else:
                                            print(f"Failed to send email: {notification_result.get('error')}")
                                    except Exception as e:
                                        print(f"Error sending email: {str(e)}")
                                elif not ALERT_EMAIL:
                                    print("Email not sent: EMAIL_USER not configured in .env file")
                                else:
                                    time_since_last_email = int(current_time - last_email_time)
                                    print(f"Email not sent: waiting {EMAIL_INTERVAL - time_since_last_email} more seconds before sending next email")
                            else:
                                print("\nNo security concerns detected.")
                    else:
                        print(f"Failed to upload to S3: {upload_result.get('error')}")
                            
                except Exception as e:
                    print(f"Error processing image: {str(e)}")
            else:
                time_since_last = int(current_time - last_save_time)
                print(f"Motion detected, but waiting {SAVE_INTERVAL - time_since_last} more seconds before saving next image")
            
        cv2.imshow("Motion Detection", frame)
        cv2.imshow("Threshold", thresh)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Exiting...")
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    while True:
        print("==========STATUS:ONLINE===========")
        print("1. ACTIVATE SECURITY SYSTEM")
        print("---")
        print("2. ANALYZE ACTIVITY")
        print("---")
        print("3. DEACTIVATE SECURITY SYSTEM")
        print("====================================")
        user_input = input("Enter your choice: ")
        
        if user_input == "1":
            main()
        elif user_input == "2":
            analytics()
        elif user_input == "3":
            print("==========STATUS:OFFLINE===========")
            print("Deactivating security system...")
            print("===================================")
            break

