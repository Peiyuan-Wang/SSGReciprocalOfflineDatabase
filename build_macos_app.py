#!/usr/bin/env python3
"""Build a lightweight macOS application wrapper for the local GUI."""

from __future__ import annotations

import plistlib
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
APP = HERE / "dist" / "SSG Reciprocal Database.app"


def main() -> None:
    if APP.exists():
        shutil.rmtree(APP)
    macos = APP / "Contents" / "MacOS"
    resources = APP / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    shutil.copy2(HERE / "ssg_database_gui.py", resources / "ssg_database_gui.py")

    info = {
        "CFBundleName": "SSG Reciprocal Database Preview",
        "CFBundleDisplayName": "SSG Reciprocal Database Preview",
        "CFBundleIdentifier": "org.ssg.reciprocaldatabase.offline.dev",
        "CFBundleVersion": "0.1.6",
        "CFBundleShortVersionString": "0.1.6",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "SSGReciprocalDatabase",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }
    with (APP / "Contents" / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)

    launcher = macos / "SSGReciprocalDatabase"
    launcher_source = r'''#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void log_failure(const char *message) {
    FILE *stream = fopen("/tmp/SSGReciprocalDatabase-launch.log", "a");
    if (stream != NULL) {
        fprintf(stream, "%s\n", message);
        fclose(stream);
    }
}

int main(void) {
    char executable[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) != 0) {
        log_failure("Unable to resolve application executable path.");
        return 70;
    }
    char resolved[PATH_MAX];
    if (realpath(executable, resolved) == NULL) {
        log_failure("Unable to canonicalize application executable path.");
        return 71;
    }
    char *marker = strstr(resolved, "/Contents/MacOS/");
    if (marker == NULL) {
        log_failure("Application bundle layout is invalid.");
        return 72;
    }
    *marker = '\0';
    char script[PATH_MAX];
    snprintf(script, sizeof(script), "%s/Contents/Resources/ssg_database_gui.py", resolved);

    const char *candidates[] = {
        "/opt/anaconda3/bin/python3",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        NULL
    };
    for (int index = 0; candidates[index] != NULL; ++index) {
        if (access(candidates[index], X_OK) == 0) {
            execl(candidates[index], candidates[index], script, (char *)NULL);
        }
    }
    log_failure("No executable Python runtime with Tk 8.6 was found.");
    return 73;
}
'''
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "launcher.c"
        source.write_text(launcher_source, encoding="utf-8")
        subprocess.run(
            ["clang", "-Wall", "-Wextra", "-O2", str(source), "-o", str(launcher)],
            check=True,
        )
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(APP)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    print(APP)


if __name__ == "__main__":
    main()
