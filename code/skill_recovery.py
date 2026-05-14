"""挽回Skill独立封装 - UP-207

将 recovery_engine.py 增强为独立Skill。
融合电销中「逼单收尾」和「长期跟进」技巧。
"""
import json
from datetime import datetime, timedelta
from loguru import logger
from code.time_utils import get_beijing_time

# 挽回策略配置（增强版）
RECOVERY_STRATEGIES = {
    "price": {
        "approach": "强调零风险+ROI计算，先工作后付费",
        "hooks": [
            "费用的事我给你算笔账——前两月每月才1毛钱，入职后才开始付。你一个半月工资就回本，后面全是净赚。不就业不收费，你零风险。",
            "我发你一份费用明细——你看看分期方案，前两个月每月1毛钱，第3个月你已经在上班拿工资了。这个压力你能接受吧？",
        ],
        "delay_hours": 24,
        "max_attempts": 3,
    },
    "distance": {
        "approach": "强调住宿免费+短期投入换长期回报",
        "hooks": [
            "你告诉我你在哪，我帮你算下最近的校区。住宿我全包，拎包入住。一个半月换一辈子技术傍身，这趟路值得。",
            "远是暂时的，职业是长期的。广州杭州都有校区，学完深圳上海北京都能推荐就业。你只需要人过来就行。",
        ],
        "delay_hours": 48,
        "max_attempts": 3,
    },
    "time": {
        "approach": "提供灵活方案+时间ROI计算",
        "hooks": [
            "我们有白天班和晚班，前两周还能远程跟。我发你课程时间表，你看看哪个时间段能配合。一个半月忙一阵，换以后几十年轻松。",
            "忙说明你在努力生活，但忙一阵子换以后轻松，还是忙一辈子？时间挤一挤就有了。",
        ],
        "delay_hours": 72,
        "max_attempts": 3,
    },
    "hesitation": {
        "approach": "用案例打消顾虑+限时名额",
        "hooks": [
            "我发你几个跟你情况差不多的学员案例——32岁从工厂出来的、送外卖转行的、被裁后重新出发的，都在这边拿到结果了。你看完再决定。",
            "犹豫很正常，我发你一份零风险方案——不就业不收费，试听3天不满意随时走。你实在不放心，先来看看再说。",
        ],
        "delay_hours": 48,
        "max_attempts": 3,
    },
    "trust": {
        "approach": "重建信任+公开透明",
        "hooks": [
            "我理解你还有顾虑。这样——我开视频带你看看我们广州总部，看看真实的上课场景和学员状态。你看完了再做判断。",
            "实话跟你说，我们每个月300多学员从全国各地过来。如果是骗人的，早被报警了。你不放心的话，我发你营业执照和办学资质，自己核实。",
        ],
        "delay_hours": 24,
        "max_attempts": 2,
    },
    "silence": {
        "approach": "轻触回归+价值唤醒",
        "hooks": [
            "最近怎么样？分享个好消息——上周一个跟你情况差不多的学员，学完大数据在深圳拿到13K了。你最近还在看机会吗？",
            "宝子，最近网安岗位又放出一批新的，薪资比上季度涨了15%。你还有兴趣了解一下吗？",
        ],
        "delay_hours": 168,  # 7天
        "max_attempts": 5,
    },
}

# 不可挽回的情况（直接放弃）
NO_RECOVERY = {
    "legal_threat": "涉及法律威胁，不可挽回",
    "insult_repeated": "多次辱骂，加入黑名单",
    "explicit_opt_out": "明确要求删除数据/不再联系",
}


def should_recover(state: dict, intent: str) -> tuple:
    """判断是否应该挽回，返回 (should_recover: bool, reason: str)"""
    if intent in NO_RECOVERY:
        return False, NO_RECOVERY[intent]

    reject_count = state.get("_reject_count", 0)
    if reject_count >= 3:
        return False, f"拒绝次数已达{reject_count}次"

    trust = state.get("trust_level", 50)
    if trust < 15:
        return False, f"信任值过低({trust})"

    current_node = state.get("current_node", "")
    if current_node == "completed":
        return False, "已完成状态，不挽回"

    return True, ""


def classify_recovery_type(state: dict, intent: str, user_msg: str) -> str:
    """根据用户状态和意图分类挽回类型"""
    if intent == "objection_price":
        return "price"
    elif intent == "objection_distance":
        return "distance"
    elif intent == "objection_time":
        return "time"
    elif intent == "objection_consider":
        return "hesitation"
    elif intent in ("objection_institution", "objection_is_scam", "objection_negative_reviews"):
        return "trust"
    elif intent == "reject":
        if state.get("trust_level", 50) < 30:
            return "trust"
        return "hesitation"
    else:
        return "silence"


def get_recovery_hook(recovery_type: str, attempt: int) -> str:
    """获取挽回钩子话术"""
    strategy = RECOVERY_STRATEGIES.get(recovery_type, RECOVERY_STRATEGIES["silence"])
    hooks = strategy["hooks"]
    idx = min(attempt, len(hooks) - 1)
    return hooks[idx]


def execute(params: dict, context: dict = None) -> dict:
    """
    挽回Skill入口

    params:
        state: dict — 用户状态
        intent: str — 当前意图
        user_msg: str — 用户消息
        attempt: int — 当前尝试次数（可选）

    returns:
        dict: {
            "should_recover": bool,
            "recovery_type": str,
            "hook": str,
            "next_delay_hours": int,
            "reason": str,
        }
    """
    state = params.get("state", {})
    intent = params.get("intent", "reject")
    user_msg = params.get("user_msg", "")
    attempt = params.get("attempt", 0)

    should, reason = should_recover(state, intent)
    if not should:
        logger.info(f"不挽回: {reason}")
        return {
            "should_recover": False,
            "recovery_type": "",
            "hook": "",
            "next_delay_hours": 0,
            "reason": reason,
        }

    recovery_type = classify_recovery_type(state, intent, user_msg)
    hook = get_recovery_hook(recovery_type, attempt)
    strategy = RECOVERY_STRATEGIES.get(recovery_type, RECOVERY_STRATEGIES["silence"])
    next_delay = strategy["delay_hours"]

    logger.info(f"挽回策略: type={recovery_type}, attempt={attempt}, delay={next_delay}h")

    return {
        "should_recover": True,
        "recovery_type": recovery_type,
        "hook": hook,
        "next_delay_hours": next_delay,
        "strategy_approach": strategy["approach"],
        "reason": f"分类为{recovery_type}挽回",
    }


def get_skill_meta():
    """返回Skill元信息"""
    from code.skill_registry import SkillMeta
    return SkillMeta(
        name="recovery",
        description="对话挽回：6种挽回策略（价格/距离/时间/犹豫/信任/沉默），含智能分类和延迟调度",
        version="2.0",
        category="sales",
        applicable_stages=[
            "match_campus", "show_fee", "invite",
            "report_info", "reject_qualify",
        ],
        timeout_seconds=5,
        max_retries=0,
    )
