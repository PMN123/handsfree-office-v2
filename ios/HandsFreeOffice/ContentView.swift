//
//  ContentView.swift
//  HandsFreeOffice
//
//  Created by Praniil Nagaraj on 9/20/25.
//

import SwiftUI

// MARK: - Liquid Glass Button
struct GlassButtonStyle: ButtonStyle {
    var isProminent: Bool = false
    func makeBody(configuration: Configuration) -> some View {
        let pressed = configuration.isPressed
        return configuration.label
            .font(.title3)
            .frame(width: 56, height: 56)
            .background(
                ZStack {
                    // frosted pill
                    RoundedRectangle(cornerRadius: 18, style: .continuous).fill(.ultraThinMaterial)
                    // liquid sheen
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .fill(LinearGradient(colors: [Color.white.opacity(0.25), Color.white.opacity(0.05)], startPoint: .topLeading, endPoint: .bottomTrailing))
                        .blur(radius: 8)
                    // tint for prominent
                    if isProminent {
                        LinearGradient(colors: [Color.accentColor.opacity(0.35), Color.accentColor.opacity(0.15)], startPoint: .topLeading, endPoint: .bottomTrailing)
                            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    }
                }
            )
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                // gradient stroke + inner highlight
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(LinearGradient(colors: [Color.white.opacity(0.6), Color.white.opacity(0.15)], startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1)
                    .blendMode(.overlay)
            )
            .shadow(color: (isProminent ? Color.accentColor : Color.black).opacity(isProminent ? 0.25 : 0.10), radius: isProminent ? 16 : 10, x: 0, y: 10)
            .scaleEffect(pressed ? 0.96 : 1.0)
            .animation(.spring(response: 0.28, dampingFraction: 0.8), value: pressed)
            .contentShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .padding(2)
    }
}

struct GlassCard<CardContent: View>: View {
    let content: CardContent
    init(@ViewBuilder content: () -> CardContent) { self.content = content() }
    var body: some View {
        content
            .padding(16)
            .frame(maxWidth: .infinity)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .overlay(
                ZStack {
                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .stroke(LinearGradient(colors: [Color.white.opacity(0.55), Color.white.opacity(0.15)], startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1)
                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .stroke(Color.black.opacity(0.08), lineWidth: 1)
                        .blur(radius: 1)
                        .offset(y: 1)
                        .mask(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(LinearGradient(colors: [.black, .clear], startPoint: .top, endPoint: .bottom)))
                }
            )
    }
}

// MARK: - Animated Liquid Background
struct LiquidBackground: View {
    var body: some View {
        TimelineView(.animation) { timeline in
            // Drive animation from the timeline's date without mutating view state
            let t = CGFloat(timeline.date.timeIntervalSinceReferenceDate)
            ZStack {
                LinearGradient(colors: [Color(.systemBackground), Color.accentColor.opacity(0.05)],
                               startPoint: .topLeading,
                               endPoint: .bottomTrailing)
                    .ignoresSafeArea()
                Circle()
                    .fill(RadialGradient(colors: [Color.accentColor.opacity(0.35), .clear],
                                          center: .center,
                                          startRadius: 0,
                                          endRadius: 220))
                    .frame(width: 440, height: 440)
                    .blur(radius: 60)
                    .offset(x: sin(t) * 120, y: cos(t * 0.8) * 140)
                Circle()
                    .fill(RadialGradient(colors: [Color.purple.opacity(0.28), .clear],
                                          center: .center,
                                          startRadius: 0,
                                          endRadius: 240))
                    .frame(width: 420, height: 420)
                    .blur(radius: 70)
                    .offset(x: cos(t * 0.6) * -130, y: sin(t * 0.9) * 150)
            }
        }
    }
}

struct StatusPill: View {
    let title: String
    let systemImage: String
    let isOn: Bool
    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: systemImage)
                .imageScale(.small)
            Text(title)
                .font(.caption)
                .monospaced()
        }
        .padding(.vertical, 6)
        .padding(.horizontal, 10)
        .background((isOn ? Color.green : Color.gray).opacity(0.15))
        .foregroundStyle(isOn ? Color.green : Color.secondary)
        .clipShape(Capsule())
        .overlay(Capsule().stroke((isOn ? Color.green : Color.secondary).opacity(0.25), lineWidth: 1))
    }
}

// MARK: - Main View
struct ContentView: View {
    @StateObject var streamer = MotionSpeechStreamer()

