import subprocess
import sys

print("Starting FastAPI and Streamlit...")

# Launch both processes using the current Python environment
backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "middleware:app", "--reload"])
frontend = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py"])

try:
    # Keep the script running while both servers operate
    backend.wait()
    frontend.wait()
except KeyboardInterrupt:
    # Catch Ctrl+C in the VS Code terminal to kill both instantly
    print("\nShutting down both servers...")
    backend.terminate()
    frontend.terminate()
    print("Servers stopped.")