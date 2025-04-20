#!/usr/bin/env python3

import os
import re
import sys
import subprocess
import requests
import tkinter as tk
from tkinter import ttk, messagebox
from dotenv import load_dotenv, set_key
import getpass

# ──────── Core Environment Setup ────────

def download_requirements():
    """Download requirements.txt from GitHub repository"""
    print("\nDownloading requirements.txt from GitHub...")
    try:
        url = "https://raw.githubusercontent.com/Sbussiso/home-security-server/master/requirements.txt"
        response = requests.get(url)
        response.raise_for_status()
        with open('requirements.txt', 'w') as f:
            f.write(response.text)
        print("✓ Successfully downloaded requirements.txt")
        return True
    except Exception as e:
        print(f"✗ Error downloading requirements.txt: {e}")
        return False

def run_command(command, description):
    """Run a shell command showing progress"""
    print(f"\n{description}...")
    try:
        subprocess.run(command, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print("✓ Success")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Error: {e.stderr.decode().strip()}")
        return False

def setup_environment():
    """Install dependencies and create needed directories"""
    print("="*80)
    print("Security System Setup Wizard")
    print("="*80)
    print("\nSetting up the environment...")

    # Python version check
    if sys.version_info < (3, 7):
        print("✗ Error: Python 3.7 or higher is required")
        sys.exit(1)

    # requirements.txt
    if not os.path.exists('requirements.txt'):
        if not download_requirements():
            print("\nWarning: requirements.txt missing; please create it manually.")
            sys.exit(1)

    # pip install
    if not run_command("pip install -r requirements.txt", "Installing dependencies"):
        print("\nWarning: Failed to install dependencies; you may need to run:")
        print("    pip install -r requirements.txt")

    # directories
    for d in ("temp", "logs"):
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            print(f"✓ Created directory: {d}")

    print("\nEnvironment setup completed!")
    print("="*80)

# ──────── Terminal‑based Configuration ────────

def validate_email(email: str) -> bool:
    return re.match(r'^[\w\.\+\-]+@[\w\-]+\.[a-zA-Z]{2,}$', email) is not None

def prompt_terminal_configuration():
    print("\n" + "="*30)
    print(" Security System Configuration (Terminal) ")
    print("="*30)

    # AWS
    aws_access_key = input("AWS Access Key               : ").strip()
    aws_secret_key = getpass.getpass("AWS Secret Key               : ").strip()
    aws_region     = input("AWS Region [us-east-1]       : ").strip() or "us-east-1"

    # Email
    email_user     = input("Email Address                : ").strip()
    while not validate_email(email_user):
        print("✗ Invalid email format.")
        email_user = input("Email Address                : ").strip()
    email_password = getpass.getpass("Email Password               : ").strip()
    smtp_server    = input("SMTP Server [smtp.gmail.com] : ").strip() or "smtp.gmail.com"
    smtp_port      = input("SMTP Port [587]              : ").strip() or "587"

    # Database
    db_path        = input("Database Path [security_camera.db]: ").strip() or "security_camera.db"
    master_username= input("Master Username [admin]      : ").strip() or "admin"
    master_password= getpass.getpass("Master Password             : ").strip()

    # Server
    server_host    = input("Server Host [0.0.0.0]        : ").strip() or "0.0.0.0"
    server_port    = input("Server Port [5000]           : ").strip() or "5000"
    try:
        port_num = int(server_port)
        if not (1 <= port_num <= 65535):
            raise ValueError
    except ValueError:
        print("✗ Invalid port number; must be 1–65535.")
        sys.exit(1)

    # Write the .env file
    env_path = ".env"
    if os.path.exists(env_path):
        os.remove(env_path)

    with open(env_path, "w") as f:
        f.write("# AWS Credentials\n")
        f.write(f"AWS_ACCESS_KEY={aws_access_key}\n")
        f.write(f"AWS_SECRET_KEY={aws_secret_key}\n")
        f.write(f"AWS_REGION={aws_region}\n\n")

        f.write("# Email Configuration\n")
        f.write(f"EMAIL_USER={email_user}\n")
        f.write(f"EMAIL_PASSWORD={email_password}\n")
        f.write(f"SMTP_SERVER={smtp_server}\n")
        f.write(f"SMTP_PORT={smtp_port}\n\n")

        f.write("# Database Configuration\n")
        f.write(f"DB_PATH={db_path}\n")
        f.write(f"MASTER_USERNAME={master_username}\n")
        f.write(f"MASTER_PASSWORD={master_password}\n\n")

        f.write("# Server Configuration\n")
        f.write(f"SERVER_HOST={server_host}\n")
        f.write(f"SERVER_PORT={server_port}\n")

    print("\n✓ Configuration saved to .env")
    print("="*30)

# ──────── GUI‑based Configuration ────────

class SetupWizardGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Security System Setup Wizard")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        # ... [your existing GUI code unchanged] ...
        # (copy over all of your setup_aws_frame, setup_email_frame, etc. and save_configuration)
        # In save_configuration(), you already write a .env and then self.root.destroy()

    # [Include all methods from your original GUI class here: setup_aws_frame, setup_email_frame, …, save_configuration]

# ──────── Main Entrypoint ────────

if __name__ == "__main__":
    choice = input("Do you want to use the GUI for setup? (yes/no): ").strip().lower()
    setup_environment()

    if choice == "yes":
        root = tk.Tk()
        SetupWizardGUI(root)
        root.mainloop()
    else:
        prompt_terminal_configuration()
