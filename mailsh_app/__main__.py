"""
Entry point for running Mailsh as a module (python -m mailsh).
"""

import sys
from .cli.shell import Mailsh


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