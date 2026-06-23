import tkinter as tk
from tkinter import simpledialog
import threading
import requests
import time
import random
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

def format_pair_title(base_currency, quote_currency):
    base = CURRENCY_META.get(base_currency, {"code": base_currency, "flag": "💱"})
    quote = CURRENCY_META.get(quote_currency, {"code": quote_currency, "flag": ""})
    return f"{base['flag']} {base['code']}/{quote['code']}"

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
        
        self.target_price = 0.0 
        self.fluctuation_threshold_ratio = 0.005
        
        self.window = tk.Toplevel(master)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.85)
        self.window.configure(bg='#1e272e')
        
        self.win_width = 160
        self.win_height = 70
        self.window.geometry(f"{self.win_width}x{self.win_height}+100+{100 + initial_y_offset}")

        # UI 元素布局
        self.display_title = format_pair_title(self.base_currency, self.quote_currency)
        self.title_label = tk.Label(self.window, text=self.display_title, font=('Segoe UI', 9, 'bold'), fg='#808e9b', bg='#1e272e')
        self.title_label.pack(pady=(5, 0))
        
        self.price_label = tk.Label(self.window, text="- Loading...", font=('Segoe UI', 16, 'bold'), fg='white', bg='#1e272e')
        self.price_label.pack()
        
        self.previous_price = None
        self.last_update_time = "" # 保存银行数据的具体发布时间
        self.target_alert_triggered = False
        self.start_x = None
        self.start_y = None

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
        self.window.bind("<ButtonPress-1>", self.start_move)
        self.window.bind("<ButtonRelease-1>", self.stop_move)
        self.window.bind("<B1-Motion>", self.do_move)
        self.window.bind("<Button-3>", self.show_menu)
        
        # 绑定鼠标悬停事件 (用于显示更新时间)
        self.window.bind("<Enter>", self.on_hover_enter)
        self.window.bind("<Leave>", self.on_hover_leave)

        self.update_data_loop()

    # --- 鼠标悬停感知逻辑 ---
    def on_hover_enter(self, event):
        """鼠标放上去时，显示中行最新发布时间"""
        if self.last_update_time:
            self.title_label.config(text=f"🕒 {self.last_update_time}", fg="#f1c40f")

    def on_hover_leave(self, event):
        """鼠标移开时，恢复显示货币名称"""
        self.title_label.config(text=self.display_title, fg="#808e9b")

    def build_context_menu(self):
        self.context_menu = tk.Menu(self.window, tearoff=0, bg='#2f3640', fg='white', borderwidth=0, activebackground='#00a8ff')
        
        self.base_currency_menu = tk.Menu(self.context_menu, tearoff=0, bg='#2f3640', fg='white', borderwidth=0)
        self.quote_currency_menu = tk.Menu(self.context_menu, tearoff=0, bg='#2f3640', fg='white', borderwidth=0)
        for currency in CURRENCY_META.keys():
            self.base_currency_menu.add_command(label=currency, command=lambda c=currency: self.change_base_currency(c))
            self.quote_currency_menu.add_command(label=currency, command=lambda c=currency: self.change_quote_currency(c))
        
        self.context_menu.add_cascade(label="💱 选择基准货币", menu=self.base_currency_menu)
        self.context_menu.add_cascade(label="💴 选择报价货币", menu=self.quote_currency_menu)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🎯 设定目标提醒价", command=self.set_target_price)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="➕ 新增监控浮窗", command=self.create_new_window)
        self.context_menu.add_command(label="❌ 关闭当前浮窗", command=self.close_window)

    def show_menu(self, event):
        self.context_menu.post(event.x_root, event.y_root)

    def reset_pair_state(self):
        self.display_title = format_pair_title(self.base_currency, self.quote_currency)
        self.title_label.config(text=self.display_title, fg="#808e9b")
        self.price_label.config(text="- Loading...", fg='white')
        self.previous_price = None
        self.last_update_time = ""
        self.target_price = 0.0
        self.target_alert_triggered = False
        threading.Thread(target=self._thread_fetch, daemon=True).start()

    def change_base_currency(self, new_currency):
        self.base_currency = new_currency
        self.reset_pair_state()

    def change_quote_currency(self, new_currency):
        self.quote_currency = new_currency
        self.reset_pair_state()

    def set_target_price(self):
        pair_title = format_pair_title(self.base_currency, self.quote_currency)
        new_target = simpledialog.askfloat("设定目标价", f"请输入 {pair_title} 的目标汇率:\n(跌至该值时触发系统通知)", parent=self.window, minvalue=0.0)
        if new_target is not None:
            self.target_price = new_target
            self.target_alert_triggered = False

    def create_new_window(self):
        y_offset = len(app_instances) * 75
        new_app = FloatWindow(self.master, initial_base_currency="美元", initial_quote_currency="人民币", initial_y_offset=y_offset)
        app_instances.append(new_app)

    def close_window(self):
        self.window.destroy()
        if self in app_instances:
            app_instances.remove(self)
        if not app_instances:
            self.master.quit()

    # --- 鼠标拖拽、磁吸与屏幕边缘防越界逻辑 ---
    def start_move(self, event):
        self.start_x = event.x
        self.start_y = event.y

    def stop_move(self, event):
        self.start_x = None
        self.start_y = None

    def do_move(self, event):
        if self.start_x is not None and self.start_y is not None:
            deltax = event.x - self.start_x
            deltay = event.y - self.start_y
            new_x = self.window.winfo_x() + deltax
            new_y = self.window.winfo_y() + deltay
            
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
            return

        self.last_update_time = update_time
        price_text = f"{new_price:.4f}"
        arrow = "-"
        color = 'white'
        pair_title = format_pair_title(self.base_currency, self.quote_currency)
        
        # 涨跌箭头与变色逻辑
        if self.previous_price is not None:
            price_diff = new_price - self.previous_price
            abs_diff = abs(price_diff)
            
            if new_price > self.previous_price:
                arrow = "↑"
                color = '#ff4757'
                if self.previous_price and abs_diff / self.previous_price >= self.fluctuation_threshold_ratio:
                    send_system_notification(f"📈 {pair_title} 上涨", f"现价: {price_text} (发自 {update_time})")
            elif new_price < self.previous_price:
                arrow = "↓"
                color = '#2ed573'
                if self.previous_price and abs_diff / self.previous_price >= self.fluctuation_threshold_ratio:
                    send_system_notification(f"📉 {pair_title} 下跌", f"现价: {price_text} (发自 {update_time})")
        
        self.price_label.config(text=f"{arrow} {price_text}", fg=color)
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

    def update_data_loop(self):
        threading.Thread(target=self._thread_fetch, daemon=True).start()
        # 频率提升：20秒 到 45秒 之间的随机休眠，兼顾极限实时性与防封杀
        random_delay = random.randint(20000, 45000)
        self.window.after(random_delay, self.update_data_loop)

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw() 
    
    app = FloatWindow(root, initial_base_currency="英镑", initial_quote_currency="人民币", initial_y_offset=0)
    app_instances.append(app)

    root.mainloop()
