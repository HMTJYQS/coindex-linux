import AppKit
import SwiftUI

enum Palette {
    private static func adaptive(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            let value = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
            return NSColor(srgbRed: Double((value >> 16) & 255) / 255,
                           green: Double((value >> 8) & 255) / 255,
                           blue: Double(value & 255) / 255, alpha: 1)
        })
    }
    static let accent = adaptive(0x555FC9, 0xA3AAFF)
    static let action = Color(red: 0.345, green: 0.384, blue: 0.80)
    static let canvas = adaptive(0xF7F8FA, 0x101113)
    static let surface = adaptive(0xFFFFFF, 0x191A1E)
    static let sidebar = adaptive(0xEFF0F4, 0x141519)
    static let subtle = adaptive(0xF2F3F7, 0x212228)
    static let border = adaptive(0xE1E3EB, 0x303139)
    static let ink = adaptive(0x20212B, 0xF3F3F7)
    static let muted = adaptive(0x676A79, 0xA4A7B5)
    static let accentWash = adaptive(0xE5E7FA, 0x2B2D46)
    static let success = adaptive(0x27805B, 0x66C79F)
    static func kind(_ kind: String) -> Color {
        switch kind {
        case "running": return adaptive(0x3276AD, 0x7BB7EA)
        case "review": return accent
        case "continue": return adaptive(0x996921, 0xDBB46C)
        case "wait": return adaptive(0x67748C, 0xA4B2CA)
        case "manual": return muted
        default: return adaptive(0x8661AE, 0xBC98DE)
        }
    }
}

struct CoindexGlyph: Shape {
    func path(in rect: CGRect) -> Path { Path(BrandGeometry.path(in: rect)) }
}

struct BrandBadge: View {
    var size: CGFloat = 32
    var body: some View {
        CoindexGlyph().stroke(.white, style: StrokeStyle(lineWidth: size * 0.08, lineCap: .round, lineJoin: .round))
            .frame(width: size, height: size)
            .background(LinearGradient(colors: [Palette.action, Color(red: 0.23, green: 0.25, blue: 0.56)], startPoint: .topLeading, endPoint: .bottomTrailing), in: RoundedRectangle(cornerRadius: size * 0.25))
            .accessibilityHidden(true)
    }
}

struct CoindexButtonStyle: ButtonStyle {
    var prominent = false
    func makeBody(configuration: Configuration) -> some View {
        InteractiveButtonBody(configuration: configuration, prominent: prominent)
    }
}

struct QuietIconStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        InteractiveButtonBody(configuration: configuration, quiet: true)
    }
}

private struct InteractiveButtonBody: View {
    let configuration: ButtonStyleConfiguration
    var prominent = false
    var quiet = false
    @Environment(\.isEnabled) private var enabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var hovered = false
    var body: some View {
        configuration.label.font(.system(size: quiet ? 13 : 12, weight: .medium))
            .padding(.horizontal, quiet ? 0 : 12).padding(.vertical, quiet ? 0 : 8)
            .frame(width: quiet ? 28 : nil, height: quiet ? 28 : nil)
            .foregroundStyle(prominent ? Color.white : quiet ? (hovered ? Palette.accent : Palette.muted) : Palette.ink)
            .background(prominent ? Palette.action : hovered || configuration.isPressed ? Palette.accentWash : quiet ? Color.clear : Palette.surface, in: RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).fill(prominent && hovered ? Color.white.opacity(0.12) : Color.clear).allowsHitTesting(false))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(prominent || quiet ? Color.clear : hovered ? Palette.accent.opacity(0.5) : Palette.border, lineWidth: 1).allowsHitTesting(false))
            .opacity(enabled ? (configuration.isPressed ? 0.75 : 1) : 0.45)
            .scaleEffect(configuration.isPressed && enabled && !reduceMotion ? 0.97 : 1)
            .contentShape(RoundedRectangle(cornerRadius: 7))
            .onHover { hovered = $0 && enabled }
            .onChange(of: enabled) { _, value in if !value { hovered = false } }
            .modifier(HandCursor(active: hovered && enabled))
            .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: hovered)
    }
}

struct HoverPlainStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View { PlainButtonBody(configuration: configuration) }
}

private struct PlainButtonBody: View {
    let configuration: ButtonStyleConfiguration
    @Environment(\.isEnabled) private var enabled
    @State private var hovered = false
    var body: some View {
        configuration.label
            .background(hovered ? Palette.accent.opacity(0.09) : Color.clear, in: RoundedRectangle(cornerRadius: 7))
            .opacity(enabled ? (configuration.isPressed ? 0.65 : 1) : 0.45)
            .contentShape(Rectangle()).onHover { hovered = $0 && enabled }
            .onChange(of: enabled) { _, value in if !value { hovered = false } }
            .modifier(HandCursor(active: hovered && enabled))
    }
}

private struct HandCursor: ViewModifier {
    let active: Bool
    @State private var pushed = false
    func body(content: Content) -> some View {
        content.onChange(of: active) { _, value in
            if value && !pushed { NSCursor.pointingHand.push(); pushed = true }
            else if !value && pushed { NSCursor.pop(); pushed = false }
        }.onDisappear {
            if pushed { NSCursor.pop(); pushed = false }
        }
    }
}

struct StatusBadge: View {
    let task: TodoTask
    var body: some View {
        Label(task.kindTitle, systemImage: task.symbol)
            .font(.system(size: 11, weight: .medium)).foregroundStyle(Palette.kind(task.kind))
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(Palette.kind(task.kind).opacity(0.09), in: RoundedRectangle(cornerRadius: 5))
    }
}

struct SettingsSection<Content: View>: View {
    let title: String
    let symbol: String
    @ViewBuilder let content: Content
    init(_ title: String, symbol: String, @ViewBuilder content: () -> Content) {
        self.title = title; self.symbol = symbol; self.content = content()
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(title, systemImage: symbol).font(.system(size: 13, weight: .semibold)).foregroundStyle(Palette.ink)
            content
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Palette.border))
    }
}

extension View {
    func coindexInput() -> some View {
        self.padding(11).background(Palette.surface, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Palette.border))
    }
}
