/* =========================================================
   PALETTE TRY-OUT
========================================================= */
(function () {
    try {
        const fromUrl = new URLSearchParams(window.location.search).get("palette");

        if (fromUrl === "default") {
            localStorage.removeItem("palette");
        } else if (fromUrl) {
            localStorage.setItem("palette", fromUrl);
        }

        const palette = localStorage.getItem("palette");
        if (palette) {
            document.documentElement.setAttribute("data-palette", palette);
        }
    } catch (e) {}
})();

/* =========================================================
   THEME (light / dark)
   Ye functions global hain taaki onclick="toggleNextTheme()" chale
========================================================= */

function getSavedTheme() {
    try {
        return localStorage.getItem("theme") || "light";
    } catch (e) {
        return "light"; // private mode me localStorage fail ho sakta hai
    }
}

function saveTheme(theme) {
    try {
        localStorage.setItem("theme", theme);
    } catch (e) {}
}

function updateThemeButtonIcon(theme) {
    const btn = document.getElementById("themeToggleBtn");
    if (btn) {
        btn.textContent = theme === "dark" ? "☀️" : "🌙";
    }
}

function toggleNextTheme() {
    const current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    const next = current === "dark" ? "light" : "dark";

    document.documentElement.setAttribute("data-theme", next);
    saveTheme(next);
    updateThemeButtonIcon(next);
}

/* =========================================================
   UPLOAD PAGE
========================================================= */
const ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png"];
const MAX_FILE_SIZE_MB = 10;

function analyzeReport() {
    const fileInput = document.getElementById("reportFile");

    if (!fileInput || fileInput.files.length === 0) {
        alert("Please upload your health report first.");
        return;
    }

    const file = fileInput.files[0];

    if (!ALLOWED_TYPES.includes(file.type)) {
        alert("Please upload a PDF, JPG or PNG file.");
        return;
    }

    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
        alert("File is too large. Maximum size is " + MAX_FILE_SIZE_MB + " MB.");
        return;
    }

    window.location.href = "processing.html";
}

/* =========================================================
   ANALYSIS PAGE
========================================================= */
function saveReport() {
    // Abhi sirf placeholder hai. Asli save ke liye Flask route pe fetch/POST karna hoga.
    alert("Report saved successfully!");
}

/* =========================================================
   PAGE LOAD
========================================================= */
document.addEventListener("DOMContentLoaded", function () {

    // ---- Theme restore ----
    const theme = getSavedTheme();
    document.documentElement.setAttribute("data-theme", theme);
    updateThemeButtonIcon(theme);

    // ---- Show selected file name ----
    const reportFile = document.getElementById("reportFile");
    const fileName = document.getElementById("fileName");

    if (reportFile && fileName) {
        reportFile.addEventListener("change", function () {
            fileName.textContent = reportFile.files.length > 0
                ? "Selected File: " + reportFile.files[0].name
                : "";
        });
    }

    // ---- Processing page animation ----
    const steps = document.querySelectorAll(".processing-step");
    const progressBar = document.querySelector(".progress-bar");

    if (steps.length === 0 || !progressBar) return;

    const total = steps.length;

    // HTML me jo step pehle se "active" hai, wahi se shuru karo
    let current = Array.from(steps).findIndex(function (s) {
        return s.classList.contains("active");
    });

    function setState(index, state) {
        const step = steps[index];
        const icon = step.querySelector("span");
        step.classList.remove("active", "completed");

        if (state === "active") {
            step.classList.add("active");
            icon.textContent = "⟳";
        } else if (state === "completed") {
            step.classList.add("completed");
            icon.textContent = "✓";
        }
    }

    // Agar HTML me koi step active nahi hai to pehla step active kar do
    if (current === -1) {
        current = 0;
        setState(0, "active");
    }
    progressBar.style.width = ((current + 1) / total * 100) + "%";

    const interval = setInterval(function () {
        setState(current, "completed");
        current++;

        if (current < total) {
            setState(current, "active");
            progressBar.style.width = ((current + 1) / total * 100) + "%";
        } else {
            clearInterval(interval);
            progressBar.style.width = "100%";

            const title = document.querySelector(".processing-card h1");
            const text = document.querySelector(".processing-text");

            if (title) title.textContent = "Report Processing Completed";
            if (text) text.textContent = "Your report has been processed successfully. Opening your analysis...";

            // Flask template me data-next-url se analysis page ka link milta hai
            const card = document.querySelector(".processing-card");
            const nextUrl = card ? card.dataset.nextUrl : null;

            if (nextUrl) {
                setTimeout(function () {
                    window.location.href = nextUrl;
                }, 1500);
            }
        }
    }, 2000);
});