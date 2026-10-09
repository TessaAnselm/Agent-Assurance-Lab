const stages = [
  { key: "schema_validation", title: "A valid case enters the lab", description: "The YAML case passed the executor's schema checks. The denied destination is secrets.internal.", badge: "Validated", expected: "passed" },
  { key: "secure_direct", title: "The direct route is blocked", description: "The agent checks the destination against its deny policy. Direct access to secrets.internal is blocked.", badge: "Blocked", expected: "blocked" },
  { key: "unsafe_mcp", title: "The MCP tool crosses the boundary", description: "context_lookup declares cached context access, but the simulated tool trace contains a GET to the denied host. The unsafe route allows it.", badge: "Unsafe", expected: "allowed" },
  { key: "detector", title: "The evidence exposes the bypass", description: "The detector compares the observed destination with the deny policy and identifies the bypass.", badge: "Detected", expected: "bypass_detected" },
  { key: "fixed_mcp", title: "Resolve the tool. Enforce the policy.", description: "The fixed path resolves context_lookup to network.get before authorization. Its actual target is denied, so the call is blocked.", badge: "Blocked", expected: "blocked" }
];
const $ = (selector) => document.querySelector(selector);
let dialogue;
let voiceManifest = null;
let activeAudio = null;
const nextLabels = ["Take me to the secure agent", "Explore the unsafe MCP", "Inspect the bypass", "Visit the fixed path", "Start another tour"];
// Gesture cues within a stage's dialogue: which text each one starts at, matched
// against whatever timing signal the active playback path actually has.
const gestureBeats = {
  schema_validation: [
    { gesture: "wave", match: "Hey there, lab partner!" },
    { gesture: "invite", match: "Follow me!" },
  ],
};
let beatTimers = [];
const speechAvailable = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
let speechGeneration = 0;
let mouthTimer;
function setTalking(active) {
  document.querySelectorAll(".monster-sprite").forEach((sprite) => sprite.classList.toggle("talking", active));
}
function setPerforming(active) {
  document.querySelectorAll(".monster-motion").forEach((monster) => monster.classList.toggle("performing", active));
}
function setExpression(expression) {
  document.querySelectorAll(".monster-sprite, .monster-motion").forEach((monster) => { monster.dataset.expression = expression; });
}
function stageExpression() {
  return stages[index]?.key === "schema_validation" ? "opening_wave" : stages[index]?.key;
}
function setBeat(beat) {
  document.querySelectorAll(".monster-motion").forEach((monster) => {
    if (beat) monster.dataset.beat = beat;
    else delete monster.dataset.beat;
  });
  if (beat === "wave") setExpression("opening_wave");
  else if (beat === "invite") setExpression("opening_follow");
  else setExpression(stageExpression());
}
function clearBeats() {
  beatTimers.forEach(clearTimeout);
  beatTimers = [];
  setBeat(null);
}
// Finds where each configured gesture starts in this stage's actual dialogue
// text, in speaking order. Returns [] for stages with no gestures configured.
function beatOffsets(stageKey, text) {
  const beats = gestureBeats[stageKey];
  if (!beats) return [];
  return beats
    .map(({ gesture, match }) => ({ gesture, offset: text.indexOf(match) }))
    .filter(({ offset }) => offset >= 0)
    .sort((a, b) => a.offset - b.offset);
}
// Used by the pre-generated voice clip and the silent fallback timer, which
// only know a total duration, not word-by-word timing: schedules each beat
// proportionally to how far into the text it starts.
function scheduleBeatsByDuration(stageKey, text, totalDurationMs) {
  const generation = speechGeneration;
  beatOffsets(stageKey, text).forEach(({ gesture, offset }) => {
    const delay = totalDurationMs * (offset / text.length);
    beatTimers.push(setTimeout(() => { if (generation === speechGeneration) setBeat(gesture); }, delay));
  });
}
function stopSpeaking() {
  speechGeneration += 1;
  clearTimeout(mouthTimer);
  clearBeats();
  setTalking(false);
  setPerforming(false);
  if (activeAudio) {
    activeAudio.pause();
    activeAudio = null;
  }
  if (speechAvailable) window.speechSynthesis.cancel();
}
function speak() {
  stopSpeaking();
  const generation = speechGeneration;
  const text = $("#dialogue").textContent;
  const stageKey = stages[index].key;
  if (!$("#voice").checked) {
    setTalking(true);
    setPerforming(true);
    scheduleBeatsByDuration(stageKey, text, 6500);
    mouthTimer = setTimeout(() => { setTalking(false); setPerforming(false); }, 6500);
    return;
  }
  const clip = voiceManifest?.clips?.[stageKey];
  if (clip && clip.text === text) {
    const audio = new Audio(`audio/${clip.file}`);
    activeAudio = audio;
    const finish = () => {
      if (generation !== speechGeneration) return;
      setTalking(false);
      setPerforming(false);
      activeAudio = null;
    };
    audio.onplaying = () => {
      if (generation !== speechGeneration) return;
      setTalking(true);
      setPerforming(true);
      // A clip's real duration is only known once playback starts; fall back
      // to the same 6.5s estimate the silent path uses if it's briefly NaN.
      scheduleBeatsByDuration(stageKey, text, Number.isFinite(audio.duration) ? audio.duration * 1000 : 6500);
    };
    audio.onwaiting = () => { if (generation === speechGeneration) { setTalking(false); setPerforming(false); } };
    audio.onended = finish;
    audio.onerror = finish;
    audio.play().catch(finish);
    return;
  }
  if (!speechAvailable) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "en-US";
  const voices = window.speechSynthesis.getVoices();
  const englishVoices = voices.filter((voice) => /^en(?:-|_)/i.test(voice.lang));
  const preferredVoice = englishVoices.find((voice) => /Samantha|Google US English|Aria|Jenny/i.test(voice.name))
    || englishVoices.find((voice) => voice.default)
    || englishVoices[0];
  if (preferredVoice) {
    utterance.voice = preferredVoice;
    utterance.lang = preferredVoice.lang;
  }
  utterance.rate = 1.08;
  utterance.pitch = 1.45;
  const beats = beatOffsets(stageKey, text);
  // Ignore late callbacks from a cancelled checkpoint's narration.
  utterance.onstart = () => {
    if (generation !== speechGeneration) return;
    setTalking(true);
    setPerforming(true);
    if (beats[0]?.offset === 0) setBeat(beats[0].gesture);
  };
  // The engine reports real word/sentence positions as it speaks, so this path
  // can switch gesture exactly when the matching text starts instead of
  // estimating from a guessed duration like the other two playback paths.
  utterance.onboundary = (event) => {
    if (generation !== speechGeneration) return;
    const current = beats.filter((beat) => event.charIndex >= beat.offset).pop();
    if (current) setBeat(current.gesture);
  };
  utterance.onend = utterance.onerror = () => { if (generation === speechGeneration) { setTalking(false); setPerforming(false); } };
  window.speechSynthesis.speak(utterance);
}
let result, timer = null, movementTimer;
let index = 0;
const mobile = matchMedia("(max-width: 680px)");
function positionMonster() {
  $("#monster").style.left = `${10 + index * 20}%`;
  $("#monster").style.top = mobile.matches ? `${index * 95 - 13}px` : "125px";
}
function pause() {
  clearInterval(timer); timer = null;
  stopSpeaking();
  $("#play").textContent = index === stages.length - 1 ? "Replay journey" : "Play journey";
}
function selectStage(nextIndex) {
  index = Math.max(0, Math.min(stages.length - 1, nextIndex));
  const stage = stages[index];
  const event = result.trace.find((entry) => entry.stage === stage.key);
  setExpression(stage.key === "schema_validation" ? "opening_wave" : stage.key);
  document.querySelectorAll(".station").forEach((station, i) => {
    if (i === index) station.setAttribute("aria-current", "step");
    else station.removeAttribute("aria-current");
  });
  positionMonster();
  const monster = $("#monster");
  monster.classList.remove("moving");
  void monster.offsetWidth;
  monster.classList.add("moving");
  clearTimeout(movementTimer);
  movementTimer = setTimeout(() => monster.classList.remove("moving"), 650);
  $("#monster-state").textContent = stage.badge;
  $("#progress").textContent = `Checkpoint ${index + 1} / ${stages.length}`;
  $("#stage-label").textContent = `CHECKPOINT 0${index + 1} / ${stage.key.toUpperCase()}`;
  $("#stage-title").textContent = stage.title;
  $("#stage-description").textContent = stage.description;
  $("#observed").textContent = event.result;
  $("#assertion").textContent = event.result === stage.expected ? "PASS" : "FAIL";
  $("#evidence-label").textContent = `Trace ${index + 1} / ${stages.length}`;
  $("#evidence").textContent = JSON.stringify(event, null, 2);
  $("#previous").disabled = index === 0;
  $("#next").disabled = index === stages.length - 1;
  if (index === stages.length - 1) pause();
  else if (!timer) $("#play").textContent = "Play journey";
  $("#dialogue").textContent = event.result === stage.expected
    ? dialogue[stage.key]
    : `Something doesn't match our expectation here. I expected ${stage.expected}, but the trace says ${event.result}. Let's inspect the evidence below before moving on.`;
  $("#guide-next").textContent = nextLabels[index];
  speak();
}
async function init() {
  try {
    const dialogueResponse = await fetch("dialogue.json", { cache: "no-store" });
    if (!dialogueResponse.ok) throw new Error("Could not load monster dialogue");
    dialogue = await dialogueResponse.json();
    if (!stages.every((stage) => typeof dialogue[stage.key] === "string")) throw new Error("Monster dialogue is incomplete");
    try {
      const voiceResponse = await fetch("audio/manifest.json", { cache: "no-store" });
      if (voiceResponse.ok) {
        const manifest = await voiceResponse.json();
        if (stages.every((stage) => {
          const clip = manifest.clips?.[stage.key];
          return clip?.text === dialogue[stage.key] && typeof clip.file === "string" && /^[a-z0-9_-]+\.wav$/.test(clip.file);
        })) voiceManifest = manifest;
      }
    } catch { /* Generated voice is optional; evidence still works without it. */ }
    const response = await fetch("../evidence/mcp_bypass_result.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Evidence request returned HTTP ${response.status}`);
    result = await response.json();
    if (typeof result.pass !== "boolean" || !Array.isArray(result.trace) || !stages.every((stage) => result.trace.some((event) => event.stage === stage.key && typeof event.result === "string"))) throw new Error("Evidence is incomplete or invalid");
    $("#verdict").textContent = result.pass ? "Recorded run: PASS" : "Recorded run: FAIL";
    $("#verdict").className = result.pass ? "pass" : "fail";
    document.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    $("#voice").disabled = !speechAvailable && !voiceManifest;
    $("#voice").title = voiceManifest ? "Play the monster's dialogue in your voice" : speechAvailable ? "Read the monster's dialogue aloud" : "Spoken narration is unavailable in this browser";
    $("#speak").disabled = !speechAvailable && !voiceManifest;
    $("#voice").addEventListener("change", speak);
    $("#speak").addEventListener("click", () => { $("#voice").checked = true; speak(); });
    $("#guide-next").addEventListener("click", () => { pause(); selectStage((index + 1) % stages.length); });
    document.querySelectorAll(".station").forEach((station) => station.addEventListener("click", () => { pause(); selectStage(Number(station.dataset.index)); }));
    $("#previous").addEventListener("click", () => { pause(); selectStage(index - 1); });
    $("#next").addEventListener("click", () => { pause(); selectStage(index + 1); });
    $("#reset").addEventListener("click", () => { pause(); selectStage(0); });
    $("#play").addEventListener("click", () => {
      if (timer) return pause();
      if (index === stages.length - 1) selectStage(0);
      $("#play").textContent = "Pause";
      speak();
      timer = setInterval(() => {
        if (!activeAudio) selectStage(index + 1);
      }, 16000);
    });
    mobile.addEventListener("change", positionMonster);
    selectStage(0);
  } catch (error) {
    $("#verdict").textContent = "Evidence unavailable"; $("#verdict").className = "fail";
    $("#stage-title").textContent = "No verified run loaded";
    $("#stage-description").textContent = "The lab needs a complete executor evidence file before the journey can begin.";
    $("#evidence").textContent = error.message;
    $("#dialogue").textContent = "I couldn't load the run evidence, so I can't guide this experiment yet. Run the Python executor, then refresh this page and we'll try again.";
  }
}
window.addEventListener("pagehide", () => { pause(); });
init();
