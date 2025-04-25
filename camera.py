import cv2
import threading
import time
import base64
import numpy as np
import asyncio
import os
import logging
from iot_messaging import iot_publisher

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

def publish_camera_status(status, error=None):
    """Publish camera status event if IoT is connected"""
    if not iot_publisher._is_connected:
        logging.warning(f"IoT not connected, skipping camera status publish ({status})")
        return False

    try:
        event_data = {
            "status": status,
            "timestamp": time.time()
        }
        if error:
            event_data["error"] = str(error)

        success = iot_publisher.publish_event(f"camera/status/{status}", event_data)
        if success:
             logging.info(f"Camera status '{status}' published successfully.")
        else:
             logging.warning(f"Failed to publish camera status '{status}'.")
        return success
    except Exception as e:
        logging.error(f"Error publishing camera status '{status}': {e}")
        return False

def publish_motion_event(motion_bbox, current_time):
    """Publish motion event to IoT if connected"""
    if not iot_publisher._is_connected:
        logging.warning("IoT not connected, skipping motion event")
        return False

    try:
        event_data = {
            "timestamp": current_time,
            "confidence": 100.0,
            "bounding_box": {
                "x": motion_bbox[0],
                "y": motion_bbox[1],
                "width": motion_bbox[2],
                "height": motion_bbox[3]
            }
        }
        return iot_publisher.publish_event("motion_detected", event_data)
    except Exception as e:
        logging.error(f"Error publishing motion event: {e}")
        return False

# Internal monitoring loop function
async def _monitor_camera_async(motion_processor_func, save_interval):
    """
    Internal asynchronous camera monitoring loop.
    Captures frames, detects motion, and calls the motion processor function.
    """
    global camera, is_monitoring, last_frame, frame_lock

    backSub = cv2.createBackgroundSubtractorMOG2(
        history=_BG_SUBTRACTOR_HISTORY,
        varThreshold=_BG_SUBTRACTOR_THRESHOLD,
        detectShadows=True
    )

    last_save_time = 0
    last_motion_time = 0

    logging.info("Camera monitoring loop started.")
    publish_camera_status("started") # Publish started status

    while is_monitoring:
        if camera is None or not camera.isOpened():
            logging.warning("Waiting for camera...")
            publish_camera_status("error", "Camera not available") # Publish error status
            await asyncio.sleep(0.5)
            continue

        ret, frame = camera.read()
        if not ret:
            logging.warning("Failed to grab frame.")
            publish_camera_status("error", "Failed to grab frame") # Publish error status
            await asyncio.sleep(0.1)
            continue

        # --- Motion Detection ---
        resized_frame = cv2.resize(frame, (_RESIZE_WIDTH, _RESIZE_HEIGHT))
        original_for_processing = resized_frame.copy()
        fgMask = backSub.apply(resized_frame)

        # Apply morphological operations for noise reduction
        thresh = cv2.threshold(fgMask, 250, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.erode(thresh, None, iterations=2)
        thresh = cv2.dilate(thresh, None, iterations=2)

        # Find contours
        contours, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        motion_detected = False
        processed_frame_for_display = resized_frame.copy()
        motion_bbox = None

        for c in contours:
            if cv2.contourArea(c) < _MIN_CONTOUR_AREA:
                continue

            motion_detected = True
            (x, y, w, h) = cv2.boundingRect(c)
            motion_bbox = (x, y, w, h)
            cv2.rectangle(processed_frame_for_display, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(processed_frame_for_display, "Motion Detected", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            break

        # Update the frame available for fetching
        with frame_lock:
            last_frame = processed_frame_for_display

        # Process motion if detected and interval passed
        if motion_detected:
            current_time = time.time()
            if current_time - last_save_time >= save_interval:
                logging.info(f"Motion detected! Processing frame ({time.strftime('%H:%M:%S')})...")
                try:
                    # Publish motion event to IoT if enough time has passed
                    if current_time - last_motion_time >= 1.0:
                        if publish_motion_event(motion_bbox, current_time):
                            logging.info("Motion event published successfully")
                            last_motion_time = current_time

                    # Process the frame
                    await asyncio.to_thread(motion_processor_func, original_for_processing)
                    last_save_time = current_time
                except Exception as e:
                    logging.error(f"Error processing motion: {e}")

        await asyncio.sleep(0.05)

    logging.info("Camera monitoring loop stopped.")
    publish_camera_status("stopped") # Publish stopped status

def start_monitoring(motion_processor_func, save_interval=20):
    """Starts the camera monitoring process."""
    global camera, is_monitoring, monitor_thread

    if is_monitoring:
        logging.warning("Camera is already monitoring.")
        return False, "Camera is already monitoring"

    logging.info("Attempting to start camera monitoring...")
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        logging.error("Error: Could not open video device.")
        publish_camera_status("error", "Could not open video device") # Publish error status
        camera = None
        return False, "Could not open video device"

    is_monitoring = True

    def run_async_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_monitor_camera_async(motion_processor_func, save_interval))
        finally:
            loop.close()

    monitor_thread = threading.Thread(target=run_async_loop, daemon=True)
    monitor_thread.start()
    logging.info("Camera monitoring started successfully.")
    # Status 'started' is published inside the loop now
    return True, "Camera monitoring started"

def stop_monitoring():
    """Stops the camera monitoring process."""
    global camera, is_monitoring, monitor_thread, last_frame

    if not is_monitoring:
        logging.warning("Camera is not currently monitoring.")
        return False, "Camera is not monitoring"

    logging.info("Attempting to stop camera monitoring...")
    is_monitoring = False # Signal the loop to stop

    if monitor_thread is not None:
        monitor_thread.join(timeout=2.0)
        if monitor_thread.is_alive():
            logging.warning("Warning: Monitoring thread did not stop gracefully.")
        monitor_thread = None

    if camera is not None:
        camera.release()
        camera = None
        logging.info("Camera released.")

    with frame_lock:
        last_frame = None

    logging.info("Camera monitoring stopped.")
    # Status 'stopped' is published at the end of the loop now
    return True, "Camera monitoring stopped"

def get_current_frame():
    """Gets the last captured frame from the camera."""
    global last_frame, frame_lock, is_monitoring

    if not is_monitoring:
        return None, "Camera is not monitoring"

    with frame_lock:
        if last_frame is None:
            return None, "No frame captured yet or monitoring stopped"

        ret, buffer = cv2.imencode('.jpg', last_frame)
        if not ret:
            return None, "Failed to encode frame"

        frame_base64 = base64.b64encode(buffer).decode('utf-8')
        return frame_base64, "Frame retrieved successfully"

def is_camera_monitoring():
    """Checks if the camera is currently monitoring."""
    global is_monitoring
    return is_monitoring

