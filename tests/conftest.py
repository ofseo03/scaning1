"""pytest 공통 설정."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))
# 브랜치 라우팅 규칙도 테스트 대상이다.
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
