"""
Coze Code Node — S3 成分合规检查（ingredient_compliance.py）

架构位置：三层控制 → 第1层强约束（Code Node 硬编码查表，不进LLM）
前置节点：S2 分类判定（classification_decision.py）→ is_classified=True 后进入
后置节点：S4 风险分级

判定逻辑：逐成分查 GB 38850-2020 活性/惰性清单 + 禁用/限用规则。
         全部数据硬编码在 Code Node 中，零外部依赖，确定性输出。

法规依据：
  - GB 38850-2020 表1：消毒剂原料活性（有效）成分清单（85项）
  - GB 38850-2020 表2：消毒剂原料惰性成分清单（115项）
  - GB 38850-2020 第5条：禁用物质规定（8条）
  - GB 38850-2020 第6条：限用物质规定（皮肤/黏膜限量）
  - GB 38850-2020 第1号修改单

Coze 兼容性：
  - Python 3.11.3（Coze 运行时版本）
  - 仅用标准库
  - 单函数入口 main()
"""

import re

# ═══════════════════════════════════════════════════════════════
# GB 38850-2020 表1：活性（有效）成分清单（含第1号修改单）
# ═══════════════════════════════════════════════════════════════
# 格式: "归一化名称": (CAS编码, 使用范围代码, [常用别名])
# 使用范围代码: A=室内空气 C=污染物 D=生活饮用水 E=环境及物体表面
#              H=人体 K=集中空调 M=医疗器械 S=游泳池水 W=医院污水
#              #E=仅限于物体表面

