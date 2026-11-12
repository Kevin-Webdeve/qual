# Qual 2.3 — 4K and Source FPS Export

A Windows desktop tool with three local workflows: export a standard mobile-compatible MP4, enhance a video, or experiment with CompressBase's public Quality + FPS helper. Video processing stays on your computer. No TikTok account or API key is required. The app does not post to TikTok.

## Open the application

Double-click **Launch Qual** (Windows may hide its `.bat` extension), or open **dist/2.3/Qual/Qual.exe**. The title must say **Qual 2.3**. Keep the entire `dist/2.3/Qual` folder together when copying the app to another PC. The portable build includes Python, FFmpeg, and the local method runtime. Older builds are kept separately so an open old version does not prevent the update.

## Mobile compatible: start here if phone playback is delayed

1. Choose the original edit when possible.
2. Leave **Mobile compatible (recommended)** selected in the Method tab.
3. Leave **Mobile resolution → Keep original size** and **Mobile frame rate → Keep source (normal speed)** to retain your recording's 4K dimensions and 120 fps timing. **Limit to 1080p**, **Automatic (30/60 fps)**, and explicit **30/60 fps** are available for comparison.
4. Click **Export mobile MP4**. Transfer the exported file to your phone and check it locally, then upload that new file to TikTok for a comparison.

This mode re-encodes H.264 High-profile video with one AAC-LC stereo audio track when sound exists. The default **Keep source (normal speed)** passes the source's presentation timestamps through to the encoder, preserving its frame count and playback timing, including native 120 fps, fractional rates such as 119.88 fps, and variable timing. It does not generate extra frames or retime frame counts onto a 30/60 fps timeline. Footage that is already encoded for slow motion stays at its existing playback speed; this option does not infer real-world capture speed from camera settings.

The full image and source dimensions are preserved by default, including landscape 3840 × 2160 and portrait 2160 × 3840. Normal square-pixel 4K recordings retain their dimensions; non-square pixels are normalized and odd dimensions are rounded down to even values for H.264. HDR is converted to SDR. No motion interpolation or picture enhancement is applied. Look and Export tab adjustments belong to Enhance mode; mobile resolution and frame rate are set on the Method tab. This is a new video encode, not a lossless container-only patch.

The encoder selects its H.264 level for the actual output rather than forcing the previous Level 4.2 restriction. Exports above 1080p allow bitrate ceilings of 100 Mbps above 60 fps, 60 Mbps above 30 fps, and 40 Mbps at lower rates; 1080p and smaller use 40/20/12 Mbps. CRF encoding still determines the actual bitrate. Keeping 4K/120 fps can produce larger files and requires suitable decoding hardware. The selected resolution and frame timing control the local file; they do not guarantee TikTok's delivered resolution, FPS, or playback smoothness.

For a constant frame rate, Automatic chooses 30 fps for sources at or below 30.1 fps, and 60 fps for higher-rate footage. Explicit 30/60 fps choices are also available. These options sample the existing timeline by dropping or duplicating frames, rather than slowing it down. Use them for a comparison if the source-rate export lags in TikTok. Audio is resampled using its timestamps, with silence padding only as needed to cover the video. The output ends at the video end, with no experimental audio tail. When converting a file previously prepared by Qual's Quality + FPS method, the clean stereo duplicate is preferred and the special audio track is discarded. A fresh export from the original edit avoids an additional generation of compression.

**A local export cannot verify TikTok's subsequent mobile playback.** A file that works in the phone gallery but lags inside TikTok points toward the platform's processing or playback path; the exact cause still needs a real-file/platform comparison. Upload the mobile-compatible export directly rather than applying Quality + FPS to it again.

## Quality + FPS: experimental preparation

1. Choose your original MP4, MOV, or M4V video.
2. In **Method**, select **Quality + FPS (preserve video)**.
3. Click **Prepare Quality + FPS** and choose a new filename.
4. Wait for preparation and verification to finish. Use **Open output folder** to find the MP4.
5. **Open verification report** shows the JSON report saved beside it. Upload the MP4 yourself using your preferred TikTok workflow.

