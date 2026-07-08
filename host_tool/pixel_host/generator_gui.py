"""Standalone PySide6 GUI for offline video-to-pixelbin generation."""

from __future__ import annotations

import os
import queue
import threading

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import (
        QApplication,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - exercised only without PySide6.
    raise SystemExit("PySide6 is not installed. Run: .\\setup_host_env.ps1") from exc

from .video_generator import VideoGenerateOptions, generate_pixelbin_from_video


class GenerateWorker(threading.Thread):
    """Run OpenCV conversion outside the Qt event loop."""

    def __init__(self, options: VideoGenerateOptions, messages: queue.Queue[tuple[str, object]]) -> None:
        super().__init__(daemon=True)
        self.options = options
        self.messages = messages

    def run(self) -> None:
        try:
            result = generate_pixelbin_from_video(
                self.options,
                progress=lambda done, total: self.messages.put(("progress", (done, total))),
                log=lambda message: self.messages.put(("log", message)),
            )
            self.messages.put(("done", result))
        except Exception as exc:  # noqa: BLE001
            self.messages.put(("error", str(exc)))


class MainWindow(QMainWindow):
    """Small offline utility for preparing playback files."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pixel Offline Generator")
        self.resize(820, 560)

        self.worker: GenerateWorker | None = None
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()

        self.message_timer = QTimer(self)
        self.message_timer.timeout.connect(self._drain_messages)
        self.message_timer.start(100)

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.addWidget(self._build_file_group())
        layout.addWidget(self._build_options_group())
        layout.addWidget(self._build_progress_group())
        layout.addWidget(self._build_log_group(), 1)

    def _build_file_group(self) -> QGroupBox:
        group = QGroupBox("Files")
        layout = QGridLayout(group)

        self.input_edit = QLineEdit()
        self.output_edit = QLineEdit()
        self.preview_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Select source video")
        self.output_edit.setPlaceholderText("Select output .pixelbin")
        self.preview_edit.setPlaceholderText("Optional preview .mp4")

        input_button = QPushButton("Browse")
        output_button = QPushButton("Browse")
        preview_button = QPushButton("Browse")
        input_button.clicked.connect(self._select_input)
        output_button.clicked.connect(self._select_output)
        preview_button.clicked.connect(self._select_preview)

        layout.addWidget(QLabel("Input video"), 0, 0)
        layout.addWidget(self.input_edit, 0, 1)
        layout.addWidget(input_button, 0, 2)
        layout.addWidget(QLabel("Output file"), 1, 0)
        layout.addWidget(self.output_edit, 1, 1)
        layout.addWidget(output_button, 1, 2)
        layout.addWidget(QLabel("Preview MP4"), 2, 0)
        layout.addWidget(self.preview_edit, 2, 1)
        layout.addWidget(preview_button, 2, 2)
        layout.setColumnStretch(1, 1)
        return group

    def _build_options_group(self) -> QGroupBox:
        group = QGroupBox("Options")
        layout = QGridLayout(group)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 240)
        self.fps_spin.setValue(60)

        self.start_spin = self._seconds_spin(0.0)
        self.end_spin = self._seconds_spin(0.0)
        self.brightness_spin = self._factor_spin(1.0, 0.1, 4.0)
        self.gamma_spin = self._factor_spin(1.0, 0.1, 4.0)
        self.saturation_spin = self._factor_spin(1.0, 0.0, 4.0)
        self.ww_spin = self._level_spin(0)
        self.cw_spin = self._level_spin(0)

        form_left = QFormLayout()
        form_left.addRow("FPS", self.fps_spin)
        form_left.addRow("Start s", self.start_spin)
        form_left.addRow("End s", self.end_spin)
        form_left.addRow("WW", self.ww_spin)
        form_left.addRow("CW", self.cw_spin)

        form_right = QFormLayout()
        form_right.addRow("Brightness", self.brightness_spin)
        form_right.addRow("Gamma", self.gamma_spin)
        form_right.addRow("Saturation", self.saturation_spin)
        form_right.addRow("ROI", QLabel("Center crop 2:3"))
        form_right.addRow("Output", QLabel("32 x 48, 4 boards"))

        self.generate_button = QPushButton("Generate")
        self.generate_button.clicked.connect(self._generate)

        layout.addLayout(form_left, 0, 0)
        layout.addLayout(form_right, 0, 1)
        layout.addWidget(self.generate_button, 1, 0, 1, 2)
        return group

    def _build_progress_group(self) -> QGroupBox:
        group = QGroupBox("Progress")
        layout = QVBoxLayout(group)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_label = QLabel("Idle")
        self.progress_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Log")
        layout = QVBoxLayout(group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        return group

    @staticmethod
    def _seconds_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 24.0 * 3600.0)
        spin.setDecimals(3)
        spin.setSingleStep(1.0)
        spin.setValue(value)
        return spin

    @staticmethod
    def _factor_spin(value: float, minimum: float, maximum: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(3)
        spin.setSingleStep(0.05)
        spin.setValue(value)
        return spin

    @staticmethod
    def _level_spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 1000)
        spin.setSingleStep(10)
        spin.setValue(value)
        return spin

    def _select_input(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Select source video",
            "",
            "Video/GIF Files (*.mp4 *.avi *.mov *.mkv *.wmv *.gif);;All Files (*)",
        )
        if not path:
            return
        self.input_edit.setText(path)
        if not self.output_edit.text().strip():
            base, _ext = os.path.splitext(path)
            self.output_edit.setText(base + ".pixelbin")
        if not self.preview_edit.text().strip():
            base, _ext = os.path.splitext(path)
            self.preview_edit.setText(base + "_preview.mp4")

    def _select_output(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Save pixelbin file",
            "",
            "PixelBin Files (*.pixelbin);;All Files (*)",
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".pixelbin"
        self.output_edit.setText(path)

    def _select_preview(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Save preview mp4",
            "",
            "MP4 Files (*.mp4);;All Files (*)",
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".mp4"
        self.preview_edit.setText(path)

    def _generate(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self._log("Generation is already running")
            return

        options = VideoGenerateOptions(
            input_path=self.input_edit.text().strip(),
            output_path=self.output_edit.text().strip(),
            preview_mp4_path=self.preview_edit.text().strip(),
            fps=self.fps_spin.value(),
            start_s=self.start_spin.value(),
            end_s=self.end_spin.value(),
            brightness=self.brightness_spin.value(),
            gamma=self.gamma_spin.value(),
            saturation=self.saturation_spin.value(),
            ww=self.ww_spin.value(),
            cw=self.cw_spin.value(),
        )

        self.progress_bar.setValue(0)
        self.progress_label.setText("Starting...")
        self.generate_button.setEnabled(False)
        self._log(f"GENERATE input={options.input_path}")
        self._log(f"GENERATE output={options.output_path}")
        if options.preview_mp4_path:
            self._log(f"GENERATE preview={options.preview_mp4_path}")
        self.worker = GenerateWorker(options, self.messages)
        self.worker.start()

    def _drain_messages(self) -> None:
        while True:
            try:
                kind, payload = self.messages.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self._log(str(payload))
            elif kind == "progress":
                done, total = payload  # type: ignore[misc]
                total_int = int(total)
                done_int = int(done)
                if total_int > 0:
                    percent = min(100, int(done_int * 100 / total_int))
                    self.progress_bar.setValue(percent)
                    self.progress_label.setText(f"{done_int}/{total_int} frames")
                else:
                    self.progress_label.setText(f"{done_int} frames")
            elif kind == "done":
                result = payload
                self.progress_bar.setValue(100)
                self.progress_label.setText("Done")
                self._log(
                    "DONE "
                    f"frames={result.frames_written} fps={result.fps} "  # type: ignore[attr-defined]
                    f"duration={result.duration_s:.2f}s output={result.output_path}"  # type: ignore[attr-defined]
                )
                if result.preview_mp4_path:  # type: ignore[attr-defined]
                    self._log(f"PREVIEW output={result.preview_mp4_path}")  # type: ignore[attr-defined]
                self.generate_button.setEnabled(True)
                self.worker = None
            elif kind == "error":
                message = str(payload)
                self.progress_label.setText("Failed")
                self._log(f"ERROR {message}")
                QMessageBox.critical(self, "Generation failed", message)
                self.generate_button.setEnabled(True)
                self.worker = None

    def _log(self, message: str) -> None:
        self.log_text.append(message)


def run() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
