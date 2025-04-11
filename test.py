import flet as ft
import requests
import os
import time
import base64
from datetime import datetime
import threading
import asyncio
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
S3_BUCKET_DELETE_ENDPOINT = f"{REST_API_URL}/s3/bucket/delete"
CAMERA_CONTROL_ENDPOINT = f"{REST_API_URL}/camera"

async def main(page: ft.Page):
    page.title = "Security Camera System"
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.START
    page.window_width = 1200
    page.window_height = 800

    is_running = False
    video_update_task = None

    # --- UI Controls ---
    video_image = ft.Image(
        # Placeholder image or leave empty initially
        # src="placeholder.png", 
        width=640, 
        height=480,
        fit=ft.ImageFit.CONTAIN,
        border_radius=ft.border_radius.all(5)
    )

    status_label = ft.Text("System Ready")
    alerts_list = ft.ListView(expand=1, spacing=10, padding=10, auto_scroll=True)

    async def update_video_feed():
        """Fetches the latest frame from the API and updates the image control."""
        nonlocal is_running
        while is_running:
            try:
                response = await asyncio.to_thread(requests.get, CAMERA_CONTROL_ENDPOINT, timeout=5)
                response.raise_for_status()
                result = response.json()

                if result.get('success') and result.get('frame'):
                    video_image.src_base64 = result['frame']
                    if video_image.page:
                        video_image.page.update()
                else:
                    error_msg = result.get('detail', 'Frame not available')
                    await add_alert(page, f"Frame retrieval failed: {error_msg}")

            except requests.exceptions.Timeout:
                if is_running:
                    await add_alert(page, "Video feed request timed out.")
                await asyncio.sleep(2)
            except requests.exceptions.RequestException as e:
                if is_running:
                     await add_alert(page, f"Error updating video feed: {str(e)}")
                await asyncio.sleep(2)
            
            # Reduce flickering and CPU usage by waiting a bit
            await asyncio.sleep(0.1) # Update roughly 10 times per second

    async def start_monitoring(e):
        nonlocal is_running, video_update_task
        if not is_running:
            start_button.disabled = True
            await add_alert(page, "Attempting to start monitoring...")
            try:
                response = await asyncio.to_thread(
                    requests.post, CAMERA_CONTROL_ENDPOINT, json={'action': 'start'}, timeout=10
                )
                response.raise_for_status()
                result = response.json()

                if result.get('success'):
                    is_running = True
                    start_button.disabled = False
                    stop_button.disabled = False
                    status_label.value = "Monitoring Active"
                    await add_alert(page, "Camera monitoring started successfully.")
                    video_update_task = asyncio.create_task(update_video_feed())
                    video_image.page.update()
                else:
                    error_msg = result.get('detail', 'Unknown error')
                    await add_alert(page, f"Failed to start monitoring: {error_msg}")
                    start_button.disabled = False # Re-enable button on failure
                    video_image.page.update() # Update button state
            except requests.exceptions.Timeout:
                await add_alert(page, "Error starting monitoring: Request timed out.")
                start_button.disabled = False # Re-enable button on failure
                video_image.page.update() # Update button state
            except requests.exceptions.RequestException as e:
                await add_alert(page, f"Error starting monitoring: {str(e)}")
                start_button.disabled = False # Re-enable button on failure
                video_image.page.update() # Update button state
            except Exception as e:
                await add_alert(page, f"Unexpected error starting monitoring: {str(e)}")
                start_button.disabled = False # Re-enable button on failure
                video_image.page.update() # Update button state

    async def stop_monitoring(e):
        nonlocal is_running, video_update_task
        if is_running:
            stop_button.disabled = True
            await add_alert(page, "Attempting to stop monitoring...")
            is_running = False
            if video_update_task:
                video_update_task.cancel()
                try:
                    await video_update_task # Wait for cancellation
                except asyncio.CancelledError:
                    pass # Expected
                video_update_task = None
                
            start_button.disabled = False
            stop_button.disabled = True
            status_label.value = "System Ready"
            video_image.src_base64 = None
            await add_alert(page, "Camera monitoring stopped.")
            video_image.page.update()

            # Now attempt to inform the backend API (fire and forget for now)
            async def send_stop_request():
                try:
                    await asyncio.to_thread(requests.post, CAMERA_CONTROL_ENDPOINT, json={'action': 'stop'}, timeout=10)
                    # Log success/failure if needed, but don't block UI
                except Exception as stop_req_e:
                    print(f"Failed to send stop request to API: {stop_req_e}")
            asyncio.create_task(send_stop_request())

        else:
            start_button.disabled = False
            stop_button.disabled = True
            status_label.value = "System Ready"
            video_image.src_base64 = None
            await add_alert(page, "Camera monitoring not active. Cannot stop.")
            video_image.page.update()

    async def show_analytics(e):
        await add_alert(page, "Analytics feature not yet implemented.")
        await page.update()
        pass

    async def add_alert(page_ref: ft.Page, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        alerts_list.controls.append(ft.Text(f"[{timestamp}] {message}"))
        # Limit number of alerts shown
        if len(alerts_list.controls) > 200:
            alerts_list.controls.pop(0)
        # Use synchronous update, even in async context
        if alerts_list.page:
            page_ref.update()

    # --- Self Destruct Dialog Logic ---

    # Define the dialog instance outside the functions that use it
    self_destruct_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("⚠️ WARNING: Self Destruct"),
        content=ft.Text(
            "This will delete ALL data including:\n"
            "- All images in S3 bucket\n"
            "- All database records\n"
            "- All security alerts\n\n"
            "This action cannot be undone!\n\n"
            "Are you sure you want to proceed?"
        ),
        actions_alignment=ft.MainAxisAlignment.END,
        # Actions will be assigned in open_self_destruct_dialog
    )

    async def handle_confirm_destruct(e):
        """Handles the confirmation action of the self-destruct dialog."""
        await add_alert(page, "Self-destruct sequence initiated...")
        # Close dialog first
        self_destruct_dialog.open = False
        page.update()

        # --- Add API call logic here ---
        try:
            # 1. Delete S3 bucket
            await add_alert(page, "Deleting S3 bucket...")
            response_s3 = await asyncio.to_thread(requests.post, S3_BUCKET_DELETE_ENDPOINT, json={
                'bucket_name': 'computer-vision-analysis', # Make this configurable?
                'confirmation': 'CONFIRM_DELETE'
            }, timeout=60) # Longer timeout for bucket deletion
            response_s3.raise_for_status()
            result_s3 = response_s3.json()
            if result_s3.get('success'):
                await add_alert(page, "✅ S3 bucket deleted.")
            else:
                await add_alert(page, f"❌ Failed to delete S3 bucket: {result_s3.get('detail', 'Unknown error')}")
                # Decide whether to proceed if S3 fails

            # 2. Clean up database (delete all)
            await add_alert(page, "Cleaning up database...")
            response_db = await asyncio.to_thread(requests.post, DB_CLEANUP_ENDPOINT, params={'days': 0}, timeout=30)
            response_db.raise_for_status()
            result_db = response_db.json()
            if result_db.get('success'):
                count = result_db.get('deleted_count', 0)
                await add_alert(page, f"✅ Database cleaned: {count} records deleted.")
            else:
                 await add_alert(page, f"❌ Failed to clean database: {result_db.get('detail', 'Unknown error')}")

            # 3. Stop monitoring if active
            if is_running:
                await stop_monitoring(None) # Pass None for event arg if called internally

            await add_alert(page, "Self-destruct complete. Closing application.")
            await page.update() # Show final alert
            await asyncio.sleep(3) # Allow user to see final message
            await page.window_close_async() # Close the app window

        except Exception as sd_e:
            await add_alert(page, f"❌ Error during self-destruct: {str(sd_e)}")
            # Ensure dialog is closed even on error
            self_destruct_dialog.open = False
            page.update()

    async def handle_cancel_destruct(e):
        """Handles the cancellation action of the self-destruct dialog."""
        self_destruct_dialog.open = False
        page.update()
        await add_alert(page, "Self-destruct cancelled.")

    async def open_self_destruct_dialog(e):
        """Assigns actions and opens the self-destruct dialog."""
        # Assign handlers just before opening
        self_destruct_dialog.actions = [
            ft.TextButton("Confirm Delete", on_click=handle_confirm_destruct, style=ft.ButtonStyle(color=ft.Colors.RED)),
            ft.TextButton("Cancel", on_click=handle_cancel_destruct),
        ]
        page.dialog = self_destruct_dialog
        self_destruct_dialog.open = True
        page.update()

    # --- Control Buttons ---
    start_button = ft.ElevatedButton("Start Monitoring", on_click=start_monitoring, icon=ft.Icons.PLAY_ARROW)
    stop_button = ft.ElevatedButton("Stop Monitoring", on_click=stop_monitoring, disabled=True, icon=ft.Icons.STOP)
    analytics_button = ft.ElevatedButton("View Analytics", on_click=show_analytics, icon=ft.Icons.ANALYTICS)
    self_destruct_button = ft.ElevatedButton(
        "Self Destruct",
        on_click=open_self_destruct_dialog,
        icon=ft.Icons.DELETE_FOREVER,
        color=ft.Colors.WHITE,
        bgcolor=ft.Colors.RED_700
    )

    # --- Layout ---
    left_column = ft.Column(
        [
            ft.Text("Live Feed", theme_style=ft.TextThemeStyle.HEADLINE_SMALL),
            video_image,
            ft.Row(
                [start_button, stop_button, analytics_button, self_destruct_button],
                alignment=ft.MainAxisAlignment.START
            ),
            ft.Container(height=10), # Spacer
            ft.Text("Status", style=ft.TextThemeStyle.TITLE_MEDIUM),
            status_label,
        ],
        expand=True,
        spacing=10
    )

    right_column = ft.Column(
        [
            ft.Text("Recent Alerts", theme_style=ft.TextThemeStyle.HEADLINE_SMALL),
            ft.Container(
                content=alerts_list,
                border=ft.border.all(1, ft.Colors.OUTLINE),
                border_radius=ft.border_radius.all(5),
                padding=5,
                expand=True # Make alerts list fill available space
            )
        ],
        expand=True,
        spacing=10
    )

    # Add layout to page
    page.add(
        ft.Row(
            [
                ft.Container(left_column, padding=10, expand=2), # Give left column more weight initially
                ft.Container(right_column, padding=10, expand=1)
            ],
            expand=True
        )
    )

    # Initial cleanup call (run in background thread)
    async def run_initial_cleanup(page_ref: ft.Page):
        try:
            await add_alert(page_ref, "Performing initial database cleanup...")
            response = await asyncio.to_thread(requests.post, DB_CLEANUP_ENDPOINT, params={'days': 30}, timeout=30)
            response.raise_for_status()
            result = response.json()
            if result.get('success'):
                count = result.get('deleted_count', 0)
                await add_alert(page_ref, f"Initial cleanup complete: {count} old images deleted.")
            else:
                await add_alert(page_ref, f"Initial cleanup failed: {result.get('detail', 'Unknown error')}")
        except Exception as cleanup_e:
            await add_alert(page_ref, f"Error during initial cleanup: {str(cleanup_e)}")

    # Don't block startup, run cleanup in background
    asyncio.create_task(run_initial_cleanup(page))

ft.app(target=main)