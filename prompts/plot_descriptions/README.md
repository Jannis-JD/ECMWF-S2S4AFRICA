# Plot descriptions

Reference captions for the plots that go into the Kenya weather briefing, meant as training or
few-shot material for a cheaper captioning model.

- `descriptions.jsonl`: one record per plot image. Fields: `id`, `source` (`Kenya` for
  `plots/Kenya/<date>/weekly/`, `briefing` for `plots/briefing/<date>/`), `date` (the folder date),
  `plot` (file name without `.png`), `family` (the plot family letter of
  `prompts/image_caption_prompt.md`), `image_url` (the image in the public bucket) and
  `description`.
- `batches/*.json`: the captions as they were written, `{"<source>_<date>_<plot>": "<caption>"}`.
  Add new captions here.
- `build_descriptions.py`: rebuilds `descriptions.jsonl` from the batches.

The images are not stored here, only their bucket URLs.

The captions follow the rules of `prompts/image_caption_prompt.md`: 2 to 4 sentences, opening with
the meteorological content, compass directions instead of administrative names, only numbers that
can be read off the plot, no em dashes. They were written by Claude (Opus) looking at each image and
have not been checked by a forecaster. Values are read from colour scales, so treat them as
approximate.

## Comparing captioning models

`caption_eval.py` captions a held-out test set (the 8 Kenya slide plots on the dates in
`TEST_DATES`) with a cheaper model and has Opus grade the results, blind, against the image and
the reference caption (accuracy, coverage and style, 1 to 5). Images are cached in `images/` by
`fetch_images.py`; outputs and grades go to `runs/` (both gitignored).

```bash
python fetch_images.py
python caption_eval.py generate --model gemini:gemini-3.1-flash-lite --prompt compact
python caption_eval.py generate --model claude:sonnet --prompt compact   # uses your claude login
python caption_eval.py judge --runs runs/test/*__compact.jsonl
python caption_eval.py report
```

Results on 23 test images (October 2026):

| model, prompt | accuracy | coverage | style |
|---|---|---|---|
| Claude Sonnet, compact | 4.30 | 4.87 | 3.26 (too long) |
| Gemma 4 26B, baseline | 3.43 | 2.00 | 2.78 |
| Gemini 3.1 Flash-Lite, compact | 3.30 | 3.26 | 4.57 |
| Gemini 3.1 Flash-Lite, baseline (`prompts/image_caption_prompt.md`) | 3.22 | 2.17 | 3.04 |
| Claude Haiku, compact | 2.30 | 2.83 | 4.35 |

Example captions in the prompt (`compact`, `fewshot`) make the cheap models write like the
reference, but they keep misreading the maps (2 to 3 factual slips per caption); asking them to
tabulate per-region readings first (`twostep`) made accuracy worse. Sonnet was the only model
that read the maps reliably, so `ai_weather_briefing_from_images.py` now captions with Sonnet
(`prompts/image_caption_prompt_compact.md`, the plot guide and three captions from this folder)
and falls back to Flash-Lite. The 90-word limit in the compact prompt was added after these runs.
