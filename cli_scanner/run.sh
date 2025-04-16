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

# Check for list flag
LIST_FLAG=""
if [[ "$*" == *"-l"* || "$*" == *"--list"* ]]; then
  LIST_FLAG="--list"
fi

# Run the scanner with parallel processing
if [ -z "$1" ]; then
  python3 scanner.py --parallel $WORKERS $LIST_FLAG
elif [[ "$1" == "-l" || "$1" == "--list" ]]; then
  python3 scanner.py --parallel $WORKERS --list
else
  python3 scanner.py --date "$1" --parallel $WORKERS $LIST_FLAG
fi
