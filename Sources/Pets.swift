import AppKit
import Combine
import ImageIO
import SwiftUI
import UniformTypeIdentifiers
import Carbon

final class PetArtwork: Identifiable {
    let id: String
    let name: String
    let description: String
    let url: URL
    let rows: Int
    private let atlas: CGImage
    private var cache: [Int: NSImage] = [:]

    init?(id: String, name: String, description: String = "", url: URL) {
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
              image.width == 1536, image.height == 1872 || image.height == 2288,
              ![CGImageAlphaInfo.none, .noneSkipFirst, .noneSkipLast].contains(image.alphaInfo) else { return nil }
        self.id = id; self.name = name; self.description = description; self.url = url
        self.atlas = image; self.rows = image.height / PetAnimation.cellHeight
    }

    func image(_ frame: PetFrame) -> NSImage? {
        let key = frame.row * 8 + frame.column
        if let image = cache[key] { return image }
        guard (0..<rows).contains(frame.row), (0..<8).contains(frame.column),
              let cell = atlas.cropping(to: CGRect(x: frame.column * 192, y: frame.row * 208, width: 192, height: 208)) else { return nil }
        let image = NSImage(cgImage: cell, size: NSSize(width: 192, height: 208))
        cache[key] = image
        return image
    }

    static func load(customDirectory: URL, codexDirectory: URL = URL(fileURLWithPath: NSHomeDirectory() + "/.codex/pets")) -> [PetArtwork] {
        let names = [("codex", "Codex"), ("dewey", "Dewey"), ("fireball", "Fireball"),
                     ("hoots", "Hoots"), ("rocky", "Rocky"), ("seedy", "Seedy"),
                     ("stacky", "Stacky"), ("bsod", "BSOD"), ("null-signal", "Null Signal")]
        var builtins = names.compactMap { id, name -> PetArtwork? in
            guard let url = Bundle.main.url(forResource: id, withExtension: "webp", subdirectory: "Pets") else { return nil }
            return PetArtwork(id: id, name: name, url: url)
        }
        var custom: [PetArtwork] = []
        let bundledDirectory = Bundle.main.resourceURL?.appendingPathComponent("CustomPets", isDirectory: true)
        for directory in [customDirectory, bundledDirectory, codexDirectory].compactMap({ $0 }) {
            let children = (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? []
            for folder in children.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
                guard let data = try? Data(contentsOf: folder.appendingPathComponent("pet.json")),
                      let info = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let name = info["displayName"] as? String,
                      let path = info["spritesheetPath"] as? String else { continue }
                let url = folder.appendingPathComponent(path).resolvingSymlinksInPath()
                guard url.path.hasPrefix(folder.resolvingSymlinksInPath().path + "/") else { continue }
                let prefix = directory == codexDirectory ? "custom:" : "coindex:"
                let id = prefix + ((info["id"] as? String) ?? folder.lastPathComponent)
                if !custom.contains(where: { $0.id == id }), let pet = PetArtwork(id: id, name: name,
                    description: info["description"] as? String ?? "", url: url) { custom.append(pet) }
            }
        }
        builtins.insert(contentsOf: custom, at: 0)
        return builtins
    }
}

struct PetPreferences: Codable {
    var enabled = true
    var selectedID = "coindex:coindex-cat"
    var size = PetAnimation.defaultSize
    var onDemand = false
    var x: Double?
    var y: Double?
}

final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