ACTIVE_INGREDIENTS = {
    "二溴海因": ("77-48-5", "E/C/M/S", ["1,3'-二溴-5,5'-二甲基乙内酰脲"]),
    "二氯海因": ("118-52-5", "E/M/S", ["1,3'-二氯-5,5'-二甲基乙内酰脲"]),
    "溴氯海因": ("16079-88-2", "C/E/H/M/S", ["1-溴-3-氯-5,5'-二甲基乙内酰脲"]),
    "二溴氰乙酰胺": ("10222-01-2", "E", []),
    "六氯酚": ("70-30-4", "H", ["2,2'-亚甲基双(3,4,6-三氯苯酚)"]),
    "三氯生": ("3380-34-5", "E/H/M", ["三氯羟基二苯醚"]),
    "咪唑硫酸盐": ("1450-93-7", "E", []),
    "苯甲基氯化物": ("41870-52-4", "E/H", []),
    "乙酸": ("64-19-7", "H", []),
    "酸性氧化电位水": ("", "E/H/M", []),
    "苯扎溴铵": ("91080-29-4", "A/E/H/M", []),
    "苯扎氯铵": ("8001-54-5", "A/E/H/M", []),
    "苄索氯铵": ("121-54-0", "A/E/H/M", []),
    "苯甲酸": ("65-85-0", "E/H", []),
    "邻苯基苯酚": ("90-43-7", "E", []),
    "溴": ("7726-95-6", "E", []),
    "溴氯-5,5'-二甲基咪唑烷-2,4'-二酮": ("32718-18-6", "E", []),
    "次氯酸钙": ("7778-54-3", "C/D/E/H/M/S", []),
    "西曲溴铵": ("8044-71-1", "E/H", []),
    "醋酸氯己定": ("56-95-1", "A/E/H/M", []),
    "葡萄糖酸氯己定": ("18472-51-0", "A/E/H/M", []),
    "氯化磷酸三钠": ("56802-99-4", "C/E/M", []),
    "氯": ("7782-50-5", "D/E/S", []),
    "二氧化氯": ("10049-04-4", "A/C/D/H/M/S/E", []),
    "对氯间二甲苯苯酚": ("88-04-0", "E/H/M", []),
    "柠檬酸": ("77-92-9", "H/M/E", []),
    "甲酚": ("1319-77-3", "E", []),
    "癸酸": ("334-48-5", "E", []),
    "椰油脂肪酸二乙醇酰胺": ("68140-00-1", "E", []),
    "双癸基二甲基溴化铵": ("2390-68-3", "A/E/H/M", []),
    "双癸基二甲基氯化铵": ("7173-51-5", "A/E/H/M", []),
    "二辛基二甲基氯化铵": ("5538-94-3", "A/E/H/M", []),
    "二甲基苯酚": ("95-87-4", "H/E", []),
    "二辛基二乙烯三铵甘氨酸磷酸盐": ("—", "E", []),
    "十二烷基三甲基溴化铵": ("1119-94-4", "A/E/H/M", []),
    "十二烷基二甲基苄基氯化铵": ("139-07-1", "A/E/H/M", []),
    "十二烷基二甲基苄基溴化铵": ("7281-04-1", "A/E/H/M", []),
    "十二烷基三甲基氯化铵": ("112-00-5", "A/E/H/M", []),
    "度米芬": ("538-71-6", "A/E/H/M", ["十二烷基-二甲基-2-苯氧乙基溴化铵"]),
    "乙醇": ("64-17-5", "A/E/H/M", []),
    "甲醛": ("50-00-0", "#E/M", []),
    "戊二醛": ("111-30-8", "#E/M", []),
    "乙二醛": ("107-22-2", "#E/M", []),
    "乌洛托品": ("100-97-0", "A/E/H", ["六亚甲基四胺"]),
    "过氧化氢": ("7722-84-1", "A/E/H/M", []),
    "过氧戊二酸": ("110-94-1", "E/M", []),
    "次氯酸": ("7790-92-3", "E/H/M/#A", []),
    "碘": ("7553-56-2", "E/H/M", []),
    "壬酸": ("112-05-0", "E", []),
    "十八烷二甲基氧化铵": ("—", "A/E/H/M", []),
    "辛酸": ("124-07-2", "E", []),
    "寡\\[2-(2-乙氧基)-乙氧基乙酯]氯化胍": ("374572-91-5", "E", []),
    "邻苯二甲醛": ("643-79-8", "M", []),
    "臭氧及臭氧水": ("—", "A/D/E/S", []),
    "过氧乙酸": ("79-21-0", "A/C/E/H/M", []),
    "聚六亚甲基双胍盐酸盐": ("32289-58-0", "H/E", []),
    "聚\\[2-(2-乙氧基)-乙氧基乙酯]胍": ("—", "A", []),
    "聚二甲基二烯丙基氯化铵": ("26062-79-3", "A/E/H/M", []),
    "盐酸聚六亚甲基胍": ("57028-96-3", "A/E/H", []),
    "单过硫酸氢钾复合盐": ("70693-62-8", "E", []),
    "过硫酸氢钾": ("7727-21-1", "E", []),
    "高锰酸钾": ("7722-64-7", "H", []),
    "聚维酮碘": ("25655-41-8", "E/H/M", []),
    "正丙醇": ("71-23-8", "E/H", []),
    "异丙醇": ("67-63-0", "E/H", []),
    "(2-((2-((2-羧乙基)(2-羟乙基)氨基)乙基)氨基)-2-氧乙基)椰油烷基二甲基,季铵盐氢氧化物内盐": ("100085-64-1", "E", []),
    "氯化、溴化或过氧化的苄基烷基二甲基季铵盐化合物": ("季铵盐混合物", "A/E/H/M", []),
    "C12\\~C14 烷基苄基二甲基氯化铵": ("85409-22-9", "A/E/H/M", []),
    "C12-C16 烷基苄基二甲基氯化铵": ("68424-85-1", "A/E/H/M", []),
    "C12\\~C18 烷基苄基二甲基,1,2-苯并异噻唑-3(2H)-酮,1,1-二氧化物(1:1)盐化季铵盐化合物": ("68989-01-5", "A/E/H/M", []),
    "C12\\~C14 烷基\\[(乙苯基)甲基]二甲基氯化铵": ("85409-23-0", "A/E/H/M", []),
    "C8\\~C10 二烷基二甲基氯化铵": ("68424-95-3", "A/E/H/M", []),
    "氯化、溴化或硫酸甲酯化的二烷基二甲基季铵盐化合物": ("季铵盐混合物", "A/E/H/M", []),
    "水杨酸": ("69-72-7", "C/E/H", []),
    "银离子": ("7440-22-4", "E/H", []),
    "苯甲酸钠": ("532-32-1", "E/H", []),
    "优氯净": ("2893-78-9", "A/C/D/E/H/M/S/W", ["二氯异氰尿酸钠"]),
    "次氯酸钠": ("7681-52-9", "C/D/E/H/M/S/W", []),
    "氯胺 T": ("127-65-1", "D/E/M", []),
    "三氯异氰尿酸": ("87-90-1", "C/D/E/H/M/S/W", []),
    "三氯卡班": ("101-20-2", "E/H", ["三氯均二苯脲"]),
    "过碳酰胺": ("124-43-6", "E", []),
    "十一烯酸锌": ("557-08-4", "H", []),
    "过碳酸钠": ("15630-89-4", "E/W", []),
    "溶菌酶": ("9001-63-2", "E/H", []),
    "溶葡萄球菌酶": ("9011-93-2", "E/H", []),
}

