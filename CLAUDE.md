# Raspberry Pi HQ Camera HDMI Viewer

## プロジェクト概要

Raspberry Pi 3B+ と HQ Camera（IMX477）を使い、机の上を撮影して HDMI 出力するビューアアプリケーション。

- 目標FPS: 5FPS 程度（それ以上は不要）
- ROI（表示領域）を動的に変更できること
- X11 / Wayland 不要で動作すること
- カメラは物理的に 180度回転して設置されることがあるため、回転設定を切り替えられること
- Webインタフェースを用意して、以下の処理を行えるようにする
  - ROI の位置とサイズを変更
  - カメラの回転設定を変更（180度回転の切り替え）
  - プリセットの保存・呼び出し
- MQTT を使用して、外部からプリセットの切り替えとonline/awayの状態管理ができるようにする
- ../pi-setup のセットアップスクリプトで、必要なライブラリのインストールや環境設定を行う

---

## 採用アーキテクチャ

**picamera2 + ScalerCrop + pygame（kmsdrm）+ Web UI + MQTT**

```
HQ Camera → ISP（ScalerCrop + Transform） → pygame（kmsdrm） → HDMI出力
                      ↑
              Web UI (REST API) / MQTT で動的に ROI・回転・プリセットを変更
```

### 選定理由
- ScalerCrop はISPレベルのハードウェアクロップのため CPU 負荷なし
- SDL_VIDEODRIVER=kmsdrm により X11 不要
- 5FPS・1080p の要件なら処理余裕あり
- 動的な ROI 変更が `set_controls()` 1行で済む

---

## ディレクトリ構成

```
desk-cam/
  CLAUDE.md
  py/
    app.py           # メインループ & 各モジュール統合
    config.py        # JSON設定永続化 (~/.config/desk-cam/config.json)
    camera.py        # picamera2ラッパー (ROI, 回転, フレーム取得)
    display.py       # pygame kmsdrm表示
    web_server.py    # HTTPサーバー + REST API
    mqtt_client.py   # MQTT (online/away, プリセット切替)
    logger.py        # タグ付きロガー
  web/
    index.html       # SPA (ROIエディタ, プリセット管理)
```

## 重要な実装ポイント

### カメラ設定 (camera.py)

- `Camera(rotation)`: Transform(hflip, vflip) で初期化、main=1920x1080/RGB888
- `get_frame()`: `capture_array("main")` で numpy 配列取得
- `get_frame_jpeg(quality=70)`: Pillow で JPEG エンコード（Web プレビュー用）
- `set_roi(x, y, w, h)`: `set_controls({"ScalerCrop": (x,y,w,h)})`
- `set_rotation(enabled)`: カメラ再起動が必要（1-2秒の中断）
- Transform 使用時、ScalerCrop の座標は**回転後の座標系**で指定できる（直感的）
- センサー最大サイズは `camera_properties["PixelArraySize"]` で取得

### フレーム表示 (display.py)

```python
# 速い（推奨）: メモリコピー1回で済む
surf = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
```

### Web API (web_server.py)

- `GET /api/status` — 現在の ROI, 回転, プリセット一覧, センサーサイズ
- `POST /api/roi` — `{x, y, w, h}`
- `POST /api/rotation` — `{enabled: bool}`
- `GET /api/presets` — プリセット一覧
- `POST /api/presets` — 保存 `{name}`
- `POST /api/presets/<name>/load` — 読込
- `DELETE /api/presets/<name>` — 削除
- `GET /api/snapshot` — 現在フレームの JPEG

### MQTT (mqtt_client.py)

- トピック: `clients/<hostname>` → `"online"` (retain + will=`"away"`)
- トピック: `clients/<hostname>/preset` → 現在のプリセット名 (retain)
- トピック: `clients/<hostname>/preset/set` → subscribe、受信したプリセット名をロード
- paho-mqtt の `loop_start()` でバックグラウンド実行
- MQTT 接続失敗時はログ警告のみ（MQTT なしでも動作継続）

### 設定 (config.py)

パス: `~/.config/desk-cam/config.json`

```json
{
  "roi": {"x": 0, "y": 0, "w": 4056, "h": 3040},
  "rotation": true,
  "presets": {
    "default": {"x": 0, "y": 0, "w": 4056, "h": 3040, "rotation": true}
  },
  "mqtt": {"broker": "localhost", "port": 1883, "ws_port": 9090, "topic_prefix": "clients"},
  "web_port": 8080
}
```

---

## FPS の目安（kmsdrm + frombuffer 使用時）

| main size | 期待 FPS |
|---|---|
| 640×480 | 20〜30 FPS |
| 1280×720 | 10〜15 FPS |
| 1920×1080 | 5〜8 FPS ← ターゲット |

---

## 実行環境・前提条件

| 項目 | 内容 |
|---|---|
| ハードウェア | Raspberry Pi 3B+ |
| カメラ | HQ Camera（IMX477）、センサー最大 4056×3040 |
| OS | Raspberry Pi OS Lite 推奨（デスクトップ不要） |
| Python ライブラリ | `picamera2`, `pygame`, `libcamera`, `Pillow`, `paho-mqtt` |
| 実行ユーザー | `video` グループへの所属が必要 |
| 環境変数 | `SDL_VIDEODRIVER=kmsdrm`, `SDL_AUDIODRIVER=dummy` |

```bash
# 実行
SDL_VIDEODRIVER=kmsdrm SDL_AUDIODRIVER=dummy python3 py/app.py
```

## Ansible デプロイ

ロール: `pi-setup/ansible/roles/desk-cam-pygame/`

```bash
ansible-playbook -i inventory playbook.yml --tags desk-cam-pygame
```

---

## 実装しないこと（スコープ外）

- 音声処理
- X11 / Wayland での動作
- GStreamer パイプライン
- 高FPS対応（5FPS 以上は不要）
- UDP ソケットによる ROI 制御（Web UI で代替）
