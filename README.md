# 言語学かんたん構造図メーカー - ウェブアプリ版

あなたの Python 製統語論構造図作成ソフトのウェブアプリ版です。

## 概要

元々の PyQt6 ベースのデスクトップアプリを、Flask を使用したウェブアプリとして再構築しました。
Mac の CPU 世代問題を回避し、ブラウザさえあればどの環境でも動作します。

## 機能

- **木構造の作成・編集**: GB/X バー理論期の表記に対応
- **ノード操作**: ラベル変更、末端文字入力、追加、削除
- **クリップボード機能**: コピー、切り取り、貼り付け、複製
- **履歴管理**: Undo/Redo（最大 100 件）
- **c-command 判定**: 言語学理論に基づく照応関係の分析
- **ファイル入出力**: JSON 形式での保存・読み込み
- **画像出力**: SVG 形式からの PNG エクスポート
- **ズーム機能**: 25%〜250% の拡大縮小

## 起動方法

```bash
# 依存パッケージのインストール
pip install flask flask-cors

# サーバー起動
python app.py
```

ブラウザで `http://localhost:5000` にアクセスしてください。

## 使い方

### 基本操作

1. **ノード選択**: クリックで選択、ダブルクリックで編集
2. **ノード追加**: リボンの規則ボタンまたは「自由項目」から追加
3. **ラベル変更**: F2 キーまたはダブルクリック
4. **末端文字入力**: Ctrl+Enter または葉ノードをダブルクリック
5. **削除**: Delete キーまたは右クリックメニュー

### ショートカットキー

| キー | 機能 |
|------|------|
| F2 | ラベル変更 |
| Delete | ノード削除 |
| Ctrl+Z | 元に戻す |
| Ctrl+Y | やり直す |
| Ctrl+C | コピー |
| Ctrl+V | 貼り付け |
| Ctrl+X | 切り取り |
| Ctrl+D | 複製 |
| Ctrl+Enter | 末端文字入力 |
| Ctrl+0 | ズームリセット |
| Ctrl+ホイール | ズームイン/アウト |

### c-command 判定

1. 起点となるノード A を選択
2. 「起点 A に設定」をクリック
3. 目標ノード B を選択
4. 「判定」をクリックして結果を表示

## ファイル形式

`.gktm` または `.json` 形式で保存できます：

```json
{
  "format": "gktm",
  "version": 1,
  "head_left": true,
  "figure_number": 1,
  "tree": {
    "uid": "...",
    "label": "C''",
    "trace": false,
    "terminal": "",
    "children": [...]
  }
}
```

## 技術スタック

- **バックエンド**: Python + Flask
- **フロントエンド**: HTML5, CSS3, JavaScript (Vanilla)
- **描画**: SVG (Scalable Vector Graphics)
- **データ構造**: 元コードの Node クラスを継承

## デスクトップ版との違い

| 機能 | デスクトップ版 | ウェブ版 |
|------|---------------|---------|
| UI | PyQt6 リボン | Web リボン |
| 描画 | QGraphicsView | SVG |
| ファイル保存 | ダイアログ | ダウンロード |
| 画像出力 | PNG/JPEG/BMP | PNG (SVG 経由) |
| シリアル認証 | あり | なし |
| プラットフォーム | Windows のみ | クロスプラットフォーム |

## 開発者向け

### API エンドポイント

- `POST /api/session` - 新しいセッション作成
- `GET /api/tree?session_id=xxx` - 木構造取得
- `POST /api/new` - 新規木作成
- `POST /api/save` - 保存用データ取得
- `POST /api/load` - 文件読み込み
- `POST /api/undo` - 元に戻す
- `POST /api/redo` - やり直す
- `POST /api/copy` - コピー
- `POST /api/cut` - 切り取り
- `POST /api/paste` - 貼り付け
- `POST /api/duplicate` - 複製
- `POST /api/edit_label` - ラベル編集
- `POST /api/edit_terminal` - 末端文字編集
- `POST /api/delete` - 削除
- `POST /api/clear_children` - 子全削除
- `POST /api/swap` - 左右交換
- `POST /api/toggle_head` - ヘッド方向切替
- `POST /api/set_ccommand_a` - c-command 起点設定
- `POST /api/check_ccommand` - c-command 判定
- `POST /api/add_node` - ノード追加
- `POST /api/apply_rule` - 規則適用

### ローカル開発

```bash
# 開発モードで起動（デバッグ有効）
python app.py

# または
export FLASK_ENV=development
flask run
```

## ライセンス

元のデスクトップ版に準じます。

## サポート

問題や要望があれば、元のデスクトップ版の開発元にご連絡ください。
