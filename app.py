import tkinter as tk
from tkinter import ttk, messagebox
import cv2
import os
import time
import requests
import base64
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageTk
import threading
import numpy as np

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
S3_BUCKET_DELETE_ENDPOINT = f"{REST_API_URL}/s3/bucket/delete"
CAMERA_CONTROL_ENDPOINT = f"{REST_API_URL}/camera"

class SecurityCameraApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Security Camera System")
        self.root.geometry("1200x800")
        
        # Variables
        self.is_running = False
        self.last_save_time = 0
        self.last_email_time = 0
        self.SAVE_INTERVAL = 20
        self.EMAIL_INTERVAL = 60
        
        # Create main frame
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Create video display
        self.video_frame = ttk.LabelFrame(self.main_frame, text="Live Feed", padding="5")
        self.video_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)
        
        self.video_label = ttk.Label(self.video_frame)
        self.video_label.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Create control buttons
        self.control_frame = ttk.Frame(self.main_frame)
        self.control_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=5)
        
        self.start_button = ttk.Button(self.control_frame, text="Start Monitoring", command=self.start_monitoring)
        self.start_button.grid(row=0, column=0, padx=5)
        
        self.stop_button = ttk.Button(self.control_frame, text="Stop Monitoring", command=self.stop_monitoring, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1, padx=5)
        
        self.analytics_button = ttk.Button(self.control_frame, text="View Analytics", command=self.show_analytics)
        self.analytics_button.grid(row=0, column=2, padx=5)

        self.self_destruct_button = ttk.Button(self.control_frame, text="Self Destruct", command=self.self_destruct)
        self.self_destruct_button.grid(row=0, column=3, padx=5)
        
        # Create status frame
        self.status_frame = ttk.LabelFrame(self.main_frame, text="Status", padding="5")
        self.status_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=5)
        
        self.status_label = ttk.Label(self.status_frame, text="System Ready")
        self.status_label.grid(row=0, column=0, sticky=tk.W)
        
        # Create alerts frame
        self.alerts_frame = ttk.LabelFrame(self.main_frame, text="Recent Alerts", padding="5")
        self.alerts_frame.grid(row=0, column=2, rowspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)
        
        self.alerts_text = tk.Text(self.alerts_frame, height=20, width=40)
        self.alerts_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.alerts_text.config(state=tk.DISABLED)
        
        # Configure grid weights
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.columnconfigure(2, weight=1)
        self.main_frame.rowconfigure(0, weight=1)
        
        # Start the video update loop
        self.update_video_loop()
        
        # Clean up old images
        self.cleanup_db(days=30)
    
    def update_video_loop(self):
        if self.is_running:
            try:
                response = requests.get(CAMERA_CONTROL_ENDPOINT)
                response.raise_for_status()
                result = response.json()
                
                if result.get('success') and result.get('frame'):
                    # Convert base64 frame to image
                    frame_data = base64.b64decode(result['frame'])
                    nparr = np.frombuffer(frame_data, np.uint8)
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    
                    if frame is not None:
                        # Convert frame for display
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        frame_pil = Image.fromarray(frame_rgb)
                        frame_tk = ImageTk.PhotoImage(frame_pil)
                        
                        # Update display
                        self.video_label.config(image=frame_tk)
                        self.video_label.image = frame_tk
            except Exception as e:
                self.add_alert(f"Error updating video: {str(e)}")
        
        # Schedule next update
        self.root.after(100, self.update_video_loop)

    def start_monitoring(self):
        if not self.is_running:
            try:
                response = requests.post(CAMERA_CONTROL_ENDPOINT, json={'action': 'start'})
                response.raise_for_status()
                result = response.json()
                
                if result.get('success'):
                    self.is_running = True
                    self.start_button.config(state=tk.DISABLED)
                    self.stop_button.config(state=tk.NORMAL)
                    self.status_label.config(text="Monitoring Active")
                    self.add_alert("Camera monitoring started")
                else:
                    self.add_alert(f"Failed to start monitoring: {result.get('error')}")
            except Exception as e:
                self.add_alert(f"Error starting monitoring: {str(e)}")

    def stop_monitoring(self):
        if self.is_running:
            try:
                response = requests.post(CAMERA_CONTROL_ENDPOINT, json={'action': 'stop'})
                response.raise_for_status()
                result = response.json()
                
                if result.get('success'):
                    self.is_running = False
                    self.start_button.config(state=tk.NORMAL)
                    self.stop_button.config(state=tk.DISABLED)
                    self.status_label.config(text="System Ready")
                    self.add_alert("Camera monitoring stopped")
                else:
                    self.add_alert(f"Failed to stop monitoring: {result.get('error')}")
            except Exception as e:
                self.add_alert(f"Error stopping monitoring: {str(e)}")

    def self_destruct(self):
        """
        Emergency protocol to delete all data and shut down the system.
        This is a destructive operation that cannot be undone.
        """
        # Confirm with user before proceeding
        if not messagebox.askyesno("⚠️ WARNING: Self Destruct", 
            "This will delete ALL data including:\n"
            "- All images in S3 bucket\n"
            "- All database records\n"
            "- All security alerts\n\n"
            "This action cannot be undone!\n\n"
            "Are you sure you want to proceed?"):
            return

        try:
            # Delete S3 bucket and all its contents
            response = requests.post(S3_BUCKET_DELETE_ENDPOINT, json={
                'bucket_name': 'computer-vision-analysis',
                'confirmation': 'CONFIRM_DELETE'
            })
            response.raise_for_status()
            result = response.json()
            
            if result.get('success'):
                self.add_alert("✅ S3 bucket and all contents deleted successfully")
            else:
                self.add_alert(f"❌ Failed to delete S3 bucket: {result.get('error')}")
                return

            # Clean up database
            cleanup_response = requests.post(DB_CLEANUP_ENDPOINT, params={'days': 0})
            cleanup_response.raise_for_status()
            cleanup_result = cleanup_response.json()
            
            if cleanup_result.get('success'):
                deleted_count = cleanup_result.get('deleted_count', 0)
                self.add_alert(f"✅ Database cleaned up: {deleted_count} records deleted")
            else:
                self.add_alert(f"❌ Failed to clean up database: {cleanup_result.get('error')}")

            # Stop monitoring if active
            self.stop_monitoring()
            
            # Show final confirmation
            messagebox.showinfo("Self Destruct Complete", 
                "All data has been deleted and the system has been shut down.\n"
                "Please restart the application to use it again.")
            
            # Close the application
            self.root.destroy()

        except requests.exceptions.RequestException as e:
            self.add_alert(f"❌ Error during self-destruct: {str(e)}")
            messagebox.showerror("Error", f"Failed to complete self-destruct: {str(e)}")

    def show_analytics(self):
        try:
            response = requests.get(DB_IMAGE_ENDPOINT, params={'limit': 1000})
            response.raise_for_status()
            result = response.json()
            
            if 'error' in result:
                messagebox.showerror("Error", f"Error retrieving images: {result['error']}")
                return
            
            images = result.get('images', [])
            
            if not images:
                messagebox.showinfo("Analytics", "No images found in the database.")
                return
            
            # Create analytics window
            analytics_window = tk.Toplevel(self.root)
            analytics_window.title("Security Camera Analytics")
            analytics_window.geometry("800x600")
            
            # Create text widget for analytics
            analytics_text = tk.Text(analytics_window, wrap=tk.WORD)
            analytics_text.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)
            
            # Display summary statistics
            analytics_text.insert(tk.END, f"Total Images: {len(images)}\n")
            
            images_with_alerts = sum(1 for img in images if img['alert_count'] > 0)
            analytics_text.insert(tk.END, f"Images with Security Alerts: {images_with_alerts}\n")
            analytics_text.insert(tk.END, f"Alert Rate: {(images_with_alerts/len(images))*100:.2f}%\n\n")
            
            # Display recent images
            analytics_text.insert(tk.END, "----- 10 Most Recent Images -----\n")
            for i, img in enumerate(images[:10]):
                alert_status = f"🚨 {img['alert_count']} alerts" if img['alert_count'] > 0 else "No alerts"
                analytics_text.insert(tk.END, f"{i+1}. [{img['timestamp']}] {img['filename']} - {alert_status}\n")
            
            # Display recent alerts
            if images_with_alerts > 0:
                analytics_text.insert(tk.END, "\n----- Recent Security Alerts -----\n")
                alert_count = 0
                for img in images:
                    if img['alert_count'] > 0:
                        analytics_text.insert(tk.END, f"Image: {img['filename']} - {img['timestamp']}\n")
                        if img['s3_url']:
                            analytics_text.insert(tk.END, f"S3 URL: {img['s3_url']}\n")
                        analytics_text.insert(tk.END, f"Total Alerts: {img['alert_count']}\n")
                        analytics_text.insert(tk.END, "-" * 40 + "\n")
                        
                        alert_count += 1
                        if alert_count >= 10:
                            break
            
            analytics_text.config(state=tk.DISABLED)
            
        except requests.exceptions.RequestException as e:
            messagebox.showerror("Error", f"Error accessing database: {str(e)}")

    # REST API wrapper functions
    def analyze_image(self, image_url):
        try:
            response = requests.post(ANALYZE_ENDPOINT, json={'image_url': image_url})
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {'error': str(e), 'labels': [], 'security_alerts': []}

    def upload_to_s3(self, image_data, filename):
        try:
            _, buffer = cv2.imencode('.jpg', image_data)
            image_base64 = base64.b64encode(buffer).decode('utf-8')
            
            response = requests.post(UPLOAD_ENDPOINT, json={
                'image_data': image_base64,
                'filename': filename
            })
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {'error': str(e), 'success': False, 's3_url': None}

    def send_notification(self, recipient_email, subject, message, image_data=None):
        try:
            image_base64 = None
            if image_data is not None:
                _, buffer = cv2.imencode('.jpg', image_data)
                image_base64 = base64.b64encode(buffer).decode('utf-8')
            
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

    def save_image_to_db(self, image_data, filename):
        try:
            _, buffer = cv2.imencode('.jpg', image_data)
            image_base64 = base64.b64encode(buffer).decode('utf-8')
            
            response = requests.post(DB_IMAGE_ENDPOINT, json={
                'image_data': image_base64,
                'filename': filename
            })
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {'error': str(e), 'success': False}

    def add_alert_to_db(self, image_id, alert_type, confidence):
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

    def update_s3_url_in_db(self, image_id, s3_url):
        try:
            response = requests.post(DB_S3URL_ENDPOINT, json={
                'image_id': image_id,
                's3_url': s3_url
            })
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {'error': str(e), 'success': False}

    def cleanup_db(self, days=30):
        try:
            response = requests.post(DB_CLEANUP_ENDPOINT, params={'days': days})
            response.raise_for_status()
            result = response.json()
            if result.get('success'):
                deleted_count = result.get('deleted_count', 0)
                if deleted_count > 0:
                    self.add_alert(f"Cleaned up {deleted_count} old images from database")
        except requests.exceptions.RequestException as e:
            self.add_alert(f"Error cleaning up database: {str(e)}")

    def add_alert(self, message):
        self.alerts_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.alerts_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.alerts_text.see(tk.END)
        self.alerts_text.config(state=tk.DISABLED)

if __name__ == '__main__':
    root = tk.Tk()
    app = SecurityCameraApp(root)
    root.mainloop()
