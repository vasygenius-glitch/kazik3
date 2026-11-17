import os
import sys
import shutil
import urllib.request
import zipfile
from PIL import Image

ASSETS_ZIP_URL = "https://github.com/vasygenius-glitch/kazik3/releases/download/v2.0-cards-assets/cards_assets_opt.zip"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS_DIR = os.path.join(BASE_DIR, "assets", "cards")
PIGS_DIR = os.path.join(CARDS_DIR, "guinea_pigs")


def prepare_cards():
    os.makedirs(PIGS_DIR, exist_ok=True)
    existing_jpg = [
        f for f in os.listdir(PIGS_DIR)
        if f.startswith("pig_") and f.endswith(".jpg")
    ]
    if len(existing_jpg) >= 200:
        print(f"[prepare_cards] All {len(existing_jpg)} card images are already present in {PIGS_DIR}.")
        return

    tmp_zip = os.path.join(CARDS_DIR, "_tmp_cards.zip")
    print(f"[prepare_cards] Downloading cards package from {ASSETS_ZIP_URL}...")
    req = urllib.request.Request(
        ASSETS_ZIP_URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp, open(tmp_zip, "wb") as out_f:
        shutil.copyfileobj(resp, out_f)

    print(f"[prepare_cards] Extracting and optimizing 200 card images...")
    with zipfile.ZipFile(tmp_zip, "r") as z:
        for item in z.infolist():
            if not item.filename.endswith(".webp"):
                continue
            base = os.path.splitext(item.filename)[0]
            webp_path = os.path.join(PIGS_DIR, item.filename)
            jpg_path = os.path.join(PIGS_DIR, f"{base}.jpg")

            with open(webp_path, "wb") as f:
                f.write(z.read(item))

            try:
                with Image.open(webp_path) as im:
                    w, h = im.size
                    max_dim = 800
                    if max(w, h) > max_dim:
                        scale = max_dim / max(w, h)
                        im = im.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
                    im.convert("RGB").save(jpg_path, "JPEG", quality=82, optimize=True)
            finally:
                if os.path.exists(webp_path):
                    os.remove(webp_path)

    if os.path.exists(tmp_zip):
        os.remove(tmp_zip)

    final_count = len([f for f in os.listdir(PIGS_DIR) if f.startswith("pig_") and f.endswith(".jpg")])
    print(f"[prepare_cards] Done! Ready {final_count} card images in {PIGS_DIR}.")


if __name__ == "__main__":
    prepare_cards()
