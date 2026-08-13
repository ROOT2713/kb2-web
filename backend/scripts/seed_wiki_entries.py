"""Seed 20+ additional wiki entries for high-frequency standards."""
import json
import urllib.request
import urllib.error
import time

API = "http://localhost:3027/api/wiki"
AUTH = "http://localhost:3027/api/auth"

# Login
def login():
    data = json.dumps({"username": "admin", "password": "adminljj0806!"}).encode()
    req = urllib.request.Request(f"{AUTH}/login", data=data,
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())["access_token"]

token = login()
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
}

ENTRIES = [
    # ── 综合布线 ──
    {
        "title": "综合布线系统工程设计规范",
        "standard_no": "GB 50311-2016",
        "category": "standard", "subcategory": "综合布线",
        "summary": "建筑物综合布线系统的设计规范，涵盖工作区、水平干线、垂直干线、设备间、进线间等子系统设计要求。",
        "content": {
            "scope": "适用于建筑与建筑群综合布线系统工程设计。",
            "key_clauses": "5.1.1 工作区信息插座安装高度宜为300mm；6.1.1 水平子系统应采用4对非屏蔽/屏蔽对绞电缆；7.1.1 垂直干线子系统应采用光缆或大对数对绞电缆。",
            "application": "信息化机房和办公场所综合布线方案设计评审。",
        },
        "importance": 9, "status": "published",
    },
    {
        "title": "综合布线系统工程验收规范",
        "standard_no": "GB 50312-2016",
        "category": "standard", "subcategory": "综合布线",
        "summary": "综合布线系统工程施工及验收的技术要求与测试方法。",
        "content": {
            "scope": "适用于建筑与建筑群综合布线系统的工程验收。",
            "key_clauses": "5.0.1 电缆链路测试应包括连接图和长度、衰减、近端串扰等参数；6.0.1 光缆链路测试应包括衰减和长度。",
            "application": "弱电工程验收评审。",
        },
        "importance": 8, "status": "published",
    },
    # ── 智能建筑 ──
    {
        "title": "智能建筑设计标准",
        "standard_no": "GB 50314-2015",
        "category": "standard", "subcategory": "智能建筑",
        "summary": "智能建筑工程设计的技术标准，涵盖信息化应用系统、智能化集成系统、信息设施系统等。",
        "content": {
            "scope": "适用于新建、扩建和改建的智能建筑工程设计。",
            "key_clauses": "4.1.1 智能建筑应以绿色建筑为目标；5.1.1 信息化应用系统应包括公共服务、智能卡应用、物业运营管理。",
            "application": "政务数据中心和办公大楼的智能化方案评审。",
        },
        "importance": 9, "status": "published",
    },
    {
        "title": "建筑物电子信息系统防雷技术规范",
        "standard_no": "GB 50343-2012",
        "category": "standard", "subcategory": "智能建筑",
        "summary": "建筑物电子信息系统防雷设计、施工及验收技术规范，包含雷电防护等级划分。",
        "content": {
            "scope": "适用于建筑物电子信息系统防雷工程。",
            "key_clauses": "4.1.1 电子信息系统的雷电防护等级分为A、B、C、D四级；5.2.1 电源线路应采用三级SPD防护。",
            "application": "机房和电子设备防雷系统验收。",
        },
        "importance": 7, "status": "published",
    },
    # ── 安防补充 ──
    {
        "title": "公共安全视频监控联网系统信息传输、交换、控制技术要求",
        "standard_no": "GB/T 28181-2016",
        "category": "standard", "subcategory": "安防",
        "summary": "公共安全视频监控系统的联网信息传输、交换与控制协议标准。",
        "content": {
            "scope": "适用于公共安全视频监控系统的联网建设和管理。",
            "key_clauses": "6.1 信令传输应采用SIP协议；7.1 媒体流传输应采用RTP/RTCP协议；8.1 系统应支持注册、心跳、设备目录查询等基本功能。",
            "application": "视频监控系统联网方案评审。",
        },
        "importance": 8, "status": "published",
    },
    # ── 消防补充 ──
    {
        "title": "自动喷水灭火系统设计规范",
        "standard_no": "GB 50084-2017",
        "category": "standard", "subcategory": "消防",
        "summary": "自动喷水灭火系统的设计参数和系统配置要求。",
        "content": {
            "scope": "适用于新建、扩建和改建的民用与工业建筑自动喷水灭火系统设计。",
            "key_clauses": "5.0.1 火灾危险等级分为轻危险级、中危险级、严重危险级和仓库危险级；6.1.1 系统类型包括湿式、干式、预作用等。",
            "application": "建筑消防系统验收。",
        },
        "importance": 7, "status": "published",
    },
    {
        "title": "建筑灭火器配置设计规范",
        "standard_no": "GB 50140-2005",
        "category": "standard", "subcategory": "消防",
        "summary": "建筑灭火器配置的类型、规格、数量与设置位置的设计要求。",
        "content": {
            "scope": "适用于新建、扩建和改建的工业和民用建筑灭火器配置设计。",
            "key_clauses": "4.1.1 灭火器设置位置应明显、便于取用；5.1.1 灭火器配置应按A、B、C、D、E类火灾分别选型。",
            "application": "机房和办公区域消防验收。",
        },
        "importance": 6, "status": "published",
    },
    # ── 声学补充 ──
    {
        "title": "厅堂扩声系统设计规范",
        "standard_no": "GB 50371-2006",
        "category": "standard", "subcategory": "声学",
        "summary": "厅堂扩声系统的声学特性指标与设计规范。",
        "content": {
            "scope": "适用于各类厅堂扩声系统设计。",
            "key_clauses": "3.1.1 扩声系统声学特性指标分为一级、二级；3.2.1 一级指标要求最大声压级≥103dB，传输频率特性63Hz-8kHz。",
            "application": "会议厅、报告厅扩声系统验收测试。",
        },
        "importance": 7, "status": "published",
    },
    {
        "title": "剧场、电影院和多用途厅堂建筑声学设计规范",
        "standard_no": "GB/T 50356-2005",
        "category": "standard", "subcategory": "声学",
        "summary": "剧场、电影院和多用途厅堂的建筑声学设计标准。",
        "content": {
            "scope": "适用于新建和改建的剧场、电影院和多用途厅堂建筑声学设计。",
            "key_clauses": "4.1.1 剧场观众厅中频混响时间宜为1.2-1.5s；6.1.1 电影院观众厅中频混响时间宜为0.5-0.8s。",
            "application": "影剧院声学验收。",
        },
        "importance": 6, "status": "published",
    },
    # ── 信息化测评 ──
    {
        "title": "系统与软件工程 系统与软件质量要求和评价(SQuaRE) 第51部分",
        "standard_no": "GB/T 25000.51-2016",
        "category": "standard", "subcategory": "信息化",
        "summary": "就绪可用软件产品(RUSP)的质量要求和测试细则，是软件验收测评的核心标准。",
        "content": {
            "scope": "适用于就绪可用软件产品的质量要求和测试。",
            "key_clauses": "5.2 产品说明应完整准确；5.3 用户文档集应包含安装、使用和维护说明；6.2 功能性测试应包括适合性、准确性、互操作性等子特性。",
            "application": "信息化项目软件验收测评。",
        },
        "importance": 10, "status": "published",
    },
    {
        "title": "信息化工程监理规范",
        "standard_no": "GB/T 19668-2014",
        "category": "standard", "subcategory": "信息化",
        "summary": "信息化工程监理的通用要求和实施规范，覆盖监理阶段划分、监理内容和方法。",
        "content": {
            "scope": "适用于信息化工程项目的监理工作。",
            "key_clauses": "第4章 监理阶段划分为招标、设计、实施、验收四个阶段；第5章 监理内容包括质量控制、进度控制、投资控制、变更控制、信息管理和协调。",
            "application": "政务信息化项目监理方案编制。",
        },
        "importance": 9, "status": "published",
    },
    # ── 等保/信息安全 ——
    {
        "title": "信息安全技术 信息系统安全等级保护定级指南",
        "standard_no": "GB/T 22240-2020",
        "category": "standard", "subcategory": "信息安全",
        "summary": "信息系统安全保护等级定级方法和定级要素，是等保定级的依据标准。",
        "content": {
            "scope": "适用于信息系统安全保护等级定级工作。",
            "key_clauses": "4.1 定级要素包括受侵害的客体和对客体的侵害程度；5.1 安全保护等级分为第一级至第五级。",
            "application": "信息系统等保定级。",
        },
        "importance": 9, "status": "published",
    },
    {
        "title": "信息安全技术 信息安全风险评估方法",
        "standard_no": "GB/T 20984-2022",
        "category": "standard", "subcategory": "信息安全",
        "summary": "信息安全风险评估的模型、要素、流程和方法。",
        "content": {
            "scope": "适用于各类组织开展信息安全风险评估。",
            "key_clauses": "5.1 风险评估要素包括资产、威胁、脆弱性、安全措施和风险；5.2 风险计算采用R=f(A,V,T)模型。",
            "application": "信息系统安全风险评估。",
        },
        "importance": 8, "status": "published",
    },
    {
        "title": "信息安全技术 信息系统密码应用基本要求",
        "standard_no": "GB/T 39786-2021",
        "category": "standard", "subcategory": "信息安全",
        "summary": "信息系统密码应用的基本要求，是密评的核心依据标准。",
        "content": {
            "scope": "适用于指导信息系统密码应用方案设计和测评。",
            "key_clauses": "5.1 密码应用应遵循合规性、正确性、有效性原则；6.1 第一级至第五级分别对应不同的密码应用技术要求。",
            "application": "商用密码应用安全性评估（密评）。",
        },
        "importance": 9, "status": "published",
    },
    {
        "title": "信息安全技术 网络安全事件应急演练指南",
        "standard_no": "GB/T 38645-2020",
        "category": "standard", "subcategory": "信息安全",
        "summary": "网络安全事件应急演练的策划、实施、评估和改进的指南。",
        "content": {
            "scope": "适用于各类组织网络安全事件应急演练。",
            "key_clauses": "4.1 应急演练类型包括桌面推演、实战演练和混合演练；6.1 演练评估应包括预案有效性、响应速度和处置效果。",
            "application": "网络安全应急演练方案。",
        },
        "importance": 6, "status": "published",
    },
    # ── 供配电补充 ──
    {
        "title": "通用用电设备配电设计规范",
        "standard_no": "GB 50055-2011",
        "category": "standard", "subcategory": "供配电",
        "summary": "通用用电设备的配电设计规范，涵盖电动机、电梯、电热设备等。",
        "content": {
            "scope": "适用于工业与民用建筑通用用电设备配电设计。",
            "key_clauses": "2.1.1 电动机的起动方式应根据电源容量和负载特性确定；3.1.1 电梯供电应采用双电源切换。",
            "application": "建筑电气系统设计评审。",
        },
        "importance": 7, "status": "published",
    },
    {
        "title": "20kV及以下变电所设计规范",
        "standard_no": "GB 50053-2013",
        "category": "standard", "subcategory": "供配电",
        "summary": "20kV及以下变电所设计的各项技术要求。",
        "content": {
            "scope": "适用于20kV及以下变电所设计。",
            "key_clauses": "3.1.1 变电所位置应靠近负荷中心；4.1.1 变压器容量应根据计算负荷确定。",
            "application": "建筑配电系统设计评审。",
        },
        "importance": 7, "status": "published",
    },
    # ── 数据中心补充 ──
    {
        "title": "信息技术 数据中心运行维护规范",
        "standard_no": "GB/T 36344-2018",
        "category": "standard", "subcategory": "数据中心",
        "summary": "数据中心运行维护的管理框架和技术要求。",
        "content": {
            "scope": "适用于数据中心运维管理。",
            "key_clauses": "5.1 运维内容应包括基础设施运维、系统运维、安全管理；6.1 运维级别分为基础级、标准级和增强级。",
            "application": "数据中心运维方案编制。",
        },
        "importance": 7, "status": "published",
    },
    # ── 防雷/接地 ──
    {
        "title": "建筑物防雷设计规范",
        "standard_no": "GB 50057-2010",
        "category": "standard", "subcategory": "防雷",
        "summary": "建筑物防雷分类、防雷措施和设计要求。",
        "content": {
            "scope": "适用于新建、扩建和改建建筑物防雷设计。",
            "key_clauses": "3.0.1 建筑物防雷分类按重要性、使用性质和雷击后果分为一、二、三类；5.2.1 接闪器布置应符合表5.2.1的规定。",
            "application": "建筑和机房防雷系统验收。",
        },
        "importance": 8, "status": "published",
    },
    # ── 绿色建筑 ──
    {
        "title": "绿色建筑评价标准",
        "standard_no": "GB/T 50378-2019",
        "category": "standard", "subcategory": "绿色建筑",
        "summary": "绿色建筑评价的指标体系和技术要求。",
        "content": {
            "scope": "适用于民用建筑绿色性能评价。",
            "key_clauses": "3.1.1 评价指标体系包括安全耐久、健康舒适、生活便利、资源节约、环境宜居五大性能；3.2.1 绿色建筑等级分为基本级、一星级、二星级、三星级。",
            "application": "绿色建筑评价和认证。",
        },
        "importance": 7, "status": "published",
    },
]

# CREATE
created = 0
failed = 0
for i, entry in enumerate(ENTRIES):
    try:
        req = urllib.request.Request(
            f"{API}/entry",
            data=json.dumps(entry).encode(),
            headers=headers,
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        created += 1
        print(f"  ✓ [{result.get('id')}] {entry['title']}")
    except urllib.error.HTTPError as e:
        msg = e.read().decode()
        failed += 1
        print(f"  ✗ [{e.code}] {entry['title']}: {msg[:80]}")
    except Exception as e:
        failed += 1
        print(f"  ✗ {entry['title']}: {e}")
    time.sleep(0.3)  # rate limit

print(f"\nDone: {created} created, {failed} failed")
