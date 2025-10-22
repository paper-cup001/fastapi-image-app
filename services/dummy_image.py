# main.py において、test_mode=trueの場合、このコードが利用される。
# 画像の白色部分をユーザーIDに基づく色に置き換えるため、ユーザー端末ごとに背景色が異なるダミー画像ができる。

from PIL import Image
import hashlib
import io

def user_id_to_color(user_short_id):
    # user_short_idからハッシュ値を生成し、RGBに変換
    h = hashlib.md5(user_short_id.encode()).hexdigest()
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return (r, g, b)

def replace_white_with_color(image_path, user_short_id):
    print(user_short_id)
    img = Image.open(image_path).convert("RGB")
    target_color = user_id_to_color(user_short_id)
    pixels = img.load()
    width, height = img.size

    for y in range(height):
        for x in range(width):
            if pixels[x, y] == (255, 255, 255):
                pixels[x, y] = target_color

    # ここでバイナリに変換して返す
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


# 例: 画像を保存したい場合
# img = replace_white_with_color("dummy_image.jpg", "abcd1234")
# img.save("dummy_image_colored.jpg")