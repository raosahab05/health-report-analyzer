"""
daily_plan.py
Builds a time-of-day diet plan and precaution plan from analysed report parameters.
General educational guidance only, not a medical prescription.
"""


def do(text):
    return {"text": text, "kind": "do"}


def avoid(text):
    return {"text": text, "kind": "avoid"}


# key, label, time range, icon
SLOTS = [
    ("morning", "Morning", "6:30 – 9:00 AM", "🌅"),
    ("afternoon", "Afternoon", "12:30 – 2:30 PM", "☀️"),
    ("evening", "Evening", "4:30 – 6:30 PM", "🌇"),
    ("night", "Night", "7:30 – 9:00 PM", "🌙"),
    ("bedtime", "Bedtime", "9:30 – 10:30 PM", "😴"),
]

DIET_TITLES = {
    "morning": ("Breakfast", "Start with water, then a proper breakfast"),
    "afternoon": ("Lunch", "Your main meal of the day"),
    "evening": ("Evening snack", "Something light around tea time"),
    "night": ("Dinner", "Lighter than lunch, and not too late"),
    "bedtime": ("Before bed", "Keep it simple and let the body settle"),
}

CARE_TITLES = {
    "morning": ("Start the day right", "Habits to build into your morning"),
    "afternoon": ("Through the day", "Small things that add up"),
    "evening": ("Stay active", "Movement and things to avoid"),
    "night": ("Wind down", "Ease off for the day"),
    "bedtime": ("Before sleep", "Rest and keep track of how you feel"),
}

BASE_DIET = {
    "morning": [
        do("Start with a glass of plain water."),
        do("Breakfast: vegetable poha, upma, besan chilla or oats, with a protein side such as curd, sprouts, paneer or an egg if you eat them."),
        do("Add one seasonal fruit."),
    ],
    "afternoon": [
        do("Lunch: 2 whole-grain rotis (or a small bowl of rice) with a bowl of dal, one cooked vegetable and a fresh salad."),
        do("A small bowl of curd or a glass of buttermilk, if it suits you."),
        do("Keep a water bottle within reach and sip through the day."),
    ],
    "evening": [
        do("A fruit, some roasted chana or a small handful of nuts."),
        avoid("Keep fried and packaged snacks (namkeen, samosa, biscuits) occasional."),
    ],
    "night": [
        do("Dinner: something light, such as vegetable dal, khichdi or 1–2 rotis with sabzi."),
        do("Finish dinner 2–3 hours before you go to bed."),
    ],
    "bedtime": [
        do("Sip water if you are thirsty, but not a large amount right before sleeping."),
        avoid("Avoid late-night snacking and heavy or sweet foods close to bedtime."),
    ],
}

BASE_CARE = {
    "morning": [
        do("Wake up at a regular time and drink water."),
        do("Do light stretching or a 15–20 minute walk, as suits you."),
        do("Take any medicines your doctor has prescribed at their usual time."),
    ],
    "afternoon": [
        do("Don't skip meals; keep lunch at a regular time."),
        do("If you sit for long, stand up and walk for a couple of minutes every hour."),
    ],
    "evening": [
        do("Fit in about 30 minutes of activity such as brisk walking, yoga or cycling, as suits you."),
        avoid("Avoid smoking and tobacco, and keep alcohol out or minimal."),
    ],
    "night": [
        do("Keep dinner light and early."),
        do("Note any new symptoms (tiredness, pain, dizziness, fever) so you can tell your doctor."),
    ],
    "bedtime": [
        do("Sleep 7–8 hours, at a regular time."),
        do("Keep screens away for 30 minutes before bed."),
        do("Keep your latest reports and medicine list handy for your next doctor visit."),
    ],
}

