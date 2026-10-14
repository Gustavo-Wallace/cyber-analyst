# Cyber Analyst

Local-first Windows desktop application for investigating cybersecurity data in CSV files.

## Overview

Cyber Analyst brings dataset exploration, deterministic analysis and a grounded local AI Analyst into one investigation workspace.

## Main features

- Load CSV datasets, preview rows and search raw values.
- Build investigations with dataset profiling, semantic classification and deterministic analysis.
- Review Dashboard charts, evidence-backed findings and cross-dataset correlations.
- Browse shared identifiers and observed co-occurrence relations.
- Filter and search investigation objects, then navigate to their source evidence.
- Ask the local AI Analyst grounded questions in English or Portuguese.

## Installation / portable usage

The Windows portable build is an **experimental engineering build**, not an officially published release. There is currently no public release download.

If you have the experimental package, keep the entire folder together and run `CyberAnalyst.exe`. The `_internal` directory must remain beside it. Python installation and administrator privileges are not required.

CSV browsing works without local AI. To run an investigation or use AI Analyst, configure an external `llama-server.exe` and a compatible GGUF model in **Settings**, then choose **Apply settings**.

## Basic workflow

1. Open **Data** and add one or more CSV datasets.
2. Configure local AI in **Settings** and apply the configuration.
3. Open **Dashboard** and choose **Analyze**.
4. Review charts, alerts, analyses, identifiers, connections and data matches.
5. Use filters, investigation search or **AI Analyst** to inspect the available evidence.

## Local AI and privacy

Dataset processing and inference run locally. Investigation data is sent to the configured local llama.cpp server on `127.0.0.1`, not an external AI service.

The portable package includes neither llama.cpp nor GGUF models and does not download them automatically. The validated development model is `Qwen3-4B-Q5_K_M.gguf`.

Analytical values come from deterministic processing. AI assists with classification, selection and grounded answers; findings' attention levels are investigation priorities, not vulnerability severity.

## Run from source

Requires Python 3.12 or newer. From the project directory in Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m cyber_analyst
```

## Limitations

- The portable build is unsigned; independent clean-machine Windows compatibility validation is still pending.
- Investigations and manually selected runtime/model paths are session-local and must be loaded or configured again after restarting.
- Correlation uses compatible single-column equality matching; fuzzy and composite-key matching are not supported.
- There is no installer or automatic update mechanism. Third-party redistribution obligations must be resolved before a public release.

## License

Cyber Analyst is licensed under the GNU General Public License version 3 only (`GPL-3.0-only`). See [LICENSE](LICENSE).

Third-party components retain their own licenses. The experimental portable package includes their license notices.
