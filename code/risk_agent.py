"""风控搭子雏形 - UP-212

独立线程审核输出 + "否决→重生成"闭环
在主Agent生成回复后，异步审核是否合规/安全，不合规则触发重生成。
"""
import threading
import time
from loguru import logger

# 审核结果
AUDIT_PASS = "pass"
AUDIT_VETO = "veto"
AUDIT_WARN = "warn"


def audit_reply(reply: str, state: dict, intent: str) -> dict:
    """
    审核主Agent生成的回复
    返回 {"verdict": "pass"|"veto"|"warn", "reason": str, "suggested_fix": str}
    """
    reasons = []
    suggested_fix = ""

    # 1. 违禁词检查
    forbidden_words = ["培训", "学费", "上课", "招生", "老师", "机构", "保证就业", "包就业"]
    found_forbidden = [w for w in forbidden_words if w in reply]
    if found_forbidden:
        reasons.append(f"含违禁词: {found_forbidden}")
        for w in found_forbidden:
            reply = reply.replace(w, "服务")

    # 2. 过长检查
    if len(reply) > 300:
        reasons.append(f"回复过长({len(reply)}字符)")

    # 3. 敏感数字检查（禁止具体金额）
    import re
    if re.search(r'\d{3,}元|\d+万', reply):
        # 允许在特定阶段
        current_node = state.get("current_node", "")
        if current_node not in ("show_fee", ""):
            reasons.append("非费用阶段出现金额数字")
            suggested_fix = "避免在非费用阶段提及具体金额"

    # 4. 承诺检查
    commitment_words = ["保证", "一定", "肯定能", "百分百", "绝对"]
    found_commit = [w for w in commitment_words if w in reply]
    if found_commit:
        reasons.append(f"含承诺性词汇: {found_commit}")

    # 5. 竞品名称检查
    competitor_names = ["达内", "黑马", "千锋", "北大青鸟"]
    found_competitors = [w for w in competitor_names if w in reply]
    if found_competitors:
        reasons.append(f"含竞品名称: {found_competitors}")

    if not reasons:
        return {"verdict": AUDIT_PASS, "reason": "", "suggested_fix": ""}
    elif len(reasons) == 1 and "过长" in reasons[0]:
        return {"verdict": AUDIT_WARN, "reason": "; ".join(reasons), "suggested_fix": suggested_fix}
    else:
        return {"verdict": AUDIT_VETO, "reason": "; ".join(reasons), "suggested_fix": suggested_fix}


def audit_reply_async(reply: str, state: dict, intent: str, callback=None):
    """异步审核：在独立线程中执行审核，通过回调通知结果"""
    result = {"verdict": AUDIT_PASS, "reason": "", "suggested_fix": ""}

    def _audit():
        nonlocal result
        result = audit_reply(reply, state, intent)
        if callback:
            callback(result)

    t = threading.Thread(target=_audit, daemon=True)
    t.start()
    # 等待最多3秒
    t.join(timeout=3)
    if t.is_alive():
        logger.warning("风控审核超时(3s)，默认放行")
        return {"verdict": AUDIT_PASS, "reason": "审核超时", "suggested_fix": ""}
    return result


def generate_safe_fallback(state: dict, original_reply: str, audit_result: dict) -> str:
    """当审核否决时，生成安全的兜底回复"""
    node = state.get("current_node", "icebreak")
    fallbacks = {
        "icebreak": "你好，我是小范，做IT人才服务6年了。你是想零基础转行学门技术，还是已经有经验想直接内推？",
        "qualify": "我先了解下你的基本情况——学历是统招大专还是本科？哪年毕业？多大了？在哪个城市？",
        "match_campus": "我帮你看看最近的校区，方便说说你在哪个城市吗？",
        "show_fee": "费用这块，我建议你来校区当面了解，合同上写得明明白白。",
        "invite": "这周末方便来校区看看吗？实地了解下环境。",
        "report_info": "方便把你的姓名和电话发给我吗？我帮你登记一下。",
        "completed": "好的，你的信息我已收到，我们会尽快联系你。",
    }
    fallback = fallbacks.get(node, "这个问题我建议你来校区当面聊，会更清楚。")
    logger.info(f"风控否决回复，使用兜底话术。原因: {audit_result.get('reason', '')}")
    return fallback
