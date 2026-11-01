from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

ACTIVE_STATES = ("queued", "scanning", "resolving", "downloading", "processing")
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
    height: int = 0  # 0 = highest available; otherwise a scanned resolution
    container: str = "mp4"
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
        if not isinstance(self.height, int) or not 0 <= self.height <= 100_000:
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
    height = f"[height={options.height}]" if options.height else ""
    codec = {"any": "", "h264": "[vcodec^=avc1]", "vp9": "[vcodec^=vp9]", "av1": "[vcodec^=av01]"}[
        options.video_codec
    ]
    video = f"bestvideo{height}{codec}"
    # MP4 should use native AAC when offered, at the selected video resolution.
    preferred = (
        f"{video}+bestaudio[acodec^=mp4a]/{video}+bestaudio[acodec^=aac]/"
        if options.container == "mp4"
        else ""
    )
    return preferred + f"{video}+bestaudio/best{height}{codec}"


def scan_summary(info: dict) -> dict:
    """Persist format facts without signed stream URLs or authentication headers."""
    formats = info.get("formats") or [info]
    resolutions = {}
    for fmt in formats:
        if fmt.get("vcodec") == "none" or fmt.get("has_drm") or fmt.get("protocol") == "mhtml":
            continue
        height = fmt.get("height")
        if not isinstance(height, (int, float)) or not 0 < height <= 100_000:
            continue
        height = int(height)
        row = {"height": height, "width": int(fmt.get("width") or 0), "fps": float(fmt.get("fps") or 0)}
        previous = resolutions.get(height)
        if previous is None or (row["width"], row["fps"]) > (previous["width"], previous["fps"]):
            resolutions[height] = row
    return {
        "id": info.get("id"),
        "extractor_key": info.get("extractor_key") or info.get("extractor") or "generic",
        "title": info.get("title"),
        "duration": info.get("duration"),
        "resolutions": [resolutions[h] for h in sorted(resolutions, reverse=True)],
        "has_video": bool(resolutions)
        or any(
            f.get("vcodec") != "none" and f.get("ext") not in ("mp3", "m4a", "opus", "flac", "wav", "ogg")
            for f in formats
        ),
    }
