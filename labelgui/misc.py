from pathlib import Path
import shutil
import numpy as np
import yaml

from bbo.yaml import load as yaml_load


def save_cfg(save_path: Path, cfg):
    with open(save_path, "w") as yml_file:
        yaml.dump(cfg, yml_file, default_flow_style=False, sort_keys=False)


def archive_cfg(cfg, target_dir: Path):
    if isinstance(cfg, Path):
        shutil.copy(cfg, target_dir.as_posix())
        cfg = yaml_load(cfg)

    save_cfg(target_dir / "labelgui_cfg_processed.yml", cfg)


def read_video_meta(reader):
    header = reader.get_meta_data()

    # Add required headers that are not normally part of standard video formats but are required information
    if "sensor" in header:
        header['offset'] = tuple(header['sensor']['offset'])
        header['sensorsize'] = tuple(header['sensor']['size'])
    else:
        print("Infering sensor size from image and setting offset to 0!")
        header['sensorsize'] = (reader.get_data(0).shape[1], reader.get_data(0).shape[0], reader.get_data(0).shape[2])
        header['offset'] = tuple(np.asarray([0, 0]))

    return header