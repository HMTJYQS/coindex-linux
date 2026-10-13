import CoreGraphics

// Original coindex mark. Unit coordinates use a top-left origin.
enum BrandGeometry {
    static func path(in rect: CGRect) -> CGPath {
        let path = CGMutablePath()
        path.move(to: CGPoint(x: 0.68, y: 0.25))
        path.addCurve(to: CGPoint(x: 0.21, y: 0.49), control1: CGPoint(x: 0.46, y: 0.08), control2: CGPoint(x: 0.21, y: 0.25))
        path.addCurve(to: CGPoint(x: 0.65, y: 0.70), control1: CGPoint(x: 0.21, y: 0.72), control2: CGPoint(x: 0.46, y: 0.85))
        path.move(to: CGPoint(x: 0.49, y: 0.48))
        path.addLine(to: CGPoint(x: 0.62, y: 0.61))
        path.addLine(to: CGPoint(x: 0.86, y: 0.36))
        var transform = CGAffineTransform(a: rect.width, b: 0, c: 0, d: rect.height, tx: rect.minX, ty: rect.minY)
        return path.copy(using: &transform)!
    }
}
