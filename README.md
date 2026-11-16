# 🏥 Health Report Analyzer

A Flask-based web application designed to help users understand their health reports through report analysis, personalized diet guidance, precautions, and health monitoring.

## 📌 About the Project

**Health Report Analyzer** is a web-based healthcare assistance project that allows users to upload their health reports and understand important health parameters in a simple and user-friendly way.

The application provides report analysis, dietary guidance, health precautions, and historical health tracking through an interactive dashboard.

## ✨ Features

- 📄 **Report Upload:** Upload health reports for processing and analysis.
- 🔍 **Report Analysis:** Extract and understand important health parameters.
- 🥗 **Diet Guidance:** Get diet-related suggestions based on report analysis.
- 🛡️ **Health Precautions:** View relevant precautions and recommendations.
- 📊 **Health Trends:** Monitor and compare previously recorded health data.
- 📅 **Daily Diet Plan:** View a structured daily diet routine.
- 📁 **Report History:** Maintain a history of previously processed reports.
- 💻 **Responsive Interface:** User-friendly web interface.

## 🛠️ Technologies Used

| Technology | Purpose |
|---|---|
| Python | Backend programming |
| Flask | Web framework |
| HTML5 | Page structure |
| CSS3 | Styling and layout |
| JavaScript | Frontend interactions |
| PyPDF | PDF text extraction |
| PyMuPDF | PDF processing |
| Tesseract OCR | Text extraction from scanned reports |
| SQLite / JSON | Data storage |

## 📂 Project Structure

```text
health-report-analyzer/
│
├── app.py
├── daily_plan.py
├── requirements.txt
├── README.md
├── .gitignore
│
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── script.js
│
└── templates/
    ├── _day_plan.html
    ├── analysis.html
    ├── diet.html
    ├── index.html
    ├── precautions.html
    ├── processing.html
    ├── trends.html
    └── upload.html
```

## ⚙️ Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/raosahab05/health-report-analyzer.git
```

### 2. Navigate to Project Directory

```bash
cd health-report-analyzer
```

### 3. Create a Virtual Environment

```bash
python -m venv venv
```

### 4. Activate Virtual Environment

**Windows PowerShell:**

```powershell
.\venv\Scripts\Activate.ps1
```

### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

### 6. Run the Application

```bash
python app.py
```

### 7. Open in Browser

```text
http://127.0.0.1:5000
```

## 🔮 Future Improvements

- AI-powered health report explanations.
- Improved health parameter detection.
- Advanced health trend visualization.
- Enhanced report comparison.
- More personalized diet recommendations.

## ⚠️ Disclaimer

This project is developed for educational purposes. It is not a substitute for professional medical advice, diagnosis, or treatment. Users should consult qualified healthcare professionals for medical decisions.

## 👨‍💻 Developer

**Yuvraj Yadav**

- GitHub: [@raosahab05](https://github.com/raosahab05)
- Project: [Health Report Analyzer](https://github.com/raosahab05/health-report-analyzer)

---

⭐ If you find this project interesting, consider giving it a star!