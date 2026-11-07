# Submission pack (draft)

Use only claims that can be shown in the current build. The Nestwork demo replays a **recorded** clip; it is not a
live venue camera. The other venue listings are simulated. No seat-state accuracy result has been measured on held-out
venue footage.

## Submission sheet

| Field | Current draft |
|---|---|
| Team name | `[confirm registered team name]` |
| Team members | Daffa, Yacine, Omair, Khalid (confirm spelling/registration) |
| Project | Birdie |
| One-line description | Birdie shows study-space availability in Doha before you make the drive. |
| Hugging Face Space | [Affaad/birdiee](https://huggingface.co/spaces/Affaad/birdiee) |
| Detector | [`PekingU/rtdetr_r18vd`](https://huggingface.co/PekingU/rtdetr_r18vd), used as a pretrained detector; no fine-tuning is claimed. |
| Dataset | No project dataset is published yet. |
| Demo video | `[add link if/when recorded]` |

## Short demo flow

1. Open the customer app at the Space root and choose Nestwork Msheireb. Explain that it is recorded footage played
   through the detection pipeline; other venues are sample data.
2. Show the free and unavailable study-space counts and the mapped seat statuses. A seat is only shown as usable when
   its configured seat and workspace evidence passes the backend rules; uncalibrated or uncertain seats remain unknown.
3. Open `/operator/`, select the recorded video, and run it through the detector. Show the detections and resulting
   states. The camera-region/table/seat mapping is configured ahead of time; the model does not discover a venue layout.
4. Point out one detected person or belonging and show how the corresponding mapped seat/workspace status changes.
   Only claim a specific transition if it occurs in the clip during the actual demo.
5. Explain the limits: pretrained model, fixed camera calibration, simulated listings, and no measured real-world
   accuracy or validated arrival forecast.

The operator video upload is for this demonstration. Uploaded frames are sent to the Space for processing. Do not claim
that video remains on the venue camera, never leaves the venue, is blurred, or is retained/deleted in a particular way
unless that behavior has been independently verified for the deployed Space.

## Claims supported by the repository

- The app distinguishes a recorded demo venue from simulated venue listings.
- The vision pipeline uses pretrained RT-DETR and configured seat/table/workspace regions.
- The API exposes seat and study-space availability, including uncertain states; only verified usable spaces count as
  available.
- The test suite checks application behavior, but passing tests do not establish accuracy on real venue footage.

## Do not claim

- That the Nestwork listing is a live camera, or that other listings are live venues.
- That the model detects every chair, person, or bag, or automatically discovers tables/seats/layouts.
- Any accuracy, latency, operating cost, or compute-credit figure unless it is freshly measured and recorded with its
  method and conditions.
- That the model is fine-tuned, a dataset is published, or an arrival forecast is accurate.
- That frames are blurred, never leave the venue, or are never retained without deployment-level verification.
- That users can book or check in; those features are out of scope for this MVP.
