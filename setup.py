"""
py2app build script for Vibe Coding Rings.

Usage:
    pip install py2app
    python setup.py py2app
    # Output: dist/Vibe Coding Rings.app
"""
from setuptools import setup

APP = ["menubar.py"]

DATA_FILES = [
    ("static", [
        "static/index.html",
        "static/rings.js",
        "static/style.css",
    ]),
]

OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "fastapi",
        "uvicorn",
        "starlette",
        "anyio",
        "h11",
        "pydantic",
        "rumps",
    ],
    "excludes": ["tkinter", "test", "unittest", "distutils", "zmq", "numpy", "pandas", "scipy", "matplotlib"],
    "frameworks": [
        "/opt/homebrew/Caskroom/miniconda/base/lib/libffi.8.dylib",
        "/opt/homebrew/Caskroom/miniconda/base/lib/libssl.3.dylib",
        "/opt/homebrew/Caskroom/miniconda/base/lib/libcrypto.3.dylib",
    ],
    "plist": {
        "LSUIElement": True,                          # menubar-only, no Dock icon
        "CFBundleName": "Vibe Coding Rings",
        "CFBundleDisplayName": "Vibe Coding Rings",
        "CFBundleIdentifier": "com.zxw1992.vibe-coding-rings",
        "CFBundleVersion": "1.0.3",
        "CFBundleShortVersionString": "1.0.3",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "MIT",
    },
}

setup(
    name="Vibe Coding Rings",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
