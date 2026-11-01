from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

ACTIVE_STATES = ("queued", "resolving", "downloading", "processing")
TERMINAL_STATES = ("completed", "failed", "cancelled", "skipped", "expanded")
DEFAULT_TEMPLATE = "%(title).180B [%(id)s].%(ext)s"


def validate_url(value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Enter an HTTP or HTTPS media URL without credentials.")
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("A URL cannot contain whitespace or control characters.")
    return value


def validate_template(value: str) -> str:
    # Only basenames: user-controlled folders belong in Destination / Collection.
    if not value or any(c in value for c in ("/", "\\", "\x00", "\n", "\r", ":")):
        raise ValueError("The filename template must be a basename, without folders or colons.")
    if value in (".", "..") or "%(ext)s" not in value or "%(id)s" not in value:
        raise ValueError("The filename template must include %(id)s and %(ext)s to avoid collisions.")
    remainder = re.sub(r"%\([A-Za-z0-9_.,|+> -]+\)[0-9.]*[A-Za-z]", "", value.replace("%%", ""))
    if "%" in remainder:
        raise ValueError("Invalid yt-dlp filename template.")
    return value


def validate_collection(value: str) -> str:
    value = value.strip()
    if value and (
        value in (".", "..") or re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value.endswith((".", " "))
    ):
        raise ValueError("Use a single folder name for the collection.")
    if value and PureWindowsPath(value).is_reserved():
        raise ValueError("This collection name is reserved on Windows.")
    return value


@dataclass(frozen=True)
class DownloadOptions:
    destination: str
    collection: str = ""
    mode: str = "video"
    height: int = 1080  # 0 = best available
    container: str = "mkv"
    video_codec: str = "any"
    audio_codec: str = "mp3"
    subtitles: bool = False
    automatic_subtitles: bool = False
    subtitle_languages: str = "en,ru"
    metadata: bool = True
    thumbnail: bool = False
    playlist: bool = True
    template: str = DEFAULT_TEMPLATE
    rate_kib: int = 0
    retries: int = 5

    def validate(self) -> DownloadOptions:
        if not self.destination or not Path(self.destination).is_absolute():
            raise ValueError("Choose an absolute download destination.")
        validate_collection(self.collection)
        validate_template(self.template)
        if self.mode not in ("video", "audio"):
            raise ValueError("Unknown download mode.")
        if self.height not in (0, 4320, 2160, 1440, 1080, 720, 480, 360):
            raise ValueError("Unknown resolution.")
        if self.container not in ("mkv", "mp4", "webm") or self.video_codec not in (
            "any",
            "h264",
            "vp9",
            "av1",
        ):
            raise ValueError("Unknown video format.")
        if self.audio_codec not in ("mp3", "m4a", "opus", "flac", "wav", "best"):
            raise ValueError("Unknown audio format.")
        if not 0 <= self.rate_kib <= 1_000_000 or not 0 <= self.retries <= 50:
            raise ValueError("Rate or retry count is out of range.")
        if not re.fullmatch(r"[A-Za-z0-9_.*,-]+", self.subtitle_languages):
            raise ValueError("Use comma-separated subtitle language codes.")
        return self

    @property
    def folder(self) -> Path:
        return (
            Path(self.destination) / self.collection.strip()
            if self.collection.strip()
            else Path(self.destination)
        )

    def to_dict(self) -> dict:
        return asdict(self)


def format_selector(options: DownloadOptions) -> str:
    if options.mode == "audio":
        return "bestaudio/best"
    height = f"[height<=?{options.height}]" if options.height else ""
    codec = {"any": "", "h264": "[vcodec^=avc1]", "vp9": "[vcodec^=vp9]", "av1": "[vcodec^=av01]"}[
        options.video_codec
    ]
    # Keep the resolution / codec constraint on *every* fallback.
    return f"bestvideo{height}{codec}+bestaudio/best{height}{codec}"
