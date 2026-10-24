# Wardrobe Archive demo

A local wardrobe mock based on the supplied Yeezy UI reference. The Wardrobe view shows three shirts, three pants, and three pairs of shoes photographed unworn on flat surfaces. The Plan view shows seven outfits in Monday through Sunday columns. `images/` contains the source photos and `rendered/` contains the transparent product images shown in the grid.

## Run

Put your Google AI Studio API key in `demo/.env`:

```dotenv
GEMINI_API_KEY=your-api-key
```

Then start the local app:

```powershell
cd demo
npm install
npm run dev
```

Open `http://localhost:8000`. If you already preview the website at `http://127.0.0.1:3000` or another local port, the Plan view will also connect to the Node API at `http://127.0.0.1:8000` while `npm run dev` is running. The Node server loads `.env` and uses Google's `@google/genai` JavaScript SDK to request plans from `gemma-4-26b-a4b-it`. The API key stays on the server, and `.env` is ignored by Git. An existing shell `GEMINI_API_KEY` takes precedence over the value in `.env`. Without a key or a running Node server, the Plan view shows a labeled sample week.

Use **ADD A PIECE** to upload a flat-lay photo. The site automatically removes the background, centers the clothing on a transparent square, and saves both the original and cutout in this browser using IndexedDB. Transparent PNG uploads skip background removal. Saved looks use localStorage.

Background removal uses the [ORMBG ONNX model](https://huggingface.co/onnx-community/ormbg-ONNX) through [Transformers.js](https://huggingface.co/docs/transformers.js/en/index). The first upload needs internet access to fetch the library and model. Processing happens in the browser.

When you open Plan, the app generates a Gemma 4 week if there is no saved plan for the upcoming Monday. **GENERATE WITH GEMMA 4** refreshes it. The planner sends reduced copies of the wardrobe images, names, and categories to the Google API, then saves only the selected item IDs and brief explanations in localStorage. The server validates that every recommendation refers to a piece in the wardrobe.

The server uses the machine's DNS settings first. If they cannot resolve Google's API host, it falls back to Google's public DNS (`8.8.8.8`) for that host only. This does not change Windows DNS settings. If Plan still reports a DNS or connection error, check the machine's internet connection and VPN settings, then restart `npm run dev` and try again.

## Rebuild the sample images

The demo includes the nine photos and prepared cutouts, so rebuilding is optional. To regenerate them:

```powershell
py -m venv demo/.venv
demo/.venv/Scripts/python.exe -m pip install -r demo/requirements.txt
demo/.venv/Scripts/python.exe demo/scripts/prepare-flat-lays.py
cd demo
npm install
npm run render-seeds
cd ..
demo/.venv/Scripts/python.exe demo/scripts/polish-flat-lays.py
```

The finishing script trims two samples where the model retained part of the surface. `reference/yeezyUI.png` is the supplied layout reference.

## Sample photo sources

| Source file | Pexels photo ID |
| --- | --- |
| `shirt-white-tee.jpg` | 12025472 |
| `shirt-black-flat-tee.jpg` | 6046205 |
| `shirt-cream-knit.jpg` | 6046231 |
| `pants-brown-lace.jpg` | 6046228 |
| `pants-taupe-folded.jpg` | 33633245 |
| `pants-indigo-denim.jpg` | 18533673 |
| `shoes-monochrome-slipons.jpg` | 35618109 |
| `shoes-pink-runner.jpg` | 6748330 |
| `shoes-taupe-boot.jpg` | 8408556 |

Photo URLs follow `https://www.pexels.com/photo/ID/`. See the [Pexels license](https://www.pexels.com/license/) for reuse terms.
