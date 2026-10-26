###V0.0.8忽略 pygetwindow 的假异常。
###V0.0.7更换支持库，点击时不干扰鼠标
###V0.0.6多显示器（多屏）支持。
###V0.0.5新增外部调用方式。
###V0.0.3支持按照截图文件识别的方法点击按钮，禁用文字ocr(识别能力不足)。
# Win_Click_input.py

import win32api
import win32con
import os
import time
import subprocess
import cv2
import numpy as np
from PIL import ImageGrab
import pyautogui
import pygetwindow as gw
import psutil
import pyperclip

# ============================
# 配置 & 工具函数
# ============================

def wait_for_window(window_title, timeout=10):
    print(f"🔍 等待窗口: '{window_title}'")
    start = time.time()
    while time.time() - start < timeout:
        windows = gw.getWindowsWithTitle(window_title)
        if windows:
            win = windows[0]
            try:
                if win.isMinimized:
                    win.restore()
                win.activate()
            except gw.PyGetWindowException as e:
                # 忽略“错误码 0 - 操作成功完成”这种假异常
                if "Error code from Windows: 0" in str(e):
                    print("⚠️ 忽略 pygetwindow 的假异常（错误码 0）")
                else:
                    # 其他真实异常仍需抛出
                    raise
            time.sleep(0.5)
            print(f"✅ 找到窗口: {win.title}")
            return win
        time.sleep(0.5)
    raise TimeoutError(f"未在 {timeout} 秒内找到窗口 '{window_title}'")


