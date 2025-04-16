#!/bin/bash

# Get number of available cores for parallel processing
NUM_CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

# Use half the available cores (minimum 2, maximum 6 for stability)
WORKERS=$(( NUM_CORES / 2 ))
if (( WORKERS < 2 )); then
  WORKERS=2
elif (( WORKERS > 6 )); then
  WORKERS=6
fi

# Run the scanner with parallel processing
if [ -z "$1" ]; then
  python3 scanner.py --parallel $WORKERS
else
  python3 scanner.py --date "$1" --parallel $WORKERS
fi
