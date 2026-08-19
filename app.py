"""
言語学かんたん構造図メーカー - ウェブアプリ版
Flask を使用したサーバーサイドAPI
"""
import os
import json
import copy
from uuid import uuid4
from datetime import date
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from flask import Flask, request, jsonify, send_from_directory, render_template_string
from flask_cors import CORS

# ============================================================
# コアデータ構造（元コードから移植）
# ============================================================

@dataclass
class Node:
    """GB/X バー理論期の表記を保持する句構造木ノード。"""
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


# ============================================================
# Flask アプリケーション
# ============================================================

app = Flask(__name__)
CORS(app)

# セッション管理（簡易版：メモリ内）
sessions: Dict[str, dict] = {}


def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        sessions[session_id] = {
            "root": build_default_tree(True),
            "head_left": True,
            "figure_number": 1,
            "undo_stack": [],
            "redo_stack": [],
            "selected_uid": None,
            "ccommand_a_uid": None,
            "clipboard_subtree": None,
        }
    return sessions[session_id]


def snapshot(session: dict) -> tuple:
    return copy.deepcopy(session["root"]), session["head_left"]


def push_undo(session: dict):
    session["undo_stack"].append(snapshot(session))
    session["undo_stack"] = session["undo_stack"][-100:]
    session["redo_stack"].clear()


def assign_parent_map_recursive(root: Node) -> Dict[str, Node]:
    return assign_parent_map(root)


def build_all_nodes_map(root: Node) -> Dict[str, Node]:
    node_by_uid: Dict[str, Node] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        node_by_uid[node.uid] = node
        stack.extend(node.children)
    return node_by_uid


# ============================================================
# HTML テンプレート
# ============================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>言語学かんたん構造図メーカー - ウェブ版</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: 'Yu Mincho', 'MS PMincho', 'MS Mincho', 'Noto Serif CJK JP', serif;
            background: #f5f5f5;
            overflow: hidden;
        }
        #ribbon {
            background: linear-gradient(to bottom, #fefefe, #e8e8e8);
            border-bottom: 2px solid #1f3f5c;
            padding: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items: center;
        }
        .ribbon-group {
            border: 1px solid #ccc;
            border-radius: 4px;
            padding: 4px 6px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .ribbon-group-title {
            font-size: 10px;
            color: #666;
            margin-bottom: 2px;
        }
        .ribbon-buttons {
            display: flex;
            gap: 2px;
            flex-wrap: wrap;
            justify-content: center;
        }
        button {
            padding: 4px 8px;
            font-size: 12px;
            border: 1px solid #999;
            border-radius: 3px;
            background: white;
            cursor: pointer;
            transition: all 0.15s;
        }
        button:hover {
            background: #e8f4fc;
            border-color: #1f3f5c;
        }
        button:active {
            background: #1f3f5c;
            color: white;
        }
        button.large {
            padding: 8px 12px;
            font-size: 13px;
        }
        #canvas-container {
            position: relative;
            width: 100vw;
            height: calc(100vh - 140px);
            overflow: auto;
            background: white;
            margin-top: 4px;
        }
        #tree-svg {
            min-width: 800px;
            min-height: 600px;
        }
        .node-label {
            fill: #12324f;
            font-size: 14px;
            font-family: serif;
            cursor: pointer;
            user-select: none;
        }
        .node-label.trace {
            fill: darkblue;
        }
        .node-label.selected {
            stroke: #ff6600;
            stroke-width: 2px;
        }
        .node-label.ccommand-a {
            stroke: #00aa00;
            stroke-width: 2px;
        }
        .terminal-text {
            fill: #145a32;
            font-size: 12px;
            font-family: serif;
        }
        .edge {
            stroke: #1f3f5c;
            stroke-width: 1.6;
            fill: none;
        }
        .edge.dashed {
            stroke-dasharray: 5, 5;
        }
        #status-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: #e8e8e8;
            border-top: 1px solid #ccc;
            padding: 4px 8px;
            font-size: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        #zoom-controls {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        #zoom-slider {
            width: 120px;
        }
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.4);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }
        .modal.active {
            display: flex;
        }
        .modal-content {
            background: white;
            padding: 20px;
            border-radius: 8px;
            min-width: 300px;
            max-width: 500px;
        }
        .modal-content h3 {
            margin-bottom: 12px;
            color: #1f3f5c;
        }
        .modal-content input {
            width: 100%;
            padding: 8px;
            margin-bottom: 12px;
            border: 1px solid #ccc;
            border-radius: 4px;
            font-size: 14px;
        }
        .modal-buttons {
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        }
        .modal-buttons button {
            padding: 6px 16px;
        }
        .modal-buttons button.primary {
            background: #1f3f5c;
            color: white;
            border-color: #1f3f5c;
        }
        #context-menu {
            display: none;
            position: fixed;
            background: white;
            border: 1px solid #ccc;
            border-radius: 4px;
            box-shadow: 2px 2px 8px rgba(0,0,0,0.2);
            z-index: 1001;
            min-width: 150px;
        }
        #context-menu button {
            width: 100%;
            text-align: left;
            padding: 6px 12px;
            border: none;
            border-radius: 0;
            background: transparent;
        }
        #context-menu button:hover {
            background: #e8f4fc;
        }
        #context-menu hr {
            border: none;
            border-top: 1px solid #eee;
            margin: 4px 0;
        }
    </style>
