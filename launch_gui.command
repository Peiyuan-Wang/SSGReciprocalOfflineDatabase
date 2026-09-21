#!/bin/zsh
set -eu
cd "${0:A:h}"

for candidate in /opt/anaconda3/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [[ -x "$candidate" ]] && "$candidate" -c 'import tkinter; assert tkinter.TkVersion >= 8.6' 2>/dev/null; then
    exec "$candidate" ssg_database_gui.py "$@"
  fi
done

print -u2 "No Python runtime with Tcl/Tk 8.6 or newer was found."
print -u2 "Use the packaged desktop application or install a current Python distribution."
exit 1
