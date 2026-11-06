# Handoff: Birdie mobile app

## Overview
Birdie shows live seat availability in libraries, cafés, coworking spaces and study rooms. Users browse nearby places, open a place to see a floor plan of tables and chairs coloured by status, tap a free chair, and check in by scanning the QR code on the table (or typing a 4-digit code). Checked-in seats show as taken to everyone else until the user frees them.

## About the design files
`Birdie App v3.dc.html` is a **design reference built in HTML**: a working prototype that shows the intended look and behaviour. It is not production code. Recreate it in the target codebase's environment (SwiftUI, React Native, Flutter, etc.) using that codebase's patterns. If no codebase exists yet, a native iOS (SwiftUI) or React Native app is a good fit.

Open the HTML file in a browser (served from this folder, so `support.js`, `ios-frame.jsx` and `image-slot.js` load) to click through it. The iPhone bezel (`ios-frame.jsx`) and photo drop-zones (`image-slot.js`) are prototype scaffolding only. All mock data and logic live in the `<script data-dc-script>` block at the bottom of the HTML file.

## Fidelity
**High fidelity.** Final colours, type, spacing, radii and interactions. Recreate them exactly. Design frame: iPhone, 402 × 874 pt. Content starts below the status bar at ~58pt top padding; screen side padding is 20pt.

## Design tokens

### Colours
| Token | Hex | Use |
|---|---|---|
| cream | `#F6F1E7` | App background, tables on floor plan, sheets |
| mist | `#DCE9F2` | Cards, search field, floor plan surface, secondary buttons, keypad keys |
| indigo | `#4B3BFF` | Primary buttons, selected category, featured cards, "your seat", kicker labels, splash background |
| ink | `#16172E` | Primary text, selected sort chip, activity bar, scanner background |
| slate | `#4A4D63` | Secondary text, icons, dashed fixture outlines |
| free | `#2FB86A` | Free seat, live dot, success |
| taken | `#EF4E4E` | Taken seat, errors |
| scanner well | `#0E0F20` | QR viewfinder interior |

Translucent: live-dot halo `rgba(47,184,106,0.18)`; sheet backdrop `rgba(22,23,46,0.32)`.

### Typography
Plus Jakarta Sans (Google Fonts), weights 500 / 600 / 700 / 800. One family throughout.
| Role | Size | Weight | Tracking |
|---|---|---|---|
| Splash wordmark | 56 | 800 | −0.045em |
| Big number (featured card) | 38 | 800 | −0.045em |
| Screen title | 28–36 | 800 | −0.035 to −0.04em, line-height 1.05–1.1 |
| Section title | 20–22 | 800 | −0.03em |
| Card / row title | 15–16 | 700 | −0.02em |
| Button | 16–17 | 700 | 0 |
| Body / meta | 13–15 | 500–600 | 0 |
| Chip / label | 12–13 | 700 | 0 |
| Kicker | 12, uppercase | 700 | +0.08em, indigo |
Timers use `tabular-nums`.

### Radii, spacing, shadows
- Radii: pills 999; primary buttons 18; cards/featured 22–24; floor plan 28; bottom sheets 32 (top corners); category tiles 20; code boxes 18; segmented control 12 (inner 9).
- Spacing: 4-pt base; common gaps 6, 8, 12, 14, 18, 22.
- Shadows: floating activity bar `0 14px 34px rgba(22,23,46,0.28)`; bottom sheet `0 -14px 40px rgba(22,23,46,0.16)`; toast `0 12px 30px rgba(22,23,46,0.25)`; segmented thumb `0 1px 3px rgba(22,23,46,0.14)`; round back button on photo `0 4px 14px rgba(22,23,46,0.18)`.
- Selected chair ring: `0 0 0 2.5px mist, 0 0 0 5px indigo`.

## Screens

### 1. Splash
Full-screen indigo. The logo without its tile (white bird head, green eye, path in the HTML) at 80pt, plus the "Birdie" wordmark 56/800 in white, gap 16. The logo scales 0.86→1 and fades in (700ms `cubic-bezier(0.2,0.8,0.2,1)`), holds about 1.6s, then the screen fades out (450ms) while the logo scales to 1.06. Tap skips. Status bar is light. Shown once per launch. The logo appears nowhere else in the app.

