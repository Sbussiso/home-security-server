import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

def send_security_alert(recipient_email, subject, message, image_path=None):
    """
    Send a security alert email with optional image attachment.
    
    Parameters:
        recipient_email (str): Email address to send the alert to
        subject (str): Email subject line
        message (str): Email body text
        image_path (str, optional): Path to an image file to attach
        
    Returns:
        bool: True if email was sent successfully, False otherwise
        str: Error message if sending failed, None if successful
    """
    # Get email credentials from environment variables
    sender_email = os.getenv('EMAIL_USER')
    sender_password = os.getenv('EMAIL_PASSWORD')
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    
    # Check if credentials are available
    if not sender_email or not sender_password:
        return False, "Missing email credentials. Set EMAIL_USER and EMAIL_PASSWORD in .env file."
    
    try:
        # Create a multipart message
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Subject'] = subject
        
        # Add timestamp to the message
        full_message = f"{message}\n\nTimestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        msg.attach(MIMEText(full_message, 'plain'))
        
        # Attach image if provided
        if image_path and os.path.exists(image_path):
            with open(image_path, 'rb') as file:
                attachment = MIMEApplication(file.read(), Name=os.path.basename(image_path))
            
            # Add header to attachment
            attachment['Content-Disposition'] = f'attachment; filename="{os.path.basename(image_path)}"'
            msg.attach(attachment)
        
        # Connect to server and send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Secure the connection
            server.login(sender_email, sender_password)
            server.send_message(msg)
            
        return True, None
    
    except Exception as e:
        error_message = f"Failed to send email: {str(e)}"
        return False, error_message


# For testing the function directly
if __name__ == "__main__":
    # Test sending an email
    recipient = "sbussiso321@gmail.com"
    subject = "Security Alert Test"
    message = "This is a test security alert from your camera system."
    
    # Test with no attachment
    success, error = send_security_alert(recipient, subject, message)
    
    if success:
        print(f"Test email sent successfully to {recipient}")
    else:
        print(f"Failed to send test email: {error}")



