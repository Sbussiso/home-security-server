import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import os

load_dotenv()

# Replace these with your actual credentials (be sure to secure these properly!)
aws_access_key = os.getenv('AWS_ACCESS_KEY')
aws_secret_key = os.getenv('AWS_SECRET_KEY')
region = os.getenv('AWS_REGION')

s3_client = boto3.client('s3',
                         aws_access_key_id=aws_access_key,
                         aws_secret_access_key=aws_secret_key,
                         region_name=region)




########################################################
# Check if the bucket exists; if not, create it.
########################################################    
def bucket_exists(bucket_name, s3_client):
    """
    Check if an S3 bucket exists.

    Parameters:
        bucket_name (str): The name of the bucket to check.
        s3_client (boto3.client): A boto3 S3 client.

    Returns:
        bool: True if the bucket exists, otherwise False.
    """
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        return True
    except ClientError as e:
        # A 404 error indicates that the bucket does not exist
        if e.response['Error']['Code'] == '404':
            return False
        else:
            # Any other error is unexpected and should be raised
            raise

def create_bucket(bucket_name, s3_client, region=None):
    """
    Create an S3 bucket in a specified region.

    Parameters:
        bucket_name (str): The name of the bucket to create (must be globally unique).
        s3_client (boto3.client): A boto3 S3 client.
        region (str): The region for the bucket (e.g., 'us-east-1').

    Returns:
        bool: True if bucket was successfully created, otherwise False.
    """
    try:
        if region is None or region == 'us-east-1':
            # For us-east-1, a LocationConstraint isn't required
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            # For other regions, the LocationConstraint parameter is mandatory
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        print(f'Bucket "{bucket_name}" created successfully.')
    except ClientError as e:
        print("Error creating bucket:", e)
        return False
    return True

# Replace this bucket name with one that is globally unique.
bucket_name = "computer-vision-analysis"  # Change to your preferred unique bucket name
region = "us-east-1"

# Check if the bucket exists; if not, create it.
if bucket_exists(bucket_name, s3_client):
    print(f"Bucket '{bucket_name}' already exists.")
else:
    print(f"Bucket '{bucket_name}' does not exist. Creating it now...")
    if create_bucket(bucket_name, s3_client, region):
        print(f"Bucket '{bucket_name}' successfully created.")
    else:
        print(f"Failed to create bucket '{bucket_name}'.")



########################################################
# Upload a file to the bucket.
########################################################

def upload_file(file_name, bucket_name, object_name=None):
    """
    Upload a file to an S3 bucket and return a pre-signed URL.
    If the bucket doesn't exist, it will be created automatically.

    Parameters:
        file_name (str): Path to the file to upload
        bucket_name (str): Name of the bucket to upload to
        object_name (str): S3 object name. If not specified, file_name is used

    Returns:
        bool: True if file was uploaded successfully, False otherwise
        str: Error message if upload failed, None if successful
        str: Pre-signed S3 URL of the uploaded file if successful, None if failed
    """
    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = os.path.basename(file_name)

    try:
        # Check if file exists locally
        if not os.path.exists(file_name):
            return False, f"File {file_name} does not exist locally", None

        # Check if bucket exists, if not create it
        if not bucket_exists(bucket_name, s3_client):
            print(f"Bucket '{bucket_name}' does not exist. Creating it now...")
            if not create_bucket(bucket_name, s3_client, region):
                return False, f"Failed to create bucket '{bucket_name}'", None
            print(f"Bucket '{bucket_name}' created successfully")

        # Upload the file
        s3_client.upload_file(file_name, bucket_name, object_name)
        print(f"Successfully uploaded {file_name} to {bucket_name}/{object_name}")
        
        # Generate a pre-signed URL that expires in 1 hour
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket_name,
                'Key': object_name
            },
            ExpiresIn=3600  # URL expires in 1 hour
        )
        return True, None, presigned_url
    except ClientError as e:
        error_message = f"Error uploading {file_name} to {bucket_name}: {str(e)}"
        print(error_message)
        return False, error_message, None
    except Exception as e:
        error_message = f"Unexpected error uploading {file_name}: {str(e)}"
        print(error_message)
        return False, error_message, None



def delete_bucket(bucket_name, s3_client):
    """
    Delete all objects in the bucket and then delete the bucket itself.
    This is a destructive operation that cannot be undone.

    Parameters:
        bucket_name (str): The name of the bucket to delete
        s3_client (boto3.client): A boto3 S3 client

    Returns:
        bool: True if bucket was successfully deleted, False otherwise
        str: Error message if deletion failed, None if successful
    """
    try:
        # First, delete all objects in the bucket
        print(f"Deleting all objects in bucket '{bucket_name}'...")
        
        # List all objects in the bucket
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket_name):
            if 'Contents' in page:
                # Delete all objects in the current page
                delete_keys = {'Objects': [{'Key': obj['Key']} for obj in page['Contents']]}
                s3_client.delete_objects(Bucket=bucket_name, Delete=delete_keys)
                print(f"Deleted {len(page['Contents'])} objects from bucket '{bucket_name}'")

        # Now delete the bucket itself
        print(f"Deleting bucket '{bucket_name}'...")
        s3_client.delete_bucket(Bucket=bucket_name)
        print(f"Bucket '{bucket_name}' successfully deleted")
        return True, None
        
    except ClientError as e:
        error_message = f"Error deleting bucket '{bucket_name}': {str(e)}"
        print(error_message)
        return False, error_message
    except Exception as e:
        error_message = f"Unexpected error deleting bucket '{bucket_name}': {str(e)}"
        print(error_message)
        return False, error_message
