import cv2
import threading
import time
import base64
import numpy as np
import asyncio
import os

# Global camera state variables
camera = None
is_monitoring = False
monitor_thread = None
last_frame = None
frame_lock = threading.Lock()

# Motion detection parameters (can be adjusted)
_MIN_CONTOUR_AREA = 1500
_RESIZE_WIDTH = 500
_RESIZE_HEIGHT = 500
_BG_SUBTRACTOR_HISTORY = 500
_BG_SUBTRACTOR_THRESHOLD = 50

# Internal monitoring loop function
async def _monitor_camera_async(motion_processor_func, save_interval):
    """
    Internal asynchronous camera monitoring loop.
    Captures frames, detects motion, and calls the motion processor function.
    """
    global camera, is_monitoring, last_frame, frame_lock
    
    # Initialize background subtractor here within the async context if possible
    # Or ensure it's properly handled across threads if created outside
    backSub = cv2.createBackgroundSubtractorMOG2(
        history=_BG_SUBTRACTOR_HISTORY, 
        varThreshold=_BG_SUBTRACTOR_THRESHOLD, 
        detectShadows=True
    )
    
    last_save_time = 0

    print("Camera monitoring loop started.")
    while is_monitoring:
        if camera is None or not camera.isOpened():
            print("Waiting for camera...")
            await asyncio.sleep(0.5) # Wait a bit longer if camera is not ready
            continue

        ret, frame = camera.read()
        if not ret:
            print("Failed to grab frame.")
            await asyncio.sleep(0.1) # Short sleep on frame grab failure
            continue

        # --- Motion Detection ---
        resized_frame = cv2.resize(frame, (_RESIZE_WIDTH, _RESIZE_HEIGHT))
        original_for_processing = resized_frame.copy() # Use resized copy for processing
        fgMask = backSub.apply(resized_frame)
        
        # Apply morphological operations for noise reduction
        thresh = cv2.threshold(fgMask, 250, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.erode(thresh, None, iterations=2)
        thresh = cv2.dilate(thresh, None, iterations=2)

        # Find contours
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        motion_detected = False
        processed_frame_for_display = resized_frame.copy() # Frame to draw on and store

        for c in contours:
            if cv2.contourArea(c) < _MIN_CONTOUR_AREA:
                continue
            
            motion_detected = True
            (x, y, w, h) = cv2.boundingRect(c)
            cv2.rectangle(processed_frame_for_display, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(processed_frame_for_display, "Motion Detected", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            break # Optional: Stop after first detected motion for performance

        # Update the frame available for fetching
        with frame_lock:
            last_frame = processed_frame_for_display
        
        # Process motion if detected and interval passed
        if motion_detected:
            current_time = time.time()
            if current_time - last_save_time >= save_interval:
                print(f"Motion detected! Processing frame ({time.strftime('%H:%M:%S')})...")
                try:
                    # Run the synchronous processing function in a separate thread 
                    # to avoid blocking the async loop
                    await asyncio.to_thread(motion_processor_func, original_for_processing)
                    last_save_time = current_time
                except Exception as e:
                    print(f"Error calling motion processor: {e}")

        # Small delay to prevent high CPU usage
        await asyncio.sleep(0.05) 

    print("Camera monitoring loop stopped.")


def start_monitoring(motion_processor_func, save_interval=20):
    """Starts the camera monitoring process."""
    global camera, is_monitoring, monitor_thread
    
    if is_monitoring:
        print("Camera is already monitoring.")
        return False, "Camera is already monitoring"

    print("Attempting to start camera monitoring...")
    camera = cv2.VideoCapture(0) # Use default camera
    if not camera.isOpened():
        print("Error: Could not open video device.")
        camera = None # Ensure camera is None if failed
        return False, "Could not open video device"

    is_monitoring = True
    
    # Define a target function that sets up and runs the async loop
    def run_async_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Pass the motion processor function and save interval to the async loop
            loop.run_until_complete(_monitor_camera_async(motion_processor_func, save_interval))
        finally:
            loop.close()

    monitor_thread = threading.Thread(target=run_async_loop, daemon=True)
    monitor_thread.start()
    print("Camera monitoring started successfully.")
    return True, "Camera monitoring started"

def stop_monitoring():
    """Stops the camera monitoring process."""
    global camera, is_monitoring, monitor_thread, last_frame

    if not is_monitoring:
        print("Camera is not currently monitoring.")
        return False, "Camera is not monitoring"

    print("Attempting to stop camera monitoring...")
    is_monitoring = False

    if monitor_thread is not None:
        monitor_thread.join(timeout=2.0) # Wait for the thread to finish
        if monitor_thread.is_alive():
             print("Warning: Monitoring thread did not stop gracefully.")
        monitor_thread = None

    if camera is not None:
        camera.release()
        camera = None
        print("Camera released.")
        
    with frame_lock:
        last_frame = None # Clear last frame on stop

    print("Camera monitoring stopped.")
    return True, "Camera monitoring stopped"

def get_current_frame():
    """Gets the last captured frame from the camera."""
    global last_frame, frame_lock, is_monitoring

    if not is_monitoring:
        return None, "Camera is not monitoring"
        
    with frame_lock:
        if last_frame is None:
            # Could be starting up or no frame captured yet
            return None, "No frame captured yet or monitoring stopped"

        # Encode the frame to JPEG format
        ret, buffer = cv2.imencode('.jpg', last_frame)
        if not ret:
            return None, "Failed to encode frame"
            
        # Encode buffer to base64
        frame_base64 = base64.b64encode(buffer).decode('utf-8')
        return frame_base64, "Frame retrieved successfully"

def is_camera_monitoring():
    """Checks if the camera is currently monitoring."""
    global is_monitoring
    return is_monitoring
