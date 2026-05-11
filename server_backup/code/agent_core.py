"""核心调度 - 智能升级版 v2.0



核心升级:

1. LLM决策架构：关键节点模板直出，非关键节点LLM自主决策

2. 向量记忆系统：语义检索历史对话

3. 动态异议处理：LLM生成个性化异议回应

4. 深度用户画像：多维度用户分析

5. 对话挽回引擎：智能挽回策略

6. 数据分析增强：转化漏斗可视化



集成模块：

  lead_scorer: 线索评分

  conversation_analytics: 对话分析

  intent_classifier: 意图识别（LLM增强）

  personalization: 个性化触达

  decision_engine: 自主决策

  content_generator: 内容生成

  experiment_manager: A/B测试

  human_collaboration: 人工协作

  memory_vector: 向量记忆

  objection_handler: 动态异议

  user_profiler: 深度画像

  recovery_engine: 对话挽回

"""

import asyncio

import copy

import re

import time

import json

from datetime import datetime, timedelta

from loguru import logger

from code.model_router import stream_llm, CONFIG, get_llm_health, call_model

from code.memory_manager import load_state, save_state, add_history, get_history, record_active

from code.compliance_checker import hard_check

from code.intent_classifier import classify

from code.info_extractor import extract_entities, extract_report_info

from code.state_machine import (

    get_next_state, generate_reply_instruction,

    REPORT_SLOTS, init_report_slots, REGULAR_SLOTS, KB,

    detect_pain_points

)

from code.time_utils import get_beijing_time

from code.dynamic_redline import check as dynamic_check

from code.trust_engine import adjust_trust, init_trust, apply_daily_decay

from code.guardrail import (

    classify_question_tier, get_layer2_system_prompt, get_layer3_reply

)

from code.lead_scorer import (

    calculate_lead_score, get_lead_grade, update_behavior_signals,

    get_lead_strategy, log_lead_score_change

)

from code.conversation_analytics import (

    log_conversation_start, log_intent_detected, log_slot_update,

    log_state_transition, log_objection_handled, log_pain_detected,

    log_trust_changed, log_compliance_block, log_conversation_end,

    log_llm_call, log_human_handoff, flush_if_needed

)

from code.decision_engine import (

    should_skip_steps, get_objection_strategy, can_advance_dynamic,

    should_end_conversation, should_handoff_to_human

)

from code.human_collaboration import (

    build_handoff_context, format_handoff_message,

    should_send_observe_alert, is_user_human_active,

    mark_user_human_active, generate_sales_suggestion

)



# ---- 新增集成模块 ----

try:

    from code.memory_vector import add_memory as _vm_add_memory, search as _vm_search, clear_user_memories as _vm_clear_user

    VECTOR_MEMORY_AVAILABLE = True

except ImportError:

    VECTOR_MEMORY_AVAILABLE = False

    _vm_add_memory = None

    _vm_search = None

    _vm_clear_user = None

try:

    from code.user_profiler import build_deep_profile, get_personalized_strategy

    USER_PROFILER_AVAILABLE = True

except ImportError:

    USER_PROFILER_AVAILABLE = False

try:

    from code.objection_handler import generate_objection_response as generate_objection_llm

    OBJECTION_HANDLER_AVAILABLE = True

except ImportError:

    OBJECTION_HANDLER_AVAILABLE = False

try:

    from code.recovery_engine import should_attempt_recovery, schedule_recovery, get_recovery_hook

    RECOVERY_AVAILABLE = True

except ImportError:

    RECOVERY_AVAILABLE = False

try:

    from code.tools import execute_tool, build_tool_prompt, TOOLS

    TOOLS_AVAILABLE = True

except ImportError:

    TOOLS_AVAILABLE = False



# ---- LLM 熔断机制 ----

_llm_fail_count = 0

_llm_fuse_open = False

_last_llm_check_time = 0



# ---- 定义节点类型 ----

# 关键节点：必须模板直出（合规红线）

TEMPLATE_NODES = {"show_fee", "invite", "reject_qualify", "report_info", "completed"}



# 非关键节点：可以让LLM自主决策

LLM_NODES = {"icebreak", "qualify", "match_campus"}





def _get_llm_fuse_threshold():

    _reload_config_if_needed()

    return CONFIG.get("security", {}).get("llm_fallback_to_template_after_failures", 3)





def _get_llm_recovery_interval():

    _reload_config_if_needed()

    return CONFIG.get("security", {}).get("llm_recovery_check_interval_seconds", 60)





def _get_max_msg_length():

    _reload_config_if_needed()

    return CONFIG.get("security", {}).get("max_msg_length", 2000)





MAX_MSG_LENGTH = 2000



# ---- 配置热更新 ----

_config_last_mtime = 0





def _reload_config_if_needed():

    global CONFIG, _config_last_mtime

    try:

        import os

        from code import CONFIG_FILE

        mtime = os.path.getmtime(CONFIG_FILE)

        if mtime != _config_last_mtime:

            _config_last_mtime = mtime

            import yaml

            with open(CONFIG_FILE, encoding="utf-8") as f:

                new_config = yaml.safe_load(f)

            CONFIG.clear()

            CONFIG.update(new_config)

            logger.info("配置热更新完成")

    except Exception as e:

        logger.debug(f"配置热更新检查失败: {e}")





def _mask_pii(text: str) -> str:

    text = re.sub(r'(1[3-9]\d)\d{4}(\d{3})', r'\1****\2', text)

    return text