# Ordered roughly by how important it is to see a doctor.
CONDITIONS = {
    "platelet": {
        "label": "Low platelets",
        "diet": {
            "morning": [do("Stay well hydrated through the day with water, coconut water or clear soups.")],
            "afternoon": [do("Include folate, B12, iron and vitamin C: dal, leafy greens and citrus fruit.")],
            "evening": [avoid("Avoid alcohol.")],
        },
        "care": {
            "morning": [avoid("Avoid contact sports and activities with a risk of injury or falls.")],
            "afternoon": [avoid("Avoid aspirin and ibuprofen-type painkillers unless your doctor approves.")],
            "evening": [do("Use a soft toothbrush and be careful with sharp tools.")],
            "bedtime": [do("Get a repeat platelet count when your doctor advises.")],
        },
        "notes": ["Low platelets need a doctor's evaluation to find the cause; don't wait for them to improve on their own."],
        "signs": ["Bleeding gums, nosebleeds, or bruises that appear easily", "Black stools, blood in urine, or a severe headache"],
    },
    "kidney": {
        "label": "Kidney markers",
        "diet": {
            "morning": [do("Keep meals simple and balanced; don't start a high-protein diet or supplements on your own.")],
            "afternoon": [do("Follow any fluid, salt or protein limits your doctor has given you; don't set your own.")],
        },
        "care": {
            "morning": [avoid("Avoid over-the-counter painkillers such as ibuprofen or diclofenac unless your doctor approves.")],
            "afternoon": [do("Drink water as your doctor advises; don't cut down or force extra fluids on your own.")],
            "evening": [avoid("Avoid herbal or ayurvedic supplements without checking with your doctor.")],
            "bedtime": [do("Tell your doctor about swelling in the feet or face, or a drop in urine.")],
        },
        "notes": ["Kidney values can shift with hydration and other factors, so a repeat test and your doctor's review matter more than a single result."],
        "signs": ["Swelling of the face or feet, very little urine, or breathlessness"],
    },
    "liver": {
        "label": "Liver markers",
        "diet": {
            "morning": [do("Have a light, home-cooked breakfast such as dalia, oats or poha with fruit.")],
            "afternoon": [do("Keep lunch simple: dal, lightly cooked vegetables and roti; limit oily and spicy restaurant food.")],
            "evening": [do("Choose fruit or coconut water over packaged and fried snacks.")],
            "night": [do("Eat an early, light dinner such as khichdi or vegetable dal.")],
        },
        "care": {
            "morning": [avoid("Avoid alcohol completely.")],
            "afternoon": [avoid("Avoid unprescribed medicines, herbal remedies and protein supplements.")],
            "bedtime": [do("Ask your doctor whether a repeat liver test is needed.")],
        },
        "notes": [],
        "signs": ["Yellow eyes or skin, dark urine, or pale stools", "Severe abdominal pain or persistent vomiting"],
    },
    "sugar": {
        "label": "Blood sugar",
        "diet": {
            "morning": [do("Choose oats, vegetable poha or besan chilla with protein instead of white bread, sweetened cereal or sugary tea.")],
            "afternoon": [do("Fill half the plate with vegetables, add dal, and keep the roti or rice portion moderate.")],
            "evening": [do("Pick whole fruit, roasted chana or nuts instead of biscuits, sweets or namkeen.")],
            "night": [do("Keep dinner lighter than lunch and skip dessert.")],
            "bedtime": [avoid("Avoid sugary drinks or sweets before bed.")],
        },
        "care": {
            "morning": [do("If your doctor asked you to monitor sugar, check at the times they suggested and note the readings.")],
            "afternoon": [do("Take a 10–15 minute walk after lunch.")],
            "night": [do("A short walk after dinner also helps.")],
            "bedtime": [do("Tell your doctor if you notice unusual thirst, frequent urination, blurred vision or slow-healing wounds.")],
        },
        "notes": ["If you take medicine for blood sugar, don't change it or skip meals on your own; ask your doctor first."],
        "signs": ["Very high thirst, frequent urination or blurred vision", "Confusion, extreme weakness or fainting"],
    },
    "hb_low": {
        "label": "Low hemoglobin",
        "diet": {
            "morning": [do("Make breakfast iron-rich: sprouts, poha with peanuts or a fortified cereal, with a vitamin-C fruit such as orange or guava.")],
            "afternoon": [do("Have dal, rajma or chana with leafy greens such as palak or methi, plus a lemon or tomato salad.")],
            "evening": [avoid("Keep tea and coffee at least an hour away from meals; they reduce iron absorption.")],
            "night": [do("Include dal or legumes with a green vegetable.")],
        },
        "care": {
            "morning": [do("Notice tiredness, dizziness, breathlessness or pale skin, and tell your doctor if they persist.")],
            "evening": [do("If you feel dizzy or breathless, go easy on exercise and rest.")],
            "bedtime": [avoid("Don't start iron tablets on your own; ask your doctor for the right dose and duration.")],
        },
        "notes": ["Low hemoglobin that doesn't improve should be checked by a doctor to find the cause."],
        "signs": ["Chest pain, fainting or severe breathlessness", "Black or bloody stools"],
    },
    "thyroid": {
        "label": "Thyroid marker",
        "diet": {
            "morning": [do("Ask your doctor whether tea, coffee, calcium or iron should be spaced away from your thyroid medicine, if you take one.")],
            "afternoon": [do("Eat balanced meals with protein, whole grains, nuts and seeds; use iodised salt in normal amounts.")],
            "night": [avoid("Don't start iodine or kelp supplements without medical advice.")],
        },
        "care": {
            "morning": [do("Take thyroid medicine, if prescribed, at the same time every day.")],
            "bedtime": [do("Tell your doctor about palpitations, tremors, unusual weight change, or feeling too hot or too cold.")],
        },
        "notes": [],
        "signs": ["Racing heartbeat, chest pain or marked breathlessness"],
    },
    "cholesterol": {
        "label": "Cholesterol / LDL",
        "diet": {
            "morning": [do("Add oats, or a few soaked almonds or walnuts.")],
            "afternoon": [do("Raise fibre with dal, beans and vegetables; keep ghee, butter and cream small.")],
            "evening": [do("Have a fruit or unsalted nuts instead of fried snacks.")],
            "night": [avoid("Go easy on fried food and rich, creamy gravies at dinner.")],
        },
        "care": {
            "evening": [do("Aim for regular brisk walking or other aerobic activity.")],
            "bedtime": [do("Ask your doctor how often to repeat a lipid test.")],
        },
        "notes": [],
        "signs": ["Chest pain or pressure, or pain spreading to the arm or jaw: get emergency help"],
    },
    "triglycerides": {
        "label": "Triglycerides",
        "diet": {
            "morning": [avoid("Skip sugary drinks and packaged fruit juices.")],
            "afternoon": [do("Prefer boiled, steamed or lightly sautéed dishes over deep-fried ones, and measure the cooking oil.")],
            "evening": [do("Choose a fruit or roasted snack over fried snacks.")],
            "night": [do("Keep white rice, maida and sweets small at dinner.")],
        },
        "care": {
            "evening": [do("Regular aerobic activity helps bring triglycerides down.")],
            "night": [avoid("Avoid alcohol; it can raise triglycerides.")],
        },
        "notes": [],
        "signs": ["Severe, persistent pain in the upper abdomen"],
    },
    "hdl_low": {
        "label": "Low HDL",
        "diet": {
            "morning": [do("Add a small portion of walnuts, almonds or flaxseed.")],
            "night": [avoid("Avoid vanaspati and re-used frying oil.")],
        },
        "care": {
            "evening": [do("Regular brisk walking or other aerobic exercise helps raise HDL.")],
        },
        "notes": [],
        "signs": [],
    },
    "uric": {
        "label": "Uric acid",
        "diet": {
            "morning": [do("Drink water regularly through the day, unless you've been told to limit fluids.")],
            "afternoon": [do("Keep meals balanced; ask your doctor which foods to limit rather than cutting out whole food groups.")],
            "evening": [avoid("Skip sweetened soft drinks and alcohol, especially beer.")],
        },
        "care": {
            "afternoon": [do("Aim for steady, healthy weight; avoid crash diets and long fasts.")],
            "bedtime": [do("Tell your doctor promptly about sudden painful, red, swollen joints.")],
        },
        "notes": [],
        "signs": ["Sudden severe pain, redness or swelling in a joint"],
    },
    "crp": {
        "label": "Inflammation (CRP)",
        "diet": {
            "morning": [do("Add colourful fruit such as papaya, orange or berries, and a few nuts or seeds.")],
            "afternoon": [do("Fill the plate with vegetables; turmeric and ginger in regular cooking is fine.")],
            "evening": [avoid("Skip sugary drinks and packaged snacks.")],
        },
        "care": {
            "morning": [do("Note symptoms such as fever, pain or swelling, and when they started.")],
            "night": [do("See your doctor if fever or pain lasts more than a few days; CRP rises for many reasons.")],
            "bedtime": [do("Get enough rest; sleep supports recovery.")],
        },
        "notes": [],
        "signs": ["Fever that lasts more than 2–3 days", "Pain or swelling that keeps getting worse"],
    },
    "b12": {
        "label": "Low vitamin B12",
        "diet": {
            "morning": [do("Include milk, curd or fortified foods, or an egg if you eat them.")],
            "afternoon": [do("Add curd or paneer to lunch; fish or chicken if you are non-vegetarian.")],
        },
        "care": {
            "bedtime": [do("Ask your doctor whether you need a B12 supplement and for how long.")],
        },
        "notes": ["Food alone may not correct low B12; many people need a supplement or injection prescribed by a doctor."],
        "signs": ["Numbness or tingling in the hands and feet, or trouble with balance"],
    },
    "vitd": {
        "label": "Low vitamin D",
        "diet": {
            "morning": [do("Include fortified milk or an egg if you eat them.")],
            "afternoon": [do("Add vitamin-D sources such as fortified foods or fatty fish, if suitable for you.")],
        },
        "care": {
            "morning": [do("Spend some time in gentle morning sunlight with arms and face uncovered, as your doctor advises.")],
            "bedtime": [do("Ask your doctor about a vitamin D dose; don't self-dose.")],
        },
        "notes": ["Vitamin D doses are individual; follow your doctor's advice rather than a general dose."],
        "signs": ["Persistent bone pain or muscle weakness"],
    },
    "homocysteine": {
        "label": "Homocysteine",
        "diet": {
            "morning": [do("Include milk, curd, fortified foods or an egg (B12 sources) if they suit you.")],
            "afternoon": [do("Add folate-rich foods: leafy greens, dal and other legumes.")],
        },
        "care": {
            "evening": [avoid("Avoid smoking, and keep up regular activity.")],
        },
        "notes": ["Ask your doctor whether B12 and folate levels should be checked."],
        "signs": [],
    },
}

