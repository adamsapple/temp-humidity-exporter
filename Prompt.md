# thexporter (temperature/humidity exporter)
これは以下のようなプログラムを作るための開発環境だ
- Raspberrypi上で動作するpythonのデーモンプログラム
- bluepyを用いて、温湿度計bluetoothデバイスの情報を取得し、flaskを用いてprometheus形式の出力を行う
  - デバイスはpvvx_形式のアドバタイズデータを出力している 
  
## ルーティング
  -	/     　　動作状態、接続デバイス一覧
  -	/health　 正常動作なら1、違うなら0
  - /metrics  取得したデバイスの温度、湿度、バッテリレベル、電波強度(rssi)をprometheusの形式で出力

## ファイル構成
  - src
    - dustbox 不要なソース。編集、確認不要
    - dustbox2 不要なソース。編集、確認不要
    - thexporter 本プログラムのライブラリ
      - controller/status.py  / の具体の出力処理
      - controller/health.py  /health で必要な、具体の出力処理
      - controller/metrics.py /metrics で必要な、具体の出力処理
      - main.py エントリポイント python -m thexporter  等で利用
      - /device/pvvx.py pvvxタイプのデバイス
      - config.py 設定ファイルを読み込む
      - constants.py 定数類
      - web.py flask周りの記述
      - metrics.py /metrics で必要な、具体の出力処理
      - scanthread.py デバイスを一定周期でscanする
      - scandata.py metrics.py とscanthread.py間での情報受け渡し。
    - test1.py 動作検証用ソース。このコードはraspberrypi上のコンテナ上でbluetoothデバイスの情報を取得し、標準出力へ状態を出力できることが確認できている。
    - thexporter.py エントリポイント。python3 src/thexporter.py  等で利用
  - config.json 起動IP、ポート、ログレベル、scan頻度、受信デバイス名とmacアドレスなどが記載されている

## やってほしいこと。
上記コードは実装が不足しています。
上記の仕様に則って、実装を完了させてほしいです。
作成したソースコードに関数ヘッダと関数説明、複雑な処理のステートメントにもコメントの追加をお願いします。