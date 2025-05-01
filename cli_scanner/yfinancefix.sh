#!/bin/bash
set -e
PYTHON_PATH=$(which python)
echo "Using Python interpreter: $PYTHON_PATH"

YFINANCE_DIR=$(python -c "import yfinance, os; print(os.path.dirname(yfinance.__file__))")
DATA_PY="$YFINANCE_DIR/data.py"

echo "Found yfinance at: $YFINANCE_DIR"
echo "Modifying: $DATA_PY"

sed -i '' 's/^import requests as requests$/from curl_cffi import requests/' "$DATA_PY"

# (Note the double quotes around the file path and extra '' after -i for macOS sed)
sed -i '' '85s/.*/        self._set_session(session or requests.Session(impersonate="chrome"))/' "$DATA_PY"

echo "Patch applied successfully."