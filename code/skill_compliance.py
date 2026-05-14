"""合规自检Skill独立封装 - UP-204

将 compliance_checker.py 的 hard_check() 包装为 Skill 标准接口。
可在 Agent 生成回复后作为独立审核步骤调用。
"""
from loguru import logger
from code.compliance_checker import hard_check


def execute(params: dict, context: dict = None) -> dict:
    """
    合规自检Skill

    params:
        text: str — 待检查的文本
        current_node: str — 当前状态节点
        is_objection: bool — 是否是异议处理回复
        is_template: bool — 是否是KB模板直出

    returns:
        dict: {"passed": bool, "safe_text": str, "reason": str}
    """
    text = params.get("text", "")
    current_node = params.get("current_node", "icebreak")
    is_objection = params.get("is_objection", False)
    is_template = params.get("is_template", False)

    if not text.strip():
        return {"passed": True, "safe_text": text, "reason": "空文本"}

    is_safe, safe_text = hard_check(
        text,
        current_node=current_node,
        is_objection=is_objection,
        is_template=is_template,
    )

    if is_safe:
        logger.info(f"合规自检通过: node={current_node}, len={len(text)}")
        return {"passed": True, "safe_text": safe_text, "reason": ""}
    else:
        logger.warning(f"合规自检拦截: node={current_node}, original_len={len(text)}")
        return {
            "passed": False,
            "safe_text": safe_text,
            "reason": "触发合规拦截，已替换为安全话术",
        }


def get_skill_meta():
    """返回Skill元信息（供skill_registry注册）"""
    from code.skill_registry import SkillMeta
    return SkillMeta(
        name="compliance_check",
        description="合规自检：检查回复是否触发违禁词/阶段敏感词/动态红线",
        version="1.0",
        category="sales",
        applicable_stages=[
            "icebreak", "qualify", "match_campus", "show_fee",
            "invite", "report_info", "completed",
            "pre_assessment", "pre_training", "reject_qualify",
        ],
        timeout_seconds=5,
        max_retries=0,
    )
