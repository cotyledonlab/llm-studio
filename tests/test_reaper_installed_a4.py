import hashlib
from argparse import Namespace
import wave

import pytest

from tools.qualification import reaper_installed_a4 as installed
from tools.qualification.reaper_installed_a4 import (
    project_layout, write_replacement_tone,
)
from tools.qualification.reaper_take_replacement import tone


def test_project_layout_binds_expected_a4_tracks_and_item_guids(tmp_path):
    project = tmp_path / 'session.RPP'
    project.write_text('''<REAPER_PROJECT 0.1
  <TRACK {KEYS}
    NAME Keys
    VOLPAN 1 0 -1 -1 1
    <ITEM
      POSITION 0
      LENGTH 5
      IGUID {KEYS-ITEM}
      GUID {KEYS-TAKE}
      <SOURCE WAVE
      >
    >
  >
  <TRACK {BASS}
    NAME Bass
    VOLPAN 0 -0.2 -1 -1 1
    <FXCHAIN
      <VST "VST: ReaEQ (Cockos)" reaeq.vst.dylib
      >
    >
    <ITEM
      POSITION 0
      LENGTH 5
      IGUID {BASS-ITEM}
    >
  >
  <TRACK {DRUMS}
    NAME Drums
    VOLPAN 1 0 -1 -1 1
    <ITEM
      POSITION 0
      LENGTH 5
      IGUID {DRUMS-ITEM}
    >
  >
>
''')

    layout = project_layout(project)

    assert [track['name'] for track in layout] == ['Keys', 'Bass', 'Drums']
    assert [track['guid'] for track in layout] == ['{KEYS}', '{BASS}', '{DRUMS}']
    assert layout[-1]['item_guid'] == '{DRUMS-ITEM}'
    assert layout[-1]['length_sec'] == 5
    installed._validate_saved_bass(layout[1])


def test_replacement_tone_is_same_shape_440hz_but_byte_distinct(tmp_path):
    old = tmp_path / 'drums-440.wav'
    new = tmp_path / 'replacement-440.wav'
    tone(old, 440)
    result = write_replacement_tone(new, 5.0)

    with wave.open(str(new), 'rb') as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(),
                audio.getnframes()) == (1, 2, 48000, 240000)
    assert result['frequency_hz'] == 440
    assert result['sha256'] != hashlib.sha256(old.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        write_replacement_tone(new, 5.0)


def test_saved_project_hash_mismatch_refuses_before_bridge_or_fixture_write(tmp_path, monkeypatch):
    monkeypatch.setattr(installed, 'BASE', tmp_path)
    root = tmp_path / 'run'
    resource = root / 'profile/resource'
    (resource / 'Scripts').mkdir(parents=True)
    (resource / 'reaper.ini').write_text('[REAPER]\n')
    (resource / 'Scripts/agent_bridge.lua').write_text('-- installed bridge')
    (resource / 'Scripts/llm_studio_reaper.lua').write_text('-- installed handler')
    project = root / 'session.RPP'
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text('mutated saved project')
    output = root / 'evidence.json'
    args = Namespace(controller=root, resource=resource, project=project,
                     output=output, timeout_sec=5,
                     expected_project_sha256='0' * 64,
                     expected_drum_source_sha256='1' * 64)
    monkeypatch.setattr(installed.bootstrap, 'validate_controller_checkout',
                        lambda *_: pytest.fail('controller validation must not follow a hash refusal'))

    evidence = installed.run(args)

    assert evidence['ok'] is False
    assert 'saved project SHA256 differs' in evidence['error']
    assert evidence['replace_call_count'] == 0
    assert not (root / 'installed-a4-replacement-440hz.wav').exists()
    assert output.is_file()


@pytest.mark.parametrize('track', [
    {'name': 'Bass', 'volume': 0.5011872336, 'pan': -0.2,
     'fx': ['VST: ReaEQ (Cockos)']},
    {'name': 'Bass', 'volume': 1e-50, 'pan': -0.2,
     'fx': ['VST: ReaEQ (Cockos)']},
    {'name': 'Bass', 'volume': 0.0, 'pan': 0.0,
     'fx': ['VST: ReaEQ (Cockos)']},
    {'name': 'Bass', 'volume': 0.0, 'pan': -0.2, 'fx': []},
])
def test_unsafe_saved_bass_baseline_is_refused(track):
    with pytest.raises(ValueError, match='saved Bass baseline'):
        installed._validate_saved_bass(track)


def test_current_drum_source_hash_mismatch_is_refused():
    with pytest.raises(ValueError, match='current Drums source SHA256 differs'):
        installed._require_sha256_match('2' * 64, '3' * 64, 'current Drums source')


def test_live_bass_must_be_silent_with_expected_pan_and_eq():
    installed._validate_live_bass({'volume': 0.0, 'gain_db': None, 'pan': -0.2,
                                   'fx': [{'name': 'VST: ReaEQ (Cockos)'}]})
    with pytest.raises(ValueError, match='live Bass'):
        installed._validate_live_bass({'volume': 1.0, 'gain_db': 0.0, 'pan': -0.2,
                                       'fx': [{'name': 'VST: ReaEQ (Cockos)'}]})
    with pytest.raises(ValueError, match='live Bass'):
        installed._validate_live_bass({'volume': 1e-50, 'gain_db': -1000.0, 'pan': -0.2,
                                       'fx': [{'name': 'VST: ReaEQ (Cockos)'}]})
