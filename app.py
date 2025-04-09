import cv2 
import os
import time
from datetime import datetime
from aws_s3 import upload_file
from rekognition import analyze_image
from notifications import send_security_alert
from database import save_image, add_security_alert, save_temp_image_file, update_s3_url, cleanup_old_images, get_recent_images
from dotenv import load_dotenv

load_dotenv()

# Email to receive security alerts
ALERT_EMAIL = os.getenv('EMAIL_USER')

def analytics():
    """List all images and security alerts in the database"""
    print("\n===== SECURITY CAMERA ANALYTICS =====")
    
    # Get recent images (limit parameter is set to a high number to get all images)
    images = get_recent_images(limit=1000)
    
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
        timestamp_str = img['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
        alert_status = f"🚨 {img['alert_count']} alerts" if img['alert_count'] > 0 else "No alerts"
        print(f"{i+1}. [{timestamp_str}] {img['filename']} - {alert_status}")
    
    # Get images with alerts
    if images_with_alerts > 0:
        print("\n----- Recent Security Alerts -----")
        alert_count = 0
        for img in images:
            if img['alert_count'] > 0:
                timestamp_str = img['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
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

def main():
    # Ensure email settings are configured
    if not ALERT_EMAIL:
        print("Warning: EMAIL_USER not set in .env file. Email notifications will not work.")
    
    # Periodically clean up old images from database (older than 30 days)
    deleted_count = cleanup_old_images(days=30)
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

    # Create temp directory if needed (for S3 uploads and email attachments)
    if not os.path.exists('temp_images'):
        os.makedirs('temp_images')

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
                    image_id = save_image(original_frame, filename)
                    print(f"Image saved with ID: {image_id}")
                    last_save_time = current_time
                    
                    # Create temporary file for S3 upload
                    temp_image_path = save_temp_image_file(image_id)
                    
                    # Upload to S3 and get URL
                    success, error, s3_url = upload_file(temp_image_path, 'computer-vision-analysis', filename)
                    if success:
                        print(f"Image uploaded to S3. URL: {s3_url}")
                        
                        # Update the S3 URL in the database
                        update_s3_url(image_id, s3_url)
                        
                        # Analyze the image with Rekognition
                        print("Analyzing image with Rekognition...")
                        analysis = analyze_image(s3_url)
                        
                        if analysis['error']:
                            print(f"Rekognition analysis error: {analysis['error']}")
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
                                    add_security_alert(
                                        image_id=image_id,
                                        alert_type=alert['type'],
                                        confidence=alert['confidence']
                                    )
                                
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
                                        # Send the email using the temporary file
                                        email_success, email_error = send_security_alert(
                                            ALERT_EMAIL, 
                                            subject, 
                                            message, 
                                            temp_image_path
                                        )
                                        
                                        if email_success:
                                            print(f"Security alert email sent to {ALERT_EMAIL}")
                                            last_email_time = current_time
                                        else:
                                            print(f"Failed to send email: {email_error}")
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
                        print(f"Failed to upload to S3: {error}")
                        
                    # Clean up the temporary file
                    if temp_image_path and os.path.exists(temp_image_path):
                        try:
                            os.remove(temp_image_path)
                        except:
                            pass  # Ignore errors when deleting temp file
                            
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

