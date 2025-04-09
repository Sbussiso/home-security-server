from flask import Flask, request
from flask_restful import Resource, Api
from rekognition import analyze_image
from aws_s3 import upload_file
from notifications import send_security_alert
from database import (
    save_image, add_security_alert, save_temp_image_file,
    update_s3_url, cleanup_old_images, get_recent_images
)
import requests
from dotenv import load_dotenv
import os
import tempfile
import cv2
import numpy as np
import base64

# Load environment variables
load_dotenv()

# Initialize the Flask application
app = Flask(__name__)
# Create an API object from Flask-RESTful
api = Api(app)


# Define a resource
class HelloWorld(Resource):
    def get(self):
        # Returns a JSON response for GET requests
        return {'message': 'Hello, world!'}

    def post(self):
        # For a POST request, get the JSON payload sent by the client
        json_data = request.get_json(force=True)
        # You can process json_data here. For demonstration, we return it back.
        return {'you sent': json_data}, 201

class ImageAnalysis(Resource):
    def post(self):
        """
        Analyze an image using AWS Rekognition.
        Expects a JSON payload with 'image_url' field.
        """
        try:
            # Get the image URL from the request
            data = request.get_json(force=True)
            image_url = data.get('image_url')
            
            if not image_url:
                return {'error': 'No image URL provided'}, 400

            # Use the existing analyze_image function from rekognition.py
            result = analyze_image(image_url)
            return result, 200

        except Exception as e:
            return {'error': f'Unexpected error: {str(e)}'}, 500