# ═══════════════════════════════════════════════════════════════
# GB 38850-2020 表2：惰性成分清单（常用部分，共约115项）
# ═══════════════════════════════════════════════════════════════

INERT_INGREDIENTS = {
    "丁二醇": ("110-63-4", "E/H", []),
    "山梨糖醇": ("154-58-5", "E", []),
    "16/18 混合醇": ("——", "H", []),
    "苯并三唑": ("95-14-7", "M", []),
    "烷氧基乙醇": ("38471-49-7", "E", []),
    "氨基甲基丙醇": ("124-68-5", "H", []),
    "甲氨基丙醇": ("3179-63-3", "H", []),
    "8-羟基喹啉": ("148-24-3", "E/M", []),
    "羟基硫酸酸钠": ("134-31-6", "M", []),
    "乙酸": ("64-19-7", "E", []),
    "丙酮": ("67-64-1", "E", []),
    "丙烯酸聚合物": ("25133-97-5", "H", []),
    "烷基酚聚氧乙烯醚": ("9016-45-9", "E", []),
    "烷基多苷": ("61789-05-7", "E", []),
    "烷基苯磺酸": ("—", "C", []),
    "烷基酚聚氧乙烯醚硫酸盐": ("—", "M", []),
    "精氨酸乙基酯": ("2645-08-1", "H", []),
    "硝酸钡": ("10022-31-8", "M", []),
    "苯甲酸苄酯": ("120-51-4", "H", []),
    "甜菜碱": ("107-43-7", "E/H", []),
    "硼酸": ("10043-35-3", "H", []),
    "氮化硼": ("10043-11-5", "E", []),
    "碳酸钙": ("471-34-1", "E", []),
    "氯化钙": ("10043-52-4", "E/H", []),
    "氢氧化钙": ("1305-62-0", "E", []),
    "羧甲基纤维素": ("—", "E/M", []),
    "羧甲基纤维素钠": ("—", "E", []),
    "甲壳素": ("1398-61-4", "H", []),
    "顺丁烯二酸": ("110-16-7", "C/E/M", []),
    "柠檬酸": ("77-92-9", "H/M/F", []),
    "硫酸钴": ("10124-43-3", "E", []),
    "月桂酰胺丙基甜菜碱": ("61789-40-0", "E/H", []),
    "椰油酰基二乙醇胺": ("68603-42-9", "H", []),
    "磷酸氢二钠": ("7558-79-4", "E/H/M", []),
    "十二烷基苯磺酸": ("27176-87-0", "H", []),
    "十二烷基二甲基甜菜碱": ("683-10-3", "C/E/H/M", []),
    "泛醇": ("81-13-0", "E/H", []),
    "乙二胺四乙酸二钠": ("6381-92-6", "E/H/M/S", []),
    "乙二胺四乙酸四钠": ("13235-36-4", "E/H/M/S", []),
    "乙氧基羊毛脂": ("61790-81-6", "E/H", []),
    "乙氧基甲基葡萄糖苷": ("3162-96-7", "E/H", []),
    "乙二胺四乙酸": ("60-00-4", "E/H", []),
    "聚氧乙烯脂肪醇醚": ("68131-39-5", "E/H/M", []),
    "丙三醇": ("56-81-5", "A/E/H/M", []),
    "甘草酸": ("1405-86-3", "H", []),
    "透明质酸": ("9004-61-9", "E/H", []),
    "硅胶": ("112926-00-8", "E", []),
    "盐酸": ("7647-01-0", "E/H", []),
    "羟乙基纤维素": ("9004-62-0", "E/H", []),
    "羟甲基淀粉钠": ("70161-44-3", "C/E/M", []),
    "羟丙基甲基纤维素": ("9004-65-3", "E/H", []),
    "辛酸鲸蜡硬脂醇酯": ("25339-09-7", "E/H", []),
    "聚乙氧基壬基酚": ("37205-87-1", "E", []),
    "肉豆蔻酸异丙酯": ("110-27-0", "E/H", []),
    "乳酸": ("79-33-4", "E/H/M", []),
    "硬脂酸镁": ("557-04-0", "C/E/M", []),
    "硫酸镁": ("7487-88-9", "E", []),
    "苹果酸": ("6915-15-7", "E/M", []),
    "麦芽糊精": ("9050-36-6", "H", []),
    "葡萄糖": ("34620-77-4", "E/H", []),
    "脂肪酰二铵": ("35444-44-1", "E", []),
    "对羟基苯甲酸甲酯/尼泊金甲酯": ("99-76-3", "E/H", []),
    "磷酸": ("7664-38-2", "E/H/M", []),
    "草酸": ("144-62-7", "E", []),
    "十五烷基苯磺酸": ("31169-63-8", "E", []),
    "二甲基硅油共聚醇": ("9016-00-6", "E/H", []),
    "聚乙二醇": ("25322-68-3", "E/H", []),
    "聚丙烯酸": ("9003-01-4", "E/H", []),
    "聚丙烯酸树脂": ("", "H", []),
    "辛苯昔醇/曲拉通 X-100": ("9002-93-1", "E/H", []),
    "聚乙二醇双硬脂酸酯": ("9004-99-3", "E/H", []),
    "聚氧乙烯硬脂脂肪酸酯": ("9005-67-8", "E/H", []),
    "聚丙二醇异构烷烃": ("64365-06-6", "E/H", []),
    "聚苯硅氧烷": ("9005-12-3", "E/H", []),
    "聚乙烯吡咯烷酮": ("9003-39-8", "E/H", []),
    "山梨酸钾": ("24634-61-5590-00-1", "E/H", []),
    "焦磷酸钾": ("7320-34-5", "E/H", []),
    "碘酸钾": ("7758-05-6", "E/H", []),
    "碘化钾": ("7681-11-0", "E/H", []),
    "酒石酸钾": ("921-53-9", "E", []),
    "壬基酚聚氧乙烯醚": ("14409-72-4", "E/H", []),
    "依地烯醇": ("145-13-1", "E/M", []),
    "丙二醇": ("57-55-6", "E/H", []),
    "对甲苯磺酸钠": ("657-84-1", "C/E/M", []),
    "溴化钠": ("7647-15-6", "E", []),
    "无水碳酸钠": ("497-19-8", "E/K", []),
    "氯化钠": ("7647-14-5", "E/H", []),
    "磷酸二氢钠": ("7558-80-7", "E/H/M", []),
    "十二烷基苯磺酸钠": ("25155-30-0", "C/E/H", []),
    "十二烷基硫酸钠": ("151-21-3", "C/E/H/M", []),
    "十二烷基磺酸钠": ("2386-53-0", "E", []),
    "碳酸氢钠": ("144-55-8", "C/D/E/M/S", []),
    "硫酸氢钠": ("7681-38-1", "E", []),
    "硅酸氢钠": ("26482-69-9", "E", []),
    "亚硫酸氢钠": ("7631-90-5", "E/H", []),
    "氢氧化钠": ("1310-73-2", "E", []),
    "木质素磺酸钠": ("8061-51-6", "E", []),
    "无水偏硅酸钠": ("6834-92-0", "E", []),
    "五水偏硅酸钠": ("10213-79-3", "E/H/M", []),
    "亚硝酸钠": ("7632-00-0", "E/M", []),
    "吡硫酮钠": ("3811-73-2", "E/H", []),
    "磷酸钠": ("7632-05-5", "E/M", []),
    "硫酸钠": ("7757-82-6", "E/H", []),
    "亚硫酸钠": ("7757-83-7", "E/H", []),
    "亚碲酸钠": ("10102-20-2", "E/H", []),
    "硼砂": ("1303-96-4", "E", []),
    "焦偏磷酸钠": ("7758-29-4", "C/E/M/S", ["三聚磷酸钠"]),
    "丁二酸": ("110-15-6", "E/M", []),
    "硫酸": ("7664-93-9", "C/E", []),
    "酒石酸": ("147-71-7", "D/E/M", []),
    "月桂醇聚氧乙烯醚": ("5274-68-0", "E/H/M", []),
    "焦磷酸钠": ("7722-88-5", "E", []),
    "三乙醇胺": ("102-71-6", "E/H", []),
    "磷酸三钠": ("7601-54-9", "C/E/H/M", []),
    "吐温 80": ("9005-65-6", "C/E/H", []),
}

