Hands Free

An accessibility app revolutionizing communication.

Screengrab from the app! Brainstorming our idea Specific hand gestures to
program for Features we wanted to implement wit CV HandsFree: Accessible,
Intuitive, and Scalable Computer Control Inspiration Many of us have
grandparents or family members who aren’t as technologically adept as we are.
As
devices become more compact and interfaces more complex, it’s easy for people
with less digital experience to feel left behind.
For individuals with motor
challenges such as involuntary tremors, arthritis, or tendon issues, interacting
with small buttons, precise trackpads, or cluttered UIs becomes even harder.
We created HandsFree to bridge this gap — not only to help those with
accessibility needs, but also to boost productivity for everyone.
By combining
natural language, motion sensors, and hand gestures, we designed a more
intuitive way to control your computer without relying solely on traditional
peripherals.
⸻ What it Does At its core, HandsFree has three features: 1.
Natural Language → Commands The app can listen to a user’s voice commands and
convert them into computer actions.
Users can launch apps, open websites, draft
and send emails, and more.
An integrated large language model (LLM) interprets
commands and generates executable JSON scripts, which are safely run on the
computer.
2. Phone Gyroscope → Mouse Input A smartphone can be turned into a
wireless mouse.
The gyroscopic sensor maps tilt directions to mouse movement,
with tap gestures mapped to clicks.
This design allows users to control their
computer in any orientation, even without a flat surface.
The motion smoothing
ensures precise, stable input without jitter. 3. Laptop Camera → Hand Gestures
Through computer vision, the laptop camera detects hand gestures and maps them
to system controls.
For example: • Index finger raised → Scroll up • Pinky
raised → Scroll down • Two-finger horizontal swipe → Switch browser tabs •
Three-finger vertical swipe → Zoom in/out Gestures are customizable, enabling
both accessibility and personalization.
⸻ How We Built It We divided the project into three major components: 1. Natural
Language Commands • Implemented a Swift GUI for the mobile device to capture
speech.
• Created a Python server for command parsing and execution.
• Used a
layered approach: first matching common tasks via a lookup, then applying TF-IDF
vectorization for fuzzy matching, and finally falling back on Ollama LLM to
handle novel commands.
• Added a safety whitelist to prevent unsafe system
calls. 2. Gyroscope Mouse Control • Considered two designs: absolute positioning
vs. relative tilt control.
• Chose tilt-based relative control, since it
requires less precise hand positioning and is more accessible.
• Modeled mouse
velocity as a vector function of pitch (\theta) and roll (\phi): \vec{v} = (k_x
\cdot \phi, ; k_y \cdot \theta) where k_x, k_y are sensitivity constants.
•
Implemented smoothing and thresholds to ensure predictable and stable cursor
motion.
3. Gesture Recognition • Built on MediaPipe + OpenCV (cv2) to detect
hand landmarks.
• Extracted 21 landmark points per hand (e.g., wrist, knuckles,
fingertips).
• Engineered features such as Euclidean distances, angles between
fingers, and normalized ratios.
• Tuned parameters for detection confidence and
minimum gesture persistence to reduce false positives.
⸻ Challenges We Faced • Integration Pain: Adding new features sometimes broke
old ones, leading to hours of debugging.
• Gesture Precision: Distinguishing
between 2-, 3-, and 4-finger gestures was difficult, especially with varying
lighting.
• Fatigue & Morale: Working through the night in cold, rainy weather
reduced efficiency and led to mistakes.
• Framework Conflicts: We began in Swift
but considered Flutter for cross-platform support, which introduced dependency
and compatibility headaches.
⸻ Accomplishments We’re Proud Of • Successfully
integrated three distinct features into one cohesive app.
• Developed a scalable
pipeline for natural language → JSON execution.
• Implemented real-time mouse
control from phone gyroscope, even modeling tilt vectors using multivariable
calculus.
• Built a computer vision system capable of robust hand gesture
recognition, leveraging ML and tuning parameters for real-world usability.
•
Created something that not only works but has real-world accessibility
potential.
⸻ What We Learned • Technical Skills: • Swift/Xcode for iOS apps. • Pathlib and
asynchronous servers in Python.
• TF-IDF vectorization, scikit-learn basics. •
MediaPipe + OpenCV for computer vision. • Soft Skills: • The importance of sleep
for productivity.
• Task delegation and team communication. • Adapting under
pressure when initial approaches fail.
• Balancing technical ambition with
realistic deliverables in 24 hours. ⸻ What’s Next for HandsFree If given more
time, we would: 1. Port the project to Flutter for cross-platform support (iOS,
Android, Windows).
2. Expand accessibility options, such as: • Voice-based
cursor navigation for low-mobility users. • Larger, high-contrast gesture
visualizations for low-vision users.
• Configurable dwell-clicking for users
with limited dexterity. 3. Shift computation client-side for independence from
servers.
4. Support one phone controlling multiple computers for IT and
education settings. 5. Reduce latency with Bluetooth or Wi-Fi Direct
connections.
6. Continue refining gesture precision and personalization
features.

Built With

  - chatgpt
  - cv2
  - github
  - json
  - mediapipe
  - ollama
  - opencv
  - python
  - swift
  - tenacity
  - vscode
  - xcode
