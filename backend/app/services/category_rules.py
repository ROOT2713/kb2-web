"""文档分类规则模块 — 9 类分类体系的自动推断。"""
import re

CATEGORIES = {
    "gov":        "政务",
    "security":   "安全",
    "it":         "信息化",
    "cost":       "造价",
    "evaluation": "测评",
    "regulation": "法规",
    "standard":   "标准",
    "daily":      "日常",
    "news":       "资讯",
}

ISOLATED_CATEGORIES = frozenset({"daily", "news"})

BANK_TO_CATEGORY = {
    "standards":     "standard",
    "industry_docs": "it",
    "project_docs":  "it",
    "templates":     "it",
    "tech_guides":   "it",
    "checklist":     "evaluation",
    "business":      "cost",
    "xhs":           "news",
    "general":       None,
    "methodology":   "it",
}

CATEGORY_REGEX_RULES = [
    (r'(GB/?T?\s*\d+|GA/?T?\s*\d+|JJF\s*\d+|DB\d{2}/?T?\s*\d+|EGAG|GDZW)', "standard"),
    (r'(规范|标准|规程|导则)\s*(GB|GA|DB|JJF)', "standard"),
    (r'^[\[【（(]?(GB|GA|DB|JJF)', "standard"),
    (r'(法|条例|管理办法|实施办法|管理规定|实施细则)', "regulation"),
    (r'^中华人民共和国\w*法', "regulation"),
    (r'(通知|批复|意见|函|报告)\s*(\(?\d{4}\)?)', "gov"),
    (r'^(关于|印发|转发).*(通知|意见|批复|方案)', "gov"),
    (r'(国务院|省政府|市政府|区政府|发改委|财政厅|财政|工信厅)', "gov"),
    (r'(等保|等级保护|密码应用|密评|商用密码|网络安全|渗透测试|信息安全)', "security"),
    (r'(信息化|电子政务|数字化|数字政府|数据治理|项目管理|验收管理)', "it"),
    (r'(需求规格|概要设计|详细设计|技术方案|建设方案|运维方案)', "it"),
    (r'(软件开发|系统集成|数据中台|业务中台|技术架构)', "it"),
    (r'(造价|取费|费用|费率|定额|预算|概算|决算)', "cost"),
    (r'(软件造价|工程造价|投资估算)', "cost"),
    (r'(测评|评测|检测|评估|验收|测试报告|评估报告)', "evaluation"),
    (r'(检查项|检查要求|核查力度)', "evaluation"),
    (r'(新闻|资讯|报道|快讯|动态|周报|月报|趋势)', "news"),
    (r'(日常|笔记|草稿|memo|note|README)', "daily"),
    (r'(综合|通用)', None),
]


def infer_category(title: str = "", filename: str = "", bank: str = "") -> str:
    """自动推断文档分类。优先级：关键词正则 > bank 映射 > 空字符串"""
    source = title or filename
    for pattern, cat in CATEGORY_REGEX_RULES:
        if re.search(pattern, source, re.IGNORECASE):
            if cat is not None:
                return cat
            break
    if bank in BANK_TO_CATEGORY and BANK_TO_CATEGORY[bank] is not None:
        return BANK_TO_CATEGORY[bank]
    return ""


def get_category_label(cat_key: str) -> str:
    return CATEGORIES.get(cat_key, cat_key)
