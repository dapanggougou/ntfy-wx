import wx
import wx.adv
import requests
import json
import threading
import time
from datetime import datetime
from urllib.parse import urlparse
import logging
import os

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NtfyMessage:
    """消息数据类"""
    def __init__(self, data):
        self.id = data.get('id', '')
        self.time = data.get('time', 0)
        self.event = data.get('event', '')
        self.topic = data.get('topic', '')
        self.message = data.get('message', '')
        self.title = data.get('title', '')
        self.tags = data.get('tags', [])
        self.priority = data.get('priority', 3)
        self.click = data.get('click', '')
        self.attachment = data.get('attachment', {})
        self.server = data.get('server', '')

    def get_formatted_time(self):
        """获取格式化的时间字符串"""
        return datetime.fromtimestamp(self.time).strftime('%Y-%m-%d %H:%M:%S')

    def get_priority_text(self):
        """获取优先级文本"""
        priority_map = {1: 'Min', 2: 'Low', 3: 'Default', 4: 'High', 5: 'Max'}
        return priority_map.get(self.priority, 'Unknown')

    def to_dict(self):
        """将消息对象转换为字典，用于持久化"""
        return {
            'id': self.id,
            'time': self.time,
            'event': self.event,
            'topic': self.topic,
            'message': self.message,
            'title': self.title,
            'tags': self.tags,
            'priority': self.priority,
            'click': self.click,
            'attachment': self.attachment,
            'server': self.server,
        }

