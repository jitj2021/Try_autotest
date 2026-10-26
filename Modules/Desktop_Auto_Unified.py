# -*- coding: utf-8 -*-
"""
Desktop_Auto_Unified.py - 桌面自动化控制器
支持：pywinauto(UI控件树) / OpenCV(图像) / pyautogui(图像) / PaddleOCR(文字)
特性：OCR后台常驻 / 中文路径兼容 / 无干扰点击 / 容错日志 / HTML测试报告
"""
import os
import time
import cv2
import numpy as np
import pyautogui
import mss
import subprocess
import psutil
import pyperclip
import pygetwindow as gw
import win32api
import win32con
import atexit
import logging
import datetime
import re
from PIL import Image

# 解决 Windows 高 DPI 缩放导致截图不完整/坐标偏移的问题
import ctypes
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

import warnings  # 导入 warnings 模块
# 全局屏蔽 pywinauto 的 32位/64位不匹配警告
warnings.filterwarnings("ignore", message=".32-bit application should be automated using 32-bit Python.") # 全局屏蔽 pywinauto 的 32位/64位不匹配警告

# ================= 1. 依赖检查与导入 =================
import win32gui  # 用于获取前台窗口句柄
try:
    import uiautomation as auto
    UIAUTOMATION_AVAILABLE = True
except ImportError:
    UIAUTOMATION_AVAILABLE = False
    print("⚠️ 未安装 uiautomation，UIAutomation模式不可用。")

try:
    from pywinauto import Application, Desktop
    PYWINAUTO_AVAILABLE = True
except ImportError:
    PYWINAUTO_AVAILABLE = False
    print("⚠️ 未安装 pywinauto，UI控件树模式不可用。")

from Modules.Paddle_OCR_auto import OCRClickAssistant

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

# ================= 2. 全局日志管理器 =================
def setup_logger():
    """初始化日志系统：同时输出到控制台和文件"""
    log_dir=os.path.abspath(r'C:\\test\\data\\ESTEC\\logs') #ESTEC软件导出测试报告保存目录
    os.makedirs(log_dir, exist_ok=True)
    log_filename = os.path.join(log_dir, f"auto_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    
    logger = logging.getLogger("AutoTestLogger")
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        fh = logging.FileHandler(log_filename, encoding='utf-8')
        fh.setLevel(logging.INFO)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        logger.addHandler(fh)
        logger.addHandler(ch)
        
    return logger, log_filename

logger, LOG_FILE = setup_logger()


#### 计时工具
import functools
# import time
def profile_time(func):
    """函数耗时统计装饰器"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()

        logger.info(f"▶▶ [{func.__name__}] 开始")

        try:
            return func(*args, **kwargs)

        finally:
            elapsed = (time.perf_counter() - start) * 1000
            logger.info(
                f"◀◀ [{func.__name__}] 结束，耗时 {elapsed:.1f} ms"
            )

    return wrapper

# ================= 窗口前置 / 置顶（绕过 Windows 前台锁）=================
def _extract_hwnd(target):
    """从多种对象里抽出窗口句柄 hwnd。
    支持：int / pywinauto wrapper / uiautomation control / pygetwindow win / None。
    抽不到返回 None，由调用方决定回退。"""
    if target is None:
        return None
    if isinstance(target, int):
        return target
    for attr in ('handle', 'NativeWindowHandle', '_hWnd', 'hWnd'):
        try:
            h = getattr(target, attr, None)
        except Exception:
            # pywinauto WindowSpecification 在窗口已销毁时
            # 访问任何属性都会抛 ElementNotFoundError，必须兜住
            continue
        if isinstance(h, int) and h:
            return h
    return None

def bring_to_front(hwnd):
    """把指定 hwnd 的窗口"激活到前台"，绕过 Windows 前台锁。"""
    if not hwnd:
        return False
    try:
        # 0. 窗口不存在/不可见则放弃
        if not win32gui.IsWindow(hwnd):
            return False
            
        # 1. 最小化 → 还原（否则 SetForegroundWindow 对最小化窗口无效）
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        except Exception:
            pass

        # 2. 已经在前台，无需操作
        try:
            if win32gui.GetForegroundWindow() == hwnd:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                return True
        except Exception:
            pass
            
        # 3. 把当前线程输入挂接到"当前前台窗口"的线程，临时获得设置前台的资格
        attached = False
        fg_tid = cur_tid = 0
        try:
            fg_hwnd = win32gui.GetForegroundWindow()
            fg_tid = win32gui.GetWindowThreadProcessId(fg_hwnd)[0]
            cur_tid = win32api.GetCurrentThreadId()
            if fg_tid and fg_tid != cur_tid:
                attached = bool(win32api.AttachThreadInput(cur_tid, fg_tid, True))
        except Exception:
            attached = False
            
        try:
            # 4. 模拟按下 Alt（不释放）——经典技巧：让系统以为"用户正在交互"，从而放行 SetForegroundWindow
            try:
                win32api.keybd_event(0x12, 0, 0, 0)  # VK_MENU(Alt) down
            except Exception:
                pass
                
            # 5. 真正前置
            ok = False
            try:
                win32gui.SetForegroundWindow(hwnd)
                ok = True
            except Exception:
                pass
            try:
                win32gui.BringWindowToTop(hwnd)
            except Exception:
                pass
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            except Exception:
                pass
                
            # 6. 释放 Alt
            try:
                win32api.keybd_event(0x12, 0, win32con.KEYEVENTF_KEYUP, 0)
            except Exception:
                pass
        finally:
            # 7. 解除线程挂接
            if attached:
                try:
                    win32api.AttachThreadInput(cur_tid, fg_tid, False)
                except Exception:
                    pass
                    
        # 8. 校验
        try:
            return win32gui.GetForegroundWindow() == hwnd
        except Exception:
            return ok
    except Exception as e:
        logger.warning(f"⚠️ bring_to_front 异常: {e}")
        return False

def set_topmost(hwnd, on=True):
    """把窗口设为/取消"永久置顶"。"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    try:
        flag = win32con.HWND_TOPMOST if on else win32con.HWND_NOTOPMOST
        win32gui.SetWindowPos(
            hwnd, flag, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
        )
        return True
    except Exception as e:
        logger.warning(f"⚠️ set_topmost 异常: {e}")
        return False

# ================= 3. OCR 引擎单例管理器 =================
class _OCRManager:
    """PaddleOCR-json.exe 后台常驻，脚本结束自动清理"""
    _assistant = None
    _is_registered = False

    @classmethod
    def get_assistant(cls, config_file='config.ini'):
        """获取 OCR 助手单例，首次调用时初始化"""
        if cls._assistant is None:
            logger.info("🔄 [OCR] 首次初始化，启动后台 OCR 引擎...")
            cls._assistant = OCRClickAssistant(config_file=config_file)
            cls._assistant.screenshot_type = 'pc'
            cls._assistant.update_config('ColorFilter', 'enable_color_filter', 'False')
            if not cls._is_registered:
                atexit.register(cls.cleanup)
                cls._is_registered = True
        return cls._assistant

    @classmethod
    def cleanup(cls):
        """脚本退出时清理所有 PaddleOCR-json.exe 后台进程"""
        logger.info("🧹 [OCR] 清理后台进程...")
        count = 0
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] and 'PaddleOCR-json.exe' in proc.info['name']:
                    proc.kill()
                    count += 1
            except:
                pass
        logger.info(f"✅ 终止 {count} 个 OCR 进程")

# ================= 4. HTML 测试报告生成器 =================
from datetime import datetime as dt #使用别名防止名称污染
t1_suffix = dt.now().strftime("%Y%m%d_%H")

test_report_path=os.path.abspath(r'C:\\test\\data\\ESTEC\\test_report')+'\\'+f'{t1_suffix}' #ESTEC软件导出测试报告保存目录

