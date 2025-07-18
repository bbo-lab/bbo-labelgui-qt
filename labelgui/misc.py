import shutil
from pathlib import Path
import os

import numpy as np
import yaml
from bbo.yaml import load as yaml_load


def save_cfg(save_path: Path, cfg):
    with open(save_path, "w") as yml_file:
        yaml.dump(cfg, yml_file, default_flow_style=False, sort_keys=False)


def load_cfg(file_config: Path):
    if file_config.as_posix().endswith('yml'):
        return yaml_load(file_config)
    else:
        return read_cfg_from_py(file_config)


def archive_cfg(cfg, target_dir: Path):
    if isinstance(cfg, Path):
        shutil.copy(cfg, target_dir.as_posix())
        cfg = load_cfg(cfg)

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


def read_cfg_from_py(path: Path, save_yml=False):
    assert path.as_posix().endswith(".py"), "Invalid file format"
    with open(path.as_posix(), 'r') as cfg_file:
        config_txt = cfg_file.read()
        cfg_old = eval(config_txt)  # this is ugly since eval is used (make sure only trusted strings are evaluated)

    cfg_dict = {
        # SKETCH
        "sketch_files": [cfg_old['standardSketchFile']],

        # VIDEOS
        "dataset_name": "",  # If empty, takes name of recording folder
        "recording_folder": cfg_old['standardRecordingFolder'],
        "recording_filenames": cfg_old['standardRecordingFileNames'],

        "video_times": {i_rec: {
            # file: Either provide file with frame times or 'fps'
            "fps": 1,
            "offset": 0.0,
        }
            for i_rec, _ in enumerate(cfg_old['standardRecordingFileNames'])
        },

        # LABELS
        "load_labels_file": None,  # str: Give path to file or takes labels from canonical path
        "reference_labels_file": False,
        # bool or str: If True, takes ref labels from the canonical path. Or specify path to file

        # DATA SELECTION
        "allowed_cams": cfg_old['allowed_cams'],
        "min_time": cfg_old['minPose'],
        "max_time": cfg_old['maxPose'],
        "d_time": cfg_old['dFrame'],

        # DISPLAY
        "sketch_zoom_scale": cfg_old['sketchZoomScale'],

        # SAVE SETTINGS
        "exit_save_labels": cfg_old['exitSaveLabels'],
        "auto_save": cfg_old['autoSave'],
        "auto_save_N0": cfg_old['autoSaveN0'],
        "auto_save_N1": cfg_old['autoSaveN1'],

        # ACTIVATE/DEACTIVATE CONTROLS
        "controls": {
            "buttons": {
                # general
                "save_labels": cfg_old['button_saveLabels'],
                "single_label_mode": True,
                "zoom_out": cfg_old['button_home'],
                # labels
                "previous_label": cfg_old['button_previousLabel'],
                "next_label": cfg_old['button_nextLabel'],
                # Recordings
                "next_time": cfg_old['button_next'],
                "previous_time": cfg_old['button_previous'],
            },
            "fields": {
                "current_time": cfg_old['field_currentPose'],
                "d_time": cfg_old['field_dFrame']
            }
        }
    }

    return cfg_dict