def _store_vector_memory(user_id, user_msg, assistant_msg, state=None):
    """存储对话到向量记忆（非阻塞）"""
    if not VECTOR_MEMORY_AVAILABLE or not _vm_add_memory:
        return
    try:
        metadata = {}
        if state:
            metadata = {"state": state.get("current_node", ""), "lead_score": state.get("lead_score", 0)}
        _vm_add_memory(user_id, user_msg, assistant_msg, metadata)
    except Exception as e:
        logger.debug(f"向量记忆存储失败: {e}")

def _get_relevant_memories(user_id, query, top_k=3):
    """获取相关记忆（非阻塞）"""
    if not VECTOR_MEMORY_AVAILABLE or not _vm_search:
        return ""
    try:
        memories = _vm_search(user_id, query, top_k)
        if memories:
            return "\n".join([m["text"] for m in memories])
    except Exception as e:
        logger.debug(f"向量记忆检索失败: {e}")
    return ""

def _build_user_profile_context(state, history=None):
    """构建用户画像上下文"""
    if not USER_PROFILER_AVAILABLE:
        return ""
    try:
        profile = build_deep_profile(state, history or [])
        strategies = get_personalized_strategy(profile)
        parts = []
        if strategies.get("decision_style"):
            parts.append(f"决策风格: {strategies['decision_style']}")
        if strategies.get("communication_style"):
            parts.append(f"沟通风格: {strategies['communication_style']}")
        if strategies.get("economic_pressure"):
            parts.append(f"经济压力: {strategies['economic_pressure']}")
        return "、".join(parts) if parts else ""
    except Exception as e:
        logger.debug(f"用户画像构建失败: {e}")
        return ""






def _is_llm_available() -> bool:

    global _llm_fuse_open, _llm_fail_count, _last_llm_check_time

    if not _llm_fuse_open:

        return True

    now = time.time()

    if now - _last_llm_check_time > _get_llm_recovery_interval():

        _last_llm_check_time = now

        health = get_llm_health()

        if health:

            _llm_fuse_open = False

            _llm_fail_count = 0

            logger.info("LLM熔断恢复，切换回LLM模式")

            return True

    return False





def _on_llm_failure():

    global _llm_fail_count, _llm_fuse_open

    _llm_fail_count += 1

    threshold = _get_llm_fuse_threshold()

    if _llm_fail_count >= threshold:

        _llm_fuse_open = True

        logger.warning(f"LLM连续失败{_llm_fail_count}次，熔断开启，切换纯模板模式")

        from code.error_monitor import alert_llm_fuse

        alert_llm_fuse(_llm_fail_count)





def _on_llm_success():

    global _llm_fail_count

    _llm_fail_count = 0





def _estimate_tokens(text: str) -> int:

    cn_chars = len(re.findall(r'[一-鿿]', text))

    en_chars = len(text) - cn_chars

    return int(cn_chars / 1.5 + en_chars / 4)





def _truncate_history_by_token(history: list, max_tokens: int = 1500) -> list:

    if not history:

        return history

    total_tokens = 0

    kept = []

    for h in reversed(history):

        entry_text = h.get("user", "") + h.get("assistant", "")

        entry_tokens = _estimate_tokens(entry_text)

        if total_tokens + entry_tokens > max_tokens:

            break

        kept.insert(0, h)

        total_tokens += entry_tokens

    if len(kept) < 2 and len(history) >= 2:

        kept = history[-2:]

    return kept





def build_decision_prompt(user_state, intent, collected_slots,

                          pain_points, lead_score, history, current_node, msg):

    """构建LLM决策prompt - 让LLM像真人销售一样思考和回复"""



    constitution = CONFIG.get("persona_constitution", "")

    persona = CONFIG.get("persona", "")



    # 构建用户画像

    profile_parts = []

    for k, label in [("education", "学历"), ("age", "年龄"),

                      ("毕业年份", "毕业年份"), ("city", "城市"), ("direction", "方向")]:

        if user_state.get(k):

            profile_parts.append(f"{label}: {user_state[k]}")

    profile_str = "、".join(profile_parts) if profile_parts else "暂无"
    # Collect and missing fields for LLM awareness
    collect_fields = [("education", "学历"), ("age", "年龄"),
                      ("graduated_year", "毕业年份"),
                      ("city", "城市"), ("direction", "方向")]
    collected = [label for k, label in collect_fields if user_state.get(k)]
    missing = [label for k, label in collect_fields if not user_state.get(k)]
    collected_str = "、".join(collected) if collected else "无"
    missing_str = "、".join(missing) if missing else "全部已收集"

    pain_str = "、".join(pain_points) if pain_points else "无"




    # 构建痛点描述




    # 构建历史对话

    history_str = "\n".join(

        [f"用户：{h['user']}\n小范：{h['assistant']}" for h in history[-3:]]

    )



    # 当前阶段说明

    stage_desc = {

        "icebreak": "破冰阶段，目标是建立连接，判断用户意向",

        "qualify": "资质筛查阶段，目标是收集用户基础信息（学历、年龄、毕业年份、城市、方向）",

        "match_campus": "校区匹配阶段，目标是让用户知道有合适的校区"

    }.get(current_node, "")



    # 构建信任度说明

    trust = user_state.get("trust_level", 50)

    trust_desc = "高" if trust >= 70 else "中" if trust >= 50 else "低"



    # 获取向量记忆和用户画像
    user_id = user_state.get("_user_id", "")
    memory_context = _get_relevant_memories(user_id, msg) if user_id else ""
    profile_context = _build_user_profile_context(user_state, history)

    prompt = f"""{constitution}



{persona}



【当前情况】

- 对话阶段：{current_node}（{stage_desc}）

- 用户意图：{intent}

- 已收集信息：{profile_str}

- 已收集字段：{collected_str}

- 未收集字段：{missing_str}

- 用户痛点：{pain_str}

- 线索等级：{lead_score}（{"S级高价值" if lead_score >= 80 else "A级" if lead_score >= 60 else "B级" if lead_score >= 40 else "C级"}）

- 信任度：{trust}（{trust_desc}）



【最近对话】

{history_str}



【用户最新消息】

{msg}



【你的任务】

你现在就是小范本人，像真人销售一样思考和回复。



回复要求：

1. 先理解用户的真实意图和情绪

2. 根据当前阶段选择合适的策略

3. 如果用户有痛点，先共情再引导

4. 如果用户问了无关问题，礼貌拉回主线

5. 每次回复都要提供新价值（案例、资讯、建议）

6. 不要重复之前说过的话

7. 控制在100字以内，口语化表达

8. 可以适当使用表情符号增加亲和力



绝对不能出现的词：培训、学费、上课、招生、老师、机构、保证、一定、包就业



直接输出你的回复，不要加任何前缀或解释："""



    return prompt





