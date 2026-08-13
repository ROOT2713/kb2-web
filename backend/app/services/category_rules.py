"""文档分类规则模块 — 三级分类体系（大类→分类→子分类）的自动推断。

层次结构：
  super_category (大类层): 信息化项目 | 个人资讯
    category (中类层): it/security/evaluation/cost/gov/regulation/standard/supervision/consulting/business/daily/news
      subcategory (细分类): 信息化管理办法/等级报告-安全文档/验收测评文档/...

2026-07-20 v2.0: 增加 subcategory 推断 + 修复 BANK_TO_CATEGORY 映射
"""
import re

# ── 大类 (super_category) 映射 ───────────────────────────────────
SUPER_CATEGORY_MAP = {
    "it":         "信息化项目",
    "security":   "信息化项目",
    "evaluation": "信息化项目",
    "cost":       "信息化项目",
    "gov":        "信息化项目",
    "regulation": "信息化项目",
    "standard":   "信息化项目",
    "supervision":"信息化项目",
    "consulting": "信息化项目",
    "business":   "信息化项目",
    # 个人资讯
    "daily":      "个人资讯",
    "news":       "个人资讯",
}

SUPER_CATEGORY_DEFAULT = "信息化项目"  # fallback

def get_super_category(cat_key: str) -> str:
    """返回 category 所属的大类。"""
    return SUPER_CATEGORY_MAP.get(cat_key, SUPER_CATEGORY_DEFAULT)


# ── 中类 (category) ───────────────────────────────────────────────
CATEGORIES = {
    "gov":         "政务",
    "security":    "安全",
    "it":          "信息化",
    "cost":        "造价",
    "evaluation":  "测评",
    "regulation":  "法规",
    "standard":    "标准",
    "daily":       "日常",
    "news":        "资讯",
    "supervision": "监理",
    "consulting":  "咨询",
    "business":    "商密",
}

ISOLATED_CATEGORIES = frozenset({"daily", "news"})

BANK_TO_CATEGORY = {
    "standards":      "standard",
    "industry_docs":  "it",
    "project_docs":   "it",
    "templates":      "it",
    "tech_guides":    "it",
    "checklist":      "evaluation",
    "business":       "business",     # 修复: 原为 cost
    "咨询":           "consulting",    # 修复: 原为 news
    "kb_xhs":         "daily",
    "general":        None,
    "methodology":    "it",
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
    (r'(监理)', "supervision"),
    (r'(咨询)', "consulting"),
    (r'(商务|合同|招标|投标|采购|报价|商密)', "business"),
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


# ── 细分类 (subcategory) 推断 ────────────────────────────────────
# 规则格式: (regex_pattern, category_match, subcategory_label)
SUBCATEGORY_RULES = [
    # 信息化项目下的细分类
    (r'信息化管理|信息化项目|项目管理|管理办法|实施办法', "it", "信息化管理办法"),
    (r'等级|等保.*测评|等级保护|网络安全等级|安全文档|安全报告', "security", "等级报告/安全文档"),
    (r'密码|密评|商用密码|密码测评|密码应用', "security", "商业密码测评文档"),
    (r'验收|验收测评|软硬件.*验收|验收.*软硬件|工程.*验收', "evaluation", "验收测评文档"),
    (r'商务|合同|招标|投标|采购|报价|商业|商密', "business", "商密文档"),
    (r'模板|template|范本|格式|样式', "it", "模板文档"),
    (r'造价|取费|定额|预算|概算|决算|费用|费率', "cost", "造价文档"),
    (r'监理|supervision', "supervision", "监理文档"),
    (r'咨询|consult|顾问|建议书', "consulting", "咨询文档"),
    (r'测评|评测|检测|评估|测试|检查', "evaluation", "测评"),
    # 个人资讯下的细分类
    (r'XHS|xhs|小红书|日常|笔记|草稿|memo|note|日记|生活', "daily", "日常"),
    (r'新闻|资讯|动态|周报|月报|趋势|行业', "news", "资讯"),
    (r'技术|tech|guide|指南|教程|参考|manual', "it", "技术指导"),
    (r'AI|人工智能|机器学习|深度学习', "it", "AI/人工智能"),
]


def infer_subcategory(title: str = "", filename: str = "", bank: str = "",
                      category: str = "", doc_type: str = "") -> str:
    """自动推断子分类标签。
    
    返回中文子类标签（如"信息化管理办法"），无匹配则返回空字符串。
    """
    source = title or filename or ""
    if bank == "kb_xhs":
        return "日常"
    for pattern, cat_match, subcat_label in SUBCATEGORY_RULES:
        if category and cat_match != category:
            continue  # category 不匹配则跳过
        if re.search(pattern, source, re.IGNORECASE):
            return subcat_label
    return ""


# ── 子分类 → category 正向映射（供前端树构建）───────────────────
SUBCATEGORY_TO_CATEGORY = {
    "信息化管理办法":      "it",
    "等级报告/安全文档":    "security",
    "商业密码测评文档":    "security",
    "验收测评文档":        "evaluation",
    "商密文档":            "business",
    "模板文档":            "it",
    "造价文档":            "cost",
    "监理文档":            "supervision",
    "咨询文档":            "consulting",
    "测评":                "evaluation",
    "日常":                "daily",
    "资讯":                "news",
    "技术指导":            "it",
    "AI/人工智能":         "it",
}

# ── 前端展示用的分类树 ───────────────────────────────────────────
SUPER_CATEGORY_ORDER = ["信息化项目", "个人资讯"]
