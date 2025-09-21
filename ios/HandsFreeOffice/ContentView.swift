//
//  ContentView.swift
//  HandsFreeOffice
//
//  Created by Praniil Nagaraj on 9/20/25.
//

import SwiftUI

struct ContentView: View {
    @StateObject var streamer = MotionSpeechStreamer()
    @State private var gesturesOn: Bool = false

    var body: some View {
        VStack(spacing: 16) {
            Text("Hands-Free Office").font(.title2).bold()
            Text(streamer.connectionStatus).font(.footnote)
                        
            Button(streamer.isListening ? "Stop listening" : "Start listening") {
                streamer.isListening ? streamer.stopListening() : streamer.startListening()
            }.buttonStyle(.borderedProminent)

            Button(streamer.isMotionActive ? "Stop motion" : "Start motion") {
                streamer.isMotionActive ? streamer.stopMotion() : streamer.startMotion()
            }
            .buttonStyle(.bordered)
            
            Button {
                let enable = !streamer.isGesturesOn
                streamer.sendJSON([
                    "type": "gesture",
                    "kind": "gestures_toggle",
                    "enabled": enable
                ])
                streamer.isGesturesOn = enable
            } label: {
                Text(streamer.isGesturesOn ? "Stop hand gestures" : "Start hand gestures")
            }
            .buttonStyle(.bordered)

            HStack(spacing: 8) {
                Circle()
                    .fill(streamer.isMotionActive ? Color.green : Color.gray)
                    .frame(width: 10, height: 10)
                Text(streamer.isMotionActive ? "Motion: ON" : "Motion: OFF")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading) {
                Text("Say:")
                Text("• open gmail")
                Text("• type hello team meeting at 3 pm")
                Text("• send email")
                Text("• open presentation")
                Text("• next slide / previous slide")
            }.font(.callout).padding(.top, 8)

            Spacer()
        }
        .padding()
        .onAppear { streamer.connect() }
        .onDisappear { streamer.disconnect() }
    }
}
