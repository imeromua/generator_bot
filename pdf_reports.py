"""Генерація PDF-звітів про роботу генератора.

Типи звітів:
  • quick   — основні метрики (1 стор.)
  • detailed — з графіками (3-5 стор.)
  • personnel — статистика працівників
  • technical — ТО і діагностика
  • financial — витрати на паливо

Бібліотека: ReportLab
"""

import io
import logging
from datetime import datetime
from typing import List, Dict, Any

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Перевірка доступності ReportLab
# ---------------------------------------------------------------------------
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True
except ImportError:  # pragma: no cover
    REPORTLAB_AVAILABLE = False

# ---------------------------------------------------------------------------
# Кольорова схема
# ---------------------------------------------------------------------------
_COLOR_PRIMARY = colors.HexColor("#1976D2")   # синій
_COLOR_SUCCESS = colors.HexColor("#2E7D32")   # зелений
_COLOR_WARNING = colors.HexColor("#F57C00")   # помаранчевий
_COLOR_DANGER  = colors.HexColor("#C62828")   # червоний
_COLOR_GRAY    = colors.HexColor("#78909C")
_COLOR_LIGHT   = colors.HexColor("#F5F7FA")
_COLOR_BORDER  = colors.HexColor("#CFD8DC")

# ---------------------------------------------------------------------------
# Стилі
# ---------------------------------------------------------------------------

def _build_styles():
    """Створює стилі для звіту."""
    base = getSampleStyleSheet()

    styles = {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontSize=18,
            leading=22,
            textColor=_COLOR_PRIMARY,
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            textColor=_COLOR_GRAY,
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "ReportH2",
            parent=base["Heading2"],
            fontSize=13,
            leading=16,
            textColor=_COLOR_PRIMARY,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "normal": ParagraphStyle(
            "ReportNormal",
            parent=base["Normal"],
            fontSize=10,
            leading=13,
        ),
        "bold": ParagraphStyle(
            "ReportBold",
            parent=base["Normal"],
            fontSize=10,
            leading=13,
            fontName="Helvetica-Bold",
        ),
        "small": ParagraphStyle(
            "ReportSmall",
            parent=base["Normal"],
            fontSize=8,
            leading=11,
            textColor=_COLOR_GRAY,
        ),
        "center": ParagraphStyle(
            "ReportCenter",
            parent=base["Normal"],
            fontSize=10,
            leading=13,
            alignment=TA_CENTER,
        ),
    }
    return styles


# ---------------------------------------------------------------------------
# Допоміжні компоненти
# ---------------------------------------------------------------------------

def _divider() -> "HRFlowable":
    """Горизонтальна розділяюча лінія."""
    return HRFlowable(width="100%", thickness=1, color=_COLOR_BORDER, spaceAfter=8, spaceBefore=8)


def _kpi_table(kpis: List[Dict], styles: dict) -> "Table":
    """Таблиця KPI-карток (2 колонки)."""
    data = []
    row = []
    for i, kpi in enumerate(kpis):
        icon = kpi.get("icon", "📊")
        label = kpi.get("label", "")
        value = kpi.get("value", "—")
        trend = kpi.get("trend", "")

        cell_content = [
            Paragraph(f"<b>{icon} {label}</b>", styles["small"]),
            Paragraph(f"<b>{value}</b>", ParagraphStyle(
                "KPIValue", parent=styles["normal"],
                fontSize=13, textColor=_COLOR_PRIMARY,
            )),
        ]
        if trend:
            cell_content.append(Paragraph(trend, styles["small"]))

        row.append(cell_content)
        if len(row) == 2:
            data.append(row)
            row = []

    if row:
        row.append("")
        data.append(row)

    if not data:
        return Spacer(1, 0)

    col_width = (A4[0] - 40 * mm) / 2
    t = Table(data, colWidths=[col_width, col_width])
    t.setStyle(TableStyle([
        ("BOX",        (0, 0), (-1, -1), 0.5, _COLOR_BORDER),
        ("INNERGRID",  (0, 0), (-1, -1), 0.5, _COLOR_BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), _COLOR_LIGHT),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("PADDING",    (0, 0), (-1, -1), 8),
    ]))
    return t