GENERAL_SIGNS = [
    "Chest pain, severe breathlessness or fainting: get emergency help right away",
    "Any new symptom that is severe, or keeps getting worse",
]

ATTENTION = {
    "High", "Very High", "Low", "Deficient", "Insufficient",
    "Borderline High", "Prediabetes Range", "Above Optimal",
}
HIGH = {"High", "Very High"}


def detect_conditions(parameter_analysis):
    """Return {condition_key: ["Hemoglobin: Low", ...]} for out-of-range parameters."""
    found = {}

    def flag(key, name, status):
        found.setdefault(key, []).append(f"{name}: {status}")

    for name, parameter in (parameter_analysis or {}).items():
        if not isinstance(parameter, dict):
            continue

        status = str(parameter.get("status", "")).strip()
        if status not in ATTENTION:
            continue

        n = name.lower().strip()

        if ("hba1c" in n or "glucose" in n or "blood sugar" in n) and status in HIGH | {"Prediabetes Range"}:
            flag("sugar", name, status)
        if "triglyceride" in n and status in HIGH | {"Borderline High"}:
            flag("triglycerides", name, status)
        if (n in {"total cholesterol", "cholesterol"} or "ldl cholesterol" in n or "non-hdl" in n) \
                and status in HIGH | {"Borderline High", "Above Optimal"}:
            flag("cholesterol", name, status)
        if "hdl cholesterol" in n and status == "Low":
            flag("hdl_low", name, status)
        if "hemoglobin" in n and "a1c" not in n and status == "Low":
            flag("hb_low", name, status)
        if "b12" in n and status in {"Low", "Deficient"}:
            flag("b12", name, status)
        if "vitamin d" in n and status in {"Low", "Deficient", "Insufficient"}:
            flag("vitd", name, status)
        if "uric acid" in n and status in HIGH:
            flag("uric", name, status)
        if "homocysteine" in n and status in HIGH:
            flag("homocysteine", name, status)
        if (n == "bun" or any(t in n for t in ("creatinine", "urea", "egfr"))) and status in HIGH | {"Low"}:
            flag("kidney", name, status)
        if (n in {"sgot", "sgpt", "ast", "alt"} or "bilirubin" in n) and status in HIGH:
            flag("liver", name, status)
        if (n == "crp" or "c-reactive" in n) and status in HIGH:
            flag("crp", name, status)
        if "platelet" in n and status == "Low":
            flag("platelet", name, status)
        if n in {"tsh", "t3", "t4"} and status in {"High", "Low"}:
            flag("thyroid", name, status)

    return found


