"""实体信息提取器 - 企业级改造版

主要改造:
1. 毕业年份正则歧义（"18年" 可能是年龄也可能是年份）
2. 毕业月份提取过于宽泛（任何"X月"都会匹配）
3. 报备信息专用提取（解析"字段：值"格式）
4. 年龄提取增加更多模式（"97年的""我95年"等）
5. 城市列表扩展+区级匹配
6. 方向提取增强（"安全""网络"等简称）
7. 经验年限+方向联合推断
"""
import re
from loguru import logger


def extract_entities(msg: str) -> dict:
    res = {
        "education": "", "age": "", "city": "", "graduated_year": "",
        "graduated_month": "", "major": "", "direction": "",
        "experience_years": "", "name": "", "phone": ""
    }
    logger.info(f"🔍 提取实体: {msg[:80]}")

    # ---- 姓名 ----
    n = re.search(r"(?:姓名[：:]\s*|我叫|我是|叫|名字是|名字叫)\s*([\u4e00-\u9fa5]{2,4})", msg)
    if n:
        candidate = n.group(1)
        exclude = {"大专", "本科", "硕士", "博士", "高中", "中专", "统招", "非统招",
                   "网安", "大数据", "想做", "想学", "想做网安", "想学大数据",
                   "转行", "内推", "实训", "报名", "统招本科", "统招大专",
                   "非统招本科", "非统招大专", "自考本科", "成人本科",
                   "计算机", "信息管理", "软件工程", "网络安全"}
        if candidate not in exclude:
            res["name"] = candidate

    # Fallback: short pure Chinese message (2-4 chars) likely a name
    if not res["name"] and 2 <= len(msg.strip()) <= 4:
        if re.fullmatch(r"[一-龥]{2,4}", msg.strip()):
            exclude_short = {"好的", "可以", "行吧", "嗯嗯", "对的", "是的", "没错",
                            "你好", "在吗", "了解", "明白", "知道", "不想", "不要",
                            "算了", "不用", "没空", "太远", "太贵", "考虑", "想想",
                            "转行", "学习", "网安", "大数据", "大专", "本科"}
            if msg.strip() not in exclude_short:
                res["name"] = msg.strip()
                logger.info(f"Name (fallback): {res['name']}")
            logger.info(f"✅ 姓名: {res['name']}")

    # ---- 电话 ----
    ph = re.search(r"(?:电话|手机|联系)[：:]*\s*(1[3-9]\d{9})", msg)
    if ph:
        res["phone"] = ph.group(1)
        logger.info(f"✅ 电话: {res['phone']}")
    else:
        ph = re.search(r"\b(1[3-9]\d{9})\b", msg)
        if ph:
            res["phone"] = ph.group(1)
            logger.info(f"✅ 电话: {res['phone']}")

    # ---- 学历 ----
    if re.search(r"硕士|研究生", msg):
        res["education"] = "硕士"
        logger.info(f"✅ 学历: {res['education']}")
    elif re.search(r"博士", msg):
        res["education"] = "博士"
        logger.info(f"✅ 学历: {res['education']}")
    elif "本科" in msg:
        is_non = any(k in msg for k in ["非统招", "成人", "自考", "函授", "专升本", "夜大"])
        res["education"] = f"{'非统招' if is_non else '统招'}本科"
        logger.info(f"✅ 学历: {res['education']}")
    elif "大专" in msg:
        is_non = any(k in msg for k in ["非统招", "成人", "自考", "函授", "夜大"])
        res["education"] = f"{'非统招' if is_non else '统招'}大专"
        logger.info(f"✅ 学历: {res['education']}")
    elif re.search(r"高中|中专|技校", msg):
        res["education"] = "高中/中专"
        logger.info(f"✅ 学历: {res['education']}")

    # ---- 年龄（增强：支持"97年的""我95年""90后"等） ----
    m = re.search(r"(?:我|今年|年龄[：:]?\s*)(\d{1,2})\s*(?:岁|周岁)", msg)
    if not m:
        m = re.search(r"(\d{1,2})\s*(?:岁|周岁)", msg)
    if m:
        age = int(m.group(1))
        if 18 <= age <= 50:
            res["age"] = str(age)
            logger.info(f"✅ 年龄: {res['age']}")
    if not res["age"]:
        # 从出生年份推断："97年的""我95年""90后"
        m = re.search(r"(?:我|本人|本人是)?(?:19[89]\d|20[01]\d)\s*(?:年的|年出生|后)", msg)
        if m:
            birth_str = re.search(r"(19[89]\d|20[01]\d)", m.group())
            if birth_str:
                birth_year = int(birth_str.group())
                from code.time_utils import get_beijing_time
                now = get_beijing_time()
                age = now.year - birth_year
                if 18 <= age <= 50:
                    res["age"] = str(age)
                    logger.info(f"✅ 年龄(推断): {res['age']}")
    if not res["age"]:
        # 短消息中的年龄: "29，上海" "25广州" "28 杭州" (无"岁"后缀)
        # 条件: 消息较短(<=15字)且包含城市名，数字在18-50之间
        cities_short = ["广州","深圳","杭州","成都","武汉","南昌","北京","上海",
                        "长沙","南京","重庆","西安","郑州","合肥","福州","厦门",
                        "南宁","昆明","贵阳","太原","济南","天津","东莞","佛山",
                        "苏州","无锡","宁波","青岛","大连","沈阳","长春","哈尔滨",
                        "石家庄","赣州"]
        has_city = any(c in msg for c in cities_short)
        if has_city and len(msg.strip()) <= 15:
            # Pattern 1: number + separator (29，上海 / 25 广州)
            m = re.search(r"(\d{2})\s*[，,\s]", msg)
            if not m:
                # Pattern 2: number directly before city (25广州)
                city_pattern = "|".join(re.escape(c) for c in cities_short)
                m = re.search(r"(\d{2})(?=" + city_pattern + ")", msg)
            if m:
                age = int(m.group(1))
                if 18 <= age <= 50:
                    res["age"] = str(age)
                    logger.info(f"✅ 年龄(短消息): {res['age']}")
    if not res["age"]:
        # "90后""95后"等
        m = re.search(r"(8[0-9]|9[0-5])后", msg)
        if m:
            decade = int(m.group(1))
            birth_year = 1900 + decade if decade >= 80 else 2000 + decade
            from code.time_utils import get_beijing_time
            age = get_beijing_time().year - birth_year
            if 18 <= age <= 50:
                res["age"] = str(age)
                logger.info(f"✅ 年龄(代际推断): {res['age']}")

    # ---- 城市（增强：区级匹配） ----
    # 先匹配市辖区，提取所属城市
    district_map = {
        "白云": "广州", "海珠": "广州", "番禺": "广州", "天河": "广州", "越秀": "广州",
        "钱塘": "杭州", "临平": "杭州", "西湖": "杭州", "余杭": "杭州", "萧山": "杭州",
        "南山": "深圳", "福田": "深圳", "宝安": "深圳", "龙岗": "深圳", "罗湖": "深圳",
        "红谷": "南昌", "青山湖": "南昌",
    }
    for district, city in district_map.items():
        if district in msg:
            res["city"] = city
            logger.info(f"✅ 区→城市: {district} -> {city}")
            break

    if not res["city"]:
        cities_priority = [
            ("赣州", ["赣州"]),
            ("广州", ["广州", "羊城"]),
            ("深圳", ["深圳", "鹏城"]),
            ("杭州", ["杭州"]),
            ("成都", ["成都", "蓉城"]),
            ("武汉", ["武汉", "江城"]),
            ("南昌", ["南昌"]),
            ("北京", ["北京"]),
            ("上海", ["上海"]),
            ("长沙", ["长沙"]),
            ("南京", ["南京"]),
            ("重庆", ["重庆"]),
            ("西安", ["西安"]),
            ("郑州", ["郑州"]),
            ("合肥", ["合肥"]),
            ("福州", ["福州"]),
            ("厦门", ["厦门"]),
            ("南宁", ["南宁"]),
            ("昆明", ["昆明"]),
            ("贵阳", ["贵阳"]),
            ("太原", ["太原"]),
            ("济南", ["济南"]),
            ("天津", ["天津"]),
            ("东莞", ["东莞"]),
            ("佛山", ["佛山"]),
            ("苏州", ["苏州"]),
            ("无锡", ["无锡"]),
            ("宁波", ["宁波"]),
            ("青岛", ["青岛"]),
            ("大连", ["大连"]),
            ("沈阳", ["沈阳"]),
            ("长春", ["长春"]),
            ("哈尔滨", ["哈尔滨"]),
            ("石家庄", ["石家庄"]),
        ]
        for city, aliases in cities_priority:
            if any(a in msg for a in aliases):
                res["city"] = city
                logger.info(f"✅ 城市: {city}")
                break

    if not res["city"]:
        province_map = {
            "江西": "赣州", "广东": "广州", "浙江": "杭州",
            "湖南": "长沙", "湖北": "武汉", "四川": "成都",
            "福建": "福州", "广西": "南宁", "云南": "昆明",
            "贵州": "贵阳", "山西": "太原", "山东": "济南",
            "河北": "石家庄", "辽宁": "沈阳", "吉林": "长春",
            "黑龙江": "哈尔滨", "江苏": "南京", "安徽": "合肥",
        }
        for province, default_city in province_map.items():
            if province in msg:
                res["city"] = default_city
                logger.info(f"✅ 省份->城市: {province} -> {default_city}")
                break

    # ---- 毕业年份 ----
    m = re.search(r"(\d{4})\s*年\s*(?:毕业|届|毕业的)", msg)
    if not m:
        m = re.search(r"(?:毕业|届)\s*[于在]?\s*(\d{4})", msg)
    if not m:
        m = re.search(r"(\d{2})\s*年\s*(?:毕业|届)", msg)
        if m:
            year = "20" + m.group(1)
        else:
            year = None
    else:
        year = m.group(1) if m else None

    if year:
        year_int = int(year)
        if 2000 <= year_int <= 2030:
            res["graduated_year"] = year
            logger.info(f"✅ 毕业年份: {year}")

    # Relative graduation year: "毕业两年了" "刚毕业" "去年毕业"
    if not res["graduated_year"]:
        from code.time_utils import get_beijing_time
        now = get_beijing_time()
        m_rel = re.search(r"(?:毕业|届)(?:了\s*)?(\d)\s*年", msg)
        if m_rel:
            years_ago = int(m_rel.group(1))
            res["graduated_year"] = str(now.year - years_ago)
            logger.info(f"Relative grad year: {res['graduated_year']} ({years_ago}y ago)")
        elif re.search(r"刚\s*毕业|今年\s*毕业|应届", msg):
            res["graduated_year"] = str(now.year)
            logger.info(f"Fresh grad: {res['graduated_year']}")
        elif re.search(r"去年\s*毕业", msg):
            res["graduated_year"] = str(now.year - 1)
            logger.info(f"Last year grad: {res['graduated_year']}")


    # ---- 毕业月份 ----
    if res["graduated_year"]:
        mo = re.search(r"(\d{1,2})\s*月\s*(?:毕业|拿证|离校)", msg)
        if not mo:
            mo = re.search(r"\d{4}\s*年\s*(\d{1,2})\s*月", msg)
        if mo:
            month = int(mo.group(1))
            if 1 <= month <= 12:
                res["graduated_month"] = str(month)
                logger.info(f"✅ 毕业月份: {res['graduated_month']}")

    # ---- 专业 ----
    if "体育" in msg:
        res["major"] = "体育"
        logger.info("✅ 专业: 体育")
    elif "艺术" in msg:
        res["major"] = "艺术"
        logger.info("✅ 专业: 艺术")
    elif re.search(r"计算机|软件工程|软件技术|信息工程|信息管理", msg):
        res["major"] = "计算机"
        logger.info("✅ 专业: 计算机")
    elif re.search(r"电商|电子商务", msg):
        res["major"] = "电商"
        logger.info("✅ 专业: 电商")
    elif re.search(r"机电|机械|电子工程|自动化", msg):
        res["major"] = "机电"
        logger.info("✅ 专业: 机电")
    elif re.search(r"会计|财务|金融", msg):
        res["major"] = "会计"
        logger.info("✅ 专业: 会计")

    # ---- 方向（增强：支持简称，排除"安全感""安全第一"等非方向语境） ----
    if re.search(r"网安|网络安全|信息安全|渗透|红蓝|攻防|安全方向|安全岗位|做安全|学安全|安全工程师", msg):
        res["direction"] = "网安"
        logger.info("✅ 方向: 网安")
    elif re.search(r"大数据|数据分析|数据开发|数开", msg):
        res["direction"] = "大数据"
        logger.info("✅ 方向: 大数据")

    # ---- 经验年限 ----
    m = re.search(r"(\d{1,2})\s*年\s*(?:经验|工作经验|项目经验)", msg)
    if not m:
        m = re.search(r"(?:有|做了|干了)\s*(\d{1,2})\s*年", msg)
    if m:
        exp = int(m.group(1))
        if 1 <= exp <= 30:
            res["experience_years"] = str(exp)
            logger.info(f"✅ 经验: {exp}年")

    # ---- 经验+方向联合推断 ----
    # "3年网安经验" → 经验年限+方向同时提取
    if not res["experience_years"] or not res["direction"]:
        m = re.search(r"(\d{1,2})\s*年\s*(网安|网络安全|大数据|安全|数据)", msg)
        if m:
            exp = int(m.group(1))
            if 1 <= exp <= 30 and not res["experience_years"]:
                res["experience_years"] = str(exp)
                logger.info(f"✅ 经验(联合): {exp}年")
            dir_text = m.group(2)
            if not res["direction"]:
                if dir_text in ("网安", "网络安全", "安全"):
                    res["direction"] = "网安"
                elif dir_text in ("大数据", "数据"):
                    res["direction"] = "大数据"
                logger.info(f"✅ 方向(联合): {res['direction']}")

    logger.info(f"📦 提取完成: { {k: v for k, v in res.items() if v} }")
    return res