class MessagePanel(wx.Panel):
    """消息显示面板（左右布局）"""
    def __init__(self, parent):
        super().__init__(parent)
        self.message_ids = set()
        self.messages = []
        self.init_ui()

    def init_ui(self):
        self.splitter = wx.SplitterWindow(self) # 将splitter设为实例属性

        left_panel = wx.Panel(self.splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        list_label = wx.StaticText(left_panel, label="消息列表")
        font = list_label.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        list_label.SetFont(font)

        self.message_list = wx.ListCtrl(left_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.message_list.AppendColumn('时间', width=120)
        self.message_list.AppendColumn('主题', width=100)
        self.message_list.AppendColumn('标题', width=150)
        self.message_list.AppendColumn('优先级', width=60)
        self.message_list.AppendColumn('服务器', width=150)

        left_sizer.Add(list_label, 0, wx.ALL, 5)
        left_sizer.Add(self.message_list, 1, wx.EXPAND | wx.ALL, 5)
        left_panel.SetSizer(left_sizer)

        right_panel = wx.Panel(self.splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        detail_label = wx.StaticText(right_panel, label="消息详情")
        detail_label.SetFont(font)

        self.detail_text = wx.TextCtrl(right_panel, style=wx.TE_MULTILINE | wx.TE_READONLY)

        right_sizer.Add(detail_label, 0, wx.ALL, 5)
        right_sizer.Add(self.detail_text, 1, wx.EXPAND | wx.ALL, 5)
        right_panel.SetSizer(right_sizer)

        self.splitter.SplitVertically(left_panel, right_panel, 500)
        self.splitter.SetMinimumPaneSize(200)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

        self.message_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_message_selected)

    def add_message(self, message):
        """添加新消息（带去重功能），返回是否成功添加"""
        if message.event == 'message' and message.id:
            if message.id in self.message_ids:
                logger.debug(f"消息已存在，跳过: {message.id}")
                return False

            self.message_ids.add(message.id)

            # 按时间倒序插入
            insert_index = 0
            for i, existing_msg in enumerate(self.messages):
                if message.time > existing_msg.time:
                    break
                insert_index = i + 1

            self.messages.insert(insert_index, message)
            self._insert_message_into_listctrl(insert_index, message)
            return True
        return False
    
    def load_messages(self, messages_data):
        """从持久化数据中批量加载消息"""
        self.clear_messages()
        
        # 转换并去重
        loaded_messages = []
        for data in messages_data:
            if data.get('id') not in self.message_ids:
                msg = NtfyMessage(data)
                loaded_messages.append(msg)
                self.message_ids.add(msg.id)
        
        # 按时间倒序排序
        self.messages = sorted(loaded_messages, key=lambda m: m.time, reverse=True)
        
        # 批量更新UI
        self.message_list.Freeze()
        try:
            for i, msg in enumerate(self.messages):
                self._insert_message_into_listctrl(i, msg)
        finally:
            self.message_list.Thaw()
        logger.info(f"成功加载 {len(self.messages)} 条历史消息。")

    def _insert_message_into_listctrl(self, index, message):
        """将消息插入到ListCtrl的指定位置"""
        list_index = self.message_list.InsertItem(index, message.get_formatted_time())
        self.message_list.SetItem(list_index, 1, message.topic)
        self.message_list.SetItem(list_index, 2, message.title or message.message[:30] or 'No Title')
        self.message_list.SetItem(list_index, 3, message.get_priority_text())
        self.message_list.SetItem(list_index, 4, message.server)

        if message.priority >= 4:
            self.message_list.SetItemTextColour(list_index, wx.Colour(255, 0, 0))
        elif message.priority <= 2:
            self.message_list.SetItemTextColour(list_index, wx.Colour(128, 128, 128))

    def on_message_selected(self, event):
        """消息选中事件"""
        selected = event.GetIndex()
        if 0 <= selected < len(self.messages):
            message = self.messages[selected]
            self.show_message_detail(message)

    def show_message_detail(self, message):
        """显示消息详情"""
        detail = f"ID: {message.id}\n"
        detail += f"服务器: {message.server}\n"
        detail += f"时间: {message.get_formatted_time()}\n"
        detail += f"主题: {message.topic}\n"
        detail += f"标题: {message.title}\n"
        detail += f"消息: {message.message}\n"
        detail += f"优先级: {message.get_priority_text()} ({message.priority})\n"
        detail += f"标签: {', '.join(message.tags)}\n"
        if message.click:
            detail += f"点击链接: {message.click}\n"
        if message.attachment:
            detail += f"附件: {message.attachment.get('name', 'N/A')}\n"
            detail += f"附件URL: {message.attachment.get('url', 'N/A')}\n"
        self.detail_text.SetValue(detail)

    def clear_messages(self):
        """清空消息"""
        self.message_list.DeleteAllItems()
        self.messages.clear()
        self.message_ids.clear()
        self.detail_text.SetValue("")

class SubscriptionPanel(wx.Panel):
    """多订阅管理面板"""
    def __init__(self, parent, on_subscription_change):
        super().__init__(parent)
        self.on_subscription_change = on_subscription_change
        self.subscriptions = []
        self.init_ui()

    def init_ui(self):
        sub_box = wx.StaticBox(self, label="订阅管理")
        sub_sizer = wx.StaticBoxSizer(sub_box, wx.VERTICAL)

        add_grid_sizer = wx.FlexGridSizer(2, 2, 5, 5)
        add_grid_sizer.AddGrowableCol(1)
        add_grid_sizer.Add(wx.StaticText(self, label="服务器URL:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT)
        self.server_input = wx.TextCtrl(self, value="https://ntfy.sh", style=wx.TE_PROCESS_ENTER)
        self.server_input.SetHint("例如: https://ntfy.sh")
        add_grid_sizer.Add(self.server_input, 1, wx.EXPAND)
        add_grid_sizer.Add(wx.StaticText(self, label="主题名称:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT)
        self.topic_input = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.topic_input.SetHint("输入主题")
        add_grid_sizer.Add(self.topic_input, 1, wx.EXPAND)
        self.add_btn = wx.Button(self, label="添加订阅")

        self.sub_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL, size=(-1, 150))
        self.sub_list.AppendColumn('服务器URL', width=150)
        self.sub_list.AppendColumn('主题', width=100)
        self.sub_list.AppendColumn('状态', width=80)
        self.sub_list.AppendColumn('消息数', width=60)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.remove_btn = wx.Button(self, label="删除", size=(60, -1))
        self.remove_btn.Enable(False)
        btn_sizer.Add(self.remove_btn, 0, wx.ALL, 5)

        sub_sizer.Add(add_grid_sizer, 0, wx.EXPAND | wx.ALL, 5)
        sub_sizer.Add(self.add_btn, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 5)
        sub_sizer.Add(self.sub_list, 1, wx.EXPAND | wx.ALL, 5)
        sub_sizer.Add(btn_sizer, 0)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(sub_sizer, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(main_sizer)

        self.add_btn.Bind(wx.EVT_BUTTON, self.on_add_subscription)
        self.remove_btn.Bind(wx.EVT_BUTTON, self.on_remove_subscription)
        self.sub_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_subscription_selected)
        self.topic_input.Bind(wx.EVT_TEXT_ENTER, self.on_add_subscription)
        self.server_input.Bind(wx.EVT_TEXT_ENTER, self.on_add_subscription)

    def add_subscription(self, server_url, topic_name):
        """添加订阅"""
        if not server_url or not topic_name:
            return False
        
        if not server_url.startswith(('http://', 'https://')):
            server_url = 'https://' + server_url
        server_url = server_url.rstrip('/')

        if any(s['server'] == server_url and s['topic'] == topic_name for s in self.subscriptions):
            return False

        sub_data = {'server': server_url, 'topic': topic_name, 'status': '未连接', 'message_count': 0}
        self.subscriptions.append(sub_data)

        index = self.sub_list.InsertItem(len(self.subscriptions) - 1, server_url)
        self.sub_list.SetItem(index, 1, topic_name)
        self.sub_list.SetItem(index, 2, '未连接')
        self.sub_list.SetItem(index, 3, '0')
        return True

    def on_add_subscription(self, event):
        """添加订阅事件"""
        server_url = self.server_input.GetValue().strip()
        topic_name = self.topic_input.GetValue().strip()
        
        if self.add_subscription(server_url, topic_name):
            self.topic_input.SetValue("")
            self.on_subscription_change()
        else:
            wx.MessageBox("服务器URL和主题名称不能为空，且订阅不能重复。", "错误", wx.OK | wx.ICON_WARNING)

    def on_remove_subscription(self, event):
        """删除订阅事件"""
        selected = self.sub_list.GetFirstSelected()
        if selected >= 0:
            sub = self.subscriptions[selected]
            msg = f"确定要删除订阅吗？\n服务器: {sub['server']}\n主题: {sub['topic']}"
            if wx.MessageBox(msg, "确认删除", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                self.subscriptions.pop(selected)
                self.sub_list.DeleteItem(selected)
                self.remove_btn.Enable(False)
                self.on_subscription_change()

    def on_subscription_selected(self, event):
        """订阅选择事件"""
        self.remove_btn.Enable(True)

    def get_subscriptions(self):
        """获取所有订阅"""
        return self.subscriptions

    def update_subscription_status(self, server_url, topic_name, status):
        """更新订阅状态"""
        for i, sub in enumerate(self.subscriptions):
            if sub['server'] == server_url and sub['topic'] == topic_name:
                sub['status'] = status
                self.sub_list.SetItem(i, 2, status)
                break

    def update_subscription_message_count(self, server_url, topic_name, count):
        """更新订阅消息数量"""
        for i, sub in enumerate(self.subscriptions):
            if sub['server'] == server_url and sub['topic'] == topic_name:
                sub['message_count'] = count
                self.sub_list.SetItem(i, 3, str(count))
                break

class ControlPanel(wx.Panel):
    """控制面板"""
    def __init__(self, parent, on_connect, on_disconnect, on_fetch_history):
        super().__init__(parent)
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_fetch_history = on_fetch_history
        self.init_ui()

    def init_ui(self):
        self.sub_panel = SubscriptionPanel(self, self.on_subscriptions_changed)
        connect_box = wx.StaticBox(self, label="连接控制")
        connect_sizer = wx.StaticBoxSizer(connect_box, wx.VERTICAL)
        self.auto_reconnect_cb = wx.CheckBox(self, label="启用自动重连")
        self.auto_reconnect_cb.SetValue(True)
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.connect_btn = wx.Button(self, label="连接所有订阅")
        self.disconnect_btn = wx.Button(self, label="断开所有连接")
        self.disconnect_btn.Enable(False)
        button_sizer.Add(self.connect_btn, 0, wx.ALL, 5)
        button_sizer.Add(self.disconnect_btn, 0, wx.ALL, 5)
        connect_sizer.Add(self.auto_reconnect_cb, 0, wx.ALL, 5)
        connect_sizer.Add(button_sizer, 0, wx.EXPAND)

        history_box = wx.StaticBox(self, label="历史消息")
        history_sizer = wx.StaticBoxSizer(history_box, wx.VERTICAL)
        history_control_sizer = wx.BoxSizer(wx.HORIZONTAL)
        history_label = wx.StaticText(self, label="获取时间范围:")
        self.since_choice = wx.Choice(self, choices=['10m', '1h', '24h', 'all'])
        self.since_choice.SetSelection(0)
        self.fetch_btn = wx.Button(self, label="获取历史消息")
        history_control_sizer.Add(history_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        history_control_sizer.Add(self.since_choice, 0, wx.ALL, 5)
        history_control_sizer.Add(self.fetch_btn, 0, wx.ALL, 5)
        history_sizer.Add(history_control_sizer, 0, wx.EXPAND)

        self.clear_btn = wx.Button(self, label="清空消息")
        self.status_text = wx.StaticText(self, label="状态: 未连接")

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self.sub_panel, 1, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(connect_sizer, 0, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(history_sizer, 0, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(self.clear_btn, 0, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(self.status_text, 0, wx.ALL, 5)
        self.SetSizer(main_sizer)

        self.connect_btn.Bind(wx.EVT_BUTTON, self.on_connect_click)
        self.disconnect_btn.Bind(wx.EVT_BUTTON, self.on_disconnect_click)
        self.fetch_btn.Bind(wx.EVT_BUTTON, self.on_fetch_click)
        self.clear_btn.Bind(wx.EVT_BUTTON, self.on_clear_click)

    def on_connect_click(self, event):
        subscriptions = self.sub_panel.get_subscriptions()
        auto_reconnect = self.auto_reconnect_cb.GetValue()
        if subscriptions:
            self.on_connect(subscriptions, auto_reconnect)
        else:
            wx.MessageBox("请至少添加一个订阅", "错误", wx.OK | wx.ICON_WARNING)

    def set_connected_state(self, connected):
        """根据连接状态更新UI"""
        self.connect_btn.Enable(not connected)
        self.disconnect_btn.Enable(connected)
        status = "已连接" if connected else "已断开"
        self.status_text.SetLabel(f"状态: {status}")

    def on_disconnect_click(self, event):
        self.on_disconnect()

    def on_fetch_click(self, event):
        subscriptions = self.sub_panel.get_subscriptions()
        since = self.since_choice.GetStringSelection()
        if subscriptions:
            self.on_fetch_history(subscriptions, since)
        else:
            wx.MessageBox("请至少添加一个订阅", "错误", wx.OK | wx.ICON_WARNING)

    def on_clear_click(self, event):
        parent = self.GetParent().GetParent() # ControlPanel -> Splitter -> Frame
        if hasattr(parent, 'message_panel'):
            parent.message_panel.clear_messages()
            parent.SetStatusText("消息已清空")
            for sub in self.sub_panel.get_subscriptions():
                parent.sub_message_counts[(sub['server'], sub['topic'])] = 0
                self.sub_panel.update_subscription_message_count(sub['server'], sub['topic'], 0)

    def on_subscriptions_changed(self):
        pass

    def update_status(self, status):
        wx.CallAfter(self.status_text.SetLabel, f"状态: {status}")

    def update_subscription_status(self, server_url, topic_name, status):
        wx.CallAfter(self.sub_panel.update_subscription_status, server_url, topic_name, status)

class NotificationIcon(wx.adv.TaskBarIcon):
    """系统托盘图标"""
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.set_icon()
        
        # *** BUG修复：在这里添加对通知点击事件的绑定 ***
        # 当用户点击从托盘弹出的通知气泡时，会触发此事件。
        # 我们将它绑定到 on_show 方法，以实现显示和激活主窗口的功能。
        self.Bind(wx.adv.EVT_TASKBAR_BALLOON_CLICK, self.on_show)
      
    def set_icon(self):
        icon = wx.Icon()
        # 创建一个简单的位图作为图标
        bmp = wx.Bitmap(16, 16)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.Colour(0, 120, 215))) # 蓝色背景
        dc.Clear()
        dc.SetTextForeground(wx.Colour(255, 255, 255)) # 白色文字
        font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        dc.SetFont(font)
        dc.DrawText("N", 2, -1) # 在图标上写一个'N'
        dc.SelectObject(wx.NullBitmap)
        icon.CopyFromBitmap(bmp)
        self.SetIcon(icon, "Ntfy消息监听器")
  
    def CreatePopupMenu(self):
        menu = wx.Menu()
        show_item = menu.Append(wx.ID_ANY, "显示主窗口")
        menu.AppendSeparator()
        exit_item = menu.Append(wx.ID_EXIT, "退出")
        self.Bind(wx.EVT_MENU, self.on_show, show_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        return menu
  
    def OnLeftDoubleClick(self, event):
        self.on_show(event)
  
    def on_show(self, event):
        self.parent.Restore()
        self.parent.Show()
        self.parent.Raise()
  
    def on_exit(self, event):
        self.parent.Close()
  
    def show_notification(self, title, message):
        """显示系统托盘通知"""
        self.ShowBalloon(title, message, 3000, wx.ICON_INFORMATION)

class NtfyGUI(wx.Frame):
    """主窗口"""
    CONFIG_FILE = "ntfy_client_data.json"

    def __init__(self):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
          
        super().__init__(None, title="Ntfy消息监听器", size=(1200, 800))
        self.listening_threads = {}
        self.stop_listening = False
        self.auto_reconnect = True
        self.current_subscriptions = []
        self.reconnect_delay = 5
        self.sub_message_counts = {}
      
        self.init_ui()
        self.init_menu()
        self.init_tray()
        self.Center()
      
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        self.Bind(wx.EVT_ICONIZE, self.OnIconize)

        # 启动时加载数据并自动连接
        self.load_data()
        self.auto_start_listening()
      
    def init_ui(self):
        self.splitter = wx.SplitterWindow(self)
        self.control_panel = ControlPanel(
            self.splitter, 
            self.start_listening, 
            self.stop_listening_func,
            self.fetch_history
        )
        self.message_panel = MessagePanel(self.splitter)
        self.splitter.SplitVertically(self.control_panel, self.message_panel, 450)
        self.splitter.SetMinimumPaneSize(350)
        self.CreateStatusBar()
        self.SetStatusText("准备就绪")
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)
  
    def init_menu(self):
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        minimize_item = file_menu.Append(wx.ID_ANY, "最小化到托盘\tCtrl+M")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "退出\tCtrl+Q")
        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, "关于")
        menubar.Append(file_menu, "文件")
        menubar.Append(help_menu, "帮助")
        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, self.on_minimize, minimize_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
  
    def init_tray(self):
        self.tray_icon = NotificationIcon(self)

    def auto_start_listening(self):
        """程序启动时自动开始连接"""
        subscriptions = self.control_panel.sub_panel.get_subscriptions()
        auto_reconnect = self.control_panel.auto_reconnect_cb.GetValue()
        if subscriptions:
            logger.info("检测到已保存的订阅，启动时自动连接...")
            self.start_listening(subscriptions, auto_reconnect)
        else:
            logger.info("无已保存的订阅，等待用户操作。")

    def start_listening(self, subscriptions, auto_reconnect):
        """开始监听多个订阅"""
        if self.listening_threads:
            logger.warning("已在监听中，请先断开。")
            return

        self.stop_listening = False
        self.auto_reconnect = auto_reconnect
        self.current_subscriptions = subscriptions
      
        for sub in subscriptions:
            sub_key = (sub['server'], sub['topic'])
            if sub_key not in self.sub_message_counts:
                self.sub_message_counts[sub_key] = 0
            
            thread = threading.Thread(target=self.listen_subscription_with_reconnect, args=(sub,), daemon=True)
            self.listening_threads[sub_key] = thread
            thread.start()
          
        wx.CallAfter(self.SetStatusText, f"正在监听 {len(subscriptions)} 个订阅")
        wx.CallAfter(self.control_panel.set_connected_state, True)
  
    def stop_listening_func(self):
        """停止监听所有订阅"""
        self.stop_listening = True
        self.auto_reconnect = False
      
        for sub in self.current_subscriptions:
            wx.CallAfter(self.control_panel.update_subscription_status, sub['server'], sub['topic'], "已断开")
        
        self.listening_threads.clear()
          
        wx.CallAfter(self.SetStatusText, "已停止监听")
        wx.CallAfter(self.control_panel.set_connected_state, False)
  
    def listen_subscription_with_reconnect(self, subscription):
        """带自动重连的单订阅监听函数"""
        reconnect_attempts = 0
        server_url, topic = subscription['server'], subscription['topic']
        sub_key = (server_url, topic)

        while not self.stop_listening:
            try:
                wx.CallAfter(self.control_panel.update_subscription_status, server_url, topic, "连接中...")
                self.listen_subscription_messages(subscription)
              
                if self.stop_listening: break
                
                if self.auto_reconnect:
                    reconnect_attempts += 1
                    logger.info(f"订阅 {sub_key} 连接断开，尝试重连... (第{reconnect_attempts}次)")
                    wx.CallAfter(self.control_panel.update_subscription_status, server_url, topic, f"重连中({reconnect_attempts})")
                    for _ in range(self.reconnect_delay):
                        if self.stop_listening: return
                        time.sleep(1)
                else: break
                  
            except Exception as e:
                if self.stop_listening: break

                if self.auto_reconnect:
                    reconnect_attempts += 1
                    logger.error(f"订阅 {sub_key} 连接错误: {e}, 尝试重连... (第{reconnect_attempts}次)")
                    wx.CallAfter(self.control_panel.update_subscription_status, server_url, topic, f"错误,重连中({reconnect_attempts})")
                    for _ in range(self.reconnect_delay):
                        if self.stop_listening: return
                        time.sleep(1)
                else:
                    wx.CallAfter(self.control_panel.update_subscription_status, server_url, topic, "连接错误")
                    break
      
        if sub_key in self.listening_threads:
            del self.listening_threads[sub_key]
        wx.CallAfter(self.control_panel.update_subscription_status, server_url, topic, "已断开")

    def add_message_and_notify(self, message, is_live_message=False):
        """
        在主线程中添加消息到UI，并根据来源决定是否发送通知。
        - message: NtfyMessage 对象
        - is_live_message: bool, True表示来自实时流，False表示来自历史记录
        """
        is_newly_added = self.message_panel.add_message(message)

        if is_newly_added:
            sub_key = (message.server, message.topic)
            self.sub_message_counts[sub_key] = self.sub_message_counts.get(sub_key, 0) + 1
            self.control_panel.sub_panel.update_subscription_message_count(
                message.server, message.topic, self.sub_message_counts[sub_key]
            )

            if is_live_message:
                self.SetStatusText(f"[{message.topic}] {message.title or message.message[:30]}")
                title = f"新消息 - {message.topic}"
                notification_text = message.title or message.message[:50]
                self.tray_icon.show_notification(title, notification_text)

  
    def listen_subscription_messages(self, subscription):
        """监听单个订阅消息的核心函数"""
        server_url, topic = subscription['server'], subscription['topic']
        sub_key = (server_url, topic)
        url = f"{server_url}/{topic}/json"
        logger.info(f"连接到订阅 {sub_key}: {url}")
      
        try:
            # 修改点：将 read_timeout 设置为 None，表示不限制读取超时。
            # 这样只有在TCP连接真正中断时，iter_lines才会抛出异常，从而触发重连。
            # 这完美解决了“因长时间无消息而错误重连”的问题。
            with requests.get(url, stream=True, timeout=(5, None)) as resp:
                resp.raise_for_status()
                wx.CallAfter(self.control_panel.update_subscription_status, server_url, topic, "已连接")
          
                for line in resp.iter_lines():
                    if self.stop_listening: break
                    if not line: continue
                    
                    try:
                        data = json.loads(line.decode('utf-8'))
                        data['server'] = server_url
                        message = NtfyMessage(data)
                        wx.CallAfter(self.add_message_and_notify, message, is_live_message=True)
                                
                    except json.JSONDecodeError as e:
                        logger.warning(f"JSON解析错误: {e}, on line: {line}")
                        
        except requests.RequestException as e:
            logger.error(f"订阅 {sub_key} 请求错误: {e}")
            raise

  
    def fetch_history(self, subscriptions, since):
        """获取多个订阅的历史消息"""
        def fetch_thread():
            total_messages_fetched = 0
            for sub in subscriptions:
                server_url, topic = sub['server'], sub['topic']
                sub_key = (server_url, topic)
                try:
                    url = f"{server_url}/{topic}/json?poll=1&since={since}"
                    logger.info(f"获取订阅 {sub_key} 历史消息: {url}")
                    resp = requests.get(url, timeout=10)
                    resp.raise_for_status()
                  
                    for line in resp.iter_lines():
                        if not line: continue
                        try:
                            data = json.loads(line.decode('utf-8'))
                            data['server'] = server_url
                            message = NtfyMessage(data)
                            wx.CallAfter(self.add_message_and_notify, message, is_live_message=False)
                            
                            if message.event == 'message':
                                total_messages_fetched += 1

                        except json.JSONDecodeError as e:
                            logger.warning(f"JSON解析错误: {e}")
                  
                except requests.RequestException as e:
                    logger.error(f"获取订阅 {sub_key} 历史消息失败: {e}")
          
            wx.CallAfter(self.SetStatusText, f"历史消息获取完成: 新增 {total_messages_fetched} 条 (since={since})")
      
        threading.Thread(target=fetch_thread, daemon=True).start()
        self.SetStatusText(f"正在获取 {len(subscriptions)} 个订阅的历史消息...")
  
    def on_minimize(self, event):
        self.Hide()
  
    def OnIconize(self, event):
        if event.IsIconized():
            self.Hide()
  
    def on_exit(self, event):
        self.Close()
  
    def on_about(self, event):
        info = wx.adv.AboutDialogInfo()
        info.SetName("Ntfy消息监听器")
        info.SetVersion("4.1 - 通知功能增强版")
        info.SetDescription(
            "一个用于监听ntfy.sh消息的GUI应用程序\n\n"
            "功能特性:\n"
            "• 持久化订阅、消息和窗口布局\n"
            "• 启动时自动连接所有订阅\n"
            "• 支持为每个主题指定不同服务器\n"
            "• 多订阅同时监听\n"
            "• 消息自动去重\n"
            "• 自动重连机制\n"
            "• 历史消息获取\n"
            "• 实时消息系统托盘通知\n"
        )
        info.SetWebSite("https://ntfy.sh")
        wx.adv.AboutBox(info)
  
    def OnClose(self, event):
        """关闭窗口时保存数据"""
        self.save_data()
        self.stop_listening = True
        self.auto_reconnect = False
        if hasattr(self, 'tray_icon'):
            self.tray_icon.Destroy()
        event.Skip()

    def save_data(self):
        """将数据保存到JSON文件"""
        try:
            subs_to_save = [
                {'server': s['server'], 'topic': s['topic']} 
                for s in self.control_panel.sub_panel.get_subscriptions()
            ]
            window_settings = {
                'size': self.GetSize().Get(),
                'position': self.GetPosition().Get(),
                'splitter_position': self.splitter.GetSashPosition()
            }
            messages_to_save = [msg.to_dict() for msg in self.message_panel.messages]
            data_to_save = {
                'subscriptions': subs_to_save,
                'window_settings': window_settings,
                'messages': messages_to_save
            }
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=4, ensure_ascii=False)
            logger.info(f"数据已成功保存到 {self.CONFIG_FILE}")
        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    def load_data(self):
        """从JSON文件加载数据"""
        if not os.path.exists(self.CONFIG_FILE):
            logger.info(f"配置文件 {self.CONFIG_FILE} 不存在，使用默认设置。")
            return
        try:
            with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            settings = data.get('window_settings', {})
            if 'size' in settings: self.SetSize(tuple(settings['size']))
            if 'position' in settings: self.SetPosition(tuple(settings['position']))
            if 'splitter_position' in settings: self.splitter.SetSashPosition(settings['splitter_position'])
            
            sub_panel = self.control_panel.sub_panel
            for sub in data.get('subscriptions', []):
                sub_panel.add_subscription(sub['server'], sub['topic'])
            
            messages = data.get('messages', [])
            if messages:
                self.message_panel.load_messages(messages)
            
            for sub in sub_panel.get_subscriptions():
                sub_key = (sub['server'], sub['topic'])
                count = sum(1 for m in self.message_panel.messages if m.server == sub['server'] and m.topic == sub['topic'])
                self.sub_message_counts[sub_key] = count
                sub_panel.update_subscription_message_count(sub['server'], sub['topic'], count)

            logger.info(f"数据已从 {self.CONFIG_FILE} 加载。")
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"加载数据失败，文件可能已损坏或格式不正确: {e}")
        except Exception as e:
            logger.error(f"加载数据时发生未知错误: {e}")

class NtfyApp(wx.App):
    """应用程序类"""
    def OnInit(self):
        frame = NtfyGUI()
        frame.Show()
        return True

if __name__ == '__main__':
    app = NtfyApp()
    app.MainLoop()