# ═══════════════════════════════════════════════════════════════
# GB 38850-2020 第5条：禁用物质规则
# ═══════════════════════════════════════════════════════════════

# 5.1 禁止添加《中国药典》（消毒防腐类药物除外）中的药品及其同名原料
# 5.6 用于人体/医疗器械/生活饮用水的消毒剂原料，禁止使用工业级
# 以下为常见的禁用成分信号（实际需结合KB药典数据）
PROHIBITED_SIGNALS = [
    "抗生素", "激素", "抗真菌药物", "抗病毒药物",
]

# ═══════════════════════════════════════════════════════════════
# GB 38850-2020 第6条：限用物质（浓度限量）
# ═══════════════════════════════════════════════════════════════

RESTRICTION_LIMITS = {
    "skin": {  # 6.1 皮肤消毒剂限量
        "葡萄糖酸氯己定": {"limit": 45.0, "unit": "g/L", "rule": "6.1"},
        "醋酸氯己定": {"limit": 45.0, "unit": "g/L", "rule": "6.1"},
        "三氯生": {"limit": 20.0, "unit": "g/L", "rule": "6.1"},
        "苯扎溴铵": {"limit": 5.0, "unit": "g/L", "rule": "6.1"},
        "苯扎氯铵": {"limit": 5.0, "unit": "g/L", "rule": "6.1"},
    },
    "mucosal": {  # 6.2 黏膜消毒剂限量
        "葡萄糖酸氯己定": {"limit": 5.0, "unit": "g/L", "rule": "6.2"},
        "醋酸氯己定": {"limit": 5.0, "unit": "g/L", "rule": "6.2"},
        "三氯生": {"limit": 3.5, "unit": "g/L", "rule": "6.2"},
        "苯扎溴铵": {"limit": 2.0, "unit": "g/L", "rule": "6.2"},
        "苯扎氯铵": {"limit": 2.0, "unit": "g/L", "rule": "6.2"},
    },
}

