# Insulin Management Decision-Support System
## Architecture Document — Nightscout-Based Build

**Status:** Draft for review with CDE/endocrinologist
**Design principle:** This system produces *guideline estimates and reminders*, not autonomous dosing. All actual bolus decisions remain human-confirmed. This keeps it aligned with #WeAreNotWaiting norms and gives your clinical team a clean line to sign off on (data/suggestions = engineering; dosing = medical decision).

---

## 1. High-Level Data Flow

```
 ┌─────────────┐   ┌──────────────┐   ┌───────────────┐   ┌────────────┐
 │ Google       │   │ Garmin       │   │ Nutrition      │   │ Nightscout │
 │ Calendar API │   │ Health API   │   │ Log (see §4)   │   │ REST API   │
 │ (events)     │   │ (HR, steps,  │   │ (macros, meal  │   │ (IOB, COB, │
 │              │   │ activity)    │   │ favorites)     │   │ BG, doses) │
 └──────┬───────┘   └──────┬───────┘   └───────┬────────┘   └─────┬──────┘
        │                  │                   │                  │
        └──────────────────┴─────────┬─────────┴──────────────────┘
                                      ▼
                          ┌───────────────────────┐
                          │  Ingestion & Normalize │
                          │  Layer (per-source     │
                          │  adapters → common     │
                          │  timeline schema)       │
                          └───────────┬────────────┘
                                      ▼
                          ┌───────────────────────┐
                          │  Timeseries Store       │
                          │  (Nightscout Mongo, or  │
                          │  extend with Postgres/  │
                          │  Timescale for your own │
                          │  derived tables)         │
                          └───────────┬────────────┘
                                      ▼
                          ┌───────────────────────┐
                          │  Recommendation Engine  │
                          │  - macro budget calc    │
                          │  - meal-matching        │
                          │  - activity-adjusted    │
                          │    guidance (rules from │
                          │  your care team)         │
                          └───────────┬────────────┘
                                      ▼
                ┌─────────────────────┴─────────────────────┐
                ▼                                             ▼
     ┌─────────────────────┐                     ┌───────────────────────┐
     │ Garmin Connect IQ    │                     │ Mobile/Web App or      │
     │ Watch App: alarms +  │                     │ Nightscout webhook /   │
     │ meal/dose reminder   │                     │ push notification      │
     └─────────────────────┘                     └───────────────────────┘
```

---

## 2. Why Build on Nightscout Rather Than From Scratch

Nightscout already solves the hardest, highest-liability parts:
- Ingests treatment data (bolus, basal, IOB, COB) from Loop, AAPS, OpenAPS
- Has a mature REST API (`/api/v1/entries`, `/api/v1/treatments`, `/api/v1/profile`)
- Has a plugin architecture (you can add a custom plugin rather than forking core)
- Has existing alerting/webhook infrastructure you can extend instead of rebuilding

**Your build = a companion service** that reads from Nightscout's API, pulls in the three external sources, computes guidance, and writes back either as Nightscout "treatment notes" / custom entries, or pushes directly to your own notification layer. This keeps Nightscout's core (which your educators may already trust) untouched.

---

## 3. Input Layer — API Details

| Source | API | Data pulled | Notes |
|---|---|---|---|
| Nightscout | REST API (self-hosted) | IOB, COB, BG trend, treatment history, active profile (ISF, carb ratio, basal) | Auth via API secret or token; this is your source of truth for dosing math |
| Google Calendar | Calendar API v3 | Event start/end, title, duration | Use event duration + a tag/keyword convention ("gym", "meeting", "travel") to classify activity-relevance |
| Garmin | Garmin Health API (server-to-server push) | Heart rate stream, activity sessions, steps, stress score | Requires Garmin Health API partner approval — apply early, this has the longest lead time |
| Nutrition | See §4 below | Meal macros, "favorite meals" library | Cronometer has no public API — this is the layer needing a decision |

---

## 4. Nutrition Input — The Open Question

Cronometer does not offer a public/partner API. Three realistic paths, in order of effort:

1. **Manual favorites library (recommended to start):** You define your "favorite meals" once (macros per meal) in a simple table Nightscout or your own DB. No live Cronometer integration needed — this alone unlocks the "which of my favorite meals fits today's budget" feature, which is most of the value.
2. **CSV export bridge:** Cronometer supports data export; a scheduled job ingests the export on a cadence (daily) rather than real-time API calls. Fragile but workable.
3. **Switch logging tool:** Apps like FatSecret or Nutritionix have documented partner APIs. Only worth it if you want live, ad-hoc meal logging integrated rather than a fixed favorites list.

Start with (1) — it's the lowest-engineering, highest-value option and doesn't block anything else.

---

## 5. Recommendation Engine — Scope and Guardrails

This is the layer your endocrinologist/CDE should review most closely. Suggested scope boundaries:

**In scope (decision support):**
- Given a target daily calorie/macro budget and today's calendar events, rank your favorite meals by fit
- Flag days where a calendar event (e.g., long meeting, travel, workout) suggests adjusting meal timing or size
- Surface an activity-adjusted note (e.g., "Garmin shows sustained elevated HR — your care team's guidance for exercise days may apply") — phrased as a prompt to apply *their* rules, not a computed dose
- Generate a reminder ("time to consider checking BG/dosing for [meal]") tied to calendar/meal timing

**Explicitly out of scope (do not compute or auto-send):**
- Calculated bolus units
- Any automatic communication to a pump
- Overriding or second-guessing existing Loop/AAPS/OpenAPS dosing algorithms

Keep the actual carb-ratio/ISF/IOB-decay math confined to what Nightscout/your looping algorithm already does — your engine should *reference* those numbers for context, not recompute them independently. Two independent dosing calculators disagreeing with each other is a real safety hazard, so treat existing algorithm as the single source of truth for numbers and your engine as a scheduling/prioritization layer on top of it.

---

## 6. Output Layer

**Garmin Connect IQ App**
- Connect IQ SDK (not the Health API — that's inbound only) for on-watch UI
- Widget/app shows: today's suggested meal, macro budget remaining, upcoming event-based reminder
- Alarms/notifications are user-facing prompts only ("Consider dosing now") — Garmin's platform does not support third-party apps issuing pump commands, so this stays a human-in-the-loop nudge, which also matches your scope boundary above

**Notifications / Web**
- Extend Nightscout's existing alert/webhook system, or build a small mobile companion (push via Firebase/APNs) if you want richer UI than the watch allows

---

## 7. Suggested Build Order

1. Stand up your Nightscout instance + confirm API access to IOB/COB/BG/treatments
2. Build the favorites-meal library (manual macros) — unlocks meal-matching immediately
3. Google Calendar ingestion + simple event classifier
4. Recommendation engine v1: rules-based (no ML) meal-ranking against macro budget + calendar
5. Garmin Connect IQ reminder app (start with manual "check app" alert, add Health API HR/activity input in v2)
6. Review v1 logic with your CDE/endo before any dose-adjacent language ships to the watch
7. Layer in Garmin Health API activity data to refine recommendations

---

## 8. Open Decisions to Bring to Your Care Team

- What phrasing is acceptable for dose-related reminders (they may want strict "check your numbers" language, not anything implying a specific dose)
- Whether activity data should adjust *timing* suggestions only, or also flag "discuss exercise-day dosing pattern with your endo"
- Data retention/privacy approach if any of this data leaves your own infrastructure (Garmin Health API, Google Calendar API both require OAuth consent screens — fine for personal use, but review scopes carefully)
