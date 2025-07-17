import argparse
import os
from pathlib import Path
from bbo import label_lib
import logging
from PyQt5.QtWidgets import QApplication

from . import ui


logger = logging.getLogger(__name__)

def main():
    # Parse inputs
    parser = argparse.ArgumentParser(description="LabelGUI - Simple GUI to annotate data.")
    parser.add_argument('INPUT_PATH', type=str, help="Directory with detect job configuration")
    parser.add_argument('--labels', type=str, required=False, nargs='*', default=None,
                        help="If given, merges labes.npz in given dirs into labels.npz file specified in INPUT_PATH "
                             "config file")
    # TODO: check with kay if these are necessary
    parser.add_argument('--merge', type=str, required=False, nargs='*', default=None,
                        help="If given, merges given labes.npz into labels.npz file specified in INPUT_PATH")
    parser.add_argument('--add', type=str, required=False, nargs='*', default=None,
                        help="Like merge, but never overwrites target data")
    parser.add_argument('--combine_cams', type=str, required=False, nargs='*', default=None,
                        help="If given, merges given labes.npz into a labels.npz file specified in INPUT_PATH, "
                             "where each labels file stands for a separate camera. 'None' serves as a placeholder.")
    parser.add_argument('--strict', required=False, action="store_true",
                        help="With --labels, merges only frames where frames were labeled in all cameras")
    parser.add_argument('--yml_only', required=False, action="store_true",
                        help="Switches between master mode and worker mode")
    parser.add_argument('--sync', type=str, required=False, nargs='*', default=[False],
                        help="Sync via mqtt. Defaults to channel bbo/sync/fr_idx")
    parser.add_argument('-log', '--loglevel', default='info', help='Provide logging level')

    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel.upper())

    input_path = os.path.expanduser(args.INPUT_PATH)
    logger.log(logging.INFO, f"Input path: {input_path}")

    if args.merge is not None:
        label_lib.merge(args.merge, target_file=input_path, overwrite=True, yml_only=args.yml_only)

    if args.add is not None:
        label_lib.merge(args.add, target_file=input_path, overwrite=False, yml_only=args.yml_only)
    elif args.combine_cams is not None:
        label_lib.combine_cams(args.combine_cams, target_file=input_path, yml_only=args.yml_only)
    else:
        app = QApplication([])
        gui = ui.MainWindow(Path(input_path), sync=args.sync[0] if len(args.sync)>0 else "bbo/sync/fr_idx")
        gui.show()
        app.exec_()

    return


if __name__ == '__main__':
    main()
