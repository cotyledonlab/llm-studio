import AppKit
import Foundation

guard let app = NSWorkspace.shared.frontmostApplication,
      let bundleID = app.bundleIdentifier else {
    fputs("frontmost application is unavailable\n", stderr)
    exit(2)
}

let timestamp = ISO8601DateFormatter()
timestamp.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
let observation: [String: Any] = [
    "observed_at_utc": timestamp.string(from: Date()),
    "name": app.localizedName ?? "",
    "bundle_id": bundleID,
    "process_id": app.processIdentifier,
]

do {
    let data = try JSONSerialization.data(withJSONObject: observation, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0a]))
} catch {
    fputs("could not encode frontmost-application observation: \(error)\n", stderr)
    exit(3)
}