async def generate_llm_decision(user_state, intent, collected_slots,

                                pain_points, lead_score, history, current_node, msg):

    """让LLM自主决策生成回复，支持工具调用"""



    # 第一步：检查是否需要工具调用

    tool_result = None

    if TOOLS_AVAILABLE and _is_llm_available():

        try:

            tool_prompt = build_tool_prompt(msg, user_state)

            tool_reply = ""

            async for token in stream_llm(tool_prompt, 0.1, "main"):

                if token:

                    tool_reply += token

            _on_llm_success()

            tool_reply = tool_reply.strip()

            # 解析工具调用

            if tool_reply.startswith("{") and '"tool"' in tool_reply:

                import json as _json

                try:

                    tool_call = _json.loads(tool_reply)

                    if "tool" in tool_call:

                        user_id = user_state.get("_user_id", "")

                        tool_result = execute_tool(tool_call["tool"], tool_call.get("parameters", {}), user_id)

                        logger.info(f"工具调用: {tool_call['tool']} -> {str(tool_result)[:100]}")

                except Exception as te:

                    logger.debug(f"工具调用解析失败: {te}")

        except Exception as e:

            logger.debug(f"工具决策失败: {e}")



    # 第二步：构建决策prompt（含工具结果）

    prompt = build_decision_prompt(

        user_state, intent, collected_slots,

        pain_points, lead_score, history, current_node, msg

    )

    # 如果有工具结果，追加到prompt中

    if tool_result:

        import json as _json_fmt

        tool_context = f"\n\n【工具查询结果】\n{_json_fmt.dumps(tool_result, ensure_ascii=False)}\n请基于以上信息回复用户。"

        prompt += tool_context



    reply = ""

    try:

        async for token in stream_llm(prompt, 0.7, "main"):

            if token:

                reply += token

        _on_llm_success()

    except Exception as e:

        logger.warning(f"LLM决策失败: {e}")

        _on_llm_failure()

        return ""



    return reply.strip()





async def generate_objection_response(intent, user_msg, state, history):

    """让LLM动态生成异议回应"""



    pain_points = state.get("pain_points", [])

    lead_score = state.get("lead_score", 50)



    # 获取最匹配的案例

    from code.content_generator import match_case, format_case_for_prompt

    case = match_case(state)

    case_text = format_case_for_prompt(case)



    prompt = f"""你是小范，26岁的IT人才服务顾问。用户表达了顾虑：

"{user_msg}"



用户背景：

- 年龄：{state.get('age', '未知')}

- 学历：{state.get('education', '未知')}

- 城市：{state.get('city', '未知')}

- 痛点：{'、'.join(pain_points) if pain_points else '无'}

- 线索等级：{lead_score}



相似案例：

{case_text}



【异议处理5步法】

1. 共情：先理解用户的顾虑

2. 探因：询问具体原因

3. 举证：用案例或数据证明

4. 重构：重新定义问题

5. 行动：给出明确下一步



要求：

1. 真诚自然，像朋友聊天

2. 不要模板化，要针对用户的具体情况

3. 引用案例时要自然融入对话

4. 控制在120字以内

5. 不要出现"培训""学费""保证""一定"等词

6. 可以适当使用表情符号



直接输出回复："""



    reply = ""

    try:

        async for token in stream_llm(prompt, 0.7, "main"):

            if token:

                reply += token

        _on_llm_success()

    except Exception as e:

        logger.warning(f"异议回应生成失败: {e}")

        _on_llm_failure()

        return ""



    return reply.strip()





