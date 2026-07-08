"""Offline video-to-pixelbin conversion for the 32x48 logical display."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os

from .display_mapping import SCREEN_HEIGHT, SCREEN_WIDTH, split_screen_to_boards
from .pixelbin import DEFAULT_BOARD_COUNT, write_pixelbin


ProgressCallback = Callable[[int, int], None]
LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class VideoGenerateOptions:
    """User-selected conversion settings for one output file."""

    input_path: str
    output_path: str
    preview_mp4_path: str = ""
    fps: int = 60
    start_s: float = 0.0
    end_s: float = 0.0
    brightness: float = 1.0
    gamma: float = 1.0
    saturation: float = 1.0
    ww: int = 0
    cw: int = 0
    board_count: int = DEFAULT_BOARD_COUNT


@dataclass(frozen=True)
class VideoGenerateResult:
    """Summary returned after a successful conversion."""

    output_path: str
    preview_mp4_path: str
    frames_written: int
    fps: int
    duration_s: float
    source_fps: float
    source_frames: int


def generate_pixelbin_from_video(
    options: VideoGenerateOptions,
    progress: ProgressCallback | None = None,
    log: LogCallback | None = None,
) -> VideoGenerateResult:
    """Convert a source video into the existing board-major pixelbin format."""
    _validate_options(options)

    if _is_gif(options.input_path):
        return _generate_from_gif(options, progress=progress, log=log)
    return _generate_from_video(options, progress=progress, log=log)


def _generate_from_video(
    options: VideoGenerateOptions,
    progress: ProgressCallback | None,
    log: LogCallback | None,
) -> VideoGenerateResult:
    """Convert a video file through OpenCV."""

    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on local environment.
        raise RuntimeError("opencv-python is not installed. Run host_tool/setup_host_env.ps1 first.") from exc

    capture = cv2.VideoCapture(options.input_path)
    if not capture.isOpened():
        raise ValueError(f"cannot open video: {options.input_path}")

    try:
        source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        source_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if source_fps <= 0.0:
            raise ValueError("source video did not report a valid FPS")

        start_frame = max(0, int(round(options.start_s * source_fps)))
        if options.end_s > options.start_s:
            end_frame = min(source_frames, int(round(options.end_s * source_fps))) if source_frames > 0 else None
        else:
            end_frame = source_frames if source_frames > 0 else None
        if end_frame is not None and end_frame <= start_frame:
            raise ValueError("selected video time range is empty")

        frame_step = source_fps / options.fps
        total_output_frames = _estimate_output_frames(start_frame, end_frame, source_frames, source_fps, options.fps)
        if log is not None:
            log(
                f"source fps={source_fps:.3f} frames={source_frames} "
                f"output fps={options.fps} estimated_frames={total_output_frames}"
            )

        preview_writer = _open_preview_writer(cv2, options)
        if preview_writer is not None and log is not None:
            log(f"preview mp4={options.preview_mp4_path}")

        def frame_records():
            written = 0
            next_source_index = float(start_frame)
            gamma_lut = _build_gamma_lut(np, options.gamma)

            while end_frame is None or int(round(next_source_index)) < end_frame:
                source_index = int(round(next_source_index))
                if source_frames > 0 and source_index >= source_frames:
                    break

                capture.set(cv2.CAP_PROP_POS_FRAMES, source_index)
                ok, bgr = capture.read()
                if not ok or bgr is None:
                    break

                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                rgb = _process_rgb_frame(cv2, np, rgb, options, gamma_lut)
                if preview_writer is not None:
                    _write_preview_frame(cv2, preview_writer, rgb)
                board_frames = split_screen_to_boards(rgb.tobytes(), board_count=options.board_count)
                written += 1
                if progress is not None:
                    progress(written, total_output_frames)
                yield options.ww, options.cw, board_frames
                next_source_index += frame_step

        frames_written = write_pixelbin(
            options.output_path,
            frame_records(),
            fps=options.fps,
            board_count=options.board_count,
        )
    finally:
        if "preview_writer" in locals() and preview_writer is not None:
            preview_writer.release()
        capture.release()

    duration_s = frames_written / options.fps if options.fps > 0 else 0.0
    return VideoGenerateResult(
        output_path=options.output_path,
        preview_mp4_path=options.preview_mp4_path,
        frames_written=frames_written,
        fps=options.fps,
        duration_s=duration_s,
        source_fps=source_fps,
        source_frames=source_frames,
    )


def _generate_from_gif(
    options: VideoGenerateOptions,
    progress: ProgressCallback | None,
    log: LogCallback | None,
) -> VideoGenerateResult:
    """Convert an animated GIF through Pillow while preserving GIF frame timing."""
    try:
        import cv2  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]
        from PIL import Image, ImageSequence  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on local environment.
        raise RuntimeError("Pillow and opencv-python are required. Run host_tool/setup_host_env.ps1 first.") from exc

    frames, timestamps_s, duration_s = _load_gif_frames(Image, ImageSequence, options.input_path)
    if not frames:
        raise ValueError(f"gif contains no frames: {options.input_path}")

    start_s = min(options.start_s, duration_s)
    end_s = options.end_s if options.end_s > options.start_s else duration_s
    end_s = min(end_s, duration_s)
    if end_s <= start_s:
        raise ValueError("selected GIF time range is empty")

    total_output_frames = max(1, int(round((end_s - start_s) * options.fps)))
    source_fps = len(frames) / duration_s if duration_s > 0.0 else float(options.fps)
    if log is not None:
        log(
            f"source gif frames={len(frames)} duration={duration_s:.3f}s "
            f"output fps={options.fps} estimated_frames={total_output_frames}"
        )

    preview_writer = _open_preview_writer(cv2, options)
    if preview_writer is not None and log is not None:
        log(f"preview mp4={options.preview_mp4_path}")

    try:
        def frame_records():
            gamma_lut = _build_gamma_lut(np, options.gamma)
            for written in range(1, total_output_frames + 1):
                sample_s = start_s + (written - 1) / options.fps
                source_index = _gif_frame_index_at(timestamps_s, sample_s)
                rgb = _process_rgb_frame(cv2, np, frames[source_index], options, gamma_lut)
                if preview_writer is not None:
                    _write_preview_frame(cv2, preview_writer, rgb)
                board_frames = split_screen_to_boards(rgb.tobytes(), board_count=options.board_count)
                if progress is not None:
                    progress(written, total_output_frames)
                yield options.ww, options.cw, board_frames

        frames_written = write_pixelbin(
            options.output_path,
            frame_records(),
            fps=options.fps,
            board_count=options.board_count,
        )
    finally:
        if preview_writer is not None:
            preview_writer.release()

    return VideoGenerateResult(
        output_path=options.output_path,
        preview_mp4_path=options.preview_mp4_path,
        frames_written=frames_written,
        fps=options.fps,
        duration_s=frames_written / options.fps,
        source_fps=source_fps,
        source_frames=len(frames),
    )


def _validate_options(options: VideoGenerateOptions) -> None:
    if not options.input_path:
        raise ValueError("input video path is required")
    if not os.path.exists(options.input_path):
        raise ValueError(f"input video does not exist: {options.input_path}")
    if not options.output_path:
        raise ValueError("output pixelbin path is required")
    output_dir = os.path.dirname(os.path.abspath(options.output_path))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    if options.preview_mp4_path:
        preview_dir = os.path.dirname(os.path.abspath(options.preview_mp4_path))
        if preview_dir:
            os.makedirs(preview_dir, exist_ok=True)
    if options.fps < 1 or options.fps > 240:
        raise ValueError("output FPS must be 1..240")
    if options.start_s < 0.0 or options.end_s < 0.0:
        raise ValueError("start/end time must be non-negative")
    if options.end_s > 0.0 and options.end_s <= options.start_s:
        raise ValueError("end time must be greater than start time")
    if options.gamma <= 0.0:
        raise ValueError("gamma must be positive")
    if options.brightness <= 0.0:
        raise ValueError("brightness must be positive")
    if options.saturation < 0.0:
        raise ValueError("saturation must be non-negative")
    if not 0 <= options.ww <= 1000 or not 0 <= options.cw <= 1000:
        raise ValueError("WW/CW must be 0..1000")


def _estimate_output_frames(
    start_frame: int,
    end_frame: int | None,
    source_frames: int,
    source_fps: float,
    output_fps: int,
) -> int:
    if end_frame is not None:
        source_span = max(0, end_frame - start_frame)
    elif source_frames > 0:
        source_span = max(0, source_frames - start_frame)
    else:
        return 0
    seconds = source_span / source_fps
    return max(1, int(round(seconds * output_fps)))


def _process_rgb_frame(cv2, np, rgb, options: VideoGenerateOptions, gamma_lut):  # type: ignore[no-untyped-def]
    cropped = _center_crop_to_screen_aspect(rgb)
    resized = cv2.resize(cropped, (SCREEN_WIDTH, SCREEN_HEIGHT), interpolation=cv2.INTER_AREA)
    rgb = resized

    if options.saturation != 1.0:
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * options.saturation, 0, 255)
        rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

    if options.brightness != 1.0:
        rgb = np.clip(rgb.astype(np.float32) * options.brightness, 0, 255).astype(np.uint8)

    if gamma_lut is not None:
        rgb = cv2.LUT(rgb, gamma_lut)

    return rgb


def _open_preview_writer(cv2, options: VideoGenerateOptions):  # type: ignore[no-untyped-def]
    if not options.preview_mp4_path:
        return None

    preview_size = (SCREEN_WIDTH * 10, SCREEN_HEIGHT * 10)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(options.preview_mp4_path, fourcc, float(options.fps), preview_size)
    if not writer.isOpened():
        raise ValueError(f"cannot open preview mp4 for writing: {options.preview_mp4_path}")
    return writer


def _write_preview_frame(cv2, writer, rgb):  # type: ignore[no-untyped-def]
    preview_rgb = cv2.resize(rgb, (SCREEN_WIDTH * 10, SCREEN_HEIGHT * 10), interpolation=cv2.INTER_NEAREST)
    preview_bgr = cv2.cvtColor(preview_rgb, cv2.COLOR_RGB2BGR)
    writer.write(preview_bgr)


def _center_crop_to_screen_aspect(frame):  # type: ignore[no-untyped-def]
    height, width = frame.shape[:2]
    target_aspect = SCREEN_WIDTH / SCREEN_HEIGHT
    source_aspect = width / height

    if source_aspect > target_aspect:
        crop_width = max(1, int(round(height * target_aspect)))
        x0 = (width - crop_width) // 2
        return frame[:, x0 : x0 + crop_width]

    crop_height = max(1, int(round(width / target_aspect)))
    y0 = (height - crop_height) // 2
    return frame[y0 : y0 + crop_height, :]


def _build_gamma_lut(np, gamma: float):  # type: ignore[no-untyped-def]
    if abs(gamma - 1.0) < 0.001:
        return None
    inv_gamma = 1.0 / gamma
    return np.array([((value / 255.0) ** inv_gamma) * 255.0 for value in range(256)]).clip(0, 255).astype("uint8")


def _is_gif(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".gif"


def _load_gif_frames(Image, ImageSequence, path: str):  # type: ignore[no-untyped-def]
    frames = []
    timestamps_s = []
    elapsed_ms = 0

    with Image.open(path) as image:
        for frame in ImageSequence.Iterator(image):
            timestamps_s.append(elapsed_ms / 1000.0)
            rgba = frame.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
            composited = Image.alpha_composite(background, rgba).convert("RGB")
            frames.append(composited)
            duration_ms = int(frame.info.get("duration", image.info.get("duration", 100)) or 100)
            elapsed_ms += max(10, duration_ms)

    rgb_arrays = []
    try:
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - checked by caller.
        raise RuntimeError("numpy is required by opencv-python") from exc

    for frame in frames:
        rgb_arrays.append(np.array(frame))

    duration_s = max(0.001, elapsed_ms / 1000.0)
    return rgb_arrays, timestamps_s, duration_s


def _gif_frame_index_at(timestamps_s: list[float], sample_s: float) -> int:
    index = 0
    for current_index, timestamp_s in enumerate(timestamps_s):
        if timestamp_s > sample_s:
            break
        index = current_index
    return index
