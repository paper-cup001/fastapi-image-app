# 商品撮影用ウェブアプリ

## 概要

- このウェブアプリは薄型長方形の商品の撮影（ゲームカセット、DVDケース、書籍など）を行う目的で作られました。
- 撮影用治具に対応しており、その治具に商品を置いて撮影すると、トリミングが自動で行われます。
- 撮影者と管理者の役割があり、撮影者はスマートフォンを用いた撮影に集中することができます。
- 管理者はウェブアプリを用いて撮影した画像を管理したり、curlコマンドを用いて画像をダウンロードすることができます。


## 撮影用治具について

本ウェブアプリは、L字型の撮影用治具に対応しています。この治具を用いることで、撮影後に自動でトリミングが適用されます。
なお、治具を使用しなくてもアプリ自体はご利用いただけますが、その場合は自動トリミングは行われません。

    この治具は以下の通り、実用新案登録済です。

    実用新案登録番号：第1234567号（日本）

    主な対応商品：ゲームカセット、DVDケース、文庫本など

治具の詳細に関してはお問い合わせください。

## スクリーンショット

- 撮影者側
- 管理者側




## 前提条件

このアプリは以下の環境で動作します：

- MongoDB（バージョン4.4以上推奨）
- Python 3.9 以上（Python 3.11 にて開発・確認済）
- `pip` で依存ライブラリをインストールできる環境
- `uvicorn` によるFastAPIアプリの実行が可能であること

## 注意事項

### MongoDBバージョンについて

MongoDB 5.0 以降は、AVX命令を必須とするため、旧世代CPUでは動作しない場合があります。  
その場合は MongoDB 4.4 でも動作します。

- 詳細: [MongoDB Hardware Requirements](https://www.mongodb.com/docs/manual/administration/production-notes/#hardware)

### MongoDBの初期設定

db.py ファイル内の `MONGO_URL` 変数を、MongoDBの接続URLに設定してください。

MONGO_URL = "mongodb://localhost:27017" # localhostの部分を環境に応じて変更してください

リレーショナルデータベース（MySQLやPostgreSQL）に慣れている方へ：

    このアプリが使用する image_db データベース、および images コレクション（テーブルに相当）は、アプリが初回にデータを書き込んだ時にMongoDBが自動で作成します

    特別なマイグレーション、初期スクリプト、DDL定義ファイルは不要です

    画像はMongoDBの GridFS を通じて保存され、これに必要な fs.files および fs.chunks も同様に自動作成されます



## セットアップ手順

本アプリケーションを動作させるには、以下のいずれかの方法で環境を構築してください。

### 方法1: Anaconda / Miniconda を利用する場合 (推奨)

Condaを利用することで、Python本体や関連ライブラリを含めた環境を最も確実に再現できます。

1.  **リポジトリをクローンします。**
    ```bash
    git clone https://github.com/yourusername/your-repo.git
    cd your-repo
    ```

2.  **Conda環境を構築します。**
    `documents/environment.yml` ファイルを元に、プロジェクト用の仮想環境 `fastapi_env` を作成します。
    ```bash
    conda env create -f documents/environment.yml
    ```

3.  **作成した環境を有効化します。**
    ```bash
    conda activate fastapi_env
    ```

4.  **アプリケーションを起動します。**
    ```bash
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
    ```

### 方法2: Pip と Venv を利用する場合

Anacondaを利用しない場合は、Python標準の仮想環境機能 `venv` と `pip` を使ってセットアップします。

**注意:** この方法では、`pyzbar` や `opencv` が必要とするPython以外のシステムライブラリが別途必要になる場合があります。お使いのOSに合わせて事前にインストールしてください。

-   **Debian / Ubuntu の場合:**
    `sudo apt-get update && sudo apt-get install -y libzbar0 libgl1-mesa-glx`
-   **Fedora / CentOS の場合:**
    `sudo yum install -y zbar libglvnd-glx`

1.  **リポジトリをクローンします。**
    ```bash
    git clone https://github.com/yourusername/your-repo.git
    cd your-repo
    ```

2.  **Pythonの仮想環境を作成し、有効化します。**
    ```bash
    python -m venv venv
    source venv/bin/activate
    # Windowsの場合は `venv\Scripts\activate`
    ```

3.  **必要なパッケージをインストールします。**
    ```bash
    pip install -r documents/requirements.txt
    ```

4.  **アプリケーションを起動します。**
    ```bash
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
    ```




## 使い方

1. group_idの決定と取得

