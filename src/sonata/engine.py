from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sonata.database import Database
from sonata.models import DownloadOptions, format_selector, validate_url
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


def download_command(paths: AppPaths, url: str, options: DownloadOptions) -> list[str]:
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
        options.template,
        "--format",
        format_selector(options),
    ]
    if options.mode == "audio":
        command += ["--extract-audio", "--audio-format", options.audio_codec, "--audio-quality", "0"]
    else:
        command += ["--merge-output-format", options.container, "--remux-video", options.container]
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
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="sonata")
        self.lock = threading.RLock()
        self.running: dict[int, threading.Event] = {}
        self.processes: dict[int, subprocess.Popen] = {}
        self.targets: dict[int, str] = {}
        self.enabled = False
        self.closed = False
        self.concurrency = int(database.setting("concurrency", 2))

    def log(self, job_id: int, line: str):
        self.notify("log", (job_id, line))

    def tick(self):
        with self.lock:
            if not self.enabled or self.closed:
                return
            pending = sorted((j for j in self.db.jobs() if j["state"] == "queued"), key=lambda j: j["id"])
            for job in pending:
                if len(self.running) >= self.concurrency:
                    break
                if job["id"] in self.running:
                    continue
                self.running[job["id"]] = threading.Event()
                self.executor.submit(self._run, job)

    def start(self, job_ids: list[int] | None = None):
        with self.lock:
            for job in self.db.jobs():
                if (job_ids is None or job["id"] in job_ids) and job["state"] in (
                    "paused",
                    "failed",
                    "cancelled",
                ):
                    self.db.update(job["id"], state="queued", error="", speed=0, eta=None)
            self.enabled = True
        self.tick()

    def stop(self, job_ids: list[int] | None = None, state: str = "paused"):
        with self.lock:
            if job_ids is None:
                self.enabled = False
            for job in self.db.jobs():
                job_id = job["id"]
                if job_ids is not None and job_id not in job_ids:
                    continue
                if job_id in self.running:
                    self.targets[job_id] = state
                    self.running[job_id].set()
                elif job["state"] in ("queued", "paused", "failed"):
                    self.db.update(job_id, state=state, speed=0, eta=None)
            processes = [p for job_id, p in self.processes.items() if job_ids is None or job_id in job_ids]
        for process in processes:
            stop_process(process)

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
                raise RuntimeError("\n".join(tail)[-4000:] or f"yt-dlp exited with code {code}")
        finally:
            stop_process(process)
            process.wait()
            process.stdout.close()
            with self.lock:
                self.processes.pop(job_id, None)

    def _run(self, job: dict):
        job_id = job["id"]
        try:
            options = DownloadOptions(**json.loads(job["options"])).validate()
            options.folder.mkdir(parents=True, exist_ok=True)
            self.db.update(job_id, state="resolving", error="", speed=0, eta=None)
            info_lines = []

            def inspect_line(line):
                if line.startswith("{"):
                    info_lines.append(line)
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
            self._stream(job_id, command + ["--", job["url"]], inspect_line)
            if not info_lines:
                raise RuntimeError("The extractor returned no media information.")
            info = json.loads(info_lines[-1])
            title = str(info.get("title") or job["url"])
            self.db.update(job_id, title=title)
            if info.get("entries") is not None:
                if not options.playlist:
                    raise ValueError("This URL is a playlist. Enable playlists and channels to add it.")
                count = self._expand(job_id, info, options, job["url"])
                if not count:
                    raise ValueError("The playlist contains no downloadable entries.")
                self.db.update(job_id, state="expanded", progress=100, error=f"{count} entries")
                return
            media_key = f"{str(info.get('extractor_key') or info.get('extractor') or 'generic').lower()}:{info.get('id', job['url'])}"
            if not self.db.claim(media_key, job_id):
                self.db.update(
                    job_id, state="skipped", error="Already in the library or another active download."
                )
                return
            self._check(job_id)
            self.db.update(job_id, state="downloading", progress=0)
            files = []

            def progress_line(line):
                if line.startswith("SONATA_PROGRESS:"):
                    progress = json.loads(line.partition(":")[2])
                    total = progress.get("total_bytes") or progress.get("total_bytes_estimate") or 0
                    done = progress.get("downloaded_bytes") or 0
                    self.db.update(
                        job_id,
                        progress=min(99.9, done / total * 100) if total else 0,
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

            self._stream(job_id, download_command(self.paths, job["url"], options), progress_line)
            self._check(job_id)
            # Include written metadata, subtitles and thumbnails beside the final media.
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
            self.db.complete(
                job_id,
                media_key,
                title,
                list(dict.fromkeys(files + sidecars)),
                options.folder,
                options.collection,
            )
        except Stopped:
            self.db.update(job_id, state=self.targets.get(job_id, "paused"), speed=0, eta=None)
        except Exception as exc:
            self.db.update(job_id, state="failed", error=str(exc)[-4000:], speed=0, eta=None)
            self.log(job_id, str(exc))
        finally:
            self.db.release(job_id)
            with self.lock:
                self.running.pop(job_id, None)
                self.targets.pop(job_id, None)
            self.notify("changed", job_id)

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
                # Survive pause/retry during a large expansion without duplicating rows.
                if url not in existing:
                    self.db.add(url, options, str(entry.get("title") or url), parent_id=job_id)
                    existing.add(url)
                count += 1

        visit(info)
        return count