@MainActor
final class PetController: NSObject, ObservableObject {
    @Published private(set) var artwork: [PetArtwork] = []
    @Published private(set) var preferences = PetPreferences()
    @Published private(set) var state = PetState.idle
    @Published private(set) var activities: [TodoTask] = []
    @Published private(set) var visible = false
    @Published var error = ""
    private weak var model: AppModel?
    private var panel: PetPanel?
    private var tray: NSPopover?
    private var subscription: AnyCancellable?
    private var clickMonitor: Any?
    private var hotKey: EventHotKeyRef?
    private var hotKeyHandler: EventHandlerRef?
    private var preferencesURL: URL?
    private var customDirectory: URL?
    private var connected = false
    var selected: PetArtwork? { artwork.first { $0.id == preferences.selectedID } ?? artwork.first { $0.id == "coindex:coindex-cat" } ?? artwork.first }
    var statusTitle: String {
        switch state {
        case .waiting: return "需要你处理"
        case .failed: return "更新遇到问题"
        case .review: return "结果待校对"
        case .running: return "正在工作"
        default: return model?.isOffDuty == true ? "已下班" : "coindex"
        }
    }

    func connect(_ model: AppModel) {
        guard !connected else { return }
        connected = true; self.model = model
        preferencesURL = model.dataDirectory.appendingPathComponent("pet-preferences.json")
        customDirectory = model.dataDirectory.appendingPathComponent("pets", isDirectory: true)
        if let url = preferencesURL, let data = try? Data(contentsOf: url),
           let saved = try? JSONDecoder().decode(PetPreferences.self, from: data) {
            preferences = saved
            preferences.size = min(224, max(80, saved.size.isFinite ? saved.size : 112))
        }
        reloadArtwork()
        subscription = model.objectWillChange.debounce(for: .milliseconds(60), scheduler: RunLoop.main).sink { [weak self] _ in
            MainActor.assumeIsolated { self?.updateActivity() }
        }
        updateActivity()
        registerShortcut()
        clickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.preferences.onDemand, self.tray?.isShown != true else { return }
                self.hide(persist: false)
            }
        }
        if preferences.enabled && !preferences.onDemand { show() }
    }

    func reloadArtwork() {
        guard let directory = customDirectory else { return }
        let home = model?.snapshot?.settings.codexHome ?? ""
        let root = home.isEmpty ? (ProcessInfo.processInfo.environment["CODEX_HOME"] ?? NSHomeDirectory() + "/.codex") : (home as NSString).expandingTildeInPath
        artwork = PetArtwork.load(customDirectory: directory, codexDirectory: URL(fileURLWithPath: root).appendingPathComponent("pets"))
        if selected == nil { error = "缺少宠物素材，请重新构建 coindex。" }
    }

    func updateActivity() {
        guard let model else { return }
        let tasks = (model.snapshot?.tasks ?? []).filter { $0.isOpen && !$0.isSnoozed }
        func rank(_ task: TodoTask) -> Int {
            PetAnimation.priority(task.kind == "decision" || task.kind == "continue" ? .waiting : task.kind == "review" ? .review : task.kind == "running" ? .running : .idle)
        }
        activities = tasks.sorted { rank($0) == rank($1) ? ($0.priority == $1.priority ? $0.updatedAt > $1.updatedAt : $0.priority < $1.priority) : rank($0) < rank($1) }
        if tasks.contains(where: { $0.kind == "decision" || $0.kind == "continue" }) { state = .waiting }
        else if !model.error.isEmpty || !(model.snapshot?.modelError ?? "").isEmpty { state = .failed }
        else if tasks.contains(where: { $0.kind == "review" }) { state = .review }
        else if model.syncing || tasks.contains(where: { $0.kind == "running" }) { state = .running }
        else { state = .idle }
    }

    func setEnabled(_ value: Bool) {
        preferences.enabled = value; save()
        if value { show() } else { hide(persist: false) }
    }
    func select(_ id: String) { preferences.selectedID = id; resize(); save(); if preferences.enabled { show() } }
    func setSize(_ size: Double) { preferences.size = min(224, max(80, size)); resize(); save() }
    func setOnDemand(_ value: Bool) { preferences.onDemand = value; save(); if preferences.enabled { show() } }
    func toggle() { visible ? hide() : setEnabled(true) }
    func wake() {
        setEnabled(true)
        panel?.makeKey()
        func findSprite(_ view: NSView) -> PetSpriteView? {
            if let sprite = view as? PetSpriteView { return sprite }
            return view.subviews.compactMap { findSprite($0) }.first
        }
        if let content = panel?.contentView, let sprite = findSprite(content) { panel?.makeFirstResponder(sprite) }
    }

    func show() {
        if panel == nil {
            let created = PetPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            created.title = "coindex 宠物"
            created.isOpaque = false; created.backgroundColor = .clear; created.hasShadow = false
            created.level = .floating; created.hidesOnDeactivate = false
            created.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
            created.isReleasedWhenClosed = false
            created.contentView = NSHostingView(rootView: PetOverlay(pet: self))
            panel = created
            resize()
            if let x = preferences.x, let y = preferences.y, x.isFinite, y.isFinite {
                created.setFrameOrigin(NSPoint(x: x, y: y))
            } else if let screen = NSScreen.main {
                created.setFrameOrigin(NSPoint(x: screen.visibleFrame.maxX - created.frame.width - 28, y: screen.visibleFrame.minY + 24))
            }
        }
        if let panel { panel.setFrameOrigin(clamped(panel.frame.origin, size: panel.frame.size)) }
        visible = true; panel?.orderFrontRegardless()
    }

    func hide(persist: Bool = true) {
        tray?.close(); panel?.orderOut(nil); visible = false
        if persist { preferences.enabled = false; save() }
    }

    private func resize() {
        guard let panel else { return }
        let height = preferences.selectedID == "mini" ? 48 : preferences.size * 208 / 192 + 52
        let size = NSSize(width: max(196, preferences.size + 24), height: height)
        panel.setFrame(NSRect(origin: clamped(panel.frame.origin, size: size), size: size), display: true)
    }

    func clamped(_ point: NSPoint, size: NSSize) -> NSPoint {
        let center = NSPoint(x: point.x + size.width / 2, y: point.y + size.height / 2)
        let screens = NSScreen.screens
        let screen = screens.first { $0.visibleFrame.contains(center) } ?? screens.min {
            hypot($0.frame.midX - center.x, $0.frame.midY - center.y) < hypot($1.frame.midX - center.x, $1.frame.midY - center.y)
        }
        guard let bounds = screen?.visibleFrame else { return point }
        return NSPoint(x: min(max(bounds.minX, point.x), max(bounds.minX, bounds.maxX - size.width)),
                       y: min(max(bounds.minY, point.y), max(bounds.minY, bounds.maxY - size.height)))
    }

    func moved() {
        guard let panel else { return }
        preferences.x = panel.frame.minX; preferences.y = panel.frame.minY; save()
    }

    func openPreferences() { openMain(); model?.showPetSettings = true }
    func newTodo() { openMain(); model?.editManual() }
    func openTask(_ task: TodoTask) { model?.selectedTaskId = task.id; model?.filter = "all"; tray?.close(); openMain() }
    func openMain() {
        NSApp.activate(ignoringOtherApps: true)
        if let window = NSApp.windows.first(where: { $0 !== panel && $0.title == "coindex" }) {
            if window.isMiniaturized { window.deminiaturize(nil) }
            window.makeKeyAndOrderFront(nil)
        } else { model?.reopenMainWindow?() }
    }

    func showActivity(relativeTo view: NSView) {
        if tray?.isShown == true { tray?.close(); return }
        let popover = NSPopover()
        popover.behavior = .transient
        popover.contentViewController = NSHostingController(rootView: PetActivityTray(pet: self))
        popover.contentSize = NSSize(width: 360, height: 380)
        tray = popover
        popover.show(relativeTo: view.bounds, of: view, preferredEdge: .minY)
    }

    func contextMenu(event: NSEvent, in view: NSView) {
        let menu = NSMenu()
        for (name, action) in [("更换宠物…", #selector(changePet)), ("打开 coindex", #selector(openMainAction)),
                               ("新建待办…", #selector(newTodoAction)), ("隐藏宠物", #selector(hideAction))] {
            let item = NSMenuItem(title: name, action: action, keyEquivalent: ""); item.target = self; menu.addItem(item)
        }
        NSMenu.popUpContextMenu(menu, with: event, for: view)
    }
    @objc private func changePet() { openPreferences() }
    @objc private func openMainAction() { openMain() }
    @objc private func newTodoAction() { newTodo() }
    @objc private func hideAction() { hide() }

    private func save() {
        guard let url = preferencesURL else { return }
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            try JSONEncoder().encode(preferences).write(to: url, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        } catch { self.error = "宠物设置未保存：\(error.localizedDescription)" }
    }

    func importPet() {
        let chooser = NSOpenPanel()
        chooser.allowedContentTypes = [.png, .webP]; chooser.canChooseDirectories = false
        chooser.message = "选择 Codex 格式的透明宠物图集（1536 × 1872 或 1536 × 2288）"
        guard chooser.runModal() == .OK, let source = chooser.url, let directory = customDirectory else { return }
        do {
            let values = try source.resourceValues(forKeys: [.fileSizeKey])
            guard (values.fileSize ?? Int.max) <= 20 * 1024 * 1024,
                  PetArtwork(id: "check", name: "", url: source) != nil else {
                throw NSError(domain: "Pet", code: 1, userInfo: [NSLocalizedDescriptionKey: "需要 1536 × 1872 或 1536 × 2288 的 PNG/WebP，且不超过 20 MB。"])
            }
            let id = UUID().uuidString.lowercased(), folder = directory.appendingPathComponent(id)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            do {
                let name = source.deletingPathExtension().lastPathComponent
                let filename = "spritesheet." + source.pathExtension.lowercased()
                try FileManager.default.copyItem(at: source, to: folder.appendingPathComponent(filename))
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: folder.appendingPathComponent(filename).path)
                try JSONSerialization.data(withJSONObject: ["id": id, "displayName": name, "spritesheetPath": filename]).write(to: folder.appendingPathComponent("pet.json"), options: .atomic)
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: folder.appendingPathComponent("pet.json").path)
                reloadArtwork(); select("coindex:" + id); error = ""
            } catch { try? FileManager.default.removeItem(at: folder); throw error }
        } catch { self.error = error.localizedDescription }
    }

    private func registerShortcut() {
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let pointer = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(GetApplicationEventTarget(), { _, _, pointer in
            guard let pointer else { return noErr }
            Task { @MainActor in Unmanaged<PetController>.fromOpaque(pointer).takeUnretainedValue().wake() }
            return noErr
        }, 1, &type, pointer, &hotKeyHandler)
        let status = RegisterEventHotKey(UInt32(kVK_ANSI_P), UInt32(controlKey | optionKey),
            EventHotKeyID(signature: 0x434F494E, id: 1), GetApplicationEventTarget(), 0, &hotKey)
        if status != noErr { error = "显示宠物快捷键 ⌃⌥P 已被占用，可从菜单栏打开。" }
    }

    func shutdown() {
        if let clickMonitor { NSEvent.removeMonitor(clickMonitor) }; clickMonitor = nil
        if let hotKey { UnregisterEventHotKey(hotKey) }; hotKey = nil
        if let hotKeyHandler { RemoveEventHandler(hotKeyHandler) }; hotKeyHandler = nil
        subscription = nil; tray?.close(); panel?.close(); panel = nil
    }
}

