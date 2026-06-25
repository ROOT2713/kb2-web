"""Text cleaning pipeline.

Ported from: kb-web server.py clean_pipeline() L1100-L1112, clean_watermarks() L1035-L1058,
             clean_page_artifacts() L1059-L1065, clean_html_residuals() L1066-L1072,
             clean_encoding_errors() L1073-L1079, normalize_whitespace() L1080-L1094,
             clean_transcript_errors() L1095-L1099, filename_to_title() L1113-L1146,
             deai_postprocess() L1147-L1163, normalize_query() L231-L234,
             _fix_encoding() L235-L241, _extract_numbers() L242-L248,
             normalize_standard_numbers() L249-L276, expand_amount_tiers() L277-L321
"""

import html as _html_mod
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ── 去AI味后处理 + 逻辑校验（quality-gate feature）──

# 禁用词表：(AI味表达, 替换建议)
_DEAI_RULES = [
    ("综上所述，", ""),
    ("总而言之，", ""),
    ("值得注意的是，", ""),
    ("值得注意的是：", ""),
    ("此外，", ""),  # 需要上下文感知，先去掉逗号前缀
    ("另外，", ""),
    ("不仅", ""),  # 简化处理，prompt层面已要求拆句
    ("而且", "同时"),
    ("具有重要意义", "有具体影响"),
    ("发挥着重要作用", "起到关键作用"),
    ("不断提升", "逐步提高"),
    ("日益完善", "持续优化"),
    ("相关人员", "操作人员"),
    ("相关部门", "责任部门"),
    ("在一定程度上", "部分"),
    ("在…方面", "针对"),
]


def clean_watermarks(text: str) -> str:
    """清洗常见网站水印和无效内容"""
    # 清洗重复的网站水印行 (如 www.bzfxw.com)
    text = re.sub(r'(?:^|\n)(?:www\.\w+\.(?:com|cn|net|org)\s*){2,}', '\n', text, flags=re.MULTILINE)
    # 清洗单独一行的水印
    text = re.sub(r'^\s*www\.\w+\.(?:com|cn|net|org)\s*$', '', text, flags=re.MULTILINE)
    # 清洗 [fQTQT ... hQ芅弣] 类乱码标记
    text = re.sub(r'\[fQTQT\s+www\.\w+\.\w+\s+h.?\]', '', text)
    # D2增强：清洗版权/水印文字
    _WATERMARK_PATTERNS = [
        r'(?:版权所有|翻印必究|侵权必究|未经.?授权.{0,6}(?:不得|禁止).{0,10}(?:转载|复制|传播))',
        r'(?:本文档|本资料|本文件).{0,6}仅供.{0,10}(?:学习|参考|内部|交流)',
        r'(?:仅供|限于).{0,6}(?:学习|参考|内部|交流|研究).{0,6}(?:使用|用途)',
        r'(?:内部资料|机密文件| Confidential).{0,10}(?:请勿|禁止).{0,6}(?:外传|泄露|传播)',
        r'(?:免责声明|声明：|Disclaimer).{0,40}(?:不代表|不承担|仅供参考)',
        r'(?:下载自|来源：|出处：)\s*(?:www\.)?\w+\.(?:com|cn|net|org)',
        r'(?:转发|分享|下载).{0,6}(?:请注明|注明出处|侵删)',
    ]
    for pat in _WATERMARK_PATTERNS:
        text = re.sub(pat, '', text, flags=re.IGNORECASE)
    # 清洗连续空行（超过2行合并为2行）
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def clean_page_artifacts(text: str) -> str:
    """去除页眉页脚：第X页/共Y页、Page X of Y、页码行"""
    text = re.sub(r'第\s*\d+\s*页\s*/\s*共\s*\d+\s*页', '', text)
    text = re.sub(r'Page\s+\d+\s*(of\s+\d+)?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\s*[-—]\s*\d+\s*[-—]\s*$', '', text, flags=re.MULTILINE)
    return text.strip()


def clean_html_residuals(text: str) -> str:
    """去除HTML标签残留和HTML实体"""
    text = _html_mod.unescape(text)
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'</?(div|span|p|table|tr|td|th|img|a)[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'style="[^"]*"', '', text)
    return text.strip()


def clean_encoding_errors(text: str) -> str:
    """去除替换字符U+FFFD、零宽字符、BOM"""
    text = text.replace('�', '')
    text = text.replace('​', '').replace('‌', '').replace('‍', '')
    text = text.replace('﻿', '')
    return text


def normalize_whitespace(text: str) -> str:
    """全角数字字母转半角，连续空格压缩"""
    result = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            result.append(' ')
        else:
            result.append(ch)
    text = ''.join(result)
    text = re.sub(r'[ \t]+', ' ', text)
    return text


def clean_transcript_errors(text: str) -> str:
    """视频转录专用：去除口语填充词"""
    text = re.sub(r'(?<![一-龥])(?:嗯|啊|呃|那个|就是说|对吧)(?![一-龥])', '', text)
    return text.strip()


