"""Write a small labelgui base data directory for the bundle's smoke test.

    python packaging/make_sample_job.py DIRECTORY

DIRECTORY gets user `smoke` with a job of two short MP4 videos and the SVG bird sketch
from example/.
"""

import shutil
import sys
from pathlib import Path

import imageio.v3 as iio
import numpy as np

example = Path(__file__).resolve().parents[1] / "example"
base = Path(sys.argv[1])
job = base / "data" / "user" / "smoke"
(job / "recordings").mkdir(parents=True, exist_ok=True)
(base / "user").mkdir(exist_ok=True)

frames = np.zeros((10, 64, 64, 3), dtype=np.uint8)
frames[:, 16:48, 16:48] = np.linspace(0, 255, 10, dtype=np.uint8)[:, None, None, None]
for camera in range(2):
    iio.imwrite(job / "recordings" / f"camera_{camera}.mp4", frames, plugin="pyav", codec="libx264", fps=10)

shutil.copytree(example / "images", job / "images", dirs_exist_ok=True)
shutil.copy(example / "sketch_svg.yml", job)
(job / "labelgui_cfg.yml").write_text(
    "recording_folder: recordings\n"
    "recording_filenames: [camera_0.mp4, camera_1.mp4]\n"
    "sketch_files: [sketch_svg.yml]\n"
    "dataset_name: smoke\n"
    "exit_save_labels: false\n"
)