    var body: some View {
        ZStack {
            LiquidBackground()

            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    header

                    // Status row=
                    GlassCard {
                        VStack(alignment: .leading, spacing: 12) {
                            HStack(spacing: 10) {
                                StatusPill(title: streamer.connectionStatus, systemImage: "antenna.radiowaves.left.and.right", isOn: streamer.connectionStatus.lowercased().contains("connected"))
                                StatusPill(title: streamer.isListening ? "listening" : "idle", systemImage: "mic", isOn: streamer.isListening)
                                StatusPill(title: streamer.isMotionActive ? "motion on" : "motion off", systemImage: "figure.walk.motion", isOn: streamer.isMotionActive)
                                StatusPill(title: streamer.isGesturesOn ? "gestures on" : "gestures off", systemImage: "hand.point.up.left", isOn: streamer.isGesturesOn)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            Text("hands-free controls for your Mac")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }

                    // Controls grid
                    VStack(spacing: 16) {
                        GlassCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("voice control").font(.headline)
                                HStack(alignment: .center) {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(streamer.isListening ? "listening" : "idle")
                                            .font(.subheadline)
                                        Text(streamer.isListening ? "tap to stop" : "tap to start")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Button {
                                        streamer.isListening ? streamer.stopListening() : streamer.startListening()
                                    } label: {
                                        Image(systemName: streamer.isListening ? "mic.slash.fill" : "mic.fill")
                                            .symbolRenderingMode(.hierarchical)
                                    }
                                    .buttonStyle(GlassButtonStyle(isProminent: true))
                                    .accessibilityLabel(streamer.isListening ? "stop voice listening" : "start voice listening")
                                }
                            }
                        }

                        GlassCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("motion control").font(.headline)
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(streamer.isMotionActive ? "motion on" : "motion off")
                                            .font(.subheadline)
                                        Text(streamer.isMotionActive ? "tap to stop" : "tap to start")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Button {
                                        streamer.isMotionActive ? streamer.stopMotion() : streamer.startMotion()
                                    } label: {
                                        Image(systemName: streamer.isMotionActive ? "pause.circle.fill" : "play.circle.fill")
                                            .symbolRenderingMode(.hierarchical)
                                    }
                                    .buttonStyle(GlassButtonStyle())
                                    .accessibilityLabel(streamer.isMotionActive ? "stop motion" : "start motion")
                                }
                            }
                        }

                        GlassCard {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("hand gestures").font(.headline)
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(streamer.isGesturesOn ? "gestures on" : "gestures off")
                                            .font(.subheadline)
                                        Text(streamer.isGesturesOn ? "tap to stop" : "tap to start")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Button {
                                        let enable = !streamer.isGesturesOn
                                        streamer.sendJSON(["type": "gesture", "kind": "gestures_toggle", "enabled": enable])
                                        streamer.isGesturesOn = enable
                                    } label: {
                                        Image(systemName: streamer.isGesturesOn ? "hand.raised.slash.fill" : "hand.raised.fill")
                                            .symbolRenderingMode(.hierarchical)
                                    }
                                    .buttonStyle(GlassButtonStyle())
                                    .accessibilityLabel(streamer.isGesturesOn ? "disable hand gestures" : "enable hand gestures")
                                }
                            }
                        }
                    }

                    // Quick tips
                    GlassCard {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("try saying")
                                .font(.headline)
                            VStack(alignment: .leading, spacing: 6) {
                                Label("open gmail", systemImage: "envelope.open")
                                Label("type hello team meeting at 3 pm", systemImage: "keyboard")
                                Label("send email", systemImage: "paperplane")
                                Label("open presentation", systemImage: "play.rectangle.on.rectangle")
                                Label("next slide / previous slide", systemImage: "arrow.left.arrow.right")
                            }
                            .font(.callout)
                            .foregroundStyle(.secondary)
                        }
                    }

                    Spacer(minLength: 8)
                }
                .padding(20)
                .onAppear { streamer.connect() }
                .onDisappear { streamer.disconnect() }
            }
        }
    }

    // MARK: - Header
    private var header: some View {
        HStack(alignment: .center) {
            ZStack {
                Circle().fill(LinearGradient(colors: [Color.accentColor.opacity(0.25), Color.accentColor.opacity(0.1)], startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: 54, height: 54)
                    .overlay(Circle().stroke(Color.accentColor.opacity(0.25), lineWidth: 1))
                Image(systemName: "wave.3.right")
                    .font(.title3)
                    .foregroundStyle(Color.accentColor)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text("Hands‑Free Office")
                    .font(.title2).bold()
                Text("control your Mac with your voice, motion, and hand gestures")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
    }
}
