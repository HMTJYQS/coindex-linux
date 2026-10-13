"""Create isolated UI preview bundles. No production task data or backend connections."""
import argparse, copy, json, pathlib, plistlib, shutil, subprocess
root = pathlib.Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=pathlib.Path, default=root/"build/design-preview")
args = parser.parse_args()
source = root / "dist/coindex.app"
for appearance in ("light", "dark"):
    directory = args.output.resolve() / appearance
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
    wrapper.write_text("#!/bin/sh\nexport CODEX_TODO_DATA_DIR="+shlex.quote(str(data))+"\nexport CODEX_HOME="+shlex.quote(str(data/"demo-codex"))+"\nexec "+shlex.quote(str(native))+" --demo --preview-"+appearance+"\n")
    wrapper.chmod(0o755)
    infofile = app / "Contents/Info.plist"
    info = plistlib.loads(infofile.read_bytes())
    info["CFBundleIdentifier"] = "org.coindex.design-preview."+appearance
    info["CFBundleName"] = info["CFBundleDisplayName"] = "coindex " + appearance.title() + " Preview"
    infofile.write_bytes(plistlib.dumps(info))
    demo = app / "Contents/Resources/demo.json"
    snapshot = json.loads(demo.read_text())
    snapshot["tasks"][0]["title"] = "为文档搜索增加全文检索"
    running = copy.deepcopy(snapshot["tasks"][1])
    running.update(id="demo-running", conversation_id="dev-server:demo-running", thread_id="demo-running",
                   host="dev-server", conversation_title="知识库摘要生成", kind="running",
                   title="让知识库文档自动生成摘要", detail="为新增文档生成便于阅读与检索的摘要",
                   progress="正在整理第三组文档，前两组摘要已完成", next_action="摘要生成后核对内容与引用", priority=2)
    active_conversation = copy.deepcopy(snapshot["conversations"][0])
    active_conversation.update(id=running["conversation_id"], thread_id=running["thread_id"], title=running["conversation_title"],
                               summary=running["detail"], analysis_state="running", active=True)
    snapshot["conversations"].insert(0, active_conversation)
    manual = copy.deepcopy(running)
    manual.update(id="demo-manual", kind="manual", title="整理本周应用发布计划", detail="汇总版本和验收时间。", host="manual")
    snapshot["tasks"].insert(0, running)
    snapshot["tasks"].append(manual)
    demo.write_text(json.dumps(snapshot, ensure_ascii=False))
    subprocess.run(["codesign","--force","--deep","--sign","-",str(app)], check=True, capture_output=True)
    print(app)
