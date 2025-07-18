import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np
import paho.mqtt.client as mqtt
import pandas as pd
import svidreader
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMdiArea, \
    QFileDialog, \
    QMainWindow
from bbo import label_lib, path_management as bbo_pm

from labelgui import misc as labelgui_misc
from labelgui.select_user import SelectUserWindow
from .controls_dock import ControlsDock
from .sketch_dock import SketchDock
from .viewer_sub_window import ViewerSubWindow

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, drive: Path, file_config=None, parent=None, sync: str | bool = False):
        super(MainWindow, self).__init__(parent)

        self.user = None
        self.drive = drive
        self.cfg = {}
        self.file_config = None
        self.mqtt_client = None
        self.sync = sync

        self.cameras: List[Dict] = []
        self.subwindows: Dict = {}
        self.labels = label_lib.get_empty_labels()
        self.ref_labels = label_lib.get_empty_labels()
        self.neighbor_points = {}
        self.auto_save_counter = 0

        # Docks
        self.mdi = QMdiArea()
        self.dock_sketch = SketchDock()
        self.dock_controls = ControlsDock()

        # Menus
        self.session_menu = self.menuBar().addMenu("&File")
        self.session_menu.addAction("Save Labels As...", self.save_labels_as)

        self.view_menu = self.menuBar().addMenu("&View")
        self.view_menu.addAction("&Tab (single cam view)", lambda: self.mdi_view_select("tab_view"))
        self.view_menu.addAction("&Tile", lambda: self.mdi_view_select("tile_view"))
        self.view_menu.addAction("&Cascade", lambda: self.mdi_view_select("cascade_view"))

        # Config
        self.load_cfg()

        # Load some params from config
        self.d_time = self.cfg['d_time']
        self.min_time = int(self.cfg['min_time'])
        self.max_time = int(self.cfg['max_time'])
        self.current_time = None
        self.times = []
        self.cam_times = []
        self.dock_sketch.sketch_zoom_scale = self.cfg.get('sketch_zoom_scale', 0.1)

        # Files
        self.dataset_name = self.cfg['dataset_name'] if len(self.cfg['dataset_name']) \
            else Path(self.cfg['recording_folder']).name
        self.labels_folder = None  # Output folder to store labels/results

        # Data load status
        self.recordings_loaded = False
        self.labels_loaded = False
        self.gui_loaded = False

        # Loaded data
        self.init_files_folders()
        self.dock_sketch.load_sketches(sketch_files=[Path(file)
                                                     for file in self.cfg['sketch_files']])

        load_labels_file = self.cfg["load_labels_file"]
        self.load_labels(labels_file=Path(load_labels_file) if isinstance(load_labels_file, str) else None)
        self.load_ref_labels()

        self.dock_sketch.init_sketch()
        self.init_viewer()
        self.fill_controls()
        self.connect_controls()

        # GUI layout
        self.setCentralWidget(self.mdi)
        self.set_docks_layout()
        self.showMaximized()
        self.setFocus()
        self.setWindowTitle('Labeling GUI')

        self.gui_loaded = True
        self.mqtt_connect()

        # TODO: ignoring calibration for now, will implement later if necessary

    # Init functions
    def init_files_folders(self):
        recording_folder = Path(self.cfg['recording_folder'])
        rec_files = (
            [bbo_pm.decode_path(recording_folder / i).expanduser().resolve() for i in
             self.cfg['recording_filenames']]
        )
        self.load_recordings(rec_files)
        self.load_times()

        # create folder structure / save backup / load last frame
        self.init_assistant_folders(recording_folder)
        self.init_autosave()
        labelgui_misc.archive_cfg(self.file_config, self.labels_folder)
        self.restore_last_frame_time()

    def load_cfg(self):
        if os.path.isdir(self.drive):
            self.user, job, correct_exit = SelectUserWindow.start(self.drive)
            if correct_exit:
                file_loc = self.drive / 'data' / 'user' / self.user
                file_config = file_loc / 'labelgui_cfg.yml'
                if job is not None:
                    if (file_loc / 'jobs' / f'{job}.yml').is_file():
                        file_config = file_loc / 'jobs' / f'{job}.yml'
                    elif (file_loc / 'jobs' / f'{job}.py').is_file():
                        file_config = file_loc / 'jobs' / f'{job}.py'

                self.cfg = labelgui_misc.load_cfg(file_config)
            else:
                sys.exit()
        else:
            logger.log(logging.ERROR, 'Server is not mounted')
            sys.exit()
        logger.log(logging.INFO, "++++++++++++++++++++++++++++++++++++")
        logger.log(logging.INFO, f"file_config: {file_config}")
        logger.log(logging.INFO, "++++++++++++++++++++++++++++++++++++")
        self.file_config = file_config

    def load_labels(self, labels_file: Optional[Path] = None):
        if labels_file is None:
            labels_file = self.labels_folder / 'labels.yml'

        if labels_file.exists():
            logger.log(logging.INFO, f'Loading labels from: {labels_file}')
            self.labels = label_lib.load(labels_file, v0_format=False)
            self.labels_loaded = True
        else:
            logger.log(logging.WARNING, f'Autoloading failed. Labels file {labels_file} does not exist.')

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
            logger.log(logging.WARNING, f" Not Found: reference labels file {ref_labels_file.as_posix()} ")

    def load_recordings(self, files: List[Path]):
        cameras = []
        logger.log(logging.DEBUG, svidreader.__file__)
        for file in files:
            logger.log(logging.INFO, f"File name: {file.name}")
            reader = svidreader.get_reader(file.as_posix(), backend="iio", cache=True)
            header = labelgui_misc.read_video_meta(reader)
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

    def load_times(self):
        if self.recordings_loaded:
            num_frames = self.get_n_frames()

            for cam_idx, cam in enumerate(self.cameras):
                video_times_dict = self.cfg["video_times"].get(cam_idx, {})
                if 'file' in video_times_dict:
                    # TODO: Check with Kay
                    times_pd = pd.read_csv(video_times_dict['file'], comment="#")
                    cam_times = np.array(times_pd.iloc[:, 0]).astype(float)  # Loading times from first column
                    assert len(cam_times) == num_frames[cam_idx], (f"video times in the csv file "
                                                                   f"do not match the number of frames in the recording {cam_idx}")
                else:
                    cam_times = np.arange(num_frames[cam_idx]) / video_times_dict.get('fps',
                                                                                      cam['header']['fps'])
                cam_times += video_times_dict.get('offset', 0)
                self.cam_times.append(list(cam_times))

            # Concatenate and remove duplicates
            times = set(sum(self.cam_times, []))
            times = np.asarray(sorted(times))
            times = times[(times >= self.min_time) & (times < self.max_time)]
            logger.log(logging.INFO, f"{len(times)} VALID TIMEPOINTS SELECTED")
            self.times = times.tolist()
            self.current_time = self.times[0]

    def restore_last_frame_time(self):
        # Retrieve last frame from 'exit' file
        file_exit_status = self.labels_folder / 'exit_status.npy'
        if file_exit_status.is_file():
            exit_status = np.load(file_exit_status.as_posix(), allow_pickle=True)[()]
            self.set_time(exit_status.get('i_time', self.times[0]))

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
            labelgui_misc.archive_cfg(file, backup_folder)
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
        labelgui_misc.archive_cfg(self.file_config, autosave_folder)

    # Init gui functions
    def init_viewer(self):

        # Open windows
        for cam_idx, cam in enumerate(self.cameras):
            if cam_idx in self.cfg['allowed_cams']:
                window = ViewerSubWindow(index=cam_idx,
                                         reader=cam['reader'],
                                         parent=self.mdi)
                window.setWindowTitle(f"{cam['file_name']} ({cam_idx})")
                window.redraw_frame()
                self.subwindows[cam_idx] = window

        self.mdi.setViewMode(QMdiArea.TabbedView)
        self.set_time(self.current_time)

    def fill_controls(self):
        # Sketches dock
        self.dock_sketch.fill_controls()

        # Controls dock
        self.dock_controls.widgets['fields']['current_time'].setText(str(round(self.current_time, 6)))
        self.dock_controls.widgets['fields']['d_time'].setText(str(self.d_time))

    def connect_controls(self):
        controls_cfg = self.cfg['controls']
        list_labels = self.dock_sketch.list_labels

        # Sketches dock
        self.dock_sketch.connect_canvas()
        self.dock_sketch.connect_label_buttons(controls_cfg)
        self.dock_sketch.combobox_sketches.currentIndexChanged.connect(self.sketch_select)
        list_labels.currentItemChanged.connect(self.label_select)
        list_labels.setCurrentRow(0)

        # Control dock
        if controls_cfg['buttons']['save_labels']:
            self.dock_controls.widgets['buttons']['save_labels'].setEnabled(True)
            self.dock_controls.widgets['buttons']['save_labels'].clicked.connect(
                lambda: self.save_labels(None))
        if controls_cfg['buttons']['zoom_out']:
            self.dock_controls.widgets['buttons']['zoom_out'].setEnabled(True)
            self.dock_controls.widgets['buttons']['zoom_out'].clicked.connect(
                self.viewer_zoom_reset)
        self.dock_controls.widgets['buttons']['single_label_mode'].setEnabled(
            controls_cfg['buttons']['single_label_mode'])

        if controls_cfg['buttons']['previous_time']:
            self.dock_controls.widgets['buttons']['previous_time'].setEnabled(True)
            self.dock_controls.widgets['buttons']['previous_time'].clicked.connect(self.goto_previous_time)
        if controls_cfg['buttons']['next_time']:
            self.dock_controls.widgets['buttons']['next_time'].setEnabled(True)
            self.dock_controls.widgets['buttons']['next_time'].clicked.connect(self.goto_next_time)

        if controls_cfg['fields']['current_time']:
            self.dock_controls.widgets['fields']['current_time'].setEnabled(True)
            self.dock_controls.widgets['fields']['current_time'].editingFinished.connect(
                self.field_current_time_changed)
        if controls_cfg['fields']['d_time']:
            self.dock_controls.widgets['fields']['d_time'].setEnabled(True)
            self.dock_controls.widgets['fields']['d_time'].editingFinished.connect(self.set_d_time)

        # Viewer
        for _, subwin in self.subwindows.items():
            subwin.connect_controls()
            subwin.mouse_clicked_signal.connect(self.viewer_click)

    # Viewer functions
    def viewer_change_frame(self):
        self.viewer_clear_labels()

        self.viewer_update_images()
        self.viewer_plot_labels()
        self.viewer_plot_ref_labels()

    def viewer_update_images(self):
        for _, subwin in self.subwindows.items():
            subwin.redraw_frame()

    def viewer_plot_labels(self, label_names=None, current_label_name=None):
        if label_names is None:
            label_names = label_lib.get_labels(self.labels)
        if current_label_name is None:
            current_label_name = self.get_current_label()

        for cam_idx, subwin in self.subwindows.items():
            frame_idx = subwin.frame_idx
            if frame_idx is None:
                subwin.clear_all_labels()
                subwin.label_labeler.setText("")
                continue

            subwin.label_labeler.setText(
                ", ".join(label_lib.get_frame_labelers(self.labels, subwin.frame_idx))
            )
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
                                      current_label=current_label_name == label_name)
                    subwin.clear_label(label_name, label_type='guess_label')

                else:
                    # Plot a guess position based on previous or/and next frames
                    point = np.full((1, 2), np.nan)

                    # Try to take mean of a symmetrical situation
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
                                          label_type='guess_label',
                                          current_label=current_label_name == label_name)

    def viewer_plot_ref_labels(self):
        # Plot reference labels

        for cam_idx, subwin in self.subwindows.items():
            frame_idx = subwin.frame_idx
            if frame_idx is None:
                continue

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
                        logger.log(logging.DEBUG, f"Drawing line, {line_coords.shape}, {line_coords}")
                        subwin.draw_line(*line_coords.T, line_name=label_name, line_type='error_line')

    def viewer_click(self, x: float, y: float, cam_frame_idx: int, cam_idx: int, action: str = 'create_label'):
        # Initialize array
        label_name = self.get_current_label()

        match action:
            case 'select_label':
                coords = np.array([x, y], dtype=np.float64)
                point_dists = []
                frame_labels = label_lib.get_labels_from_frame(self.labels, frame_idx=cam_frame_idx)
                label_names = list(frame_labels.keys())
                for ln, ld in frame_labels.items():
                    if len(ld) > cam_idx and not np.any(np.isnan(ld[cam_idx])):
                        point_dists.append(
                            np.linalg.norm(ld[cam_idx] - coords))
                    else:
                        point_dists.append(np.inf)

                self.set_current_label(label_names[np.argmin(point_dists)])

            case 'create_label':
                self.add_label([x, y], label_name, cam_frame_idx, cam_idx)
                self.viewer_plot_labels(label_names=[label_name])
                if self.dock_controls.widgets['buttons']['single_label_mode'].isChecked():
                    self.goto_next_time()

            case 'auto_label':
                # TODO:
                pass

            case 'delete_label':
                if self.user not in self.labels['labeler_list']:
                    self.labels['labeler_list'].append(self.user)

                label_dict = self.labels['labels'].get(label_name, {})
                # Only delete the label if it already exists
                if (cam_frame_idx in label_dict and
                        not np.any(np.isnan(label_dict[cam_frame_idx]['coords'][cam_idx, :]))):
                    label_dict[cam_frame_idx]['coords'][cam_idx, :] = np.nan
                    # For synchronization, deletion time and user must be recorded
                    label_dict[cam_frame_idx]['point_times'][cam_idx] = time.time()
                    label_dict[cam_frame_idx]['labeler'][cam_idx] = self.labels['labeler_list'].index(self.user)

                    self.subwindows[cam_idx].clear_label(label_name=label_name,
                                                         label_type='label')

            case _:
                logger.log(logging.WARNING, f'Unknown action {action} for cam_idx {cam_idx} '
                                            f'and location {x}, {y}')

    def viewer_clear_labels(self):
        for cam_idx, subwin in self.subwindows.items():
            subwin.clear_all_labels()

    def viewer_zoom_reset(self):
        # Reset view in all the subwindows
        for _, subwin in self.subwindows.items():
            subwin.plot_wget.autoRange()

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

    def mqtt_on_message(self, message):
        # TODO: Test this function
        logger.log(logging.INFO, f"Received message '{message.payload.decode()}' on topic '{message.topic}'")
        match message.topic:
            case "bbo/sync/fr_idx":
                fr_idx = int(message.payload.decode())
                cam_idx = 0 # TODO: This needs to be changed when to support multiple cams
                self.set_time(self.cam_times[cam_idx][fr_idx], mqtt_publish=False)

    # Getter functions
    def get_current_time(self):
        return self.current_time

    def get_n_frames(self):
        return [cam["header"]["num_frames"] for cam in self.cameras]

    def get_fps(self):
        return [cam["header"]["fps"] for cam in self.cameras]

    def get_sensor_sizes(self):
        return [cam["header"]["sensorsize"] for cam in self.cameras]

    def get_x_res(self):
        return [ss[0] for ss in self.get_sensor_sizes()]

    def get_y_res(self):
        return [ss[1] for ss in self.get_sensor_sizes()]

    def get_valid_time(self, input_time: float):
        """
            Returns a valid time that is closest to the given 'time'
        """
        times_arr = np.asarray(self.times)
        current_time_idx = self.times.index(self.current_time)
        # Asserting that the change in time should be more than self.d_time
        diff_time = np.abs(self.current_time - input_time)
        diff_sign = int(np.sign(input_time - self.current_time))
        if diff_time < self.d_time:
            input_time = self.current_time + (diff_sign * self.d_time)

        if diff_sign > 0:
            search_slice = times_arr[current_time_idx:]
        else:
            search_slice = times_arr[:current_time_idx + 1][::-1]

        if len(search_slice) > 0:
            diff_idx = np.argmin(np.abs(search_slice - input_time))
            return self.times[current_time_idx + (diff_sign * diff_idx)]
        else:
            return self.current_time

    def get_current_label(self):
        selected_label = self.dock_sketch.list_labels.currentItem()
        if selected_label is not None:
            return selected_label.text()
        else:
            return None

    # Setter functions
    def set_time(self, input_time: float, mqtt_publish=True):
        if input_time not in self.times:
            return

        self.current_time = input_time

        for cam_idx, subwin in self.subwindows.items():
            if input_time in self.cam_times[cam_idx]:
                subwin.frame_idx = self.cam_times[cam_idx].index(input_time)
            else:
                subwin.frame_idx = None
                subwin.label_labeler.setText("")

            if mqtt_publish:
                self.mqtt_publish()

        # Viewer
        self.viewer_change_frame()

    def set_d_time(self):
        self.d_time = float(self.dock_controls.widgets['fields']['d_time'].text())

    def set_docks_layout(self):
        # Right dock area
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_sketch)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_controls)

        self.resizeDocks([self.dock_sketch, self.dock_controls],
                         [600, 600], Qt.Horizontal)

    def trigger_autosave_event(self):
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

    def set_current_label(self, label: str or int):
        match label:
            case int():
                pass
            case str():
                if label in self.dock_sketch.get_sketch_labels():
                    label = list(self.dock_sketch.get_sketch_labels().keys()).index(label)
                else:
                    logger.log(logging.WARNING, f"Label name {label} not in the sketch!")
                    return
            case _:
                logger.log(logging.WARNING, f"Input {label} has unknown type")
                return

        self.dock_sketch.list_labels.setCurrentRow(label)

    # Others
    def add_label(self, coords, label_name, fr_idx, cam_idx):
        data_shape = (len(self.cameras), 2)

        label_dict = self.labels['labels'].setdefault(label_name, {})
        frame_dict = label_dict.setdefault(fr_idx, {
            'coords': np.full(data_shape, np.nan, dtype=np.float64),
            # TODO: check with kay about the dtype of times
            'point_times': np.full(data_shape[0], 0, dtype=np.float64),
            'labeler': np.full(data_shape[0], 0, dtype=np.uint16)
        })

        if self.user not in self.labels["labeler_list"]:
            self.labels["labeler_list"].append(self.user)
        frame_dict['labeler'][cam_idx] = self.labels["labeler_list"].index(self.user)
        frame_dict['point_times'][cam_idx] = time.time()
        coords = np.array(coords, dtype=np.float64)
        frame_dict['coords'][cam_idx] = coords

    def save_labels(self, file: Path = None):
        if file is None:
            file = self.labels_folder / 'labels.yml'

        label_lib.save(file, self.labels)
        logger.log(logging.INFO, f'Saved labels ({file.as_posix()})')

    def save_labels_as(self):
        """ MenuBar > Save As..."""
        file = QFileDialog.getSaveFileName(self, "Save Labels As...", "", "Session File (*.yml)")[0]
        if file:
            logger.log(logging.INFO, f"Saving Labels As {file}")
            self.save_labels(Path(file))

    def mdi_view_select(self, view_mode: str):
        match view_mode:
            case "tab_view":
                self.mdi.setViewMode(QMdiArea.TabbedView)
            case "tile_view":
                self.mdi.setViewMode(QMdiArea.SubWindowView)
                self.mdi.tileSubWindows()
            case "cascade_view":
                self.mdi.setViewMode(QMdiArea.SubWindowView)
                self.mdi.cascadeSubWindows()
            case _:
                logger.log(logging.WARNING, f"Unknown MDI view mode selected")

    def sketch_select(self):
        self.trigger_autosave_event()
        self.dock_sketch.clear_sketch()
        self.dock_sketch.current_sketch_idx = self.dock_sketch.combobox_sketches.currentIndex()
        self.dock_sketch.init_sketch()
        self.dock_sketch.combobox_sketches.clearFocus()

        list_labels = self.dock_sketch.list_labels
        list_labels.currentItemChanged.disconnect()
        list_labels.clear()
        list_labels.addItems(self.dock_sketch.get_sketch_labels())
        list_labels.currentItemChanged.connect(self.label_select)
        list_labels.setCurrentRow(0)

    def label_select(self):
        self.trigger_autosave_event()
        self.dock_sketch.update_sketch(current_label_name=self.get_current_label())
        self.dock_sketch.list_labels.clearFocus()
        for _, subwin in self.subwindows.items():
            subwin.set_current_label(label_name=self.get_current_label())

    def goto_next_time(self):
        self.set_time(self.get_valid_time(self.current_time + self.d_time))
        self.dock_controls.widgets['fields']['current_time'].setText(str(round(self.current_time, 6)))

    def goto_previous_time(self):
        self.set_time(self.get_valid_time(self.current_time - self.d_time))
        self.dock_controls.widgets['fields']['current_time'].setText(str(round(self.current_time, 6)))

    def field_current_time_changed(self):
        new_time = float(self.dock_controls.widgets['fields']['current_time'].text())
        self.set_time(self.get_valid_time(new_time))
        self.dock_controls.widgets['fields']['current_time'].setText(str(round(self.current_time, 6)))

    # Shortcuts
    def keyPressEvent(self, event):
        controls_cfg = self.cfg['controls']

        if controls_cfg['buttons']['next_time'] and event.key() == Qt.Key_D:
            self.goto_next_time()
        elif controls_cfg['buttons']['previous_time'] and event.key() == Qt.Key_A:
            self.goto_previous_time()
        elif not event.isAutoRepeat():
            if controls_cfg['buttons']['save_labels'] and event.key() == Qt.Key_S:
                self.save_labels()
            elif controls_cfg['buttons']['zoom_out'] and event.key() == Qt.Key_O:
                self.dock_controls.widgets['buttons']['zoom_out'].click()
            elif controls_cfg['buttons']['next_label'] and event.key() == Qt.Key_N:
                self.dock_sketch.widgets['buttons']['next_label'].click()
            elif controls_cfg['buttons']['previous_label'] and event.key() == Qt.Key_P:
                self.dock_sketch.widgets['buttons']['previous_label'].click()

    def closeEvent(self, event):
        exit_status = {'i_time': self.current_time}
        np.save(self.labels_folder / 'exit_status.npy', exit_status)


class UnsupportedFormatException(Exception):
    pass
