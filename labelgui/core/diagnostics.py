"""Plain-text diagnostics for the current camera frames."""
import numpy as np


def format_frame_report(time, frames, annotations, references):
    """Describe stored points and their metadata, without generating guesses."""
    rows = [('Camera', 'Frame', 'Source', 'Label', 'X', 'Y', 'Labeler', 'Point time (Unix s)')]
    stores = [('labels', annotations)] + [(f'reference[{i}]', store) for i, store in enumerate(references)]
    for camera, frame in enumerate(frames):
        for source, store in stores:
            users = store.data.get('labeler_list', [])
            for point in store.points(frame, camera, include_guesses=False):
                entry = store.data['labels'][point.name][frame]
                indices = entry.get('labeler', ())
                labeler = '-'
                if camera < len(indices):
                    index = indices[camera]
                    if np.isfinite(index) and index == int(index) and 0 <= index < len(users):
                        labeler = users[int(index)]
                times = entry.get('point_times', ())
                point_time = times[camera] if camera < len(times) else np.nan
                rows.append((str(camera), str(frame), source, point.name,
                             f'{point.coords[0]:.6g}', f'{point.coords[1]:.6g}', labeler,
                             f'{point_time:.6f}' if np.isfinite(point_time) else '-'))
    rows = [[str(value).replace('\n', '\\n').replace('\r', '\\r').replace('\t', ' ')
             for value in row] for row in rows]
    widths = [max(map(len, column)) for column in zip(*rows)]
    table = [' | '.join(value.ljust(width) for value, width in zip(row, widths)) for row in rows]
    table.insert(1, '-+-'.join('-' * width for width in widths))
    if len(rows) == 1:
        table.append('(no stored labels on these frames)')
    camera_frames = ', '.join(f'camera {camera} = {frame}' for camera, frame in enumerate(frames))
    return f'Time: {time:.6f} s\nFrames: {camera_frames}\n' + '\n'.join(table)
