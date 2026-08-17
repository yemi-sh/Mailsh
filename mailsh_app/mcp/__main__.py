"""
Entry point for running the Mailsh MCP server.

This module provides the entry point to run the MCP server as a module.
"""

import sys
import os
from pathlib import Path

# Add the parent directory to the Python path to resolve imports correctly
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mailsh_app.mcp.server import main

if __name__ == "__main__":
    main()