from __future__ import annotations

from pathlib import Path
import stat

import pytest

from llm_studio.bootstrap import UnsafeBootstrap
from tools.qualification.install_profile_license import install_license


def setup_case(tmp_path: Path):
    allowed = tmp_path / "llm-studio-reaper"
    profile = allowed / "profile"
    resource = profile / "resource"
    resource.mkdir(parents=True, mode=0o700)
    profile.chmod(0o700)
    resource.chmod(0o700)
    source_dir = tmp_path / "license-source"
    source_dir.mkdir(mode=0o700)
    source = source_dir / "source.rk"
    source.write_bytes(b"synthetic fixture only")
    source.chmod(0o600)
    calls = []

    def guard(path):
        calls.append(path)
        return False

    return allowed, profile, resource, source, calls, guard


def test_installs_exclusively_with_private_mode_and_guard(tmp_path):
    allowed, _, resource, source, calls, guard = setup_case(tmp_path)
    target = install_license(source, resource, allowed_root=allowed, running_guard=guard)
    assert calls == [resource]
    assert target.read_bytes() == b"synthetic fixture only"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_refuses_live_resource_before_creating_target(tmp_path):
    allowed, _, resource, source, calls, _ = setup_case(tmp_path)
    with pytest.raises(UnsafeBootstrap, match="REAPER is running"):
        install_license(source, resource, allowed_root=allowed, running_guard=lambda path: True)
    assert calls == []
    assert not (resource / "reaper-license.rk").exists()


@pytest.mark.parametrize("bad_mode", [0o644, 0o400])
def test_requires_source_mode_0600(tmp_path, bad_mode):
    allowed, _, resource, source, _, guard = setup_case(tmp_path)
    source.chmod(bad_mode)
    with pytest.raises(UnsafeBootstrap, match="mode 0600"):
        install_license(source, resource, allowed_root=allowed, running_guard=guard)


def test_refuses_existing_or_symlink_destination(tmp_path):
    allowed, _, resource, source, _, guard = setup_case(tmp_path)
    target = resource / "reaper-license.rk"
    target.write_bytes(b"keep")
    with pytest.raises(UnsafeBootstrap, match="must be absent"):
        install_license(source, resource, allowed_root=allowed, running_guard=guard)
    assert target.read_bytes() == b"keep"


def test_refuses_symlink_destination_without_touching_target(tmp_path):
    allowed, _, resource, source, _, guard = setup_case(tmp_path)
    other = resource / "keep.rk"
    other.write_bytes(b"keep")
    target = resource / "reaper-license.rk"
    target.symlink_to(other)
    with pytest.raises(UnsafeBootstrap, match="must be absent"):
        install_license(source, resource, allowed_root=allowed, running_guard=guard)
    assert target.is_symlink()
    assert other.read_bytes() == b"keep"


def test_refuses_symlink_component_in_source_path(tmp_path):
    allowed, _, resource, source, _, guard = setup_case(tmp_path)
    alias = tmp_path / "source-alias"
    alias.symlink_to(source.parent, target_is_directory=True)
    with pytest.raises(UnsafeBootstrap, match="path contains symlink"):
        install_license(alias / source.name, resource, allowed_root=allowed, running_guard=guard)


def test_refuses_non_private_source_parent(tmp_path):
    allowed, _, resource, source, _, guard = setup_case(tmp_path)
    source.parent.chmod(0o755)
    with pytest.raises(UnsafeBootstrap, match="source parent.*mode 0700"):
        install_license(source, resource, allowed_root=allowed, running_guard=guard)


def test_refuses_non_private_resource_parent(tmp_path):
    allowed, profile, resource, source, _, guard = setup_case(tmp_path)
    profile.chmod(0o755)
    with pytest.raises(UnsafeBootstrap, match="mode 0700"):
        install_license(source, resource, allowed_root=allowed, running_guard=guard)


def test_refuses_resource_outside_allowed_root(tmp_path):
    allowed, _, _, source, _, guard = setup_case(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    with pytest.raises(UnsafeBootstrap, match="under"):
        install_license(source, outside, allowed_root=allowed, running_guard=guard)
