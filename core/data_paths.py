"""User data survives replacing/extracting a new application folder."""
import os
import sys
from pathlib import Path


def data_dir():
    override = os.environ.get('JARVIS_DATA_DIR')
    if override:
        path = Path(override).expanduser()
    elif sys.platform == 'win32':
        path = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'JarvisGPT'
    elif sys.platform == 'darwin':
        path = Path.home() / 'Library' / 'Application Support' / 'JarvisGPT'
    else:
        path = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'jarvisgpt'
    path.mkdir(parents=True, exist_ok=True)
    return path
