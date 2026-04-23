# temp-humidity-exporter <!-- omit in toc -->

BLE 温湿度センサーのアドバタイズを `bluepy` で受信し、Flask で Prometheus 形式のメトリクスを公開する exporter です。現行実装の本体は `src/thexporter/` パッケージで、`src/thexporter.py` は起動用の薄いラッパーです。

## 目次  <!-- omit in toc -->

- [現在の対応アドバタイズデータ](#現在の対応アドバタイズデータ)
- [主な構成](#主な構成)
- [セットアップ](#セットアップ)
- [設定ファイル](#設定ファイル)
- [起動方法](#起動方法)
- [HTTP エンドポイント](#http-エンドポイント)
- [Prometheus メトリクス](#prometheus-メトリクス)
- [Docker 利用時の注意](#docker-利用時の注意)
- [補足](#補足)
- [気になっていること](#気になっていること)
- [デバイスについて](#デバイスについて)
  - [ざっと手順](#ざっと手順)
  - [ファームウェアを変更する(pvvx化)](#ファームウェアを変更するpvvx化)


## 現在の対応アドバタイズデータ

- `pvvx_atc1441`: 15 バイトの ATC1441 互換 PVVX アドバタイズデータ
- `pvvx_custom`: 17 バイトの PVVX Custom Format
- `auto`: 上記 2 形式を自動判定

現行の `src/thexporter` 実装は PVVX 系の Environmental Sensing service data をデコードします。旧 README にあった `bthome` の説明は、現行実装とは一致しません。

## 主な構成

- `src/thexporter.py`: 起動用エントリポイント
- `src/thexporter/`: exporter 本体
- `config.json`: 実行時設定ファイル
- `requirements.txt`: Python 依存関係

## セットアップ

Raspberry Pi OS など Linux 環境を想定しています。

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv bluez bluetooth
cd /workspaces/temp-humidity-exporter
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

BLE スキャンには BlueZ とスキャン権限が必要です。root で実行しない場合は、環境によって次のような capability 付与が必要です。

```bash
sudo setcap 'cap_net_raw,cap_net_admin+eip' "$(readlink -f "$(which python3)")"
```

## 設定ファイル

現行実装では `config.json` が必須です。起動時に指定されたパスのファイルが存在しない場合、プロセスは終了します。

設定例:

```json
{
  "bind_host": "0.0.0.0",
  "port": 8000,
  "log_level": "INFO",
  "scan_seconds": 3.0,
  "metric_ttl_seconds": 180,
  "negative_cache_seconds": 60,
  "default_decoder": "auto",
  "default_sensor_name": "pvvx",
  "discovered_devices_path": "./discovered_devices.yml",
  "sensors": [
    {
      "mac": "AA:BB:CC:DD:EE:01",
      "name_alias": "greenhouse_north",
      "decoder": "auto"
    },
    {
      "mac": "AA:BB:CC:DD:EE:02",
      "name_alias": "greenhouse_south",
      "decoder": "pvvx_custom"
    }
  ]
}
```

設定項目:

- `bind_host`: Flask の bind アドレス。既定値は `0.0.0.0`
- `port`: HTTP listen ポート。既定値は `8000`
- `log_level`: ログレベル。既定値は `INFO`
- `scan_seconds`: 1 回の BLE スキャン時間。既定値は `3.0`
- `metric_ttl_seconds`: センサー値を fresh とみなす秒数。既定値は `180`
- `negative_cache_seconds`: `0x181A` を持たない広告として見えた MAC を一時的に再評価しない秒数。既定値は `60`。`0` で無効化
- `default_decoder`: 未指定センサーの既定 decoder 名。既定値は `auto`
- `default_sensor_name`: 自動発見時のフォールバック名プレフィックス。既定値は `pvvx`
- `discovered_devices_path`: 自動発見したデバイスを書き出す YAML のパス。省略時は `config.json` と同じディレクトリの `discovered_devices.yml`
- `sensors`: 監視対象センサーの配列。各要素は `mac` または `address`、任意で `name_alias`、`decoder`、`material`、`color` を持てます

`sensors.name_alias` は表示名の上書きです。未指定時は BLE 広告の Local Name を使い、それも無い場合は `pvvx_<末尾6桁>` のフォールバック名になります。

`0x181A` の Service Data を含む広告を受信すると、対象デバイスは `discovered_devices.yml` に保存され、次回起動以降も収集対象になります。書き出される YAML は次のような構成です。

```yaml
devices:
  - mac: "AA:BB:CC:DD:EE:01"
    name: "LYWSD03MMC"
    decoder: "pvvx_custom"
    target: "undefined"
```

`target` は `undefined` / `include` / `ignore` を受け付けます。`undefined` と `include` は収集対象、`ignore` は収集対象外です。`undefined` のデバイスはメトリクス収集対象ですが、`/health` と `/healthz` の必須監視対象には含めません。

`0x181A` を持たないデバイスは negative cache に入り、`negative_cache_seconds` の間は再判定をスキップします。TTL が切れると再び `0x181A` を持つかどうか評価されます。

## 起動方法

既定の `config.json` を使う場合:

```bash
cd /workspaces/temp-humidity-exporter
. .venv/bin/activate
python3 src/thexporter.py
```

設定ファイルを明示する場合:

```bash
python3 src/thexporter.py --config /path/to/config.json
```

モジュール起動でも同じです。

```bash
python3 -m src.thexporter --config /path/to/config.json
```

利用できる CLI オプションは `-c`, `--config` のみです。

## HTTP エンドポイント

- `/`: exporter の状態とデバイス一覧を JSON で返します
- `/health`: ヘルスチェック用のプレーンテキストを返します
- `/healthz`: `/health` と同じ内容を返します
- `/metrics`: Prometheus text format でメトリクスを返します

`/health` は以下の条件で `200` を返します。

- `sensors` にある全センサーと、`discovered_devices.yml` で `target: include` の全センサーが TTL 内で fresh
- それらが 1 台も無い場合は、`ignore` ではない発見済みセンサーのうち少なくとも 1 台が TTL 内で fresh
- かつ scanner thread が稼働中で、直近エラーがない

条件を満たさない場合は `503` を返します。レスポンス本文は `200\n` または `503\n` です。

## Prometheus メトリクス

主なメトリクス:

- `thexporter_info`
- `thexporter_scanner_running`
- `thexporter_scrape_success`
- `thexporter_sensor_up`
- `thexporter_last_seen_timestamp_seconds`
- `thexporter_advertisement_age_seconds`
- `thexporter_temperature_celsius`
- `thexporter_humidity_percent`
- `thexporter_battery_percent`
- `thexporter_battery_voltage_volts`
- `thexporter_rssi_dbm`
- `thexporter_packet_counter`
- `thexporter_flags`

センサー単位のメトリクスには少なくとも次のラベルが付きます。

- `address`
- `sensor_name`
- `decoder`

Prometheus 設定例:

```yaml
scrape_configs:
  - job_name: temp-humidity-exporter
    static_configs:
      - targets:
          - raspberrypi.local:8000
```

## Docker 利用時の注意

コンテナで BLE を使う場合は、少なくとも次が必要です。

- `network_mode: host`
- `cap_add: [NET_ADMIN, NET_RAW]`
- `/run/dbus` のマウント
- コンテナ内で読める `config.json`

起動コマンドは現行実装に合わせて `python src/thexporter.py --config /app/config.json` を基準にしてください。

## 補足

この README は `src/thexporter` の現行実装を基準にしています。`dustbox` / `dustbox2` 配下の旧ソースは参照していません。

## 気になっていること

- `docker history` で`DISK USAGEが868MB`で大きい印象。問題はDockerfileの`apt install(480MB)`なので、これを最適化したい
  - https://github.com/IanHarvey/bluepy にビルド方法が記載されてるので、追って参考にしよう
- `mecric`に`material`と`color`が含まれており、これがフィラメントを示すだろう、と考えている。grafanaでどういうダッシュボードを作ると一番良いかを模索中

## デバイスについて

### ざっと手順

1. [Xiaomi Home](https://play.google.com/store/apps/details?id=com.xiaomi.smarthome&hl=ja) アプリのダウンロードとユーザ登録
1. [Xiaomi Home](https://play.google.com/store/apps/details?id=com.xiaomi.smarthome&hl=ja) アプリでデバイスをいったん登録
1. [token-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor) を用いてファーム更新用の情報を取得
1. 上記で取得したtoken等を用いてファームウェアを更新
   ファームウェアは2層化されている様子。
    1. まずは公式側のファームの更新
    1. つづいて、ATCファームウェアを導入する
1. [nRF Connect](https://play.google.com/store/apps/details?id=no.nordicsemi.android.mcp&hl=ja) 等のBluetoothデバッグアプリを用いて、対象のデバイスがUUID[0x181A]でService Dataをアドバタイズ出力しているか、を確認する
   
### ファームウェアを変更する(pvvx化)

- https://pvvx.github.io/ATC_MiThermometer/TelinkMiFlasher.html
- https://atc1441.github.io/TelinkFlasher.html
