import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from sonata.engine import spawn_options
from sonata.media import MediaRunner, MediaTask, execute_task, finish_download_mp4, inspect_media
from sonata.paths import AppPaths


def test_processing_never_uses_input_as_output(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    with pytest.raises(ValueError, match="different"):
        MediaTask(str(source), str(source)).validate()
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        MediaTask(str(source), str(output)).validate()
    assert source.read_bytes() == b"original"
    assert output.read_bytes() == b"existing"


@pytest.fixture
def media_sample(tmp_path):
    if os.environ.get("SONATA_INTEGRATION") != "1":
        pytest.skip("requires bundled media tools")
    paths = AppPaths(tmp_path / "profile", Path(__file__).resolve().parents[1] / "vendor")
    source = tmp_path / "Тест recording.mkv"
    subprocess.run(
        [
            str(paths.tool("ffmpeg")),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=352x262:r=30000/1001",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "libopus",
            "-metadata",
            "title=Название",
            "-metadata",
            "artist=SONATA",
            "-metadata",
            "genre=Music",
            "-metadata",
            "comment=https://example.org/test",
            "-metadata",
            "description=Сохранённое описание",
            str(source),
        ],
        check=True,
        timeout=30,
        **spawn_options(),
    )
    return paths, source


def tags(info):
    return {key.lower(): value for key, value in info["format"].get("tags", {}).items()}


def test_mp4_preserves_metadata_and_technical_fields(media_sample, tmp_path):
    paths, source = media_sample
    original_hash = hashlib.file_digest(source.open("rb"), "sha256").hexdigest()
    runner = MediaRunner()
    output = tmp_path / "converted.mp4"
    info = execute_task(paths, MediaTask(str(source), str(output), audio_codec="aac"), runner.run)
    assert hashlib.file_digest(source.open("rb"), "sha256").hexdigest() == original_hash
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"], video["codec_name"]) == (352, 262, "h264")
    assert audio["codec_name"] == "aac"
    assert int(audio["sample_rate"]) == 48000
    assert tags(info)["title"] == "Название"
    assert tags(info)["artist"] == "SONATA"
    assert tags(info)["genre"] == "Music"
    assert tags(info)["description"] == "Сохранённое описание"
    assert tags(info)["comment"] == "https://example.org/test"
    assert abs(float(info["format"]["duration"]) - 3) < 0.2


def test_download_mp4_finalizer_converts_opus_without_reencoding_video(media_sample, tmp_path):
    paths, source = media_sample
    file = tmp_path / "download.mp4"
    runner = MediaRunner()
    execute_task(paths, MediaTask(str(source), str(file), operation="remux"), runner.run)
    assert any(s.get("codec_name") == "opus" for s in inspect_media(paths, file)["streams"])
    finish_download_mp4(paths, file, runner.run)
    info = inspect_media(paths, file)
    assert next(s for s in info["streams"] if s["codec_type"] == "audio")["codec_name"] == "aac"
    assert next(s for s in info["streams"] if s["codec_type"] == "video")["codec_name"] == "h264"
    assert tags(info)["title"] == "Название"


def test_audio_thumbnail_trim_and_metadata_tools(media_sample, tmp_path):
    paths, source = media_sample
    runner = MediaRunner()
    audio = tmp_path / "audio.mp3"
    info = execute_task(
        paths, MediaTask(str(source), str(audio), operation="audio", audio_codec="mp3"), runner.run
    )
    assert {s["codec_type"] for s in info["streams"]} == {"audio"}
    assert tags(info)["title"] == "Название"
    image = tmp_path / "thumbnail.jpg"
    info = execute_task(
        paths, MediaTask(str(source), str(image), operation="thumbnail", start=0.5), runner.run
    )
    assert image.stat().st_size > 100
    assert info["streams"][0]["width"] == 352
    trimmed = tmp_path / "trimmed.mkv"
    info = execute_task(
        paths,
        MediaTask(
            str(source), str(trimmed), operation="trim", video_codec="h264", audio_codec="aac", end=1.5
        ),
        runner.run,
    )
    assert abs(float(info["format"]["duration"]) - 1.5) < 0.2
    edited = tmp_path / "edited.mkv"
    info = execute_task(
        paths,
        MediaTask(str(source), str(edited), operation="metadata", metadata={"title": "Новое название"}),
        runner.run,
    )
    assert tags(info)["title"] == "Новое название"
    assert tags(info)["artist"] == "SONATA"


def test_embed_and_extract_subtitles(media_sample, tmp_path):
    paths, source = media_sample
    subtitle = tmp_path / "captions.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nПривет, SONATA\n", encoding="utf-8")
    runner = MediaRunner()
    output = tmp_path / "subtitled.mkv"
    info = execute_task(
        paths,
        MediaTask(
            str(source),
            str(output),
            operation="embed_subtitle",
            subtitle=str(subtitle),
            subtitle_language="rus",
        ),
        runner.run,
    )
    assert any(s.get("codec_type") == "subtitle" for s in info["streams"])
    extracted = tmp_path / "extracted.srt"
    execute_task(paths, MediaTask(str(output), str(extracted), operation="extract_subtitle"), runner.run)
    assert "Привет, SONATA" in extracted.read_text(encoding="utf-8")


def test_failed_processing_keeps_original_and_removes_temporary_output(media_sample, tmp_path):
    paths, source = media_sample
    before = source.read_bytes()
    output = tmp_path / "failed.mp4"
    with pytest.raises(RuntimeError):
        execute_task(
            paths,
            MediaTask(
                str(source),
                str(output),
                operation="advanced",
                extra_args=["-c:v", "encoder_that_does_not_exist"],
            ),
            MediaRunner().run,
        )
    assert source.read_bytes() == before
    assert not output.exists()
    assert not list(tmp_path.glob(".sonata-process-*"))
