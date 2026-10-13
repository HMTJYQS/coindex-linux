import AppKit
import Foundation

@main
struct IconBuilder {
    static func main() throws {
        let folder = CommandLine.arguments[1]
        try FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
        for size in [16, 32, 128, 256, 512] {
            for scale in [1, 2] {
                let pixels = size * scale
                let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
                NSGraphicsContext.saveGraphicsState()
                NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
                let context = NSGraphicsContext.current!.cgContext
                context.scaleBy(x: CGFloat(pixels) / 1024, y: CGFloat(pixels) / 1024)
                let rect = CGRect(x: 68, y: 68, width: 888, height: 888)
                let tile = CGPath(roundedRect: rect, cornerWidth: 202, cornerHeight: 202, transform: nil)
                context.saveGState()
                context.setShadow(offset: CGSize(width: 0, height: -9), blur: 24, color: NSColor.black.withAlphaComponent(0.20).cgColor)
                context.addPath(tile); context.setFillColor(NSColor(srgbRed: 0.30, green: 0.33, blue: 0.68, alpha: 1).cgColor); context.fillPath()
                context.restoreGState()
                context.saveGState(); context.addPath(tile); context.clip()
                let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [
                    NSColor(srgbRed: 0.24, green: 0.26, blue: 0.56, alpha: 1).cgColor,
                    NSColor(srgbRed: 0.43, green: 0.46, blue: 0.87, alpha: 1).cgColor
                ] as CFArray, locations: [0, 1])!
                context.drawLinearGradient(gradient, start: CGPoint(x: 820, y: 90), end: CGPoint(x: 220, y: 970), options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
                context.restoreGState()
                context.addPath(tile); context.setStrokeColor(NSColor.white.withAlphaComponent(0.20).cgColor); context.setLineWidth(2); context.strokePath()
                // Use exactly the same vector geometry as the sidebar brand.
                context.translateBy(x: 0, y: 1024); context.scaleBy(x: 1, y: -1)
                context.addPath(BrandGeometry.path(in: CGRect(x: 58, y: 58, width: 908, height: 908)))
                context.setStrokeColor(NSColor.white.cgColor); context.setLineWidth(74)
                context.setLineCap(.round); context.setLineJoin(.round); context.strokePath()
                NSGraphicsContext.restoreGraphicsState()
                let name = "icon_\(size)x\(size)" + (scale == 2 ? "@2x" : "") + ".png"
                try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: folder + "/" + name))
            }
        }
        // Monochrome menu bar template, readable at native 18-point size.
        let tray = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 36, pixelsHigh: 36, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: tray)
        let context = NSGraphicsContext.current!.cgContext
        context.translateBy(x: 0, y: 36); context.scaleBy(x: 1, y: -1)
        context.addPath(BrandGeometry.path(in: CGRect(x: -3, y: -3, width: 40, height: 40)))
        context.setLineWidth(3.3); context.setLineCap(.round); context.setLineJoin(.round); context.setStrokeColor(NSColor.black.cgColor); context.strokePath()
        NSGraphicsContext.restoreGraphicsState()
        try tray.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: folder + "/../MenuIcon.png"))
    }
}
