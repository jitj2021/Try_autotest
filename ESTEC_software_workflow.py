# -*- coding: utf-8 -*-
import uiautomation as automation

# 数据目录
import os
# 基于脚本所在目录拼接文件路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))



def resource_path(relative_path):
    """Resolve project resources relative to this script, independent of CWD."""
    from pathlib import Path
    path = Path(relative_path).expanduser()
    if path.is_absolute():
        return str(path)
    return str((Path(BASE_DIR) / path).resolve())

def main():
    # 脚本目录下示例数据目录
    # file_path_export_default=resource_path(r"TEST_data\ESTEC\Datas\Export_data\ESTEC数据_新模板")
    file_path_import=resource_path(r"TEST_data\ESTEC\Datas\Raw_data")

    # 运行前先检查外部依赖，避免启动软件后才因缺少测试资源而失败。
    app_path_test = r"C:\Program Files (x86)\ESTEC-P\ESTEC.exe"
    required_resources = [
        file_path_import,
        os.path.join(file_path_import, "ESTEC含高程数据模板.xls"),
        resource_path(r"TEST_data\ESTEC\btn_png\初始界面界面_菜单按钮列表\按钮\按钮_新建.png"),
        resource_path(r"TEST_data\ESTEC\btn_png\检测数据界面_菜单按钮列表\按钮\10_导出到excel.png"),
        resource_path(r"TEST_data\ESTEC\btn_png\检测数据界面_菜单按钮列表\按钮\11_从excel导入.png"),
    ]
    missing_resources = [path for path in required_resources if not os.path.exists(path)]
    if missing_resources:
        details = "\n".join(f"  - {path}" for path in missing_resources)
        raise FileNotFoundError(
            "测试无法启动，缺少以下资源（请补齐 TEST_data 目录/测试数据）：\n" + details
        )
    if not os.path.isfile(app_path_test):
        raise FileNotFoundError(f"找不到被测软件 ESTEC.exe：{app_path_test}")

    # 待测软件数据存储目录
    Estec_rawdata_path=os.path.abspath(r'C:\\test\\data\\ESTEC\\Estec_rawdata') #ESTEC软件原始数据保存目录
    Estec_extdata_path=os.path.abspath(r'C:\\test\\data\\ESTEC\\Estec_extdata') #ESTEC软件导出数据保存目录
    test_report_path=os.path.abspath(r'C:\\test\\data\\ESTEC\\test_report') #ESTEC软件导出测试报告保存目录
    test_logs_path=os.path.abspath(r'C:\\test\\data\\ESTEC\\logs') #ESTEC软件测试日志保存目录

    #######################################
    # 准备测试数据

    # 1、只创建目标文件夹
    from Modules.file_copy_batch import batch_copy

    target_dirs = [
        Estec_rawdata_path,
        Estec_extdata_path,
        test_report_path,
        test_logs_path    
    ]

    batch_copy(
        [],                 # 空任务列表，表示不复制任何文件/目录
        extra_dirs=target_dirs,
        verbose=True
    )

    # 2、复制测试数据至目标文件夹

    from Modules.file_copy_batch import batch_copy_from_lists

    sources = [
        file_path_import,
        # r"D:\\data\\b",
    ]

    targets = [
        Estec_rawdata_path,
        # r"D:\\data\\b1",
    ]

    batch_copy_from_lists(
        sources,
        targets,
        clean_target=False,
        recursive=True,
        overwrite=True,
    )


    #######################################


    # 测试软件目录
    # app_path_test=r"C:\\Program Files (x86)\\ESTEC-Debug_11_Outdated\\ESTEC.exe"
    app_path_test=r"C:\\Program Files (x86)\\ESTEC-P\\ESTEC.exe"

    # 待测软件主窗口标题
    title_name_main=["嘉信埋地钢质管道防腐层检测数据处理系统(ESTEC)","嘉信埋地钢质管道防腐层检测数据处理系统标准版(ESTEC-S)"]
    from Modules.Desktop_Auto_Unified import UnifiedDesktopController
    import time
    from datetime import datetime


    import warnings  # 导入 warnings 模块
    warnings.filterwarnings("ignore", message=".*32-bit application should be automated using 32-bit Python.*") # 全局屏蔽 pywinauto 的 32位/64位不匹配警告

    # ###连接被测软件、启动软件
    from Modules.Desktop_bot_boot import bot_boot
    # 指定被测软件启动方式(3种)
    bot = bot_boot(boot_select=1, app_path_test=app_path_test,window_title=title_name_main)
    # bot = bot_boot(boot_select=2,window_title=title_name_main)
    # bot = bot_boot(boot_select=3,target_pid=14912)

    # 检查 bot 是否成功创建
    if bot is None or bot.main_window is None:
        print("❌ 软件未成功启动/连接，终止测试！")
        exit(1) # 退出程序，返回错误码 1
    # ================= 2. 执行测试操作 =================
    print("开始测试...")


    # 查看主界面并截图,前置步骤
    def es_main_window():
        try:
            time.sleep(0.2)    
            #######################################
            print("⏳ 正在等待'关于'弹窗...")        
            popup = bot.wait_for_popup("关于",timeout=3)
            if popup:
               bot.click(target="确定(&O)",mode="pywinauto")
            else:
                print("未找到'关于'弹窗！")      
            time.sleep(1)
        finally:
            print("✅启动软件，关闭弹窗-->测试完成。")

    # 前置步骤，后续测试依赖此步骤执行完毕
    es_main_window()
    
    # 新建基础卷
    def es_new_basic_table():
        try:
            time.sleep(0.2)    # 菜单 Menu , 按钮 Button
            #######################################
            print("⏳ 准备新建基础卷_使用快捷按钮操作...")
            bot.click(resource_path(r"TEST_data\ESTEC\btn_png\初始界面界面_菜单按钮列表\按钮\按钮_新建.png"), mode='image', color=True, timeout=0.5, screenshot_delay=0.6)
            time.sleep(0.6) #等待新建窗口加载完成
        
            # ### a.导出excel模板
            # print("⏳ 准备导出基础卷excel模板...")
            bot.click(resource_path(r"TEST_data\ESTEC\btn_png\检测数据界面_菜单按钮列表\按钮\10_导出到excel.png"), mode='image', color=True, timeout=0.5, screenshot_delay=0.6)
            time.sleep(0.2) #等待导出提示窗口加载完成
            t_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
            # print(t_suffix)  # 例如：20260621_143025
            # 导出数据文件(“打开文件窗口”调用函数)
            bot.select_file_in_open_dialog(
                file_path=Estec_extdata_path+"\\ESTEC数据_模板_"+f"{t_suffix}",            
                base_dir=BASE_DIR,
                popup_title="另存为",
                input_control_type="ComboBox",
                target_button_regex=r"保存(\(&S\)|\(S\))?",
                popup_timeout=0.6,
                control_timeout=0.5,
                screenshot_delay=0.6,
                after_open_delay=0.3,
                raise_on_error=False
            )           
            time.sleep(0.1) 

            popup = bot.wait_for_popup("提示",timeout=0.6)
            if popup:
               bot.click(target="确定",mode="pywinauto")
            else:
                print("未找到按钮，点击失败！")

            ###b.从excel导入数据
            # 导入excel数据-旧版格式
            # bot.click("从Excel导入", mode='uiautomation', timeout=3, screenshot_delay=1)
            bot.click(resource_path(r"TEST_data\ESTEC\btn_png\检测数据界面_菜单按钮列表\按钮\11_从excel导入.png"), mode='image', color=True, timeout=0.5, screenshot_delay=0.6)
            time.sleep(1)
        

            # 打开本地数据文件(“打开文件窗口”调用函数)
            bot.select_file_in_open_dialog(
                file_path=Estec_rawdata_path+r"\\ESTEC含高程数据模板.xls",            
                base_dir=BASE_DIR,
                popup_title="从Excel中导入检测数据",
                input_control_type="ComboBox",
                target_button_regex=r"打开(\(&O\)|\(O\))?",
                popup_timeout=0.6,
                control_timeout=0.6,
                screenshot_delay=0.5,
                after_open_delay=0.3,
                raise_on_error=False
            )        
        
            print("⏳ 准备核对数据一致性_新格式...")
            time.sleep(0.5) # 稍微增加等待时间，确保表格渲染完成
        
            # 1. 预期数据
            # 注意：这里的 Key 必须与软件界面上的列头文字高度相似
            # 如果软件显示的是 "距离(m)"，这里最好也是 "距离(m)"
            expected_data = [
                {'序号': 1.0, '距离(m)': 0.0, '电流(mA)': 566.75, '埋深(m)': 1.19, '高程(m)': 127.1},
                {'序号': 2.0, '距离(m)': 56.2, '电流(mA)': 610.83, '埋深(m)': 1.20, '高程(m)': 127.13},
                {'序号': 3.0, '距离(m)': 101.9, '电流(mA)': 465.41, '埋深(m)': 1.34, '高程(m)': 128.14},
                {'序号': 4.0, '距离(m)': 134.9, '电流(mA)': 453.39, '埋深(m)': 1.48, '高程(m)': 126.14},
                {'序号': 5.0, '距离(m)': 205.4, '电流(mA)': 409.38, '埋深(m)': 1.45, '高程(m)': 125.12},
            ]
        
            # 2. 调用核对
            # strict_mode=True: 如果实际表格少了"高程(m)"这一列，或者多了其他列，直接报错 FAIL
            is_ok, report = bot.check_table_data(
                expected_data=expected_data, 
                row_start=0,       
                tolerance=0.01,
                strict_mode=True  # 开启严格模式
            )
        
            if is_ok:
                print("✅ 数据核对一致")
            else:
                print("❌ 数据核对失败，请查看报告中的详细差异")
                # 可以在这里打印 report['details'] 方便调试
                if 'details' in report:
                    for line in report['details']:
                        print(line)
        
        finally:
            print("✅新建基础卷-->测试完成。")   # 新版、旧版数据格式 

    # 2、新建基础卷
    es_new_basic_table()

    # 打开基础卷数据
    # bot.click_menu(['文件(F)', '打开(O)', '基础卷(B)'])

    # 切换管道注释界面
    bot.click_menu(['切换(V)', '管道注释(M)'])

    # 录入管道注释
    def pip_note():
        bot.input_by_label('管线名称：', '测试管线001', automation_id="txtPipeName")
        bot.input_by_label("检测日期：", "2020年05月06日", automation_id="dateTimePicker1")
        bot.input_by_label('管体规格：', 'φ219X7',    control_type='ComboBox')
        bot.input_by_label('管线类别：', '天然气管线',       automation_id='comPipeType')
        bot.input_by_label('信号频率：', '128',        automation_id='comMsgFrequency')
        bot.input_by_label('信号供入点：', '阀井A点',      automation_id='comMsgEntrance')
        bot.input_by_label('防腐类别：', '三层PE',    control_type='ComboBox')
        bot.input_by_label('管段位置：', '中段',       automation_id='comPipeLocation')
        bot.input_by_label('初始电流：', '600',         automation_id='comIniCurrent')
        bot.input_by_label('描述信息：', '测试描述ABC！@123',automation_id='txtDescrip')  


        # 检查界面是否为管道注释界面
        # bot.check(resource_path(r"TEST_data\ESTEC\btn_png\界面元素\管道注释界面.png"), mode='image', color=True, timeout=0.5)
    
    pip_note()

    # 1、保存基础卷数据
    bot.click_menu(['文件(F)', '保存(S)'])
    # 导出数据文件(“打开文件窗口”调用函数)
    t_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    bot.select_file_in_open_dialog(
        file_path=Estec_extdata_path+"\\保存_"+f"{t_suffix}.PDS",            
        base_dir=BASE_DIR,
        popup_title="保存",
        input_control_type="ComboBox",
        target_button_regex=r"保存(\(&S\)|\(S\))?",
        popup_timeout=0.6,
        control_timeout=0.5,
        screenshot_delay=0.6,
        after_open_delay=0.3,
        raise_on_error=False
    )           
    time.sleep(0.1) 

    popup = bot.wait_for_popup("提示",timeout=0.6)
    if popup:
       bot.click(target="确定",mode="pywinauto")
    else:
        print("未找到按钮，点击失败！")

    # 2、另存为基础卷数据
    bot.click_menu(['文件(F)', '保存(S)'])
    # 导出数据文件(“打开文件窗口”调用函数)
    t_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    bot.select_file_in_open_dialog(
        file_path=Estec_extdata_path+"\\另存_"+f"{t_suffix}.PDS",            
        base_dir=BASE_DIR,
        # popup_title="另存为(A)",
        popup_title="保存",
        input_control_type="ComboBox",
        target_button_regex=r"保存(\(&S\)|\(S\))?",
        popup_timeout=0.6,
        control_timeout=0.5,
        screenshot_delay=0.6,
        after_open_delay=0.3,
        raise_on_error=False
    )           
    time.sleep(0.1) 

    popup = bot.wait_for_popup("提示",timeout=0.6)
    if popup:
       bot.click(target="确定",mode="pywinauto")
    else:
        print("未找到按钮，点击失败！")






    ###########
    # 测试结束，关闭软件并生成报告
    bot.close_app()
    bot.generate_report()

if __name__ == "__main__":
    main()
