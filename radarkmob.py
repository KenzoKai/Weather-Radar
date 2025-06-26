#!/usr/bin/env python3
import os
import io
import gzip
import shutil
import logging
import tempfile
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
import numpy as np
import pyart
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from flask import Flask, Response, request
from botocore.config import Config
from botocore import UNSIGNED
from pyart.io.nexrad_archive import read_nexrad_archive

# ——————————————
# Configuration
# ——————————————
BUCKET        = "noaa-nexrad-level2"
SITE          = "KMOB"
POLL_INTERVAL = 1                   # seconds between checks
LOCAL_TZ      = ZoneInfo("America/Chicago")
FIG_SIZE      = (10, 10)            # inches → 2000×2000 px at 200 dpi
FIG_DPI       = 200

# ——————————————
# Logging
# ——————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.getLogger("botocore").setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.INFO)

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
    vols = list_today_volumes()
    if not vols:
        return None
    return max(vols, key=lambda o: o["LastModified"])["Key"]

def parse_timestamp_from_key(key: str) -> datetime:
    base = os.path.basename(key)
    ts = base[len(SITE):len(SITE)+15]  # "YYYYMMDD_HHMMSS"
    dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
    return dt.replace(tzinfo=ZoneInfo("UTC"))

def frame_generator():
    last_key   = None
    last_frame = None

    while True:
        try:
            key = latest_volume_key()
            if not key:
                time.sleep(POLL_INTERVAL)
                continue

            if key == last_key and last_frame is not None:
                yield last_frame
                time.sleep(POLL_INTERVAL)
                continue

            logging.info(f"New volume detected: {key}")
            last_key = key

            # 1) download
            fd, download_path = tempfile.mkstemp(prefix="vol_", suffix=None)
            os.close(fd)
            s3.download_file(BUCKET, key, download_path)

            # 2) detect gzip
            with open(download_path, "rb") as f:
                magic = f.read(2)

            if magic == b"\x1f\x8b":
                fd, raw_path = tempfile.mkstemp(prefix="vol_dec_")
                os.close(fd)
                with gzip.open(download_path, "rb") as gf, open(raw_path, "wb") as rf:
                    shutil.copyfileobj(gf, rf)
                os.remove(download_path)
            else:
                raw_path = download_path  # not gzipped

            # 3) read with Py-ART
            try:
                radar = pyart.io.read(raw_path)
            except Exception:
                radar = read_nexrad_archive(raw_path, delay_field_loading=True)

            os.remove(raw_path)

            # 4) choose sweep based on elevation query param
            desired_elev = request.args.get("elev", default=0.2, type=float)
            angles = radar.fixed_angle["data"]  # array of tilt angles
            sweep_idx = int(np.argmin(np.abs(angles - desired_elev)))
            logging.debug(f"Selected sweep {sweep_idx} at {angles[sweep_idx]}° for requested {desired_elev}°")

            # 5) build title
            utc_dt = parse_timestamp_from_key(key)
            local_dt = utc_dt.astimezone(LOCAL_TZ)
            title = (
                f"{SITE} {angles[sweep_idx]:.1f}° Elevation   "
                f"{local_dt:%Y-%m-%d %H:%M:%S %Z}\n"
                "Equivalent reflectivity factor"
            )

            # 6) plot
            fig, ax = plt.subplots(figsize=FIG_SIZE, dpi=FIG_DPI)
            disp = pyart.graph.RadarMapDisplay(radar)
            disp.plot_ppi(
                field="reflectivity",
                sweep=sweep_idx,
                vmin=-20, vmax=70,
                cmap="NWSRef",
                ax=ax,
                raster=True
            )
            # North arrow
            ax.annotate(
                "", xy=(0.1, 0.25), xytext=(0.1, 0.1),
                xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", lw=3, color="black")
            )
            ax.text(
                0.1, 0.27, "N",
                transform=ax.transAxes,
                ha="center", va="bottom",
                fontsize=24, fontweight="bold"
            )

            ax.set_title(title, fontsize=12)
            ax.axis("off")

            buf = io.BytesIO()
            fig.savefig(buf, format="jpeg", bbox_inches="tight", pad_inches=0)
            plt.close(fig)
            jpg = buf.getvalue()

            frame = (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" +
                jpg +
                b"\r\n"
            )
            last_frame = frame
            yield frame

        except Exception:
            logging.exception("Error generating frame; retrying…")
        finally:
            time.sleep(POLL_INTERVAL)

@app.route("/radar_stream")
def radar_stream():
    return Response(
        frame_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
