import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


def main() -> int:
    """从源码目录运行包内 CLI。"""
    sys.path.insert(0, str(SRC_DIR))
    from text_to_sql_demo.db.init_db import main as package_main

    return package_main()


if __name__ == "__main__":
    raise SystemExit(main())
