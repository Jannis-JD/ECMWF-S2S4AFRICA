"""Merge the hand-written caption batches in batches/ into descriptions.jsonl.

Each batch is a JSON object {"<source>_<date>_<plot>": "<caption>"}, where source is
"Kenya" (plots/Kenya/<date>/weekly/<plot>.png) or "briefing" (plots/briefing/<date>/<plot>.png).
Run from this folder: python build_descriptions.py
"""
import glob
import json
import os
import re

BUCKET_URL = "https://storage.googleapis.com/africa-forecasting-data"
here = os.path.dirname(os.path.abspath(__file__))

# plot name pattern -> plot family letter of prompts/image_caption_prompt.md
FAMILIES = [
    (r"efi_sot", "B"),
    (r"percentile_exedance", "C"),
    (r"chance_higherthan", "D"),
    (r"anomaly_from_", "E"),
    (r"chance_of_above_or_below", "F"),
    (r"^chirps_", "J"),
    (r"^tahmo_", "K"),
    (r"_chirps_(verify_5mm|bias|mae)$|week1_mae", "L"),
    (r"^mjo_rmm", "M"),
    (r"^(enso|iod)_", "N"),
    (r"^(itcz|hovmoller_olr|olr_map)", "O"),
    (r"^kenya_ond_|analog_years", "P"),
    (r"precip", "A"),
]


def family(plot):
    return next((letter for pattern, letter in FAMILIES if re.search(pattern, plot)), None)


records = []
for batch in sorted(glob.glob(os.path.join(here, "batches", "*.json"))):
    with open(batch, encoding="utf-8") as f:
        captions = json.load(f)
    for key, caption in captions.items():
        source, date, plot = re.match(r"(Kenya|briefing)_(\d{4}-\d{2}-\d{2})_(.+)", key).groups()
        path = f"plots/Kenya/{date}/weekly/{plot}.png" if source == "Kenya" else f"plots/briefing/{date}/{plot}.png"
        records.append({
            "id": key,
            "source": source,
            "date": date,
            "plot": plot,
            "family": family(plot),
            "image_url": f"{BUCKET_URL}/{path}",
            "description": caption,
        })

records.sort(key=lambda r: (r["plot"], r["date"]))
with open(os.path.join(here, "descriptions.jsonl"), "w", encoding="utf-8") as f:
    for record in records:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

print(f"Wrote {len(records)} descriptions for {len({r['plot'] for r in records})} plot types")
