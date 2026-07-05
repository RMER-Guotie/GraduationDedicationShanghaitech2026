"""PySide6 debug GUI for one Pixel Controller board."""

from __future__ import annotations

from dataclasses import asdict
import math
from typing import Callable, Optional

try:
    from PySide6.QtCore import Qt, QElapsedTimer, QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - exercised only without PySide6.
    raise SystemExit("PySide6 is not installed. Run: pip install -r requirements.txt") from exc

from . import protocol as proto
from .device import FrameTiming, PixelDevice
from .serial_link import SerialLink, list_serial_ports

DEFAULT_CHUNK_DELAY_S = 0.0016
STRESS_POINT_DURATION_MS = 8000
# Sweep chunk pacing at a fixed target to find the stable closed-loop limit.
STRESS_POINTS = (
    (60, 2.00),
    (60, 1.75),
    (60, 1.60),
    (60, 1.50),
    (60, 1.25),
    (60, 1.00),
    (60, 0.75),
    (60, 0.50),
)


class MainWindow(QMainWindow):
    """Small synchronous debug panel for firmware bring-up."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pixel Controller Host Tool")
        self.resize(920, 620)

        self.device: Optional[PixelDevice] = None
        self.link: Optional[SerialLink] = None
        self.breath_timer = QTimer(self)
        self.breath_timer.timeout.connect(self.send_breath_frame)
        self.breath_phase = 0.0
        self.breath_busy = False
        self.breath_sent_frames = 0
        self.breath_fps_timer = QElapsedTimer()
        self.stress_timer = QTimer(self)
        self.stress_timer.timeout.connect(self.send_stress_frame)
        self.stress_index = 0
        self.stress_busy = False
        self.stress_ok_frames = 0
        self.stress_timeout_count = 0
        self.stress_commit_error_count = 0
        self.stress_last_mask = 0
        self.stress_target_fps = 0
        self.stress_delay_ms = 0.0
        self.stress_start_errors = 0
        self.stress_start_commits = 0
        self.stress_frame_time_total_ms = 0.0
        self.stress_begin_total_ms = 0.0
        self.stress_chunks_total_ms = 0.0
        self.stress_pacing_total_ms = 0.0
        self.stress_commit_write_total_ms = 0.0
        self.stress_response_wait_total_ms = 0.0
        self.stress_elapsed_timer = QElapsedTimer()

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_status_group())
        layout.addWidget(self._build_output_group())
        layout.addWidget(self._build_log_group(), 1)

        self.refresh_ports()
        self._set_connected(False)

    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox("Connection")
        row = QHBoxLayout(group)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(180)
        self.baud_spin = QSpinBox()
        self.baud_spin.setRange(1200, 4000000)
        self.baud_spin.setValue(115200)
        self.baud_spin.setSingleStep(115200)

        self.refresh_button = QPushButton("Refresh")
        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")

        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.connect_device)
        self.disconnect_button.clicked.connect(self.disconnect_device)

        row.addWidget(QLabel("Port"))
        row.addWidget(self.port_combo, 1)
        row.addWidget(QLabel("Baud"))
        row.addWidget(self.baud_spin)
        row.addWidget(self.refresh_button)
        row.addWidget(self.connect_button)
        row.addWidget(self.disconnect_button)
        return group

    def _build_status_group(self) -> QGroupBox:
        group = QGroupBox("Device")
        layout = QGridLayout(group)

        self.hello_button = QPushButton("HELLO")
        self.status_button = QPushButton("STATUS")
        self.auto_status_check = QCheckBox("Auto status after command")
        self.auto_status_check.setChecked(True)

        self.info_label = QLabel("Not connected")
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.hello_button.clicked.connect(self.request_hello)
        self.status_button.clicked.connect(self.request_status)

        layout.addWidget(self.hello_button, 0, 0)
        layout.addWidget(self.status_button, 0, 1)
        layout.addWidget(self.auto_status_check, 0, 2)
        layout.addWidget(self.info_label, 1, 0, 1, 3)
        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("Output")
        layout = QGridLayout(group)

        self.r_spin = self._byte_spin(255)
        self.g_spin = self._byte_spin(0)
        self.b_spin = self._byte_spin(0)
        self.ww_spin = self._level_spin(0)
        self.cw_spin = self._level_spin(0)
        self.breath_fps_spin = QSpinBox()
        self.breath_fps_spin.setRange(1, 90)
        self.breath_fps_spin.setValue(20)
        self.breath_period_spin = QDoubleSpinBox()
        self.breath_period_spin.setRange(0.5, 20.0)
        self.breath_period_spin.setDecimals(1)
        self.breath_period_spin.setSingleStep(0.5)
        self.breath_period_spin.setValue(3.0)
        self.breath_period_spin.setSuffix(" s")
        self.breath_delay_spin = QDoubleSpinBox()
        self.breath_delay_spin.setRange(0.5, 3.0)
        self.breath_delay_spin.setDecimals(2)
        self.breath_delay_spin.setSingleStep(0.25)
        self.breath_delay_spin.setValue(DEFAULT_CHUNK_DELAY_S * 1000.0)
        self.breath_delay_spin.setSuffix(" ms")

        form = QFormLayout()
        form.addRow("R", self.r_spin)
        form.addRow("G", self.g_spin)
        form.addRow("B", self.b_spin)
        form.addRow("WW", self.ww_spin)
        form.addRow("CW", self.cw_spin)
        form.addRow("Breath FPS", self.breath_fps_spin)
        form.addRow("Breath period", self.breath_period_spin)
        form.addRow("Breath delay", self.breath_delay_spin)

        self.send_solid_button = QPushButton("Send Solid")
        self.start_breath_button = QPushButton("Start Breath")
        self.stop_breath_button = QPushButton("Stop")
        self.start_stress_button = QPushButton("Start Stress")
        self.stop_stress_button = QPushButton("Stop Stress")

        self.send_solid_button.clicked.connect(self.send_solid)
        self.start_breath_button.clicked.connect(self.start_breath)
        self.stop_breath_button.clicked.connect(self.stop_breath)
        self.start_stress_button.clicked.connect(self.start_stress)
        self.stop_stress_button.clicked.connect(self.stop_stress)

        button_row = QHBoxLayout()
        button_row.addWidget(self.send_solid_button)
        button_row.addWidget(self.start_breath_button)
        button_row.addWidget(self.stop_breath_button)
        button_row.addWidget(self.start_stress_button)
        button_row.addWidget(self.stop_stress_button)
        button_row.addStretch(1)

        layout.addLayout(form, 0, 0)
        layout.addLayout(button_row, 0, 1)
        layout.setColumnStretch(1, 1)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Log")
        layout = QVBoxLayout(group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        return group

    @staticmethod
    def _byte_spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 255)
        spin.setValue(value)
        return spin

    @staticmethod
    def _level_spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 1000)
        spin.setValue(value)
        spin.setSingleStep(10)
        return spin

    def refresh_ports(self) -> None:
        current = self.port_combo.currentText()
        self.port_combo.clear()
        try:
            ports = list_serial_ports()
        except Exception as exc:  # noqa: BLE001
            self.log(f"Port scan failed: {exc}")
            ports = []
        self.port_combo.addItems(ports)
        if current:
            index = self.port_combo.findText(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)

    def connect_device(self) -> None:
        port = self.port_combo.currentText().strip()
        if not port:
            QMessageBox.warning(self, "No port", "Select a serial port first.")
            return

        self.disconnect_device(log_disconnect=False)
        try:
            self.link = SerialLink(port, baudrate=self.baud_spin.value(), timeout=0.05)
            self.link.open()
            self.device = PixelDevice(self.link)
            self._set_connected(True)
            self.log(f"Connected {port} @ {self.baud_spin.value()}")
            self.request_hello()
        except Exception as exc:  # noqa: BLE001
            self.device = None
            self.link = None
            self._set_connected(False)
            self.log(f"Connect failed: {exc}")
            QMessageBox.critical(self, "Connect failed", str(exc))

    def disconnect_device(self, log_disconnect: bool = True) -> None:
        self.stop_breath(log_stop=False)
        self.stop_stress(log_stop=False)
        if self.link is not None:
            self.link.close()
        if log_disconnect and self.device is not None:
            self.log("Disconnected")
        self.device = None
        self.link = None
        self._set_connected(False)

    def request_hello(self) -> None:
        def op() -> None:
            assert self.device is not None
            hello = self.device.hello()
            self.info_label.setText(
                f"uid={proto.format_uid(hello.uid_hash)} role=0x{hello.role_id:02x} "
                f"lanes={hello.lanes} leds/lane={hello.leds_per_lane} chunks={hello.chunk_count}"
            )
            self.log(f"HELLO {asdict(hello)}")

        self._run_device_op("HELLO", op)

    def request_status(self) -> None:
        def op() -> None:
            assert self.device is not None
            status = self.device.status()
            self._show_status(status)

        self._run_device_op("STATUS", op)

    def send_solid(self) -> None:
        self.stop_breath(log_stop=False)
        self.stop_stress(log_stop=False)

        def op() -> None:
            assert self.device is not None
            commit = self.device.send_solid(
                self.r_spin.value(),
                self.g_spin.value(),
                self.b_spin.value(),
                ww=self.ww_spin.value(),
                cw=self.cw_spin.value(),
                chunk_delay_s=self._chunk_delay_s(),
            )
            self.log(f"SOLID commit={asdict(commit)} {self._last_frame_timing_text()}")
            self._maybe_status()

        self._run_device_op("Send solid", op)

    def start_breath(self) -> None:
        if self.device is None:
            QMessageBox.warning(self, "Not connected", "Connect to a device first.")
            return

        self.stop_stress(log_stop=False)
        interval_ms = max(1, int(1000 / self.breath_fps_spin.value()))
        self.breath_phase = 0.0
        self.breath_sent_frames = 0
        self.breath_fps_timer.restart()
        self.breath_timer.start(interval_ms)
        self._set_controls_enabled(True)
        self.log(
            f"BREATH started target={self.breath_fps_spin.value()}fps "
            f"period={self.breath_period_spin.value():.1f}s delay={self._breath_chunk_delay_s() * 1000.0:.2f}ms"
        )

    def stop_breath(self, log_stop: bool = True) -> None:
        if self.breath_timer.isActive():
            self.breath_timer.stop()
            if log_stop:
                self.log("BREATH stopped")
        self._set_controls_enabled(self.device is not None)

    def send_breath_frame(self) -> None:
        if self.device is None or self.breath_busy:
            return

        self.breath_busy = True
        try:
            commit = self.device.send_frame(
                self._build_breath_frame(),
                ww=self.ww_spin.value(),
                cw=self.cw_spin.value(),
                chunk_delay_s=self._breath_chunk_delay_s(),
            )
            self.breath_phase += 1.0 / max(1, self.breath_fps_spin.value())
            self._update_breath_fps_log(commit.status)
        except Exception as exc:  # noqa: BLE001
            self.stop_breath(log_stop=False)
            self.log(f"BREATH failed: {exc}")
            QMessageBox.critical(self, "Breath failed", str(exc))
        finally:
            self.breath_busy = False

    def _build_breath_frame(self) -> bytes:
        period_s = max(0.5, self.breath_period_spin.value())
        breath = 0.5 - 0.5 * math.cos((2.0 * math.pi * self.breath_phase) / period_s)
        floor = 0.08
        level = floor + (1.0 - floor) * breath
        frame = bytearray()

        for lane in range(proto.LANES):
            lane_hue = (self.breath_phase * 0.12 + lane / proto.LANES) % 1.0
            for pixel in range(proto.LEDS_PER_LANE):
                hue = (lane_hue + pixel / (proto.LEDS_PER_LANE * 2.0)) % 1.0
                r, g, b = self._hsv_to_rgb(hue, 1.0, level)
                frame.extend((r, g, b))

        return bytes(frame)

    @staticmethod
    def _hsv_to_rgb(hue: float, saturation: float, value: float) -> tuple[int, int, int]:
        hue = hue % 1.0
        sector = int(hue * 6.0)
        fraction = hue * 6.0 - sector
        p = value * (1.0 - saturation)
        q = value * (1.0 - fraction * saturation)
        t = value * (1.0 - (1.0 - fraction) * saturation)

        if sector == 0:
            r, g, b = value, t, p
        elif sector == 1:
            r, g, b = q, value, p
        elif sector == 2:
            r, g, b = p, value, t
        elif sector == 3:
            r, g, b = p, q, value
        elif sector == 4:
            r, g, b = t, p, value
        else:
            r, g, b = value, p, q

        return int(r * 255.0), int(g * 255.0), int(b * 255.0)

    def _chunk_delay_s(self) -> float:
        return DEFAULT_CHUNK_DELAY_S

    def _breath_chunk_delay_s(self) -> float:
        return self.breath_delay_spin.value() / 1000.0

    def _update_breath_fps_log(self, status: int) -> None:
        self.breath_sent_frames += 1
        elapsed_ms = self.breath_fps_timer.elapsed()
        if elapsed_ms >= 1000:
            actual_fps = self.breath_sent_frames * 1000.0 / elapsed_ms
            self.log(
                f"BREATH actual={actual_fps:.1f}fps target={self.breath_fps_spin.value()} "
                f"status={status} {self._last_frame_timing_text()}"
            )
            self.breath_sent_frames = 0
            self.breath_fps_timer.restart()

    def start_stress(self) -> None:
        if self.device is None:
            QMessageBox.warning(self, "Not connected", "Connect to a device first.")
            return

        self.stop_breath(log_stop=False)
        self.stress_index = 0
        self.log("STRESS started")
        self._start_stress_point()

    def stop_stress(self, log_stop: bool = True) -> None:
        if self.stress_timer.isActive():
            self.stress_timer.stop()
            if log_stop:
                self.log("STRESS stopped")
        self._set_controls_enabled(self.device is not None)

    def _start_stress_point(self) -> None:
        if self.device is None:
            return

        if self.stress_index >= len(STRESS_POINTS):
            self.stress_timer.stop()
            self.log("STRESS complete")
            self._set_controls_enabled(True)
            return

        self.stress_target_fps, self.stress_delay_ms = STRESS_POINTS[self.stress_index]
        self.stress_ok_frames = 0
        self.stress_timeout_count = 0
        self.stress_commit_error_count = 0
        self.stress_last_mask = 0
        self.stress_frame_time_total_ms = 0.0
        self.stress_begin_total_ms = 0.0
        self.stress_chunks_total_ms = 0.0
        self.stress_pacing_total_ms = 0.0
        self.stress_commit_write_total_ms = 0.0
        self.stress_response_wait_total_ms = 0.0
        start_status = self._try_status()
        if start_status is not None:
            self.stress_start_errors = start_status.error_count
            self.stress_start_commits = start_status.commit_count
        else:
            self.stress_start_errors = 0
            self.stress_start_commits = 0
        self.breath_phase = 0.0
        self.stress_elapsed_timer.restart()
        self.stress_timer.start(max(1, int(1000 / self.stress_target_fps)))
        self._set_controls_enabled(True)
        self.log(
            f"STRESS point {self.stress_index + 1}/{len(STRESS_POINTS)} "
            f"target={self.stress_target_fps}fps delay={self.stress_delay_ms:.2f}ms"
        )

    def send_stress_frame(self) -> None:
        if self.device is None or self.stress_busy:
            return

        self.stress_busy = True
        try:
            frame_start_ms = self.stress_elapsed_timer.elapsed()
            commit = self.device.send_frame(
                self._build_breath_frame(),
                ww=self.ww_spin.value(),
                cw=self.cw_spin.value(),
                chunk_delay_s=self.stress_delay_ms / 1000.0,
            )
            self._accumulate_stress_timing(self.device.last_frame_timing)
            if self.device.last_frame_timing is None:
                self.stress_frame_time_total_ms += (self.stress_elapsed_timer.elapsed() - frame_start_ms)
            self.stress_last_mask = commit.received_mask
            if commit.status == proto.OK:
                self.stress_ok_frames += 1
            else:
                self.stress_commit_error_count += 1
            self.breath_phase += 1.0 / max(1, self.stress_target_fps)
        except Exception as exc:  # noqa: BLE001
            self.stress_timeout_count += 1
            self._finish_stress_point(f"timeout={exc}")
            self.stress_index += 1
            self._start_stress_point()
            return
        finally:
            self.stress_busy = False

        if self.stress_elapsed_timer.elapsed() >= STRESS_POINT_DURATION_MS:
            self._finish_stress_point("done")
            self.stress_index += 1
            self._start_stress_point()

    def _finish_stress_point(self, reason: str) -> None:
        self.stress_timer.stop()
        elapsed_ms = max(1, self.stress_elapsed_timer.elapsed())
        actual_fps = self.stress_ok_frames * 1000.0 / elapsed_ms
        measured_frames = self.stress_ok_frames + self.stress_commit_error_count
        avg_frame_ms = self.stress_frame_time_total_ms / max(1, measured_frames)
        status_text = self._read_status_delta_summary()
        self.log(
            f"STRESS result target={self.stress_target_fps}fps delay={self.stress_delay_ms:.2f}ms "
            f"actual={actual_fps:.1f}fps avg_frame={avg_frame_ms:.1f}ms ok={self.stress_ok_frames} "
            f"timeout={self.stress_timeout_count} commit_err={self.stress_commit_error_count} "
            f"last_mask=0x{self.stress_last_mask:04x} reason={reason} "
            f"{self._stress_timing_avg_text(measured_frames)} {status_text}"
        )

    def _accumulate_stress_timing(self, timing: Optional[FrameTiming]) -> None:
        if timing is None:
            return

        self.stress_frame_time_total_ms += timing.total_ms
        self.stress_begin_total_ms += timing.begin_ms
        self.stress_chunks_total_ms += timing.chunks_ms
        self.stress_pacing_total_ms += timing.pacing_ms
        self.stress_commit_write_total_ms += timing.commit_write_ms
        self.stress_response_wait_total_ms += timing.response_wait_ms

    def _stress_timing_avg_text(self, frame_count: int) -> str:
        count = max(1, frame_count)
        return (
            f"avg_begin={self.stress_begin_total_ms / count:.1f}ms "
            f"avg_chunks={self.stress_chunks_total_ms / count:.1f}ms "
            f"avg_pacing={self.stress_pacing_total_ms / count:.1f}ms "
            f"avg_commit_wr={self.stress_commit_write_total_ms / count:.1f}ms "
            f"avg_wait_rsp={self.stress_response_wait_total_ms / count:.1f}ms"
        )

    def _last_frame_timing_text(self) -> str:
        if self.device is None:
            return "timing=unavailable"

        timing = self.device.last_frame_timing
        if timing is None:
            return "timing=unavailable"

        return (
            f"timing total={timing.total_ms:.1f}ms begin={timing.begin_ms:.1f}ms "
            f"chunks={timing.chunks_ms:.1f}ms pacing={timing.pacing_ms:.1f}ms "
            f"commit_wr={timing.commit_write_ms:.1f}ms wait_rsp={timing.response_wait_ms:.1f}ms"
        )

    def _try_status(self) -> Optional[proto.StatusResponse]:
        if self.device is None:
            return None

        try:
            return self.device.status()
        except Exception as exc:  # noqa: BLE001
            self.log(f"STATUS read failed: {exc}")
            return None

    def _read_status_delta_summary(self) -> str:
        status = self._try_status()
        if status is None:
            return "status=unavailable"

        error_delta = status.error_count - self.stress_start_errors
        commit_delta = status.commit_count - self.stress_start_commits

        return (
            f"rx_used={status.rx_used} error_delta={error_delta} errors={status.error_count} "
            f"commit_delta={commit_delta} commits={status.commit_count} "
            f"flags={proto.status_flags_to_text(status.status_flags)}"
        )

    def _run_device_op(self, name: str, op: Callable[[], None]) -> None:
        if self.device is None:
            QMessageBox.warning(self, "Not connected", "Connect to a device first.")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        self._set_controls_enabled(False)
        try:
            op()
        except Exception as exc:  # noqa: BLE001
            self.log(f"{name} failed: {exc}")
            QMessageBox.critical(self, f"{name} failed", str(exc))
        finally:
            self._set_controls_enabled(True)
            QApplication.restoreOverrideCursor()

    def _maybe_status(self) -> None:
        if self.auto_status_check.isChecked() and self.device is not None:
            status = self.device.status()
            self._show_status(status)

    def _show_status(self, status: proto.StatusResponse) -> None:
        self.log(
            "STATUS "
            f"uid={proto.format_uid(status.uid_hash)} "
            f"flags={proto.status_flags_to_text(status.status_flags)} "
            f"rc=0b{status.rc_stable_bits:04b} "
            f"current={status.current_ma}mA ww={status.ww_current} cw={status.cw_current} "
            f"frame={status.frame_id} commits={status.commit_count} errors={status.error_count}"
        )

    def _set_connected(self, connected: bool) -> None:
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.hello_button.setEnabled(connected)
        self.status_button.setEnabled(connected)
        self.send_solid_button.setEnabled(connected)
        self.start_breath_button.setEnabled(connected)
        self.stop_breath_button.setEnabled(connected and self.breath_timer.isActive())
        self.start_stress_button.setEnabled(connected)
        self.stop_stress_button.setEnabled(connected and self.stress_timer.isActive())

    def _set_controls_enabled(self, enabled: bool) -> None:
        if self.device is None:
            self._set_connected(False)
            return
        busy = self.breath_timer.isActive() or self.stress_timer.isActive()
        self.refresh_button.setEnabled(enabled)
        self.disconnect_button.setEnabled(enabled)
        self.hello_button.setEnabled(enabled and not busy)
        self.status_button.setEnabled(enabled and not busy)
        self.send_solid_button.setEnabled(enabled and not busy)
        self.start_breath_button.setEnabled(enabled and not busy)
        self.stop_breath_button.setEnabled(enabled and self.breath_timer.isActive())
        self.start_stress_button.setEnabled(enabled and not busy)
        self.stop_stress_button.setEnabled(enabled and self.stress_timer.isActive())

    def log(self, message: str) -> None:
        self.log_text.append(message)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.disconnect_device(log_disconnect=False)
        super().closeEvent(event)


def run() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
