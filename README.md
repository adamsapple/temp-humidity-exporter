# temp-humidity-exporter

Bluetooth 対応の温湿度計が送信する BLE アドバタイズを受信し、Flask の `/metrics` で Prometheus 形式のメトリクスとして公開する exporter です。

現状サポートしているアドバタイズ形式:
- `bthome`: BTHome v2 の平文広告
- `pvvx_custom`: PVVX / ATC 系カスタムファームウェアの Custom Format
- `auto`: 上の 2 形式を順に自動判定

## ファイル構成

- `src/thexporter/`: exporter の Python パッケージ本体
- `requirements.txt`: Python 依存関係
- `config.json`: 起動時に読むローカル設定ファイル
- `Dockerfile`: コンテナイメージ定義
- `docker-compose.yml`: Raspberry Pi 上の compose 起動定義

## Raspberry Pi 4B での準備

Raspberry Pi OS を想定しています。

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv bluez bluetooth
cd /workspaces/temp-humidity-exporter
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Bluetooth スキャンには BlueZ が必要です。アドバタイズ受信だけであれば通常は root 不要ですが、環境によっては `sudo setcap 'cap_net_raw,cap_net_admin+eip' $(readlink -f $(which python3))` などの追加設定が必要になることがあります。

## 起動方法

複数の温湿度計を個別に管理する場合は、既定では `config.json` を読みます。

```bash
cd /workspaces/temp-humidity-exporter
. .venv/bin/activate
python3 src/thexporter.py
```

dev container など BlueZ や system D-Bus が見えていない環境でアプリの疎通だけ確認したい場合は、mock バックエンドを使えます。

```bash
cd /workspaces/temp-humidity-exporter
. .venv/bin/activate
THX_SCANNER_BACKEND=mock python3 src/thexporter.py
```

`config.json` の例:

```json
{
  "bind_host": "0.0.0.0",
  "port": 8000,
  "metric_ttl_seconds": 180,
  "scan_mode": "passive",
  "log_level": "INFO",
  "default_decoder": "auto",
  "default_sensor_name": "ble_sensor",
  "sensors": [
    {"mac": "AA:BB:CC:DD:EE:01", "name": "greenhouse_north", "decoder": "auto"},
    {"mac": "AA:BB:CC:DD:EE:02", "name": "greenhouse_south", "decoder": "bthome"}
  ]
}
```

単一端末だけで使いたい場合は従来どおり以下でも動作します。

```bash
THX_SENSOR_MAC=AA:BB:CC:DD:EE:FF \
THX_SENSOR_NAME=greenhouse_main \
THX_DECODER=auto \
python3 src/thexporter.py
```

主要な環境変数:

- `THX_CONFIG_PATH`: 設定ファイルのパス。既定値は `config.json`
- `THX_SENSORS`: 複数センサー設定用の JSON 配列。指定時は `config.json` の `sensors` より優先されます。各要素は `mac` または `address`、任意で `name`、`decoder` を持てます
- `THX_SENSOR_MAC`: 単一センサー向けの後方互換設定。`THX_SENSORS` 未指定時のみ使用
- `THX_SENSOR_NAME`: 単一センサー時の `sensor_name` ラベル。複数センサー時は未指定項目のデフォルト名プレフィックスにも使用
- `THX_DECODER`: 既定の decoder。`auto`, `bthome`, `pvvx_custom`
- `THX_SCANNER_BACKEND`: `ble` または `mock`。既定値は `ble`
- `THX_SCAN_MODE`: `passive` または `active`。既定値は `passive`。失敗時は自動で `active` へフォールバック
- `THX_METRIC_TTL_SECONDS`: 何秒間を fresh とみなすか。既定値は `180`
- `THX_BIND_HOST`: Flask bind アドレス。既定値は `0.0.0.0`
- `THX_PORT`: Flask listen port。既定値は `8000`
- `THX_LOG_LEVEL`: `DEBUG`, `INFO` など

設定の優先順位は `環境変数 > config.json > 既定値` です。

`THX_SENSORS` も `config.json` も指定しない場合は、対応する広告を見つけたセンサーを自動発見して `ble_sensor_<mac>` 形式の名前で出力します。
ただし `THX_SCANNER_BACKEND=mock` の場合は、未設定時に `00:00:00:00:00:01` / `<default_sensor_name>_mock` の疑似センサーを生成します。


## Docker Compose での起動

Raspberry Pi 上で `docker compose` を使う場合は、BlueZ の system D-Bus にアクセスできるように `host` ネットワークと `/run/dbus` のマウントを使います。

```bash
cd /workspaces/temp-humidity-exporter
docker compose up -d --build
```

この compose 定義では以下を前提にしています。

- イメージ内にコピーされた `config.json` を `/app/config.json` として使用
- `DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/dbus/system_bus_socket` を設定
- `NET_ADMIN` と `NET_RAW` を付与
- ポートは `network_mode: host` で Raspberry Pi 本体の `8000` をそのまま使用

環境によって BLE スキャン権限が不足する場合は、追加で `privileged: true` を検討してください。まずは現在の compose 定義で試すのがおすすめです。
`docker compose` を dev container などからホストの Docker daemon に向けて実行する場合、workspace 内の `./config.json` を bind mount するとパス解決の違いで失敗することがあります。この compose 定義はその問題を避けるため、`config.json` をイメージへ同梱する前提にしています。設定を変えたら `docker compose up --build` でイメージを作り直してください。
一方で、一般的な dev container のように `/run/dbus/system_bus_socket` と Bluetooth デバイスが見えていない環境では、実 BLE スキャンはできません。その場合は `THX_SCANNER_BACKEND=mock` で Flask と metrics の確認を行い、実機 BLE は Raspberry Pi ホストかこの compose 環境で確認してください。

## エンドポイント

- `/`: 設定済みセンサー一覧の簡易確認
- `/healthz`: 設定済み全センサーが TTL 内なら `200`。未設定モードでは少なくとも 1 台 fresh なら `200`
- `/metrics`: Prometheus 形式の exporter 出力

代表的なメトリクス:

- `ble_temp_humidity_configured_sensor_info`
- `ble_temp_humidity_sensor_up`
- `ble_temp_humidity_temperature_celsius`
- `ble_temp_humidity_relative_humidity_percent`
- `ble_temp_humidity_battery_percent`
- `ble_temp_humidity_battery_voltage_volts`
- `ble_temp_humidity_last_seen_timestamp_seconds`
- `ble_temp_humidity_advertisement_age_seconds`
- `ble_temp_humidity_rssi_dbm`

各メトリクスには `address` と `sensor_name` ラベルが付くため、Prometheus 側で複数端末を識別できます。

## Prometheus 設定例

```yaml
scrape_configs:
  - job_name: temp-humidity-exporter
    static_configs:
      - targets:
          - raspberrypi.local:8000
```

## 補足

温湿度計ごとに BLE 広告フォーマットは異なります。もし実機が `bthome` / `pvvx_custom` 以外の形式を使っている場合は、その広告データ仕様に合わせて `src/thexporter/decoders.py` の decoder を追加してください。
