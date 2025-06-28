# Weather Radar Web Application

A sophisticated web application that displays NEXRAD weather radar data with advanced topographical contour visualization overlayed on an interactive map. This application fetches real-time radar data from NOAA's AWS S3 bucket and creates professional-grade topographical contours with distance-adaptive clustering.

<img src="https://github.com/KenzoKai/Weather-Radar/blob/main/nexrad1.png?raw=true" alt="KenzoRadar" width="100%">
<p>
<img src="https://github.com/KenzoKai/Weather-Radar/blob/main/nexrad2.png?raw=true" alt="KenzoRadar" width="260" hspace="10">
<img src="https://github.com/KenzoKai/Weather-Radar/blob/main/nexrad3.png?raw=true" alt="KenzoRadar" width="260" hspace="10">
<img src="https://github.com/KenzoKai/Weather-Radar/blob/main/nexrad4.png?raw=true" alt="KenzoRadar" width="260" hspace="10">
</p>
## Features

### Core Functionality
- **Real-time Radar Data**: Fetches the latest NEXRAD Level II data from NOAA
- **Interactive Map**: Uses Leaflet.js for smooth map interaction with dark/light themes
- **WebSocket Streaming**: Real-time data updates via Socket.IO
- **Multiple Elevation Angles**: Choose from different radar sweep elevations (0.5° to 19.5°)
- **Radar Sweep Animation**: Live rotating beam visualization

### Advanced Topographical Contours
- **Nested Contour Layers**: True topographical-style contours where higher intensities are nested within lower intensities
- **Distance-Adaptive Clustering**: Intelligent clustering that adapts to radar beam spreading at longer ranges
- **DBSCAN Clustering Algorithm**: Groups nearby precipitation points for coherent contour boundaries
- **Smooth Polygon Rendering**: Advanced polygon simplification with rounded corners and edges
- **Six dBZ Intensity Levels**: Light (7-15), Moderate (15-25), Heavy (25-35), Very Heavy (35-45), Intense (45-55), Extreme (55+)

### Interactive Controls
- **Data Filtering**: Adjustable dBZ threshold and data density controls
- **Opacity Control**: Separate opacity controls for point overlays and contour layers
- **Auto-refresh**: Configurable automatic data updates
- **Manual Refresh**: On-demand data refresh capability

## Current Configuration

- **Radar Site**: KMOB (Mobile, Alabama)
- **Location**: 30.6794°N, 88.2397°W
- **Data Source**: NOAA NEXRAD Level II (AWS S3)
- **Update Frequency**: Real-time via WebSocket with 30-second polling

## Installation

1. **Clone or download the project files**

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**:
   ```bash
   python app.py
   ```

4. **Open your web browser** and navigate to:
   ```
   http://localhost:5000
   ```

## Usage

### Web Interface Controls

- **Elevation Angle**: Select different radar sweep angles (0.5° to 19.5°)
- **Radar Opacity**: Adjust the transparency of radar overlays
- **Min dBZ Threshold**: Filter out weak returns (-10 to 15 dBZ)
- **Data Density**: Control point sampling (every 1st to 4th point)
- **Auto-refresh**: Toggle automatic data updates
- **Sweep Animation**: Enable/disable rotating radar beam visualization

### API Endpoints

- `GET /`: Main web interface
- `GET /api/radar_data`: JSON radar data with contour information
- `GET /api/radar_image`: PNG radar image (fallback)
- `GET /api/radar_bounds`: Radar coverage boundary information
- `GET /api/radar_status`: Current radar scanning status
- **WebSocket Events**: Real-time data streaming via Socket.IO

## Technical Implementation

### Topographical Contour System

#### 1. **Nested Contour Logic**
```python
# Processes dBZ levels from highest to lowest intensity
# Each contour encompasses ALL precipitation >= that intensity level
for level in reversed(dbz_levels):
    level_points = [p for p in all_points if p['dbz'] >= level['min']]
```

#### 2. **Distance-Adaptive Clustering**
- **Close range (< 111km)**: Standard clustering parameters
- **Medium range (111-222km)**: 1.5x larger clustering distance, 1.3x larger buffers
- **Long range (> 222km)**: 2.0x larger clustering distance, 1.6x larger buffers

#### 3. **DBSCAN Clustering Parameters**
- **Light precipitation (7-15 dBZ)**: 2.5km clustering radius, very lenient grouping
- **Moderate to heavy (15-35 dBZ)**: 2km clustering radius, moderate grouping
- **Very heavy to extreme (35+ dBZ)**: 1.5km clustering radius, tighter grouping

