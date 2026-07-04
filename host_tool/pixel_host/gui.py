"""PySide6 debug GUI for one Pixel Controller board."""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable, Optional

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
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

from . import patterns
from . import protocol as proto
from .device import PixelDevice
from .serial_link import SerialLink, list_serial_ports


class MainWindow(QMainWindow):
    """Small synchronous debug panel for firmware bring-up."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pixel Controller Host Tool")
        self.resize(920, 620)

        self.device: Optional[PixelDevice] = None
        self.link: Optional[SerialLink] = None

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

        form = QFormLayout()
        form.addRow("R", self.r_spin)
        form.addRow("G", self.g_spin)
        form.addRow("B", self.b_spin)
        form.addRow("WW", self.ww_spin)
        form.addRow("CW", self.cw_spin)

        self.send_solid_button = QPushButton("Send Solid")
        self.lane_test_button = QPushButton("Lane Test")
        self.all_black_button = QPushButton("All Black")

        self.send_solid_button.clicked.connect(self.send_solid)
        self.lane_test_button.clicked.connect(self.send_lane_test)
        self.all_black_button.clicked.connect(self.all_black)

        button_row = QHBoxLayout()
        button_row.addWidget(self.send_solid_button)
        button_row.addWidget(self.lane_test_button)
        button_row.addWidget(self.all_black_button)
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

    def all_black(self) -> None:
        def op() -> None:
            assert self.device is not None
            status = self.device.all_black()
            self._show_status(status)
            self.log("ALL_BLACK sent")

        self._run_device_op("ALL_BLACK", op)

    def send_solid(self) -> None:
        def op() -> None:
            assert self.device is not None
            commit = self.device.send_solid(
                self.r_spin.value(),
                self.g_spin.value(),
                self.b_spin.value(),
                ww=self.ww_spin.value(),
                cw=self.cw_spin.value(),
            )
            self.log(f"SOLID commit={asdict(commit)}")
            self._maybe_status()

        self._run_device_op("Send solid", op)

    def send_lane_test(self) -> None:
        def op() -> None:
            assert self.device is not None
            commit = self.device.send_frame(
                patterns.lane_test(),
                ww=self.ww_spin.value(),
                cw=self.cw_spin.value(),
            )
            self.log(f"LANE_TEST commit={asdict(commit)}")
            self._maybe_status()

        self._run_device_op("Lane test", op)

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
        self.lane_test_button.setEnabled(connected)
        self.all_black_button.setEnabled(connected)

    def _set_controls_enabled(self, enabled: bool) -> None:
        if self.device is None:
            self._set_connected(False)
            return
        self.refresh_button.setEnabled(enabled)
        self.disconnect_button.setEnabled(enabled)
        self.hello_button.setEnabled(enabled)
        self.status_button.setEnabled(enabled)
        self.send_solid_button.setEnabled(enabled)
        self.lane_test_button.setEnabled(enabled)
        self.all_black_button.setEnabled(enabled)

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
