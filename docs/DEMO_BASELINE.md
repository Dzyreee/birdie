# Recorded-video baseline

The first supplied WhatsApp clip is the calibration reference. It is approximately 9 seconds long,
832 × 464 pixels, and remains outside Git. `recording_sha256` in the venue config prevents its camera
polygons and mirror mask from being used on another recording by mistake. The second clip has a different
camera position and requires a separate calibration.

The reflection behind the left partition is ignored for person detections. Seven seat positions are
provisionally mapped to tables; S03, S05, S07, and S11 remain pending and are excluded from configured
capacity until a person verifies their table and camera/workspace polygons. S09's ID and table assignment
are inferred from the visible empty wooden chair. The schematic and polygons are approximate, not a surveyed floor plan.

Manual inspection of sampled frames from this clip found S01/S02/S09 empty, S04 with a backpack,
and seated people at S06/S08/S10. The pretrained `PekingU/rtdetr_r18vd` model detected the backpack as
`handbag` around 0.49–0.58 confidence in sampled frames; no fine-tuning was performed.

One real-model replay sampled ten frames. After the three-frame smoothing period, S01/S02 were free,
S04 was held, and S06/S08/S10 were occupied throughout the remaining frames. S09 stayed unknown when
a detected item on its shared table could not be assigned to one chair. The new usable-space gate additionally
requires the chair detector and an unblocked configured workspace; it can therefore report fewer spaces than FREE seats.
This single short clip has no observed seat transitions and is not a held-out accuracy evaluation. It does
not establish general detector accuracy, real-time behavior, or the production 30-minute rule.