def _data_table(headers: List[str], rows: List[List], styles: dict) -> "Table":
    """Загальна таблиця даних."""
    header_row = [Paragraph(f"<b>{h}</b>", styles["small"]) for h in headers]
    all_rows = [header_row] + [
        [Paragraph(str(c), styles["small"]) for c in r] for r in rows
    ]

    col_count = len(headers)
    avail = A4[0] - 40 * mm
    col_w = avail / col_count

    t = Table(all_rows, colWidths=[col_w] * col_count)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _COLOR_PRIMARY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _COLOR_LIGHT]),
        ("BOX",        (0, 0), (-1, -1), 0.5, _COLOR_BORDER),
        ("INNERGRID",  (0, 0), (-1, -1), 0.5, _COLOR_BORDER),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING",    (0, 0), (-1, -1), 6),
    ]))
    return t


# ---------------------------------------------------------------------------
# Основна функція генерації
# ---------------------------------------------------------------------------

def generate_pdf_report(
    report_type: str,
    period_start: str,
    period_end: str,
    data: Dict[str, Any],
) -> bytes:
    """Генерує PDF-звіт і повертає байти.

    Args:
        report_type: "quick" | "detailed" | "personnel" | "technical" | "financial"
        period_start: "DD.MM.YYYY"
        period_end:   "DD.MM.YYYY"
        data:         dict з усіма даними звіту

    Returns:
        bytes PDF-документа
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab недоступний. Встановіть: pip install reportlab")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    styles = _build_styles()
    story = []

    # ------------------------------------------------------------------
    # Шапка
    # ------------------------------------------------------------------
    story.append(Paragraph("⚡ Звіт про роботу генератора", styles["title"]))
    story.append(Paragraph(
        f"Період: {period_start} — {period_end}",
        styles["subtitle"],
    ))
    story.append(_divider())

    # ------------------------------------------------------------------
    # Тип звіту
    # ------------------------------------------------------------------
    type_builders = {
        "quick":      _build_quick,
        "detailed":   _build_detailed,
        "personnel":  _build_personnel,
        "technical":  _build_technical,
        "financial":  _build_financial,
    }
    builder = type_builders.get(report_type, _build_quick)
    builder(story, data, styles)

    # ------------------------------------------------------------------
    # Підвал
    # ------------------------------------------------------------------
    story.append(Spacer(1, 20))
    story.append(_divider())
    generated_at = datetime.now(config.KYIV).strftime("%d.%m.%Y %H:%M")
    story.append(Paragraph(
        f"Сформовано: {generated_at}   |   Генератор-Бот",
        styles["small"],
    ))

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Будівельники розділів
# ---------------------------------------------------------------------------

def _build_quick(story: list, data: dict, styles: dict):
    """Швидкий звіт — основні метрики (1 стор.)."""
    story.append(Paragraph("📈 ЗАГАЛЬНІ ПОКАЗНИКИ", styles["h2"]))

    kpis = [
        {"icon": "📊", "label": "Мотогодини",   "value": f"{data.get('total_hours', 0):.1f} год"},
        {"icon": "⛽", "label": "Витрата",       "value": f"{data.get('total_fuel', 0):.1f} л"},
        {"icon": "📉", "label": "Середня л/год", "value": f"{data.get('avg_rate', 0):.2f} л/год"},
        {"icon": "💰", "label": "Вартість",      "value": f"{data.get('fuel_cost', 0):,.0f} грн"},
        {"icon": "🎯", "label": "Ефективність",  "value": f"{data.get('efficiency', 0):.0f}%"},
        {"icon": "🔧", "label": "Кількість ТО",  "value": str(data.get("maintenance_count", 0))},
    ]
    story.append(_kpi_table(kpis, styles))

    if data.get("recommendations"):
        story.append(Spacer(1, 12))
        story.append(Paragraph("💡 РЕКОМЕНДАЦІЇ", styles["h2"]))
        for i, rec in enumerate(data["recommendations"], 1):
            story.append(Paragraph(f"{i}. {rec}", styles["normal"]))


def _build_detailed(story: list, data: dict, styles: dict):
    """Детальний звіт з розбивкою по днях."""
    _build_quick(story, data, styles)

    # Щоденна статистика
    if data.get("daily_stats"):
        story.append(Spacer(1, 12))
        story.append(Paragraph("📅 ЩОДЕННА СТАТИСТИКА", styles["h2"]))
        headers = ["Дата", "Мотогод.", "Паливо (л)", "л/год", "Відключень (год)"]
        rows = []
        for d in data["daily_stats"]:
            rows.append([
                d.get("date", ""),
                f"{d.get('work_hours', 0):.1f}",
                f"{d.get('fuel_consumed', 0):.1f}",
                f"{d.get('fuel_rate', 0):.2f}",
                str(d.get("outage_hours", 0)),
            ])
        story.append(_data_table(headers, rows, styles))

    # Розбивка по генераторах
    if data.get("generator_stats"):
        story.append(Spacer(1, 12))
        story.append(Paragraph("🔋 ПО ГЕНЕРАТОРАХ", styles["h2"]))
        for gen in data["generator_stats"]:
            name = gen.get("name", "Генератор")
            hours = gen.get("total_hours", 0)
            fuel = gen.get("total_fuel", 0)
            story.append(Paragraph(
                f"• <b>{name}</b>: {hours:.1f} год, {fuel:.1f} л",
                styles["normal"],
            ))


def _build_personnel(story: list, data: dict, styles: dict):
    """Звіт по персоналу."""
    story.append(Paragraph("📅 СТАТИСТИКА ПЕРСОНАЛУ", styles["h2"]))

    if data.get("personnel_stats"):
        headers = ["ПІБ", "Змін", "Годин", "Витрата (л)", "л/год"]
        rows = []
        for p in data["personnel_stats"]:
            rows.append([
                p.get("name", ""),
                str(p.get("shifts", 0)),
                f"{p.get('hours', 0):.1f}",
                f"{p.get('fuel', 0):.1f}",
                f"{p.get('rate', 0):.2f}",
            ])
        story.append(_data_table(headers, rows, styles))
    else:
        story.append(Paragraph("Дані відсутні", styles["normal"]))


def _build_technical(story: list, data: dict, styles: dict):
    """Технічний звіт — ТО і діагностика."""
    story.append(Paragraph("🔧 ТЕХНІЧНЕ ОБСЛУГОВУВАННЯ", styles["h2"]))

    mnt = data.get("maintenance", {})
    story.append(Paragraph(
        f"• Мастило: {mnt.get('last_oil', 'н/д')}  (через {mnt.get('oil_remaining', '?')} год)",
        styles["normal"],
    ))
    story.append(Paragraph(
        f"• Свічки: {mnt.get('last_spark', 'н/д')}  (через {mnt.get('spark_remaining', '?')} год)",
        styles["normal"],
    ))
    story.append(Paragraph(
        f"• Планове ТО: через {mnt.get('next_service_hours', '?')} год",
        styles["normal"],
    ))

    if data.get("anomalies"):
        story.append(Spacer(1, 12))
        story.append(Paragraph("⚠️ ВИЯВЛЕНІ АНОМАЛІЇ", styles["h2"]))
        for a in data["anomalies"]:
            story.append(Paragraph(f"• {a}", styles["normal"]))


def _build_financial(story: list, data: dict, styles: dict):
    """Фінансовий звіт — витрати на паливо."""
    story.append(Paragraph("💰 ФІНАНСОВИЙ АНАЛІЗ", styles["h2"]))

    fuel_price = data.get("fuel_price", 0)
    total_fuel = data.get("total_fuel", 0)
    total_cost = data.get("fuel_cost", 0)

    story.append(Paragraph(f"• Ціна палива: {fuel_price:.2f} грн/л", styles["normal"]))
    story.append(Paragraph(f"• Витрачено палива: {total_fuel:.1f} л", styles["normal"]))
    story.append(Paragraph(f"• Загальні витрати: {total_cost:,.0f} грн", styles["normal"]))

    if data.get("refill_history"):
        story.append(Spacer(1, 10))
        story.append(Paragraph("📥 ЗАПРАВКИ", styles["h2"]))
        headers = ["Дата", "Літри", "Водій", "Чек №"]
        rows = []
        for r in data["refill_history"]:
            rows.append([
                r.get("date", ""),
                f"{r.get('liters', 0):.1f}",
                r.get("driver", ""),
                r.get("receipt", ""),
            ])
        story.append(_data_table(headers, rows, styles))
