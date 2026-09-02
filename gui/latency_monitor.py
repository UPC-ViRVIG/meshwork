import csv
import time
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QTimer, Qt

from logger import get_logger


class UILatencyMonitor(QObject):

    def __init__(self, interval_ms: int = 100, report_interval_s: float = 30.0,
                 csv_path: Optional[Path] = None, parent=None):
        super().__init__(parent)
        self.logger = get_logger()
        self.interval_ms = int(interval_ms)
        self.report_interval_s = float(report_interval_s)
        self.csv_path = Path(csv_path) if csv_path else None

        self._timer = QTimer(self)
        self._timer.setInterval(self.interval_ms)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)

        self._last_tick = None
        self._window_start = None
        self._samples = []

    def start(self):
        now = time.perf_counter()
        self._last_tick = now
        self._window_start = now
        self._samples = []
        self._timer.start()
        self.logger.info(
            f"UI latency monitor started (tick={self.interval_ms}ms, "
            f"report every {self.report_interval_s:.0f}s, csv={self.csv_path})"
        )

    def stop(self):
        if self._timer.isActive():
            self._timer.stop()
        self._flush()

    def _on_tick(self):
        now = time.perf_counter()
        expected = self.interval_ms / 1000.0
        delay_ms = max(0.0, (now - self._last_tick - expected) * 1000.0)
        self._last_tick = now
        self._samples.append(delay_ms)
        if now - self._window_start >= self.report_interval_s:
            self._flush()
            self._window_start = now

    def _flush(self):
        if not self._samples:
            return
        arr = np.asarray(self._samples, dtype=float)
        self._samples = []
        stats = {
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'samples': int(arr.size),
            'p50_ms': float(np.percentile(arr, 50)),
            'p95_ms': float(np.percentile(arr, 95)),
            'p99_ms': float(np.percentile(arr, 99)),
            'max_ms': float(arr.max()),
        }
        self.logger.info(
            f"UI event-loop latency: p50={stats['p50_ms']:.1f}ms p95={stats['p95_ms']:.1f}ms "
            f"p99={stats['p99_ms']:.1f}ms max={stats['max_ms']:.1f}ms (n={stats['samples']})"
        )
        if self.csv_path is None:
            return
        try:
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not self.csv_path.exists()
            with open(self.csv_path, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(stats.keys()))
                if write_header:
                    writer.writeheader()
                writer.writerow(stats)
        except IOError as e:
            self.logger.warning(f"Failed to write UI latency CSV: {e}")