### 2. Browse (home)
Food-delivery-style browsing, scrolling vertically.
1. **Location header:** "Seats near" (13/600 slate) above "Old Town ⌄" (22/800, indigo chevron).
2. **Search field:** mist, height 50, radius 16, magnifier icon; placeholder "Search libraries, cafés, coworks". Filters by name, area and type.
3. **Category rail** (scrolls sideways): 64×64 tiles, radius 20, with 12/700 labels below: All, Libraries, Cafés, Coworking, Study rooms. Line icons with 2.2 stroke. The selected tile is indigo with a white icon; the others are mist with an ink icon.
4. **"Free right now"** section title with a "● Live" indicator, then a sideways rail of indigo cards (148 wide, radius 22, padding 16): free count 38/800 white, "seats free", place name 15/700, walk time 12/500 mist. Shows the top 5 places by free seats, respecting the category. Hidden while searching.
5. **List:** title "All places" (or the category name). Sort chips: Nearest / Most seats free / Open late (34 high, 1.5pt ink border; selected chip filled ink with cream text). Rows: a 92×92 photo (radius 20) followed by the name 16/700, "Type · Area" 13/500 slate, "● N of M free · X min walk", and a 5pt bar split green/red by the share of free seats. Full places show a red dot, "Full right now" and the photo at 55% opacity. Empty state: "No places match that search."

### 3. Place detail
- **Hero photo:** 250 tall, full width. A 42pt round cream back button sits at top-left (y 56).
- **Content sheet:** overlaps the photo by 28pt, cream, top radius 28, padding 22/20.
  - Name 28/800; meta line "Type · Area · X min walk · Open till HH:MM".
  - Amenity chips (mist, 12/700).
  - A 1pt mist divider.
  - Headline "N seats free" (30/800), or "Full right now" / "None free here" when a filter matches nothing. "● Live" sits on the right.
- **Segmented control:** All seats / Outlet / Window. Chairs that don't match fade to 22% opacity and can't be tapped.
- **Floor plan:** 362 wide, height varies by layout (360–490), mist, radius 28.
  - Tables are cream rectangles (radius 10, or 6 for thin bars) or circles, labelled with a letter (13/700 slate).
  - Fixtures such as "Books" or "Counter" have a 1.5pt dashed slate border at 70% opacity.
  - A cream strip along the top edge marks windows. "↑ Entrance" is centred at the bottom.
  - **Chairs:** a 34×34 hit area containing a backrest (18×5, radius 3) above a seat (22×16, radius 6), gap 2. Chairs are rotated so the seat faces the table: 0° above it, 180° below, ±90° at the sides, and radial around round tables. Placed 17pt from the table edge.
  - Chair colours: green free, red taken, indigo yours. Only free chairs (and yours) can be tapped.
  - Layout coordinates for each venue type (library, café, cowork, study) are in `LAYOUTS` in the script.
- **Legend:** Free / Taken / Yours.
- **Seat sheet** (bottom sheet, opens when a free chair is tapped):
  - Grab handle; a 56pt green tile showing the seat label (e.g. "A3"); title "Seat A3 is free" 20/800; chips for table name, plus "Window" and/or "Outlet"; a close button.
  - Primary button "⌗ Scan to check in" (indigo, 56 high).
  - The selected chair gets the indigo ring.

### 4. Scan to check in
- **Screen:** full-screen ink, light status bar.
  - Header: close (×) in a slate circle, title "Check in".
  - Title "Scan the code on A3" (26/800) above "Find the Birdie sticker on the edge of the table and fit it in the frame." (15/500 mist).
- **Viewfinder:** 270×270, radius 32, `#0E0F20`.
  - Cream corner brackets, 5pt thick and 56pt long.
  - A green scan line with a glow moves up and down (1.6s ease-in-out, alternating).
  - The prototype pretends the code was found after about 3.2s (or on tap). In production, use the device camera with QR detection.
- **On success:**
  - The brackets turn green and a green circle with a check mark covers the frame.
  - The title changes to "Seat A3 confirmed", with "Checking you in…" below.
  - After 1s the app moves to Checked in.
- **Other actions:** the secondary outline button "Enter code instead" opens the code screen. Close returns to Place detail.

