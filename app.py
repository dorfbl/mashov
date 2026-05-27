import asyncio
import re
import json
import httpx
import hashlib
import os
from datetime import date, timedelta
from flask import Flask, render_template
from mashov import MashovClient

app = Flask(__name__)

USERNAME   = "021940135"
PASSWORD   = "!Meggie4life"
SEMEL      = 414235
YEAR       = 2026
STUDENT_ID = "071681ed-b592-4744-93db-90246e989e3f"
PARENT_ID  = "eb1abb33-dd62-4c78-9eac-9a87aec544de"

# Get your key at https://console.anthropic.com
ANTHROPIC_API_KEY = "sk-ant-.........."

DAY_NAMES = {1:"ראשון",2:"שני",3:"שלישי",4:"רביעי",5:"חמישי",6:"שישי"}

SUBJECT_STYLE = {
    "עברית":         ("pill-heb",  "📖"),
    "מתמטיקה":       ("pill-math", "➕"),
    "חינוך גופני":   ("pill-pe",   "⚽"),
    "אמנויות":       ("pill-art",  "🎨"),
    "מדעים":         ("pill-sci",  "🔬"),
    "העשרה":         ("pill-enr",  "⭐"),
    "כישורי חיים":   ("pill-life", "💛"),
    "מפתח הלב":      ("pill-hrt",  "❤️"),
    "זהירות בדרכים": ("pill-road", "🚦"),
}

MSG_COLORS  = ["#534AB7","#0F6E56","#BA7517","#993556","#3B6D11",
               "#185FA5","#993C1D","#3B6D11","#534AB7","#0F6E56"]
ACT_COLORS  = ["#534AB7","#0F6E56","#BA7517","#993556","#3B6D11",
               "#185FA5","#3B6D11","#993C1D"]
ACT_EMOJI   = {1:"🥾",2:"📖",3:"🎭",4:"🎶",5:"🎨"}
MSG_EMOJIS  = ["📚","🎵","📝","✅","🔔","💬","📣","📩","🔖","📮"]
MONTH_MAP   = {"01":"ינואר","02":"פברואר","03":"מרץ","04":"אפריל",
               "05":"מאי","06":"יוני","07":"יולי","08":"אוגוסט",
               "09":"ספטמבר","10":"אוקטובר","11":"נובמבר","12":"דצמבר"}


CACHE_FILE = "smart_cache.json"

def data_hash(acts_raw, convs_with_body):
    """Hash of activity titles+dates and message ids — changes only when new data arrives."""
    sig = json.dumps([
        [(a.get("title",""), a.get("activityStartDate","")) for a in acts_raw],
        [(c["id"], c["date_iso"]) for c in convs_with_body]
    ], ensure_ascii=False, sort_keys=True)
    return hashlib.md5(sig.encode()).hexdigest()

def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_cache(hash_val, smart_data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"hash": hash_val, "smart": smart_data}, f, ensure_ascii=False)
    except Exception as e:
        print(f"Cache save error: {e}")


def fmt_date(iso):
    parts = iso[:10].split("-")
    if len(parts) == 3:
        return f"{parts[2]}.{parts[1]}.{parts[0][2:]}"
    return iso[:10]


def strip_html(html):
    text = re.sub(r'<[^>]+>', ' ', html or "")
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&[a-zA-Z]+;', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def safe_html(html):
    if not html:
        return ""
    html = re.sub(r'<(script|style|iframe)[^>]*>.*?</\1>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r' on\w+="[^"]*"', '', html)
    html = re.sub(r" on\w+='[^']*'", '', html)
    return html


def days_until(date_str):
    try:
        target = date.fromisoformat(date_str[:10])
        delta = (target - date.today()).days
        return delta
    except Exception:
        return 999


def clean_for_prompt(text):
    """Remove characters that could break JSON in Claude response."""
    text = text.replace("\\", " ").replace('"', ' ').replace("'", " ")
    text = re.sub(r'[\x00-\x1f\x7f]', ' ', text)
    return text[:300]

async def ask_claude(prompt):
    """Call Claude API and return parsed JSON."""
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "YOUR_ANTHROPIC_API_KEY_HERE":
        print("No Anthropic API key set.")
        return None
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"Content-Type": "application/json",
                         "x-api-key": ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01"},
                json={
                    "model": "claude-sonnet-4-5",
                    "max_tokens": 1500,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            data = resp.json()
            if "error" in data:
                print(f"Claude API error response: {data['error']}")
                return None
            text = data["content"][0]["text"]
            # extract JSON block robustly
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                text = match.group(0)
            else:
                text = re.sub(r'```json|```', '', text).strip()
            return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"Claude JSON parse error: {e}")
        return None
    except Exception as e:
        print(f"Claude API error: {e}")
        return None


