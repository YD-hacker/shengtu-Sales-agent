"""意图分类器 - 智能升级版

升级点:
1. 正则快速匹配（第一层）+ LLM深度理解（第二层）
2. 多意图返回（主意图 + 次要意图 + 置信度）
3. 新增 request_human 意图
4. 意图冲突检测和优先级处理
5. 意图历史追踪
"""
import re
import json
from loguru import logger

# ---- 意图优先级（数值越大优先级越高）----
INTENT_PRIORITY = {
    "user_frustration": 100,
    "request_human": 95,
    "correct_info": 90,
    "express_pain": 80,
    "reject": 75,
    "objection_consider": 70,
    "objection_learn": 70,
    "objection_time": 70,
    "objection_distance": 70,
    "objection_institution": 70,
    "objection_price": 70,
    "confirm": 60,
    "fee_intent": 55,
    "icebreak_greet": 50,
    "experienced": 45,
    "newbie": 45,
    "normal": 30,
    "off_topic": 10,
}

# ---- 正则快速匹配规则 ----
REGEX_RULES = [
    # 情绪优先
    {
        "pattern": r"(说了.*遍|又说|重复|问过|烦不烦|够了|没听清|这些我都)",
        "intent": "user_frustration",
        "confidence": 0.9,
    },
    # 人工接管
    {
        "pattern": r"(转人工|找人工|人工客服|换人聊|跟真人|跟人聊|不想跟机器|"
                    r"不是机器人吧|你是机器人吗|有没有真人|让真人来|叫人|找销售|找老师|领导|主管|经理|负责人|太套路|不像真人)",
        "intent": "request_human",
        "confidence": 0.95,
    },
    # 信息纠正
    {
        "pattern": r"(说错|纠正|搞错|其实是|我纠正|更正|更正一下|搞错了|不对[，,]是|不是[，,]是)",
        "intent": "correct_info",
        "confidence": 0.85,
    },
    {
        "pattern": r"我(?:的)?(?:是|学历)[是为]?[，,]?(?:统招)?(?:本科|大专|硕士)",
        "intent": "correct_info",
        "confidence": 0.8,
    },
    # 痛点表达
    {
        "pattern": r"(年纪大|年龄大|岁数|老了|在厂里|工厂|流水线|送外卖|跑滴滴|保安|"
                    r"没出路|看不到希望|不甘心|不想再|受够了|被裁|裁员|失业|找不到|"
                    r"混不下去|温水煮青蛙|怕学不会|担心跟不上|怕来不及|犹豫.*转行|不敢.*辞职|被骗|上当|被坑|割韭菜|失业|交不起|付不起|扛不住|撑不下去)",
        "intent": "express_pain",
        "confidence": 0.85,
    },
    # 异议类
    {
        "pattern": r"(再想想|再看看|不放心|让我考虑|再考虑|还在考虑|考虑一下|犹豫下)",
        "intent": "objection_consider",
        "confidence": 0.8,
    },
    {
        "pattern": r"(学不会|难不难|零基础.*怕|没基础|太难|跟不上|能学会吗|能学得会|学得会吗|怕学不好)",
        "intent": "objection_learn",
        "confidence": 0.8,
    },
    {
        "pattern": r"(没时间|太忙|加班|请不了假|走不开|忙不过来|多久|几个月|时间.*长|太久了|耗.*时间|四个月.*久)",
        "intent": "objection_time",
        "confidence": 0.8,
    },
    {
        "pattern": r"(太远|距离|远不远|不方便过去|外地)",
        "intent": "objection_distance",
        "confidence": 0.8,
    },
    {
        "pattern": r"(培训机构|机构|公司|你们是做什么的|你们靠谱吗|是不是骗人|骗|忽悠|割韭菜|你是谁|你是干什么|你做什么的|你怎么加到我|怎么加到我的|你谁啊|干嘛的|搜不到.*信息|网上.*搜不到|查不到.*公司|公司.*在哪|你们.*地址|文字游戏|合同.*漏洞)",
        "intent": "objection_institution",
        "confidence": 0.8,
    },
    {
        "pattern": r"(太贵|贵了|付不起|没钱|承担不起|不值得|不值这个价|怎么这么贵)",
        "intent": "objection_price",
        "confidence": 0.85,
    },
    # 拒绝
    {
        "pattern": r"(不用了|算了|不要|不去了|不学|不感兴趣|别发了|别再|拉黑|退订|"
                    r"不需要|不用|不想|别找我|免了|拉倒|再见|拜拜|打扰了|不了)",
        "intent": "reject",
        "confidence": 0.9,
    },
    # 费用意图
    {
        "pattern": r"(收费|多少钱|费用|价格|付款|19600|25200|分期|要钱|付钱|怎么付|怎么收)",
        "intent": "fee_intent",
        "confidence": 0.85,
    },
    # 业务意图
    {
        "pattern": r"(有.*(经验|工作经验|项目)|做过|干过|从事|在职|正在做|应聘|求职|内推|找工|跳槽|岗位|职位)",
        "intent": "experienced",
        "confidence": 0.8,
    },
    {
        "pattern": r"(转行|零基础|没经验|想学|学习|小白|不会|没学过|改行|重新学|入门|从零)",
        "intent": "newbie",
        "confidence": 0.8,
    },
    # 访问意向（周末去看看、去试试等）
    {
        "pattern": r"(?:周末|周[一二三四五六日]|明天|后天|今天|这周|下周|上午|下午|晚上|中午).*(?:去|过来|到).*(?:看|试|瞧|了解)",
        "intent": "confirm",
        "confidence": 0.85,
    },
    {
        "pattern": r"(?:去看看|去试试|过去看看|过去瞧瞧|去看下|了解下|看下|试试看)",
        "intent": "confirm",
        "confidence": 0.8,
    },
    {
        "pattern": r"(?:考虑|想).*(?:周末|下周|明天|后天|这周).*(?:去|过来|到)",
        "intent": "confirm",
        "confidence": 0.8,
    },
    # 扩展确认（好的没问题、那行吧等）
    {
        "pattern": r"(?:好的|行|成|中).*(?:没问题|可以|行|好)",
        "intent": "confirm",
        "confidence": 0.85,
    },
]

