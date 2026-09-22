"""Apply and recover one bounded patch through the installed controller transport."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm_studio.reaper import ReaperStudioAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("output already exists")
    from reaper_connector import bridge
    adapter = ReaperStudioAdapter(
        lambda op, params: bridge.send(op, params, timeout=10, resource_path=args.resource))
    session = adapter.observe_session()
    if not session.path.is_relative_to(Path('/private/tmp/llm-studio-reaper')) or not session.tracks:
        raise RuntimeError("active session must be a disposable project with a track")
    track = session.tracks[0]
    before = adapter.read_volume_envelope(session, track.guid, start_sec=1, end_sec=3)
    by_time = {point['time_sec']: point for point in before['points']}
    if 1 not in by_time or 3 not in by_time:
        raise RuntimeError("one/three-second boundary points required")
    points = [
        {'time_sec': 1, 'gain_db': by_time[1]['gain_db']} if not by_time[1]['silent'] else {'time_sec': 1, 'silent': True},
        {'time_sec': 2, 'gain_db': -12},
        {'time_sec': 3, 'gain_db': by_time[3]['gain_db']} if not by_time[3]['silent'] else {'time_sec': 3, 'silent': True},
    ]
    patch = adapter.patch_volume_envelope(session, track.guid, before, points)
    recovered = adapter.undo_volume_patch(session, track.guid, patch)
    result = {
        'ok': recovered['undone'] is True,
        'session': session.id,
        'track_guid': track.guid,
        'controller_transport': 'installed file-drop bridge',
        'before_points': before['points'],
        'patched_points': patch['observed']['points'],
        'recovered_points': recovered['observed']['points'],
        'recovery_matches_before': recovered['observed']['points'] == before['points'],
        'undo_label': patch.get('undo_label'),
    }
    if not result['ok'] or not result['recovery_matches_before']:
        raise RuntimeError("installed transport recovery differs")
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
