"""Measurements for the current transfer, never a synthetic whole-task percentage."""
import math
import time
from video_parser.services import task_runtime


class TransferProgress:
    def __init__(self, track=1, tracks=1):
        self.track = track
        self.tracks = tracks
        self.started = time.monotonic()

    def report(self, received, total=0, *, estimated=False, finished=False):
        elapsed = time.monotonic() - self.started
        values = {'bytes': received, 'total_bytes': total, 'track': self.track,
                  'tracks': self.tracks, 'estimated_total': int(estimated), 'sampled_at': time.time()}
        # Connection/extraction time is excluded. Early samples are too noisy for ETA.
        if elapsed >= .5 and received > 0 and not finished:
            speed = received / elapsed
            if math.isfinite(speed) and speed > 0:
                values['speed_bytes_per_second'] = speed
                if total > received:
                    values['eta_seconds'] = (total - received) / speed
        task_runtime.progress('downloading', '正在下载当前音视频轨道…', force=finished, **values)
