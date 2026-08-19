import sys
import os
import re
import json
import copy
from uuid import uuid4
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Callable

from PyQt6.QtCore import Qt, QRectF, QRect, QSettings, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import (
    QAction, QFont, QFontInfo, QPen, QPainter, QImage, QColor,
    QPalette, QPixmap, QKeySequence, QWheelEvent, QCloseEvent,
    QLinearGradient, QBrush,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabBar, QStackedWidget, QToolButton, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsSimpleTextItem, QFileDialog, QMessageBox,
    QInputDialog, QStatusBar, QLineEdit, QSplashScreen, QLabel, QFrame,
    QScrollArea, QSlider, QMenu, QToolBar,
)

APP_NAME = "構造図エディター"
APP_VERSION = "1.0"
ORGANIZATION = "The Meisho Fellowship"
COPYRIGHT = "© 2025-2026 The Meisho Fellowship. All Rights Reserved."
DOCUMENT_EXTENSION = ".jundai"
DOCUMENT_FORMAT = "jundai-tree-document"
EXPORT_SCALE = 4.0


@dataclass
class Node:
    """GB/Xバー理論期の表記を保持する句構造木ノード。"""
    label: str
    uid: str = field(default_factory=lambda: uuid4().hex)
    trace: bool = False
    terminal: str = ""
    children: List["Node"] = field(default_factory=list)


def node_to_dict(node: Node) -> dict:
    return {
        "uid": node.uid,
        "label": node.label,
        "trace": node.trace,
        "terminal": node.terminal,
        "children": [node_to_dict(child) for child in node.children],
    }


def node_from_dict(data: dict) -> Node:
    return Node(
        label=str(data.get("label", "X")),
        uid=str(data.get("uid") or uuid4().hex),
        trace=bool(data.get("trace", False)),
        terminal=str(data.get("terminal", "")),
        children=[node_from_dict(child) for child in data.get("children", [])],
    )


def renew_uids(node: Node):
    node.uid = uuid4().hex
    for child in node.children:
        renew_uids(child)


def build_default_tree(head_left: bool = True) -> Node:
    root = Node("C''")
    c_bar = Node("C'")
    c = Node("C")
    i_double = Node("I''")
    n_double = Node("N''")
    i_bar = Node("I'")
    c_bar.children = [c, i_double] if head_left else [i_double, c]
    i_double.children = [n_double, i_bar] if head_left else [i_bar, n_double]
    root.children = [c_bar]
    return root


def assign_parent_map(root: Node) -> Dict[str, Node]:
    parent_map: Dict[str, Node] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node.children:
            parent_map[child.uid] = node
            stack.append(child)
    return parent_map


def layout_tree(root: Node, h_spacing: int = 145, v_spacing: int = 110) -> Dict[str, tuple]:
    positions: Dict[str, tuple] = {}
    next_x = 0

    def visit(node: Node, depth: int) -> float:
        nonlocal next_x
        if not node.children:
            x = next_x
            next_x += h_spacing
            positions[node.uid] = (x, depth * v_spacing)
            return x
        xs = [visit(child, depth + 1) for child in node.children]
        x = sum(xs) / len(xs)
        positions[node.uid] = (x, depth * v_spacing)
        return x

    visit(root, 0)
    return positions


def dominates(a: Node, b: Node, parent_map: Dict[str, Node]) -> bool:
    current: Optional[Node] = b
    while current is not None:
        if current.uid == a.uid:
            return True
        current = parent_map.get(current.uid)
    return False


def first_branching_node_above(node: Node, parent_map: Dict[str, Node]) -> Optional[Node]:
    current = parent_map.get(node.uid)
    while current is not None:
        if len(current.children) >= 2:
            return current
        current = parent_map.get(current.uid)
    return None


def c_commands(a: Node, b: Node, parent_map: Dict[str, Node]) -> bool:
    if a.uid == b.uid:
        return False
    if dominates(a, b, parent_map) or dominates(b, a, parent_map):
        return False
    branching = first_branching_node_above(a, parent_map)
    return branching is not None and dominates(branching, b, parent_map)


def settings() -> QSettings:
    return QSettings("MeishoFellowship", "KouzouzuEditor")


def sanitize_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]', "_", value.strip())
    return value or "ユーザー"


def request_username(parent) -> Optional[str]:
    saved = settings().value("username", "", type=str).strip()
    if saved:
        return saved
    while True:
        text, ok = QInputDialog.getText(
            parent,
            "初回設定",
            "構造図エディターへようこそ。\n保存ファイル名に使用するユーザー名を入力してください:",
            QLineEdit.EchoMode.Normal,
            "",
        )
        if not ok:
            return None
        username = text.strip()
        if username:
            settings().setValue("username", username)
            return username
        QMessageBox.information(parent, "ユーザー名", "1文字以上のユーザー名を入力してください。")


class TreeView(QGraphicsView):
    zoom_changed = pyqtSignal(int)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setBackgroundBrush(QColor("white"))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            self.zoom_changed.emit(round(self.transform().m11() * 100))
            event.accept()
        else:
            super().wheelEvent(event)

    def set_zoom_percent(self, percent: int):
        self.resetTransform()
        factor = max(0.1, percent / 100.0)
        self.scale(factor, factor)
        self.zoom_changed.emit(percent)


