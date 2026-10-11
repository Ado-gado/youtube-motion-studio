/* Local composition builder. No network calls, no project reset, no automatic save.
   Run inside After Effects: File > Scripts > Run Script File.
   Creates two native-layer compositions RU/EN in the existing project.
   Requires the sibling ae_timeline.json and assets folder. */
(function () {
    var root = File($.fileName).parent;
    var f = new File(root.fsName + '/ae_timeline.json');
    if (!f.exists) { alert('Missing ae_timeline.json beside this script.'); return; }
    f.encoding = 'UTF-8';
    if (!f.open('r')) { alert('Cannot read ae_timeline.json.'); return; }
    var raw = f.read(); f.close();
    // ae_timeline.json is generated locally from scene.js, never fetched from a site.
    var data;
    try { data = (typeof JSON !== 'undefined' && JSON.parse) ? JSON.parse(raw) : eval('(' + raw + ')'); }
    catch (e) { alert('Invalid local timeline: ' + e.toString()); return; }
    for (var i = 0; i < data.layers.length; i++) {
        var spec = data.layers[i];
        if (spec.type === 'image' && !new File(root.fsName + '/' + spec.file).exists) {
            alert('Missing asset: ' + spec.file); return;
        }
    }
    function rgb(hex) {
        return [parseInt(hex.substr(1, 2), 16) / 255, parseInt(hex.substr(3, 2), 16) / 255, parseInt(hex.substr(5, 2), 16) / 255];
    }
    function polygon(vertices) {
        var sh = new Shape(); sh.vertices = vertices; sh.closed = true;
        sh.inTangents = []; sh.outTangents = [];
        for (var i = 0; i < vertices.length; i++) { sh.inTangents.push([0, 0]); sh.outTangents.push([0, 0]); }
        return sh;
    }
    function animate(prop, times, values) {
        prop.setValuesAtTimes(times, values);
        for (var k = 1; k <= prop.numKeys; k++) {
            prop.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR);
            if (prop.isSpatial) { prop.setSpatialAutoBezierAtKey(k, false); prop.setSpatialContinuousAtKey(k, false); prop.setSpatialTangentsAtKey(k, [0, 0], [0, 0]); }
        }
    }
    var warnings = [], folder, imported = {};
    app.beginUndoGroup('Documentary Motion RU EN');
    try {
        if (!app.project) app.newProject();
        folder = app.project.items.addFolder('Documentary Motion');
        var assetsFolder = app.project.items.addFolder('Plague Assets'); assetsFolder.parentFolder = folder;
        for (var j = 0; j < data.layers.length; j++) {
            var asset = data.layers[j];
            if (asset.type === 'image' && !imported[asset.file]) {
                var options = new ImportOptions(new File(root.fsName + '/' + asset.file));
                imported[asset.file] = app.project.importFile(options); imported[asset.file].parentFolder = assetsFolder;
            }
        }
        var fontNames = {Lora: 'Lora-Regular', Onest: 'Onest-Regular', PTMono: 'PTMono-Regular', PTSerif: 'PTSerif-Bold', Oswald: 'Oswald-SemiBold'};
        var languages = ['ru', 'en'];
        for (var langIndex = 0; langIndex < languages.length; langIndex++) {
            var lang = languages[langIndex];
            var comp = app.project.items.addComp('Documentary Scene ' + lang.toUpperCase(), data.width, data.height, 1, data.duration, data.fps);
            comp.parentFolder = folder; comp.bgColor = rgb(data.paper);
            comp.comment = 'Native text and image layers; sampled 2D parallax, not a native 3D camera. Browser preview and AE appearance require comparison.';
            for (var n = 0; n < data.layers.length; n++) {
                var d = data.layers[n], layer, trimEnd = null, maskPath = null;
                if (d.type === 'image') {
                    layer = comp.layers.add(imported[d.file]);
                    layer.property('ADBE Transform Group').property('ADBE Anchor Point').setValue([d.pixelWidth / 2, d.pixelHeight / 2]);
                    if (d.sat < 1) {
                        var tint = layer.property('ADBE Effect Parade').addProperty('ADBE Tint');
                        tint.property(1).setValue([0, 0, 0]); tint.property(2).setValue([1, 1, 1]); tint.property(3).setValue((1 - d.sat) * 100);
                    }
                    if (d.shadow) {
                        var shadow = layer.property('ADBE Effect Parade').addProperty('ADBE Drop Shadow');
                        shadow.property(1).setValue(rgb('#101416')); shadow.property(2).setValue(27); shadow.property(3).setValue(135); shadow.property(4).setValue(27); shadow.property(5).setValue(32);
                    }
                } else if (d.type === 'text') {
                    var words = d.content || data.texts[lang][d.key]; layer = comp.layers.addText(words);
                    var source = layer.property('ADBE Text Properties').property('ADBE Text Document'), td = source.value;
                    td.resetCharStyle(); td.font = fontNames[d.font]; td.fontSize = d.size;
                    td.fillColor = rgb(d.color); td.applyFill = true; td.applyStroke = false;
                    td.justification = ParagraphJustification.LEFT_JUSTIFY; td.autoLeading = false; td.leading = d.size * 1.15; td.tracking = 0;
                    source.setValue(td);
                    if (source.value.font !== fontNames[d.font]) warnings.push('Font substitution: ' + fontNames[d.font] + ' > ' + source.value.font);
                    layer.property('ADBE Transform Group').property('ADBE Anchor Point').setValue([0, 0]);
                    var mask = layer.property('ADBE Mask Parade').addProperty('ADBE Mask Atom');
                    mask.maskMode = MaskMode.ADD; maskPath = mask.property('ADBE Mask Shape');
                    layer.label = 2;
                } else if (d.type === 'rect') {
                    layer = comp.layers.addSolid(rgb(d.color), d.id, d.w, d.h, 1, data.duration);
                } else if (d.type === 'path') {
                    layer = comp.layers.addShape();
                    var group = layer.property('ADBE Root Vectors Group').addProperty('ADBE Vector Group');
                    var contents = group.property('ADBE Vectors Group');
                    var path = contents.addProperty('ADBE Vector Shape - Group');
                    var curve = polygon(data.path); curve.closed = false; path.property('ADBE Vector Shape').setValue(curve);
                    var stroke = contents.addProperty('ADBE Vector Graphic - Stroke');
                    stroke.property('ADBE Vector Stroke Color').setValue(rgb(d.color)); stroke.property('ADBE Vector Stroke Width').setValue(3);
                    var trim = contents.addProperty('ADBE Vector Filter - Trim'); trimEnd = trim.property('ADBE Vector Trim End');
                    layer.property('ADBE Transform Group').property('ADBE Anchor Point').setValue([0, 0]);
                }
                layer.name = d.id + (d.type === 'text' ? ' [EDIT TEXT]' : ''); layer.inPoint = 0; layer.outPoint = data.duration;
                var textLeft = d.type === 'text' ? layer.sourceRectAtTime(0, false).left - 5 : -5;
                var times = [], pos = [], scales = [], rotations = [], opacities = [], masks = [], ends = [];
                for (var k = 0; k < d.samples.length; k++) {
                    var pair = d.samples[k], s = pair[1], scaleX = 100 * s.scale, scaleY = scaleX;
                    if (d.type === 'image') { scaleX *= d.w / d.pixelWidth; scaleY *= d.h / d.pixelHeight; }
                    times.push(pair[0]); pos.push([s.x, s.y + (d.type === 'text' ? d.size * (1-s.reveal)*s.scale : 0)]); scales.push([scaleX, scaleY]); rotations.push(s.rot); opacities.push(s.opacity * 100);
                    if (maskPath) { var dy=d.size*(1-s.reveal), top=-d.size-dy, bottom=.07*d.size-dy; masks.push(polygon([[-5,top],[d.width,top],[d.width,bottom],[-5,bottom]])); }
                    if (trimEnd) ends.push(s.reveal * 100);
                }
                var transform = layer.property('ADBE Transform Group');
                animate(transform.property('ADBE Position'), times, pos); animate(transform.property('ADBE Scale'), times, scales);
                animate(transform.property('ADBE Rotate Z'), times, rotations); animate(transform.property('ADBE Opacity'), times, opacities);
                if (maskPath) animate(maskPath, times, masks);
                if (trimEnd) animate(trimEnd, times, ends);
                layer.comment = d.type === 'text' ? 'Change Source Text to translate. Review line width and reveal mask after editing.' : 'Sampled from the shared browser timeline. Individual native properties remain editable.';
            }
            for (var m = 0; m < 3; m++) {
                var mt = [0, data.duration / 3, data.duration * 2 / 3][m], marker = new MarkerValue(['Start', 'Middle', 'End'][m]);
                comp.markerProperty.setValueAtTime(mt, marker);
            }
            comp.time = 2.8;
            if (lang === 'ru') comp.openInViewer();
        }
        alert('Created RU and EN compositions. Text layers are marked [EDIT TEXT]. Save with File > Save As.\nAE render has not been verified on this computer. Install included fonts before comparison.' + (warnings.length ? '\nFont warnings: ' + warnings.join('\n') : ''));
    } catch (e) { alert('Builder stopped: ' + e.toString() + '\nUndo the Documentary Motion group if needed.'); }
    finally { app.endUndoGroup(); }
}());
