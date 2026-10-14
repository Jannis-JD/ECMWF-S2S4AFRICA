"""Download plot images from the public bucket into prompts/plot_descriptions/images/ (gitignored).

Usage (from the repo root or this folder):
    python prompts/plot_descriptions/fetch_images.py                      # every image in descriptions.jsonl
    python prompts/plot_descriptions/fetch_images.py --dates 2026-09-05 --plots weekly_precip,efi_sot_precip
        # Kenya weekly plots for those dates (use --source briefing for plots/briefing/<date>/)

Images are saved as images/<source>_<date>_<plot>.png, the same key the batches use.
Missing objects (HTTP 404) are reported and skipped.
"""
import argparse
import json
import os
import urllib.error
import urllib.request

BUCKET_URL = "https://storage.googleapis.com/africa-forecasting-data"
here = os.path.dirname(os.path.abspath(__file__))
image_dir = os.path.join(here, "images")


def image_url(source, date, plot):
    if source == "Kenya":
        return f"{BUCKET_URL}/plots/Kenya/{date}/weekly/{plot}.png"
    return f"{BUCKET_URL}/plots/briefing/{date}/{plot}.png"


def fetch(key, url):
    path = os.path.join(image_dir, f"{key}.png")
    if os.path.exists(path):
        return path
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
    except urllib.error.HTTPError as e:
        print(f"missing ({e.code}): {url}")
        return None
    with open(path, "wb") as f:
        f.write(data)
    print(f"fetched {key}")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", help="comma-separated dates; default: every record in descriptions.jsonl")
    parser.add_argument("--plots", help="comma-separated plot names (without .png)")
    parser.add_argument("--source", default="Kenya", choices=["Kenya", "briefing"])
    args = parser.parse_args()
    os.makedirs(image_dir, exist_ok=True)

    if args.dates:
        for date in args.dates.split(","):
            for plot in args.plots.split(","):
                fetch(f"{args.source}_{date}_{plot}", image_url(args.source, date, plot))
    else:
        with open(os.path.join(here, "descriptions.jsonl"), encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                fetch(record["id"], record["image_url"])
