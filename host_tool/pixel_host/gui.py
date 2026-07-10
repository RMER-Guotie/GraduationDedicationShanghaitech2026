"""PySide6 GUI for multi-board Pixel Controller bench control."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
DEFAULT_CHUNK_DELAY_MS = 0.25
FRAME_RGB_BYTES = proto.LANES * proto.LEDS_PER_LANE * 3
RC_POLL_INTERVAL_MS = 100
AUTOPLAY_DIR = Path(__file__).resolve().parents[1] / "autoplay"

ACTION_MODE1 = "mode1"
ACTION_MODE2 = "mode2"
ACTION_BLACK = "black"
ACTION_PAUSE = "pause"
RC_ACTION_ORDER = (ACTION_MODE1, ACTION_MODE2, ACTION_BLACK, ACTION_PAUSE)
RC_ACTION_LABELS = {
    ACTION_MODE1: "Mode 1",
    ACTION_MODE2: "Mode 2",
    ACTION_BLACK: "Black",
    ACTION_PAUSE: "Pause",
}
RC_ACTION_FILES = {
    ACTION_MODE1: "mode1.pixelbin",
    ACTION_MODE2: "mode2.pixelbin",
    ACTION_BLACK: "black.pixelbin",
}


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
    io_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def action_from_rc_bits(bits: int) -> str | None:
    """Map latched RC press bits to one GUI action."""
    for bit_index, action in enumerate(RC_ACTION_ORDER):
        if bits & (1 << bit_index):
            return action
    return None


class PlaybackControl:
    """Thread-safe playback controls shared by the GUI and worker thread."""

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._speed = 1.0
        self._chunk_delay_s = DEFAULT_CHUNK_DELAY_MS / 1000.0
        self._lock = threading.Lock()

    def set_speed(self, value: float) -> None:
        with self._lock:
            self._speed = max(0.1, value)

    def get_speed(self) -> float:
        with self._lock:
            return self._speed

    def set_chunk_delay_ms(self, value: float) -> None:
        with self._lock:
            self._chunk_delay_s = max(0.0, value) / 1000.0

    def get_chunk_delay_s(self) -> float:
        with self._lock:
            return self._chunk_delay_s


class SlotSender(threading.Thread):
    """Persistent sender for one board so playback can pace all slots independently."""

    def __init__(self, session: BoardSession, control: PlaybackControl, log_queue: queue.Queue[str]) -> None:
        super().__init__(daemon=True)
        self.session = session
        self.control = control
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
                with self.session.io_lock:
                    commit = self.session.device.send_frame(
                        frame_rgb,
                        ww=ww,
                        cw=cw,
                        chunk_delay_s=self.control.get_chunk_delay_s(),
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
                    f"PLAY started file={self.path} fps={reader.header.fps} frames={reader.header.frame_count} "
                    f"chunk_delay={self.control.get_chunk_delay_s() * 1000.0:.2f}ms"
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
            sender = SlotSender(session, self.control, self.log_queue)
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


class RcPollWorker(threading.Thread):
    """Poll STATUS in the background and forward latched RC press events."""

    def __init__(
        self,
        sessions: list[BoardSession],
        event_queue: queue.Queue[tuple[int, int, int]],
    ) -> None:
        super().__init__(daemon=True)
        self.sessions = sessions
        self.event_queue = event_queue

    def run(self) -> None:
        for session in self.sessions:
            if not session.io_lock.acquire(timeout=0.002):
                continue
            try:
                status = session.device.status()
                session.state = "connected"
                session.last_error = ""
                if status.rc_event_bits:
                    self.event_queue.put((session.slot_id, session.role_id, status.rc_event_bits))
            except Exception as exc:  # noqa: BLE001
                session.state = "error"
                session.error_count += 1
                session.last_error = f"status: {exc}"
            finally:
                session.io_lock.release()


class AutoConnectWorker(threading.Thread):
    """Scan serial ports and open valid boards without blocking the Qt event loop."""

    def __init__(
        self,
        baudrate: int,
        log_queue: queue.Queue[str],
        result_queue: queue.Queue[dict[int, BoardSession]],
    ) -> None:
        super().__init__(daemon=True)
        self.baudrate = baudrate
        self.log_queue = log_queue
        self.result_queue = result_queue

    def run(self) -> None:
        found: list[tuple[int, str, int, SerialLink, PixelDevice]] = []
        try:
            ports = list_serial_ports()
            self.log_queue.put(f"SCAN ports={ports}")
            for port in ports:
                link = SerialLink(port, baudrate=self.baudrate, timeout=0.05)
                try:
                    self.log_queue.put(f"[{port}] checking")
                    link.open()
                    device = PixelDevice(link=link, response_timeout=DEFAULT_RESPONSE_TIMEOUT_S)
                    hello = device.hello()
                    if 1 <= hello.role_id <= 20:
                        found.append((hello.role_id, port, hello.uid_hash, link, device))
                        self.log_queue.put(f"[{port}] role={hello.role_id} uid={proto.format_uid(hello.uid_hash)}")
                    else:
                        self.log_queue.put(f"[{port}] skipped invalid role={hello.role_id}")
                        link.close()
                except Exception as exc:  # noqa: BLE001
                    self.log_queue.put(f"[{port}] skipped: no pixel response ({exc})")
                    link.close()

            found.sort(key=lambda item: item[0])
            for ignored in found[MAX_ACTIVE_BOARDS:]:
                role_id, port, uid_hash, link, _device = ignored
                self.log_queue.put(f"[{port}] role={role_id} uid={proto.format_uid(uid_hash)} ignored above 4-board limit")
                link.close()

            sessions: dict[int, BoardSession] = {}
            for slot_id, item in enumerate(found[:MAX_ACTIVE_BOARDS], start=1):
                role_id, port, uid_hash, link, device = item
                sessions[slot_id] = BoardSession(slot_id, role_id, port, uid_hash, link, device)
                self.log_queue.put(f"slot {slot_id} <= role {role_id} on {port}")

            if len(sessions) < MAX_ACTIVE_BOARDS:
                for slot_id in range(len(sessions) + 1, MAX_ACTIVE_BOARDS + 1):
                    self.log_queue.put(f"slot {slot_id} missing")

            self.result_queue.put(sessions)
        except Exception as exc:  # noqa: BLE001
            for _role_id, _port, _uid_hash, link, _device in found:
                link.close()
            self.log_queue.put(f"SCAN failed: {exc}")
            self.result_queue.put({})


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
        self.auto_connect_worker: Optional[AutoConnectWorker] = None
        self.rc_poll_worker: Optional[RcPollWorker] = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.connect_result_queue: queue.Queue[dict[int, BoardSession]] = queue.Queue()
        self.rc_event_queue: queue.Queue[tuple[int, int, int]] = queue.Queue()
        self.slot_frames = {slot_id: bytearray(FRAME_RGB_BYTES) for slot_id in range(1, MAX_ACTIVE_BOARDS + 1)}
        self.repeat_send_active = False
        self.repeat_send_busy = False
        self.repeat_send_count = 0
        self.repeat_send_skip_count = 0
        self.active_rc_action: Optional[str] = None

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._drain_log_queue)
        self.log_timer.start(100)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_slot_status)
        self.status_timer.start(500)

        self.repeat_send_timer = QTimer(self)
        self.repeat_send_timer.timeout.connect(self._repeat_channel_test_tick)

        self.rc_timer = QTimer(self)
        self.rc_timer.timeout.connect(self._poll_rc_events)
        self.rc_timer.start(RC_POLL_INTERVAL_MS)

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
        self.repeat_hz_spin = QDoubleSpinBox()
        self.repeat_hz_spin.setRange(1.0, 120.0)
        self.repeat_hz_spin.setDecimals(1)
        self.repeat_hz_spin.setSingleStep(1.0)
        self.repeat_hz_spin.setValue(30.0)
        self.repeat_hz_spin.setSuffix(" Hz")

        form = QFormLayout()
        form.addRow("R", self.r_spin)
        form.addRow("G", self.g_spin)
        form.addRow("B", self.b_spin)
        form.addRow("WW", self.ww_spin)
        form.addRow("CW", self.cw_spin)
        form.addRow("Channel", self.channel_spin)
        form.addRow("Repeat", self.repeat_hz_spin)

        self.channel_test_button = QPushButton("Send Channel Test")
        self.repeat_test_button = QPushButton("Start Repeat")
        self.import_file_button = QPushButton("Import And Play")
        self.pause_button = QPushButton("Pause")
        self.stop_playback_button = QPushButton("Stop")
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.25, 4.0)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setSingleStep(0.25)
        self.speed_spin.setValue(1.0)
        self.speed_spin.setSuffix("x")
        self.chunk_delay_spin = QDoubleSpinBox()
        self.chunk_delay_spin.setRange(0.0, 5.0)
        self.chunk_delay_spin.setDecimals(2)
        self.chunk_delay_spin.setSingleStep(0.05)
        self.chunk_delay_spin.setValue(DEFAULT_CHUNK_DELAY_MS)
        self.chunk_delay_spin.setSuffix(" ms")
        self.file_label = QLabel("No file")
        self.file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.rc_action_buttons: dict[str, QPushButton] = {}

        self.channel_test_button.clicked.connect(lambda: self.send_channel_test())
        self.repeat_test_button.clicked.connect(lambda: self.toggle_repeat_channel_test())
        self.import_file_button.clicked.connect(lambda: self.import_and_play())
        self.pause_button.clicked.connect(lambda: self.toggle_pause())
        self.stop_playback_button.clicked.connect(lambda: self.stop_playback())
        self.speed_spin.valueChanged.connect(self.playback_control.set_speed)
        self.chunk_delay_spin.valueChanged.connect(self.playback_control.set_chunk_delay_ms)

        playback_row = QHBoxLayout()
        playback_row.addWidget(self.import_file_button)
        playback_row.addWidget(self.pause_button)
        playback_row.addWidget(self.stop_playback_button)
        playback_row.addWidget(QLabel("Speed"))
        playback_row.addWidget(self.speed_spin)
        playback_row.addWidget(QLabel("Chunk delay"))
        playback_row.addWidget(self.chunk_delay_spin)
        playback_row.addWidget(self.file_label, 1)

        rc_row = QHBoxLayout()
        rc_row.addWidget(QLabel("RC / Mode"))
        for action in RC_ACTION_ORDER:
            button = QPushButton(RC_ACTION_LABELS[action])
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, current=action: self.trigger_rc_action(current, "GUI"))
            self.rc_action_buttons[action] = button
            rc_row.addWidget(button)
        rc_row.addStretch(1)

        layout.addLayout(form, 0, 0)
        layout.addWidget(self.channel_test_button, 1, 0)
        layout.addWidget(self.repeat_test_button, 2, 0)
        layout.addLayout(playback_row, 0, 1, 2, 1)
        layout.addLayout(rc_row, 2, 1)
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
        if self.auto_connect_worker is not None and self.auto_connect_worker.is_alive():
            self.log("Auto connect is already running")
            return

        self.stop_playback()
        self.disconnect_all(log_disconnect=False)
        self._reset_channel_frames()
        self.auto_connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.connection_summary_label.setText("Connecting...")
        self.log("Connecting...")
        self.auto_connect_worker = AutoConnectWorker(self.baud_spin.value(), self.log_queue, self.connect_result_queue)
        self.auto_connect_worker.start()

    def disconnect_all(self, log_disconnect: bool = True) -> None:
        self.stop_playback()
        self.stop_repeat_channel_test()
        for session in self.sessions.values():
            session.link.close()
        if log_disconnect and self.sessions:
            self.log("Disconnected all boards")
        self.sessions.clear()
        self.set_active_rc_action(None)
        self.clear_pending_rc_events()
        self.update_slot_status()

    def send_channel_test(self) -> None:
        if self.is_playback_active():
            self.log("Channel test blocked while file playback is active")
            QMessageBox.warning(self, "Playback active", "Pause or stop file playback before channel testing.")
            return

        if self.repeat_send_busy:
            self.log("Channel test skipped because a send is still active")
            return

        self.repeat_send_busy = True
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.channel_test_button.setEnabled(False)
        self.repeat_test_button.setEnabled(False)
        try:
            self._send_channel_test_once(log_each_slot=True)
        finally:
            self.repeat_send_busy = False
            QApplication.restoreOverrideCursor()
            self.channel_test_button.setEnabled(not self.repeat_send_active)
            self.repeat_test_button.setEnabled(True)
            self.update_slot_status()

    def toggle_repeat_channel_test(self) -> None:
        if self.repeat_send_active:
            self.stop_repeat_channel_test()
            return

        if self.is_playback_active():
            self.log("Repeat channel test blocked while file playback is active")
            QMessageBox.warning(self, "Playback active", "Stop file playback before repeat channel testing.")
            return

        if not self.sessions:
            self.log("No connected boards; repeat test not started")
            return

        self.repeat_send_active = True
        self.repeat_send_count = 0
        self.repeat_send_skip_count = 0
        self.repeat_test_button.setText("Stop Repeat")
        self.channel_test_button.setEnabled(False)
        self.import_file_button.setEnabled(False)
        interval_ms = max(1, int(round(1000.0 / self.repeat_hz_spin.value())))
        self.repeat_send_timer.start(interval_ms)
        self.log(f"REPEAT started hz={self.repeat_hz_spin.value():.1f} interval={interval_ms}ms")

    def stop_repeat_channel_test(self) -> None:
        if not self.repeat_send_active:
            return

        self.repeat_send_timer.stop()
        self.repeat_send_active = False
        self.repeat_send_busy = False
        self.repeat_test_button.setText("Start Repeat")
        self.channel_test_button.setEnabled(not self.is_playback_active())
        self.import_file_button.setEnabled(not self.is_playback_active())
        self.log(f"REPEAT stopped sent={self.repeat_send_count} skipped={self.repeat_send_skip_count}")

    def _repeat_channel_test_tick(self) -> None:
        if self.repeat_send_busy:
            self.repeat_send_skip_count += 1
            return

        self.repeat_send_busy = True
        try:
            ok = self._send_channel_test_once(log_each_slot=False)
            if ok:
                self.repeat_send_count += 1
                if self.repeat_send_count % max(1, int(self.repeat_hz_spin.value())) == 0:
                    self.log(f"REPEAT sent={self.repeat_send_count} skipped={self.repeat_send_skip_count}")
        finally:
            self.repeat_send_busy = False
            self.update_slot_status()

    def _send_channel_test_once(self, log_each_slot: bool) -> bool:
        channel = self.channel_spin.value()
        slot_id = ((channel - 1) // proto.LANES) + 1
        lane = (channel - 1) % proto.LANES
        session = self.sessions.get(slot_id)
        if session is None:
            self.log(f"channel {channel} maps to missing slot {slot_id}")
            return False

        self._set_lane_color(slot_id, lane)
        ok = True
        for current_slot_id, current_session in sorted(self.sessions.items()):
            frame = bytes(self.slot_frames[current_slot_id])
            try:
                with current_session.io_lock:
                    commit = current_session.device.send_frame(
                        frame,
                        ww=self.ww_spin.value(),
                        cw=self.cw_spin.value(),
                        chunk_delay_s=self.chunk_delay_spin.value() / 1000.0,
                    )
                if commit.status == proto.OK:
                    current_session.ok_frames += 1
                    current_session.state = "connected"
                    current_session.last_error = ""
                else:
                    ok = False
                    current_session.error_count += 1
                    current_session.state = "error"
                    current_session.last_error = f"commit status={commit.status}"
                if log_each_slot:
                    self.log(
                        f"CHANNEL channel={channel} slot={current_slot_id} role={current_session.role_id} "
                        f"changed_lane={lane + 1 if current_slot_id == slot_id else 0} "
                        f"commit_status={commit.status} mask=0x{commit.received_mask:04x}"
                    )
            except Exception as exc:  # noqa: BLE001
                ok = False
                current_session.error_count += 1
                current_session.state = "error"
                current_session.last_error = str(exc)
                self.log(f"CHANNEL channel={channel} slot={current_slot_id} failed: {exc}")
        return ok

    def _set_lane_color(self, slot_id: int, lane: int) -> None:
        frame = self.slot_frames[slot_id]
        pixel = bytes((self.r_spin.value(), self.g_spin.value(), self.b_spin.value()))
        lane_offset = lane * proto.LEDS_PER_LANE * 3
        for index in range(proto.LEDS_PER_LANE):
            offset = lane_offset + index * 3
            frame[offset : offset + 3] = pixel

    def _reset_channel_frames(self) -> None:
        for slot_id in range(1, MAX_ACTIVE_BOARDS + 1):
            self.slot_frames[slot_id] = bytearray(FRAME_RGB_BYTES)

    def import_and_play(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Open pixelbin file",
            "",
            "PixelBin Files (*.pixelbin *.bin);;All Files (*)",
        )
        if not path:
            return

        if not self.load_playback_file(path, show_error=True):
            return

        self.set_active_rc_action(None)
        self.start_playback()

    def load_playback_file(self, path: str, show_error: bool) -> bool:
        try:
            with PixelBinReader(path) as reader:
                if reader.header.board_count != MAX_ACTIVE_BOARDS:
                    raise ValueError(f"expected {MAX_ACTIVE_BOARDS} boards, got {reader.header.board_count}")
                if reader.header.lanes != proto.LANES or reader.header.leds_per_lane != proto.LEDS_PER_LANE:
                    raise ValueError("pixelbin geometry does not match current protocol")
                self.file_label.setText(path)
                self.playback_path = path
                return True
        except Exception as exc:  # noqa: BLE001
            self.log(f"File load failed: {exc}")
            if show_error:
                QMessageBox.critical(self, "File load failed", str(exc))
            return False

    def start_playback(self) -> bool:
        if self.playback_path is None:
            return False
        if self.repeat_send_active:
            self.log("Playback blocked while repeat channel test is active")
            QMessageBox.warning(self, "Repeat active", "Stop repeat channel testing before file playback.")
            return False
        if not self.sessions:
            self.log("No connected boards; playback not started")
            QMessageBox.warning(self, "No boards", "Auto connect at least one board before playback.")
            return False

        self.stop_playback()
        self.playback_control.stop_event.clear()
        self.playback_control.pause_event.clear()
        self.playback_control.set_speed(self.speed_spin.value())
        self.playback_control.set_chunk_delay_ms(self.chunk_delay_spin.value())
        self.playback_worker = PlaybackWorker(self.playback_path, self.sessions, self.playback_control, self.log_queue)
        self.playback_worker.start()
        self._set_playback_running(True)
        return True

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

    def trigger_rc_action(self, action: str, source: str) -> None:
        if action not in RC_ACTION_ORDER:
            return

        if action == self.active_rc_action:
            self.update_rc_action_buttons()
            self.log(f"{source} {RC_ACTION_LABELS[action]} ignored; already active")
            return

        if action == ACTION_PAUSE:
            self.stop_repeat_channel_test()
            if self.is_playback_active():
                self.playback_control.pause_event.set()
                self.pause_button.setText("Resume")
            self.set_active_rc_action(action)
            self.log(f"{source} selected {RC_ACTION_LABELS[action]}; RGB submission paused")
            return

        path = self.rc_action_path(action)
        if path is None:
            return
        if not path.exists():
            self.log(f"{source} {RC_ACTION_LABELS[action]} missing file: {path}")
            if source == "GUI":
                QMessageBox.warning(self, "Missing file", f"Missing demo file:\n{path}")
            self.update_rc_action_buttons()
            return

        if not self.load_playback_file(str(path), show_error=(source == "GUI")):
            self.update_rc_action_buttons()
            return

        if self.start_playback():
            self.set_active_rc_action(action)
            self.log(f"{source} selected {RC_ACTION_LABELS[action]}: {path}")
        else:
            self.update_rc_action_buttons()

    def rc_action_path(self, action: str) -> Path | None:
        filename = RC_ACTION_FILES.get(action)
        if filename is None:
            return None
        return AUTOPLAY_DIR / filename

    def set_active_rc_action(self, action: Optional[str]) -> None:
        self.active_rc_action = action
        self.update_rc_action_buttons()

    def update_rc_action_buttons(self) -> None:
        for action, button in self.rc_action_buttons.items():
            active = action == self.active_rc_action
            button.setChecked(active)
            if active:
                button.setStyleSheet("font-weight: 600; background-color: #d8f0ff;")
            else:
                button.setStyleSheet("")

    def stop_playback(self) -> None:
        if self.playback_worker is not None:
            self.playback_control.stop_event.set()
            self.playback_worker.join(timeout=1.0)
        self.playback_worker = None
        self._set_playback_running(False)

    def is_playback_active(self) -> bool:
        return self.playback_worker is not None and self.playback_worker.is_alive()

    def _set_playback_running(self, running: bool) -> None:
        if running:
            self.stop_repeat_channel_test()
        self.channel_test_button.setEnabled((not running) and (not self.repeat_send_active))
        self.repeat_test_button.setEnabled(not running)
        self.import_file_button.setEnabled((not running) and (not self.repeat_send_active))
        self.pause_button.setEnabled(running)
        self.stop_playback_button.setEnabled(running)
        self.pause_button.setText("Pause")

    def _poll_rc_events(self) -> None:
        self._drain_rc_events()
        if self.rc_poll_worker is not None and self.rc_poll_worker.is_alive():
            return
        if not self.sessions:
            return
        if self.auto_connect_worker is not None and self.auto_connect_worker.is_alive():
            return

        self.rc_poll_worker = RcPollWorker(list(self.sessions.values()), self.rc_event_queue)
        self.rc_poll_worker.start()

    def _drain_rc_events(self) -> None:
        while True:
            try:
                slot_id, role_id, bits = self.rc_event_queue.get_nowait()
            except queue.Empty:
                break

            action = action_from_rc_bits(bits)
            if action is None:
                self.log(f"RC slot={slot_id} role={role_id} bits=0b{bits:04b} ignored")
                continue

            self.log(
                f"RC slot={slot_id} role={role_id} bits=0b{bits:04b} "
                f"-> {RC_ACTION_LABELS[action]}"
            )
            self.trigger_rc_action(action, "RC")

    def clear_pending_rc_events(self) -> None:
        while True:
            try:
                self.rc_event_queue.get_nowait()
            except queue.Empty:
                break

    def update_slot_status(self) -> None:
        self._drain_connect_results()
        connected_count = len(self.sessions)
        if self.auto_connect_worker is None or not self.auto_connect_worker.is_alive():
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
        self._drain_connect_results()
        self._drain_rc_events()

    def _drain_connect_results(self) -> None:
        updated = False
        while True:
            try:
                sessions = self.connect_result_queue.get_nowait()
            except queue.Empty:
                break
            self.sessions = sessions
            self.auto_connect_worker = None
            self.auto_connect_button.setEnabled(True)
            self.disconnect_button.setEnabled(True)
            updated = True
        if updated:
            self.update_slot_status()

    def log(self, message: str) -> None:
        self.log_text.append(message)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.stop_repeat_channel_test()
        self.disconnect_all(log_disconnect=False)
        super().closeEvent(event)


def run() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