def _build(kind, titles, base, parameter_analysis):
    found = detect_conditions(parameter_analysis)
    keys = [k for k in CONDITIONS if k in found]

    slots = []
    for key, label, time, icon in SLOTS:
        steps = [dict(step, tag=None) for step in base[key]]
        seen = {step["text"] for step in steps}

        for condition_key in keys:
            for step in CONDITIONS[condition_key][kind].get(key, []):
                if step["text"] not in seen:
                    seen.add(step["text"])
                    steps.append(dict(step, tag=CONDITIONS[condition_key]["label"]))

        title, subtitle = titles[key]
        slots.append({
            "key": key,
            "label": label,
            "time": time,
            "icon": icon,
            "title": title,
            "subtitle": subtitle,
            "steps": steps,
        })

    notes, signs = [], []
    for condition_key in keys:
        for note in CONDITIONS[condition_key]["notes"]:
            if note not in notes:
                notes.append(note)
        for sign in CONDITIONS[condition_key]["signs"]:
            if sign not in signs:
                signs.append(sign)
    for sign in GENERAL_SIGNS:
        if sign not in signs:
            signs.append(sign)

    return {
        "slots": slots,
        "conditions": [CONDITIONS[k]["label"] for k in keys],
        "flagged": [detail for k in keys for detail in found[k]],
        "notes": notes,
        "signs": signs,
        "personalised": bool(keys),
    }


def build_daily_diet(parameter_analysis):
    return _build("diet", DIET_TITLES, BASE_DIET, parameter_analysis)


def build_daily_precautions(parameter_analysis):
    return _build("care", CARE_TITLES, BASE_CARE, parameter_analysis)
