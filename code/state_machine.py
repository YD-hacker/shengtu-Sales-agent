"""严格状态机 + 资格判定 + 信任门禁 + 问题诊断 - 智能升级版

核心升级:
1. 人设"小范"——话术从KB配置读取，代码零硬编码
2. 信任门禁：trust_level 不够时阻止状态跳转
3. 痛点追踪：express_pain 意图记录痛点，先共情再继续
4. 异议5步法：所有 objection_ 意图经过 共情→探因→举证→重构→行动
5. 信任不足时的死锁防护：提供"信任修复路径"
6. 话术全部从 knowledge_base.yaml 读取，修改话术无需改代码
7. 动态异议策略：根据decision_engine策略模式调整回应方式
8. 个性化话术：根据用户画像生成针对性内容
"""
import yaml
from loguru import logger
from code.time_utils import get_beijing_time
from code.trust_engine import can_advance_to, get_trust_gate_message
from code import KB_FILE

with open(KB_FILE, encoding="utf-8") as f:
    KB = yaml.safe_load(f)["scripts"]

REPORT_SLOTS = [
    "name", "gender", "education", "graduation_time", "major",
    "target_position", "phone", "departure_city", "campus_base",
    "arrival_time", "need_accommodation", "remarks"
]
REGULAR_SLOTS = ["education", "age", "graduated_year", "city", "direction"]

# 痛点关键词 → 标签映射
PAIN_KEYWORDS = {
    "age_too_old": ["年纪大", "年龄大", "岁数", "老了", "30多", "30几"],
    "factory_worker": ["在厂里", "工厂", "流水线", "进厂"],
    "low_end_job": ["送外卖", "跑滴滴", "保安", "服务员", "收银"],
    "no_future": ["没出路", "看不到希望", "混日子", "温水煮青蛙"],
    "fear_change": ["怕学不会", "担心跟不上", "怕来不及", "不敢辞职"],
    "layoff": ["被裁", "裁员", "失业", "下岗"],
    "unwilling": ["不甘心", "不想再", "受够了"],
}


def init_report_slots(state):
    for slot in REPORT_SLOTS:
        state.setdefault(slot, "")


def detect_pain_points(msg, state):
    """痛点检测引擎"""
    pains = state.get("pain_points", [])
    new_pains = []

    for pain_tag, keywords in PAIN_KEYWORDS.items():
        if any(kw in msg for kw in keywords):
            if pain_tag not in pains:
                new_pains.append(pain_tag)

    if new_pains:
        state["pain_points"] = pains + new_pains
        logger.info(f"痛点检测: {new_pains} -> 累计 {state['pain_points']}")

    return new_pains


def get_pain_empathy(state):
    """
    根据痛点标签生成共情话术
    优先从KB读取，降级使用默认话术
    """
    pains = state.get("pain_points", [])
    if not pains:
        return ""

    latest_pain = pains[-1]

    # 从KB读取共情话术
    pain_empathy_map = KB.get("pain_empathy", {})
    if latest_pain in pain_empathy_map:
        return pain_empathy_map[latest_pain]

    # 降级默认
    default_map = {
        "age_too_old": "年纪大不是问题，讲真的，我见过35岁转行的，现在在深圳拿1万5。关键是你愿不愿意迈出这一步。",
        "factory_worker": "在厂里干久了确实看不到头，咱这边有从流水线转过来做网安的，现在日子比以前好太多。",
        "low_end_job": "送外卖跑滴滴辛苦还不稳定，咱这边学了技术，坐办公室吹空调拿工资，不用风吹日晒。",
        "no_future": "看不到希望的时候最难受，我能理解。但你愿意了解，说明你还没放弃，这已经是第一步了。",
        "fear_change": "怕学不会很正常，谁第一次接触新东西不害怕？咱这边零基础从打字开始教，一步一步来。",
        "layoff": "被裁确实难受，但你想想看，这也许是推你一把的机会。趁这个时间学门手艺，比再找个随时可能裁人的活强。",
        "unwilling": "不甘心就对了一半——剩下一半就是行动。咱不就业不收费，你零风险试一试，不好随时走。",
    }
    return default_map.get(latest_pain, "我理解你的顾虑，咱先看看基础条件，再一步步来。")


