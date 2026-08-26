# Local wake word (fully offline) 🔊

Ultron already listens for "Ultron" via the browser's speech service. For a
**fully local** wake word, run any detector you like next to him and have it
poke his API — no cloud, no Chrome.

## The hook

```bash
curl -X POST http://localhost:3000/api/wake \
     -H 'Content-Type: application/json' \
     -d '{"reason": "openWakeWord"}'
```

Every connected Ultron tab/PWA receives a `wake` event over SSE and arms the
microphone. (If the browser lacks mic permission, he shows a hint instead.)

## Example: openWakeWord (Python)

```bash
pip install openwakeword sounddevice
# then run the script below — it detects "hey jarvis"-style models;
# train a custom "ultron" model at https://github.com/dscripka/openWakeWord
```

```python
# wake_ultron.py — prints + pokes Ultron when the wake word fires
import time, urllib.request
from openwakeword.model import Model

URL = "http://localhost:3000/api/wake"
model = Model()  # uses default pretrained models; add your custom ultron.onnx

import numpy as np, sounddevice as sd
samplerate = 16000

def callback(indata, frames, time_info, status):
    preds = model.predict(indata)
    for name, score in preds.items():
        if score > 0.5:
            print(f"WAKE: {name} ({score:.2f})")
            req = urllib.request.Request(
                URL, data=b'{"reason":"openWakeWord"}',
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req)
            model.reset()

with sd.InputStream(channels=1, samplerate=samplerate, dtype="int16", callback=callback):
    print("listening for the wake word…")
    while True:
        time.sleep(0.1)
```

## Alternatives

- **Porcupine** (Picovoice) — free personal tier, custom keywords, very low CPU
- A physical button / Stream Deck hitting the same endpoint works too

> This script is an untested example — adjust model names and thresholds to your setup.
