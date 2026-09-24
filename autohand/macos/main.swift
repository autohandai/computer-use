// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Autohand AI LLC

import ApplicationServices
import CoreGraphics
import Darwin
import Foundation

private let bundleIdentifier = "ai.autohand.computer-use"

private struct ParsedArguments {
    let positionals: [String]
    let options: [String: String]

    init(_ arguments: ArraySlice<String>) {
        var positionals: [String] = []
        var options: [String: String] = [:]
        var index = arguments.startIndex
        while index < arguments.endIndex {
            let argument = arguments[index]
            if argument.hasPrefix("--") {
                let valueIndex = arguments.index(after: index)
                if valueIndex < arguments.endIndex {
                    options[String(argument.dropFirst(2))] = arguments[valueIndex]
                    index = arguments.index(after: valueIndex)
                    continue
                }
            }
            positionals.append(argument)
            index = arguments.index(after: index)
        }
        self.positionals = positionals
        self.options = options
    }
}

private func writeJSON(_ value: [String: Any], to path: String?) throws {
    guard let path else { return }
    let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    try data.write(to: URL(fileURLWithPath: path), options: .atomic)
}

private func requestPermissions(resultPath: String?) throws -> Int32 {
    let accessibilityOptions = ["AXTrustedCheckOptionPrompt": true] as CFDictionary
    let accessibility = AXIsProcessTrustedWithOptions(accessibilityOptions)
    let screenRecording = CGRequestScreenCaptureAccess()
    try writeJSON([
        "accessibility": accessibility,
        "screenRecording": screenRecording,
        "bundleIdentifier": Bundle.main.bundleIdentifier ?? bundleIdentifier,
    ], to: resultPath)
    return 0
}

private func inspectPermissions(resultPath: String?) throws -> Int32 {
    try writeJSON([
        "accessibility": AXIsProcessTrusted(),
        "screenRecording": CGPreflightScreenCaptureAccess(),
        "bundleIdentifier": Bundle.main.bundleIdentifier ?? bundleIdentifier,
    ], to: resultPath)
    return 0
}

private func processExists(_ pid: pid_t) -> Bool {
    if kill(pid, 0) == 0 { return true }
    return errno == EPERM
}

private func embeddedEnvironment() -> [String: String] {
    var environment = ProcessInfo.processInfo.environment
    environment["CUA_DRIVER_EMBEDDED"] = "1"
    environment["CUA_DRIVER_HOST_BUNDLE_ID"] = Bundle.main.bundleIdentifier ?? bundleIdentifier
    environment["CUA_DRIVER_PERMISSION_MODE"] = "standard"
    environment["CUA_DRIVER_RS_TELEMETRY_ENABLED"] = "0"
    return environment
}

private func serve(driverPath: String, socketPath: String, ownerPID: pid_t) throws -> Int32 {
    let socketURL = URL(fileURLWithPath: socketPath)
    try FileManager.default.createDirectory(
        at: socketURL.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try? FileManager.default.removeItem(at: socketURL)

    let daemon = Process()
    daemon.executableURL = URL(fileURLWithPath: driverPath)
    daemon.arguments = ["serve", "--embedded", "--socket", socketPath]
    daemon.environment = embeddedEnvironment()
    daemon.standardOutput = FileHandle.nullDevice
    daemon.standardError = FileHandle.nullDevice
    try daemon.run()

    while daemon.isRunning && processExists(ownerPID) {
        Thread.sleep(forTimeInterval: 0.2)
    }
    if daemon.isRunning {
        daemon.terminate()
    }
    daemon.waitUntilExit()
    try? FileManager.default.removeItem(at: socketURL)
    return processExists(ownerPID) ? daemon.terminationStatus : 0
}

private func waitForSocket(_ path: String, timeout: TimeInterval) -> Bool {
    let deadline = Date().addingTimeInterval(timeout)
    while Date() < deadline {
        if FileManager.default.fileExists(atPath: path) { return true }
        Thread.sleep(forTimeInterval: 0.05)
    }
    return false
}

private func privateSocketPath(processID: Int32) throws -> String {
    let directory = URL(fileURLWithPath: "/tmp")
        .appendingPathComponent("autohand-computer-use-\(getuid())", isDirectory: true)
    try FileManager.default.createDirectory(
        at: directory,
        withIntermediateDirectories: true,
        attributes: [.posixPermissions: 0o700]
    )
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path)
    return directory.appendingPathComponent("\(processID).sock").path
}

