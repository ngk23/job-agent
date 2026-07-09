"""Allow running agent package directly with: python -m agent"""

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