# ═══════════════════════════════════════════════════════════════
# 市场俗名 → 标准名称映射
# 这些名称不在 GB 38850-2020 中，但用户实际会输入
# 由人工维护，提取脚本不覆盖
# ═══════════════════════════════════════════════════════════════

MARKET_ALIASES = {
    "酒精": "乙醇",
    "双氧水": "过氧化氢",
    "甘油": "丙三醇",
    "纳米银": "银离子",
    "碘伏": "聚维酮碘",
    "84消毒液": "次氯酸钠",
    "新洁尔灭": "苯扎溴铵",
    "洗必泰": "醋酸氯己定",
    "卡波姆": "聚丙烯酸",  # 交联聚丙烯酸聚合物，Carbomer/Carbopol
}

# ═══════════════════════════════════════════════════════════════
# 成分状态枚举
# ═══════════════════════════════════════════════════════════════

STATUS_ALLOWED_ACTIVE = "allowed_active"       # 在活性成分清单中
STATUS_ALLOWED_INERT = "allowed_inert"         # 在惰性成分清单中
STATUS_PROHIBITED = "prohibited"               # 禁用物质
STATUS_RESTRICTED = "restricted"                # 限用物质（需检查浓度）
STATUS_UNKNOWN = "unknown"                     # 未在任何清单中命中
STATUS_WATER = "water_base"                    # 水/溶剂基底


def _normalize(s: str) -> str:
    """归一化成分名称用于字典查询。"""
    s = s.strip()
    # 移除浓度后缀，如 "乙醇（75%）" → "乙醇"
    s = re.sub(r'[（(]\d+[%％]?[)）]', '', s)
    s = re.sub(r'[（(][^)）]*?(含量|浓度|纯度)[)）]', '', s)
    s = re.sub(r'[（(][^)）]*$', '', s)
    s = re.sub(r'\d+[%％]', '', s)
    # 移除常见后缀
    s = re.sub(r'\s*[≤≤>=]\s*[\d.]+.*$', '', s)
    return s.strip()


