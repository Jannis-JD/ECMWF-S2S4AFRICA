"""Try cheap captioning models against the reference captions in descriptions.jsonl.

Two steps, run from this folder:

    python caption_eval.py generate --model gemini:gemini-3.1-flash-lite --prompt baseline
    python caption_eval.py judge --runs runs/test/*.jsonl
    python caption_eval.py report

generate  captions every test image (see TEST_DATES) with one model and one prompt variant and
          writes runs/test/<model>__<prompt>.jsonl. Backends:
            gemini:<model id>  Gemini API (GOOGLE_API_KEY, from the env or test/.env);
                               this also serves the open-weights Gemma models (gemma-4-...)
            claude:<alias>     the `claude` CLI (haiku, sonnet, ...), using your Claude login
judge     asks Opus (through the `claude` CLI) to score every candidate caption of an image at
          once, blind and in random order, against the image and the reference caption, and
          writes runs/test/judgements.jsonl (images already judged for a run are skipped).
report    prints the mean scores per run, plus rule checks that need no judge.

Prompt variants (see PROMPTS) build on prompts/image_caption_prompt.md, the system prompt
ai_weather_briefing_from_images.py uses in production. Few-shot examples only come from
dates outside TEST_DATES. Images are fetched with fetch_images.py.
"""
import argparse
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")  # captions contain minus signs the Windows console can't print

here = os.path.dirname(os.path.abspath(__file__))
repo = os.path.dirname(os.path.dirname(here))
image_dir = os.path.join(here, "images")
run_dir = os.path.join(here, "runs", "test")

# Held out from few-shot examples: one date in each of the three seasons the 8 slide plots
# have full coverage for.
TEST_DATES = {"2026-06-28", "2026-08-28", "2026-10-05"}
# The 8 Kenya plots ai_weather_briefing_from_images.py captions every day.
SLIDE_PLOTS = {
    "weekly_precip": "ECMWF S2S weekly precipitation forecast",
    "gefs_weekly_precip": "GEFS weekly precipitation forecast",
    "weekly_precip_downscaled": "downscaled ECMWF precipitation forecast",
    "weekly_medium_range_precip": "medium-range ECMWF precipitation forecast",
    "chance_of_above_or_below": "tercile balance (above/below normal)",
    "efi_sot_precip": "extreme forecast index (EFI)",
    "50th_percentile_exedance": "probability of exceeding the median (p50 exceedance)",
    "anomaly_from_50th": "ensemble mean anomaly (p50anom)",
}

# How to read each plot, for the variants that add per-plot guidance. Kept short: these are
# facts about the plot, the caption rules stay in the shared prompt.
PLOT_GUIDE = {
    "weekly_precip": "Weekly ensemble-mean total precipitation from ECMWF S2S on a coarse 1.5 degree grid, one panel per week. The colorbar maximum changes from day to day, so read the numbers off this colorbar.",
    "gefs_weekly_precip": "Weekly ensemble-mean total precipitation from NOAA GEFS, one panel per week (often 5 weeks). The colorbar maximum changes from day to day. Heavy rain at the top edge of the map is usually in southern Ethiopia, not Kenya.",
    "weekly_precip_downscaled": "Weekly total precipitation from ECMWF downscaled to a fine grid, one panel per week. Point out where the maxima are (often the west near Lake Victoria, the central highlands just south of the equator, and the coast) and where it stays dry (usually the northwest).",
    "weekly_medium_range_precip": "Weekly total precipitation from the ECMWF medium-range ensemble, only two panels (week 1 and week 2). The colorbar maximum changes from day to day, so read the numbers off this colorbar.",
    "chance_of_above_or_below": "Tercile balance: P(above normal) minus P(below normal), in percentage points from -100 to +100. Teal/green = above normal favoured, brown = below normal favoured, white = no lean. Report it as points (for example +75 to +100 points), never as a probability.",
    "efi_sot_precip": "Extreme Forecast Index for weekly precipitation, shaded only from 0.5 (white) to 1.0 (red), with black Shift of Tails contours. Unshaded panels mean no wet-extreme signal. Say where and in which weeks the EFI is shaded, with its value range, and whether SOT contours sit on it. Many forecasts have little or no signal; then say so briefly.",
    "50th_percentile_exedance": "Probability that the weekly total exceeds the model-climate median, in fixed bins 0/1/10/25/45/55/75/90/99/100%. Purple and blues are low (drier than normal), light green is 45 to 55% (normal odds), yellow to dark red are high (wetter than normal). Quote the bins, for example 90 to 99%.",
    "anomaly_from_50th": "Ensemble-mean weekly precipitation minus the model-climate median, in mm (kg m**-2). Blue = wetter than the median, red = drier (the colormap is RdBu). The colorbar range changes from day to day, so read the numbers off this colorbar.",
}

