"""Build the bundled Vite frontend only when it is missing."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


WEB_DIR = Path(__file__).resolve().parents[1] / "web"
DIST_DIR = WEB_DIR / "dist"


def ensure_frontend_built() -> None:
    if (DIST_DIR / "index.html").is_file():
        return
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            "未找到 Node.js/npm。请安装 Node.js 20+，然后在 web 目录运行 `npm install`，再重新执行 stock-data run。"
        )
    if not (WEB_DIR / "node_modules").is_dir():
        raise RuntimeError(
            "前端依赖尚未安装。请运行：`cd web && npm install`，完成后重新执行 stock-data run。"
        )
    try:
        subprocess.run([npm, "run", "build"], cwd=WEB_DIR, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("前端构建失败。请在 web 目录运行 `npm run build` 查看详细错误。") from exc
