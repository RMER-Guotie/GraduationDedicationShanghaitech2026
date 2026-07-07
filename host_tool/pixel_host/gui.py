"""PySide6 GUI for multi-board Pixel Controller bench control."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import time
from typing import Optional

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QDoubleSpinBox,
        QFileDialog,
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
from .device import PixelDevice
from .pixelbin import PixelBinReader
from .serial_link import SerialLink, list_serial_ports

MAX_ACTIVE_BOARDS = 4
TOTAL_CHANNELS = MAX_ACTIVE_BOARDS * proto.LANES
DEFAULT_BAUD = 115200
DEFAULT_RESPONSE_TIMEOUT_S = 1.0
DEFAULT_CHUNK_DELAY_S = 0.0


@dataclass
class BoardSession:
    """Open controller session assigned to one GUI playback slot."""

    slot_id: int
    role_id: int
    port: str
    uid_hash: int
    link: SerialLink
    device: PixelDevice
    state: str = "connected"
    last_error: str = ""
    ok_frames: int = 0
    error_count: int = 0
    skipped_count: int = 0


class PlaybackControl:
    """Thread-safe playback controls shared by the GUI and worker thread."""

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._speed = 1.0
        self._lock = threading.Lock()

    def set_speed(self, value: float) -> None:
        with self._lock:
            self._speed = max(0.1, value)

    def get_speed(self) -> float:
        with self._lock:
            return self._speed


class SlotSender(threading.Thread):
    """Persistent sender for one board so playback can pace all slots independently."""

    def __init__(self, session: BoardSession, log_queue: queue.Queue[str]) -> None:
        super().__init__(daemon=True)
        self.session = session
        self.log_queue = log_queue
        self.stop_event = threading.Event()
        self.items: queue.Queue[tuple[int, bytes, int, int] | None] = queue.Queue(maxsize=1)

    def submit(self, frame_index: int, frame_rgb: bytes, ww: int, cw: int) -> None:
        item = (frame_index, frame_rgb, ww, cw)
        try:
            self.items.put_nowait(item)
        except queue.Full:
            self.session.skipped_count += 1
            try:
                self.items.get_nowait()
            except queue.Empty:
                pass
            try:
                self.items.put_nowait(item)
            except queue.Full:
                self.session.skipped_count += 1

    def stop(self) -> None:
        self.stop_event.set()
        try:
            self.items.put_nowait(None)
        except queue.Full:
            pass

    def run(self) -> None:
        while not self.stop_event.is_set():
            item = self.items.get()
            if item is None:
                break

            frame_index, frame_rgb, ww, cw = item
            try:
                commit = self.session.device.send_frame(
                    frame_rgb,
                    ww=ww,
                    cw=cw,
                    chunk_delay_s=DEFAULT_CHUNK_DELAY_S,
                )
                if commit.status == proto.OK:
                    self.session.ok_frames += 1
                    self.session.state = "connected"
                    self.session.last_error = ""
                else:
                    self._record_error(
                        f"slot {self.session.slot_id} role {self.session.role_id} "
                        f"frame {frame_index} commit status={commit.status} "
                        f"mask=0x{commit.received_mask:04x}"
                    )
            except Exception as exc:  # noqa: BLE001
                self._record_error(f"slot {self.session.slot_id} role {self.session.role_id} frame {frame_index}: {exc}")

    def _record_error(self, message: str) -> None:
        self.session.error_count += 1
        self.session.state = "error"
        self.session.last_error = message
        self.log_queue.put(message)


class PlaybackWorker(threading.Thread):
    """Loop a pixelbin file and distribute board slices to slot senders."""

    def __init__(
        self,
        path: str,
        sessions: dict[int, BoardSession],
        control: PlaybackControl,
        log_queue: queue.Queue[str],
    ) -> None:
        super().__init__(daemon=True)
        self.path = path
        self.sessions = dict(sessions)
        self.control = control
        self.log_queue = log_queue
        self.senders: dict[int, SlotSender] = {}

    def run(self) -> None:
        try:
            with PixelBinReader(self.path) as reader:
                self._start_senders()
                self._log_missing_slots(reader.header.board_count)
                self.log_queue.put(
                    f"PLAY started file={self.path} fps={reader.header.fps} frames={reader.header.frame_count}"
                )
                frame_count = 0
                next_deadline = time.perf_counter()

                while not self.control.stop_event.is_set():
                    if self.control.pause_event.is_set():
                        next_deadline = time.perf_counter()
                        time.sleep(0.05)
                        continue

                    frame = reader.read_frame()
                    if frame is None:
                        reader.seek_frame(0)
                        continue

                    for slot_id, board_frame in enumerate(frame.board_frames, start=1):
                        sender = self.senders.get(slot_id)
                        if sender is not None:
                            sender.submit(frame.index, board_frame, frame.ww, frame.cw)

                    frame_count += 1
                    if frame_count % max(1, reader.header.fps) == 0:
                        self.log_queue.put(f"PLAY submitted={frame_count}")

                    speed = self.control.get_speed()
                    period_s = 1.0 / (reader.header.fps * speed)
                    next_deadline += period_s
                    sleep_s = next_deadline - time.perf_counter()
                    if sleep_s > 0.0:
                        time.sleep(sleep_s)
                    else:
                        next_deadline = time.perf_counter()
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"PLAY failed: {exc}")
        finally:
            self._stop_senders()
            self.log_queue.put("PLAY stopped")

    def _start_senders(self) -> None:
        for slot_id, session in self.sessions.items():
            sender = SlotSender(session, self.log_queue)
            self.senders[slot_id] = sender
            sender.start()

    def _stop_senders(self) -> None:
        for sender in self.senders.values():
            sender.stop()
        for sender in self.senders.values():
            sender.join(timeout=1.0)

    def _log_missing_slots(self, board_count: int) -> None:
        for slot_id in range(1, min(board_count, MAX_ACTIVE_BOARDS) + 1):
            if slot_id not in self.sessions:
                self.log_queue.put(f"slot {slot_id} missing, playback will skip it")


class MainWindow(QMainWindow):
    """Four-board GUI controller for bench testing and file playback."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pixel Controller Host Tool")
        self.resize(980, 680)

        self.sessions: dict[int, BoardSession] = {}
        self.playback_path: Optional[str] = None
        self.playback_control = PlaybackControl()
        self.playback_worker: Optional[PlaybackWorker] = None
        self.log_queue: queue.Queue[str] = queue.Queue()

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._drain_log_queue)
        self.log_timer.start(100)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_slot_status)
        self.status_timer.start(500)

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_slot_status_group())
        layout.addWidget(self._build_control_group())
        layout.addWidget(self._build_log_group(), 1)

        self._set_playback_running(False)
        self.update_slot_status()

    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox("Connection")
        row = QHBoxLayout(group)

        self.baud_spin = QSpinBox()
        self.baud_spin.setRange(1200, 4000000)
        self.baud_spin.setValue(DEFAULT_BAUD)
        self.baud_spin.setSingleStep(115200)

        self.auto_connect_button = QPushButton("Auto Connect")
        self.disconnect_button = QPushButton("Disconnect")
        self.connection_summary_label = QLabel("0/4 connected")
        self.connection_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.auto_connect_button.clicked.connect(lambda: self.auto_connect())
        self.disconnect_button.clicked.connect(lambda: self.disconnect_all())

        row.addWidget(QLabel("Baud"))
        row.addWidget(self.baud_spin)
        row.addWidget(self.auto_connect_button)
        row.addWidget(self.disconnect_button)
        row.addWidget(self.connection_summary_label, 1)
        return group

    def _build_slot_status_group(self) -> QGroupBox:
        group = QGroupBox("Slots")
        layout = QGridLayout(group)
        self.slot_labels: dict[int, QLabel] = {}

        layout.addWidget(QLabel("Slot"), 0, 0)
        layout.addWidget(QLabel("Output columns"), 0, 1)
        layout.addWidget(QLabel("Board"), 0, 2)
        layout.addWidget(QLabel("Port"), 0, 3)
        layout.addWidget(QLabel("UID"), 0, 4)
        layout.addWidget(QLabel("State"), 0, 5)

        for slot_id in range(1, MAX_ACTIVE_BOARDS + 1):
            layout.addWidget(QLabel(str(slot_id)), slot_id, 0)
            first_col = (slot_id - 1) * proto.LANES + 1
            last_col = slot_id * proto.LANES
            layout.addWidget(QLabel(f"{first_col}-{last_col}"), slot_id, 1)
            label = QLabel("missing")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.slot_labels[slot_id] = label
            layout.addWidget(label, slot_id, 2, 1, 4)

        return group

    def _build_control_group(self) -> QGroupBox:
        group = QGroupBox("Control")
        layout = QGridLayout(group)

        self.r_spin = self._byte_spin(255)
        self.g_spin = self._byte_spin(0)
        self.b_spin = self._byte_spin(0)
        self.ww_spin = self._level_spin(0)
        self.cw_spin = self._level_spin(0)
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(1, TOTAL_CHANNELS)
        self.channel_spin.setValue(1)

        form = QFormLayout()
        form.addRow("R", self.r_spin)
        form.addRow("G", self.g_spin)
        form.addRow("B", self.b_spin)
        form.addRow("WW", self.ww_spin)
        form.addRow("CW", self.cw_spin)
        form.addRow("Channel", self.channel_spin)

        self.channel_test_button = QPushButton("Send Channel Test")
        self.import_file_button = QPushButton("Import And Play")
        self.pause_button = QPushButton("Pause")
        self.stop_playback_button = QPushButton("Stop")
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.25, 4.0)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setSingleStep(0.25)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setSuffix("x")
        self.file_label = QLabel("No file")
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.channel_test_button.clicked.connect(lambda: self.send_channel_test())
        self.import_file_button.clicked.connect(lambda: self.import_and_play())
        self.pause_button.clicked.connect(lambda: self.toggle_pause())
        self.stop_playback_button.clicked.connect(lambda: self.stop_playback())
        self.speed_spin.valueChanged.connect(self.playback_control.set_speed)

        playback_row = QHBoxLayout()
        playback_row.addWidget(self.import_file_button)
        playback_row.addWidget(self.pause_button)
        playback_row.addWidget(self.stop_playback_button)
        playback_row.addWidget(QLabel("Speed"))
        playback_row.addWidget(self.speed_spin)
        playback_row.addWidget(self.file_label, 1)

        layout.addLayout(form, 0, 0)
        layout.addWidget(self.channel_test_button, 1, 0)
        layout.addLayout(playback_row, 0, 1, 2, 1)
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
        spin.setSingleStep(10)
        spin.setValue(value)
        return spin

    def auto_connect(self) -> None:
        self.stop_playback()
        self.disconnect_all(log_disconnect=False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.auto_connect_button.setEnabled(False)

        found: list[tuple[int, str, int, SerialLink, PixelDevice]] = []
        try:
            ports = list_serial_ports()
            self.log(f"SCAN ports={ports}")
            for port in ports:
                link = SerialLink(port, baudrate=self.baud_spin.value(), timeout=0.05)
                try:
                    link.open()
                    device = PixelDevice(link=link, response_timeout=DEFAULT_RESPONSE_TIMEOUT_S)
                    hello = device.hello()
                    if 1 <= hello.role_id <= 20:
                        found.append((hello.role_id, port, hello.uid_hash, link, device))
                        self.log(f"[{port}] role={hello.role_id} uid={proto.format_uid(hello.uid_hash)}")
                    else:
                        self.log(f"[{port}] invalid role={hello.role_id}, ignored")
                        link.close()
                except Exception as exc:  # noqa: BLE001
                    self.log(f"[{port}] no response: {exc}")
                    link.close()

            found.sort(key=lambda item: item[0])
            for ignored in found[MAX_ACTIVE_BOARDS:]:
                role_id, port, uid_hash, link, _device = ignored
                self.log(f"[{port}] role={role_id} uid={proto.format_uid(uid_hash)} ignored above 4-board limit")
                link.close()

            for slot_id, item in enumerate(found[:MAX_ACTIVE_BOARDS], start=1):
                role_id, port, uid_hash, link, device = item
                self.sessions[slot_id] = BoardSession(slot_id, role_id, port, uid_hash, link, device)
                self.log(f"slot {slot_id} <= role {role_id} on {port}")

            if len(self.sessions) < MAX_ACTIVE_BOARDS:
                for slot_id in range(len(self.sessions) + 1, MAX_ACTIVE_BOARDS + 1):
                    self.log(f"slot {slot_id} missing")
        finally:
            QApplication.restoreOverrideCursor()
            self.auto_connect_button.setEnabled(True)
            self.update_slot_status()

    def disconnect_all(self, log_disconnect: bool = True) -> None:
        self.stop_playback()
        for session in self.sessions.values():
            session.link.close()
        if log_disconnect and self.sessions:
            self.log("Disconnected all boards")
        self.sessions.clear()
        self.update_slot_status()

    def send_channel_test(self) -> None:
        if self.is_playback_active():
            self.log("Channel test blocked while file playback is active")
            QMessageBox.warning(self, "Playback active", "Pause or stop file playback before channel testing.")
            return

        channel = self.channel_spin.value()
        slot_id = ((channel - 1) // proto.LANES) + 1
        lane = (channel - 1) % proto.LANES
        session = self.sessions.get(slot_id)
        if session is None:
            self.log(f"channel {channel} maps to missing slot {slot_id}")
            return

        target_frame = self._build_channel_frame(lane)
        black_frame = bytes(proto.LANES * proto.LEDS_PER_LANE * 3)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.channel_test_button.setEnabled(False)
        try:
            for current_slot_id, current_session in sorted(self.sessions.items()):
                frame = target_frame if current_slot_id == slot_id else black_frame
                try:
                    commit = current_session.device.send_frame(
                        frame,
                        ww=self.ww_spin.value(),
                        cw=self.cw_spin.value(),
                        chunk_delay_s=DEFAULT_CHUNK_DELAY_S,
                    )
                    if commit.status == proto.OK:
                        current_session.ok_frames += 1
                        current_session.state = "connected"
                        current_session.last_error = ""
                    else:
                        current_session.error_count += 1
                        current_session.state = "error"
                        current_session.last_error = f"commit status={commit.status}"
                    self.log(
                        f"CHANNEL channel={channel} slot={current_slot_id} role={current_session.role_id} "
                        f"target_lane={lane + 1 if current_slot_id == slot_id else 0} "
                        f"commit_status={commit.status} mask=0x{commit.received_mask:04x}"
                    )
                except Exception as exc:  # noqa: BLE001
                    current_session.error_count += 1
                    current_session.state = "error"
                    current_session.last_error = str(exc)
                    self.log(f"CHANNEL channel={channel} slot={current_slot_id} failed: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
            self.channel_test_button.setEnabled(True)
            self.update_slot_status()

    def _build_channel_frame(self, lane: int) -> bytes:
        frame = bytearray(proto.LANES * proto.LEDS_PER_LANE * 3)
        pixel = bytes((self.r_spin.value(), self.g_spin.value(), self.b_spin.value()))
        lane_offset = lane * proto.LEDS_PER_LANE * 3
        for index in range(proto.LEDS_PER_LANE):
            offset = lane_offset + index * 3
            frame[offset : offset + 3] = pixel
        return bytes(frame)

    def import_and_play(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Open pixelbin file",
            "",
            "PixelBin Files (*.pixelbin *.bin);;All Files (*)",
        )
        if not path:
            return

        try:
            with PixelBinReader(path) as reader:
                if reader.header.board_count != MAX_ACTIVE_BOARDS:
                    raise ValueError(f"expected {MAX_ACTIVE_BOARDS} boards, got {reader.header.board_count}")
                if reader.header.lanes != proto.LANES or reader.header.leds_per_lane != proto.LEDS_PER_LANE:
                    raise ValueError("pixelbin geometry does not match current protocol")
                self.file_label.setText(path)
                self.playback_path = path
        except Exception as exc:  # noqa: BLE001
            self.log(f"Import failed: {exc}")
            QMessageBox.critical(self, "Import failed", str(exc))
            return

        self.start_playback()

    def start_playback(self) -> None:
        if self.playback_path is None:
            return
        if not self.sessions:
            self.log("No connected boards; playback not started")
            QMessageBox.warning(self, "No boards", "Auto connect at least one board before playback.")
            return

        self.stop_playback()
        self.playback_control.stop_event.clear()
        self.playback_control.pause_event.clear()
        self.playback_control.set_speed(self.speed_spin.value())
        self.playback_worker = PlaybackWorker(self.playback_path, self.sessions, self.playback_control, self.log_queue)
        self.playback_worker.start()
        self._set_playback_running(True)

    def toggle_pause(self) -> None:
        if self.playback_worker is None or not self.playback_worker.is_alive():
            return
        if self.playback_control.pause_event.is_set():
            self.playback_control.pause_event.clear()
            self.pause_button.setText("Pause")
            self.log("PLAY resumed")
        else:
            self.playback_control.pause_event.set()
            self.pause_button.setText("Resume")
            self.log("PLAY paused")

    def stop_playback(self) -> None:
        if self.playback_worker is not None:
            self.playback_control.stop_event.set()
            self.playback_worker.join(timeout=1.0)
        self.playback_worker = None
        self._set_playback_running(False)

    def is_playback_active(self) -> bool:
        return self.playback_worker is not None and self.playback_worker.is_alive()

    def _set_playback_running(self, running: bool) -> None:
        self.channel_test_button.setEnabled(not running)
        self.pause_button.setEnabled(running)
        self.stop_playback_button.setEnabled(running)
        self.pause_button.setText("Pause")

    def update_slot_status(self) -> None:
        connected_count = len(self.sessions)
        self.connection_summary_label.setText(f"{connected_count}/{MAX_ACTIVE_BOARDS} connected")

        for slot_id in range(1, MAX_ACTIVE_BOARDS + 1):
            label = self.slot_labels.get(slot_id)
            if label is None:
                continue
            session = self.sessions.get(slot_id)
            if session is None:
                label.setText("missing")
                label.setStyleSheet("color: #a04040;")
                continue

            error_text = f" last={session.last_error}" if session.last_error else ""
            label.setText(
                f"role={session.role_id} port={session.port} uid={proto.format_uid(session.uid_hash)} "
                f"state={session.state} ok={session.ok_frames} err={session.error_count} "
                f"skip={session.skipped_count}{error_text}"
            )
            label.setStyleSheet("color: #206020;" if session.state == "connected" else "color: #a06000;")

        if self.playback_worker is not None and not self.playback_worker.is_alive():
            self.playback_worker = None
            self._set_playback_running(False)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                self.log(self.log_queue.get_nowait())
            except queue.Empty:
                break

    def log(self, message: str) -> None:
        self.log_text.append(message)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.disconnect_all(log_disconnect=False)
        super().closeEvent(event)


def run() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
