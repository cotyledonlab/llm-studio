# Disposable REAPER profile license setup

REAPER documents `reaper-license.rk` in its resource directory. Its official
changelog says macOS uses the resource path associated with the INI supplied
to `-cfgfile`; this supports copying an existing licensed resource file into a
separate profile before launching that profile.

Keep an existing license file in a user-only source directory. Set that
directory to mode `700` and the file to mode `600`. Do not put the key in a
command argument, shell history, clipboard, repository, or log.

For a disposable profile, create the profile and `resource` directories under
`/private/tmp/llm-studio-reaper`, both owned by the current user and mode `700`.
If REAPER needs an empty-profile bootstrap to create its resource/config files,
launch that bootstrap and quit it completely first. Then copy the license and
launch the actual profile:

```sh
PYTHONPATH=src python3 tools/qualification/install_profile_license.py \
  --source "$LICENSE_FILE" \
  --resource /private/tmp/llm-studio-reaper/qualification-123/profile/resource
```

The helper requires the source to be a regular, non-symlink file owned by the
current user with mode `600`, inside a current-user-owned source directory
with mode `700`. It requires profile parent and resource directories to be
private mode `700`, refuses an existing target, and checks
that no REAPER process is using the destination resource. It creates the
destination exclusively with mode `600`, copies bytes without displaying
them, and does not launch REAPER. The caller supplies the source path; the
repository contains no license or machine-specific source path.

Remove the disposable profile after REAPER exits. File deletion on APFS/SSDs
does not guarantee physical erasure, so keep temporary profiles out of backups
and sync services.
