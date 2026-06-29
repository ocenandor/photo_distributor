# Quality Lab Experiment Baselines

These settings are fixed for lab evaluation only. They are not production
workflow defaults.

## Current Production-Like Baseline

- Run id: `sface_baseline`
- Recognizer: OpenCV SFace
- Detector: OpenCV YuNet
- Detection threshold: `0.6`
- Match threshold: `0.45`
- Derived references: disabled

## Current Derived-Reference Lab Baseline

- Run id: `sface_derived_0_50_det_0_75`
- Source run id: `sface_baseline`
- Recognizer: OpenCV SFace
- Detector: OpenCV YuNet
- Detection threshold: `0.6`
- Match threshold for reporting: `0.35`
- Derived reference candidate score: `>= 0.50`
- Derived reference detection score: `>= 0.75`
- Derived reference box height ratio: `>= 0.12`
- Derived reference box area ratio: `>= 0.01`
- Derived references per person: `<= 4`

The derived-reference baseline is useful because it improved the threshold
sweep on the current labeled dataset without adding false recipients at
threshold `0.35`. It is still experimental and must not be copied into
production until we have more labeled events and a stronger risk analysis.
