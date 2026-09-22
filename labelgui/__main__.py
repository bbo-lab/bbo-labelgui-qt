import argparse
import logging
from pathlib import Path

from bbo import label_lib


def main():
    parser = argparse.ArgumentParser(description='LabelGUI - guided video annotation.')
    parser.add_argument('INPUT_PATH', help='Base data directory, or target label file for merge commands')
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument('--merge', nargs='+', help='Merge label files into INPUT_PATH')
    operations.add_argument('--add', nargs='+', help='Add labels without overwriting target data')
    operations.add_argument('--combine_cams', nargs='+', help='Combine labels from separate cameras')
    parser.add_argument('--yml_only', action='store_true', help='Only write YAML label files')
    parser.add_argument('--sync', nargs='?', const=False, default='bbo/sync/t',
                        help='MQTT topic; pass --sync without a topic to disable synchronization')
    parser.add_argument('-log', '--loglevel', default='info')
    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel.upper())
    path = Path(args.INPUT_PATH).expanduser()
    if args.merge is not None:
        label_lib.merge(args.merge, target_file=path, overwrite=True, yml_only=args.yml_only)
    elif args.add is not None:
        label_lib.merge(args.add, target_file=path, overwrite=False, yml_only=args.yml_only)
    elif args.combine_cams is not None:
        label_lib.combine_cams(args.combine_cams, target_file=path, yml_only=args.yml_only)
    else:
        from PySide6.QtWidgets import QApplication
        from labelgui.ui import MainWindow
        app = QApplication([])
        try:
            gui = MainWindow(path, sync=args.sync)
        except (ValueError, OSError) as error:
            logging.getLogger(__name__).error('Could not open labeling session: %s', error)
            raise SystemExit(1) from error
        gui.show()
        app.exec()


if __name__ == '__main__':
    main()
