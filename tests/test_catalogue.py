from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from importlib import resources
from pathlib import Path

import pytest

from llm_studio.catalogue import Catalogue, CatalogueError


def packaged_document() -> dict:
    path = resources.files("llm_studio.catalogue_data").joinpath("catalogue.json")
    return json.loads(path.read_text())


def test_packaged_catalogue_exposes_exact_three_roles_and_fixtures() -> None:
    catalogue = Catalogue.packaged()

    instruments = [catalogue.get(identifier) for identifier in catalogue.ids()]

    assert {instrument.data["role"] for instrument in instruments} == {"drums", "bass", "keys"}
    assert len(instruments) == 3
    assert all(instrument.fixture["events"] for instrument in instruments)
    assert all(instrument.qualification == "qualified" for instrument in instruments)
    assert all(instrument.data["qualification"]["evidence"] for instrument in instruments)
    assert all(instrument.data["parameters"] for instrument in instruments)
    assert all(
        instrument.data["render"]["sample_rates"] == (48000,)
        for instrument in instruments
    )


def test_unknown_id_does_not_substitute_another_sound() -> None:
    with pytest.raises(CatalogueError, match="unknown instrument.*available"):
        Catalogue.packaged().get("studio.bass.missing")


def test_tampered_state_is_rejected_when_catalogue_loads() -> None:
    document = copy.deepcopy(packaged_document())
    document["instruments"][0]["state"]["parameters"]["level"] = 0.9

    with pytest.raises(CatalogueError, match="state integrity check failed"):
        Catalogue(document)


def test_backend_specific_fields_are_required() -> None:
    document = copy.deepcopy(packaged_document())
    document["instruments"][0]["backend"].pop("executable")

    with pytest.raises(CatalogueError, match="backend.*missing fields.*executable"):
        Catalogue(document)


def test_parameter_metadata_and_render_contract_are_required() -> None:
    document = copy.deepcopy(packaged_document())
    document["instruments"][0].pop("parameters")

    with pytest.raises(CatalogueError, match="missing fields.*parameters"):
        Catalogue(document)


def test_packaged_dexed_state_is_content_addressed() -> None:
    instrument = Catalogue.packaged().get("studio.keys.dexed-factory-v1")

    state = instrument.restored_state()

    assert hashlib.sha256(state).hexdigest() == instrument.data["state"]["raw_state_sha256"]


def test_returned_catalogue_state_is_deeply_immutable() -> None:
    instrument = Catalogue.packaged().get("studio.drums.sc-basic-v1")

    with pytest.raises(TypeError):
        instrument.data["state"]["seed"] = 99


def test_missing_backend_has_actionable_exact_error() -> None:
    with pytest.raises(CatalogueError) as caught:
        Catalogue.packaged().check_dependencies(
            "studio.bass.sc-pulse-v1", executables={}
        )

    message = str(caught.value)
    assert "scsynth 3.14.1" in message
    assert "docs/qualification/instrument-catalogue.md" in message


def test_wrong_native_backend_build_is_rejected() -> None:
    with pytest.raises(CatalogueError, match="3.14.1 build 426edf6; found scsynth 3.14.0"):
        Catalogue.packaged().check_dependencies(
            "studio.bass.sc-pulse-v1",
            executables={"scsynth": Path("/test/scsynth")},
            executable_versions={"scsynth": "scsynth 3.14.0"},
        )


def test_native_version_prefix_collision_is_rejected() -> None:
    with pytest.raises(CatalogueError, match="found scsynth 3.14.10 build 426edf6"):
        Catalogue.packaged().check_dependencies(
            "studio.bass.sc-pulse-v1",
            executables={"scsynth": Path("/test/scsynth")},
            executable_versions={"scsynth": "scsynth 3.14.10 build 426edf6"},
        )


def test_validated_native_executable_and_observation_are_retained() -> None:
    instrument = Catalogue.packaged().check_dependencies(
        "studio.bass.sc-pulse-v1",
        executables={"scsynth": Path("/test/scsynth")},
        executable_versions={"scsynth": "scsynth 3.14.1 build 426edf6"},
        distributions={"supriya": "26.9b0"},
    )

    assert instrument.runtime["executable"] == "/test/scsynth"
    assert instrument.runtime["executable_version"] == "scsynth 3.14.1 build 426edf6"


def test_native_probe_nonzero_exit_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "llm_studio.catalogue.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 2, stdout="", stderr="broken"),
    )

    with pytest.raises(CatalogueError, match="failed probing.*broken"):
        Catalogue.packaged().check_dependencies(
            "studio.bass.sc-pulse-v1",
            executables={"scsynth": Path("/test/scsynth")},
        )


def test_native_probe_timeout_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr("llm_studio.catalogue.subprocess.run", time_out)

    with pytest.raises(CatalogueError, match="timed out probing scsynth"):
        Catalogue.packaged().check_dependencies(
            "studio.bass.sc-pulse-v1",
            executables={"scsynth": Path("/test/scsynth")},
        )


def test_wrong_python_backend_version_is_rejected_before_plugin_lookup() -> None:
    with pytest.raises(CatalogueError, match="pedalboard==0.9.24; found 0.9.25"):
        Catalogue.packaged().check_dependencies(
            "studio.keys.dexed-factory-v1",
            distributions={"pedalboard": "0.9.25"},
        )


def test_missing_plugin_names_expected_path_and_install_action(tmp_path) -> None:
    with pytest.raises(CatalogueError) as caught:
        Catalogue.packaged().check_dependencies(
            "studio.keys.dexed-factory-v1",
            distributions={"pedalboard": "0.9.24"},
            home=tmp_path,
        )

    message = str(caught.value)
    assert "Dexed.vst3/Contents/MacOS/Dexed" in message
    assert "install Dexed VST3 1.0.1" in message


def test_wrong_plugin_binary_is_rejected_without_fallback(tmp_path) -> None:
    binary = tmp_path / "Library/Audio/Plug-Ins/VST3/Dexed.vst3/Contents/MacOS/Dexed"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"not dexed")

    with pytest.raises(CatalogueError) as caught:
        Catalogue.packaged().check_dependencies(
            "studio.keys.dexed-factory-v1",
            distributions={"pedalboard": "0.9.24"},
            home=tmp_path,
        )

    assert hashlib.sha256(b"not dexed").hexdigest() in str(caught.value)
    assert "requires Dexed VST3 executable SHA-256" in str(caught.value)
