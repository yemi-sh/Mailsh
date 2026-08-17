#!/usr/bin/env python3
"""
Mailsh - A robust command-line email sending client

This is now a simple entry point that delegates to the mailsh package.
"""

import sys
from mailsh_app.cli.shell import Mailsh


def main():
    """Entry point"""
    try:
        cli = Mailsh()
        cli.run()
    except KeyboardInterrupt:
        print("\n\nInterrupted. Goodbye! 👋")
        sys.exit(0)
    except Exception as e:
        print(f"\nFatal error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()