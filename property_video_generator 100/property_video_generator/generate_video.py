#!/usr/bin/env python3
"""Entry point: python generate_video.py --input sample/property.json"""
import sys

from propvideo.cli import main

if __name__ == "__main__":
    sys.exit(main())