# ---- 确认意图规则（特殊处理）----
CONFIRM_PATTERN = re.compile(
    r"(?:(?:周末|周[一二三四五六日]|明天|后天|今天|这周|下周|上午|下午|晚上|中午)?\s*)?"
    r"(?:嗯|可以|行|好的|OK|没问题|了解|明白了|对|是的|是|好|对的|没错|同意|"
    r"没问题啊|好呀|行啊|OK啊|走起|来吧|行吧|嗯嗯|好嘞|妥|妥了|当然|必须的|"
    r"那行|成|中|好哦|好哒|嗯呢|嗯啊|欧了|欧克|ok的|可以啊|行哒|行的)"
    r"(?:\s*(?:去看看|去试试|过去看看|过去瞧瞧|看看|试试|瞧瞧))?\s*[!！。.~～，,]*$",
    re.IGNORECASE,
)


DENY_WORDS = re.compile(r"(不|没|别|非|未|算)")

# ---- 问候规则 ----
GREET_PATTERN = re.compile(
    r"(你好|hi|hello|在吗|在不在|在不|嗨|早上好|下午好|晚上好|hey)[\s!！。.呀哦呐嘞嗯吧啊]*",
    re.IGNORECASE,
)

# ---- 业务关键词 ----
BIZ_KEYWORDS = [
    "网安", "大数据", "转行", "学习", "培训", "就业", "工作", "求职", "内推",
    "学历", "大专", "本科", "毕业", "年龄", "城市", "经验", "年限", "收费",
    "费用", "多少钱", "分期", "学信网", "截图", "保障", "合同", "校区", "试听",
    "考核", "岗位", "职位", "机构", "公司", "实训", "报名", "开课", "班",
    "住宿", "周二", "周末", "过来", "去哪", "安排", "专业", "方向",
]


def _regex_classify(msg: str) -> tuple:
    """第一层：正则快速匹配，返回 (intent, confidence)"""
    # 检查确认意图（特殊处理）
    if not DENY_WORDS.search(msg) and CONFIRM_PATTERN.fullmatch(msg.strip()):
        return "confirm", 0.9

    # 数字回复
    if re.fullmatch(r"[1-9]\s*", msg):
        return "confirm", 0.85

    # 问候
    if GREET_PATTERN.fullmatch(msg.strip()):
        return "icebreak_greet", 0.9

    # 规则匹配
    matched_intents = []
    for rule in REGEX_RULES:
        if re.search(rule["pattern"], msg):
            matched_intents.append((rule["intent"], rule["confidence"]))

    if matched_intents:
        # 返回优先级最高的意图
        matched_intents.sort(key=lambda x: INTENT_PRIORITY.get(x[0], 0), reverse=True)
        return matched_intents[0]

    # 业务关键词检查
    if any(kw in msg for kw in BIZ_KEYWORDS):
        return "normal", 0.6

    return "off_topic", 0.5