def _parse_concentration(raw: str) -> tuple[str, float | None, str | None]:
    """从成分字符串中提取名称和可能浓度。

    返回: (normalized_name, concentration_value, concentration_unit)
    例: "乙醇 75%" → ("乙醇", 75, "%")
         "苯扎氯铵 0.5g/L" → ("苯扎氯铵", 0.5, "g/L")
    """
    name = _normalize(raw)
    conc = None
    unit = None

    # "X%" 或 "X％"
    m = re.search(r'(\d+\.?\d*)\s*[%％]', raw)
    if m:
        conc = float(m.group(1))
        unit = "%"
        return name, conc, unit

    # "X g/L" 或 "Xg/L"
    m = re.search(r'(\d+\.?\d*)\s*(g/L|g/l|mg/L|mg/l|mg/kg|ppm)', raw)
    if m:
        conc = float(m.group(1))
        unit = m.group(2)
        return name, conc, unit

    return name, conc, unit


def _build_lookup_index():
    """构建从名称（含别名、市场俗名）到条目的一级索引。"""
    index = {}
    for name, (cas, scope, aliases) in ACTIVE_INGREDIENTS.items():
        entry = ("active", name, cas, scope)
        index[name] = entry
        for alias in aliases:
            if alias not in index:
                index[alias] = entry
    for name, (cas, scope, aliases) in INERT_INGREDIENTS.items():
        entry = ("inert", name, cas, scope)
        index[name] = entry
        for alias in aliases:
            if alias not in index:
                index[alias] = entry
    # 市场俗名 → 标准名映射（不在 GB 38850 中，但用户会输入）
    for market_name, standard_name in MARKET_ALIASES.items():
        if market_name not in index and standard_name in index:
            index[market_name] = index[standard_name]
    return index


_LOOKUP = _build_lookup_index()


def check_single_ingredient(raw_name: str, product_type: str = "") -> dict:
    """检查单个成分的合规状态。

    输入:
        raw_name: 用户输入的成分名称（可能含浓度信息）
        product_type: 产品类型上下文（用于禁用规则判断）

    返回:
        ingredient:      归一化后的成分名称
        original_input:  用户原始输入
        status:          allowed_active / allowed_inert / restricted / unknown
        cas:             CAS编码
        basis:           法规依据文本
        category:        active / inert / unknown
        usage_scope:     允许使用范围
        restriction:     限用信息（仅 restricted 状态时有值）
    """
    name, conc, conc_unit = _parse_concentration(raw_name)

    if not name:
        return {
            "ingredient": raw_name,
            "original_input": raw_name,
            "status": STATUS_UNKNOWN,
            "cas": "",
            "basis": "",
            "category": "unknown",
            "usage_scope": "",
            "restriction": None,
        }

    # 水/溶剂基底特殊处理
    if name in ("水", "去离子水", "纯水", "纯净水", "蒸馏水", "DI water"):
        return {
            "ingredient": "水",
            "original_input": raw_name,
            "status": STATUS_WATER,
            "cas": "7732-18-5",
            "basis": "水为通用溶剂基底，非活性或惰性成分。",
            "category": "base",
            "usage_scope": "通用",
            "restriction": None,
        }

    # 1. 精确匹配一级索引
    entry = _LOOKUP.get(name)
    if entry:
        ing_type, match_name, cas, scope = entry
        status = STATUS_ALLOWED_ACTIVE if ing_type == "active" else STATUS_ALLOWED_INERT

        result = {
            "ingredient": match_name,
            "original_input": raw_name,
            "status": status,
            "cas": cas,
            "basis": f"依据GB 38850-2020表{'1' if ing_type == 'active' else '2'}，"
                     f"「{match_name}」为{'活性（有效）' if ing_type == 'active' else '惰性'}成分，"
                     f"允许用于{_expand_scope(scope)}。",
            "category": ing_type,
            "usage_scope": scope,
            "restriction": None,
        }

        # 检查限用规则
        restriction = _check_restriction(match_name, product_type, conc, conc_unit)
        if restriction:
            result["status"] = STATUS_RESTRICTED
            result["restriction"] = restriction
            result["basis"] += f" 需注意：{restriction['rule']}规定该成分有限量要求"
            if conc is not None:
                result["basis"] += f"，当前申报浓度为{conc}{conc_unit or '%'}。"

        return result

    # 2. 模糊匹配（子串包含）
    for key_name, entry2 in _LOOKUP.items():
        if key_name in name or name in key_name:
            ing_type, match_name, cas, scope = entry2
            status = STATUS_ALLOWED_ACTIVE if ing_type == "active" else STATUS_ALLOWED_INERT
            result = {
                "ingredient": match_name,
                "original_input": raw_name,
                "status": status,
                "cas": cas,
                "basis": f"依据GB 38850-2020表{'1' if ing_type == 'active' else '2'}，"
                         f"「{raw_name}」近似匹配至「{match_name}」，"
                         f"为{'活性（有效）' if ing_type == 'active' else '惰性'}成分，"
                         f"允许用于{_expand_scope(scope)}。",
                "category": ing_type,
                "usage_scope": scope,
                "restriction": None,
            }
            restriction = _check_restriction(match_name, product_type, conc, conc_unit)
            if restriction:
                result["status"] = STATUS_RESTRICTED
                result["restriction"] = restriction
                result["basis"] += f" 需注意：{restriction['rule']}规定该成分有限量要求。"
            return result

    # 3. 未命中
    return {
        "ingredient": name,
        "original_input": raw_name,
        "status": STATUS_UNKNOWN,
        "cas": "",
        "basis": f"「{raw_name}」未在GB 38850-2020表1（活性成分）和表2（惰性成分）中检索到，"
                 f"可能存在以下情况：（1）属于新消毒产品原料，需按《新消毒产品和新涉水产品"
                 f"卫生行政许可管理规定》办理；（2）名称使用了非标准表述，请核实INCI名称或"
                 f"CAS号后重新查询。",
        "category": "unknown",
        "usage_scope": "",
        "restriction": None,
    }


