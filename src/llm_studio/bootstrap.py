"""Safe, reviewable bootstrap for the pinned REAPER controller.

This module only prepares REAPER's local support files.  It never launches
REAPER, sends bridge commands, or automates its UI.  A plan captures every
precondition; apply refuses a running REAPER and rollback refuses to overwrite
files changed after apply.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PINNED_CONTROLLER_COMMIT = "fd56d0008ffa5fba25cc58a70e5ae632c80b4c16"
OSC_AGENT_LINE = 'OSC "Agent" 3 8000 "127.0.0.1" 9000 1024 10 "Agent"'


class BootstrapError(RuntimeError):
    """A bootstrap precondition or safety check failed."""


class UnsafeBootstrap(BootstrapError):
    """A requested write is unsafe and was not attempted."""


class RollbackRefused(BootstrapError):
    """Rollback would overwrite a file that changed after apply."""


@dataclass(frozen=True)
class PlannedFile:
    relative_path: str
    content: bytes
    source_hash: str
    before_hash: str | None
    reason: str

    @property
    def after_hash(self) -> str:
        return _sha256(self.content)


@dataclass(frozen=True)
class BootstrapPlan:
    resource_path: Path
    controller_path: Path
    controller_commit: str
    files: tuple[PlannedFile, ...]
    created_dirs: tuple[str, ...]
    producer_handoff: tuple[str, ...]


@dataclass(frozen=True)
class BootstrapResult:
    plan: BootstrapPlan
    backup_dir: Path | None
    changed: tuple[str, ...]
    unchanged: tuple[str, ...]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_hash(path: Path) -> str | None:
    return _sha256(path.read_bytes()) if path.exists() else None


def _controller_identity(controller_path: Path) -> str:
    """Require the approved commit *and* a clean controller worktree."""
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(controller_path), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(controller_path), "status", "--porcelain"], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BootstrapError(f"controller checkout cannot be verified: {exc}") from exc
    if commit != PINNED_CONTROLLER_COMMIT:
        raise BootstrapError(
            f"controller commit is {commit or 'unknown'}, expected {PINNED_CONTROLLER_COMMIT}"
        )
    if dirty:
        raise BootstrapError("controller checkout is dirty; refusing unpinned resource content")
    return commit


def _safe_target(resource_path: Path, relative_path: str) -> Path:
    """Resolve a managed target without following a symlink outside resource."""
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise UnsafeBootstrap(f"unsafe managed path: {relative_path!r}")
    if resource_path.is_symlink() or not resource_path.is_dir():
        raise UnsafeBootstrap(f"resource directory is unavailable or a symlink: {resource_path}")
    resource = resource_path.resolve()
    current = resource
    for part in Path(relative_path).parts:
        current = current / part
        if current.is_symlink():
            raise UnsafeBootstrap(f"managed path contains symlink: {current}")
    target = resource / relative_path
    if os.path.commonpath((str(resource), str(target.parent.resolve()))) != str(resource):
        raise UnsafeBootstrap(f"managed path escapes resource directory: {relative_path}")
    return target


def _read_source(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise BootstrapError(f"approved controller resource is missing or unsafe: {path}")
    return path.read_bytes()


def _agent_ini(current: bytes) -> bytes:
    """Add exactly one Agent OSC surface while retaining every other line."""
    text = current.decode("utf-8", errors="strict")
    lines = text.splitlines(keepends=True)
    section_start = next((i for i, line in enumerate(lines) if line.strip().lower() == "[reaper]"), None)
    if section_start is None:
        newline = "\r\n" if "\r\n" in text else "\n"
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        lines.extend([f"[REAPER]{newline}"])
        section_start = len(lines) - 1
    section_end = next(
        (i for i in range(section_start + 1, len(lines)) if re.match(r"\s*\[[^]]+\]", lines[i])),
        len(lines),
    )
    scope = lines[section_start + 1 : section_end]
    for line in scope:
        if line.startswith("csurf_") and line.rstrip().endswith('"Agent"') and "OSC" in line:
            if line.rstrip().split("=", 1)[-1] != OSC_AGENT_LINE:
                raise BootstrapError("existing Agent OSC configuration differs from the approved loopback ports")
            return current
    used: list[int] = []
    count_index: int | None = None
    count_value = 0
    for index, line in enumerate(scope):
        match = re.match(r"csurf_(\d+)=", line)
        if match:
            used.append(int(match.group(1)))
        match = re.match(r"csurf_cnt=(\d+)", line)
        if match:
            count_index, count_value = section_start + 1 + index, int(match.group(1))
    slot = max(used, default=-1) + 1
    newline = "\r\n" if "\r\n" in text else "\n"
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    lines.insert(section_end, f"csurf_{slot}={OSC_AGENT_LINE}{newline}")
    new_count = max(count_value, slot + 1)
    if count_index is None:
        lines.insert(section_end + 1, f"csurf_cnt={new_count}{newline}")
    else:
        ending = "\r\n" if lines[count_index].endswith("\r\n") else "\n"
        lines[count_index] = f"csurf_cnt={new_count}{ending}"
    return "".join(lines).encode("utf-8")


def _apply_unified_patch(original: bytes, patch: bytes) -> bytes:
    """Apply a conventional unified diff, rejecting fuzzy or malformed hunks."""
    old = original.decode("utf-8").splitlines(keepends=True)
    patch_lines = patch.decode("utf-8").splitlines(keepends=True)
    hunks = [i for i, line in enumerate(patch_lines) if line.startswith("@@ ")]
    if not hunks:
        raise BootstrapError("controller hook patch has no unified-diff hunk")
    output: list[str] = []
    cursor = 0
    for hunk_pos, start in enumerate(hunks):
        match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", patch_lines[start])
        if not match:
            raise BootstrapError("malformed controller hook hunk")
        old_start = int(match.group(1)) - 1
        if old_start < cursor or old_start > len(old):
            raise BootstrapError("controller hook hunk is out of range")
        output.extend(old[cursor:old_start])
        cursor = old_start
        end = hunks[hunk_pos + 1] if hunk_pos + 1 < len(hunks) else len(patch_lines)
        for line in patch_lines[start + 1 : end]:
            if line.startswith("\\ No newline"):
                continue
            if not line or line[0] not in " +-":
                raise BootstrapError("malformed controller hook patch line")
            value = line[1:]
            if line[0] == " ":
                if cursor >= len(old) or old[cursor] != value:
                    raise BootstrapError("controller hook patch does not match pinned bridge")
                output.append(value)
                cursor += 1
            elif line[0] == "-":
                if cursor >= len(old) or old[cursor] != value:
                    raise BootstrapError("controller hook patch does not match pinned bridge")
                cursor += 1
            else:
                output.append(value)
    output.extend(old[cursor:])
    return "".join(output).encode("utf-8")


def plan_bootstrap(resource_path: Path, controller_path: Path, project_path: Path | None = None) -> BootstrapPlan:
    """Build a side-effect-free plan for the approved controller resources."""
    resource_path = Path(resource_path)
    controller_path = Path(controller_path)
    commit = _controller_identity(controller_path)
    if not resource_path.is_dir() or resource_path.is_symlink():
        raise UnsafeBootstrap(f"resource directory is unavailable or a symlink: {resource_path}")
    project_path = Path(project_path) if project_path else Path(__file__).resolve().parents[2]
    bridge = _read_source(controller_path / "bridge" / "agent_bridge.lua")
    osc = _read_source(controller_path / "osc" / "Agent.ReaperOSC")
    managed: list[tuple[str, bytes, str]] = [
        ("Scripts/agent_bridge.lua", bridge, "pinned controller bridge"),
        ("OSC/Agent.ReaperOSC", osc, "pinned controller OSC surface"),
    ]
    handler = project_path / "adapters/reaper/studio_handler.lua"
    hook = project_path / "adapters/reaper/controller-studio-hook.patch"
    if handler.exists() or hook.exists():
        if not handler.exists() or not hook.exists():
            raise BootstrapError("studio bridge extension is incomplete (handler and hook are both required)")
        handler_bytes = _read_source(handler)
        hook_bytes = _read_source(hook)
        managed[0] = (
            "Scripts/agent_bridge.lua",
            _apply_unified_patch(bridge, hook_bytes),
            "pinned controller bridge with exact studio hook",
        )
        managed.append(("Scripts/llm_studio_reaper.lua", handler_bytes, "studio bridge handler"))
    ini_path = _safe_target(resource_path, "reaper.ini")
    ini = ini_path.read_bytes() if ini_path.exists() else b""
    updated_ini = _agent_ini(ini)
    if updated_ini != ini:
        managed.append(("reaper.ini", updated_ini, "Agent OSC control-surface configuration"))
    files: list[PlannedFile] = []
    for relative, content, reason in managed:
        target = _safe_target(resource_path, relative)
        files.append(PlannedFile(relative, content, _sha256(content), _file_hash(target), reason))
    return BootstrapPlan(
        resource_path=resource_path.resolve(),
        controller_path=controller_path.resolve(),
        controller_commit=commit,
        files=tuple(files),
        created_dirs=("AgentBridge/in", "AgentBridge/out", "AgentBridge/log", "AgentBridge/midi-in", "AgentBridge/midi-out"),
        producer_handoff=(
            "With REAPER stopped, review this plan and apply it.",
            "Start REAPER and load/reload Scripts/agent_bridge.lua from the Actions list; configure it as a startup action if desired.",
            "Confirm the Agent OSC surface in Preferences > Control/OSC/Web, then run controller doctor/status and a bridge ping.",
        ),
    )


def dry_run(plan: BootstrapPlan) -> dict:
    """Return the reviewed writes and no side effects."""
    return {
        "mode": "dry-run",
        "controller_commit": plan.controller_commit,
        "files": [
            {"path": f.relative_path, "action": "unchanged" if f.before_hash == f.after_hash else "write", "reason": f.reason,
             "before_hash": f.before_hash, "after_hash": f.after_hash}
            for f in plan.files
        ],
        "create_dirs": list(plan.created_dirs),
        "producer_handoff": list(plan.producer_handoff),
    }


def reaper_running() -> bool:
    """Best-effort detection only; an uncertain probe is treated as unsafe."""
    try:
        code = subprocess.run(["pgrep", "-x", "REAPER"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        if code == 0:
            return True
        if code == 1:
            return False
        raise UnsafeBootstrap(f"REAPER process probe returned unexpected status {code}")
    except OSError as exc:
        raise UnsafeBootstrap(f"cannot determine whether REAPER is running: {exc}") from exc


def apply(plan: BootstrapPlan, *, running: Callable[[], bool] = reaper_running) -> BootstrapResult:
    """Apply a reviewed plan after all source and target preconditions hold."""
    if running():
        raise UnsafeBootstrap("REAPER appears to be running; refusing configuration writes")
    if _controller_identity(plan.controller_path) != plan.controller_commit:
        raise BootstrapError("controller identity changed since plan")
    for item in plan.files:
        if _sha256(item.content) != item.source_hash:
            raise BootstrapError(f"plan content hash is invalid: {item.relative_path}")
        target = _safe_target(plan.resource_path, item.relative_path)
        if _file_hash(target) != item.before_hash:
            raise BootstrapError(f"target changed since plan: {item.relative_path}")
    for relative in plan.created_dirs:
        directory = _safe_target(plan.resource_path, relative)
        if directory.exists() and not directory.is_dir():
            raise UnsafeBootstrap(f"managed queue path is not a directory: {directory}")
    changing = [item for item in plan.files if item.before_hash != item.after_hash]
    if not changing:
        for relative in plan.created_dirs:
            _safe_target(plan.resource_path, relative).mkdir(parents=True, exist_ok=True)
        return BootstrapResult(plan, None, (), tuple(item.relative_path for item in plan.files))
    stamp = f"bootstrap-{uuid.uuid4().hex}"
    backup_dir = _safe_target(plan.resource_path, f"LLMStudioBackups/{stamp}")
    backup_dir.mkdir(parents=True, exist_ok=False)
    changed: list[str] = []
    unchanged: list[str] = []
    records: list[dict] = []
    for item in plan.files:
        target = _safe_target(plan.resource_path, item.relative_path)
        if item.before_hash == item.after_hash:
            unchanged.append(item.relative_path)
            continue
        backup = backup_dir / item.relative_path
        if target.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup, follow_symlinks=False)
            backup_name: str | None = item.relative_path
        else:
            backup_name = None
        records.append({"path": item.relative_path, "before_hash": item.before_hash, "after_hash": item.after_hash, "backup": backup_name, "state": "prepared"})
    manifest_path = backup_dir / "manifest.json"
    _write_json_atomic(manifest_path, {"version": 1, "files": records})
    save_result(BootstrapResult(plan, backup_dir, (), tuple(unchanged)), backup_dir / "result.json")
    for index, (item, record) in enumerate(zip(changing, records)):
        target = _safe_target(plan.resource_path, item.relative_path)
        record["state"] = "writing"
        _write_json_atomic(manifest_path, {"version": 1, "files": records})
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.llm-studio-new")
        if temporary.exists() or temporary.is_symlink():
            raise UnsafeBootstrap(f"refusing to replace unexpected temporary file: {temporary}")
        with temporary.open('xb') as stream:
            stream.write(item.content)
        os.replace(temporary, target)
        changed.append(item.relative_path)
        record["state"] = "applied"
        _write_json_atomic(manifest_path, {"version": 1, "files": records})
    for relative in plan.created_dirs:
        _safe_target(plan.resource_path, relative).mkdir(parents=True, exist_ok=True)
    return BootstrapResult(plan, backup_dir, tuple(changed), tuple(unchanged))


def verify(result: BootstrapResult) -> dict:
    """Observe installed hashes; it makes no claim that REAPER loaded them."""
    files = []
    ok = True
    for item in result.plan.files:
        observed = _file_hash(_safe_target(result.plan.resource_path, item.relative_path))
        matched = observed == item.after_hash
        files.append({"path": item.relative_path, "expected_hash": item.after_hash, "observed_hash": observed, "ok": matched})
        ok = ok and matched
    dirs = {relative: _safe_target(result.plan.resource_path, relative).is_dir() for relative in result.plan.created_dirs}
    return {"ok": ok and all(dirs.values()), "files": files, "dirs": dirs, "runtime_verification_required": True}


def rollback(result: BootstrapResult, *, running: Callable[[], bool] = reaper_running) -> tuple[str, ...]:
    """Restore exact backups only when no post-apply edits would be lost."""
    if running():
        raise UnsafeBootstrap("REAPER appears to be running; refusing rollback writes")
    if result.backup_dir is None:
        return ()
    manifest_path = result.backup_dir / "manifest.json"
    try:
        records = json.loads(manifest_path.read_text())["files"]
    except (OSError, ValueError, KeyError) as exc:
        raise BootstrapError(f"rollback manifest is unavailable: {exc}") from exc
    for record in records:
        target = _safe_target(result.plan.resource_path, record["path"])
        observed = _file_hash(target)
        if observed not in (record["before_hash"], record["after_hash"]):
            raise RollbackRefused(f"post-apply edit detected: {record['path']}")
        if record["backup"] is not None:
            backup = result.backup_dir / record["backup"]
            if _file_hash(backup) != record["before_hash"]:
                raise RollbackRefused(f"backup integrity failure: {record['path']}")
    restored: list[str] = []
    for record in records:
        target = _safe_target(result.plan.resource_path, record["path"])
        if _file_hash(target) == record["before_hash"]:
            continue
        if record["backup"] is None:
            target.unlink()
        else:
            backup = result.backup_dir / record["backup"]
            if _file_hash(backup) != record["before_hash"]:
                raise RollbackRefused(f"backup integrity failure: {record['path']}")
            temporary = target.with_name(f".{target.name}.llm-studio-rollback")
            with temporary.open('xb') as stream:
                stream.write(backup.read_bytes())
            shutil.copystat(backup, temporary, follow_symlinks=False)
            os.replace(temporary, target)
        restored.append(record["path"])
    return tuple(restored)


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.new")
    if temporary.exists() or temporary.is_symlink():
        raise UnsafeBootstrap(f"refusing to replace unexpected temporary file: {temporary}")
    with temporary.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + "\n")
    os.replace(temporary, path)


def save_plan(plan: BootstrapPlan, path: Path) -> None:
    """Persist a reviewed plan so a later CLI process can apply that exact plan."""
    _write_json_atomic(Path(path), {
        "version": 1, "resource_path": str(plan.resource_path), "controller_path": str(plan.controller_path),
        "controller_commit": plan.controller_commit, "created_dirs": list(plan.created_dirs),
        "producer_handoff": list(plan.producer_handoff),
        "files": [{"relative_path": item.relative_path, "content": base64.b64encode(item.content).decode(),
                   "source_hash": item.source_hash, "before_hash": item.before_hash, "reason": item.reason} for item in plan.files],
    })


def load_plan(path: Path) -> BootstrapPlan:
    """Load a persisted plan without recalculating its preconditions."""
    try:
        data = json.loads(Path(path).read_text())
        files = tuple(PlannedFile(item["relative_path"], base64.b64decode(item["content"]), item["source_hash"], item["before_hash"], item["reason"]) for item in data["files"])
        for item in files:
            if _sha256(item.content) != item.source_hash:
                raise BootstrapError(f"persisted plan content hash is invalid: {item.relative_path}")
        return BootstrapPlan(Path(data["resource_path"]), Path(data["controller_path"]), data["controller_commit"], files, tuple(data["created_dirs"]), tuple(data["producer_handoff"]))
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise BootstrapError(f"invalid persisted bootstrap plan: {exc}") from exc


def save_result(result: BootstrapResult, path: Path) -> None:
    """Persist apply state, including its reviewed plan, for later verification."""
    path = Path(path).resolve()
    plan_path = path.with_suffix(path.suffix + ".plan")
    save_plan(result.plan, plan_path)
    _write_json_atomic(Path(path), {
        "version": 1,
        "plan_path": str(plan_path),
        "backup_dir": str(result.backup_dir) if result.backup_dir else None,
        "changed": list(result.changed),
        "unchanged": list(result.unchanged),
    })


def load_result(path: Path) -> BootstrapResult:
    """Load persisted apply state without trusting ambient configuration."""
    try:
        data = json.loads(Path(path).read_text())
        return BootstrapResult(
            load_plan(Path(data["plan_path"])),
            Path(data["backup_dir"]) if data["backup_dir"] else None,
            tuple(data["changed"]),
            tuple(data["unchanged"]),
        )
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise BootstrapError(f"invalid persisted bootstrap result: {exc}") from exc


def load_recovery_result(backup_dir: Path) -> BootstrapResult:
    """Load the receipt written before the first managed file mutation."""
    backup_dir = Path(backup_dir)
    result = load_result(backup_dir / "result.json")
    try:
        records = json.loads((backup_dir / "manifest.json").read_text())["files"]
    except (OSError, KeyError, ValueError) as exc:
        raise BootstrapError(f"invalid recovery manifest: {exc}") from exc
    changed = tuple(record["path"] for record in records if record.get("state") in ("writing", "applied"))
    return BootstrapResult(result.plan, backup_dir, changed, result.unchanged)
