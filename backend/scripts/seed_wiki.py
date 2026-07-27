"""Seed script — populate wiki_entries with high-frequency standard entries.

Run: cd /home/ubuntu/kb2-web/backend && python3 scripts/seed_wiki.py
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Must be before any app imports to set env
os.environ.setdefault("APP_ENV", "production")

from app.services import wiki_service
from app.models.database import init_db

# Initialize tables
init_db()

entries = [
    # ── GB 50174-2017 数据中心设计规范 ──
    {
        "title": "数据中心设计规范",
        "standard_no": "GB 50174-2017",
        "category": "standard", "subcategory": "数据中心",
        "tags": ["数据中心", "机房", "设计规范"],
        "summary": "GB 50174-2017 是数据中心机房设计的国家标准，规定机房分级（A/B/C三级）、环境要求（温度24±1℃）、供配电、布线等核心设计要求。",
        "content": json.dumps({
            "scope": "适用于新建、改建和扩建的数据中心机房设计，涵盖A级（容错）、B级（冗余）、C级（基本）三级分类。",
            "key_clauses": "5.1 温度要求：A/B级机房24±1℃，C级18-28℃\n5.2 湿度要求：A/B级40-60%RH\n6.1 供配电：A级双路独立电源+BPS\n8.1 布线：采用上走线或下走线方式",
            "application": "数据中心设计、机房建设、IDC规划等场景的核心设计依据。",
        }, ensure_ascii=False),
        "importance": 10, "status": "published",
    },
    # ── GB/T 22239-2019 等保2.0 ──
    {
        "title": "信息安全技术 网络安全等级保护基本要求",
        "standard_no": "GB/T 22239-2019",
        "category": "standard", "subcategory": "信息安全",
        "tags": ["等保", "网络安全", "信息安全", "等级保护"],
        "summary": "GB/T 22239-2019（等保2.0）是网络安全等级保护的核心标准，规定第一级至第四级系统的安全通用要求和安全扩展要求。",
        "content": json.dumps({
            "scope": "适用于指导分等级的信息系统安全建设、测评和监管。覆盖安全物理环境、安全通信网络、安全区域边界、安全计算环境、安全管理中心五大方面。",
            "key_clauses": "第三级系统要求：安全审计、入侵防范、恶意代码防范、数据备份恢复\n测评周期：第三级及以上系统每年至少一次等级测评",
            "application": "等保测评、安全整改、系统定级备案的核心依据。",
        }, ensure_ascii=False),
        "importance": 10, "status": "published",
    },
    # ── GB/T 28448-2019 等保测评要求 ──
    {
        "title": "信息安全技术 网络安全等级保护测评要求",
        "standard_no": "GB/T 28448-2019",
        "category": "standard", "subcategory": "信息安全",
        "tags": ["等保", "测评要求", "网络安全"],
        "summary": "GB/T 28448-2019 规定了网络安全等级保护测评的测评方法、测评内容和测评流程，与GB/T 22239配套使用。",
        "content": json.dumps({
            "scope": "适用于测评机构进行等级保护测评工作，也适用于运营者开展自查。",
            "key_clauses": "测评分为安全通用测评和物联网/工业控制系统等扩展测评\n测评流程：测评准备→方案编制→现场测评→分析报告",
            "application": "等保测评项目实施、测评报告编制的核心依据。",
        }, ensure_ascii=False),
        "importance": 9, "status": "published",
    },
    # ── GB 3096-2008 声环境质量标准 ──
    {
        "title": "声环境质量标准",
        "standard_no": "GB 3096-2008",
        "category": "standard", "subcategory": "声学",
        "tags": ["声环境", "噪音", "噪声限值"],
        "summary": "GB 3096-2008 规定了五类声环境功能区的环境噪声限值，是民用建筑隔声设计的基础标准。",
        "content": json.dumps({
            "scope": "适用于城乡声环境质量评价与管理。",
            "key_clauses": "0类（康复疗养）：昼间50dB，夜间40dB\n1类（居住文教）：昼间55dB，夜间45dB\n2类（商业居住混合）：昼间60dB，夜间50dB\n3类（工业）：昼间65dB，夜间55dB\n4类（交通干线）：昼间70dB，夜间55-60dB",
            "application": "建筑声学设计、环境影响评价、噪声投诉判定。",
        }, ensure_ascii=False),
        "importance": 8, "status": "published",
    },
    # ── GB 50052-2009 供配电系统设计规范 ──
    {
        "title": "供配电系统设计规范",
        "standard_no": "GB 50052-2009",
        "category": "standard", "subcategory": "供配电",
        "tags": ["供配电", "电气", "电力"],
        "summary": "GB 50052-2009 是供配电系统设计的国家标准，规定负荷分级、供电要求、变配电所设计等。",
        "content": json.dumps({
            "scope": "适用于新建、改建和扩建的供配电系统设计。",
            "key_clauses": "负荷分级：一级≥二级≥三级\n一级负荷需双路独立电源\n60A以上照明负荷采用三相四线制",
            "application": "建筑电气设计、机房供配电设计的核心依据。",
        }, ensure_ascii=False),
        "importance": 8, "status": "published",
    },
    # ── GB 50116 火灾自动报警系统设计规范 ──
    {
        "title": "火灾自动报警系统设计规范",
        "standard_no": "GB 50116",
        "category": "standard", "subcategory": "消防",
        "tags": ["消防", "火灾报警", "弱电"],
        "summary": "GB 50116 是火灾自动报警系统设计的国家标准，规定系统组成、探测器选择、报警区域划分和消防联动控制要求。",
        "content": json.dumps({
            "scope": "适用于新建、改建和扩建的工业与民用建筑火灾自动报警系统设计。",
            "key_clauses": "系统由火灾探测器、手动报警按钮、区域显示器、消防控制室设备等组成\n探测器按保护面积和保护半径设置\n消防联动控制包括切非消防电源、启动消防泵、迫降电梯等",
            "application": "消防系统工程设计、弱电系统集成的核心依据。",
        }, ensure_ascii=False),
        "importance": 8, "status": "published",
    },
    # ── GB 50348 安全防范工程技术标准 ──
    {
        "title": "安全防范工程技术标准",
        "standard_no": "GB 50348",
        "category": "standard", "subcategory": "安防",
        "tags": ["安防", "出入口控制", "视频监控"],
        "summary": "GB 50348 是安全防范工程设计的通用标准，涵盖视频监控、出入口控制、入侵报警等系统的设计、施工和验收要求。",
        "content": json.dumps({
            "scope": "适用于新建、改建和扩建的各类建（构）筑物的安全防范工程设计。",
            "key_clauses": "安防系统包括视频安防监控、入侵报警、出入口控制、电子巡查等子系统\n出入口控制系统由识别装置、控制单元和执行机构组成\n系统应满足安全等级要求，重点部位全方位防护",
            "application": "安防工程设计、弱电系统集成、安全检查的核心依据。",
        }, ensure_ascii=False),
        "importance": 8, "status": "published",
    },
    # ── GB 50462-2015 数据中心施工验收规范 ──
    {
        "title": "数据中心基础设施施工及验收规范",
        "standard_no": "GB 50462-2015",
        "category": "standard", "subcategory": "数据中心",
        "tags": ["数据中心", "施工验收", "机房"],
        "summary": "GB 50462-2015 规定了数据中心基础设施施工及验收的技术要求，与GB 50174配套使用。",
        "content": json.dumps({
            "scope": "适用于数据中心机房基础设施的施工和验收。",
            "key_clauses": "验收分为隐蔽工程验收、分项工程验收和竣工验收三个阶段\n配电系统需做负载测试\n环境系统需做运行调试",
            "application": "数据中心验收、机房施工管理的核心依据。",
        }, ensure_ascii=False),
        "importance": 7, "status": "published",
    },
    # ── 影院声学规范 ──
    {
        "title": "电影院建筑设计规范",
        "standard_no": "JGJ 58",
        "category": "standard", "subcategory": "声学",
        "tags": ["电影院", "混响时间", "声学"],
        "summary": "JGJ 58 规定了电影院观众厅的混响时间设计值，中频(500Hz)满场混响时间宜为0.5-0.7s。",
        "content": json.dumps({
            "scope": "适用于新建、改建的电影院建筑设计。",
            "key_clauses": "混响时间：500Hz满场0.5-0.7s\n银幕后的扬声器系统应有足够的声压级\n观众厅应有良好的声场均匀度",
            "application": "电影院设计、影音室声学设计。",
        }, ensure_ascii=False),
        "importance": 6, "status": "published",
    },
    # ── GB 50054-2011 低压配电设计规范 ──
    {
        "title": "低压配电设计规范",
        "standard_no": "GB 50054-2011",
        "category": "standard", "subcategory": "供配电",
        "tags": ["低压配电", "电气"],
        "summary": "GB 50054-2011 是低压配电系统设计的国家标准，规定配电箱设置、导线选择和接地保护等要求。",
        "content": json.dumps({
            "scope": "适用于交流1000V及以下的低压配电系统设计。",
            "key_clauses": "配电箱位置应便于操作和维护\n导线截面应根据负载电流和线路压降计算确定\n接地保护应符合安全要求",
            "application": "建筑电气设计、机房配电设计的核心依据。",
        }, ensure_ascii=False),
        "importance": 7, "status": "published",
    },
]

# ── 剧场声学条目（无标准编号，用 content field）──
entries.append({
    "title": "剧场观众厅混响时间设计值",
    "standard_no": "",
    "category": "standard", "subcategory": "声学",
    "tags": ["剧场", "混响时间", "声学设计"],
    "summary": "剧场观众厅的中频(500Hz)满场混响时间推荐值：歌剧1.2-1.4s，话剧0.8-1.0s。",
    "content": json.dumps({
        "scope": "适用于剧场的声学设计与评价。",
        "key_clauses": "歌剧观众厅：500Hz满场1.2-1.4s\n话剧观众厅：500Hz满场0.8-1.0s\n多功能厅：根据主要功能确定",
        "application": "剧场设计、演艺厅声学设计的参考依据。",
    }, ensure_ascii=False),
    "importance": 6, "status": "published",
})

# ── 政务核心条目 ──
{
    "title": "政府投资条例",
    "standard_no": "国务院令第712号",
    "category": "regulation", "subcategory": "政府投资",
    "tags": ["政府投资", "投资管理", "基本建设"],
    "summary": "政府投资条例（国务院令第712号）是规范政府投资行为的行政法规，对政府投资决策、年度计划、项目实施和监督管理作出全面规定。",
    "content": json.dumps({
        "scope": "适用于使用预算安排的资金进行的固定资产投资建设活动，包括新建、扩建、改建、技术改造等。",
        "key_clauses": "政府投资以非经营性项目为主\\n投资决策需经过前期论证和审批（重大项目需专家评审）\\n年度计划经批准后必须严格执行\\n项目完工后应及时办理竣工财务决算和资产移交",
        "application": "政务信息化项目的立项审批、预算审批、竣工决算的核心行政法规依据。",
    }, ensure_ascii=False),
    "importance": 9, "status": "published",
},
{
    "title": "中华人民共和国招标投标法",
    "standard_no": "主席令第21号",
    "category": "regulation", "subcategory": "招标投标",
    "tags": ["招标", "投标", "采购"],
    "summary": "招标投标法是规范招标投标活动的基本法律，对招标、投标、开标、评标和中标等环节作出全面规定。",
    "content": json.dumps({
        "scope": "适用于在中华人民共和国境内进行的所有招标投标活动。大型基础设施、公用事业等关系社会公共利益、公众安全的项目必须招标。",
        "key_clauses": "公开招标为原则，邀请招标为例外\\n招标文件不得要求特定供应商或含有倾向性条款\\n评标委员会由5人以上单数组成，技术经济专家不少于2/3\\n中标人确定后15日内向有关行政监督部门提交招标投标情况书面报告",
        "application": "政务信息化项目招标采购、工程建设招标、服务采购等场景的核心法律依据。",
    }, ensure_ascii=False),
    "importance": 9, "status": "published",
},
{
    "title": "信息系统工程监理规范",
    "standard_no": "GB/T 19668",
    "category": "standard", "subcategory": "监理",
    "tags": ["监理", "信息化监理", "信息系统"],
    "summary": "GB/T 19668 系列标准规定了信息系统工程监理的术语、通用布缆、电子设备机房等工程的监理规范。",
    "content": json.dumps({
        "scope": "适用于信息系统工程监理单位的监理活动，以及建设单位、承建单位对监理工作的配合与检查。覆盖信息化项目的质量、进度、投资控制等。",
        "key_clauses": "监理工作应贯穿系统规划、招标、设计、实施、验收全过程\\n监理方应独立于建设方和承建方\\n质量控制包括设备验收、施工监督、系统测试等环节",
        "application": "信息化项目监理、质量监督、验收评估的核心标准依据。",
    }, ensure_ascii=False),
    "importance": 8, "status": "published",
},
{
    "title": "中华人民共和国政府采购法",
    "standard_no": "主席令第14号",
    "category": "regulation", "subcategory": "政府采购",
    "tags": ["政府采购", "采购", "政务采购"],
    "summary": "政府采购法规定了政府机关使用财政性资金进行采购的行为规范，明确采购方式、程序和监督管理要求。",
    "content": json.dumps({
        "scope": "适用于各级国家机关、事业单位和团体组织使用财政性资金采购货物、工程和服务的行为。",
        "key_clauses": "政府采购实行集中采购和分散采购相结合\\n采购方式包括公开招标（为主）、邀请招标、竞争性谈判、询价、单一来源等\\n采购金额达到公开招标数额标准的必须公开招标\\n采购人不得以不合理的条件对供应商实行差别待遇",
        "application": "政务信息化采购、软件服务采购、硬件设备采购等场景的核心法律依据。",
    }, ensure_ascii=False),
    "importance": 8, "status": "published",
},
{
    "title": "中华人民共和国网络安全法",
    "standard_no": "主席令第53号",
    "category": "regulation", "subcategory": "网络安全",
    "tags": ["网络安全", "等级保护", "安全"],
    "summary": "网络安全法是网络安全领域的基础性法律，确立网络安全等级保护制度、关键信息基础设施保护、个人信息保护等核心制度。",
    "content": json.dumps({
        "scope": "适用于在中华人民共和国境内建设、运营、维护和使用网络以及网络安全的监督管理。",
        "key_clauses": "国家实行网络安全等级保护制度（第21条）\\n关键信息基础设施在等保基础上实行重点保护（第31条）\\n重要数据应境内存储、出境需安全评估（第37条）\\n网络运营者应制定应急预案并定期演练（第25条）",
        "application": "等保测评、网络安全建设、数据安全合规等场景的核心法律依据。",
    }, ensure_ascii=False),
    "importance": 9, "status": "published",
},

print(f"Inserting {len(entries)} wiki entries...")
count = 0
for e in entries:
    eid = wiki_service.create_entry(**e)
    if eid:
        count += 1
        print(f"  [{eid}] {e['title']} ({e['standard_no'] or '—'})")
    else:
        print(f"  ✗ FAILED: {e['title']}")

print(f"\nDone: {count}/{len(entries)} entries created.")

# Add relations between related standards
print("\nAdding cross-references...")
rels = [
    (1, 8, "配套规范", "GB 50174 vs GB 50462：设计与施工验收配套"),         # 数据中心设计 → 施工验收
    (2, 3, "配套规范", "GB/T 22239 vs GB/T 28448：等保基本要求与测评要求配套"),   # 等保基本要求 → 测评要求
    (4, 11, "引用关系", "GB 3096 是剧场声学设计的噪声限值依据"),             # 声环境 → 剧场
    (1, 5, "引用关系", "数据中心机房需符合供配电设计要求"),                  # 数据中心 → 供配电
    (1, 10, "引用关系", "数据中心需符合低压配电设计要求"),                  # 数据中心 → 低压配电
]
for src, tgt, rtype, desc in rels:
    ok = wiki_service.add_relation(src, tgt, rtype, desc)
    if ok:
        print(f"  {src} → {tgt}: {rtype}")
    else:
        print(f"  ✗ {src} → {tgt} failed")

print("\n✅ Seed complete!")
