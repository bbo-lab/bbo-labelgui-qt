"""Small file and video metadata helpers."""
import shutil
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

def copy_file(file_path: Path, target_dir: Path):
    shutil.copy(file_path, target_dir.as_posix())


def read_video_meta(reader):
    header = reader.get_meta_data()

    # Add required headers that are not normally part of standard video formats but are required information
    if "sensor" in header:
        header['offset'] = tuple(header['sensor']['offset'])
        header['sensorsize'] = tuple(header['sensor']['size'])
    else:
        logger.info('Inferring sensor size from image and setting offset to 0')
        shape = reader.get_data(0).shape
        header['sensorsize'] = (shape[1], shape[0], shape[2] if len(shape) > 2 else 1)
        header['offset'] = tuple(np.asarray([0, 0]))

    return header