### 5. Enter code
- **Layout:**
  - A "‹ Scan instead" pill button; title "Enter seat code"; the line "Type the 4-digit code printed under the QR on seat A3."
  - Four 64×72 mist boxes (radius 18, 30/800 digits). The next empty box has a 2pt indigo ring.
  - A custom 3×4 keypad: 60-high mist keys, radius 18. The bottom row is blank / 0 / backspace.
- **Behaviour:**
  - Entering 4 digits checks the code automatically. Correct → Checked in.
  - Wrong → all boxes get red rings, the code clears, and the message reads "That code doesn't match A3. Try again." in red.
  - The prototype shows the right code below the boxes as a hint. Remove this in production.

### 6. Checked in
- **Content:**
  - A "‹ Floor plan" pill button.
  - A 128pt green tile (radius 36) with the seat label 44/800.
  - Kicker "CHECKED IN"; title "You're in."; body "Others now see A3 as taken. Free it up when you leave so the next person can sit."
  - A mist card with rows Place / Seat / Since ("2:14 PM (12:05)", time elapsed counting up).
  - Outline button (2pt ink) "Leaving? Free up A3".
- **Freeing up:** marks the seat free, returns to Place detail, and shows the toast "Thanks. A3 is free for the next person."

### Global: activity bar and toast
- **Activity bar:** while checked in, a floating ink bar sits at the bottom of Browse and Place (12pt from the sides, 30 from the bottom, radius 24). It contains a 44pt green seat tile, "Checked in at A3", the place name, and the elapsed time 20/800 tabular. Tapping it opens Checked in. It is hidden while the seat sheet is open.
- **Toast:** an ink pill at the top (y 60, 16pt from the sides, radius 18). Auto-dismisses after 3.2s.

## Interactions and state
- **Seat status:** `free | taken`, plus `mine` derived from the current check-in. There is no hold or reservation step. In the prototype, seats change at random every 2.6s to simulate live updates. In production, subscribe to a realtime feed (WebSocket or similar) so seats turn colour as they change.
- **State:**
  - Navigation: `screen` (browse, place, scan, code, in) and `placeId`.
  - Browse: `cat`, `sort` and `query`.
  - Place: `seg` (all / outlet / window) and `sel` (the selected chair index).
  - Check-in: `pending` is the seat being checked into during scan or code entry. `mine` is the current check-in: `{placeId, idx, label, name, since}`.
- **One seat at a time:** checking into a new seat frees the previous one.
- **Backend needs:**
  - Places: name, type, area, walk distance, hours, amenities, photo, floor plan.
  - Floor plan: tables (rectangles with chairs on top, bottom, left and right sides, or circles with n chairs) and fixtures, plus per-chair attributes (window, outlet).
  - Live seat status.
  - A check-in endpoint that validates the QR payload or the 4-digit seat code.
  - A check-out endpoint.
- **Transitions:**
  - Chair opacity fades over 200ms; bottom sheets slide up from the bottom.
  - Viewfinder brackets change colour over 250ms; splash timings are listed above.
  - Use platform-native push navigation between screens.
- **Accessibility:** each chair has an accessibility label such as "A3, free". An optional setting (`statusGlyphs`) adds × to taken chairs so status doesn't rely on colour alone.

## Assets
- **Logo:** inline SVG (bird head path, indigo stroke, green eye circle), defined in the brief and in the splash markup. On indigo, drop the tile. Minimum size 24px.
- **Icons:** simple line icons drawn inline (search, chevrons, close, category icons, scan frame, backspace, entrance arrow). Replace with the platform icon set (e.g. SF Symbols: `magnifyingglass`, `books.vertical`, `cup.and.saucer`, `laptopcomputer`, `chair`, `qrcode.viewfinder`, `delete.left`).
- **Place photos:** none are supplied. The prototype leaves those spaces blank for photos to be added later.

## Files
- `Birdie App v3.dc.html`: the full prototype. Markup is at the top; mock data (`PLACES`, `LAYOUTS`) and logic are in the script block at the bottom.
- `support.js`: runtime needed to open the prototype in a browser. Not part of the design.
- `ios-frame.jsx`: iPhone bezel for the prototype only.
- `image-slot.js`: photo drop-zone for the prototype only.