def calculate_graduation_years(grad_year, grad_month=7):
    now = get_beijing_time()
    years = now.year - grad_year
    if now.month < grad_month:
        years -= 1
    return max(0, years)


def check_qualification(state):
    """资格硬判定 - 保障班/非保障班"""
    edu = state.get("education", "")
    age = state.get("age", "")
    major = state.get("major", "")
    grad_year_str = state.get("graduated_year", "")
    grad_month_str = state.get("graduated_month", "7")
    direction = state.get("direction", "")

    logger.info(f"资格判定: edu={edu}, age={age}, major={major}, "
                f"year={grad_year_str}, month={grad_month_str}, dir={direction}")

    if not edu or any(kw in edu for kw in ["非统招", "自考", "成人", "函授", "专升本", "3+2", "高中", "中专"]):
        logger.info("   学历不合格")
        return False
    try:
        a = int(age)
        if a < 22 or a > 32:
            logger.info(f"   年龄不合格: {a}")
            return False
    except (ValueError, TypeError):
        logger.info(f"   年龄无法解析: {age}")
        return False
    if major in ("体育", "艺术"):
        logger.info(f"   专业不合格: {major}")
        return False
    if grad_year_str:
        try:
            grad_year = int(grad_year_str)
            grad_month = int(grad_month_str) if grad_month_str else 7
            diff = calculate_graduation_years(grad_year, grad_month)
            logger.info(f"   毕业年限={diff}")
            if direction == "网安":
                if "大专" in edu and diff < 2:
                    return False
                if "本科" in edu and diff < 1:
                    return False
            elif direction == "大数据":
                if "本科" not in edu or diff < 2:
                    return False
            else:
                if diff < 1:
                    return False
        except Exception as e:
            logger.warning(f"资格判定异常: {e}")

    logger.info("   合格")
    return True


