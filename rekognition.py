import boto3
import requests
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import os

load_dotenv()

# Replace these with your actual credentials (be sure to secure these properly!)
aws_access_key = os.getenv('AWS_ACCESS_KEY')
aws_secret_key = os.getenv('AWS_SECRET_KEY')
region = os.getenv('AWS_REGION')

rekognition_client = boto3.client('rekognition',
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_key,
    region_name=region
)

def analyze_image(image_url, min_confidence=70, max_labels=20):
    """
    Analyze an image using AWS Rekognition and return the results.

    Parameters:
        image_url (str): The S3 URL of the image to analyze
        min_confidence (int): Minimum confidence level for detected labels (default: 70)
        max_labels (int): Maximum number of labels to return (default: 10)

    Returns:
        dict: A dictionary containing:
            - 'labels': List of detected labels with their confidence scores
            - 'security_alerts': List of detected security-relevant items
            - 'error': Error message if any, None if successful
    """
    result = {
        'labels': [],
        'security_alerts': [],
        'error': None
    }

    # Define security-relevant labels to watch for
    security_labels = {
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

    try:
        # Download the image from the provided URL
        response = requests.get(image_url)
        response.raise_for_status()
        image_bytes = response.content

        # Call Rekognition to detect labels
        rekognition_response = rekognition_client.detect_labels(
            Image={'Bytes': image_bytes},
            MaxLabels=max_labels,
            MinConfidence=min_confidence
        )

        # Process the labels
        labels = rekognition_response.get('Labels', [])
        result['labels'] = [
            {
                'name': label['Name'],
                'confidence': label['Confidence']
            }
            for label in labels
        ]

        # Check for security-relevant labels
        for label in labels:
            label_name = label['Name'].lower()
            if label_name in security_labels:
                alert = {
                    'type': security_labels[label_name],
                    'confidence': label['Confidence']
                }
                result['security_alerts'].append(alert)

    except requests.exceptions.RequestException as e:
        result['error'] = f"Error downloading image: {str(e)}"
    except ClientError as e:
        result['error'] = f"Error detecting labels: {str(e)}"
    except Exception as e:
        result['error'] = f"Unexpected error: {str(e)}"

    return result

# Example usage when running the script directly
if __name__ == '__main__':
    image_url = "https://replicate.delivery/pbxt/KOJpWfZmaP6tUv8fqR2n0z3FdBhtytoP5llaecrvvez0p4LE/dog.jpeg"
    analysis = analyze_image(image_url)
    
    if analysis['error']:
        print(f"Error: {analysis['error']}")
    else:
        print("\nDetected labels:")
        for label in analysis['labels']:
            print(f"{label['name']} (Confidence: {label['confidence']:.2f}%)")
        
        if analysis['security_alerts']:
            print("\nSecurity Alerts:")
            for alert in analysis['security_alerts']:
                print(f"{alert['type']} (Confidence: {alert['confidence']:.2f}%)")