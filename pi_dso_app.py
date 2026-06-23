#!/usr/bin/env python3
"""
Raspberry Pi — Speech DSO Application (fixed for 48kHz 32bit stereo)
"""

import sys
import numpy as np
import sounddevice as sd
import scipy.signal as signal
from collections import deque
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

SAMPLE_RATE      = 48000
CHUNK_SIZE       = 512
DISPLAY_SECONDS  = 0.05
FFT_SIZE         = 2048
SPEC_HISTORY     = 200
DEVICE_KEYWORD   = "googlevoicehat"

DISPLAY_SAMPLES  = int(SAMPLE_RATE * DISPLAY_SECONDS)

NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
def freq_to_note(f):
    if f <= 0:
        return "—"
    midi = 69 + 12 * np.log2(f / 440.0)
    note = NOTE_NAMES[int(round(midi)) % 12]
    octave = int(round(midi)) // 12 - 1
    return f"{note}{octave}"

def find_device():
    devs = sd.query_devices()
    for i, d in enumerate(devs):
        if DEVICE_KEYWORD in d["name"].lower() and d["max_input_channels"] > 0:
            return i
    return None

def compute_fft(samples):
    n = len(samples)
    if n < FFT_SIZE:
        samples = np.pad(samples, (0, FFT_SIZE - n))
    window   = np.hanning(FFT_SIZE)
    spectrum = np.abs(np.fft.rfft(samples[:FFT_SIZE] * window))
    freqs    = np.fft.rfftfreq(FFT_SIZE, d=1.0 / SAMPLE_RATE)
    spectrum_db = 20 * np.log10(spectrum / FFT_SIZE + 1e-9)
    return freqs, spectrum_db

def rms(samples):
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))

def peak(samples):
    return float(np.max(np.abs(samples)))

def thd_percent(samples):
    n = len(samples)
    if n < FFT_SIZE:
        samples = np.pad(samples, (0, FFT_SIZE - n))
    spectrum = np.abs(np.fft.rfft(samples[:FFT_SIZE] * np.hanning(FFT_SIZE)))
    freqs    = np.fft.rfftfreq(FFT_SIZE, d=1.0 / SAMPLE_RATE)
    lo, hi   = np.searchsorted(freqs, 80), np.searchsorted(freqs, 4000)
    if lo >= hi:
        return 0.0, 0.0
    f0_idx   = lo + np.argmax(spectrum[lo:hi])
    f0_amp   = spectrum[f0_idx]
    if f0_amp < 1.0:
        return 0.0, 0.0
    harmonic_power = 0.0
    for h in range(2, 7):
        idx = f0_idx * h
        if idx < len(spectrum):
            harmonic_power += spectrum[idx] ** 2
    thd = 100.0 * np.sqrt(harmonic_power) / f0_amp
    return float(thd), float(freqs[f0_idx])

