# Voice Pipeline & Audio — Review (Phase B)

Subject owner: voice pipeline & audio. Scope: Porcupine wake word, faster-whisper STT
(and the Vosk alternative), Piper TTS, the TTS text formatter, audio I/O via `sounddevice`
and `aplay` on the Scarlett 2i4, and especially **USB audio device index stability**.

This report describes and proposes only. Nothing here is implemented. Anything touching
secrets/`.env` is flagged separately at the end of each affected item and summarized in its
own section.

All paths relative to `/home/tyler/projects/workshop-assistant/`. Line numbers verified
against current source at time of writing.

---

## 1. Current state

### 1.1 Audio device selection (the central fragility)

The system identifies audio devices by **numeric index**, which is assigned by ALSA/PortAudio
at enumeration time and is **not stable across reboots or USB re-plugs**.

- `config/settings.py:1-4` hardcodes `AUDIO_INPUT_DEVICE = 1` (Scarlett), `AUDIO_OUTPUT_DEVICE = 3`
  (USB speakers), `SCARLETT_SAMPLE_RATE = 48000`.
- **Input is partially self-healing.** `src/wake_word.py:18-27` runs at import time: it calls
  `sd.query_devices()`, finds the first device whose name contains `'Scarlett'` with input
  channels, and overrides `AUDIO_INPUT_DEVICE` with that device's index. On any exception it
  silently `pass`es and keeps the settings value (`wake_word.py:26-27`).
- **This override does not propagate.** `src/speech_to_text.py` imports `AUDIO_INPUT_DEVICE`
  directly from settings (`speech_to_text.py:13`) and uses it in `sd.rec(...)` and
  `sd.InputStream(...)` (lines 62, 123, 151). It never sees the corrected index from
  `wake_word.py` — the two modules hold independent copies of the integer. So wake-word
  detection can self-correct while STT recording still points at the stale index. Today this
  happens to work only because `AUDIO_INPUT_DEVICE = 1` is correct on the current boot.
- **Output is fully hardcoded and never auto-detected.** `src/text_to_speech.py:72-78` shells
  out to `aplay ... -D plughw:{AUDIO_OUTPUT_DEVICE},0` with the literal settings value. Note
  this is the **ALSA card index**, a *different* numbering scheme from PortAudio's
  `sounddevice` indices, yet both are configured as plain integers in the same settings block.
  There is no name-based detection for output at all.
- The `/devices` API endpoint (`src/api_server.py:525-542`) enumerates devices via
  `sd.query_devices()` for the UI, and `AUDIO_INPUT_DEVICE`/`AUDIO_OUTPUT_DEVICE` are
  writable via `/settings` (`api_server.py:344-345, 357-358`) and are restart keys
  (`_RESTART_KEYS`), so changing them re-execs the process. This is the current manual
  recovery path when an index drifts.

### 1.2 Wake word (Porcupine)

- `src/wake_word.py:33-38` creates one shared Porcupine instance at import from
  `PORCUPINE_ACCESS_KEY` (secrets) and the `.ppn` model, `WAKE_WORD_SENSITIVITY = 0.9`.
- Porcupine needs 16 kHz; the Scarlett runs at 48 kHz. Each frame is captured at 48 kHz
  (`blocksize=samples_needed`, `wake_word.py:45`) and **resampled per frame** with
  `scipy.signal.resample` (`wake_word.py:66, 90`). `signal.resample` uses an FFT method,
  which is heavier than necessary for a fixed 3:1 integer downsample run on every frame.
- `listen_for_wake_word()` (line 53) and `listen_for_wake_word_stoppable(stop_event)` (line 75)
  both wrap the stream in a `while True` / `try-except` that logs the error and retries after a
  1-second `time.sleep` (lines 70-72, 94-98). This is the main resilience mechanism: if the
  Scarlett is unplugged, the stream open fails, it logs and retries every second forever. It
  does **not** re-detect the device index on retry, so if the index changed, it retries against
  the wrong index indefinitely.

### 1.3 STT (faster-whisper, default; Vosk alternative)

- `src/speech_to_text.py:28-45` loads exactly one model at import based on `STT_ENGINE`
  (`whisper` default, `tiny`/`int8`). Vosk is the alternate path.
- Three record paths exist: fixed `transcribe_speech()` (line 48), `transcribe_short(1.5)`
  (line 115, used for barge-in snippets), and the default dynamic
  `transcribe_speech_dynamic()` (line 133).
