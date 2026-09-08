import json
import sys
import time
import threading
import queue
import pymem.process
from groq import Groq
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QSettings
from PyQt5.QtWidgets import (QApplication, QLabel, QHBoxLayout, QVBoxLayout, QWidget, QListWidgetItem,
                             QListWidget, QLineEdit, QPushButton, QComboBox)
import ctypes
from ctypes import wintypes
import winreg
import re
import logging

logging.basicConfig(
    filename='translator_debug.log',
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

pm = pymem.Pymem("ShootersPool Online Standalone.exe")
cegui_module = pymem.process.module_from_name(pm.process_handle, "CEGUIBase.dll")
base_offset = 0x001F99E0
offsets = [0x2C, 0x1EC, 0x14, 0x1EC, 0x0, 0x360, 0x0]

buffer = ctypes.create_unicode_buffer(1024)
size = wintypes.DWORD(1024)
ctypes.windll.kernel32.QueryFullProcessImageNameW(pm.process_handle, 0, buffer, ctypes.byref(size))
exe_path = buffer.value

if exe_path:
    key_path = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, exe_path, 0, winreg.REG_SZ, "~ DISABLEDXMAXIMIZEDWINDOWEDMODE")
    except Exception as e:
        logging.error(f"Window Maximisation Error: {e}")


LANGUAGE_MAP = {
    "English": ("en", "English"),
    "Español": ("es", "Spanish"),
    "Français": ("fr", "French"),
    "Português": ("pt", "Portuguese"),
    "普通话": ("zh", "Mandarin Chinese"),
    "广东话": ("yue", "Cantonese"),
    "Deutsch": ("de", "German"),
    "Italiano": ("it", "Italian"),
    "Русский": ("ru", "Russian"),
    "한국어": ("ko", "Korean"),
    "日本語": ("ja", "Japanese")
}
with open("localisation.json", "r", encoding="utf-8") as f:
    LOCALISATION = json.load(f)

def make_game_fake_borderless(window_title):
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, window_title)
    if hwnd:
        GWL_STYLE = -16
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000

        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        style &= ~WS_CAPTION
        style &= ~WS_THICKFRAME
        user32.SetWindowLongW(hwnd, GWL_STYLE, style)

        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)

        # Force the window to update its frame (0x0027 = NOMOVE | NOSIZE | NOZORDER | FRAMECHANGED)
        user32.SetWindowPos(hwnd, 0, 0, 0, screen_width, screen_height, 0x0024)

STATE_ROLE = Qt.UserRole + 1

log_queue = queue.Queue(maxsize=1)


def get_pointer_address(base, offsets):
    addr = pm.read_uint(base + base_offset)
    for offset in offsets[:-1]:
        addr = pm.read_uint(addr + offset)
    return addr + offsets[-1]


def read_chat_log_worker():
    while True:
        try:
            chat_address = get_pointer_address(cegui_module.lpBaseOfDll, offsets)
            chunk_size = 256  # Reduced from 4096 to safely approach page boundaries
            max_size = 1048576
            chat_bytes = bytearray()
            current_addr = chat_address

            while len(chat_bytes) < max_size:
                try:
                    chunk = pm.read_bytes(current_addr, chunk_size)
                except pymem.exception.MemoryReadError:
                    # We hit a memory boundary (Error 299). Stop reading chunks
                    # and proceed with the bytes we successfully gathered so far.
                    break

                null_pos = -1
                for i in range(0, len(chunk) - 3, 4):
                    if chunk[i] == 0 and chunk[i + 1] == 0 and chunk[i + 2] == 0 and chunk[i + 3] == 0:
                        null_pos = i
                        break
                if null_pos != -1:
                    chat_bytes.extend(chunk[:null_pos])
                    break
                else:
                    chat_bytes.extend(chunk)
                    current_addr += chunk_size

            chat_text = chat_bytes.decode("utf-32le", errors="ignore")

            # Only push to queue if we actually extracted something
            if chat_text:
                if log_queue.full():
                    try:
                        log_queue.get_nowait()
                    except queue.Empty:
                        pass
                log_queue.put(chat_text)

        except Exception as error:
            # This now only catches base pointer resolution failures, not string read failures
            logging.warning(f"Memory Pointer Error: {error}")

        time.sleep(1)


