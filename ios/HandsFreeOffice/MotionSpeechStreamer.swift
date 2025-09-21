import Foundation
import SwiftUI
import Combine
import AVFAudio
import AVFoundation
import Speech
import CoreMotion
import QuartzCore

/// HandsFreeOffice iOS client
/// Minimal mode: gyroscopic mouse + tap-to-click
/// - Motion:
///     • sends `{ "type":"gesture", "kind":"tilt_angles", "roll_deg":D, "pitch_deg":D, "dt":D }` at ~60 Hz
///       (roll: right-tilt positive; pitch: forward-tilt positive → cursor down)
///     • sends `{ "type":"gesture", "kind":"tap" }` on phone knock
/// - Voice (unchanged): streams `{ "type":"command", "text":"..." }`
final class MotionSpeechStreamer: NSObject, ObservableObject {
    // MARK: - Published UI state
    @Published var connectionStatus: String = "disconnected"
    @Published var isListening: Bool = false
    @Published var isMotionActive: Bool = false
    @Published var isGesturesOn: Bool = false


    // MARK: - Networking
    private var webSocket: URLSessionWebSocketTask?
    private let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.waitsForConnectivity = true
        return URLSession(configuration: cfg)
    }()

    /// ⬇️ Set this to your Mac’s IP (same network as phone)
    private let serverURL = URL(string: "ws://100.69.87.156:8765")!

    private var pingTimer: Timer?
    private var reconnectBackoff: TimeInterval = 0.5
    private let maxBackoff: TimeInterval = 6.0

    // MARK: - Motion (gyro mouse)
    private let motion = CMMotionManager()

    // Send timing
    private var lastSend: TimeInterval = 0
    private let targetHz: Double = 60.0   // send rate
    private var motionStartedSent = false

    // Tap detection (knock) via userAcceleration magnitude (in g)
    private var lastTapAt: TimeInterval = 0
    private let tapCooldown: TimeInterval = 0.25
    private let tapThreshold: Double = 1.10

    // MARK: - Speech (unchanged path)
    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let audioEngine = AVAudioEngine()
    private var request = SFSpeechAudioBufferRecognitionRequest()
    private var recognitionTask: SFSpeechRecognitionTask?

    private var partialDebounce: Timer?
    private var lastHeard: String = ""
    private var lastSent: String = ""
    private var lastSentAt: Date = .distantPast
    private var pttEnabled = false

    // MARK: - Lifecycle
    deinit {
        stopListening()
        stopMotion()
        partialDebounce?.invalidate()
        partialDebounce = nil
        disconnect()
    }

    // MARK: - WebSocket
    func connect() {
        disconnect()
        print("WS connecting to:", serverURL.absoluteString)
        let task = session.webSocketTask(with: serverURL)
        webSocket = task
        task.resume()
        // hello handshake (helps verify connection from server logs)
        sendJSON(["type":"hello", "from":"ios"])
        connectionStatus = "connecting"
        startReceiveLoop()
        startPing()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            self.connectionStatus = "connected"
            self.reconnectBackoff = 0.5
            print("WS connected (optimistic)")
        }
    }

    func disconnect() {
        stopPing()
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        connectionStatus = "disconnected"
    }

    private func startReceiveLoop() {
        webSocket?.receive { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .failure(let error):
                print("WS receive error:", error.localizedDescription)
                DispatchQueue.main.async { self.connectionStatus = "error: \(error.localizedDescription)" }
                self.scheduleReconnect()
            case .success:
                break // ignore acks
            }
            self.startReceiveLoop()
        }
    }

    private func startPing() {
        stopPing()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 8.0, repeats: true) { [weak self] _ in
            guard let self = self, let ws = self.webSocket else { return }
            ws.send(.string("ping")) { err in if let err { print("WS ping error:", err.localizedDescription) } }
        }
    }

    private func stopPing() { pingTimer?.invalidate(); pingTimer = nil }

    private func scheduleReconnect() {
        stopPing()
        webSocket = nil
        connectionStatus = "reconnecting in \(Int(reconnectBackoff * 1000))ms"
        let delay = reconnectBackoff
        reconnectBackoff = min(maxBackoff, reconnectBackoff * 2)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in self?.connect() }
    }

    func sendJSON(_ dict: [String: Any]) {
        guard let ws = webSocket else { return }
        do {
            let data = try JSONSerialization.data(withJSONObject: dict, options: [])
            guard let text = String(data: data, encoding: .utf8) else { return }
            ws.send(.string(text)) { err in
                if let err {
                    print("❌ ws send error:", err.localizedDescription)
                    self.connectionStatus = "send error: \(err.localizedDescription)"
                }
            }
        } catch {
            print("❌ ws encode error:", error.localizedDescription)
        }
    }

    // MARK: - Speech
    func setPushToTalk(enabled: Bool) { pttEnabled = enabled }

    func startListening() {
        SFSpeechRecognizer.requestAuthorization { auth in
            guard auth == .authorized else { print("speech not authorized:", auth.rawValue); return }
            let askMic: (@escaping (Bool) -> Void) -> Void = { completion in
                if #available(iOS 17.0, *) { AVAudioApplication.requestRecordPermission { completion($0) } }
                else { AVAudioSession.sharedInstance().requestRecordPermission { completion($0) } }
            }
            askMic { granted in
                guard granted else { print("mic permission denied"); return }
                DispatchQueue.main.async { self.beginSpeech() }
            }
        }
    }

    private func beginSpeech() {
        guard recognitionTask == nil else { return }
        isListening = true

        let audioSession = AVAudioSession.sharedInstance()
        try? audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
        try? audioSession.setActive(true, options: .notifyOthersOnDeactivation)

        request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = !pttEnabled
        request.contextualStrings = []

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            self.request.append(buffer)
        }

        audioEngine.prepare()
        try? audioEngine.start()

        recognitionTask = speechRecognizer?.recognitionTask(with: request) { result, error in
            if let error { print("speech error:", error.localizedDescription); return }
            guard let result else { return }

            let orig = result.bestTranscription.formattedString
            let heard = orig.lowercased()
            self.lastHeard = orig
            print("heard:", heard, "final:", result.isFinal)
            DispatchQueue.main.async { self.connectionStatus = "heard: \(heard)" }

            if self.pttEnabled {
                if result.isFinal { self.sendCommand(heard); self.restartRecognitionSoon() }
                return
            }

            if result.isFinal {
                self.sendCommand(heard)
                self.restartRecognitionSoon()
                return
            }

            // Debounce partials: treat 1300 ms pause as end of utterance
            if heard == self.lastSent && Date().timeIntervalSince(self.lastSentAt) < 0.8 { return }
            self.partialDebounce?.invalidate()
            self.partialDebounce = Timer.scheduledTimer(withTimeInterval: 1.3, repeats: false) { _ in
                self.sendCommand(self.lastHeard)
                self.restartRecognitionSoon()
            }
        }
    }

    private func restartRecognitionSoon() {
        stopListening()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { self.beginSpeech() }
    }

    func stopListening() {
        partialDebounce?.invalidate(); partialDebounce = nil
        isListening = false
        recognitionTask?.cancel(); recognitionTask = nil
        request.endAudio()
        if audioEngine.isRunning { audioEngine.stop() }
        audioEngine.inputNode.removeTap(onBus: 0)
        try? AVAudioSession.sharedInstance().setActive(false)
    }

    private func sendCommand(_ raw: String) {
        let orig = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !orig.isEmpty else { return }
        let text = orig.lowercased()

        var cmd = text
        // normalize “g mail”, “g-mail”, etc. to “gmail” (case-insensitive)
        let patterns = [#"(?i)\bg[\s\-]?mail\b"#]
        for pat in patterns {
            cmd = cmd.replacingOccurrences(of: pat, with: "gmail", options: .regularExpression)
        }

        if cmd.contains("open gmail") || cmd.contains("open mail") || cmd.contains("open email") {
            cmd = "open gmail"
        } else if cmd.hasPrefix("type ") || cmd.contains("   type ") {
            if let r = text.range(of: "type ") {
                let idx = orig.index(orig.startIndex, offsetBy: orig.distance(from: text.startIndex, to: r.lowerBound))
                cmd = String(orig[idx...])
            }
        }

        if cmd == lastSent && Date().timeIntervalSince(lastSentAt) < 1.0 { return }
        lastSent = cmd; lastSentAt = Date()

        print("sending command:", cmd)
        sendJSON(["type":"command", "text": cmd])
    }

    // MARK: - Motion (gyro mouse only)
    func startMotion() {
        guard motion.isDeviceMotionAvailable else { return }
        isMotionActive = true
        motionStartedSent = false
        lastSend = 0
        motion.deviceMotionUpdateInterval = 1.0 / 60.0
        motion.startDeviceMotionUpdates(using: .xArbitraryZVertical, to: .main) { dm, _ in
            guard let dm = dm else { return }
            self.processGyro(dm)
        }
    }

    func stopMotion() {
        isMotionActive = false
        motion.stopDeviceMotionUpdates()
        motionStartedSent = false
    }

    /// Convert gyro into small cursor deltas; no smoothing/physics.
    private func processGyro(_ dm: CMDeviceMotion) {
        let now = CACurrentMediaTime()
        if !motionStartedSent {
            sendJSON(["type":"gesture", "kind":"motion_started"])
            motionStartedSent = true
            lastSend = now
            return
        }

        // throttle to ~targetHz
        let dt = now - lastSend
        if dt < (1.0 / targetHz) { return }
        lastSend = now

        // Orientation angles (radians) in .xArbitraryZVertical frame
        let rollRad  = dm.attitude.roll    // right-tilt positive in this frame
        let pitchRad = dm.attitude.pitch   // sign depends on frame; we want forward-tilt positive

        // Convert to degrees
        let toDeg = 180.0 / .pi
        let rollDeg  = rollRad * toDeg
        // Define forward tilt (top edge lower) as positive → cursor down on screen.
        // CoreMotion pitch is positive when top edge rises in some orientations, so invert:
        let pitchDeg = -(pitchRad * toDeg)

        sendJSON([
            "type": "gesture",
            "kind": "tilt_angles",
            "roll_deg": rollDeg,
            "pitch_deg": pitchDeg,
            "dt": dt
        ])

        // Tap detection via acceleration spike (unchanged)
        let a = dm.userAcceleration
        let am = sqrt(a.x*a.x + a.y*a.y + a.z*a.z)
        if am > tapThreshold, (now - lastTapAt) > tapCooldown {
            lastTapAt = now
            sendJSON(["type":"gesture", "kind":"tap"])
        }
    }
}
