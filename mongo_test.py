from pymongo import MongoClient

try:
    client = MongoClient("mongodb://192.168.100.132:27017", serverSelectionTimeoutMS=2000)
    db = client["test_db"]
    db.test_collection.insert_one({"test": "ok"})
    print("✅ MongoDB接続成功 & テストデータ登録成功")
except Exception as e:
    print("❌ 接続失敗:", e)