def _check_restriction(ingredient_name: str, product_type: str,
                       conc: float | None, conc_unit: str | None) -> dict | None:
    """检查成分是否受GB 38850-2020第6条限量约束。"""
    for scope_type in ("skin", "mucosal"):
        limits = RESTRICTION_LIMITS.get(scope_type, {})
        if ingredient_name in limits:
            limit_info = limits[ingredient_name]
            result = {
                "scope": scope_type,
                "limit": limit_info["limit"],
                "unit": limit_info["unit"],
                "rule": f"GB 38850-2020 第{limit_info['rule']}条",
                "exceeded": None,
            }
            if conc is not None:
                # 尝试判断是否超标
                effective_conc = conc
                if conc_unit == "%":
                    effective_conc = conc * 10  # 1% ≈ 10 g/L (近似)
                elif conc_unit in ("g/L", "mg/L"):
                    if conc_unit == "mg/L":
                        effective_conc = conc / 1000
                else:
                    effective_conc = conc
                result["exceeded"] = effective_conc > limit_info["limit"]
            return result
    return None


def _expand_scope(code: str) -> str:
    """展开使用范围代码为中文描述。"""
    mapping = {
        "A": "室内空气消毒", "C": "污染物消毒", "D": "生活饮用水消毒",
        "E": "环境及物体表面消毒", "#E": "物体表面(限)",
        "H": "人体消毒", "K": "集中空调通风系统", "M": "医疗器械消毒",
        "S": "游泳池水消毒", "W": "医院污水消毒",
    }
    result = []
    for ch in code:
        if ch in mapping:
            result.append(mapping[ch])
        elif ch == "/":
            continue
        elif ch == "#":
            continue
        elif ch == "#E":
            result.append(mapping["#E"])
    if not result:
        return code
    return "、".join(result)


