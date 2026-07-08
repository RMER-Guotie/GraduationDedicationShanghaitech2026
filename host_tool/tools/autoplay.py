"""Autostart playback controller with USB scan and RC mode switching."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
import queue
import threading
import time

from pixel_host import protocol as proto
from pixel_host.device import PixelDevice
from pixel_host.pixelbin import PixelBinReader, PixelFrame
from pixel_host.serial_link import SerialLink, list_serial_ports


DEFAULT_BOARD_COUNT = 4
DEFAULT_MODE_COUNT = 4
DEFAULT_MODE_DIR = Path(__file__).resolve().parents[1] / "autoplay"


@dataclass
class SenderStats:
    """Counters for one board sender thread."""

    sent: int = 0
    ok: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass
class AutoBoard:
    """One opened controller with a lock shared by frame sends and STATUS polling."""

    port: str
    role_id: int
    uid_hash: int
    device: PixelDevice
    slot_id: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    sender: "BoardSender | None" = None


class BoardSender(threading.Thread):
    """Latest-frame-only sender for one connected board."""

    def __init__(self, board: AutoBoard, chunk_delay_s: float) -> None:
        super().__init__(daemon=True)
        self.board = board
        self.chunk_delay_s = chunk_delay_s
        self.queue: queue.Queue[tuple[int, bytes, int, int] | None] = queue.Queue(maxsize=1)
        self.stats = SenderStats()
        self._stop_requested = threading.Event()

    def submit(self, frame_index: int, frame_rgb: bytes, ww: int, cw: int) -> None:
        item = (frame_index, frame_rgb, ww, cw)
        try:
            self.queue.put_nowait(item)
            return
        except queue.Full:
            self.stats.skipped += 1

        try:
            self.queue.get_nowait()
        except queue.Empty:
            pass

        try:
            self.queue.put_nowait(item)
        except queue.Full:
            self.stats.skipped += 1

    def stop(self) -> None:
        self._stop_requested.set()
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass

    def run(self) -> None:
        while not self._stop_requested.is_set():
            item = self.queue.get()
            if item is None:
                break

            frame_index, frame_rgb, ww, cw = item
            self.stats.sent += 1
            try:
                with self.board.lock:
                    commit = self.board.device.send_frame(
                        frame_rgb,
                        ww=ww,
                        cw=cw,
                        chunk_delay_s=self.chunk_delay_s,
                    )
                if commit.status == proto.OK:
                    self.stats.ok += 1
                else:
                    self.stats.errors += 1
                    log(
                        f"slot {self.board.slot_id} role {self.board.role_id} "
                        f"frame {frame_index} commit status={commit.status} "
                        f"mask=0x{commit.received_mask:04x}"
                    )
            except Exception as exc:
                self.stats.errors += 1
                log(f"slot {self.board.slot_id} role {self.board.role_id} frame {frame_index} skipped: {exc}")


def log(message: str) -> None:
    """Print a timestamped log line for the startup console."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def mode_from_rc_bits(rc_bits: int) -> int | None:
    """Map RC bit0..bit3 to mode1..mode4, choosing the lowest active bit."""
    for bit in range(DEFAULT_MODE_COUNT):
        if rc_bits & (1 << bit):
            return bit + 1
    return None


def scan_new_boards(boards_by_port: dict[str, AutoBoard], args: argparse.Namespace) -> None:
    """Open new USB CDC COM ports that answer HELLO."""
    try:
        ports = list_serial_ports()
    except Exception as exc:
        log(f"serial scan failed: {exc}")
        return

    existing_roles = {board.role_id for board in boards_by_port.values()}
    for port in ports:
        if port in boards_by_port:
            continue

        link = SerialLink(port, baudrate=args.baud, timeout=args.serial_timeout)
        try:
            link.open()
            device = PixelDevice(link=link, response_timeout=args.response_timeout)
            hello = device.hello()
            if not 1 <= hello.role_id <= 20:
                raise ValueError(f"invalid role_id={hello.role_id}")
            if hello.role_id in existing_roles:
                raise ValueError(f"duplicate role_id={hello.role_id}")

            board = AutoBoard(port=port, role_id=hello.role_id, uid_hash=hello.uid_hash, device=device)
            boards_by_port[port] = board
            existing_roles.add(hello.role_id)
            log(f"{port} HELLO role={hello.role_id} uid={proto.format_uid(hello.uid_hash)} connected")
        except Exception as exc:
            log(f"{port} no response: {exc}")
            link.close()