class TestReport:
    """简易 HTML 测试报告：记录每步操作、状态、截图，最终生成 HTML 文件"""
    def __init__(self, report_dir=f"{test_report_path}", app_name="未知软件"):
        self.report_dir = report_dir
        self.app_name = app_name
        self.img_dir = os.path.join(report_dir, "images")
        os.makedirs(self.img_dir, exist_ok=True)
        self.steps = []
        self.step_counter = 0
        self.start_time = time.time()
        
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        self.report_filename = f"report_{self.app_name}_{timestamp}.html"

    def capture_and_record(self, action_desc, status, extra_info="", images=None):
        """记录一个测试步骤。
        """
        self.step_counter += 1
        # 如果没有传入自定义图片列表，则执行默认的单次截图
        if images is None:
            images = []
            img_name = f"step_{self.step_counter:03d}_{int(time.time())}.jpg"
            img_path = os.path.join(self.img_dir, img_name)
            try:
                with mss.mss() as sct:
                    img_bgra = np.array(sct.grab(sct.monitors[1])) 
                    img_bgr = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)
                    cv2.imencode('.jpg', img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(img_path)
                images.append(img_path)
            except Exception as e:
                logger.error(f"截图失败: {e}")
                
        self.steps.append({
            "id": self.step_counter, "action": action_desc, "status": status,
            "imgs": images, "info": extra_info,
            "time": datetime.datetime.now().strftime("%H:%M:%S")
        })
        return images

    def generate_html(self):
        """生成 HTML 报告文件"""
        duration = round(time.time() - self.start_time, 2)
        pass_count = sum(1 for s in self.steps if s['status'] == 'PASS')
        fail_count = sum(1 for s in self.steps if s['status'] == 'FAIL')
        html_path = os.path.join(self.report_dir, self.report_filename)
        report_title = f"🤖 {self.app_name} 自动化测试报告"
        
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{report_title}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background: #f4f7f6; }}
        .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .stats {{ display: flex; gap: 20px; margin-top: 10px; }}
        .stat-box {{ background: rgba(255,255,255,0.1); padding: 10px 15px; border-radius: 5px; }}
        table {{ width: 100%; border-collapse: collapse; background: white; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; vertical-align: middle; }}
        th {{ background: #34495e; color: white; }}
        tr.status-pass {{ background-color: #e8f5e9; }}
        tr.status-fail {{ background-color: #ffebee; }}
        img {{ max-width: 200px; max-height: 150px; border: 1px solid #ccc; cursor: pointer; transition: transform 0.2s; }}
        img:hover {{ transform: scale(1.05); border-color: #3498db; }}
        .img-label {{ font-weight: bold; color: #e74c3c; font-size: 0.9em; margin-bottom: 4px; display: block; }}
    </style>
</head>
<body>
    <div class="header">
        <h2>{report_title}</h2>
        <div class="stats">
            <div class="stat-box">⏱️ 耗时: {duration}s</div>
            <div class="stat-box">📝 总步骤: {len(self.steps)}</div>
            <div class="stat-box">✅ 成功: {pass_count}</div>
            <div class="stat-box">❌ 失败: {fail_count}</div>
            <div class="stat-box">📂 日志: {os.path.basename(LOG_FILE)}</div>
        </div>
    </div>
    <table>
        <thead>
            <tr>
                <th width="5%">序号</th>
                <th width="10%">时间</th>
                <th width="20%">操作</th>
                <th width="8%">结果</th>
                <th width="35%">备注</th>
                <th width="22%">截图对比 (点击放大)</th>
            </tr>
        </thead>
        <tbody>
"""
        for s in self.steps:
            cls = f"status-{s['status'].lower()}"
            imgs = s.get('imgs', [])
            img_tags = []
            
            for i, img_path in enumerate(imgs):
                if img_path and os.path.exists(img_path):
                    rel = os.path.relpath(img_path, self.report_dir).replace("\\", "/")
                    label = ""
                    if len(imgs) > 1:
                        label = '<span class="img-label">🎯 点击前 (红框标注)</span>' if i == 0 else '<span class="img-label">✨ 点击后 (实际效果)</span>'
                    tag = f'{label}<a href="{rel}" target="_blank"><img src="{rel}" /></a>'
                    img_tags.append(tag)
                    
            imgs_html = "".join(img_tags) if img_tags else "无"
            html += f"""
            <tr class="{cls}">
                <td>{s['id']}</td>
                <td>{s['time']}</td>
                <td>{s['action']}</td>
                <td>{s['status']}</td>
                <td>{s['info']}</td>
                <td>{imgs_html}</td>
            </tr>
            """
            
        html += """
        </tbody>
    </table>
</body>
</html>
"""
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"📊 报告已生成: {os.path.abspath(html_path)}")

# ================= 5. 统一桌面自动化控制器 =================
class UnifiedDesktopController:
    """统一桌面自动化控制器。
    查找范围说明：
    - pywinauto 模式：仅在目标窗口控件树内搜索，不受其他软件干扰
    - OCR/image/pyautogui 模式：全屏搜索，可能受遮挡或同名元素干扰
    - auto 模式：优先 pywinauto（窗口内），失败后降级 OCR（全屏）
    """
    def __init__(self, app_path=None, window_title="", ocr_config='config.ini', backend="uia", app_name=None):
        # 智能提取软件名称：app_name > app_path 文件名 > window_title > 未知软件
        if app_name:
            self.app_name = app_name
        elif app_path:
            self.app_name = os.path.splitext(os.path.basename(app_path))[0]
        elif window_title:
            # 连接模式(无 app_path)时，用窗口标题当软件名，避免显示"未知软件"
            # window_title 可能是 list，取第一个非空元素
            _t = window_title[0] if isinstance(window_title, list) else window_title
            self.app_name = str(_t).strip() or "未知软件"
        else:
            self.app_name = "未知软件"
            
        self.ocr = _OCRManager.get_assistant(config_file=ocr_config)
        self.app_path = app_path
        self.window_title = window_title
        self.backend = backend
        
        # 初始状态：没有关联任何进程
        # 底层使用了 subprocess.Popen 来启动外部程序后状态改变，连接已有进程时状态不变（None）
        self.proc = None 
        self.window = None       
        self.app_ui = None       
        self.main_window = None 
        self.auto_window = None   # 用于保存 uiautomation 的窗口对象
        self.screen_width, self.screen_height = pyautogui.size()
        # 初始化全局桌面对象，用于捕获独立弹出窗口
        self.desktop = Desktop(backend=self.backend) if PYWINAUTO_AVAILABLE else None
        self.original_main_window = None  # 用于保存主窗口，以便后续切回
        # 将 app_name 传入报告生成器
        self.report = TestReport(app_name=self.app_name)
        logger.info(f"✅ 控制器初始化完成 (屏幕: {self.screen_width}x{self.screen_height}, 目标: {self.app_name})")

    # ==================== 窗口与应用管理 ====================
    def start_app(self, startup_delay=2):
        """启动应用并连接窗口"""
        if self.proc:
            logger.info("⚠️ 应用已启动，跳过")
            return True
        if not os.path.exists(self.app_path):
            error_msg = f"\n❌ 错误：被测程序不存在，路径: -> {self.app_path}"
            self.report.capture_and_record("启动应用", "FAIL", "文件不存在")
            raise FileNotFoundError(error_msg)  # 抛出异常，强制打断后续所有测试代码
            
        logger.info(f"🚀 启动被测软件: {self.app_path}")
        self.proc = subprocess.Popen([self.app_path])
        logger.info(f"✅ PID: {self.proc.pid}，等待 {startup_delay}s...")
        time.sleep(startup_delay)
        
        try:
            self.window = self._wait_for_window(timeout=10)
            logger.info(f"✅ 找到窗口: {self.window.title}")
            # 连接 pywinauto（三级降级策略）
            if PYWINAUTO_AVAILABLE:
                self._connect_pywinauto()
            # 连接 uiautomation
            self._connect_uiautomation()
            # 保存最初的主窗口引用
            self.original_main_window = self.main_window 
            # 启动后把界面激活到前台
            self.focus_window()
            self.report.capture_and_record(f"启动 {os.path.basename(self.app_path)}", "PASS")
        except TimeoutError as e:
            logger.error(f"❌ {e}")
            self.report.capture_and_record("启动应用", "FAIL", str(e))
        except Exception as e:
            logger.error(f"❌ 启动异常: {e}")
            self.report.capture_and_record("启动应用", "FAIL", str(e))

    def _pick_best_hwnd_for_pid(self, pid, preferred_titles=None):
        """枚举 PID 的所有顶层窗口，用【打分法】挑出"主窗口"而非弹窗/对话框。
        解决：同 PID 下既有主窗口又有'关于...'等弹窗时，旧'可见有标题'策略按遍历顺序误选弹窗。
        打分信号（高→低权重）：
          标题命中提示(包含匹配) +2000  —— 用户给的主窗口标题白名单，精准锁定
          无 owner                +1000  —— 主窗口强信号；弹窗/对话框通常被主窗口 owned
          当前前台                +300
          可调整大小(WS_THICKFRAME)+100  —— 主窗口常有，对话框常无
          非对话框类(!=#32770)    +50
          可见                    +20
          有标题                  +10
          面积(连续,封顶200)      —— 主窗口通常更大，作 tie-breaker
        返回得分最高的 hwnd；枚举不到返回 None。"""
        if not self.desktop:
            return None
        try:
            wins = self.desktop.windows(process=pid)   # 列表 API，多个也不抛 ambiguous
        except Exception as e:
            logger.warning(f"⚠️ 枚举 PID={pid} 的顶层窗口失败: {e}")
            return None
            
        if not wins:
            logger.warning(f"⚠️ PID={pid} 未枚举到任何顶层窗口")
            return None
            
        preferred = preferred_titles if isinstance(preferred_titles, list) else ([preferred_titles] if preferred_titles else [])
        preferred = [p for p in preferred if p]
        fg = win32gui.GetForegroundWindow()
        
        def _safe(fn, default):
            try: 
                return fn()
                
            except Exception: 
                return default
            
        best_hwnd, best_score = None, -1
        logger.info(f"🔎 [PID={pid}] 共 {len(wins)} 个顶层窗口，打分挑选主窗口:")
        
        for w in wins:
            hwnd = w.handle
            title = _safe(w.window_text, "") or ""
            cls = _safe(w.class_name, "") or ""
            try:
                r = w.rectangle()
                visible = r.width() > 0 and r.height() > 0
                area = max(0, r.width()) * max(0, r.height())
            except Exception:
                visible, area = False, 0
                
            # owner：弹窗/对话框通常有 owner，主窗口通常没有
            try:
                owner = win32gui.GetWindow(hwnd, win32con.GW_OWNER)
            except Exception:
                owner = 0
            has_owner = bool(owner)
            
            # 样式：WS_THICKFRAME=0x00040000 表示可调整大小
            try:
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            except Exception:
                style = 0
            thickframe = bool(style & 0x00040000)
            is_dlg_class = (cls == '#32770')
            
            score = 0
            if preferred and any((p == title) or (p in title) for p in preferred):
                score += 2000
            if not has_owner: 
                score += 1000
            if hwnd == fg: 
                score += 300
            if thickframe: 
                score += 100
            if not is_dlg_class: 
                score += 50
            if visible: 
                score += 20
            if title.strip(): 
                score += 10
            score += min(area // 10000, 200)
            
            if score > best_score:
                best_score, best_hwnd = score, hwnd
                
        if best_hwnd is not None:
            logger.info(f"✅ [PID筛选] 选中 hwnd={best_hwnd} (score={best_score})")
        return best_hwnd

    def connect_existing(self, window_title=None, pid=None):
        """连接到已经打开的软件（不启动新进程）。
        :param window_title: 窗口标题（支持传入字符串或列表，多标题时按顺序优先级匹配）
        :param pid: 进程ID（优先级高于 window_title）
        """
        if not PYWINAUTO_AVAILABLE:
            logger.error("❌ pywinauto 未安装，无法连接现有窗口")
            return False
        try:
            if pid:
                logger.info(f"🔌 正在通过 PID={pid} 连接应用...")
                # 先枚举该 PID 的顶层窗口挑一个 hwnd，避免 connect(process=) 多窗口抛 ambiguous
                target_hwnd = self._pick_best_hwnd_for_pid(pid, preferred_titles=window_title)
                if target_hwnd:
                    # 用句柄精确连接：handle 唯一，绝不会再 ambiguous
                    self.app_ui = Application(backend=self.backend).connect(handle=target_hwnd, timeout=5)
                    self.main_window = self.app_ui.window(handle=target_hwnd)
                else:
                    # 枚举不到（极少见）才退回 process 连接；仅当该 PID 恰好单窗口时不抛
                    self.app_ui = Application(backend=self.backend).connect(process=pid, timeout=5)
                    self.main_window = self.app_ui.window()
                self.window_title = self.main_window.window_text()
                logger.info(f"✅ 通过 PID 连接成功: '{self.window_title}'")
                # 补上 uiautomation 连接（与标题分支对齐）
                self._connect_uiautomation()
            elif window_title:
                # 1. 统一转换为列表格式，兼容单字符串
                titles = window_title if isinstance(window_title, list) else [window_title]
                logger.info(f"🔍 正在通过标题 {titles} 查找并连接应用...")
                foreground_hwnd = win32gui.GetForegroundWindow()
                desktop = Desktop(backend=self.backend)
                
                # 2. 收集所有模糊匹配的窗口
                matched_windows = []
                for t in titles:
                    matched_windows.extend(desktop.windows(title_re=f".*{re.escape(t)}.*"))
                if not matched_windows:
                    raise TimeoutError(f"未找到标题包含 {titles} 的窗口")

                # ================= 四级智能筛选策略 =================
                target_win = None
                # 【策略 1】最高优先级：寻找标题【完全精确匹配】的窗口（按传入列表顺序）
                for title in titles:
                    for win in matched_windows:
                        real_title = win.window_text()
                        if real_title == title:
                            target_win = win
                            break
                    if target_win: 
                        break
                    
                # 【策略 2】次高优先级：选择当前处于【前台】的窗口
                if not target_win:
                    for win in matched_windows:
                        if win.handle == foreground_hwnd:
                            target_win = win
                            break
                            
                # 【策略 3】第三优先级：选择第一个【可见且有效】的窗口
                if not target_win:
                    for win in matched_windows:
                        try:
                            rect = win.rectangle()
                            if rect.width() > 0 and rect.height() > 0:
                                target_win = win
                                break
                        except: 
                            continue
                        
                # 【策略 4】终极兜底：盲选列表第一个
                if not target_win:
                    target_win = matched_windows[0]
                    
                # 3. 执行连接
                self.app_ui = Application(backend=self.backend).connect(handle=target_win.handle)
                self.main_window = target_win
                self.window_title = self.main_window.window_text()
                logger.info(f"✅ 最终连接成功: '{self.window_title}' (句柄: {target_win.handle})")
                # 连接 uiautomation
                self._connect_uiautomation()
            else:
                logger.error("⚠️ 必须提供 window_title 或 pid")
                return False
                
            # 保存主窗口引用，供 switch_to_main_window 切回
            self.original_main_window = self.main_window
            # 关联已有软件后，把界面激活到前台（关联≠到前台，必须显式前置）
            self.focus_window()
            # 若初始化时没拿到名字(仍为"未知软件")，用 connect 后的真实标题回填软件名 + 报告名
            if (not self.app_name) or self.app_name == "未知软件":
                real = self.window_title
                if isinstance(real, list): 
                    real = real[0] if real else ""
                if real:
                    self.app_name = real
                    self.report.app_name = real
                    ts = time.strftime('%Y%m%d_%H%M%S', time.localtime(self.report.start_time))
                    self.report.report_filename = f"report_{real}_{ts}.html"
                    
            self.report.capture_and_record(f"连接已有应用 '{self.window_title}'", "PASS")
            return True            
        except Exception as e:
            logger.error(f"❌ 连接已有应用失败: {e}")
            self.report.capture_and_record("连接已有应用", "FAIL", str(e))
            return False

    def connect(self, pid=None, window_title=None, startup_delay=2):
        """统一连接入口：智能判断是启动新应用还是连接已有应用。
        :param pid: 进程ID（优先级最高，用于连接已有应用）
        :param window_title: 窗口标题（用于连接已有应用，多个时优先前台）
        :param startup_delay: 启动新应用时的等待时间
        """
        if pid:
            return self.connect_existing(pid=pid, window_title=window_title), True
        # 如果指定了 window_title 且没有 app_path，则连接已有应用
        if window_title and not self.app_path:
            return self.connect_existing(window_title=window_title), True
        # 如果有 app_path，则启动新应用
        if self.app_path:
            return self.start_app(startup_delay=startup_delay), True
        logger.error("❌ 连接失败：未提供 app_path、pid 或 window_title")
        return False

    def _connect_pywinauto(self):
        """三级降级连接 pywinauto：句柄 → 精确标题 → 模糊标题"""
        hwnd = getattr(self.window, '_hWnd', None) or getattr(self.window, 'hWnd', None)
        
        # 第一级：句柄精确连接（最稳妥，无视同名窗口）
        if hwnd:
            try:
                self.app_ui = Application(backend=self.backend).connect(handle=hwnd, timeout=2)
                self.main_window = self.app_ui.window(handle=hwnd)
                logger.info(f"✅ pywinauto 句柄连接成功")
                return
            except Exception as e:
                logger.warning(f"⚠️ 句柄连接失败: {e}")
                
        # 第二级：精确标题匹配
        try:
            self.app_ui = Application(backend=self.backend).connect(title=self.window_title, timeout=3)
            self.main_window = self.app_ui.window(title=self.window_title)
            logger.info(f"✅ pywinauto 精确标题连接成功")
            return
        except Exception as e:
            logger.warning(f"⚠️ 精确标题连接失败: {e}")
            
        # 第三级：模糊匹配兜底
        try:
            _esc = re.escape(self.window_title) if isinstance(self.window_title, str) else re.escape(str(self.window_title))
            self.app_ui = Application(backend=self.backend).connect(title_re=f".*{_esc}.*", timeout=2)
            self.main_window = self.app_ui.window(title_re=f".*{_esc}.*")
            logger.info(f"✅ pywinauto 模糊匹配连接成功")
        except Exception as e:
            logger.warning(f"⚠️ pywinauto 全部连接方式失败: {e}")
            logger.warning(f"💡 尝试切换 backend（当前: {self.backend}）")
            self.main_window = None

    def _connect_uiautomation(self):
        """绑定 uiautomation 窗口对象。
        优先用已知 hwnd 经 ControlFromHandle 精确绑定——避免从桌面根按 Name 全局搜索。
        全局搜索既慢、又可能搜到同名窗口、还可能因某个顶层窗口不响应 UIA 而 hang 数十秒。"""
        if not UIAUTOMATION_AVAILABLE:
            return
        # 方式1（推荐）：已知 hwnd 直接绑定，O(1)，不遍历桌面，不会 hang
        hwnd = getattr(self.main_window, 'handle', None)
        if hwnd:
            try:
                t0 = time.time()
                ctrl = auto.ControlFromHandle(hwnd)
                if ctrl is not None:
                    self.auto_window = ctrl
                    logger.info(f"✅ uiautomation 通过 hwnd={hwnd} 绑定成功: '{ctrl.Name}' (耗时 {time.time()-t0:.2f}s)")
                    return
            except Exception as e:
                logger.warning(f"⚠️ ControlFromHandle({hwnd}) 失败，回退标题搜索: {e}")

        # 方式2（回退）：按标题从桌面搜（保留兼容，缩短超时并记录耗时）
        try:
            title = self.window_title
            if isinstance(title, list): 
                title = title[0] if title else ""
            if not title:
                logger.warning("⚠️ uiautomation 连接失败：无可用窗口标题")
                return
            t0 = time.time()
            self.auto_window = auto.WindowControl(Name=title, searchDepth=1)
            if self.auto_window.Exists(2, 0.5):
                logger.info(f"✅ uiautomation 标题搜索连接成功: '{self.auto_window.Name}' (耗时 {time.time()-t0:.2f}s)")
            else:
                logger.warning(f"⚠️ uiautomation 未找到标题为 '{title}' 的窗口，UIA模式将不可用")
                self.auto_window = None
        except Exception as e:
            logger.warning(f"⚠️ uiautomation 连接异常: {e}")
            self.auto_window = None

    def _wait_for_window(self, timeout=10):
        """等待窗口出现（支持传入多个标题，匹配到任意一个即返回）"""
        # 统一转换为列表格式，兼容传入单个字符串的情况
        titles = self.window_title if isinstance(self.window_title, list) else [self.window_title]
        start = time.time()
        while time.time() - start < timeout:
            for title in titles:
                windows = gw.getWindowsWithTitle(title)
                if windows:
                    win = windows[0]
                    # 将实际匹配到的准确标题记录下来，供后续 pywinauto 精确连接使用
                    self.window_title = win.title 
                    logger.info(f"✅ 匹配到窗口: '{self.window_title}'")
                    try:
                        if win.isMinimized: 
                            win.restore()
                        win.activate()
                    except gw.PyGetWindowException as e:
                        if "Error code from Windows: 0" not in str(e): 
                            raise
                    return win
            time.sleep(0.5)
        raise TimeoutError(f"未在 {timeout}s 内找到窗口 {titles}")

    def close_app(self):
        """安全关闭应用（如果是启动的则杀进程，如果是连接的则只断开控制）"""
        # 判断是否是我们自己启动的进程
        if self.proc and self.proc.poll() is None:
            logger.info(f"🛑 正在彻底关闭软件 (PID: {self.proc.pid})...")
            try:
                parent = psutil.Process(self.proc.pid)
                for child in parent.children(recursive=True): 
                    child.kill()
                parent.kill()
                time.sleep(1)
                self.report.capture_and_record("关闭被测软件", "PASS", "进程已终止")
            except Exception as e:
                logger.error(f"❌ 关闭软件失败: {e}")
        else:
            # 如果是通过 connect_existing 连接的，self.proc 为空，只断开 pywinauto 连接
            logger.info(f"🔌 仅断开自动化控制连接，保留原软件继续运行")
            
        # 清理内部对象
        self.proc = None
        self.app_ui = None
        self.main_window = None

    # ==================== 独立子窗口切换 ====================
    @profile_time
    def wait_for_popup(self, title_keyword, timeout=0.5):
        """等待独立的弹出窗口出现，并自动将操作焦点切换到该窗口。
        :param title_keyword: 弹出窗口的标题关键字（支持模糊匹配）
        :param timeout: 超时时间（秒）
        """
        if not PYWINAUTO_AVAILABLE or not self.desktop:
            logger.error("❌ pywinauto 不可用，无法等待弹出窗口")
            return False
        logger.info(f"⏳ 等待弹出窗口: '{title_keyword}' (超时 {timeout}s)...")
        start = time.time()
        while time.time() - start < timeout:
            try:
                # 在桌面级别模糊查找窗口（re.escape：弹窗标题含括号等元字符时不转义会找不到）
                popup = self.desktop.window(title_re=f".*{re.escape(title_keyword)}.*")
                # 验证窗口是否真实可见（排除隐藏或已销毁的句柄）
                rect = popup.rectangle()
                if rect.width() > 0 and rect.height() > 0:
                    self.main_window = popup  # 切换内部引用
                    self.focus_window(popup)  # 把弹窗激活到前台
                    actual_title = popup.window_text()
                    logger.info(f"✅ 捕获到弹出窗口: '{actual_title}'，已激活到前台")
                    self.report.capture_and_record(f"等待弹窗 '{title_keyword}'", "PASS", actual_title)
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        logger.error(f"❌ 超时未找到弹出窗口: '{title_keyword}'")
        self.report.capture_and_record(f"等待弹窗 '{title_keyword}'", "FAIL", "超时")
        return False

    def switch_to_main_window(self):
        """将操作焦点切回最初的主窗口，并真正激活到前台"""
        if self.original_main_window:
            self.main_window = self.original_main_window
            self.focus_window(self.original_main_window)
            logger.info(f"🔄 焦点已切回主窗口: '{self.window_title}'")
        else:
            logger.warning("⚠️ 没有保存的主窗口记录，无法切回")

    def focus_window(self, target=None, topmost=False):
        """把目标窗口激活到前台（默认操作 self.main_window）。
        :param target: 可传 hwnd(int) / pywinauto wrapper / uiautomation control / pygetwindow win / None。
                       None 时优先 self.main_window，再退 self.auto_window。
        :param topmost: 是否额外设为永久置顶（默认 False，一般不要开）。
        返回 True 表示成功到前台。"""
        if target is None:
            target = self.main_window or self.auto_window
        hwnd = _extract_hwnd(target)
        if not hwnd:
            logger.warning("⚠️ focus_window：拿不到窗口句柄，无法前置")
            return False
        ok = bring_to_front(hwnd)
        if topmost: 
            set_topmost(hwnd, True)
        logger.info(f"{'✅' if ok else '⚠️'} 窗口前置 hwnd={hwnd} -> {'成功' if ok else '失败'}")
        return ok

    def set_window_topmost(self, target=None, on=True):
        """对外暴露的"永久置顶/取消置顶"开关（副作用大，仅特殊场景用）。"""
        if target is None:
            target = self.main_window or self.auto_window
        return set_topmost(_extract_hwnd(target), on)

    # ==================== 底层截图与点击 ====================
    def _capture_screen_only(self):
        """仅截取当前全屏，返回图片路径（用于点击后截图）"""
        with mss.mss() as sct:
            sct_img = sct.grab(sct.monitors[1])
            img_bgra = np.array(sct_img)
            img_bgr = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)
            temp_path = os.path.join(self.report.img_dir, f"after_{int(time.time()*1000)}.jpg")
            cv2.imencode('.jpg', img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(temp_path)
            return temp_path

    def _capture_and_mark_click_area(self, x, y, box_size=40):
        """截取全屏，并在指定坐标 (x,y) 画红框标注，返回图片路径（用于点击前截图）"""
        with mss.mss() as sct:
            sct_img = sct.grab(sct.monitors[1])
            img_bgra = np.array(sct_img)
            img_bgr = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)
            # 计算红框的左上角和右下角（以点击点为中心）
            x1 = max(0, x - box_size // 2)
            y1 = max(0, y - box_size // 2)
            x2 = min(img_bgr.shape[1], x + box_size // 2)
            y2 = min(img_bgr.shape[0], y + box_size // 2)
            # 画红框 (BGR格式中，红色是 (0, 0, 255))，线宽为 2
            cv2.rectangle(img_bgr, (x1, y1), (x2, y2), (0, 0, 255), 2)
            temp_path = os.path.join(self.report.img_dir, f"before_{int(time.time()*1000)}.jpg")
            cv2.imencode('.jpg', img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(temp_path)
            return temp_path

    def _win32_click(self, x, y, double=False):
        """无干扰点击：瞬移→点击→恢复原位"""
        old_pos = win32api.GetCursorPos()
        try:
            win32api.SetCursorPos((x, y))
            if double:
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                time.sleep(0.05)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            else:
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        finally:
            win32api.SetCursorPos(old_pos)

    def _capture_screen(self):
        """全屏截图，返回 (BGR数组, 临时文件路径)"""
        with mss.mss() as sct:
            # 如果需要截取所有屏幕（包含副屏），将 monitors[1] 改为 monitors[0]
            sct_img = sct.grab(sct.monitors[1])
            # mss 在 Windows 返回 BGRA 格式，直接转换为 BGR
            img_bgra = np.array(sct_img)
            img_bgr = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)
            temp_path = os.path.join(self.report.img_dir, f"temp_{int(time.time()*1000)}.jpg")
            cv2.imencode('.jpg', img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(temp_path)
            return img_bgr, temp_path

    # ==================== 核心查找逻辑 ====================  
    @profile_time  
    def find_element(self, target=None, reference_text=None, mode='auto',
                     confidence=0.8, timeout=3, control_type=None, class_name=None,
                     color=True, pair_template=None):
        """查找元素坐标。
        :param target: 图片路径 或 文字字符串 或 控件标题
        :param reference_text: OCR参考文本（多目标时选最近的）
        :param mode: 'auto'/'image'/'ocr'/'pyautogui'/'pywinauto'/'uiautomation'
        :param confidence: 图像匹配置信度
        :param timeout: 超时秒数
        :param control_type: pywinauto控件类型（如 'Button','Edit','MenuItem'）
        :param class_name: pywinauto控件类名（如 Win10记事本输入框用 'Edit'）
        :param color: True=彩色匹配(BGR)，False=灰度匹配
        :param pair_template: 配对模板路径，用于差异遮罩区分成对图标
        """
        start = time.time()
        while time.time() - start < timeout:
            pos = None
            temp_path = None
            if mode == 'auto':
                if target and os.path.exists(target):
                    mode = 'image'
                else:
                    if PYWINAUTO_AVAILABLE and self.main_window:
                        pos = self._find_by_pywinauto(target, control_type, class_name)
                        if pos: return pos
                    if UIAUTOMATION_AVAILABLE and self.auto_window:
                        pos = self._find_by_uiautomation(target, control_type, class_name)
                        if pos: return pos
                    mode = 'ocr'
            try:
                if mode == 'image':
                    _, temp_path = self._capture_screen()
                    pos = self._find_by_image(target, confidence, color=color, pair_template=pair_template)
                elif mode == 'ocr':
                    _, temp_path = self._capture_screen()
                    pos = self._find_by_ocr(temp_path, target, reference_text)
                elif mode == 'pyautogui':
                    pos = self._find_by_pyautogui(target, confidence)
                elif mode == 'pywinauto':
                    pos = self._find_by_pywinauto(target, control_type, class_name)
                elif mode == 'uiautomation': 
                    pos = self._find_by_uiautomation(target, control_type, class_name)
                if pos: return pos
            finally:
                if temp_path and os.path.exists(temp_path):
                    try: os.remove(temp_path)
                    except: pass
            time.sleep(0.3)
        return None

    def _imread_unicode(self, path, flags):
        """中文路径安全读图"""
        return cv2.imdecode(np.fromfile(path, dtype=np.uint8), flags)

    def _log_top_peaks(self, res, k=5):
        """打印相关图里最高的 k 个峰，用于判断候选是否可区分"""
        if res.size == 0:
            return
        flat = res.flatten()
        k = min(k, flat.size)
        idx = np.argpartition(flat, -k)[-k:]
        idx = idx[np.argsort(flat[idx])[::-1]]
        cols = res.shape[1]
        vals = []
        for rank, i in enumerate(idx, 1):
            y, x = divmod(int(i), cols)
            vals.append(float(flat[i]))
            logger.info(f"  [top{rank}] val={flat[i]:.4f} pos=({x},{y})")
        # 并列嫌疑警告：top1 与 top2 太接近，说明模板区分度不够
        if len(vals) >= 2 and (vals[0] - vals[1]) < 0.02:
            logger.warning("  ⚠️ top1 与 top2 分数几乎并列，模板区分度不足！")

    def _find_by_image(self, template_path, confidence, color=True, pair_template=None):
        """OpenCV 图像匹配（支持中文路径）。
        :param color: True=彩色匹配(BGR)，False=灰度匹配。
        :param pair_template: 配对模板路径。提供后只匹配"两模板不同的区域"，
                              可彻底区分仅箭头朝向不同的成对图标。
        """
        if not template_path or not os.path.exists(template_path):
            return None
        try:
            flag = cv2.IMREAD_COLOR if color else cv2.IMREAD_GRAYSCALE
            tpl = self._imread_unicode(template_path, flag)
        except Exception:
            return None
        if tpl is None:
            return None

        # 截屏，通道与模板保持一致
        with mss.mss() as sct:
            img_bgra = np.array(sct.grab(sct.monitors[1]))
            img_bgr = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)
            screen = img_bgr if color else cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            
        if tpl.shape[0] > screen.shape[0] or tpl.shape[1] > screen.shape[1]: 
            return None

        # 可选：差异遮罩，只比"两模板不同的那块"
        mask, method = None, cv2.TM_CCOEFF_NORMED
        if pair_template and os.path.exists(pair_template):
            pair = self._imread_unicode(pair_template, cv2.IMREAD_COLOR if color else cv2.IMREAD_GRAYSCALE)
            if pair is not None and pair.shape == tpl.shape:
                d1 = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY) if tpl.ndim == 3 else tpl
                d2 = cv2.cvtColor(pair, cv2.COLOR_BGR2GRAY) if pair.ndim == 3 else pair
                _, m = cv2.threshold(cv2.absdiff(d1, d2), 15, 255, cv2.THRESH_BINARY)
                m = cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=1)
                if m.sum() > 0:
                    # mask 通道数须与 template 一致：彩色→3，灰度→1
                    mask = cv2.cvtColor(m, cv2.COLOR_GRAY2BGR) if tpl.ndim == 3 else m
                    method = cv2.TM_CCORR_NORMED  # 带 mask 仅支持 CCORR / SQDIFF

        t0 = time.perf_counter()
        res = (cv2.matchTemplate(screen, tpl, method, mask=mask) if mask is not None
               else cv2.matchTemplate(screen, tpl, method))
        logger.info(f"[img-match] matchTemplate 耗时 {(time.perf_counter()-t0)*1000:.1f} ms")
        self._log_top_peaks(res, k=5)
        _, max_v, _, max_l = cv2.minMaxLoc(res)

        # 关键：返回"全局最佳点" max_l，绝不用 np.where 的最左上达标点
        if max_v >= confidence:
            h, w = tpl.shape[:2]
            return (max_l[0] + w // 2, max_l[1] + h // 2)
        return None

    def _find_by_pyautogui(self, template_path, confidence):
        """pyautogui 图像匹配（支持中文路径）"""
        if not template_path or not os.path.exists(template_path):
            return None
        try:
            img_data = np.fromfile(template_path, dtype=np.uint8)
            img_cv = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
            if img_cv is None: 
                return None
            img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            location = pyautogui.locateCenterOnScreen(pil_img, confidence=confidence)
            if location: 
                return (location.x, location.y)
        except Exception as e:
            logger.error(f"pyautogui 异常: {e}")
        return None

    @profile_time
    def _find_by_pywinauto(self, target=None, control_type=None, class_name=None):
        """pywinauto 控件树查找（仅在当前窗口内搜索，不受其他软件干扰）"""
        if not PYWINAUTO_AVAILABLE or not self.main_window: return None
        try:
            kwargs = {}
            if target: kwargs['title'] = target
            # win32 backend 不支持 control_type 参数，强行传入会导致查找失败
            if control_type and self.backend != 'win32': kwargs['control_type'] = control_type
            if class_name: kwargs['class_name'] = class_name
            if not kwargs: return None
            elem = self.main_window.child_window(**kwargs)
            rect = elem.rectangle()
            if rect.left == 0 and rect.right == 0 and rect.top == 0 and rect.bottom == 0: return None
            return ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        except Exception:
            return None

    @profile_time
    def _find_by_uiautomation(self, target=None, control_type=None, class_name=None):
        """uiautomation 控件树查找（仅在当前窗口内搜索）"""
        if not UIAUTOMATION_AVAILABLE or not self.auto_window: return None
        try:
            elem = self._get_uia_element(target, control_type, class_name)
            if elem and elem.Exists(0, 0):
                rect = elem.BoundingRectangle
                # 兼容不同版本 uiautomation 的 BoundingRectangle 返回格式
                if hasattr(rect, 'left'):
                    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
                else:
                    left, top, right, bottom = rect[0], rect[1], rect[2], rect[3]
                width = right - left
                height = bottom - top
                if width > 0 and height > 0:
                    return (left + width // 2, top + height // 2)
            return None
        except Exception:
            return None

    @profile_time
    def _get_uia_element(self, target=None, control_type=None, class_name=None, 
                         automation_id=None, regex_name=None, found_index=1, 
                         search_depth=8, search_interval=0.2, require_exists=False):
        # search_depth=15,数值过小（=6）会导致获取页面内容失败
        """【核心方法】获取 uiautomation 控件对象（支持全局/局部搜索与多种定位策略）。
        :param target: 控件的 Name (精确匹配)
        :param control_type: 控件类型 (如 'Button', 'DataItem', 'Table' 等)
        :param class_name: 控件的 ClassName
        :param automation_id: 控件的 AutomationId (最稳定的定位方式，推荐优先使用)
        :param regex_name: 控件 Name 的正则表达式
        :param found_index: 当有多个同名控件时，获取第几个 (从1开始)
        :param search_depth: 搜索深度 (默认15)
        :param search_interval: 搜索间隔秒数 (默认0.5)
        :param require_exists: 是否要求控件必须存在
        :return: uiautomation 控件对象
        """
        if not UIAUTOMATION_AVAILABLE:
            raise RuntimeError("uiautomation 未安装")
        # 确定搜索根节点：优先使用绑定的主窗口，若未绑定则降级为全局桌面根节点
        root = self.auto_window if self.auto_window else auto.RootControl()

        # 构建搜索参数
        search_kwargs = {
            'searchFromControl': root, 
            'searchDepth': search_depth, 
            'searchInterval': search_interval,
            'foundIndex': found_index
        }
        # 多条件组合定位
        if target:
            search_kwargs['Name'] = target
        if regex_name:
            search_kwargs['RegexName'] = regex_name
        if class_name:
            search_kwargs['ClassName'] = class_name
        if automation_id:
            search_kwargs['AutomationId'] = automation_id

        # 控件类型映射
        type_map = {
            'Button': auto.ButtonControl, 'Edit': auto.EditControl, 'Text': auto.TextControl,
            'Window': auto.WindowControl, 'MenuItem': auto.MenuItemControl, 'CheckBox': auto.CheckBoxControl,
            'ComboBox': auto.ComboBoxControl, 'List': auto.ListControl, 'ListItem': auto.ListItemControl,
            'Pane': auto.PaneControl, 'DataItem': auto.DataItemControl, 'Table': auto.TableControl,
            'Tree': auto.TreeControl, 'Document': auto.DocumentControl, 'Custom': auto.CustomControl,
            'Header': auto.HeaderControl,
        }
        ctrl_class = type_map.get(control_type, auto.Control) if control_type else auto.Control
        
        try:
            element = ctrl_class(**search_kwargs)
            if require_exists:
                if not element.Exists(search_depth * search_interval, 0.5):
                    error_msg = f"❌ UIA 查找控件失败: target='{target}', type='{control_type}'"
                    logger.error(error_msg)
                    raise TimeoutError(error_msg)
            return element
        except Exception as e:
            logger.error(f"❌ UIA 控件实例化异常: {e}")
            raise

    def _get_uia_table_structure(self, table_control=None, timeout=5):
        """
        【增强版-兼容WinForms】自动识别 DataGridView 的结构：获取所有列名。
        针对 ESTEC 等软件表头识别不到的问题，增加了暴力搜索策略 + 数据行过滤。
        """
        if not UIAUTOMATION_AVAILABLE:
            return None, []

        # 1. 获取表格控件
        if table_control is None:
            try:
                table_control = self.auto_window.TableControl(searchDepth=15)
                if not table_control.Exists(timeout, 0.5):
                    logger.warning("⚠️ 未在当前窗口找到 Table 控件")
                    return None, []
            except Exception as e:
                logger.error(f"❌ 查找 Table 控件异常: {e}")
                return None, []

        column_names = []
        
        # --- 策略 A: 标准 Header -> HeaderItem ---
        try:
            header_ctrl = table_control.HeaderControl(searchDepth=2)
            if header_ctrl and header_ctrl.Exists(1, 0.2):
                children = header_ctrl.GetChildren()
                for child in children:
                    try:
                        name = child.Name.strip()
                        if name: column_names.append(name)
                    except: continue
        except Exception: pass

        # --- 策略 B: Table 直接子节点找 HeaderItem ---
        if not column_names:
            try:
                all_children = table_control.GetChildren()
                for child in all_children:
                    if child.ControlTypeName == 'HeaderItem':
                        name = child.Name.strip()
                        if name: column_names.append(name)
            except Exception: pass

        # --- 策略 C: 【关键修复】WinForms DataGridView 专用兜底 (OCR) ---
        if not column_names:
            try:
                import mss
                import cv2
                import numpy as np
                
                rect = table_control.BoundingRectangle
                if hasattr(rect, 'left'):
                    t_left, t_top, t_right, t_bottom = rect.left, rect.top, rect.right, rect.bottom
                else:
                    t_left, t_top, t_right, t_bottom = rect[0], rect[1], rect[2], rect[3]
                
                # 【关键】只截取表格顶部 40px 的区域，避免截到第一行数据
                cap_top = max(0, t_top - 5)
                cap_bottom = min(self.screen_height, t_top + 40) 
                cap_left = max(0, t_left)
                cap_right = min(self.screen_width, t_right)
                
                if cap_bottom > cap_top and cap_right > cap_left:
                    with mss.mss() as sct:
                        monitor = {"top": cap_top, "left": cap_left, "width": cap_right - cap_left, "height": cap_bottom - cap_top}
                        img_bgra = np.array(sct.grab(monitor))
                        img_bgr = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)
                        
                        temp_hdr_path = os.path.join(self.report.img_dir, f"temp_header_{int(time.time())}.jpg")
                        cv2.imencode('.jpg', img_bgr)[1].tofile(temp_hdr_path)
                        
                        ocr_res = self.ocr.ocr_with_image(temp_hdr_path)
                        if ocr_res and ocr_res.get('code') == 100:
                            texts_with_pos = []
                            for item in ocr_res.get('data', []):
                                txt = item.get('text', '').strip()
                                box = item.get('box', [])
                                if txt and box:
                                    x_pos = box[0][0] 
                                    texts_with_pos.append((x_pos, txt))
                            
                            texts_with_pos.sort(key=lambda x: x[0])
                            column_names = [t[1] for t in texts_with_pos]
                            logger.info(f"✅ 策略C (OCR兜底): 识别到原始表头 {column_names}")
                        
                        try: os.remove(temp_hdr_path)
                        except: pass

            except Exception as e:
                logger.warning(f"⚠️ 策略 C (OCR) 执行异常: {e}")

        # ==========================================
        # 清洗表头：部分 WinForms/UIA 控件会把表头与首行数据交错返回。
        # 例如：['序号', '1.0', '距离(m）', '0.0', ...]。
        # 这些数字是单元格值，不是列名，不能参与列结构比较。
        # ==========================================
        def _looks_numeric(value):
            try:
                float(str(value).strip().replace(',', ''))
                return True
            except (TypeError, ValueError):
                return False

        if len(column_names) >= 4 and len(column_names) % 2 == 0:
            even_items = column_names[::2]
            odd_items = column_names[1::2]
            # 只在“奇数位几乎全是数字、偶数位几乎全是文本”时，
            # 才按交错结构提取表头，避免误删正常列名。
            odd_numeric_ratio = sum(_looks_numeric(x) for x in odd_items) / max(1, len(odd_items))
            even_text_ratio = sum(not _looks_numeric(x) for x in even_items) / max(1, len(even_items))
            if odd_numeric_ratio >= 0.8 and even_text_ratio >= 0.8:
                logger.info(
                    f"🧹 检测到表头与首行数据交错，已只保留表头项："
                    f"原始 {len(column_names)} 项 -> {len(even_items)} 个候选列名"
                )
                column_names = even_items
        elif len(column_names) > 10:
            # 非交错结构的兜底：过滤明显的纯数字数据项。
            cleaned_cols = [item for item in column_names if not _looks_numeric(item)]
            if cleaned_cols:
                logger.info(f"🧹 已过滤疑似混入表头的数字数据项：{len(column_names)} -> {len(cleaned_cols)}")
                column_names = cleaned_cols

        # 去重并保持顺序
        seen = set()
        unique_cols = []
        for c in column_names:
            c_clean = c.strip()
            if c_clean and c_clean not in seen:
                seen.add(c_clean)
                unique_cols.append(c_clean)
        
        if not unique_cols:
            logger.warning("⚠️ 所有策略均未能识别到列名！请检查表格是否可见。")
            
        return table_control, unique_cols
    

    def check_table_data(self, expected_data, column_names_map=None, row_start=0, tolerance=0.01, timeout=5, table_control=None, strict_mode=True):
        """
        核对参考数据与 UI 表格的数据行。
        表头仅用于建立“参考字段 -> UI 列索引”的映射；绝不把表头文本与数据值相互比较。
        :param strict_mode: True=任一参考字段无法映射或单元格缺失时判失败；不因 UIA 将首行数据误报为列名而提前终止。
        """
        if not UIAUTOMATION_AVAILABLE:
            logger.error("❌ uiautomation 未安装")
            return False, {'error': 'uiautomation not available'}

        desc = "核对表格数据一致性"
        logger.info(f"🔍 开始{desc}...")
        
        # 1. 自动获取表格结构和实际列名
        actual_table, actual_col_names = self._get_uia_table_structure(table_control, timeout)
        
        if not actual_table:
            msg = "未找到表格控件"
            logger.error(f"❌ {msg}")
            self.report.capture_and_record(desc, "FAIL", msg)
            return False, {'error': msg}

        logger.info(f" 识别到的实际列: {actual_col_names}")

        # 2. 获取预期列名
        if not expected_data:
            return True, {'details': [], 'all_consistent': True}
        
        expected_keys = list(expected_data[0].keys())
        logger.info(f"📋 预期的列: {expected_keys}")

        # 3. 列一致性检查 (核心修复：全角/半角括号兼容 + 模糊匹配)        
        def normalize_col(s):
            """
            超级归一化：
            1. 去除所有空格
            2. 全角括号转半角
            3. 转小写
            """
            s = str(s)
            # 全角转半角映射
            trans_map = str.maketrans({
                '（': '(', '）': ')', 
                '【': '[', '】': ']', 
                '\u3000': ' ', # 全角空格
            })
            s = s.translate(trans_map)
            # 去除所有空白字符
            s = re.sub(r'\s+', '', s)
            return s.lower()

        norm_actual_map = {} 
        for c in actual_col_names:
            norm_actual_map[normalize_col(c)] = c
            
        norm_expected_map = {} 
        for c in expected_keys:
            norm_expected_map[normalize_col(c)] = c
        
        matched_cols = {} 
        missing_in_actual = [] 
        extra_in_actual = []   
        
        # 匹配逻辑
        for exp_key in expected_keys:
            n_exp = normalize_col(exp_key)
            found = False
            
            # 1. 精确归一化匹配 (解决 距离(m) vs 距离(m） 的问题)
            if n_exp in norm_actual_map:
                matched_cols[exp_key] = norm_actual_map[n_exp]
                found = True
            else:
                # 2. 包含匹配 (防止 OCR 多字少字)
                for n_act, act_val in norm_actual_map.items():
                    if n_exp in n_act or n_act in n_exp:
                        matched_cols[exp_key] = act_val
                        found = True
                        break
            
            if not found:
                missing_in_actual.append(exp_key)

        # 检查多余列
        for act_key in actual_col_names:
            n_act = normalize_col(act_key)
            is_matched = False
            if act_key in matched_cols.values():
                is_matched = True
            else:
                for n_exp in norm_expected_map:
                    if n_act in n_exp or n_exp in n_act:
                        is_matched = True
                        break
            
            if not is_matched:
                extra_in_actual.append(act_key)

        # 报告列差异
        error_msg_parts = []
        if missing_in_actual:
            error_msg_parts.append(f"实际表格缺失列: {missing_in_actual}")
        if extra_in_actual:
            error_msg_parts.append(f"实际表格多余列: {extra_in_actual}")
            
        if strict_mode and (missing_in_actual or extra_in_actual):
            final_msg = "❌ 列结构不一致! " + "; ".join(error_msg_parts)
            logger.error(final_msg)
            detail_info = f"预期列: {expected_keys}<br>实际列: {actual_col_names}<br>{final_msg}"
            self.report.capture_and_record(desc, "FAIL", detail_info)
            return False, {'error': 'Column mismatch', 'details': error_msg_parts}
        
        if not strict_mode and missing_in_actual:
            logger.warning(f"⚠️ 非严格模式下，跳过缺失列: {missing_in_actual}")

        if not matched_cols:
            msg = "没有任何列可以匹配，无法进行数据核对"
            logger.error(f"❌ {msg}")
            self.report.capture_and_record(desc, "FAIL", msg)
            return False, {'error': msg}

        logger.info(f"✅ 列匹配成功: {list(matched_cols.keys())} -> {list(matched_cols.values())}")

        # 4. 逐行比对数据
        report_details = []
        is_all_consistent = True
        
        # 获取所有数据行。不同 WinForms/WPF 控件的 UIA 树层级差异很大，
        # Row 可能不是 Table 的直接子项；因此先浅层递归找行，再递归读取单元格。
        def _children_safe(ctrl):
            try:
                return ctrl.GetChildren() or []
            except Exception:
                return []

        def _ctrl_type(ctrl):
            try:
                return str(ctrl.ControlTypeName or '')
            except Exception:
                return ''

        def _ctrl_name(ctrl):
            try:
                return str(ctrl.Name or '').strip()
            except Exception:
                return ''

        try:
            data_rows = []
            visited = set()
            def _find_rows(parent, depth=0):
                if depth > 4 or len(data_rows) >= max(100, len(expected_data) + row_start + 20):
                    return
                for child in _children_safe(parent):
                    try:
                        ident = child.GetRuntimeId()
                    except Exception:
                        ident = id(child)
                    if ident in visited:
                        continue
                    visited.add(ident)
                    typ = _ctrl_type(child)
                    name = _ctrl_name(child)
                    if 'Header' in typ or 'Header' in name:
                        continue
                    grandchildren = _children_safe(child)
                    # Row 控件优先；某些 provider 将行暴露为 DataItem/Custom。
                    if typ == 'Row' or (typ in ('DataItem', 'Custom') and grandchildren and
                                        (any(_ctrl_type(x) in ('DataItem', 'Text', 'Custom') for x in grandchildren))):
                        data_rows.append(child)
                    else:
                        _find_rows(child, depth + 1)
            _find_rows(actual_table)

            # 去掉嵌套重复行：只保留最外层候选，避免同一行被重复核对。
            if not data_rows:
                logger.warning('⚠️ UIA 树中未发现明确 Row 控件，将尝试从表格后代读取单元格')
        except Exception as e:
            logger.warning(f"⚠️ 获取行结构异常: {e}")
            data_rows = []

        def _read_cells(row_ctrl):
            """从行控件递归提取单元格；优先读取 ValuePattern，去重并保留 UIA 顺序。"""
            found, seen_nodes = [], set()
            def walk(node, depth=0):
                if depth > 5:
                    return
                for child in _children_safe(node):
                    typ = _ctrl_type(child)
                    name = _ctrl_name(child)
                    try:
                        rid = tuple(child.GetRuntimeId())
                    except Exception:
                        rid = (id(child),)
                    if rid in seen_nodes:
                        continue
                    seen_nodes.add(rid)
                    if 'Header' in typ or 'Header' in name:
                        continue
                    # 单元格一般是 DataItem；Text/Custom 仅作为 provider 的兜底。
                    if typ in ('DataItem', 'Text'):
                        val = name
                        try:
                            vp = self._get_value_pattern(child)
                            if vp:
                                val = str(vp.Value)
                        except Exception:
                            pass
                        found.append((child, str(val or '')))
                    else:
                        walk(child, depth + 1)
            walk(row_ctrl)
            return found

        for row_idx, expected_row in enumerate(expected_data):
            ui_row_index = row_start + row_idx
            row_report = f"【第 {ui_row_index+1} 行】"
            row_consistent = True
            
            if ui_row_index >= len(data_rows):
                row_report += " <span style='color:red'>(UI行数不足，无法读取)</span>"
                is_all_consistent = False
                report_details.append(row_report)
                continue
            
            current_row_ctrl = data_rows[ui_row_index]
            
            # 在当前行中查找单元格
            # DataGridView 的单元格通常是 DataItem，Name 格式可能是 "Value" 或 "ColumnName Value" 或 "Row X Column Y"
            # 最可靠的是利用 GridItemPattern 或者按顺序读取
            
            # UIA 行可能有嵌套容器，不能只读取直接子项；递归提取真实单元格。
            cells = _read_cells(current_row_ctrl)
            
            # 如果 Cells 数量与 匹配列数量 不一致，可能有问题，但我们按索引对应
            # 注意：cells 的顺序应该与 actual_col_names 的顺序一致
            
            for exp_key, act_key in matched_cols.items():
                expected_val = expected_row.get(exp_key)
                if expected_val is None: continue
                
                # 找到 act_key 在 actual_col_names 中的索引
                try:
                    col_idx = actual_col_names.index(act_key)
                except ValueError:
                    row_report += f" {exp_key}[内部错误:列索引丢失] "
                    continue
                
                actual_val_str = None
                cell_found = False
                
                if col_idx < len(cells):
                    cell, actual_val_str = cells[col_idx]
                    cell_found = True
                else:
                    # 兜底：按列索引在整行后代中寻找 DataItem/Cell 控件；
                    # 不再用列标题匹配单元格名称，因为多数 UIA 单元格名称只返回值。
                    try:
                        candidates = []
                        def _collect_dataitems(node, depth=0):
                            if depth > 5:
                                return
                            for ch in _children_safe(node):
                                if _ctrl_type(ch) in ('DataItem', 'Text'):
                                    candidates.append(ch)
                                else:
                                    _collect_dataitems(ch, depth + 1)
                        _collect_dataitems(current_row_ctrl)
                        if col_idx < len(candidates):
                            cell = candidates[col_idx]
                            cell_found = True
                            vp = self._get_value_pattern(cell)
                            actual_val_str = str(vp.Value) if vp else _ctrl_name(cell)
                    except Exception as e:
                        logger.debug(f"单元格索引兜底失败: {e}")

                if not cell_found:
                    row_report += f" {exp_key}[<span style='color:orange'>未找到单元格</span>] "
                    # 如果是严格模式，找不到单元格也算失败
                    if strict_mode:
                        row_consistent = False
                    continue
                
                # 清洗数据用于比对
                try:
                    # 处理空值
                    if actual_val_str is None: actual_val_str = ""
                    
                    # 尝试数值比对
                    try:
                        act_f = float(actual_val_str)
                        exp_f = float(expected_val)
                        if abs(act_f - exp_f) > tolerance:
                            row_report += f" {exp_key}[<span style='color:red'>X:期望{exp_f},实际{act_f}</span>] "
                            row_consistent = False
                        else:
                            row_report += f" {exp_key}[✓] "
                    except ValueError:
                        # 字符串比对
                        if str(actual_val_str).strip() != str(expected_val).strip():
                            row_report += f" {exp_key}[<span style='color:red'>x:期望'{expected_val}',实际'{actual_val_str}'</span>] "
                            row_consistent = False
                        else:
                            row_report += f" {exp_key}[✓] "
                except Exception as e:
                    row_report += f" {exp_key}[<span style='color:red'>比对异常:{e}</span>] "
                    row_consistent = False
            
            if not row_consistent:
                is_all_consistent = False
            report_details.append(row_report)

        final_status = "PASS" if is_all_consistent else "FAIL"
        logger.info(f"{'✅' if is_all_consistent else '❌'} {desc} 完成: {final_status}")
        
        extra_info = "核对结果：<br>" + "<br>".join(report_details)
        if missing_in_actual or extra_in_actual:
             extra_info += f"<br><span style='color:orange'>注意: 列差异 -> {error_msg_parts}</span>"
            
        self.report.capture_and_record(desc, final_status, extra_info)
        return is_all_consistent, {'details': report_details, 'all_consistent': is_all_consistent}

    def _find_by_ocr(self, temp_path, target_text, reference_text=None):
        """OCR 文字识别查找（全屏范围）"""
        if not target_text: return None
        result = self.ocr.ocr_with_image(temp_path)
        if not result or result.get('code') != 100: return None
        positions = self.ocr.find_text_positions(
            result, [target_text], (self.screen_width, self.screen_height),
            reference_text=reference_text, enable_color_check=False
        )
        if positions and isinstance(positions, dict) and 'absolute' in positions:
            return positions['absolute']
        return None

    # ==================== 业务 API ====================
    @profile_time
    def click(self, target=None, reference_text=None, mode='auto', timeout=0.5,
              offset_x=0, offset_y=0, control_type=None, class_name=None, screenshot_delay=0.5,
              color=True, pair_template=None):
        """等待并单击元素（自动记录点击前后对比截图）"""
        desc = f"点击[{mode}]"
        if target:
            # 路径只取文件名，非路径原样显示
            display_target = os.path.basename(target) if ('\\' in str(target) or '/' in str(target)) else target
            desc += f" '{display_target}'"
        if class_name: desc += f" (class={class_name})"
        
        try:
            pos = self.find_element(target, reference_text, mode, timeout=timeout,
                                    control_type=control_type, class_name=class_name,
                                    color=color, pair_template=pair_template)            
            if pos:
                fx, fy = pos[0] + offset_x, pos[1] + offset_y
                # 1. 点击前截图并用红框标注点击区域
                before_img = self._capture_and_mark_click_area(fx, fy)
                # 2. 执行底层点击
                self._win32_click(fx, fy)
                logger.info(f"✅ {desc} -> ({fx}, {fy})")
                # 3. 等待界面响应（如弹窗、页面跳转）
                if screenshot_delay > 0:
                    time.sleep(screenshot_delay)
                # 4. 点击后截图（记录实际效果）
                after_img = self._capture_screen_only()
                # 5. 将两张截图一起传入报告生成器
                self.report.capture_and_record(desc, "PASS", f"({fx},{fy})", images=[before_img, after_img])
                return True
            else:
                logger.warning(f"⚠️ {desc} 超时未找到")
                self.report.capture_and_record(desc, "FAIL", "未找到")
                return False
        except Exception as e:
            logger.error(f"❌ {desc} 异常: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return False

    # 菜单点击模块
    def click_menu(self, menu_path, timeout=3, search_depth=8):
        """
        点击多级菜单（支持任意级数，带完整截图记录）
        :param menu_path: 菜单路径，可以是：
                          - 字符串：'文件(F)' （单级）
                          - 列表：['文件(F)', '打开(O)'] （两级）
                          - 列表：['文件(F)', '打开(O)', '基础卷(B)'] （三级）
        :param timeout: 查找超时时间（秒）
        :param search_depth: UIA控件树搜索深度（默认8，复杂软件可设为12或15）
        :return: bool 是否成功
        """
        if not UIAUTOMATION_AVAILABLE or not self.auto_window:
            logger.error("❌ uiautomation 不可用或未连接窗口")
            return False
        
        # 统一转换为列表格式
        if isinstance(menu_path, str):
            menu_path = [menu_path]
        
        if not menu_path:
            logger.error("❌ 菜单路径不能为空")
            return False
            
        try:
            images = []
            current_parent = self.auto_window  # 初始搜索根节点为目标窗口
            
            # 逐级点击菜单
            for level, menu_name in enumerate(menu_path):
                # 查找当前级菜单项
                menu_item = auto.MenuItemControl(
                    searchFromControl=current_parent, 
                    searchDepth=2,  # 同级菜单深度通常为1-2
                    Name=menu_name
                )
                
                if not menu_item.Exists(timeout, 0.5):
                    # 如果找不到，尝试从窗口根节点重新搜索（第一级菜单）
                    if level == 0:
                        menu_item = auto.MenuItemControl(
                            searchFromControl=self.auto_window, 
                            searchDepth=search_depth, 
                            Name=menu_name
                        )
                        if not menu_item.Exists(timeout, 0.5):
                            after_img = self._capture_screen_only()
                            self.report.capture_and_record(
                                f"点击菜单 {' -> '.join(menu_path)}", 
                                "FAIL", f"第{level+1}级菜单'{menu_name}'未找到", 
                                images=[after_img]
                            )
                            return False
                    else:
                        after_img = self._capture_screen_only()
                        self.report.capture_and_record(
                            f"点击菜单 {' -> '.join(menu_path)}", 
                            "FAIL", f"第{level+1}级菜单'{menu_name}'未找到", 
                            images=images + [after_img]
                        )
                        return False

                # 获取坐标用于截图标注
                rect = menu_item.BoundingRectangle
                left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
                cx, cy = left + (right - left) // 2, top + (bottom - top) // 2
                
                # 【截图】点击当前级菜单前（带红框）
                before_img = self._capture_and_mark_click_area(cx, cy)
                images.append(before_img)
                
                # 执行点击
                menu_item.Click()
                logger.info(f"✅ 点击第{level+1}级菜单: {menu_name}")
                
                # 如果不是最后一级，等待子菜单展开
                if level < len(menu_path) - 1:
                    time.sleep(0.3)  # 等待子菜单动画
                    # 更新搜索根节点为刚点击的菜单项（子菜单是它的子控件）
                    current_parent = menu_item
                else:
                    # 最后一级菜单，等待操作完成
                    time.sleep(0.5)
            
            # 所有级菜单点击完成，截取最终效果
            after_img = self._capture_screen_only()
            images.append(after_img)
            
            # 记录成功
            menu_path_str = ' -> '.join(menu_path)
            self.report.capture_and_record(
                f"点击菜单 {menu_path_str}", 
                "PASS", 
                images=images
            )
            return True
            
        except Exception as e:
            logger.error(f"❌ 点击菜单异常: {e}")
            self.report.capture_and_record(
                f"点击菜单 {' -> '.join(menu_path)}", 
                "FAIL", str(e)
            )
            return False

    # 通用文本录入函数
    # ---------- 表单定位辅助方法 ----------
    def _capture_and_mark_rect(self, left, top, right, bottom):
        """截图并用红框精准套住指定矩形"""
        with mss.mss() as sct:
            img_bgr = cv2.cvtColor(np.array(sct.grab(sct.monitors[1])), cv2.COLOR_BGRA2BGR)
            h, w = img_bgr.shape[:2]
            x1, y1 = max(0, int(left) - 2), max(0, int(top) - 2)
            x2, y2 = min(w, int(right) + 2), min(h, int(bottom) + 2)
            cv2.rectangle(img_bgr, (x1, y1), (x2, y2), (0, 0, 255), 2)
            p = os.path.join(self.report.img_dir, f"before_{int(time.time()*1000)}.jpg")
            cv2.imencode('.jpg', img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(p)
            return p

    def _norm_label(self, s):
        """标签归一化：删除所有空白 + 冒号/标点"""
        return re.sub(r'[\s：:·•\.\-]', '', str(s or '')).strip()

    def _collect_form_controls(self, root=None, max_depth=15, max_count=800):
        """一次遍历收集 标签/Edit/ComboBox/日期控件。
        关键修复：
          1) 链式遍历(GetFirstChild+GetNextSibling)，比 GetChildren 全；
          2) 新增日期控件：ClassName 含 'DateTimePick' 的 Pane（解决检测日期漏收）；
          3) 跳过 Table/List/菜单 子树，提速并避免误收表格单元格。"""
        root = root or self.auto_window
        labels, edits, combos, dates = [], [], [], []
        LABEL_TYPES = {'Text', 'Custom'}
        SKIP_SUBTREE = {'Table', 'List', 'Tree', 'MenuBar', 'ToolBar', 'StatusBar', 'TitleBar'}
        def walk(ctrl, depth):
            if depth > max_depth or (len(labels) + len(edits) + len(combos) + len(dates)) >= max_count:
                return
            try:
                child = ctrl.GetFirstChildControl()
            except Exception:
                child = None
            while child is not None:
                if (len(labels) + len(edits) + len(combos) + len(dates)) >= max_count:
                    return
                try:
                    tn, nm, cn = child.ControlTypeName, child.Name, child.ClassName
                except Exception:
                    tn, nm, cn = "", "", ""
                if tn in SKIP_SUBTREE:
                    pass  # 不递归进表格/菜单子树
                else:
                    if tn == 'Edit':
                        edits.append(child)
                    elif tn == 'ComboBox':
                        combos.append(child)
                    elif tn == 'Pane' and cn and 'DateTimePick' in cn:
                        dates.append(child)
                    elif tn in LABEL_TYPES and nm and nm.strip():
                        labels.append(child)
                    walk(child, depth + 1)
                try:
                    child = child.GetNextSiblingControl()
                except Exception:
                    child = None
        walk(root, 0)
        return labels, edits, combos, dates

    def _find_label_control(self, label_text, labels):
        """三级容错匹配标签：精确 → 归一相等 → 互相包含"""
        n = self._norm_label(label_text)
        if not n:
            return None
        for t in labels:
            try:
                if t.Name == label_text:
                    return t
            except Exception:
                pass
        for t in labels:
            try:
                if self._norm_label(t.Name) == n:
                    return t
            except Exception:
                pass
        for t in labels:
            try:
                nt = self._norm_label(t.Name)
                if nt and (n in nt or nt in n):
                    return t
            except Exception:
                pass
        return None

    def _rect_of(self, ctrl):
        try:
            r = ctrl.BoundingRectangle
            rect = (r.left, r.top, r.right, r.bottom) if hasattr(r, 'left') else tuple(r[:4])
            if (rect[2] - rect[0]) > 0 and (rect[3] - rect[1]) > 0:
                return rect
        except Exception:
            pass
        return None

    def _match_input_by_position(self, label_rect, candidates, row_tolerance=None):
        """坐标邻近匹配：同行 + 标签右侧 + 水平最近"""
        l_left, l_top, l_right, l_bottom = label_rect
        l_cy = (l_top + l_bottom) / 2.0
        l_h = max(1, l_bottom - l_top)
        best, best_eff = None, float('inf')
        for c in candidates:
            cr = self._rect_of(c)
            if not cr:
                continue
            c_left, c_top, c_right, c_bottom = cr
            c_cy = (c_top + c_bottom) / 2.0
            c_h = max(1, c_bottom - c_top)
            tol = row_tolerance if row_tolerance else max(l_h, c_h) * 0.8
            if abs(c_cy - l_cy) > tol:
                continue
            dx = c_left - l_right
            if dx < -8:
                continue
            eff = dx if dx >= 0 else (abs(dx) + 1000)
            if eff < best_eff:
                best_eff, best = eff, c
        return best

    def _match_input_by_center(self, label_center, candidates, row_tolerance=14):
        """OCR 兜底：只有标签中心点时，找 同行+右侧+最近 输入框"""
        cx, cy = label_center
        best, best_dx = None, float('inf')
        for c in candidates:
            cr = self._rect_of(c)
            if not cr:
                continue
            c_cx = (cr[0] + cr[2]) / 2.0
            c_cy = (cr[1] + cr[3]) / 2.0
            c_h = max(1, cr[3] - cr[1])
            if abs(c_cy - cy) > max(row_tolerance, c_h * 0.8):
                continue
            dx = c_cx - cx
            if dx < 5:
                continue
            if dx < best_dx:
                best_dx, best = dx, c
        return best

    def _find_label_by_ocr(self, label_text):
        """OCR 兜底：全屏找标签文字中心坐标"""
        n = self._norm_label(label_text)
        words = [w for w in (n, str(label_text).strip()) if w]
        _, temp_path = self._capture_screen()
        try:
            result = self.ocr.ocr_with_image(temp_path)
        except Exception as e:
            logger.warning(f"⚠️ OCR 兜底异常: {e}")
            return None
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass
        if not result or result.get('code') != 100:
            return None
        for w in words:
            try:
                pos = self.ocr.find_text_positions(result, [w], (self.screen_width, self.screen_height),
                                                   reference_text=None, enable_color_check=False)
                if pos and isinstance(pos, dict) and pos.get('absolute'):
                    logger.info(f"🔎 OCR 兜底命中标签 '{w}' -> {pos['absolute']}")
                    return pos['absolute']
            except Exception:
                pass
        return None

    # ---------- 日期控件专用：解析 + 原生消息设值 ----------
    def _parse_date_value(self, value):
        """从多种日期字符串中解析出 (year, month, day)。
        兼容 '2020年05月06日' / '2020-05-06' / '2020/05/06' / '05/06/2020' 等常见写法。
        规则：优先按"年在前"的四位数年份匹配；若没有四位年份，则退回 y/m/d 三段数字，
        按位置猜测（第三段为4位则视为 mm/dd/yyyy）。解析失败返回 None。"""
        s = str(value).strip()
        # 情形1：包含四位年份，如 2020年05月06日 / 2020-05-06 / 2020/05/06
        m = re.search(r'(\d{4})\D+(\d{1,2})\D+(\d{1,2})', s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return y, mo, d
        # 情形2：年份在最后，如 05/06/2020
        m = re.search(r'(\d{1,2})\D+(\d{1,2})\D+(\d{4})', s)
        if m:
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return y, mo, d
        logger.warning(f"⚠️ 日期值 '{value}' 无法解析为 年/月/日")
        return None

    def _set_datetimepicker_value(self, ctrl, value):
        """直接通过 Win32 消息 DTM_SETSYSTEMTIME 给 SysDateTimePick32 控件设值。

        【关键修复说明】旧实现是 Click() 后 SendKeys(原始日期字符串)，存在两个致命问题：
          1) DateTimePicker 没有"全选"语义，Ctrl+A 对其无效，光标真正落在哪个分段完全不可控；
          2) 该控件按"分段"接受输入(年/月/日各段独立、且要求纯数字)，直接把
             '2020年05月06日' 这种带中文/分隔符的整串文本 SendKeys 进去，控件根本无法识别，
             导致录入失败或年月日错位、乱码。
        改为直接发送 DTM_SETSYSTEMTIME 消息设置底层 SYSTEMTIME 结构体，
        与控件当前显示格式(yyyy-MM-dd / MM/dd/yyyy / 中文年月日 等)完全无关，一次性、原子化设值，
        不再依赖键盘录入。"""
        parsed = self._parse_date_value(value)
        if not parsed:
            return False
        year, month, day = parsed
        hwnd = _extract_hwnd(ctrl)
        if not hwnd:
            logger.warning("⚠️ 未能取得日期控件 hwnd，无法用原生消息设值")
            return False
        try:
            DTM_FIRST = 0x1000
            DTM_SETSYSTEMTIME = DTM_FIRST + 2
            GDT_VALID = 0

            class SYSTEMTIME(ctypes.Structure):
                _fields_ = [
                    ("wYear", ctypes.c_ushort), ("wMonth", ctypes.c_ushort),
                    ("wDayOfWeek", ctypes.c_ushort), ("wDay", ctypes.c_ushort),
                    ("wHour", ctypes.c_ushort), ("wMinute", ctypes.c_ushort),
                    ("wSecond", ctypes.c_ushort), ("wMilliseconds", ctypes.c_ushort),
                ]

            st = SYSTEMTIME()
            st.wYear, st.wMonth, st.wDay = year, month, day
            st.wDayOfWeek = st.wHour = st.wMinute = st.wSecond = st.wMilliseconds = 0
            ok = ctypes.windll.user32.SendMessageW(hwnd, DTM_SETSYSTEMTIME, GDT_VALID, ctypes.byref(st))
            if ok:
                logger.info(f"✅ 原生消息设置日期成功: {year}-{month:02d}-{day:02d}")
                return True
            logger.warning("⚠️ DTM_SETSYSTEMTIME 返回失败")
            return False
        except Exception as e:
            logger.warning(f"⚠️ DTM_SETSYSTEMTIME 设置日期异常: {e}")
            return False

    # ---------- 通用：COM 调用重试（规避 uiautomation 库已知的偶发重入异常） ----------
    def _retry_uia_call(self, fn, *args, retries=2, delay=0.3, desc="", **kwargs):
        """包一层重试。uiautomation/comtypes 有个已知的偶发问题：
        紧接在另一次 UI 变更(比如我们刚发过的 DTM_SETSYSTEMTIME 原生消息、或刚点击/切焦点)
        之后立刻再发一次 UIA 调用，容易撞上
        '(-2147220991, 事件无法调用任何订户, ...)' 这种 COM 重入异常——
        这是库本身的时序问题，不是目标控件真的不可用，直接重试通常就能成功，
        不应该让它把整个脚本/软件带崩。"""
        last_err = None
        for i in range(retries + 1):
            try:
                return True, fn(*args, **kwargs)
            except Exception as e:
                last_err = e
                if i < retries:
                    logger.warning(f"⚠️ {desc} 第{i+1}次异常，{delay}s后重试: {e}")
                    time.sleep(delay)
        logger.warning(f"⚠️ {desc} 重试{retries}次后仍失败: {last_err}")
        return False, None

    def _detect_stray_modal_dialog(self):
        """安全地探测前台是否意外出现了一个模态对话框（如"字段不能为空"之类的校验提示）。
        Windows 标准 MessageBox / 大多数 WinForms 校验提示框的窗口类名固定是 '#32770'，
        与具体标题文字无关——不需要像 wait_for_popup 那样猜一个标题关键字去匹配
        (猜错标题、或标题太泛，会把不相关窗口误判成弹窗，甚至误把 self.main_window
        切换过去，风险比不猜更大)。这里只探测+记录，不代为点击：
        不同软件确定按钮的文案不一样，代点错了风险比不点更大，交给上层按需处理。"""
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            cls = win32gui.GetClassName(hwnd)
            if cls == "#32770":
                return win32gui.GetWindowText(hwnd) or "(无标题)"
        except Exception:
            pass
        return None

    def _input_date_by_keyboard(self, ctrl, value, segment_order='YMD', desc=""):
        """独立、可复用的日期控件键盘录入方法。适用于原生 SysDateTimePick32 一类的
        分段日期控件（不支持 ValuePattern，必须靠键盘按分段输入，不能整串 SendKeys）。
        不依赖 input_by_label 的标签查找流程，拿到控件的 UIA 元素就能直接调用。

        :param ctrl: 目标日期控件的 UIA 元素（需要能 SetFocus，比如通过 AutomationId 取到的元素）。
        :param value: 日期值，支持 '2020年05月06日' / '2020-05-06' / '2020/05/06' / '05/06/2020' 等常见写法。
        :param segment_order: 控件【显示格式】的分段顺序，决定按什么顺序键入、光标要往右移几次：
            'YMD' = 年/月/日 在前（如中文 yyyy年MM月dd日），默认——目前唯一在真实软件上验证过的格式；
            'MDY' = 月/日/年 在前（如英文 MM/dd/yyyy）；
            'DMY' = 日/月/年 在前（如欧洲 dd/MM/yyyy）。
            必须和目标控件实际显示格式一致，顺序不对会把数字打进错误的分段——
            用之前建议先用 automation.py 之类的 UIA 查看器看一眼控件当前显示的日期文本，
            确认年月日出现的先后顺序。
        :param desc: 日志里用的描述文字，不传则用 value 拼一个默认值。
        :return: (是否成功, 控件当前显示的日期文本或 None)
        """
        if not desc:
            desc = f"日期控件录入 = {value}"
        parsed = self._parse_date_value(value)
        ok_focus, _ = self._retry_uia_call(ctrl.SetFocus, desc=f"{desc} SetFocus")
        if not ok_focus:
            return False, None
        time.sleep(0.15)

        if parsed:
            y, mo, d = parsed
            order_map = {
                'YMD': [f"{y:04d}", f"{mo:02d}", f"{d:02d}"],
                'MDY': [f"{mo:02d}", f"{d:02d}", f"{y:04d}"],
                'DMY': [f"{d:02d}", f"{mo:02d}", f"{y:04d}"],
            }
            segments = order_map.get(str(segment_order).upper(), order_map['YMD'])
            # 只信任控件刚 SetFocus 拿到焦点时默认停在最左边那一段（原生控件的默认行为），
            # 全程只用 {Right} 单步前进、不回退（{Home}/{End} 会跳到控件的最小/最大日期，
            # {Left} 在段间是循环的，两者都不能用来"归位"，实测踩过坑）。
            ok_type = True
            for idx, seg in enumerate(segments):
                if idx > 0:
                    self._retry_uia_call(auto.SendKeys, '{Right}', desc=f"{desc} 定位-前进到段{idx}")
                    time.sleep(0.1)
                ok_seg, _ = self._retry_uia_call(auto.SendKeys, seg, waitTime=0.08, desc=f"{desc} 分段录入(段{idx}='{seg}')")
                if not ok_seg:
                    ok_type = False
                    break
                time.sleep(0.15)
        else:
            digits = re.sub(r'\D', '', str(value))
            ok_type, _ = self._retry_uia_call(auto.SendKeys, digits, waitTime=0.08, desc=f"{desc} 数字录入")

        if not ok_type:
            return False, None

        self._retry_uia_call(auto.SendKeys, '{Enter}', desc=f"{desc} 确认Enter")
        time.sleep(0.2)
        # 回读校验：日期控件的 Name 就是当前显示的日期文本（如 '2026年08月02日'）；
        # 读取本身也可能撞上偶发 COM 异常——读取失败不代表没写成功，不能当失败处理。
        ok_read, name_val = self._retry_uia_call(lambda: ctrl.Name, retries=1, delay=0.2, desc=f"{desc} 回读校验")
        if ok_read and parsed:
            y, mo, d = parsed
            name_str = str(name_val or "")
            # 日期控件可能按本地格式显示 2020年5月6日、2020年05月06日或 2020/5/6；
            # 统一解析为年月日比较，避免仅因零填充/分隔符不同误报失败。
            displayed = self._parse_date_value(name_str)
            success = displayed == (y, mo, d)
            if not success:
                logger.warning(f"⚠️ {desc} 键盘录入后回读日期 '{name_str}' 与目标不符")
            return success, name_val
        return True, name_val  # 读取本身失败，按已执行的写入动作判定，不误判失败

    def _get_value_pattern(self, ctrl):
        """兼容获取 ValuePattern。库里 EditControl/ComboBoxControl 等具体类型化的控件
        有 GetValuePattern() 这个便捷方法；但如果查找路径返回的是没有具体类型化的
        通用 Control 基类对象，这个方法根本不存在，调用会直接抛
        AttributeError('Control' object has no attribute 'GetValuePattern')。
        这里统一走一层：优先用 GetValuePattern()，拿不到就退回库文档写明的等价方式
        GetPattern(PatternId.ValuePattern)，两种控件对象都能用。"""
        try:
            return ctrl.GetValuePattern()
        except AttributeError:
            pass
        except Exception:
            pass
        try:
            return ctrl.GetPattern(auto.PatternId.ValuePattern)
        except Exception:
            return None

    def _safe_control_type(self, ctrl):
        """安全读取 ControlTypeName。控件已失效/目标软件已崩溃时，这个属性访问本身
        就会抛 COM 异常——原来的代码在函数尾部直接裸访问 matched.ControlTypeName，
        一旦软件状态异常，这行本身就会把异常冲出最外层 try/except，
        导致日志里看到的"❌ ... 异常"其实是这里炸的，不是真正的业务逻辑失败。"""
        try:
            return ctrl.ControlTypeName
        except Exception:
            return "未知(控件可能已失效/软件可能已崩溃)"

    # ---------- 主函数：通用文本录入（四策略融合） ----------
    def input_by_label(self, label_text, value, control_type='Edit', automation_id=None,
                       timeout=3, search_depth=12, auto_fallback=True, row_tolerance=None,
                       capture_screenshots=True, use_native_date_message=False,
                       date_segment_order='YMD'):
        """根据标签/AutomationId 定位输入框并录入（针对 WinForms 优化，带完整截图）。
        定位四策略（逐级兜底）：
          1. AutomationId 直定位（WinForms 首选，最稳，秒级）；
          2. 按输入框自身 Name 定位（WinForms 特性：ComboBox.Name=标签文本）；
          3. 坐标邻近匹配（标签Text→右侧最近输入框，含日期控件）；
          4. OCR 兜底。
        录入：日期控件用键盘；Edit/ComboBox 用 SetValue→SendKeys→粘贴。
        :param automation_id: 控件 AutomationId（强烈推荐传入，见字段映射表）
        :param control_type: 优先类型 'Edit'/'ComboBox'
        :param capture_screenshots: 是否为本次录入截图存进报告，默认 True。
            批量录入很多字段（如一次性录 9 个字段）时，每个字段都截图+编码+写盘
            是主要耗时来源之一，可传 False 跳过截图只保留 PASS/FAIL 记录来提速；
            失败时的错误信息仍会正常记录，不影响排错。
        :param use_native_date_message: 日期控件是否用 DTM_SETSYSTEMTIME 原生消息直接设值。
            默认 False（只用键盘分段录入）。原生消息虽然与显示格式无关，但是绕开了
            .NET 控件自身的事件/校验流程，在实测中会导致老旧/调试版软件崩溃或状态错乱，
            因此默认关闭；只有确认目标软件能扛住原生消息时才建议显式传 True。
        :param date_segment_order: 日期控件键盘录入时的分段顺序，见 _input_date_by_keyboard。
            默认 'YMD'（年/月/日在前），是目前唯一在本模块验证过的格式；如果换了一个
            显示格式不同的日期控件（比如英文 MM/dd/yyyy），需要显式传 'MDY'/'DMY'。
        """
        desc = f"录入 '{label_text}' = {value}"
        if not UIAUTOMATION_AVAILABLE or not self.auto_window:
            logger.error("❌ uiautomation 未连接")
            self.report.capture_and_record(desc, "FAIL", "UIA未连接")
            return False

        try:
            matched = None

            # ===== 策略1：AutomationId 直定位 =====
            if automation_id:
                try:
                    elem = self._get_uia_element(automation_id=automation_id,
                                                 search_depth=search_depth, require_exists=False)
                    if elem.Exists(timeout, 0.2):
                        matched = elem
                        logger.info(f"✅ [策略1] AutomationId='{automation_id}' 命中")
                except Exception as e:
                    logger.warning(f"⚠️ 策略1 异常: {e}")

            # ===== 策略2：按输入框自身 Name 定位 =====
            if not matched:
                type_order = ['ComboBox', 'Edit'] if control_type == 'ComboBox' else ['Edit', 'ComboBox']
                if not auto_fallback:
                    type_order = [control_type]
                for tn in type_order:
                    try:
                        elem = self._get_uia_element(target=label_text, control_type=tn,
                                                     search_depth=search_depth, require_exists=False)
                        if elem.Exists(0.5, 0.1):
                            matched = elem
                            logger.info(f"✅ [策略2] 按 Name='{label_text}' type={tn} 命中")
                            break
                    except Exception:
                        pass

            # ===== 策略3：坐标邻近匹配（含日期控件） =====
            labels = edits = combos = dates = None
            if not matched:
                labels, edits, combos, dates = self._collect_form_controls(max_depth=search_depth)
                logger.info(f"🔎 [策略3] 标签={len(labels)} Edit={len(edits)} Combo={len(combos)} Date={len(dates)}")
                label_ctrl = self._find_label_control(label_text, labels)
                if label_ctrl:
                    lr = self._rect_of(label_ctrl)
                    if lr:
                        pool = edits + combos + dates
                        m = self._match_input_by_position(lr, pool, row_tolerance)
                        if m:
                            matched = m
                            logger.info(f"✅ [策略3] 坐标命中标签 '{label_ctrl.Name}' → {matched.ControlTypeName}")

            # ===== 策略4：OCR 兜底 =====
            if not matched:
                if labels is None:
                    labels, edits, combos, dates = self._collect_form_controls(max_depth=search_depth)
                center = self._find_label_by_ocr(label_text)
                if center:
                    m = self._match_input_by_center(center, edits + combos + dates, row_tolerance or 14)
                    if m:
                        matched = m
                        logger.info("✅ [策略4] OCR 兜底命中")

            if not matched:
                after_img = self._capture_screen_only()
                self.report.capture_and_record(desc, "FAIL", "四种策略均未定位到输入框", images=[after_img])
                return False

            # ===== 录入 =====
            # 判断是否日期控件（无 ValuePattern，必须键盘输入）
            is_date = False
            try:
                is_date = 'DateTimePick' in (matched.ClassName or '')
            except Exception:
                pass

            # 截图：红框套住输入框（capture_screenshots=False 时跳过，省一次截图+编码+写盘）
            before_img = None
            if capture_screenshots:
                mr = self._rect_of(matched)
                before_img = self._capture_and_mark_rect(*mr) if mr else self._capture_screen_only()

            # 确定真正操作对象（ComboBox 深入内部 Edit，避免点下拉箭头▼）
            op = matched
            if matched.ControlTypeName == 'ComboBox':
                inner = self._extract_edit_from_combo(matched)
                if inner is not None:
                    op = inner
                    logger.info("✅ ComboBox 深入内部 Edit")

            input_ok = False
            if is_date:
                if use_native_date_message:
                    # 【已知风险，默认关闭】直接发 DTM_SETSYSTEMTIME 原生消息虽然与显示
                    # 格式无关，但绕开了 .NET 控件自身的事件/校验流程；在这类老旧/调试版
                    # 软件上实测会导致软件崩溃或状态错乱（消息本身就返回失败，随后连它自己
                    # 的 UIA 元素都跟着失效），因此默认不启用，只有显式传
                    # use_native_date_message=True 才会走这条路。
                    input_ok = self._set_datetimepicker_value(matched, value)
                    time.sleep(0.3)  # 静置，避免紧接着的 UIA 调用撞上库的 COM 重入异常

                if not input_ok:
                    # 键盘录入（默认主路径）：更贴近真实用户操作，不直接捅控件内部状态。
                    # 不复用 matched（可能已是过期引用），有 automation_id 时重新取一次干净引用。
                    date_ctrl = matched
                    if automation_id:
                        try:
                            elem = self._get_uia_element(automation_id=automation_id,
                                                         search_depth=search_depth, require_exists=False)
                            if elem.Exists(1, 0.2):
                                date_ctrl = elem
                        except Exception:
                            pass
                    input_ok, _ = self._input_date_by_keyboard(date_ctrl, value,
                                                               segment_order=date_segment_order, desc=desc)
            else:
                # Edit / ComboBox内部Edit：SetValue → 回读校验 → 失败则键盘兜底 → 再回读校验
                def _read_back(o):
                    """带重试地读回控件当前值。
                    【问题根因说明】读取本身也是一次 UIA 调用，紧跟在刚 SetValue/SendKeys
                    之后立刻读，同样会偶发撞上 uiautomation 库的 COM 重入异常——
                    "读取时抛异常"不等于"确认读到了空值"，不能一概判定为失败，
                    否则会把明明写成功的字段误判为失败（旧代码把这两种情况混在一起，
                    曾把'管线名称'这种已经写成功的字段错误标记为回读为空）。
                    返回 (读到的值, 是否读取成功)；读取成功但值为空，才是真的没写进去。"""
                    def _do_read():
                        vp2 = self._get_value_pattern(o)
                        return vp2.Value if vp2 else o.Name
                    ok, val = self._retry_uia_call(_do_read, retries=1, delay=0.2, desc="回读校验")
                    return val, ok

                write_ok = False
                try:
                    vp = self._get_value_pattern(op)
                    if vp:
                        vp.SetValue(str(value))
                        write_ok = True
                except Exception as e:
                    logger.warning(f"⚠️ {desc} SetValue 调用异常: {e}")

                if write_ok:
                    time.sleep(0.15)
                    actual, read_ok = _read_back(op)
                    if read_ok:
                        input_ok = actual is not None and str(actual).strip() != ""
                        if not input_ok:
                            logger.warning(f"⚠️ {desc} SetValue 未报错但确认回读为空，判定为未真正写入，走键盘兜底")
                    else:
                        # 读取本身失败（异常），不能确认是否为空——SetValue 调用没报错，
                        # 按已执行的写入动作判定成功，避免误判
                        input_ok = True

                if not input_ok:
                    fallback_write_ok = False
                    try:
                        op.Click()
                        time.sleep(0.1)
                        # 清空改用真实组合键。
                        try:
                            op.SetFocus()
                        except Exception:
                            pass
                        time.sleep(0.1)   # 给焦点真正切换过去留出时间，避免 Ctrl+A 打到还没切焦点的旧控件上
                        pyautogui.hotkey('ctrl', 'a')
                        # pyautogui.press('delete') #部分输入框不允许为空，会弹窗
                        op.SendKeys(str(value), waitTime=0.02)
                        fallback_write_ok = True
                    except Exception as e:
                        logger.warning(f"⚠️ {desc} 键盘兜底写入异常: {e}")

                    if fallback_write_ok:
                        time.sleep(0.15)
                        actual, read_ok = _read_back(op)
                        if read_ok:
                            input_ok = actual is not None and str(actual).strip() != ""
                            if not input_ok:
                                logger.warning(f"⚠️ {desc} 键盘兜底后确认回读为空，控件可能真的没写进去")
                        else:
                            input_ok = True  # 同上：读取异常不代表没写成功

            # 安全探测一下是否意外冒出了模态对话框（比如"不能为空"之类的校验提示）。
            # 只探测+标记失败，不代为点击——不同软件确定按钮文案不一样，代点错了比不点风险更大。
            stray = self._detect_stray_modal_dialog()
            if stray:
                logger.warning(f"⚠️ {desc} 后检测到意外弹窗: '{stray}'，"
                              f"很可能是控件校验（如不允许留空）拦下了这次录入，判定为失败")
                input_ok = False

            time.sleep(0.2)  # 前面各步骤已经有针对性的等待/回读校验了，这里只需留一点缓冲，不用再盲等0.4s
            images = []
            if capture_screenshots:
                after_img = self._capture_screen_only()
                images = [before_img, after_img]
            status = "PASS" if input_ok else "FAIL"
            self.report.capture_and_record(desc, status, f"类型={matched.ControlTypeName}"
                                           + (f"；意外弹窗='{stray}'" if stray else ""), images=images)
            logger.info(f"{'✅' if input_ok else '❌'} {desc} （类型={matched.ControlTypeName}, 日期={is_date}）")
            return input_ok

        except Exception as e:
            logger.error(f"❌ {desc} 异常: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return False

    def double_click(self, target=None, reference_text=None, mode='auto', timeout=5,
                     offset_x=0, offset_y=0, control_type=None, class_name=None, screenshot_delay=0.5,
                     color=True, pair_template=None):
        """等待并双击元素（自动记录点击前后对比截图）"""
        desc = f"双击[{mode}]"
        if target:
            display_target = os.path.basename(target) if ('\\' in str(target) or '/' in str(target)) else target
            desc += f" '{display_target}'"
        if class_name: desc += f" (class={class_name})"
        
        try:
            pos = self.find_element(target, reference_text, mode, timeout=timeout,
                                    control_type=control_type, class_name=class_name,
                                    color=color, pair_template=pair_template)            
            if pos:
                fx, fy = pos[0] + offset_x, pos[1] + offset_y
                # 1. 点击前截图并用红框标注
                before_img = self._capture_and_mark_click_area(fx, fy)
                # 2. 执行底层双击
                self._win32_click(fx, fy, double=True)
                logger.info(f"✅ {desc} -> ({fx}, {fy})")
                # 3. 等待界面响应
                if screenshot_delay > 0:
                    time.sleep(screenshot_delay)
                # 4. 点击后截图
                after_img = self._capture_screen_only()
                # 5. 记录到报告
                self.report.capture_and_record(desc, "PASS", f"({fx},{fy})", images=[before_img, after_img])
                return True
            else:
                logger.warning(f"⚠️ {desc} 超时未找到")
                self.report.capture_and_record(desc, "FAIL", "未找到")
                return False
        except Exception as e:
            logger.error(f"❌ {desc} 异常: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return False

    def check(self, target=None, mode='auto', timeout=3, control_type=None, class_name=None,
              color=True, pair_template=None):
        """检查元素是否存在（不点击），返回 True/False"""
        desc = f"检查[{mode}]"
        if target:
            desc += f" '{target}'"
        if class_name:
            desc += f" (class={class_name})"
        pos = self.find_element(target, mode=mode, timeout=timeout,
                                control_type=control_type, class_name=class_name,
                                color=color, pair_template=pair_template)        
        exists = pos is not None
        logger.info(f"🔍 {desc} -> {'存在' if exists else '未找到'}")
        self.report.capture_and_record(desc, "PASS" if exists else "FAIL", str(pos) if exists else "")
        return exists

    def input_text(self, text, target=None, mode='global', method='paste',
                   press_enter=True, control_type=None, class_name=None, screenshot_delay=0.5):
        """输入文本。
        :param mode: 'global'(剪贴板/键盘模拟) 或 'pywinauto'(控件级直接写入) 或 'uiautomation'
        :param target: 控件标题（pywinauto/uiautomation模式）
        :param class_name: 控件类名
        """
        desc = "输入文本"
        if target: desc += f"(title='{target}')"
        if class_name: desc += f"(class='{class_name}')"
        
        if mode == 'pywinauto' and (target or class_name):
            if not PYWINAUTO_AVAILABLE or not self.main_window:
                logger.error("❌ pywinauto 未连接")
                self.report.capture_and_record(desc, "FAIL", "未连接")
                return False
            try:
                elem = self._get_ui_element(target=target, control_type=control_type, class_name=class_name)
                if hasattr(elem, 'set_edit_text'): elem.set_edit_text(str(text))
                else:
                    elem.set_focus()
                    elem.type_keys(str(text), with_spaces=True, with_tabs=True, with_newlines=True)
                if press_enter: elem.type_keys('{ENTER}')
                if screenshot_delay > 0: time.sleep(screenshot_delay)
                logger.info(f"✅ [UI树] {desc}")
                self.report.capture_and_record(desc, "PASS", text[:30])
                return True
            except Exception as e:
                logger.error(f"❌ [UI树] {desc}: {e}")
                self.report.capture_and_record(desc, "FAIL", str(e))
                return False
                
        # uiautomation 模式
        elif mode == 'uiautomation' and (target or class_name):
            if not UIAUTOMATION_AVAILABLE or not self.auto_window:
                logger.error("❌ uiautomation 未连接")
                self.report.capture_and_record(desc, "FAIL", "未连接")
                return False
            try:
                elem = self._get_uia_element(target=target, control_type=control_type, class_name=class_name)
                # 尝试使用 ValuePattern 直接写入，失败则用 SendKeys 模拟键盘
                # （原来用 hasattr(elem,'GetValuePattern') 判断——如果 elem 是没有具体
                # 类型化的通用 Control 对象，这个方法根本不存在，hasattr 恒为 False，
                # 于是永远走 SendKeys 慢路径。改用兼容 helper，两种控件对象都能命中。）
                vp = self._get_value_pattern(elem)
                if vp:
                    vp.SetValue(str(text))
                else:
                    elem.SendKeys(str(text), waitTime=0.1)
                if press_enter: elem.SendKeys('{Enter}', waitTime=0.1)
                if screenshot_delay > 0: time.sleep(screenshot_delay)
                logger.info(f"✅ [UIA] {desc}")
                self.report.capture_and_record(desc, "PASS", text[:30])
                return True
            except Exception as e:
                logger.error(f"❌ [UIA] {desc}: {e}")
                self.report.capture_and_record(desc, "FAIL", str(e))
                return False
        # 全局模式
        else:
            try:
                if method == 'paste':
                    pyperclip.copy(str(text))
                    pyautogui.hotkey('ctrl', 'v')
                else:
                    pyautogui.write(str(text), interval=0.05)
                if press_enter: pyautogui.press('enter')                
                if screenshot_delay > 0: time.sleep(screenshot_delay)
                logger.info(f"✅ [全局] {desc}")
                self.report.capture_and_record(desc, "PASS")
                return True
            except Exception as e:
                logger.error(f"❌ [全局] {desc}: {e}")
                self.report.capture_and_record(desc, "FAIL", str(e))
                return False

    # ==================== pywinauto 专属操作 API ====================
    def _get_ui_element(self, target=None, control_type=None, class_name=None):
        """内部方法：获取 pywinauto 控件对象（仅限当前窗口内）"""
        if not PYWINAUTO_AVAILABLE or not self.main_window:
            raise RuntimeError("❌ pywinauto 未连接")
        kwargs = {}
        if target: kwargs['title'] = target
        if control_type: kwargs['control_type'] = control_type
        if class_name: kwargs['class_name'] = class_name
        if not kwargs: raise ValueError("❌ 至少提供 target/control_type/class_name 之一")
        elem = self.main_window.child_window(**kwargs)
        try:
            elem.wrapper_object()
            return elem
        except Exception:
            logger.error(f"❌ 找不到控件: {kwargs}")
            raise

    # ==================== uiautomation 专属操作 API ====================
    def click_control_uia(self, target=None, control_type='Button', class_name=None, screenshot_delay=0.5):
        """[UIA] 控件级直接点击（发送UIA消息，无视遮挡）"""
        desc = f"[UIA] 直接点击"
        if target: desc += f" '{target}'"
        if class_name: desc += f" (class={class_name})"
        try:
            elem = self._get_uia_element(target=target, control_type=control_type, class_name=class_name)
            if elem.Exists(3, 1):
                elem.Click()
                if screenshot_delay > 0: time.sleep(screenshot_delay)
                logger.info(f"✅ {desc}")
                self.report.capture_and_record(desc, "PASS")
                return True
            else:
                logger.warning(f"⚠️ {desc} 未找到控件")
                self.report.capture_and_record(desc, "FAIL", "未找到")
                return False
        except Exception as e:
            logger.error(f"❌ {desc}: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return False

    def get_control_text_uia(self, target=None, control_type=None, class_name=None):
        """[UIA] 获取控件文本内容（毫秒级，100%准确）"""
        desc = "[UIA] 获取控件文本"
        if target: desc += f" '{target}'"
        if class_name: desc += f" (class={class_name})"
        try:
            elem = self._get_uia_element(target=target, control_type=control_type, class_name=class_name)
            text = ""
            # 1. 尝试获取 ValuePattern (适用于 Edit/输入框)
            try:
                val_pattern = self._get_value_pattern(elem)
                if val_pattern:
                    text = val_pattern.Value
            except:
                pass
            # 2. 尝试获取 Name 属性
            if not text:
                text = elem.Name
            # 3. 尝试获取 TextPattern (适用于 Document/Text)
            if not text:
                try:
                    text_pattern = elem.GetTextPattern()
                    if text_pattern:
                        text = text_pattern.DocumentRange.GetText()
                except:
                    pass
            logger.info(f"✅ {desc} -> '{str(text)[:50]}'")
            self.report.capture_and_record(desc, "PASS", str(text)[:50])
            return text
        except Exception as e:
            logger.error(f"❌ {desc}: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return None

    def wait_for_control_uia(self, target=None, state='visible', timeout=10, control_type=None, class_name=None):
        """[UIA] 等待控件达到指定状态（主要利用 Exists 的等待机制）"""
        desc = f"[UIA] 等待 '{target or class_name}' {state}"
        try:
            elem = self._get_uia_element(target=target, control_type=control_type, class_name=class_name)
            # uiautomation 的 Exists 方法自带轮询等待功能
            exists = elem.Exists(timeout, 1)
            if exists:
                logger.info(f"✅ {desc}")
                self.report.capture_and_record(desc, "PASS")
                return True
            else:
                raise TimeoutError(f"等待 {timeout}s 后控件仍未出现")
        except Exception as e:
            logger.error(f"❌ {desc}: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return False

    def select_control_uia(self, target=None, item_text='', control_type='ComboBox', class_name=None):
        """[UIA] 下拉框选择指定项"""
        desc = f"[UIA] 选择 '{item_text}'"
        if target:
            desc += f" in '{target}'"
        try:
            elem = self._get_uia_element(target=target, control_type=control_type, class_name=class_name)
            if elem.Exists(3, 1):
                # uiautomation 的 ComboBox 选择逻辑：展开并点击 ListItem
                elem.Expand()
                time.sleep(0.3)
                item = elem.ListItemControl(Name=item_text)
                if item.Exists(3, 1):
                    item.Click()
                    logger.info(f"✅ {desc}")
                    self.report.capture_and_record(desc, "PASS")
                    return True
                else:
                    raise ValueError(f"下拉列表中未找到 '{item_text}'")
            else:
                raise RuntimeError("未找到下拉框控件")
        except Exception as e:
            logger.error(f"❌ {desc}: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return False

    # ==================== 弹窗查找辅助方法 ====================
    def _normalize_window_title(self, title):
        """规范化窗口标题：去除普通空格、全角空格、零宽字符，转小写。
        用于解决标题里多了空格导致匹配失败的问题。"""
        return re.sub(r"[\s\u00a0\u200b]+", "", str(title or "")).strip().lower()

    def _get_target_pid_for_popup(self):
        """获取当前被测软件 PID。
        查找弹窗时优先匹配同进程窗口，避免误找到其他软件的同名窗口。"""
        try:
            if self.proc and getattr(self.proc, "pid", None):
                return self.proc.pid
        except Exception:
            pass
        try:
            hwnd = _extract_hwnd(self.main_window or self.auto_window)
        except Exception:
            hwnd = None
        if hwnd:
            try:
                return win32gui.GetWindowThreadProcessId(hwnd)[1]
            except Exception:
                return None
        return None

    def _list_top_windows_for_debug(self, only_visible=True, limit=50):
        """打印当前顶层窗口标题，方便确认真实弹窗标题。
        当你找不到弹窗时，可以先调用：bot._list_top_windows_for_debug()"""
        rows = []
        def enum_cb(hwnd, _):
            try:
                if not win32gui.IsWindow(hwnd): return True
                if only_visible and not win32gui.IsWindowVisible(hwnd): return True
                title = win32gui.GetWindowText(hwnd)
                if not title or not title.strip(): return True
                try: pid = win32gui.GetWindowThreadProcessId(hwnd)[1]
                except Exception: pid = 0
                rows.append((hwnd, pid, title))
            except Exception: pass
            return True
        try: win32gui.EnumWindows(enum_cb, None)
        except Exception as e:
            logger.warning(f"⚠️ 枚举顶层窗口失败: {e}")
            return []
        logger.info(f"🔎 当前{'可见' if only_visible else ''}顶层窗口共 {len(rows)} 个，显示前 {min(limit, len(rows))} 个：")
        for hwnd, pid, title in rows[:limit]:
            logger.info(f"   hwnd={hwnd:<8} pid={pid:<6} title='{title}'")
        return rows

    def _find_window_hwnd_by_title(self, titles=None, title_regex=None, timeout=5,
                                   prefer_same_process=True, match_visible=True):
        """通过窗口标题查找顶层窗口 hwnd。
        不使用 uiautomation 全局搜索，避免 UIA 树卡死。
        :param titles: 标题字符串或列表
        :param title_regex: 标题正则表达式
        :param timeout: 超时时间
        :param prefer_same_process: 是否优先匹配当前被测软件同进程窗口
        :param match_visible: 是否只匹配可见窗口
        :return: (hwnd, window_title)
        """
        if isinstance(titles, str):
            titles = [titles]
        titles = [str(t) for t in titles if t]
        norm_titles = [self._normalize_window_title(t) for t in titles]
        
        if not titles and not title_regex:
            logger.error("❌ _find_window_hwnd_by_title：titles 和 title_regex 不能同时为空")
            return None, None
            
        compiled_regex = None
        if title_regex:
            try: compiled_regex = re.compile(title_regex)
            except re.error as e:
                logger.error(f"❌ 弹窗标题正则表达式错误: {title_regex}")
                compiled_regex = None
                
        target_pid = self._get_target_pid_for_popup() if prefer_same_process else None
        logger.info(f"⏳ 等待弹窗: titles={titles}, regex={title_regex}, timeout={timeout}s, target_pid={target_pid}")
        
        end_time = time.time() + timeout
        while time.time() < end_time:
            candidates = []
            def enum_cb(hwnd, _):
                try:
                    if not win32gui.IsWindow(hwnd): return True
                    if match_visible and not win32gui.IsWindowVisible(hwnd): return True
                    title = win32gui.GetWindowText(hwnd)
                    if not title or not title.strip(): return True
                    try: pid = win32gui.GetWindowThreadProcessId(hwnd)[1]
                    except Exception: pid = 0
                    
                    norm_title = self._normalize_window_title(title)
                    score = 0
                    # 正则匹配
                    if compiled_regex:
                        try:
                            if compiled_regex.search(title): score = max(score, 5000)
                        except Exception: pass
                    # 标题列表匹配
                    for idx, t in enumerate(titles):
                        nt = norm_titles[idx]
                        if nt and norm_title == nt: score = max(score, 4000 - idx)
                        elif nt and nt in norm_title: score = max(score, 3000 - idx)
                        elif t and t in title: score = max(score, 2500 - idx)
                    if score <= 0: return True
                    # 同进程加分
                    if target_pid and pid == target_pid: score += 2000
                    # 前台窗口加分
                    try:
                        if hwnd == win32gui.GetForegroundWindow(): score += 1000
                    except Exception: pass
                    # 窗口面积加分，作为 tie-breaker
                    try:
                        rect = win32gui.GetWindowRect(hwnd)
                        width = max(0, rect[2] - rect[0])
                        height = max(0, rect[3] - rect[1])
                        area = width * height
                        score += min(area // 10000, 200)
                    except Exception: pass
                    candidates.append((score, hwnd, title, pid))
                except Exception: pass
                return True
            try: win32gui.EnumWindows(enum_cb, None)
            except Exception as e: logger.warning(f"⚠️ EnumWindows 异常: {e}")
            
            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                best_score, best_hwnd, best_title, best_pid = candidates[0]
                logger.info(f"✅ 找到候选弹窗: hwnd={best_hwnd}, pid={best_pid}, score={best_score}, title='{best_title}'")
                return best_hwnd, best_title
            time.sleep(0.3)
        logger.warning(f"⚠️ 未在 {timeout}s 内找到弹窗: titles={titles}, regex={title_regex}")
        return None, None

    def _extract_edit_from_combo(self, combo):
        """从 ComboBox 中提取【真正可输入】的 Edit 子控件。
        背景：Windows 标准"打开/保存/导入"文件对话框里，"文件名"输入框是一个 ComboBox，
        其内部 = Edit(可打字) + Button(下拉三角▼)。
        直接对 ComboBox 调 ValuePattern.SetValue 常常"写进去但不显示"，
        Click 容器也容易点到下拉三角。因此必须深入拿到内部的 Edit 再操作。
        :return: Edit 控件对象；找不到返回 None
        """
        # 方式1：uiautomation 便捷方法，在 combo 子树内找 Edit
        try:
            edit = combo.EditControl(searchDepth=3)
            if edit is not None and edit.Exists(1, 0.3): return edit
        except Exception: pass
        # 方式2：手动递归子节点，兜底找第一个 Edit
        def _walk(ctrl, depth=0):
            if depth > 4: return None
            try: children = ctrl.GetChildren()
            except Exception: return None
            for c in children:
                try:
                    if c.ControlTypeName == "Edit": return c
                except Exception: pass
                r = _walk(c, depth + 1)
                if r is not None: return r
            return None
        try: return _walk(combo)
        except Exception: return None

    def _pick_editable_combo(self, base_kwargs, max_try=3):
        """在弹窗内挑选【可编辑】的 ComboBox（即"文件名"框）。
        判别法：含 Edit 子控件 = 可编辑 = 文件名框；不含 Edit = 纯下拉 = 文件类型框，跳过。
        最多尝试 max_try 个 found_index，避免误选文件类型框。"""
        for idx in range(1, max_try + 1):
            kw = dict(base_kwargs)
            kw['found_index'] = idx
            try:
                c = self._get_uia_element(require_exists=False, **kw)
            except Exception:
                break
            if not c.Exists(1, 0.3):
                break
            if self._extract_edit_from_combo(c) is not None:
                logger.info(f"✅ 第 {idx} 个 ComboBox 含可编辑 Edit，判定为‘文件名’输入框")
                return c
            logger.info(f"⏭️ 第 {idx} 个 ComboBox 不含 Edit（疑似‘文件类型’框），跳过")
        return None

    def _pick_target_button(self, root=None, target_button_text=None,
                            target_button_regex=None, target_button_automation_id=None,
                            target_button_class_name=None, search_depth=15, timeout=3):
        """在弹窗内智能挑选真正的'打开/确认'按钮，结构性排除 ComboBox 的下拉三角 ▼。
        ▼ 的中心点必落在某 ComboBox 矩形内 → in_combo=True → -5000（死刑线）。"""
        if root is None:
            root = self.auto_window
        if root is None:
            return None

        # 刷新 root，防 SetValue/焦点变化后 stale
        try:
            hwnd = _extract_hwnd(root)
            if hwnd:
                fresh = auto.ControlFromHandle(hwnd)
                if fresh is not None: 
                    root = fresh
        except Exception as e:
            logger.warning(f"⚠️ [挑选打开按钮] 刷新 root 失败: {e}")
            
        compiled = re.compile(target_button_regex) if target_button_regex else None
        strip_target = self._normalize_window_title(target_button_text).replace("&", "") if target_button_text else ""
        
        def _rect(ctrl):
            try:
                r = ctrl.BoundingRectangle
                return (r.left, r.top, r.right, r.bottom) if hasattr(r, "left") else tuple(r[:4])
            except Exception: 
                return None
            
        def _collect(ctor, max_n=200):
            """foundIndex 条件枚举"""
            out = []
            for i in range(1, max_n + 1):
                try:
                    c = ctor(searchFromControl=root, foundIndex=i, searchDepth=search_depth, searchInterval=0.05)
                    if not c.Exists(0, 0): 
                        break
                    out.append(c)
                except Exception: 
                    break
            return out
            
        def _center_in_any(rect, boxes):
            if not rect or not boxes: 
                return False
            cx, cy = (rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0
            return any(cl <= cx <= cr and ct <= cy <= cb for (cl, ct, cr, cb) in boxes)
            
        try:
            fast_names = []
            # 修复: 将未定义的 target 改为 target_button_text
            if target_button_text:
                if isinstance(target_button_text, (list, tuple)):
                    fast_names.extend(target_button_text)
                else:
                    fast_names.append(target_button_text)
            for fast_name in fast_names:
                try:
                    fast_btn = root.ButtonControl(Name=fast_name, searchDepth=8)
                    if fast_btn.Exists(0, 0):
                        logger.info(f"⚡ 快速定位目标按钮: {fast_name!r}")
                        return fast_btn
                except Exception: continue
        except Exception: pass
        
        _refind = getattr(getattr(auto, "Control", None), "ReFind", None)
        _orig_defaults = getattr(_refind, "__defaults__", None) if _refind else None
        _patched = False
        if _refind is not None:
            try:
                auto.Control.ReFind.__defaults__ = (0.3, 0.05)
                _patched = True
            except Exception: pass
            
        end = time.time() + max(0.5, timeout)
        while time.time() < end:
            t0 = time.perf_counter()
            buttons = _collect(auto.ButtonControl)
            combos = _collect(auto.ComboBoxControl)
            combo_rects = [r for r in (_rect(c) for c in combos) if r]
            
            if not buttons:
                time.sleep(0.3)
                continue
                
            try:
                pr = _rect(root)
                pop_h = max(1, (pr[3] - pr[1])) if pr else 1
                pop_top = pr[1] if pr else 0
            except Exception:
                pop_h, pop_top = 1, 0
                
            best, best_score, best_in_combo = None, -1, True
            for ctrl in buttons:
                try:
                    name = ctrl.Name or ""
                    rect = _rect(ctrl)
                except Exception: continue
                if not rect or (rect[2] - rect[0]) <= 0 or (rect[3] - rect[1]) <= 0: continue
                
                in_combo = _center_in_any(rect, combo_rects)
                score = 0
                if target_button_automation_id:
                    try:
                        if ctrl.AutomationId == target_button_automation_id: score += 3000
                    except Exception: pass
                if target_button_text and name == target_button_text: score += 1000
                if target_button_text and self._normalize_window_title(name).replace("&", "") == strip_target: score += 800
                if compiled and compiled.search(name): score += 900
                if name and ("打开" in name or name.strip().lower().startswith("open")): score += 200
                if target_button_class_name:
                    try:
                        if ctrl.ClassName == target_button_class_name:
                            score += 100
                    except Exception:
                        pass
                score += int(((rect[1] - pop_top) / pop_h) * 300)   # 越靠底越像确认按钮
                if in_combo:
                    score -= 5000                                    # ★ 下拉三角 ▼ 死刑线
                if score > best_score:
                    best, best_score, best_in_combo = ctrl, score, in_combo
                    
            if best is not None and best_score > 0 and not best_in_combo:
                logger.info(f"✅ [挑选打开按钮] 选中 name={best.Name!r} score={best_score}")
                return best
            time.sleep(0.3)
        logger.warning("⚠️ [挑选打开按钮] 超时未找到合格按钮")
        return None     

    # ==================== 打开文件窗口,文件选择弹窗专用 API ====================   
    ## 缩短搜索深度 control_search_depth=5足够，可缩短查找时长。 
    def select_file_in_open_dialog(self, file_path, popup_title="导入数据", popup_title_regex=None, base_dir=None,
                                   input_control_type="ComboBox", input_target=None, input_class_name=None,
                                   input_automation_id=None, input_found_index=1, target_button_text="打开(O)",
                                   target_button_regex=None, target_button_class_name=None, target_button_automation_id=None,
                                   target_button_found_index=1, popup_timeout=5, control_timeout=0.6, control_search_depth=5,
                                   screenshot_delay=2, after_open_delay=1, clear_before=True, input_method="setvalue",# setvalue/paste/auto
                                   check_file_exists=False, raise_on_error=False, prefer_same_process=True,
                                   match_visible=True, list_windows_on_fail=True, allow_uia_fallback=False,
                                   prefer_editable_combo=False):
        """在独立弹出的"打开文件 / 导入数据"窗口中选择文件。
        修复版：
            1. 优先使用 win32gui.EnumWindows 根据标题查找弹窗 hwnd；
            2. 找到 hwnd 后使用 auto.ControlFromHandle(hwnd) 绑定 UIA；
            3. 避免直接使用 auto.WindowControl(Name=...) 全局搜索导致 UIA 卡死；
            4. 标题匹配支持精确、去空格、包含、正则；
            5. 失败时可自动打印当前顶层窗口标题，方便排查真实标题。
        :param file_path: 文件路径（绝对或相对）
        :param popup_title: 弹窗标题，支持字符串或列表
        :param popup_title_regex: 弹窗标题正则表达式
        :param base_dir: 相对路径基础目录
        :param input_control_type: 文件路径输入框控件类型，默认 ComboBox
        :param target_button_text: 打开按钮文本
        :param target_button_regex: 打开按钮正则
        :param popup_timeout: 等待弹窗出现超时时间
        :param control_timeout: 等待输入框/打开按钮超时时间
        :param input_method: 输入方式 auto/setvalue/paste/sendkeys
        :param prefer_same_process: 是否优先查找被测软件同进程弹窗
        :param match_visible: 是否只匹配可见窗口
        :param list_windows_on_fail: 找不到弹窗时是否打印当前顶层窗口列表
        :param allow_uia_fallback: 是否允许在 win32 找不到时回退到 UIA 局部搜索
        :param prefer_editable_combo: 是否自动挑选含 Edit 的可编辑 ComboBox,False为关闭二次扫描
        :return: True 成功 / False 失败
        """
        action_desc = "文件选择弹窗-打开或保存文件"
        # ---------- 0. 基础检查 ----------
        if not UIAUTOMATION_AVAILABLE:
            msg = "uiautomation 未安装或不可用"
            logger.error(f"❌ {msg}")
            self.report.capture_and_record(action_desc, "FAIL", msg)
            if raise_on_error:
                raise RuntimeError(msg)
            return False
        if not file_path:
            msg = "file_path 不能为空"
            logger.error(f"❌ {msg}")
            self.report.capture_and_record(action_desc, "FAIL", msg)
            if raise_on_error:
                raise ValueError(msg)
            return False
            
        try:
            if os.path.isabs(file_path):
                full_path = os.path.normpath(file_path)
            else:
                if isinstance(base_dir, str) and base_dir.lower() == "script":
                    import sys
                    base_path = os.path.dirname(os.path.abspath(sys.argv[0])) if getattr(sys, "argv", None) and sys.argv and sys.argv[0] else os.getcwd()
                else:
                    base_path = base_dir if base_dir else os.getcwd()
                full_path = os.path.normpath(os.path.join(base_path, file_path))
            logger.info(f"📂 文件选择弹窗准备输入路径: {full_path}")
            if check_file_exists and not os.path.exists(full_path):
                msg = f"文件不存在: {full_path}"
                logger.error(f"❌ {msg}")
                self.report.capture_and_record(action_desc, "FAIL", msg)
                if raise_on_error:
                    raise FileNotFoundError(msg)
                return False
        except Exception as e:
            msg = f"路径处理失败: {e}"
            logger.error(f"❌ {msg}")
            self.report.capture_and_record(action_desc, "FAIL", msg)
            if raise_on_error:
                raise
            return False

        # ---------- 2. 整理弹窗标题 ----------
        titles = popup_title if isinstance(popup_title, list) else [popup_title]
        titles = [str(t) for t in titles if t]
        if not titles and not popup_title_regex:
            msg = "popup_title 和 popup_title_regex 不能同时为空"
            logger.error(f"❌ {msg}")
            self.report.capture_and_record(action_desc, "FAIL", msg)
            if raise_on_error:
                raise ValueError(msg)
            return False
            
        # ---------- 3. 查找并绑定弹窗 ----------
        original_auto_window = self.auto_window
        popup_window = None
        popup_hwnd = None
        popup_real_title = ""
        
        try:
            # 3.1 优先使用 win32gui 查找顶层窗口 hwnd
            popup_hwnd, popup_real_title = self._find_window_hwnd_by_title(
                titles=titles, title_regex=popup_title_regex, timeout=popup_timeout,
                prefer_same_process=prefer_same_process, match_visible=match_visible
            )
            if popup_hwnd:
                try:
                    popup_window = auto.ControlFromHandle(popup_hwnd)
                except Exception as e:
                    logger.warning(f"⚠️ 绑定失败: {e}")
                    popup_window = None
                    
            # 3.2 可选：UIA 局部回退（默认关闭，因为 UIA 搜索可能卡住）
            if not popup_window and allow_uia_fallback and self.auto_window:
                logger.info("⏳ win32 未找到弹窗，尝试 UIA 局部回退查找...")
                fallback_end = time.time() + max(1, popup_timeout)
                while time.time() < fallback_end:
                    try:
                        if popup_title_regex:
                            ctrl = auto.WindowControl(RegexName=popup_title_regex, searchFromControl=self.auto_window, searchDepth=8)
                            if ctrl.Exists(0, 0):
                                popup_window = ctrl
                                popup_real_title = ctrl.Name
                                popup_hwnd = _extract_hwnd(ctrl)
                                break
                        else:
                            for t in titles:
                                fuzzy_regex = f".*{re.escape(t)}.*"
                                ctrl = auto.WindowControl(RegexName=fuzzy_regex, searchFromControl=self.auto_window, searchDepth=8)
                                if ctrl.Exists(0, 0):
                                    popup_window = ctrl
                                    popup_real_title = ctrl.Name
                                    popup_hwnd = _extract_hwnd(ctrl)
                                    break
                            if popup_window:
                                break
                    except Exception as e:
                        logger.warning(f"⚠️ UIA 局部回退查找异常: {e}")
                    time.sleep(0.3)
                    
            if not popup_window:
                if list_windows_on_fail:
                    self._list_top_windows_for_debug(only_visible=True, limit=50)
                raise TimeoutError(f"未找到文件选择弹窗: title={titles}, regex={popup_title_regex}")

            # ---------- 4. 激活弹窗 ----------
            if popup_hwnd:
                self.focus_window(popup_hwnd)
            else:
                self.focus_window(popup_window)
            try:
                popup_window.SetActive()
            except Exception:
                pass
            if not popup_real_title:
                try:
                    popup_real_title = popup_window.Name
                except Exception:
                    popup_real_title = str(popup_title)
            logger.info(f"✅ 已找到文件选择弹窗: '{popup_real_title}'")
            self.report.capture_and_record("定位文件选择弹窗", "PASS", popup_real_title, images=[])
            
            # 临时切换 UIA 搜索根节点到弹窗
            self.auto_window = popup_window

            # ---------- 5. 定位文件路径输入框 ----------
            raw_input = self._get_uia_element(
                target=input_target, control_type=input_control_type, class_name=input_class_name,
                automation_id=input_automation_id, found_index=input_found_index,
                search_depth=control_search_depth, search_interval=0.3, require_exists=False
            )
            if not raw_input.Exists(control_timeout, 0.05): #轮询间隔 0.05s
                raise TimeoutError(f"未找到文件路径输入框")
                
            # ComboBox 容器 → 深入内部 Edit
            edit_box = raw_input
            if input_control_type == "ComboBox":
                # 5.1 若开启"优先可编辑框"，先确保选中的是"文件名"框而非"文件类型"框
                if prefer_editable_combo and not input_automation_id and not input_target:
                    editable_combo = self._pick_editable_combo(
                        base_kwargs=dict(target=input_target, control_type=input_control_type, class_name=input_class_name,
                                         automation_id=input_automation_id, search_depth=control_search_depth, search_interval=0.3)
                    )
                    if editable_combo is not None: 
                        raw_input = editable_combo
                # 5.2 深入取 ComboBox 内部的 Edit
                inner_edit = self._extract_edit_from_combo(raw_input)
                if inner_edit is not None:
                    edit_box = inner_edit
                    logger.info("✅ 已从 ComboBox 深入定位到内部 Edit 输入框")
                else:
                    logger.warning("⚠️ ComboBox 内未找到 Edit 子控件")
            # 点击真正的 Edit，确保焦点落在输入区
            try:
                edit_box.Click()
            except Exception:
                try:
                    edit_box.SetFocus()
                except Exception:
                    pass

            # 清空输入框
            if clear_before:
                try:
                    edit_box.SendKeys('^a{Delete}', waitTime=0.02)
                except Exception:
                    try:
                        auto.SendKeys('^a{Delete}')
                    except Exception:
                        pass

            # ---------- 6. 输入文件路径 ----------
            def _input_by_value_pattern():
                try:
                    value_pattern = self._get_value_pattern(edit_box)
                    if value_pattern:
                        value_pattern.SetValue(full_path)
                        return True
                except Exception:
                    pass
                return False
                
            def _input_by_paste():
                try:
                    edit_box.SetFocus()
                except Exception:
                    pass
                try:
                    pyperclip.copy(full_path)
                except Exception:
                    return False
                try:
                    auto.SendKeys('^v')
                    return True
                except Exception:
                    try:
                        pyautogui.hotkey('ctrl', 'v')
                        return True
                    except Exception:
                        return False

            def _input_by_sendkeys():
                try:
                    edit_box.SendKeys(full_path, waitTime=0.02)
                    return True
                except Exception:
                    return False

            input_ok = False
            if input_method in ("auto", "setvalue"):
                input_ok = _input_by_value_pattern()
            if not input_ok and input_method in ("auto", "paste"):
                input_ok = _input_by_paste()
            if not input_ok and input_method in ("auto", "sendkeys"):
                input_ok = _input_by_sendkeys()
            if not input_ok:
                raise RuntimeError("输入文件路径失败")
                
            self.report.capture_and_record("输入文件路径", "PASS", full_path, images=[])

            # ---------- 7. 定位并点击"打开"按钮 ----------
            button_desc = f"点击目标按钮: '{target_button_regex or target_button_text}'"
            # 7.1 优先：结构性智能挑选（▼ 会被 in_combo 死刑线排除）
            target_button = self._pick_target_button(
                root=self.auto_window, target_button_text=target_button_text,
                target_button_regex=target_button_regex, target_button_automation_id=target_button_automation_id,
                target_button_class_name=target_button_class_name, search_depth=control_search_depth, timeout=control_timeout,
            )
            # 7.2 回退：原有按 Name/正则 查找
            if target_button is None:
                logger.info("⏭️ 智能挑选未命中，回退原有查找")
                target_button = self._get_uia_element(
                    target=None if target_button_regex else target_button_text, control_type="Button", 
                    class_name=target_button_class_name, automation_id=target_button_automation_id, 
                    regex_name=target_button_regex, found_index=target_button_found_index, 
                    search_depth=control_search_depth, search_interval=0.3, require_exists=False,
                )
                if not target_button.Exists(control_timeout, 0.5):
                    raise TimeoutError(f"未找到目标按钮")

            # 截图 + 点击
            before_img = after_img = None
            click_x = click_y = None
            try:
                rect = target_button.BoundingRectangle
                if hasattr(rect, "left"):
                    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
                else:
                    left, top, right, bottom = rect[0], rect[1], rect[2], rect[3]
                if (right - left) > 0 and (bottom - top) > 0:
                    click_x, click_y = left + (right - left) // 2, top + (bottom - top) // 2
                    before_img = self._capture_and_mark_click_area(click_x, click_y)
            except Exception as e:
                logger.warning(f"⚠️ 目标按钮点击前截图失败: {e}")
                
            try:
                target_button.Click()
                logger.info(f"✅ {button_desc}，UIA 控件点击成功")
            except Exception as e:
                logger.warning(f"⚠️ UIA 控件点击失败，尝试坐标点击: {e}")
                if click_x is not None:
                    self._win32_click(click_x, click_y)
                    logger.info(f"✅ {button_desc}，坐标点击成功 -> ({click_x}, {click_y})")
                else:
                    raise

            if screenshot_delay > 0:
                time.sleep(screenshot_delay)
            # 点击后截图
            try:
                after_img = self._capture_screen_only()
            except Exception as e:
                logger.warning(f"⚠️ 打开按钮点击后截图失败: {e}")

            images = []
            if before_img:
                images.append(before_img)
            if after_img:
                images.append(after_img)
            self.report.capture_and_record(button_desc, "PASS", full_path, images=images if images else [])

            # 等待数据窗口加载
            if after_open_delay > 0:
                time.sleep(after_open_delay)
            logger.info(f"✅ 文件选择弹窗导入完成: {full_path}")
            return True
        except Exception as e:
            logger.error(f"❌ 文件选择弹窗导入失败: {e}")
            self.report.capture_and_record(action_desc, "FAIL", str(e))
            if raise_on_error:
                raise
            return False
        finally:
            # 无论成功失败，都必须恢复原来的 UIA 搜索范围
            self.auto_window = original_auto_window
            logger.info("🔄 已恢复原 UIA 搜索窗口范围")

    # ===================================================================
    def click_control_directly(self, target=None, control_type='Button', class_name=None, screenshot_delay=0.5, mode='pywinauto'):
        """控件级直接点击（发送Windows消息，无视遮挡）"""
        desc = f"直接点击"
        if target: desc += f" '{target}'"
        if class_name: desc += f" (class={class_name})"
        try:
            if mode == 'uiautomation':
                if not UIAUTOMATION_AVAILABLE: raise RuntimeError("uiautomation 不可用")
                elem = self._get_uia_element(target=target, control_type=control_type, class_name=class_name)
                elem.Click()
            else:
                # 原有 pywinauto 逻辑
                elem = self._get_ui_element(target=target, control_type=control_type, class_name=class_name)
                elem.click_input()
            # 点击后延迟
            if screenshot_delay > 0:
                time.sleep(screenshot_delay)
            logger.info(f"✅ [{mode.upper()}] {desc}")
            self.report.capture_and_record(desc, "PASS")
            return True
        except Exception as e:
            logger.error(f"❌ [{mode.upper()}] {desc}: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return False

    def get_control_text(self, target=None, control_type=None, class_name=None):
        """获取控件文本内容（毫秒级，100%准确）"""
        desc = "获取控件文本"
        if target:
            desc += f" '{target}'"
        if class_name:
            desc += f" (class={class_name})"
        try:
            elem = self._get_ui_element(target=target, control_type=control_type, class_name=class_name)
            text = ""
            # 按优先级尝试不同的获取文本方法，兼容 win32 和 uia
            # 1. win32 Edit 控件专属方法
            if hasattr(elem, 'text_block'):
                try:
                    text = elem.text_block()
                except:
                    pass
            # 2. uia Edit/Document 控件方法
            if not text and hasattr(elem, 'get_value'):
                try:
                    text = elem.get_value()
                except:
                    pass
            # 3. 通用窗口文本
            if not text and hasattr(elem, 'window_text'):
                try:
                    text = elem.window_text()
                except:
                    pass
            # 4. 兜底方案
            if not text:
                try:
                    texts = elem.texts()
                    text = "".join([t for t in texts if t])
                except:
                    pass
            logger.info(f"✅ [UI树] {desc} -> '{str(text)[:50]}'")
            self.report.capture_and_record(desc, "PASS", str(text)[:50])
            return text
        except Exception as e:
            logger.error(f"❌ [UI树] {desc}: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return None

    def get_control_property(self, target=None, property_name='enabled', control_type=None, class_name=None):
        """获取控件属性（如 enabled, visible, rectangle 等）"""
        desc = f"获取属性 '{property_name}'"
        if target:
            desc += f" '{target}'"
        try:
            elem = self._get_ui_element(target=target, control_type=control_type, class_name=class_name)
            props = elem.get_properties()
            val = props.get(property_name)
            logger.info(f"✅ [UI树] {desc} -> {val}")
            self.report.capture_and_record(desc, "PASS", str(val))
            return val
        except Exception as e:
            logger.error(f"❌ [UI树] {desc}: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return None

    def check_control(self, target=None, is_checked=True, control_type='CheckBox', class_name=None):
        """勾选/取消勾选复选框"""
        desc = f"{'勾选' if is_checked else '取消'} '{target or class_name}'"
        try:
            elem = self._get_ui_element(target=target, control_type=control_type, class_name=class_name)
            if is_checked:
                elem.check()
            else:
                elem.uncheck()
            logger.info(f"✅ [UI树] {desc}")
            self.report.capture_and_record(desc, "PASS")
            return True
        except Exception as e:
            logger.error(f"❌ [UI树] {desc}: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return False

    def select_control(self, target=None, item_text='', control_type='ComboBox', class_name=None):
        """下拉框选择指定项"""
        desc = f"选择 '{item_text}'"
        if target:
            desc += f" in '{target}'"
        try:
            elem = self._get_ui_element(target=target, control_type=control_type, class_name=class_name)
            elem.select(item_text)
            logger.info(f"✅ [UI树] {desc}")
            self.report.capture_and_record(desc, "PASS")
            return True
        except Exception as e:
            logger.error(f"❌ [UI树] {desc}: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return False

    def wait_for_control(self, target=None, state='visible', timeout=10, control_type=None, class_name=None):
        """等待控件达到指定状态（exists/visible/enabled/ready）"""
        desc = f"等待 '{target or class_name}' {state}"
        try:
            elem = self._get_ui_element(target=target, control_type=control_type, class_name=class_name)
            elem.wait(state, timeout=timeout)
            logger.info(f"✅ [UI树] {desc}")
            self.report.capture_and_record(desc, "PASS")
            return True
        except Exception as e:
            logger.error(f"❌ [UI树] {desc}: {e}")
            self.report.capture_and_record(desc, "FAIL", str(e))
            return False   
            
    def generate_report(self):
        """生成并打开 HTML 报告"""
        self.report.generate_html()
        try:
            # 使用动态生成的带软件名的文件名
            report_path = os.path.join(self.report.report_dir, self.report.report_filename)
            os.startfile(os.path.abspath(report_path))
        except Exception as e:
            logger.warning(f"⚠️ 自动打开报告失败: {e}")