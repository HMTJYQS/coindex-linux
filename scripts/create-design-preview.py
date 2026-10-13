"""Create isolated UI preview bundles. No production task data or backend connections."""
import copy, json, pathlib, plistlib, shutil, subprocess
root = pathlib.Path(__file__).resolve().parent.parent
source = root / "dist/coindex.app"
for appearance in ("light", "dark"):
    directory = root / "build/design-preview" / appearance
    app = directory / ("coindex " + appearance.title() + " Preview.app")
    data = directory / "data"
    if app.exists(): shutil.rmtree(app)
    shutil.copytree(source, app)
    data.mkdir(parents=True, exist_ok=True)
    (data / "pet-preferences.json").write_text(json.dumps(dict(enabled=False,selectedID="coindex:coindex-cat",size=112,onDemand=False)))
    native = app / "Contents/MacOS/coindex-native"
    (app / "Contents/MacOS/coindex").rename(native)
    wrapper = app / "Contents/MacOS/coindex"
    # This wrapper only launches our built native binary with isolated demo arguments.
    import shlex
    wrapper.write_text("#!/bin/sh\nexport CODEX_TODO_DATA_DIR="+shlex.quote(str(data))+"\nexec "+shlex.quote(str(native))+" --demo --preview-"+appearance+"\n")
    wrapper.chmod(0o755)
    infofile = app / "Contents/Info.plist"
    info = plistlib.loads(infofile.read_bytes())
    info["CFBundleIdentifier"] = "org.coindex.design-preview."+appearance
    info["CFBundleName"] = info["CFBundleDisplayName"] = "coindex " + appearance.title() + " Preview"
    infofile.write_bytes(plistlib.dumps(info))
    demo = app / "Contents/Resources/demo.json"
    snapshot = json.loads(demo.read_text())
    running = copy.deepcopy(snapshot["tasks"][1])
    running.update(id="demo-running", kind="running", title="为文档搜索增加全文检索", progress="正在构建检索索引，已完成文档解析", next_action="索引完成后验证搜索结果和延迟", priority=2)
    manual = copy.deepcopy(running)
    manual.update(id="demo-manual", kind="manual", title="整理本周应用发布计划", detail="汇总版本和验收时间。", host="manual")
    snapshot["tasks"].insert(0, running)
    snapshot["tasks"].append(manual)
    demo.write_text(json.dumps(snapshot, ensure_ascii=False))
    subprocess.run(["codesign","--force","--deep","--sign","-",str(app)], check=True, capture_output=True)
    print(app)
