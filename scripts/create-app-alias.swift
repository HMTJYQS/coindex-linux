import Foundation

let app = URL(fileURLWithPath: CommandLine.arguments[1])
let alias = URL(fileURLWithPath: CommandLine.arguments[2])
let data = try app.bookmarkData(options: .suitableForBookmarkFile, includingResourceValuesForKeys: nil, relativeTo: nil)
try URL.writeBookmarkData(data, to: alias)
var stale = false
let resolved = try URL(resolvingBookmarkData: data, options: .withoutUI, relativeTo: nil, bookmarkDataIsStale: &stale)
guard resolved.standardizedFileURL == app.standardizedFileURL else { fatalError("Alias target mismatch") }
