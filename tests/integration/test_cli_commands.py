import subprocess
import sys
from pathlib import Path


def test_init_db_script_creates_database(tmp_path: Path) -> None:
    db_path = tmp_path / "demo.db"
    project_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [
            sys.executable,
            "scripts/init_db.py",
            "--db-path",
            str(db_path),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert db_path.exists()
    assert "已初始化电商 demo 数据库" in result.stdout