async def fetch_data():
    async with MashovClient(username=USERNAME, password=PASSWORD,
                            semel=SEMEL, year=YEAR) as client:
        await client.login()

        timetable_raw = await client.get_timetable(STUDENT_ID)
        convs_raw     = await client.get_conversations(take=20)
        acts_resp     = await client.request("GET", "/api/schoolActivities/permitted")
        acts_raw      = acts_resp.json()

        # fetch full message bodies
        convs_with_body = []
        for i, c in enumerate(convs_raw[:15]):
            conv_id = c.get("conversationId", "")
            sender  = c["messages"][0].get("senderName","") if c.get("messages") else ""
            body_raw = ""
            body_html = ""
            try:
                r    = await client.request("GET", f"/api/mail/conversations/{conv_id}")
                data = r.json()
                if isinstance(data, list) and data:
                    body_raw  = strip_html(data[0].get("body",""))
                    body_html = safe_html(data[0].get("body",""))
                elif isinstance(data, dict):
                    raw = data.get("body","")
                    if not raw and data.get("messages"):
                        raw = data["messages"][0].get("body","")
                    body_raw  = strip_html(raw)
                    body_html = safe_html(raw)
            except Exception:
                pass
            convs_with_body.append({
                "id": conv_id,
                "subject": c["subject"],
                "date": fmt_date(c["sendTime"]),
                "date_iso": c["sendTime"][:10],
                "sender": sender,
                "color": MSG_COLORS[i % len(MSG_COLORS)],
                "emoji": MSG_EMOJIS[i % len(MSG_EMOJIS)],
                "is_new": c.get("isNew", False),
                "body": body_html,
                "body_text": body_raw
            })

    # ── timetable ──────────────────────────────────────────────────
    schedule = {}
    seen = set()
    for entry in timetable_raw:
        tt = entry["timeTable"]
        gd = entry["groupDetails"]
        day, lesson = tt["day"], tt["lesson"]
        subject = gd["subjectName"]
        key = (day, lesson, subject)
        if key in seen:
            continue
        seen.add(key)
        teacher = gd["groupTeachers"][0]["teacherName"] if gd["groupTeachers"] else ""
        style, emoji = SUBJECT_STYLE.get(subject, ("pill-enr","📚"))
        schedule.setdefault(day,[]).append({
            "lesson": lesson, "subject": subject,
            "teacher": teacher, "style": style, "emoji": emoji
        })
    for day in schedule:
        schedule[day].sort(key=lambda x: x["lesson"])

    day_classes = {1:"d1",2:"d2",3:"d3",4:"d4",5:"d5",6:"d6"}
    days = []
    for day in sorted(schedule):
        days.append({
            "num": day, "name": DAY_NAMES.get(day, str(day)),
            "cls": day_classes.get(day,"d1"), "lessons": schedule[day]
        })

    # ── activities ──────────────────────────────────────────────────
    acts = []
    for i, a in enumerate(acts_raw):
        date_str = a.get("activityStartDate","")[:10]
        parts    = date_str.split("-")
        day_num  = parts[2] if len(parts)==3 else "?"
        month    = MONTH_MAP.get(parts[1],"") if len(parts)==3 else ""
        acts.append({
            "title":       a.get("title",""),
            "day":         day_num,
            "month":       month,
            "date_fmt":    fmt_date(date_str),
            "date_iso":    date_str,
            "days_until":  days_until(date_str),
            "color":       ACT_COLORS[i % len(ACT_COLORS)],
            "emoji":       ACT_EMOJI.get(a.get("activityType",1),"🎒"),
            "answered":    a.get("isAnswered", False),
            "description": strip_html(a.get("description",""))[:600]
        })

    # ── smart AI layer ──────────────────────────────────────────────
    today_str   = date.today().isoformat()
    acts_text   = "\n".join([f"- {clean_for_prompt(a['title'])} בתאריך {a['date_iso']} ({a['days_until']} ימים מהיום): {clean_for_prompt(a['description'])}" for a in acts])
    msgs_text   = "\n".join([f"- [{c['date_iso']}] {clean_for_prompt(c['subject'])}: {clean_for_prompt(c['body_text'])}" for c in convs_with_body])

    smart_prompt = (
        f"TODAY IS: {today_str}. This is critical for all date comparisons.\n\n"
        f"School activities (each has days_until = days from today, negative means already passed):\n{acts_text}\n\n"
        f"Teacher messages (date is when message was sent):\n{msgs_text}\n\n"
        "Return ONLY valid JSON (no markdown, no extra text):\n"
        "{\"upcoming_events\":[],\"homework\":[]}\n\n"
        "STRICT RULES:\n"
        f"1. upcoming_events: ONLY include events where days_until >= 0 (today or future). "
        "If days_until is negative the event already happened - EXCLUDE IT. "
        "Merge relevant message info (what to bring, timing) into the matching event. "
        "urgency: days_until==0 -> today, ==1 -> tomorrow, 2-7 -> soon, >7 -> future.\n"
        f"2. homework: ONLY tasks from messages that are still relevant as of {today_str}. "
        "If a message mentions a due date that has already passed, EXCLUDE IT. "
        "If no due date mentioned, include only if message was sent within the last 7 days. "
        "Extract concrete tasks: pages to read, items to bring for a lesson, exercises to complete. "
        "urgency: due today -> today, due tomorrow -> tomorrow, due within 7 days -> soon, no date -> no_date.\n"
        "3. All text values in Hebrew.\n"
        "4. Return empty arrays [] if nothing qualifies.\n"
        "JSON schema: upcoming_events items have: title, date_iso, date_fmt(DD.MM.YY), days_until(int), "
        "urgency, emoji, to_bring(string array), notes. "
        "homework items have: subject, task, due_date(DD.MM.YY or null), emoji, urgency."
    )

    # Check cache before calling Claude
    current_hash = data_hash(acts_raw, convs_with_body)
    cache = load_cache()

    if cache.get("hash") == current_hash and cache.get("smart"):
        print("✅ Cache hit — skipping Claude API call")
        smart = cache["smart"]
    else:
        print(f"🔄 Data changed (hash {current_hash[:8]}) — calling Claude...")
        smart = await ask_claude(smart_prompt)
        if not smart:
            smart = {"upcoming_events": [], "homework": []}
        else:
            save_cache(current_hash, smart)
            print("💾 Smart data cached")

    # Python-side safety filter — never trust Claude alone
    today = date.today()
    filtered_events = []
    for ev in smart.get("upcoming_events", []):
        try:
            ev_date = date.fromisoformat(ev["date_iso"])
            if (ev_date - today).days < 0:
                continue  # already passed
            ev["days_until"] = (ev_date - today).days
            # fix urgency based on real calculation
            d = ev["days_until"]
            ev["urgency"] = "today" if d==0 else "tomorrow" if d==1 else "soon" if d<=7 else "future"
        except Exception:
            pass
        filtered_events.append(ev)
    smart["upcoming_events"] = filtered_events

    filtered_hw = []
    for hw in smart.get("homework", []):
        due = hw.get("due_date")
        if due and due != "null":
            try:
                parts = due.split(".")
                if len(parts) == 3:
                    year = int(parts[2]) + 2000
                    hw_date = date(year, int(parts[1]), int(parts[0]))
                    if hw_date < today:
                        continue  # past due
                    d = (hw_date - today).days
                    hw["urgency"] = "today" if d==0 else "tomorrow" if d==1 else "soon" if d<=7 else "no_date"
            except Exception:
                pass
        filtered_hw.append(hw)
    smart["homework"] = filtered_hw

    urgency_colors = {
        "today":    "#C41E3A",
        "tomorrow": "#BA7517",
        "soon":     "#185FA5",
        "future":   "#3B6D11",
        "no_date":  "#534AB7"
    }
    urgency_labels = {
        "today":    "היום!",
        "tomorrow": "מחר",
        "soon":     "近く",
        "future":   "בקרוב",
        "no_date":  ""
    }
    urgency_labels = {
        "today":    "היום! 🔴",
        "tomorrow": "מחר 🟡",
        "soon":     "השבוע 🔵",
        "future":   "בקרוב 🟢",
        "no_date":  ""
    }

    for ev in smart.get("upcoming_events", []):
        ev["color"] = urgency_colors.get(ev.get("urgency","future"), "#534AB7")
        ev["urgency_label"] = urgency_labels.get(ev.get("urgency","future"), "")
    for hw in smart.get("homework", []):
        hw["color"] = urgency_colors.get(hw.get("urgency","no_date"), "#534AB7")
        hw["urgency_label"] = urgency_labels.get(hw.get("urgency","no_date"), "")

    cache_used = (cache.get("hash") == current_hash and cache.get("smart"))

    return {
        "days":       days,
        "convs":      convs_with_body,
        "acts":       acts,
        "upcoming":   smart.get("upcoming_events", []),
        "homework":   smart.get("homework", []),
        "today_str":  today_str,
        "cache_used": cache_used
    }


@app.route("/")
def index():
    data = asyncio.run(fetch_data())
    return render_template("index.html", **data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=False, port=5050)