def get_next_state(current_state, state, intent, lead_grade="A"):
    """
    状态跳转 + 信任门禁 + 多路径支持

    P1优化: 引入lead_grade参数，不同等级线索走不同路径
    - S级: 完整路径，快速推进
    - A级: 标准路径（默认）
    - B级: 跳过match_campus，直通show_fee
    - C级: 跳过match_campus，直通show_fee
    """
    """
    状态跳转 + 信任门禁
    """
    logger.info(f"状态跳转: {current_state} + intent={intent}, trust={state.get('trust_level', 50)}")

    # 法律风险：进入合规保护模式，不跳转
    if intent == "legal_threat":
        state["_legal_threat_mode"] = True
        state["_legal_threat_rounds"] = 0
        logger.info(f"法律风险触发: user_id={state.get('user_id', '')}, msg相关意图")
        return current_state

    # 情绪优先：不跳转
    if intent == "user_frustration":
        return current_state

    # 痛点表达：不跳转
    if intent == "express_pain":
        return current_state

    # 拒绝：不跳转（岗前考核阶段例外：reject→pre_training）
    if intent == "reject":
        if current_state == "pre_assessment":
            target_state = "pre_training"
            logger.info("   岗前考核拒绝，转岗前实训路径")
            return target_state
        return current_state

    # 信息纠正：回退重判
    if intent == "correct_info":
        if current_state in ("reject_qualify", "match_campus", "show_fee", "invite"):
            state["is_qualified"] = None
            return "qualify"
        return "qualify"

    # ---- 状态跳转表 ----
    target_state = current_state

    if current_state == "icebreak":
        if intent == "experienced":
            target_state = "pre_assessment"
        elif intent in ("newbie", "icebreak_greet", "fee_intent"):
            target_state = "qualify"
        else:
            target_state = "icebreak"

    elif current_state == "qualify":
        required = REGULAR_SLOTS
        filled = all(
            isinstance(state.get(k), str) and state.get(k).strip()
            for k in required
        )
        logger.info(f"   槽位检查: { {k: state.get(k) for k in required} } 满={filled}")
        if filled:
            is_qualified = check_qualification(state)
            state["is_qualified"] = is_qualified
            if is_qualified:
                # P1: B/C级线索跳过match_campus，直通show_fee（缩短对话轮次）
                if lead_grade in ("B", "C"):
                    logger.info(f"   {lead_grade}级线索跳过match_campus，直通show_fee")
                    target_state = "show_fee"
                else:
                    target_state = "match_campus"
            else:
                target_state = "reject_qualify"
        else:
            target_state = "qualify"

    elif current_state == "match_campus":
        if intent in ("confirm", "fee_intent"):
            target_state = "show_fee"
        elif intent.startswith("objection_"):
            target_state = "match_campus"
        else:
            target_state = "match_campus"

    elif current_state == "pre_assessment":
        if intent in ("confirm", "fee_intent"):
            target_state = "invite"
            state["_pre_assessment_pass"] = True
            logger.info("   岗前考核通过，快速通道直通invite")
        elif intent == "reject":
            target_state = "pre_training"
            logger.info("   岗前考核未通过，转岗前实训路径")
        elif intent.startswith("objection_"):
            target_state = "pre_assessment"
        else:
            target_state = "pre_assessment"

    elif current_state == "pre_training":
        if intent in ("confirm",):
            target_state = "qualify"
            logger.info("   接受岗前实训，进入标准qualify路径")
        elif intent == "reject":
            target_state = "reject_qualify"
            logger.info("   拒绝岗前实训，转非保障班")
        elif intent.startswith("objection_"):
            target_state = "pre_training"
        else:
            target_state = "pre_training"

    elif current_state == "show_fee":
        if intent in ("confirm", "fee_intent"):
            target_state = "invite"
        elif intent == "objection_price":
            # P1: 价格异议回退路径 - 推荐更便宜的方案
            target_state = "match_campus"
            state["_price_objection_fallback"] = True
            logger.info("   价格异议回退到match_campus，推荐更便宜方案")
        elif intent.startswith("objection_"):
            target_state = "show_fee"
        else:
            target_state = "show_fee"

    elif current_state == "reject_qualify":
        if intent == "confirm":
            target_state = "show_fee"
        elif intent.startswith("objection_"):
            target_state = "reject_qualify"
        else:
            target_state = "reject_qualify"

    elif current_state == "invite":
        if intent == "confirm":
            target_state = "report_info"
        elif intent.startswith("objection_"):
            target_state = "invite"
        else:
            target_state = "invite"

    elif current_state == "report_info":
        if intent == "confirm":
            target_state = "completed"
        else:
            target_state = "report_info"

    elif current_state == "completed":
        target_state = "completed"

    # ---- 信任门禁检查 ----
    if target_state != current_state and not can_advance_to(state, target_state):
        logger.info(f"信任门禁: trust={state.get('trust_level', 50)} 不足以跳转到 {target_state}")
        state["_trust_blocked"] = True
        state["_trust_blocked_target"] = target_state
        return current_state

    # 清除信任阻断标记
    state.pop("_trust_blocked", None)
    state.pop("_trust_blocked_target", None)

    return target_state