PROMPTS = ["baseline", "guided", "fewshot", "fewshot_img", "compact", "twostep"]

TWOSTEP = """First read the image, then write the caption from your readings. Reply with JSON only:
{"colorbar": "<label, minimum and maximum of the colorbar>",
 "weeks": [{"dates": "<panel title>", "west": "<value or range>", "northwest": "...", "north": "...",
            "northeast": "...", "central highlands": "...", "east": "...", "coast": "...", "south": "...",
            "max": "<largest value and where>", "min": "<smallest value and where>"}, ...one per panel],
 "caption": "<the caption, written only from the readings above>"}
Read every panel. Use the latitude/longitude ticks to place values: west = 34E to 35E (Lake Victoria,
Uganda border), northwest = Lake Turkana near 36E 3N to 4N, north = 4N to 5N (Ethiopian border),
northeast/east = toward 41E (Somali border), central highlands = 36.5E to 37.5E near the equator,
coast = east of 39E between 1.5S and 4.5S, south = the Tanzanian border."""


def load_records():
    with open(os.path.join(here, "descriptions.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_records(records):
    return [r for r in records if r["date"] in TEST_DATES and r["plot"] in SLIDE_PLOTS and r["source"] == "Kenya"]


def examples_for(record, records, n):
    """n reference captions of the same plot from non-test dates, spread over the year."""
    pool = sorted((r for r in records if r["plot"] == record["plot"] and r["date"] not in TEST_DATES),
                  key=lambda r: r["date"])
    if len(pool) <= n:
        return pool
    step = len(pool) / n
    return [pool[int(i * step)] for i in range(n)]


def image_path(record):
    return os.path.join(image_dir, f"{record['id']}.png")


def read_file(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def build_prompt(variant, record, records):
    """Return (system prompt, list of user parts); a part is a str or ("image", path)."""
    base = read_file(os.path.join(repo, "prompts", "image_caption_prompt.md"))
    context = f"Context: this is the pipeline's '{SLIDE_PLOTS[record['plot']]}' output for {record['date']}."
    image = ("image", image_path(record))
    if variant == "baseline":
        return base, [image, context]

    guide = f"How to read this plot: {PLOT_GUIDE[record['plot']]}"
    if variant == "guided":
        return base, [image, context + "\n" + guide]

    if variant == "twostep":
        system = read_file(os.path.join(repo, "prompts", "image_caption_prompt_compact.md"))
        examples = examples_for(record, records, 3)
        shots = "\n\n".join(f"Example caption ({e['date']}):\n{e['description']}" for e in examples)
        return system, [image, f"{context}\n{guide}\n\nReference captions of this plot type from other dates, "
                               f"showing the expected style, length and level of detail. Their numbers and "
                               f"places do not apply to this image:\n\n{shots}\n\n{TWOSTEP}"]

    if variant == "compact":
        system = read_file(os.path.join(repo, "prompts", "image_caption_prompt_compact.md"))
        examples = examples_for(record, records, 3)
        shots = "\n\n".join(f"Example ({e['date']}):\n{e['description']}" for e in examples)
        return system, [image, f"{context}\n{guide}\n\nReference captions of this plot type from other dates, "
                               f"showing the expected style, length and level of detail. Their numbers and "
                               f"places do not apply to this image:\n\n{shots}"]

    examples = examples_for(record, records, 3)
    if variant == "fewshot":
        shots = "\n\n".join(f"Example ({e['date']}):\n{e['description']}" for e in examples)
        return base, [image, f"{context}\n{guide}\n\nReference captions of this plot type from other dates, "
                             f"written by an expert. Match their style, length and level of detail, but describe "
                             f"only what this image shows; their numbers and places do not apply to it:\n\n{shots}"]

    if variant == "fewshot_img":
        parts = []
        for e in examples[:2]:
            parts += [("image", image_path(e)), f"Expert caption of the image above ({e['date']}):\n{e['description']}"]
        return base, parts + [f"Now caption this image in the same style. Describe only what it shows.\n{context}\n{guide}", image]
    raise ValueError(variant)


def call_gemini(model, system, parts):
    from google import genai
    from google.genai import types

    if "GOOGLE_API_KEY" not in os.environ:
        env = os.path.join(repo, "test", ".env")
        for line in read_file(env).splitlines():
            if line.startswith("GOOGLE_API_KEY="):
                os.environ["GOOGLE_API_KEY"] = line.split("=", 1)[1].strip()
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    contents = []
    for p in parts:
        if isinstance(p, tuple):
            with open(p[1], "rb") as f:
                contents.append(types.Part.from_bytes(data=f.read(), mime_type="image/png"))
        else:
            contents.append(p)
    # Gemma models on the Gemini API take no system instruction, so it goes first in the turn.
    if model.startswith("gemma"):
        contents = [system] + contents
        config = types.GenerateContentConfig(max_output_tokens=4000)
    else:
        config = types.GenerateContentConfig(system_instruction=system, max_output_tokens=4000)
    for attempt in range(6):
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            return response.text.strip(), response.usage_metadata.model_dump() if response.usage_metadata else None
        except Exception as e:  # rate limits on the free tier: back off and retry
            if attempt == 5 or not re.search(r"429|RESOURCE_EXHAUSTED|503|UNAVAILABLE|500", str(e)):
                raise
            time.sleep(20 * (attempt + 1))


def call_claude(model, system, parts, effort=None):
    """Run the claude CLI headless; images are passed by path and opened with its Read tool."""
    text, n = [], 0
    for p in parts:
        if isinstance(p, tuple):
            n += 1
            text.append(f"[Image {n}: read the file {p[1].replace(os.sep, '/')} with the Read tool]")
        else:
            text.append(p)
    prompt = "\n\n".join(text) + "\n\nOpen the image file(s) with the Read tool, then answer. Output only the caption."
    with tempfile.TemporaryDirectory() as cwd:  # outside the repo, so the repo CLAUDE.md is not loaded
        system_file = os.path.join(cwd, "system.md")
        with open(system_file, "w", encoding="utf-8") as f:
            f.write(system)
        cmd = [shutil.which("claude"), "-p", "--model", model, "--system-prompt-file", system_file,
               "--tools", "Read", "--allowedTools", "Read", "--add-dir", image_dir,
               "--output-format", "json", "--no-session-persistence"]
        if effort:
            cmd += ["--effort", effort]
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                             cwd=cwd, timeout=600)
    if not out.stdout.strip():
        raise RuntimeError(out.stderr.strip()[-500:])
    result = json.loads(out.stdout)
    if result.get("is_error"):
        raise RuntimeError(result.get("result"))
    return result["result"].strip(), {"cost_usd": result.get("total_cost_usd"), "usage": result.get("usage")}


def generate(args):
    records = load_records()
    backend, model = args.model.split(":", 1)
    os.makedirs(run_dir, exist_ok=True)
    out_path = os.path.join(run_dir, f"{backend}-{model}__{args.prompt}.jsonl".replace("/", "_"))
    done = set()
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            done = {json.loads(line)["id"] for line in f}
    todo = [r for r in test_records(records) if r["id"] not in done][: args.limit]
    for record in todo:
        system, parts = build_prompt(args.prompt, record, records)
        t0 = time.time()
        try:
            caption, usage = (call_gemini if backend == "gemini" else call_claude)(model, system, parts)
        except Exception as e:
            print(f"FAILED {record['id']}: {e}")
            continue
        readings = None
        if args.prompt == "twostep":
            try:
                parsed = json.loads(re.search(r"\{.*\}", caption, re.S).group(0))
                readings, caption = parsed, parsed["caption"].strip()
            except Exception as e:
                print(f"FAILED {record['id']}: no JSON caption ({e})")
                continue
        row = {"id": record["id"], "model": args.model, "prompt": args.prompt, "caption": caption, "readings": readings,
               "seconds": round(time.time() - t0, 1), "usage": usage}
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{record['id']} ({row['seconds']}s)\n  {caption}\n")
        if backend == "gemini" and args.sleep:
            time.sleep(args.sleep)


JUDGE_SYSTEM = """You grade captions of weather forecast plots written for professional forecasters.
You get the plot image, a reference caption written by an expert, and several candidate captions.
The image is the ground truth; the reference shows what a good caption covers, but may itself be
slightly off, so check against the image. Grade each candidate on:

- accuracy (1-5): are its numbers, places, dates and weeks consistent with the image? Values are read
  from colour scales, so ranges within about one colour step count as correct. 5 = no errors,
  4 = one small slip, 3 = one clear error or several small ones, 2 = several clear errors,
  1 = mostly wrong or describes the wrong thing (e.g. treats a tercile balance as a probability,
  reads blue as dry on a RdBu precip anomaly, invents a signal on an empty EFI map).
- coverage (1-5): does it give the main pattern and how it changes over the weeks, with values and
  locations, as the reference does? 5 = all the key points, 1 = vague or misses the headline.
- style (1-5): the house rules: 2 to 4 sentences, opens with the meteorological content (never
  "This map/plot shows..."), compass directions or visible features rather than administrative
  names, numbers read off the plot, no em dashes, no hedging or preamble.

List each clear factual error briefly. Reply with JSON only:
{"<candidate label>": {"accuracy": n, "coverage": n, "style": n, "errors": ["..."]}, ...}"""


def judge(args):
    records = {r["id"]: r for r in load_records()}
    runs = {}
    for path in args.runs:
        with open(path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                runs.setdefault(row["id"], []).append(row)
    out_path = os.path.join(run_dir, "judgements.jsonl")
    judged = set()
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                judged.add((row["id"], row["model"], row["prompt"]))
    for image_id, rows in sorted(runs.items()):
        rows = [r for r in rows if (image_id, r["model"], r["prompt"]) not in judged]
        if not rows:
            continue
        random.Random(image_id).shuffle(rows)
        labels = [chr(ord("A") + i) for i in range(len(rows))]
        record = records[image_id]
        candidates = "\n\n".join(f"Candidate {l}:\n{r['caption']}" for l, r in zip(labels, rows))
        parts = [("image", image_path(record)),
                 f"Plot: {SLIDE_PLOTS.get(record['plot'], record['plot'])}, {record['date']}.\n"
                 f"How to read it: {PLOT_GUIDE.get(record['plot'], '')}\n\n"
                 f"Reference caption:\n{record['description']}\n\n{candidates}"]
        try:
            text, _ = call_claude(args.judge_model, JUDGE_SYSTEM, parts)
            scores = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        except Exception as e:
            print(f"FAILED {image_id}: {e}")
            continue
        with open(out_path, "a", encoding="utf-8") as f:
            for label, row in zip(labels, rows):
                s = scores.get(label) or scores.get(f"Candidate {label}") or {}
                f.write(json.dumps({"id": image_id, "model": row["model"], "prompt": row["prompt"],
                                    **{k: s.get(k) for k in ("accuracy", "coverage", "style", "errors")}},
                                   ensure_ascii=False) + "\n")
        print(f"judged {image_id}: {len(rows)} candidates")


def rule_checks(caption):
    sentences = len(re.findall(r"[.!?](\s|$)", caption.strip()))
    return {
        "em_dash": "—" in caption,
        "plot_opening": bool(re.match(r"\s*(this|the)\s+(image|map|plot|figure|diagram|chart)", caption, re.I)),
        "sentences_ok": 2 <= sentences <= 4,
        "words": len(caption.split()),
    }


def report(args):
    stats = {}
    for path in glob.glob(os.path.join(run_dir, "*__*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                s = stats.setdefault((row["model"], row["prompt"]), {"n": 0, "secs": [], "rules": []})
                s["n"] += 1
                s["secs"].append(row["seconds"])
                s["rules"].append(rule_checks(row["caption"]))
    judgements = {}
    path = os.path.join(run_dir, "judgements.jsonl")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                judgements.setdefault((row["model"], row["prompt"]), []).append(row)

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else float("nan")

    print(f"{'model':42} {'prompt':12} {'n':>3} {'judged':>6} {'acc':>5} {'cov':>5} {'style':>5} "
          f"{'errs':>5} {'rules':>6} {'words':>5} {'sec':>5}")
    rows = []
    for key, s in stats.items():
        j = judgements.get(key, [])
        rules_ok = mean([float(not r["em_dash"] and not r["plot_opening"] and r["sentences_ok"]) for r in s["rules"]])
        rows.append((mean([x["accuracy"] for x in j]), key, s, j, rules_ok))
    for acc, key, s, j, rules_ok in sorted(rows, key=lambda r: -(r[0] if r[0] == r[0] else -1)):
        print(f"{key[0]:42} {key[1]:12} {s['n']:>3} {len(j):>6} {acc:5.2f} {mean([x['coverage'] for x in j]):5.2f} "
              f"{mean([x['style'] for x in j]):5.2f} {mean([len(x['errors'] or []) for x in j]):5.2f} "
              f"{rules_ok:6.0%} {mean([r['words'] for r in s['rules']]):5.0f} {mean(s['secs']):5.1f}")
    if args.by_plot:
        print()
        for key in sorted(judgements):
            per_plot = {}
            for x in judgements[key]:
                per_plot.setdefault(records_plot(x["id"]), []).append(x["accuracy"])
            print(key[0], key[1], {p: round(mean(v), 1) for p, v in sorted(per_plot.items())})


def records_plot(image_id):
    return re.match(r"(?:Kenya|briefing)_\d{4}-\d{2}-\d{2}_(.+)", image_id).group(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--model", required=True, help="gemini:<model id> or claude:<alias>")
    g.add_argument("--prompt", default="baseline", choices=PROMPTS)
    g.add_argument("--limit", type=int)
    g.add_argument("--sleep", type=float, default=0, help="seconds between Gemini calls (free-tier rate limits)")
    j = sub.add_parser("judge")
    j.add_argument("--runs", nargs="+", required=True)
    j.add_argument("--judge-model", default="opus")
    r = sub.add_parser("report")
    r.add_argument("--by-plot", action="store_true")
    args = parser.parse_args()
    {"generate": generate, "judge": judge, "report": report}[args.cmd](args)
