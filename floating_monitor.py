import tkinter as tk
from tkinter import simpledialog
import threading
import requests
import time
import random
from bs4 import BeautifulSoup
from plyer import notification

# ================= 货币 UI 映射字典 =================
CURRENCY_UI_MAP = {
    "英镑": "🇬🇧 GBP/CNY", "美元": "🇺🇸 USD/CNY", "欧元": "🇪🇺 EUR/CNY",
    "日元": "🇯🇵 JPY/CNY", "港币": "🇭🇰 HKD/CNY", "澳大利亚元": "🇦🇺 AUD/CNY",
    "加拿大元": "🇨🇦 CAD/CNY", "瑞士法郎": "🇨🇭 CHF/CNY", "新加坡元": "🇸🇬 SGD/CNY"
}
# ====================================================

# 全局列表，存储所有悬浮窗实例以计算磁吸
app_instances = []

def send_system_notification(title, message):
    def _notify():
        try:
            notification.notify(title=title, message=message, app_name="汇率极客监控", timeout=5)
        except Exception as e:
            print(f"通知发送失败: {e}")
    threading.Thread(target=_notify, daemon=True).start()

class FloatWindow:
    def __init__(self, master, initial_currency="英镑", initial_y_offset=0):
        self.master = master
        self.currency_name = initial_currency
        
        self.target_price = 0.0 
        self.fluctuation_threshold = 0.01
        
        self.window = tk.Toplevel(master)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.60)
        self.window.configure(bg='#1e272e')
        
        self.win_width = 160
        self.win_height = 70
        self.window.geometry(f"{self.win_width}x{self.win_height}+100+{100 + initial_y_offset}")

        # UI 元素布局
        display_title = CURRENCY_UI_MAP.get(self.currency_name, f"💱 {self.currency_name}/CNY")
        self.title_label = tk.Label(self.window, text=display_title, font=('Segoe UI', 9, 'bold'), fg='#808e9b', bg='#1e272e')
        self.title_label.pack(pady=(5, 0))
        
        self.price_label = tk.Label(self.window, text="- Loading...", font=('Segoe UI', 16, 'bold'), fg='white', bg='#1e272e')
        self.price_label.pack()
        
        self.previous_price = None
        self.target_alert_triggered = False
        self.start_x = None
        self.start_y = None

        self.build_context_menu()

        # 绑定鼠标事件
        self.window.bind("<ButtonPress-1>", self.start_move)
        self.window.bind("<ButtonRelease-1>", self.stop_move)
        self.window.bind("<B1-Motion>", self.do_move)
        self.window.bind("<Button-3>", self.show_menu)

        self.update_data_loop()

    def build_context_menu(self):
        self.context_menu = tk.Menu(self.window, tearoff=0, bg='#2f3640', fg='white', borderwidth=0, activebackground='#00a8ff')
        
        self.currency_menu = tk.Menu(self.context_menu, tearoff=0, bg='#2f3640', fg='white', borderwidth=0)
        for currency in CURRENCY_UI_MAP.keys():
            self.currency_menu.add_command(label=currency, command=lambda c=currency: self.change_currency(c))
        
        self.context_menu.add_cascade(label="💱 切换监控货币", menu=self.currency_menu)
        self.context_menu.add_separator()
        
        self.context_menu.add_command(label="🎯 设定目标提醒价", command=self.set_target_price)
        self.context_menu.add_separator()
        
        self.context_menu.add_command(label="➕ 新增一个监控浮窗", command=self.create_new_window)
        self.context_menu.add_command(label="❌ 关闭当前浮窗", command=self.close_window)

    def show_menu(self, event):
        self.context_menu.post(event.x_root, event.y_root)

    def change_currency(self, new_currency):
        self.currency_name = new_currency
        self.title_label.config(text=CURRENCY_UI_MAP.get(new_currency, f"💱 {new_currency}/CNY"))
        self.price_label.config(text="- Loading...", fg='white')
        self.previous_price = None
        self.target_alert_triggered = False
        threading.Thread(target=self._thread_fetch, daemon=True).start()

    def set_target_price(self):
        new_target = simpledialog.askfloat("设定目标价", f"请输入 {self.currency_name} 的目标买入价:\n(当汇率跌至或低于该值时，将触发系统通知)", parent=self.window, minvalue=0.0)
        if new_target is not None:
            self.target_price = new_target
            self.target_alert_triggered = False

    def create_new_window(self):
        y_offset = len(app_instances) * 75
        new_app = FloatWindow(self.master, initial_currency="美元", initial_y_offset=y_offset)
        app_instances.append(new_app)

    def close_window(self):
        self.window.destroy()
        if self in app_instances:
            app_instances.remove(self)
        if not app_instances:
            self.master.quit()

    # --- 鼠标拖拽与磁吸对齐逻辑 ---
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
            
            # 1. 计算窗口磁吸
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

            # ================= 仅新增：屏幕边缘防越界检测 =================
            screen_width = self.window.winfo_screenwidth()
            screen_height = self.window.winfo_screenheight()

            # 限制 X 坐标不出屏幕左右边界
            if new_x < 0:
                new_x = 0
            elif new_x + self.win_width > screen_width:
                new_x = screen_width - self.win_width

            # 限制 Y 坐标不出屏幕上下边界
            if new_y < 0:
                new_y = 0
            elif new_y + self.win_height > screen_height:
                new_y = screen_height - self.win_height
            # ==============================================================

            self.window.geometry(f"+{new_x}+{new_y}")

    # --- 数据抓取与 UI 更新逻辑 ---
    def fetch_boc_rate(self):
        timestamp = int(time.time() * 1000)
        url = f"https://www.boc.cn/sourcedb/whpj/index.html?_t={timestamp}"
        headers = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = 'utf-8' 
            soup = BeautifulSoup(response.text, 'html.parser')
            for tr in soup.find_all('tr'):
                tds = tr.find_all('td')
                if len(tds) > 6 and self.currency_name in tds[0].text:
                    sell_rate = float(tds[3].text.strip()) / 100
                    return sell_rate
            return None
        except Exception:
            return None

    def update_ui(self, new_price):
        if new_price is None:
            self.price_label.config(text="Net Error", fg='#ff4757')
            return

        price_text = f"{new_price:.4f}"
        arrow = "-"
        color = 'white'
        
        if self.previous_price is not None:
            price_diff = new_price - self.previous_price
            abs_diff = abs(price_diff)
            
            if new_price > self.previous_price:
                arrow = "↑"
                color = '#ff4757'
                if abs_diff >= self.fluctuation_threshold:
                    send_system_notification(f"📈 {self.currency_name} 汇率上涨", f"当前价格: {price_text}\n上涨幅度: +{abs_diff:.4f}")
            elif new_price < self.previous_price:
                arrow = "↓"
                color = '#2ed573'
                if abs_diff >= self.fluctuation_threshold:
                    send_system_notification(f"📉 {self.currency_name} 汇率下跌", f"当前价格: {price_text}\n下跌幅度: -{abs_diff:.4f}")
        
        self.price_label.config(text=f"{arrow} {price_text}", fg=color)
        self.previous_price = new_price

        if self.target_price > 0 and new_price <= self.target_price:
            if not self.target_alert_triggered:
                send_system_notification(f"🚨 {self.currency_name} 达标强提醒", f"现汇卖出价已达或低于预期目标价 {self.target_price}！\n当前最新价: {price_text}")
                self.target_alert_triggered = True
        elif new_price > self.target_price:
            self.target_alert_triggered = False

    def _thread_fetch(self):
        new_price = self.fetch_boc_rate()
        self.window.after(0, self.update_ui, new_price)

    def update_data_loop(self):
        threading.Thread(target=self._thread_fetch, daemon=True).start()
        random_delay = random.randint(60000, 120000)
        self.window.after(random_delay, self.update_data_loop)

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw() 
    
    app = FloatWindow(root, initial_currency="英镑", initial_y_offset=0)
    app_instances.append(app)

    root.mainloop()