async def process_message_stream(user_id, msg):

    """

    处理用户消息（流式输出）- v2.0



    完整流程:

    1. 输入校验

    2. 记录活跃 + 信任衰减

    3. 加载用户状态 + 初始化

    4. 意图识别（LLM增强）

    5. 实体提取 → 更新槽位

    6. 痛点检测

    7. 线索评分更新

    8. 信任自动奖惩

    9. 三层护栏分类

    10. 状态跳转 + 动态信任门禁

    11. 人工协作检查

    12. 生成回复（LLM决策/模板直出/异议动态生成）

    13. 合规检查

    14. 流式输出

    15. 事件记录

    """

    session_start = time.time()

    try:

        _reload_config_if_needed()



        # ---- 0. 输入校验 ----

        max_len = _get_max_msg_length()

        if len(msg) > max_len:

            yield "消息太长了，简单说下你的情况就好，比如学历、年龄、想学什么方向？"

            return



        # ---- 1. 记录活跃 & 信任衰减 ----

        record_active(user_id)

        state = load_state(user_id)

        state = copy.deepcopy(state)
        state["_user_id"] = user_id

        if "current_node" not in state:

            state["current_node"] = "icebreak"

        init_report_slots(state)

        init_trust(state)

        apply_daily_decay(state)



        # 对话轮次计数

        state["_conversation_rounds"] = state.get("_conversation_rounds", 0) + 1



        old_state = state["current_node"]



        # ---- 对话终止检查 ----

        if old_state not in ("completed",):

            end_now, end_reason = should_end_conversation(

                state, state.get("lead_score", 0), state["_conversation_rounds"]

            )

            if end_now:

                logger.info(f"[{user_id}] 对话终止: {end_reason}")

                polite_end = "好的，不打扰你了。以后有想法随时联系我。"

                save_state(user_id, state)

                yield polite_end

                add_history(user_id, msg, polite_end)
                _store_vector_memory(user_id, msg, polite_end, state)

                log_conversation_end(user_id, end_reason, state["_conversation_rounds"],

                                     time.time() - session_start, 0)

                flush_if_needed()

                return



        # 记录对话开始

        if state["_conversation_rounds"] == 1:

            log_conversation_start(user_id)



        # ---- 2. 意图识别（LLM增强） ----

        collected_slots = {

            k: state.get(k) for k in ["education", "age", "city", "direction", "graduated_year"]

            if state.get(k)

        }

        intent_result = classify(msg, old_state, collected_slots)

        intent = intent_result["intent"]

        confidence = intent_result.get("confidence", 0.5)

        method = intent_result.get("method", "regex")



        log_intent_detected(user_id, intent, confidence, msg[:100])

        logger.info(f"[{user_id}] 旧状态={old_state}, 意图={intent}({confidence:.2f}, {method}), 信任={state.get('trust_level', 50)}")



        # ---- 3. 实体提取 → 更新槽位 ----

        ents = extract_entities(msg)

        any_extracted = False

        for k, v in ents.items():

            if v:

                old_v = state.get(k, "")

                state[k] = v

                any_extracted = True

                log_v = _mask_pii(v) if k == "phone" else v

                logger.info(f"[{user_id}] 槽位更新: {k} = {log_v}")

                log_slot_update(user_id, k, old_v, v)



        # off_topic 但提取到业务实体 → 修正意图

        if intent == "off_topic" and any_extracted:

            intent = "normal"

            logger.info(f"[{user_id}] 意图修正: off_topic -> normal")



        # ---- 4. 痛点检测 ----

        new_pains = detect_pain_points(msg, state)

        if new_pains:

            pain_points = state.get("pain_points", [])

            log_pain_detected(user_id, new_pains, len(pain_points))



        # ---- 5. 线索评分更新 ----

        old_lead_score = state.get("lead_score", 0)

        update_behavior_signals(state, intent, msg, any_extracted)

        new_lead_score = calculate_lead_score(state)

        lead_grade = get_lead_grade(new_lead_score)

        log_lead_score_change(state, old_lead_score, new_lead_score, f"intent={intent}")

        logger.info(f"[{user_id}] 线索分: {old_lead_score} -> {new_lead_score} ({lead_grade})")



        # ---- 6. 信任自动奖惩 ----

        old_trust = state.get("trust_level", 50)

        if any_extracted:

            adjust_trust(state, "user_shares_info", "用户提供信息")

        if intent == "confirm":

            adjust_trust(state, "user_confirms", "用户确认")

        if new_pains:

            adjust_trust(state, "empathy_confirm", f"检测到痛点: {new_pains}")

        new_trust = state.get("trust_level", 50)

        if new_trust != old_trust:

            log_trust_changed(user_id, intent, new_trust - old_trust, old_trust, new_trust)



        # ---- 6.5 辱骂处理 ----

        if intent == "insult":

            state["_insult_count"] = state.get("_insult_count", 0) + 1

            adjust_trust(state, "pushy_sales", "用户辱骂")

            insult_count = state["_insult_count"]

            logger.info(f"[{user_id}] 用户辱骂，第{insult_count}次")

            if insult_count >= 2:

                # 2次辱骂，转人工

                from code.human_collaboration import build_handoff_context, format_handoff_message

                context = build_handoff_context(state, new_lead_score)

                handoff_msg = format_handoff_message(context)

                from code.error_monitor import _send_alert

                _send_alert("用户辱骂转人工", handoff_msg, "warning")

                mark_user_human_active(user_id, "", 3)

                save_state(user_id, state)

                yield "我理解你现在情绪不太好，我这边帮你转接一下，稍等。"

                add_history(user_id, msg, "我理解你现在情绪不太好，我这边帮你转接一下，稍等。")

                _store_vector_memory(user_id, msg, "我理解你现在情绪不太好，我这边帮你转接一下，稍等。", state)

                return

            else:

                # 第一次辱骂，给出有尊严的回应

                insult_reply = "我理解你可能有些不满，但我确实是想帮你找到合适的方案。如果你现在不方便聊，随时找我都行。"

                save_state(user_id, state)

                yield insult_reply

                add_history(user_id, msg, insult_reply)

                _store_vector_memory(user_id, msg, insult_reply, state)

                flush_if_needed()

                return



        # ---- 7. 拒绝状态 ----

        if intent == "reject":

            state["rejected"] = True

            state["last_rejected_time"] = get_beijing_time().isoformat()

            state["_reject_count"] = state.get("_reject_count", 0) + 1

            # 调度挽回任务
            if RECOVERY_AVAILABLE:
                try:
                    recovery_info = should_attempt_recovery(state, intent, get_history(user_id))
                    if recovery_info.get("should_recover"):
                        schedule_recovery(user_id, recovery_info["reason"], state)
                        logger.info(f"[{user_id}] 挽回任务已调度: {recovery_info['reason']}")
                except Exception as rec_e:
                    logger.debug(f"挽回调度失败: {rec_e}")

            logger.info(f"[{user_id}] 用户表达拒绝，已记录")



        # ---- 8. 情绪挫败计数 ----

        if intent == "user_frustration":

            state["_frustration_count"] = state.get("_frustration_count", 0) + 1



        # ---- 9. 人工协作检查 ----

        should_handoff, handoff_level, handoff_reason = should_handoff_to_human(

            state, new_lead_score, intent

        )

        if should_handoff:

            context = build_handoff_context(state, new_lead_score)

            handoff_msg = format_handoff_message(context)

            log_human_handoff(user_id, handoff_reason, handoff_level, context)



            from code.channel_pusher import push_report_info

            # 推送给销售

            from code.error_monitor import _send_alert

            _send_alert("人工协作触发", handoff_msg, "warning")



            if handoff_level >= 3:

                # 完全转人工

                mark_user_human_active(user_id, "", handoff_level)

                save_state(user_id, state)

                yield "我这边帮你转接一下，稍等。"

                add_history(user_id, msg, "我这边帮你转接一下，稍等。")
                _store_vector_memory(user_id, msg, "我这边帮你转接一下，稍等。", state)

                return



        # 人工旁观提醒（级别1）

        if should_send_observe_alert(state, new_lead_score, intent):

            context = build_handoff_context(state, new_lead_score)

            suggestion = generate_sales_suggestion(state, new_lead_score, msg, intent)

            if suggestion:

                from code.error_monitor import _send_alert

                _send_alert("旁观提醒", f"用户{user_id}: {msg[:50]}\n建议: {suggestion}", "warning")



        # ---- 10. 周五问候检测 ----

        now = get_beijing_time()

        if now.weekday() == 4 and old_state in ("invite", "show_fee", "match_campus"):

            friday_greeting = KB.get("friday_greeting", ["周末愉快！"])[0]

            state["_append_friday_greeting"] = friday_greeting



        # ---- correct_info: clear incorrect fields and re-qualify ----

        if intent == "correct_info":

            # Clear potentially incorrect name if it matches education patterns

            name = state.get("name", "")

            if name and any(kw in name for kw in ["统招", "本科", "大专", "自考", "成人", "函授"]):

                state["name"] = ""

            # Reset qualification status for re-evaluation

            state["is_qualified"] = None

            # 清除向量记忆中的矛盾数据

            if VECTOR_MEMORY_AVAILABLE and _vm_clear_user:

                try:

                    cleared = _vm_clear_user(user_id)

                    logger.info(f"[{user_id}] correct_info: 已清除{cleared}条向量记忆")

                except Exception as e:

                    logger.debug(f"清除向量记忆失败: {e}")

            # 重置痛��（用户可能之前说了假的痛点）

            state["pain_points"] = []

            logger.info(f"[{user_id}] correct_info: 已重置is_qualified、pain_points、向量记忆")



        # ---- qualify phase: fee intent -> acknowledge + continue collecting ----

        if old_state == "qualify" and intent == "fee_intent":

            missing = []

            for k, v in [("graduated_year", "哪年毕业的"), ("age", "年龄"),

                          ("city", "在哪个城市"), ("education", "学历"),

                          ("direction", "想学什么方向")]:

                if not state.get(k):

                    missing.append(v)

            if missing:

                fee_ack = "费用的事你放心，后面我详细跟你说。"

                fee_ack += f"先把基础条件确认下——{'、'.join(missing[:2])}，简单说下？"

            else:

                fee_ack = "你的基本情况我都了解了，费用这块马上给你详细说明。"

            save_state(user_id, state)

            yield fee_ack

            add_history(user_id, msg, fee_ack)
            _store_vector_memory(user_id, msg, fee_ack, state)

            flush_if_needed()

            return



        # ---- 11. 三层护栏分类 ----

        tier = classify_question_tier(msg, old_state, intent)

        logger.info(f"[{user_id}] 护栏层级: {tier}")



        # ---- 12. 第二层：知识相关问题 → 自由回答 + 拉回 ----

        if tier == "layer2":

            adjust_trust(state, "provide_value", "回答知识相关问题")



            if _is_llm_available():

                system_prompt = get_layer2_system_prompt(msg, old_state, state)

                buffered_reply = ""

                try:

                    llm_start = time.time()

                    async for token in stream_llm(system_prompt, 0.5, "main"):

                        if token:

                            buffered_reply += token

                    _on_llm_success()

                    log_llm_call(user_id, "main", True, (time.time() - llm_start) * 1000, False)

                except Exception as e:

                    logger.warning(f"Layer2 LLM调用失败: {e}")

                    _on_llm_failure()

                    log_llm_call(user_id, "main", False, 0, True)

                    buffered_reply = ""

            else:

                buffered_reply = ""



            if not buffered_reply.strip():

                buffered_reply = get_layer3_reply(old_state, state, msg)



            ok, final_text = hard_check(buffered_reply, old_state, is_objection=False)

            if not ok:

                log_compliance_block(user_id, old_state, buffered_reply[:100], "global_forbidden")

                from code.error_monitor import alert_compliance_block

                alert_compliance_block(user_id, old_state, buffered_reply[:100])

            elif dynamic_check(final_text):

                final_text = "有些话我不方便线上说，周末来校区我当面给你讲清楚。"



            friday = state.pop("_append_friday_greeting", None)

            if friday:

                final_text += f"\n{friday}"



            save_state(user_id, state)

            for char in final_text:

                yield char

                await asyncio.sleep(0.02)

            add_history(user_id, msg, final_text)
            _store_vector_memory(user_id, msg, final_text, state)

            flush_if_needed()

            return



        # ---- 13. 第三层：完全无关 → 兜底 + 拉回 ----

        if tier == "layer3":

            if old_state == "qualify":

                required = REGULAR_SLOTS

                all_filled = all(isinstance(state.get(k), str) and state.get(k).strip()

                                 for k in required)

                if not all_filled:

                    new_state = "qualify"

                else:

                    # For correct_info, use a neutral intent to allow proper transition

                    check_intent = intent if intent != "correct_info" else "normal"

                    new_state = get_next_state(old_state, state, check_intent)

            else:

                new_state = get_next_state(old_state, state, intent)

            state["current_node"] = new_state

            save_state(user_id, state)

            log_state_transition(user_id, old_state, new_state, intent, new_trust, new_lead_score)



            reply = get_layer3_reply(old_state, state)

            adjust_trust(state, "irrelevant_reply", "用户问了无关问题")



            friday = state.pop("_append_friday_greeting", None)

            if friday:

                reply += f"\n{friday}"



            save_state(user_id, state)

            yield reply

            add_history(user_id, msg, reply)
            _store_vector_memory(user_id, msg, reply, state)

            flush_if_needed()

            return



        # ---- 14. 第一层：核心业务 ----



        # 情绪优先处理

        if intent == "user_frustration":

            lines = ["理解理解，是我这边没记清楚，抱歉！我已经记下了："]

            for k, v in [("education", "学历"), ("age", "年龄"),

                          ("graduated_year", "毕业年份"), ("city", "城市"),

                          ("direction", "方向")]:

                if state.get(k):

                    lines.append(f"{v}: {state[k]}")

            missing = [v for k, v in [("education", "学历"), ("age", "年龄"),

                                       ("graduated_year", "毕业年份"), ("city", "城市"),

                                       ("direction", "方向")] if not state.get(k)]

            if missing:

                lines.append(f"还需要补充：{'、'.join(missing)}，方便说下吗？")

            else:

                lines.append("咱们马上匹配校区。")

            full_reply = "\n".join(lines)

            save_state(user_id, state)

            yield full_reply

            add_history(user_id, msg, full_reply)
            _store_vector_memory(user_id, msg, full_reply, state)

            flush_if_needed()

            return



        # ---- 状态跳转（动态流程控制） ----

        skip_target = should_skip_steps(state, new_lead_score, intent)

        if skip_target:

            new_state = skip_target

            logger.info(f"[{user_id}] 动态跳转: {old_state} -> {new_state}")

        else:

            if old_state == "report_info" and intent != "off_topic":

                report_ents = extract_report_info(msg)

                for k, v in report_ents.items():

                    if k in REPORT_SLOTS and v:

                        state[k] = v

                save_state(user_id, state)



            if old_state == "qualify":

                required = REGULAR_SLOTS

                all_filled = all(isinstance(state.get(k), str) and state.get(k).strip()

                                 for k in required)

                if not all_filled:

                    new_state = "qualify"

                else:

                    # For correct_info, use a neutral intent to allow proper transition

                    check_intent = intent if intent != "correct_info" else "normal"

                    new_state = get_next_state(old_state, state, check_intent)

            elif old_state == "report_info":

                if state.get("name") and state.get("phone"):

                    new_state = "completed"

                else:

                    new_state = "report_info"

            else:

                new_state = get_next_state(old_state, state, intent)



        # correct_info回退到qualify时，重新检查资格判定

        if new_state == "qualify" and old_state != "qualify" and intent == "correct_info":

            required = REGULAR_SLOTS

            all_filled = all(isinstance(state.get(k), str) and state.get(k).strip()

                             for k in required)

            if all_filled:

                check_intent = "normal"

                new_state = get_next_state("qualify", state, check_intent)

                logger.info(f"[{user_id}] correct_info重判: {old_state} -> qualify -> {new_state}")



        # 动态信任门禁

        if new_state != old_state and not can_advance_dynamic(state, new_state, new_lead_score):

            logger.info(f"[{user_id}] 动态门禁阻止: {old_state} -> {new_state}")

            new_state = old_state



        state["current_node"] = new_state

        save_state(user_id, state)

        log_state_transition(user_id, old_state, new_state, intent, new_trust, new_lead_score)

        logger.info(f"[{user_id}] 状态变更: {old_state} -> {new_state}")



        # ---- 异议处理（动态策略 + LLM生成） ----

        if intent.startswith("objection_"):

            try:

                strategy = get_objection_strategy(intent, state, new_lead_score)

                state["_objection_strategy"] = strategy  # 传递给state_machine

                log_objection_handled(user_id, intent, "", strategy["round"], "processing")



                # 尝试LLM动态生成异议回应

                if strategy["use_llm"] and _is_llm_available() and new_lead_score >= 50:

                    personalized = await generate_objection_llm(intent, msg, state, get_history(user_id))

                    if personalized:

                        ok, final_text = hard_check(personalized, new_state, is_objection=True)

                        if ok:

                            friday = state.pop("_append_friday_greeting", None)

                            if friday:

                                final_text += f"\n{friday}"

                            save_state(user_id, state)

                            for char in final_text:

                                yield char

                                await asyncio.sleep(0.02)

                            add_history(user_id, msg, final_text)
                            _store_vector_memory(user_id, msg, final_text, state)

                            flush_if_needed()

                            return



                # 异议超限检查

                if strategy["escalate"]:

                    log_objection_handled(user_id, intent, "", strategy["round"], "escalated")

                    # 高价值用户转人工

                    if new_lead_score >= 60:

                        context = build_handoff_context(state, new_lead_score)

                        handoff_msg = format_handoff_message(context)

                        from code.error_monitor import _send_alert

                        _send_alert("异议超限转人工", handoff_msg, "warning")



            except Exception as obj_e:

                logger.warning(f"异议处理异常: {obj_e}")



        # ---- 痛点共情（个性化） ----

        if intent == "express_pain":

            pain_tag = new_pains[-1] if new_pains else state.get("pain_points", ["none"])[-1]



            if _is_llm_available() and new_lead_score >= 50:

                from code.content_generator import generate_personalized_empathy

                empathy = await generate_personalized_empathy(state, msg, pain_tag)

            else:

                from code.state_machine import get_pain_empathy

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

                template = f"{empathy}\n{guide}"

            else:

                template = "我理解你的顾虑。咱先看下基础条件，一步步来，好吗？"



            ok, final_text = hard_check(template, new_state, is_objection=False)

            if not ok:

                log_compliance_block(user_id, new_state, template[:100], "global_forbidden")

                from code.error_monitor import alert_compliance_block

                alert_compliance_block(user_id, new_state, template[:100])



            friday = state.pop("_append_friday_greeting", None)

            if friday:

                final_text += f"\n{friday}"



            save_state(user_id, state)

            for char in final_text:

                yield char

                await asyncio.sleep(0.02)

            add_history(user_id, msg, final_text)
            _store_vector_memory(user_id, msg, final_text, state)

            flush_if_needed()

            return



        # ---- 快速通道：校区确认/问费用 → 展示费用 ----

        if old_state == "match_campus" and intent in ("confirm", "fee_intent"):

            # A/B测试：检查是否有费用话术实验

            from code.experiment_manager import get_experiment_template, record_exposure

            exp_template = get_experiment_template(user_id, "show_fee", "fee_intent")

            if exp_template:

                fee_text = exp_template

                record_exposure(user_id, "fee_show", "variant")

            else:

                fee_text = KB["fee_show_core"][0] if state.get("is_qualified")                     else KB["fee_show_non_guarantee"][0]



            ok, safe_text = hard_check(fee_text, "show_fee", is_template=True)

            fee_text = safe_text

            state["fee_displayed"] = True

            state["current_node"] = "show_fee"

            adjust_trust(state, "user_confirms", "用户确认查看费用")

            save_state(user_id, state)

            yield fee_text

            add_history(user_id, msg, fee_text)
            _store_vector_memory(user_id, msg, fee_text, state)

            flush_if_needed()

            return



        # ---- 快速通道：邀约确认 → 报备模板 ----

        if old_state == "invite" and intent == "confirm":

            confirm_msg = "好的，那咱们就说定了，你把下面信息填一下，我帮你安排实训和住宿。"

            template = (

                "为了给你安排实训和住宿，麻烦你填一下以下信息发给我：\n"

                "姓名：\n性别：\n学历：\n毕业时间：\n专业：\n沟通岗位：\n"

                "联系电话：\n出发城市：\n实训基地：\n到达时间：\n是否需要住宿：\n其他备注："

            )

            full_reply = confirm_msg + "\n" + template



            visit_time_str = state.get("visit_time")

            appointment_time = None

            if visit_time_str:

                try:

                    appointment_time = datetime.fromisoformat(visit_time_str)

                except Exception:

                    pass

            if not appointment_time:

                now = get_beijing_time()

                days_until_tuesday = (1 - now.weekday()) % 7

                if days_until_tuesday == 0:

                    days_until_tuesday = 7

                appointment_time = now + timedelta(days=days_until_tuesday)

                appointment_time = appointment_time.replace(

                    hour=10, minute=0, second=0, microsecond=0

                )



            from code.scheduler import scheduler as task_scheduler

            from code.trial_follow_up import schedule_trial_follow_up

            schedule_trial_follow_up(task_scheduler, user_id, appointment_time)



            state["current_node"] = "report_info"

            adjust_trust(state, "user_confirms", "用户确认邀约")

            save_state(user_id, state)

            yield full_reply

            add_history(user_id, msg, full_reply)
            _store_vector_memory(user_id, msg, full_reply, state)

            flush_if_needed()

            return



        # ---- 报备信息收集 ----

        if new_state == "report_info" and intent != "off_topic":

            missing_fields = []

            if not state.get("name"):

                missing_fields.append("姓名")

            if not state.get("phone"):

                missing_fields.append("联系电话")

            prompt_text = f"还差{'、'.join(missing_fields)}，麻烦补一下。"

            yield prompt_text

            add_history(user_id, msg, prompt_text)
            _store_vector_memory(user_id, msg, prompt_text, state)

            flush_if_needed()

            return



        # ---- 报备完成 → completed ----

        if new_state == "completed" and old_state == "report_info":

            if state.get("name") and state.get("phone"):

                from code.channel_pusher import push_report_info

                push_report_info(user_id, state)

                full_reply = "收到，你的信息已提交，我们到时会提前联系你。"

                add_history(user_id, msg, full_reply)
                _store_vector_memory(user_id, msg, full_reply, state)

                log_conversation_end(user_id, "completed", state["_conversation_rounds"],

                                     time.time() - session_start,

                                     sum(1 for k in ["education", "age", "graduated_year", "city", "direction"] if state.get(k)))

                yield full_reply

                flush_if_needed()

                return

            else:

                state["current_node"] = "report_info"

                save_state(user_id, state)

                missing_fields = []

                if not state.get("name"):

                    missing_fields.append("姓名")

                if not state.get("phone"):

                    missing_fields.append("联系电话")

                prompt_text = f"还差{'、'.join(missing_fields)}，麻烦补一下。"

                yield prompt_text

                add_history(user_id, msg, prompt_text)
                _store_vector_memory(user_id, msg, prompt_text, state)

                flush_if_needed()

                return



        # ---- 核心改造：分层决策架构 ----



        # 关键节点：模板直出（保证合规）

        if new_state in TEMPLATE_NODES:

            instr = generate_reply_instruction(old_state, new_state, state, intent, new_lead_score)

            template = instr["template"]



            is_objection = intent.startswith("objection_")

            ok, final_text = hard_check(template, new_state, is_objection=is_objection)



            if not ok:

                log_compliance_block(user_id, new_state, template[:100], "stage_forbidden")

                from code.error_monitor import alert_compliance_block

                alert_compliance_block(user_id, new_state, template[:100])



            friday = state.pop("_append_friday_greeting", None)

            if friday:

                final_text += f"\n{friday}"



            save_state(user_id, state)

            for char in final_text:

                yield char

                await asyncio.sleep(0.02)

            add_history(user_id, msg, final_text)
            _store_vector_memory(user_id, msg, final_text, state)

            flush_if_needed()

            return



        # 非关键节点：让LLM自主决策

        if new_state in LLM_NODES and _is_llm_available():

            history = get_history(user_id)

            history = _truncate_history_by_token(history, max_tokens=1500)



            llm_reply = await generate_llm_decision(

                state, intent, collected_slots,

                state.get("pain_points", []), new_lead_score,

                history, new_state, msg

            )



            if llm_reply:

                # 合规检查

                ok, final_text = hard_check(llm_reply, new_state, is_objection=False)

                if not ok:

                    # 合规失败，降级到模板

                    logger.warning(f"[{user_id}] LLM回复合规失败，降级到模板")

                    instr = generate_reply_instruction(old_state, new_state, state, intent, new_lead_score)

                    final_text = instr["template"]

                    ok, final_text = hard_check(final_text, new_state, is_objection=False)



                friday = state.pop("_append_friday_greeting", None)

                if friday:

                    final_text += f"\n{friday}"



                save_state(user_id, state)

                for char in final_text:

                    yield char

                    await asyncio.sleep(0.02)

                add_history(user_id, msg, final_text)
                _store_vector_memory(user_id, msg, final_text, state)

                flush_if_needed()

                return



        # 降级：模板回复

        instr = generate_reply_instruction(old_state, new_state, state, intent, new_lead_score)

        template = instr["template"]

        rules = instr.get("rules", [])

        forbidden = instr.get("forbidden", [])



        # LLM改写（带熔断保护）

        history = get_history(user_id)

        history = _truncate_history_by_token(history, max_tokens=1500)

        history_str = "\n".join(

            [f"用户：{h['user']}\n小范：{h['assistant']}" for h in history]

        )

        rules_str = "\n".join([f"- {r}" for r in rules])

        forbid_str = "\n绝对不能出现这些词或数字：" + ", ".join(forbidden)             if forbidden else ""



        constitution = CONFIG.get("persona_constitution", "")

        persona = CONFIG.get("persona", "")



        system_prompt = f"""{constitution}



{persona}



【强制指令】你必须输出与下面【原话】完全相同的文字。

禁止事项：

- 严禁替换任何称呼，原话是什么就输出什么

- 严禁添加原文没有的任何字、词、标点

- 严禁删除原文的任何字、词、标点

- 严禁改变句子结构

- 严禁出现"培训""学费""上课""招生""老师""机构""保证""一定"等违禁词

唯一允许的改动：如果原话中有"说真的""你想想看"等口语，可以替换为同义口语（如"讲真的""你想下"）



原话：{template}



规则：

{rules_str}{forbid_str}



历史：

{history_str}



直接输出原话（不要加任何前缀或解释）："""



        buffered_reply = ""



        if _is_llm_available():

            temp = 0.1

            try:

                llm_start = time.time()

                async for token in stream_llm(system_prompt, temp, "main"):

                    if token:

                        buffered_reply += token

                _on_llm_success()

                log_llm_call(user_id, "main", True, (time.time() - llm_start) * 1000, False)

            except Exception as e:

                logger.warning(f"LLM改写失败: {e}")

                _on_llm_failure()

                log_llm_call(user_id, "main", False, 0, True)

                buffered_reply = ""

        else:

            logger.info("LLM熔断中，使用原始模板")



        if not buffered_reply.strip():

            buffered_reply = template



        # 合规检查

        is_objection = intent.startswith("objection_")

        ok, final_text = hard_check(buffered_reply, new_state, is_objection=is_objection)

        if not ok:

            log_compliance_block(user_id, new_state, buffered_reply[:100], "global_forbidden")

            from code.error_monitor import alert_compliance_block

            alert_compliance_block(user_id, new_state, buffered_reply[:100])

        elif dynamic_check(final_text):

            final_text = "有些话我不方便线上说，周末来校区我当面给你讲清楚。"



        friday = state.pop("_append_friday_greeting", None)

        if friday:

            final_text += f"\n{friday}"



        save_state(user_id, state)



        for char in final_text:

            yield char

            await asyncio.sleep(0.02)



        add_history(user_id, msg, final_text)
        _store_vector_memory(user_id, msg, final_text, state)

        flush_if_needed()



    except Exception as e:

        logger.error(f"处理失败: {e}", exc_info=True)

        from code.error_monitor import alert_unexpected_error

        alert_unexpected_error(user_id, str(e))

        yield "我这边出了点小问题，你再说一遍？"