def format_chat_log(chat_text):
    lines = chat_text.split("\n")
    formatted_lines = []
    for line in lines:
        rest = line[19:].split("> ")
        if len(rest) > 1:
            author = rest[0]
            msg = rest[1].strip()
            msg_clean = ""
            for char in msg:
                if ord(char) >= 32:
                    msg_clean += char
            msg_clean = re.sub(r'\[.*?\]', '', msg_clean).strip()
            formatted_lines.append((author, msg_clean))
    return formatted_lines


class TranslationThread(QThread):
    translation_done = pyqtSignal(QListWidgetItem, str)

    def __init__(self, client, item, text, lang):
        super().__init__()
        self.client = client
        self.item = item
        self.text = text
        self.lang = lang

    def run(self):
        try:
            response = self.client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[  # type: ignore
                    {"role": "system",
                     "content": f"Translate this cuesports simulator gaming chat to {self.lang}. Output only the"
                                f" translation prefixed with the source language code in brackets (e.g., [fr])."},
                    {"role": "user", "content": self.text}
                ]
            )
            translation = response.choices[0].message.content.strip()
            self.translation_done.emit(self.item, translation)
        except Exception as error:
            logging.error(f"Thread API Error: {error}")
            self.translation_done.emit(self.item, "[Translation Failed]")


class ReverseTranslationThread(QThread):
    translation_done = pyqtSignal(str)

    def __init__(self, client, text, source_lang, target_lang):
        super().__init__()
        self.client = client
        self.text = text
        self.source_lang = source_lang
        self.target_lang = target_lang

    def run(self):
        try:
            response = self.client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[ # type: ignore
                    {"role": "system", "content": f"Translate this message to the language code: {self.target_lang}."
                                                  f" Adapt {self.source_lang} gaming slang into the target language's "
                                                  f"natural equivalent. Output ONLY the translated text."},
                    {"role": "user", "content": self.text}
                ]
            )
            translation = response.choices[0].message.content.strip()
            self.translation_done.emit(translation)
        except Exception as error:
            logging.error(f"Reverse Translation Error: {error}")
            self.translation_done.emit("")


