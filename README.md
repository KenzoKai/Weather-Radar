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
