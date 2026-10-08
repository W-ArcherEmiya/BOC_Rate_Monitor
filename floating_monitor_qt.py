import random
import sqlite3
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from plyer import notification
from PySide6.QtCore import QPoint, Qt, QTimer, QObject, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)


CURRENCY_META = {
    "人民币": {"code": "CNY", "flag": "CN"},
    "英镑": {"code": "GBP", "flag": "GB"},
    "美元": {"code": "USD", "flag": "US"},
    "欧元": {"code": "EUR", "flag": "EU"},
    "日元": {"code": "JPY", "flag": "JP"},
    "港币": {"code": "HKD", "flag": "HK"},
    "澳大利亚元": {"code": "AUD", "flag": "AU"},
    "加拿大元": {"code": "CAD", "flag": "CA"},
    "瑞士法郎": {"code": "CHF", "flag": "CH"},
    "新加坡元": {"code": "SGD", "flag": "SG"},
}

HISTORY_DB_PATH = Path(__file__).with_name("rate_history.sqlite3")
MAX_HISTORY_SECONDS = 3 * 365 * 24 * 60 * 60
DAY_SECONDS = 24 * 60 * 60
FRANKFURTER_API_URL = "https://api.frankfurter.dev/v2/rates"
CHART_RANGE_OPTIONS = [
    ("30min", 30 * 60),
    ("1h", 60 * 60),
    ("2h", 2 * 60 * 60),
    ("1d", 24 * 60 * 60),
    ("2d", 2 * 24 * 60 * 60),
    ("1周", 7 * 24 * 60 * 60),
    ("1个月", 30 * 24 * 60 * 60),
    ("3个月", 90 * 24 * 60 * 60),
    ("6个月", 180 * 24 * 60 * 60),
    ("1年", 365 * 24 * 60 * 60),
    ("2年", 2 * 365 * 24 * 60 * 60),
    ("3年", 3 * 365 * 24 * 60 * 60),
]

app_instances = []


def currency_code(currency):
    return CURRENCY_META.get(currency, {"code": currency})["code"]


def format_pair_title(base_currency, quote_currency):
    return f"{currency_code(base_currency)}/{currency_code(quote_currency)}"


def short_currency_code(currency):
    return currency_code(currency)[:2]


def uses_external_history(range_seconds):
    return range_seconds >= DAY_SECONDS