def selected_boards(boards_by_port: dict[str, AutoBoard], max_boards: int) -> list[AutoBoard]:
    """Return smallest-role boards and assign playback slots compactly."""
    boards = sorted(boards_by_port.values(), key=lambda board: board.role_id)
    selected = boards[:max_boards]
    for slot_id, board in enumerate(selected, start=1):
        board.slot_id = slot_id
    for board in boards[max_boards:]:
        board.slot_id = None
    return selected


def poll_rc(boards: list[AutoBoard], timeout_log: bool = False) -> tuple[AutoBoard, int, int] | None:
    """Return the first board reporting RC bits as board, bits, selected mode."""
    for board in sorted(boards, key=lambda item: item.role_id):
        try:
            with board.lock:
                status = board.device.status()
        except Exception as exc:
            if timeout_log:
                log(f"{board.port} role={board.role_id} STATUS failed: {exc}")
            continue

        mode = mode_from_rc_bits(status.rc_stable_bits)
        if mode is not None:
            return board, status.rc_stable_bits, mode
    return None


def wait_for_start(args: argparse.Namespace) -> tuple[list[AutoBoard], int, bool]:
    """Wait until all boards connect or RC forces a mode."""
    boards_by_port: dict[str, AutoBoard] = {}
    last_summary = 0.0
    log("waiting for USB controllers; RC input can force playback before all boards connect")

    while True:
        scan_new_boards(boards_by_port, args)
        selected = selected_boards(boards_by_port, args.boards)

        rc_event = poll_rc(selected, timeout_log=False)
        if rc_event is not None:
            board, rc_bits, mode = rc_event
            log(
                f"RC force start from role={board.role_id} port={board.port}: "
                f"rc=0b{rc_bits:04b} -> mode{mode}"
            )
            log_selected_boards(selected, forced=True)
            return selected, mode, True

        if len(selected) >= args.boards:
            log("all requested controllers connected; entering mode1")
            log_selected_boards(selected, forced=False)
            return selected, 1, False

        now = time.monotonic()
        if now - last_summary >= args.summary_interval:
            roles = ", ".join(str(board.role_id) for board in selected) if selected else "none"
            log(f"connected {len(selected)}/{args.boards}; roles={roles}")
            last_summary = now

        time.sleep(args.scan_interval)


def log_selected_boards(boards: list[AutoBoard], forced: bool) -> None:
    mode = "forced partial mapping" if forced else "full mapping"
    for board in boards:
        log(f"{mode}: slot{board.slot_id} <- role={board.role_id} port={board.port}")


def start_senders(boards: list[AutoBoard], chunk_delay_s: float) -> None:
    for board in boards:
        board.sender = BoardSender(board, chunk_delay_s=chunk_delay_s)
        board.sender.start()


def stop_and_close(boards: list[AutoBoard]) -> None:
    for board in boards:
        if board.sender is not None:
            board.sender.stop()
    for board in boards:
        if board.sender is not None:
            board.sender.join(timeout=1.0)
    for board in boards:
        board.device.link.close()


def mode_file(mode_dir: Path, mode: int) -> Path:
    return mode_dir / f"mode{mode}.pixelbin"


def submit_frame(boards: list[AutoBoard], frame: PixelFrame) -> None:
    for board in boards:
        if board.slot_id is None or board.sender is None:
            continue
        if board.slot_id > len(frame.board_frames):
            log(f"slot {board.slot_id} missing in pixelbin frame {frame.index}")
            continue
        board.sender.submit(frame.index, frame.board_frames[board.slot_id - 1], frame.ww, frame.cw)


def print_stats(boards: list[AutoBoard], submitted: int, start_time: float) -> None:
    elapsed = max(0.001, time.perf_counter() - start_time)
    fps = submitted / elapsed
    parts = []
    for board in sorted(boards, key=lambda item: item.slot_id or 99):
        if board.sender is None:
            continue
        stats = board.sender.stats
        parts.append(f"s{board.slot_id}/r{board.role_id}:ok={stats.ok} err={stats.errors} skip={stats.skipped}")
    log(f"play submitted={submitted} fps={fps:.1f} {' '.join(parts)}")