class DSO(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Speech DSO  —  ESP32 + Raspberry Pi")
        self.setMinimumSize(1024, 600)
        pg.setConfigOption("background", "#0d0d0d")
        pg.setConfigOption("foreground", "#e0e0e0")
        self._buf = deque(np.zeros(DISPLAY_SAMPLES, dtype=np.float32), maxlen=DISPLAY_SAMPLES)
        self._spec_buf = np.full((FFT_SIZE // 2 + 1, SPEC_HISTORY), -80.0)
        self._col_idx  = 0
        self._stream   = None
        self._paused   = False
        self._build_ui()
        self._start_stream()
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._refresh)
        self._timer.start(40)

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(8, 8, 8, 8)
        top = QtWidgets.QHBoxLayout()
        self._lbl_rms  = self._meter_label("RMS: —")
        self._lbl_peak = self._meter_label("Peak: —")
        self._lbl_thd  = self._meter_label("THD: —")
        self._lbl_freq = self._meter_label("F0: —")
        self._lbl_note = self._meter_label("Note: —")
        for w in [self._lbl_rms, self._lbl_peak, self._lbl_thd, self._lbl_freq, self._lbl_note]:
            top.addWidget(w)
        top.addStretch()
        self._btn_pause = QtWidgets.QPushButton("Pause")
        self._btn_pause.setFixedWidth(90)
        self._btn_pause.clicked.connect(self._toggle_pause)
        self._btn_pause.setStyleSheet("background:#1a1a2e;color:#e0e0e0;border:1px solid #444;padding:4px;")
        top.addWidget(self._btn_pause)
        root.addLayout(top)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self._wave_plot = pg.PlotWidget(title="Time domain  (50 ms window)")
        self._wave_plot.setLabel("left", "Amplitude")
        self._wave_plot.setLabel("bottom", "Time", units="s")
        self._wave_plot.setYRange(-2**30, 2**30)
        t_axis = np.linspace(0, DISPLAY_SECONDS, DISPLAY_SAMPLES)
        self._wave_curve = self._wave_plot.plot(t_axis, np.zeros(DISPLAY_SAMPLES), pen=pg.mkPen("#00e5ff", width=1))
        self._wave_plot.showGrid(x=True, y=True, alpha=0.2)
        self._wave_plot.addLine(y=0, pen=pg.mkPen("#444", style=QtCore.Qt.DashLine))
        splitter.addWidget(self._wave_plot)
        self._fft_plot = pg.PlotWidget(title="FFT spectrum")
        self._fft_plot.setLabel("left", "Magnitude", units="dB")
        self._fft_plot.setLabel("bottom", "Frequency", units="Hz")
        self._fft_plot.setXRange(0, SAMPLE_RATE // 2)
        self._fft_plot.setYRange(-90, 0)
        self._fft_curve = self._fft_plot.plot(pen=pg.mkPen("#ff6d00", width=1))
        lr = pg.LinearRegionItem([300, 3400], movable=False, brush=pg.mkBrush(255, 255, 0, 18))
        lr.setZValue(-10)
        self._fft_plot.addItem(lr)
        self._fft_plot.showGrid(x=True, y=True, alpha=0.2)
        splitter.addWidget(self._fft_plot)
        spec_widget = pg.PlotWidget(title="Spectrogram  (rolling)")
        spec_widget.setLabel("left", "Frequency", units="Hz")
        spec_widget.setLabel("bottom", "Time", units="frames")
        self._spec_img = pg.ImageItem()
        spec_widget.addItem(self._spec_img)
        cmap = pg.colormap.get("inferno")
        self._spec_img.setColorMap(cmap)
        self._spec_img.setLevels([-80, 0])
        self._spec_img.setRect(QtCore.QRectF(0.0, 0.0, float(SPEC_HISTORY), float(SAMPLE_RATE // 2)))
        splitter.addWidget(spec_widget)
        splitter.setSizes([220, 200, 180])
        root.addWidget(splitter)

    def _meter_label(self, text):
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet("background:#111;color:#00e5ff;border:1px solid #333;padding:4px 10px;border-radius:4px;font-family:monospace;font-size:13px;")
        lbl.setFixedHeight(30)
        return lbl

    def _start_stream(self):
        dev = find_device()
        if dev is None:
            print("[WARN] Device not found — using default input")
        else:
            print(f"[I2S] Using device #{dev}: {sd.query_devices(dev)['name']}")
        try:
            self._stream = sd.InputStream(
                device=dev, samplerate=SAMPLE_RATE, channels=2,
                dtype="int32", blocksize=CHUNK_SIZE, callback=self._audio_callback)
            self._stream.start()
            print("[STREAM] Started OK")
        except Exception as e:
            print(f"[ERROR] Could not open audio stream: {e}")

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"[STREAM] {status}")
        if not self._paused:
            mono = indata[:, 0].astype(np.float32)
            self._buf.extend(mono)
            arr = np.array(self._buf, dtype=np.float32)
            if len(arr) >= FFT_SIZE:
                _, col = compute_fft(arr[-FFT_SIZE:])
            else:
                _, col = compute_fft(arr)
            self._spec_buf[:, self._col_idx] = col
            self._col_idx = (self._col_idx + 1) % SPEC_HISTORY

    def _refresh(self):
        arr = np.array(self._buf, dtype=np.float32)
        if len(arr) < DISPLAY_SAMPLES:
            return
        t = np.linspace(0, DISPLAY_SECONDS, DISPLAY_SAMPLES)
        self._wave_curve.setData(t, arr)
        freqs, spec_db = compute_fft(arr)
        self._fft_curve.setData(freqs, spec_db)
        disp = np.roll(self._spec_buf, -self._col_idx, axis=1)
        self._spec_img.setImage(disp.T, autoLevels=False)
        r = rms(arr)
        p = peak(arr)
        thd, f0 = thd_percent(arr[-FFT_SIZE:] if len(arr) >= FFT_SIZE else arr)
        self._lbl_rms.setText( f"RMS:  {r:10.0f}")
        self._lbl_peak.setText(f"Peak: {p:10.0f}")
        self._lbl_thd.setText( f"THD:  {thd:5.1f}%")
        self._lbl_freq.setText(f"F0:   {f0:6.1f} Hz")
        self._lbl_note.setText(f"Note: {freq_to_note(f0)}")

    def _toggle_pause(self):
        self._paused = not self._paused
        self._btn_pause.setText("Resume" if self._paused else "Pause")

    def closeEvent(self, _):
        if self._stream:
            self._stream.stop()
            self._stream.close()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window,          QtGui.QColor("#0d0d0d"))
    palette.setColor(QtGui.QPalette.WindowText,      QtGui.QColor("#e0e0e0"))
    palette.setColor(QtGui.QPalette.Base,            QtGui.QColor("#111111"))
    palette.setColor(QtGui.QPalette.Text,            QtGui.QColor("#e0e0e0"))
    palette.setColor(QtGui.QPalette.Button,          QtGui.QColor("#1a1a2e"))
    palette.setColor(QtGui.QPalette.ButtonText,      QtGui.QColor("#e0e0e0"))
    palette.setColor(QtGui.QPalette.Highlight,       QtGui.QColor("#00e5ff"))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#000000"))
    app.setPalette(palette)
    win = DSO()
    win.showFullScreen()
    sys.exit(app.exec_())