final class PetSpriteView: NSView {
    weak var controller: PetController?
    var artwork: PetArtwork?
    var state = PetState.idle
    private var displayed: NSImage?
    private var animation: PetAnimation = .make(.idle)
    private var index = 0
    private var timer: Timer?
    private var cursorTimer: Timer?
    private var lastCursor = NSEvent.mouseLocation
    private var lookUntil = Date.distantPast
    private var hover = false
    private var dragStart: NSPoint?
    private var origin: NSPoint?
    private var moved = false
    private var tracking: NSTrackingArea?
    private var reducedMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    override var acceptsFirstResponder: Bool { true }
    override var isFlipped: Bool { true }
    override func hitTest(_ point: NSPoint) -> NSView? { bounds.contains(point) ? self : nil }

    func configure(_ artwork: PetArtwork?, state: PetState, controller: PetController) {
        let changed = self.artwork?.id != artwork?.id || self.state != state
        self.artwork = artwork; self.state = state; self.controller = controller
        setAccessibilityElement(true); setAccessibilityRole(.image)
        setAccessibilityLabel("\(artwork?.name ?? "宠物")，\(controller.statusTitle)。拖动移动，点击更换宠物。")
        if changed { restart() }
    }
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        if window != nil {
            restart()
            cursorTimer?.invalidate()
            cursorTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in self?.checkCursor() }
        } else { timer?.invalidate(); cursorTimer?.invalidate() }
    }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let tracking { removeTrackingArea(tracking) }
        let new = NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect], owner: self)
        tracking = new; addTrackingArea(new)
    }
    private func restart() {
        timer?.invalidate(); index = 0
        reducedMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        animation = .make(hover ? .jumping : state, reducedMotion: reducedMotion)
        render()
    }
    private func render() {
        guard animation.frames.indices.contains(index) else { return }
        displayed = artwork?.image(animation.frames[index]); needsDisplay = true
        guard window?.isVisible == true, !reducedMotion else { return }
        let delay = Double(animation.frames[index].milliseconds) / 1000
        timer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
            guard let self else { return }
            if self.index + 1 < self.animation.frames.count { self.index += 1 }
            else if let loop = self.animation.loopStart { self.index = loop }
            else { return }
            self.render()
        }
    }
    private func checkCursor() {
        guard window?.isVisible == true else { timer?.invalidate(); return }
        let reduce = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        if reduce != reducedMotion { restart() }
        if timer?.isValid != true && !reducedMotion { render() }
        guard !reducedMotion, !hover, dragStart == nil, [.idle, .running, .waving].contains(state),
              let window else { return }
        let cursor = NSEvent.mouseLocation
        if cursor != lastCursor { lookUntil = Date().addingTimeInterval(0.9); lastCursor = cursor }
        if Date() < lookUntil {
            let rect = window.convertToScreen(convert(bounds, to: nil))
            if let frame = PetAnimation.look(dx: cursor.x - rect.midX, dy: cursor.y - rect.midY, rows: artwork?.rows ?? 9) {
                displayed = artwork?.image(frame); needsDisplay = true
            }
        }
    }
    override func draw(_ dirtyRect: NSRect) {
        NSGraphicsContext.current?.imageInterpolation = .none
        displayed?.draw(in: bounds, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
    }
    override func mouseEntered(with event: NSEvent) { hover = true; restart() }
    override func mouseExited(with event: NSEvent) { hover = false; if dragStart == nil { restart() } }
    override func mouseDown(with event: NSEvent) {
        window?.makeKey(); window?.makeFirstResponder(self)
        dragStart = NSEvent.mouseLocation; origin = window?.frame.origin; moved = false
    }
    override func mouseDragged(with event: NSEvent) {
        guard let start = dragStart, let origin, let window, let controller else { return }
        let cursor = NSEvent.mouseLocation, dx = cursor.x - start.x, dy = cursor.y - start.y
        guard moved || hypot(dx, dy) > 3 else { return }
        if !moved { moved = true; hover = false; timer?.invalidate(); animation = .make(dx < 0 ? .runningLeft : .runningRight, reducedMotion: reducedMotion, loop: true); index = 0; render() }
        window.setFrameOrigin(controller.clamped(NSPoint(x: origin.x + dx, y: origin.y + dy), size: window.frame.size))
    }
    override func mouseUp(with event: NSEvent) {
        dragStart = nil
        if moved { controller?.moved(); restart() } else { controller?.openPreferences() }
    }
    override func rightMouseDown(with event: NSEvent) { controller?.contextMenu(event: event, in: self) }
    override func keyDown(with event: NSEvent) {
        guard let window, let controller else { return }
        var point = window.frame.origin
        switch event.keyCode {
        case 123: point.x -= 10
        case 124: point.x += 10
        case 125: point.y -= 10
        case 126: point.y += 10
        case 53: if let origin { point = origin }; window.resignKey()
        default: super.keyDown(with: event); return
        }
        window.setFrameOrigin(controller.clamped(point, size: window.frame.size)); controller.moved()
    }
    deinit { timer?.invalidate(); cursorTimer?.invalidate() }
}

