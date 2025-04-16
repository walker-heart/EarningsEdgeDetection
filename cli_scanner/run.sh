#!/bin/bash

# Make sure dependencies are installed (pip install -r requirements.txt)

# Get number of available cores for parallel processing
NUM_CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

# Use half the available cores (minimum 2, maximum 6 for stability)
WORKERS=$(( NUM_CORES / 2 ))
if (( WORKERS < 2 )); then
  WORKERS=2
elif (( WORKERS > 6 )); then
  WORKERS=6
fi

# Check for flags
LIST_FLAG=""
IRONFLY_FLAG=""
if [[ "$*" == *"-l"* || "$*" == *"--list"* ]]; then
  LIST_FLAG="--list"
fi
if [[ "$*" == *"-i"* || "$*" == *"--iron-fly"* ]]; then
  IRONFLY_FLAG="--iron-fly"
fi

# Run the scanner with parallel processing
if [ -z "$1" ]; then
  python3 scanner.py --parallel $WORKERS $LIST_FLAG $IRONFLY_FLAG
elif [[ "$1" == "-l" || "$1" == "--list" || "$1" == "-i" || "$1" == "--iron-fly" ]]; then
  # Handle flags when they appear as the first argument
  if [[ "$1" == "-l" || "$1" == "--list" ]]; then
    LIST_FLAG="--list"
  else
    IRONFLY_FLAG="--iron-fly"
  fi
  
  # Check for second flag
  if [[ "$2" == "-l" || "$2" == "--list" ]]; then
    LIST_FLAG="--list"
  elif [[ "$2" == "-i" || "$2" == "--iron-fly" ]]; then
    IRONFLY_FLAG="--iron-fly"
  fi
  
  python3 scanner.py --parallel $WORKERS $LIST_FLAG $IRONFLY_FLAG
else
  # Date is provided as first argument
  python3 scanner.py --date "$1" --parallel $WORKERS $LIST_FLAG $IRONFLY_FLAG
fi
