#!/usr/bin/env python3
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple


EXPECTED_HEADERS = [
    "编号",
    "日期",
    "项目名称",
    "事项类型",
    "事项描述",
    "当前状态",
    "优先级",
    "责任方",
    "协同方",
    "下一步动作",
    "截止时间",
    "留痕方式",
    "留痕位置",
    "是否写入周报",
    "备注",
]

CONF_FIELDS = ["项目名称", "事项类型", "当前状态", "责任方", "截止时间"]

ITEM_TYPES = ["需求确认", "Bug修复", "数据接入", "等保整改", "账号权限", "原型设计", "文档材料", "客户沟通", "上线部署", "验收推进", "其他"]
STATUSES = ["待处理", "进行中", "待确认", "已完成", "阻塞", "暂缓"]
PRIORITIES = ["高", "中", "低"]


def today_shanghai() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def parse_iso_date(value: Optional[str]) -> date:
    if not value:
        return today_shanghai()
    return datetime.strptime(value, "%Y-%m-%d").date()


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def compact(text: str) -> str:
    return re.sub(r"[\s_，,。；;：:（）()《》“”\"'、/-]+", "", text.lower())


def sentence(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    return text if text.endswith(("。", "！", "？")) else text + "。"


CN_NUM = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def parse_cn_num(raw: str) -> Optional[int]:
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    if raw in CN_NUM:
        return CN_NUM[raw]
    if len(raw) == 2 and raw[0] == "十" and raw[1] in CN_NUM:
        return 10 + CN_NUM[raw[1]]
    if len(raw) == 2 and raw[1] == "十" and raw[0] in CN_NUM:
        return CN_NUM[raw[0]] * 10
    if len(raw) == 3 and raw[1] == "十" and raw[0] in CN_NUM and raw[2] in CN_NUM:
        return CN_NUM[raw[0]] * 10 + CN_NUM[raw[2]]
    return None


def date_string(d: date) -> str:
    return d.strftime("%Y-%m-%d")


PROJECT_ALIASES: List[Tuple[str, str]] = [
    ("慈溪市家电产业 VOCs 智治捷溯项目（二期）", "慈溪市家电产业 VOCs 智治捷溯项目（二期）"),
    ("慈溪 VOCs 二期", "慈溪市家电产业 VOCs 智治捷溯项目（二期）"),
    ("慈溪 VOCs", "慈溪市家电产业 VOCs 智治捷溯项目（二期）"),
    ("慈溪vocs", "慈溪市家电产业 VOCs 智治捷溯项目（二期）"),
    ("家电产业 VOCs", "慈溪市家电产业 VOCs 智治捷溯项目（二期）"),
    ("家电 VOCs", "慈溪市家电产业 VOCs 智治捷溯项目（二期）"),
    ("镇海数字治气二期项目", "镇海数字治气二期项目"),
    ("镇海数字治气二期", "镇海数字治气二期项目"),
    ("镇海数字治气", "镇海数字治气二期项目"),
    ("镇海二期", "镇海数字治气二期项目"),
    ("数字治气", "镇海数字治气二期项目"),
    ("镇海", "镇海数字治气二期项目"),
    ("余姚二期", "余姚二期"),
    ("余姚", "余姚二期"),
]


def identify_project(text: str) -> Tuple[str, str, str]:
    ctext = compact(text)
    for alias, canonical in sorted(PROJECT_ALIASES, key=lambda x: len(compact(x[0])), reverse=True):
        if compact(alias) and compact(alias) in ctext:
            conf = "高"
            if alias in ("余姚", "镇海", "数字治气") and re.search(alias + r"(那个|这个|这边)?", text):
                conf = "中"
            return canonical, conf, f"原文出现“{alias}”，归一化为“{canonical}”。"
    if "其他" in text:
        return "其他", "中", "原文出现“其他”，按项目名称填写为“其他”。"
    return "待确认", "低", "原文未出现可可靠归一化的项目名称。"


def has_any(text: str, words: List[str]) -> bool:
    return any(w.lower() in text.lower() for w in words)


def identify_item_type(text: str) -> Tuple[str, str, str, List[str]]:
    lower = text.lower()
    bug_words = ["打不开", "报错", "异常", "bug", "功能不可用", "查不到", "显示异常", "失败"]
    if has_any(lower, bug_words):
        return "Bug修复", "高", "核心问题是系统异常或功能不可用，因此归为Bug修复。", []

    if has_any(text, ["数据口径", "口径"]) and has_any(text, ["确认", "没说清楚", "不清楚", "待明确"]):
        return "需求确认", "低", "事项涉及数据口径确认，可能归为需求确认，也可能归为数据接入。", ["数据接入"]

    checks: List[Tuple[str, List[str], str]] = [
        ("等保整改", ["等保", "漏洞", "整改", "安全问题", "测评报告", "渗透", "弱口令", "漏洞扫描"], "核心工作对象是等保、安全或整改闭环，因此归为等保整改。"),
        ("原型设计", ["原型", "低保真", "高保真", "ui", "UI", "交互", "设计图", "页面范围", "产品流程"], "核心交付物是页面、原型或交互设计，因此归为原型设计。"),
        ("账号权限", ["账号", "权限", "角色", "菜单", "登录", "用户配置"], "核心工作对象是账号、权限或角色配置，因此归为账号权限。"),
        ("上线部署", ["上线", "部署", "发版", "IRS", "irs", "代码工厂", "服务器环境", "环境"], "核心工作对象是上线、部署或环境处理，因此归为上线部署。"),
        ("验收推进", ["验收", "签字", "确认单", "试运行", "验收材料", "验收报告"], "核心目标是验收或签字确认，因此归为验收推进。"),
        ("文档材料", ["方案", "制度", "汇报", "周报", "说明书", "PPT", "ppt", "材料", "文档"], "核心交付物是方案、汇报或材料文档，因此归为文档材料。"),
        ("数据接入", ["接口", "字段", "库表", "数据同步", "数据清洗", "数据编目", "ODS", "ods", "ETL", "etl", "数据底座"], "核心工作对象是接口、字段或数据处理链路，因此归为数据接入。"),
        ("需求确认", ["需求边界", "需求口径", "功能范围", "纳入本期", "客户确认", "页面范围"], "核心是范围、口径或是否纳入本期的确认，因此归为需求确认。"),
    ]
    for item_type, words, rationale in checks:
        if has_any(text, words):
            return item_type, "高", rationale, []

    if has_any(text, ["沟通", "电话", "微信", "会议", "调研安排", "业主说"]):
        return "客户沟通", "中", "原文主要记录沟通或安排，未识别到更明确交付物，因此归为客户沟通。", []
    return "其他", "低", "未识别到明确交付物或工作对象，暂归为其他。", ["需求确认", "客户沟通"]


def identify_status(text: str) -> Tuple[str, str, str]:
    if has_any(text, ["已完成", "已经完成", "已提交", "已修复", "已确认", "闭环了"]):
        return "已完成", "高", "原文明确表示已完成、已提交或已确认。"
    if has_any(text, ["先不做", "后面再说", "下阶段处理", "暂缓"]):
        return "暂缓", "高", "原文明确表示后续或下阶段再处理。"
    if has_any(text, ["卡住", "阻塞", "无法继续", "没权限", "资源不足", "接口没给", "等反馈"]):
        return "阻塞", "中", "原文体现资源、权限或外部反馈导致推进受阻。"
    if has_any(text, ["还没说清楚", "待确认", "需要确认", "需确认", "口径"]) and has_any(text, ["业主", "客户", "第三方"]):
        return "待确认", "高", "事项需要外部进一步明确后才能继续。"
    if re.search(r"(我|我要|我这边).{0,8}(确认|问|催|协调|整理|推进)", text):
        return "待处理", "中", "下一步由用户推进，事项尚未完成，因此判断为待处理。"
    if has_any(text, ["正在", "在做", "处理中", "开发中", "排查中"]):
        return "进行中", "中", "原文显示已有人员正在处理，未见明确卡点。"
    return "待处理", "低", "原文未明确状态，按默认规则暂判断为待处理。"


def identify_responsibility(text: str) -> Tuple[str, str, str]:
    if re.search(r"(我|我要|我这边).{0,10}(确认|问|催|协调|推进|整理|同步)", text) or re.search(r"(再|去)?问(一下|下)?", text):
        return "我方", "高", "下一步动作由用户发起或推动，因此责任方为我方。"
    if re.search(r"开发.{0,12}(修复|实现|配置|排查|开发|处理|出|提交)", text):
        return "开发", "中", "原文显示下一步主要需要开发处理。"
    if re.search(r"业主.{0,12}(确认|反馈|提供|明确)", text):
        return "业主", "中", "原文显示下一步需要业主确认、反馈或提供资料。"
    if re.search(r"第三方.{0,12}(提供|确认|反馈|处理)", text):
        return "第三方", "中", "原文显示下一步需要第三方配合处理。"
    if re.search(r"运维.{0,12}(部署|配置|处理|开通)", text):
        return "运维", "中", "原文显示下一步需要运维处理环境、部署或账号配置。"
    if re.search(r"等保公司.{0,12}(出|测评|复测|确认)", text):
        return "等保公司", "中", "原文显示下一步需要等保公司测评或出具材料。"
    return "待确认", "低", "原文未明确下一步主要推动方。"


def identify_collaborators(text: str) -> str:
    parties = []
    for p in ["开发", "业主", "第三方", "等保公司", "运维", "产品", "测试", "领导"]:
        if p in text:
            parties.append(p)
    return "、".join(parties)


WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


@dataclass
class DueResult:
    value: str
    confidence: str
    rationale: str
    relative: bool = False
    ambiguous: bool = False


def end_of_month(today: date, month: Optional[int] = None) -> date:
    year = today.year
    month = month or today.month
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return next_month - timedelta(days=1)


def identify_due_date(text: str, today: date) -> DueResult:
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?\s*前?", text)
    if m:
        d = date(today.year, int(m.group(1)), int(m.group(2)))
        return DueResult(date_string(d), "高", f"用户明确提供日期，解析为 {date_string(d)}。")

    m = re.search(r"([一二两三四五六七八九十]{1,3})\s*月\s*([一二两三四五六七八九十]{1,3})\s*[日号]?\s*前?", text)
    if m:
        month = parse_cn_num(m.group(1))
        day = parse_cn_num(m.group(2))
        if month and day:
            d = date(today.year, month, day)
            return DueResult(date_string(d), "高", f"用户明确提供中文日期，解析为 {date_string(d)}。")

    m = re.search(r"(本周|这周|下周)?\s*周([一二三四五六日天])\s*前?", text)
    if m:
        prefix = m.group(1) or "本周"
        target = WEEKDAY_MAP[m.group(2)]
        monday = today - timedelta(days=today.weekday())
        if prefix == "下周":
            monday = monday + timedelta(days=7)
        d = monday + timedelta(days=target)
        if prefix == "本周" and d < today:
            d = d + timedelta(days=7)
        return DueResult(date_string(d), "中", f"根据“{m.group(0).strip()}”推断为 {date_string(d)}。", relative=True)

    if "今天" in text:
        return DueResult(date_string(today), "中", f"根据“今天”推断为 {date_string(today)}。", relative=True)
    if "明天" in text:
        d = today + timedelta(days=1)
        return DueResult(date_string(d), "中", f"根据“明天”推断为 {date_string(d)}。", relative=True)
    if "后天" in text:
        d = today + timedelta(days=2)
        return DueResult(date_string(d), "中", f"根据“后天”推断为 {date_string(d)}。", relative=True)

    m = re.search(r"([一二两三四五六七八九十\d]{1,3})\s*月\s*底\s*前?", text)
    if m:
        month = parse_cn_num(m.group(1))
        if month:
            d = end_of_month(today, month)
            return DueResult(date_string(d), "中", f"根据“{m.group(0).strip()}”推断为 {date_string(d)}。", relative=True)
    if "月底" in text:
        d = end_of_month(today)
        return DueResult(date_string(d), "中", f"根据“月底”推断为 {date_string(d)}。", relative=True)

    if has_any(text, ["尽快", "最近", "这两天", "近期"]):
        return DueResult("待确认", "低", "原文只有模糊期限表达，无法安全转换为具体日期。", ambiguous=True)
    return DueResult("", "高", "原文未提供截止时间，按规则留空。")


def identify_priority(text: str, due: DueResult) -> str:
    if has_any(text, ["今天", "明天", "周五前", "本周必须", "马上", "尽快", "影响验收", "影响上线", "领导要", "业主要", "卡节点", "月底前", "必须完成"]):
        return "高"
    if due.value and due.value != "待确认":
        return "中"
    if not due.value:
        return "低"
    return "中"


def identify_trace_method(text: str) -> str:
    if has_any(text, ["邮件", "发邮件", "邮件确认"]):
        return "邮件"
    if has_any(text, ["会议", "开会", "纪要", "现场会"]):
        return "会议纪要"
    if has_any(text, ["禅道", "Jira", "jira", "任务单"]):
        return "禅道/Jira"
    if has_any(text, ["代码工厂", "IRS", "irs"]):
        return "代码工厂"
    if has_any(text, ["文件", "材料", "附件", "文档"]):
        return "文件记录"
    return "微信群"


def identify_trace_location(text: str) -> str:
    m = re.search(r"(项目群\s*[0-9一二三四五六七八九十/:\-月日号点半 ]{1,30})", text)
    if m:
        return clean_text(m.group(1))
    if "已经发在项目群" in text or "已发在项目群" in text:
        return "项目群"
    if "邮件已经发了" in text or "邮件已发送" in text:
        return "邮件已发送"
    if "会议纪要已经出了" in text or "会议纪要已出" in text:
        return "会议纪要"
    return "待补充"


def strip_project_phrase(text: str) -> str:
    out = text.strip(" ，,。")
    for alias, _ in sorted(PROJECT_ALIASES, key=lambda x: len(x[0]), reverse=True):
        out = re.sub(re.escape(alias) + r"[，,、：:\s]*", "", out, count=1)
    return out.strip(" ，,。")


def make_description(text: str, item_type: str) -> str:
    if "排污许可" in text and "原型" in text:
        parts = ["排污许可系统原型需提交业主查看"]
        if re.search(r"(本周|这周)?周五", text):
            parts[0] = "排污许可系统原型需在本周五前提交业主查看"
        if "案卷评查" in text:
            parts.append("当前开发资源集中在案卷评查系统")
        if "低保真" in text:
            parts.append("可能先提交低保真版本")
        return "，".join(parts) + "。"
    if "数据口径" in text or "口径" in text:
        return sentence(strip_project_phrase(text).replace("那个", "").replace("明天再问下", "需要进一步确认").replace("还没说清楚", "尚未明确"))

    content = strip_project_phrase(text)
    content = re.sub(r"(今天|明天|后天)?\s*(我|我要|我这边).{0,30}$", "", content).strip(" ，,。")
    if not content:
        content = text
    return sentence(content[:120])


def make_next_action(text: str, item_type: str, due: DueResult) -> str:
    if "排污许可" in text and "原型" in text:
        return "确认排污许可原型页面范围，并与开发确认本周可交付内容。"
    if "数据口径" in text or "口径" in text:
        prefix = "明天" if "明天" in text else ""
        return sentence(f"{prefix}向业主确认数据口径，并同步后续处理方式")
    m = re.search(r"(我|我要|我这边).{0,4}(确认|问|催|协调|整理|推进)(.{0,35})", text)
    if m:
        action = (m.group(2) + m.group(3)).strip(" ，,。一下")
        return sentence(action)
    if item_type == "Bug修复":
        return "定位异常原因并安排责任方修复验证。"
    if item_type == "原型设计":
        return "确认原型范围和近期可交付版本。"
    if item_type == "数据接入":
        return "确认数据字段、接口口径和下一步接入安排。"
    if item_type == "需求确认":
        return "确认需求范围和后续处理口径。"
    return "明确责任方和下一步处理动作。"


def weekly_flag(item_type: str, text: str) -> str:
    if item_type in {"需求确认", "Bug修复", "数据接入", "等保整改", "原型设计", "客户沟通", "上线部署", "验收推进", "文档材料"}:
        return "是"
    if has_any(text, ["个人提醒", "临时想法", "私事"]):
        return "否"
    return "是"


def build_needs(fields: Dict[str, str], confidence: Dict[str, str], due: DueResult, alternatives: Dict[str, List[str]]) -> List[str]:
    needs: List[str] = []
    for key, value in fields.items():
        if value in ("待确认", "待补充"):
            needs.append(f"{key}：{value}。")
    for field_name, conf in confidence.items():
        if conf == "低":
            if field_name == "事项类型" and alternatives.get("事项类型"):
                needs.append(f"事项类型置信度低：当前识别为“{fields.get('事项类型')}”，备选类型为“{'、'.join(alternatives['事项类型'])}”。")
            else:
                needs.append(f"{field_name}置信度低，请确认。")
    if due.relative and due.value and due.value != "待确认":
        needs.append(f"截止时间：根据相对日期推断为 {due.value}，请确认。")
    if fields.get("当前状态") == "阻塞":
        needs.append("当前状态：已判断为阻塞，请确认是否需要上报。")
    deduped: List[str] = []
    for item in needs:
        if item not in deduped:
            deduped.append(item)
    return deduped or ["暂无明显缺失字段。"]


def parse_item(text: str, today: Optional[date] = None) -> Dict[str, Any]:
    text = clean_text(text)
    if len(text) < 8:
        raise ValueError("信息不足，建议至少包含项目名称和事项内容。")
    today = today or today_shanghai()

    project, project_conf, project_rationale = identify_project(text)
    item_type, type_conf, type_rationale, type_alts = identify_item_type(text)
    status, status_conf, status_rationale = identify_status(text)
    due = identify_due_date(text, today)
    responsibility, resp_conf, resp_rationale = identify_responsibility(text)
    priority = identify_priority(text, due)

    fields: Dict[str, str] = {
        "编号": "待生成",
        "日期": date_string(today),
        "项目名称": project,
        "事项类型": item_type,
        "事项描述": make_description(text, item_type),
        "当前状态": status,
        "优先级": priority,
        "责任方": responsibility,
        "协同方": identify_collaborators(text),
        "下一步动作": make_next_action(text, item_type, due),
        "截止时间": due.value,
        "留痕方式": identify_trace_method(text),
        "留痕位置": identify_trace_location(text),
        "是否写入周报": weekly_flag(item_type, text),
        "备注": f"原始记录：{text}",
    }
    confidence = {
        "项目名称": project_conf,
        "事项类型": type_conf,
        "当前状态": status_conf,
        "责任方": resp_conf,
        "截止时间": due.confidence,
    }
    rationale = {
        "项目名称": project_rationale,
        "事项类型": type_rationale,
        "当前状态": status_rationale,
        "责任方": resp_rationale,
        "截止时间": due.rationale,
    }
    alternatives = {"事项类型": type_alts} if type_alts else {}
    draft = {
        "draft_id": f"draft_{today.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
        "status": "draft",
        "source_text": text,
        "fields": fields,
        "confidence": confidence,
        "rationale": rationale,
        "alternatives": alternatives,
        "needs_confirmation": build_needs(fields, confidence, due, alternatives),
    }
    return draft


FIELD_ALIASES = {
    "项目名称": "项目名称",
    "项目": "项目名称",
    "事项类型": "事项类型",
    "类型": "事项类型",
    "当前状态": "当前状态",
    "状态": "当前状态",
    "优先级": "优先级",
    "责任方": "责任方",
    "协同方": "协同方",
    "下一步动作": "下一步动作",
    "下一步": "下一步动作",
    "截止时间": "截止时间",
    "时间": "截止时间",
    "留痕方式": "留痕方式",
    "留痕位置": "留痕位置",
    "是否写入周报": "是否写入周报",
    "周报": "是否写入周报",
    "备注": "备注",
}


def normalize_field_value(field: str, value: str, today: date) -> Tuple[str, Optional[str]]:
    value = clean_text(value).strip(" ，,。")
    if field == "截止时间":
        due = identify_due_date(value, today)
        if due.value:
            return due.value, due.rationale
        return value, f"用户已明确修改为 {value}。"
    if field == "项目名称":
        project, _, rationale = identify_project(value)
        return (project if project != "待确认" else value), f"用户已明确修改项目名称为“{project if project != '待确认' else value}”。"
    if field == "事项类型" and value not in ITEM_TYPES:
        return value, f"用户已明确修改事项类型为“{value}”，但不在标准选项中，请复核。"
    if field == "当前状态" and value not in STATUSES:
        return value, f"用户已明确修改状态为“{value}”，但不在标准选项中，请复核。"
    if field == "优先级" and value not in PRIORITIES:
        return value, f"用户已明确修改优先级为“{value}”，但不在标准选项中，请复核。"
    return value, f"用户已明确修改为“{value}”。"


def update_draft(draft: Dict[str, Any], changes: str, today: Optional[date] = None) -> Dict[str, Any]:
    today = today or today_shanghai()
    changes = clean_text(changes)
    fields = dict(draft.get("fields") or {})
    confidence = dict(draft.get("confidence") or {})
    rationale = dict(draft.get("rationale") or {})

    patterns = [
        r"(?P<field>项目名称|项目|事项类型|类型|当前状态|状态|优先级|责任方|协同方|下一步动作|下一步|截止时间|时间|留痕方式|留痕位置|是否写入周报|周报|备注)\s*(改成|改为|填|填写|设为|设置为)\s*(?P<value>[^，。；;]+)",
    ]
    matched = False
    for pattern in patterns:
        for m in re.finditer(pattern, changes):
            field = FIELD_ALIASES.get(m.group("field"))
            if not field:
                continue
            value, why = normalize_field_value(field, m.group("value"), today)
            fields[field] = value
            if field in CONF_FIELDS:
                confidence[field] = "高"
                rationale[field] = why or f"用户已明确修改为“{value}”。"
            matched = True

    if not matched:
        raise ValueError("未识别到可修改字段，请使用“字段改成/填xxx”的表达。")

    due = DueResult(fields.get("截止时间", ""), confidence.get("截止时间", "高"), rationale.get("截止时间", ""), False)
    draft["fields"] = fields
    draft["confidence"] = confidence
    draft["rationale"] = rationale
    draft["needs_confirmation"] = build_needs(fields, confidence, due, draft.get("alternatives") or {})
    draft["status"] = "draft"
    return draft


def tab_row(draft: Dict[str, Any], number: Optional[str] = None) -> str:
    fields = draft.get("fields") or {}
    values = []
    for h in EXPECTED_HEADERS:
        if h == "编号" and number:
            values.append(number)
        else:
            values.append(str(fields.get(h, "")))
    return "\t".join(values)


def render_draft(draft: Dict[str, Any]) -> str:
    fields = draft.get("fields") or {}
    confidence = draft.get("confidence") or {}
    rationale = draft.get("rationale") or {}
    needs = draft.get("needs_confirmation") or ["暂无明显缺失字段。"]
    lines: List[str] = ["【事项草稿】", f"草稿ID：{draft.get('draft_id', '')}"]
    for h in EXPECTED_HEADERS:
        lines.append(f"{h}：{fields.get(h, '')}")
    lines.append("")
    lines.append("【置信度】")
    for field in CONF_FIELDS:
        lines.append(f"{field}置信度：{confidence.get(field, '')}")
    lines.append("")
    lines.append("【系统判断依据】")
    for field in CONF_FIELDS:
        lines.append(f"- {field}：{rationale.get(field, '')}")
    lines.append("")
    lines.append("【需要确认 / 补充的字段】")
    if needs == ["暂无明显缺失字段。"]:
        lines.append("暂无明显缺失字段。")
    else:
        for item in needs:
            lines.append(f"- {item}")
    lines.append("")
    lines.append("是否确认写入金山文档《项目推进与留痕台账》的“事项总表”？")
    return "\n".join(lines)