#### 4. **Polygon Smoothing**
- **Douglas-Peucker simplification**: Reduces angular edges while preserving shape
- **Secondary buffer smoothing**: Eliminates sharp corners with positive/negative buffering
- **Leaflet rendering enhancements**: Increased smoothFactor with rounded line caps/joins

### Data Processing Pipeline

1. **Data Retrieval**: Downloads latest NEXRAD Level II files from AWS S3
2. **Decompression**: Handles gzipped radar files automatically
3. **Radar Processing**: Uses PyART (Python ARM Radar Toolkit) for data parsing
4. **Coordinate Conversion**: Converts polar radar coordinates to geographic lat/lon
5. **Clustering Analysis**: Groups nearby points using distance-adaptive DBSCAN
6. **Contour Generation**: Creates smooth polygons using Shapely geometric operations
7. **Topographical Layering**: Renders nested contours from lowest to highest intensity

### Real-time Streaming

- **WebSocket Communication**: Bidirectional real-time data streaming
- **Background Processing**: Separate thread monitors for new radar volumes
- **Efficient Updates**: Only streams new data when radar volumes change
- **Client Synchronization**: All connected clients receive simultaneous updates

## Customization

### Changing Radar Site

To use a different NEXRAD radar site, modify these variables in `app.py`:

```python
SITE = "KXXX"  # Replace with desired radar site code
RADAR_LAT = XX.XXXX  # Radar latitude
RADAR_LON = -XX.XXXX  # Radar longitude
```

### Adjusting Clustering Parameters

Modify clustering sensitivity in the `create_radar_overlay()` function:

```python
# Adjust eps (clustering distance) and min_samples for different behaviors
if level['min'] < 15:  # Light precipitation
    eps = 0.025  # Increase for larger clusters
    min_samples = max(2, min(5, len(level_points) // 30))
```

### Customizing Contour Appearance

Modify dBZ levels and colors in `app.py`:

```python
dbz_levels = [
    {'min': 7, 'max': 15, 'color': '#02FD02', 'bg_color': '#014A01', 'name': 'Light'},
    # Add or modify levels as needed
]
```

## Dependencies

### Backend (Python)
- **Flask**: Web framework and API endpoints
- **Flask-SocketIO**: Real-time WebSocket communication
- **PyART**: Advanced radar data processing
- **Boto3**: AWS S3 access for NEXRAD data
- **NumPy**: Numerical computations and array operations
- **Matplotlib**: Color mapping and image generation
- **scikit-learn**: DBSCAN clustering algorithm
- **Shapely**: Advanced geometric operations and polygon processing

### Frontend (JavaScript)
- **Leaflet.js**: Interactive mapping and overlay rendering
- **Socket.IO**: Real-time client-server communication

## Data Sources

- **NEXRAD Level II Data**: NOAA via AWS S3 (`noaa-nexrad-level2` bucket)
- **Map Tiles**: OpenStreetMap and CartoDB (dark theme)
- **Radar Locations**: National Weather Service

## Browser Compatibility

- Modern browsers with JavaScript and WebSocket support
- Tested on Chrome, Firefox, Safari, and Edge
- Mobile-responsive design with touch-friendly controls

## Performance Optimization

### Data Sampling
- Configurable point density to balance detail vs. performance
- Intelligent filtering based on dBZ thresholds
- Efficient coordinate transformation algorithms

### Clustering Optimization
- Adaptive parameters based on data density
- Distance-based clustering for radar beam characteristics
- Polygon simplification to reduce rendering complexity

### Real-time Efficiency
- WebSocket streaming eliminates polling overhead
- Background processing prevents UI blocking
- Incremental updates only when new data is available

## Troubleshooting

### No Radar Data Available
- Check if the radar site is operational
- Verify internet connection for AWS S3 access
- Some radar sites may have temporary outages

### Clustering Issues
- Adjust clustering parameters for your specific use case
- Check console logs for clustering statistics
- Verify sufficient data points for meaningful clusters

### Performance Issues
- Reduce data density setting for better performance
- Increase dBZ threshold to filter weak returns
- Consider using fewer elevation angles

### WebSocket Connection Problems
- Check firewall settings for WebSocket traffic
- Verify Socket.IO client/server version compatibility
- Monitor browser console for connection errors

## License

This project uses publicly available NOAA weather data and open-source libraries. Please respect the terms of service for all data sources and dependencies.

## Contributing

Contributions are welcome! Please consider:
- Improving clustering algorithms
- Adding new visualization features
- Optimizing performance
- Supporting additional radar sites
- Enhancing mobile experience

## Acknowledgments

- **NOAA**: For providing free access to NEXRAD radar data
- **PyART Community**: For excellent radar data processing tools
- **Leaflet.js**: For powerful mapping capabilities
- **scikit-learn**: For robust clustering algorithms