class S3Upload(Resource):
    def post(self):
        """
        Upload an image to S3 and return the URL.
        Expects a JSON payload with 'image_data' (base64 encoded) and 'filename' fields.
        """
        try:
            data = request.get_json(force=True)
            image_data = data.get('image_data')
            filename = data.get('filename')
            
            if not image_data or not filename:
                return {'error': 'Missing image_data or filename'}, 400

            try:
                # Decode base64 image data
                image_bytes = base64.b64decode(image_data)
                nparr = np.frombuffer(image_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                if img is None:
                    return {'error': 'Invalid image data'}, 400

                # Save image to temporary file
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                    cv2.imwrite(temp_file.name, img)
                    temp_path = temp_file.name

                try:
                    # Use the existing upload_file function from aws_s3.py
                    success, error, s3_url = upload_file(
                        temp_path,
                        'computer-vision-analysis',
                        filename
                    )

                    if success:
                        return {
                            'success': True,
                            's3_url': s3_url
                        }, 200
                    else:
                        return {'error': error}, 500

                finally:
                    # Clean up temporary file
                    if os.path.exists(temp_path):
                        os.remove(temp_path)

            except base64.binascii.Error:
                return {'error': 'Invalid base64 image data'}, 400
            except Exception as e:
                return {'error': f'Error processing image: {str(e)}'}, 400

        except Exception as e:
            return {'error': f'Error uploading to S3: {str(e)}'}, 500

class Notification(Resource):
    def post(self):
        """
        Send a security alert notification.
        Expects a JSON payload with 'recipient_email', 'subject', 'message', and 'image_data' (base64 encoded) fields.
        """
        try:
            data = request.get_json(force=True)
            recipient_email = data.get('recipient_email')
            subject = data.get('subject')
            message = data.get('message')
            image_data = data.get('image_data')
            
            if not all([recipient_email, subject, message]):
                return {'error': 'Missing required fields'}, 400

            temp_path = None
            try:
                # If image data is provided, save it to a temporary file
                if image_data:
                    image_bytes = base64.b64decode(image_data)
                    nparr = np.frombuffer(image_bytes, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    
                    if img is None:
                        return {'error': 'Invalid image data'}, 400

                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                        cv2.imwrite(temp_file.name, img)
                        temp_path = temp_file.name

                # Use the existing send_security_alert function
                success, error = send_security_alert(
                    recipient_email,
                    subject,
                    message,
                    temp_path
                )

                if success:
                    return {'success': True}, 200
                else:
                    return {'error': error}, 500

            finally:
                # Clean up temporary file
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

        except base64.binascii.Error:
            return {'error': 'Invalid base64 image data'}, 400
        except Exception as e:
            return {'error': f'Error sending notification: {str(e)}'}, 500

class DatabaseImage(Resource):
    def post(self):
        """
        Save an image to the database.
        Expects a JSON payload with 'image_data' (base64 encoded) and 'filename' fields.
        """
        try:
            data = request.get_json(force=True)
            image_data = data.get('image_data')
            filename = data.get('filename')
            
            if not image_data or not filename:
                return {'error': 'Missing image_data or filename'}, 400

            # Decode base64 image data
            image_bytes = base64.b64decode(image_data)
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                return {'error': 'Invalid image data'}, 400

            # Save to database
            image_id = save_image(img, filename)
            return {'success': True, 'image_id': image_id}, 200

        except Exception as e:
            return {'error': f'Error saving image to database: {str(e)}'}, 500

    def get(self):
        """
        Get recent images from the database.
        Optional query parameter 'limit' to specify number of images to return.
        """
        try:
            limit = request.args.get('limit', default=10, type=int)
            images = get_recent_images(limit)
            
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
            
            return {'images': serialized_images}, 200
        except Exception as e:
            return {'error': f'Error retrieving images: {str(e)}'}, 500

class SecurityAlert(Resource):
    def post(self):
        """
        Add a security alert to the database.
        Expects a JSON payload with 'image_id', 'alert_type', and 'confidence' fields.
        """
        try:
            data = request.get_json(force=True)
            image_id = data.get('image_id')
            alert_type = data.get('alert_type')
            confidence = data.get('confidence')
            
            if not all([image_id, alert_type, confidence]):
                return {'error': 'Missing required fields'}, 400

            # Add alert to database
            alert_id = add_security_alert(image_id, alert_type, confidence)
            return {'success': True, 'alert_id': alert_id}, 200

        except Exception as e:
            return {'error': f'Error adding security alert: {str(e)}'}, 500

class DatabaseCleanup(Resource):
    def post(self):
        """
        Clean up old images from the database.
        Optional query parameter 'days' to specify how many days of images to keep.
        """
        try:
            days = request.args.get('days', default=30, type=int)
            deleted_count = cleanup_old_images(days)
            return {'success': True, 'deleted_count': deleted_count}, 200
        except Exception as e:
            return {'error': f'Error cleaning up database: {str(e)}'}, 500

class S3UrlUpdate(Resource):
    def post(self):
        """
        Update the S3 URL for an image in the database.
        Expects a JSON payload with 'image_id' and 's3_url' fields.
        """
        try:
            data = request.get_json(force=True)
            image_id = data.get('image_id')
            s3_url = data.get('s3_url')
            
            if not all([image_id, s3_url]):
                return {'error': 'Missing required fields'}, 400

            # Update S3 URL
            success = update_s3_url(image_id, s3_url)
            if success:
                return {'success': True}, 200
            else:
                return {'error': 'Failed to update S3 URL'}, 500

        except Exception as e:
            return {'error': f'Error updating S3 URL: {str(e)}'}, 500

# Add the resources to the API
api.add_resource(HelloWorld, '/')
api.add_resource(ImageAnalysis, '/analyze')
api.add_resource(S3Upload, '/upload')
api.add_resource(Notification, '/notify')
api.add_resource(DatabaseImage, '/db/image')
api.add_resource(SecurityAlert, '/db/alert')
api.add_resource(DatabaseCleanup, '/db/cleanup')
api.add_resource(S3UrlUpdate, '/db/s3url')

if __name__ == '__main__':
    # Run the Flask app in debug mode for development purposes
    app.run(debug=True)