struct PetSprite: NSViewRepresentable {
    let artwork: PetArtwork?
    let state: PetState
    let controller: PetController
    func makeNSView(context: Context) -> PetSpriteView { PetSpriteView() }
    func updateNSView(_ view: PetSpriteView, context: Context) { view.configure(artwork, state: state, controller: controller) }
    static func dismantleNSView(_ view: PetSpriteView, coordinator: ()) { view.removeFromSuperview() }
}

private final class PetTrayButton: NSButton {
    weak var controller: PetController?
    init(controller: PetController) {
        self.controller = controller; super.init(frame: .zero)
        image = NSImage(systemSymbolName: "bell", accessibilityDescription: "查看待办活动")
        isBordered = false; bezelStyle = .inline; target = self; action = #selector(clicked)
        toolTip = "查看待办活动"; setAccessibilityLabel("查看待办活动")
    }
    required init?(coder: NSCoder) { fatalError() }
    @objc private func clicked() { controller?.showActivity(relativeTo: self) }
}
private struct PetBell: NSViewRepresentable {
    let pet: PetController
    func makeNSView(context: Context) -> NSButton { PetTrayButton(controller: pet) }
    func updateNSView(_ view: NSButton, context: Context) {}
}

struct PetOverlay: View {
    @ObservedObject var pet: PetController
    var body: some View {
        VStack(spacing: 4) {
            if pet.preferences.selectedID != "mini" {
                PetSprite(artwork: pet.selected, state: pet.state, controller: pet).frame(width: pet.preferences.size, height: pet.preferences.size * 208 / 192)
            }
            HStack(spacing: 10) {
                Button { pet.newTodo() } label: { Image(systemName: "square.and.pencil") }.help("新建待办")
                PetBell(pet: pet).frame(width: 18, height: 22)
                Button { pet.openMain() } label: { Text(pet.statusTitle).font(.system(size: 11, weight: .medium)).lineLimit(1) }.help("打开 coindex")
                Button { pet.hide() } label: { Image(systemName: "chevron.down") }.help("隐藏宠物")
            }.buttonStyle(HoverPlainStyle()).font(.system(size: 13)).padding(.horizontal, 12).frame(height: 32)
                .background(.regularMaterial, in: Capsule()).overlay(Capsule().stroke(.primary.opacity(0.1), lineWidth: 0.5))
                .shadow(color: .black.opacity(0.1), radius: 3, y: 2)
        }.padding(.horizontal, 8).padding(.bottom, 8).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
    }
}

