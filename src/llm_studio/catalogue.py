"""Strict access to the small, versioned instrument catalogue."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from importlib import metadata, resources
from pathlib import Path
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


@dataclass(frozen=True)
class Instrument:
    """One validated catalogue entry and its deterministic audition fixture."""

    data: Mapping[str, Any]
    fixture: Mapping[str, Any]

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
            self._entries[identifier] = entry

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
        if fixture.get("instrument_id") != instrument_id:
            raise CatalogueError(f"fixture {fixture_name} targets the wrong instrument")
        if _canonical_hash(fixture) != entry["audition_fixture_sha256"]:
            raise CatalogueError(f"fixture integrity check failed for {instrument_id}")
        return Instrument(entry, fixture)

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
            observed_build = (
                executable_versions.get(executable, "")
                if executable_versions is not None
                else subprocess.run(
                    [str(observed), "-v"], capture_output=True, text=True, check=False
                ).stdout.strip()
            )
            expected_parts = (backend["version"], backend["build_hash"])
            if not all(part in observed_build for part in expected_parts):
                raise CatalogueError(
                    f"{instrument_id} requires {executable} {backend['version']} build "
                    f"{backend['build_hash']}; found {observed_build or 'unknown build'}"
                )

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
        return instrument

    @staticmethod
    def _validate_entry(entry: object) -> None:
        if not isinstance(entry, dict):
            raise CatalogueError("instrument catalogue entry is not an object")
        required = {
            "id", "name", "role", "backend", "state", "state_sha256", "assets",
            "provenance", "playable_range", "mappings", "audition_fixture",
            "audition_fixture_sha256", "qualification",
        }
        missing = required - entry.keys()
        if missing:
            raise CatalogueError(f"catalogue entry is missing fields: {sorted(missing)}")
        if _canonical_hash(entry["state"]) != entry["state_sha256"]:
            raise CatalogueError(f"state integrity check failed for {entry['id']}")
        if entry["qualification"]["status"] not in {"candidate", "qualified"}:
            raise CatalogueError(f"invalid qualification status for {entry['id']}")
