#!/usr/bin/env python3
"""
Weather Radar Web Application Launcher

This script provides an easy way to start the weather radar web application
with proper error handling and user-friendly messages.
"""

import sys
import subprocess
import os
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are installed"""
    required_packages = [
        'flask',
        'boto3', 
        'numpy',
        'pyart',
        'matplotlib'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    return missing_packages

def install_dependencies():
    """Install missing dependencies"""
    print("Installing required dependencies...")
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        print("✓ Dependencies installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to install dependencies: {e}")
        return False

def main():
    """Main launcher function"""
    print("=" * 60)
    print("🌦️  Weather Radar Web Application")
    print("=" * 60)
    
    # Check if we're in the right directory
    if not Path('app.py').exists():
        print("✗ Error: app.py not found in current directory")
        print("Please run this script from the project root directory")
        sys.exit(1)
    
    # Check dependencies
    print("Checking dependencies...")
    missing = check_dependencies()
    
    if missing:
        print(f"✗ Missing packages: {', '.join(missing)}")
        response = input("Would you like to install them now? (y/n): ").lower().strip()
        
        if response in ['y', 'yes']:
            if not install_dependencies():
                sys.exit(1)
        else:
            print("Please install the required packages manually:")
            print("pip install -r requirements.txt")
            sys.exit(1)
    else:
        print("✓ All dependencies are installed")
    
    # Start the application
    print("\nStarting Weather Radar Web Application...")
    print("📡 Radar Site: KMOB (Mobile, Alabama)")
    print("🌐 Server will start at: http://localhost:5000")
    print("📊 Data Source: NOAA NEXRAD Level II")
    print("\nPress Ctrl+C to stop the server")
    print("-" * 60)
    
    try:
        # Import and run the Flask app
        from app import app
        app.run(host="0.0.0.0", port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped by user")
    except Exception as e:
        print(f"\n✗ Error starting application: {e}")
        print("\nTroubleshooting tips:")
        print("1. Check your internet connection (needed for radar data)")
        print("2. Ensure port 5000 is not in use by another application")
        print("3. Try running: python app.py directly")
        sys.exit(1)

if __name__ == "__main__":
    main()