class NodeItem(QGraphicsSimpleTextItem):
    def __init__(self, text: str, font: QFont, uid: str, main_window):
        super().__init__(text)
        self.uid = uid
        self.main_window = main_window
        self.setFont(font)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def mouseDoubleClickEvent(self, event):
        self.main_window.edit_node_by_uid(self.uid)
        event.accept()

    def contextMenuEvent(self, event):
        self.setSelected(True)
        self.main_window.show_node_context_menu(event.screenPos())
        event.accept()


class RibbonButton(QToolButton):
    def __init__(self, action: QAction, large: bool = False):
        super().__init__()
        self.setDefaultAction(action)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if large:
            self.setProperty("ribbonLarge", True)
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            self.setIconSize(QSize(32, 32))
            self.setMinimumSize(78, 68)
        else:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.setMinimumHeight(24)


class RibbonGroup(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("RibbonGroup")
        self.row = QHBoxLayout()
        self.row.setContentsMargins(5, 4, 5, 1)
        self.row.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("RibbonGroupTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(self.row, 1)
        layout.addWidget(title_label)

    def add_large(self, action: QAction):
        self.row.addWidget(RibbonButton(action, True))

    def add_column(self, actions: List[QAction]):
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        for action in actions:
            column.addWidget(RibbonButton(action))
        column.addStretch(1)
        self.row.addWidget(holder)


class RibbonPage(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setObjectName("RibbonPage")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("RibbonPageContent")
        self.groups = QHBoxLayout(content)
        self.groups.setContentsMargins(4, 2, 4, 2)
        self.groups.setSpacing(1)
        self.groups.addStretch(1)
        self.setWidget(content)

    def add_group(self, group: RibbonGroup):
        self.groups.insertWidget(self.groups.count() - 1, group)


class RibbonBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("RibbonBar")
        self.tabs = QTabBar()
        self.tabs.setObjectName("RibbonTabBar")
        self.tabs.setDrawBase(False)
        self.pages = QStackedWidget()
        self.pages.setObjectName("RibbonPages")
        self.pages.setFixedHeight(103)
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tabs)
        layout.addWidget(self.pages)

    def add_page(self, title: str, page: RibbonPage):
        self.pages.addWidget(page)
        self.tabs.addTab(title)
        if self.pages.count() == 1:
            self.tabs.setCurrentIndex(0)


class MainWindow(QMainWindow):
    def __init__(self, username: str):
        super().__init__()
        self.username = username
        self.resize(1380, 900)
        self.setMinimumSize(960, 650)
        self.head_left = True
        self.figure_number = settings().value("save_number", 1, type=int)
        self.selected_uid: Optional[str] = None
        self.ccommand_a_uid: Optional[str] = None
        self.clipboard_subtree: Optional[Node] = None
        self.undo_stack: List[tuple] = []
        self.redo_stack: List[tuple] = []
        self.current_file: Optional[str] = None
        self.modified = False
        self.root = build_default_tree(self.head_left)
        self.parent_map: Dict[str, Node] = {}
        self.node_by_uid: Dict[str, Node] = {}

        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self.on_selection_changed)
        self.view = TreeView(self.scene)
        self.create_actions()
        self.create_quick_access_toolbar()

        central = QWidget()
        central.setObjectName("CentralPanel")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(5, 0, 5, 5)
        layout.setSpacing(5)
        layout.addWidget(self.create_ribbon())
        layout.addWidget(self.view, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar(self))
        self.user_label = QLabel(f"ユーザー: {self.username}")
        self.zoom_label = QLabel("100%")
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(25, 250)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(125)
        self.zoom_slider.valueChanged.connect(self.view.set_zoom_percent)
        self.view.zoom_changed.connect(self.update_zoom_status)
        self.statusBar().addPermanentWidget(self.user_label)
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.statusBar().addPermanentWidget(self.zoom_slider)

        self.refresh(fit_view=True)
        self.update_title()
        self.statusBar().showMessage("準備完了。Ctrl+ホイールで拡大縮小、ドラッグでキャンバス移動。")

    @property
    def selected_node(self) -> Optional[Node]:
        return self.node_by_uid.get(self.selected_uid or "")

    def make_action(self, text: str, slot: Callable, shortcut: Optional[str] = None,
                    tooltip: Optional[str] = None, checkable: bool = False) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if tooltip:
            action.setToolTip(tooltip)
            action.setStatusTip(tooltip)
        return action

    def create_actions(self):
        self.a_new = self.make_action("新規", self.new_tree, "Ctrl+N")
        self.a_open = self.make_action("開く", self.open_document, "Ctrl+O")
        self.a_save = self.make_action("保存", self.save_document, "Ctrl+S")
        self.a_save_as = self.make_action("名前を付けて保存", self.save_document_as, "Ctrl+Shift+S")
        self.a_export = self.make_action("高画質PNG保存", self.save_image)
        self.a_username = self.make_action("ユーザー名変更", self.change_username)
        self.a_undo = self.make_action("元に戻す", self.undo, "Ctrl+Z")
        self.a_redo = self.make_action("やり直す", self.redo, "Ctrl+Y")
        self.a_label = self.make_action("ラベル変更", self.edit_label_selected, "F2")
        self.a_terminal = self.make_action("末端文字", self.edit_terminal_selected, "Ctrl+Enter")
        self.a_delete = self.make_action("枝削除", self.delete_selected_node, "Delete")
        self.a_clear = self.make_action("子を全削除", self.clear_children)
        self.a_copy = self.make_action("部分木をコピー", self.copy_subtree, "Ctrl+C")
        self.a_cut = self.make_action("部分木を切り取り", self.cut_subtree, "Ctrl+X")
        self.a_paste = self.make_action("子として貼り付け", self.paste_subtree, "Ctrl+V")
        self.a_duplicate = self.make_action("部分木を複製", self.duplicate_subtree, "Ctrl+D")
        self.a_swap = self.make_action("子の左右を交換", self.swap_selected_children)
        self.a_fit = self.make_action("全体を表示", self.fit_tree, "Ctrl+0")
        self.a_actual = self.make_action("100%", lambda: self.zoom_slider.setValue(100), "Ctrl+1")
        self.a_c_a = self.make_action("起点 A に設定", self.set_ccommand_a)
        self.a_c_check = self.make_action("c-command 判定", self.check_ccommand)
        self.head_action = self.make_action("既定順：左", self.toggle_head, checkable=True)
        self.head_action.setChecked(True)

    def create_quick_access_toolbar(self):
        toolbar = self.addToolBar("クイックアクセス")
        toolbar.setObjectName("QuickAccessToolBar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.addActions([self.a_save, self.a_undo, self.a_redo])

    def create_ribbon(self) -> RibbonBar:
        ribbon = RibbonBar()
        home = RibbonPage()
        group = RibbonGroup("ファイル")
        group.add_large(self.a_new)
        group.add_column([self.a_open, self.a_save, self.a_export])
        home.add_group(group)
        group = RibbonGroup("履歴")
        group.add_column([self.a_undo, self.a_redo])
        home.add_group(group)
        group = RibbonGroup("クリップボード")
        group.add_large(self.a_paste)
        group.add_column([self.a_copy, self.a_cut, self.a_duplicate])
        home.add_group(group)
        group = RibbonGroup("編集")
        group.add_large(self.a_label)
        group.add_column([self.a_terminal, self.a_delete, self.a_clear])
        home.add_group(group)
        group = RibbonGroup("設定")
        group.add_column([self.a_swap, self.head_action, self.a_username])
        home.add_group(group)

        insert = RibbonPage()
        categories = [
            ("節・屈折", ["C''", "C'", "C", "I''", "I'", "I"]),
            ("名詞", ["N''", "N'", "N", "Det"]),
            ("動詞", ["V''", "V'", "V"]),
            ("前置詞", ["P''", "P'", "P"]),
            ("形容詞・副詞", ["A''", "A'", "A", "Adv''", "Adv'", "Adv", "Deg"]),
        ]
        for title, labels in categories:
            group = RibbonGroup(title)
            actions = [self.make_add_action(label) for label in labels]
            for i in range(0, len(actions), 3):
                group.add_column(actions[i:i + 3])
            insert.add_group(group)
        group = RibbonGroup("空範疇・自由項目")
        group.add_column([self.make_add_action("e"), self.make_add_action("PRO"), self.make_add_action("pro")])
        group.add_column([self.make_action("t_i", self.add_trace), self.make_action("自由項目", self.add_free_node)])
        insert.add_group(group)

        rules = RibbonPage()
        for title, specs in [
            ("基本規則", self.basic_rule_specs()),
            ("名詞句", self.np_rule_specs()),
            ("動詞句", self.vp_rule_specs()),
            ("前置詞句", self.pp_rule_specs()),
            ("形容詞・副詞句", self.ap_adv_rule_specs()),
        ]:
            group = RibbonGroup(title)
            actions = [self.make_rule_action(*spec) for spec in specs]
            for i in range(0, len(actions), 3):
                group.add_column(actions[i:i + 3])
            rules.add_group(group)

        theory = RibbonPage()
        group = RibbonGroup("c-command")
        group.add_large(self.a_c_a)
        group.add_large(self.a_c_check)
        theory.add_group(group)
        group = RibbonGroup("部分木")
        group.add_column([self.a_copy, self.a_duplicate, self.a_swap])
        theory.add_group(group)

        display = RibbonPage()
        group = RibbonGroup("ズーム")
        group.add_large(self.a_fit)
        group.add_large(self.a_actual)
        display.add_group(group)

        ribbon.add_page("ホーム", home)
        ribbon.add_page("挿入", insert)
        ribbon.add_page("句構造規則", rules)
        ribbon.add_page("理論ツール", theory)
        ribbon.add_page("表示", display)
        return ribbon

    def make_add_action(self, text: str, label: Optional[str] = None, trace: bool = False) -> QAction:
        label = label or text
        return self.make_action(text, lambda checked=False, l=label, t=trace: self.add_label_to_selected(l, t))

    def make_rule_action(self, text: str, required_label: str, child_labels) -> QAction:
        return self.make_action(text, lambda checked=False, r=required_label, c=child_labels, d=text: self.apply_simple_rule(r, c, d))

    def basic_rule_specs(self):
        return [
            ("C'' → C'", "C''", ["C'"]), ("C' → C I''", "C'", ["C", "I''"]),
            ("C' → C", "C'", ["C"]), ("I'' → N'' I'", "I''", ["N''", "I'"]),
            ("I'' → I'", "I''", ["I'"]), ("I' → I", "I'", ["I"]),
            ("I' → I V''", "I'", ["I", "V''"]), ("I' → I A''", "I'", ["I", "A''"]),
            ("I' → Adv' I'", "I'", ["Adv'", "I'"]),
        ]

    def np_rule_specs(self):
        return [
            ("N'' → Det N'", "N''", ["Det", "N'"]), ("N'' → N'", "N''", ["N'"]),
            ("N'' → N' P''", "N''", ["N'", "P''"]), ("N' → N", "N'", ["N"]),
            ("N' → N P''", "N'", ["N", "P''"]), ("N' → N C''", "N'", ["N", "C''"]),
            ("N' → N I''", "N'", ["N", "I''"]), ("N' → A' N'", "N'", ["A'", "N'"]),
            ("N' → N' P''", "N'", ["N'", "P''"]), ("N' → N' A''", "N'", ["N'", "A''"]),
        ]

    def vp_rule_specs(self):
        return [
            ("V'' → V'", "V''", ["V'"]), ("V'' → V' P''", "V''", ["V'", "P''"]),
            ("V' → V", "V'", ["V"]), ("V' → V N''", "V'", ["V", "N''"]),
            ("V' → V P''", "V'", ["V", "P''"]), ("V' → V C''", "V'", ["V", "C''"]),
            ("V' → V I''", "V'", ["V", "I''"]), ("V' → V A''", "V'", ["V", "A''"]),
            ("V' → V V''", "V'", ["V", "V''"]), ("V' → Adv' V'", "V'", ["Adv'", "V'"]),
            ("V' → V' Adv''", "V'", ["V'", "Adv''"]), ("V' → V' P''", "V'", ["V'", "P''"]),
        ]

    def pp_rule_specs(self):
        return [
            ("P'' → P'", "P''", ["P'"]), ("P'' → P' N''", "P''", ["P'", "N''"]),
            ("P' → P", "P'", ["P"]), ("P' → P N''", "P'", ["P", "N''"]),
            ("P' → P C''", "P'", ["P", "C''"]), ("P' → P I''", "P'", ["P", "I''"]),
            ("P' → P P''", "P'", ["P", "P''"]), ("P' → Adv' P'", "P'", ["Adv'", "P'"]),
            ("P' → P' P''", "P'", ["P'", "P''"]),
        ]

    def ap_adv_rule_specs(self):
        return [
            ("A'' → A'", "A''", ["A'"]), ("A' → A", "A'", ["A"]),
            ("A' → A P''", "A'", ["A", "P''"]), ("A' → A C''", "A'", ["A", "C''"]),
            ("A' → A I''", "A'", ["A", "I''"]), ("A' → Adv' A'", "A'", ["Adv'", "A'"]),
            ("A' → A' P''", "A'", ["A'", "P''"]), ("Adv'' → Adv'", "Adv''", ["Adv'"]),
            ("Adv' → Adv", "Adv'", ["Adv"]), ("Adv' → Adv P''", "Adv'", ["Adv", "P''"]),
            ("Adv' → Adv Adv''", "Adv'", ["Adv", "Adv''"]), ("Deg'' → Deg'", "Deg''", ["Deg'"]),
            ("Deg' → Deg", "Deg'", ["Deg"]), ("Deg' → Deg A''", "Deg'", ["Deg", "A''"]),
        ]

    def mincho_font(self, size=12):
        for family in ("Yu Mincho", "MS PMincho", "MS Mincho", "Noto Serif CJK JP", "Times New Roman"):
            font = QFont(family, size)
            if QFontInfo(font).exactMatch():
                return font
        return QFont("serif", size)

    def refresh(self, fit_view=False):
        selected_uid = self.selected_uid
        self.parent_map = assign_parent_map(self.root)
        self.node_by_uid = {}
        stack = [self.root]
        while stack:
            node = stack.pop()
            self.node_by_uid[node.uid] = node
            stack.extend(node.children)
        if selected_uid not in self.node_by_uid:
            selected_uid = None
            self.selected_uid = None
        positions = layout_tree(self.root)
        self.scene.blockSignals(True)
        self.scene.clear()
        font = self.mincho_font(12)
        terminal_font = self.mincho_font(11)

        def draw_edges(node):
            px, py = positions[node.uid]
            for child in node.children:
                cx, cy = positions[child.uid]
                pen = QPen(QColor("#355b7a"), 1.55)
                if child.trace:
                    pen.setStyle(Qt.PenStyle.DashLine)
                self.scene.addLine(px, py + 20, cx, cy - 20, pen)
                draw_edges(child)

        draw_edges(self.root)
        for uid_value, (x, y) in positions.items():
            node_value = self.node_by_uid[uid_value]
            item = NodeItem(node_value.label, font, uid_value, self)
            item.setBrush(QColor("#153d96") if node_value.trace else QColor("#173b5d"))
            item.setPos(x - item.boundingRect().width() / 2, y - item.boundingRect().height() / 2)
            item.setData(0, uid_value)
            self.scene.addItem(item)
            if not node_value.children and node_value.terminal:
                terminal_item = self.scene.addSimpleText(node_value.terminal, terminal_font)
                terminal_item.setBrush(QColor("#16643a"))
                terminal_item.setPos(x - terminal_item.boundingRect().width() / 2, y + 32)
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-45, -45, 45, 45))
        if selected_uid:
            for item in self.scene.items():
                if item.data(0) == selected_uid:
                    item.setSelected(True)
                    break
        self.scene.blockSignals(False)
        if fit_view:
            QTimer.singleShot(0, self.fit_tree)

    def fit_tree(self):
        if self.scene.sceneRect().isValid():
            self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.update_zoom_status(round(self.view.transform().m11() * 100))

    def update_zoom_status(self, value):
        self.zoom_label.setText(f"{value}%")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(max(25, min(250, value)))
        self.zoom_slider.blockSignals(False)

    def on_selection_changed(self):
        items = self.scene.selectedItems()
        self.selected_uid = items[0].data(0) if items else None
        node = self.selected_node
        if node:
            suffix = f" / 末端: {node.terminal or '未入力'}" if not node.children else ""
            self.statusBar().showMessage(f"選択: {node.label}{suffix}")
        else:
            self.statusBar().showMessage("未選択")

    def show_node_context_menu(self, pos):
        menu = QMenu(self)
        menu.addActions([self.a_label, self.a_terminal])
        menu.addSeparator()
        menu.addActions([self.a_copy, self.a_cut, self.a_paste, self.a_duplicate])
        menu.addSeparator()
        menu.addActions([self.a_swap, self.a_delete, self.a_clear])
        menu.exec(pos)

    def snapshot(self):
        return copy.deepcopy(self.root), self.head_left

    def push_undo(self):
        self.undo_stack.append(self.snapshot())
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()
        self.modified = True
        self.update_title()

    def undo(self):
        if not self.undo_stack:
            self.statusBar().showMessage("これ以上元に戻せません")
            return
        self.redo_stack.append(self.snapshot())
        self.root, self.head_left = self.undo_stack.pop()
        self.after_restore("元に戻しました")

    def redo(self):
        if not self.redo_stack:
            self.statusBar().showMessage("これ以上やり直せません")
            return
        self.undo_stack.append(self.snapshot())
        self.root, self.head_left = self.redo_stack.pop()
        self.after_restore("やり直しました")

    def after_restore(self, message):
        self.selected_uid = None
        self.ccommand_a_uid = None
        self.head_action.blockSignals(True)
        self.head_action.setChecked(self.head_left)
        self.head_action.setText("既定順：左" if self.head_left else "既定順：右")
        self.head_action.blockSignals(False)
        self.modified = True
        self.refresh()
        self.update_title()
        self.statusBar().showMessage(message)

    def toggle_head(self, checked):
        self.head_left = checked
        self.head_action.setText("既定順：左" if checked else "既定順：右")
        self.modified = True
        self.update_title()

    def swap_selected_children(self):
        node = self.selected_node
        if node is None or len(node.children) < 2:
            QMessageBox.information(self, "左右交換", "子を2つ以上持つノードを選択してください。")
            return
        self.push_undo()
        node.children.reverse()
        self.refresh()

    def apply_simple_rule(self, required_label, child_labels, description):
        node = self.selected_node
        if node is None:
            QMessageBox.information(self, "ノード未選択", f"先に {required_label} を選択してください。")
            return
        if node.label != required_label:
            QMessageBox.warning(self, "規則が適用できません", f"{description} は {required_label} に適用してください。\n選択中: {node.label}")
            return
        if node.children and QMessageBox.question(self, "確認", f"{node.label} の既存の子を置き換えますか？") != QMessageBox.StandardButton.Yes:
            return
        self.push_undo()
        children = [Node(str(label)) for label in child_labels]
        if not self.head_left:
            children.reverse()
        node.children = children
        self.refresh()

    def add_label_to_selected(self, label, trace=False):
        parent = self.selected_node
        if parent is None:
            QMessageBox.information(self, "ノード未選択", "追加先の親ノードを選択してください。")
            return
        self.push_undo()
        parent.children.append(Node(label=label, trace=trace))
        self.refresh()

    def add_trace(self):
        text, ok = QInputDialog.getText(self, "移動痕跡", "インデックス:", QLineEdit.EchoMode.Normal, "i")
        if ok:
            self.add_label_to_selected(f"t_{text.strip() or 'i'}", True)

    def add_free_node(self):
        text, ok = QInputDialog.getText(self, "自由項目", "ラベル:", QLineEdit.EchoMode.Normal, "V'")
        if ok:
            self.add_label_to_selected(text.strip() or "X")

    def edit_node_by_uid(self, uid_value):
        node = self.node_by_uid.get(uid_value)
        if node:
            self.edit_terminal_node(node) if not node.children else self.edit_label_node(node)

    def edit_terminal_node(self, node):
        if node.children:
            QMessageBox.information(self, "末端文字", "末端文字は葉ノードにだけ設定できます。")
            return
        text, ok = QInputDialog.getText(self, "末端文字", "末端文字:", QLineEdit.EchoMode.Normal, node.terminal)
        if ok and text.strip() != node.terminal:
            self.push_undo()
            node.terminal = text.strip()
            self.refresh()

    def edit_label_node(self, node):
        text, ok = QInputDialog.getText(self, "ラベル変更", "ラベル:", QLineEdit.EchoMode.Normal, node.label)
        if ok and text.strip() and text.strip() != node.label:
            self.push_undo()
            node.label = text.strip()
            self.refresh()

    def edit_terminal_selected(self):
        if self.selected_node:
            self.edit_terminal_node(self.selected_node)
        else:
            QMessageBox.information(self, "末端文字", "ノードを選択してください。")

    def edit_label_selected(self):
        if self.selected_node:
            self.edit_label_node(self.selected_node)
        else:
            QMessageBox.information(self, "ラベル変更", "ノードを選択してください。")

    def copy_subtree(self):
        if self.selected_node is None:
            QMessageBox.information(self, "コピー", "部分木を選択してください。")
            return
        self.clipboard_subtree = copy.deepcopy(self.selected_node)

    def cut_subtree(self):
        if self.selected_node is None or self.selected_node.uid == self.root.uid:
            QMessageBox.information(self, "切り取り", "根以外の部分木を選択してください。")
            return
        self.copy_subtree()
        self.delete_selected_node()

    def paste_subtree(self):
        parent = self.selected_node
        if parent is None or self.clipboard_subtree is None:
            QMessageBox.information(self, "貼り付け", "貼り付け先とコピー済み部分木が必要です。")
            return
        self.push_undo()
        clone = copy.deepcopy(self.clipboard_subtree)
        renew_uids(clone)
        parent.children.append(clone)
        self.refresh()

    def duplicate_subtree(self):
        node = self.selected_node
        if node is None or node.uid == self.root.uid:
            QMessageBox.information(self, "複製", "根以外の部分木を選択してください。")
            return
        parent = self.parent_map.get(node.uid)
        self.push_undo()
        clone = copy.deepcopy(node)
        renew_uids(clone)
        parent.children.insert(parent.children.index(node) + 1, clone)
        self.refresh()

    def delete_selected_node(self):
        node = self.selected_node
        if node is None or node.uid == self.root.uid:
            QMessageBox.information(self, "枝削除", "根以外のノードを選択してください。")
            return
        parent = self.parent_map.get(node.uid)
        self.push_undo()
        parent.children.remove(node)
        self.selected_uid = None
        if self.ccommand_a_uid == node.uid:
            self.ccommand_a_uid = None
        self.refresh()

    def clear_children(self):
        node = self.selected_node
        if node is None or not node.children:
            QMessageBox.information(self, "子削除", "子を持つノードを選択してください。")
            return
        if QMessageBox.question(self, "確認", f"{node.label} の子をすべて削除しますか？") == QMessageBox.StandardButton.Yes:
            self.push_undo()
            node.children = []
            self.refresh()

    def set_ccommand_a(self):
        if self.selected_node is None:
            QMessageBox.information(self, "c-command", "起点 A を選択してください。")
            return
        self.ccommand_a_uid = self.selected_node.uid

    def check_ccommand(self):
        a = self.node_by_uid.get(self.ccommand_a_uid or "")
        b = self.selected_node
        if a is None or b is None:
            QMessageBox.information(self, "c-command", "起点 A を設定し、目標 B を選択してください。")
            return
        QMessageBox.information(self, "c-command", f"{a.label} → {b.label}: {c_commands(a, b, self.parent_map)}\n{b.label} → {a.label}: {c_commands(b, a, self.parent_map)}")

    def change_username(self):
        text, ok = QInputDialog.getText(self, "ユーザー名変更", "新しいユーザー名:", QLineEdit.EchoMode.Normal, self.username)
        if ok and text.strip():
            self.username = text.strip()
            settings().setValue("username", self.username)
            self.user_label.setText(f"ユーザー: {self.username}")
            self.update_title()

    def new_tree(self):
        if not self.maybe_save():
            return
        self.root = build_default_tree(self.head_left)
        self.current_file = None
        self.modified = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.selected_uid = None
        self.refresh(fit_view=True)
        self.update_title()

    def document_data(self):
        return {
            "format": DOCUMENT_FORMAT,
            "version": 1,
            "application": APP_NAME,
            "username": self.username,
            "head_left": self.head_left,
            "save_number": self.figure_number,
            "tree": node_to_dict(self.root),
        }

    def base_filename(self):
        now = datetime.now()
        safe_user = sanitize_filename(self.username)
        return f"【構造図-{self.figure_number:03d}】{safe_user}，{now:%Y-%m-%d_%H-%M-%S}"

    def save_document(self):
        if self.current_file:
            return self._save_document(self.current_file)
        return self.save_document_as()

    def save_document_as(self):
        default_path = os.path.join(os.path.expanduser("~"), self.base_filename() + DOCUMENT_EXTENSION)
        filename, _ = QFileDialog.getSaveFileName(
            self, "名前を付けて保存", self.current_file or default_path,
            f"構造図エディターファイル (*{DOCUMENT_EXTENSION})"
        )
        if not filename:
            return False
        if not filename.lower().endswith(DOCUMENT_EXTENSION):
            filename += DOCUMENT_EXTENSION
        return self._save_document(filename)

    def _save_document(self, filename):
        try:
            with open(filename, "w", encoding="utf-8") as file:
                json.dump(self.document_data(), file, ensure_ascii=False, indent=2)
            self.current_file = filename
            self.modified = False
            self.update_title()
            self.statusBar().showMessage(f"保存しました: {filename}")
            return True
        except Exception as exc:
            QMessageBox.critical(self, "保存エラー", str(exc))
            return False

    def open_document(self):
        if not self.maybe_save():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "構造図を開く", os.path.expanduser("~"),
            f"構造図エディターファイル (*{DOCUMENT_EXTENSION});;旧形式 (*.gktm *.json)"
        )
        if not filename:
            return
        try:
            with open(filename, "r", encoding="utf-8") as file:
                data = json.load(file)
            if "tree" not in data:
                raise ValueError("対応していないファイル形式です。")
            self.root = node_from_dict(data["tree"])
            self.head_left = bool(data.get("head_left", True))
            self.figure_number = int(data.get("save_number", data.get("figure_number", self.figure_number)))
            self.current_file = filename
            self.modified = False
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.selected_uid = None
            self.head_action.blockSignals(True)
            self.head_action.setChecked(self.head_left)
            self.head_action.setText("既定順：左" if self.head_left else "既定順：右")
            self.head_action.blockSignals(False)
            self.refresh(fit_view=True)
            self.update_title()
        except Exception as exc:
            QMessageBox.critical(self, "読込エラー", str(exc))

    def maybe_save(self):
        if not self.modified:
            return True
        answer = QMessageBox.question(
            self, "未保存の変更", "変更を保存しますか？",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return bool(self.save_document())
        return answer == QMessageBox.StandardButton.Discard

    def update_title(self):
        name = os.path.basename(self.current_file) if self.current_file else "無題"
        mark = "*" if self.modified else ""
        self.setWindowTitle(f"{mark}{name} - {APP_NAME}")

    def save_image(self):
        rect = self.scene.itemsBoundingRect().adjusted(-35, -35, 35, 35)
        if rect.width() < 20 or rect.height() < 20:
            QMessageBox.warning(self, "保存", "描画領域が小さすぎます。")
            return
        scale = EXPORT_SCALE
        width = max(1, round(rect.width() * scale))
        height = max(1, round(rect.height() * scale))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(1.0)
        image.fill(Qt.GlobalColor.white)
        image.setDotsPerMeterX(round(300 / 0.0254))
        image.setDotsPerMeterY(round(300 / 0.0254))
        painter = QPainter(image)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self.scene.render(painter, QRectF(0, 0, width, height), rect, Qt.AspectRatioMode.KeepAspectRatio)
        painter.end()
        default_path = os.path.join(os.path.expanduser("~"), self.base_filename() + ".png")
        filename, _ = QFileDialog.getSaveFileName(self, "高画質PNGとして保存", default_path, "PNG画像 (*.png)")
        if not filename:
            return
        if not filename.lower().endswith(".png"):
            filename += ".png"
        if image.save(filename, "PNG", 100):
            self.figure_number += 1
            settings().setValue("save_number", self.figure_number)
            self.statusBar().showMessage(f"高画質PNGを保存しました: {filename}")
        else:
            QMessageBox.critical(self, "エラー", "画像の保存に失敗しました。")

    def closeEvent(self, event: QCloseEvent):
        event.accept() if self.maybe_save() else event.ignore()


def apply_windows7_theme(app):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#d9e9f6"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#edf5fb"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#1b3348"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#1b3348"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#e7f1f8"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#18354d"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3399ff"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setStyleSheet(r"""
        QMainWindow, QDialog, QMessageBox, QInputDialog, QFileDialog {
            background:#d9e9f6; color:#1b3348;
        }
        #CentralPanel { background:#d9e9f6; }
        #RibbonBar { background:#c7deef; border-bottom:1px solid #6c9ac0; }
        #RibbonTabBar { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #eaf4fb,stop:1 #bfd8eb); border-bottom:1px solid #759fbe; }
        #RibbonTabBar::tab { min-width:74px; padding:6px 14px; margin-top:2px; color:#173a55; border:1px solid transparent; border-bottom:none; }
        #RibbonTabBar::tab:hover { background:#f7fbfe; border-color:#8fb3cf; border-top-left-radius:4px; border-top-right-radius:4px; }
        #RibbonTabBar::tab:selected { background:#ffffff; font-weight:bold; border:1px solid #769eba; border-bottom:1px solid #ffffff; border-top-left-radius:4px; border-top-right-radius:4px; }
        #RibbonPages, #RibbonPageContent { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffffff,stop:0.55 #f7fbfe,stop:1 #dceaf5); }
        #RibbonPages { border-left:1px solid #769eba; border-right:1px solid #769eba; border-bottom:1px solid #769eba; }
        #RibbonGroup { background:transparent; border-right:1px solid #b4cadb; }
        #RibbonGroupTitle { color:#526c81; font-size:9pt; padding:1px 8px 2px 8px; }
        QToolButton { color:#173a55; background:transparent; border:1px solid transparent; border-radius:3px; padding:3px 6px; }
        QToolButton:hover { border:1px solid #e5a02d; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #fffef5,stop:0.48 #ffeab0,stop:1 #ffc85c); }
        QToolButton:pressed, QToolButton:checked { border:1px solid #bd7318; background:#ffd273; }
        #QuickAccessToolBar { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #f5fbff,stop:1 #c8dfef); border:1px solid #82aac7; spacing:2px; }
        QGraphicsView { background:#ffffff; border:1px solid #739cba; border-radius:2px; }
        QGraphicsView:focus { border:1px solid #3c86c5; }
        QStatusBar { color:#153951; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #f2f9fd,stop:1 #bdd8eb); border-top:1px solid #739cba; }
        QLineEdit { background:#ffffff; color:#19364c; border:1px solid #7da5c2; border-radius:2px; padding:4px; selection-background-color:#3399ff; }
        QPushButton { min-width:70px; border:1px solid #789fbc; border-radius:3px; padding:5px 12px; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ffffff,stop:1 #d9e9f5); color:#173a55; }
        QPushButton:hover { border-color:#df9426; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #fffef6,stop:1 #ffd67d); }
        QPushButton:pressed { background:#f4bc54; }
        QMenu { background:#ffffff; border:1px solid #809db4; padding:3px; }
        QMenu::item { padding:5px 26px 5px 24px; border-radius:2px; }
        QMenu::item:selected { background:#d8edfc; border:1px solid #7eb4dc; }
        QToolTip { background:#ffffe1; color:#1d2f3c; border:1px solid #767676; padding:3px; }
        QScrollArea { background:transparent; border:none; }
        QScrollBar:horizontal { height:14px; background:#e7f1f8; }
        QScrollBar::handle:horizontal { min-width:28px; border:1px solid #8eafc6; border-radius:3px; background:#c4dced; }
        QScrollBar:vertical { width:14px; background:#e7f1f8; }
        QScrollBar::handle:vertical { min-height:28px; border:1px solid #8eafc6; border-radius:3px; background:#c4dced; }
    """)


def create_splash():
    width, height = 760, 430
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    outer = QRectF(1, 1, width - 2, height - 2)
    gradient = QLinearGradient(0, 0, 0, height)
    gradient.setColorAt(0.0, QColor("#fafdff"))
    gradient.setColorAt(0.42, QColor("#d8ebf8"))
    gradient.setColorAt(1.0, QColor("#7fb2d5"))
    painter.setBrush(QBrush(gradient))
    painter.setPen(QPen(QColor("#4e86ac"), 2))
    painter.drawRoundedRect(outer, 12, 12)
    glow = QLinearGradient(0, 45, width, 330)
    glow.setColorAt(0.0, QColor(255, 255, 255, 230))
    glow.setColorAt(0.55, QColor(178, 220, 247, 110))
    glow.setColorAt(1.0, QColor(44, 124, 181, 30))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(glow))
    painter.drawEllipse(QRectF(-90, 22, 690, 335))
    painter.setPen(QPen(QColor("#ffffff"), 1))
    painter.drawLine(28, 342, width - 28, 342)
    title_font = QFont("Segoe UI", 34)
    title_font.setWeight(QFont.Weight.Light)
    painter.setFont(title_font)
    painter.setPen(QColor("#123d5c"))
    painter.drawText(QRect(48, 128, width - 96, 82), Qt.AlignmentFlag.AlignCenter, APP_NAME)
    sub_font = QFont("Segoe UI", 11)
    painter.setFont(sub_font)
    painter.setPen(QColor("#315d79"))
    painter.drawText(QRect(48, 213, width - 96, 34), Qt.AlignmentFlag.AlignCenter, "Syntax Tree Editing Environment")
    copyright_font = QFont("Segoe UI", 9)
    painter.setFont(copyright_font)
    painter.setPen(QColor("#244b64"))
    painter.drawText(QRect(35, 360, width - 70, 28), Qt.AlignmentFlag.AlignCenter, COPYRIGHT)
    painter.drawText(QRect(35, 389, width - 70, 20), Qt.AlignmentFlag.AlignCenter, f"Version {APP_VERSION}")
    painter.end()
    splash = QSplashScreen(pixmap)
    splash.setWindowFlags(splash.windowFlags() | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
    return splash


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION)
    apply_windows7_theme(app)
    app.setFont(QFont("Segoe UI", 10))
    splash = create_splash()
    splash.show()
    splash.showMessage("  設定を読み込んでいます...", Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, QColor("#244b64"))
    app.processEvents()
    username = request_username(splash)
    if username is None:
        splash.close()
        return 0
    splash.showMessage(f"  {username} さんの環境を準備しています...", Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, QColor("#244b64"))
    app.processEvents()
    window = MainWindow(username)
    window.show()
    QTimer.singleShot(1400, splash.close)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
