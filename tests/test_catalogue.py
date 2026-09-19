from __future__ import annotations

import copy
import hashlib
import json
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
    assert all(instrument.qualification == "candidate" for instrument in instruments)


def test_unknown_id_does_not_substitute_another_sound() -> None:
    with pytest.raises(CatalogueError, match="unknown instrument.*available"):
        Catalogue.packaged().get("studio.bass.missing")


def test_tampered_state_is_rejected_when_catalogue_loads() -> None:
    document = copy.deepcopy(packaged_document())
    document["instruments"][0]["state"]["parameters"]["level"] = 0.9

    with pytest.raises(CatalogueError, match="state integrity check failed"):
        Catalogue(document)


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
