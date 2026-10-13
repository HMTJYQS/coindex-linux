import Foundation

// Frame contract and timings verified against the installed Codex 26.1007.21159.
enum PetState: String, CaseIterable {
    case idle, running, waiting, review, failed, waving, jumping
    case runningLeft = "running-left", runningRight = "running-right"
}

struct PetFrame: Equatable {
    let row: Int
    let column: Int
    let milliseconds: Int
}

struct PetAnimation {
    static let cellWidth = 192
    static let cellHeight = 208
    static let columns = 8
    static let defaultSize = 112.0
    static let sizeRange = 80.0...224.0
    static let requiredFrames = [6, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8]
    let frames: [PetFrame]
    let loopStart: Int?

    static func row(_ row: Int, count: Int, duration: Int, last: Int) -> [PetFrame] {
        (0..<count).map { PetFrame(row: row, column: $0, milliseconds: $0 == count - 1 ? last : duration) }
    }

    static func make(_ state: PetState, reducedMotion: Bool = false, loop: Bool = false) -> PetAnimation {
        let idle = zip(0..<6, [280, 110, 110, 140, 140, 320]).map {
            PetFrame(row: 0, column: $0.0, milliseconds: $0.1)
        }
        let slowIdle = idle.map { PetFrame(row: $0.row, column: $0.column, milliseconds: $0.milliseconds * 6) }
        let action: [PetFrame]
        switch state {
        case .idle: action = idle
        case .runningRight: action = row(1, count: 8, duration: 120, last: 220)
        case .runningLeft: action = row(2, count: 8, duration: 120, last: 220)
        case .waving: action = row(3, count: 4, duration: 140, last: 280)
        case .jumping: action = row(4, count: 5, duration: 140, last: 280)
        case .failed: action = row(5, count: 8, duration: 140, last: 240)
        case .waiting: action = row(6, count: 6, duration: 150, last: 260)
        case .running: action = row(7, count: 6, duration: 120, last: 220)
        case .review: action = row(8, count: 6, duration: 150, last: 280)
        }
        if reducedMotion { return PetAnimation(frames: [action[0]], loopStart: nil) }
        if state == .idle { return PetAnimation(frames: slowIdle, loopStart: 0) }
        if loop { return PetAnimation(frames: action, loopStart: 0) }
        let repeated = action + action + action
        return PetAnimation(frames: repeated + slowIdle, loopStart: repeated.count)
    }

    // Cocoa y points upward; the atlas uses clockwise angles starting at north.
    static func look(dx: Double, dy: Double, rows: Int) -> PetFrame? {
        guard rows == 11, hypot(dx, dy) > 1 else { return nil }
        let angle = (atan2(dx, dy) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
        let direction = Int(floor(angle / 22.5 + 0.5)) % 16
        return PetFrame(row: 9 + direction / 8, column: direction % 8, milliseconds: 0)
    }

    static func priority(_ state: PetState) -> Int {
        switch state {
        case .waiting: return 0
        case .failed: return 1
        case .review: return 2
        case .running: return 3
        default: return 4
        }
    }
}
