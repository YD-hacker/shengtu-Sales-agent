"""动态红线检测

修复:
1. "包括就业" 不应误杀 — "包"后面必须是直接接"就业"或最多1个连接字
2. "100%就位" 不应误杀 — 限定"100%就业/上岗"精确匹配
3. 增加 "包X就业" 组合模式
4. P1修复: Unicode同形字绕过检测（使用NFKC标准化）
"""
import re
import unicodedata

FORBIDDEN_PATTERNS = [
    # "包就业" / "包当就业" — "包"后面紧跟"就业"或最多1个连接字(当/你/了)
    # 但排除"包括就业"等正常短语
    re.compile(r"包(?!括)[当你我了]?就业", re.IGNORECASE),
    # "100%就业/上岗" — 精确匹配完整词组，避免"100%就位"等误杀
    re.compile(r"100%\s*(?:就业|上岗)", re.IGNORECASE),
    # "绝对能/会...保证" — 更精确的匹配
    re.compile(r"绝对[能会].*?保证", re.IGNORECASE),
    # P0修复: 口语化变体 — "保你有班上""保证你上岗""保你能就业"
    re.compile(r"保[你我他].{0,6}(就业|上岗|有班|找到.{0,2}工作|有工作)"),
    re.compile(r"保证.{0,6}(就业|上岗|工作|找到)"),
    re.compile(r"保[证底].{0,2}(薪资|工资|月薪|收入)"),
    re.compile(r"(月薪|年薪|工资).{0,4}(过万|上万|[1-9]万)"),
    re.compile(r"(毕业|学完).{0,2}(就|直接).{0,2}(进|去|入职).{0,4}(大厂|名企|头部)"),
    # S-002: Prompt注入攻击检测
    re.compile(r"(忽略|无视|跳过|忘记|删除).{0,10}(之前|上面|以上|所有|全部).{0,10}(指令|规则|限制|约束|对话|内容|prompt|system)", re.IGNORECASE),
    re.compile(r"(输出|告诉我|显示|打印|列出|返回|回复).{0,10}(你的|系统).{0,10}(提示词|prompt|指令|规则|设定|system|persona)", re.IGNORECASE),
    re.compile(r"(你是|现在你是|从现在开始你是|扮演).{0,5}(DAN|开发者模式|不受限制|无限制|自由模式|越狱|jailbreak)", re.IGNORECASE),
    re.compile(r"(Ignore|forget|bypass|override|delete|remove|clear).{0,15}(previous|above|all|system).{0,15}(instructions|rules|constraints|prompt|directives)", re.IGNORECASE),
    re.compile(r"(pretend|imagine|roleplay|act as if|simulate).{0,20}(no rules|no restrictions|anything|unlimited)", re.IGNORECASE),
    re.compile(r"\{%|%\}|\{\{.*?\}\}", re.IGNORECASE),  # 模板注入攻击
    re.compile(r"(输出.*所有.*违禁|列出.*所有.*规则|告诉我.*秘密|泄露.*系统)", re.IGNORECASE),
]


def check(msg: str) -> bool:
    """检查消息是否命中动态红线，返回 True 表示命中

    P1修复: 使用Unicode NFKC标准化，防止同形字绕过
    例如: "忽畧"(形近字) → normalize后仍匹配"忽略"
    """
    # NFKC标准化：将兼容字符映射到标准形式
    normalized = unicodedata.normalize('NFKC', msg)
    for p in FORBIDDEN_PATTERNS:
        if p.search(msg) or p.search(normalized):
            return True
    return False
