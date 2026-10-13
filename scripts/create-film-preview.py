"""Build an isolated native UI preview with a simulated nudge receipt.

The temporary build has no backend resources. It always starts with --demo,
uses fictional fixtures and changes only the copied AppModel source. The
production application and its data are never changed.
"""
import argparse
import json
import pathlib
import plistlib
import shlex
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=pathlib.Path, default=ROOT / "build/film-preview")
args = parser.parse_args()
output = args.output.resolve()
source = output / "Sources"
source.mkdir(parents=True, exist_ok=True)
for path in (ROOT / "Sources").glob("*.swift"):
    shutil.copy2(path, source / path.name)
model_path = source / "AppModel.swift"
model = model_path.read_text()
old = 'if isDemo || !task.isOpen || task.isManual || nudgePending(task) { return true }'
assert model.count(old) == 1
model = model.replace(old, 'if !task.isOpen || task.isManual || nudgePending(task) { return true }')
marker = '    func nudge(_ task: TodoTask, retryUnknown: Bool = false) {\n'
assert model.count(marker) == 1
model = model.replace(marker, marker + '''        // Only this temporary UI preview can simulate a nudge.
        if isDemo {
            guard !nudgePending(task) else { return }
            requestingNudges.insert(task.conversationId)
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                guard let self,
                      let url = Bundle.main.url(forResource: "demo", withExtension: "json"),
                      let data = try? Data(contentsOf: url),
                      var value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                else { return }
                let now = Date().timeIntervalSince1970
                value["nudges"] = [["action_id":"demo-nudge", "task_id":task.id,
                    "conversation_id":task.conversationId, "status":"sent",
                    "created_at":now-3, "updated_at":now, "error":"", "attention":"演示回执"]]
                if let changed = try? JSONSerialization.data(withJSONObject: value),
                   let snapshot = try? self.decoder.decode(Snapshot.self, from: changed) {
                    self.snapshot = snapshot
                    self.showToast("演示催办已完成 · 未发送真实消息")
                }
                self.requestingNudges.remove(task.conversationId)
            }
            return
        }
''')
model_path.write_text(model)
app = output / "coindex Film Preview.app"
if app.exists():
    shutil.rmtree(app)
shutil.copytree(ROOT / "dist/coindex.app", app)
resources = app / "Contents/Resources"
shutil.rmtree(resources / "backend")
data_directory = output / "data"
data_directory.mkdir(exist_ok=True)
(data_directory / "pet-preferences.json").write_text(json.dumps({"enabled":False,"selectedID":"coindex:coindex-cat","size":112,"onDemand":False}))
snapshot = json.loads((ROOT / "build/readme-preview/light/coindex Light Preview.app/Contents/Resources/demo.json").read_text())
snapshot.pop("nudges", None)
(resources / "demo.json").write_text(json.dumps(snapshot, ensure_ascii=False))
native = app / "Contents/MacOS/coindex-native"
sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
arch = subprocess.check_output(["uname", "-m"], text=True).strip()
files = ["BrandGeometry", "DesignSystem", "Models", "PetAnimation", "Pets", "AppModel", "MainView", "ConnectionViews", "CodexTodoApp"]
subprocess.run(["swiftc", "-swift-version", "5", "-O", "-sdk", sdk,
                "-target", arch + "-apple-macosx14.0", "-module-cache-path", str(ROOT / "build/module-cache"),
                *[str(source / (name + ".swift")) for name in files], "-o", str(native)], check=True)
wrapper = app / "Contents/MacOS/coindex"
wrapper.write_text("#!/bin/sh\nexport CODEX_TODO_DATA_DIR=" + shlex.quote(str(data_directory)) +
                   "\nexport CODEX_HOME=" + shlex.quote(str(data_directory / "demo-codex")) +
                   "\nexec " + shlex.quote(str(native)) + " --demo --preview-light\n")
wrapper.chmod(0o755)
info_path = app / "Contents/Info.plist"
info = plistlib.loads(info_path.read_bytes())
info["CFBundleIdentifier"] = "org.coindex.film-preview"
info["CFBundleName"] = info["CFBundleDisplayName"] = "coindex Film Preview"
info_path.write_bytes(plistlib.dumps(info))
subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True, capture_output=True)
print(app)
