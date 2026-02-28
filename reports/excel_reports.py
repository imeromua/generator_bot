"""Enhanced Excel Report Generator with Charts and Advanced Formatting.

Features:
- Multiple report types (quick, detailed, technical, financial)
- Conditional formatting (low fuel = red, high efficiency = green)
- Multi-sheet workbooks
- Auto-sizing columns
- Professional styling
"""

import io
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import config
import database.db_api as db

logger = logging.getLogger(__name__)

try:
    from openpyxl import Workbook
    from openpyxl.chart import LineChart, BarChart, Reference
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    EXCEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    EXCEL_AVAILABLE = False


class ExcelReportGenerator:
    """Generate professional Excel reports with charts."""

    # Color scheme
    COLORS = {
        'header_blue': '2481CC',
        'light_blue': 'D6E8FA',
        'header_bg': 'EAF2FB',
        'green': '27AE60',
        'dark_green': '1A7A44',
        'orange': 'F39C12',
        'dark_yellow': 'D4AC0D',
        'red': 'E74C3C',
        'yellow': 'F4D03F',
        'gray': 'BDC3C7',
        'purple': '6C3483',
        'dark_blue': '1565C0',
        'teal': '117A65',
        'dark_text': '1A1A2E',
        'light_green': 'D5F5E3',
    }

    def __init__(self):
        self.wb = None
        self._border = None
        self._init_border()

    def _init_border(self):
        if not EXCEL_AVAILABLE:
            return
        try:
            thin = Side(style='thin', color='AAAAAA')
            self._border = Border(left=thin, right=thin, top=thin, bottom=thin)
        except Exception:
            pass

    def _fill(self, color_key: str) -> "PatternFill":
        color = self.COLORS.get(color_key, color_key)
        return PatternFill(start_color=color, end_color=color, fill_type='solid')

    def _style_header(self, cell, color_key: str = 'header_blue'):
        cell.font = Font(bold=True, color='FFFFFF', size=11)
        cell.fill = self._fill(color_key)
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        if self._border:
            cell.border = self._border

    def _style_data(self, cell, bold: bool = False, align: str = 'center'):
        cell.alignment = Alignment(horizontal=align, vertical='center')
        if bold:
            cell.font = Font(bold=True)
        if self._border:
            cell.border = self._border

    def generate_report(self, report_type: str, days: int, generator_id: str = None) -> bytes:
        """Generate Excel report based on type."""
        if not EXCEL_AVAILABLE:
            raise RuntimeError("openpyxl не встановлено")

        self.wb = Workbook()

        if report_type == 'quick':
            self._generate_quick_report(days, generator_id)
        elif report_type == 'detailed':
            self._generate_detailed_report(days, generator_id)
        elif report_type == 'technical':
            self._generate_technical_report(days, generator_id)
        elif report_type == 'financial':
            self._generate_financial_report(days, generator_id)
        elif report_type == 'personnel':
            self._generate_personnel_report(days, generator_id)
        else:
            raise ValueError(f"Невідомий тип звіту: {report_type}")

        buf = io.BytesIO()
        self.wb.save(buf)
        buf.seek(0)
        return buf.read()

    # ------------------------------------------------------------------
    # Quick summary report
    # ------------------------------------------------------------------

    def _generate_quick_report(self, days: int, gen_id: str):
        """Quick summary report with KPI cards and daily table."""
        ws = self.wb.active
        ws.title = "Швидкий звіт"

        gen_id = gen_id or db.get_active_generator()
        gen_name = db.get_generator_name(gen_id)
        now = datetime.now(config.KYIV)
        start_dt = now - timedelta(days=days)

        # Title
        ws['A1'] = f"Генератор «{gen_name}» — Швидкий звіт за {days} днів"
        ws['A1'].font = Font(bold=True, size=14, color=self.COLORS['dark_text'])
        ws.merge_cells('A1:F1')
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws['A1'].fill = self._fill('header_bg')
        ws.row_dimensions[1].height = 28

        # KPI Section header
        ws['A3'] = 'Ключові показники'
        ws['A3'].font = Font(bold=True, size=12)

        daily = self._build_daily_stats(start_dt, now, gen_id)
        total_hours = round(sum(d['work_hours'] for d in daily), 1)
        total_fuel = round(sum(d['fuel_consumed'] for d in daily), 1)
        avg_rate = round(total_fuel / total_hours, 2) if total_hours > 0 else 0.0
        fuel_price = getattr(config, 'FUEL_PRICE', 50.0)
        fuel_cost = round(total_fuel * fuel_price, 0)

        kpi_labels = ['Мотогодини', 'Витрата палива, л', 'Сер. витрата, л/год', 'Вартість палива, грн']
        kpi_values = [total_hours, total_fuel, avg_rate, fuel_cost]

        for ci, (lbl, val) in enumerate(zip(kpi_labels, kpi_values), start=1):
            lc = ws.cell(row=4, column=ci, value=lbl)
            lc.font = Font(bold=True, size=10)
            lc.fill = self._fill('light_blue')
            lc.alignment = Alignment(horizontal='center')
            vc = ws.cell(row=5, column=ci, value=val)
            vc.font = Font(bold=True, size=13)
            vc.alignment = Alignment(horizontal='center')
            ws.column_dimensions[get_column_letter(ci)].width = 22

        # Daily summary table
        ws['A7'] = 'Щоденна статистика'
        ws['A7'].font = Font(bold=True, size=12)

        headers = ['Дата', 'Мотогодини', 'Витрата, л', 'Залишок ранок, л', 'Залишок вечір, л', 'Заправка, л']
        for ci, h in enumerate(headers, start=1):
            self._style_header(ws.cell(row=8, column=ci, value=h))
        ws.row_dimensions[8].height = 30

        for ri, d in enumerate(daily, start=9):
            ws.cell(row=ri, column=1, value=d['date'])
            ws.cell(row=ri, column=2, value=d['work_hours'])
            ws.cell(row=ri, column=3, value=d['fuel_consumed'])
            ws.cell(row=ri, column=4, value=d.get('morning_fuel', ''))
            eve_cell = ws.cell(row=ri, column=5, value=d.get('evening_fuel', ''))
            ws.cell(row=ri, column=6, value=d.get('refill_total', 0) or '')
            for ci in range(1, 7):
                self._style_data(ws.cell(row=ri, column=ci), bold=(ci == 1))
            # Conditional formatting on evening fuel
            eve_val = d.get('evening_fuel')
            if isinstance(eve_val, (int, float)):
                if eve_val < 15:
                    eve_cell.fill = self._fill('red')
                elif eve_val < 40:
                    eve_cell.fill = self._fill('orange')

        # Fuel timeline chart
        if len(daily) > 1:
            chart = LineChart()
            chart.title = f"Витрата палива — {gen_name}"
            chart.x_axis.title = "Дата"
            chart.y_axis.title = "Літри"
            chart.width = 20
            chart.height = 10

            data_start_row = 9
            data_end_row = 8 + len(daily)
            fuel_ref = Reference(ws, min_col=3, min_row=data_start_row, max_row=data_end_row)
            date_ref = Reference(ws, min_col=1, min_row=data_start_row, max_row=data_end_row)
            chart.add_data(fuel_ref, titles_from_data=False)
            chart.set_categories(date_ref)
            if chart.series and chart.series[0] is not None and chart.series[0].title is not None:
                chart.series[0].title.value = "Витрата, л"
            ws.add_chart(chart, f"A{data_end_row + 3}")

    # ------------------------------------------------------------------
    # Detailed multi-sheet report
    # ------------------------------------------------------------------

    def _generate_detailed_report(self, days: int, gen_id: str):
        """Detailed multi-sheet report with daily breakdown."""
        gen_id = gen_id or db.get_active_generator()
        gen_name = db.get_generator_name(gen_id)
        now = datetime.now(config.KYIV)
        start_dt = now - timedelta(days=days)

        # Sheet 1: Summary
        ws_summary = self.wb.active
        ws_summary.title = "Зведення"
        self._fill_summary_sheet(ws_summary, days, gen_id, gen_name, now, start_dt)

        # Sheet 2: Daily Stats
        ws_daily = self.wb.create_sheet("Щоденна статистика")
        self._fill_daily_sheet(ws_daily, gen_id, gen_name, days, now, start_dt)

        # Sheet 3: Maintenance
        ws_maint = self.wb.create_sheet("Технічне обслуговування")
        self._fill_maintenance_sheet(ws_maint, gen_id, gen_name)

    def _fill_summary_sheet(self, ws, days, gen_id, gen_name, now, start_dt):
        ws['A1'] = f"Детальний звіт: «{gen_name}» за {days} днів"
        ws['A1'].font = Font(bold=True, size=14, color=self.COLORS['dark_text'])
        ws.merge_cells('A1:G1')
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws['A1'].fill = self._fill('header_bg')
        ws.row_dimensions[1].height = 28

        ws['A2'] = f"Сформовано: {now.strftime('%d.%m.%Y %H:%M')}"
        ws['A2'].font = Font(italic=True, size=10)

        daily = self._build_daily_stats(start_dt, now, gen_id)
        total_hours = round(sum(d['work_hours'] for d in daily), 1)
        total_fuel = round(sum(d['fuel_consumed'] for d in daily), 1)
        avg_rate = round(total_fuel / total_hours, 2) if total_hours > 0 else 0.0
        fuel_price = getattr(config, 'FUEL_PRICE', 50.0)
        fuel_cost = round(total_fuel * fuel_price, 0)
        total_refills = round(sum(d.get('refill_total', 0) or 0 for d in daily), 1)

        summary_data = [
            ('Генератор', gen_name),
            ('Період', f"{start_dt.strftime('%d.%m.%Y')} — {now.strftime('%d.%m.%Y')}"),
            ('Кількість днів', days),
            ('Загальні мотогодини', total_hours),
            ('Загальна витрата палива, л', total_fuel),
            ('Середня витрата, л/год', avg_rate),
            ('Загальна вартість палива, грн', fuel_cost),
            ('Загальне поповнення, л', total_refills),
        ]

        for ri, (label, value) in enumerate(summary_data, start=4):
            lc = ws.cell(row=ri, column=1, value=label)
            lc.font = Font(bold=True)
            lc.fill = self._fill('light_blue')
            vc = ws.cell(row=ri, column=2, value=value)
            self._style_data(lc, bold=True, align='left')
            self._style_data(vc)
        ws.column_dimensions['A'].width = 36
        ws.column_dimensions['B'].width = 28

    def _fill_daily_sheet(self, ws, gen_id, gen_name, days, now, start_dt):
        ws['A1'] = f"Щоденна статистика — «{gen_name}»"
        ws['A1'].font = Font(bold=True, size=13)
        ws.merge_cells('A1:H1')
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws['A1'].fill = self._fill('header_bg')
        ws.row_dimensions[1].height = 24

        headers = [
            'Дата',
            'Мотогодини',
            'Витрата, л',
            'Сер. витрата, л/год',
            'Залишок ранок, л',
            'Залишок вечір, л',
            'Заправка, л',
            'Зміни',
        ]
        for ci, h in enumerate(headers, start=1):
            self._style_header(ws.cell(row=2, column=ci, value=h))
        ws.row_dimensions[2].height = 36

        col_widths = [14, 14, 13, 18, 18, 18, 13, 20]
        for ci, w in enumerate(col_widths, start=1):
            ws.column_dimensions[get_column_letter(ci)].width = w

        daily = self._build_daily_stats(start_dt, now, gen_id)
        for ri, d in enumerate(daily, start=3):
            rate = round(d['fuel_consumed'] / d['work_hours'], 2) if d['work_hours'] > 0 else ''
            shifts_str = ', '.join(d.get('shifts_active', []))
            row_vals = [
                d['date'],
                d['work_hours'],
                d['fuel_consumed'],
                rate,
                d.get('morning_fuel', ''),
                d.get('evening_fuel', ''),
                d.get('refill_total', 0) or '',
                shifts_str,
            ]
            for ci, val in enumerate(row_vals, start=1):
                c = ws.cell(row=ri, column=ci, value=val)
                self._style_data(c, bold=(ci == 1), align='left' if ci == 8 else 'center')
            # Highlight low evening fuel
            eve_val = d.get('evening_fuel')
            if isinstance(eve_val, (int, float)):
                eve_cell = ws.cell(row=ri, column=6)
                if eve_val < 15:
                    eve_cell.fill = self._fill('red')
                elif eve_val < 40:
                    eve_cell.fill = self._fill('orange')
                elif eve_val > 60:
                    eve_cell.fill = self._fill('light_green')

    def _fill_maintenance_sheet(self, ws, gen_id, gen_name):
        ws['A1'] = f"Технічне обслуговування — «{gen_name}»"
        ws['A1'].font = Font(bold=True, size=13)
        ws.merge_cells('A1:E1')
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws['A1'].fill = self._fill('header_bg')

        stats = db.get_maintenance_stats(gen_id)
        ws['A3'] = 'Мотогодини (загалом):'
        ws['A3'].font = Font(bold=True)
        ws['B3'] = f"{float(stats.get('total_hours', 0)):.1f} год"

        oil_interval = getattr(config, 'OIL_CHANGE_INTERVAL', 250)
        spark_interval = getattr(config, 'SPARK_CHANGE_INTERVAL', 500)
        oil_h = float(stats.get('last_oil_change', 0) or 0)
        spark_h = float(stats.get('last_spark_change', 0) or 0)
        total_h = float(stats.get('total_hours', 0) or 0)

        ws['A4'] = 'До заміни мастила:'
        ws['A4'].font = Font(bold=True)
        ws['B4'] = f"{max(0, oil_interval - (total_h - oil_h)):.0f} год"
        ws['A5'] = 'До заміни свічок:'
        ws['A5'].font = Font(bold=True)
        ws['B5'] = f"{max(0, spark_interval - (total_h - spark_h)):.0f} год"

        mnt_col_hdrs = ['Дата', 'Тип ТО', 'Мотогодини', 'Виконав', 'Примітки']
        for ci, h in enumerate(mnt_col_hdrs, start=1):
            self._style_header(ws.cell(row=7, column=ci, value=h))

        col_widths_mnt = [14, 22, 18, 20, 20]
        for ci, w in enumerate(col_widths_mnt, start=1):
            ws.column_dimensions[get_column_letter(ci)].width = w

        mnt_map = {'oil': 'Заміна мастила', 'spark': 'Заміна свічок', 'maintenance': 'Планове ТО'}
        mnt_history = db.get_maintenance_history(gen_id, 100)
        for ri, rec in enumerate(mnt_history, start=8):
            rec_id, date_s, action, hours, admin_name, *_ = rec
            ws.cell(row=ri, column=1, value=date_s)
            ws.cell(row=ri, column=2, value=mnt_map.get(action, action))
            ws.cell(row=ri, column=3, value=f"{float(hours):.1f} год")
            ws.cell(row=ri, column=4, value=admin_name or '—')
            for ci in range(1, 5):
                self._style_data(ws.cell(row=ri, column=ci))

    # ------------------------------------------------------------------
    # Technical report
    # ------------------------------------------------------------------

    def _generate_technical_report(self, days: int, gen_id: str):
        """Technical report focused on generator performance."""
        gen_id = gen_id or db.get_active_generator()
        gen_name = db.get_generator_name(gen_id)
        now = datetime.now(config.KYIV)
        start_dt = now - timedelta(days=days)

        ws = self.wb.active
        ws.title = "Технічний звіт"

        ws['A1'] = f"Технічний звіт: «{gen_name}» за {days} днів"
        ws['A1'].font = Font(bold=True, size=14, color=self.COLORS['dark_text'])
        ws.merge_cells('A1:E1')
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws['A1'].fill = self._fill('header_bg')
        ws.row_dimensions[1].height = 28

        stats = db.get_maintenance_stats(gen_id)
        main_stats = db.get_generator_stats(gen_id)
        daily = self._build_daily_stats(start_dt, now, gen_id)
        total_hours = round(sum(d['work_hours'] for d in daily), 1)
        total_fuel = round(sum(d['fuel_consumed'] for d in daily), 1)
        avg_rate = round(total_fuel / total_hours, 2) if total_hours > 0 else 0.0

        oil_interval = getattr(config, 'OIL_CHANGE_INTERVAL', 250)
        spark_interval = getattr(config, 'SPARK_CHANGE_INTERVAL', 500)
        total_h = float(stats.get('total_hours', 0) or 0)
        oil_h = float(stats.get('last_oil_change', 0) or 0)
        spark_h = float(stats.get('last_spark_change', 0) or 0)
        oil_remaining = max(0, oil_interval - (total_h - oil_h))
        spark_remaining = max(0, spark_interval - (total_h - spark_h))

        tech_data = [
            ('Загальні мотогодини (всього)', f"{float(main_stats.get('total_hours', 0)):.1f} год"),
            ('Мотогодини за звітний період', f"{total_hours:.1f} год"),
            ('Загальна витрата палива', f"{total_fuel:.1f} л"),
            ('Середня витрата, л/год', f"{avg_rate:.2f}"),
            ('До заміни мастила', f"{oil_remaining:.0f} год"),
            ('До заміни свічок', f"{spark_remaining:.0f} год"),
        ]

        ws['A3'] = 'Технічні показники'
        ws['A3'].font = Font(bold=True, size=12)
        for ri, (label, value) in enumerate(tech_data, start=4):
            lc = ws.cell(row=ri, column=1, value=label)
            vc = ws.cell(row=ri, column=2, value=value)
            lc.font = Font(bold=True)
            lc.fill = self._fill('light_blue')
            self._style_data(lc, bold=True, align='left')
            self._style_data(vc)
            # Highlight if maintenance is due
            if 'мастила' in label and oil_remaining < oil_interval * 0.1:
                vc.fill = self._fill('red')
            elif 'свічок' in label and spark_remaining < spark_interval * 0.1:
                vc.fill = self._fill('red')

        ws.column_dimensions['A'].width = 36
        ws.column_dimensions['B'].width = 20

        # Maintenance history sheet
        ws_maint = self.wb.create_sheet("ТО Історія")
        self._fill_maintenance_sheet(ws_maint, gen_id, gen_name)

    # ------------------------------------------------------------------
    # Financial report
    # ------------------------------------------------------------------

    def _generate_financial_report(self, days: int, gen_id: str):
        """Financial report with cost analysis."""
        gen_id = gen_id or db.get_active_generator()
        gen_name = db.get_generator_name(gen_id)
        now = datetime.now(config.KYIV)
        start_dt = now - timedelta(days=days)

        ws = self.wb.active
        ws.title = "Фінансовий звіт"

        ws['A1'] = f"Фінансовий звіт: «{gen_name}» за {days} днів"
        ws['A1'].font = Font(bold=True, size=14, color=self.COLORS['dark_text'])
        ws.merge_cells('A1:F1')
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws['A1'].fill = self._fill('header_bg')
        ws.row_dimensions[1].height = 28

        daily = self._build_daily_stats(start_dt, now, gen_id)
        total_hours = round(sum(d['work_hours'] for d in daily), 1)
        total_fuel = round(sum(d['fuel_consumed'] for d in daily), 1)
        avg_rate = round(total_fuel / total_hours, 2) if total_hours > 0 else 0.0
        fuel_price = getattr(config, 'FUEL_PRICE', 50.0)
        fuel_cost = round(total_fuel * fuel_price, 0)
        cost_per_hour = round(fuel_cost / total_hours, 2) if total_hours > 0 else 0.0

        fin_data = [
            ('Ціна палива, грн/л', fuel_price),
            ('Загальна витрата палива, л', total_fuel),
            ('Загальна вартість палива, грн', fuel_cost),
            ('Мотогодин', total_hours),
            ('Вартість 1 мотогодини, грн', cost_per_hour),
            ('Середня витрата, л/год', avg_rate),
        ]

        ws['A3'] = 'Фінансові показники'
        ws['A3'].font = Font(bold=True, size=12)
        for ri, (label, value) in enumerate(fin_data, start=4):
            lc = ws.cell(row=ri, column=1, value=label)
            vc = ws.cell(row=ri, column=2, value=value)
            lc.font = Font(bold=True)
            lc.fill = self._fill('light_blue')
            self._style_data(lc, bold=True, align='left')
            self._style_data(vc)
        ws.column_dimensions['A'].width = 36
        ws.column_dimensions['B'].width = 20

        # Daily cost breakdown
        ws['A11'] = 'Щоденні витрати'
        ws['A11'].font = Font(bold=True, size=12)
        fin_headers = ['Дата', 'Мотогодини', 'Витрата, л', 'Вартість, грн']
        for ci, h in enumerate(fin_headers, start=1):
            self._style_header(ws.cell(row=12, column=ci, value=h))
        for ri, d in enumerate(daily, start=13):
            day_cost = round(d['fuel_consumed'] * fuel_price, 0)
            row_vals = [d['date'], d['work_hours'], d['fuel_consumed'], day_cost]
            for ci, val in enumerate(row_vals, start=1):
                c = ws.cell(row=ri, column=ci, value=val)
                self._style_data(c, bold=(ci == 1))
        for ci, w in enumerate([14, 14, 13, 16], start=1):
            ws.column_dimensions[get_column_letter(ci)].width = w

    # ------------------------------------------------------------------
    # Personnel report
    # ------------------------------------------------------------------

    def _generate_personnel_report(self, days: int, gen_id: str):
        """Personnel report with shift statistics."""
        gen_id = gen_id or db.get_active_generator()
        gen_name = db.get_generator_name(gen_id)
        now = datetime.now(config.KYIV)
        start_dt = now - timedelta(days=days)

        ws = self.wb.active
        ws.title = "По персоналу"

        ws['A1'] = f"Звіт по персоналу: «{gen_name}» за {days} днів"
        ws['A1'].font = Font(bold=True, size=14, color=self.COLORS['dark_text'])
        ws.merge_cells('A1:E1')
        ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
        ws['A1'].fill = self._fill('header_bg')
        ws.row_dimensions[1].height = 28

        start_date = start_dt.strftime('%Y-%m-%d')
        end_date = now.strftime('%Y-%m-%d')
        logs = db.get_logs_for_period(start_date, end_date, gen_id)

        pname_map: dict = {}
        for row in logs:
            event_type, ts_str, user_name = row[0], row[1], row[2]
            if event_type in ('m_start', 'd_start', 'e_start', 'x_start'):
                if user_name not in pname_map:
                    pname_map[user_name] = {'name': user_name, 'shifts': 0}
                pname_map[user_name]['shifts'] += 1

        personnel_headers = ['Ім\'я', 'Кількість змін']
        ws['A3'] = 'Статистика по персоналу'
        ws['A3'].font = Font(bold=True, size=12)
        for ci, h in enumerate(personnel_headers, start=1):
            self._style_header(ws.cell(row=4, column=ci, value=h))
        for ri, p in enumerate(pname_map.values(), start=5):
            ws.cell(row=ri, column=1, value=p['name'])
            ws.cell(row=ri, column=2, value=p['shifts'])
            for ci in range(1, 3):
                self._style_data(ws.cell(row=ri, column=ci))
        ws.column_dimensions['A'].width = 30
        ws.column_dimensions['B'].width = 20

    # ------------------------------------------------------------------
    # Helper: build daily statistics
    # ------------------------------------------------------------------

    def _build_daily_stats(self, start_dt: datetime, now: datetime, gen_id: str) -> list:
        """Build daily statistics list from database logs."""
        start_date = start_dt.strftime('%Y-%m-%d')
        end_date = now.strftime('%Y-%m-%d')
        logs = db.get_logs_for_period(start_date, end_date, gen_id)
        fuel_rate = db.get_fuel_consumption_rate()

        days_data = defaultdict(
            lambda: {
                'shifts': {'m': {}, 'd': {}, 'e': {}, 'x': {}},
                'refills': [],
                'morning_fuel': None,
                'evening_fuel': None,
            }
        )

        for row_data in logs:
            event_type, ts_str, user_name, value, driver_name, receipt_number, *_ = row_data
            if not ts_str:
                continue
            try:
                ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
            except Exception:
                continue
            date_str = ts.strftime('%Y-%m-%d')
            day = days_data[date_str]

            if event_type.endswith('_start'):
                shift = event_type.split('_')[0]
                if shift in day['shifts']:
                    day['shifts'][shift]['start'] = ts.strftime('%H:%M')
            elif event_type.endswith('_end'):
                shift = event_type.split('_')[0]
                if shift in day['shifts']:
                    day['shifts'][shift]['end'] = ts.strftime('%H:%M')
            elif event_type == 'refill':
                try:
                    liters = float(value or 0)
                except Exception:
                    liters = 0.0
                day['refills'].append(liters)
            elif event_type == 'corr_fuel_set':
                try:
                    day['evening_fuel'] = float(value or 0)
                except Exception:
                    pass

        # Initialize fuel balance from current state
        state = db.get_state()
        current_fuel = float(state.get('current_fuel', 0) or 0)

        # Calculate backwards from current fuel to get starting fuel for the period
        # We need to account for all refills and consumption from end_date to now
        total_period_fuel = sum(sum(day['refills']) for day in days_data.values())
        total_period_consumption = 0.0
        for day in days_data.values():
            total_shift_mins = 0
            for shift_data in day['shifts'].values():
                s_str = shift_data.get('start')
                e_str = shift_data.get('end')
                if s_str and e_str:
                    try:
                        s_t = datetime.strptime(s_str, '%H:%M')
                        e_t = datetime.strptime(e_str, '%H:%M')
                        diff = (e_t - s_t).total_seconds() / 60
                        if diff < 0:
                            diff += 24 * 60
                        total_shift_mins += diff
                    except Exception:
                        pass
            work_hours = total_shift_mins / 60
            total_period_consumption += work_hours * fuel_rate

        # Starting fuel = current_fuel - refills + consumption
        starting_fuel = current_fuel - total_period_fuel + total_period_consumption
        prev_fuel = starting_fuel if starting_fuel > 0 else None

        result = []
        for date_str in sorted(days_data.keys()):
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                date_fmt = dt.strftime('%d.%m.%Y')
            except Exception:
                date_fmt = date_str

            day = days_data[date_str]
            total_shift_mins = 0
            shifts_active = []
            for sname, shift_data in day['shifts'].items():
                s_str = shift_data.get('start')
                e_str = shift_data.get('end')
                if s_str and e_str:
                    try:
                        s_t = datetime.strptime(s_str, '%H:%M')
                        e_t = datetime.strptime(e_str, '%H:%M')
                        diff = (e_t - s_t).total_seconds() / 60
                        if diff < 0:
                            diff += 24 * 60
                        total_shift_mins += diff
                        shifts_active.append(sname)
                    except Exception:
                        pass

            work_hours = round(total_shift_mins / 60, 2)
            fuel_consumed = round(work_hours * fuel_rate, 1) if work_hours > 0 else 0.0
            refill_total = round(sum(day['refills']), 1) if day['refills'] else 0.0

            morning_fuel = day.get('morning_fuel') or prev_fuel
            if morning_fuel is not None:
                evening_fuel = round(float(morning_fuel) + refill_total - fuel_consumed, 1)
            else:
                morning_fuel = None
                evening_fuel = None

            prev_fuel = evening_fuel if isinstance(evening_fuel, float) else None

            result.append(
                {
                    'date': date_fmt,
                    'work_hours': work_hours,
                    'fuel_consumed': fuel_consumed,
                    'morning_fuel': morning_fuel,
                    'evening_fuel': evening_fuel,
                    'morning_balance': morning_fuel,
                    'evening_balance': evening_fuel,
                    'refill_total': refill_total if refill_total > 0 else None,
                    # outage_hours = work_hours because the generator runs during power outages
                    'outage_hours': work_hours,
                    'shifts_active': shifts_active,
                }
            )

        return result


def generate_excel_report(report_type: str, days: int, generator_id: str = None) -> bytes:
    """Main entry point for Excel report generation."""
    generator = ExcelReportGenerator()
    return generator.generate_report(report_type, days, generator_id)
