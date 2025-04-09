import os
import sqlite3
import datetime
import base64
from sqlalchemy import Column, Integer, String, DateTime, LargeBinary, Float, Boolean, create_engine, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from dotenv import load_dotenv
import cv2
import numpy as np

# Load environment variables
load_dotenv()

# Define the database path
DB_PATH = os.getenv('DB_PATH', 'security_camera.db')

# Create the SQLAlchemy engine
engine = create_engine(f'sqlite:///{DB_PATH}', echo=False)
Base = declarative_base()
Session = sessionmaker(bind=engine)

class Image(Base):
    """Model for storing captured images"""
    __tablename__ = 'images'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.datetime.now)
    filename = Column(String(255))
    image_data = Column(LargeBinary)  # Store the actual image binary data
    s3_url = Column(String(500), nullable=True)  # S3 URL if uploaded
    width = Column(Integer)
    height = Column(Integer)
    
    # Relationship with security alerts
    alerts = relationship("SecurityAlert", back_populates="image", cascade="all, delete-orphan")

class SecurityAlert(Base):
    """Model for storing security alerts detected in images"""
    __tablename__ = 'security_alerts'
    
    id = Column(Integer, primary_key=True)
    image_id = Column(Integer, ForeignKey('images.id'), nullable=False)
    alert_type = Column(String(100))  # Type of alert (e.g., "Person detected")
    confidence = Column(Float)  # Confidence level of the detection
    timestamp = Column(DateTime, default=datetime.datetime.now)
    notified = Column(Boolean, default=False)  # Whether an email notification was sent
    
    # Relationship with image
    image = relationship("Image", back_populates="alerts")

# Create all tables
Base.metadata.create_all(engine)

def save_image(image_array, filename=None, s3_url=None):
    """
    Save an image to the database.
    
    Parameters:
        image_array (numpy.ndarray): The OpenCV image array
        filename (str, optional): Original filename if available
        s3_url (str, optional): S3 URL if the image was uploaded
        
    Returns:
        int: ID of the saved image
    """
    # Convert image to bytes
    _, img_encoded = cv2.imencode('.jpg', image_array)
    img_bytes = img_encoded.tobytes()
    
    # Get height and width
    height, width = image_array.shape[:2]
    
    # Create timestamp if filename not provided
    if not filename:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"motion_{timestamp}.jpg"
    
    # Create a new session
    session = Session()
    
    try:
        # Create a new image record
        new_image = Image(
            filename=filename,
            image_data=img_bytes,
            s3_url=s3_url,
            width=width,
            height=height
        )
        
        session.add(new_image)
        session.commit()
        
        # Return the image ID
        return new_image.id
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def get_image(image_id):
    """
    Retrieve an image from the database.
    
    Parameters:
        image_id (int): ID of the image to retrieve
        
    Returns:
        tuple: (numpy.ndarray, dict) - The image array and metadata
    """
    session = Session()
    
    try:
        # Get the image record
        image = session.query(Image).filter(Image.id == image_id).first()
        
        if not image:
            return None, None
        
        # Convert bytes to numpy array
        img_array = np.frombuffer(image.image_data, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        
        # Create metadata dictionary
        metadata = {
            'id': image.id,
            'timestamp': image.timestamp,
            'filename': image.filename,
            's3_url': image.s3_url,
            'width': image.width,
            'height': image.height
        }
        
        return img, metadata
    finally:
        session.close()

def save_temp_image_file(image_id, temp_dir='temp_images'):
    """
    Save an image from the database to a temporary file for processing.
    
    Parameters:
        image_id (int): ID of the image to save
        temp_dir (str): Directory to save the temporary file
        
    Returns:
        str: Path to the saved temporary file
    """
    # Ensure temp directory exists
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    
    # Get the image from database
    img, metadata = get_image(image_id)
    
    if img is None:
        return None
    
    # Create a temporary file
    temp_path = os.path.join(temp_dir, metadata['filename'])
    cv2.imwrite(temp_path, img)
    
    return temp_path

def add_security_alert(image_id, alert_type, confidence, notified=False):
    """
    Add a security alert for an image.
    
    Parameters:
        image_id (int): ID of the associated image
        alert_type (str): Type of the security alert
        confidence (float): Confidence level of the detection
        notified (bool): Whether a notification was sent
        
    Returns:
        int: ID of the created alert
    """
    session = Session()
    
    try:
        alert = SecurityAlert(
            image_id=image_id,
            alert_type=alert_type,
            confidence=confidence,
            notified=notified
        )
        
        session.add(alert)
        session.commit()
        
        return alert.id
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def get_recent_images(limit=10):
    """
    Get the most recent images from the database.
    
    Parameters:
        limit (int): Maximum number of images to return
        
    Returns:
        list: List of image metadata dictionaries
    """
    session = Session()
    
    try:
        images = session.query(Image).order_by(Image.timestamp.desc()).limit(limit).all()
        
        result = []
        for image in images:
            metadata = {
                'id': image.id,
                'timestamp': image.timestamp,
                'filename': image.filename,
                's3_url': image.s3_url,
                'width': image.width,
                'height': image.height,
                'alert_count': len(image.alerts)
            }
            result.append(metadata)
            
        return result
    finally:
        session.close()

def get_image_with_alerts(image_id):
    """
    Get an image and its associated security alerts.
    
    Parameters:
        image_id (int): ID of the image
        
    Returns:
        tuple: (numpy.ndarray, dict, list) - Image array, metadata, and alerts
    """
    session = Session()
    
    try:
        # Get the image
        image = session.query(Image).filter(Image.id == image_id).first()
        
        if not image:
            return None, None, None
            
        # Convert bytes to numpy array
        img_array = np.frombuffer(image.image_data, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        
        # Create metadata dictionary
        metadata = {
            'id': image.id,
            'timestamp': image.timestamp,
            'filename': image.filename,
            's3_url': image.s3_url,
            'width': image.width,
            'height': image.height
        }
        
        # Get alerts
        alerts = []
        for alert in image.alerts:
            alerts.append({
                'id': alert.id,
                'alert_type': alert.alert_type,
                'confidence': alert.confidence,
                'timestamp': alert.timestamp,
                'notified': alert.notified
            })
            
        return img, metadata, alerts
    finally:
        session.close()

def update_s3_url(image_id, s3_url):
    """
    Update the S3 URL for an image.
    
    Parameters:
        image_id (int): ID of the image
        s3_url (str): S3 URL to set
        
    Returns:
        bool: True if successful, False otherwise
    """
    session = Session()
    
    try:
        image = session.query(Image).filter(Image.id == image_id).first()
        
        if not image:
            return False
            
        image.s3_url = s3_url
        session.commit()
        
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()

def cleanup_old_images(days=30):
    """
    Delete images older than the specified number of days.
    
    Parameters:
        days (int): Number of days to keep images
        
    Returns:
        int: Number of deleted images
    """
    session = Session()
    
    try:
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)
        old_images = session.query(Image).filter(Image.timestamp < cutoff_date).all()
        
        count = len(old_images)
        
        for image in old_images:
            session.delete(image)
            
        session.commit()
        
        return count
    except Exception:
        session.rollback()
        return 0
    finally:
        session.close()

# Test function to initialize the database
if __name__ == "__main__":
    print(f"Database initialized at {DB_PATH}")
    print(f"Tables created: {', '.join(Base.metadata.tables.keys())}")
