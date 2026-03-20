from pathlib import Path
import subprocess
import sys


def test_demo_backtest_runs():
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "trading_bot.cli", "backtest", "--config", str(root / "examples" / "config" / "demo.yaml")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Backtest finished" in proc.stdout