def find_image_location_on_screen(image_path, timeout=5, confidence=0.8):
    if not os.path.exists(image_path):
        print(f"❌ 图像文件不存在: {image_path}")
        return None
    start = time.time()
    while time.time() - start < timeout:
        screen = ImageGrab.grab(all_screens=True)
        screen_path = "temp_screen.png"
        screen.save(screen_path)
        screen_img = cv2.imread(screen_path, 0)
        template = cv2.imread(image_path, 0)
        if screen_img is None or template is None:
            os.remove(screen_path)
            time.sleep(0.5)
            continue
        res = cv2.matchTemplate(screen_img, template, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= confidence)
        for pt in zip(*loc[::-1]):
            h, w = template.shape
            center = (pt[0] + w // 2, pt[1] + h // 2)
            os.remove(screen_path)
            return center
        time.sleep(0.5)
        os.remove(screen_path)
    return None

def click_without_mouse(x, y):
    """后台模拟点击：临时移动到坐标 → 点击 → 立即恢复"""
    old_pos = win32api.GetCursorPos()
    try:
        # 临时移动（持续不到1ms，用户几乎察觉不到）
        win32api.SetCursorPos((x, y))
        # 执行点击
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    finally:
        # 恢复原鼠标位置
        win32api.SetCursorPos(old_pos)


def click_image_on_screen(image_path, timeout=5, confidence=0.8, offset_x=0, offset_y=0):
    """点击图像（带偏移），返回是否成功"""
    pos = find_image_location_on_screen(image_path, timeout=timeout, confidence=confidence)
    if pos:
        x = pos[0] + offset_x
        y = pos[1] + offset_y
        click_without_mouse(x, y)
        time.sleep(0.05)
        print(f"✅ 点击按钮成功: {image_path} → ({x}, {y})")
        return True
    else:
        print(f"⚠️ 未找到图像: {image_path}")
        return False


def input_text(text, interval=0.05, press_enter=True):
    """输入文本（可选回车）"""
    pyautogui.write(str(text), interval=interval)
    if press_enter:
        pyautogui.press("enter")
    print(f"✅ 已输入文本: {text} (回车: {press_enter})")


# ============================
# 分步操作 API（新增核心）
# ============================

class AppController:
    """
    封装应用控制逻辑，支持启动 → 操作 → 关闭
    """
    def __init__(self, app_path=None, window_title="", startup_delay=2):
        self.app_path = app_path
        self.window_title = window_title
        self.proc = None
        self.window = None
        self._closed = False

        if app_path:
            self.start(startup_delay)

    def start(self, startup_delay=2):
        """启动应用并获取窗口"""
        if self.proc is not None:
            print("⚠️ 应用已启动，跳过重复启动")
            return
        if not os.path.exists(self.app_path):
            raise FileNotFoundError(f"程序不存在: {self.app_path}")
        print(f"🚀 启动应用: {self.app_path}")
        self.proc = subprocess.Popen([self.app_path])
        time.sleep(startup_delay)
        self.window = wait_for_window(self.window_title, timeout=10)

    def click(self, image_path, timeout=5, confidence=0.8, offset_x=0, offset_y=0):
        """点击图像按钮"""
        if self._closed:
            raise RuntimeError("应用已关闭，无法操作")
        return click_image_on_screen(image_path, timeout, confidence, offset_x, offset_y)

    def type_text(self, text, interval=0.05, press_enter=True):
        """输入文本"""
        if self._closed:
            raise RuntimeError("应用已关闭，无法操作")
        return input_text(text, interval, press_enter)

    def paste_text(self, text):  # ← 新增方法
        """通过剪贴板粘贴文本（更稳定，避免字符丢失）"""
        if self._closed:
            raise RuntimeError("应用已关闭，无法操作")
        if self.window:
            self.window.activate()
            time.sleep(0.1)
        pyperclip.copy(str(text))
        pyautogui.hotkey('ctrl', 'v')
        print(f"✅ 已粘贴文本: {text[:50]}{'...' if len(text) > 50 else ''}")

    def close(self):
        """安全关闭应用"""
        if self._closed:
            return
        print("CloseOperation: 正在关闭应用...")
        try:
            if self.proc and self.proc.poll() is None:
                parent = psutil.Process(self.proc.pid)
                for child in parent.children(recursive=True):
                    child.kill()
                parent.kill()
                self.proc.wait(timeout=3)
                print("✅ 进程已终止")
            else:
                # 备用：Alt+F4
                try:
                    win = wait_for_window(self.window_title, timeout=2)
                    win.activate()
                    time.sleep(0.3)
                    pyautogui.hotkey("alt", "f4")
                    print("✅ 已发送 Alt+F4")
                except:
                    pass
        except Exception as e:
            print(f"⚠️ 关闭时出错: {e}")
        finally:
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ============================
# 兼容旧接口（可选保留）
# ============================

def auto_sequence(
    app_path=None,
    window_title="",
    steps=None,
    screenshot=None,
    close_at_end=False,
    step_interval=1.0,
    **kwargs
):
    """
    【兼容旧用法】
    仍支持原有调用方式，但内部使用新分步逻辑
    """
    controller = AppController(app_path, window_title)
    try:
        if steps:
            for step in steps:
                step_type = step.get("type")
                value = step.get("value")
                if step_type == "image":
                    controller.click(
                        value,
                        timeout=step.get("timeout", 5),
                        confidence=step.get("confidence", 0.8),
                        offset_x=step.get("offset_x", 0),
                        offset_y=step.get("offset_y", 0)
                    )
                
                elif step_type == "input":
                    interval = step.get("interval", 0.05)
                    press_enter = step.get("enter", True)
                    input_text(str(value), interval=interval, press_enter=press_enter)
                    success = True

                elif step_type == "paste":  # 输入方式为paste 类型
                    press_enter = step.get("enter", True)
                    # 使用剪贴板粘贴
                    pyperclip.copy(str(value))
                    pyautogui.hotkey('ctrl', 'v')
                    if press_enter:
                        pyautogui.press("enter")
                    success = True
                    print(f"✅ 已粘贴文本: {value[:40]}{'...' if len(str(value)) > 40 else ''} (回车: {press_enter})")
                
                time.sleep(step_interval)

        if screenshot:
            os.makedirs("screenshots", exist_ok=True)
            ImageGrab.grab(all_screens=True).save(os.path.join("screenshots", screenshot))
            print(f"📸 截图已保存: {screenshot}")
    finally:
        if close_at_end:
            controller.close()

# ============================
# 全局简化 API（支持顶层调用）
# ============================

import atexit
import threading

class _SimpleAppController:
    def __init__(self):
        self._app = None
        self._lock = threading.Lock()  # 虽单线程，但留扩展余地

    def start(self, app_path, window_title, startup_delay=2):
        with self._lock:
            if self._app is not None:
                print("ℹ️ 应用已启动，跳过重复初始化")
                return
            self._app = AppController(app_path, window_title, startup_delay)
            # 注册自动关闭（仅注册一次）
            atexit.register(self._auto_close)

    def _auto_close(self):
        with self._lock:
            if self._app:
                print("CloseOperation: 程序退出，自动关闭应用...")
                self._app.close()
                self._app = None

    def click(self, *args, **kwargs):
        if self._app is None:
            raise RuntimeError("❌ 请先启动程序！")
        return self._app.click(*args, **kwargs)

    def paste_text(self, text):
        if self._app is None:
            raise RuntimeError("❌ 请先启动程序！")
        return self._app.paste_text(text)

    def type_text(self, *args, **kwargs):
        if self._app is None:
            raise RuntimeError("❌ 请先启动程序！")
        return self._app.type_text(*args, **kwargs)

    def close(self):
        """手动关闭（会取消自动关闭，避免重复）"""
        with self._lock:
            if self._app:
                atexit.unregister(self._auto_close)
                self._app.close()
                self._app = None


# 全局实例
_simple_controller = _SimpleAppController()

# 暴露给用户的顶层函数
start_app = _simple_controller.start
click = _simple_controller.click
type_text = _simple_controller.type_text
paste_text = _simple_controller.paste_text
close_app = _simple_controller.close

# ============================
# 直接运行方法
# ============================
if __name__ == "__main__":
    steps = [
        {"type": "image", "value": ".\\PortTools\\MinGW\\btn_png\\serialwin_top.png", "timeout": 5},
        {"type": "image", "value": ".\\PortTools\\MinGW\\btn_png\\com_btn.png", "timeout": 5},
        {"type": "image", "value": ".\\PortTools\\MinGW\\btn_png\\btserver.png", "timeout": 3},
        {"type": "image", "value": ".\\PortTools\\MinGW\\btn_png\\openport.png", "timeout": 3},
        {
            "type": "image",
            "value": ".\\PortTools\\MinGW\\btn_png\\data_draw_btn.png", #参考图，偏移坐标找到输入框
            "offset_x": 3,
            "offset_y": -73,
            "timeout": 3
        },
        {"type": "paste", "value": "LOG, LFFF1, 61, 22201170005, 128, 2064, 845, 2, 561, 1, 3, 53, 10", "enter": True},
        {"type": "image", "value": ".\\PortTools\\MinGW\\btn_png\\send_btn.png", "timeout": 3},
        {
            "type": "image", 
            "value": ".\\PortTools\\MinGW\\btn_png\\port_notopen.png",
            "offset_x": 0,
            "offset_y": 36,
            "timeout": 3
        },  
    ]

    auto_sequence(
        app_path=r".\\PortTools\\MinGW\\SerialTest.exe",
        window_title="SerialTest",
        steps=steps,
        screenshot="final_result.png",
        close_at_end=True,
        step_interval=0.2
    )


# ============================
# 外部调用运行方法
# ============================
# 使用方式（分步调用示例）
# 方式 1：使用 AppController 类（推荐）
'''
#外部脚本： my_automation_script.py

import Win_Click_input as wci
import time

# 启动程序（只调用一次）
wci.start_app(r"PortTools\\MinGW\\SerialTest.exe", "SerialTest")

# 分步骤操作
wci.click(r"PortTools\\MinGW\\btn_png\\serialwin_top.png") #串口工具置顶，防止遮挡
wci.click(r"PortTools\\MinGW\\btn_png\\com_btn.png")
time.sleep(0.5)
wci.click(r"PortTools\\MinGW\btn_png\\btserver.png")
time.sleep(0.5)
wci.click(r"PortTools\\MinGW\\btn_png\\openport.png")
time.sleep(1)

# 发送多条数据
for i in range(3):
    wci.click(r"PortTools\\MinGW\\btn_png\\data_draw_btn.png", offset_y=-73)
    time.sleep(0.5)         
    # 用 paste_text 发送完整数据
    num=i + 60
    depth_i=i + 2150
    current_i=i + 860
    wci.paste_text(f"LOG, LFFF1, {num}, 22201170005, 128, {depth_i}, {current_i}, 2, 561, 1, 3, 53, 10")
    time.sleep(0.5)
    wci.click(r"PortTools\\MinGW\\btn_png\\send_btn.png")
    time.sleep(0.3)     
    if wci.click(r"PortTools\\MinGW\\btn_png\\data_input_clean.png"): #输入框的x关闭按钮
        time.sleep(0.3) 
wci.close_app() # 手动关闭SerialTest程序，否则 Python 退出时自动关闭

'''
# ============================
