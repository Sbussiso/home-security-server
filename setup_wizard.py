import tkinter as tk
from tkinter import ttk, messagebox
import os
import subprocess
import sys
from dotenv import load_dotenv, set_key
import re
import requests

def download_requirements():
    """Download requirements.txt from GitHub repository"""
    print("\nDownloading requirements.txt from GitHub...")
    try:
        url = "https://raw.githubusercontent.com/Sbussiso/home-security-server/master/requirements.txt"
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes
        
        with open('requirements.txt', 'w') as f:
            f.write(response.text)
        print("✓ Successfully downloaded requirements.txt")
        return True
    except Exception as e:
        print(f"✗ Error downloading requirements.txt: {str(e)}")
        return False

def run_command(command, description):
    """Run a command and show progress in the console"""
    print(f"\n{description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print("✓ Success")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Error: {e.stderr}")
        return False
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return False

def setup_environment():
    """Setup the environment by installing dependencies and checking requirements"""
    print("="*80)
    print("Security System Setup Wizard")
    print("="*80)
    print("\nSetting up the environment...")
    
    # Check Python version
    if sys.version_info < (3, 7):
        print("✗ Error: Python 3.7 or higher is required")
        return False
    
    # Check if requirements.txt exists, if not download it
    if not os.path.exists('requirements.txt'):
        if not download_requirements():
            print("\nWarning: Failed to download requirements.txt. You may need to create it manually.")
            return False
    
    # Install dependencies
    if not run_command("pip install -r requirements.txt", "Installing dependencies"):
        print("\nWarning: Failed to install dependencies. You may need to install them manually.")
        print("Please run: pip install -r requirements.txt")
    
    # Create necessary directories
    directories = ["temp", "logs"]
    for directory in directories:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
                print(f"✓ Created directory: {directory}")
            except Exception as e:
                print(f"✗ Error creating directory {directory}: {str(e)}")
    
    print("\nEnvironment setup completed!")
    print("="*80)
    return True

