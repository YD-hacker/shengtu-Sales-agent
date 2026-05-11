"""三层护栏系统 - 企业级交付版

第一层：核心业务硬限死
  收费、邀约、承诺等关键节点，话术一字不差，合规红线全量检查

第二层：辅助咨询软引导
  知识相关但话术库未覆盖的问题
  允许模型自由组织语言（温度0.5），但必须遵守护栏规则
  回答后强制拉回业务主线

第三层：完全未知礼貌兜底
  对无聊/无关问题，根据当前状态返回带进度引导的通用拒答
"""
import re
import yaml
from loguru import logger
from code.compliance_checker import hard_check
from code import KB_FILE

# 加载KB
with open(KB_FILE, encoding="utf-8") as f:
    KB = yaml.safe_load(f)["scripts"]

# ---- 第二层：知识相关问题识别 ----
KNOWLEDGE_ADJACENT_PATTERNS = [
    # 竞品对比
    re.compile(r"(达内|黑马|传智|尚硅课|课工场|极客|优就业|蜗牛|千锋|中公|牛客|拉勾).{0,5}(区别|不同|对比|哪个好|怎么样|靠谱)"),
    re.compile(r"(你们).{0,5}(和|跟|比).{0,5}(区别|不同|优势)"),
    # 课程相关
    re.compile(r"(网安|网络安全|大数据).{0,5}(好学吗|难不难|学什么|课程|内容|多久|多长时间)"),
    re.compile(r"(零基础|没基础).{0,5}(能学|学会|跟上|来得及)"),
    # 就业相关
    re.compile(r"(就业|找工作|薪资|工资|待遇|月薪).{0,5}(怎么样|多少|前景|方向|岗位)"),
    re.compile(r"(网安|网络安全).{0,5}(前景|未来|发展|需求|缺人)"),
    re.compile(r"(大数据).{0,5}(前景|未来|发展|需求)"),
    # 合同/保障
    re.compile(r"(合同|协议|保障).{0,5}(怎么签|什么样|内容|条款)"),
    # 学信网
    re.compile(r"学信网"),
    # 宿舍/环境
    re.compile(r"(宿舍|住宿|伙食|环境).{0,5}(怎么样|条件|几人)"),
    # 面试/考核
    re.compile(r"(面试|考核|笔试|机试).{0,5}(什么|怎样|难吗)"),
]

# ---- 第二层护栏规则 ----
LAYER2_RULES = [
    "绝对不能承诺就业率、薪资具体数字",
    "绝对不能说'包就业''保证就业'等违规词",
    "不能贬低竞争对手（不提竞品名字，只说'传统培训机构'）",
    "回答必须基于事实，不确定的要说'具体你可以来校区了解'",
    "回答后必须自然过渡到业务主线",
]


def classify_question_tier(msg: str, current_node: str, intent: str) -> str:
    """
    判断用户问题属于哪一层护栏
    """
    # 明确的业务意图 → 第一层
    if intent in ("confirm", "fee_intent", "correct_info", "user_frustration",
                  "newbie", "experienced", "icebreak_greet", "normal", "reject"):
        return "layer1"

    # 异议意图 → 第一层
    if intent.startswith("objection_"):
        return "layer1"

    # 痛点表达 → 第一层
    if intent == "express_pain":
        return "layer1"

    # off_topic → 先检查是否为知识相关问题
    if intent == "off_topic":
        # 检查是否匹配知识相关模式
        for pattern in KNOWLEDGE_ADJACENT_PATTERNS:
            if pattern.search(msg):
                return "layer2"
                # Company/institution info questions
        if re.search(r"(公司.*在哪|地址|搜不到|查不到|官网|你们.*公司|公司.*全称|多少.*学员|就业.*率|有.*合同|保障.*条款|正规|靠谱|口碑|评价)", msg):
            return "layer2"
        return "layer3"
def get_layer2_system_prompt(msg: str, current_node: str, state: dict) -> str:
    """
    生成第二层护栏的系统提示词
    """
    from code.model_router import CONFIG

    # 从KB读取拉回话术
    pullback_map = KB.get("pullback", {})
    pullback = pullback_map.get(current_node, "咱先把正事聊了？")

    rules_str = "\n".join([f"- {r}" for r in LAYER2_RULES])
    info_summary = _build_info_summary(state)

    system_prompt = f"""{CONFIG['persona']}

用户问了一个关于我们业务的问题，你需要给出真诚、有用的回答。

【已收集的用户信息】
{info_summary}

【用户的问题】
{msg}

【护栏规则 - 必须遵守】
{rules_str}

【格式要求】
1. 先直接回答用户的问题，态度真诚，不要回避
2. 回答完后，自然地加一句拉回业务主线：
   "{pullback}"
3. 控制在100字以内

直接输出："""

    return system_prompt


def get_layer3_reply(current_node: str, state: dict) -> str:
    """
    第三层：礼貌兜底 + 进度引导
    拉回话术从KB读取
    """
    pullback_map = KB.get("pullback", {})
    default_pullback = "咱先把正事办了吧？"
    hint = pullback_map.get(current_node, default_pullback)

    base = "这个我确实不太擅长聊😅"
    return f"{base} {hint}"


def _build_info_summary(state: dict) -> str:
    """构建用户信息摘要"""
    parts = []
    field_map = [
        ("education", "学历"), ("age", "年龄"), ("graduated_year", "毕业年份"),
        ("city", "城市"), ("direction", "方向"), ("major", "专业"),
    ]
    for k, label in field_map:
        v = state.get(k, "")
        if v:
            parts.append(f"{label}: {v}")
    return "\n".join(parts) if parts else "（尚未收集到用户信息）"
