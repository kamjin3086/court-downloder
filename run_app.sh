#!/bin/bash

# Ensure the script exits if any command fails
set -e

echo "============================================"
echo " 法院文书下载器 - 启动与依赖安装脚本 (macOS/Linux)"
echo "============================================"

# Variables
VENV_DIR="venv"
PYTHON_CMD="python3"

# --- Check for Python 3 ---
echo "Checking for Python 3..."
if ! command -v $PYTHON_CMD &> /dev/null
then
    echo "Error: $PYTHON_CMD command not found."
    echo "Please install Python 3.10 or higher and ensure it's in your PATH."
    exit 1
fi
echo "Python 3 found."

# --- Set up and activate virtual environment ---
echo "Checking for virtual environment ('$VENV_DIR')..."
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to create virtual environment."
        exit 1
    fi
    echo "Virtual environment created."
else
    echo "Virtual environment found."
fi

echo "Activating virtual environment..."
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
if [ $? -ne 0 ]; then
    echo "Error: Failed to activate virtual environment."
    exit 1
fi

# --- Install/Check Dependencies ---
echo "Checking and installing dependencies from requirements.txt..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Error: Failed to install dependencies."
    # Deactivate venv before exiting on error
    deactivate
    exit 1
fi
echo "Dependencies are up to date."

# --- Start the Application ---
echo "============================================"
echo "Starting Court Downloader application..."
echo "Access at: http://localhost:8000 or http://127.0.0.1:8000"
echo "Press CTRL+C in this window to stop the server."
echo "============================================"

# Run Uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000

# --- Cleanup (optional but good practice) ---
EXIT_CODE=$?
echo
echo "Application stopped (Exit code: $EXIT_CODE)."

# Deactivate the virtual environment
# This runs after uvicorn stops (e.g., Ctrl+C or error)
if type deactivate &> /dev/null
then
  echo "Deactivating virtual environment."
  deactivate
fi

exit $EXIT_CODE 