"""Offline contracts for the A4 native runner and render measurements."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import wave

from tools.qualification.reaper_export_stems import read_pcm, tone_magnitude
from tools.qualification.reaper_take_replacement import tone, wait_for_active_copy


def test_prepares_two_stage_native_runner_without_opening_reaper():
    base = Path('/private/tmp/llm-studio-reaper')
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='test-gate-a4-', dir=base) as name:
        source = Path(name) / 'session.RPP'
        source.write_text('<REAPER_PROJECT 0.1\n>\n')
        profile = Path(name) / 'profile'
        profile.mkdir()
        cfgfile = profile / 'reaper.ini'
        cfgfile.write_text('[REAPER]\n')
        result = subprocess.run([sys.executable,
            'tools/qualification/reaper_take_replacement.py',
            '--source', str(source), '--cfgfile', str(cfgfile)],
            check=True, capture_output=True, text=True)
        root = Path(result.stdout.strip())
        try:
            assert root.is_dir()
            assert 'reaper_take_replacement.lua' in (root / 'run.lua').read_text()
            assert 'single_track_source' in Path('tools/qualification/reaper_take_replacement.lua').read_text()
            assert 'empty_media_source_track' in Path('tools/qualification/reaper_take_replacement.lua').read_text()
            assert 'reaper_take_replacement_reopen.lua' in (root / 'reopen.lua').read_text()
            assert len(list((root / 'media').glob('*.wav'))) == 4
            assert not (root / 'native-evidence.txt').exists()
        finally:
            shutil.rmtree(root)


def test_pcm_reader_and_frequency_measurement(tmp_path):
    target = tmp_path / 'tone.wav'
    tone(target, 440)
    with wave.open(str(target), 'rb') as source:
        assert source.getnframes() == 240000
        assert source.getframerate() == 48000
    # The comparison reader intentionally requires stereo exports, not dry mono assets.
    try:
        read_pcm(target)
    except ValueError as error:
        assert 'stereo PCM' in str(error)
    else:
        raise AssertionError('mono source was accepted as a stereo export')
    assert callable(tone_magnitude)


def test_reopen_waits_for_independent_active_project_observation(tmp_path):
    expected = tmp_path / 'session.RPP'
    paths = iter(['/source.RPP', str(expected)])
    wait_for_active_copy(lambda: {'path': next(paths)}, expected,
                         timeout=1, interval=0)

    try:
        wait_for_active_copy(lambda: {'path': '/source.RPP'}, expected,
                             timeout=0, interval=0)
    except TimeoutError as error:
        assert str(expected) in str(error)
        assert '/source.RPP' in str(error)
    else:
        raise AssertionError('stage two was allowed without active-copy observation')
