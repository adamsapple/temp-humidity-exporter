# サマリ

機能追加をしたい。
bluetoothデバイスからデバイス名を取得したい。
現在はconfig.jsonにあらかじめデバイス名を記載している。これをデバイスから取得して利用する仕様に変更したい。

現在は広告データに181aが含まれているかどうかで、対象デバイスかどうかを判断してるが、アドバタイズデータの容量制限の都合から、デバイス側が送信データをローテーションしている可能性がある。また、ローテーションしてない場合は広告データからLocal NameやShort Nameを取得できない為、GATT通信から取得してくるようにしたい。

## 前提

- src/.dustbox以下は不要なファイルであり、調査や編集は不要


## 追加機能の要件

- SCANしたデバイス情報は、DiscoveredDevices(というクラス or 辞書)に以下の情報を保持する
  - mac
  - device_name (初期値はNone)
  - ターゲットとするか(is_target):unknown, include, exclude
- extract_pvvx_service_dataでpayloadがあるかどうかのチェックをする前にadtype(9,8)にdevice_nameが入っているかの確認をする
- 情報収集対象のデバイスにおいて、初回発見後x秒以上たっても広告データからデバイス名が取得出来ていないデバイスはGATT通信を用いてデバイス名を取得出来るかを試す。取得できなければ、x秒後に再度試す。このxはconfig.jsonに設定を設け引用する。
- もしこの方法でデバイス名が問題無く取得できるのであれば、config.jsonへのデバイス名設定は不要なため削除する。
- metricsにて配信するデバイス情報はでデバイス名が取得できたもののみにする。でないとprometheus的に属性が変わってしまい別情報になってしまう為。別情報にならない方法があるなら教えてほしい。


## AIからの実装応答(実装指示メモ)

### 実装方針

```md
- device_name の取得は `handleDiscovery()` の先頭で実施する。
- adtype 9 (Complete Local Name) / adtype 8 (Shortened Local Name) を確認し、取得できた名前を保持する。
- その後で `extract_pvvx_service_data()` を実行し、PVVX の service data が存在するかを判定する。
- これにより、「名前だけを含む広告」と「181A service data を含む広告」が別パケットで到着しても、同一 MAC address の情報として後で統合できるようにする。
```

### データ保持方針

```md
- 新しい独立クラス `DiscoveredDevices` は必須ではない。
- 既存の `ScanDataStore` に、発見済みデバイスの状態を保持する辞書を追加する方針とする。
- `SensorReading.name` は最終的な表示名として残すが、名前の source of truth は ScanDataStore 内の発見済みデバイス状態で保持する。
- 発見済みデバイス状態には最低限以下を持たせる。
  - address
  - device_name (`None` 可)
  - is_target (`unknown` / `include` / `exclude`)
  - first_seen_timestamp
  - last_seen_timestamp
  - last_gatt_name_attempt_timestamp
  - last_gatt_name_error
```

### スキャン時の処理順

```md
1. `handleDiscovery()` 呼び出し時に `device.addr` を正規化して address を取得する。
2. address をキーに発見済みデバイス状態を更新する。
3. adtype 9 / 8 を確認し、名前があれば `device_name` を更新する。
4. `extract_pvvx_service_data()` を実行する。
5. PVVX payload を decode できた場合のみ、対象デバイス判定を行う。
6. 対象デバイスであれば `is_target=include` とし、`SensorReading` を更新する。
7. 名前が未取得の対象デバイスについてのみ、条件を満たせば GATT による名前取得を試行する。
8. 対象外と判断したデバイスは `is_target=exclude` とする。
```

### GATT による device_name 取得方針

```md
- GATT による名前取得は、少なくとも一度は対象デバイスと判定できた address のみを対象とする。
- 初回発見から一定秒数以上経過しても `device_name` が未取得の場合に試行する。
- 再試行間隔は `config.json` で設定可能にする。
- 例: `device_name_retry_seconds`
- GATT 接続はスキャン処理と密結合にせず、可能であれば直列実行の専用処理に分離する。
- `handleDiscovery()` の中で毎回直接接続するのではなく、再試行条件を満たした対象のみを順次処理する。
- 成功時は `device_name` を更新し、失敗時は `last_gatt_name_attempt_timestamp` と `last_gatt_name_error` を更新する。
```

### config.json の扱い

```md
- `config.json` のセンサー定義における `name` は、今回の方針では必須とはしない。
- ただし即時削除はせず、後方互換のため当面は optional override として残す方が安全である。
- 監視対象の特定には `mac` / `address` を引き続き利用する。
- GATT 名取得が十分安定してから、`name` を廃止するかどうかを別途判断する。
```

### Prometheus メトリクス方針

```md
- 温度・湿度・電池残量などの測定値メトリクスでは、可変な `sensor_name` をラベルに使用しない。
- 測定値メトリクスの識別子は `address` を用いる。
- これにより、デバイス名が後から取得・変更された場合でも、Prometheus 上の時系列分裂を避ける。
- 人間向けの名前は別メトリクス `thexporter_sensor_info` で公開する。
- 例:
  - `thexporter_temperature_celsius{address="AA:BB:CC:DD:EE:FF"} 23.4`
  - `thexporter_sensor_info{address="AA:BB:CC:DD:EE:FF",sensor_name="Living Room"} 1`
- `sensor_name` が未取得の間は `thexporter_sensor_info` を出さない。
- `/` の JSON ステータスでも `device_name` を返し、人間が確認しやすいようにする。
```

### 実装対象ファイルの目安

```md
- `src/thexporter/scanthread.py`
  - `handleDiscovery()` の先頭で adtype 8/9 を回収する処理を追加する。
  - PVVX 判定後に対象デバイス状態と `SensorReading` を更新する。
- `src/thexporter/scandata.py`
  - 発見済みデバイス状態を保持するデータ構造と更新メソッドを追加する。
- `src/thexporter/config.py`
  - `device_name_retry_seconds` などの設定値を追加する。
- `src/thexporter/metric_builder.py`
  - 測定値メトリクスから `sensor_name` ラベルを外す。
  - `thexporter_sensor_info` を追加する。
- `src/thexporter/controller/status.py`
  - デバイス状態の `device_name` を JSON に含める。
- `README.md`
  - 名前解決順序、GATT フォールバック、Prometheus ラベル方針を更新する。
```

### 注意点

```md
- `extract_pvvx_service_data()` の中に adtype 8/9 の処理は入れない。
  - この関数は PVVX service data 抽出に責務を限定したままにする。
- `SensorReading.name` のみで発見済みデバイス状態を表現しようとしない。
  - 名前だけの広告を保持できない
  - `is_target` や GATT 再試行状態を持てない
  - 読み取り値キャッシュと discovery 状態の責務が混ざる
- スキャンと GATT 接続の同時実行は BLE アダプタの状態に影響する可能性があるため、実機で安定性確認を行う。
```
