import os
import sys
import subprocess

# Change to script directory
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

print(f"Working directory: {os.getcwd()}")

# Build with PyInstaller
print("Building with PyInstaller...")
result = subprocess.run([sys.executable, "-m", "PyInstaller", "salikha_pro.spec", "--clean"], 
                       capture_output=True, text=True)
print(result.stdout)
print(result.stderr)

if result.returncode != 0:
    print("PyInstaller build failed!")
    input("Press Enter to exit...")
    sys.exit(1)

# Check for Inno Setup
inno_paths = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 5\ISCC.exe",
]

iscc = None
for path in inno_paths:
    if os.path.exists(path):
        iscc = path
        break

if iscc:
    print(f"Building installer with Inno Setup: {iscc}")
    result = subprocess.run([iscc, "salikha_pro_setup.iss"], capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
    if result.returncode == 0:
        print("Installer built successfully!")
else:
    print("Inno Setup not found. Skipping installer creation.")
    print("You can manually run: ISCC.exe salikha_pro_setup.iss")

print("\nBuild complete!")
print(f"Executable: dist\\salikha_pro.exe")