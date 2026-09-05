# Ardour qualification environment

Observed on 2026-09-05. Hardware identifiers such as serial number and UUID are deliberately omitted.

| Item | Observed value | Command |
|---|---|---|
| Host | MacBook Air `Mac16,12` | `system_profiler SPHardwareDataType` |
| CPU | Apple M4, 10 cores (4 performance, 6 efficiency) | `system_profiler SPHardwareDataType` |
| Memory | 16 GB | `system_profiler SPHardwareDataType` |
| Architecture | `arm64` | `uname -a` |
| macOS | 26.5.2 (25F84), Darwin 25.5.0 | `sw_vers`; `uname -a` |
| Xcode | 26.6 (17F113) | `xcodebuild -version` |
| Compiler | Apple clang 21.0.0 | `clang --version` |
| Python | Homebrew Python 3.14.6; no `python` command on the probe PATH | `python3 --version`; `command -v python` |
| Audio input | Built-in MacBook Air microphone, mono, 48 kHz | `system_profiler SPAudioDataType` |
| Audio output | Built-in MacBook Air speakers, stereo, 48 kHz | `system_profiler SPAudioDataType` |
| External audio interface | None reported | `system_profiler SPAudioDataType` |
| Ardour application | Not installed under `/Applications` | `find /Applications -maxdepth 3 -iname '*Ardour*'` |
| Ardour executable | Not found | `command -v ardour`; `command -v ardour8` |
| Ardour package receipt | Not found | `pkgutil --pkgs` filtered for Ardour |
| Running Ardour process | Not found | `pgrep -fal 'Ardour|ardour'` |
| Listening Ardour MCP endpoint | Not found | process check plus the read-only MCP probe |

## No-charge source-build attempt

The upstream Git repository was shallow-cloned to a temporary directory at commit `ba38f08ea4e63ae3b8c39405e61239aa7d490f2a` (commit date 2026-09-04). This source identity contains `libs/surfaces/mcp_http`.

Commands:

```sh
git clone --depth 1 https://github.com/Ardour/ardour.git /private/tmp/ardour-issue-8-source
cd /private/tmp/ardour-issue-8-source
python3 ./waf configure
```

Observed result: configuration stopped at `Checking for boost library >= 1.68: no`. Before invoking Waf through `python3`, `./waf configure` failed because its shebang requests `python`, which is absent on this host. No Ardour binary or application bundle was produced.

The upstream macOS build instructions require building the dependency stack from source and explain that maintaining those dependencies is a major reason for providing ready-to-run binaries. The current Ardour FAQ states that the stack contains 89 other free/libre libraries. Installing and maintaining that unpinned stack is not a reproducible project-local setup within this qualification's bounded investigation.

An official paid ready-to-run build remains an optional convenience, but it was not downloaded or substituted for the required no-purchase baseline.

## Reproduction notes

The source-build commands above reproduce the first failure, not a successful build. A successful baseline still needs a pinned, automated dependency-stack build for Apple Silicon/macOS 26, followed by a produced build identity, signature/hash and runtime tests. Until that exists, the no-charge build acceptance criterion is **failed**.
