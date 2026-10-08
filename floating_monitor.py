import tkinter as tk
from tkinter import simpledialog
import threading
import requests
import time
import random
import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup
from plyer import notification

# ================= 货币 UI 映射字典 =================
CURRENCY_META = {
    "人民币": {"code": "CNY", "flag": "🇨🇳"},
    "英镑": {"code": "GBP", "flag": "🇬🇧"},
    "美元": {"code": "USD", "flag": "🇺🇸"},
    "欧元": {"code": "EUR", "flag": "🇪🇺"},
    "日元": {"code": "JPY", "flag": "🇯🇵"},
    "港币": {"code": "HKD", "flag": "🇭🇰"},
    "澳大利亚元": {"code": "AUD", "flag": "🇦🇺"},
    "加拿大元": {"code": "CAD", "flag": "🇨🇦"},
    "瑞士法郎": {"code": "CHF", "flag": "🇨🇭"},
    "新加坡元": {"code": "SGD", "flag": "🇸🇬"},
}
CURRENCY_UI_MAP = {
    currency: f"{meta['flag']} {meta['code']}/CNY"
    for currency, meta in CURRENCY_META.items()
    if currency != "人民币"
}
# ====================================================

# 全局列表，存储所有悬浮窗实例以计算磁吸
app_instances = []
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

def currency_code(currency):
    return CURRENCY_META.get(currency, {"code": currency})["code"]

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
            CREATE INDEX IF NOT EXISTS idx_external_rate_history_pair_date
            ON external_rate_history (base_currency, quote_currency, rate_date)
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
            """
            INSERT OR REPLACE INTO app_settings (key, value)
            VALUES (?, ?)
            """,
            [
                ("base_currency", base_currency),
                ("quote_currency", quote_currency),
            ]
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
            (time.time(), base_currency, quote_currency, price)
        )
        conn.execute("DELETE FROM rate_history WHERE timestamp < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()

def load_history_points(base_currency, quote_currency, range_seconds, max_points=240):
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
            (base_currency, quote_currency, cutoff)
        ).fetchall()
    finally:
        conn.close()

    if len(rows) <= max_points:
        return rows

    step = len(rows) / max_points
    sampled = [rows[int(index * step)] for index in range(max_points)]
    if sampled[-1] != rows[-1]:
        sampled[-1] = rows[-1]
    return sampled

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
            [
                (rate_date, base_currency, quote_currency, price, time.time())
                for rate_date, price in rows
            ]
        )
        conn.commit()
    finally:
        conn.close()

def load_external_history_points(base_currency, quote_currency, start_date, end_date, max_points=240):
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
            (base_currency, quote_currency, start_date.isoformat(), end_date.isoformat())
        ).fetchall()
    finally:
        conn.close()

    points = [
        (datetime.strptime(rate_date, "%Y-%m-%d").timestamp(), price)
        for rate_date, price in rows
    ]
    return sample_points(points, max_points)

def sample_points(points, max_points):
    if len(points) <= max_points:
        return points

    step = len(points) / max_points
    sampled = [points[int(index * step)] for index in range(max_points)]
    if sampled[-1] != points[-1]:
        sampled[-1] = points[-1]
    return sampled

def fetch_external_history_points(base_currency, quote_currency, range_seconds, session, max_points=240):
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
        params={
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
            "base": base_code,
            "quotes": quote_code,
        },
        timeout=10
    )
    response.raise_for_status()
    payload = response.json()
    rows = [
        (item["date"], float(item["rate"]))
        for item in payload
        if item.get("quote") == quote_code and item.get("rate") is not None
    ]
    save_external_history_points(base_currency, quote_currency, rows)
    return load_external_history_points(base_currency, quote_currency, start_date, end_date, max_points)

def format_pair_title(base_currency, quote_currency):
    base = CURRENCY_META.get(base_currency, {"code": base_currency, "flag": "💱"})
    quote = CURRENCY_META.get(quote_currency, {"code": quote_currency, "flag": ""})
    return f"{base['flag']} {base['code']}/{quote['code']}"

def short_currency_code(currency):
    return currency_code(currency)[:2]

def send_system_notification(title, message):
    """独立线程发送系统通知，避免阻塞 UI"""
    def _notify():
        try:
            notification.notify(title=title, message=message, app_name="汇率极客监控", timeout=5)
        except Exception as e:
            pass # 忽略部分系统禁用了通知权限导致的报错
    threading.Thread(target=_notify, daemon=True).start()

