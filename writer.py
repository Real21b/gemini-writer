#!/usr/bin/env python3
"""
Gemini Writing Agent - entry point.

The agent itself lives in ``core/``; this file only starts the CLI so that the
documented ``python writer.py "..."`` command keeps working.
"""

from cli.main import run

if __name__ == "__main__":
    run()
