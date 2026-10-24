# Rilldex product film

A 60-second, 1080p / 60 fps tour of RL training diagnosis, execution and behavior analysis. An original dithered agent connects to tools; attachment waves cross the frame. Text-led; no narration or music.

```sh
cd scripts/promo
npm install
node render.cjs --preview
node render.cjs
node serve.cjs
```

Requires Node.js and FFmpeg on PATH. Outputs go to `outputs/rilldex-promo`. Use `--width 1280 --fps 30` for a smaller export. `--preview` renders chapter stills and a contact sheet.

Visual reference: [Paper’s dithering examples](https://shaders.paper.design/dithering). A minimal agent plays one short retro level. Dithered headlines, directional light and stepped star animations share a Bayer grid. Tentacles reach each tool before waves spread from its connection.

The ending clears a two-second dungeon, then scans in the logo and closing copy with BBS-style pixel lettering. A GitHub button appears above a populated dithered RL dashboard with slow live-style updates.

Training and execution values come from the seeded product-tour fixture; behavior comparisons use authored examples aggregated by Rilldex. The structure scene zooms from four focused items to an authored 43-item, eight-level rollout, with type colors shared with the app. Unit-map excerpts come from the [public OpenHands trace](https://github.com/metauto-ai/agent-as-a-judge/blob/43c2fa7b84ef0c1522e8250576e6798bace29dd0/benchmark/trajectories/OpenHands/39_Drug_Response_Prediction_SVM_GDSC_ML.json). Each scene identifies its source. The film is an animated product demonstration, not a performance benchmark or screen recording.