class FloatWindow:
    def __init__(self, master, initial_base_currency="英镑", initial_quote_currency="人民币", initial_y_offset=0):
        self.master = master
        self.base_currency = initial_base_currency
        self.quote_currency = initial_quote_currency
        self.chart_range_label = "30min"
        self.chart_range_seconds = 30 * 60
        
        self.target_price = 0.0 
        self.fluctuation_threshold_ratio = 0.005
        
        self.window = tk.Toplevel(master)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.88)
        self.window.configure(bg='#111827')
        
        self.win_width = 240
        self.win_height = 128
        self.chart_width = 212
        self.chart_height = 36
        self.max_history_points = 120
        self.window.geometry(f"{self.win_width}x{self.win_height}+100+{100 + initial_y_offset}")

        # UI 元素布局
        self.display_title = format_pair_title(self.base_currency, self.quote_currency)
        self.outer_frame = tk.Frame(self.window, bg="#dfe6e9", bd=1)
        self.outer_frame.pack(fill="both", expand=True)

        self.content_frame = tk.Frame(self.outer_frame, bg="#18202b")
        self.content_frame.pack(fill="both", expand=True, padx=1, pady=1)

        self.header_frame = tk.Frame(self.content_frame, bg="#18202b")
        self.header_frame.pack(fill="x", padx=12, pady=(10, 0))

        self.badge_label = tk.Label(
            self.header_frame,
            text=short_currency_code(self.base_currency),
            font=("Segoe UI", 7, "bold"),
            fg="#f5f6fa",
            bg="#263343",
            padx=5,
            pady=1
        )
        self.badge_label.pack(side="left")

        self.title_label = tk.Label(
            self.header_frame,
            text=self.display_title,
            font=('Segoe UI', 9, 'bold'),
            fg='#f5f6fa',
            bg='#18202b'
        )
        self.title_label.pack(side="left", padx=(6, 0))

        self.time_label = tk.Label(
            self.header_frame,
            text="",
            font=('Consolas', 8),
            fg="#f1c40f",
            bg="#18202b"
        )
        self.time_label.pack(side="right")

        self.value_frame = tk.Frame(self.content_frame, bg="#18202b")
        self.value_frame.pack(fill="x", padx=12, pady=(8, 0))
        
        self.price_label = tk.Label(
            self.value_frame,
            text="- Loading...",
            font=('Consolas', 22, 'bold'),
            fg='white',
            bg='#18202b'
        )
        self.price_label.pack(side="left")

        self.change_label = tk.Label(
            self.value_frame,
            text="--",
            font=('Segoe UI', 8, 'bold'),
            fg="#dcdde1",
            bg="#263343",
            padx=6,
            pady=2
        )
        self.change_label.pack(side="right", pady=(8, 0))

        self.chart_canvas = tk.Canvas(
            self.content_frame,
            width=self.chart_width,
            height=self.chart_height,
            bg='#18202b',
            highlightthickness=0
        )
        self.chart_canvas.pack(padx=12, pady=(5, 8))
        
        self.previous_price = None
        self.price_history = []
        self.chart_message = f"No data {self.chart_range_label}"
        self.chart_load_token = 0
        self.last_update_time = "" # 保存银行数据的具体发布时间
        self.target_alert_triggered = False
        self.is_closing = False
        self.start_x = None
        self.start_y = None
        self.start_window_x = None
        self.start_window_y = None

        # ====== 核心网络优化：建立持久化长连接 Session ======
        self.http_session = requests.Session()
        self.http_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.boc.cn/sourcedb/whpj/",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "keep-alive"
        })

        self.build_context_menu()

        # 绑定鼠标拖拽与点击事件
        self.bind_window_events(self.window)
        self.bind_window_events(self.outer_frame)
        self.bind_window_events(self.content_frame)
        self.bind_window_events(self.header_frame)
        self.bind_window_events(self.badge_label)
        self.bind_window_events(self.title_label)
        self.bind_window_events(self.time_label)
        self.bind_window_events(self.value_frame)
        self.bind_window_events(self.price_label)
        self.bind_window_events(self.change_label)
        self.bind_window_events(self.chart_canvas)
        
        # 绑定鼠标悬停事件 (用于显示更新时间)
        self.window.bind("<Enter>", self.on_hover_enter)
        self.window.bind("<Leave>", self.on_hover_leave)

        self.refresh_chart_history(force_external=True)
        self.update_data_loop()

    def bind_window_events(self, widget):
        widget.bind("<ButtonPress-1>", self.start_move)
        widget.bind("<ButtonRelease-1>", self.stop_move)
        widget.bind("<B1-Motion>", self.do_move)
        widget.bind("<Button-3>", self.show_menu)

    # --- 鼠标悬停感知逻辑 ---
    def on_hover_enter(self, event):
        """鼠标放上去时，显示中行最新发布时间"""
        if self.last_update_time:
            self.time_label.config(text=self.last_update_time)

    def on_hover_leave(self, event):
        """鼠标移开时，隐藏更新时间"""
        x = self.window.winfo_pointerx()
        y = self.window.winfo_pointery()
        left = self.window.winfo_rootx()
        top = self.window.winfo_rooty()
        right = left + self.win_width
        bottom = top + self.win_height
        if left <= x <= right and top <= y <= bottom:
            return
        self.time_label.config(text="")

    def build_context_menu(self):
        self.context_menu = None
        self.context_menu_x = 0
        self.context_menu_y = 0

    def show_menu(self, event):
        self.context_menu_x = event.x_root
        self.context_menu_y = event.y_root
        self.show_custom_menu(
            [
                ("💱 选择基准货币  ▶", self.show_base_currency_menu),
                ("💴 选择报价货币  ▶", self.show_quote_currency_menu),
                ("📈 线图范围      ▶", self.show_chart_range_menu),
                None,
                ("🎯 设定目标提醒价", self.set_target_price),
                None,
                ("➕ 新增监控浮窗", self.create_new_window),
                ("❌ 关闭当前浮窗", self.request_close_window),
            ],
            event.x_root,
            event.y_root
        )

    def show_base_currency_menu(self):
        items = [("← 返回", lambda: self.show_menu_at_last_position()), None]
        items.extend((currency, lambda c=currency: self.change_base_currency(c)) for currency in CURRENCY_META.keys())
        self.show_custom_menu(items, self.context_menu_x, self.context_menu_y)

    def show_quote_currency_menu(self):
        items = [("← 返回", lambda: self.show_menu_at_last_position()), None]
        items.extend((currency, lambda c=currency: self.change_quote_currency(c)) for currency in CURRENCY_META.keys())
        self.show_custom_menu(items, self.context_menu_x, self.context_menu_y)

    def show_chart_range_menu(self):
        items = [("← 返回", lambda: self.show_menu_at_last_position()), None]
        items.extend((label, lambda l=label, s=seconds: self.change_chart_range(l, s)) for label, seconds in CHART_RANGE_OPTIONS)
        self.show_custom_menu(items, self.context_menu_x, self.context_menu_y)

    def show_menu_at_last_position(self):
        class MenuEvent:
            pass
        event = MenuEvent()
        event.x_root = self.context_menu_x
        event.y_root = self.context_menu_y
        self.show_menu(event)

    def show_custom_menu(self, items, x, y):
        self.destroy_context_menu()
        menu = tk.Toplevel(self.window)
        self.context_menu = menu
        menu.overrideredirect(True)
        menu.attributes("-topmost", True)
        menu.attributes("-alpha", 0.94)
        menu.configure(bg="#dfe6e9")

        frame = tk.Frame(menu, bg="#18202b", bd=0)
        frame.pack(fill="both", expand=True, padx=1, pady=1)

        for item in items:
            if item is None:
                tk.Frame(frame, height=1, bg="#718093").pack(fill="x", padx=1, pady=2)
                continue
            label, command = item
            row = tk.Label(
                frame,
                text=label,
                font=("Segoe UI", 9),
                fg="white",
                bg="#18202b",
                anchor="w",
                padx=10,
                pady=5,
                width=18
            )
            row.pack(fill="x")
            row.bind("<Enter>", lambda event, widget=row: widget.config(bg="#00a8ff"))
            row.bind("<Leave>", lambda event, widget=row: widget.config(bg="#18202b"))
            row.bind("<ButtonRelease-1>", lambda event, cmd=command: self.run_menu_command(cmd))

        menu.update_idletasks()
        menu_width = menu.winfo_width()
        menu_height = menu.winfo_height()
        screen_width = menu.winfo_screenwidth()
        screen_height = menu.winfo_screenheight()
        x = min(x, screen_width - menu_width)
        y = min(y, screen_height - menu_height)
        menu.geometry(f"+{max(0, x)}+{max(0, y)}")
        menu.focus_force()
        menu.bind("<FocusOut>", lambda event: self.destroy_context_menu())
        menu.bind("<Escape>", lambda event: self.destroy_context_menu())

    def run_menu_command(self, command):
        self.destroy_context_menu()
        command()

    def destroy_context_menu(self):
        if self.context_menu is None:
            return
        try:
            self.context_menu.destroy()
        except tk.TclError:
            pass
        self.context_menu = None

    def reset_pair_state(self):
        self.update_pair_header()
        self.price_label.config(text="- Loading...", fg='white')
        self.change_label.config(text="--", fg="#dcdde1", bg="#263343")
        self.previous_price = None
        self.refresh_chart_history(force_external=True)
        self.last_update_time = ""
        self.target_price = 0.0
        self.target_alert_triggered = False
        threading.Thread(target=self._thread_fetch, daemon=True).start()

    def update_pair_header(self):
        self.display_title = format_pair_title(self.base_currency, self.quote_currency)
        self.title_label.config(text=self.display_title, fg="#f5f6fa")
        self.badge_label.config(text=short_currency_code(self.base_currency))

    def change_base_currency(self, new_currency):
        self.base_currency = new_currency
        save_last_currency_pair(self.base_currency, self.quote_currency)
        self.reset_pair_state()

    def change_quote_currency(self, new_currency):
        self.quote_currency = new_currency
        save_last_currency_pair(self.base_currency, self.quote_currency)
        self.reset_pair_state()

    def change_chart_range(self, label, seconds):
        self.chart_range_label = label
        self.chart_range_seconds = seconds
        self.refresh_chart_history(force_external=True)

    def set_target_price(self):
        pair_title = format_pair_title(self.base_currency, self.quote_currency)
        new_target = simpledialog.askfloat("设定目标价", f"请输入 {pair_title} 的目标汇率:\n(跌至该值时触发系统通知)", parent=self.window, minvalue=0.0)
        if new_target is not None:
            self.target_price = new_target
            self.target_alert_triggered = False

    def create_new_window(self):
        y_offset = len(app_instances) * (self.win_height + 8)
        new_app = FloatWindow(self.master, initial_base_currency="美元", initial_quote_currency="人民币", initial_y_offset=y_offset)
        app_instances.append(new_app)

    def request_close_window(self):
        if self.is_closing:
            return
        self.is_closing = True
        save_last_currency_pair(self.base_currency, self.quote_currency)
        self.destroy_context_menu()
        self.finish_close_window()

    def finish_close_window(self):
        if not self.window.winfo_exists():
            return
        self.window.withdraw()
        self.master.update()
        self.window.destroy()
        if self in app_instances:
            app_instances.remove(self)
        if not app_instances:
            self.master.quit()

    # --- 鼠标拖拽、磁吸与屏幕边缘防越界逻辑 ---
    def start_move(self, event):
        self.start_x = event.x_root
        self.start_y = event.y_root
        self.start_window_x = self.window.winfo_x()
        self.start_window_y = self.window.winfo_y()

    def stop_move(self, event):
        self.start_x = None
        self.start_y = None
        self.start_window_x = None
        self.start_window_y = None

    def do_move(self, event):
        if self.start_x is not None and self.start_y is not None:
            deltax = event.x_root - self.start_x
            deltay = event.y_root - self.start_y
            new_x = self.start_window_x + deltax
            new_y = self.start_window_y + deltay
            
            snap_dist = 15 
            
            # 1. 计算悬浮窗之间的磁吸
            for other_app in app_instances:
                if other_app == self: 
                    continue
                ox = other_app.window.winfo_x()
                oy = other_app.window.winfo_y()
                
                if abs(new_x + self.win_width - ox) < snap_dist: new_x = ox - self.win_width
                elif abs(new_x - (ox + self.win_width)) < snap_dist: new_x = ox + self.win_width
                elif abs(new_x - ox) < snap_dist: new_x = ox
                    
                if abs(new_y + self.win_height - oy) < snap_dist: new_y = oy - self.win_height
                elif abs(new_y - (oy + self.win_height)) < snap_dist: new_y = oy + self.win_height
                elif abs(new_y - oy) < snap_dist: new_y = oy

            # 2. 屏幕边缘防越界检测
            screen_width = self.window.winfo_screenwidth()
            screen_height = self.window.winfo_screenheight()

            if new_x < 0: new_x = 0
            elif new_x + self.win_width > screen_width: new_x = screen_width - self.win_width

            if new_y < 0: new_y = 0
            elif new_y + self.win_height > screen_height: new_y = screen_height - self.win_height

            self.window.geometry(f"+{new_x}+{new_y}")

    # --- 数据抓取与 UI 更新逻辑 ---
    def fetch_boc_rates(self):
        timestamp = int(time.time() * 1000)
        url = f"https://www.boc.cn/sourcedb/whpj/index.html?_t={timestamp}"
        try:
            # 使用建立好的长连接 Session，大幅提升抓取速度
            response = self.http_session.get(url, timeout=5)
            response.encoding = 'utf-8' 
            soup = BeautifulSoup(response.text, 'html.parser')
            rates = {"人民币": (1.0, "")}
            for tr in soup.find_all('tr'):
                tds = tr.find_all('td')
                if len(tds) >= 8:
                    currency_name = tds[0].text.strip()
                    if currency_name in CURRENCY_UI_MAP:
                        try:
                            sell_rate = float(tds[3].text.strip()) / 100
                        except ValueError:
                            continue
                        update_time = tds[7].text.strip() # 提取第八列：发布时间
                        rates[currency_name] = (sell_rate, update_time)
            return rates
        except Exception:
            return None

    def fetch_pair_rate(self):
        rates = self.fetch_boc_rates()
        if not rates:
            return None, None

        base_rate_data = rates.get(self.base_currency)
        quote_rate_data = rates.get(self.quote_currency)
        if not base_rate_data or not quote_rate_data:
            return None, None

        base_rate, base_update_time = base_rate_data
        quote_rate, quote_update_time = quote_rate_data
        if quote_rate == 0:
            return None, None

        update_times = [t for t in (base_update_time, quote_update_time) if t]
        update_time = " / ".join(dict.fromkeys(update_times)) or "CNY"
        return base_rate / quote_rate, update_time

    def update_ui(self, result):
        new_price, update_time = result
        if new_price is None:
            self.price_label.config(text="Net Error", fg='#ff4757')
            self.change_label.config(text="--", fg="#ff4757", bg="#3d2228")
            return

        self.last_update_time = update_time
        price_text = f"{new_price:.4f}"
        arrow = "-"
        color = 'white'
        change_text = "--"
        change_fg = "#dcdde1"
        change_bg = "#263343"
        pair_title = format_pair_title(self.base_currency, self.quote_currency)
        
        # 涨跌箭头与变色逻辑
        if self.previous_price is not None:
            price_diff = new_price - self.previous_price
            abs_diff = abs(price_diff)
            change_pct = price_diff / self.previous_price * 100 if self.previous_price else 0
            change_text = f"{change_pct:+.2f}%"
            
            if new_price > self.previous_price:
                arrow = "↑"
                color = '#ff4757'
                change_fg = "#ff4b55"
                change_bg = "#3d2228"
                if self.previous_price and abs_diff / self.previous_price >= self.fluctuation_threshold_ratio:
                    send_system_notification(f"📈 {pair_title} 上涨", f"现价: {price_text} (发自 {update_time})")
            elif new_price < self.previous_price:
                arrow = "↓"
                color = '#2ed573'
                change_fg = "#2ed573"
                change_bg = "#1f3a2e"
                if self.previous_price and abs_diff / self.previous_price >= self.fluctuation_threshold_ratio:
                    send_system_notification(f"📉 {pair_title} 下跌", f"现价: {price_text} (发自 {update_time})")
        
        self.price_label.config(text=f"{arrow} {price_text}", fg=color)
        self.change_label.config(text=change_text, fg=change_fg, bg=change_bg)
        self.record_price(new_price)
        self.refresh_chart_history(force_external=False)
        self.previous_price = new_price

        # 目标价强提醒逻辑
        if self.target_price > 0 and new_price <= self.target_price:
            if not self.target_alert_triggered:
                send_system_notification(f"🚨 {pair_title} 达标提醒", f"已跌破 {self.target_price}！\n当前最新价: {price_text}")
                self.target_alert_triggered = True
        elif new_price > self.target_price:
            self.target_alert_triggered = False

    def _thread_fetch(self):
        result = self.fetch_pair_rate()
        self.window.after(0, self.update_ui, result)

    def record_price(self, price):
        save_history_point(self.base_currency, self.quote_currency, price)

    def refresh_chart_history(self, force_external=False):
        if uses_external_history(self.chart_range_seconds):
            if force_external:
                self.load_external_chart_history_async()
            return

        self.chart_load_token += 1
        self.chart_message = f"No data {self.chart_range_label}"
        self.price_history = load_history_points(
            self.base_currency,
            self.quote_currency,
            self.chart_range_seconds,
            self.max_history_points
        )
        self.draw_chart()

    def load_external_chart_history_async(self):
        self.chart_load_token += 1
        token = self.chart_load_token
        base_currency = self.base_currency
        quote_currency = self.quote_currency
        range_seconds = self.chart_range_seconds
        range_label = self.chart_range_label
        self.price_history = []
        self.chart_message = f"Loading {range_label}"
        self.draw_chart()
        threading.Thread(
            target=self._thread_load_external_chart_history,
            args=(token, base_currency, quote_currency, range_seconds, range_label),
            daemon=True
        ).start()

    def _thread_load_external_chart_history(self, token, base_currency, quote_currency, range_seconds, range_label):
        try:
            points = fetch_external_history_points(
                base_currency,
                quote_currency,
                range_seconds,
                self.http_session,
                self.max_history_points
            )
            message = f"No data {range_label}"
        except Exception:
            points = []
            message = "History error"

        self.window.after(0, self.apply_external_chart_history, token, points, message)

    def apply_external_chart_history(self, token, points, message):
        if token != self.chart_load_token:
            return
        self.price_history = points
        self.chart_message = message
        self.draw_chart()

    def draw_chart(self):
        self.chart_canvas.delete("all")

        width = self.chart_width
        height = self.chart_height
        pad_x = 5
        pad_y = 4
        baseline_y = height - pad_y
        self.chart_canvas.create_line(pad_x, baseline_y, width - pad_x, baseline_y, fill='#263343')

        if not self.price_history:
            self.chart_canvas.create_text(width / 2, height / 2, text=self.chart_message, fill='#485460', font=('Segoe UI', 7))
            return

        prices = [price for _, price in self.price_history]
        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price

        if len(prices) == 1 or price_range == 0:
            y = height / 2
            self.chart_canvas.create_line(pad_x, y, width - pad_x, y, fill='#00a8ff', width=2)
            return

        points = []
        usable_width = width - pad_x * 2
        usable_height = height - pad_y * 2
        last_index = len(prices) - 1

        for index, price in enumerate(prices):
            x = pad_x + usable_width * index / last_index
            y = pad_y + usable_height * (max_price - price) / price_range
            points.extend((x, y))

        line_color = '#ff4757' if prices[-1] >= prices[0] else '#2ed573'
        glow_color = '#4a252b' if prices[-1] >= prices[0] else '#1f3a2e'
        fill_points = points + [points[-2], baseline_y, points[0], baseline_y]
        self.chart_canvas.create_polygon(*fill_points, fill=glow_color, outline='', smooth=True)
        self.chart_canvas.create_line(*points, fill=line_color, width=2, smooth=True)
        self.chart_canvas.create_oval(points[-2] - 5, points[-1] - 5, points[-2] + 5, points[-1] + 5, fill=line_color, outline='', stipple='gray50')
        self.chart_canvas.create_oval(points[-2] - 2, points[-1] - 2, points[-2] + 2, points[-1] + 2, fill=line_color, outline=line_color)

    def update_data_loop(self):
        threading.Thread(target=self._thread_fetch, daemon=True).start()
        # 频率提升：20秒 到 45秒 之间的随机休眠，兼顾极限实时性与防封杀
        random_delay = random.randint(20000, 45000)
        self.window.after(random_delay, self.update_data_loop)

if __name__ == "__main__":
    init_history_db()
    initial_base_currency, initial_quote_currency = load_last_currency_pair()

    root = tk.Tk()
    root.withdraw() 
    
    app = FloatWindow(root, initial_base_currency=initial_base_currency, initial_quote_currency=initial_quote_currency, initial_y_offset=0)
    app_instances.append(app)

    root.mainloop()