private func runMCPProxy(driverPath: String) throws -> Int32 {
    let processID = ProcessInfo.processInfo.processIdentifier
    let socketPath = try privateSocketPath(processID: processID)
    try? FileManager.default.removeItem(atPath: socketPath)

    let executableURL = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    let appPath = executableURL
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .path

    let launcher = Process()
    launcher.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    launcher.arguments = [
        "-g", "-n", appPath, "--args", "serve",
        "--driver-path", driverPath,
        "--socket", socketPath,
        "--owner-pid", String(processID),
    ]
    launcher.standardOutput = FileHandle.nullDevice
    launcher.standardError = FileHandle.standardError
    try launcher.run()
    launcher.waitUntilExit()
    guard launcher.terminationStatus == 0, waitForSocket(socketPath, timeout: 10) else {
        throw NSError(domain: bundleIdentifier, code: 2, userInfo: [
            NSLocalizedDescriptionKey: "Autohand Computer Use could not start its embedded driver.",
        ])
    }

    let proxy = Process()
    proxy.executableURL = URL(fileURLWithPath: driverPath)
    proxy.arguments = ["mcp", "--embedded", "--socket", socketPath]
    proxy.environment = embeddedEnvironment()
    proxy.standardInput = FileHandle.standardInput
    proxy.standardOutput = FileHandle.standardOutput
    proxy.standardError = FileHandle.standardError
    try proxy.run()
    proxy.waitUntilExit()
    try? FileManager.default.removeItem(atPath: socketPath)
    return proxy.terminationStatus
}

private func requiredOption(_ name: String, in arguments: ParsedArguments) throws -> String {
    if let value = arguments.options[name], !value.isEmpty { return value }
    throw NSError(domain: bundleIdentifier, code: 64, userInfo: [
        NSLocalizedDescriptionKey: "Missing required --\(name) option.",
    ])
}

private func run() throws -> Int32 {
    let arguments = ParsedArguments(CommandLine.arguments.dropFirst())
    guard let command = arguments.positionals.first else {
        throw NSError(domain: bundleIdentifier, code: 64, userInfo: [
            NSLocalizedDescriptionKey: "Expected permissions, serve, or mcp.",
        ])
    }

    switch command {
    case "permissions":
        guard let operation = arguments.positionals.dropFirst().first else {
            throw NSError(domain: bundleIdentifier, code: 64, userInfo: [
                NSLocalizedDescriptionKey: "Expected permissions grant or permissions status.",
            ])
        }
        if operation == "grant" {
            return try requestPermissions(resultPath: arguments.options["result-path"])
        }
        if operation == "status" {
            return try inspectPermissions(resultPath: arguments.options["result-path"])
        }
        throw NSError(domain: bundleIdentifier, code: 64, userInfo: [
            NSLocalizedDescriptionKey: "Unknown permissions operation: \(operation).",
        ])
    case "serve":
        let driverPath = try requiredOption("driver-path", in: arguments)
        let socketPath = try requiredOption("socket", in: arguments)
        let ownerValue = try requiredOption("owner-pid", in: arguments)
        guard let ownerPID = pid_t(ownerValue) else {
            throw NSError(domain: bundleIdentifier, code: 64, userInfo: [
                NSLocalizedDescriptionKey: "Invalid --owner-pid value.",
            ])
        }
        return try serve(driverPath: driverPath, socketPath: socketPath, ownerPID: ownerPID)
    case "mcp":
        return try runMCPProxy(driverPath: requiredOption("driver-path", in: arguments))
    default:
        throw NSError(domain: bundleIdentifier, code: 64, userInfo: [
            NSLocalizedDescriptionKey: "Unknown command: \(command).",
        ])
    }
}

do {
    exit(try run())
} catch {
    FileHandle.standardError.write(Data("Autohand Computer Use: \(error.localizedDescription)\n".utf8))
    exit(1)
}
