// Injected into the real main.qml; all navigation and model code is production.
TestCase { id: mtpEvents; when: false }
function mtpCheck(condition, message) { if (!condition) throw new Error(message); }
function mtpWait(predicate, message) {
    for (var i = 0; i < 800 && !predicate(); ++i) mtpEvents.wait(10);
    mtpCheck(predicate(), message);
}
function mtpFind(item, predicate) {
    if (predicate(item)) return item;
    var children = item.children || [];
    for (var i = 0; i < children.length; ++i) {
        var found = mtpFind(children[i], predicate);
        if (found) return found;
    }
    return null;
}
function mtpClickPhone(uri, button) {
    var list = mtpFind(sidebar, function(item) { return item.positionViewAtIndex !== undefined; });
    var row;
    mtpWait(function() {
        var index = sidebar.entries.findIndex(function(item) { return item.id === "device:" + uri; });
        if (index < 0) return false;
        list.positionViewAtIndex(index, ListView.Contain);
        row = list.itemAtIndex(index);
        return row && row.button;
    }, "Missing phone row");
    mtpEvents.wait(30);
    mtpEvents.mouseClick(row.button, row.button.width / 2, 22, button || Qt.LeftButton);
}
function mtpLoaded(path) {
    mtpWait(function() { return engine.current_path === path && !engine.loading; }, "Location did not load: " + path);
    mtpCheck(engine.error_text === "", "MTP error: " + engine.error_text);
}
function mtpItem(name) {
    for (var i = 0; i < engine.item_count; ++i) {
        var item = JSON.parse(engine.item_json(i));
        if (item.name === name) return item;
    }
    throw new Error("Missing item: " + name);
}
function mtpOpenFolder(name) {
    var entry = mtpItem(name), target;
    mtpWait(function() {
        target = mtpFind(window.activePane, function(item) { return item.path === entry.path && item.is_dir === true && item.visible; });
        return !!target;
    }, "Missing folder delegate: " + name);
    // The delegate is destroyed during navigation; send both clicks through the stable content item.
    var point = target.mapToItem(window.contentItem, target.width / 2, target.height / 2);
    console.log("MTP_CASE_OPEN", name);
    mtpEvents.mouseDoubleClickSequence(window.contentItem, point.x, point.y, Qt.LeftButton);
    mtpLoaded(entry.path);
    return entry.path;
}
Timer {
    interval: 100; running: true
    onTriggered: {
        try {
            theme.reduceMotionSetting = true;
            window.width = 1000; window.height = 760;
            var startup = core.get_setting("mtpStartupPath");
            if (startup) {
                mtpLoaded(startup);
                mtpCheck(engine.read_only && engine.location_kind === "mtp", "MTP startup state lost");
                console.log("MTP_UI_TEST_STARTUP_PASS"); Qt.quit(); return;
            }
            var stay = core.get_setting("devicesTestRoot") + "/stay";
            window.showFiles(); engine.set_path(stay); sidebar.expanded = true;
            if (core.get_setting("mtpMissingService") === "true") {
                mtpEvents.wait(1800);
                mtpCheck(sidebar.drives.length === 0 && !engine.loading, "Missing optional service did not degrade gracefully");
                console.log("MTP_UI_TEST_MISSING_SERVICE_PASS"); Qt.quit(); return;
            }
            var root = "mtp://2f746573742f70686f6e65/";
            var second = "mtp://2f746573742f7365636f6e64/";
            mtpWait(function() { return sidebar.drives.length === 3; }, "Phone discovery failed");
            mtpClickPhone(root); mtpLoaded(root);
            mtpCheck(engine.read_only && engine.location_kind === "mtp", "MTP is not a read-only virtual location");
            mtpCheck(sidebar.activeId === "device:" + root, "Phone highlight missing");
            var storage = mtpOpenFolder("Internal storage");
            mtpCheck(engine.item_count === 5, "Folder listing or hidden-file filtering failed");
            var file = mtpItem("notes.txt");
            mtpCheck(file.size === 12345 && !file.is_dir, "File metadata lost");
            var camera = mtpOpenFolder("Camera");
            mtpCheck(engine.item_count === 0, "Empty folder not empty");
            engine.navigate_up(); mtpLoaded(storage);
            engine.go_back(); mtpLoaded(camera);
            engine.go_forward(); mtpLoaded(storage);
            engine.view_mode = "list"; mtpEvents.wait(200);
            var unicode = mtpOpenFolder("a # % π");
            mtpCheck(unicode.indexOf("%23") >= 0 && unicode.indexOf("%25") >= 0, "URI escaping lost");
            engine.navigate_up(); mtpLoaded(storage);
            window.activePane.selectAll();
            window.copySelection(true); window.trashSelection(); window.deleteSelection();
            mtpCheck(!confirmDialog.visible && !batchRename.visible, "Read-only actions opened mutation dialogs");
            mtpCheck(core.rename_item(file.path, "changed.txt").length > 0, "Core allowed MTP rename");
            var slow = mtpItem("Slow");
            engine.set_path(slow.path); engine.set_path(stay); mtpLoaded(stay);
            mtpEvents.wait(700); mtpCheck(engine.current_path === stay, "Stale listing changed current location");
            var count = window.tabs.length;
            mtpClickPhone(second, Qt.MiddleButton); mtpLoaded(second);
            mtpCheck(window.tabs.length === count + 1, "Phone middle-click did not open a new tab");
            mtpOpenFolder("Internal storage");
            mtpItem("Second phone only.txt");
            mtpCheck(sidebar.activeId === "device:" + second, "Second phone highlight wrong");
            console.log("MTP_CASE locked");
            mtpClickPhone("mtp://2f746573742f6c6f636b6564/");
            mtpWait(function() { return !engine.loading && engine.error_text.length > 0; }, "Locked phone error missing");
            mtpCheck(engine.item_count === 0, "Locked phone retained old rows");
            mtpClickPhone(root); mtpLoaded(root);
            console.log("MTP_CASE unplug");
            core.set_setting("mtpTestPresence", "absent");
            mtpWait(function() { return sidebar.drives.length === 0 && !engine.loading && engine.error_text.length > 0; }, "Unplug did not refresh sidebar and view");
            core.set_setting("mtpTestPresence", "present");
            mtpWait(function() { return sidebar.drives.length === 3; }, "Reconnect not discovered");
            mtpClickPhone(root); mtpLoaded(root);
            console.log("MTP_UI_TEST_ALL_PASS");
        } catch (error) { console.error("MTP_UI_TEST_FAIL", error.message); }
        Qt.quit();
    }
}
