import psutil
import time
import os
import logging
from iot_messaging import iot_publisher
import threading

class SystemHealthMonitor:
    def __init__(self, interval=60):
        self.interval = interval  # seconds between checks
        self.start_time = time.time()
        self._monitoring = False
        self._monitor_thread = None

    def get_cpu_usage(self):
        """Get current CPU usage percentage"""
        return psutil.cpu_percent(interval=1)

    def get_memory_usage(self):
        """Get current memory usage"""
        memory = psutil.virtual_memory()
        return {
            "total": memory.total,
            "available": memory.available,
            "used": memory.used,
            "percent": memory.percent
        }

    def get_disk_space(self):
        """Get disk space usage"""
        disk = psutil.disk_usage('/')
        return {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent
        }

    def get_uptime(self):
        """Get system uptime in seconds"""
        return time.time() - self.start_time

    def publish_health_metrics(self):
        """Publish all health metrics to IoT"""
        if not iot_publisher._is_connected:
            logging.warning("IoT connection not available, skipping health metrics")
            return

        try:
            # CPU Usage
            cpu_usage = self.get_cpu_usage()
            iot_publisher.publish_event("system/health/cpu_usage", {
                "usage_percent": cpu_usage,
                "timestamp": time.time()
            })

            # Memory Usage
            memory_usage = self.get_memory_usage()
            iot_publisher.publish_event("system/health/memory_usage", {
                "total_bytes": memory_usage["total"],
                "used_bytes": memory_usage["used"],
                "available_bytes": memory_usage["available"],
                "usage_percent": memory_usage["percent"],
                "timestamp": time.time()
            })

            # Disk Space
            disk_space = self.get_disk_space()
            iot_publisher.publish_event("system/health/disk_space", {
                "total_bytes": disk_space["total"],
                "used_bytes": disk_space["used"],
                "free_bytes": disk_space["free"],
                "usage_percent": disk_space["percent"],
                "timestamp": time.time()
            })

            # Uptime
            uptime = self.get_uptime()
            iot_publisher.publish_event("system/health/uptime", {
                "uptime_seconds": uptime,
                "timestamp": time.time()
            })

        except Exception as e:
            logging.error(f"Error publishing health metrics: {e}")

    def start_monitoring(self):
        """Start the health monitoring loop"""
        if self._monitoring:
            return

        self._monitoring = True
        logging.info("Starting system health monitoring...")

        def monitor_loop():
            while self._monitoring:
                try:
                    if iot_publisher._is_connected:
                        self.publish_health_metrics()
                    else:
                        logging.warning("IoT connection not available, waiting...")
                except Exception as e:
                    logging.error(f"Error in health monitoring loop: {e}")
                time.sleep(self.interval)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self):
        """Stop the health monitoring loop"""
        if not self._monitoring:
            return

        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        logging.info("Stopped system health monitoring")

# Create a singleton instance
health_monitor = SystemHealthMonitor() 