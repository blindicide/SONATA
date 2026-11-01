from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from sonata.database import Database
from sonata.models import DownloadOptions, format_selector, scan_summary, validate_url
from sonata.paths import AppPaths


class Stopped(Exception):
    pass


def spawn_options() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def stop_process(process: subprocess.Popen):
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def base_command(paths: AppPaths) -> list[str]:
    return [
        str(paths.tool("yt-dlp")),
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-update",
        "--no-remote-components",
        "--no-color",
        "--socket-timeout",
        "20",
        "--ffmpeg-location",
        str(paths.tool("ffmpeg").parent),
        "--no-js-runtimes",
        "--js-runtimes",
        f"deno:{paths.tool('deno')}",
    ]


def media_identity(info: dict, url: str) -> tuple[str, str]:
    extractor = str(info.get("extractor_key") or info.get("extractor") or "generic").lower()
    if extractor == "generic":
        digest = hashlib.sha256(url.partition("#")[0].encode("utf-8")).hexdigest()
        return f"generic:{digest}", digest[:12]
    return f"{extractor}:{info.get('id') or url}", ""


def download_command(
    paths: AppPaths, url: str, options: DownloadOptions, filename_tag: str = ""
) -> list[str]:
    options.validate()
    command = base_command(paths) + [
        "--no-playlist",
        "--continue",
        "--no-overwrites",
        "--newline",
        "--progress",
        "--no-simulate",
        "--progress-delta",
        "0.5",
        "--progress-template",
        "download:SONATA_PROGRESS:%(progress)j",
        "--print",
        "after_move:SONATA_FILE:%(filepath)j",
        "--retries",
        str(options.retries),
        "--fragment-retries",
        str(options.retries),
        "--windows-filenames",
        "--paths",
        str(options.folder),
        "--output",
        options.template.replace("%(ext)s", f"{filename_tag}.%(ext)s") if filename_tag else options.template,
        "--format",
        format_selector(options),
    ]
    if options.mode == "audio":
        command += ["--extract-audio", "--audio-format", options.audio_codec, "--audio-quality", "0"]
    else:
        command += ["--merge-output-format", options.container, "--remux-video", options.container]
        if options.container == "mp4" and options.video_codec == "any":
            command += ["--format-sort", "res,vcodec:h264,acodec:aac"]
    if options.rate_kib:
        command += ["--limit-rate", str(options.rate_kib * 1024)]
    if options.subtitles:
        command += ["--write-subs", "--sub-langs", options.subtitle_languages]
        if options.automatic_subtitles:
            command += ["--write-auto-subs"]
    if options.metadata:
        command += ["--embed-metadata", "--write-info-json"]
    if options.thumbnail:
        command += ["--write-thumbnail"]
    return command + ["--", validate_url(url)]