Powered by [CompressBase](https://compressbase.com/method-api). This mode runs their publicly offered **local SL/SR helper**, bundled without changes. It does not call their legacy metadata-patch endpoint or reproduce their other protected variants.

The encoded H.264, HEVC, or AV1 video is copied without sharpening, scaling, tone mapping, or video re-encoding. Source frame timing can be preserved at 60 fps, 120 fps, and variable rates. The app first converts audio to AAC-LC stereo, or creates silent audio when the source has none. The helper adds a short silent audio tail, a special SL/SR channel layout, and a clean stereo duplicate. The container may be about 0.35 seconds longer. Some players may handle the special audio layout differently. The output retains the required `Patched by Compressbase` comment.

Before saving, Qual compares every compressed video packet's size/hash and relative presentation timestamp with the original. A drift over 1 ms, missing packet, changed packet, or decode failure stops the operation. Both audio tracks are checked; the special track's decoded channels are relabeled only during the decoder check. The saved file is not changed by that check. Files up to 8 GiB are supported by the local helper; free disk space is also needed for temporary files.

**These are local file checks. They do not verify or guarantee TikTok playback resolution, frame rate, compression behavior, or acceptance.** A preserved high frame rate and this nonstandard audio layout may work differently across playback paths. If a TikTok upload looks slow or delayed on phones, use Mobile compatible from the original edit. The report does not claim that TikTok's compression has been bypassed. Quality + FPS typically adds some data; it is not the smaller-file compression mode.

## Enhance + export: improve the picture

1. Select **Enhance + export** in the Method tab.
2. In **Look**, choose Balanced, Crisp edits, Low light, Natural, or Animation / gaming. Fine-tune adaptive or classic sharpening, temporal noise reduction, contrast, color, brightness, and shadow/gamma lift. Optional gradient cleanup can reduce banding but may soften texture.
3. In **Export**, choose a portrait canvas at 720p, 1080p, or 4K, or keep the original size. Fit preserves the full image with black bars. Center crop fills the canvas; adjust its horizontal and vertical position to keep your subject visible.
4. Keep the source frame rate, or choose 30/60 fps. These frame-rate choices alone duplicate/drop frames. **Smooth to 60 fps** generates in-between frames for sources below 60 fps; it is slow and can warp edges, text, or fast motion. It overrides the frame-rate selection for those sources.
5. Choose **Maximum detail**, **High quality**, or **Smaller file**. Slow encoding is the default to improve compression efficiency. Faster modes are available.
6. Move the frame slider and **Refresh before / after**. Both stills use the same crop/canvas. **100% detail** opens a full-resolution comparison: drag to pan, and move the divider. Still previews include temporal-noise-reduction pre-roll but exclude motion interpolation.
7. **Make 3s sample** encodes up to three seconds from the selected time with your actual export settings and opens it in the default video player. Samples are temporary; copy one elsewhere if you want to keep it.
8. Export the full MP4 to a new filename. If desired, choose that enhanced MP4 as the input and run Quality + FPS afterward.

**Advice** can analyze three source frames and metadata. It suggests conservative settings, flags dark/clipped shadows, and warns about upscaling, large crops, strong cleanup, or synthetic motion. Recommendations are optional, do not measure the entire video, and cannot infer creative intent.

HDR PQ/HLG footage is tone-mapped to SDR BT.709 in Enhance mode. Both workflows show SDR previews on screen; Quality + FPS retains original HDR video. Color conversion uses source tags when available, with HD/SD matrix assumptions for untagged footage. Incorrect source tags may still require manual correction in an editor. Interlaced sources are deinterlaced in Enhance mode.

Enhance exports use H.264 High-profile video, AAC audio when present, limited-range BT.709 color tags, and fast-start MP4. Maximum detail uses CRF 16, High quality CRF 18, and Smaller file CRF 22. CRF is not a target size: output size depends on content and may exceed a heavily compressed original. A smaller canvas generally reduces file size. Upscaling cannot reconstruct missing captured detail.

## Original-file protection and cancellation

Neither workflow can save over its source file. Output is staged in temporary storage, and the chosen destination is replaced only after processing succeeds. Cancelling stops the worker and cleans unfinished output. Quality + FPS adds a `.quality-fps.json` report beside its output. This version handles one file at a time.

## Run or rebuild from source

Requires Python 3.12+ with Tk support, Windows x64 for the bundled method runtime, and internet access during initial setup only.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools/setup_method.py
.\.venv\Scripts\python.exe app.py
```

Setup downloads the public method helper and an official Node LTS archive. It verifies the archive's SHA256 against Node's published checksums and records provenance. Runtime helper integrity is checked against that record. Processing does not download updates or send media to a server.

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe build.py
```

Processing tests: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
Hidden Windows UI workflow test: `.\.venv\Scripts\python.exe tests/check_desktop.py`.
Packaged diagnostic: `dist/2.3/Qual/Qual.exe --self-check test-artifacts/bundle-check.json`.

## References and components

- [CompressBase's public method documentation](https://compressbase.com/method-api)
- [FFmpeg filter documentation](https://www.ffmpeg.org/ffmpeg-filters.html)
- Bundled components and notices: `THIRD_PARTY.md` and `dist/2.3/Qual/licenses/`.
- PREX reference reviewed: [public FAQ](https://prexoptimizer.xyz/). Its page advertises container-only preservation of 120 fps sources; its FAQ says TikTok displays up to 60 fps. Those claims are not verified by Qual, and no PREX code, accounts, or protected service access are used by this app.

Qual is independent and is not affiliated with TikTok or CompressBase. The upstream method helper is credited in its UI and documentation.
