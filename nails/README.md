# 💅 Nails

An app for finding nail salons close to you.

- **Business owner:** uploads her salon with a name, phone, city, location on a map, the treatments she offers, a **price range** (from ___ to ___ ₪) and **at least 5 photos** of her work.
- **Customer:** chooses a radius (2 / 5 / 10 / 25 / 50 km) from her location, or picks a city, filters by treatment and by budget (up to 100 / 150 / 250 / 400 ₪), and sees the closest salons first, with the price range on every card.
- **WhatsApp button:** opens a chat with the business and a ready-made message: "היי! הגעתי אלייך דרך אפליקציית Nails 💅"
  Every press is counted, so the business owner can see how many enquiries came through the app.

## What's in the app

| Screen | What it does |
|------|-----|
| Home | Search, radius, treatment filter, salons sorted by distance |
| Business page | Photo gallery, distance, treatments, WhatsApp / call / Waze navigation |
| Add business (+) | Form: details → location (GPS or map tap) → photos (5–12) |
| My business | Statistics (views, WhatsApp enquiries), edit details, photos, delete |
| Favourites | Businesses saved with the heart button (stored on the device) |

The owner can manage her business without signing up: she gets a **private management link** (saved on the device it was created on, and can be copied to another phone).

## Running locally

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
# open http://localhost:8000
```

Demo data (optional): `pip install pillow && python scripts/seed_demo.py`

Tests: `pytest`

## Structure

```
app/main.py     server (FastAPI): search, add, edit, WhatsApp
app/geo.py      distance calculation, phone formatting
app/db.py       database (SQLite) + photos folder
static/         the app itself (HTML/CSS/JS), RTL, built for phones
tests/          tests
```

Data is saved in `data/` (configurable with `NAILS_DATA`).
