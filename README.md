# Health Report Analyzer

A Flask web app that reads a laboratory health report (PDF or image), extracts the values,
and shows a simple analysis, a daily diet plan, daily precautions and a health history trend.
> For general informational purposes only. It does not diagnose any condition or replace
> advice from a qualified healthcare professional.

## Features

- Upload a digital PDF, scanned PDF or photo of a report (OCR with Tesseract)
- Extracts common parameters (CBC, lipid profile, kidney, liver, thyroid, vitamins and more)
- Highlights values outside the reference range
- Time-of-day diet plan and precautions (morning to bedtime) based on the report
- Health history with trend charts across uploaded reports
- Light and dark mode

## Setup

1. Install [Python 3.10+](https://www.python.org/downloads/)
2. Install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (Windows default path:
   `C:\Program Files\Tesseract-OCR\tesseract.exe`)
3. Install the packages:

   ```
   pip install -r requirements.txt
   ```

4. Run the app:

   ```
   python app.py
   ```

5. Open http://127.0.0.1:5000

Optional: set your own secret key before running.

```
set FLASK_SECRET_KEY=your-own-long-random-string
```

## Project structure

```
app.py              Flask routes and report analysis
daily_plan.py       Time-of-day diet and precaution plans
templates/          HTML pages (Jinja)
static/css/         Styles
static/js/          Page scripts
```

## Privacy

Uploaded files are deleted right after text extraction. Analysis history is stored locally in
`report_history.json`, which is excluded from this repository. Do not commit real patient reports.