def extract_report_info(msg: str) -> dict:
    """
    报备信息专用提取器
    修复: 原实现直接调用 extract_entities，无法解析"字段：值"格式

    支持两种格式:
    1. 结构化: "姓名：张三\n性别：男\n..."
    2. 自然语言: "我叫张三，电话13800138000"
    """
    field_mapping = {
        "姓名": "name",
        "性别": "gender",
        "学历": "education",
        "毕业时间": "graduation_time",
        "专业": "major",
        "沟通岗位": "target_position",
        "联系电话": "phone",
        "电话": "phone",
        "出发城市": "departure_city",
        "实训基地": "campus_base",
        "到达时间": "arrival_time",
        "是否需要住宿": "need_accommodation",
        "住宿": "need_accommodation",
        "其他备注": "remarks",
        "备注": "remarks",
    }

    result = {}

    # 策略1: 结构化解析（"字段：值"格式）
    for line in msg.split("\n"):
        line = line.strip()
        if not line:
            continue
        for cn_field, en_field in field_mapping.items():
            if line.startswith(cn_field):
                # 提取冒号后的值
                val = re.split(r"[：:]", line, maxsplit=1)
                if len(val) >= 2:
                    value = val[1].strip()
                    if value:
                        # 特殊处理: 如果有多个字段映射到同一个key，保留第一个
                        if en_field not in result:
                            result[en_field] = value
                break

    # 策略2: 对于没匹配到的字段，用自然语言提取器补充
    base_ents = extract_entities(msg)

    # 合并：结构化解析优先，自然语言补充
    for k, v in base_ents.items():
        if k in ("name", "phone", "education", "major", "city", "graduated_year"):
            if k not in result and v:
                result[k] = v

    # 特殊: need_accommodation 标准化
    if "need_accommodation" in result:
        val = result["need_accommodation"]
        if re.search(r"(是|需要|要|嗯|好)", val):
            result["need_accommodation"] = "是"
        elif re.search(r"(不|没|否)", val):
            result["need_accommodation"] = "否"

    if result:
        logger.info(f"📋 报备信息提取: {result}")

    return result
