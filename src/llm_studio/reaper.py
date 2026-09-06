"""Studio semantics over the pinned controller's transport, with no index fallback."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping


class ReaperAdapterError(RuntimeError):
    """A request did not produce trustworthy observed state."""


class UnsupportedReaperCapability(ReaperAdapterError):
    pass


class SessionChanged(ReaperAdapterError):
    pass


class TrackBindingOrphaned(ReaperAdapterError):
    pass


def _error(code: str, detail: str) -> ReaperAdapterError:
    kind = {"UNKNOWN_OP": UnsupportedReaperCapability, "UNSUPPORTED": UnsupportedReaperCapability,
            "SESSION_CHANGED": SessionChanged, "TRACK_ORPHANED": TrackBindingOrphaned}.get(code, ReaperAdapterError)
    return kind(f"{code}: {detail}")


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Track:
    guid: str
    name: str
    index: int


@dataclass(frozen=True)
class Session:
    id: str
    token: str
    path: Path
    state_change_count: int
    tracks: tuple[Track, ...]

    def track(self, guid: str) -> Track:
        for track in self.tracks:
            if track.guid == guid:
                return track
        raise TrackBindingOrphaned(guid)


class ReaperStudioAdapter:
    """Inject ``reaper_connector.bridge.send``; keep transport ownership upstream.

    Only disposable sessions are writable in this issue #9 qualification slice.
    Gain uses dB at this boundary; ``silent=True`` explicitly requests zero gain.
    This is not the production proposal/conflict protocol reserved for issue #10.
    """

    def __init__(self, bridge_send: Callable, *, disposable_roots: tuple[Path, ...] | None = None):
        self._bridge_send = bridge_send
        roots = disposable_roots if disposable_roots is not None else (
            Path('/private/tmp/llm-studio-reaper'), Path.home() / 'Music/ReaperConnector/Test Projects')
        self._roots = tuple(root.resolve() for root in roots)

    def _send(self, operation: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            reply = self._bridge_send(operation, params)
        except Exception as exc:
            raise _error(str(getattr(exc, 'code', 'TRANSPORT')), str(exc)) from exc
        if not isinstance(reply, Mapping):
            raise ReaperAdapterError('non-object bridge reply')
        if reply.get('ok') is False:
            error = reply.get('error', {})
            raise _error(str(error.get('code', 'UNKNOWN')), str(error.get('detail', operation)))
        if reply.get('ok') is not True or not isinstance(reply.get('result'), Mapping):
            raise ReaperAdapterError('missing successful observed result')
        return reply['result']

    def observe_session(self) -> Session:
        result = self._send('studio.session_snapshot', {})
        raw, tracks = result.get('session'), result.get('tracks')
        # The upstream encoder represents an empty Lua table as {}, not [].
        if tracks == {}:
            tracks = []
        if not isinstance(raw, Mapping) or not isinstance(tracks, list):
            raise ReaperAdapterError('incomplete snapshot')
        if any(not isinstance(raw.get(key), str) or not raw[key] for key in ('id', 'token', 'path')):
            raise ReaperAdapterError('snapshot lacks saved session identity')
        if not Path(raw['path']).is_absolute() or raw['id'] != raw['path'] or type(raw.get('state_change_count')) is not int:
            raise ReaperAdapterError('invalid session identity')
        parsed, seen = [], set()
        for item in tracks:
            if not isinstance(item, Mapping):
                raise ReaperAdapterError('malformed track')
            guid = item.get('guid')
            if not isinstance(guid, str) or not guid or guid in seen or not isinstance(item.get('name'), str) or type(item.get('index')) is not int or item['index'] != len(parsed):
                raise ReaperAdapterError('invalid GUID/index discovery')
            parsed.append(Track(guid, item['name'], item['index']))
            seen.add(guid)
        return Session(raw['id'], raw['token'], Path(raw['path']), raw['state_change_count'], tuple(parsed))

    @staticmethod
    def _params(session: Session, guid: str, **extra: Any) -> dict:
        session.track(guid)
        return {'session_id': session.id, 'session_token': session.token, 'track_guid': guid, **extra}

    def _writable(self, session: Session) -> Path:
        path = session.path
        if not path.is_absolute() or path != path.resolve() or not path.is_file() or path.suffix.lower() != '.rpp':
            raise ReaperAdapterError('requires canonical saved disposable project')
        if not any(path.is_relative_to(root) for root in self._roots):
            raise ReaperAdapterError('project is outside disposable roots')
        return path

    def read_track(self, session: Session, guid: str) -> Mapping[str, Any]:
        result = dict(self._send('studio.get_track_state', self._params(session, guid)))
        volume, pan, fx = result.get('volume'), result.get('pan'), result.get('fx')
        if fx == {}:
            fx = []
        if result.get('guid') != guid or not _number(volume) or volume < 0 or not _number(pan) or not -1 <= pan <= 1 or not isinstance(fx, list):
            raise ReaperAdapterError('invalid observed mixer/FX state')
        for index, item in enumerate(fx):
            if not isinstance(item, Mapping) or item.get('index') != index or not isinstance(item.get('name'), str) or type(item.get('params')) is not int or item['params'] < 0:
                raise ReaperAdapterError('invalid FX discovery')
        result.update(fx=fx, gain_db=20 * math.log10(volume) if volume else None, silent=volume == 0)
        return result

    def set_mixer(self, session: Session, guid: str, *, gain_db: float | None = None,
                  pan: float | None = None, silent: bool = False) -> Mapping[str, Any]:
        if type(silent) is not bool or (silent and gain_db is not None):
            raise ValueError('use either gain_db or explicit silence')
        if gain_db is not None and (not _number(gain_db) or not -150 <= gain_db <= 12):
            raise ValueError('gain_db must be finite within -150..12')
        if pan is not None and (not _number(pan) or not -1 <= pan <= 1):
            raise ValueError('pan must be finite within -1..1')
        if gain_db is None and pan is None and not silent:
            raise ValueError('no mixer control requested')
        self._writable(session)
        values = {}
        if silent or gain_db is not None:
            values['volume'] = 0 if silent else 10 ** (gain_db / 20)
        if pan is not None:
            values['pan'] = pan
        result = self._send('studio.set_mixer', self._params(session, guid, **values))
        observed = result.get('observed')
        if not isinstance(observed, Mapping) or any(not _number(observed.get(key)) or not math.isclose(observed[key], value, rel_tol=1e-9, abs_tol=1e-12) for key, value in values.items()):
            raise ReaperAdapterError('mixer readback differs; do not retry blindly')
        return result

    def import_stem(self, session: Session, guid: str, stem: Path, *, position_sec: float = 0) -> Mapping[str, Any]:
        if not _number(position_sec) or position_sec < 0:
            raise ValueError('position_sec must be finite and nonnegative')
        params = self._params(session, guid)
        project = self._writable(session)
        source = stem.resolve(strict=True)
        if not source.is_file() or source.suffix.lower() != '.wav':
            raise ReaperAdapterError('qualification import supports WAV files only')
        media = project.parent / 'media'
        if media.is_symlink() or media != media.resolve():
            raise ReaperAdapterError('media directory must not be a symlink')
        media.mkdir(exist_ok=True)
        digest = _digest(source)
        destination = media / f'{digest}.wav'
        if destination.is_symlink():
            raise ReaperAdapterError('media asset must not be a symlink')
        if destination.exists():
            if _digest(destination) != digest:
                raise ReaperAdapterError('existing media hash differs')
        else:
            fd, name = tempfile.mkstemp(prefix='.stem-', dir=media)
            temporary = Path(name)
            try:
                with os.fdopen(fd, 'wb') as output, source.open('rb') as input:
                    while block := input.read(1024 * 1024):
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
                if _digest(temporary) != digest:
                    raise ReaperAdapterError('source changed during staging')
                # Atomic no-clobber publication; never replace an existing take.
                os.link(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        result = self._send('studio.import_stem', {**params, 'stem_path': str(destination), 'position_sec': position_sec})
        if result.get('durable_path') != str(destination) or result.get('track_guid') != guid or not isinstance(result.get('item_guid'), str) or not result['item_guid'] or not _number(result.get('length_sec')) or result['length_sec'] <= 0 or result.get('position_sec') != position_sec:
            raise ReaperAdapterError('incomplete media readback; do not retry blindly')
        return result
