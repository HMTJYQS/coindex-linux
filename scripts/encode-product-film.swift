// Encode locally rendered RGBA frames, then optionally add an original score.
import AVFoundation
import CoreVideo
import Foundation

func fail(_ message: String) -> Never { fputs(message + "\n", stderr); exit(1) }
let args = CommandLine.arguments
guard args.count == 8, let width = Int(args[1]), let height = Int(args[2]),
      let fps = Int32(args[3]), let frames = Int(args[4]) else {
    fail("Usage: encoder width height fps frames silent.mp4 score.wav final.mp4")
}
let silentURL = URL(fileURLWithPath: args[5])
let finalURL = URL(fileURLWithPath: args[7])
for url in [silentURL, finalURL] { try? FileManager.default.removeItem(at: url) }
let writer = try AVAssetWriter(outputURL: silentURL, fileType: .mp4)
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: width, AVVideoHeightKey: height,
    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 7_000_000,
        AVVideoExpectedSourceFrameRateKey: fps, AVVideoMaxKeyFrameIntervalKey: fps * 2,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel]
])
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
    kCVPixelBufferWidthKey as String: width, kCVPixelBufferHeightKey as String: height,
    kCVPixelBufferCGImageCompatibilityKey as String: true,
    kCVPixelBufferCGBitmapContextCompatibilityKey as String: true
])
writer.add(input)
guard writer.startWriting() else { fail(writer.error?.localizedDescription ?? "Cannot start video") }
writer.startSession(atSourceTime: .zero)
let byteCount = width * height * 4
let handle = FileHandle.standardInput
for index in 0..<frames {
    var bytes = Data()
    while bytes.count < byteCount {
        let part = handle.readData(ofLength: byteCount - bytes.count)
        guard !part.isEmpty else { fail("Incomplete frame \(index)") }
        bytes.append(part)
    }
    while !input.isReadyForMoreMediaData {
        if writer.status == .failed { fail(writer.error?.localizedDescription ?? "Video failed") }
        Thread.sleep(forTimeInterval: 0.002)
    }
    var optional: CVPixelBuffer?
    guard let pool = adaptor.pixelBufferPool,
          CVPixelBufferPoolCreatePixelBuffer(nil, pool, &optional) == kCVReturnSuccess,
          let pixel = optional else { fail("Cannot allocate video frame") }
    CVPixelBufferLockBaseAddress(pixel, [])
    let stride = CVPixelBufferGetBytesPerRow(pixel)
    let address = CVPixelBufferGetBaseAddress(pixel)!
    bytes.withUnsafeBytes { buffer in
        for row in 0..<height {
            memcpy(address.advanced(by: row * stride), buffer.baseAddress!.advanced(by: row * width * 4), width * 4)
        }
    }
    CVPixelBufferUnlockBaseAddress(pixel, [])
    guard adaptor.append(pixel, withPresentationTime: CMTime(value: Int64(index), timescale: fps)) else {
        fail(writer.error?.localizedDescription ?? "Cannot append video frame")
    }
}
input.markAsFinished()
let done = DispatchSemaphore(value: 0)
writer.finishWriting { done.signal() }
done.wait()
guard writer.status == .completed else { fail(writer.error?.localizedDescription ?? "Cannot finish video") }

let composition = AVMutableComposition()
let video = AVURLAsset(url: silentURL)
let audio = AVURLAsset(url: URL(fileURLWithPath: args[6]))
let duration = CMTime(value: Int64(frames), timescale: fps)
let range = CMTimeRange(start: .zero, duration: duration)
guard let originalVideo = video.tracks(withMediaType: .video).first,
      let originalAudio = audio.tracks(withMediaType: .audio).first,
      let videoTrack = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid),
      let audioTrack = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)
else { fail("Missing media track") }
try videoTrack.insertTimeRange(range, of: originalVideo, at: .zero)
try audioTrack.insertTimeRange(range, of: originalAudio, at: .zero)
guard let exporter = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) else {
    fail("Cannot create exporter")
}
exporter.outputURL = finalURL
exporter.outputFileType = .mp4
exporter.shouldOptimizeForNetworkUse = true
exporter.metadata = []
let exported = DispatchSemaphore(value: 0)
exporter.exportAsynchronously { exported.signal() }
exported.wait()
guard exporter.status == .completed else { fail(exporter.error?.localizedDescription ?? "Cannot export film") }
print("Encoded \(frames) frames at \(fps) fps; original stereo score included.")
