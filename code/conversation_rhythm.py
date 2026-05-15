"""对话节奏引擎 — 消除机器人感

核心设计:
1. 回复前可变延迟（模拟「读消息→思考→组织语言」）
2. 逐字输出 + 标点处自然停顿（模拟真人打字节奏）
3. 长回复自动分段（模拟真人不会一次发200字）
4. 结尾钩子（每次回复抛一个反问/引导，避免对话冷场）

策略来源:
- 顶级AI销售Agent的体验设计实践
- 真人微信聊天行为模式分析
"""
import asyncio
import random
import re

# ══════════════════════════════════════════
# 初始延迟配置（秒）
# format: (min, max) — 每个状态一个区间
# ══════════════════════════════════════════
INITIAL_DELAYS = {
    "icebreak":       (1.5, 2.5),   # 破冰：稍慢，像在组织语言
    "qualify":        (0.8, 1.5),   # 问信息：正常对话节奏
    "match_campus":   (0.8, 1.5),   # 校区匹配：正常
    "show_fee":       (2.0, 3.0),   # 报价：放慢，给用户时间消化
    "invite":         (0.8, 1.8),   # 邀约：正常偏快，有决断感
    "report_info":    (0.5, 1.2),   # 报备：快，事务性
    "completed":      (0.5, 1.0),   # 完成：快
    "reject_qualify": (1.5, 2.5),   # 拒绝告知：慢，需要共情
    "pre_assessment": (1.0, 2.0),   # 岗前考核：中等
    "pre_training":   (1.0, 2.0),   # 岗前实训：中等
    "default":        (0.8, 1.5),
}

# 异议处理阶段额外增加的延迟（秒）
OBJECTION_EXTRA_DELAY = (1.0, 2.0)

# ══════════════════════════════════════════
# 字符间延迟配置（秒）
# ══════════════════════════════════════════
CHAR_DELAY_BASE = (0.015, 0.04)      # 基础打字速度
CHAR_DELAY_COMMA = (0.08, 0.18)      # 逗号/顿号/省略号处停顿
CHAR_DELAY_PERIOD = (0.15, 0.35)     # 句号/问号/感叹号处停顿
CHAR_DELAY_AFTER_NUMBER = (0.03, 0.06) # 数字后稍慢（用户需要看清）

# ══════════════════════════════════════════
# 分段阈值（字符数）
# ══════════════════════════════════════════
SEGMENT_MAX_CHARS = 80     # 单段最长字符（超过则强制分段）
SEGMENT_MIN_CHARS = 30     # 分段最短字符（短于此不强制分）
SEGMENT_BREAK_DELAY = (1.0, 2.0)  # 段间延迟

# ══════════════════════════════════════════
# 钩子话术（每个状态补充反问/引导，避免冷场）
# ══════════════════════════════════════════
HOOKS = {
    "icebreak":    ["你之前有了解过网络安全或者大数据吗？"],
    "qualify":     [
        "方便说下你哪年毕业的吗？",
        "你在哪个城市呢？",
        "想学网安还是大数据？",
    ],
    "match_campus": ["你看这个安排方便吗？"],
    "show_fee":     [
        "你觉得这个方案能接受吗？",
        "有什么想问的随时说。",
        "你看看还有什么顾虑？",
    ],
    "invite":       [
        "这周二还是周末方便过来？",
        "我先帮你留个位置？",
        "你定个时间，我帮你安排好。",
    ],
    "report_info":  [
        "名字和电话发我就行。",
        "你先发名字和手机号，其他的来了再补。",
    ],
    "completed":    [
        "有消息我第一时间跟你说。",
        "有什么问题随时找我。",
    ],
    "reject_qualify": ["你看要不要了解一下非保障班？"],
    "pre_assessment": ["这周方便过来做个技术评估吗？"],
}


def _r(min_val: float, max_val: float) -> float:
    """返回区间内随机浮点数"""
    return min_val + random.random() * (max_val - min_val)


def get_initial_delay(node: str, is_objection: bool = False, intent: str = "") -> float:
    """获取回复前初始延迟（模拟思考和读消息）

    根据意图复杂度动态调整：
    - 简单确认（confirm/icebreak_greet）：快速回复
    - 情绪类（express_pain/user_frustration）：稍慢，像在想怎么安慰
    - 异议类：更慢，像在组织论据
    - 费用相关：慢，像在查资料
    """
    base = INITIAL_DELAYS.get(node, INITIAL_DELAYS["default"])
    delay = _r(*base)

    # 意图复杂度调整
    if intent in ("confirm", "icebreak_greet"):
        delay *= 0.5  # 简单确认，快速回复
    elif intent in ("express_pain", "user_frustration"):
        delay *= 1.3  # 情绪回应，稍慢
    elif intent in ("fee_intent", "competitive_inquiry"):
        delay *= 1.4  # 需要查信息，更慢
    elif intent == "correct_info":
        delay *= 0.8  # 纠正信息，中等偏快

    if is_objection:
        delay += _r(*OBJECTION_EXTRA_DELAY)
    return delay


