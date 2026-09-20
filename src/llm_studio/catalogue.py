"""Strict access to the small, versioned instrument catalogue."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from copy import deepcopy
from dataclasses import dataclass, field
from importlib import metadata, resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class CatalogueError(RuntimeError):
    """The catalogue or a requested instrument is not usable as declared."""


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def plain(value: Any) -> Any:
    """Return JSON-compatible data from an immutable catalogue value."""

    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    return value


def _required(mapping: object, fields: set[str], context: str) -> Mapping[str, Any]:
    if not isinstance(mapping, dict):
        raise CatalogueError(f"{context} is not an object")
    missing = fields - mapping.keys()
    if missing:
        raise CatalogueError(f"{context} is missing fields: {sorted(missing)}")
    return mapping


@dataclass(frozen=True)
class Instrument:
    """One validated catalogue entry and its deterministic audition fixture."""

    data: Mapping[str, Any]
    fixture: Mapping[str, Any]
    runtime: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def qualification(self) -> str:
        return str(self.data["qualification"]["status"])


class Catalogue:
    """Loads packaged entries and rejects missing or mismatched dependencies."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        if document.get("schema_version") != 1:
            raise CatalogueError("unsupported instrument catalogue schema")
        entries = document.get("instruments")
        if not isinstance(entries, list) or not entries:
            raise CatalogueError("instrument catalogue has no entries")
        self._entries: dict[str, Mapping[str, Any]] = {}
        for entry in entries:
            self._validate_entry(entry)
            identifier = entry["id"]
            if identifier in self._entries:
                raise CatalogueError(f"duplicate instrument catalogue id: {identifier}")
            self._entries[identifier] = _freeze(deepcopy(entry))

    @classmethod
    def packaged(cls) -> "Catalogue":
        document = json.loads(
            resources.files("llm_studio.catalogue_data").joinpath("catalogue.json").read_text()
        )
        return cls(document)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def get(self, instrument_id: str) -> Instrument:
        try:
            entry = self._entries[instrument_id]
        except KeyError as exc:
            available = ", ".join(self.ids())
            raise CatalogueError(
                f"unknown instrument catalogue id {instrument_id!r}; available: {available}"
            ) from exc
        fixture_name = entry["audition_fixture"]
        fixture_path = resources.files("llm_studio.catalogue_data").joinpath(
            "fixtures", fixture_name
        )
        fixture = json.loads(fixture_path.read_text())
        self._validate_fixture(entry, fixture)
        if fixture.get("instrument_id") != instrument_id:
            raise CatalogueError(f"fixture {fixture_name} targets the wrong instrument")
        if _canonical_hash(fixture) != entry["audition_fixture_sha256"]:
            raise CatalogueError(f"fixture integrity check failed for {instrument_id}")
        return Instrument(entry, _freeze(fixture))

    def check_dependencies(
        self,
        instrument_id: str,
        *,
        executables: Mapping[str, Path] | None = None,
        executable_versions: Mapping[str, str] | None = None,
        distributions: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> Instrument:
        """Return an entry only when its exact runtime dependencies are present.

        Optional maps make the host observations injectable for deterministic
        tests. They do not provide alternate sounds or weaken hash checks.
        """

        instrument = self.get(instrument_id)
        entry = instrument.data
        backend = entry["backend"]
        runtime: dict[str, Any] = {"assets": []}
        executable = backend.get("executable")
        if executable:
            observed = (
                executables.get(executable) if executables is not None else shutil.which(executable)
            )
            if not observed:
                raise CatalogueError(
                    f"{instrument_id} requires {executable} {backend['version']}; "
                    f"install the pinned backend described in {entry['provenance']['reference']}"
                )
            observed_path = Path(observed).resolve()
            if executable_versions is not None:
                observed_build = executable_versions.get(executable, "")
            else:
                try:
                    probe = subprocess.run(
                        [str(observed_path), "-v"],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=5,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise CatalogueError(
                        f"timed out probing {executable} at {observed_path}"
                    ) from exc
                except OSError as exc:
                    raise CatalogueError(
                        f"could not execute {executable} at {observed_path}: {exc}"
                    ) from exc
                if probe.returncode != 0:
                    detail = (probe.stderr or probe.stdout).strip() or "no diagnostic"
                    raise CatalogueError(
                        f"failed probing {executable} at {observed_path}: {detail}"
                    )
                observed_build = probe.stdout.strip()
            version_pattern = rf"(?<![0-9.]){re.escape(backend['version'])}(?![0-9.])"
            build_pattern = rf"(?<![0-9A-Fa-f]){re.escape(backend['build_hash'])}(?![0-9A-Fa-f])"
            if not re.search(version_pattern, observed_build) or not re.search(
                build_pattern, observed_build, re.IGNORECASE
            ):
                raise CatalogueError(
                    f"{instrument_id} requires {executable} {backend['version']} build "
                    f"{backend['build_hash']}; found {observed_build or 'unknown build'}"
                )
            runtime["executable"] = str(observed_path)
            runtime["executable_version"] = observed_build

        distribution = backend.get("python_distribution")
        if distribution:
            required_version = backend.get("python_version", backend["version"])
            try:
                observed_version = (
                    distributions[distribution]
                    if distributions is not None
                    else metadata.version(distribution)
                )
            except (KeyError, metadata.PackageNotFoundError) as exc:
                raise CatalogueError(
                    f"{instrument_id} requires Python distribution "
                    f"{distribution}=={required_version}; install the pinned qualification requirements"
                ) from exc
            if observed_version != required_version:
                raise CatalogueError(
                    f"{instrument_id} requires {distribution}=={required_version}; "
                    f"found {observed_version}"
                )
            runtime["python_distribution_version"] = observed_version

        root = home or Path.home()
        for asset in entry["assets"]:
            path = Path(str(asset["path"]).replace("$HOME", str(root))).resolve()
            if not path.is_file():
                raise CatalogueError(
                    f"{instrument_id} requires {asset['name']} at {path}; "
                    f"{asset['install_hint']}"
                )
            observed_hash = _file_hash(path)
            if observed_hash != asset["sha256"]:
                raise CatalogueError(
                    f"{instrument_id} requires {asset['name']} SHA-256 {asset['sha256']}; "
                    f"found {observed_hash} at {path}"
                )
            runtime["assets"].append(str(path))
        return Instrument(instrument.data, instrument.fixture, _freeze(runtime))

    @staticmethod
    def _validate_entry(entry: object) -> None:
        entry = _required(entry, {
            "id", "name", "role", "backend", "state", "state_sha256", "assets",
            "provenance", "playable_range", "mappings", "audition_fixture",
            "audition_fixture_sha256", "qualification",
        }, "instrument catalogue entry")
        identifier = entry["id"]
        if not isinstance(identifier, str) or not identifier:
            raise CatalogueError("catalogue entry id must be a nonempty string")
        if entry["role"] not in {"drums", "bass", "keys"}:
            raise CatalogueError(f"invalid role for {identifier}")
        backend = _required(
            entry["backend"], {"name", "version", "build_hash", "python_distribution"},
            f"backend for {identifier}",
        )
        if not isinstance(entry["assets"], list):
            raise CatalogueError(f"assets for {identifier} are not a list")
        for asset in entry["assets"]:
            _required(
                asset, {"name", "path", "sha256", "install_hint"},
                f"asset for {identifier}",
            )
        if backend["name"] == "SuperCollider NRT":
            _required(
                backend, {"executable", "python_version"}, f"backend for {identifier}"
            )
            _required(
                entry["state"], {"synthdef", "parameters", "seed"},
                f"state for {identifier}",
            )
        elif backend["name"] == "Pedalboard VST3":
            _required(
                entry["state"], {"kind", "plugin", "raw_state_sha256"},
                f"state for {identifier}",
            )
            if not entry["assets"]:
                raise CatalogueError(f"Pedalboard backend for {identifier} requires an asset")
        else:
            raise CatalogueError(f"unsupported backend for {identifier}: {backend['name']}")
        playable = _required(
            entry["playable_range"], {"midi_min", "midi_max"},
            f"playable range for {identifier}",
        )
        if not 0 <= playable["midi_min"] <= playable["midi_max"] <= 127:
            raise CatalogueError(f"invalid playable range for {identifier}")
        _required(
            entry["mappings"], {"drum_map", "controllers", "keyswitches"},
            f"mappings for {identifier}",
        )
        _required(entry["provenance"], {"reference"}, f"provenance for {identifier}")
        qualification = _required(
            entry["qualification"], {"status", "evidence"},
            f"qualification for {identifier}",
        )
        fixture_name = entry["audition_fixture"]
        if Path(fixture_name).name != fixture_name or not fixture_name.endswith(".json"):
            raise CatalogueError(f"invalid audition fixture path for {identifier}")
        if _canonical_hash(entry["state"]) != entry["state_sha256"]:
            raise CatalogueError(f"state integrity check failed for {identifier}")
        if qualification["status"] not in {"candidate", "qualified"}:
            raise CatalogueError(f"invalid qualification status for {identifier}")

    @staticmethod
    def _validate_fixture(entry: Mapping[str, Any], fixture: object) -> None:
        fixture = _required(
            fixture,
            {"schema_version", "instrument_id", "sample_rate", "start_s", "duration_s", "tail_s", "events"},
            f"fixture for {entry['id']}",
        )
        if fixture["schema_version"] != 1 or fixture["sample_rate"] <= 0:
            raise CatalogueError(f"invalid fixture metadata for {entry['id']}")
        if fixture["start_s"] < 0 or fixture["duration_s"] <= 0 or fixture["tail_s"] < 0:
            raise CatalogueError(f"invalid fixture timing for {entry['id']}")
        if not isinstance(fixture["events"], list) or not fixture["events"]:
            raise CatalogueError(f"fixture for {entry['id']} has no events")
        for event in fixture["events"]:
            event = _required(event, {"at_s"}, f"fixture event for {entry['id']}")
            if event["at_s"] < 0:
                raise CatalogueError(f"fixture for {entry['id']} has a negative event time")
            if ("midi_note" in event) == ("controller" in event):
                raise CatalogueError(f"fixture for {entry['id']} has an ambiguous event")
            if "midi_note" in event:
                _required(
                    event, {"midi_note", "velocity", "duration_s"},
                    f"note event for {entry['id']}",
                )
                if not 0 <= event["midi_note"] <= 127 or not 1 <= event["velocity"] <= 127:
                    raise CatalogueError(f"fixture for {entry['id']} has invalid note data")
                if event["duration_s"] <= 0:
                    raise CatalogueError(f"fixture for {entry['id']} has invalid note duration")
            elif "controller" in event:
                _required(
                    event, {"controller", "value"}, f"controller event for {entry['id']}"
                )
                if not 0 <= event["controller"] <= 127 or not 0 <= event["value"] <= 127:
                    raise CatalogueError(f"fixture for {entry['id']} has invalid controller data")
            else:
                raise CatalogueError(f"fixture for {entry['id']} has an unknown event")