def generate_reply_instruction(old_state, new_state, state, intent, lead_score=50):
    """
    生成回复指令 - 话术全部从KB读取，支持个性化和动态策略
    """

    # ---- 法律风险：合规保护模式 ----
    if state.get("_legal_threat_mode") or intent == "legal_threat":
        return {
            "template": "你的反馈我已记录，我们会通过官方渠道联系你处理。如有疑问，欢迎拨打我们的官方客服电话。",
            "rules": ["停止推销", "转人工"],
            "forbidden": ["金额", "收费", "就业", "保障", "承诺"]
        }

    # ---- 信任不足时的修复话术 ----
    if state.get("_trust_blocked"):
        gate_msg = get_trust_gate_message(state, state.get("_trust_blocked_target", ""))
        if gate_msg:
            return {"template": gate_msg, "rules": [], "forbidden": ["金额", "收费"]}

    # ---- 情绪处理 ----
    if intent == "user_frustration":
        lines = ["理解理解，是我这边没记清楚，抱歉！我已经记下了："]
        for k, v in [("education", "学历"), ("age", "年龄"), ("graduated_year", "毕业年份"),
                      ("city", "城市"), ("direction", "方向")]:
            if state.get(k):
                lines.append(f"{v}: {state[k]}")
        missing = [v for k, v in [("education", "学历"), ("age", "年龄"),
                                   ("graduated_year", "毕业年份"), ("city", "城市"),
                                   ("direction", "方向")] if not state.get(k)]
        if missing:
            lines.append(f"还需要补充：{'、'.join(missing)}，方便说下吗？")
        else:
            lines.append("咱们马上匹配校区。")
        return {"template": "\n".join(lines), "rules": [], "forbidden": []}

    # ---- 痛点共情 ----
    if intent == "express_pain":
        empathy = get_pain_empathy(state)
        if empathy:
            missing = []
            if not state.get("education"):
                missing.append("学历")
            if not state.get("age"):
                missing.append("年龄")
            if not state.get("graduated_year"):
                missing.append("毕业年份")
            if missing:
                guide = f"咱先看下基础条件——{'、'.join(missing[:2])}方便说下吗？"
            else:
                guide = "你的条件我都了解了，马上给你匹配校区。"
            return {"template": f"{empathy}\n{guide}", "rules": [], "forbidden": ["金额", "收费"]}
        return {"template": "我理解你的顾虑。咱先看下基础条件，一步步来，好吗？",
                "rules": [], "forbidden": ["金额", "收费"]}

    # ---- 拒绝挽留 ----
    if intent == "reject":
        node = state.get("current_node", "icebreak")
        if node in ("invite", "show_fee", "report_info"):
            return {
                "template": "理解。这样，我先把你的信息记着，什么时候想了解随时找我，不催你。",
                "rules": [], "forbidden": ["金额", "收费"]
            }
        return {
            "template": "好的，不打扰了。以后有想法随时联系我。",
            "rules": [], "forbidden": ["金额", "收费"]
        }

    # ---- 异议5步法（支持动态策略） ----
    if intent.startswith("objection_"):
        strategy = state.get("_objection_strategy", {})
        return _generate_objection_reply(intent, state, strategy)

    # ---- 题外话 ----
    if intent == "off_topic":
        if old_state in ("icebreak", None):
            return {
                "template": KB.get("icebreak_greet", KB.get("icebreak_normal",
                    ["你好，我是小范，做IT人才服务6年了。你是想零基础转行学门技术，还是已经有经验想直接内推？"]))[0],
                "rules": [], "forbidden": []
            }
        # 从KB读取拉回话术
        pullback_map = KB.get("pullback", {})
        default_pullback = "咱先把正事办了，方便说说你的学历和年龄吗？"
        template = pullback_map.get(old_state, default_pullback)
        return {"template": template, "rules": [], "forbidden": []}

    # ---- icebreak → qualify（个性化开场） ----
    if old_state == "icebreak" and new_state == "qualify":
        template = _get_personalized_qualify_opening(state, lead_score)
        return {
            "template": template,
            "rules": [], "forbidden": ["金额", "收费"]
        }

    # ---- qualify → match_campus ----
    if old_state == "qualify" and new_state == "match_campus":
        return {
            "template": "你的基本情况我都了解了，马上给你匹配最近的校区。",
            "rules": [], "forbidden": ["金额", "收费"]
        }

    # ---- 各状态话术 ----
    if new_state == "icebreak":
        return {
            "template": KB.get("icebreak_greet", KB.get("icebreak_normal",
                ["你好，我是小范，做IT人才服务6年了。你是想零基础转行学门技术，还是已经有经验想直接内推？"]))[0],
            "rules": [], "forbidden": ["金额", "费用"]
        }

    elif new_state == "qualify":
        missing = []
        if not state.get("education"):
            missing.append("学历（统招大专/本科？）")
        if not state.get("age"):
            missing.append("年龄")
        if not state.get("graduated_year"):
            missing.append("哪年毕业的")
        if not state.get("city"):
            missing.append("在哪个城市")
        if not state.get("direction"):
            missing.append("想学网安还是大数据？")
        if missing:
            confirmed = []
            for k, v in [("education", "学历"), ("age", "年龄"), ("city", "城市"),
                          ("direction", "方向")]:
                if state.get(k):
                    confirmed.append(v)
            if confirmed:
                prefix = f"你说的{'、'.join(confirmed)}我都记下了。"
            else:
                prefix = ""

            # Vary the ask to avoid sounding repetitive
            ask_count = state.get("_qualify_ask_count", 0)
            state["_qualify_ask_count"] = ask_count + 1
            ask_variants = [
                f"{'，'.join(missing[:2])}方便说下吗？",
                f"还需要了解下{'、'.join(missing[:2])}。",
                f"还差{'、'.join(missing[:2])}，简单说下就行。",
            ]
            ask_text = ask_variants[ask_count % len(ask_variants)]

            return {
                "template": f"{prefix}{ask_text}",
                "rules": [], "forbidden": ["金额", "收费", "校区"]
            }
        return {
            "template": "你的基本情况我都了解了，马上给你匹配最近的校区。",
            "rules": [], "forbidden": ["金额"]
        }

    elif new_state == "match_campus":
        direction = state.get("direction", "网安")
        city = state.get("city", "")
        if any(c in city for c in ["广东", "广州", "深圳", "赣州"]):
            campus = f"广州{direction}校区（{'海珠' if direction == '网安' else '番禺'}）"
        else:
            campus = f"杭州{direction}校区（{'钱塘' if direction == '网安' else '临平'}）"
        # AUDIT-009: 区分实训校区与就业推荐城市
        cities_tip = KB.get("employment_cities",
            ["就业推荐城市覆盖深圳、上海、北京、广州、杭州——都是IT岗位密集的一线城市，五险一金、周末双休是标配。"])[0]
        meal_tip = KB.get("meal_disclosure",
            ["住宿我们全包，吃饭你自己解决哈——校区周边吃饭很方便，一顿十几块钱就能吃好。"])[0]
        return {
            "template": f"按你的情况，最近的实训校区在{campus}，过来实训免费住宿。{cities_tip} {meal_tip}",
            "rules": [], "forbidden": ["金额", "收费", "费用"]
        }

    elif new_state == "pre_assessment":
        template = KB.get("pre_assessment_invite",
            ["你有经验，不用从头学。直接来校区做个技术评估，通过的话走快速内推流程，不用跟零基础的一起上课。这周方便过来吗？"])[0]
        return {"template": template, "rules": [], "forbidden": ["金额", "收费"]}

    elif new_state == "pre_training":
        template = KB.get("pre_assessment_fail",
            ["评估结果出来了，有几个模块还需要加强。你可以选择参加我们的岗前实训（一个半月），专门补这几个模块。当然不强制，你自己决定。要是想参加，咱先了解下你的基础条件。"])[0]
        return {"template": template, "rules": [], "forbidden": ["金额", "收费"]}

    elif new_state == "show_fee":
        if state.get("is_qualified"):
            template = KB["fee_show_core"][0]
        else:
            template = KB["fee_show_non_guarantee"][0]
        return {"template": template, "rules": ["严格按原话说"], "forbidden": []}

    elif new_state == "invite":
        if state.get("_pre_assessment_pass"):
            template = KB.get("pre_assessment_pass",
                ["评估通过了，你的技术水平符合我们的内推标准。接下来把报备信息填一下，我帮你匹配合作企业的在招岗位。"])[0]
            state.pop("_pre_assessment_pass", None)
        else:
            template = _get_personalized_invite(state, lead_score)
        return {
            "template": template,
            "rules": [], "forbidden": ["金额"]
        }

    elif new_state == "reject_qualify":
        # Add empathy based on pain points before the reject template
        pain_empathy = ""
        pains = state.get("pain_points", [])
        if pains:
            pain_empathy = get_pain_empathy(state)
        reject_msg = KB["reject_qualify"][0]
        if pain_empathy:
            template = pain_empathy + "\n" + reject_msg
        else:
            template = reject_msg
        return {"template": template, "rules": [], "forbidden": []}

    elif new_state == "report_info":
        return {
            "template": (
                "为了给你安排实训和住宿，麻烦你填一下以下信息发给我：\n"
                "姓名：\n性别：\n学历：\n毕业时间：\n专业：\n沟通岗位：\n"
                "联系电话：\n出发城市：\n实训基地：\n到达时间：\n是否需要住宿：\n其他备注："
            ),
            "rules": [], "forbidden": []
        }

    elif new_state == "completed":
        reemployment = KB.get("reemployment_guarantee",
            ["签约后2年内，如果你因非自身原因被裁，凭公司离职证明回来，我们免费重新帮你推荐就业，薪资标准不变。"])[0]
        grace = KB.get("payment_grace_period",
            ["如果被裁时分期还没付完，可以申请最长30天的付费延期——等你找到新工作、拿到工资后再恢复。"])[0]
        salary_fallback = KB.get("salary_shortfall_guarantee",
            ["如果推荐岗位的实际薪资没达到承诺的最低标准，我们会继续帮你推荐，直到薪资达标为止。"])[0]
        return {"template": KB.get("completed",
            ["你的信息我都收到了，我们会尽快安排。有什么问题随时找我。"])[0]
            + f" {reemployment} {grace} {salary_fallback}",
            "rules": [], "forbidden": []}

    return {"template": KB["default"][0], "rules": [], "forbidden": []}


