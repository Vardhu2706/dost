# Dost: a friend you can call. No app, no login.

Built for the Sarvam Bulbul Build Challenge. Demo video: `<DEMO_VIDEO_LINK>` · Post: `<POST_LINK>`

A friend to talk to, not therapy or a medical service, and not clinically validated. See [Status](#status).

## Why Dost
Many people have no access to mental-health support, but most people have a phone.
Dost is a friend who listens, in your language and in your way of talking. It tells you it is an AI
in the first line, and it points you toward real people.

## What it does
- **Talk by phone or in the browser.** Call a Twilio trial US number, or have Dost call you back
  (`POST /call-me`). Phone and browser reach the same orchestrator.
- **Hindi/Hinglish, English and Telugu.** Explicit requests ("speak English", "hindi mein bolo")
  switch reliably, and the voice, the reply rules and the fixed lines switch together. Automatic
  switching from language detection is experimental: one voice per reply, and a cooldown after each
  switch.
- **Mirrors your register.** It picks up tum/aap and casual or formal, and answers the same way.
- **Remembers one open loop you chose.** After a call it keeps a short summary and one thing you
  wanted to come back to (for example "tell me how the interview went"), and asks about it next call.
- **Says goodbye warmly.** A short closing ritual: reflect one thing you said, name one small thing
  to carry, and a warm goodbye, with no pressure to return.
- **Barge-in.** Interrupt at any time and Dost stops talking and listens.
- **Forget-me.** Say "bhool jao" or "forget it" and everything stored for your number is deleted.

## Built with Sarvam
| Piece | What we use |
|---|---|
| Speech to text | Saaras realtime (`saaras:v3-realtime`), streaming, with auto language detection |
| Reasoning | Sarvam 105B (`sarvam-105b`, set by `LLM_MODEL`) for replies, the per-turn analyzer, the post-call summarizer and the returning-caller opener |
| Text to speech | Bulbul v4 Flash, streamed |

Voices: Hindi `amit_hi_conversational`, English `sunny_en_social`, Telugu `tarun_te_narration`.

## How it works
```
phone (8 kHz mu-law) or browser audio  ->  PCM16 frames
  -> orchestrator (one per call)
  -> Saaras STT (streaming finals, voice activity for barge-in)
  -> safety screen (rules) + analyzer (language, register, risk, phase)
  -> reply LLM -> sentence chunker -> Bulbul TTS -> audio back to the caller
```

## Safety by design
- **AI disclosure first.** The first line says Dost is an AI, and it never denies it if asked.
- **No clinical claims.** "A friend to talk to", never "therapist".
- **Crisis protocol.** If you may be at risk, Dost asks whether you are safe, says Tele-MANAS
  **14416** plainly by the second crisis turn, and mentions **112** for immediate danger. It never
  gives methods, never places or forwards a call itself, and never hangs up first.
- **No engagement bait.** The only continuity is an open loop the caller chose.
- **No raw audio stored.** Identity is an HMAC of the phone number: pseudonymized, not anonymous.
  Whoever holds the server secret and a number can recompute it.

## Data and privacy
- Audio and text are **processed by Sarvam** (speech-to-text, text-to-speech, LLM) and, on the phone
  leg, **by Twilio**. Their own retention policies apply.
- Transcripts are deleted once the summary is saved.
- The summary and open loop are kept until the caller says forget-me.
- A 7-day purge of leftover transcripts (when summarizing failed) runs **only at server start**.

## Status
- **Working proof of concept:** phone and browser calls work end to end in Hindi/Hinglish and
  English, with memory, crisis handling and forget-me. Telugu is early and the least tested.
- **Not clinically validated:** no mental-health professional has reviewed it. The safety screen is
  rules plus an LLM; it will miss things and over-trigger, so do not rely on it for anyone's safety.
- **Phone leg on a Twilio trial US number** (verified callers only). Calling from India is an
  international call billed by the caller's carrier; callback mode avoids that.

It needs clinician review before any real-world use.

## Roadmap
Not built yet:
- An Indian phone number.
- Missed-call callback, so callers pay nothing.
- WhatsApp calling (blocked by a Meta account restriction).
- Tele-MANAS warm transfer, only with the caller's explicit consent.
- Anti-prank logic.
- Clinician and native-speaker review.

## Known limits
- Phone audio is 8 kHz, so Dost hears phone callers less clearly than browser callers.
- Jokes or quoted song lyrics may trigger the safety question; the screen errs toward over-triggering.
- Forget-me needs a short phrase (8 words or fewer); a long sentence may not trigger it.
- Browser calls with no number typed get no memory, and nothing is stored.

## Setup and run
Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env.local     # then fill in the values
uv run python -m dost.main     # serves http://127.0.0.1:8000
```

Open `http://127.0.0.1:8000/?token=<SERVER_SECRET>`. **Do not share this URL: it contains the
server secret as a token.** In the browser, type a phone number before calling; memory is keyed on
it and the memory scenes do not work without one.

### Phone setup (Twilio)
1. Start a tunnel: `cloudflared tunnel --url http://127.0.0.1:8000`, then copy the https URL it
   prints. The URL changes every time the tunnel restarts.
2. Set `PUBLIC_BASE_URL` in `.env.local` to that URL exactly, with no trailing slash, and restart
   the server.
3. In the Twilio console, open the number's Configure page. Under "A call comes in", choose Webhook,
   method HTTP POST, URL `<PUBLIC_BASE_URL>/twilio/voice`. Update this whenever the tunnel URL
   changes.
4. Trial accounts can only receive calls from verified caller IDs (add your mobile under Verified
   Caller IDs) and play a trial notice before connecting.
5. To have Dost call you: `uv run python scripts/call_me.py`. It rings `CALLBACK_NUMBER`, uses the
   same webhook, and is rate limited.

### Configuration (`.env.example`)
| Variable | Purpose |
|---|---|
| `SARVAM_API_KEY` | Sarvam STT/TTS/LLM |
| `SERVER_SECRET` | HMAC key for caller identity; also the browser token and `/call-me` secret |
| `DB_PATH` | SQLite file (default `dost.db`) |
| `DEFAULT_LANG` | `hi-IN` by default |
| `VOICE_HI` | Hindi voice (default `amit_hi_conversational`) |
| `VOICE_EN` | English voice (default `sunny_en_social`) |
| `VOICE_TE` | Telugu voice (default `tarun_te_narration`) |
| `LLM_MODEL` | Sarvam chat model (default `sarvam-105b`) |
| `TRANSCRIPT_TTL_DAYS`, `SOFT_WIND_DOWN_MIN` | Transcript purge age, soft call wind-down |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_NUMBER` | Twilio phone leg |
| `PUBLIC_BASE_URL` | Tunnel URL Twilio reaches |
| `CALLBACK_NUMBER` | Verified mobile (E.164) that `/call-me` rings |

Secrets live only in `.env*` files, which are git-ignored. Only `.env.example` is committed.

### Tests and evals
```bash
uv run pytest                              # offline unit/integration tests
uv run python tests/evals/run_evals.py     # live evals; calls Sarvam, can hit rate limits
```
122 offline tests pass. The live evals cover crisis, passive-ideation and not-a-crisis cases, with
one known expected failure (joke context).

Re-run a single flaky scenario by id: `run_evals.py <scenario_id>`. One live eval can flake because
the analyzer is nondeterministic.
