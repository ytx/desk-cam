# Raspberry Pi HQ Camera HDMI Viewer

## プロジェクト概要

Raspberry Pi 3B+ と HQ Camera（IMX477）を使い、机の上を撮影して HDMI 出力するビューアアプリケーション。

- 目標FPS: 5FPS 程度（それ以上は不要）
- ROI（表示領域）を動的に変更できること
- X11 / Wayland 不要で動作すること
- カメラは物理的に 180度回転して設置されることがあるため、回転設定を切り替えられること
- Webインタフェースを用意して、以下の処理を行えるようにする
  - ROI の位置とサイズを変更（プレビュー上でドラッグ操作可能）
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
    display.py       # pygame kmsdrm表示 (アスペクト比保持 + 黒帯)
    web_server.py    # HTTPサーバー + REST API (ThreadingMixIn)
    mqtt_client.py   # MQTT (online/away, プリセット切替)
    logger.py        # タグ付きロガー
  web/
    index.html       # SPA (プレビュー, ROIエディタ, プリセット管理)
```

---

## ISP / ScalerCrop の仕組みと制約

### ISP 出力サイズは常に 1920x1080 固定

ROI のアスペクト比に関わらず ISP 出力は 1920x1080。理由:
- 出力サイズを変更すると ISP がセンサーモードを再選択し、ScalerCrop の有効範囲が変わってしまう
- reconfigure には stop→start が必要で 1-2 秒の中断が発生する
- 固定なら crop_limits も固定で扱いやすい

### ScalerCrop の座標系

```
センサー物理ピクセル: 4056×3040 (PixelArraySize)
ISP 有効範囲:         センサーモード依存（例: 2028x1080 モード時は y=440〜2600 付近のみ有効）
```

- `set_controls({"ScalerCrop": (x, y, w, h)})` でセンサー座標系の ROI を指定
- ISP は ROI を 16:9 にクロップしてから 1920x1080 に拡大出力
- **ISP の有効範囲外の座標はクランプされる**（例: y=200 を指定しても y=440 に修正される）
- `PixelArraySize` は物理サイズで、`ScalerCropMaximum` は ISP の報告する最大範囲だが、**実際の有効範囲はそれより狭い**
- 実際の有効範囲は、全センサー指定時の metadata `ScalerCrop` で取得（`_effective_crop`）

### HDMI 表示のアスペクト比補正 (display.py)

ISP 出力は常に 16:9 だが、ROI が 4:3 や 1:1 の場合もある。
display.py で ROI のアスペクト比に合わせて表示し、余白を黒で埋める。

```
ROI 16:9 → 画面いっぱい
ROI 4:3  → 左右に黒帯（ピラーボックス）
ROI 1:1  → 左右に大きな黒帯
```

### Web プレビューの全体像表示

ISP 出力が 16:9 のため、4:3 センサーの全体像は直接取得できない。
スナップショット撮影時に以下の処理で全体像を合成:

1. ScalerCrop を全センサー (0,0,4056,3040) に設定
2. ISP は 16:9 にクロップして出力（例: y=440〜2600 のみ）→ `_effective_crop` に記録
3. 撮影後、Python 側で 4:3 キャンバス (1920x1440) を作成
4. 撮影画像をキャンバスの正しい Y 位置に貼り付け（上下の黒帯がクロップ部分）
5. `snapshot_crop` を `(0, 0, 4056, 3040)` に設定（キャンバスは全センサーを表現）
6. ScalerCrop を元の ROI に復元

`Refresh` ボタン押下時のみ実行（自動更新なし、HDMI が一瞬全体表示になるため）。

### スレッド安全性

- `camera.py` の全メソッドは `threading.Lock` で保護
- `crop_limits` / `snapshot_crop` / `get_actual_roi()` はキャッシュ値を返す（ロック不要）
- `get_status()` はキャッシュ値のみ参照（デッドロック防止）

---

## 重要な実装ポイント

### カメラ (camera.py)

- ISP 出力: 常に 1920x1080 / RGB888 固定
- `get_frame()`: ロック付きで `capture_array("main")` → numpy (H,W,3) BGR
- `set_roi(x, y, w, h)`: ScalerCrop 設定のみ（metadata 読み返し不要）
- `set_rotation(enabled)`: stop→configure→start（1-2秒中断）
- `crop_limits`: 起動時に `_effective_crop` から取得してキャッシュ（ISP の実際の有効範囲）
- `snapshot_crop`: プレビュー画像の座標系 = 全センサー (0,0,4056,3040)
- `refresh_snapshot()`: 明示的呼び出しのみ

### HDMI 表示 (display.py)

- `set_roi_aspect(w, h)`: ROI 変更時に呼び出し、表示アスペクト比を更新
- `show_frame()`: ROI アスペクト比で画面内にフィット + 黒帯、アスペクト変更時のみ `screen.fill`
- BGR→RGB 変換: `frame[:, :, ::-1]`
- 高速変換: `pygame.image.frombuffer()` → `pygame.transform.scale()`

### Web サーバー (web_server.py)

- `ThreadingMixIn` で並列リクエスト処理
- `urlparse` でクエリパラメータを除去してからパスマッチング（GET/POST/DELETE 全て）
- API エンドポイント:
  - `GET /api/status` — ROI, rotation, presets, sensor, crop_limits, snapshot_crop
  - `POST /api/roi` — `{x, y, w, h}`
  - `POST /api/rotation` — `{enabled: bool}`
  - `POST /api/snapshot/refresh` — 全体像再撮影（JPEG 返却）
  - `GET /api/snapshot` — キャッシュ済み全体像 JPEG
  - `POST /api/presets` — 保存 `{name}`
  - `POST /api/presets/<name>/load` — 読込
  - `DELETE /api/presets/<name>` — 削除

### Web UI (web/index.html)

- プレビュー: キャッシュ済み全体像を表示、`Refresh` ボタンで更新
- ROI オーバーレイ: Canvas で描画、`snapshot_crop` 座標系でマッピング
- ROI 操作: 四隅/四辺ドラッグでリサイズ、矩形内ドラッグで移動、`crop_limits` でクランプ
- ドラッグ完了時に自動 Apply
- 数値入力 + Apply ボタンでも ROI 変更可能
- Apply 後に `fetchStatus()` で最新値を反映

### 設定永続化 (config.py)

- パス: `~/.config/desk-cam/config.json`
- `set()` → 即座に JSON 書き込み + 5秒デバウンスで `persist()`
- `persist()`: `sudo /boot/firmware/config/save.sh --all` で boot パーティションにコピー
- overlay filesystem 環境で電源断にも対応

### MQTT (mqtt_client.py)

- paho-mqtt `CallbackAPIVersion.VERSION2`
- トピック: `clients/<hostname>` → `"online"` (retain + will=`"away"`)
- トピック: `clients/<hostname>/preset` → 現在のプリセット名 (retain)
- トピック: `clients/<hostname>/preset/set` → subscribe、受信したプリセット名をロード
- `loop_start()` でバックグラウンド実行
- 接続失敗時はログ警告のみ（MQTT なしでも動作継続）

---

## 設定デフォルト値

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

## Ansible デプロイ

ロール: `pi-setup/ansible/roles/desk-cam-pygame/`
プレイブック: `pi-setup/ansible/desk-cam.yml`
インベントリ: `pi-setup/ansible/inventory.yml` の `desk-cam` グループ

```bash
cd ~/git/pi-setup/ansible
ansible-playbook -i inventory.yml desk-cam.yml
```

### ロールの処理内容
1. システムパッケージインストール (python3-picamera2, pygame, numpy, pil, paho-mqtt, libsdl2)
2. video グループ追加
3. synchronize で py/ と web/ をリモートへ転送
4. systemd サービスデプロイ (`SDL_VIDEODRIVER=kmsdrm`, `SDL_AUDIODRIVER=dummy`)
5. CUI モード設定 (`multi-user.target`)
6. デフォルト config.json 作成 (`force: no` で既存は上書きしない)
7. config-persistence に登録 (`/boot/firmware/config/config.json` が無い場合のみ)

---

## 実行環境

| 項目 | 内容 |
|---|---|
| ハードウェア | Raspberry Pi 3B+ |
| カメラ | HQ Camera（IMX477）、センサー 4056×3040 |
| OS | Raspberry Pi OS Lite（デスクトップ不要） |
| Python ライブラリ | `picamera2`, `pygame`, `libcamera`, `Pillow`, `paho-mqtt` |
| 実行ユーザー | `video` グループ所属 |
| 環境変数 | `SDL_VIDEODRIVER=kmsdrm`, `SDL_AUDIODRIVER=dummy` |
| overlay filesystem | config-persistence で設定を boot パーティションに永続化 |

---

## 実装しないこと（スコープ外）

- 音声処理
- X11 / Wayland での動作
- GStreamer パイプライン
- 高FPS対応（5FPS 以上は不要）
- UDP ソケットによる ROI 制御（Web UI で代替）
- ISP 出力サイズの動的変更（センサーモード変更による副作用が大きい）
