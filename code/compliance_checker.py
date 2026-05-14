"""合规硬拦截 - 修复版

主要修复:
1. 合规检查改为先缓冲后检查的架构（由 agent_core 调用方控制）
2. 从 config.yaml 读取 forbidden words（不再硬编码两份）
3. 阶段敏感拦截更精确
"""
import re
import yaml
from code import CONFIG_FILE

# 从配置文件加载合规规则
try:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        _cfg = yaml.safe_load(f)
    _redline = _cfg.get("redline_fence", {})
    GLOBAL_FORBIDDEN = _redline.get("global_forbidden", [
        "包就业", "100%就业", "保就业", "贷款", "分期贷", "助学贷",
        "100%上岗", "绝对保证",
        # P0: 隐性承诺词库增补
        "高薪", "高工资", "轻松月入", "月入过万", "年薪",
        "大厂", "名企", "头部企业", "上市公司直签",
        "学完就", "毕业就进", "入职没问题",
        "名额有限", "最后几个", "马上截止", "即将涨价",
        "保底", "保底薪资", "保薪", "保就业率",
    ])
    STAGE_FORBIDDEN = _redline.get("stage_forbidden", [
        "培训", "学费", "上课", "招生", "老师", "机构", "一定", "保证"
    ])
    EARLY_FORBIDDEN_NUMBERS = _redline.get("early_forbidden_numbers", [
        "19600", "25200", "3600", "免费实训", "保薪资XX元"
    ])
except Exception:
    # 降级默认值（与config.yaml保持同步）
    GLOBAL_FORBIDDEN = [
        "包就业", "100%就业", "保就业", "贷款", "分期贷", "助学贷",
        "100%上岗", "绝对保证", "学历造假", "学信网可查", "不用考试",
        # P0: 隐性承诺词库增补
        "高薪", "高工资", "轻松月入", "月入过万", "年薪",
        "大厂", "名企", "头部企业", "上市公司直签",
        "学完就", "毕业就进", "入职没问题",
        "名额有限", "最后几个", "马上截止", "即将涨价",
        "保底", "保底薪资", "保薪", "保就业率",
    ]
    STAGE_FORBIDDEN = [
        "培训", "学费", "上课", "招生", "老师", "机构", "一定", "保证"
    ]
    EARLY_FORBIDDEN_NUMBERS = [
        "19600", "25200", "3600", "免费实训", "保薪资XX元"
    ]

# 允许在这些阶段出现阶段敏感词（合法话术中包含"学费"等词）
FEE_STAGE_WHITELIST = {"show_fee", "invite", "reject_qualify"}


def _normalize(text):
    """去除空白和标点，用于模糊匹配（含~`等绕过字符）"""
    return re.sub(r"[\s\.\-\/|,，、。！？@#$%^&*()~`'\":;\+=\[\]{}<>«»…—]+", "", text)


def _get_fallback_message(trigger_type="global"):
    """分级兜底话术 - 每条末尾带邀约钩子"""
    fallbacks = {
        "global": (
            "这个问题涉及具体政策，我线上不方便说清楚。"
            "你来校区我给你看合同原文，上面写得明明白白。"
            "你平时周末方便还是工作日方便？"
        ),
        "stage_fee_sensitive": (
            "费用的事我们明明白白说。"
            "你来校区我给你看详细的费用方案和工作保障条款，你亲自看最放心。"
            "这周末有空吗？"
        ),
        "dynamic_redline": (
            "你提到的这个情况，我建议你来校区看看实际的教学环境和学员反馈，"
            "比我在线上说更有说服力。"
        ),
    }
    return fallbacks.get(trigger_type, fallbacks["global"])


def hard_check(text, current_node, is_objection=False, is_template=False):
    """
    合规硬检查
    返回: (is_safe, safe_text)
    - is_safe=True: 内容合规
    - is_safe=False: 内容违规，safe_text 为替换话术

    is_objection: 是否是异议处理回复，异议阶段豁免部分阶段敏感词
    is_template: 是否是KB模板直出（快速通道），模板只做全局违禁词检查
    """
    normalized = _normalize(text)

    # 全局违禁词检查（不可豁免）
    for w in GLOBAL_FORBIDDEN:
        if _normalize(w) in normalized:
            return False, _get_fallback_message("global")

    # 动态红线检查（不可豁免，补充正则无法覆盖的组合模式）
    from code.dynamic_redline import check as dynamic_check
    if dynamic_check(text):
        return False, _get_fallback_message("dynamic_redline")

    # KB模板直出（快速通道）：只检查全局违禁词+动态红线，跳过阶段敏感词
    if is_template:
        return True, text

    # 阶段敏感检查：仅在早期阶段（非收费展示阶段）拦截
    # 异议处理时豁免阶段敏感词（异议话术需要正面回应质疑，可能涉及"培训""机构"等词）
    if current_node not in FEE_STAGE_WHITELIST:
        stage_words = STAGE_FORBIDDEN + EARLY_FORBIDDEN_NUMBERS
        for w in stage_words:
            # 异议阶段豁免"机构""培训"（需要正面回应质疑）
            if is_objection and w in ("机构", "培训"):
                continue
            # 身份澄清豁免：允许说"不是培训机构"等否定句式
            if w in ("培训", "机构", "老师", "学校"):
                if any(p in normalized for p in ["不是培训", "不是机构", "不是学校", "不是老师", "非培训", "非机构"]):
                    continue
            if _normalize(w) in normalized:
                return False, _get_fallback_message("stage_fee_sensitive")

    return True, text