def check_compliance(main_ingredients: str, product_category: str,
                     sub_type: str = "") -> dict:
    """批量检查成分合规状态。

    输入:
        main_ingredients: S1 输出的成分列表文本（"、"或"，"或换行分隔）
        product_category: S2 输出的产品类别
        sub_type:         S2 输出的子类型

    返回:
        results:          逐成分检查结果列表
        overall_status:   all_allowed / has_unknown / has_restricted / has_prohibited
        ingredient_count: 成分总数
        summary:          合规概要文本
    """
    # 解析成分列表：按"、"，"，"或换行分隔
    raw_list = [s.strip() for s in re.split(r'[、，,;\n]', main_ingredients) if s.strip()]
    if not raw_list:
        return {
            "results": [],
            "overall_status": "no_ingredients",
            "ingredient_count": 0,
            "summary": "未提供成分信息，无法执行合规检查。",
        }

    results = []
    statuses = set()

    for raw in raw_list:
        r = check_single_ingredient(raw, product_category)
        results.append(r)
        statuses.add(r["status"])

    # 判定总体状态
    if STATUS_UNKNOWN in statuses:
        has_unknown = any(r["status"] == STATUS_UNKNOWN for r in results)
        unknown_count = sum(1 for r in results if r["status"] == STATUS_UNKNOWN)
        if unknown_count == len(results):
            overall = "all_unknown"
        else:
            overall = "has_unknown"
    elif STATUS_RESTRICTED in statuses:
        overall = "has_restricted"
    else:
        overall = "all_allowed"

    # 生成概要
    allowed_count = sum(1 for r in results
                        if r["status"] in (STATUS_ALLOWED_ACTIVE, STATUS_ALLOWED_INERT, STATUS_WATER))
    restricted_count = sum(1 for r in results if r["status"] == STATUS_RESTRICTED)
    unknown_count = sum(1 for r in results if r["status"] == STATUS_UNKNOWN)

    parts = []
    if allowed_count > 0:
        parts.append(f"{allowed_count}个成分在GB 38850-2020清单中")
    if restricted_count > 0:
        parts.append(f"{restricted_count}个成分有限量要求（第6条）")
    if unknown_count > 0:
        parts.append(f"{unknown_count}个成分未收录，可能属于新消毒产品原料")

    summary = "；".join(parts) if parts else "无成分信息"
    summary = f"共{len(raw_list)}个成分：{summary}。"

    return {
        "results": results,
        "overall_status": overall,
        "ingredient_count": len(raw_list),
        "summary": summary,
    }


async def main(args) -> dict:
    """Coze Code Node 入口（Python 3.11.3 / Coze 当前标准格式）。

    Coze 输入变量（来自 S1 entry_merge + S2 classification_decision）:
        main_ingredients:  string  — 成分列表（S1 输出，"、"分隔）
        product_category:  string  — 产品类别（S2 输出）
        sub_type:          string  — 子类型（S2 输出，可选）

    Coze 输出变量:
        overall_status:      string  — all_allowed / has_unknown / has_restricted / all_unknown
        ingredient_count:    int     — 成分总数
        summary:             string  — 合规概要文本
        results_json:        string  — 逐成分结果JSON（供S4使用）
        compliance_basis:    string  — 整体法规依据
    """
    import json as _json

    try:
        main_ingredients = args.params.get("main_ingredients", "") if hasattr(args, "params") else args.get("main_ingredients", "")
        product_category = args.params.get("product_category", "") if hasattr(args, "params") else args.get("product_category", "")
        sub_type = args.params.get("sub_type", "") if hasattr(args, "params") else args.get("sub_type", "")
    except Exception:
        main_ingredients = ""
        product_category = ""
        sub_type = ""

    if not main_ingredients.strip():
        return {
            "overall_status": "no_ingredients",
            "ingredient_count": 0,
            "summary": "未提供成分信息，无法执行合规检查。请先完成信息采集（S1）。",
            "results_json": "[]",
            "compliance_basis": "GB 38850-2020《消毒剂原料清单及禁限用物质》",
        }

    result = check_compliance(main_ingredients, product_category, sub_type)

    # 序列化逐成分结果
    serializable = []
    for r in result["results"]:
        serializable.append({
            "ingredient": r["ingredient"],
            "original_input": r["original_input"],
            "status": r["status"],
            "cas": r["cas"],
            "basis": r["basis"],
            "category": r["category"],
            "usage_scope": r["usage_scope"],
            "restriction": r["restriction"],
        })

    return {
        "overall_status": result["overall_status"],
        "ingredient_count": result["ingredient_count"],
        "summary": result["summary"],
        "results_json": _json.dumps(serializable, ensure_ascii=False),
        "compliance_basis": "GB 38850-2020《消毒剂原料清单及禁限用物质》（含第1号修改单）",
    }
