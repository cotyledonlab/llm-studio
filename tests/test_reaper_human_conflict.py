from pathlib import Path
import subprocess
import sys
import tempfile


def test_prepares_bounded_human_conflict_wrapper():
    base = Path("/private/tmp/llm-studio-reaper")
    base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="test-human-conflict-", dir=base) as name:
        root = Path(name)
        source = root / "session.RPP"
        source.write_text("<REAPER_PROJECT 0.1\n>\n")
        profile = root / "profile"
        profile.mkdir()
        cfgfile = profile / "reaper.ini"
        cfgfile.write_text("[REAPER]\n")
        output = root / "human-conflict.txt"
        wrapper = output.with_suffix(".lua")
        result = subprocess.run(
            [sys.executable, "tools/qualification/reaper_human_conflict.py",
             "--source", str(source), "--cfgfile", str(cfgfile),
             "--output", str(output)],
            check=True, text=True, capture_output=True,
        )
        assert Path(result.stdout.strip()) == wrapper
        text = wrapper.read_text()
        assert "STUDIO_HUMAN_CONFLICT" in text
        assert str(source) in text
        assert "reaper_human_conflict.lua" in text
