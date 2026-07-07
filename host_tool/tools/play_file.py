"""Play a local pixelbin file to multiple controller boards."""

from __future__ import annotations

import argparse
import queue
import threading
import time
from dataclasses import dataclass

from pixel_host import protocol as proto
from pixel_host.device_manager import ConnectedDevice
from pixel_host.pixelbin import PixelBinReader, PixelFrame


@dataclass
class WorkerStats:
    sent: int = 0
    ok: int = 0
    skipped: int = 0
    errors: int = 0


class BoardWorker(threading.Thread):
    """One sending thread per connected board so slow boards do not block all roles."""

    def __init__(self, connected: ConnectedDevice, chunk_delay_s: float) -> None:
        super().__init__(daemon=True)
        self.connected = connected
        self.chunk_delay_s = chunk_delay_s
        self.queue: queue.Queue[tuple[int, bytes, int, int] | None] = queue.Queue(maxsize=1)
        self.stats = WorkerStats()
        self._stop_requested = threading.Event()

    def submit(self, frame_index: int, frame_rgb: bytes, ww: int, cw: int) -> None:
        item = (frame_index, frame_rgb, ww, cw)
        try:
            self.queue.put_nowait(item)
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
                commit = self.connected.device.send_frame(
                    frame_rgb,
                    ww=ww,
                    cw=cw,
                    chunk_delay_s=self.chunk_delay_s,
                )
                if commit.status == proto.OK:
                    self.stats.ok += 1
                else:
                    self.stats.errors += 1
                    print(
                        f"slot {self.connected.slot_id} role {self.connected.role_id} "
                        f"frame {frame_index} commit status={commit.status} "
                        f"mask=0x{commit.received_mask:04x}"
                    )
            except Exception as exc:
                self.stats.errors += 1
                print(f"slot {self.connected.slot_id} role {self.connected.role_id} frame {frame_index} skipped: {exc}")


def connect_workers(args: argparse.Namespace) -> dict[int, BoardWorker]:
    workers: dict[int, BoardWorker] = {}
    ports = args.ports if args.ports else None

    for connected in scan_ports(ports, args):
        if connected.slot_id is None:
            print(
                f"[{connected.port}] role={connected.role_id} uid={proto.format_uid(connected.uid_hash)} "
                "has no configured slot, ignored"
            )
            connected.device.link.close()
            continue
        if connected.slot_id in workers:
            print(f"[{connected.port}] duplicate slot {connected.slot_id}, ignoring")
            connected.device.link.close()
            continue
        worker = BoardWorker(connected, chunk_delay_s=args.chunk_delay_ms / 1000.0)
        workers[connected.slot_id] = worker
        print(
            f"[{connected.port}] role={connected.role_id} slot={connected.slot_id} "
            f"uid={proto.format_uid(connected.uid_hash)} connected"
        )

    for worker in workers.values():
        worker.start()

    return workers


def scan_ports(ports: list[str] | None, args: argparse.Namespace) -> list[ConnectedDevice]:
    from pixel_host.serial_link import list_serial_ports
    from pixel_host.device_manager import load_device_config, resolve_assignment
    from pixel_host.device import PixelDevice
    from pixel_host.serial_link import SerialLink

    connected: list[ConnectedDevice] = []
    config_entries = load_device_config(args.config)
    port_list = ports if ports else list_serial_ports()
    for port in port_list:
        link = SerialLink(port, baudrate=args.baud, timeout=0.05)
        try:
            link.open()
            device = PixelDevice(link=link, response_timeout=args.timeout)
            hello = device.hello()
            role_id, slot_id = resolve_assignment(hello, config_entries)
            if 1 <= role_id <= 20:
                connected.append(
                    ConnectedDevice(port=port, role_id=role_id, slot_id=slot_id, uid_hash=hello.uid_hash, device=device)
                )
            else:
                print(f"[{port}] invalid role_id={role_id}, ignored")
                link.close()
        except Exception as exc:
            print(f"[{port}] no response: {exc}")
            link.close()
    return connected


def submit_frame(workers: dict[int, BoardWorker], frame: PixelFrame) -> None:
    for slot_id, board_frame in enumerate(frame.board_frames, start=1):
        worker = workers.get(slot_id)
        if worker is None:
            continue
        worker.submit(frame.index, board_frame, frame.ww, frame.cw)


def print_stats(workers: dict[int, BoardWorker], frame_index: int, start_time: float) -> None:
    elapsed = max(0.001, time.perf_counter() - start_time)
    fps = frame_index / elapsed
    parts = []
    for slot_id in sorted(workers):
        worker = workers[slot_id]
        stats = worker.stats
        parts.append(f"s{slot_id}/r{worker.connected.role_id}:ok={stats.ok} err={stats.errors} skip={stats.skipped}")
    print(f"play frame={frame_index} fps={fps:.1f} {' '.join(parts)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Play a pixelbin file to scanned controller boards")
    parser.add_argument("--file", required=True, help="Input .pixelbin path")
    parser.add_argument("--config", default=None, help="Optional physical role-to-slot JSON config")
    parser.add_argument("--ports", nargs="*", help="Optional explicit COM port list")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--chunk-delay-ms", type=float, default=0.0)
    parser.add_argument("--fps", type=float, default=0.0, help="Override file fps when positive")
    parser.add_argument("--once", action="store_true", help="Play file once instead of looping")
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after this many submitted frames")
    parser.add_argument("--stats-interval", type=float, default=1.0)
    args = parser.parse_args()

    workers = connect_workers(args)
    if not workers:
        print("no configured boards connected")
        return 2

    submitted = 0
    last_stats = time.perf_counter()
    start_time = last_stats

    try:
        with PixelBinReader(args.file) as reader:
            fps = args.fps if args.fps > 0.0 else float(reader.header.fps)
            period = 1.0 / fps
            print(
                f"playing {args.file}: boards={reader.header.board_count} fps={fps:.1f} "
                f"frames={reader.header.frame_count}"
            )
            next_deadline = time.perf_counter()
            for frame in reader.iter_frames(loop=not args.once):
                submit_frame(workers, frame)
                submitted += 1

                now = time.perf_counter()
                if now - last_stats >= args.stats_interval:
                    print_stats(workers, submitted, start_time)
                    last_stats = now

                if args.max_frames > 0 and submitted >= args.max_frames:
                    break

                next_deadline += period
                sleep_time = next_deadline - time.perf_counter()
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    next_deadline = time.perf_counter()
    except KeyboardInterrupt:
        print("stopped by user")
    finally:
        for worker in workers.values():
            worker.stop()
        for worker in workers.values():
            worker.join(timeout=1.0)
            worker.connected.device.link.close()
        print_stats(workers, submitted, start_time)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