class SetupWizard:
    def __init__(self, root):
        self.root = root
        self.root.title("Security System Setup Wizard")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        # Create main frame
        self.main_frame = ttk.Frame(self.root, padding="20")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Create notebook for different configuration sections
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Create frames for each section
        self.aws_frame = ttk.Frame(self.notebook, padding="10")
        self.email_frame = ttk.Frame(self.notebook, padding="10")
        self.database_frame = ttk.Frame(self.notebook, padding="10")
        self.server_frame = ttk.Frame(self.notebook, padding="10")
        
        # Add frames to notebook
        self.notebook.add(self.aws_frame, text="AWS Configuration")
        self.notebook.add(self.email_frame, text="Email Configuration")
        self.notebook.add(self.database_frame, text="Database Configuration")
        self.notebook.add(self.server_frame, text="Server Configuration")
        
        # Initialize variables
        self.aws_access_key = tk.StringVar()
        self.aws_secret_key = tk.StringVar()
        self.aws_region = tk.StringVar(value="us-east-1")
        
        self.email_user = tk.StringVar()
        self.email_password = tk.StringVar()
        self.smtp_server = tk.StringVar(value="smtp.gmail.com")
        self.smtp_port = tk.StringVar(value="587")
        
        self.db_path = tk.StringVar(value="security_camera.db")
        self.master_username = tk.StringVar(value="admin")
        self.master_password = tk.StringVar()
        
        # Server variables
        self.server_host = tk.StringVar(value="0.0.0.0")
        self.server_port = tk.StringVar(value="5000")
        
        self.setup_aws_frame()
        self.setup_email_frame()
        self.setup_database_frame()
        self.setup_server_frame()
        
        # Add save button
        self.save_button = ttk.Button(self.main_frame, text="Save Configuration", command=self.save_configuration)
        self.save_button.grid(row=1, column=0, pady=20)
        
        # Add help text
        help_text = """
        Welcome to the Security System Setup Wizard!

        This wizard will help you configure your security system.
        Please fill in all the required information in each tab.

        After saving the configuration, you can start the server with:
        python server.py
        """
        ttk.Label(self.main_frame, text=help_text, wraplength=550, justify=tk.LEFT).grid(row=2, column=0, pady=10)
        
    def setup_aws_frame(self):
        # AWS Access Key
        ttk.Label(self.aws_frame, text="AWS Access Key:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.aws_frame, textvariable=self.aws_access_key, show="*").grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5)
        
        # AWS Secret Key
        ttk.Label(self.aws_frame, text="AWS Secret Key:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.aws_frame, textvariable=self.aws_secret_key, show="*").grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5)
        
        # AWS Region
        ttk.Label(self.aws_frame, text="AWS Region:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.aws_frame, textvariable=self.aws_region).grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5)
        
    def setup_email_frame(self):
        # Email User
        ttk.Label(self.email_frame, text="Email Address:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.email_frame, textvariable=self.email_user).grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5)
        
        # Email Password
        ttk.Label(self.email_frame, text="Email Password:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.email_frame, textvariable=self.email_password, show="*").grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5)
        
        # SMTP Server
        ttk.Label(self.email_frame, text="SMTP Server:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.email_frame, textvariable=self.smtp_server).grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5)
        
        # SMTP Port
        ttk.Label(self.email_frame, text="SMTP Port:").grid(row=3, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.email_frame, textvariable=self.smtp_port).grid(row=3, column=1, sticky=(tk.W, tk.E), pady=5)
        
    def setup_database_frame(self):
        # Database Path
        ttk.Label(self.database_frame, text="Database Path:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.database_frame, textvariable=self.db_path).grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5)
        
        # Master Username
        ttk.Label(self.database_frame, text="Master Username:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.database_frame, textvariable=self.master_username).grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5)
        
        # Master Password
        ttk.Label(self.database_frame, text="Master Password:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.database_frame, textvariable=self.master_password, show="*").grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5)
        
    def setup_server_frame(self):
        # Server Host
        ttk.Label(self.server_frame, text="Server Host:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.server_frame, textvariable=self.server_host).grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5)

        # Server Port
        ttk.Label(self.server_frame, text="Server Port:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(self.server_frame, textvariable=self.server_port).grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5)
        
    def validate_email(self, email):
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
        
    def save_configuration(self):
        # Validate inputs
        if not all([self.aws_access_key.get(), self.aws_secret_key.get(), self.aws_region.get()]):
            messagebox.showerror("Error", "Please fill in all AWS configuration fields")
            return
            
        if not all([self.email_user.get(), self.email_password.get(), self.smtp_server.get(), self.smtp_port.get()]):
            messagebox.showerror("Error", "Please fill in all email configuration fields")
            return
            
        if not self.validate_email(self.email_user.get()):
            messagebox.showerror("Error", "Please enter a valid email address")
            return
            
        if not all([self.db_path.get(), self.master_username.get(), self.master_password.get()]):
            messagebox.showerror("Error", "Please fill in all database configuration fields")
            return
            
        # Validate server config
        if not all([self.server_host.get(), self.server_port.get()]):
             messagebox.showerror("Error", "Please fill in all server configuration fields")
             return

        try:
            port = int(self.server_port.get())
            if not (1 <= port <= 65535):
                 raise ValueError("Port must be between 1 and 65535")
        except ValueError:
            messagebox.showerror("Error", "Invalid port number. Please enter a number between 1 and 65535.")
            return
            
        # Create .env file
        env_path = ".env"
        if os.path.exists(env_path):
            os.remove(env_path)
            
        # Write configuration to .env file
        with open(env_path, "w") as f:
            f.write(f"# AWS Credentials\n")
            f.write(f"AWS_ACCESS_KEY={self.aws_access_key.get()}\n")
            f.write(f"AWS_SECRET_KEY={self.aws_secret_key.get()}\n")
            f.write(f"AWS_REGION={self.aws_region.get()}\n\n")
            
            f.write(f"# Email Configuration\n")
            f.write(f"EMAIL_USER={self.email_user.get()}\n")
            f.write(f"EMAIL_PASSWORD={self.email_password.get()}\n")
            f.write(f"SMTP_SERVER={self.smtp_server.get()}\n")
            f.write(f"SMTP_PORT={self.smtp_port.get()}\n\n")
            
            f.write(f"# Database Configuration\n")
            f.write(f"DB_PATH={self.db_path.get()}\n")
            f.write(f"MASTER_PASSWORD={self.master_password.get()}\n")
            f.write(f"MASTER_USERNAME={self.master_username.get()}\n")
            
            f.write(f"\n# Server Configuration\n")
            f.write(f"SERVER_HOST={self.server_host.get()}\n")
            f.write(f"SERVER_PORT={self.server_port.get()}\n")
            
        messagebox.showinfo("Success", "Configuration saved successfully!")
        self.root.destroy()

if __name__ == "__main__":
    # Ask the user whether to use GUI or terminal setup
    choice = input("Do you want to use the GUI for setup? (yes/no): ").strip().lower()
    
    # Run environment setup first
    setup_environment()
    
    if choice == "yes":
        # Start the GUI if the user chose 'yes'
        root = tk.Tk()
        app = SetupWizard(root)
        root.mainloop()
    else:
        # Proceed with terminal-based setup if the user chose 'no'
        print("Proceeding with terminal setup...")
        setup_environment()
