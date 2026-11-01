"""Local FFprobe inspection and FFmpeg processing; inputs are never overwritten."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

from sonata.engine import Stopped, spawn_options, stop_process
from sonata.paths import AppPaths


def probe_command(paths: AppPaths, source: Path) -> list[str]:
    return [
        str(paths.tool("ffprobe")),
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        "-of",
        "json",
        str(source),
    ]


def inspect_media(paths: AppPaths, source: Path, runner=None) -> dict:
    if not source.is_file():
        raise ValueError("Choose an existing media file.")
    command = probe_command(paths, source.resolve())
    if runner:
        lines = []
        runner(command, lines.append)
        return json.loads("\n".join(lines))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        **spawn_options(),
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    return json.loads(result.stdout)


def duration_of(info: dict) -> float:
    try:
        return float(info.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0


@dataclass
class MediaTask:
    source: str
    output: str
    operation: str = "convert"
    video_codec: str = "copy"
    audio_codec: str = "copy"
    audio_kbps: int = 192
    crf: int = 20
    scale_height: int = 0
    start: float = 0
    end: float = 0
    normalize: bool = False
    keep_metadata: bool = True
    metadata: dict[str, str] = field(default_factory=dict)
    subtitle: str = ""
    subtitle_track: int = 0
    subtitle_language: str = "eng"
    extra_args: list[str] = field(default_factory=list)
    overwrite: bool = False

    def validate(self):
        source, output = Path(self.source).resolve(), Path(self.output).resolve()
        if not source.is_file():
            raise ValueError("Choose an existing media file.")
        if not Path(self.output).is_absolute() or not output.suffix:
            raise ValueError("Choose an absolute output filename with an extension.")
        if source == output:
            raise ValueError("The output must be different from the input file.")
        if output.exists() and not self.overwrite:
            raise FileExistsError("The output already exists. Choose another filename.")
        if self.operation not in {
            "convert",
            "remux",
            "audio",
            "trim",
            "metadata",
            "embed_subtitle",
            "extract_subtitle",
            "thumbnail",
            "advanced",
        }:
            raise ValueError("Unknown FFmpeg operation.")
        if self.video_codec not in {"copy", "h264", "hevc", "vp9", "av1"} or self.audio_codec not in {
            "copy",
            "aac",
            "mp3",
            "opus",
            "flac",
            "pcm",
        }:
            raise ValueError("Unknown output codec.")
        if self.start < 0 or self.end < 0 or (self.end and self.end <= self.start):
            raise ValueError("The end time must be later than the start time.")
        if not 0 <= self.scale_height <= 16384 or not 0 <= self.crf <= 51 or not 8 <= self.audio_kbps <= 512:
            raise ValueError("A processing setting is out of range.")
        if self.operation == "embed_subtitle" and not Path(self.subtitle).is_file():
            raise ValueError("Choose an existing subtitle file.")
        if self.normalize and self.audio_codec == "copy":
            raise ValueError("Choose an audio encoder to apply normalization.")
        if self.scale_height and self.video_codec == "copy":
            raise ValueError("Choose a video encoder to resize the video.")
        if any(arg in ("-y", "-n", "-report", "-progress", "-i") for arg in self.extra_args):
            raise ValueError("Extra output arguments cannot change input, overwrite, or progress controls.")
        return self


def processing_command(paths: AppPaths, task: MediaTask, output: Path, info: dict) -> list[str]:
    command = [
        str(paths.tool("ffmpeg")),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "warning",
        "-nostats",
        "-progress",
        "pipe:1",
        "-i",
        str(Path(task.source).resolve()),
    ]
    if task.operation == "embed_subtitle":
        command += ["-i", str(Path(task.subtitle).resolve())]
    if task.start:
        command += ["-ss", str(task.start)]
    if task.end:
        command += ["-t", str(task.end - task.start)]
    if task.operation == "thumbnail":
        return command + ["-map", "0:v:0", "-frames:v", "1", "-q:v", "2", str(output)]
    if task.operation == "extract_subtitle":
        return command + [
            "-map",
            f"0:s:{task.subtitle_track}",
            "-c:s",
            "webvtt" if output.suffix.lower() == ".vtt" else "srt",
            str(output),
        ]
    command += ["-map_metadata", "0" if task.keep_metadata else "-1", "-map_chapters", "0"]
    if task.operation == "audio":
        command += ["-map", "0:a:0", "-vn"]
    elif output.suffix.lower() == ".mkv":
        command += ["-map", "0"]
    else:
        command += ["-map", "0:v?", "-map", "0:a?", "-map", "0:s?"]
    if task.operation == "embed_subtitle":
        command += ["-map", "1:0"]
    command += ["-c", "copy"]
    if task.video_codec != "copy" and task.operation not in {"audio", "metadata", "remux", "embed_subtitle"}:
        command += [
            "-c:v",
            {"h264": "libx264", "hevc": "libx265", "vp9": "libvpx-vp9", "av1": "libsvtav1"}[task.video_codec],
            "-crf",
            str(task.crf),
        ]
        if task.video_codec in {"h264", "hevc"}:
            command += ["-preset", "medium", "-pix_fmt", "yuv420p"]
        if task.scale_height:
            command += ["-vf", f"scale=-2:{task.scale_height}"]
    if task.audio_codec != "copy":
        command += [
            "-c:a",
            {"aac": "aac", "mp3": "libmp3lame", "opus": "libopus", "flac": "flac", "pcm": "pcm_s16le"}[
                task.audio_codec
            ],
        ]
        if task.audio_codec in {"aac", "mp3", "opus"}:
            command += ["-b:a", f"{task.audio_kbps}k"]
    if task.normalize:
        command += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    if task.operation == "embed_subtitle":
        if output.suffix.lower() == ".mp4":
            command += ["-c:s", "mov_text"]
        track = sum(s.get("codec_type") == "subtitle" for s in info.get("streams", []))
        command += [f"-metadata:s:s:{track}", f"language={task.subtitle_language}"]
    for key, value in task.metadata.items():
        command += ["-metadata", f"{key}={value}"]
    if output.suffix.lower() in {".mp4", ".m4a", ".mov"}:
        command += ["-movflags", "+faststart"]
    command += task.extra_args
    return command + [str(output)]


def publish_output(temporary: Path, output: Path, overwrite: bool):
    if overwrite:
        os.replace(temporary, output)
    elif sys.platform == "win32":
        os.rename(temporary, output)  # Windows rename refuses an existing target.
    else:
        os.link(temporary, output)
        temporary.unlink()


def execute_task(
    paths: AppPaths, task: MediaTask, runner, log=lambda *_: None, progress=lambda *_: None
) -> dict:
    task.validate()
    info = inspect_media(paths, Path(task.source), runner)
    duration = duration_of(info)
    if duration and task.start >= duration:
        raise ValueError("The start time is outside the media duration.")
    output = Path(task.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".sonata-process-", suffix=output.suffix, dir=output.parent)
    os.close(handle)
    temporary = Path(name)
    try:
        length = task.end - task.start if task.end else max(0, duration - task.start)

        def on_line(line):
            if line.startswith("out_time_us="):
                try:
                    progress(
                        min(99, float(line.partition("=")[2]) / 1_000_000 / length * 100) if length else 0
                    )
                except ValueError:
                    pass
            elif "=" not in line or line.startswith(("Error", "[")):
                log(line)

        runner(processing_command(paths, task, temporary, info), on_line)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError("FFmpeg did not produce an output file.")
        result = inspect_media(paths, temporary, runner)
        publish_output(temporary, output, task.overwrite)
        result.setdefault("format", {})["filename"] = str(output)
        progress(100)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def finish_download_mp4(paths: AppPaths, source: Path, runner, log=lambda *_: None):
    """Retain video/tags, use AAC if necessary, and finalize a standard MP4 index."""
    info = inspect_media(paths, source, runner)
    audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    task = MediaTask(
        str(source),
        str(source),
        operation="remux",
        audio_codec="aac"
        if any(s.get("codec_name") not in {"aac", "alac", "mp3"} for s in audio)
        else "copy",
    )
    handle, name = tempfile.mkstemp(prefix=".sonata-mp4-", suffix=".mp4", dir=source.parent)
    os.close(handle)
    temporary = Path(name)
    try:
        runner(processing_command(paths, task, temporary, info), log)
        finished = inspect_media(paths, temporary, runner)
        before = [
            (s.get("width"), s.get("height"))
            for s in info.get("streams", [])
            if s.get("codec_type") == "video"
        ]
        after = [
            (s.get("width"), s.get("height"))
            for s in finished.get("streams", [])
            if s.get("codec_type") == "video"
        ]
        if before != after or abs(duration_of(finished) - duration_of(info)) > 1:
            raise RuntimeError("The MP4 output failed its stream validation.")
        os.replace(temporary, source)
    finally:
        temporary.unlink(missing_ok=True)


class MediaRunner:
    def __init__(self):
        self.event = threading.Event()
        self.process = None
        self.lock = threading.RLock()

    def cancel(self):
        self.event.set()
        with self.lock:
            process = self.process
        if process:
            stop_process(process)

    def run(self, command: list[str], on_line):
        if self.event.is_set():
            raise Stopped("Cancelled")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **spawn_options(),
        )
        with self.lock:
            self.process = process
            if self.event.is_set():
                stop_process(process)
        tail = []
        try:
            for line in process.stdout:
                if self.event.is_set():
                    raise Stopped("Cancelled")
                line = line.strip()
                tail = (tail + [line])[-15:]
                on_line(line)
            if self.event.is_set():
                raise Stopped("Cancelled")
            if process.wait():
                raise RuntimeError("\n".join(tail)[-4000:])
        finally:
            stop_process(process)
            process.wait()
            process.stdout.close()
            with self.lock:
                self.process = None