- Dynamic recording streams `DYNAMIC_CHUNK_SIZE`-sample chunks, computes per-chunk energy as
  `np.abs(chunk).mean()` (line 167), and stops on `DYNAMIC_SILENCE_THRESHOLD` seconds of
  energy below `DYNAMIC_ENERGY_THRESHOLD` (line 170) or at `DYNAMIC_MAX_DURATION` (line 182).
  The energy threshold is a single fixed integer (`500`) with no noise-floor calibration —
  a loud workshop (compressor, dust collector, fans) can hold energy above 500 forever and
  defeat the silence cutoff, falling back only to the 30 s max.
- Whisper path (`_transcribe_with_whisper`, line 83) writes the audio to a temp WAV via
  `tempfile.NamedTemporaryFile(delete=False)`, transcribes with `beam_size=5, language="en"`,
  joins segments, strips trailing punctuation, then `os.unlink`s the temp file (line 110). If
  `whisper_model.transcribe` raises, the `os.unlink` is skipped and the temp WAV leaks.
- Whisper at 48 kHz: the temp WAV is written at `SCARLETT_SAMPLE_RATE` (48 kHz, line 93).
  Whisper resamples internally to 16 kHz, so this works but ships 3x the audio bytes through
  the temp file each time.

### 1.4 TTS (Piper) and formatting

- `src/text_to_speech.py:18` loads one `PiperVoice` at import. `speak()` (line 56) streams
  Piper chunks (one per sentence) directly into a long-lived `aplay` subprocess so playback
  starts on the first sentence (lines 81-86). `synthesize_to_wav()` (line 34) builds WAV bytes
  in memory for the API base64 path.
- `interrupt()` (line 25) sets `_interrupt_flag` and `.kill()`s the tracked `_audio_process`,
  enabling barge-in.
