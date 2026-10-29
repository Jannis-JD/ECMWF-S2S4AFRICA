```
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║         .    _.----~~~~~~~7                                                  ║
║             /              ~-..-~~--..--.                                    ║
║       .'.'.'                             `.                                  ║
║         .~         ███████╗██████╗ ███████╗ \                                ║ 
║       .'           ██╔════╝╚════██╗██╔════╝   .                              ║
║   .   (            ███████╗ █████╔╝███████╗    \                             ║ 
║ '.    )            ╚════██║██╔═══╝ ╚════██║     `.                           ║
║   '  (             ███████║███████╗███████║       ~-.                        ║ 
║       \           ╚══════╝╚══════╝╚══════╝            ~-~~7                  ║
║        `.       __.._     F O R  A F R I C A             '                   ║  
║          ~-.--~~     ~--.                              /                     ║
║                         ;                          .-~                       ║
║                         (                        .~                          ║
║                          `.                    .'                            ║
║                            ;                   ;                             ║
║                            `.                  `       _                     ║
║                             )                   )     / )                    ║
║                            (                 _.-'  .-' .'                    ║
║                            `.               (      )   /                     ║
║                              7             _;      < _/                      ║
║                               \           /         ~                        ║ 
║                                \         /                                   ║
║                                 `. __..-'                                    ║
║                                   ~                                          ║ 
╚══════════════════════════════════════════════════════════════════════════════╝
```

ECMWF subseasonal forecast plots for **9 African countries**,
updated automatically every day at **00:16 UTC**.

---

### Countries covered

`Angola` · `Botswana` · `Ethiopia` · `Ghana` · `Kenya`
`Madagascar` · `Namibia` · `Senegal` · `Zambia`

---

### Plot types

All plots are stored in the [`/plots`](./plots) folder, organised by country.

| # | Type | Description |
|---|------|-------------|
| i | **Accumulated precipitation** | Weekly, dekadal, and monthly totals; includes change in weekly accumulated precipitation |
| ii | **Exceedance percentages** | Percentage of ensemble members exceeding the 25th, 50th, or 75th climatological quantile |
| iii | **Anomalies** | Forecast deviation from climatological percentiles in mm |
| iv | **Tercile probabilities** | Probability of the forecast falling in the below-normal, near-normal, or above-normal category |
| v | **Meteograms** | Ensemble precipitation vs. climatology for the two most populated cities |
| vi | **Extreme Forecast Index (EFI)** | Weekly EFI with Shift of Tails (SoT) as contours |

---

### Update schedule

Plots are regenerated daily via GitHub Actions. 

![last update](https://img.shields.io/github/last-commit/alecjong-lab/ECMWF-S2S4AFRICA?label=last%20update)

---

### Data source

Forecast data from [ECMWF](https://www.ecmwf.int/) subseasonal ensemble products.

Medium-range forecast downloads use the [ECMWF Open Data portal](https://data.ecmwf.int/forecasts/)
through the `ecmwf-opendata` Python client. The downloaded ECMWF Open Data is provided under
the ECMWF Open Data Terms of Use and requires attribution under the [CC BY 4.0 licence](https://creativecommons.org/licenses/by/4.0/).

A dedicated two-week total-precipitation test is available at [`test_medium_range_total_precipitation.py`](./test_medium_range_total_precipitation.py). It uses the normal `ecmwf-opendata` client workflow, requests only deterministic cumulative `tp` at 24-hour steps from 24 to 336 hours, and writes to `data/medium_range_test/` without invoking the broader S2S or satellite workflows.
