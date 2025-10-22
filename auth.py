from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt

# --- セキュリティ関連の定数 ---
# 実際のアプリケーションでは、このキーは環境変数などから読み込むべきです
SECRET_KEY = "a_very_secret_key_that_should_be_changed"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# パスワードのハッシュ化と検証を行うためのコンテキストを設定
# scheme="bcrypt" は、ハッシュ化アルゴリズムとしてbcryptを使用することを指定
# deprecated="auto" は、将来的にbcryptが非推奨になった場合に自動的に新しいアルゴリズムに移行することを示す
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    平文のパスワードとハッシュ化されたパスワードを比較し、一致するかどうかを検証する。

    Args:
        plain_password: ユーザーが入力した平文のパスワード。
        hashed_password: データベースに保存されているハッシュ化されたパスワード。

    Returns:
        パスワードが一致する場合はTrue、そうでない場合はFalse。
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    平文のパスワードを受け取り、ハッシュ化されたパスワードを返す。

    Args:
        password: ハッシュ化する平文のパスワード。

    Returns:
        ハッシュ化されたパスワード文字列。
    """
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    与えられたデータを含むアクセストークンを生成する。

    Args:
        data: トークンに含めるデータ（ペイロード）。
        expires_delta: トークンの有効期限を指定する期間。指定しない場合はデフォルト値が使用される。

    Returns:
        エンコードされたアクセストークン文字列。
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
