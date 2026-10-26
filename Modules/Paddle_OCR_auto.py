
import hashlib
import tkinter as tk
from tkinter import scrolledtext
from tkinter import messagebox, ttk
import psutil
import os
import sys
import configparser
import time
import base64
import io
import cv2
import numpy as np
import tempfile
import shutil
import math
import random
import argparse
import glob
from pathlib import Path
import mss
from PIL import Image
import atexit

# 解决 Windows 高 DPI 缩放导致截图不完整/坐标偏移的问题
import ctypes
try:
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

# ====== PaddleOCR-json 相关导入 ======
try:
    from Modules.PPOCR_api import GetOcrApi
except ImportError:
    print("错误：未找到 PPOCR_api 模块，请先安装 paddleocr-json-python 包")
    print("安装命令: pip install paddleocr-json-python")
    sys.exit(1)

# 获取程序目录（支持打包后运行）
def get_application_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

application_path = get_application_path()
paddleocr_path = os.path.join(application_path, "PaddleOCR-json", "PaddleOCR-json.exe")

# 检查 PaddleOCR-json.exe 是否存在
if not os.path.exists(paddleocr_path):
    print(f"错误：未找到 PaddleOCR-json.exe，路径：{paddleocr_path}")
    print("请确保已将 PaddleOCR-json 文件夹放在程序目录下")
    sys.exit(1)

