#!/usr/bin/env python3
import os
import io
import gzip
import shutil
import logging
import tempfile
import time
import json
import base64
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
import numpy as np
import pyart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

from flask import Flask, Response, request, render_template, jsonify
from botocore.config import Config
from botocore import UNSIGNED
from pyart.io.nexrad_archive import read_nexrad_archive

# ——————————————
# Configuration
# ——————————————
BUCKET = "noaa-nexrad-level2"
SITE = "KMOB"
POLL_INTERVAL = 30  # seconds between checks for web app
LOCAL_TZ = ZoneInfo("America/Chicago")

# KMOB radar location (Mobile, Alabama)
RADAR_LAT = 30.6794
RADAR_LON = -88.2397

# ——————————————
# Logging
# ——————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)

# ——————————————
# S3 client (unsigned)
# ——————————————
s3 = boto3.client(
    "s3",
    region_name="us-east-1",
    config=Config(signature_version=UNSIGNED, retries={"max_attempts": 3})
)

app = Flask(__name__)

def list_today_volumes():
    """List all radar volumes for today"""
    now = datetime.utcnow()
    prefix = f"{now.year}/{now.month:02d}/{now.day:02d}/{SITE}/"
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=BUCKET, Prefix=prefix)
    vols = []
    for page in pages:
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("_V06"):
                vols.append(obj)
    return vols

def latest_volume_key():
    """Get the key of the latest radar volume"""
    vols = list_today_volumes()
    if not vols:
        return None
    return max(vols, key=lambda o: o["LastModified"])["Key"]

def parse_timestamp_from_key(key: str) -> datetime:
    """Parse timestamp from S3 key"""
    base = os.path.basename(key)
    ts = base[len(SITE):len(SITE)+15]  # "YYYYMMDD_HHMMSS"
    dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
    return dt.replace(tzinfo=ZoneInfo("UTC"))

def get_radar_data():
    """Download and process the latest radar data"""
    try:
        key = latest_volume_key()
        if not key:
            return None, "No radar data available"

        logging.info(f"Processing volume: {key}")

        # Download file
        fd, download_path = tempfile.mkstemp(prefix="vol_", suffix=None)
        os.close(fd)
        s3.download_file(BUCKET, key, download_path)

        # Handle gzip compression
        with open(download_path, "rb") as f:
            magic = f.read(2)

        if magic == b"\x1f\x8b":
            fd, raw_path = tempfile.mkstemp(prefix="vol_dec_")
            os.close(fd)
            with gzip.open(download_path, "rb") as gf, open(raw_path, "wb") as rf:
                shutil.copyfileobj(gf, rf)
            os.remove(download_path)
        else:
            raw_path = download_path

        # Read with Py-ART
        try:
            radar = pyart.io.read(raw_path)
        except Exception:
            radar = read_nexrad_archive(raw_path, delay_field_loading=True)

        os.remove(raw_path)

        # Get timestamp
        utc_dt = parse_timestamp_from_key(key)
        local_dt = utc_dt.astimezone(LOCAL_TZ)

        return radar, local_dt

    except Exception as e:
        logging.exception("Error processing radar data")
        return None, str(e)

