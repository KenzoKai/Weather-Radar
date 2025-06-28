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
from sklearn.cluster import DBSCAN
from scipy.spatial import ConvexHull
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from flask import Flask, Response, request, render_template, jsonify
from flask_socketio import SocketIO, emit
from botocore.config import Config
from botocore import UNSIGNED
from pyart.io.nexrad_archive import read_nexrad_archive
import threading

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
app.config['SECRET_KEY'] = 'radar_secret_key_2024'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global variables for streaming
streaming_active = False
current_radar_data = None
last_volume_key = None

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
    """Create radar overlay with clustered topographical contours"""
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
        lat_offset = y / 111320.0  # meters to degrees latitude
        lon_offset = x / (111320.0 * np.cos(np.deg2rad(RADAR_LAT)))
        
        lats = RADAR_LAT + lat_offset
        lons = RADAR_LON + lon_offset
        
        # Define dBZ levels for clustering
        dbz_levels = [
            {'min': 7, 'max': 15, 'color': '#02FD02', 'bg_color': '#014A01', 'name': 'Light'},
            {'min': 15, 'max': 25, 'color': '#01C501', 'bg_color': '#006300', 'name': 'Moderate'},
            {'min': 25, 'max': 35, 'color': '#FDF802', 'bg_color': '#7D7C01', 'name': 'Heavy'},
            {'min': 35, 'max': 45, 'color': '#FD9500', 'bg_color': '#7D4A00', 'name': 'Very Heavy'},
            {'min': 45, 'max': 55, 'color': '#FD0000', 'bg_color': '#7D0000', 'name': 'Intense'},
            {'min': 55, 'max': 100, 'color': '#FD00FD', 'bg_color': '#4A0080', 'name': 'Extreme'}
        ]
        
        overlay_data = []
        contour_clusters = []
        mask = ~ref_data.mask if hasattr(ref_data, 'mask') else np.ones_like(ref_data, dtype=bool)
        
        max_i = min(ref_data.shape[0], lats.shape[0])
        max_j = min(ref_data.shape[1], lats.shape[1])
        
        # Collect all valid data points with their coordinates
        all_points = []
        for i in range(0, max_i, sampling_step):
            for j in range(0, max_j, sampling_step):
                if (i < mask.shape[0] and j < mask.shape[1] and
                    mask[i, j] and ref_data[i, j] >= min_dbz_threshold):
                    
                    dbz_value = float(ref_data[i, j])
                    lat = float(lats[i, j])
                    lon = float(lons[i, j])
                    
                    all_points.append({
                        'lat': lat,
                        'lon': lon,
                        'dbz': dbz_value,
                        'color': get_reflectivity_color(dbz_value)
                    })
                    
                    overlay_data.append({
                        'lat': lat,
                        'lon': lon,
                        'value': dbz_value,
                        'color': get_reflectivity_color(dbz_value)
                    })
        
        # Process dBZ levels in reverse order (highest to lowest) for proper topographical layering
        # This creates nested contours where higher intensities are inside lower intensities
        for level_idx, level in enumerate(reversed(dbz_levels)):
            # For topographical contours, include all points >= this level's minimum
            # This creates the layered effect where each contour encompasses all higher intensities
            level_points = [p for p in all_points if p['dbz'] >= level['min']]
            
            if len(level_points) < 3:  # Need minimum points for clustering
                continue
                
            # Adjust level_idx for reversed processing
            actual_level_idx = len(dbz_levels) - 1 - level_idx
            logging.info(f"Processing topographical layer dBZ {level['min']}+: {len(level_points)} points")
            
            # Convert to coordinate arrays for clustering and calculate distances from radar
            coords = np.array([[p['lat'], p['lon']] for p in level_points])
            
            # Calculate distance from radar center for each point
            distances = []
            for p in level_points:
                # Calculate distance in degrees (approximate)
                lat_diff = p['lat'] - RADAR_LAT
                lon_diff = p['lon'] - RADAR_LON
                distance = np.sqrt(lat_diff**2 + lon_diff**2)
                distances.append(distance)
            
            distances = np.array(distances)
            
            # Adaptive clustering based on distance from radar center
            # Points farther from radar need larger clustering distances due to beam spreading
            base_eps_values = {
                'light': 0.025,    # Base eps for light precipitation
                'moderate': 0.02,  # Base eps for moderate precipitation
                'heavy': 0.015     # Base eps for heavy precipitation
            }
            
            if level['min'] < 15:  # Light precipitation
                base_eps = base_eps_values['light']
                base_min_samples = max(2, min(5, len(level_points) // 30))
            elif level['min'] < 35:  # Moderate to heavy
                base_eps = base_eps_values['moderate']
                base_min_samples = max(2, min(4, len(level_points) // 25))
            else:  # Very heavy to extreme
                base_eps = base_eps_values['heavy']
                base_min_samples = max(2, min(3, len(level_points) // 15))
            
            # Adaptive eps based on distance - increase clustering distance for farther points
            # Points closer than 1 degree use base eps, farther points get progressively larger eps
            adaptive_eps = []
            for dist in distances:
                if dist < 1.0:  # Close to radar (< ~111km)
                    eps_factor = 1.0
                elif dist < 2.0:  # Medium distance (111-222km)
                    eps_factor = 1.5
                else:  # Far from radar (> 222km)
                    eps_factor = 2.0
                
                adaptive_eps.append(base_eps * eps_factor)
            
            # Use the maximum adaptive eps for this cluster level
            eps = max(adaptive_eps) if adaptive_eps else base_eps
            min_samples = max(2, min(base_min_samples, len(level_points) // 4))
            
            clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(coords)
            labels = clustering.labels_
            
            # Debug information
            unique_labels = set(labels)
            n_clusters = len(unique_labels) - (1 if -1 in labels else 0)
            n_noise = list(labels).count(-1)
            logging.info(f"dBZ {level['min']}-{level['max']}: {n_clusters} clusters, {n_noise} noise points (eps={eps}, min_samples={min_samples})")
            
            # Process each cluster
            for label in unique_labels:
                if label == -1:  # Skip noise points
                    continue
                    
                # Get points in this cluster
                cluster_mask = labels == label
                cluster_coords = coords[cluster_mask]
                cluster_points = [level_points[i] for i in range(len(level_points)) if cluster_mask[i]]
                
                if len(cluster_coords) < 2:
                    continue
                
                # Create contour polygon for this cluster
                try:
                    # Convert to Shapely points (lon, lat for Shapely)
                    points_shapely = [Point(cluster_coords[i][1], cluster_coords[i][0]) for i in range(len(cluster_coords))]
                    
                    # Calculate average distance from radar for this cluster
                    cluster_distances = [distances[i] for i in range(len(level_points)) if cluster_mask[i]]
                    avg_distance = np.mean(cluster_distances) if cluster_distances else 0
                    
                    # Adjust buffer size based on dBZ level, cluster size, and distance from radar
                    cluster_size_factor = min(1.5, len(cluster_coords) / 5.0)
                    
                    # Distance-based buffer scaling - farther points get larger buffers
                    if avg_distance < 1.0:  # Close to radar
                        distance_factor = 1.0
                    elif avg_distance < 2.0:  # Medium distance
                        distance_factor = 1.3
                    else:  # Far from radar
                        distance_factor = 1.6
                    
                    if level['min'] < 15:  # Light precipitation
                        base_buffer = 0.008
                    elif level['min'] < 35:  # Moderate to heavy
                        base_buffer = 0.006
                    else:  # Very heavy to extreme
                        base_buffer = 0.005
                    
                    buffer_size = base_buffer * cluster_size_factor * distance_factor
                    
                    # Create individual buffers and union them
                    buffered_points = [point.buffer(buffer_size) for point in points_shapely]
                    cluster_polygon = unary_union(buffered_points)
                    
                    # Apply smoothing by using a smaller simplification tolerance
                    # and adding a small secondary buffer to smooth sharp corners
                    tolerance = buffer_size * 0.15  # Much smaller tolerance for smoother curves
                    cluster_polygon = cluster_polygon.simplify(tolerance, preserve_topology=True)
                    
                    # Apply a small secondary buffer and negative buffer to smooth corners
                    smooth_buffer = buffer_size * 0.1  # Small smoothing buffer
                    cluster_polygon = cluster_polygon.buffer(smooth_buffer).buffer(-smooth_buffer)
                    
                    # Convert back to lat/lon coordinates for frontend
                    if hasattr(cluster_polygon, 'exterior'):
                        # Single polygon
                        exterior_coords = list(cluster_polygon.exterior.coords)
                        polygon_coords = [[coord[1], coord[0]] for coord in exterior_coords]
                        
                        contour_clusters.append({
                            'polygon': polygon_coords,
                            'dbz_range': f"{level['min']}-{level['max']} dBZ",
                            'color': level['color'],
                            'bg_color': level['bg_color'],
                            'name': level['name'],
                            'min_dbz': level['min'],
                            'max_dbz': level['max'],
                            'cluster_id': f"level_{actual_level_idx}_cluster_{label}",
                            'point_count': len(cluster_points)
                        })
                    elif hasattr(cluster_polygon, 'geoms'):
                        # Multiple polygons (MultiPolygon)
                        for i, poly in enumerate(cluster_polygon.geoms):
                            if hasattr(poly, 'exterior') and poly.area > 0.000001:
                                simplified_poly = poly.simplify(tolerance, preserve_topology=True)
                                if hasattr(simplified_poly, 'exterior'):
                                    exterior_coords = list(simplified_poly.exterior.coords)
                                    polygon_coords = [[coord[1], coord[0]] for coord in exterior_coords]
                                    
                                    contour_clusters.append({
                                        'polygon': polygon_coords,
                                        'dbz_range': f"{level['min']}-{level['max']} dBZ",
                                        'color': level['color'],
                                        'bg_color': level['bg_color'],
                                        'name': level['name'],
                                        'min_dbz': level['min'],
                                        'max_dbz': level['max'],
                                        'cluster_id': f"level_{actual_level_idx}_cluster_{label}_part_{i}",
                                        'point_count': len(cluster_points)
                                    })
                
                except Exception as e:
                    logging.warning(f"Error creating contour for cluster {label} in level {level['name']}: {e}")
                    continue
        
        logging.info(f"Created overlay with {len(overlay_data)} points and {len(contour_clusters)} contour clusters")
        return {
            'points': overlay_data,
            'contours': contour_clusters
        }
    
    except Exception as e:
        logging.exception("Error creating radar overlay")
        return {'points': [], 'contours': []}

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

@app.route('/api/radar_status')
def radar_status():
    """Get current radar scanning status and azimuth information"""
    try:
        radar, timestamp = get_radar_data()
        if radar is None:
            return jsonify({'error': 'No radar data available'}), 500
        
        # Get the latest sweep information
        latest_sweep = radar.nsweeps - 1
        azimuth_data = radar.azimuth['data'][radar.get_start_end(latest_sweep)[0]:radar.get_start_end(latest_sweep)[1]]
        
        # Calculate current scanning position (simulate real-time)
        import time
        current_time = time.time()
        # Simulate 6 RPM (10 seconds per full rotation)
        rotation_period = 10.0  # seconds
        current_angle = ((current_time % rotation_period) / rotation_period) * 360
        
        return jsonify({
            'success': True,
            'current_azimuth': current_angle,
            'sweep_count': radar.nsweeps,
            'azimuth_range': {
                'min': float(np.min(azimuth_data)),
                'max': float(np.max(azimuth_data))
            },
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S %Z'),
            'scanning': True
        })
    
    except Exception as e:
        logging.exception("Error getting radar status")
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

# WebSocket event handlers
@socketio.on('connect')
def handle_connect():
    logging.info('Client connected')
    emit('status', {'message': 'Connected to radar stream'})

@socketio.on('disconnect')
def handle_disconnect():
    logging.info('Client disconnected')

@socketio.on('start_streaming')
def handle_start_streaming(data):
    global streaming_active
    streaming_active = True
    
    # Get filter parameters
    elevation = data.get('elevation', 0.5)
    threshold = data.get('threshold', 7.0)
    density = data.get('density', 2)
    
    logging.info(f"Starting radar stream with elev={elevation}, threshold={threshold}, density={density}")
    
    # Start background streaming thread
    thread = threading.Thread(target=stream_radar_data, args=(elevation, threshold, density))
    thread.daemon = True
    thread.start()

@socketio.on('stop_streaming')
def handle_stop_streaming():
    global streaming_active
    streaming_active = False
    logging.info('Stopping radar stream')

@socketio.on('update_filters')
def handle_update_filters(data):
    # Emit updated radar data with new filters
    if current_radar_data:
        elevation = data.get('elevation', 0.5)
        threshold = data.get('threshold', 7.0)
        density = data.get('density', 2)
        
        try:
            radar, timestamp = current_radar_data
            angles = radar.fixed_angle['data']
            sweep_idx = int(np.argmin(np.abs(angles - elevation)))
            
            radar_data = create_radar_overlay(radar, sweep_idx, threshold, density)
            
            emit('radar_data', {
                'success': True,
                'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S %Z'),
                'elevation': float(angles[sweep_idx]),
                'overlay_data': radar_data['points'],
                'contour_zones': radar_data['contours'],
                'filter_info': {
                    'min_dbz': threshold,
                    'density': density,
                    'point_count': len(radar_data['points']),
                    'contour_count': len(radar_data['contours'])
                }
            })
        except Exception as e:
            emit('error', {'message': str(e)})

def stream_radar_data(elevation, threshold, density):
    """Background function to stream radar data via WebSocket"""
    global streaming_active, current_radar_data, last_volume_key
    
    while streaming_active:
        try:
            # Check for new radar data
            key = latest_volume_key()
            if key and key != last_volume_key:
                logging.info(f"New radar volume detected: {key}")
                last_volume_key = key
                
                # Get and process radar data
                radar, timestamp = get_radar_data()
                if radar:
                    current_radar_data = (radar, timestamp)
                    
                    # Process data with current filters
                    angles = radar.fixed_angle['data']
                    sweep_idx = int(np.argmin(np.abs(angles - elevation)))
                    
                    radar_data = create_radar_overlay(radar, sweep_idx, threshold, density)
                    
                    # Emit radar data to all connected clients
                    socketio.emit('radar_data', {
                        'success': True,
                        'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S %Z'),
                        'elevation': float(angles[sweep_idx]),
                        'overlay_data': radar_data['points'],
                        'contour_zones': radar_data['contours'],
                        'filter_info': {
                            'min_dbz': threshold,
                            'density': density,
                            'point_count': len(radar_data['points']),
                            'contour_count': len(radar_data['contours'])
                        }
                    })
                    
                    # Emit sweep animation data
                    current_time = time.time()
                    rotation_period = 10.0  # 10 seconds per rotation
                    current_angle = ((current_time % rotation_period) / rotation_period) * 360
                    
                    socketio.emit('sweep_update', {
                        'azimuth': current_angle,
                        'scanning': True
                    })
            
            # Sleep before checking again
            time.sleep(2)  # Check every 2 seconds
            
        except Exception as e:
            logging.exception("Error in radar streaming")
            socketio.emit('error', {'message': str(e)})
            time.sleep(5)  # Wait longer on error

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