def init_history_db():
    conn = sqlite3.connect(HISTORY_DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rate_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                base_currency TEXT NOT NULL,
                quote_currency TEXT NOT NULL,
                price REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rate_history_pair_time
            ON rate_history (base_currency, quote_currency, timestamp)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS external_rate_history (
                rate_date TEXT NOT NULL,
                base_currency TEXT NOT NULL,
                quote_currency TEXT NOT NULL,
                price REAL NOT NULL,
                fetched_at REAL NOT NULL,
                PRIMARY KEY (rate_date, base_currency, quote_currency)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def load_last_currency_pair():
    conn = sqlite3.connect(HISTORY_DB_PATH)
    try:
        rows = dict(
            conn.execute(
                "SELECT key, value FROM app_settings WHERE key IN ('base_currency', 'quote_currency')"
            ).fetchall()
        )
    finally:
        conn.close()

    base_currency = rows.get("base_currency", "英镑")
    quote_currency = rows.get("quote_currency", "人民币")
    if base_currency not in CURRENCY_META:
        base_currency = "英镑"
    if quote_currency not in CURRENCY_META:
        quote_currency = "人民币"
    return base_currency, quote_currency


def save_last_currency_pair(base_currency, quote_currency):
    conn = sqlite3.connect(HISTORY_DB_PATH)
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
            [("base_currency", base_currency), ("quote_currency", quote_currency)],
        )
        conn.commit()
    finally:
        conn.close()


def save_history_point(base_currency, quote_currency, price):
    cutoff = time.time() - MAX_HISTORY_SECONDS
    conn = sqlite3.connect(HISTORY_DB_PATH)
    try:
        conn.execute(
            """
            INSERT INTO rate_history (timestamp, base_currency, quote_currency, price)
            VALUES (?, ?, ?, ?)
            """,
            (time.time(), base_currency, quote_currency, price),
        )
        conn.execute("DELETE FROM rate_history WHERE timestamp < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()


def sample_points(points, max_points):
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    sampled = [points[int(index * step)] for index in range(max_points)]
    sampled[-1] = points[-1]
    return sampled


def load_history_points(base_currency, quote_currency, range_seconds, max_points=180):
    cutoff = time.time() - range_seconds
    conn = sqlite3.connect(HISTORY_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT timestamp, price
            FROM rate_history
            WHERE base_currency = ? AND quote_currency = ? AND timestamp >= ?
            ORDER BY timestamp
            """,
            (base_currency, quote_currency, cutoff),
        ).fetchall()
    finally:
        conn.close()
    return sample_points(rows, max_points)


def load_latest_history_point(base_currency, quote_currency):
    conn = sqlite3.connect(HISTORY_DB_PATH)
    try:
        row = conn.execute(
            """
            SELECT timestamp, price
            FROM rate_history
            WHERE base_currency = ? AND quote_currency = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (base_currency, quote_currency),
        ).fetchone()
    finally:
        conn.close()
    return row


def save_external_history_points(base_currency, quote_currency, rows):
    if not rows:
        return
    conn = sqlite3.connect(HISTORY_DB_PATH)
    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO external_rate_history
                (rate_date, base_currency, quote_currency, price, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(rate_date, base_currency, quote_currency, price, time.time()) for rate_date, price in rows],
        )
        conn.commit()
    finally:
        conn.close()


def load_external_history_points(base_currency, quote_currency, start_date, end_date, max_points=180):
    conn = sqlite3.connect(HISTORY_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT rate_date, price
            FROM external_rate_history
            WHERE base_currency = ? AND quote_currency = ?
              AND rate_date >= ? AND rate_date <= ?
            ORDER BY rate_date
            """,
            (base_currency, quote_currency, start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
    finally:
        conn.close()
    points = [(datetime.strptime(rate_date, "%Y-%m-%d").timestamp(), price) for rate_date, price in rows]
    return sample_points(points, max_points)


def fetch_external_history_points(base_currency, quote_currency, range_seconds, session, max_points=180):
    base_code = currency_code(base_currency)
    quote_code = currency_code(quote_currency)
    end_date = date.today()
    start_date = end_date - timedelta(days=max(1, range_seconds // DAY_SECONDS))

    if base_code == quote_code:
        rows = []
        cursor = start_date
        while cursor <= end_date:
            rows.append((cursor.isoformat(), 1.0))
            cursor += timedelta(days=1)
        save_external_history_points(base_currency, quote_currency, rows)
        return load_external_history_points(base_currency, quote_currency, start_date, end_date, max_points)

    response = session.get(
        FRANKFURTER_API_URL,
        params={"from": start_date.isoformat(), "to": end_date.isoformat(), "base": base_code, "quotes": quote_code},
        timeout=10,
    )
    response.raise_for_status()
    rows = [
        (item["date"], float(item["rate"]))
        for item in response.json()
        if item.get("quote") == quote_code and item.get("rate") is not None
    ]
    save_external_history_points(base_currency, quote_currency, rows)
    return load_external_history_points(base_currency, quote_currency, start_date, end_date, max_points)


def send_system_notification(title, message):
    def _notify():
        try:
            notification.notify(title=title, message=message, app_name="汇率监控", timeout=5)
        except Exception:
            pass

    threading.Thread(target=_notify, daemon=True).start()


class Bridge(QObject):
    rate_loaded = Signal(object, object)
    history_loaded = Signal(int, object, str)


class ChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []
        self.message = "No data 30min"
        self.setMinimumHeight(36)

    def set_points(self, points, message=""):
        self.points = points
        self.message = message
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 2, -4, -3)
        baseline = rect.bottom()
        painter.setPen(QPen(QColor(38, 51, 67), 1))
        painter.drawLine(rect.left(), baseline, rect.right(), baseline)

        if not self.points:
            painter.setPen(QColor(96, 108, 126))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return

        prices = [price for _, price in self.points]
        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price
        if len(prices) == 1 or price_range == 0:
            y = rect.center().y()
            painter.setPen(QPen(QColor("#00a8ff"), 2))
            painter.drawLine(rect.left(), y, rect.right(), y)
            return

        path = QPainterPath()
        fill = QPainterPath()
        last_index = len(prices) - 1
        for index, price in enumerate(prices):
            x = rect.left() + rect.width() * index / last_index
            y = rect.top() + rect.height() * (max_price - price) / price_range
            if index == 0:
                path.moveTo(x, y)
                fill.moveTo(x, baseline)
                fill.lineTo(x, y)
            else:
                path.lineTo(x, y)
                fill.lineTo(x, y)

        fill.lineTo(rect.right(), baseline)
        fill.closeSubpath()
        up = prices[-1] >= prices[0]
        line_color = QColor("#ff4b55" if up else "#2ed573")
        glow_color = QColor(255, 75, 85, 32) if up else QColor(46, 213, 115, 32)
        painter.fillPath(fill, glow_color)
        painter.setPen(QPen(line_color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)

        end = path.currentPosition()
        painter.setBrush(QColor(line_color.red(), line_color.green(), line_color.blue(), 80))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(end, 5, 5)
        painter.setBrush(line_color)
        painter.drawEllipse(end, 2.4, 2.4)


class RateWindow(QWidget):
    def __init__(self, base_currency="英镑", quote_currency="人民币", y_offset=0):
        super().__init__()
        self.base_currency = base_currency
        self.quote_currency = quote_currency
        self.chart_range_label = "30min"
        self.chart_range_seconds = 30 * 60
        self.previous_price = None
        self.target_price = 0.0
        self.target_alert_triggered = False
        self.fluctuation_threshold_ratio = 0.005
        self.last_update_time = ""
        self.drag_offset = QPoint()
        self.history_token = 0
        self.http_session = requests.Session()
        self.http_session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.boc.cn/sourcedb/whpj/",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        )

        self.bridge = Bridge()
        self.bridge.rate_loaded.connect(self.update_ui)
        self.bridge.history_loaded.connect(self.apply_history)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(240, 128)
        self.move(100, 100 + y_offset)
        self.build_ui()
        self.apply_cached_rate()
        self.refresh_chart_history(force_external=True)
        self.fetch_now()
        self.schedule_next_fetch()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame(self)
        self.card.setObjectName("card")
        self.card.setStyleSheet(
            """
            QFrame#card {
                background: rgba(45, 52, 62, 232);
                border: 1px solid rgba(255, 255, 255, 36);
                border-radius: 16px;
            }
            QLabel { background: transparent; color: white; }
            """
        )
        root.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(14, 10, 14, 9)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.badge_label = QLabel(short_currency_code(self.base_currency))
        self.badge_label.setStyleSheet(
            "background: rgba(255,255,255,24); border: 1px solid rgba(255,255,255,32);"
            "border-radius: 5px; padding: 1px 5px; font: 700 9px 'Segoe UI'; color: rgba(255,255,255,230);"
        )
        self.title_label = QLabel(format_pair_title(self.base_currency, self.quote_currency))
        self.title_label.setStyleSheet("font: 700 13px 'Segoe UI'; color: white;")
        self.time_label = QLabel("")
        self.time_label.setStyleSheet("font: 10px 'Consolas'; color: #f1c40f;")
        header.addWidget(self.badge_label)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.time_label)
        layout.addLayout(header)

        value_row = QHBoxLayout()
        self.price_label = QLabel("- Loading...")
        self.price_label.setStyleSheet("font: 900 26px 'Consolas'; color: white;")
        self.change_label = QLabel("--")
        self.change_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.change_label.setStyleSheet(
            "background: rgba(255,255,255,22); border-radius: 6px; padding: 2px 7px;"
            "font: 700 10px 'Segoe UI'; color: #dcdde1;"
        )
        value_row.addWidget(self.price_label)
        value_row.addStretch(1)
        value_row.addWidget(self.change_label)
        layout.addLayout(value_row)

        self.chart = ChartWidget(self)
        layout.addWidget(self.chart)

    def enterEvent(self, event):
        if self.last_update_time:
            self.time_label.setText(self.last_update_time)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.time_label.setText("")
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            target = event.globalPosition().toPoint() - self.drag_offset
            screen = QApplication.primaryScreen().availableGeometry()
            target.setX(max(screen.left(), min(target.x(), screen.right() - self.width())))
            target.setY(max(screen.top(), min(target.y(), screen.bottom() - self.height())))
            self.move(target)
            event.accept()

    def contextMenuEvent(self, event):
        self.show_context_menu(event.globalPos())

    def show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background: rgba(24, 32, 43, 238);
                color: white;
                border: 1px solid rgba(255,255,255,60);
                padding: 4px;
            }
            QMenu::item { padding: 6px 24px 6px 10px; }
            QMenu::item:selected { background: #00a8ff; }
            QMenu::separator { height: 1px; background: rgba(255,255,255,60); margin: 4px 2px; }
            """
        )
        base_menu = menu.addMenu("选择基准货币")
        quote_menu = menu.addMenu("选择报价货币")
        for currency in CURRENCY_META:
            base_menu.addAction(currency, lambda c=currency: self.change_base_currency(c))
            quote_menu.addAction(currency, lambda c=currency: self.change_quote_currency(c))

        range_menu = menu.addMenu("线图范围")
        for label, seconds in CHART_RANGE_OPTIONS:
            range_menu.addAction(label, lambda l=label, s=seconds: self.change_chart_range(l, s))

        menu.addSeparator()
        menu.addAction("设定目标提醒价", self.set_target_price)
        menu.addSeparator()
        menu.addAction("新增监控浮窗", self.create_new_window)
        menu.addAction("关闭当前浮窗", self.close_window)
        menu.exec(pos)

    def update_pair_header(self):
        self.badge_label.setText(short_currency_code(self.base_currency))
        self.title_label.setText(format_pair_title(self.base_currency, self.quote_currency))

    def change_base_currency(self, currency):
        self.base_currency = currency
        save_last_currency_pair(self.base_currency, self.quote_currency)
        self.reset_pair_state()

    def change_quote_currency(self, currency):
        self.quote_currency = currency
        save_last_currency_pair(self.base_currency, self.quote_currency)
        self.reset_pair_state()

    def change_chart_range(self, label, seconds):
        self.chart_range_label = label
        self.chart_range_seconds = seconds
        self.refresh_chart_history(force_external=True)

    def reset_pair_state(self):
        self.previous_price = None
        self.target_price = 0.0
        self.target_alert_triggered = False
        self.price_label.setText("- Loading...")
        self.change_label.setText("--")
        self.change_label.setStyleSheet(self.change_style("#dcdde1", "rgba(255,255,255,22)"))
        self.update_pair_header()
        self.refresh_chart_history(force_external=True)
        self.fetch_now()

    def set_target_price(self):
        value, ok = QInputDialog.getDouble(self, "设定目标价", f"请输入 {format_pair_title(self.base_currency, self.quote_currency)} 的目标汇率", 0.0, 0.0)
        if ok:
            self.target_price = value
            self.target_alert_triggered = False

    def create_new_window(self):
        window = RateWindow("美元", "人民币", len(app_instances) * (self.height() + 10))
        app_instances.append(window)
        window.show()

    def close_window(self):
        save_last_currency_pair(self.base_currency, self.quote_currency)
        if self in app_instances:
            app_instances.remove(self)
        self.close()
        if not app_instances:
            QApplication.quit()

    def apply_cached_rate(self):
        latest = load_latest_history_point(self.base_currency, self.quote_currency)
        if not latest:
            return
        timestamp, price = latest
        self.last_update_time = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
        self.price_label.setText(f"- {price:.4f}")
        self.price_label.setStyleSheet("font: 900 26px 'Consolas'; color: white;")
        self.change_label.setText("cached")
        self.change_label.setStyleSheet(self.change_style("#dcdde1", "rgba(255,255,255,22)"))
        self.previous_price = price

    def fetch_boc_rates(self):
        url = f"https://www.boc.cn/sourcedb/whpj/index.html?_t={int(time.time() * 1000)}"
        try:
            response = self.http_session.get(url, timeout=5)
            response.encoding = "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")
            rates = {"人民币": (1.0, "")}
            for tr in soup.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) >= 8:
                    currency = tds[0].text.strip()
                    if currency in CURRENCY_META and currency != "人民币":
                        try:
                            sell_rate = float(tds[3].text.strip()) / 100
                        except ValueError:
                            continue
                        rates[currency] = (sell_rate, tds[7].text.strip())
            return rates
        except Exception:
            return None

    def fetch_pair_rate(self):
        rates = self.fetch_boc_rates()
        if not rates:
            return None, None
        base = rates.get(self.base_currency)
        quote = rates.get(self.quote_currency)
        if not base or not quote or quote[0] == 0:
            return None, None
        times = [value for value in (base[1], quote[1]) if value]
        return base[0] / quote[0], " / ".join(dict.fromkeys(times)) or "CNY"

    def fetch_now(self):
        threading.Thread(target=self._thread_fetch, daemon=True).start()

    def _thread_fetch(self):
        self.bridge.rate_loaded.emit(*self.fetch_pair_rate())

    def update_ui(self, price, update_time):
        if price is None:
            self.price_label.setText("Net Error")
            self.price_label.setStyleSheet("font: 900 24px 'Consolas'; color: #ff4b55;")
            return

        self.last_update_time = update_time
        price_text = f"{price:.4f}"
        arrow = "-"
        color = "white"
        change_text = "--"
        change_fg = "#dcdde1"
        change_bg = "rgba(255,255,255,22)"
        pair_title = format_pair_title(self.base_currency, self.quote_currency)

        if self.previous_price is not None:
            diff = price - self.previous_price
            abs_diff = abs(diff)
            change_text = f"{diff / self.previous_price * 100:+.2f}%"
            if diff > 0:
                arrow = "↑"
                color = "#ff4b55"
                change_fg = "#ff4b55"
                change_bg = "rgba(255,75,85,32)"
                if abs_diff / self.previous_price >= self.fluctuation_threshold_ratio:
                    send_system_notification(f"{pair_title} 上涨", f"现价: {price_text} (发自 {update_time})")
            elif diff < 0:
                arrow = "↓"
                color = "#2ed573"
                change_fg = "#2ed573"
                change_bg = "rgba(46,213,115,32)"
                if abs_diff / self.previous_price >= self.fluctuation_threshold_ratio:
                    send_system_notification(f"{pair_title} 下跌", f"现价: {price_text} (发自 {update_time})")

        self.price_label.setText(f"{arrow} {price_text}")
        self.price_label.setStyleSheet(f"font: 900 26px 'Consolas'; color: {color};")
        self.change_label.setText(change_text)
        self.change_label.setStyleSheet(self.change_style(change_fg, change_bg))
        save_history_point(self.base_currency, self.quote_currency, price)
        self.refresh_chart_history(force_external=False)
        self.previous_price = price

        if self.target_price > 0 and price <= self.target_price and not self.target_alert_triggered:
            send_system_notification(f"{pair_title} 达标提醒", f"已跌破 {self.target_price}，当前最新价: {price_text}")
            self.target_alert_triggered = True
        elif price > self.target_price:
            self.target_alert_triggered = False

    def change_style(self, fg, bg):
        return f"background: {bg}; border-radius: 6px; padding: 2px 7px; font: 700 10px 'Segoe UI'; color: {fg};"

    def refresh_chart_history(self, force_external=False):
        if uses_external_history(self.chart_range_seconds):
            if force_external:
                self.load_external_history_async()
            return
        points = load_history_points(self.base_currency, self.quote_currency, self.chart_range_seconds)
        self.chart.set_points(points, f"No data {self.chart_range_label}")

    def load_external_history_async(self):
        self.history_token += 1
        token = self.history_token
        base = self.base_currency
        quote = self.quote_currency
        seconds = self.chart_range_seconds
        label = self.chart_range_label
        self.chart.set_points([], f"Loading {label}")
        threading.Thread(target=self._thread_load_external_history, args=(token, base, quote, seconds, label), daemon=True).start()

    def _thread_load_external_history(self, token, base, quote, seconds, label):
        try:
            points = fetch_external_history_points(base, quote, seconds, self.http_session)
            message = f"No data {label}"
        except Exception:
            points = []
            message = "History error"
        self.bridge.history_loaded.emit(token, points, message)

    def apply_history(self, token, points, message):
        if token != self.history_token:
            return
        self.chart.set_points(points, message)

    def schedule_next_fetch(self):
        QTimer.singleShot(random.randint(20000, 45000), self.run_scheduled_fetch)

    def run_scheduled_fetch(self):
        self.fetch_now()
        self.schedule_next_fetch()


def main():
    init_history_db()
    app = QApplication(sys.argv)
    base_currency, quote_currency = load_last_currency_pair()
    window = RateWindow(base_currency, quote_currency)
    app_instances.append(window)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
