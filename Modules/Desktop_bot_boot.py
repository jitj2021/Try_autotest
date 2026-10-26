from Modules.Desktop_Auto_Unified import UnifiedDesktopController

# 【修复】原代码在 boot_select=1 且未传 window_title 时会引用未定义的全局名
# title_name_main，直接抛 NameError 崩溃。这里给一个模块内默认值兜底，
# 并在真正用到兜底值时打印明确提示，方便定位"忘记传标题"的调用。
DEFAULT_WINDOW_TITLE = None

###模块1，连接被测软件、启动软件
def bot_boot(boot_select=1, app_path_test="", target_pid=None, window_title=None):
	"""
	模块1：连接/启动被测软件
	:param boot_select: 1=启动新软件, 2=按标题连接, 3=按PID连接
	:param app_path_test: boot_select=1 时的软件 exe 路径
	:param target_pid:    boot_select=3 时的进程 PID
	:param window_title:  窗口标题(字符串或列表)，三种模式都可传：
		- 1: 用于"等待窗口"+app_name；不传则用旧默认列表(仅适配数据预览系统，换软件务必显式传)
		- 2: 必填，用于连接+app_name
		- 3: 可选，作为"挑主窗口打分"的标题提示+app_name 兜底；
			 若 boot_select=3 却没传 target_pid，则自动降级为标题连接(=2 的语义)并 warning
	返回: 成功返回 bot；失败返回 None
	"""
	bot = None
	try:
		if boot_select == 1:
			# 方式1：启动新软件（app_path 存在 → connect 内部走 start_app）
			effective_title = window_title or DEFAULT_WINDOW_TITLE
			if not effective_title:
				print("❌ boot_select=1 未传 window_title，且模块内无默认值，"
					  "请显式传入 window_title（不同软件标题不同，务必显式传）")
				return None
			bot = UnifiedDesktopController(
				app_path=app_path_test,
				window_title=effective_title,
				backend="win32"
			)
			bot.connect()   # 空参即可：self.app_path 存在会自动走 start_app

		elif boot_select == 2:
			# 方式2：按标题连接已有软件
			if not window_title:
				print("❌ boot_select=2 必须传入 window_title")
				return None
			bot = UnifiedDesktopController(window_title=window_title, backend="win32")
			bot.connect(window_title=window_title)   # 必须显式传，空参连不上

		elif boot_select == 3:
			if target_pid:
				# 方式3a：按 PID 连接，window_title 作标题提示(打分挑主窗口 + app_name 兜底)
				bot = UnifiedDesktopController(
					window_title=window_title or "", backend="win32"
				)
				bot.connect(pid=target_pid, window_title=window_title)   # pid+标题 一起传
			elif window_title:
				# 方式3b：没给 PID 但给了标题 → 降级为标题连接，避免直接失败
				print(f"⚠️ boot_select=3 未提供 target_pid，已自动降级为按标题连接: {window_title}")
				bot = UnifiedDesktopController(window_title=window_title, backend="win32")
				bot.connect(window_title=window_title)
			else:
				print("❌ boot_select=3 必须提供 target_pid 或 window_title 之一")
				return None
		else:
			print("❌ 无效的 boot_select 参数")
			return None

		# 成功判断用 main_window。
		if bot is None or bot.main_window is None:
			print("❌ 启动/连接软件失败（main_window 为空），准备中止测试...")
			return None

		# 打开/关联后把界面前置（focus_window 为前几轮新增方法，没有则跳过，不崩）
		if hasattr(bot, 'focus_window'):
			bot.focus_window()

		return bot

	except Exception as e:
		print(f" 软件启动/连接失败。 {e}")
		exit(1)