def _get_personalized_qualify_opening(state, lead_score):
    """个性化开场白：根据已知信息调整话术"""
    pain_points = state.get("pain_points", [])
    age = state.get("age", "")
    education = state.get("education", "")

    # 如果已经知道一些信息，不要重复问
    known = []
    if education:
        known.append(f"学历{education}")
    if age:
        known.append(f"{age}岁")

    if known:
        return f"好的，{'，'.join(known)}的情况我记下了。再了解下——你哪年毕业的？在哪个城市？想学网安还是大数据？"

    # 有痛点的用户，先共情再问
    if pain_points:
        pain_empathy_map = {
            "layoff": "被裁的事我理解，正好趁这个时间学门技术。",
            "factory_worker": "在厂里干久了确实想换个环境。",
            "low_end_job": "现在的工作确实不是长久之计。",
            "no_future": "看不到方向的时候最难熬，我懂。",
            "unwilling": "不甘心就对了，说明你还有追求。",
        }
        empathy = pain_empathy_map.get(pain_points[-1], "")
        if empathy:
            return f"{empathy}我先了解下你的情况——学历是统招大专还是本科？哪年毕业？多大了？在哪个城市？"

    # 高分用户：快节奏
    if lead_score >= 70:
        return "好的，我先快速了解下你的情况——学历、年龄、毕业年份、城市、想学什么方向？"

    return "你好呀，我是小范，做IT人才服务6年了。讲真的，转行是个大事儿，我先了解下你的情况——学历是统招大专还是本科？哪年毕业？多大了？在哪个城市？"


