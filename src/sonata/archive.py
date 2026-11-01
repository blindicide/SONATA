from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
from pathlib import Path

from sonata import __version__


def export_collection(records: list[dict], target: Path, progress=lambda *_: None) -> int:
    """Export only registered files, never a recursive directory traversal."""
    if not records:
        raise ValueError("This collection is empty.")
    if not (target.name.endswith(".tar") or target.name.endswith(".tar.gz")):
        raise ValueError("Choose a .tar or .tar.gz filename.")
    target = target.resolve()
    members = {}
    items = []
    for record in records:
        root = Path(record["folder"]).resolve()
        item = {key: record[key] for key in ("media_key", "title", "url", "collection", "completed", "size")}
        item["files"] = []
        prefix = hashlib.sha256(record["media_key"].encode("utf-8")).hexdigest()[:16]
        for filename in json.loads(record["files"]):
            path = Path(filename)
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                raise ValueError(f"Missing or unsafe collection file: {path.name}")
            if path.resolve() == target:
                raise ValueError("The archive cannot replace a source file.")
            name = f"media/{prefix}/{path.relative_to(root).as_posix()}"
            if name in members and members[name] != path:
                raise ValueError("Two files have the same archive name.")
            members[name] = path
            item["files"].append(name)
        items.append(item)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".sonata-export-", dir=target.parent)
    os.close(handle)
    manifest = {"application": "SONATA", "version": __version__, "items": items, "sha256": {}}
    try:
        with tarfile.open(
            temporary, "w:gz" if target.name.endswith(".gz") else "w", format=tarfile.PAX_FORMAT
        ) as archive:
            for index, (name, path) in enumerate(members.items(), 1):
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        digest.update(block)
                    stream.seek(0)
                    info = archive.gettarinfo(str(path), arcname=name)
                    if not info.isfile():
                        raise ValueError("Archives contain regular files only.")
                    archive.addfile(info, stream)
                manifest["sha256"][name] = digest.hexdigest()
                progress(index, len(members))
            payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            info = tarfile.TarInfo("manifest.json")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return len(members)
