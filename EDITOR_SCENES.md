# Editable scene contract v1 · Motion Studio 0.4.0

The author uses the local Windows editor: manually edits words, font, position and text in/out times, reorders multiple ZIP fragments, then exports MP4. Prepare the requested scene, not an editor or website. No automatic translation, language tabs, narration generation or unrelated demo. If the scene already exists, adapt its text layers while preserving its requested artwork and motion.

## ZIP layout

Use `scripts/pack_scene.py` as before, with `motion-editor.json` adjacent to `scene.html`. An editable scene automatically gets a `motion-scene-*.zip` filename; it does NOT trigger the legacy Downloads render watcher. The ZIP still uses the verified schema-1 `motion-job.json` manifest. All images, models, audio, scripts and source/credit files must be local and included. No environment, node_modules, browser, rendered frames or final MP4 in this source ZIP.

Copy `runtime/motion-editor.js` from the package into the scene folder and load the local copy. Keep exact text ONLY in `motion-editor.json`; do not rasterize letters into images or duplicate labels in JavaScript. Declare every editable screen-text layer with a stable ASCII id. Maximum 200 text layers per scene in v1; no artificial ten-fragment limit in the project editor.

```json
{
  "schema": 1,
  "texts": [{
    "id": "person_name",
    "label": "Имя персонажа",
    "text": "Точные слова автора",
    "font": "Lumios Brush",
    "fontSources": ["Lumios Brush", "Lumios Brush Regular"],
    "weight": "400",
    "size": 90,
    "color": "#f3eddd",
    "x": 160,
    "y": 850,
    "maxWidth": 1500,
    "maxLines": 3,
    "lineHeight": 1.2,
    "start": 1.2,
    "end": 5.8,
    "enter": 0.65,
    "exit": 0.3
  }]
}
```

Coordinates are scene pixels; y is the baseline of the first line. Times are absolute seconds within the original scene. `end` is the time when text is fully gone; exit begins at `end-exit`. Enter + exit must fit inside end-start. Text is absent outside [start,end). The local UI exposes words/font/size/color/x/y/start/end/enter/exit. maxWidth, maxLines, lineHeight, shadow are authored constraints preserved in the config; v1 does not expose every possible design setting.

## Scene integration

The following is an integration fragment, not a creative template. Keep the composition and camera tailored to the actual brief. Do not turn every scene into this fragment's layout.

```javascript
let editable;
async function initialize() {
  try {
    editable = await MotionEditor.load('motion-editor.json');
    // Load all other local scene assets before READY.
    await loadSceneAssets();
    await window.seek(0);
    window.READY = true;
  } catch (error) { window.ERROR = String(error.message || error); }
}
window.seek = async function(seconds) {
  // Deterministically clear and draw the complete scene for this time.
  drawBackgroundAndObjects(seconds);
  // Draw this on every seek; do not wrap it in a second hardcoded time window.
  editable.drawText(ctx, 'person_name', seconds);
  drawForegroundOccluders(seconds);
};
initialize();
```

`ctx` is the actual Canvas 2D context. All HTML/Canvas/WebGL effects must be seekable; Canvas text can be integrated into a composited scene, but the helper alone does not rewrite DOM text or 3D materials. Stop idle RAF loops in capture mode. Export capture rules remain in WORKFLOW.md. For mixed DOM/transparent canvases use screenshot capture; only a complete opaque 2D composition may use accelerated canvas capture.

The helper awaits the genuine local font, measures words using real glyph metrics, wraps at maxWidth, animates a rise through a fixed mask with cubic ease-out, removes the reveal mask when fully open, adds a shadow and applies the declared exit. It throws on too many lines, an unbreakable word too wide, or a fully held text bounding box outside the canvas. It does not guarantee absence of object occlusion or fit under an arbitrary camera at every intermediate frame: inspect the actual scene and transitions. Do not disable checks merely to hide layout problems.

Pass through author camera transforms if appropriate. Any `drawText` options must preserve the editable words, selected font, size and declared timing; don't override those with hardcoded defaults. Set animation/layout expressions relative to the editable values. A timeline must not cut text off via a separate scene gate before its configured end. When a text belongs only to a particular composition, design its position/motion across the scene and verify a timing edit; otherwise document its constraints instead of claiming unrestricted editing.

`MotionEditor.load` sets MOTION_EDITOR_APPLIED and MOTION_TEXT_LAYOUT_READY after reading config/fonts; actual per-layer layout is measured on first draw and recalculated for changed values. The flag is an integration signal, not proof of visual approval. `READY` is still the scene's responsibility. Render and preview fail if a declared editable scene does not apply the protocol.

## Fonts and cloud validation

Read LOCAL_FONTS.md. Lumios Brush stays on the final-render PC; never request an Adobe file upload or bundle it into GitHub/ZIP. Preserve the exact selected family and local source names. A scene-adjacent `local-fonts.json` may declare the same faces. In the editor, that declaration is rebuilt from the user's current text-layer choices, so selecting another installed font changes both preview and export. No silent fallback.

An unavailable cloud font does not block asset preparation and packaging; report `font_status=pending_local_verification`. Do not assert final text appearance has passed in that environment. Test schema, assets, seeks/transitions as available and state what remains unverified. On the PC a missing font stops preview/export with an explicit message. Do not set READY early to bypass font/layout errors.

## Verification and handoff

1. Check manifest/UTF-8, local assets, exact words, ids and valid timing against requested duration.
2. With a genuinely available requested font, change a copy of one layer's words and start/end; compare seek frames to prove that edits affect pixels. Restore the author's values. Check all transition boundary frames and fully readable holds. When cloud fonts are unavailable, mark those checks pending on PC; do not claim they ran.
3. Package the current scene, e.g. `.venv/bin/python scripts/pack_scene.py scenes/<actual-id>/scene.html --duration <actual-duration> --title <actual-id>`. Use actual width/fps and `--audio` if the requested sound is included. The packer validates the JSON structure and checksums; it does not prove visual editability by itself.
4. Include scene-adjacent ASSETS.md and CREDITS.md. Verify the download URL with a real GET and inspect the downloaded ZIP/manifest. Deliver that real `motion-scene-*.zip` link and state: source archive ready, local edits/render pending. No invented links, new website, deployment or complete cloud render just to deliver a ZIP.

Old ZIPs without this contract remain viewable/renderable in the local editor, with text controls unavailable. A flat MP4 is not a text-editable scene. Repackage an adapted source as a new archive; don't silently replace a ZIP already referenced by a saved project.