class ChatOverlay(QWidget):
    def __init__(self, api_key, lang):
        super().__init__()
        self.close_btn = None
        self.rev_thread = None
        self.reply_btn = None
        self.reply_input = None
        self.lang_input = None
        self.drag_tab = None
        self.thread = None
        self.old_pos = None
        self.api_key = api_key
        self.client = Groq(api_key=self.api_key) if self.api_key else None
        self.lang_code = LANGUAGE_MAP[lang][0]
        self.lang_english = LANGUAGE_MAP[lang][1]

        self.seen_messages = 0
        self.chat_list = QListWidget(self)
        self.init_ui()

        self.active_threads = []
        self.full_log = []

        # Start background memory thread
        self.worker_thread = threading.Thread(target=read_chat_log_worker, daemon=True)
        self.worker_thread.start()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(100)

    def init_ui(self):
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(100, 100, 250, 400)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        top_bar_layout = QHBoxLayout()
        top_bar_layout.setSpacing(0)

        self.drag_tab = QLabel("⋮⋮⋮")
        self.drag_tab.setAlignment(Qt.AlignCenter)
        self.drag_tab.setStyleSheet("color: white; background: rgba(0, 0, 0, 150); font-weight: bold;")

        self.close_btn = QPushButton("X")
        self.close_btn.setFixedWidth(30)
        self.close_btn.setStyleSheet(
            "QPushButton { color: white; background: rgba(0, 0, 0, 150); font-weight: bold; border: none; }"
            "QPushButton:hover { background: red; }"
        )
        # Use QApplication.quit() to ensure all threads and hidden windows terminate safely
        self.close_btn.clicked.connect(QApplication.quit)

        top_bar_layout.addWidget(self.drag_tab)
        top_bar_layout.addWidget(self.close_btn)

        layout.addLayout(top_bar_layout)

        self.chat_list.setStyleSheet(
            "QListWidget { background-color: rgba(0, 0, 0, 150); color: white; border: none; font-size: 14px; }"
            "QListWidget::item { padding: 5px; }"
            "QListWidget::item:hover { background-color: rgba(255, 255, 255, 50); }"

            "QScrollBar:vertical { background: transparent; width: 10px; margin: 0px; }"
            "QScrollBar::handle:vertical { background: rgba(255, 255, 255, 100); border-radius: 5px; min-height: 20px;}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )

        self.chat_list.setWordWrap(True)
        self.chat_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.chat_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.chat_list.itemClicked.connect(self.translate_message)
        layout.addWidget(self.chat_list)

        input_layout = QHBoxLayout()

        self.lang_input = QLineEdit()
        self.lang_input.setFixedWidth(40)
        self.lang_input.setStyleSheet("background-color: rgba(0, 0, 0, 150); color: white;")

        self.reply_input = QLineEdit()
        self.reply_input.setPlaceholderText(LOCALISATION["reply"][self.lang_code])
        self.reply_input.setStyleSheet("background-color: rgba(0, 0, 0, 150); color: white;")

        self.reply_btn = QPushButton(LOCALISATION["copy"][self.lang_code])
        self.reply_btn.setStyleSheet("background-color: rgba(0, 0, 0, 150); color: white;")
        self.reply_btn.clicked.connect(self.translate_and_copy)

        input_layout.addWidget(self.lang_input)
        input_layout.addWidget(self.reply_input)
        input_layout.addWidget(self.reply_btn)

        layout.addLayout(input_layout)

        self.setLayout(layout)

    def mousePressEvent(self, a0):
        if a0.button() == Qt.LeftButton:
            self.old_pos = a0.globalPos()

    def mouseMoveEvent(self, a0):
        if a0.buttons() == Qt.LeftButton and self.old_pos:
            delta = a0.globalPos() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = a0.globalPos()

    def process_queue(self):
        try:
            chat_content = log_queue.get_nowait()
            message_log = format_chat_log(chat_content)

            new_items = []
            missing_prefix = []

            if not message_log:
                pass
            elif not self.full_log:
                new_items = message_log
            else:
                match_index = -1
                match_start = -1
                match_size = 0
                max_anchor_size = min(5, len(self.full_log), len(message_log))

                for size in range(max_anchor_size, 0, -1):
                    anchor = self.full_log[-size:]
                    for i in range(len(message_log) - size, -1, -1):
                        if message_log[i: i + size] == anchor:
                            match_index = i + size
                            match_start = i
                            match_size = size
                            break
                    if match_index != -1:
                        break

                if match_index != -1:
                    new_items = message_log[match_index:]
                    if match_start > 0:
                        old_prefix_len = len(self.full_log) - match_size
                        if match_start > old_prefix_len:
                            missing_prefix = message_log[:match_start - old_prefix_len]
                else:
                    is_subset = False
                    for i in range(len(self.full_log) - len(message_log) + 1):
                        if self.full_log[i: i + len(message_log)] == message_log:
                            is_subset = True
                            break

                    if not is_subset:
                        logging.warning(
                            f"WIPING UI. Memory mismatch.\n"
                            f"Current full_log (last 3): {self.full_log[-3:]}\n"
                            f"New message_log: {message_log}"
                        )
                        self.chat_list.clear()
                        self.full_log = []
                        new_items = message_log

            for i, (author, msg) in enumerate(missing_prefix):
                self.full_log.insert(i, (author, msg))
                display_text = f"{author}: {msg}"
                item = QListWidgetItem(display_text)
                item.setData(STATE_ROLE, "idle")
                item.setData(Qt.UserRole, msg)
                self.chat_list.insertItem(i, item)

            for author, msg in new_items:
                self.full_log.append((author, msg))
                display_text = f"{author}: {msg}"
                item = QListWidgetItem(display_text)
                item.setData(STATE_ROLE, "idle")
                item.setData(Qt.UserRole, msg)
                self.chat_list.addItem(item)
                self.chat_list.scrollToBottom()

        except queue.Empty:
            pass

    def translate_message(self, item):
        if not self.client:
            return

        raw_msg = item.data(Qt.UserRole)
        if not raw_msg or len(raw_msg) <= 3:
            return

        if item.data(STATE_ROLE) in ("translating", "done"):
            return

        item.setData(STATE_ROLE, "translating")
        item.setText(f"{item.text()} ...")


        thread = TranslationThread(self.client, item, raw_msg, self.lang_english)
        thread.translation_done.connect(self.update_translated_item)
        self.active_threads.append(thread)  # Keep the thread alive

        thread.finished.connect(lambda: self.active_threads.remove(thread))

        thread.start()

    def update_translated_item(self, item, translation):
        item.setData(STATE_ROLE, "done")
        original_text = item.text()
        if original_text.endswith(" ..."):
            original_text = original_text[:-4]
        item.setText(f"{original_text} -> {translation}")
        self.lang_input.setText(re.findall(r'\[.*?\]', translation)[0])

    def translate_and_copy(self):
        target_lang = self.lang_input.text().strip()
        text_to_translate = self.reply_input.text().strip()

        if not self.client or not target_lang or not text_to_translate:
            return

        self.reply_btn.setText("...")

        # Store reference to prevent garbage collection during the request
        self.rev_thread = ReverseTranslationThread(self.client, text_to_translate, self.lang_english, target_lang)
        self.rev_thread.translation_done.connect(self.on_reply_translated)
        self.rev_thread.start()

    def on_reply_translated(self, translation):
        if translation:
            QApplication.clipboard().setText(translation)
            self.reply_btn.setText(LOCALISATION["copied"][self.lang_code])
            self.reply_input.clear()

            # Reset button text after 2 seconds
            QTimer.singleShot(2000, lambda: self.reply_btn.setText("Copy"))
        else:
            self.reply_btn.setText(LOCALISATION["failed"][self.lang_code])
            QTimer.singleShot(2000, lambda: self.reply_btn.setText("Copy"))


class WelcomeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.lang_selected = "English"
        self.lang_code = "en"
        self.setWindowTitle("Setup - ShootersPool Translator")
        self.setGeometry(100, 100, 500, 400)

        self.setStyleSheet("""
                    QWidget { background-color: #2b2b2b; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
                    QComboBox, QLineEdit { background-color: #3c3c3c; border: 1px solid #555; padding: 6px; border-radius: 4px; }
                    QPushButton { background-color: #007acc; color: white; font-weight: bold; padding: 8px; border-radius: 4px; }
                    QPushButton:hover { background-color: #0098ff; }
                """)

        self.settings = QSettings("ShootersPool", "Translator")

        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        self.lang_combo_box = QComboBox()
        self.lang_combo_box.addItems(["English","Español", "Français", "Deutsch", "Português",
                                      "普通话", "广东话", "Italiano", "Русский", "한국어", "日本語"])
        self.lang_combo_box.currentTextChanged.connect(self.text_changed)

        layout.addWidget(self.lang_combo_box)


        # 1. Instructions
        self.instructions = QLabel(LOCALISATION["instructions1"][self.lang_code])
        self.instructions.setWordWrap(True)
        layout.addWidget(self.instructions)

        # 2. Instructions2
        self.instructions2 = QLabel(LOCALISATION["instructions2"][self.lang_code])
        self.instructions2.setWordWrap(True)
        layout.addWidget(self.instructions2)

        # 3. API Key Link
        self.api_link = QLabel(LOCALISATION["instructions3"][self.lang_code])
        self.api_link.setOpenExternalLinks(True)
        layout.addWidget(self.api_link)

        # 4. Input Field
        self.api_input = QLineEdit()
        self.api_input.setPlaceholderText(LOCALISATION["instructions4"][self.lang_code])
        self.api_input.setEchoMode(QLineEdit.Password)
        saved_key = self.settings.value("api_key", type=str)
        if saved_key:
            self.api_input.setText(saved_key)
        layout.addWidget(self.api_input)

        # 5. Launch Button
        self.launch_btn = QPushButton(LOCALISATION["start"][self.lang_code])
        self.launch_btn.clicked.connect(self.launch_overlay)
        layout.addWidget(self.launch_btn)

        self.setLayout(layout)

        self.overlay = None

    def launch_overlay(self):
        user_key = self.api_input.text().strip()
        if user_key:
            self.settings.setValue("api_key", user_key)

        try:
            self.overlay = ChatOverlay(api_key=user_key, lang=self.lang_selected)
            self.overlay.show()
            make_game_fake_borderless("ShootersPool")
            self.hide()
        except Exception as error:
            logging.error(f"Fatal Overlay Error: {error}")

    def text_changed(self, s):
        self.lang_selected = s
        self.lang_code = LANGUAGE_MAP[self.lang_selected][0]
        self.update_ui_text()

    def update_ui_text(self):
        if not self.lang_selected:
            return

        self.instructions.setText(LOCALISATION["instructions1"][self.lang_code])
        self.instructions2.setText(LOCALISATION["instructions2"][self.lang_code])
        self.api_link.setText(LOCALISATION["instructions3"][self.lang_code])
        self.api_input.setPlaceholderText(LOCALISATION["instructions4"][self.lang_code])
        self.launch_btn.setText(LOCALISATION["start"][self.lang_code])


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app_window = WelcomeWindow()
    app_window.show()
    sys.exit(app.exec_())