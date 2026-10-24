# Wardrobe Archive demo

A local wardrobe mock based on the supplied Yeezy UI reference. The Wardrobe view shows three shirts, three pants, and three pairs of shoes photographed unworn on flat surfaces. The Plan view shows seven outfits in Monday through Sunday columns. `images/` contains the source photos and `rendered/` contains the transparent product images shown in the grid.

## Run

If you already ran `aws configure` for the default profile, start the app without adding a bearer key:

```powershell
cd demo
npm install
npm run dev
```

For a named profile, set `AWS_PROFILE` in your shell before starting the app. You can also set `AWS_REGION` in `demo/.env` to override the profile's Region. The selected Region must offer Gemma 3 12B IT.

Alternatively, put an Amazon Bedrock API key in `demo/.env`:

```dotenv
AWS_BEARER_TOKEN_BEDROCK=your-bedrock-api-key
AWS_REGION=us-east-1
```

Open `http://localhost:8000`. If you already preview the website at `http://127.0.0.1:3000` or another local port, the Plan view will also connect to the Node API at `http://127.0.0.1:8000` while `npm run dev` is running. With configured AWS credentials, the server calls Bedrock's Converse API through the AWS SDK. With `AWS_BEARER_TOKEN_BEDROCK`, it calls Bedrock's Chat Completions endpoint through the OpenAI JavaScript SDK. Both use `google.gemma-3-12b-it`. The bearer key stays on the server, and `.env` is ignored by Git. Environment variables already set in your shell take precedence over `.env`. Without usable credentials or a running Node server, the Plan view shows a labeled sample week.

Use **ADD A PIECE** to upload a flat-lay photo. The site automatically removes the background, centers the clothing on a transparent square, and saves both the original and cutout in this browser using IndexedDB. Transparent PNG uploads skip background removal. Saved looks use localStorage.

Background removal uses the [ORMBG ONNX model](https://huggingface.co/onnx-community/ormbg-ONNX) through [Transformers.js](https://huggingface.co/docs/transformers.js/en/index). The first upload needs internet access to fetch the library and model. Processing happens in the browser.

When you open Plan, the app generates a Gemma 3 week if there is no saved plan for the upcoming Monday. **GENERATE WITH GEMMA 3** refreshes it. The planner sends contact sheets of the wardrobe images, names, and categories to Amazon Bedrock, then saves only the selected item IDs and brief explanations in localStorage. The server validates that every recommendation refers to a piece in the wardrobe.

If Bedrock rejects a request, check the selected AWS profile or bearer key, the Region, and access to the model there. If Plan reports a network error, check the machine's internet connection and VPN settings.

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
