# 🎒 דשבורד משוב לילדים

## התקנה והפעלה

```bash
pip install -r requirements.txt
python app.py
```
פתח בדפדפן: http://localhost:5050

## הפעלת AI חכם (שיעורי בית + אירועים קרובים)

1. קבל מפתח API בחינם: https://console.anthropic.com
2. פתח `app.py` ועדכן:
   ```python
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
3. הפעל מחדש את השרת

## מה מוצג
- 🧠 AI חכם: אירועים קרובים + מה להביא + שיעורי בית
- 📅 מערכת שעות שבועית
- 💌 הודעות מהמורים (עם תוכן מלא)
- 🗺️ פעילויות השנה
