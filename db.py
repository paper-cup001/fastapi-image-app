# admin.py, photograper.py, external.pyから、参照するための設定
# 
from pymongo import MongoClient
import gridfs
import os

# MongoDBの接続情報
# Fly.ioのSecretに設定した環境変数 MONGO_URL を読み込む
MONGO_URL = os.environ.get("MONGO_URL")

# 以下のコードは変更しなくても大丈夫です。
client = MongoClient(MONGO_URL)
db = client["image_db"]
collection = db["images"]
fs = gridfs.GridFS(db)