def _get_personalized_invite(state, lead_score):
    """个性化邀约话术"""
    trust = state.get("trust_level", 50)
    city = state.get("city", "")
    pain_points = state.get("pain_points", [])

    base = "这周二新班开课，你过来直接跟课试听。名额还有两个，定吗？不方便的话周末也行。"

    # 高信任用户：加车费报销
    if trust >= 70:
        base += "你要是试听满三天，我们给你报销一半车费，就当交个朋友。"

    # 外地用户：强调住宿
    if city and not any(c in city for c in ["广州", "深圳", "杭州"]):
        base += "外地过来的话，住宿我给你安排好，拎包入住。"

    # 有痛点用户：针对性收尾
    if pain_points:
        last_pain = pain_points[-1]
        if last_pain in ("layoff", "no_future"):
            base += "趁现在有时间，先来看看，早学早就业。"
        elif last_pain == "factory_worker":
            base += "换个环境，试试看，不好随时走。"

    return base


def _generate_objection_reply(intent, state, strategy=None):
    """
    异议5步法 - 话术从KB读取，支持动态策略模式
    共情 → 探因 → 举证 → 重构 → 行动

    strategy模式:
      - standard_5step: 完整5步法（默认）
      - alternative_script: 换一种话术角度
      - direct_mode: 真诚直接模式
      - escalate: 考虑转人工
    """
    if strategy is None:
        strategy = {}

    mode = strategy.get("mode", "standard_5step")
    round_num = strategy.get("round", 1)

    # 从KB读取异议话术
    kb_objection = KB.get(intent, [])
    if kb_objection and mode == "standard_5step":
        template = kb_objection[0]
    else:
        # 使用5步法从state_machine内部话术库
        objection_5step = {
            "objection_consider": {
                "empathy": "确实，转行是大事，犹豫很正常。",
                "probe": "你是担心学完找不到工作，还是担心自己坚持不下来？",
                "evidence": "上个月有个广州的学员，32岁从工厂出来，现在在网安岗位月薪9500。",
                "reframe": "犹豫的成本比试错高——再等一年，年龄大了一岁，机会少了一分。",
                "action": "这周末你先来试听一天，住宿我安排，听完再决定？"
            },
            "objection_learn": {
                "empathy": "怕学不会，这个担心我理解。",
                "probe": "你是怕自己基础差，还是怕没时间学？",
                "evidence": "讲真的，咱这边有零基础一个半月转行的，从打字速度开始教，一步一步来。",
                "reframe": "学不会不收钱，你有什么好怕的？这是零风险的事。",
                "action": "先来试听一节课，看看难度到底怎么样，你自己判断。"
            },
            "objection_time": {
                "empathy": "忙，说明你在努力生活，我尊重你。",
                "probe": "是工作走不开，还是家里事情多？",
                "evidence": "咱这边有白天班和晚班，前两周还能远程跟。",
                "reframe": "忙一阵子换以后轻松，还是忙一辈子？时间挤一挤就有了。",
                "action": "先来校区看半小时，我给你看下时间安排表，你看看能不能配合。"
            },
            "objection_distance": {
                "empathy": "距离远确实麻烦，我理解。",
                "probe": "你现在在哪个城市？",
                "evidence": "咱四校联动，广州杭州都有校区，实训住宿全免费。",
                "reframe": "远是暂时的，职业是长期的。为了以后不走远路，现在辛苦一趟值不值？",
                "action": "我给你安排最近的校区，住宿我安排，拎包入住。"
            },
            "objection_institution": {
                "empathy": "你警惕性高，好事——说明你在认真考虑。",
                "probe": "你是担心收了钱跑路？",
                "evidence": "讲真的，我们是做IT内推实训的基地，直接跟企业合作定向输送。不就业不收费，合同白纸黑字。",
                "reframe": "你担心的事，恰恰是我们的底线——不敢承诺的才需要你警惕。",
                "action": "周末来校区看看，跟在学的学员聊几句，真不真你自己判断。"
            },
            "objection_price": {
                "empathy": "钱的事确实要算清楚，不跟你绕弯子。",
                "probe": "你是觉得贵了，还是担心付了钱没效果？",
                "evidence": "这个钱不是学费，是就业服务费——你入职拿到工资了才付。而且有两种方式，可以分期。",
                "reframe": "不是你花19600买一份工作，是你先拿到工作再付钱。哪个风险大？",
                "action": "费用细节来校区我给你看合同，一目了然。这周末方便来吗？"
            }
        }

        # alternative_script模式：备选话术
        objection_alternative = {
            "objection_consider": {
                "empathy": "我理解你想再看看，说明你是个谨慎的人。",
                "evidence": "不过我跟你说个数据，咱这边上个月就业率92%，平均薪资11000。犹豫的时间成本比试错成本高多了。",
                "action": "先来试听一天，不花你一分钱，听完你自己判断。"
            },
            "objection_learn": {
                "empathy": "谁第一次接触新东西不担心？这很正常。",
                "evidence": "咱这边教学是从零开始的，打字、办公软件、基础网络，一步一步来。而且有班主任全程跟，不会的随时问。",
                "action": "你来试听一节课，看看学员是怎么学的，心里就有底了。"
            },
            "objection_price": {
                "empathy": "我明白，花钱的事谁都想清楚。",
                "evidence": "但你想啊，这钱是入职以后才付的，不是现在掏腰包。前两个月分期才1毛钱/月，几乎零压力。",
                "action": "来校区我给你看合同，上面写得清清楚楚，不满意随时走。"
            },
            "objection_time": {
                "empathy": "时间确实紧，我理解。",
                "evidence": "咱这边有灵活班制，白天晚班都有，前两周还能远程。很多在职学员都是挤时间学的。",
                "action": "你先来校区看半小时课程安排，我帮你规划下时间。"
            },
            "objection_distance": {
                "empathy": "远确实是问题，我懂。",
                "evidence": "广州杭州四校区联动，实训期间住宿全免费，拎包入住那种。",
                "action": "我帮你算下最近的校区，住宿我安排，你只需要人过来就行。"
            },
            "objection_institution": {
                "empathy": "你的谨慎是对的，现在确实要擦亮眼。",
                "evidence": "我们跟上百家IT企业有定向输送合作，合同上写明不就业不收费。你来校区可以看企业合作协议。",
                "action": "周末来校区实地看看，跟在读学员聊聊，真假自辨。"
            },
        }

        # direct_mode模式：真诚直接
        objection_direct = {
            "objection_consider": "我直说吧，犹豫是因为不确定，不确定是因为不了解。来校区看一天，比你想一个月有用。",
            "objection_learn": "学不会不收钱，这是合同上写的。你零风险试一试，不好随时走，有什么好怕的？",
            "objection_price": "钱的事我不绕弯子——入职才付费，前两月分期1毛/月。你先拿到工作再付钱，这还不够诚意？",
            "objection_time": "忙是借口还是真忙？如果是真忙，咱有灵活班制。如果是借口，那我帮不了你。",
            "objection_distance": "远？广州杭州都有校区，住宿全免费。你告诉我你在哪，我帮你选最近的。",
            "objection_institution": "合同白纸黑字，不就业不收费。你要是还不信，周末来校区看原件，跟学员聊。",
        }

        steps = objection_5step.get(intent)
        if not steps:
            steps = {
                "empathy": "你说的这个我理解。",
                "probe": "能具体说说你的顾虑吗？",
                "evidence": "咱这边6年送出去300多个学员，口碑不是吹出来的。",
                "reframe": "有问题不怕，就怕不问——你愿意问说明你在认真考虑。",
                "action": "周末来校区聊，我给你看真实的学员案例和合同。"
            }

        pain_points = state.get("pain_points", [])
        trust_level = state.get("trust_level", 50)
        current_node = state.get("current_node", "icebreak")

        # 根据模式选择输出
        if mode == "direct_mode":
            # 真诚直接模式：简短有力
            template = objection_direct.get(intent, steps.get("empathy", "") + steps.get("action", ""))

        elif mode == "alternative_script":
            # 备选话术模式：换角度
            alt = objection_alternative.get(intent)
            if alt:
                template = f"{alt['empathy']} {alt['evidence']} {alt['action']}"
            else:
                template = f"{steps['empathy']} {steps['evidence']} {steps['action']}"

        elif mode == "escalate":
            # 超限模式：温和收尾，为转人工留口子
            template = (
                f"{steps['empathy']}我能感觉到你还有很多顾虑，"
                "这样吧，我让我们资深的顾问直接跟你聊，他比我专业，能解答你所有问题。"
            )

        else:
            # 标准5步法
            if pain_points:
                template = f"{steps['empathy']}\n{steps['evidence']}\n{steps['action']}"
            else:
                template = f"{steps['empathy']} {steps['probe']} {steps['evidence']} {steps['action']}"

        # 高意向/高价值客户追加车费报销（除escalate模式外）
        if mode != "escalate" and trust_level >= 70 and current_node in ("invite", "show_fee"):
            template += "\n另外，你要是试听满三天，我们给你报销一半车费，就当交个朋友。"

    return {"template": template, "rules": [], "forbidden": ["包就业", "保证就业"]}
