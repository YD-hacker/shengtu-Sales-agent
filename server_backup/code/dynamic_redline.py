"""动态红线检测

修复:
1. "包括就业" 不应误杀 — "包"后面必须是直接接"就业"或最多1个连接字
2. "100%就位" 不应误杀 — 限定"100%就业/上岗"精确匹配
3. 增加 "包X就业" 组合模式
"""
import re

FORBIDDEN_PATTERNS = [
    # "包就业" / "包当就业" — "包"后面紧跟"就业"或最多1个连接字(当/你/了)
    # 但排除"包括就业"等正常短语
    re.compile(r"包(?!括)[当你我了]?就业", re.IGNORECASE),
    # "100%就业/上岗" — 精确匹配完整词组，避免"100%就位"等误杀
    re.compile(r"100%\s*(?:就业|上岗)", re.IGNORECASE),
    # "绝对能/会...保证" — 更精确的匹配
    re.compile(r"绝对[能会].*?保证", re.IGNORECASE),
]


def check(msg: str) -> bool:
    """检查消息是否命中动态红线，返回 True 表示命中"""
    for p in FORBIDDEN_PATTERNS:
        if p.search(msg):
            return True
    return False