struct PetActivityTray: View {
    @ObservedObject var pet: PetController
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack { Text("待办活动").font(.headline); Spacer(); Text("\(pet.activities.count)").foregroundStyle(.secondary) }
            ScrollView {
                if pet.activities.isEmpty { Text("目前没有待办").foregroundStyle(.secondary).padding(.vertical, 30) }
                LazyVStack(spacing: 8) {
                    ForEach(pet.activities) { task in
                        Button { pet.openTask(task) } label: {
                            VStack(alignment: .leading, spacing: 5) {
                                Label(task.kindTitle + " · " + displayHost(task.host), systemImage: task.symbol).font(.caption).foregroundStyle(Palette.kind(task.kind))
                                Text(task.title).font(.system(size: 13, weight: .medium)).lineLimit(2)
                                Text(task.isManual ? task.detail : task.stopPoint).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(10).background(Palette.subtle, in: RoundedRectangle(cornerRadius: 10))
                        }.buttonStyle(HoverPlainStyle())
                    }
                }
            }
            Button("打开 coindex") { pet.openMain() }
        }.padding(16).frame(width: 360, height: 380)
    }
}

struct PetSettingsView: View {
    @ObservedObject var pet: PetController
    @Environment(\.dismiss) var dismiss
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack { Label("桌面宠物", systemImage: "pawprint").font(.system(size: 22, weight: .semibold)); Spacer(); Button("完成") { dismiss() }.buttonStyle(CoindexButtonStyle()).keyboardShortcut(.defaultAction) }
            Toggle("显示桌面宠物", isOn: Binding(get: { pet.preferences.enabled }, set: { pet.setEnabled($0) }))
            HStack {
                Text("宠物大小"); Slider(value: Binding(get: { pet.preferences.size }, set: { pet.setSize($0) }), in: PetAnimation.sizeRange, step: 1)
                Button("重置") { pet.setSize(PetAnimation.defaultSize) }.controlSize(.small)
            }
            Picker("显示方式", selection: Binding(get: { pet.preferences.onDemand }, set: { pet.setOnDemand($0) })) {
                Text("始终显示").tag(false); Text("按需显示").tag(true)
            }.pickerStyle(.segmented)
            Text("⌃⌥P 显示宠物；拖动移动，点击更换，右键隐藏。按需显示时，点击其他应用会收起。").font(.caption).foregroundStyle(.secondary)
            ScrollView {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 3), spacing: 12) {
                    petCell(id: "mini", name: "Mini", image: nil)
                    ForEach(pet.artwork) { pet in
                        petCell(id: pet.id, name: pet.name, image: pet.image(PetFrame(row: 0, column: 0, milliseconds: 0)))
                    }
                }
            }
            HStack {
                Button("导入宠物图集…") { pet.importPet() }
                Button("刷新") { pet.reloadArtwork() }
                Spacer()
            }
            Text("支持 Codex 原版及本机 ~/.codex/pets 中的自定义宠物。悬浮栏的铅笔新建待办，铃铛查看待办进展。").font(.caption).foregroundStyle(.secondary)
            if !pet.error.isEmpty { Text(pet.error).font(.caption).foregroundStyle(.orange) }
        }.padding(24).frame(width: 540, height: 660).background(Palette.canvas).foregroundStyle(Palette.ink).tint(Palette.accent).buttonStyle(CoindexButtonStyle()).toggleStyle(.switch)
    }
    private func petCell(id: String, name: String, image: NSImage?) -> some View {
        Button { pet.select(id) } label: {
            VStack(spacing: 6) {
                if let image { Image(nsImage: image).resizable().interpolation(.none).scaledToFit().frame(width: 76, height: 82) }
                else { Image(systemName: "ellipsis.bubble").font(.system(size: 30)).frame(width: 76, height: 82) }
                HStack(spacing: 4) { Text(name).lineLimit(1); if pet.preferences.selectedID == id { Image(systemName: "checkmark.circle.fill") } }.font(.caption)
            }.frame(maxWidth: .infinity).padding(10)
                .background(pet.preferences.selectedID == id ? Palette.accentWash : Palette.surface, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(pet.preferences.selectedID == id ? Palette.accent : Palette.border))
        }.buttonStyle(HoverPlainStyle()).accessibilityLabel("选择 " + name)
    }
}

struct PetMenu: View {
    @ObservedObject var pet: PetController
    var body: some View {
        Button(pet.visible ? "隐藏宠物" : "显示宠物") { pet.toggle() }
        Button("更换宠物…") { pet.openPreferences() }
    }
}
