#!/usr/bin/env python3

import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np
import paho.mqtt.client as mqtt
import svidreader
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMdiArea, \
    QFileDialog, \
    QMainWindow
from bbo import label_lib, path_management as bbo_pm
from bbo.yaml import load as yaml_load
from matplotlib import colors as mpl_colors

from labelgui.misc import archive_cfg, read_video_meta
from labelgui.select_user import SelectUserWindow
from labelgui.ui import ControlsDock, SketchDock, ViewerSubWindow

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, drive: Path, file_config=None, parent=None, sync: str | bool = False):
        super(MainWindow, self).__init__(parent)

        self.user = None
        self.drive = drive
        self.cfg = {}
        self.file_config = None
        self.mqtt_client = None

        self.cameras: List[Dict] = []
        self.subwindows: Dict = {}
        self.labels = label_lib.get_empty_labels()
        self.ref_labels = label_lib.get_empty_labels()
        self.neighbor_points = {}
        self.auto_save_counter = 0

        # init GUI
        self.mdi = QMdiArea()
        self.dock_sketch = SketchDock()
        self.dock_controls = ControlsDock()

        session_menu = self.menuBar().addMenu("&File")
        session_menu.addAction("Save Labels As...", self.save_labels_as)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction("&Tile", self.mdi.tileSubWindows)
        view_menu.addAction("&Cascade", self.mdi.cascadeSubWindows)

        # Config
        self.load_cfg()

        # Load some params from config
        self.d_frame = self.cfg['dFrame']
        self.min_frame = int(self.cfg['min_frame'])
        self.max_frame = int(self.cfg['max_frame'])
        self.allowed_frames = np.arange(self.min_frame, self.max_frame, self.d_frame, dtype=int)
        self.frame_idx = self.min_frame
        self.dock_sketch.sketch_zoom_scale = self.cfg.get('sketch_zoom_scale', 0.1)

        # Files
        self.dataset_name = self.cfg['dataset_name'] if len(self.cfg['dataset_name']) \
            else Path(self.cfg['recording_folder']).name
        self.labels_folder = None  # Output folder to store labels/results

        # Data load status
        self.recordings_loaded = False
        self.sketch_loaded = False
        self.labels_loaded = False
        self.GUI_loaded = False

        # Loaded data
        self.init_files_folders()
        self.load_sketch(sketch_file=self.drive / Path(self.cfg['sketch_file']))

        load_labels_file = self.cfg["load_labels_file"]
        self.load_labels(labels_file=Path(load_labels_file) if isinstance(load_labels_file, str) else None)
        self.load_ref_labels()

        # GUI layout
        self.setCentralWidget(self.mdi)
        self.set_docks_layout()

        self.dock_sketch.init_sketch()
        self.init_viewer()
        self.fill_controls()
        self.connect_controls()
        self.GUI_loaded = True

        self.showMaximized()
        self.setFocus()
        self.setWindowTitle('Labeling GUI')

        self.sync = sync
        self.mqtt_connect()

        # TODO: ignoring calibration for now, will implement later if necessary

    def load_cfg(self):
        if os.path.isdir(self.drive):
            self.user, job, correct_exit = SelectUserWindow.start(self.drive)
            if correct_exit:
                if job is not None:
                    file_config = self.drive / 'data' / 'user' / self.user / 'jobs' / f'{job}.yml'
                else:
                    file_config = self.drive / 'data' / 'user' / self.user / 'labelgui_cfg.yml'
                self.cfg = yaml_load(file_config)
            else:
                sys.exit()
        else:
            logger.log(logging.ERROR, 'Server is not mounted')
            sys.exit()
        logger.log(logging.INFO, "++++++++++++++++++++++++++++++++++++")
        logger.log(logging.INFO, f"file_config: {file_config}")
        logger.log(logging.INFO, "++++++++++++++++++++++++++++++++++++")
        self.file_config = file_config

    # Mqtt functions
    def mqtt_connect(self):
        if isinstance(self.sync, bool):
            return
        try:
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.on_message = self.mqtt_on_message
            self.mqtt_client.connect("127.0.0.1", 1883, 60)
            self.mqtt_client.subscribe(self.sync)
            self.mqtt_client.loop_start()
        except ConnectionRefusedError:
            logger.log(logging.ERROR, "No connection to MQTT server.")
            self.mqtt_client = None

    def mqtt_publish(self):
        if self.mqtt_client is not None:
            try:
                self.mqtt_client.publish(self.sync, payload=str(self.frame_idx))
            except ConnectionRefusedError:
                logger.log(logging.ERROR, "No connection to MQTT server.")
                self.mqtt_client = None

    def mqtt_on_message(self, client, userdata, message):
        logger.log(logging.INFO, f"Received message '{message.payload.decode()}' on topic '{message.topic}'")
        match message.topic:
            case "bbo/sync/fr_idx":
                fr_idx = int(message.payload.decode())
                self.set_frame_idx(fr_idx, mqtt_publish=False)

    # Init functions
    def init_files_folders(self):
        recording_folder = Path(self.cfg['recording_folder'])
        rec_files = (
            [bbo_pm.decode_path(recording_folder / i).expanduser().resolve() for i in
             self.cfg['recording_filenames']]
        )
        self.load_recordings(rec_files)

        # create folder structure / save backup / load last frame
        self.init_assistant_folders(recording_folder)
        self.init_autosave()
        archive_cfg(self.file_config, self.labels_folder)
        self.restore_last_frame_idx()

    def load_labels(self, labels_file: Optional[Path] = None):
        if labels_file is None:
            labels_file = self.labels_folder / 'labels.yml'

        if labels_file.exists():
            logger.log(logging.INFO, f'Loading labels from: {labels_file}')
            self.labels = label_lib.load(labels_file, v0_format=False)
            self.labels_loaded = True
        else:
            logger.log(logging.WARNING, f'Autoloading failed. Labels file {labels_file} does not exist.')

        # Add the label_names from sketch
        # TODO: Could be uncessary
        for label_name, _ in self.dock_sketch.get_sketch_labels().items():
            if label_name not in self.labels['labels']:
                self.labels['labels'][label_name] = {}

    def load_ref_labels(self):
        ref_labels_file = self.cfg['reference_labels_file']
        if isinstance(ref_labels_file, bool) and ref_labels_file:
            self.cfg[
                'reference_labels_file'] = ref_labels_file = self.drive / "data" / "references" / f"{self.dataset_name}.yml"
        elif isinstance(ref_labels_file, str):
            ref_labels_file = Path(ref_labels_file)
        else:
            return

        if ref_labels_file.is_file():
            self.ref_labels = label_lib.load(ref_labels_file, v0_format=False)
        else:
            logger.log(logging.WARNING, f"Reference labels file {ref_labels_file.as_posix()} not found")

    def load_sketch(self, sketch_file: Path):
        # load sketch
        if sketch_file.exists():
            self.dock_sketch.sketch = np.load(sketch_file.as_posix(), allow_pickle=True)[()]
            self.dock_sketch.set_sketch_zoom()
            self.sketch_loaded = True
        else:
            logger.log(logging.WARNING, f'Autoloading failed. Sketch file {sketch_file} does not exist.')

    def load_recordings(self, files: List[Path]):
        cameras = []
        logger.log(logging.DEBUG, svidreader.__file__)
        for file in files:
            logger.log(logging.INFO, f"File name: {file.name}")
            reader = svidreader.get_reader(file.as_posix(), backend="iio", cache=True)
            header = read_video_meta(reader)
            cam = {
                'file_name': file.name,
                'reader': reader,
                'header': header,
                'x_lim_prev': (0, header['sensorsize'][0]),
                'y_lim_prev': (0, header['sensorsize'][1]),
                'rotate': False,
            }
            cameras.append(cam)

        self.recordings_loaded = True
        self.cameras = cameras

    def get_n_frames(self):
        return [cam["header"]["nFrames"] for cam in self.cameras]

    def get_sensor_sizes(self):
        return [cam["header"]["sensorsize"] for cam in self.cameras]

    def get_camera_names(self):
        return [cam["file_name"] for cam in self.cameras]

    def get_x_res(self):
        return [ss[0] for ss in self.get_sensor_sizes()]

    def get_y_res(self):
        return [ss[1] for ss in self.get_sensor_sizes()]

    def restore_last_frame_idx(self):
        # Retrieve last frame from 'exit' file
        file_exit_status = self.labels_folder / 'exit_status.npy'
        if file_exit_status.is_file():
            exit_status = np.load(file_exit_status.as_posix(), allow_pickle=True)[()]
            self.set_frame_idx(exit_status['i_frame'])

    def init_assistant_folders(self, recording_folder: Path):
        # folder structure
        userfolder = self.drive / 'user' / self.user
        os.makedirs(userfolder, exist_ok=True)
        results_folder = userfolder / recording_folder.name
        os.makedirs(results_folder, exist_ok=True)
        self.labels_folder = results_folder.expanduser().resolve()

        # backup
        # TODO: Something is wrong here, check with Kay about what are the files needed to be saved and where
        backup_folder = self.labels_folder / 'backup'
        if not backup_folder.is_dir():
            os.mkdir(backup_folder)
        file = self.labels_folder / 'labelgui_cfg.yml'
        if file.is_file():
            archive_cfg(file, backup_folder)
        file = self.labels_folder / 'labels.yml'
        try:
            labels_old = label_lib.load(file, v0_format=False)
            label_lib.save(backup_folder / 'labels.yml', labels_old)
        except FileNotFoundError as e:
            pass

    def init_autosave(self):
        # autosave
        autosave_folder = self.labels_folder / 'autosave'
        if not autosave_folder.is_dir():
            os.makedirs(autosave_folder)
        archive_cfg(self.file_config, autosave_folder)

    def get_frame_idx(self):
        return self.frame_idx

    def init_viewer(self):
        cam_names = self.get_camera_names()

        # Open windows
        for cam_idx, cam_name in enumerate(cam_names):
            window = ViewerSubWindow(index=cam_idx,
                                     reader=self.cameras[cam_idx]['reader'],
                                     parent=self.mdi)
            window.setWindowTitle(f'{self.cameras[cam_idx]['file_name']} ({cam_idx})')
            window.redraw_frame(self.frame_idx)
            self.subwindows[cam_name] = window

        self.viewer_plot_labels(current_label_name="")
        self.viewer_plot_ref_labels()

    @DeprecationWarning
    def init_colors(self):
        colors = dict(mpl_colors.BASE_COLORS, **mpl_colors.CSS4_COLORS)
        # Sort colors by hue, saturation, value and name.
        by_hsv = sorted((tuple(mpl_colors.rgb_to_hsv(mpl_colors.to_rgba(color)[:3])), name)
                        for name, color in colors.items())
        sorted_names = [name for hsv, name in by_hsv]
        for i in range(24, -1, -1):
            self.colors = self.colors + sorted_names[i::24]

    def get_valid_frame_idx(self, frame_idx: int):
        return self.allowed_frames[np.argmin(np.abs(self.allowed_frames - frame_idx))]

    def set_frame_idx(self, frame_idx: int or str, mqtt_publish=True):
        if isinstance(frame_idx, str):
            frame_idx = int(frame_idx)
        self.frame_idx = self.get_valid_frame_idx(frame_idx)

        if self.GUI_loaded:
            # Controls dock
            self.dock_controls.widgets['labels']['labeler'].setText(
                ", ".join(label_lib.get_frame_labelers(self.labels, self.frame_idx))
            )
            # Viewer
            self.viewer_change_frame()

        if mqtt_publish:
            self.mqtt_publish()

    def set_docks_layout(self):
        # frame main
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_sketch)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_controls)

    def trigger_autosave_event(self):
        # TODO: would it not be better to trigger it based on time/clock?
        if self.cfg['auto_save']:
            self.auto_save_counter = self.auto_save_counter + 1
            if np.mod(self.auto_save_counter, self.cfg['auto_save_N0']) == 0:
                file = self.labels_folder / 'labels.yml'  # this is equal to self.labels_file
                label_lib.save(file, self.labels)
                logger.log(logging.INFO, 'Automatically saved labels ({:s})'.format(file.as_posix()))
            if np.mod(self.auto_save_counter, self.cfg['auto_save_N1']) == 0:
                file = self.labels_folder / 'autosave' / 'labels.yml'
                label_lib.save(file, self.labels)
                logger.log(logging.INFO, 'Automatically saved labels ({:s})'.format(file.as_posix()))

                self.auto_save_counter = 0

    def viewer_change_frame(self):
        self.viewer_update_images()

        self.viewer_clear_labels()
        self.viewer_plot_labels()
        self.viewer_plot_ref_labels()

    def viewer_update_images(self):
        for cam_idx, cam_name in enumerate(self.get_camera_names()):
            self.subwindows[cam_name].redraw_frame(self.frame_idx)

    def viewer_plot_labels(self, label_names=None, current_label_name=None):
        frame_idx = self.get_frame_idx()
        if label_names is None:
            label_names = label_lib.get_labels(self.labels)
        if current_label_name is None:
            current_label_name = self.get_current_label()

        for cam_idx, cam_name in enumerate(self.get_camera_names()):
            subwin = self.subwindows[cam_name]

            # Plot each label
            for label_name in label_names:
                label_dict = self.labels['labels'].get(label_name, {})

                if frame_idx in label_dict and \
                    not np.any(np.isnan(label_dict[frame_idx]['coords'][cam_idx])):
                        # Plot actual/annotated labels
                        point = label_dict[frame_idx]['coords'][cam_idx, :]
                        labeler = self.labels['labeler_list'][label_dict[frame_idx]['labeler'][cam_idx]]
                        logger.log(logging.INFO, f"label {label_name} {frame_idx} {labeler}: {point}")
                        subwin.draw_label(point[0], point[1], label_name,
                                          label_type='current_label' if current_label_name == label_name else 'label')

                else:
                    # Plot a guess position based on previous or/and next frames
                    point = np.full((1, 2), np.nan)

                    # Try to take mean of symmetrical situation
                    for offs in range(1, 4):
                        if frame_idx - offs in label_dict and \
                                not np.any(np.isnan(label_dict[frame_idx - offs]['coords'][cam_idx])) and \
                                frame_idx + offs in label_dict and \
                                not np.any(np.isnan(label_dict[frame_idx + offs]['coords'][cam_idx])):
                            point = np.nanmean([point,
                                                label_dict[frame_idx - offs]['coords'][(cam_idx,),],
                                                label_dict[frame_idx + offs]['coords'][(cam_idx,),]
                                                ], axis=0)
                            break

                    if np.any(np.isnan(point)):
                        # Fill from one closest neighbor, TODO: Counter from other side even if not symmetrical?
                        for offs in [-1, 1, -2, 2, -3, 3]:
                            if frame_idx + offs in label_dict:
                                point = label_dict[frame_idx + offs]['coords'][(cam_idx,),]
                                break

                    if ~np.any(np.isnan(point)):
                        subwin.draw_label(point[0][0], point[0][1], label_name,
                                          guess=True,
                                          label_type='current_label' if current_label_name == label_name else 'label')

    def viewer_plot_ref_labels(self):
        # Plot reference labels
        frame_idx = self.get_frame_idx()

        for cam_idx, cam_name in enumerate(self.get_camera_names()):
            subwin = self.subwindows[cam_name]

            for label_name in self.labels['labels']:
                if label_name in self.ref_labels['labels'] and frame_idx in self.ref_labels['labels'][label_name] and \
                        not np.any(np.isnan(self.ref_labels['labels'][label_name][frame_idx]['coords'][cam_idx])):

                    ref_label_dict = self.ref_labels['labels'][label_name]
                    label_dict = self.labels['labels'][label_name]
                    point = ref_label_dict[frame_idx]['coords'][cam_idx]
                    subwin.draw_label(point[0], point[1], label_name, label_type="ref_label")

                    if frame_idx in label_dict and \
                            not np.any(np.isnan(label_dict[frame_idx]['coords'][cam_idx])):
                        line_coords = np.concatenate((label_dict[frame_idx]['coords'][(cam_idx,), :],
                                                      ref_label_dict[frame_idx]['coords'][(cam_idx,), :]), axis=0)
                        logger.log(logging.INFO, f"Drawing line, {line_coords.shape}, {line_coords}")
                        # TODO: test this
                        subwin.draw_label(*line_coords.T, label_name, label_type='error_line')

    def viewer_click(self, cam_idx:int, x:float, y:float, action:str = 'create_label'):
        # Initialize array
        fr_idx = self.get_frame_idx()
        label_name = self.get_current_label()

        match action:
            case 'select_label':
                coords = np.array([x, y], dtype=np.float64)
                point_dists = []
                frame_labels = label_lib.get_labels_from_frame(self.labels, frame_idx=fr_idx)
                label_names = list(frame_labels.keys())
                for ln, ld in frame_labels.items():
                    if len(ld) > cam_idx and not np.any(np.isnan(ld[cam_idx])):
                        point_dists.append(
                            np.linalg.norm(ld[cam_idx] - coords))
                    else:
                        point_dists.append(np.inf)

                self.set_current_label(label_names[np.argmin(point_dists)])

            case 'create_label':
                self.add_label([x, y], label_name, cam_idx, fr_idx)
                self.viewer_plot_labels(label_names=[label_name])

            case 'auto_label':
                # TODO:
                pass

            case 'delete_label':
                if self.user not in self.labels['labeler_list']:
                    self.labels['labeler_list'].append(self.user)

                label_dict = self.labels['labels'][label_name]
                label_dict[fr_idx]['coords'][cam_idx, :] = np.nan
                # For synchronisation, deletion time and user must be recorded
                label_dict[fr_idx]['point_times'][cam_idx] = time.time()
                label_dict[fr_idx]['labeler'][cam_idx] = self.labels['labeler_list'].index(self.user)

                self.viewer_plot_labels(label_names=[label_name])

            case _:
                logger.log(logging.WARNING, f'Unknown action {action} for cam_idx {cam_idx} '
                                            f'and location {x}, {y}')

    def viewer_clear_labels(self):
        for cam_idx, cam_name in enumerate(self.get_camera_names()):
            self.subwindows[cam_name].clear_all_labels()

    def get_current_label(self):
        selected_label = self.dock_controls.list_labels.currentItem()
        if selected_label is not None:
            return selected_label.text()
        else:
            return None

    def set_current_label(self, label:str or int):
        match label:
            case int():
                pass
            case str():
                if label in self.dock_sketch.get_sketch_labels():
                    label = list(self.dock_sketch.get_sketch_labels().keys()).index(label)
                else:
                    logger.log(logging.WARNING, f"Label name {label} not in the sketch!")
            case _:
                logger.log(logging.WARNING, f"Input {label} has unknown type")

        self.dock_controls.list_labels.setCurrentRow(label)


    def fill_controls(self):
        # TODO: vmin, vmax
        # Fields
        self.dock_controls.widgets['fields']['current_frame'].setText(str(self.get_frame_idx()))
        self.dock_controls.widgets['fields']['d_frame'].setText(str(self.d_frame))

        # Lists
        list_labels = self.dock_controls.list_labels
        list_labels.addItems(self.dock_sketch.get_sketch_labels())

    def connect_controls(self):
        self.dock_controls.widgets['buttons']['home'].clicked.connect(
            self.viewer_zoom_reset)
        self.dock_controls.widgets['buttons']['save_labels'].clicked.connect(
            lambda: self.save_labels(None))

        list_labels = self.dock_controls.list_labels

        # Sketches dock
        self.dock_sketch.sketch_clicked_signal.connect(list_labels.setCurrentRow)

        # Control dock
        self.dock_controls.connect_widgets()
        list_labels.currentItemChanged.connect(self.label_select)
        list_labels.setCurrentRow(0)
        self.dock_controls.widgets['buttons']['previous_frame'].clicked.connect(self.previous_frame)
        self.dock_controls.widgets['buttons']['next_frame'].clicked.connect(self.next_frame)
        self.dock_controls.widgets['fields']['current_frame'].returnPressed.connect(
            lambda: self.set_frame_idx(self.dock_controls.widgets['fields']['current_frame'].text()))

        # Viewer
        for _, subwin in self.subwindows.items():
            subwin.mouse_clicked_signal.connect(self.viewer_click)

    def add_label(self, coords, label_name, cam_idx, fr_idx):
        # TODO
        pass

    def save_labels(self, file: Path = None):
        if file is None:
            file = self.labels_folder / 'labels.yml'

        label_lib.save(file, self.labels)

    def save_labels_as(self):
        """ MenuBar > Save As..."""
        file = QFileDialog.getSaveFileName(self, "Save Labels As...", "", "Session File (*.yml)")[0]
        if file:
            logger.log(logging.INFO, f"Saving Labels As {file}")
            self.save_labels(Path(file))

    def viewer_zoom_reset(self):
        # Reset view in all the subwindows
        for _, subwin in self.subwindows.items():
            subwin.plot_wget.autoRange()

    def label_select(self):
        self.trigger_autosave_event()
        self.dock_sketch.update_sketch(current_label_name=self.get_current_label())
        self.dock_controls.list_labels.clearFocus()
        for _, subwin in self.subwindows.items():
            subwin.set_current_label(label_name=self.get_current_label())

    def next_frame(self):
        self.set_frame_idx(
            self.get_valid_frame_idx(self.frame_idx + self.d_frame)
        )
        self.dock_controls.widgets['fields']['current_frame'].setText(str(self.get_frame_idx()))

    def previous_frame(self):
        self.set_frame_idx(
            self.get_valid_frame_idx(self.frame_idx - self.d_frame)
        )
        self.dock_controls.widgets['fields']['current_frame'].setText(str(self.get_frame_idx()))

    # Shortcuts
    def keyPressEvent(self, event):
        if self.cfg['button_next'] and event.key() == Qt.Key_D:
            self.next_frame()
        elif self.cfg['button_previous'] and event.key() == Qt.Key_A:
            self.previous_frame()
        else:
            pass

        if not (event.isAutoRepeat()):
            if self.cfg['button_next_label'] and event.key() == Qt.Key_N:
                self.dock_controls.widgets['buttons']['next_label'].click()
            elif self.cfg['button_previous_label'] and event.key() == Qt.Key_P:
                self.dock_controls.widgets['buttons']['previous_label'].click()
            elif self.cfg['button_home'] and event.key() == Qt.Key_H:
                self.dock_controls.widgets['buttons']['home'].click()

    def closeEvent(self, event):
        exit_status = dict()
        exit_status['i_frame'] = self.get_frame_idx()
        np.save(self.labels_folder / 'exit_status.npy', exit_status)


class UnsupportedFormatException(Exception):
    pass
