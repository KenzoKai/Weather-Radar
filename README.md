<<<<<<< HEAD
# Weather Radar Web Application

A modern web application that displays NEXRAD weather radar data overlayed on an interactive map. This application fetches real-time radar data from NOAA's AWS S3 bucket and displays it on a Leaflet map with accurate geographic positioning.

## Features

- **Real-time Radar Data**: Fetches the latest NEXRAD Level II data from NOAA
- **Interactive Map**: Uses Leaflet.js for smooth map interaction
- **Multiple Elevation Angles**: Choose from different radar sweep elevations
- **Auto-refresh**: Automatically updates every 30 seconds
- **Adjustable Opacity**: Control radar overlay transparency
- **Color-coded Reflectivity**: Standard NWS color scale for precipitation intensity
- **Dark/Light Map Themes**: Toggle between map styles for better visibility

## Current Configuration

- **Radar Site**: KMOB (Mobile, Alabama)
- **Location**: 30.6794°N, 88.2397°W
- **Data Source**: NOAA NEXRAD Level II (AWS S3)

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

### Web Interface

- **Elevation Angle**: Select different radar sweep angles (0.5° to 19.5°)
- **Radar Opacity**: Adjust the transparency of the radar overlay
- **Auto-refresh**: Toggle automatic data updates every 30 seconds
- **Refresh Data**: Manually refresh the radar data
- **Map Controls**: Zoom, pan, and switch between map themes

### API Endpoints

- `GET /`: Main web interface
- `GET /api/radar_data?elev=<angle>`: JSON radar data for map overlay
- `GET /api/radar_image?elev=<angle>`: PNG radar image (fallback)

## Technical Details

### Data Processing

1. **Data Retrieval**: Downloads latest NEXRAD Level II files from AWS S3
2. **Decompression**: Handles gzipped radar files automatically
3. **Radar Processing**: Uses PyART (Python ARM Radar Toolkit) for data parsing
4. **Coordinate Conversion**: Converts polar radar coordinates to geographic lat/lon
5. **Color Mapping**: Applies NWS standard reflectivity color scale

### Map Overlay

- **Point-based Rendering**: Each radar gate becomes a colored circle marker
- **Geographic Accuracy**: Proper coordinate transformation for accurate positioning
- **Performance Optimization**: Data sampling to reduce overlay complexity
- **Interactive Tooltips**: Click points to see reflectivity values

## Customization

### Changing Radar Site

To use a different NEXRAD radar site, modify these variables in `app.py`:

```python
SITE = "KXXX"  # Replace with desired radar site code
RADAR_LAT = XX.XXXX  # Radar latitude
RADAR_LON = -XX.XXXX  # Radar longitude
```

### Adjusting Update Frequency

Change the polling interval in `app.py`:

```python
POLL_INTERVAL = 30  # seconds between checks
```

### Map Styling

The application includes both light and dark map themes. You can modify the base layers in the HTML template or add additional tile providers.

## Dependencies

- **Flask**: Web framework
- **PyART**: Radar data processing
- **Boto3**: AWS S3 access
- **NumPy**: Numerical computations
- **Matplotlib**: Color mapping and image generation
- **Leaflet.js**: Interactive mapping (loaded via CDN)

## Data Sources

- **NEXRAD Level II Data**: NOAA via AWS S3 (`noaa-nexrad-level2` bucket)
- **Map Tiles**: OpenStreetMap and CartoDB
- **Radar Locations**: National Weather Service

## Browser Compatibility

- Modern browsers with JavaScript enabled
- Tested on Chrome, Firefox, Safari, and Edge
- Mobile-responsive design

## Troubleshooting

### No Radar Data Available

- Check if the radar site is operational
- Verify internet connection for AWS S3 access
- Some radar sites may have temporary outages

### Slow Loading

- Large radar files can take time to download and process
- Consider adjusting the data sampling rate in the `create_radar_overlay()` function

### Map Not Loading

- Ensure internet connection for map tile downloads
- Check browser console for JavaScript errors

## License

This project uses publicly available NOAA weather data and open-source libraries. Please respect the terms of service for all data sources and dependencies.
=======
# Radar MJPEG Streaming Flask App

This Flask application streams real-time NEXRAD Level-II radar data as an MJPEG series of images, rendering a 2000×2000 px reflectivity PPI with a North arrow and local timestamp. You can select the radar elevation angle (tilt) on the fly via a URL parameter.

---

## Features

* **Live MJPEG stream** of the most recent full-volume radar scan (`_V06`) from the NOAA Level-II S3 bucket.
* **Custom elevation**: choose any tilt (default ≈ 0.2°) by requesting `?elev=<angle>` (e.g. `?elev=0.9`).
* **High resolution**: 2000×2000 px output (10 in × 10 in @ 200 dpi).
* **North arrow** overlay in the lower-left corner.
* **Local time** title: timestamps parsed from the file name and converted to your timezone (America/Chicago by default).
* **Zero front-end code**: just point any browser or `<img>` to the `/radar_stream` endpoint.

---

## Requirements

* Python 3.9+
* Flask
* boto3
* botocore
* pyart
* matplotlib
* numpy

Install via:

```bash
pip install flask boto3 botocore numpy matplotlib arm_pyart
```

(Note: `arm_pyart` may be the package name for Py-ART; adjust as needed.)

---

## Installation & Running

1. **Clone or copy** this script (e.g. `radar_stream.py`).

2. **Configure your environment**: ensure network access to S3, or set AWS credentials if required (the NOAA bucket allows unsigned access).

3. **Run**:

   ```bash
   python radar_stream.py
   ```

4. **Browse**:

   * Default tilt (≈ 0.2°): `http://localhost:5000/radar_stream`
   * Custom tilt (e.g. 0.9°): `http://localhost:5000/radar_stream?elev=0.9`

Embed in HTML:

```html
<img src="http://yourserver:5000/radar_stream?elev=0.9" alt="Radar 0.9° tilt">
```

---

## How It Works

1. **Polling** the NOAA Level-II bucket under `YYYY/MM/DD/SITE/` to find the newest `*_V06` file.
2. **Downloading** the file and detecting if it’s gzipped (via magic bytes); decompressing if needed.
3. **Reading** the Level-II volume with Py-ART (auto-detect, fallback to `read_nexrad_archive`).
4. **Selecting** the sweep index closest to the requested elevation.
5. **Rendering** a PPI plot with Matplotlib (`Agg` backend), adding the North arrow and title.
6. **Streaming** each frame as `multipart/x-mixed-replace` MJPEG—browsers show it as a live-updating image.

---

## Customization

* **Site**: change the `SITE` constant (e.g. `KTLX`, `KDFX`).
* **Timezone**: modify `LOCAL_TZ` to your preferred zone.
* **Resolution**: adjust `FIG_SIZE` and `FIG_DPI` for higher/lower output.
* **Poll interval**: tune `POLL_INTERVAL` for quicker or slower S3 checks.

---

## License

MIT © John Bradley
>>>>>>> 051dd2d8bf358609f3465520ba5e83c4721ff501