def create_radar_overlay(radar, sweep_idx=0, min_dbz_threshold=7.0, sampling_step=2):
    """Create optimized radar overlay data for map display with filtering"""
    try:
        # Get radar data
        ref_data = radar.get_field(sweep_idx, 'reflectivity')
        azimuth = radar.azimuth['data'][radar.get_start_end(sweep_idx)[0]:radar.get_start_end(sweep_idx)[1]]
        range_data = radar.range['data']
        
        # Create coordinate arrays
        az_rad = np.deg2rad(azimuth)
        range_2d, az_2d = np.meshgrid(range_data, az_rad)
        
        # Convert to Cartesian coordinates (meters from radar)
        x = range_2d * np.sin(az_2d)
        y = range_2d * np.cos(az_2d)
        
        # Convert to lat/lon
        # Approximate conversion (good for small distances)
        lat_offset = y / 111320.0  # meters to degrees latitude
        lon_offset = x / (111320.0 * np.cos(np.deg2rad(RADAR_LAT)))
        
        lats = RADAR_LAT + lat_offset
        lons = RADAR_LON + lon_offset
        
        # Create high-resolution overlay data
        overlay_data = []
        mask = ~ref_data.mask if hasattr(ref_data, 'mask') else np.ones_like(ref_data, dtype=bool)
        
        # Optimized data processing with filtering and sampling
        max_i = min(ref_data.shape[0], lats.shape[0])
        max_j = min(ref_data.shape[1], lats.shape[1])
        
        # Apply user-defined filtering and sampling
        for i in range(0, max_i, sampling_step):
            for j in range(0, max_j, sampling_step):
                if (i < mask.shape[0] and j < mask.shape[1] and
                    mask[i, j] and ref_data[i, j] >= min_dbz_threshold):
                    overlay_data.append({
                        'lat': float(lats[i, j]),
                        'lon': float(lons[i, j]),
                        'value': float(ref_data[i, j]),
                        'color': get_reflectivity_color(ref_data[i, j])
                    })
        
        logging.info(f"Created overlay with {len(overlay_data)} points (threshold: {min_dbz_threshold} dBZ, sampling: every {sampling_step} points)")
        return overlay_data
    
    except Exception as e:
        logging.exception("Error creating radar overlay")
        return []

def get_reflectivity_color(value):
    """Get color for reflectivity value based on NWS color scale"""
    if value < -10:
        return '#000000'  # Black
    elif value < 0:
        return '#9C9C9C'  # Gray
    elif value < 5:
        return '#00ECEC'  # Cyan
    elif value < 10:
        return '#019FF4'  # Blue
    elif value < 15:
        return '#0300F4'  # Dark Blue
    elif value < 20:
        return '#02FD02'  # Green
    elif value < 25:
        return '#01C501'  # Dark Green
    elif value < 30:
        return '#008E00'  # Darker Green
    elif value < 35:
        return '#FDF802'  # Yellow
    elif value < 40:
        return '#E5BC00'  # Orange-Yellow
    elif value < 45:
        return '#FD9500'  # Orange
    elif value < 50:
        return '#FD0000'  # Red
    elif value < 55:
        return '#D40000'  # Dark Red
    elif value < 60:
        return '#BC0000'  # Darker Red
    elif value < 65:
        return '#FD00FD'  # Magenta
    else:
        return '#9854C6'  # Purple

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html', radar_lat=RADAR_LAT, radar_lon=RADAR_LON, site=SITE)

@app.route('/api/radar_data')
def radar_data():
    """API endpoint for radar data"""
    try:
        radar, timestamp = get_radar_data()
        if radar is None:
            return jsonify({'error': timestamp}), 500
        
        # Get requested elevation
        desired_elev = request.args.get('elev', default=0.5, type=float)
        angles = radar.fixed_angle['data']
        sweep_idx = int(np.argmin(np.abs(angles - desired_elev)))
        
        # Get filtering parameters
        min_dbz = request.args.get('threshold', default=7.0, type=float)
        density = request.args.get('density', default=2, type=int)
        
        # Create overlay data with filtering
        overlay_data = create_radar_overlay(radar, sweep_idx, min_dbz, density)
        
        return jsonify({
            'success': True,
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S %Z'),
            'elevation': float(angles[sweep_idx]),
            'site': SITE,
            'radar_lat': RADAR_LAT,
            'radar_lon': RADAR_LON,
            'overlay_data': overlay_data,
            'filter_info': {
                'min_dbz': min_dbz,
                'density': density,
                'point_count': len(overlay_data)
            }
        })
    
    except Exception as e:
        logging.exception("Error in radar_data endpoint")
        return jsonify({'error': str(e)}), 500

