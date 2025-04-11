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
DB_DELETE_ENDPOINT = f"{REST_API_URL}/db/delete-file"
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
        is_internal_call = e is None
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
            if not is_internal_call:
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
            if not is_internal_call:
                video_image.page.update()

    async def show_analytics(e):
        # Navigate to the analytics view
        page.go("/analytics")
        
    async def show_self_destruct(e):
        # Navigate to the self destruct view
        page.go("/self-destruct")

    async def add_alert(page_ref: ft.Page, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        alerts_list.controls.append(ft.Text(f"[{timestamp}] {message}"))
        # Limit number of alerts shown
        if len(alerts_list.controls) > 200:
            alerts_list.controls.pop(0)
        # Use synchronous update, even in async context
        if alerts_list.page:
            page_ref.update()

    # --- Self Destruct Implementation ---
    async def perform_self_destruct(e=None):
        """Performs the actual self-destruct operations"""
        print("perform_self_destruct function started")
        # Show progress and status on the self-destruct page
        self_destruct_status.value = "Self-destruct sequence initiated..."
        self_destruct_progress.visible = True
        self_destruct_confirm_btn.disabled = True
        self_destruct_cancel_btn.disabled = True
        page.update()
        
        # Track success/failure
        success = True
        error_details = []
        
        # Step 1: Delete S3 bucket
        self_destruct_status.value = "Deleting S3 bucket..."
        page.update()
        await add_alert(page, "Deleting S3 bucket...")
        try:
            print("Attempting to delete S3 bucket...")
            response = await asyncio.to_thread(
                requests.post, 
                S3_BUCKET_DELETE_ENDPOINT, 
                json={
                    'bucket_name': 'computer-vision-analysis',
                    'confirmation': 'CONFIRM_DELETE'
                }, 
                timeout=60
            )
            print(f"S3 bucket deletion response status: {response.status_code}")
            response.raise_for_status()
            result = response.json()
            print(f"S3 bucket deletion result: {result}")
            
            if result.get('success'):
                print("S3 bucket deleted successfully")
                await add_alert(page, "✅ S3 bucket deleted.")
            else:
                msg = f"⚠️ Failed to delete S3 bucket: {result.get('detail', 'Unknown error')}"
                print(msg)
                await add_alert(page, msg)
                error_details.append(msg)
                success = False
        except Exception as e:
            msg = f"❌ Error during S3 deletion: {str(e)}"
            print(f"Exception during S3 deletion: {str(e)}")
            await add_alert(page, msg)
            error_details.append(msg)
            success = False

        # Step 2: Clean database
        self_destruct_status.value = "Cleaning up database..."
        page.update()
        await add_alert(page, "Cleaning up database...")
        try:
            print("Attempting to clean database...")
            response = await asyncio.to_thread(
                requests.post, 
                DB_CLEANUP_ENDPOINT, 
                params={'days': 0}, 
                timeout=30
            )
            print(f"DB cleanup response status: {response.status_code}")
            response.raise_for_status()
            result = response.json()
            print(f"DB cleanup result: {result}")
            
            if result.get('success'):
                count = result.get('deleted_count', 0)
                print(f"Database cleaned, {count} records deleted")
                await add_alert(page, f"✅ Database cleaned: {count} records deleted.")
            else:
                msg = f"⚠️ Failed to clean database: {result.get('detail', 'Unknown error')}"
                print(msg)
                await add_alert(page, msg)
                error_details.append(msg)
                success = False
        except Exception as e:
            msg = f"❌ Error during database cleanup: {str(e)}"
            print(f"Exception during database cleanup: {str(e)}")
            await add_alert(page, msg)
            error_details.append(msg)
            success = False

        # Step 3: Delete database file
        self_destruct_status.value = "Deleting database file..."
        page.update()
        await add_alert(page, "Deleting database file...")
        try:
            print("Attempting to delete database file...")
            response = await asyncio.to_thread(
                requests.post, 
                DB_DELETE_ENDPOINT, 
                timeout=10
            )
            print(f"DB file deletion response status: {response.status_code}")
            response.raise_for_status()
            result = response.json()
            print(f"DB file deletion result: {result}")
            
            if result.get('success'):
                print("Database file deleted successfully")
                await add_alert(page, "✅ Database file deleted.")
            else:
                msg = f"⚠️ Failed to delete database file: {result.get('detail', 'Unknown error')}"
                print(msg)
                await add_alert(page, msg)
                error_details.append(msg)
                success = False
        except Exception as e:
            msg = f"❌ Error deleting database file: {str(e)}"
            print(f"Exception during database file deletion: {str(e)}")
            await add_alert(page, msg)
            error_details.append(msg)
            success = False

        # Step 4: Stop monitoring if running
        if is_running:
            self_destruct_status.value = "Stopping camera monitoring..."
            page.update()
            await add_alert(page, "Stopping camera monitoring...")
            try:
                print("Attempting to stop monitoring...")
                await stop_monitoring(None)
                print("Monitoring stopped successfully")
            except Exception as e:
                msg = f"❌ Error stopping monitoring: {str(e)}"
                print(f"Exception during monitoring stop: {str(e)}")
                await add_alert(page, msg)
                error_details.append(msg)
                success = False

        # Update final status
        if success:
            self_destruct_status.value = "✅ Self-destruct sequence completed successfully."
            await add_alert(page, "✅ Self-destruct sequence completed successfully.")
            print("Self-destruct completed successfully")
        else:
            self_destruct_status.value = "⚠️ Self-destruct completed with some errors."
            await add_alert(page, "⚠️ Self-destruct completed with some errors.")
            print(f"Self-destruct completed with errors: {error_details}")
        
        self_destruct_progress.visible = False
        self_destruct_done_btn.visible = True
        page.update()
        print("Self-destruct function completed")

    # --- Control Buttons ---
    start_button = ft.ElevatedButton("Start Monitoring", on_click=start_monitoring, icon=ft.Icons.PLAY_ARROW)
    stop_button = ft.ElevatedButton("Stop Monitoring", on_click=stop_monitoring, disabled=True, icon=ft.Icons.STOP)
    analytics_button = ft.ElevatedButton("View Analytics", on_click=show_analytics, icon=ft.Icons.ANALYTICS)
    self_destruct_button = ft.ElevatedButton(
        "Self Destruct",
        on_click=show_self_destruct,
        icon=ft.Icons.DELETE_FOREVER,
        color=ft.Colors.WHITE,
        bgcolor=ft.Colors.RED_700
    )

    # Self-destruct page UI elements
    self_destruct_status = ft.Text(
        "WARNING: This will delete ALL data including S3 bucket contents, database records, and security alerts.",
        size=16,
        color=ft.Colors.RED_700,
        weight=ft.FontWeight.BOLD
    )
    self_destruct_details = ft.Text(
        "This action cannot be undone! Are you sure you want to proceed?",
        size=14
    )
    self_destruct_progress = ft.ProgressRing(visible=False)
    self_destruct_confirm_btn = ft.ElevatedButton(
        "CONFIRM DELETE", 
        on_click=perform_self_destruct,  # Direct reference to async function
        color=ft.Colors.WHITE,
        bgcolor=ft.Colors.RED,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=8),
        )
    )
    self_destruct_cancel_btn = ft.ElevatedButton(
        "Nevermind", 
        on_click=lambda _: page.go("/"),
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=8),
        )
    )
    self_destruct_done_btn = ft.ElevatedButton(
        "Return to Main Screen", 
        on_click=lambda _: page.go("/"),
        visible=False
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
            ft.Text("Status", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
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

    # --- Routing and Views --- #

    def build_main_view():
        """Builds the main view with live feed and controls."""
        return ft.View(
            "/",
            [   ft.AppBar(title=ft.Text("Security Camera"), bgcolor=ft.Colors.ON_SURFACE_VARIANT),
                ft.Row(
                    [
                        ft.Container(left_column, padding=10),
                        ft.VerticalDivider(),
                        ft.Container(right_column, padding=10, expand=True)
                    ],
                    expand=True,
                    vertical_alignment=ft.CrossAxisAlignment.START
                )
            ]
        )
        
    def build_self_destruct_view():
        """Builds the self-destruct confirmation view."""
        return ft.View(
            "/self-destruct",
            [
                ft.AppBar(
                    title=ft.Text("⚠️ SELF DESTRUCT"), 
                    bgcolor=ft.Colors.RED_900,
                    color=ft.Colors.WHITE
                ),
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(
                                ft.Icons.WARNING_ROUNDED,
                                size=80,
                                color=ft.Colors.RED_700
                            ),
                            self_destruct_status,
                            self_destruct_details,
                            ft.Container(height=20),  # Spacer
                            self_destruct_progress,
                            ft.Container(height=20),  # Spacer
                            ft.Row(
                                [
                                    self_destruct_confirm_btn,
                                    self_destruct_cancel_btn,
                                    self_destruct_done_btn
                                ],
                                alignment=ft.MainAxisAlignment.CENTER,
                                spacing=20
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10
                    ),
                    alignment=ft.alignment.center,
                    padding=50,
                    expand=True
                )
            ]
        )

    async def build_analytics_view():
        """Builds the analytics view by fetching and formatting data."""
        view_content = ft.Column([
            ft.ProgressRing(),
            ft.Text("Loading analytics data...")
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

        view = ft.View(
            "/analytics",
            [
                ft.AppBar(title=ft.Text("Analytics"), bgcolor=ft.Colors.ON_SURFACE_VARIANT, leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: page.go("/"))),
                ft.Container(view_content, padding=20, expand=True)
            ],
            scroll=ft.ScrollMode.ADAPTIVE # Allow scrolling for the whole view
        )

        # Fetch data asynchronously after returning the initial view structure
        async def fetch_and_update():
            try:
                print("Attempting to fetch analytics data for view...")
                response = await asyncio.to_thread(requests.get, DB_IMAGE_ENDPOINT, params={'limit': 1000}, timeout=15)
                response.raise_for_status()
                result = response.json()
                print(f"API Response Raw: {result}")

                if 'error' in result or 'detail' in result:
                    api_error_msg = result.get('error') or result.get('detail')
                    print(f"API returned error: {api_error_msg}")
                    view_content.controls = [ft.Text(f"API Error: {api_error_msg}")]
                else:
                    images = result.get('images', [])
                    print(f"Extracted images (count: {len(images)}): {images[:2]}...")

                    if not images:
                        print("No images found in API response.")
                        view_content.controls = [ft.Text("No images found in the database.")]
                    else:
                        print("Processing image data for view...")
                        total_images = len(images)
                        images_with_alerts = sum(1 for img in images if img['alert_count'] > 0)
                        alert_rate = (images_with_alerts / total_images) * 100 if total_images > 0 else 0

                        summary_text = (
                            f"Total Images: {total_images}\n"
                            f"Images with Security Alerts: {images_with_alerts}\n"
                            f"Alert Rate: {alert_rate:.2f}%"
                        )

                        recent_images_text = "\n----- 10 Most Recent Images -----\n"
                        for i, img in enumerate(images[:10]):
                            alert_status = f"🚨 {img['alert_count']} alerts" if img['alert_count'] > 0 else "No alerts"
                            recent_images_text += f"{i+1}. [{img['timestamp']}] {img['filename']} - {alert_status}\n"

                        recent_alerts_text = ""
                        if images_with_alerts > 0:
                            recent_alerts_text += "\n----- Recent Security Alerts -----\n"
                            alert_count = 0
                            for img in images:
                                if img['alert_count'] > 0:
                                    recent_alerts_text += f"Image: {img['filename']} - {img['timestamp']}\n"
                                    if img['s3_url']:
                                        recent_alerts_text += f"  S3 URL: {img['s3_url']}\n"
                                    recent_alerts_text += f"  Total Alerts: {img['alert_count']}\n"
                                    recent_alerts_text += "-" * 40 + "\n"
                                    alert_count += 1
                                    if alert_count >= 10:
                                        break

                        view_content.controls = [
                            ft.Text(summary_text, selectable=True),
                            ft.Divider(),
                            ft.Text(recent_images_text, selectable=True),
                            ft.Divider(),
                            ft.Text(recent_alerts_text, selectable=True),
                        ]

            except requests.exceptions.RequestException as req_e:
                error_msg = f"Error accessing database: {str(req_e)}"
                print(f"RequestException: {error_msg}")
                view_content.controls = [ft.Text(error_msg)]
            except Exception as exc:
                error_msg = f"An unexpected error occurred: {str(exc)}"
                print(f"Generic Exception: {error_msg}")
                import traceback
                traceback.print_exc()
                view_content.controls = [ft.Text(error_msg)]

            # Update the view content
            # Check if the current view is still the analytics view before updating
            if page.route == "/analytics":
                print("Updating analytics view content...")
                page.update() # Use synchronous update
            else:
                print("Route changed before analytics data fetched, not updating view.")

        # Schedule the data fetching task
        asyncio.create_task(fetch_and_update())
        return view # Return the view with the loading indicator

    async def route_change(route):
        print(f"Route change requested: {page.route}")
        page.views.clear()
        
        if page.route == "/analytics":
            page.views.append(await build_analytics_view())
        elif page.route == "/self-destruct":
            # Reset self-destruct page state when navigating to it
            self_destruct_status.value = "WARNING: This will delete ALL data including S3 bucket contents, database records, and security alerts."
            self_destruct_details.value = "This action cannot be undone! Are you sure you want to proceed?"
            self_destruct_progress.visible = False
            self_destruct_confirm_btn.disabled = False
            self_destruct_cancel_btn.disabled = False
            self_destruct_done_btn.visible = False
            
            page.views.append(build_self_destruct_view())
        else:
            # Default to main view for "/" or any other route
            page.views.append(build_main_view())
            
        page.update() # Use synchronous update for view changes

    page.on_route_change = route_change

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

    # Initial route
    page.go(page.route) # Trigger the initial route change to display the main view

ft.app(target=main)