</head>
<body>
    <div id="ribbon">
        <div class="ribbon-group">
            <span class="ribbon-group-title">ファイル</span>
            <div class="ribbon-buttons">
                <button onclick="newTree()">新規</button>
                <button onclick="saveDocument()">保存 (JSON)</button>
                <button onclick="loadDocument()">開く</button>
                <button onclick="exportImage()">画像出力</button>
            </div>
        </div>
        <div class="ribbon-group">
            <span class="ribbon-group-title">履歴</span>
            <div class="ribbon-buttons">
                <button onclick="undo()">元に戻す</button>
                <button onclick="redo()">やり直す</button>
            </div>
        </div>
        <div class="ribbon-group">
            <span class="ribbon-group-title">クリップボード</span>
            <div class="ribbon-buttons">
                <button onclick="copySubtree()">コピー</button>
                <button onclick="cutSubtree()">切り取り</button>
                <button onclick="pasteSubtree()">貼り付け</button>
                <button onclick="duplicateSubtree()">複製</button>
            </div>
        </div>
        <div class="ribbon-group">
            <span class="ribbon-group-title">編集</span>
            <div class="ribbon-buttons">
                <button onclick="editLabel()">ラベル変更</button>
                <button onclick="editTerminal()">末端文字</button>
                <button onclick="deleteNode()">削除</button>
                <button onclick="clearChildren()">子全削除</button>
            </div>
        </div>
        <div class="ribbon-group">
            <span class="ribbon-group-title">配置</span>
            <div class="ribbon-buttons">
                <button onclick="swapChildren()">左右交換</button>
                <button onclick="toggleHeadLeft()" id="head-btn">左</button>
            </div>
        </div>
        <div class="ribbon-group">
            <span class="ribbon-group-title">c-command</span>
            <div class="ribbon-buttons">
                <button onclick="setCC commandA()">起点 A に設定</button>
                <button onclick="checkCCommand()">判定</button>
            </div>
        </div>
    </div>

    <div id="canvas-container">
        <svg id="tree-svg"></svg>
    </div>

    <div id="status-bar">
        <span id="status-message">準備完了</span>
        <div id="zoom-controls">
            <span id="zoom-label">100%</span>
            <input type="range" id="zoom-slider" min="25" max="250" value="100" oninput="setZoom(this.value)">
        </div>
    </div>

    <!-- モーダルダイアログ -->
    <div id="modal" class="modal">
        <div class="modal-content">
            <h3 id="modal-title">タイトル</h3>
            <input type="text" id="modal-input" placeholder="入力してください">
            <div class="modal-buttons">
                <button onclick="closeModal()">キャンセル</button>
                <button class="primary" onclick="confirmModal()">OK</button>
            </div>
        </div>
    </div>

    <!-- コンテキストメニュー -->
    <div id="context-menu"></div>

    <input type="file" id="file-input" accept=".gktm,.json" style="display:none" onchange="handleFileSelect(event)">

    <script>
        // グローバル状態
        let sessionId = null;
        let treeData = null;
        let positions = {};
        let selectedUid = null;
        let ccommandAUid = null;
        let zoomLevel = 100;
        let modalCallback = null;

        // セッション開始
        async function initSession() {
            const res = await fetch('/api/session', { method: 'POST' });
            const data = await res.json();
            sessionId = data.session_id;
            await loadTree();
        }

        // 木データ読み込み
        async function loadTree() {
            const res = await fetch(`/api/tree?session_id=${sessionId}`);
            const data = await res.json();
            treeData = data.tree;
            positions = data.positions;
            selectedUid = data.selected_uid;
            ccommandAUid = data.ccommand_a_uid;
            renderTree();
            updateStatus('読み込み完了');
        }

        // 木レンダリング
        function renderTree() {
            const svg = document.getElementById('tree-svg');
            svg.innerHTML = '';

            if (!treeData) return;

            // エッジ描画
            drawEdges(treeData, svg);

            // ノード描画
            drawNodes(treeData, svg);

            // ショートカットキー設定
            setupShortcuts();
        }

        function drawEdges(node, svg) {
            if (!positions[node.uid]) return;
            const [px, py] = positions[node.uid];

            node.children.forEach(child => {
                if (!positions[child.uid]) return;
                const [cx, cy] = positions[child.uid];
                
                const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                line.setAttribute('x1', px);
                line.setAttribute('y1', py + 20);
                line.setAttribute('x2', cx);
                line.setAttribute('y2', cy - 20);
                line.setAttribute('class', child.trace ? 'edge dashed' : 'edge');
                svg.appendChild(line);

                drawEdges(child, svg);
            });
        }

        function drawNodes(node, svg) {
            if (!positions[node.uid]) return;
            const [x, y] = positions[node.uid];

            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', x);
            text.setAttribute('y', y);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('dominant-baseline', 'middle');
            text.setAttribute('class', 'node-label' + (node.trace ? ' trace' : '') + 
                (selectedUid === node.uid ? ' selected' : '') +
                (ccommandAUid === node.uid ? ' ccommand-a' : ''));
            text.textContent = node.label;
            text.dataset.uid = node.uid;
            
            text.addEventListener('click', (e) => {
                e.stopPropagation();
                selectNode(node.uid);
            });
            
            text.addEventListener('dblclick', (e) => {
                e.stopPropagation();
                if (node.children.length === 0) {
                    editTerminal();
                } else {
                    editLabel();
                }
            });

            text.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                e.stopPropagation();
                selectNode(node.uid);
                showContextMenu(e.clientX, e.clientY, node);
            });

            svg.appendChild(text);

            // 末端文字
            if (node.children.length === 0 && node.terminal) {
                const termText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                termText.setAttribute('x', x);
                termText.setAttribute('y', y + 32);
                termText.setAttribute('text-anchor', 'middle');
                termText.setAttribute('class', 'terminal-text');
                termText.textContent = node.terminal;
                svg.appendChild(termText);
            }

            node.children.forEach(child => drawNodes(child, svg));
        }

        function selectNode(uid) {
            selectedUid = uid;
            renderTree();
            const node = findNode(treeData, uid);
            if (node) {
                const suffix = node.children.length === 0 && node.terminal ? ` / 末端：${node.terminal}` : '';
                updateStatus(`選択：${node.label}${suffix}`);
            }
        }

        function findNode(node, uid) {
            if (node.uid === uid) return node;
            for (const child of node.children) {
                const found = findNode(child, uid);
                if (found) return found;
            }
            return null;
        }

        // API 呼び出し
        async function apiCall(endpoint, method = 'GET', data = null) {
            const options = {
                method,
                headers: { 'Content-Type': 'application/json' }
            };
            if (data) options.body = JSON.stringify(data);
            
            const res = await fetch(`/api/${endpoint}?session_id=${sessionId}`, options);
            return await res.json();
        }

        // リボンアクション
        async function newTree() {
            if (confirm('新しい木を作成しますか？未保存の変更は失われます。')) {
                await apiCall('new', 'POST');
                await loadTree();
            }
        }

        async function saveDocument() {
            const data = await apiCall('save', 'POST');
            if (data.success) {
                const blob = new Blob([JSON.stringify(data.document, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `構造図-${Date.now()}.gktm`;
                a.click();
                URL.revokeObjectURL(url);
                updateStatus('保存しました');
            }
        }

        function loadDocument() {
            document.getElementById('file-input').click();
        }

        function handleFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;

            const reader = new FileReader();
            reader.onload = async (e) => {
                try {
                    const data = JSON.parse(e.target.result);
                    await apiCall('load', 'POST', { document: data });
                    await loadTree();
                    updateStatus('読み込みました');
                } catch (err) {
                    alert('ファイル読み込みエラー：' + err.message);
                }
            };
            reader.readAsText(file);
            event.target.value = '';
        }

        async function exportImage() {
            const svg = document.getElementById('tree-svg');
            const svgData = new XMLSerializer().serializeToString(svg);
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            const img = new Image();
            
            const bbox = svg.getBBox();
            canvas.width = bbox.width + 60;
            canvas.height = bbox.height + 60;
            
            img.onload = () => {
                ctx.fillStyle = 'white';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.drawImage(img, 30, 30);
                const pngUrl = canvas.toDataURL('image/png');
                const a = document.createElement('a');
                a.href = pngUrl;
                a.download = `構造図-${Date.now()}.png`;
                a.click();
                updateStatus('画像を出力しました');
            };
            img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgData)));
        }

        async function undo() {
            await apiCall('undo', 'POST');
            await loadTree();
        }

        async function redo() {
            await apiCall('redo', 'POST');
            await loadTree();
        }

        async function copySubtree() {
            const result = await apiCall('copy', 'POST', { uid: selectedUid });
            if (result.success) updateStatus('部分木をコピーしました');
            else alert('部分木を選択してください');
        }

        async function cutSubtree() {
            const result = await apiCall('cut', 'POST', { uid: selectedUid });
            if (result.success) {
                await loadTree();
                updateStatus('部分木を切り取りました');
            } else alert('根以外の部分木を選択してください');
        }

        async function pasteSubtree() {
            const result = await apiCall('paste', 'POST', { uid: selectedUid });
            if (result.success) {
                await loadTree();
                updateStatus('貼り付けました');
            } else alert('貼り付け先とコピー済み部分木が必要です');
        }

        async function duplicateSubtree() {
            const result = await apiCall('duplicate', 'POST', { uid: selectedUid });
            if (result.success) {
                await loadTree();
                updateStatus('複製しました');
            } else alert('根以外の部分木を選択してください');
        }

        async function editLabel() {
            if (!selectedUid) { alert('ノードを選択してください'); return; }
            const node = findNode(treeData, selectedUid);
            showModal('ラベル変更', node.label, (value) => {
                apiCall('edit_label', 'POST', { uid: selectedUid, label: value });
                loadTree();
            });
        }

        async function editTerminal() {
            if (!selectedUid) { alert('ノードを選択してください'); return; }
            const node = findNode(treeData, selectedUid);
            showModal('末端文字', node.terminal || '', (value) => {
                apiCall('edit_terminal', 'POST', { uid: selectedUid, terminal: value });
                loadTree();
            });
        }

        async function deleteNode() {
            const result = await apiCall('delete', 'POST', { uid: selectedUid });
            if (result.success) {
                selectedUid = null;
                await loadTree();
            } else alert('根以外のノードを選択してください');
        }

        async function clearChildren() {
            const result = await apiCall('clear_children', 'POST', { uid: selectedUid });
            if (result.success) await loadTree();
            else alert('子を持つノードを選択してください');
        }

        async function swapChildren() {
            const result = await apiCall('swap', 'POST', { uid: selectedUid });
            if (result.success) await loadTree();
            else alert('子を 2 つ以上持つノードを選択してください');
        }

        async function toggleHeadLeft() {
            await apiCall('toggle_head', 'POST');
            const btn = document.getElementById('head-btn');
            btn.textContent = btn.textContent === '左' ? '右' : '左';
        }

        async function setCC ommandA() {
            const result = await apiCall('set_ccommand_a', 'POST', { uid: selectedUid });
            if (result.success) {
                ccommandAUid = selectedUid;
                updateStatus(`c-command 起点 A: ${findNode(treeData, selectedUid).label}`);
            } else alert('起点 A を選択してください');
        }

        async function checkCCommand() {
            const result = await apiCall('check_ccommand', 'POST', { uid: selectedUid });
            if (result.success) {
                alert(`${result.a_label} → ${result.b_label}: ${result.ab}\\n${result.b_label} → ${result.a_label}: ${result.ba}`);
            } else alert('起点 A を設定し、目標 B を選択してください');
        }

        // 規則ボタン追加（簡易版）
        function addRuleButtons() {
            const rules = [
                ["C'' → C'", "C''", ["C'"]],
                ["C' → C I''", "C'", ["C", "I''"]],
                ["N'' → Det N'", "N''", ["Det", "N'"]],
                ["V'' → V'", "V''", ["V'"]],
                ["P'' → P'", "P''", ["P'"]],
            ];
            
            const group = document.createElement('div');
            group.className = 'ribbon-group';
            group.innerHTML = '<span class="ribbon-group-title">基本規則</span><div class="ribbon-buttons"></div>';
            
            rules.forEach(([desc, required, children]) => {
                const btn = document.createElement('button');
                btn.textContent = desc;
                btn.onclick = () => applyRule(required, children);
                group.querySelector('.ribbon-buttons').appendChild(btn);
            });
            
            document.getElementById('ribbon').appendChild(group);
        }

        async function applyRule(requiredLabel, childLabels) {
            const result = await apiCall('apply_rule', 'POST', { 
                uid: selectedUid, 
                required_label: requiredLabel, 
                child_labels: childLabels 
            });
            if (result.success) await loadTree();
            else alert(result.message || '規則を適用できません');
        }

        // ノード追加
        async function addNode(label, trace = false) {
            const result = await apiCall('add_node', 'POST', { 
                uid: selectedUid, 
                label, 
                trace 
            });
            if (result.success) await loadTree();
            else alert('親ノードを選択してください');
        }

        // ズーム
        function setZoom(value) {
            zoomLevel = value;
            document.getElementById('zoom-label').textContent = value + '%';
            const svg = document.getElementById('tree-svg');
            svg.style.transform = `scale(${value / 100})`;
            svg.style.transformOrigin = 'top left';
        }

        // ステータス更新
        function updateStatus(message) {
            document.getElementById('status-message').textContent = message;
        }

        // モーダル表示
        function showModal(title, defaultValue, callback) {
            document.getElementById('modal-title').textContent = title;
            document.getElementById('modal-input').value = defaultValue;
            document.getElementById('modal').classList.add('active');
            modalCallback = callback;
            setTimeout(() => document.getElementById('modal-input').focus(), 100);
        }

        function closeModal() {
            document.getElementById('modal').classList.remove('active');
            modalCallback = null;
        }

        function confirmModal() {
            const value = document.getElementById('modal-input').value;
            if (modalCallback) modalCallback(value);
            closeModal();
        }

        // コンテキストメニュー
        function showContextMenu(x, y, node) {
            const menu = document.getElementById('context-menu');
            menu.innerHTML = `
                <button onclick="editLabel()">ラベル変更</button>
                <button onclick="editTerminal()">末端文字</button>
                <hr>
                <button onclick="copySubtree()">コピー</button>
                <button onclick="cutSubtree()">切り取り</button>
                <button onclick="pasteSubtree()">貼り付け</button>
                <button onclick="duplicateSubtree()">複製</button>
                <hr>
                <button onclick="swapChildren()">左右交換</button>
                <button onclick="deleteNode()">削除</button>
                <button onclick="clearChildren()">子全削除</button>
            `;
            menu.style.left = x + 'px';
            menu.style.top = y + 'px';
            menu.style.display = 'block';
        }

        function hideContextMenu() {
            document.getElementById('context-menu').style.display = 'none';
        }

        // ショートカットキー
        function setupShortcuts() {
            document.addEventListener('keydown', (e) => {
                if (e.target.tagName === 'INPUT') return;
                
                switch(e.key) {
                    case 'F2': editLabel(); break;
                    case 'Delete': deleteNode(); break;
                    case 'z': if (e.ctrlKey) undo(); break;
                    case 'y': if (e.ctrlKey) redo(); break;
                    case 'c': if (e.ctrlKey) copySubtree(); break;
                    case 'v': if (e.ctrlKey) pasteSubtree(); break;
                    case 'x': if (e.ctrlKey) cutSubtree(); break;
                    case 'd': if (e.ctrlKey) duplicateSubtree(); break;
                    case 'Enter': if (e.ctrlKey) editTerminal(); break;
                    case '0': if (e.ctrlKey) setZoom(100); break;
                }
            });

            document.addEventListener('click', hideContextMenu);
        }

        // 初期化
        window.onload = async () => {
            await initSession();
            addRuleButtons();
            
            // ズームホイール
            document.getElementById('canvas-container').addEventListener('wheel', (e) => {
                if (e.ctrlKey) {
                    e.preventDefault();
                    const delta = e.deltaY > 0 ? -15 : 15;
                    const newZoom = Math.max(25, Math.min(250, zoomLevel + delta));
                    setZoom(newZoom);
                    document.getElementById('zoom-slider').value = newZoom;
                }
            });
        };
    </script>