- `check_interrupt_callback` is accepted by `speak()` (line 56) but **never used** in the body
  — dead parameter (Dossier gap #18).
- TTS tuning settings `TTS_SPEED` (`= 2`), `TTS_NOISE_SCALE`, `TTS_NOISE_W`
  (`settings.py:43-45`) are **declared but never consumed** by `text_to_speech.py` (Dossier
  gap #15). `TTS_SPEED = 2` reads as "2x slower" per the settings comment but has no effect,
  which is misleading.
- `src/tts_formatter.py` does regex cleanup for spoken output (temperature ranges, dimensions,
  e.g./i.e./etc.). It is correctly applied in all three synthesis paths (`speak`,
  `synthesize_to_wav`). Note `audio_utils.py:11` also imports `format_for_speech` but never
  calls it (the synth functions already format), so that import is unused.

### 1.5 API-side audio

- `src/audio_utils.py:15` `wav_bytes_to_numpy()` decodes uploaded WAVs (8/16/32-bit,
  stereo→mono average, multi-channel decimation) and resamples to 48 kHz with `np.interp`
  linear interpolation (line 72). It up-resamples uploads to 48 kHz only to hand them to
  Whisper which down-resamples to 16 kHz again — a double resample that adds artifacts for no
  benefit.

### 1.6 Tests / logging / error handling baseline

- **No automated tests exist** anywhere in the repo (Dossier gap #19); only a `test_query.wav`
  fixture at the repo root. There is no `tests/` directory.
- Audio errors are logged ad hoc: wake-word retries log at WARNING (`wake_word.py:71, 97`),
  TTS catches `BrokenPipeError`/`TimeoutExpired`/generic (`text_to_speech.py:87-93`), dynamic
  STT logs buffer overflow (`speech_to_text.py:160`). There is no structured "audio device
  health" signal anywhere, and `forge_state` has no audio-health field.

---

## 2. Proposed improvements

Priority 🔴 high / 🟡 medium / 🟢 low. Effort S (≲1 hr) / M (a few hrs) / L (a day+).
Tyler is a beginner — every item favors small, readable, testable diffs over cleverness.

### 🔴 / M — Centralize name-based device resolution into one helper

**Problem:** index drift across reboots/replugs is the top fragility (§1.1). Input is
half-fixed in `wake_word.py` but the fix doesn't reach `speech_to_text.py`, and output is
never auto-detected at all.

**Proposal:** add one small module, e.g. `src/audio_devices.py`, with two readable functions:
`resolve_input_device()` (find the Scarlett input by name substring, fall back to
`AUDIO_INPUT_DEVICE`) and `resolve_output_device()` (find the USB speaker by name, fall back
to `AUDIO_OUTPUT_DEVICE`). Have `wake_word.py`, `speech_to_text.py`, and `text_to_speech.py`
all call these instead of holding their own copies of the settings integer. Make the name
substrings settings values (e.g. `AUDIO_INPUT_NAME = "Scarlett"`, `AUDIO_OUTPUT_NAME`) so
they are configurable without code edits. Keep the existing numeric settings as the fallback
so nothing breaks if the names don't match.

- **Caveat to document, not solve here:** `aplay -D plughw:N` uses the **ALSA card index**,
  while `sounddevice` uses the **PortAudio index** — they are different numbering schemes.
  The output resolver should map a name to the correct ALSA identifier (or switch `aplay` to
  a stable `-D plughw:CARD=<name>` form, which ALSA supports and is index-independent). This
  is the cleanest long-term fix for output and should be called out explicitly to whoever
  implements it.
- **Tests:** unit-test the resolver with a fake device list (list of dicts) covering: name
  found, name absent (falls back to integer), multiple matches (pick first input-capable).
  No hardware needed — `sd.query_devices()` output is just data.
- **Logging:** log the resolved index AND device name at startup (`"Using input device 1:
  Scarlett 2i4 USB"`), so a drift after reboot is visible in the journal.
- **Error handling:** if neither name nor fallback index is valid, log a clear ERROR naming
  both the wanted name and the available devices.
- Secrets: none.

### 🔴 / S — Re-resolve the device index on wake-word stream-open failure

**Problem:** `wake_word.py:70-72` retries the same stale index forever after a replug. Once
the index changes, Forge is deaf until a manual restart.

**Proposal:** in the retry branch of both `listen_for_wake_word` and
`listen_for_wake_word_stoppable`, re-run the name-based resolver (from the item above) before
sleeping and retrying, so a replug that changes the index self-heals within a second or two.
Keep it minimal: one function call inside the existing `except`.

- **Tests:** simulate a stream-open `OSError` then a successful open with a fake `InputStream`
  context manager; assert the resolver was called on the retry path.
- **Logging:** log "input device re-resolved to N after audio error" at WARNING.
- **Error handling:** already wrapped in try/except with backoff; just add the re-resolve and
  cap log spam (e.g. log the device-error line at most once per N seconds so an unplugged
  Scarlett doesn't flood the log — relates to log-rotation, see §3 Infra).
- Secrets: none.

### 🟡 / S — Surface audio-device health to `forge_state`

**Problem:** there is no machine-readable signal that the mic/speaker is missing; the only
evidence is buried in `workshop_assistant.log`.

**Proposal:** add an `audio_status` key to `forge_state.state` (e.g.
`ok | input_missing | output_error`) and set it from the wake-word retry path and the TTS
error path. The UX agent can render it; that wiring is their lane — here we only define and
populate the field.

- **Tests:** assert the field flips on a simulated stream error and resets on success.
- **Logging:** state transitions already logged; this just mirrors them into shared state.
- **Dependency:** UX/interface owns displaying it (see §3).
- Secrets: none.

### 🟡 / S — Calibrate the dynamic-recording energy threshold to the noise floor

**Problem:** `DYNAMIC_ENERGY_THRESHOLD = 500` is a fixed magic number (`settings.py:22`,
used at `speech_to_text.py:170`). In a noisy workshop the floor can exceed 500, so silence is
never detected and every utterance runs to the 30 s `DYNAMIC_MAX_DURATION` (slow, and a poor
experience). In a silent room 500 may be too high and clip the user's first soft word.

**Proposal:** sample the first ~0.3 s of the stream to estimate the noise floor, then set the
silence cutoff to `floor * margin` (a small configurable multiplier) instead of a flat 500.
Keep it simple and readable; clamp to a sane min/max. Leave the flat value as the fallback.

- **Tests:** feed synthetic chunk arrays (quiet floor, loud floor, speech bursts) into a
  refactored "is this chunk silence?" helper and assert the stop logic; pure-numpy, no audio
  hardware.
- **Logging:** log the measured floor and chosen threshold once per recording at INFO.
- **Error handling:** if calibration reads zero/garbage, fall back to the fixed threshold.
- Secrets: none.

### 🟡 / S — Fix the Whisper temp-file leak and reduce double resampling

**Problem:** `_transcribe_with_whisper` (`speech_to_text.py:83-113`) leaks the temp WAV if
`transcribe` raises (the `os.unlink` at line 110 is inside the `with` after the call, so an
exception skips it). Separately, both the voice path (records at 48 kHz) and the API path
(`audio_utils.wav_bytes_to_numpy` up-resamples to 48 kHz) hand Whisper 48 kHz audio it just
re-downsamples to 16 kHz.

**Proposal (two small, independent changes):**
1. Wrap the temp-file body in `try/finally` so `os.unlink` always runs (or pass the numpy
   array to `whisper_model.transcribe`, which faster-whisper accepts directly, eliminating
   the temp file entirely — cleaner and faster). Verify the numpy path on this faster-whisper
   version before committing to it.
2. For the API path, stop up-resampling to 48 kHz in `wav_bytes_to_numpy` when the consumer is
   Whisper; let Whisper do the single resample. This is a behavior change to a shared helper —
   coordinate with whoever owns the API request flow (see §3 Intent/Infra) before touching it.

- **Tests:** unit-test that a transcribe exception leaves no temp file behind (mock the model
  to raise, assert tempdir is clean). Test `wav_bytes_to_numpy` output length/dtype for
  8/16/32-bit and mono/stereo inputs using small in-memory WAVs.
- **Logging:** keep the existing transcription log line; add a WARNING on transcribe failure.
- **Error handling:** today a transcribe exception bubbles up to the pipeline crash-restart
  wrapper. A local `try/except` returning `""` (treated as "empty transcription, ignored" by
  `main.py:69`) would degrade more gracefully than restarting the whole loop.
- Secrets: none.

### 🟢 / S — Make Piper actually honor the TTS tuning settings (or delete them)

**Problem:** `TTS_SPEED`, `TTS_NOISE_SCALE`, `TTS_NOISE_W` (`settings.py:43-45`) are declared
and exposed but never consumed by `text_to_speech.py`. `TTS_SPEED = 2` looks meaningful but
does nothing — confusing for a beginner tuning their assistant.

**Proposal:** either pass these through to `PiperVoice.synthesize` via Piper's synthesis
options (length-scale / noise-scale / noise-w) in both `speak` and `synthesize_to_wav`, or, if
they're not wanted, delete them from settings and the `/settings` allowlist so the UI doesn't
offer dead knobs. Pick one; don't leave them half-wired. Confirm the exact option names for
piper-tts 1.3.0 before wiring.

- **Tests:** assert the chosen length-scale is passed to a mocked `_voice.synthesize`.
- **Logging:** log the effective speed/noise values at startup.
- **Dependency:** UX owns the settings UI knobs (see §3).
- Secrets: none.

### 🟢 / S — Remove the per-frame FFT resample in the wake-word loop

**Problem:** `signal.resample` (FFT-based) runs on every 48 kHz→16 kHz frame
(`wake_word.py:66, 90`) — heavier than needed for a fixed 3:1 ratio on a Pi running this in a
tight loop.

**Proposal:** use a cheaper fixed-ratio downsample (`scipy.signal.resample_poly`, or even
careful decimation since 48000/16000 is an exact 3:1) to cut per-frame CPU. Low risk but
measure first — only worth it if profiling shows the loop is hot. Keep the change isolated to
the two call sites.

- **Tests:** assert output length equals `FRAME_LENGTH` and dtype is int16 for a known input.
  A regression test that wake-word still fires on `test_query.wav`-style input would be ideal
  but needs a captured "Hey Forge" clip.
- **Logging:** none new.
- **Error handling:** unchanged.
- Secrets: none.

### 🟢 / S — Clean up dead code in the audio modules

- Remove the unused `check_interrupt_callback` parameter from `text_to_speech.speak`
  (`text_to_speech.py:56`) or actually use it — barge-in already works via `interrupt()` +
  `_interrupt_flag`, so it's redundant.
- Remove the unused `format_for_speech` import in `audio_utils.py:11`.
- These are trivial readability wins; bundle them into one small PR.
- **Tests:** none required; covered by existing call sites compiling.
- Secrets: none.

### 🟢 / M — A minimal audio smoke-test harness

**Problem:** no tests at all (§1.6). Audio is the scariest thing to regress because it's
hardware-coupled.

**Proposal:** add a tiny `tests/` directory with pure-logic unit tests (no hardware): the
device resolver (fake device lists), the silence/energy helper, `format_for_speech`,
`wav_bytes_to_numpy`, and the Whisper temp-file cleanup. Plus one **manual**, clearly-labeled
hardware script (not run in CI) that records 3 s and plays it back, for Tyler to sanity-check
the Scarlett and speakers after a reboot or reimage. Use plain `pytest`; it's beginner-
friendly and already implied by the ecosystem.

- **Logging:** the manual script should print the resolved input/output device names so a
  drift is obvious.
- **Dependency:** Infra owns CI wiring if any (see §3); these tests are runnable locally
  regardless.
- Secrets: the unit tests must use fake/in-memory data and must **not** import
  `config.secrets` or hit the network (importing `wake_word.py` triggers Porcupine creation
  which needs the access key — structure tests to import only the pure helpers, or guard the
  Porcupine/model creation behind a function so it isn't run at import in test mode).

---

## 3. Dependencies on other subjects

- **Infra & deployment** —
  - The cleanest output-device fix (`plughw:CARD=<name>` / ALSA persistent naming, possibly a
    `udev` rule giving the Scarlett a stable alias) is an OS-level concern that overlaps Infra.
  - The "cap audio-error log spam" note ties into the **no log rotation** gap (Dossier #10);
    re-resolving and retrying audio could spam the already-huge `workshop_assistant.log`.
  - Whether the new unit tests run in any CI is Infra's call.
- **UX / interface** — the `audio_status` field in `forge_state` and the TTS tuning knobs are
  populated/defined here but **rendered** by the UX agent. I define the data; they display it.
  I stay out of `static/*.html`.
- **Intent & LLM layer** — the API-side `wav_bytes_to_numpy` double-resample change touches the
  shared `/query` request flow; coordinate so STT changes don't surprise the intent router.
  Empty-transcript handling (returning `""` on STT failure) relies on `main.py:69` /
  `intent_recognition` treating empty input as "ignore" — confirm with that owner.
- **Vault integration** — none. The vault agent consumes already-transcribed text; it does not
  touch audio I/O.

---

## 4. Secrets / `.env` — flagged separately

- **`PORCUPINE_ACCESS_KEY`** (`config/secrets.py`, read at `wake_word.py:15, 34`) is required
  to construct Porcupine at import. Any test or refactor must avoid importing `wake_word.py`
  at module load without that key present, and must never log or echo the key. No proposal
  here changes how the key is stored — I only note that the new test harness must not depend
  on it (guard model creation so pure helpers can be imported in isolation).
- No proposal in this report adds, moves, reads, or rotates any secret. The Anthropic / HA /
  webhook secrets are out of this subject's lane entirely.

---

## 5. Non-goals / out of scope

- **No swap of the STT or TTS engine.** No Fish-Speech (none exists in the repo — Dossier §4),
  no Whisper size bump beyond `tiny` (resource-aware on the Pi 5), no replacing Piper.
- **No rewrite of the async pipeline** in `main.py` (barge-in, crash-restart, status flow) —
  that orchestration is sound and mid-Phase-4; I build on it.
- **No UI work** — the kiosk/touchscreen (`static/*.html`) belongs to the UX agent. I only
  define the `audio_status` data and TTS knobs they may surface.
- **No changes to intent routing, Claude calls, budget, or the vault agent.**
- **No OS reimage / udev / ALSA-config implementation** — flagged as an Infra dependency, not
  done here.
- **No secret storage changes.**
- **Vosk** stays as-is: it's the non-default alternate engine; I keep it working but don't
  invest in it.

---

### Top 3 recommendations (summary)

1. 🔴 **Centralize name-based device resolution** into one `audio_devices.py` helper used by
   wake word, STT, and TTS — fixing the index-drift fragility where `wake_word.py`'s input
   auto-detect doesn't reach `speech_to_text.py` and output (`aplay plughw:3`) isn't detected
   at all. (M)
2. 🔴 **Re-resolve the device index on wake-word stream-open failure** so a USB replug
   self-heals instead of retrying a stale index forever. (S)
3. 🟡 **Fix the Whisper temp-file leak and the double 48 kHz↔16 kHz resampling**, ideally by
   passing the numpy array straight to faster-whisper and dropping the temp WAV. (S)
