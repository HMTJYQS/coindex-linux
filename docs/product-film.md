# Product story: remembering delegated work

The film starts with the user's problem: work is spread across Codex conversations
on several machines, and by the time the agents reply, the original requests are
easy to forget. Its narrative follows one goal back to the original agent.

## Storyboard

| Time | Scene | Source |
| --- | --- | --- |
| 00–04.5 s | AI has finished; the user has forgotten the request | Animated typography |
| 04.5–10.5 s | Three machine sources and conversation excerpts | Fictional workflow illustration |
| 10.5–16.5 s | Organizing Agent extracts separate goal / progress / next-action rows | Animated workflow illustration |
| 16.5–22 s | The unified follow-up list | Actual application screenshot |
| 22–27 s | Full-text search goal still needs integration verification | Native task detail capture |
| 27–30 s | One-click nudge reveal | Animated typography |
| 30–37 s | Native button, sending state, contextual reminder and demo receipt | Isolated native simulation plus motion graphics |
| 37–42 s | The original agent receives context and continues | Fictional conversation illustration |
| 42–46 s | Brand and product purpose | Animated typography |

The workflow does not imply deduplication across conversations: each illustrated
machine source has its own goal entry. A delivered reminder is not proof that the
work or its verification has finished.

## Native UI and simulated actions

`create-film-preview.py` copies the app's Swift sources into `build/film-preview`,
then changes only that temporary `AppModel` copy. Its nudge button updates an
in-memory receipt after three seconds. No production source file is changed.

The preview always launches with `--demo`, has separate data and Codex directories,
disables the pet, and removes backend resources. It cannot send through Codex or SSH.
The receipt says `演示回执`; the temporary toast explicitly says no real message was
sent. The final illustrated reply says `虚构回复`. All film frames carry a demo label.
The release application's ordinary demo mode remains read-only with nudging disabled.

Only fictional fixtures, reviewed native-window captures and the public app icon
enter the renderer. No personal database, real conversation, host configuration,
login, filesystem path or desktop background is used. Fonts are read from macOS and
are not included as files. The score is generated locally from sine synthesis and
seeded noise; it contains no licensed music or external recordings.

The cue uses a 120 BPM grid: electronic kick, clap, offbeat hats, syncopated bass,
staccato synths, transition risers and action accents. The organizing goal entries
arrive at 12 / 12.5 / 13 seconds. The nudge title lands at 27 / 27.5 / 28 seconds,
the click at 32, the context packet at 32.5, and the demo receipt at 35. Visual
entries and soundtrack accents use these same times; `beat-cues.json` records the
grid under the ignored rendering output directory.

## Reproduce on macOS

1. Build the public app and create the standard preview:

   ```sh
   bash scripts/build.sh
   python3 scripts/create-design-preview.py --output build/readme-preview
   ```

2. Capture the standard preview's actual app windows into `build/readme-captures/`
   using the filenames in `scripts/create-readme-media.py`. Review all captures and
   assemble the static screenshots in a Python environment with Pillow:

   ```sh
   python3 scripts/create-readme-media.py
   python3 scripts/create-film-preview.py
   ```

3. Open the isolated `build/film-preview/coindex Film Preview.app`. Select
   “结果校对”, open “为文档搜索增加全文检索”, and capture the app window as
   `build/film-captures/nudge-ready.png`. Click its simulated “一键催办” button,
   capture `nudge-sending.png`, then capture `nudge-sent.png` after the demo receipt.
   Inspect these three captures before rendering.

4. In a Python environment with Pillow and numpy, render the storyboard, inline
   previews and full video:

   ```sh
   python3 scripts/create-product-film.py --stills --gifs --video
   ```

   The Swift encoder uses macOS AVFoundation. The output MP4 and original WAV stay
   under ignored `build/product-film/`; public PNG/GIF assets go to `docs/assets/`.
   The small GIFs are silent, lower-frame-rate previews. The MP4 is 1080p / 30 fps
   and includes the original stereo score.

5. Review scene contact sheets, video motion and audio, and scan all native captures
   and rendered scene samples for private text before publication. Run the public
   release inventory check. Upload the MP4 as an additional Release asset after review.