@app.route('/api/radar_image')
def radar_image():
    """Generate radar image overlay for map"""
    try:
        radar, timestamp = get_radar_data()
        if radar is None:
            return Response("No radar data available", status=500)
        
        # Get requested elevation
        desired_elev = request.args.get('elev', default=0.5, type=float)
        angles = radar.fixed_angle['data']
        sweep_idx = int(np.argmin(np.abs(angles - desired_elev)))
        
        # Check if we have reflectivity data
        if 'reflectivity' not in radar.fields:
            logging.warning("No reflectivity field found in radar data")
            return Response("No reflectivity data available", status=500)
        
        # Get the reflectivity data for this sweep
        ref_data = radar.get_field(sweep_idx, 'reflectivity')
        logging.info(f"Reflectivity data shape: {ref_data.shape}, min: {np.nanmin(ref_data)}, max: {np.nanmax(ref_data)}")
        
        # Check if we have any valid data
        valid_data = ~ref_data.mask if hasattr(ref_data, 'mask') else ~np.isnan(ref_data)
        valid_count = np.sum(valid_data)
        logging.info(f"Valid reflectivity points: {valid_count} out of {ref_data.size}")
        
        if valid_count == 0:
            logging.warning("No valid reflectivity data found")
            return Response("No valid radar data", status=500)
        
        # Create high-resolution plot without axes/labels for overlay
        fig, ax = plt.subplots(figsize=(8, 8), dpi=200)
        disp = pyart.graph.RadarMapDisplay(radar)
        
        # Plot with higher resolution and no decorations
        plot = disp.plot_ppi(
            field="reflectivity",
            sweep=sweep_idx,
            vmin=-10, vmax=65,  # Adjusted range for better visibility
            cmap="NWSRef",
            ax=ax,
            colorbar_flag=False,  # Remove colorbar
            mask_outside=False,   # Don't mask data outside range
            title_flag=False      # No title
        )
        
        # Set the range to show full radar coverage (460km diameter)
        ax.set_xlim(-230000, 230000)  # 230km range in meters
        ax.set_ylim(-230000, 230000)
        ax.axis('off')
        ax.set_aspect('equal')
        
        # Remove any remaining plot elements
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlabel('')
        ax.set_ylabel('')
        ax.set_title('')
        
        # Make background transparent
        fig.patch.set_alpha(0)
        ax.patch.set_alpha(0)
        
        # Save as PNG
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight",
                   transparent=True, pad_inches=0, dpi=200,
                   facecolor='none', edgecolor='none')
        plt.close(fig)
        
        buf.seek(0)
        image_size = len(buf.getvalue())
        logging.info(f"Generated radar image: {image_size} bytes")
        
        buf.seek(0)
        return Response(buf.getvalue(), mimetype='image/png')
    
    except Exception as e:
        logging.exception("Error generating radar image")
        return Response("Error generating image", status=500)

@app.route('/api/radar_bounds')
def radar_bounds():
    """Get radar coverage bounds for image overlay"""
    try:
        # Calculate bounds for 230km radar range
        range_km = 230
        lat_offset = range_km * 1000 / 111320.0  # Convert to degrees
        lon_offset = range_km * 1000 / (111320.0 * np.cos(np.deg2rad(RADAR_LAT)))
        
        bounds = {
            'north': RADAR_LAT + lat_offset,
            'south': RADAR_LAT - lat_offset,
            'east': RADAR_LON + lon_offset,
            'west': RADAR_LON - lon_offset
        }
        
        logging.info(f"Radar bounds: {bounds}")
        return jsonify(bounds)
    
    except Exception as e:
        logging.exception("Error calculating radar bounds")
        return jsonify({'error': str(e)}), 500

@app.route('/test_image')
def test_image():
    """Test endpoint to verify image generation"""
    try:
        # Create a simple test image
        fig, ax = plt.subplots(figsize=(6, 6), dpi=100)
        ax.text(0.5, 0.5, 'Test Radar Image', ha='center', va='center',
                fontsize=20, color='red', transform=ax.transAxes)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        fig.patch.set_alpha(0)
        
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight",
                   transparent=True, pad_inches=0, dpi=100,
                   facecolor='none', edgecolor='none')
        plt.close(fig)
        
        buf.seek(0)
        return Response(buf.getvalue(), mimetype='image/png')
    
    except Exception as e:
        logging.exception("Error generating test image")
        return Response("Error generating test image", status=500)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