def clean_pipeline(text: str, source_hint: str = "") -> str:
    """可插拔清洗管线"""
    text = clean_watermarks(text)
    text = clean_page_artifacts(text)
    text = clean_html_residuals(text)
    text = clean_encoding_errors(text)
    text = normalize_whitespace(text)
    # 标准号规范化：GB／T → GB/T，确保文档和查询使用同一套格式
    text = normalize_standard_numbers(text)
    if "video" in source_hint or "whisper" in source_hint:
        text = clean_transcript_errors(text)
    # D4: 最终空行压缩（其他清洗步骤可能引入新的连续空行）
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


_GENERIC_TITLES = frozenset({
    "中华人民共和国国家标准",
    "国家标准",
    "行业标准",
    "地方标准",
    "团体标准",
    "企业标准",
})


def filename_to_title(filename: str, content: str = "") -> str:
    """从内容前20行提取 # 标题，跳过通用标题（如"中华人民共和国国家标准"），失败则用文件名去扩展名"""
    if content:
        for line in content.split("\n", 20)[:20]:
            line = line.strip()
            m = re.match(r'^#{1,3}\s+(.+)', line)
            if m:
                candidate = m.group(1).strip()
                if candidate not in _GENERIC_TITLES:
                    return candidate
    return Path(filename).stem or filename


def deai_postprocess(text: str) -> str:
    """去AI味后处理：替换禁用词，调整结构"""
    result = text

    # 1. 替换禁用词
    for old, new in _DEAI_RULES:
        result = result.replace(old, new)

    # 2. 修复连续空行（替换后可能产生）
    result = re.sub(r'\n{3,}', '\n\n', result)

    # 3. 修复标点后的多余空格
    result = re.sub(r'([。，；：！？])\s+', r'\1', result)

    return result


def normalize_query(q: str) -> str:
    """查询标准化：strip + 去多余空格 + 小写"""
    return ' '.join(q.strip().lower().split())


def _fix_encoding(text: str) -> str:
    """修复双重UTF-8编码（SQLite中常见的编码问题）"""
    try:
        return text.encode('latin-1').decode('utf-8')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def _extract_numbers(text: str) -> set:
    """提取文本中的所有数字（含中文数字单位如500万、3.5亿）"""
    text = _fix_encoding(text)  # 先修复编码
    # 阿拉伯数字（含小数、万/亿单位）
    nums = set(re.findall(r'\d+(?:\.\d+)?(?:万|亿|千|百)?', text))
    return nums


def normalize_standard_numbers(text: str) -> str:
    """统一标准号格式，提升BM25/Hindsight召回率。

    规范化规则：
    - ∕ → / (Unicode斜杠)
    - ＿ → _ → 空格 (全角下划线)
    - —/-- → - (各类破折号)
    - GA/T669 → GA/T 669 (T后无空格)
    - GA /T → GA/T (T前多余空格)
    - GA1383 → GA 1383 (前缀和数字间加空格)
    """
    # Unicode斜杠 → ASCII
    text = text.replace('∕', '/').replace('／', '/')
    # 全角下划线 → 空格（仅在标准号前缀模式中）
    text = re.sub(r'([A-Z]{2,4})[_＿]([A-Z])', r'\1 \2', text)
    # 各类破折号 → -
    text = text.replace('—', '-').replace('–', '-').replace('--', '-')
    # 标准号前缀后多余空格: "GA /T" → "GA/T"
    text = re.sub(r'([A-Z]{2,4})\s+(/\s*T)', r'\1\2', text)
    # T后无空格: "GA/T669" → "GA/T 669"
    text = re.sub(r'([A-Z]{2,4}/T)(\d)', r'\1 \2', text)
    # 前缀和数字间加空格: "GA1383" → "GA 1383"（但不匹配已正确格式化的）
    text = re.sub(r'([A-Z]{2,4})(?=\d{4})', r'\1 ', text)
    # 清理连续空格
    text = re.sub(r'  +', ' ', text)
    return text


def expand_amount_tiers(query: str) -> str:
    """金额档位扩展：将具体金额映射到文档中的分档区间，提升BM25召回率。

    例如："500万软件项目" → 追加 "300万以上"
          "200万项目" → 追加 "100万 300万"
    """
    # 政务IT造价常见分档（从造价指导书中提取）
    # 按金额排序：每个 tuple 是 (阈值, 关键词列表)
    TIERS = [
        (100,  ["100万以下", "100万元以下"]),
        (300,  ["100万", "100万元", "100万~300万", "300万元"]),
        (500,  ["300万以上", "300万元以上"]),
        (1000, ["500万", "1000万"]),
        (3000, ["1000万以上", "1000万元以上"]),
    ]

    # 提取查询中的金额（支持 "500万"、"500万元"、"500 万"）
    amounts = re.findall(r'(\d+(?:\.\d+)?)\s*(?:万|万元|百万)', query)
    if not amounts:
        return query

    tier_keywords = set()
    for amt_str in amounts:
        try:
            amt = float(amt_str)
        except ValueError:
            continue

        # 找到金额所在的分档区间
        for threshold, keywords in TIERS:
            if amt <= threshold:
                tier_keywords.update(keywords)
                break
        else:
            # 超过最大阈值
            tier_keywords.update(TIERS[-1][1])

    if not tier_keywords:
        return query

    # 追加分档关键词（不影响原始查询，只用于BM25召回）
    expanded = query + " " + " ".join(sorted(tier_keywords))
    return expanded
