import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    var model: AppModel?
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Appearance overrides are available only in the isolated demo preview.
        guard ProcessInfo.processInfo.arguments.contains("--demo") else { return }
        if ProcessInfo.processInfo.arguments.contains("--preview-dark") { NSApp.appearance = NSAppearance(named: .darkAqua) }
        if ProcessInfo.processInfo.arguments.contains("--preview-light") { NSApp.appearance = NSAppearance(named: .aqua) }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated { model?.shutdown() }
    }
}

@main
struct CoindexApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel()
    var body: some Scene {
        Window("coindex", id: "main") {
            MainView().environmentObject(model).onAppear { delegate.model = model; model.pet.connect(model) }
        }.defaultSize(width: 1200, height: 820)
            .commands {
                CommandGroup(replacing: .appSettings) {
                    Button("设置…") { model.showSettings = true }.keyboardShortcut(",")
                }
                CommandGroup(after: .newItem) {
                    Button("新建待办…") { model.editManual() }.keyboardShortcut("n")
                    Button("立即更新") { model.sync() }.keyboardShortcut("r").disabled(model.updateDisabled)
                    Button(model.isOffDuty ? "提前上班" : "下班") { model.toggleWorkday() }.disabled(model.isFinishingWorkday || model.isDemo)
                }
                CommandMenu("宠物") { PetMenu(pet: model.pet) }
            }
        MenuBarExtra {
            MenuContent().environmentObject(model)
        } label: {
            Image("MenuIcon").renderingMode(.template).resizable().frame(width: 18, height: 18)
            if model.openCount > 0 { Text("\(model.openCount)") }
        }
    }
}

struct MenuContent: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.openWindow) var openWindow
    var body: some View {
        Text("coindex · \(model.openCount) 项待办")
        Divider()
        ForEach(Array(model.tasks.prefix(5))) { task in
            Button(task.title) { model.selectedTaskId = task.id; openWindow(id: "main"); NSApp.activate(ignoringOtherApps: true) }
        }
        Divider()
        Button("打开 coindex") { openWindow(id: "main"); NSApp.activate(ignoringOtherApps: true) }
        Button("新建待办…") { openWindow(id:"main"); NSApp.activate(ignoringOtherApps:true); model.editManual() }
        Button(model.isOffDuty ? "已下班，更新暂停" : model.syncing ? "正在更新…" : "立即更新") { model.sync() }.disabled(model.updateDisabled)
        Button(model.isOffDuty ? "提前上班" : "下班") { model.toggleWorkday() }.disabled(model.isFinishingWorkday || model.isDemo)
        if model.syncing {
            Button(model.isCancelling ? "正在中止…" : "中止当前更新") { model.cancelSync() }.disabled(model.isCancelling)
        }
        Button(model.snapshot?.settings.automatic == true ? "暂停自动更新" : "恢复自动更新") {
            model.settings(["automatic": !(model.snapshot?.settings.automatic ?? false)])
        }
        Divider()
        PetMenu(pet: model.pet)
        Divider()
        Button("退出 coindex") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }
}