async def _llm_classify(msg: str, current_state: str, collected_slots: dict) -> tuple:
    """第二层：LLM深度理解，返回 (intent, confidence)"""
    try:
        from code.model_router import call_model

        slot_summary = ", ".join(
            f"{k}={v}" for k, v in collected_slots.items() if v
        ) or "无"

        prompt = f"""你是一个意图分类器。根据用户的消息和当前对话阶段，输出最可能的意图。

当前阶段：{current_state}
已收集信息：{slot_summary}
用户消息：{msg}

意图类型：
- confirm: 确认、同意、答应
- reject: 拒绝、不感兴趣、退订
- request_human: 要求转人工、找真人
- objection_consider: 犹豫、再想想、考虑
- objection_learn: 担心学不会、怕跟不上
- objection_time: 没时间、太忙
- objection_distance: 太远、不方便
- objection_institution: 不信任机构、怀疑
- objection_price: 觉得贵、付不起
- express_pain: 表达困境（工厂、被裁、不甘心等）
- user_frustration: 不耐烦、重复说过的话
- correct_info: 纠正之前的信息
- fee_intent: 问费用、价格
- newbie: 零基础想学
- experienced: 有经验想内推
- off_topic: 完全无关话题
- normal: 一般业务相关

只输出JSON：{{"intent": "意图类型", "confidence": 0.0-1.0}}"""

        result = call_model(prompt, 0.1)
        # 尝试解析JSON
        result = result.strip()
        if result.startswith("```"):
            result = result.split("```")[1]
            if result.startswith("json"):
                result = result[4:]
        parsed = json.loads(result)
        intent = parsed.get("intent", "normal")
        confidence = parsed.get("confidence", 0.5)
        return intent, confidence
    except Exception as e:
        logger.debug(f"LLM意图分类失败: {e}")
        return "normal", 0.3


def classify(msg: str, current_state: str = "", collected_slots: dict = None) -> dict:
    """意图分类入口，返回 {intent, confidence, method, all_intents}"""
    msg = msg.strip()
    if not msg:
        return {"intent": "off_topic", "confidence": 1.0, "method": "empty", "all_intents": []}

    logger.info(f"意图分类: {msg[:50]}")

    # 第一层：正则快速匹配
    regex_intent, regex_confidence = _regex_classify(msg)

    # 如果正则置信度高，直接返回
    if regex_confidence >= 0.8:
        result = {
            "intent": regex_intent,
            "confidence": regex_confidence,
            "method": "regex",
            "all_intents": [(regex_intent, regex_confidence)],
        }
        logger.info(f"  -> {regex_intent} (confidence={regex_confidence}, method=regex)")
        return result

    # 第二层：正则不确定时，尝试LLM分类
    if regex_confidence < 0.7 and len(msg) > 5:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在异步上下文中，跳过LLM（避免嵌套事件循环）
                llm_intent, llm_confidence = regex_intent, regex_confidence
            else:
                llm_intent, llm_confidence = loop.run_until_complete(
                    _llm_classify(msg, current_state, collected_slots or {})
                )
        except Exception:
            llm_intent, llm_confidence = regex_intent, regex_confidence

        # 取置信度更高的结果
        if llm_confidence > regex_confidence:
            result = {
                "intent": llm_intent,
                "confidence": llm_confidence,
                "method": "llm",
                "all_intents": [
                    (regex_intent, regex_confidence),
                    (llm_intent, llm_confidence),
                ],
            }
            logger.info(f"  -> {llm_intent} (confidence={llm_confidence}, method=llm, regex={regex_intent})")
            return result

    result = {
        "intent": regex_intent,
        "confidence": regex_confidence,
        "method": "regex",
        "all_intents": [(regex_intent, regex_confidence)],
    }
    logger.info(f"  -> {regex_intent} (confidence={regex_confidence}, method=regex)")
    return result


def classify_simple(msg: str) -> str:
    """简化版分类（兼容旧接口）"""
    result = classify(msg)
    return result["intent"]


def get_multi_intents(msg: str, current_state: str = "") -> list:
    """获取多个可能的意图（用于多意图处理）"""
    result = classify(msg, current_state)
    all_intents = result.get("all_intents", [])

    # 如果只有一个意图，尝试用正则找第二个
    if len(all_intents) <= 1:
        secondary = []
        for rule in REGEX_RULES:
            if re.search(rule["pattern"], msg) and rule["intent"] != result["intent"]:
                secondary.append((rule["intent"], rule["confidence"] * 0.8))
        all_intents.extend(secondary)

    # 按置信度排序
    all_intents.sort(key=lambda x: x[1], reverse=True)
    return all_intents[:3]  # 最多返回3个
