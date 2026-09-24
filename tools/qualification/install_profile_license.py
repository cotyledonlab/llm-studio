#!/usr/bin/env python3
"""Copy an installed REAPER license into a stopped disposable profile.

This helper never accepts license contents, invokes REAPER, or logs file data.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys

from llm_studio.bootstrap import ISOLATED_PROFILE_ROOT, UnsafeBootstrap, isolated_profile_running


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise UnsafeBootstrap(f"path contains symlink: {current}")


def _check_private_directory(path: Path, *, label: str) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise UnsafeBootstrap(f"{label} must be a directory owned by the current user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise UnsafeBootstrap(f"{label} must have mode 0700")


def install_license(source: Path, resource: Path, *, allowed_root: Path = ISOLATED_PROFILE_ROOT,
                    running_guard=isolated_profile_running) -> Path:
    """Install source bytes as resource/reaper-license.rk after strict checks."""
    source = Path(os.path.abspath(source))
    resource = Path(os.path.abspath(resource))
    allowed_root = Path(os.path.abspath(allowed_root))
    _reject_symlink_components(source)
    _reject_symlink_components(resource)

    try:
        resource.relative_to(allowed_root)
    except ValueError as exc:
        raise UnsafeBootstrap(f"resource must be under {allowed_root}") from exc
    if resource == allowed_root:
        raise UnsafeBootstrap("resource must be below the isolated profile root")
    if allowed_root.is_symlink() or allowed_root.resolve() != allowed_root:
        raise UnsafeBootstrap("isolated profile root must be canonical and not a symlink")

    source_info = source.lstat()
    if not stat.S_ISREG(source_info.st_mode) or source_info.st_uid != os.geteuid():
        raise UnsafeBootstrap("source must be a regular file owned by the current user")
    if stat.S_IMODE(source_info.st_mode) != 0o600:
        raise UnsafeBootstrap("source license must have mode 0600")
    _check_private_directory(source.parent, label="source parent")

    if not resource.is_dir() or resource.resolve() != resource:
        raise UnsafeBootstrap("resource must be an existing canonical directory")
    try:
        relative_parts = resource.relative_to(allowed_root).parts
    except ValueError as exc:
        raise UnsafeBootstrap(f"resource must be under {allowed_root}") from exc
    if len(relative_parts) < 2:
        raise UnsafeBootstrap("resource must have a private profile parent under the isolated root")
    profile_dirs = []
    parent = resource.parent
    while parent != allowed_root:
        profile_dirs.append(parent)
        parent = parent.parent
    if parent != allowed_root:
        raise UnsafeBootstrap("resource must be under the isolated profile root")
    for directory in reversed(profile_dirs):
        _check_private_directory(directory, label="profile parent")
    _check_private_directory(resource, label="resource")

    target = resource / "reaper-license.rk"
    if target.is_symlink() or target.exists():
        raise UnsafeBootstrap("destination license must be absent and not a symlink")
    if running_guard(resource):
        raise UnsafeBootstrap("REAPER is running with this isolated resource")

    # Open source without following a last-moment symlink replacement; verify
    # the opened inode still meets the owner/mode/type requirements.
    source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    destination_fd = -1
    destination_created = False
    try:
        opened_source = os.fstat(source_fd)
        if (not stat.S_ISREG(opened_source.st_mode) or opened_source.st_uid != os.geteuid()
                or stat.S_IMODE(opened_source.st_mode) != 0o600):
            raise UnsafeBootstrap("opened source no longer meets owner/mode/type requirements")
        destination_fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        destination_created = True
        while True:
            chunk = os.read(source_fd, 65536)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                view = view[written:]
        os.fchmod(destination_fd, 0o600)
    except Exception:
        if destination_fd >= 0:
            os.close(destination_fd)
            destination_fd = -1
        if destination_created:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(source_fd)
        if destination_fd >= 0:
            os.close(destination_fd)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="protected existing reaper-license.rk (mode 0600)")
    parser.add_argument("--resource", required=True, type=Path, help="stopped disposable profile resource directory")
    args = parser.parse_args(argv)
    try:
        target = install_license(args.source, args.resource)
    except (OSError, UnsafeBootstrap) as exc:
        print(f"license setup refused: {exc}", file=sys.stderr)
        return 2
    print(f"Installed license file: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