class Engine:
    def __init__(self, database: Database, paths: AppPaths, notify=lambda *_: None):
        self.db, self.paths, self.notify = database, paths, notify
        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="sonata")
        self.lock = threading.RLock()
        self.running: dict[int, threading.Event] = {}
        self.phases: dict[int, str] = {}
        self.processes: dict[int, subprocess.Popen] = {}
        self.targets: dict[int, str] = {}
        self.enabled = False
        self.scans_enabled = True
        self.closed = False
        self.concurrency = int(database.setting("concurrency", 2))

    def log(self, job_id: int, line: str):
        self.notify("log", (job_id, line))

    def tick(self):
        with self.lock:
            if self.closed:
                return
            pending = sorted(
                (j for j in self.db.jobs() if j["state"] == "queued" and j["id"] not in self.running),
                key=lambda j: j["id"],
            )
            downloads = sum(phase == "download" for phase in self.phases.values())
            scans = sum(phase == "scan" for phase in self.phases.values())
            for job in pending:
                phase = None
                if (
                    self.enabled
                    and job["auto_start"]
                    and job["scan_state"] == "ready"
                    and downloads < self.concurrency
                ):
                    phase = "download"
                    downloads += 1
                elif self.scans_enabled and job["scan_state"] == "pending" and scans < 2:
                    phase = "scan"
                    scans += 1
                if phase:
                    self.running[job["id"]] = threading.Event()
                    self.phases[job["id"]] = phase
                    self.executor.submit(self._scan if phase == "scan" else self._download, job)

    def _descendants(self, job_ids: list[int] | None, jobs: list[dict]) -> set[int]:
        if job_ids is None:
            return {j["id"] for j in jobs}
        selected = set(job_ids)
        while True:
            children = {j["id"] for j in jobs if j["parent_id"] in selected}
            if children <= selected:
                return selected
            selected |= children

    def start(self, job_ids: list[int] | None = None):
        with self.lock:
            jobs = self.db.jobs()
            selected = self._descendants(job_ids, jobs)
            for job in jobs:
                if job["id"] not in selected or job["state"] == "completed":
                    continue
                if job["state"] in ("expanded", "scanning", "downloading", "processing"):
                    self.db.update(job["id"], auto_start=1)
                elif job["state"] != "skipped" or job_ids is not None:
                    self.db.update(
                        job["id"],
                        state="queued",
                        auto_start=1,
                        error="",
                        speed=0,
                        eta=None,
                        scan_state="pending" if job["scan_state"] == "error" else job["scan_state"],
                    )
            self.enabled = self.scans_enabled = True
        self.tick()

    def stop(self, job_ids: list[int] | None = None, state: str = "paused"):
        with self.lock:
            if job_ids is None:
                self.enabled = self.scans_enabled = False
            jobs = self.db.jobs()
            selected = self._descendants(job_ids, jobs)
            for job in jobs:
                job_id = job["id"]
                if job_id not in selected:
                    continue
                if job_id in self.running:
                    self.targets[job_id] = state
                    self.running[job_id].set()
                    self.db.update(job_id, state=state, auto_start=0, speed=0, eta=None)
                elif job["state"] in ("queued", "paused", "failed"):
                    self.db.update(job_id, state=state, auto_start=0, speed=0, eta=None)
                elif job["state"] == "expanded":
                    self.db.update(job_id, auto_start=0)
            processes = [p for job_id, p in self.processes.items() if job_id in selected]
        for process in processes:
            stop_process(process)

    def rescan(self, job_ids: list[int]):
        with self.lock:
            for job_id in job_ids:
                job = self.db.job(job_id)
                if job_id in self.running or job["state"] == "completed":
                    continue
                self.db.update(job_id, state="queued", scan_state="pending", auto_start=0, error="")
            self.scans_enabled = True
        self.tick()

    def set_resolution(self, job_id: int, height: int):
        with self.lock:
            job = self.db.job(job_id)
            if job_id in self.running or job["state"] not in ("queued", "paused", "failed"):
                raise ValueError("Pause the transfer before changing its resolution.")
            info = json.loads(job["scan"])
            if height not in {row["height"] for row in info.get("resolutions", [])}:
                raise ValueError("Choose a resolution offered by this video.")
            options = replace(DownloadOptions(**json.loads(job["options"])), height=height).validate()
            self.db.update(job_id, options=json.dumps(options.to_dict()))

    def shutdown(self):
        self.closed = True
        self.stop()
        self.executor.shutdown(wait=True, cancel_futures=True)

    def _check(self, job_id: int):
        if self.running[job_id].is_set():
            raise Stopped

    def _stream(self, job_id: int, command: list[str], on_line):
        self._check(job_id)
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
            self.processes[job_id] = process
            stopped = self.running[job_id].is_set()
        if stopped:
            stop_process(process)
        tail = []
        try:
            for line in process.stdout:
                self._check(job_id)
                line = line.strip()
                if line:
                    tail.append(line)
                    tail = tail[-12:]
                    on_line(line)
            code = process.wait()
            self._check(job_id)
            if code:
                raise RuntimeError("\n".join(tail)[-4000:] or f"Process exited with code {code}")
        finally:
            stop_process(process)
            process.wait()
            process.stdout.close()
            with self.lock:
                self.processes.pop(job_id, None)

    def _finish(self, job_id: int, error: Exception | None = None):
        if isinstance(error, Stopped):
            values = {"state": self.targets.get(job_id, "paused"), "speed": 0, "eta": None}
            if self.phases.get(job_id) == "scan":
                values["scan_state"] = "pending"
            self.db.update(job_id, **values)
        elif error is not None:
            values = {"state": "failed", "error": str(error)[-4000:], "speed": 0, "eta": None}
            if self.phases.get(job_id) == "scan":
                values["scan_state"] = "error"
            self.db.update(job_id, **values)
            self.log(job_id, str(error))
        self.db.release(job_id)
        with self.lock:
            self.running.pop(job_id, None)
            self.phases.pop(job_id, None)
            self.targets.pop(job_id, None)
        self.notify("changed", job_id)

    def _scan(self, job: dict):
        job_id = job["id"]
        error = None
        try:
            options = DownloadOptions(**json.loads(job["options"])).validate()
            self.db.update(job_id, state="scanning", scan_state="scanning", error="", speed=0, eta=None)
            lines = []

            def on_line(line):
                if line.startswith("{"):
                    lines.append(line)
                else:
                    self.log(job_id, line)

            command = base_command(self.paths) + [
                "--dump-single-json",
                "--flat-playlist",
                "--skip-download",
                "--retries",
                str(options.retries),
            ]
            if not options.playlist:
                command += ["--no-playlist"]
            self._stream(job_id, command + ["--", job["url"]], on_line)
            if not lines:
                raise RuntimeError("The extractor returned no media information.")
            info = json.loads(lines[-1])
            title = str(info.get("title") or job["url"])
            self.db.update(job_id, title=title)
            if info.get("entries") is not None:
                if not options.playlist:
                    raise ValueError("This URL is a playlist. Enable playlists and channels to add it.")
                count = self._expand(job_id, info, options, job["url"])
                if not count:
                    raise ValueError("The playlist contains no downloadable entries.")
                with self.lock:
                    self._check(job_id)
                    self.db.update(
                        job_id, state="expanded", scan_state="ready", progress=100, error=f"{count} entries"
                    )
                return
            summary = scan_summary(info)
            heights = [row["height"] for row in summary["resolutions"]]
            if heights and options.mode == "video":
                height = (
                    options.height
                    if options.height in heights
                    else max(
                        (h for h in heights if not options.height or h <= options.height),
                        default=max(heights),
                    )
                )
                options = replace(options, height=height)
            with self.lock:
                self._check(job_id)
                self.db.update(
                    job_id,
                    state="queued",
                    scan_state="ready",
                    scan=json.dumps(summary),
                    options=json.dumps(options.to_dict()),
                )
        except Exception as exc:
            error = exc
        finally:
            self._finish(job_id, error)

    def _download(self, job: dict):
        job_id = job["id"]
        error = None
        try:
            options = DownloadOptions(**json.loads(job["options"])).validate()
            options.folder.mkdir(parents=True, exist_ok=True)
            info = json.loads(job["scan"])
            media_key, filename_tag = media_identity(info, job["url"])
            if not self.db.claim(media_key, job_id):
                self.db.update(
                    job_id, state="skipped", error="Already in the library or another active download."
                )
                return
            self._check(job_id)
            self.db.update(job_id, state="downloading", progress=0, error="")
            files = []

            def progress_line(line):
                if line.startswith("SONATA_PROGRESS:"):
                    progress = json.loads(line.partition(":")[2])
                    total = progress.get("total_bytes") or progress.get("total_bytes_estimate") or 0
                    self.db.update(
                        job_id,
                        progress=min(99.9, (progress.get("downloaded_bytes") or 0) / total * 100)
                        if total
                        else 0,
                        speed=progress.get("speed") or 0,
                        eta=progress.get("eta"),
                        state="processing" if progress.get("status") == "finished" else "downloading",
                    )
                elif line.startswith("SONATA_FILE:"):
                    path = Path(json.loads(line.partition(":")[2])).resolve()
                    if not path.is_relative_to(options.folder.resolve()):
                        raise ValueError("The downloader produced a path outside the destination.")
                    files.append(path)
                else:
                    self.log(job_id, line)

            self._stream(
                job_id, download_command(self.paths, job["url"], options, filename_tag), progress_line
            )
            self._check(job_id)
            if options.mode == "video" and options.container == "mp4":
                from sonata.media import finish_download_mp4

                self.db.update(job_id, state="processing", speed=0, eta=None)
                for path in files:
                    finish_download_mp4(
                        self.paths,
                        path,
                        lambda command, callback: self._stream(job_id, command, callback),
                        lambda line: self.log(job_id, line),
                    )
            sidecars = []
            for path in files:
                for candidate in path.parent.glob(path.stem.replace("[", "[[]") + ".*"):
                    if candidate.suffix.lower() in {
                        ".json",
                        ".vtt",
                        ".srt",
                        ".ass",
                        ".jpg",
                        ".jpeg",
                        ".png",
                        ".webp",
                    }:
                        sidecars.append(candidate)
            self._check(job_id)
            self.db.complete(
                job_id,
                media_key,
                job["title"],
                list(dict.fromkeys(files + sidecars)),
                options.folder,
                options.collection,
            )
        except Exception as exc:
            error = exc
        finally:
            self._finish(job_id, error)

    def _expand(self, job_id: int, info: dict, options: DownloadOptions, source: str) -> int:
        count = 0
        seen = set()
        existing = {j["url"] for j in self.db.jobs() if j["parent_id"] == job_id}

        def visit(entry):
            nonlocal count
            self._check(job_id)
            if not entry:
                return
            if entry.get("entries") is not None:
                for child in entry["entries"]:
                    visit(child)
                return
            url = entry.get("webpage_url") or entry.get("url")
            if (
                url
                and not url.startswith(("http://", "https://"))
                and str(entry.get("ie_key", "")).lower() == "youtube"
            ):
                url = f"https://www.youtube.com/watch?v={entry['id']}"
            if url and url != source and url not in seen:
                validate_url(url)
                seen.add(url)
                with self.lock:
                    self._check(job_id)
                    if url not in existing:
                        self.db.add(
                            url,
                            options,
                            str(entry.get("title") or url),
                            parent_id=job_id,
                            auto_start=bool(self.db.job(job_id)["auto_start"]),
                        )
                        existing.add(url)
                count += 1

        visit(info)
        return count