def get_char_delay(char: str, next_char: str = "") -> float:
    """获取逐字输出间隔（模拟打字节奏）"""
    if char in "，、…":
        return _r(*CHAR_DELAY_COMMA)
    if char in "。？！；：.!?;:":
        return _r(*CHAR_DELAY_PERIOD)
    if char.isdigit():
        # 数字后稍慢一点（价格等需要看清）
        if next_char.isdigit():
            return _r(*CHAR_DELAY_BASE)  # 连续数字正常
        return _r(*CHAR_DELAY_AFTER_NUMBER)
    return _r(*CHAR_DELAY_BASE)


def split_into_segments(text: str, max_chars: int = SEGMENT_MAX_CHARS) -> list:
    """将长回复按语义边界分段

    优先在句号处断开，其次逗号，最后字符数强制断开。
    返回分段列表。
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    segments = []
    remaining = text

    while len(remaining) > max_chars:
        # 在max_chars附近找最佳断点
        chunk = remaining[:max_chars]

        # 优先在句号/问号/感叹号处断开
        for sep in "。？！\n":
            idx = chunk.rfind(sep)
            if idx >= SEGMENT_MIN_CHARS:
                segments.append(remaining[:idx + 1].strip())
                remaining = remaining[idx + 1:].strip()
                break
        else:
            # 其次在逗号处断开
            idx = chunk.rfind("，")
            if idx >= SEGMENT_MIN_CHARS:
                segments.append(remaining[:idx + 1].strip())
                remaining = remaining[idx + 1:].strip()
            else:
                # 强制从max_chars断开
                # 回退到最后一个完整字符（避免截断中文字符）
                segments.append(remaining[:max_chars].strip())
                remaining = remaining[max_chars:].strip()

    if remaining:
        segments.append(remaining)

    return segments


def get_hook(node: str, state: dict = None) -> str:
    """获取结尾钩子（抛反问/引导，避免冷场）"""
    hooks = HOOKS.get(node, [])
    if not hooks:
        return ""

    # 根据已收集的槽位信息选择最合适的钩子
    if node == "qualify" and state:
        if not state.get("education"):
            return "你的学历是统招大专还是本科呀？"
        if not state.get("age"):
            return "你今年多大啦？方便说下年龄吗？"
        if not state.get("graduated_year"):
            return "你哪年毕业的呀？"
        if not state.get("city"):
            return "你现在在哪个城市呢？"
        if not state.get("direction"):
            return "想学网安还是大数据方向？"

    return random.choice(hooks)


async def humanize_output(text: str, node: str, is_objection: bool = False, intent: str = ""):
    """人性化输出生成器

    模拟真人回复节奏：
    1. 初始「读消息+思考」延迟
    2. 逐字输出 + 标点处自然停顿
    3. 长回复自动分段 + 段间停顿
    4. 结尾留钩子

    用法:
        async for chunk in humanize_output(text, node, is_objection):
            yield chunk
    """
    if not text:
        return

    # 1. 初始延迟（模拟思考和读消息）
    initial_delay = get_initial_delay(node, is_objection, intent)
    yield ""  # 空chunk触发「正在输入」状态
    await asyncio.sleep(initial_delay)

    # 2. 判断是否需要分段
    segments = split_into_segments(text)

    # 3. 逐段输出，段内逐字
    for seg_idx, segment in enumerate(segments):
        # 段间停顿（模拟发完一条、想一下、再发下一条）
        if seg_idx > 0:
            await asyncio.sleep(_r(*SEGMENT_BREAK_DELAY))
            yield ""  # 段落分隔信号

        chars = list(segment)
        for i, char in enumerate(chars):
            next_char = chars[i + 1] if i + 1 < len(chars) else ""
            yield char
            delay = get_char_delay(char, next_char)
            await asyncio.sleep(delay)

    # 如果只有一段且较短，补一个自然收尾停顿
    if len(segments) == 1 and len(text) < 60:
        await asyncio.sleep(_r(0.3, 0.6))


def inject_hook(text: str, node: str, state: dict = None) -> str:
    """在回复末尾注入钩子反问（如果合适）"""
    # 破冰阶段不注入钩子（第一次打招呼就反问很突兀）
    if node == "icebreak":
        return text

    # 已完成/报备阶段不注入
    if node in ("completed", "report_info"):
        return text

    # qualify阶段：如果所有槽位已填满，不注入
    if node == "qualify" and state:
        required = ["education", "age", "graduated_year", "city", "direction"]
        all_filled = all(state.get(k) for k in required)
        if all_filled:
            return text

    hook = get_hook(node, state)
    if not hook:
        return text

    # 避免重复——如果已有类似引导，不再追加
    text_stripped = text.rstrip()
    if any(text_stripped.endswith(q) for q in ["？", "?", "吗", "呢"]):
        return text  # 已经以问题结尾，不追加

    # 避免太长——如果文本已经超过120字，不追加
    if len(text) > 120:
        return text

    return f"{text_stripped}\n{hook}"
