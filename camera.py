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

def publish_person_detected_event(confidence, current_time):
    """Publish person detection event to IoT if connected"""
    if not iot_publisher._is_connected:
        logging.warning("IoT not connected, skipping person detection event")
        return False

    try:
        event_data = {
            "timestamp": current_time,
            "confidence": confidence
        }
        return iot_publisher.publish_event("person_detected", event_data)
    except Exception as e:
        logging.error(f"Error publishing person detection event: {e}")
        return False

# Internal monitoring loop function
async def _monitor_camera_async(processor_func, save_interval):
    """
    Internal asynchronous camera monitoring loop.
    Captures frames and calls the processor function.
    """
    global camera, is_monitoring, last_frame, frame_lock

    last_save_time = 0
    last_person_time = 0

    logging.info("Camera monitoring loop started.")
    publish_camera_status("started")

    while is_monitoring:
        if camera is None or not camera.isOpened():
            logging.warning("Waiting for camera...")
            publish_camera_status("error", "Camera not available")
            await asyncio.sleep(0.5)
            continue

        ret, frame = camera.read()
        if not ret:
            logging.warning("Failed to grab frame.")
            publish_camera_status("error", "Failed to grab frame")
            await asyncio.sleep(0.1)
            continue

        # Always update the display frame
        with frame_lock:
            last_frame = frame.copy()

        # Process frame if interval passed
        current_time = time.time()
        if current_time - last_save_time >= save_interval:
            logging.info(f"Processing frame ({time.strftime('%H:%M:%S')})...")
            try:
                # Process the frame asynchronously
                await processor_func(frame)
                last_save_time = current_time
            except Exception as e:
                logging.error(f"Error processing frame: {e}")

        await asyncio.sleep(0.05)  # Small delay to prevent CPU overload

    logging.info("Camera monitoring loop stopped.")
    publish_camera_status("stopped")

def start_monitoring(processor_func, save_interval=20):
    """Starts the camera monitoring process."""
    global camera, is_monitoring, monitor_thread

    if is_monitoring:
        logging.warning("Camera is already monitoring.")
        return False, "Camera is already monitoring"

    logging.info("Attempting to start camera monitoring...")
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        logging.error("Error: Could not open video device.")
        publish_camera_status("error", "Could not open video device")
        camera = None
        return False, "Could not open video device"

    is_monitoring = True

    def run_async_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_monitor_camera_async(processor_func, save_interval))
        finally:
            loop.close()

    monitor_thread = threading.Thread(target=run_async_loop, daemon=True)
    monitor_thread.start()
    logging.info("Camera monitoring started successfully.")
    return True, "Camera monitoring started"

def stop_monitoring():
    """Stops the camera monitoring process."""
    global camera, is_monitoring, monitor_thread, last_frame

    if not is_monitoring:
        logging.warning("Camera is not currently monitoring.")
        return False, "Camera is not monitoring"

    logging.info("Attempting to stop camera monitoring...")
    is_monitoring = False

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

