#!/usr/bin/env python3
"""Download embedding model + tokenizer + Tesseract traineddata into assets."""
import os, sys, urllib.request
ASSETS = os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "assets")
os.makedirs(ASSETS, exist_ok=True)
print("download_models: placeholder runner; configure URLs in AppConfig.")
print("OK")
