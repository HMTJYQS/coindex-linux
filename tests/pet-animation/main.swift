import Foundation
import ImageIO

func expect(_ value: @autoclosure () -> Bool, _ message: String) {
    if !value() { fatalError(message) }
}
let idle = PetAnimation.make(.idle)
expect(idle.frames.map(\.milliseconds) == [1680, 660, 660, 840, 840, 1920], "Idle must use the original slow timings")
expect(idle.loopStart == 0, "Idle loops")
let contracts: [(PetState, Int, Int, Int, Int)] = [
    (.runningRight, 1, 8, 120, 220), (.runningLeft, 2, 8, 120, 220),
    (.waving, 3, 4, 140, 280), (.jumping, 4, 5, 140, 280),
    (.failed, 5, 8, 140, 240), (.waiting, 6, 6, 150, 260),
    (.running, 7, 6, 120, 220), (.review, 8, 6, 150, 280)
]
for (state, row, count, duration, last) in contracts {
    let sequence = PetAnimation.make(state)
    expect(sequence.frames.count == count * 3 + 6, "Actions repeat three times then idle")
    expect(sequence.loopStart == count * 3, "Only idle repeats after action")
    for i in 0..<(count * 3) {
        expect(sequence.frames[i] == PetFrame(row: row, column: i % count, milliseconds: i % count == count - 1 ? last : duration), "Wrong frame for \(state)")
    }
    expect(Array(sequence.frames.suffix(6)) == idle.frames, "Wrong idle suffix")
    let reduced = PetAnimation.make(state, reducedMotion: true)
    expect(reduced.frames.count == 1 && reduced.loopStart == nil && reduced.frames[0].row == row, "Reduced motion must stay still")
    let loop = PetAnimation.make(state, loop: true)
    expect(loop.frames.count == count && loop.loopStart == 0, "Drag animation should loop")
}
expect(PetAnimation.look(dx: 0, dy: 0, rows: 11) == nil, "No direction at center")
expect(PetAnimation.look(dx: 5, dy: 10, rows: 9) == nil, "Legacy artwork has no direction rows")
for i in 0..<16 {
    let radians = Double(i) * .pi / 8
    let frame = PetAnimation.look(dx: sin(radians) * 100, dy: cos(radians) * 100, rows: 11)
    expect(frame?.row == 9 + i / 8 && frame?.column == i % 8, "Wrong 16-way direction \(i)")
}
expect([PetState.running, .review, .failed, .waiting].sorted { PetAnimation.priority($0) < PetAnimation.priority($1) } == [.waiting, .failed, .review, .running], "Activity priority differs from Codex")

let root = URL(fileURLWithPath: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "Resources/CustomPets/coindex-cat/spritesheet.png")
let images = root.pathExtension == "png" ? [root] : try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil).filter { $0.pathExtension == "webp" }
expect(!images.isEmpty, "Missing artwork")
for url in images {
    let source = CGImageSourceCreateWithURL(url as CFURL, nil)!
    let image = CGImageSourceCreateImageAtIndex(source, 0, nil)!
    expect(image.width == 1536 && image.height == 2288, "Wrong native image dimensions")
    for (row, count) in PetAnimation.requiredFrames.enumerated() {
        for column in 0..<count {
            let frame = image.cropping(to: CGRect(x: column * 192, y: row * 208, width: 192, height: 208))!
            let data = frame.dataProvider!.data!
            let bytes = CFDataGetBytePtr(data)!
            let alphaOffset = frame.alphaInfo == .premultipliedFirst || frame.alphaInfo == .first ? 0 : 3
            var nontransparent = 0
            for y in 0..<frame.height {
                for x in 0..<frame.width where bytes[y * frame.bytesPerRow + x * 4 + alphaOffset] > 16 { nontransparent += 1 }
            }
            expect(nontransparent > 30, "Empty animation/direction frame in \(url.lastPathComponent), \(row), \(column)")
        }
    }
}
print("Verified timings, loops, reduced motion, 16 directions, activity order, and all required frames of \(images.count) artwork sheets")
