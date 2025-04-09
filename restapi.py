from flask import Flask, request
from flask_restful import Resource, Api
import boto3
import requests
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Initialize the Flask application
app = Flask(__name__)
# Create an API object from Flask-RESTful
api = Api(app)

# Initialize AWS Rekognition client
rekognition_client = boto3.client('rekognition',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('AWS_SECRET_KEY'),
    region_name=os.getenv('AWS_REGION')
)

# Define security-relevant labels to watch for
SECURITY_LABELS = {
    'person': 'Person detected',
    'human': 'Person detected',
    'face': 'Face detected',
    'vehicle': 'Vehicle detected',
    'car': 'Vehicle detected',
    'truck': 'Vehicle detected',
    'motorcycle': 'Vehicle detected',
    'bicycle': 'Vehicle detected',
    'weapon': 'Weapon detected',
    'gun': 'Weapon detected',
    'knife': 'Weapon detected',
    'package': 'Package detected',
    'bag': 'Package detected',
    'backpack': 'Package detected',
    'suitcase': 'Package detected',
    'mask': 'Person wearing mask',
    'helmet': 'Person wearing helmet',
    'uniform': 'Person in uniform',
    'police': 'Police officer detected',
    'security': 'Security personnel detected'
}

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

            # Download the image
            response = requests.get(image_url)
            response.raise_for_status()
            image_bytes = response.content

            # Analyze the image with Rekognition
            rekognition_response = rekognition_client.detect_labels(
                Image={'Bytes': image_bytes},
                MaxLabels=20,
                MinConfidence=70
            )

            # Process the results
            labels = rekognition_response.get('Labels', [])
            result = {
                'labels': [],
                'security_alerts': []
            }

            # Process all labels
            for label in labels:
                label_data = {
                    'name': label['Name'],
                    'confidence': label['Confidence']
                }
                result['labels'].append(label_data)

                # Check for security-relevant labels
                label_name = label['Name'].lower()
                if label_name in SECURITY_LABELS:
                    alert = {
                        'type': SECURITY_LABELS[label_name],
                        'confidence': label['Confidence']
                    }
                    result['security_alerts'].append(alert)

            return result, 200

        except requests.exceptions.RequestException as e:
            return {'error': f'Error downloading image: {str(e)}'}, 400
        except ClientError as e:
            return {'error': f'Error detecting labels: {str(e)}'}, 500
        except Exception as e:
            return {'error': f'Unexpected error: {str(e)}'}, 500

# Add the resources to the API
api.add_resource(HelloWorld, '/')
api.add_resource(ImageAnalysis, '/analyze')

if __name__ == '__main__':
    # Run the Flask app in debug mode for development purposes
    app.run(debug=True)