def playback_loop(boards: list[AutoBoard], initial_mode: int, args: argparse.Namespace) -> None:
    """Loop mode files and switch modes when RC bits change."""
    current_mode = initial_mode
    mode_dir = Path(args.mode_dir)
    start_senders(boards, chunk_delay_s=args.chunk_delay_ms / 1000.0)
    submitted = 0
    start_time = time.perf_counter()
    last_stats = start_time
    last_rc_poll = 0.0

    try:
        while True:
            path = mode_file(mode_dir, current_mode)
            if not path.exists():
                log(f"{path} not found; waiting for RC mode change")
                current_mode = wait_for_mode_change(boards, current_mode, args)
                continue

            log(f"playing mode{current_mode}: {path}")
            with PixelBinReader(str(path)) as reader:
                fps = args.fps if args.fps > 0.0 else float(reader.header.fps)
                period = 1.0 / fps
                next_deadline = time.perf_counter()

                for frame in reader.iter_frames(loop=True):
                    now = time.perf_counter()
                    if now - last_rc_poll >= args.rc_poll_interval:
                        rc_event = poll_rc(boards, timeout_log=False)
                        last_rc_poll = now
                        if rc_event is not None:
                            board, rc_bits, new_mode = rc_event
                            if new_mode != current_mode:
                                log(
                                    f"RC mode switch from role={board.role_id}: "
                                    f"rc=0b{rc_bits:04b} mode{current_mode}->mode{new_mode}"
                                )
                                current_mode = new_mode
                                break

                    submit_frame(boards, frame)
                    submitted += 1

                    now = time.perf_counter()
                    if now - last_stats >= args.stats_interval:
                        print_stats(boards, submitted, start_time)
                        last_stats = now

                    next_deadline += period
                    sleep_time = next_deadline - time.perf_counter()
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    else:
                        next_deadline = time.perf_counter()
    finally:
        print_stats(boards, submitted, start_time)


def wait_for_mode_change(boards: list[AutoBoard], current_mode: int, args: argparse.Namespace) -> int:
    while True:
        rc_event = poll_rc(boards, timeout_log=True)
        if rc_event is not None:
            _board, _rc_bits, new_mode = rc_event
            if new_mode != current_mode:
                return new_mode
        time.sleep(args.rc_poll_interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autostart playback with USB scan and RC mode switching")
    parser.add_argument("--mode-dir", default=str(DEFAULT_MODE_DIR), help="Directory containing mode1.pixelbin..mode4.pixelbin")
    parser.add_argument("--boards", type=int, default=DEFAULT_BOARD_COUNT, help="Number of controllers required before normal start")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--serial-timeout", type=float, default=0.05)
    parser.add_argument("--response-timeout", type=float, default=1.0)
    parser.add_argument("--scan-interval", type=float, default=1.0)
    parser.add_argument("--summary-interval", type=float, default=5.0)
    parser.add_argument("--rc-poll-interval", type=float, default=0.1)
    parser.add_argument("--chunk-delay-ms", type=float, default=0.25)
    parser.add_argument("--fps", type=float, default=0.0, help="Override pixelbin fps when positive")
    parser.add_argument("--stats-interval", type=float, default=5.0)
    args = parser.parse_args()
    if not 1 <= args.boards <= DEFAULT_BOARD_COUNT:
        raise SystemExit("--boards must be 1..4")
    return args


def main() -> int:
    args = parse_args()
    mode_dir = Path(args.mode_dir)
    log(f"autoplay started; mode_dir={mode_dir}")
    for mode in range(1, DEFAULT_MODE_COUNT + 1):
        path = mode_file(mode_dir, mode)
        log(f"mode{mode} file: {path}")

    boards, mode, forced = wait_for_start(args)
    if forced and len(boards) < args.boards:
        log(f"starting with {len(boards)}/{args.boards} boards due to RC force")

    try:
        playback_loop(boards, mode, args)
    except KeyboardInterrupt:
        log("stopped by user")
    finally:
        stop_and_close(boards)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