</body>
</html>
"""

# ============================================================
# API エンドポイント
# ============================================================

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/session', methods=['POST'])
def create_session():
    session_id = uuid4().hex
    get_session(session_id)
    return jsonify({"session_id": session_id})


@app.route('/api/tree', methods=['GET'])
def get_tree():
    session_id = request.args.get('session_id')
    session = get_session(session_id)
    
    parent_map = assign_parent_map_recursive(session["root"])
    node_by_uid = build_all_nodes_map(session["root"])
    positions = layout_tree(session["root"])
    
    return jsonify({
        "tree": node_to_dict(session["root"]),
        "positions": positions,
        "selected_uid": session["selected_uid"],
        "ccommand_a_uid": session["ccommand_a_uid"]
    })


@app.route('/api/new', methods=['POST'])
def new_tree_api():
    session_id = request.args.get('session_id')
    session = get_session(session_id)
    
    session["root"] = build_default_tree(session["head_left"])
    session["undo_stack"].clear()
    session["redo_stack"].clear()
    session["selected_uid"] = None
    session["ccommand_a_uid"] = None
    
    return jsonify({"success": True})


@app.route('/api/save', methods=['POST'])
def save_document_api():
    session_id = request.args.get('session_id')
    session = get_session(session_id)
    
    document = {
        "format": "gktm",
        "version": 1,
        "head_left": session["head_left"],
        "figure_number": session["figure_number"],
        "tree": node_to_dict(session["root"])
    }
    
    return jsonify({"success": True, "document": document})


@app.route('/api/load', methods=['POST'])
def load_document_api():
    session_id = request.args.get('session_id')
    data = request.json
    document = data.get('document', {})
    
    if document.get("format") != "gktm" or "tree" not in document:
        return jsonify({"success": False, "error": "対応していないファイル形式です"})
    
    session = get_session(session_id)
    session["root"] = node_from_dict(document["tree"])
    session["head_left"] = document.get("head_left", True)
    session["figure_number"] = document.get("figure_number", 1)
    session["undo_stack"].clear()
    session["redo_stack"].clear()
    session["selected_uid"] = None
    
    return jsonify({"success": True})


@app.route('/api/undo', methods=['POST'])
def undo_api():
    session_id = request.args.get('session_id')
    session = get_session(session_id)
    
    if not session["undo_stack"]:
        return jsonify({"success": False, "message": "これ以上元に戻せません"})
    
    session["redo_stack"].append(snapshot(session))
    session["root"], session["head_left"] = session["undo_stack"].pop()
    session["selected_uid"] = None
    session["ccommand_a_uid"] = None
    
    return jsonify({"success": True})


@app.route('/api/redo', methods=['POST'])
def redo_api():
    session_id = request.args.get('session_id')
    session = get_session(session_id)
    
    if not session["redo_stack"]:
        return jsonify({"success": False, "message": "これ以上やり直せません"})
    
    session["undo_stack"].append(snapshot(session))
    session["root"], session["head_left"] = session["redo_stack"].pop()
    session["selected_uid"] = None
    session["ccommand_a_uid"] = None
    
    return jsonify({"success": True})


@app.route('/api/copy', methods=['POST'])
def copy_subtree_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    
    session = get_session(session_id)
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid:
        return jsonify({"success": False})
    
    session["clipboard_subtree"] = copy.deepcopy(node_by_uid[uid])
    return jsonify({"success": True})


@app.route('/api/cut', methods=['POST'])
def cut_subtree_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    
    session = get_session(session_id)
    parent_map = assign_parent_map_recursive(session["root"])
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid or uid == session["root"].uid:
        return jsonify({"success": False})
    
    # コピー
    session["clipboard_subtree"] = copy.deepcopy(node_by_uid[uid])
    
    # 削除
    push_undo(session)
    parent = parent_map.get(uid)
    if parent:
        parent.children = [c for c in parent.children if c.uid != uid]
    
    return jsonify({"success": True})


@app.route('/api/paste', methods=['POST'])
def paste_subtree_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    
    session = get_session(session_id)
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid or session["clipboard_subtree"] is None:
        return jsonify({"success": False})
    
    push_undo(session)
    clone = copy.deepcopy(session["clipboard_subtree"])
    renew_uids(clone)
    node_by_uid[uid].children.append(clone)
    
    return jsonify({"success": True})


@app.route('/api/duplicate', methods=['POST'])
def duplicate_subtree_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    
    session = get_session(session_id)
    parent_map = assign_parent_map_recursive(session["root"])
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid or uid == session["root"].uid:
        return jsonify({"success": False})
    
    push_undo(session)
    node = node_by_uid[uid]
    parent = parent_map.get(uid)
    clone = copy.deepcopy(node)
    renew_uids(clone)
    
    idx = parent.children.index(node)
    parent.children.insert(idx + 1, clone)
    
    return jsonify({"success": True})


@app.route('/api/edit_label', methods=['POST'])
def edit_label_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    label = data.get('label', '')
    
    session = get_session(session_id)
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid:
        return jsonify({"success": False})
    
    push_undo(session)
    node_by_uid[uid].label = label.strip()
    
    return jsonify({"success": True})


@app.route('/api/edit_terminal', methods=['POST'])
def edit_terminal_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    terminal = data.get('terminal', '')
    
    session = get_session(session_id)
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid:
        return jsonify({"success": False})
    
    push_undo(session)
    node_by_uid[uid].terminal = terminal.strip()
    
    return jsonify({"success": True})


@app.route('/api/delete', methods=['POST'])
def delete_node_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    
    session = get_session(session_id)
    parent_map = assign_parent_map_recursive(session["root"])
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid or uid == session["root"].uid:
        return jsonify({"success": False})
    
    push_undo(session)
    parent = parent_map.get(uid)
    if parent:
        parent.children = [c for c in parent.children if c.uid != uid]
    
    if session["ccommand_a_uid"] == uid:
        session["ccommand_a_uid"] = None
    
    return jsonify({"success": True})


@app.route('/api/clear_children', methods=['POST'])
def clear_children_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    
    session = get_session(session_id)
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid or not node_by_uid[uid].children:
        return jsonify({"success": False})
    
    push_undo(session)
    node_by_uid[uid].children = []
    
    return jsonify({"success": True})


@app.route('/api/swap', methods=['POST'])
def swap_children_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    
    session = get_session(session_id)
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid or len(node_by_uid[uid].children) < 2:
        return jsonify({"success": False})
    
    push_undo(session)
    node_by_uid[uid].children.reverse()
    
    return jsonify({"success": True})


@app.route('/api/toggle_head', methods=['POST'])
def toggle_head_api():
    session_id = request.args.get('session_id')
    session = get_session(session_id)
    
    session["head_left"] = not session["head_left"]
    
    return jsonify({"success": True})


@app.route('/api/set_ccommand_a', methods=['POST'])
def set_ccommand_a_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    
    session = get_session(session_id)
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid:
        return jsonify({"success": False})
    
    session["ccommand_a_uid"] = uid
    return jsonify({"success": True})


@app.route('/api/check_ccommand', methods=['POST'])
def check_ccommand_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    
    session = get_session(session_id)
    parent_map = assign_parent_map_recursive(session["root"])
    node_by_uid = build_all_nodes_map(session["root"])
    
    a_uid = session["ccommand_a_uid"]
    b_uid = uid
    
    if not a_uid or not b_uid or a_uid not in node_by_uid or b_uid not in node_by_uid:
        return jsonify({"success": False})
    
    a = node_by_uid[a_uid]
    b = node_by_uid[b_uid]
    
    ab = c_commands(a, b, parent_map)
    ba = c_commands(b, a, parent_map)
    
    return jsonify({
        "success": True,
        "a_label": a.label,
        "b_label": b.label,
        "ab": ab,
        "ba": ba
    })


@app.route('/api/add_node', methods=['POST'])
def add_node_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    label = data.get('label', 'X')
    trace = data.get('trace', False)
    
    session = get_session(session_id)
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid:
        return jsonify({"success": False})
    
    push_undo(session)
    node_by_uid[uid].children.append(Node(label=label, trace=trace))
    
    return jsonify({"success": True})


@app.route('/api/apply_rule', methods=['POST'])
def apply_rule_api():
    session_id = request.args.get('session_id')
    data = request.json
    uid = data.get('uid')
    required_label = data.get('required_label', '')
    child_labels = data.get('child_labels', [])
    
    session = get_session(session_id)
    node_by_uid = build_all_nodes_map(session["root"])
    
    if not uid or uid not in node_by_uid:
        return jsonify({"success": False, "message": "ノード未選択"})
    
    node = node_by_uid[uid]
    if node.label != required_label:
        return jsonify({"success": False, "message": f"{required_label} を選択してください"})
    
    if node.children:
        # 既存の子を置き換え
        pass
    
    push_undo(session)
    children = [Node(label=str(label)) for label in child_labels]
    if not session["head_left"]:
        children.reverse()
    node.children = children
    
    return jsonify({"success": True})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
