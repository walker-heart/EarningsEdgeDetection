"""Modified version of the scanner.py with the syntax error fixed.

The main issue was in the scan_earnings method - there was incorrect indentation after a try-except block,
causing the candidates = [] line to be outside any block structure when it was expected to be inside a try-except.

The fix is to properly indent the candidates = [] line so it's part of the surrounding try-except block.
"