class OCRClickAssistant:
    def __init__(self, config_file='config.ini'):
        self.config = configparser.ConfigParser()
        self.config_file = config_file
        self.load_config()
        
        # 验证click_delay的类型和值
        if not isinstance(self.click_delay, (int, float)) or self.click_delay < 0:
            print(f"警告: click_delay值异常 ({self.click_delay})，使用默认值0.1")
            self.click_delay = 0.1
        
        # 获取屏幕尺寸
        self.screen_width, self.screen_height = self.get_screen_size()
        print(f"屏幕尺寸: {self.screen_width}x{self.screen_height}")
        
        # 设置pyautogui安全措施（仅在PC模式下需要）
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.1
            self.pyautogui_available = True
        except ImportError:
            print("警告: 未安装 pyautogui，PC模式点击功能不可用")
            self.pyautogui_available = False
        
        # 初始化 PaddleOCR-json 引擎
        # print(f"正在初始化 PaddleOCR-json 引擎: {paddleocr_path}")
        print(f"正在初始化 PaddleOCR-json 引擎。")
        try:
            self.ocr_engine = GetOcrApi(paddleocr_path)
            print("PaddleOCR-json 引擎初始化成功。")
        except Exception as e:
            print(f"初始化 PaddleOCR-json 失败! {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        
        # 创建高速临时目录（使用系统默认 temp 目录，通常在 SSD 上）
        self.temp_dir = tempfile.mkdtemp(prefix="paddleocr_fast_")
        print(f"OCR临时目录: {self.temp_dir}")
        
        # 注册退出清理
        atexit.register(self.cleanup_temp_files)    
        self.screenshot_image = None  # 用于存储当前截图图像（BGR格式）
        
    def cleanup_temp_files(self):
        """清理临时文件目录"""
        try:
            if os.path.exists(self.temp_dir):
                # 先删除目录内所有文件
                for fname in os.listdir(self.temp_dir):
                    try:
                        os.remove(os.path.join(self.temp_dir, fname))
                    except:
                        pass
                # 再删除目录
                os.rmdir(self.temp_dir)
                print(f"已清理临时目录: {self.temp_dir}")
        except Exception as e:
            print(f"清理临时目录时出错: {e}")

    def get_screen_size(self):
        """获取准确的屏幕尺寸"""
        try:
            import pyautogui
            return pyautogui.size()
        except:
            # 如果所有方法都失败，使用默认值
            return (1920, 1080)  # 常见的默认分辨率

    def load_config(self):
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            self.create_default_config()
        
        self.config.read(self.config_file, encoding='utf-8')
        
        # 获取配置项
        self.screenshot_type = self.config.get('Settings', 'screenshot_type', fallback='pc')
        self.device_ip = self.config.get('Settings', 'device_ip', fallback='')
        self.click_delay = self.config.getfloat('Settings', 'click_delay', fallback=0.2)
        self.click_precision = self.config.getfloat('Settings', 'click_precision', fallback=0.8)
        self.mouse_move_mode = self.config.get('Settings', 'mouse_move_mode', fallback='instant')  # instant或human
        
        # 关键词过滤配置
        self.required_keywords = [kw.strip() for kw in self.config.get('Filter', 'required_keywords', fallback='').split(',') if kw.strip()]
        self.enable_filter = self.config.getboolean('Filter', 'enable_filter', fallback=False)
        
        # 颜色过滤配置
        self.enable_color_filter = self.config.getboolean('ColorFilter', 'enable_color_filter', fallback=False)
        self.clickable_colors = [c.strip() for c in self.config.get('ColorFilter', 'clickable_colors', fallback='black').split(',') if c.strip()]
        self.non_clickable_colors = [c.strip() for c in self.config.get('ColorFilter', 'non_clickable_colors', fallback='red').split(',') if c.strip()]
        self.return_rgb_value = self.config.getboolean('ColorFilter', 'return_rgb_value', fallback=True)

    def create_default_config(self):
        """创建默认配置文件"""
        self.config['Settings'] = {
            'screenshot_type': 'phone',           # pc 或 phone
            'device_ip': '',                      # 手机设备IP，留空则自动连接第一个设备
            'click_delay': '0.2',                 # 点击前的延迟（秒）
            'click_precision': '0.8',             # 点击精度（0-1，越高越精确）
            'mouse_move_mode': 'instant'          # instant:直接瞬移, human:模拟人工移动
        }
        
        self.config['Filter'] = {
            'enable_filter': 'False',             # 是否启用关键词过滤
            'required_keywords': '公司'
        }
        
        self.config['ColorFilter'] = {
            'enable_color_filter': 'True',        # 是否启用颜色过滤
            'clickable_colors': 'white,black,light_color,dark_color',  # 可点击的颜色
            'non_clickable_colors': 'red',        # 不可点击的颜色
            'return_rgb_value': 'True'            # 是否返回RGB颜色值
        }
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)
        print(f"已创建默认配置文件: {self.config_file}")

    def check_keywords_filter(self, text, reference_text=None):
        """检查文本是否包含所有必需的关键词"""
        if not self.enable_filter:
            return True  # 不过滤，始终返回True
        
        if not self.required_keywords:
            return True  # 没有设置关键词，不过滤
        
        # 检查目标文本是否包含所有必需关键词
        target_contains_all = all(keyword in text for keyword in self.required_keywords)
        
        # 如果参考文本也存在，检查参考文本是否包含所有必需关键词
        if reference_text:
            reference_contains_all = all(keyword in reference_text for keyword in self.required_keywords)
            # 只要目标文本或参考文本包含所有关键词就通过
            return target_contains_all or reference_contains_all
        
        return target_contains_all

    def get_text_color(self, box_coords, return_rgb=True):
        """改进版：根据OCR返回的坐标框获取文字颜色（通过采样文字边缘像素，对小字体更鲁棒）
        Args:
            box_coords: OCR返回的坐标框
            return_rgb: 是否返回RGB值
        Returns:
            如果return_rgb=True: (r, g, b) 或 None
            如果return_rgb=False: 颜色名称字符串
        """
        if self.screenshot_image is None:
            print("警告: 没有可用的截图图像")
            return None if return_rgb else "unknown"

        try:
            # 提取文本框坐标
            x_coords = [point[0] for point in box_coords if len(point) >= 2]
            y_coords = [point[1] for point in box_coords if len(point) >= 2]
            if not x_coords or not y_coords:
                return None if return_rgb else "unknown"

            x_min, x_max = int(min(x_coords)), int(max(x_coords))
            y_min, y_max = int(min(y_coords)), int(max(y_coords))

            # 确保坐标在图像范围内
            img_height, img_width = self.screenshot_image.shape[:2]
            x_min = max(0, min(x_min, img_width - 1))
            x_max = max(0, min(x_max, img_width - 1))
            y_min = max(0, min(y_min, img_height - 1))
            y_max = max(0, min(y_max, img_height - 1))

            # 提取文本框区域
            text_region = self.screenshot_image[y_min:y_max, x_min:x_max]
            if text_region.size == 0:
                return None if return_rgb else "unknown"

            # 转换为灰度图并进行边缘检测
            gray = cv2.cvtColor(text_region, cv2.COLOR_BGR2GRAY)
            # 对于小字体，降低Canny的阈值以检测更细微的边缘
            edges = cv2.Canny(gray, 30, 100)  # 关键修改：降低阈值

            # 找到边缘像素的坐标
            edge_points = np.column_stack(np.where(edges > 0))  # 返回 (y, x) 坐标

            if len(edge_points) == 0:
                print("警告: 未检测到任何边缘，使用文本框中心点颜色")
                center_y, center_x = (y_max - y_min) // 2, (x_max - x_min) // 2
                b, g, r = text_region[center_y, center_x]
            else:
                # 采样边缘像素的颜色
                sampled_colors = []
                # 采样所有边缘点，因为小字体的边缘点本身就不多
                for y, x in edge_points:
                    b, g, r = text_region[y, x]
                    sampled_colors.append([r, g, b])

                # 计算采样颜色的中位数（对异常值鲁棒）
                sampled_colors = np.array(sampled_colors)
                r, g, b = np.median(sampled_colors, axis=0).astype(int)

            r, g, b = int(r), int(g), int(b)
            print(f"检测到的文字颜色 - R:{r}, G:{g}, B:{b}")

            if return_rgb:
                return (r, g, b)
            return self._classify_color(r, g, b)

        except Exception as e:
            print(f"颜色识别失败: {e}")
            import traceback
            traceback.print_exc()
            return None if return_rgb else "unknown"

    def _classify_color(self, r, g, b):
        """根据RGB值分类颜色（改进:更精确区分白色和浅灰色）"""
        # 计算亮度
        brightness = 0.299 * r + 0.587 * g + 0.114 * b

        # 白色：必须非常亮且各通道值非常接近（纯白或极浅灰）
        if brightness > 230 and abs(r - g) < 15 and abs(r - b) < 15 and abs(g - b) < 15:
            return "white"
        # 浅灰色：较亮，但不够"白"的标准
        elif brightness > 200 and abs(r - g) < 30 and abs(r - b) < 30 and abs(g - b) < 30:
            return "light_gray"  # 新增类别
        # 黑色：低亮度
        elif brightness < 50:
            return "black"
        # 灰黑色：中低亮度，各通道值接近
        elif brightness < 100 and abs(r - g) < 30 and abs(r - b) < 30 and abs(g - b) < 30:
            return "dark_gray"  # 新增类别
        # 红色：红色明显 dominant
        elif r > max(g, b) * 1.5 and r > 100:
            return "red"
        # 蓝色：蓝色明显 dominant
        elif b > max(r, g) * 1.5 and b > 100:
            return "blue"
        # 绿色：绿色明显 dominant
        elif g > max(r, b) * 1.5 and g > 100:
            return "green"
        # 亮色 (非灰白)
        elif brightness > 180:
            return "light_color"
        # 暗色 (非灰黑)
        elif brightness < 80:
            return "dark_color"
        # 中等颜色
        else:
            return "medium_color"

    def check_color_filter(self, color_info):
        """检查颜色是否符合点击条件,设定放弃点击的颜色"""
        if not self.enable_color_filter:
            return True  # 颜色过滤未启用，始终返回True
        
        if isinstance(color_info, tuple):  # RGB值
            r, g, b = color_info
            color_name = self._classify_color(r, g, b)
        else:  # 颜色名称
            color_name = color_info
        
        ####根据字体颜色判断是否点击
        # 白色、黑色设定为可点击
        if color_name in ['white', 'black']:
            return True
        
        # 红色、蓝色设定为不可点击
        elif color_name in ['red', 'blue']:
            return False
        
        # 其他颜色根据配置决定
        elif color_name in self.non_clickable_colors:
            return False
        
        elif color_name in self.clickable_colors:
            return True
        
        # 默认情况下，暗色和中等颜色可点击
        else:
            return True

    def human_like_mouse_move(self, target_x, target_y):
        """模拟人类鼠标移动（带曲线和随机性）"""
        try:
            import pyautogui
            # 获取当前鼠标位置
            current_x, current_y = pyautogui.position()
            
            # 如果已经在目标位置附近，不需要移动
            if abs(current_x - target_x) < 5 and abs(current_y - target_y) < 5:
                return True
            
            # 计算距离和移动时间（基于距离的动态时间）
            distance = math.sqrt((target_x - current_x)**2 + (target_y - current_y)**2)
            move_duration = max(0.1, min(1.0, distance / 1000))  # 动态调整移动时间
            
            # 添加一些随机性到移动路径
            intermediate_points = []
            
            # 生成中间点（模拟人类移动的曲线）
            num_points = max(2, int(distance / 50))  # 根据距离决定中间点数量
            for i in range(1, num_points):
                t = i / num_points
                # 贝塞尔曲线控制点
                control_x = current_x + (target_x - current_x) * t + random.randint(-20, 20)
                control_y = current_y + (target_y - current_y) * t + random.randint(-20, 20)
                
                # 计算贝塞尔曲线上的点
                bezier_x = (1-t)**2 * current_x + 2*(1-t)*t * control_x + t**2 * target_x
                bezier_y = (1-t)**2 * current_y + 2*(1-t)*t * control_y + t**2 * target_y
                
                intermediate_points.append((int(bezier_x), int(bezier_y)))
            
            # 分段移动鼠标
            for point in intermediate_points:
                pyautogui.moveTo(point[0], point[1], duration=move_duration/len(intermediate_points))
                time.sleep(random.uniform(0.01, 0.05))  # 随机微小停顿
            
            # 最终移动到准确位置
            pyautogui.moveTo(target_x, target_y, duration=0.1)
            
            return True
            
        except Exception as e:
            print(f"人工模式鼠标移动失败: {e}")
            return False

    def safe_mouse_move(self, target_x, target_y):
        """安全移动鼠标（根据配置选择移动方式）"""
        try:
            import pyautogui
            # 获取当前鼠标位置
            current_x, current_y = pyautogui.position()
            
            # 如果已经在目标位置附近，不需要移动
            if abs(current_x - target_x) < 5 and abs(current_y - target_y) < 5:
                return True
            
            if self.mouse_move_mode == 'human':
                # 模拟人工移动
                return self.human_like_mouse_move(target_x, target_y)
            else:
                # 直接瞬移（默认）
                pyautogui.moveTo(target_x, target_y, duration=0)
                return True
            
        except Exception as e:
            print(f"鼠标移动失败: {e}")
            return False    

    def take_pc_screenshot(self):
        """使用 mss 截屏，快速保存为临时JPG文件（质量60加速写入），返回文件路径"""
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # 主屏幕
                screenshot = sct.grab(monitor)
                
                # 转换为 RGB numpy array
                img_rgb = np.array(screenshot)[:, :, :3]  # 去除 alpha 通道
                
                # 转换为 BGR 格式（OpenCV 标准）
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                
                # 保存用于颜色分析
                self.screenshot_image = img_bgr.copy()
                
                # 生成唯一文件名（微秒级时间戳+随机数避免冲突）
                temp_path = os.path.join(
                    self.temp_dir, 
                    f"ocr_{int(time.time()*1000000)}_{random.randint(1000,9999)}.jpg"
                )
                
                # 关键优化：使用 OpenCV 快速 JPEG 编码（质量60平衡速度与精度）
                # 实测：1920x1080 图片，质量60 写入时间 ~3-5ms (SSD)
                cv2.imwrite(temp_path, img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
                
                return temp_path
        except Exception as e:
            print(f"PC 截图失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def take_phone_screenshot(self):
        """使用 uiautomator2 截图，快速保存为临时JPG文件，返回文件路径和设备信息"""
        try:
            import uiautomator2 as u2
            
            # 连接设备
            if self.device_ip:
                d = u2.connect(self.device_ip)
            else:
                d = u2.connect()  # 自动连接第一个设备
            
            # 获取手机屏幕信息
            device_info = d.info
            phone_width = device_info['displayWidth']
            phone_height = device_info['displayHeight']
            print(f"手机屏幕尺寸: {phone_width}x{phone_height}")
            
            # 截图（返回 Pillow Image）
            screenshot = d.screenshot()
            
            # 转换为 RGB numpy array
            img_rgb = np.array(screenshot)
            
            # 转换为 BGR 格式
            img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            
            # 保存用于颜色分析
            self.screenshot_image = img_bgr.copy()
            
            # 生成唯一文件名
            temp_path = os.path.join(
                self.temp_dir, 
                f"ocr_phone_{int(time.time()*1000000)}_{random.randint(1000,9999)}.jpg"
            )
            
            # 快速 JPEG 编码
            cv2.imwrite(temp_path, img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
            
            return temp_path, d, (phone_width, phone_height)
            
        except Exception as e:
            print(f"手机截图失败: {e}")
            import traceback
            traceback.print_exc()
            return None, None, None

    def ocr_with_image(self, image_path, options=None):
        """
        调用 PaddleOCR-json 引擎进行识别（传入文件路径，识别后立即删除临时文件）
        Args:
            image_path: 临时图片文件路径
            options: 保留参数（PaddleOCR-json 通过配置文件设置）
        Returns:
            与 Umi-OCR 兼容的 JSON 格式结果
        """
        if not image_path or not isinstance(image_path, str) or not os.path.exists(image_path):
            print(f"OCR 错误：无效的图片路径 {image_path}")
            return None
        
        try:
            # 关键：传入字符串路径（PPOCR_api 原生支持，避免 ndarray 序列化问题）
            result = self.ocr_engine.run(image_path)
            
            # 识别完成后立即删除临时文件（减少磁盘占用）
            try:
                os.remove(image_path)
            except Exception as e:
                print(f"警告: 临时文件删除失败 {image_path}, 错误: {e}")
            
            # PaddleOCR-json 返回格式: {"code": 100, "data": [...]}
            if result and "code" in result:
                print(f"OCR 识别完成，状态码: {result['code']}, 识别到 {len(result.get('data', []))} 个文本块")
                return result
            else:
                print(f"OCR 返回格式异常: {result}")
                return {"code": 999, "data": "OCR 引擎返回格式错误"}
                    
        except Exception as e:
            print(f"OCR 识别失败: {e}")
            import traceback
            traceback.print_exc()
            
            # 异常时也尝试删除临时文件
            try:
                os.remove(image_path)
            except:
                pass
            
            return {"code": 999, "data": f"异常: {str(e)}"}

    def format_ocr_result(self, result):
        """格式化OCR结果，处理换行，并修复数字识别问题"""
        if not result or 'code' not in result:
            return "识别失败"
        
        code = result['code']
        if code == 100:  # 识别成功
            if isinstance(result['data'], list):
                # dict格式，拼接所有文本
                text_lines = []
                for item in result['data']:
                    if isinstance(item, dict) and 'text' in item:
                        text = item['text']
                        
                        # 修复数字识别问题（后处理）
                        text = self._fix_number_recognition(text)
                        
                        text_lines.append(text)
                        if 'end' in item and item['end']:
                            text_lines.append(item['end'])
                return ''.join(text_lines)
            elif isinstance(result['data'], str):
                # text格式
                text = result['data']
                return self._fix_number_recognition(text)
            else:
                return str(result['data'])
        elif code == 101:  # 无文本
            return "图片中没有检测到文本"
        else:  # 识别失败
            return f"识别失败，错误代码: {code}, 信息: {result.get('data', '未知错误')}"

    def _fix_number_recognition(self, text):
        """修复数字识别问题，特别是小数点"""
        # 修复常见的小数点误识别
        text = text.replace(',', '.')  # 将逗号替换为小数点
        
        # 修复 "O" 被识别为 "0" 的问题
        text = text.replace('O', '0').replace('o', '0')
        
        # 修复 "l" 被识别为 "1" 的问题
        text = text.replace('l', '1').replace('I', '1')        
        return text

    def calculate_click_position(self, ocr_data, target_text, screen_width, screen_height, enable_color_check=True):
        """根据OCR结果计算点击位置"""
        if not ocr_data or not isinstance(ocr_data, list):
            return None
        
        found_positions = []
        
        # 在OCR结果中查找包含目标文本的项
        for item in ocr_data:
            if isinstance(item, dict) and 'text' in item and target_text in item['text']:
                # 获取位置信息
                if 'box' in item and isinstance(item['box'], list) and len(item['box']) >= 4:
                    box = item['box']
                    
                    # 检查文字颜色（如果启用）
                    color_info = None
                    if enable_color_check:
                        if self.return_rgb_value:
                            color_info = self.get_text_color(box, return_rgb=True)
                            print(f"文本 '{item['text']}' 的RGB颜色: {color_info}")
                        else:
                            color_info = self.get_text_color(box, return_rgb=False)
                            print(f"文本 '{item['text']}' 的颜色: {color_info}")
                        
                        # 如果启用了颜色过滤且颜色不符合条件，跳过
                        if self.enable_color_filter and not self.check_color_filter(color_info):
                            print(f"文本 '{item['text']}' 颜色不符合点击条件，跳过")
                            continue
                    
                    # 计算文本框的边界
                    x_coords = [point[0] for point in box if len(point) >= 2]
                    y_coords = [point[1] for point in box if len(point) >= 2]
                    
                    if not x_coords or not y_coords:
                        continue
                    
                    # 计算文本框的中心点（更精确的方法）
                    x_min, x_max = min(x_coords), max(x_coords)
                    y_min, y_max = min(y_coords), max(y_coords)
                    
                    # 根据文本长度调整点击位置（避免点击到边缘）
                    text_length = len(item['text'])
                    width = x_max - x_min
                    height = y_max - y_min
                    
                    # 在文本框内选择一个更安全的位置（避免边缘）
                    safety_margin = min(10, width * 0.2, height * 0.2)  # 安全边距
                    safe_x_min = x_min + safety_margin
                    safe_x_max = x_max - safety_margin
                    safe_y_min = y_min + safety_margin
                    safe_y_max = y_max - safety_margin
                    
                    # 确保安全区域有效
                    if safe_x_min >= safe_x_max:
                        safe_x_min = x_min
                        safe_x_max = x_max
                    if safe_y_min >= safe_y_max:
                        safe_y_min = y_min
                        safe_y_max = y_max
                    
                    # 在安全区域内随机选择一个点（避免固定模式）
                    x_center = random.uniform(safe_x_min, safe_x_max)
                    y_center = random.uniform(safe_y_min, safe_y_max)
                    
                    # 确保坐标在屏幕范围内
                    x_center = max(0, min(x_center, screen_width - 1))
                    y_center = max(0, min(y_center, screen_height - 1))
                    
                    # 计算比例坐标
                    x_ratio = round(x_center / screen_width, 4)
                    y_ratio = round(y_center / screen_height, 4)
                    
                    position_info = {
                        'text': item['text'],
                        'absolute': (int(x_center), int(y_center)),
                        'ratio': (x_ratio, y_ratio),
                        'score': item.get('score', 0),
                        'box': box,  # 保存原始框信息
                        'safe_area': (safe_x_min, safe_y_min, safe_x_max, safe_y_max),
                        'color': color_info  # 添加颜色信息
                    }
                    
                    found_positions.append(position_info)
        
        return found_positions if found_positions else None

    def calculate_distance(self, pos1, pos2):
        """计算两个坐标点之间的欧几里得距离"""
        return math.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)

    def find_closest_position(self, positions, reference_position):
        """找到离参考位置最近的文本位置"""
        if not positions or not reference_position:
            return None
        
        closest_pos = None
        min_distance = float('inf')
        
        for pos in positions:
            distance = self.calculate_distance(pos['absolute'], reference_position)
            if distance < min_distance:
                min_distance = distance
                closest_pos = pos
        
        return closest_pos, min_distance

    def find_text_positions(self, ocr_result, target_texts, screen_size, reference_text=None, enable_color_check=True):
        """在OCR结果中查找多个目标文本的位置，并选择离参考文本最近的那个"""
        if not ocr_result or 'code' not in ocr_result:
            return None
        
        screen_width, screen_height = screen_size
        
        # 检查识别状态
        code = ocr_result['code']
        if code != 100:  # 不是成功状态
            print(f"OCR识别失败，状态码: {code}")
            return None
        
        # 获取OCR数据
        ocr_data = ocr_result['data']
        
        # 如果是文本格式，无法获取位置信息
        if isinstance(ocr_data, str):
            print("OCR返回的是文本格式，无法获取位置信息")
            return None
        
        all_positions = []
        reference_position = None
        
        # 首先查找参考文本的位置（如果有）
        if reference_text and isinstance(ocr_data, list):
            reference_positions = self.calculate_click_position(ocr_data, reference_text, screen_width, screen_height, enable_color_check)
            if reference_positions:
                # 检查参考文本是否符合过滤条件
                if self.check_keywords_filter(reference_text):
                    # 取第一个参考位置
                    reference_position = reference_positions[0]['absolute']
                    print(f"找到参考文本 '{reference_text}' 在位置: {reference_position}")
                else:
                    print(f"参考文本 '{reference_text}' 不符合关键词过滤条件，跳过")
        
        # 查找所有目标文本的位置
        for target_text in target_texts:
            positions = self.calculate_click_position(ocr_data, target_text, screen_width, screen_height, enable_color_check)
            if positions:
                # 过滤符合关键词条件的位置
                filtered_positions = []
                for pos in positions:
                    if self.check_keywords_filter(pos['text'], reference_text):
                        filtered_positions.append(pos)
                    else:
                        print(f"文本 '{pos['text']}' 不符合关键词过滤条件，跳过")
                
                if filtered_positions:
                    all_positions.extend(filtered_positions)
                    print(f"找到目标文本 '{target_text}' 的 {len(filtered_positions)} 个有效位置")
        
        if not all_positions:
            print("未找到任何符合条件的目标文本")
            return None
        
        # 打印所有找到的位置
        print("\n找到的所有符合条件的目标文本位置:")
        for i, pos in enumerate(all_positions, 1):
            print(f"{i}. 文本: '{pos['text']}'")
            print(f"   绝对坐标: {pos['absolute']}")
            print(f"   比例坐标: {pos['ratio']}")
            print(f"   置信度: {pos['score']:.4f}")
            if pos['color']:
                if isinstance(pos['color'], tuple):
                    r, g, b = pos['color']
                    color_name = self._classify_color(r, g, b)
                    print(f"   RGB颜色: ({r}, {g}, {b}) - 识别为: {color_name}")
                else:
                    print(f"   颜色: {pos['color']}")
            print(f"   安全区域: {[int(x) for x in pos['safe_area']]}")
        
        # 如果有参考位置，选择最近的那个
        if reference_position:
            closest_pos, distance = self.find_closest_position(all_positions, reference_position)
            if closest_pos:
                print(f"\n选择离参考文本最近的文本: '{closest_pos['text']}'")
                print(f"距离: {distance:.2f} 像素")
                return closest_pos
        
        # 如果没有参考位置或者没找到参考位置，让用户选择
        print(f"\n找到 {len(all_positions)} 个匹配的文本位置")
        if len(all_positions) == 1:
            # 只有一个位置，直接返回
            return all_positions[0]
        else:
            # 多个位置，让用户选择
            try:
                choice = int(input("请选择要点击的位置编号 (输入0取消): "))
                if 1 <= choice <= len(all_positions):
                    return all_positions[choice - 1]
                else:
                    print("取消选择")
                    return None
            except ValueError:
                print("输入无效，取消选择")
                return None

    def apply_offset(self, position_info, offset_x=0, offset_y=0):
        """应用偏移量到位置信息"""
        if not position_info:
            return None
            
        # 创建副本以避免修改原始数据
        offset_position = position_info.copy()
        
        # 更新绝对坐标
        original_x, original_y = offset_position['absolute']
        new_x = original_x + offset_x
        new_y = original_y + offset_y
        
        # 确保坐标在屏幕范围内
        new_x = max(0, min(new_x, self.screen_width - 1))
        new_y = max(0, min(new_y, self.screen_height - 1))
        
        offset_position['absolute'] = (int(new_x), int(new_y))
        
        # 更新比例坐标
        offset_position['ratio'] = (
            round(new_x / self.screen_width, 4),
            round(new_y / self.screen_height, 4)
        )
        
        # 更新安全区域（如果有）
        if 'safe_area' in offset_position and offset_position['safe_area']:
            safe_x_min, safe_y_min, safe_x_max, safe_y_max = offset_position['safe_area']
            # 确保安全区域也在屏幕范围内
            new_safe_x_min = max(0, min(safe_x_min + offset_x, self.screen_width - 1))
            new_safe_y_min = max(0, min(safe_y_min + offset_y, self.screen_height - 1))
            new_safe_x_max = max(0, min(safe_x_max + offset_x, self.screen_width - 1))
            new_safe_y_max = max(0, min(safe_y_max + offset_y, self.screen_height - 1))
            offset_position['safe_area'] = (
                new_safe_x_min, new_safe_y_min,
                new_safe_x_max, new_safe_y_max
            )
        
        print(f"应用偏移量: X={offset_x}, Y={offset_y}")
        print(f"原始位置: {original_x}, {original_y}")
        print(f"新位置: {new_x}, {new_y}")
        
        return offset_position

    def click_on_pc(self, position_info, offset_x=0, offset_y=0):
        """在电脑上安全点击指定位置，支持偏移量"""
        if not self.pyautogui_available:
            print("错误: pyautogui 未安装，无法执行PC点击")
            return False
        
        try:
            import pyautogui
            # 应用偏移量
            if offset_x != 0 or offset_y != 0:
                position_info = self.apply_offset(position_info, offset_x, offset_y)
                if not position_info:
                    print("应用偏移量失败")
                    return False
            
            absolute_pos = position_info['absolute']
            ratio_pos = position_info['ratio']
            
            print(f"等待 {self.click_delay:.2f} 秒后点击...")
            print(f"点击位置 - 绝对坐标: {absolute_pos}, 比例坐标: {ratio_pos}")
            print(f"鼠标移动模式: {self.mouse_move_mode}")
            
            time.sleep(self.click_delay)
            
            # 安全移动鼠标（根据配置选择移动方式）
            if not self.safe_mouse_move(absolute_pos[0], absolute_pos[1]):
                print("鼠标移动失败，尝试直接点击")
                pyautogui.click(absolute_pos[0], absolute_pos[1])
            else:
                # 短暂停顿后点击
                time.sleep(0.1)
                pyautogui.click()
            
            print("点击完成")
            return True
        except Exception as e:
            print(f"电脑点击失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def double_click_on_pc(self, position_info, offset_x=0, offset_y=0, interval=0.15):
        """在电脑上执行双击操作，支持偏移量和自定义间隔时间"""
        if not self.pyautogui_available:
            print("错误: pyautogui 未安装，无法执行PC双击")
            return False
        
        try:
            import pyautogui
            
            # 应用偏移量
            if offset_x != 0 or offset_y != 0:
                position_info = self.apply_offset(position_info, offset_x, offset_y)
            if not position_info:
                print("应用偏移量失败")
                return False
            
            absolute_pos = position_info['absolute']
            ratio_pos = position_info['ratio']
            
            print(f"等待 {self.click_delay:.2f} 秒后双击...")
            print(f"双击位置 - 绝对坐标: {absolute_pos}, 比例坐标: {ratio_pos}")
            print(f"双击间隔: {interval} 秒")
            time.sleep(self.click_delay)
            
            # 安全移动鼠标
            if not self.safe_mouse_move(absolute_pos[0], absolute_pos[1]):
                print("鼠标移动失败，尝试直接双击")
                pyautogui.doubleClick(absolute_pos[0], absolute_pos[1], interval=interval)
            else:
                time.sleep(0.1)
                pyautogui.doubleClick(interval=interval)  # pyautogui 原生双击
            
            print("双击完成")
            return True
            
        except Exception as e:
            print(f"电脑双击失败: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    def click_on_phone(self, device, position_info, offset_x=0, offset_y=0):
        """在手机上点击指定位置，支持偏移量"""
        try:
            # 应用偏移量
            if offset_x != 0 or offset_y != 0:
                position_info = self.apply_offset(position_info, offset_x, offset_y)
                if not position_info:
                    print("应用偏移量失败")
                    return False
            
            absolute_pos = position_info['absolute']
            ratio_pos = position_info['ratio']
            
            print(f"等待 {self.click_delay} 秒后点击...")
            print(f"点击位置 - 绝对坐标: {absolute_pos}, 比例坐标: {ratio_pos}")
            
            time.sleep(self.click_delay)
            
            # 使用比例坐标点击
            device.click(ratio_pos[0], ratio_pos[1])
            print("点击完成")
            return True
        except Exception as e:
            print(f"手机点击失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def manual_position_input(self, screen_size, offset_x=0, offset_y=0):
        """手动输入位置坐标，支持偏移量"""
        try:
            screen_width, screen_height = screen_size
            print(f"当前屏幕尺寸: {screen_width}x{screen_height}")
            
            print("请选择输入方式:")
            print("1. 绝对坐标")
            print("2. 比例坐标")
            choice = input("请输入选择 (1/2): ")
            
            position_info = None
            
            if choice == "1":
                x = int(input("请输入X坐标: "))
                y = int(input("请输入Y坐标: "))
                
                # 验证坐标是否在屏幕范围内
                if 0 <= x < screen_width and 0 <= y < screen_height:
                    x_ratio = round(x / screen_width, 4)
                    y_ratio = round(y / screen_height, 4)
                    position_info = {
                        'absolute': (x, y),
                        'ratio': (x_ratio, y_ratio),
                        'text': '手动输入'
                    }
                else:
                    print(f"坐标超出屏幕范围! 有效范围: X(0-{screen_width-1}), Y(0-{screen_height-1})")
                    
            elif choice == "2":
                x_ratio = float(input("请输入X比例 (0-1): "))
                y_ratio = float(input("请输入Y比例 (0-1): "))
                
                if 0 <= x_ratio <= 1 and 0 <= y_ratio <= 1:
                    x = int(x_ratio * screen_width)
                    y = int(y_ratio * screen_height)
                    position_info = {
                        'absolute': (x, y),
                        'ratio': (x_ratio, y_ratio),
                        'text': '手动输入'
                    }
                else:
                    print("比例必须在0-1之间")
            
            # 应用偏移量
            if position_info and (offset_x != 0 or offset_y != 0):
                position_info = self.apply_offset(position_info, offset_x, offset_y)
            
            return position_info
            
        except ValueError:
            print("请输入有效的数字")
            return None
    
    def run_ocr_and_click(self, target_texts, reference_text=None, options=None, offset_x=0, offset_y=0, click=True, enable_color_check=None):
        """主函数：执行OCR识别并可选点击目标文本（使用临时文件路径方案）"""
        print(f"使用 {self.screenshot_type.upper()} 截图模式")
        print(f"目标文本: {target_texts}")
        print(f"点击模式: {'启用' if click else '禁用'}")

        if reference_text:
            print(f"参考文本: {reference_text}")
        if offset_x != 0 or offset_y != 0:
            print(f"偏移量: X={offset_x}, Y={offset_y}")
        
        print(f"关键词过滤: {'启用' if self.enable_filter else '禁用'}")
        if self.enable_filter:
            print(f"必需关键词: {self.required_keywords}")
        
        # 确定是否启用颜色检查
        if enable_color_check is None:
            enable_color_check = self.enable_color_filter
        
        print(f"颜色检查: {'启用' if enable_color_check else '禁用'}")
        if enable_color_check:
            print(f"返回RGB值: {'是' if self.return_rgb_value else '否'}")
        
        print(f"鼠标移动模式: {self.mouse_move_mode}")
        
        # 截图（返回临时文件路径）
        if self.screenshot_type.lower() == 'pc':
            image_path = self.take_pc_screenshot()
            device = None
            screen_size = (self.screen_width, self.screen_height)
        else:
            image_path, device, phone_size = self.take_phone_screenshot()
            screen_size = phone_size if phone_size else (1080, 1920)  # 默认手机分辨率
        
        # 修复：使用 is None 判断（image_path 是字符串，不是 array）
        if image_path is None:
            print("截图失败，程序退出")
            return
        
        if not screen_size:
            print("无法获取屏幕尺寸，程序退出")
            return
        
        print(f"目标屏幕尺寸: {screen_size[0]}x{screen_size[1]}")
        print(f"临时图片路径: {image_path}")
        
        # OCR识别（传入文件路径）
        print("正在进行OCR识别...")
        result = self.ocr_with_image(image_path)  # 传入字符串路径
        
        if not result:
            print("OCR识别失败")
            return
        
        # 检查识别状态
        if 'code' in result:
            code = result['code']
            if code == 100:
                print("OCR识别成功")
            elif code == 101:
                print("图片中没有检测到文本")
                return
            else:
                print(f"OCR识别失败，错误代码: {code}")
                return
        
        # 格式化并显示结果
        formatted_text = self.format_ocr_result(result)
        print("\n" + "= "*50)
        print("OCR识别结果：")
        print(formatted_text)
        print("= "*50)
        
        # 查找目标文本位置
        print(f"\n正在查找目标文本: {target_texts}")
        position_info = self.find_text_positions(result, target_texts, screen_size, reference_text, enable_color_check)
        
        if position_info:
            print(f"\n找到文本: '{position_info['text']}'")
            print(f"绝对坐标: {position_info['absolute']}")
            print(f"比例坐标: {position_info['ratio']}")
            if position_info['color']:
                if isinstance(position_info['color'], tuple):
                    r, g, b = position_info['color']
                    color_name = self._classify_color(r, g, b)
                    print(f"RGB颜色: ({r}, {g}, {b}) - 识别为: {color_name}")
                else:
                    print(f"颜色: {position_info['color']}")
            print(f"安全区域: {[int(x) for x in position_info['safe_area']]}")
            
            if click:
                if self.screenshot_type.lower() == 'pc':
                    success = self.click_on_pc(position_info, offset_x, offset_y)
                else:
                    if device:
                        success = self.click_on_phone(device, position_info, offset_x, offset_y)
                    else:
                        print("手机设备连接失败，无法点击")
                        success = False
                
                if success:
                    print("点击操作完成")
                else:
                    print("点击操作失败")
            else:
                print("点击功能已禁用，仅显示识别结果")
        else:
            print(f"未找到符合条件的文本: {target_texts}")

    def batch_ocr_from_folder(self, input_folder, output_dir="output", draw_text=False):
        """批量识别指定文件夹中的所有图片（支持中文路径）"""
        from PIL import Image, ImageDraw, ImageFont
        
        # 支持的图片格式
        image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff', '*.webp']
        image_paths = []
        for ext in image_extensions:
            image_paths.extend(glob.glob(os.path.join(input_folder, ext), recursive=False))
            # 仅在Linux等区分大小写的系统上搜索大写扩展名
            if sys.platform.startswith('linux'):
                image_paths.extend(glob.glob(os.path.join(input_folder, ext.upper()), recursive=False))
        
        # 去重，大小写拓展名重复统计问题
        image_paths = list(set(os.path.abspath(p) for p in image_paths))
        image_paths.sort()  # 保持顺序稳定
        
        if not image_paths:
            print(f"在文件夹 '{input_folder}' 中未找到支持的图片文件。")
            return
        
        print(f"\n✓ 共检测到 {len(image_paths)} 张图片（已自动去重）")
        
        # 创建输出目录（支持中文路径）
        os.makedirs(output_dir, exist_ok=True)
        
        total_start = time.time()
        for idx, img_path in enumerate(image_paths, 1):
            print(f"\n[{idx}/{len(image_paths)}] 处理图片: {os.path.basename(img_path)}")
            
            # 读取图片用于颜色分析
            try:
                # 使用 OpenCV 读取图片（支持中文路径）
                img_data = np.fromfile(img_path, dtype=np.uint8)
                img_cv = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
                if img_cv is None:
                    print(f"  跳过无效图片（解码失败）: {img_path}")
                    continue
                self.screenshot_image = img_cv
            except Exception as e:
                print(f"  读取图片失败: {img_path}, 错误: {e}")
                continue
            
            # OCR识别（直接传入原图路径）
            result = self.ocr_with_image(img_path)
            if not result or result.get('code') != 100:
                print(f"  OCR 识别失败: {result.get('data', '未知错误')}")
                continue
            
            # 格式化文本结果
            text_result = self.format_ocr_result(result)
            print(f"  识别结果: {text_result[:80]}..." if len(text_result) > 80 else f"  识别结果: {text_result}")
            
            # 保存纯文本结果（Python原生open支持中文路径）
            txt_path = os.path.join(output_dir, Path(img_path).stem + ".txt")
            try:
                with open(txt_path, 'w', encoding='utf-8') as f:
                    f.write(text_result)
                print(f"  ✓ 文本结果已保存至: {txt_path}")
            except Exception as e:
                print(f"  ✗ 保存文本失败: {txt_path}, 错误: {e}")
            
            # 如果启用绘制文字
            if draw_text and isinstance(result.get('data'), list):
                img_draw = img_cv.copy()
                
                # 动态计算字体大小
                font_size = self.get_dynamic_font_size(img_cv.shape[1], img_cv.shape[0])
                
                # 使用PIL绘制中文（仅转换一次）
                img_pil = Image.fromarray(cv2.cvtColor(img_draw, cv2.COLOR_BGR2RGB))
                draw = ImageDraw.Draw(img_pil)
                font_path = self._get_chinese_font()
                
                try:
                    font = ImageFont.truetype(font_path, font_size)
                except Exception as e:
                    font = ImageFont.load_default()
                    print(f"  警告: 未找到中文字体 '{font_path}'，使用默认字体（中文可能显示异常）")
                    print(f"        错误详情: {e}")
                
                # 绘制识别结果
                for item in result['data']:
                    if 'text' in item and 'box' in item:
                        # 修复负号识别
                        text = self._fix_number_recognition(item['text'])
                        box = np.array(item['box'], dtype=np.int32)
                        
                        # 绘制多边形框
                        cv2.polylines(img_draw, [box], isClosed=True, color=(0, 255, 0), thickness=2)
                
                # 转回PIL绘制文字
                img_pil = Image.fromarray(cv2.cvtColor(img_draw, cv2.COLOR_BGR2RGB))
                draw = ImageDraw.Draw(img_pil)
                
                for item in result['data']:
                    if 'text' in item and 'box' in item:
                        text = self._fix_number_recognition(item['text'])
                        box = np.array(item['box'], dtype=np.int32)
                        x_min = min(pt[0] for pt in box)
                        y_min = min(pt[1] for pt in box) - int(font_size * 1.2)
                        draw.text((x_min, y_min), text, font=font, fill=(0, 255, 0))
                
                # 仅一次转换回BGR
                img_draw = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
                
                # 保存带文字的图片（支持中文路径）
                out_img_path = os.path.join(output_dir, Path(img_path).name)
                try:
                    cv2.imencode('.jpg', img_draw)[1].tofile(out_img_path)
                    print(f"  ✓ 带文字图片已保存至: {out_img_path}")
                except Exception as e:
                    print(f"  ✗ 保存图片失败: {out_img_path}, 错误: {e}")
        
        total_time = time.time() - total_start
        print(f"\n✓ 批量处理完成! 共{len(image_paths)}张图片，总耗时: {total_time:.2f}s，平均: {total_time/len(image_paths):.3f}s/张")

    def get_dynamic_font_size(self, img_width, img_height, min_size=12, max_size=48):
        """根据图片尺寸动态计算字体大小"""
        # 基于图片对角线长度计算（经验值：对角线的1.5%）
        diagonal = math.sqrt(img_width ** 2 + img_height ** 2)
        font_size = int(diagonal * 0.015)
        
        # 限制在合理范围
        font_size = max(min_size, min(max_size, font_size))
        
        # 额外规则：小图用小字，大图用大字
        if diagonal < 500:      # 小于500px对角线（如手机截图）
            font_size = max(10, min(16, font_size))
        elif diagonal > 2000:   # 大于2000px对角线（如4K截图）
            font_size = max(24, min(48, font_size))
        
        return font_size

    def _get_chinese_font(self):
        """智能获取系统中文字体路径"""
        # 优先级: 微软雅黑 > 思源黑体 > 系统默认
        font_candidates = []
        
        if sys.platform == 'win32':
            win_font_dir = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')
            font_candidates = [
                os.path.join(win_font_dir, 'msyh.ttc'),
                os.path.join(win_font_dir, 'msyh.ttf'),
                os.path.join(win_font_dir, 'simhei.ttf'),
                os.path.join(win_font_dir, 'simsun.ttc'),
            ]
        elif sys.platform == 'darwin':  # macOS
            font_candidates = [
                '/System/Library/Fonts/PingFang.ttc',
                '/System/Library/Fonts/STHeiti Light.ttc',
                '/Library/Fonts/Arial Unicode.ttf',
            ]
        else:  # Linux
            font_candidates = [
                '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                '/usr/share/fonts/wqy-microhei/wqy-microhei.ttc',
                '/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc',
            ]
        
        # 检查候选字体是否存在
        for font in font_candidates:
            if os.path.exists(font):
                return font
        
        # 最后回退到系统默认（PIL会自动处理）
        return "DejaVuSans.ttf"  # PIL默认字体之一

    def update_config(self, section, key, value):
        """更新配置项"""
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = str(value)
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)
        print(f"配置已更新: {section}.{key} = {value}")


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='OCR点击助手')
    parser.add_argument('target_texts', nargs='+', help='要点击的目标文本')
    parser.add_argument('--no-click', action='store_false', dest='click',
                        help='仅识别不点击', default=True)
    parser.add_argument('-r', '--reference', help='参考文本')
    parser.add_argument('-x', '--offset-x', type=int, default=0, help='X轴偏移量（像素）')
    parser.add_argument('-y', '--offset-y', type=int, default=0, help='Y轴偏移量（像素）')
    parser.add_argument('-c', '--config', default='config.ini', help='配置文件路径')
    parser.add_argument('-t', '--type', choices=['pc', 'phone'], help='截图类型')
    parser.add_argument('-d', '--device', help='设备IP地址')
    parser.add_argument('-f', '--filter', action='store_true', help='启用关键词过滤')
    parser.add_argument('-k', '--keywords', help='必需关键词，用逗号分隔')
    parser.add_argument('-m', '--mode', choices=['instant', 'human'], help='鼠标移动模式')
    parser.add_argument('--color-filter', action='store_true', help='启用颜色过滤')
    parser.add_argument('--no-color-filter', action='store_false', dest='color_filter', help='禁用颜色过滤')
    parser.add_argument('--return-rgb', action='store_true', help='返回RGB颜色值')
    parser.add_argument('--return-color-name', action='store_false', dest='return_rgb', help='返回颜色名称')
    ##识别图片选项的配置
    parser.add_argument('--folder', help='指定图片文件夹，启用批量识别模式')
    parser.add_argument('--draw-text', action='store_true', help='是否将识别文字绘制到图片上')
    parser.add_argument('--output-dir', default='output', help='输出目录（默认: output）')
    return parser.parse_args()


def main():
    """主函数，支持命令行调用"""
    # 参数解析
    args = parse_arguments()

    # 如果指定了 --folder，则进入批量识别模式
    if args.folder:
        assistant = OCRClickAssistant(args.config)
        # 根据命令行参数更新配置（可选）
        if hasattr(args, 'color_filter'):
            assistant.update_config('ColorFilter', 'enable_color_filter', str(args.color_filter))
        if hasattr(args, 'return_rgb'):
            assistant.update_config('ColorFilter', 'return_rgb_value', str(args.return_rgb))
        # 执行批量识别
        assistant.batch_ocr_from_folder(
            input_folder=args.folder,
            output_dir=args.output_dir,
            draw_text=args.draw_text
        )
        return

    # 否则，执行原始的 OCR + 点击逻辑
    # 创建助手实例
    assistant = OCRClickAssistant(args.config)

    # 根据命令行参数更新配置
    if args.type:
        assistant.update_config('Settings', 'screenshot_type', args.type)
    if args.device:
        assistant.update_config('Settings', 'device_ip', args.device)
    if args.filter:
        assistant.update_config('Filter', 'enable_filter', 'True')
    if args.keywords:
        assistant.update_config('Filter', 'required_keywords', args.keywords)
    if args.mode:
        assistant.update_config('Settings', 'mouse_move_mode', args.mode)
    if hasattr(args, 'color_filter'):
        assistant.update_config('ColorFilter', 'enable_color_filter', str(args.color_filter))
    if hasattr(args, 'return_rgb'):
        assistant.update_config('ColorFilter', 'return_rgb_value', str(args.return_rgb))

    # OCR参数（PaddleOCR-json 通过配置文件设置，此处保留接口兼容性）
    options = {
        "ocr.language": "models/config_chinese.txt",
        "ocr.cls": False,
        "tbpu.parser": "multi_para",
    }

    # 执行OCR识别和点击
    assistant.run_ocr_and_click(
        target_texts=args.target_texts,
        reference_text=args.reference,
        options=options,
        offset_x=args.offset_x,
        offset_y=args.offset_y,
        click=args.click,
        enable_color_check=args.color_filter if hasattr(args, 'color_filter') else None
    )


if __name__ == "__main__":
    # 如果通过命令行调用
    if len(sys.argv) > 1:
        main()
    else:
        # 直接运行时的示例代码
        assistant = OCRClickAssistant()
        # 可选：更新配置（如果需要）
        # assistant.update_config('Settings', 'mouse_move_mode', 'human')  # 改为人工移动模式
        assistant.update_config('Filter', 'enable_filter', 'False')  # 禁用关键词过滤
        assistant.update_config('ColorFilter', 'enable_color_filter', 'False')  # 启用颜色过滤，禁用可提高识别速度
        assistant.update_config('ColorFilter', 'return_rgb_value', 'True')  # 返回RGB值
        
        # OCR参数（可以调整这些参数）
        options = {
            "ocr.language": "models/config_chinese.txt",  # 中文模型
            "ocr.cls": False,  # 是否启用方向纠正
            "tbpu.parser": "multi_para",  # 排版解析方案
        }
        
        # 执行OCR识别和点击，启用颜色检查
        assistant.run_ocr_and_click(
            target_texts=["此电脑"],
            options=options,
            click=True,  # True:识别并点击，False：只识别，不点击
            enable_color_check=True  # 启用颜色检查
        )