#0.0.0.0
from cx_Freeze import setup, Executable

file = "setup.py"
project_name = "my_bot"

with open(file, 'r+', encoding='utf-8') as f:
    version = f.readline().split('.')
    version[-1] = str(int(version[-1]) + 1)
    version = '.'.join(version)
    f.seek(0)
    f.write(version)

# для включения конкретных файлов в build
# files = ["database/", "config/"]

# Dependencies are automatically detected, but it might need fine tuning.
build_exe_options = {
    # "excludes": ["tkinter", "unittest"],
    # "packages": ["config"],
    # "includes": ["config"],
    "optimize": 2,      # c 2 exe не запускается
    # "zip_include_packages": ["PyQt5", "matplotlib"],
    # "include_files" : files
}

# base="Win32GUI" should be used only for Windows GUI app
# base = "Win32GUI" if sys.platform == "win32" else None

setup(
    name=project_name,
    version="0.0.0.1",
    description="My Telegram Bot",
    options={"build_exe": build_exe_options},
    
    executables=[Executable("main.py", target_name="mybot")],
    
)